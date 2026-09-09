"""Integridad del artefacto de metricas.

El problema (docs/AUDIT.md, defecto A1): los gates leian exports/metrics.json y
confiaban en el. Editar ese archivo a mano y poner AUC 0.95 pasaba los cuatro
gates sin resistencia. Un control que valida su propia entrada sin verificarla no
es un control.

La solucion es que el gate NO crea el numero: lo RECOMPUTA. El entrenamiento
guarda las predicciones sobre test junto con las etiquetas, y el gate recalcula
AUC, Gini, KS y Brier desde esos vectores. Para falsear una metrica ahora hay que
fabricar 89 mil predicciones que realmente alcancen el valor declarado -- y a esas
alturas ya se hizo el trabajo.

Segunda capa: una huella del codigo de modelado. Cambiar como se entrena sin
reentrenar deja el artefacto invalido, igual que cambiar el config.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from crmlops.config import repo_root

# Modulos cuyo contenido determina el resultado del entrenamiento.
# Cambiar cualquiera invalida las metricas publicadas.
MODELING_SOURCES = (
    "src/crmlops/models/scorecard.py",
    "src/crmlops/models/gbm.py",
    "src/crmlops/models/neural.py",
    "src/crmlops/models/calibration.py",
    "src/crmlops/models/train.py",
    "src/crmlops/features/spec.py",
    "src/crmlops/sources/loader.py",
    "src/crmlops/evaluation/metrics.py",
)

PREDICTIONS_PATH = "exports/verification/test_predictions.parquet"
# Tolerancia de recomputo. No es cero: parquet guarda float32 y las metricas se
# calculan en float64, asi que hay redondeo esperable en el sexto decimal.
RECOMPUTE_TOLERANCE = 1e-4


@dataclass
class IntegrityIssue:
    kind: str
    detail: str


def code_fingerprint(root: Path | None = None) -> str:
    """Huella del codigo que produce las metricas.

    Se normalizan los finales de linea antes de hashear: el repo usa autocrlf y
    un checkout en Windows daria una huella distinta a uno en Linux para el mismo
    codigo. Sin eso, CI fallaria siempre.
    """
    root = root or repo_root()
    h = hashlib.sha256()
    for rel in MODELING_SOURCES:
        path = root / rel
        if not path.exists():
            h.update(f"<missing:{rel}>".encode())
            continue
        content = path.read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode())
        h.update(hashlib.sha256(content).digest())
    return h.hexdigest()[:16]


def save_predictions(
    y_true: np.ndarray, preds: dict[str, np.ndarray], root: Path | None = None
) -> Path:
    """Guarda etiquetas y predicciones de test para que el gate pueda recomputar."""
    root = root or repo_root()
    path = root / PREDICTIONS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame({"y": np.asarray(y_true, dtype="uint8")})
    for name, p in preds.items():
        frame[name] = np.asarray(p, dtype="float32")
    frame.to_parquet(path, index=False, compression="zstd")
    return path


def recompute_metrics(root: Path | None = None) -> dict[str, dict[str, float]]:
    """Recalcula las metricas de test desde las predicciones guardadas."""
    from crmlops.evaluation.metrics import calibration, discrimination

    root = root or repo_root()
    path = root / PREDICTIONS_PATH
    if not path.exists():
        return {}

    frame = pd.read_parquet(path)
    y = frame["y"].to_numpy()
    out: dict[str, dict[str, float]] = {}
    for name in frame.columns:
        if name == "y":
            continue
        p = frame[name].to_numpy(dtype="float64")
        d, c = discrimination(y, p), calibration(y, p)
        out[name] = {
            "auc_test": d.auc,
            "gini_test": d.gini,
            "ks_test": d.ks,
            "brier_test": c.brier,
        }
    return out


def check(
    published: dict,
    artifacts_root: Path | None = None,
    code_root: Path | None = None,
) -> list[IntegrityIssue]:
    """Verifica que las metricas publicadas no fueron alteradas.

    Son DOS raices distintas y confundirlas era un bug: `artifacts_root` es donde
    viven las predicciones (exports/), y `code_root` es donde vive el codigo de
    modelado. Al pasar una sola, verificar artefactos en un directorio temporal
    hacia que el fingerprint de codigo buscara los .py ahi y no los encontrara.
    """
    issues: list[IntegrityIssue] = []

    recorded_code = published.get("code_fingerprint")
    current_code = code_fingerprint(code_root)
    if recorded_code != current_code:
        issues.append(
            IntegrityIssue(
                "codigo_cambiado",
                f"metricas producidas por codigo {recorded_code}, actual {current_code}: "
                "reentrenar",
            )
        )

    recomputed = recompute_metrics(artifacts_root)
    if not recomputed:
        issues.append(
            IntegrityIssue(
                "sin_predicciones",
                f"falta {PREDICTIONS_PATH}; las metricas no se pueden verificar",
            )
        )
        return issues

    for model in published.get("models", []):
        name = model["modelo"]
        actual = recomputed.get(name)
        if actual is None:
            issues.append(
                IntegrityIssue("modelo_sin_predicciones", f"{name} no tiene predicciones guardadas")
            )
            continue
        for metric, value in actual.items():
            claimed = model.get(metric)
            if claimed is None:
                continue
            if abs(float(claimed) - value) > RECOMPUTE_TOLERANCE:
                issues.append(
                    IntegrityIssue(
                        "metrica_alterada",
                        f"{name}.{metric}: publicado {float(claimed):.6f}, recomputado {value:.6f}",
                    )
                )
    return issues
