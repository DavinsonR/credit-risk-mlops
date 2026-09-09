"""Los gates tienen que poder FALLAR.

Un gate que solo se ha visto pasar no es un control: es una decoracion que nadie
probo. Estos tests verifican los dos modos de falla que importan.
"""

from __future__ import annotations

import copy
import json

import pytest

from crmlops.config import load_config
from crmlops.governance.gates import config_fingerprint, evaluate


@pytest.fixture
def cfg() -> dict:
    return copy.deepcopy(load_config())


@pytest.fixture
def metrics(cfg, tmp_path):
    """Un metrics.json sintetico que pasa todos los gates."""
    payload = {
        "vintage": "260630",
        "seed": cfg["project"]["random_seed"],
        "config_fingerprint": config_fingerprint(cfg),
        "production_model": "lightgbm",
        "production_calibrator": "intercept",
        "splits": {"train": [2011, 2015], "valid": [2016, 2016], "test": [2017, 2018]},
        "models": [
            {"modelo": "lightgbm", "auc_test": 0.70, "drop_oot": 0.03, "brier_test": 0.08},
            {"modelo": "scorecard_woe", "auc_test": 0.66, "drop_oot": -0.01, "brier_test": 0.08},
        ],
    }
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fallidos(results):
    return {r.name for r in results if not r.passed}


def test_pasa_cuando_el_modelo_cumple(metrics, cfg):
    assert _fallidos(evaluate(metrics, cfg)) == set()


def test_falla_cuando_el_auc_no_alcanza(metrics, cfg):
    cfg["gates"]["min_auc_test"] = 0.75
    assert "auc_test" in _fallidos(evaluate(metrics, cfg))


def test_falla_cuando_la_degradacion_es_excesiva(metrics, cfg):
    cfg["gates"]["max_auc_drop_oot"] = 0.01
    assert "drop_oot" in _fallidos(evaluate(metrics, cfg))


def test_falla_si_cambia_el_split_sin_reentrenar(metrics, cfg):
    """El modo de falla sutil: metricas que ya no corresponden a la config."""
    cfg["splits"]["test"] = {"start": 2016, "end": 2018}
    results = evaluate(metrics, cfg)
    assert "config_coherente" in _fallidos(results)
    # Las metricas en si siguen dentro de umbral; lo que falla es la coherencia.
    assert "auc_test" not in _fallidos(results)


def test_falla_si_falta_el_archivo(tmp_path, cfg):
    results = evaluate(tmp_path / "no-existe.json", cfg)
    assert not results[0].passed


def test_falla_si_el_modelo_de_produccion_no_esta(metrics, cfg):
    data = json.loads(metrics.read_text(encoding="utf-8"))
    data["production_model"] = "modelo_fantasma"
    metrics.write_text(json.dumps(data), encoding="utf-8")
    assert "modelo_produccion" in _fallidos(evaluate(metrics, cfg))


def test_el_fingerprint_ignora_cambios_cosmeticos(cfg):
    """Cambiar una ruta no debe invalidar un entrenamiento; cambiar el split si."""
    antes = config_fingerprint(cfg)
    cfg["paths"]["exports"] = "otra/ruta"
    assert config_fingerprint(cfg) == antes

    cfg["splits"]["train"] = {"start": 2010, "end": 2015}
    assert config_fingerprint(cfg) != antes
