"""El estimador intra-celda y la descomposicion, verificados contra su definicion.

Los dos resultados que este modulo publica son formas cerradas. Una forma cerrada
que nadie contrasta contra el problema que dice resolver es una afirmacion, no un
estimador -- asi que aqui se contrastan:

  - `estudio_evento` se compara contra MINIMOS CUADRADOS POR FUERZA BRUTA con los
    efectos fijos de celda-ano escritos explicitamente como columnas de diseno.
  - `descomposicion` se compara contra el cambio OBSERVADO, que es la unica forma
    de saber que la identidad de Kitagawa no perdio un termino.

Todo corre sobre Parquet sintetico: sin datos descargados, y con la respuesta
conocida por construccion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crmlops.causal import event_study as ev

BASE = 2021
YEARS = (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025)


def _cfg(**over) -> dict:
    cfg = {
        "event_study": {
            "years": list(YEARS),
            "base_year": BASE,
            "shock_year": 2022,
            "focal_group": "Black or African American",
            "reference_group": "White",
            "cell_keys": ["county_code", "loan_purpose", "lien_status", "occupancy_type"],
            "min_per_cell_group": 25,
            "meaningful_pp": 1.0,
        }
    }
    cfg["event_study"].update(over)
    return cfg


# --------------------------------------------------------------------------
# El estimador contra minimos cuadrados explicitos
# --------------------------------------------------------------------------
def _wls_fuerza_bruta(df: pd.DataFrame, base: int) -> dict[int, float]:
    """MCO ponderado con efectos fijos de celda-ano escritos a mano.

    Cada observacion es una (celda, ano, grupo) con peso n y respuesta la tasa. Eso
    es identico a la regresion individual: dentro de una celda-ano-grupo todas las
    filas comparten la misma X, asi que las ecuaciones normales colapsan a esto.

    Diseno: una columna por celda-ano (el efecto fijo) y una columna por ano con el
    indicador del grupo focal. El coeficiente de esa columna ES theta_t.
    """
    obs, y, w = [], [], []
    for r in df.itertuples():
        obs.append((f"{r.celda}@{r.anio}", r.anio, 1))
        y.append(r.k_focal / r.n_focal)
        w.append(r.n_focal)
        obs.append((f"{r.celda}@{r.anio}", r.anio, 0))
        y.append(r.k_ref / r.n_ref)
        w.append(r.n_ref)

    fe = sorted({o[0] for o in obs})
    anios = sorted({o[1] for o in obs})
    fe_ix = {k: i for i, k in enumerate(fe)}
    th_ix = {a: len(fe) + i for i, a in enumerate(anios)}

    X = np.zeros((len(obs), len(fe) + len(anios)))
    for i, (cell_year, anio, focal) in enumerate(obs):
        X[i, fe_ix[cell_year]] = 1.0
        if focal:
            X[i, th_ix[anio]] = 1.0

    sw = np.sqrt(np.asarray(w, dtype=float))
    beta, *_ = np.linalg.lstsq(X * sw[:, None], np.asarray(y) * sw, rcond=None)
    return {a: float(beta[th_ix[a]]) for a in anios}


def _celdas_sinteticas(rng: np.random.Generator, n_condados: int = 12) -> pd.DataFrame:
    filas = []
    for c in range(n_condados):
        for purpose in ("1", "31"):
            for anio in YEARS:
                n_f = int(rng.integers(30, 400))
                n_r = int(rng.integers(60, 900))
                p_f, p_r = rng.uniform(0.15, 0.45), rng.uniform(0.05, 0.25)
                filas.append(
                    {
                        "anio": anio,
                        "county_code": f"{c:05d}",
                        "loan_purpose": purpose,
                        "lien_status": "1",
                        "occupancy_type": "1",
                        "n_focal": n_f,
                        "k_focal": int(rng.binomial(n_f, p_f)),
                        "n_ref": n_r,
                        "k_ref": int(rng.binomial(n_r, p_r)),
                    }
                )
    df = pd.DataFrame(filas)
    df["celda"] = df[["county_code", "loan_purpose", "lien_status", "occupancy_type"]].agg(
        "|".join, axis=1
    )
    return df


def test_forma_cerrada_es_la_solucion_de_minimos_cuadrados():
    """theta_t de la forma cerrada == coeficiente de MCO con los FE explicitos.

    Es la prueba que justifica no usar una libreria de regresion: si difiere, la
    forma cerrada esta mal derivada y todos los coeficientes publicados estan mal.
    """
    df = _celdas_sinteticas(np.random.default_rng(7))
    resultado = ev.estudio_evento(df, _cfg())
    fuerza = _wls_fuerza_bruta(df, BASE)

    for c in resultado.coeficientes:
        assert c.theta_pp / 100 == pytest.approx(fuerza[c.anio], abs=1e-10), (
            f"ano {c.anio}: forma cerrada {c.theta_pp / 100:.10f} vs MCO {fuerza[c.anio]:.10f}"
        )


def test_gamma_es_la_diferencia_contra_el_ano_base():
    df = _celdas_sinteticas(np.random.default_rng(11))
    r = ev.estudio_evento(df, _cfg())
    base = next(c for c in r.coeficientes if c.anio == BASE)
    assert base.gamma_pp == pytest.approx(0.0, abs=1e-12)
    assert base.se_pp == 0.0
    for c in r.coeficientes:
        assert c.gamma_pp == pytest.approx(c.theta_pp - base.theta_pp, abs=1e-10)


def test_error_agrupado_es_cero_sin_dispersion_entre_condados():
    """Si todas las celdas tienen la misma brecha, no hay nada que promediar."""
    filas = []
    for c in range(8):
        for anio in YEARS:
            n_f, n_r = 100, 200
            filas.append(
                {
                    "anio": anio,
                    "county_code": f"{c:05d}",
                    "loan_purpose": "1",
                    "lien_status": "1",
                    "occupancy_type": "1",
                    "n_focal": n_f,
                    "k_focal": 30,  # 30%
                    "n_ref": n_r,
                    "k_ref": 20,  # 10%
                }
            )
    df = pd.DataFrame(filas)
    df["celda"] = df["county_code"]
    r = ev.estudio_evento(df, _cfg())
    for c in r.coeficientes:
        assert c.theta_pp == pytest.approx(20.0, abs=1e-9)
        assert c.se_pp == pytest.approx(0.0, abs=1e-12)


def test_agrupar_por_condado_no_es_lo_mismo_que_no_agrupar():
    """Con correlacion dentro del condado, el error agrupado tiene que ser MAYOR.

    Es la razon de agrupar: las celdas de un mismo condado comparten el mercado
    local, asi que tratarlas como independientes subestima el error. Se construye
    un caso donde todas las celdas de un condado comparten desviacion.

    La desviacion se sortea por condado-ANIO y no solo por condado. Un componente
    fijo del condado se cancela solo al restar el ano base -- propiedad correcta del
    estimador, y la razon por la que este test fallaba en su primera version: los
    dos errores daban exactamente cero.
    """
    rng = np.random.default_rng(3)
    filas = []
    for c in range(20):
        for anio in (BASE, 2023):
            shock = rng.normal(0, 0.08)  # comun a todas las celdas del condado ese anio
            for purpose in ("1", "2", "31", "32"):
                p_r = 0.15
                p_f = np.clip(0.30 + shock, 0.01, 0.9)
                filas.append(
                    {
                        "anio": anio,
                        "county_code": f"{c:05d}",
                        "loan_purpose": purpose,
                        "lien_status": "1",
                        "occupancy_type": "1",
                        "n_focal": 200,
                        "k_focal": int(200 * p_f),
                        "n_ref": 400,
                        "k_ref": int(400 * p_r),
                    }
                )
    df = pd.DataFrame(filas)
    df["celda"] = df[["county_code", "loan_purpose", "lien_status", "occupancy_type"]].agg(
        "|".join, axis=1
    )
    cfg = _cfg(years=[BASE, 2023])
    por_condado = ev.estudio_evento(df, cfg)

    # Misma muestra, pero cada celda declarada como su propio condado.
    suelto = df.copy()
    suelto["county_code"] = suelto["celda"]
    por_celda = ev.estudio_evento(suelto, cfg)

    a = next(c for c in por_condado.coeficientes if c.anio == 2023)
    b = next(c for c in por_celda.coeficientes if c.anio == 2023)
    assert a.gamma_pp == pytest.approx(b.gamma_pp, abs=1e-10), "el punto no debe cambiar"
    assert a.se_pp > b.se_pp * 1.5, (
        f"agrupar por condado deberia ampliar el error: {a.se_pp:.4f} vs {b.se_pp:.4f}"
    )


# --------------------------------------------------------------------------
# El veredicto usa la misma vara para antes y despues
# --------------------------------------------------------------------------
def _coef(anio: int, gamma: float) -> ev.Coeficiente:
    return ev.Coeficiente(anio=anio, theta_pp=10 + gamma, gamma_pp=gamma, se_pp=0.1, celdas=9, n=99)


def test_tendencia_previa_no_plana_bloquea_la_lectura_causal():
    e = ev.EstudioEvento(
        base_year=BASE,
        balanceado=True,
        meaningful_pp=1.0,
        coeficientes=[_coef(2019, -2.4), _coef(BASE, 0.0), _coef(2023, 3.0)],
    )
    assert not e.tendencias_paralelas
    assert e.veredicto.startswith("NO IDENTIFICADO")


def test_nulo_identificado_cuando_todo_esta_bajo_el_umbral():
    e = ev.EstudioEvento(
        base_year=BASE,
        balanceado=True,
        meaningful_pp=1.0,
        coeficientes=[_coef(2019, 0.2), _coef(BASE, 0.0), _coef(2023, 0.4)],
    )
    assert e.tendencias_paralelas
    assert e.veredicto.startswith("NULO IDENTIFICADO")


def test_efecto_solo_si_las_previas_pasan():
    e = ev.EstudioEvento(
        base_year=BASE,
        balanceado=True,
        meaningful_pp=1.0,
        coeficientes=[_coef(2019, 0.1), _coef(BASE, 0.0), _coef(2024, 2.7)],
    )
    assert e.veredicto.startswith("EFECTO")
    assert e.efecto_maximo_pp == pytest.approx(2.7)


def test_el_ano_del_shock_no_cuenta_como_post():
    """2022 es de transicion: solicitudes de enero se deciden con tasas viejas.

    Incluirlo como post mezclaria periodos tratados y sin tratar dentro del mismo
    coeficiente, que es justo lo que la literatura de DiD escalonado penaliza.
    """
    e = ev.EstudioEvento(
        base_year=BASE,
        balanceado=True,
        meaningful_pp=1.0,
        coeficientes=[_coef(BASE, 0.0), _coef(2022, 9.9), _coef(2023, 0.3)],
    )
    assert [c.anio for c in e.posteriores] == [2023]
    assert e.efecto_maximo_pp == pytest.approx(0.3)


# --------------------------------------------------------------------------
# Descomposicion: la identidad tiene que cuadrar, no aproximar
# --------------------------------------------------------------------------
def _parquet_sintetico(tmp_path, rng: np.random.Generator):
    """Panel HMDA minimo con recomposicion DELIBERADA entre 2021 y 2023.

    El segmento '31' (refinanciacion) casi desaparece en 2023 y el grupo focal esta
    sobrerrepresentado en el segmento caro. Es el mecanismo que el modulo busca.
    """
    filas = []
    plan = {
        # (anio, purpose): (n_focal, n_ref, p_focal, p_ref)
        (2021, "1"): (4000, 12000, 0.22, 0.11),
        (2021, "31"): (6000, 20000, 0.18, 0.09),
        (2023, "1"): (3800, 11000, 0.24, 0.13),
        (2023, "31"): (400, 2000, 0.30, 0.16),
    }
    for (anio, purpose), (nf, nr, pf, pr) in plan.items():
        for grupo, n, p in (
            ("Black or African American", nf, pf),
            ("White", nr, pr),
        ):
            den = rng.binomial(n, p)
            for i in range(n):
                filas.append(
                    {
                        "activity_year": str(anio),
                        "action_taken": "3" if i < den else "1",
                        "derived_race": grupo,
                        "derived_ethnicity": "Not Hispanic or Latino",
                        "county_code": f"{i % 6:05d}",
                        "loan_purpose": purpose,
                        "lien_status": "1",
                        "occupancy_type": "1",
                        "loan_amount": "250000",
                        "income": "90",
                    }
                )
    path = tmp_path / "panel.parquet"
    pd.DataFrame(filas).to_parquet(path)
    return f"['{path.as_posix()}']"


def test_kitagawa_cuadra_exactamente():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        rng = np.random.default_rng(5)
        src = _parquet_sintetico(Path(tmp), rng)
        cfg = _cfg(years=[2021, 2023])
        con = ev._connect(2)
        ev.build_panel(con, cfg, source=src)
        d = ev.descomposicion(con, 2023, cfg)

        assert d.cuadra, (
            f"composicion {d.composicion_pp} + tasas {d.tasas_pp} != cambio {d.cambio_brecha_pp}"
        )
        assert d.composicion_pp + d.tasas_pp == pytest.approx(d.cambio_brecha_pp, abs=1e-9)
        # El plan mueve masa entre segmentos con niveles distintos, asi que el
        # termino de composicion no puede ser despreciable.
        assert abs(d.composicion_pp) > 0.01


def test_panel_balanceado_descarta_celdas_incompletas():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        rng = np.random.default_rng(9)
        src = _parquet_sintetico(Path(tmp), rng)
        cfg = _cfg(years=[2021, 2023], min_per_cell_group=200)
        con = ev._connect(2)
        ev.build_panel(con, cfg, source=src)

        desb = ev.celdas(con, cfg, balanceado=False)
        bal = ev.celdas(con, cfg, balanceado=True)
        assert bal["celda"].nunique() <= desb["celda"].nunique()
        # Balanceado significa exactamente eso: cada celda aparece en todos los anios.
        conteo = bal.groupby("celda")["anio"].nunique()
        assert set(conteo.unique()) <= {len(cfg["event_study"]["years"])}


# --------------------------------------------------------------------------
# Integridad: los coeficientes publicados se recomputan desde el CSV commiteado
# --------------------------------------------------------------------------
def test_los_coeficientes_publicados_se_recomputan_desde_las_celdas():
    """El mismo principio que el gate `integridad`: no creerle al JSON.

    `exports/event_study_cells.csv` lleva las 18.272 celda-anio con sus conteos, asi
    que un revisor puede rehacer cada coeficiente sin descargar 93.4M filas. Si el
    JSON publicado y el CSV dejan de coincidir, uno de los dos se edito a mano.
    """
    import json
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    celdas = raiz / "exports" / "event_study_cells.csv"
    publicado = raiz / "exports" / "event_study_hmda.json"
    if not (celdas.exists() and publicado.exists()):
        pytest.skip("faltan los exports; correr `run event-study`")

    df = pd.read_csv(celdas, dtype={"county_code": str, "celda": str})
    cfg = _cfg(years=sorted(df["anio"].unique().tolist()))
    recomputado = ev.estudio_evento(df, cfg)
    esperado = {
        c["anio"]: c
        for c in json.loads(publicado.read_text(encoding="utf-8"))["estudio_evento"]["coeficientes"]
    }

    for c in recomputado.coeficientes:
        e = esperado[c.anio]
        assert c.gamma_pp == pytest.approx(e["gamma_pp"], abs=1e-9), (
            f"{c.anio}: recomputado {c.gamma_pp:.6f} vs publicado {e['gamma_pp']:.6f}"
        )
        assert c.se_pp == pytest.approx(e["se_pp"], abs=1e-9)
        assert c.celdas == e["celdas"]


def test_el_csv_commiteado_esta_balanceado():
    """Cada celda aparece en todos los anios de la ventana, o el estimador compara
    conjuntos distintos entre periodos y el coeficiente mezcla dos cosas."""
    from pathlib import Path

    celdas = Path(__file__).resolve().parents[1] / "exports" / "event_study_cells.csv"
    if not celdas.exists():
        pytest.skip("falta el export; correr `run event-study`")
    df = pd.read_csv(celdas, dtype={"celda": str})
    conteo = df.groupby("celda")["anio"].nunique()
    n_anios = df["anio"].nunique()
    assert set(conteo.unique()) == {n_anios}, "hay celdas con distinta cantidad de anios"
