"""Especificacion de features: unica fuente de verdad.

Antes existian dos listas paralelas -- una en config.yaml (nombres fuente) y otra
hardcodeada en train.py (nombres de panel) -- y el fingerprint del gate hasheaba
la primera mientras el modelo usaba la segunda. Se podia quitar una variable del
modelo sin que el control lo notara (docs/AUDIT.md, defectos A2 y B1).

Ahora el codigo lee de config y punto. Si alguien cambia la lista, cambia el
fingerprint, y el gate exige reentrenar.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from crmlops.config import load_config


@dataclass(frozen=True)
class FeatureSpec:
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    forbidden_panel: frozenset[str]
    lineage: dict[str, str]

    @property
    def all(self) -> list[str]:
        return [*self.numeric, *self.categorical]

    def validate_against(self, df: pd.DataFrame) -> None:
        """Falla si el panel no trae lo declarado, o si trae algo prohibido."""
        missing = [c for c in self.all if c not in df.columns]
        if missing:
            raise KeyError(
                f"El panel no contiene features declaradas en config: {missing}. "
                "Revisar features.numeric / features.categorical."
            )
        leaked = sorted(set(self.all) & self.forbidden_panel)
        if leaked:
            raise AssertionError(
                f"FUGA: features prohibidas declaradas en config: {leaked}. "
                "Ver config.yaml features.forbidden_panel y docs/adr/0002."
            )

    def frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """Subconjunto de features con las categoricas tipadas."""
        out = df[self.all].copy()
        for c in self.categorical:
            out[c] = out[c].astype("category")
        return out


def load_spec(cfg: dict | None = None) -> FeatureSpec:
    cfg = cfg or load_config()
    f = cfg["features"]
    spec = FeatureSpec(
        numeric=tuple(f["numeric"]),
        categorical=tuple(f["categorical"]),
        forbidden_panel=frozenset(f["forbidden_panel"]),
        lineage=dict(f.get("lineage", {})),
    )
    # Chequeo de coherencia interna del propio config: declarar una feature que
    # tambien esta prohibida es una contradiccion que debe fallar al cargar.
    contradiction = sorted(set(spec.all) & spec.forbidden_panel)
    if contradiction:
        raise ValueError(
            f"config.yaml se contradice: {contradiction} esta en features y en "
            "forbidden_panel a la vez."
        )
    return spec
