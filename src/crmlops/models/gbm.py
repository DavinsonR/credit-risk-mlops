"""Retador 1: LightGBM.

Es el retador obvio en datos tabulares. Su trabajo aqui es batir al scorecard;
si le gana por poco, el scorecard sigue siendo la eleccion correcta por
interpretabilidad, estabilidad y aceptacion regulatoria.

Los hiperparametros estan deliberadamente regularizados: con 217k filas de train
y una tasa base del 6.8%, un GBM sin frenos memoriza combinaciones de estado y
sector que no generalizan a la cosecha siguiente.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd


class GBMChallenger:
    def __init__(
        self,
        numeric: list[str],
        categorical: list[str],
        *,
        random_state: int = 42,
        **overrides,
    ) -> None:
        self.numeric = numeric
        self.categorical = categorical
        self.features = numeric + categorical
        params = {
            "n_estimators": 2000,
            "learning_rate": 0.03,
            "num_leaves": 31,
            "min_child_samples": 300,  # frena hojas que memorizan nichos
            "subsample": 0.8,
            "subsample_freq": 1,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.5,
            "reg_lambda": 5.0,
            "random_state": random_state,
            "n_jobs": -1,
            "verbose": -1,
        }
        params.update(overrides)
        self.model = lgb.LGBMClassifier(**params)
        self.best_iteration_: int | None = None

    def _prep(self, X: pd.DataFrame) -> pd.DataFrame:
        out = X[self.features].copy()
        for c in self.categorical:
            out[c] = out[c].astype("category")
        return out

    def fit(self, X: pd.DataFrame, y: pd.Series, X_valid: pd.DataFrame, y_valid: pd.Series):
        """Early stopping sobre VALIDACION, que es la cosecha siguiente."""
        self.cat_dtypes_ = {c: self._prep(X)[c].dtype for c in self.categorical}
        # eval_X/eval_y y no eval_set: LightGBM 4.7 deprecó el segundo y avisaba en
        # cada entrenamiento. Es un conjunto de validación, no una lista, así que la
        # forma nueva dice mejor lo que pasa. Verificado con `reproduce`: las
        # métricas publicadas no se mueven.
        self.model.fit(
            self._prep(X),
            y,
            eval_X=self._align(X_valid),
            eval_y=y_valid,
            eval_metric="auc",
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )
        self.best_iteration_ = self.model.best_iteration_
        return self

    def _align(self, X: pd.DataFrame) -> pd.DataFrame:
        """Aplica las MISMAS categorias de train: una categoria vista solo en
        test debe caer a NaN, no crear un nivel nuevo."""
        out = X[self.features].copy()
        for c in self.categorical:
            out[c] = out[c].astype(self.cat_dtypes_[c])
        return out

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self._align(X))[:, 1]

    def importances(self) -> pd.Series:
        return pd.Series(self.model.feature_importances_, index=self.features).sort_values(
            ascending=False
        )
