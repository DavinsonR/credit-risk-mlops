"""La integridad del artefacto de metricas tiene que resistir manipulacion.

Estos tests existen porque durante la auditoria se demostro que editar
exports/metrics.json a mano y poner AUC 0.95 pasaba los cuatro gates sin
resistencia (docs/AUDIT.md, defecto A1).
"""

from __future__ import annotations

import numpy as np
import pytest

from crmlops.config import load_config
from crmlops.features.spec import load_spec
from crmlops.governance import integrity


@pytest.fixture
def artefactos(tmp_path):
    """Un repo sintetico con predicciones y metricas coherentes entre si."""
    rng = np.random.default_rng(0)
    n = 4000
    y = (rng.random(n) < 0.1).astype("uint8")
    # Predicciones con senal real, para que el AUC no sea 0.5
    p = np.clip(0.1 + 0.25 * y + rng.normal(0, 0.12, n), 0.001, 0.999)

    (tmp_path / "exports" / "verification").mkdir(parents=True)
    integrity.save_predictions(y, {"lightgbm": p}, root=tmp_path)

    real = integrity.recompute_metrics(root=tmp_path)["lightgbm"]
    published = {
        "code_fingerprint": integrity.code_fingerprint(),
        "models": [{"modelo": "lightgbm", **real}],
    }
    return tmp_path, published, real


def test_no_hay_problemas_cuando_todo_coincide(artefactos):
    root, published, _ = artefactos
    assert integrity.check(published, artifacts_root=root) == []


def test_detecta_una_metrica_inflada_a_mano(artefactos):
    """El ataque exacto que funcionaba antes de la auditoria."""
    root, published, real = artefactos
    published["models"][0]["auc_test"] = 0.95

    issues = integrity.check(published, artifacts_root=root)
    kinds = {i.kind for i in issues}
    assert "metrica_alterada" in kinds
    assert f"{real['auc_test']:.6f}" in " ".join(i.detail for i in issues)


def test_detecta_cambio_de_codigo_sin_reentrenar(artefactos):
    root, published, _ = artefactos
    published["code_fingerprint"] = "0000000000000000"
    assert "codigo_cambiado" in {i.kind for i in integrity.check(published, artifacts_root=root)}


def test_detecta_ausencia_de_predicciones(tmp_path):
    published = {"code_fingerprint": integrity.code_fingerprint(), "models": []}
    assert "sin_predicciones" in {
        i.kind for i in integrity.check(published, artifacts_root=tmp_path)
    }


def test_una_desviacion_menor_que_la_tolerancia_no_dispara(artefactos):
    """Parquet guarda float32; el ruido de redondeo no debe reportarse como fraude."""
    root, published, real = artefactos
    published["models"][0]["auc_test"] = real["auc_test"] + integrity.RECOMPUTE_TOLERANCE / 10
    assert integrity.check(published, artifacts_root=root) == []


def test_el_fingerprint_de_codigo_ignora_finales_de_linea():
    """El repo usa autocrlf: un checkout en Windows y otro en Linux deben coincidir."""
    import hashlib

    crlf = b"linea uno\r\nlinea dos\r\n"
    lf = b"linea uno\nlinea dos\n"
    assert hashlib.sha256(crlf.replace(b"\r\n", b"\n")).digest() == hashlib.sha256(lf).digest()


# --- especificacion de features ---


def test_el_spec_se_lee_de_config_y_no_esta_vacio():
    spec = load_spec(load_config())
    assert spec.numeric and spec.categorical
    assert set(spec.all).isdisjoint(spec.forbidden_panel)


def test_el_spec_rechaza_una_feature_prohibida():
    cfg = load_config()
    roto = {
        **cfg,
        "features": {**cfg["features"], "numeric": [*cfg["features"]["numeric"], "term_months"]},
    }
    with pytest.raises(ValueError, match="se contradice"):
        load_spec(roto)


def test_el_spec_falla_si_el_panel_no_trae_lo_declarado():
    import pandas as pd

    spec = load_spec(load_config())
    with pytest.raises(KeyError):
        spec.validate_against(pd.DataFrame(columns=["otra_cosa"]))
