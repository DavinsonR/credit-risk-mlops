"""El panel HMDA parsea bien y nunca entrega clases protegidas al modelo.

Corre sobre un fixture de 8,000 filas (tests/fixtures/), no sobre los 260 shards
reales: CI no tiene los datos y no debe descargarlos.
"""

from __future__ import annotations

import pandas as pd
import pytest

from crmlops.config import repo_root
from crmlops.sources import hmda
from crmlops.sources.hmda_loader import (
    AGE_BUCKETS,
    DTI_BUCKETS,
    FEATURES,
    PROTECTED,
    TARGET,
    frame_for_model,
    load_split,
)

FIXTURES = "tests/fixtures"


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return load_split("test", root=repo_root() / FIXTURES)


def test_el_fixture_existe():
    assert (repo_root() / FIXTURES / "hmda_2024_WY_sample.parquet").exists()


def test_el_panel_no_esta_vacio_y_el_target_es_binario(panel):
    assert len(panel) > 1000
    assert set(panel[TARGET].unique()) <= {0, 1}
    assert 0.05 < panel[TARGET].mean() < 0.60


# --- la distincion central del trabajo de equidad ---


def test_las_protegidas_estan_en_el_panel(panel):
    """Sin ellas no se puede medir disparate impact."""
    for col in PROTECTED:
        assert col in panel.columns, f"falta la clase protegida {col} en el panel"


def test_las_protegidas_nunca_llegan_al_modelo(panel):
    """Con ellas en el modelo, se discrimina."""
    X = frame_for_model(panel)
    presentes = [c for c in PROTECTED if c in X.columns]
    assert presentes == [], f"clase protegida en la matriz del modelo: {presentes}"


def test_frame_for_model_aborta_si_una_protegida_se_declara_feature(panel, monkeypatch):
    import crmlops.sources.hmda_loader as mod

    monkeypatch.setattr(mod, "FEATURES", [*FEATURES, "race"])
    with pytest.raises(AssertionError, match="FUGA"):
        mod.frame_for_model(panel)


# --- las tres clases de exclusion (ADR 0006) ---


def test_las_columnas_prohibidas_no_se_descargaron():
    """No basta con no usarlas: no deben estar en el Parquet."""
    prohibidas = (
        set(hmda.FORBIDDEN_OUTCOME_ONLY)
        | set(hmda.FORBIDDEN_LENDER_DECISION)
        | set(hmda.FORBIDDEN_PROXY)
    )
    assert prohibidas.isdisjoint(hmda.KEEP)


def test_el_proxy_de_redlining_esta_prohibido():
    """tract_minority_population_percent es composicion racial del barrio."""
    assert "tract_minority_population_percent" in hmda.FORBIDDEN_PROXY
    assert "tract_minority_population_percent" not in hmda.KEEP


def test_las_variables_del_tract_que_si_entran_son_economicas():
    economicas = {
        "tract_population",
        "tract_to_msa_income_percentage",
        "tract_owner_occupied_units",
    }
    assert economicas <= set(hmda.KEEP)


# --- parseo ---


def test_dti_mezcla_tramos_de_texto_y_valores_exactos(panel):
    """HMDA reporta DTI exacto solo entre 36 y 49; fuera de ahi usa tramos."""
    dti = panel["dti"].dropna()
    assert len(dti) > 0
    assert dti.min() >= 0
    assert dti.max() <= 100
    # Los puntos medios de los tramos deben aparecer entre los valores.
    assert set(DTI_BUCKETS.values()) & set(dti.unique())


def test_la_edad_no_proporcionada_queda_nula_y_no_como_8888(panel):
    """8888 es un centinela. Dejarlo numerico crearia un outlier de 8888 anios."""
    edad = panel["age"].dropna()
    assert edad.max() <= max(AGE_BUCKETS.values())
    sentinelas = panel.loc[panel["age_bucket"].astype("string") == "8888", "age"]
    assert sentinelas.isna().all()


def test_los_montos_e_ingresos_son_positivos(panel):
    assert (panel["loan_amount"] > 0).all()
    assert panel["income"].notna().all()


def test_el_muestreo_es_reproducible():
    a = load_split("test", pct=50, seed=7, root=repo_root() / FIXTURES)
    b = load_split("test", pct=50, seed=7, root=repo_root() / FIXTURES)
    assert len(a) == len(b)
