"""El panel que sale del loader cumple su contrato.

Corre sobre un fixture muestreado y sin PII (tests/fixtures/), no sobre los CSV
completos: CI no tiene los datos y no debe descargarlos.
"""

from __future__ import annotations

import pandas as pd
import pytest

from crmlops.config import load_config, repo_root
from crmlops.sources.contracts import PanelSBA, validate_panel
from crmlops.sources.loader import load_panel, split_out_of_time

FIXTURE = "tests/fixtures/sba_7a_sample.csv"


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return load_panel(load_config(), source_glob=(repo_root() / FIXTURE).as_posix())


def test_el_fixture_existe():
    assert (repo_root() / FIXTURE).exists(), "falta el fixture; regenerar con scripts/"


def test_el_fixture_no_tiene_pii():
    """El dataset trae nombres y direcciones. Publico no significa replicable."""
    header = (repo_root() / FIXTURE).read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
    for pii in ("BorrName", "BorrStreet", "BankStreet", "BorrZip"):
        assert pii not in header, f"el fixture contiene PII: {pii}"


def test_el_panel_cumple_el_contrato(panel):
    validate_panel(panel)


def test_el_panel_no_trae_la_columna_contaminada(panel):
    """term_months esta contaminado (ADR 0002); strict=True del contrato lo bloquea."""
    assert "term_months" not in panel.columns


def test_solo_entran_estados_resueltos(panel):
    """CANCLD y EXEMPT deben quedar fuera: no son 'no incumplio'."""
    assert set(panel["is_chargeoff"].unique()) <= {0, 1}
    assert 0.05 <= panel["is_chargeoff"].mean() <= 0.35


def test_el_split_es_temporal_y_no_se_solapa(panel):
    cfg = load_config()
    sp = split_out_of_time(panel, cfg)
    assert sp["train"]["approval_fy"].max() < sp["valid"]["approval_fy"].min()
    assert sp["valid"]["approval_fy"].max() < sp["test"]["approval_fy"].min()


def test_el_contrato_rechaza_columnas_extra(panel):
    """strict=True: si reaparece una columna prohibida, el contrato falla."""
    import pandera.errors

    contaminado = panel.assign(term_months=1.0)
    with pytest.raises(pandera.errors.SchemaErrors):
        PanelSBA.validate(contaminado, lazy=True)
