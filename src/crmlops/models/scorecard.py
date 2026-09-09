"""Baseline: scorecard WoE + regresion logistica.

Este es el estandar de la industria de credito, y aqui es el BASELINE que los
retadores (GBM, red neuronal) tienen que batir. No esta aqui como relleno:

  - Es interpretable por construccion -- cada punto del score se explica.
  - Los reguladores lo aceptan sin discusion.
  - Es estable: el binning absorbe outliers y deriva de distribucion.

Si un GBM le gana por poco, el scorecard sigue siendo la eleccion correcta.

CONTROL DE FUGA: el binning y los coeficientes se ajustan SOLO con train. Por eso
esta logica vive en Python y no en dbt -- una transformacion fit-on-train dentro
de un modelo dbt filtraria informacion de validacion y test.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from optbinning import BinningProcess, Scorecard
from sklearn.linear_model import LogisticRegression

# Convencion de scorecard: `pdo` puntos duplican las odds a partir de
# `score_points` en `odds`. Son los valores clasicos de la industria.
SCALING = {"method": "pdo_odds", "method_data": [20, 600, 50]}


@dataclass
class ScorecardArtifacts:
    """Todo lo que hace falta para explicar y auditar el modelo."""

    binning_table: pd.DataFrame  # IV por variable
    points_table: pd.DataFrame  # puntos por bin
    selected_features: list[str]


class WoEScorecard:
    """Scorecard WoE + logistica, con seleccion de variables por Information Value."""

    def __init__(
        self,
        numeric: list[str],
        categorical: list[str],
        *,
        min_iv: float = 0.02,
        max_iv: float = 0.75,
        random_state: int = 42,
    ) -> None:
        self.numeric = numeric
        self.categorical = categorical
        self.features = numeric + categorical
        # min_iv descarta variables sin poder; max_iv es una GUARDA ANTI-FUGA:
        # un IV por encima de ~0.75 en credito casi siempre significa que la
        # variable conoce el resultado. Ver ADR 0002.
        self.min_iv = min_iv
        self.max_iv = max_iv
        self.random_state = random_state
        self.model_: Scorecard | None = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> WoEScorecard:
        binning = BinningProcess(
            variable_names=self.features,
            categorical_variables=self.categorical,
            selection_criteria={
                "iv": {"min": self.min_iv, "max": self.max_iv, "strategy": "highest", "top": 25}
            },
        )
        self.model_ = Scorecard(
            binning_process=binning,
            estimator=LogisticRegression(
                max_iter=2000, random_state=self.random_state, solver="lbfgs"
            ),
            scaling_method=SCALING["method"],
            scaling_method_params=dict(
                zip(["pdo", "odds", "scorecard_points"], SCALING["method_data"], strict=True)
            ),
            reverse_scorecard=True,  # mas puntos = menor riesgo, como espera el negocio
        )
        self.model_.fit(X[self.features], y)
        return self

    def _check(self) -> Scorecard:
        if self.model_ is None:
            raise RuntimeError("El scorecard no esta entrenado; llamar fit() primero.")
        return self.model_

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._check().predict_proba(X[self.features])[:, 1]

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Puntaje en la escala de puntos (mas alto = menor riesgo)."""
        return self._check().score(X[self.features])

    def artifacts(self) -> ScorecardArtifacts:
        m = self._check()
        table = m.table(style="detailed")
        iv = m.binning_process_.summary()[["name", "iv", "selected"]].sort_values(
            "iv", ascending=False
        )
        return ScorecardArtifacts(
            binning_table=iv,
            points_table=table,
            selected_features=iv.loc[iv["selected"], "name"].tolist(),
        )

    def high_iv_warnings(self) -> pd.DataFrame:
        """Variables con IV sospechosamente alto: candidatas a fuga."""
        iv = self._check().binning_process_.summary()
        return iv.loc[iv["iv"] > self.max_iv, ["name", "iv"]].sort_values("iv", ascending=False)

    def save(self, path: str | Path) -> None:
        self._check().save(str(path))
