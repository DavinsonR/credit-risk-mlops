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
    """metrics.json coherente con predicciones REALES.

    Se generan predicciones sinteticas y las metricas se DERIVAN de ellas, no se
    inventan: de otro modo el chequeo de integridad las rechazaria, que es
    justamente lo que debe hacer.
    """
    import numpy as np

    from crmlops.governance import integrity

    rng = np.random.default_rng(0)
    n = 4000
    y = (rng.random(n) < 0.1).astype("uint8")

    def con_separacion(sep: float) -> np.ndarray:
        """Predicciones con señal. El AUC exacto no importa: los tests son
        relativos al valor recomputado, no a una cifra fija."""
        return np.clip(0.1 + sep * y + rng.normal(0, 0.12, n), 0.001, 0.999)

    (tmp_path / "exports" / "verification").mkdir(parents=True)
    preds = {"lightgbm": con_separacion(0.25), "scorecard_woe": con_separacion(0.10)}
    integrity.save_predictions(y, preds, root=tmp_path)
    real = integrity.recompute_metrics(root=tmp_path)

    payload = {
        "vintage": "260630",
        "seed": cfg["project"]["random_seed"],
        "config_fingerprint": config_fingerprint(cfg),
        "code_fingerprint": integrity.code_fingerprint(),
        "production_model": "lightgbm",
        "production_calibrator": "intercept",
        "production_metrics": {
            **real["lightgbm"],
            "drop_oot": 0.03,
            "ece_test": 0.01,
        },
        "splits": {"train": [2011, 2015], "valid": [2016, 2016], "test": [2017, 2018]},
        "models": [{"modelo": name, **real[name], "drop_oot": 0.03} for name in preds],
    }
    path = tmp_path / "exports" / "metrics.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fallidos(results):
    return {r.name for r in results if not r.passed}


def test_pasa_cuando_el_modelo_cumple(metrics, cfg):
    assert _fallidos(evaluate(metrics, cfg)) == set()


def test_falla_cuando_el_auc_no_alcanza(metrics, cfg):
    """Umbral relativo al AUC real del fixture: el test no depende de que las
    predicciones sinteticas acierten una cifra concreta."""
    real = json.loads(metrics.read_text(encoding="utf-8"))["production_metrics"]["auc_test"]
    cfg["gates"]["min_auc_test"] = real + 0.05
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


def test_el_gate_evalua_produccion_no_el_modelo_crudo(metrics, cfg):
    """La configuracion de produccion es modelo + calibrador.

    Antes se controlaba el modelo crudo mientras se despachaba el calibrado
    (docs/AUDIT.md, defecto C).
    """
    data = json.loads(metrics.read_text(encoding="utf-8"))
    # Metricas de produccion peores que las crudas: el gate debe usar ESTAS.
    data["production_metrics"] = {
        "auc_test": 0.50,
        "drop_oot": 0.03,
        "brier_test": 0.08,
        "ece_test": 0.01,
    }
    metrics.write_text(json.dumps(data), encoding="utf-8")
    assert "auc_test" in _fallidos(evaluate(metrics, cfg))


def test_el_margen_sobre_baseline_es_relativo(metrics, cfg):
    """Si el retador no supera al interpretable, no se promueve."""
    data = json.loads(metrics.read_text(encoding="utf-8"))
    for m in data["models"]:
        m["auc_test"] = 0.70  # produccion y baseline empatados
    data["production_metrics"] = {
        "auc_test": 0.70,
        "drop_oot": 0.03,
        "brier_test": 0.08,
        "ece_test": 0.01,
    }
    metrics.write_text(json.dumps(data), encoding="utf-8")
    assert "margen_sobre_baseline" in _fallidos(evaluate(metrics, cfg))


# --- gate de equidad: bloquea PROMOCION, no rompe el build ---


@pytest.fixture
def hmda_metrics(tmp_path):
    def _write(dir_ratio: float, promoted: bool):
        path = tmp_path / "hmda_metrics.json"
        path.write_text(
            json.dumps(
                {
                    "model": "hmda_lightgbm",
                    "disparate_impact_ratio": dir_ratio,
                    "worst_dimension_group": "Grupo X",
                    "promoted": promoted,
                }
            ),
            encoding="utf-8",
        )
        return path

    return _write


def test_un_modelo_injusto_no_promovido_no_rompe_el_build(hmda_metrics, cfg):
    """Medirlo, documentarlo y no desplegarlo ES el sistema funcionando."""
    from crmlops.governance.gates import evaluate_fairness

    res = evaluate_fairness(cfg, hmda_metrics(0.70, promoted=False))
    assert res and res[0].passed
    assert "NO promovido" in res[0].detail


def test_promover_un_modelo_injusto_SI_rompe_el_build(hmda_metrics, cfg):
    """Lo que el gate impide es desplegar algo que no cumple el umbral."""
    from crmlops.governance.gates import evaluate_fairness

    res = evaluate_fairness(cfg, hmda_metrics(0.70, promoted=True))
    assert res and not res[0].passed


def test_un_modelo_justo_promovido_pasa(hmda_metrics, cfg):
    from crmlops.governance.gates import evaluate_fairness

    res = evaluate_fairness(cfg, hmda_metrics(0.92, promoted=True))
    assert res and res[0].passed


def test_sin_archivo_de_hmda_no_hay_gate(tmp_path, cfg):
    from crmlops.governance.gates import evaluate_fairness

    assert evaluate_fairness(cfg, tmp_path / "no-existe.json") == []
