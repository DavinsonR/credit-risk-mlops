"""Recalibracion de probabilidades.

Motivacion (Semana 2): el baseline sub-predice el riesgo en test -- 7.84%
predicho contra 9.60% observado -- porque esta calibrado al regimen de
entrenamiento (tasa base 6.75%) y el ciclo se movio.

Discriminacion y calibracion son propiedades separadas. El AUC solo mide orden;
puedes ordenar perfecto y aun asi equivocarte por un factor de 2 en el nivel. El
expected loss se calcula con la PROBABILIDAD, no con el orden, asi que para
decidir en dolares hace falta calibrar.

Regla de oro: la calibracion se ajusta sobre VALIDACION, nunca sobre train (el
modelo ya vio train y sus probabilidades ahi son optimistas) ni sobre test (seria
fuga directa).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


@dataclass
class InterceptShift:
    """Ajuste de un solo parametro: corrige el nivel, preserva el orden EXACTO.

    Es el metodo mas conservador y el que un validador acepta sin discusion:
    al ser monotono no puede cambiar ningun ranking, asi que el AUC queda
    identico por construccion. Solo mueve el intercepto en escala logit para que
    la media predicha coincida con la tasa base observada.
    """

    shift: float = 0.0

    def fit(self, y: np.ndarray, p: np.ndarray) -> InterceptShift:
        target = float(np.mean(y))
        lo, hi = -10.0, 10.0
        for _ in range(60):  # biseccion: monotona, converge siempre
            mid = (lo + hi) / 2
            if float(np.mean(1 / (1 + np.exp(-(_logit(p) + mid))))) < target:
                lo = mid
            else:
                hi = mid
        self.shift = (lo + hi) / 2
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-(_logit(p) + self.shift)))


class PlattScaling:
    """Regresion logistica sobre el logit del score. Dos parametros."""

    def __init__(self) -> None:
        self.lr = LogisticRegression(solver="lbfgs")

    def fit(self, y: np.ndarray, p: np.ndarray) -> PlattScaling:
        self.lr.fit(_logit(p).reshape(-1, 1), y)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return self.lr.predict_proba(_logit(p).reshape(-1, 1))[:, 1]


class IsotonicCalibration:
    """No parametrica y monotona. Flexible, pero se sobreajusta con pocos datos."""

    def __init__(self) -> None:
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, y: np.ndarray, p: np.ndarray) -> IsotonicCalibration:
        self.iso.fit(p, y)
        return self

    def transform(self, p: np.ndarray) -> np.ndarray:
        return self.iso.predict(p)


CALIBRATORS = {
    "intercept": InterceptShift,
    "platt": PlattScaling,
    "isotonic": IsotonicCalibration,
}


def fit_calibrator(name: str, y_valid: np.ndarray, p_valid: np.ndarray):
    """Ajusta un calibrador sobre VALIDACION. Nunca sobre train ni test."""
    if name not in CALIBRATORS:
        raise ValueError(f"calibrador desconocido: {name!r}; opciones {list(CALIBRATORS)}")
    return CALIBRATORS[name]().fit(np.asarray(y_valid), np.asarray(p_valid))
