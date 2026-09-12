"""Los criterios de identificacion tienen que ser criterios, no adornos.

Un diagnostico causal que siempre concluye "no identificado" no diagnostica nada, y
uno que siempre concluye "viable" es peor. Estos tests le dan a cada criterio casos
en los dos lados.

Los tests sobre el panel real van marcados `data` y fijan el hallazgo del ADR 0013.
"""

from __future__ import annotations

import pytest

from crmlops.causal.identification import (
    LEVELS,
    THRESHOLD_USD,
    Densidad,
    Determinacion,
    Gradiente,
)

# --- los criterios, sin tocar datos ---


def test_un_tratamiento_determinado_por_la_regla_no_es_identificable():
    d = Determinacion(
        n=1_000_000, celdas=3_000, r2=0.9145, niveles_distintos=3832, masa_en_cuatro_niveles=90.95
    )
    assert not d.identificable


def test_un_tratamiento_con_variacion_propia_si_lo_es():
    d = Determinacion(
        n=1_000_000, celdas=3_000, r2=0.42, niveles_distintos=3832, masa_en_cuatro_niveles=90.95
    )
    assert d.identificable


def test_el_apilamiento_en_el_umbral_cierra_el_RD():
    den = Densidad(
        umbral=THRESHOLD_USD,
        n_exacto=52_770,
        por_ventana=[{"ventana_usd": 5000, "n": 63484, "pct_en_umbral": 83.12}],
    )
    assert not den.rd_explotable


def test_una_densidad_continua_lo_deja_abierto():
    den = Densidad(
        umbral=THRESHOLD_USD,
        n_exacto=120,
        por_ventana=[{"ventana_usd": 5000, "n": 40000, "pct_en_umbral": 0.3}],
    )
    assert den.rd_explotable


def test_el_criterio_de_densidad_mira_la_ventana_MAS_ESTRECHA():
    """La ventana ancha diluye el apilamiento y haria pasar un RD invalido.

    Con +-$50k el apilamiento baja al 18.5% y el criterio del 10% quedaria cerca de
    aprobarse; con +-$5k es 83%. Hay que mirar donde el RD seria creible.
    """
    den = Densidad(
        umbral=THRESHOLD_USD,
        n_exacto=52_770,
        por_ventana=[
            {"ventana_usd": 50000, "n": 284988, "pct_en_umbral": 18.52},
            {"ventana_usd": 5000, "n": 63484, "pct_en_umbral": 83.12},
        ],
    )
    assert not den.rd_explotable


def test_la_fraccion_explicada_por_tamano_se_calcula_bien():
    g = Gradiente(crudo_pp=7.76, dentro_de_tramo_pp=4.79, n_comparable=112_526, por_tramo=[])
    assert g.explicado_por_tamano == pytest.approx(0.3827, abs=1e-3)


def test_si_el_gradiente_desaparece_al_condicionar_era_todo_composicion():
    g = Gradiente(crudo_pp=7.76, dentro_de_tramo_pp=0.0, n_comparable=1000, por_tramo=[])
    assert g.explicado_por_tamano == pytest.approx(1.0)


def test_un_gradiente_crudo_nulo_no_divide_por_cero():
    g = Gradiente(crudo_pp=0.0, dentro_de_tramo_pp=0.0, n_comparable=0, por_tramo=[])
    assert g.explicado_por_tamano == 0.0


# --- sobre el panel real: el hallazgo del ADR 0013 ---


@pytest.mark.data
def test_el_tratamiento_esta_determinado_administrativamente():
    from crmlops.causal.identification import determinacion

    d = determinacion()
    assert d.n > 1_000_000, "el panel resuelto deberia superar el millon de prestamos"
    assert d.r2 > 0.85, f"R2 cayo a {d.r2}: revisar si cambio el dato o la definicion"
    assert not d.identificable


@pytest.mark.data
def test_hay_apilamiento_masivo_en_el_umbral():
    from crmlops.causal.identification import densidad

    den = densidad()
    estrecha = min(den.por_ventana, key=lambda d: d["ventana_usd"])
    assert estrecha["pct_en_umbral"] > 50, (
        f"el apilamiento cayo a {estrecha['pct_en_umbral']}%: el RD podria reabrirse"
    )
    assert not den.rd_explotable


@pytest.mark.data
def test_el_gradiente_no_es_enteramente_tamano():
    """El punto que corrige un analisis previo.

    Se habia afirmado que el gradiente crudo era "enteramente tamano del prestamo".
    No lo es: condicionar quita ~38% y queda un residual consistente en signo. Que
    ese residual exista es lo que obliga a explicarlo como seleccion en vez de
    descartarlo como composicion.
    """
    from crmlops.causal.identification import gradiente

    g = gradiente()
    assert g.crudo_pp > 0, f"el gradiente crudo cambio de signo: {g.crudo_pp}"
    assert g.dentro_de_tramo_pp > 0, (
        f"el residual desaparecio ({g.dentro_de_tramo_pp} pp): ahora SI seria "
        "todo composicion, y el ADR 0013 hay que reescribirlo"
    )
    assert 0.0 < g.explicado_por_tamano < 1.0
    assert g.n_comparable > 50_000


@pytest.mark.data
def test_los_dos_niveles_comparados_existen_en_el_dato():
    from crmlops.causal.identification import gradiente

    g = gradiente()
    assert g.por_tramo, f"no hay tramos con {LEVELS[0]} y {LEVELS[1]} a la vez"
    for fila in g.por_tramo:
        assert fila["n_bajo"] > 0 and fila["n_alto"] > 0
