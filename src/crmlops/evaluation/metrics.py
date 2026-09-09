"""Metricas de evaluacion para modelos de riesgo crediticio.

Un modelo de credito no se juzga solo por ranking (AUC). Se necesita:
  - discriminacion: AUC, Gini, KS
  - calibracion:    Brier, ECE  -- sin probabilidades reales no hay expected loss
  - estabilidad:    PSI          -- el score no puede derivar entre cosechas
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve


@dataclass
class DiscriminationMetrics:
    auc: float
    gini: float
    ks: float


@dataclass
class CalibrationMetrics:
    brier: float
    ece: float
    observed_rate: float
    predicted_rate: float
    calibration_ratio: float  # predicho / observado; 1.0 es perfecto


def discrimination(y_true: np.ndarray, y_score: np.ndarray) -> DiscriminationMetrics:
    """AUC, Gini y KS.

    El KS (maxima separacion entre las acumuladas de buenos y malos) es la
    metrica tradicional de scorecards; se reporta junto al AUC porque los
    equipos de riesgo la piden por costumbre y porque es mas sensible al
    comportamiento en las colas.
    """
    auc = float(roc_auc_score(y_true, y_score))
    fpr, tpr, _ = roc_curve(y_true, y_score)
    return DiscriminationMetrics(auc=auc, gini=2 * auc - 1, ks=float(np.max(tpr - fpr)))


def calibration(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> CalibrationMetrics:
    """Brier y Expected Calibration Error sobre bins de igual frecuencia.

    Se usan bins de igual frecuencia (cuantiles) y no de igual ancho: con tasas
    base del 10-20% los bins de ancho fijo quedan casi vacios en la cola alta y
    el ECE se vuelve ruido.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)

    edges = np.unique(np.quantile(y_prob, np.linspace(0, 1, n_bins + 1)))
    idx = np.clip(np.digitize(y_prob, edges[1:-1], right=True), 0, len(edges) - 2)

    ece = 0.0
    for b in range(len(edges) - 1):
        m = idx == b
        if not m.any():
            continue
        ece += (m.mean()) * abs(y_true[m].mean() - y_prob[m].mean())

    obs, pred = float(y_true.mean()), float(y_prob.mean())
    return CalibrationMetrics(
        brier=float(brier_score_loss(y_true, y_prob)),
        ece=float(ece),
        observed_rate=obs,
        predicted_rate=pred,
        calibration_ratio=pred / obs if obs else float("nan"),
    )


def reliability_table(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Tabla de confiabilidad: predicho vs observado por decil de score."""
    df = pd.DataFrame({"y": np.asarray(y_true, dtype=float), "p": np.asarray(y_prob, dtype=float)})
    df["bin"] = pd.qcut(df["p"], q=n_bins, duplicates="drop", labels=False)
    out = df.groupby("bin", observed=True).agg(
        n=("y", "size"), predicho=("p", "mean"), observado=("y", "mean")
    )
    out["diferencia"] = out["predicho"] - out["observado"]
    return out.reset_index()


def psi(expected: np.ndarray, actual: np.ndarray, n_bins: int = 10) -> float:
    """Population Stability Index entre dos distribuciones de score.

    Convencion de la industria: <0.10 estable, 0.10-0.25 vigilar, >0.25 accion.
    Los bins se definen SOBRE `expected` (la referencia de entrenamiento) y se
    aplican a `actual`: definirlos sobre ambos escondería justamente la deriva
    que se quiere medir.
    """
    expected, actual = np.asarray(expected, dtype=float), np.asarray(actual, dtype=float)
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, n_bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf

    e = np.histogram(expected, bins=edges)[0] / len(expected)
    a = np.histogram(actual, bins=edges)[0] / len(actual)
    eps = 1e-6  # evita log(0) en bins vacios
    e, a = np.clip(e, eps, None), np.clip(a, eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


def summarize(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float]:
    """Bloque de metricas listo para loguear en MLflow."""
    return {**asdict(discrimination(y_true, y_prob)), **asdict(calibration(y_true, y_prob))}
