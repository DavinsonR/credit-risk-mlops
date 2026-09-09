"""Guardas contra fuga de informacion.

Estos tests existen porque en la Semana 1 se descubrio que TermInMonths esta
contaminado (ADR 0002). Su trabajo es impedir que vuelva a entrar por descuido.
"""

from __future__ import annotations

import re

import pytest

from crmlops.config import load_config
from crmlops.sources import loader


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


def test_terminmonths_esta_prohibido(cfg):
    """TermInMonths debe estar en la lista de prohibidos. Ver ADR 0002."""
    assert "TermInMonths" in cfg["features"]["forbidden"]


def test_terminmonths_no_se_selecciona_como_feature(cfg):
    """La query del panel no debe proyectar TermInMonths como columna."""
    sql = loader.build_query(cfg)
    # Se permite en el WHERE (filtro de validez), nunca en el SELECT.
    select_part = sql.split("from ")[0]
    assert "TermInMonths" not in select_part, (
        "TermInMonths reaparecio en el SELECT del panel. Esta contaminado: "
        "se sobrescribe al liquidar el prestamo. Ver docs/adr/0002."
    )


def test_ninguna_columna_prohibida_en_el_select(cfg):
    """Ningun campo de resultado puede proyectarse al panel de modelado."""
    sql = loader.build_query(cfg)
    select_part = sql.split("from ")[0]
    # Tres columnas se proyectan A PROPOSITO y nunca son features:
    #   LoanStatus / GrossChargeOffAmount -> targets (PD y LGD)
    #   ApprovalFY                        -> eje del split out-of-time
    # test_feature_columns_excluye_no_features verifica que no lleguen al modelo.
    proyectadas_con_proposito = {"GrossChargeOffAmount", "LoanStatus", "ApprovalFY"}
    for col in cfg["features"]["forbidden"]:
        if col in proyectadas_con_proposito:
            continue
        assert not re.search(rf"\b{re.escape(col)}\b", select_part), (
            f"Columna prohibida {col!r} proyectada en el panel. "
            "Ver config.yaml: features.forbidden"
        )


def test_el_umbral_del_gate_esta_declarado(cfg):
    """El criterio del signal gate debe estar fijado en config, no en codigo."""
    assert 0.5 < cfg["signal_gate"]["min_auc"] < 1.0


def test_feature_columns_excluye_no_features(cfg):
    """El target, la severidad y el eje temporal nunca entran a la lista de features."""
    import pandas as pd

    from crmlops.evaluation.signal_check import NON_FEATURES, feature_columns

    panel_cols = ["is_chargeoff", "chargeoff_amount", "approval_fy", "gross_approval"]
    cols = feature_columns(pd.DataFrame(columns=panel_cols), cfg)
    assert set(cols).isdisjoint(NON_FEATURES)
    assert "gross_approval" in cols


def test_feature_columns_detecta_reentrada_de_term(cfg):
    """Si term_months reaparece en el panel, feature_columns debe abortar."""
    import pandas as pd

    from crmlops.evaluation.signal_check import feature_columns

    contaminado = pd.DataFrame(columns=["is_chargeoff", "approval_fy", "term_months"])
    with pytest.raises(AssertionError, match="FUGA"):
        feature_columns(contaminado, cfg)
