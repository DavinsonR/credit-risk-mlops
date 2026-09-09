"""Retador 2: red neuronal (PyTorch) con embeddings para categoricas.

Existe para responder una pregunta real, no para poner "PyTorch" en el README:
en datos tabulares, ¿le gana una red a un GBM bien regularizado? La literatura
dice que casi nunca, y reportar ese resultado honestamente demuestra mas criterio
que forzar una victoria.

Arquitectura: embedding por variable categorica (dim = min(50, (card+1)//2)),
concatenado con las numericas estandarizadas, hacia un MLP con dropout y
batchnorm. Es el equivalente practico de un FT-Transformer a esta escala, sin el
costo de atencion sobre 15 features.

CONTROL DE FUGA: el encoder de categorias y el escalador se ajustan SOLO con
train. Una categoria que aparece por primera vez en test cae al indice 0
(desconocido), que es como se comportaria en produccion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import roc_auc_score
from torch import nn

UNKNOWN = 0  # indice reservado para categorias no vistas en train


class _TabularNet(nn.Module):
    def __init__(self, cardinalities: list[int], n_numeric: int, hidden: tuple[int, ...]):
        super().__init__()
        dims = [(c, min(50, (c + 1) // 2)) for c in cardinalities]
        self.embeddings = nn.ModuleList([nn.Embedding(c, d) for c, d in dims])
        self.emb_drop = nn.Dropout(0.1)
        self.num_bn = nn.BatchNorm1d(n_numeric) if n_numeric else None

        layers: list[nn.Module] = []
        in_dim = sum(d for _, d in dims) + n_numeric
        for h in hidden:
            layers += [nn.Linear(in_dim, h), nn.BatchNorm1d(h), nn.ReLU(), nn.Dropout(0.3)]
            in_dim = h
        layers.append(nn.Linear(in_dim, 1))
        self.mlp = nn.Sequential(*layers)

    def forward(self, x_cat: torch.Tensor, x_num: torch.Tensor) -> torch.Tensor:
        parts = [emb(x_cat[:, i]) for i, emb in enumerate(self.embeddings)]
        x = self.emb_drop(torch.cat(parts, dim=1)) if parts else None
        if self.num_bn is not None:
            n = self.num_bn(x_num)
            x = torch.cat([x, n], dim=1) if x is not None else n
        return self.mlp(x).squeeze(1)


class NeuralChallenger:
    def __init__(
        self,
        numeric: list[str],
        categorical: list[str],
        *,
        hidden: tuple[int, ...] = (256, 128),
        epochs: int = 30,
        batch_size: int = 4096,
        lr: float = 1e-3,
        patience: int = 5,
        random_state: int = 42,
    ) -> None:
        self.numeric, self.categorical = numeric, categorical
        self.hidden, self.epochs, self.batch_size = hidden, epochs, batch_size
        self.lr, self.patience, self.random_state = lr, patience, random_state

    # ---- preprocesamiento (ajustado SOLO con train) ----
    def _fit_encoders(self, X: pd.DataFrame) -> None:
        self.maps_ = {}
        for c in self.categorical:
            vals = pd.Series(X[c]).astype("string").fillna("<NA>").unique()
            # indice 0 reservado para desconocido
            self.maps_[c] = {v: i + 1 for i, v in enumerate(sorted(vals))}
        num = X[self.numeric].astype(float)
        self.medians_ = num.median()
        self.mu_ = num.fillna(self.medians_).mean()
        self.sigma_ = num.fillna(self.medians_).std().replace(0, 1.0)

    def _encode(self, X: pd.DataFrame) -> tuple[torch.Tensor, torch.Tensor]:
        cat = (
            np.stack(
                [
                    pd.Series(X[c])
                    .astype("string")
                    .fillna("<NA>")
                    .map(self.maps_[c])
                    .fillna(UNKNOWN)
                    .to_numpy(dtype=np.int64)
                    for c in self.categorical
                ],
                axis=1,
            )
            if self.categorical
            else np.zeros((len(X), 0), dtype=np.int64)
        )
        num = (
            (X[self.numeric].astype(float).fillna(self.medians_) - self.mu_) / self.sigma_
        ).to_numpy(dtype=np.float32)
        return torch.from_numpy(cat), torch.from_numpy(num)

    def fit(self, X: pd.DataFrame, y: pd.Series, X_valid: pd.DataFrame, y_valid: pd.Series):
        # torch.manual_seed cubre la inicializacion de pesos y el shuffling
        # (usamos torch.randperm, no np.random), asi que basta con esta semilla.
        torch.manual_seed(self.random_state)

        self._fit_encoders(X)
        xc, xn = self._encode(X)
        yt = torch.tensor(np.asarray(y, dtype=np.float32))
        vc, vn = self._encode(X_valid)
        yv = np.asarray(y_valid)

        cards = [len(self.maps_[c]) + 1 for c in self.categorical]
        self.net_ = _TabularNet(cards, len(self.numeric), self.hidden)
        opt = torch.optim.AdamW(self.net_.parameters(), lr=self.lr, weight_decay=1e-4)
        # pos_weight compensa la tasa base baja sin remuestrear: remuestrear
        # distorsiona la calibracion, que es justo lo que necesitamos preservar.
        pos_weight = torch.tensor(float((1 - yt.mean()) / yt.mean()))
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

        best_auc, best_state, bad = -1.0, None, 0
        n = len(yt)
        epochs_run = 0
        for _epoch in range(self.epochs):
            epochs_run += 1
            self.net_.train()
            perm = torch.randperm(n)
            for i in range(0, n, self.batch_size):
                idx = perm[i : i + self.batch_size]
                if len(idx) < 2:
                    continue
                opt.zero_grad()
                loss_fn(self.net_(xc[idx], xn[idx]), yt[idx]).backward()
                opt.step()

            auc = roc_auc_score(yv, self._raw_predict(vc, vn))
            if auc > best_auc + 1e-5:
                best_auc, bad = auc, 0
                best_state = {k: v.clone() for k, v in self.net_.state_dict().items()}
            else:
                bad += 1
                if bad >= self.patience:
                    break

        if best_state is not None:
            self.net_.load_state_dict(best_state)
        self.best_valid_auc_ = best_auc
        self.epochs_run_ = epochs_run
        return self

    def _raw_predict(self, xc: torch.Tensor, xn: torch.Tensor) -> np.ndarray:
        self.net_.eval()
        with torch.no_grad():
            return torch.sigmoid(self.net_(xc, xn)).numpy()

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self._raw_predict(*self._encode(X))
