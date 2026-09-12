"""El monitoreo de deriva reimplementa dos metricas que ya existen. Hay que fijarlo.

`psi_numeric` y `score_drift` trabajan contra un perfil PERSISTIDO --cortes y
proporciones guardados en JSON-- mientras `evaluation.metrics.psi` y `stability`
trabajan contra el array de referencia. Es la misma duplicacion deliberada que hay
entre `export.onnx.onnx_predict` y el del servidor, y se sostiene igual: con tests
que verifican que las dos den lo mismo cuando reciben lo mismo.

Si divergieran, el PSI publicado en el reporte de deriva no seria comparable con el
que ya aparece en metrics.json, y nadie se enteraria.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from crmlops.evaluation.metrics import psi as psi_referencia
from crmlops.evaluation.metrics import stability
from crmlops.features.spec import FeatureSpec
from crmlops.monitoring.drift import (
    MIN_SUPPORT,
    SIN_VINTAGE,
    CategoricalProfile,
    DriftResult,
    ReferenceProfile,
    build_reference,
    compute_drift,
    psi_categorical,
    psi_numeric,
    score_drift,
)

SEMILLA = 42


@pytest.fixture
def spec() -> FeatureSpec:
    return FeatureSpec(
        numeric=("monto", "tasa"),
        categorical=("sector",),
        forbidden_panel=frozenset(),
        lineage={},
    )


@pytest.fixture
def referencia(spec) -> pd.DataFrame:
    rng = np.random.default_rng(SEMILLA)
    n = 20_000
    return pd.DataFrame(
        {
            "monto": rng.lognormal(mean=11.0, sigma=1.0, size=n),
            "tasa": rng.normal(loc=6.0, scale=1.5, size=n),
            "sector": rng.choice(["A", "B", "C"], size=n, p=[0.6, 0.3, 0.1]),
        }
    )


# --- la duplicacion, fijada ---


def test_el_psi_numerico_coincide_con_el_de_evaluation(spec, referencia):
    """Misma convencion: los cortes salen de la referencia, se aplican al nuevo."""
    rng = np.random.default_rng(SEMILLA + 1)
    nuevo = referencia["monto"].to_numpy() * rng.uniform(0.8, 1.6, len(referencia))

    perfil = build_reference(referencia, spec)
    desde_perfil = psi_numeric(perfil.numeric["monto"], nuevo)
    desde_arrays = psi_referencia(referencia["monto"].to_numpy(), nuevo)

    assert desde_perfil == pytest.approx(desde_arrays, abs=1e-9), (
        f"las dos implementaciones divergieron: {desde_perfil} vs {desde_arrays}"
    )


def test_el_drift_del_score_coincide_con_stability(spec, referencia):
    rng = np.random.default_rng(SEMILLA + 2)
    ref_scores = rng.beta(2, 20, size=15_000)
    # Corrimiento de nivel puro: se mueve el logit y no la forma.
    logit = np.log(ref_scores / (1 - ref_scores)) + 0.5
    nuevos = 1.0 / (1.0 + np.exp(-logit))

    perfil = build_reference(referencia, spec, scores=ref_scores)
    mio = score_drift(perfil.score, nuevos)
    suyo = stability(ref_scores, nuevos)

    assert mio.psi_total == pytest.approx(suyo.psi_total, abs=1e-9)
    assert mio.psi_shape == pytest.approx(suyo.psi_shape, abs=1e-9)


def test_un_corrimiento_de_nivel_no_se_confunde_con_cambio_de_forma(spec, referencia):
    """La razon de separar nivel y forma: uno se recalibra, el otro se reentrena."""
    rng = np.random.default_rng(SEMILLA + 3)
    ref_scores = rng.beta(2, 20, size=15_000)
    logit = np.log(ref_scores / (1 - ref_scores)) + 0.8
    nuevos = 1.0 / (1.0 + np.exp(-logit))

    d = score_drift(build_reference(referencia, spec, scores=ref_scores).score, nuevos)
    assert d.psi_total > 0.10, "un corrimiento de 0.8 en logit tiene que verse"
    assert d.psi_shape < 0.01, f"la forma no cambio y el PSI de forma da {d.psi_shape}"
    assert d.level_shift == pytest.approx(0.8, abs=0.02)
    assert "NIVEL" in d.interpretation


# --- vocabulario: el hallazgo de la semana 9 ---


def test_una_categoria_nueva_cuenta_como_masa_sin_soporte():
    perfil = CategoricalProfile(name="sector", categories=["A", "B"], proportions=[0.7, 0.3])
    nuevo = pd.Series(["A"] * 50 + ["B"] * 20 + ["NUEVA"] * 30)
    _, sin_soporte = psi_categorical(perfil, nuevo)
    assert sin_soporte == pytest.approx(0.30, abs=1e-9)


def test_una_categoria_vista_pero_sin_evidencia_TAMBIEN_cuenta():
    """El caso real de business_age, y el que contar solo las nuevas se perderia.

    'Existing or more than 2 years old' existia en entrenamiento con el 0.01% de la
    masa --22 prestamos de 217.060-- y hoy se lleva el 52%. No es una categoria
    nueva: es una categoria sobre la que el modelo no aprendio nada.
    """
    perfil = CategoricalProfile(
        name="business_age",
        categories=["vieja", "rarisima"],
        proportions=[0.9999, 0.0001],
    )
    nuevo = pd.Series(["vieja"] * 48 + ["rarisima"] * 52)
    _, sin_soporte = psi_categorical(perfil, nuevo)
    assert sin_soporte == pytest.approx(0.52, abs=1e-9)
    assert MIN_SUPPORT > 0.0001, "el umbral de soporte tiene que dejar fuera a 'rarisima'"


def test_el_vocabulario_roto_manda_sobre_la_banda_del_psi():
    """Una variable cuyo vocabulario cambio no esta 'vigilar': esta rota."""
    r = DriftResult("business_age", "categorica", psi=0.02, unsupported_mass=0.84)
    assert r.band == "VOCABULARIO"
    assert DriftResult("x", "numerica", psi=0.02).band == "estable"
    assert DriftResult("x", "numerica", psi=0.15).band == "vigilar"
    assert DriftResult("x", "numerica", psi=0.40).band == "ACCION"


def test_el_orden_pone_primero_el_vocabulario(spec, referencia):
    nuevo = referencia.copy()
    nuevo["sector"] = "VOCABULARIO_NUEVO"
    perfil = build_reference(referencia, spec)
    resultados = compute_drift(nuevo, perfil, spec)
    assert resultados[0].feature == "sector"
    assert resultados[0].band == "VOCABULARIO"


# --- persistencia ---


def test_el_perfil_sobrevive_el_viaje_por_json(spec, referencia, tmp_path):
    """Los cortes extremos son +-inf y en el JSON van como `null`.

    La primera version de este test asertaba lo contrario --que el archivo traia
    `Infinity`-- y dejaba escrito el riesgo: "si algun dia el perfil lo consumiera
    otro lenguaje habria que cambiarlo". Ese dia llego: el perfil se commitea y
    alimenta la vitrina, y `JSON.parse` lanza con `Infinity`. Asi que el test estaba
    fijando el defecto, y ahora fija el arreglo.
    """
    rng = np.random.default_rng(SEMILLA + 4)
    scores = rng.beta(2, 20, size=5_000)
    original = build_reference(referencia, spec, scores=scores)
    ruta = original.to_json(tmp_path / "perfil.json")

    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    assert crudo["numeric"]["monto"]["edges"][0] is None, "los infinitos van como null"

    vuelto = ReferenceProfile.from_json(ruta)
    assert vuelto.numeric["monto"].edges == original.numeric["monto"].edges
    assert vuelto.categorical["sector"].categories == original.categorical["sector"].categories
    assert vuelto.score.mean_logit == pytest.approx(original.score.mean_logit)

    # Y lo que importa: el PSI calculado con el perfil leido es el mismo.
    nuevo = referencia["monto"].to_numpy() * 1.3
    assert psi_numeric(vuelto.numeric["monto"], nuevo) == pytest.approx(
        psi_numeric(original.numeric["monto"], nuevo)
    )


def test_un_perfil_ausente_dice_como_generarlo(tmp_path):
    with pytest.raises(FileNotFoundError, match="--build"):
        ReferenceProfile.from_json(tmp_path / "no_existe.json")


def test_construir_un_perfil_no_exige_tener_los_datos_crudos(spec, referencia):
    """El defecto que `scripts/ci_local.py` encontro en su primera corrida.

    `build_reference` llamaba a `as_of_date()` adentro, que abre los 861 MB de CSV.
    Resultado: cinco tests con datos SINTETICOS --escritos precisamente para correr
    en CI-- fallaban con IOException en cualquier clon sin los datos. Pasaban aqui
    porque yo tengo los datos. Sexta vez del mismo patron.

    Este test fija la propiedad: un perfil se construye desde un DataFrame y nada
    mas. Si vuelve a exigir disco, falla aqui.
    """
    perfil = build_reference(referencia, spec)
    assert perfil.as_of == SIN_VINTAGE, "sin vintage se declara, no se adivina"
    assert perfil.n == len(referencia)
    assert perfil.numeric and perfil.categorical


def test_el_vintage_se_registra_cuando_se_pasa(spec, referencia):
    from datetime import date

    perfil = build_reference(referencia, spec, as_of=date(2026, 6, 30))
    assert perfil.as_of == "2026-06-30"


def test_el_perfil_es_JSON_valido_para_cualquier_lenguaje(spec, referencia, tmp_path):
    """`Infinity` no es JSON: `JSON.parse` lanza.

    El perfil se commitea y alimenta la vitrina, asi que un archivo que solo Python
    puede leer no sirve. La version anterior escribia 14 tokens `Infinity`. Un test
    de la semana 9 dejaba el riesgo por escrito; este lo cierra.
    """
    rng = np.random.default_rng(SEMILLA + 5)
    perfil = build_reference(referencia, spec, scores=rng.beta(2, 20, size=3_000))
    ruta = perfil.to_json(tmp_path / "perfil.json")
    texto = ruta.read_text(encoding="utf-8")

    assert "Infinity" not in texto and "NaN" not in texto

    # `parse_constant` es lo que usa json para Infinity/NaN: si se invoca, el
    # archivo no era JSON estandar.
    def prohibido(valor):  # pragma: no cover - solo corre si el archivo es invalido
        raise AssertionError(f"el JSON trae la constante no estandar {valor!r}")

    json.loads(texto, parse_constant=prohibido)

    # Y los cortes infinitos vuelven a serlo al leer.
    vuelto = ReferenceProfile.from_json(ruta)
    for nombre, p in vuelto.numeric.items():
        assert p.edges[0] == float("-inf"), nombre
        assert p.edges[-1] == float("inf"), nombre
    assert psi_numeric(vuelto.numeric["monto"], referencia["monto"].to_numpy()) == pytest.approx(
        0.0, abs=1e-9
    )
