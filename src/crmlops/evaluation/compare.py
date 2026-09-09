"""Comparacion estadistica de modelos.

Una diferencia de AUC en el cuarto decimal no es una victoria. Antes de declarar
un ganador hay que preguntar si la diferencia sobrevive al ruido de muestreo.

Se usa bootstrap pareado: en cada replica se remuestrean los MISMOS indices para
ambos modelos. Es lo correcto porque las predicciones estan correlacionadas
(mismos prestamos, mismas features); un bootstrap independiente inflaria la
varianza y haria parecer indistinguibles modelos que si difieren.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.metrics import roc_auc_score


@dataclass
class AUCComparison:
    auc_a: float
    auc_b: float
    diff: float
    ci_low: float
    ci_high: float
    p_value: float
    n_boot: int

    @property
    def significant(self) -> bool:
        """El IC del 95% no cruza cero."""
        return self.ci_low > 0 or self.ci_high < 0

    def verdict(self, name_a: str, name_b: str) -> str:
        if not self.significant:
            return f"{name_a} y {name_b} son INDISTINGUIBLES (IC95 cruza cero)"
        winner = name_a if self.diff > 0 else name_b
        return f"{winner} gana de forma significativa (p={self.p_value:.4f})"


def bootstrap_auc_diff(
    y: np.ndarray,
    p_a: np.ndarray,
    p_b: np.ndarray,
    *,
    n_boot: int = 2000,
    seed: int = 42,
) -> AUCComparison:
    """IC bootstrap pareado para AUC(a) - AUC(b)."""
    y = np.asarray(y)
    rng = np.random.default_rng(seed)
    n = len(y)

    diffs = np.empty(n_boot)
    valid = 0
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        ys = y[idx]
        if ys.min() == ys.max():  # replica degenerada sin ambas clases
            continue
        diffs[valid] = roc_auc_score(ys, p_a[idx]) - roc_auc_score(ys, p_b[idx])
        valid += 1
    diffs = diffs[:valid]

    lo, hi = np.percentile(diffs, [2.5, 97.5])
    # p-valor de dos colas por proporcion de replicas del signo contrario
    p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return AUCComparison(
        auc_a=float(roc_auc_score(y, p_a)),
        auc_b=float(roc_auc_score(y, p_b)),
        diff=float(np.mean(diffs)),
        ci_low=float(lo),
        ci_high=float(hi),
        p_value=float(min(p, 1.0)),
        n_boot=valid,
    )
