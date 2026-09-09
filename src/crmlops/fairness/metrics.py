"""Metricas de equidad para decisiones de credito.

No hay una definicion unica de "justo", y las principales son matematicamente
incompatibles entre si salvo en casos degenerados (Kleinberg, Mullainathan y
Raghavan, 2016). Por eso aqui se calculan varias y se reportan juntas: elegir una
sola y llamarla "la" metrica de equidad esconde la decision, no la resuelve.

Las tres que importan para credito:

  - *Disparate impact ratio* -- razon de tasas de seleccion entre el grupo con
    menor tasa y el de referencia. Umbral 0.80 por la regla de los 4/5 del EEOC.
    Es la unica con respaldo legal explicito.
  - *Equalized odds* -- diferencia en tasa de verdaderos positivos y de falsos
    positivos entre grupos. Pregunta si el modelo se equivoca IGUAL con todos.
  - *Calibracion por grupo* -- si el modelo dice 10%, ¿falla el 10% en cada
    grupo? Un modelo puede estar bien calibrado y aun asi violar equalized odds.

DISTINCION CRITICA. Estas metricas necesitan los atributos protegidos para
CALCULARSE, y el modelo jamas debe recibirlos como features. Mantener ambas cosas
a la vez es todo el trabajo de equidad: sin los atributos en el panel no se puede
medir discriminacion; con ellos en el modelo se discrimina.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Regla de los 4/5: Uniform Guidelines on Employee Selection Procedures,
# 29 CFR 1607.4(D). Es un umbral legal, no una convencion tecnica.
FOUR_FIFTHS = 0.80


@dataclass
class GroupOutcome:
    group: str
    n: int
    selection_rate: float  # tasa de resultado favorable (aprobacion)
    positive_rate: float  # tasa base del evento adverso en el grupo
    mean_score: float
    tpr: float | None = None  # sensibilidad
    fpr: float | None = None
    calibration_ratio: float | None = None


@dataclass
class FairnessReport:
    reference_group: str
    groups: list[GroupOutcome]
    disparate_impact_ratio: float
    worst_group: str
    equalized_odds_gap: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def passes_four_fifths(self) -> bool:
        return self.disparate_impact_ratio >= FOUR_FIFTHS

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([g.__dict__ for g in self.groups])


def _rates(y: np.ndarray, decision: np.ndarray, score: np.ndarray) -> dict[str, float]:
    """Tasas de un grupo. `decision`=1 significa resultado FAVORABLE (aprobado)."""
    out = {
        "selection_rate": float(np.mean(decision)),
        "positive_rate": float(np.mean(y)),
        "mean_score": float(np.mean(score)),
    }
    # y=1 es el evento adverso (denegacion real / incumplimiento).
    pos, neg = y == 1, y == 0
    out["tpr"] = float(np.mean(decision[pos] == 0)) if pos.any() else float("nan")
    out["fpr"] = float(np.mean(decision[neg] == 0)) if neg.any() else float("nan")
    obs = float(np.mean(y))
    out["calibration_ratio"] = float(np.mean(score)) / obs if obs else float("nan")
    return out


def evaluate(
    y_true: np.ndarray,
    scores: np.ndarray,
    groups: pd.Series,
    *,
    threshold: float,
    min_group_size: int = 500,
    exclude_groups: tuple[str, ...] = ("Race Not Available", "Joint", "Free Form Text Only"),
) -> FairnessReport:
    """Compara resultados entre grupos protegidos a un umbral de decision dado.

    `exclude_groups` deja fuera categorias que no son grupos demograficos
    coherentes: en HMDA, "Race Not Available" agrupa a quienes no declararon y
    "Joint" a solicitudes con co-solicitante de otra raza. Incluirlas como si
    fueran grupos produce comparaciones sin sentido; el reporte deja constancia
    de cuales se omitieron y por que.
    """
    y = np.asarray(y_true)
    s = np.asarray(scores, dtype=float)
    decision = (s < threshold).astype(int)  # aprobar si el riesgo es bajo
    g = pd.Series(groups).astype("string").fillna("<sin dato>").to_numpy()

    notes: list[str] = []
    outcomes: list[GroupOutcome] = []
    for name in sorted(pd.unique(g)):
        mask = g == name
        n = int(mask.sum())
        if name in exclude_groups:
            notes.append(f"excluido '{name}' (n={n:,}): no es un grupo demografico coherente")
            continue
        if n < min_group_size:
            notes.append(f"excluido '{name}' (n={n:,}): por debajo de {min_group_size}")
            continue
        outcomes.append(GroupOutcome(group=name, n=n, **_rates(y[mask], decision[mask], s[mask])))

    if not outcomes:
        return FairnessReport("n/a", [], float("nan"), "n/a", notes=notes)

    # Referencia: el grupo con MAYOR tasa de aprobacion, como en un examen de
    # fair lending -- la pregunta regulatoria es cuanto peor le va al resto.
    reference = max(outcomes, key=lambda o: o.selection_rate)
    worst = min(outcomes, key=lambda o: o.selection_rate)
    dir_ratio = (
        worst.selection_rate / reference.selection_rate
        if reference.selection_rate
        else float("nan")
    )

    valid_tpr = [o.tpr for o in outcomes if o.tpr == o.tpr]
    valid_fpr = [o.fpr for o in outcomes if o.fpr == o.fpr]
    eo_gap = (
        max(max(valid_tpr) - min(valid_tpr), max(valid_fpr) - min(valid_fpr))
        if valid_tpr and valid_fpr
        else None
    )

    return FairnessReport(
        reference_group=reference.group,
        groups=sorted(outcomes, key=lambda o: -o.selection_rate),
        disparate_impact_ratio=dir_ratio,
        worst_group=worst.group,
        equalized_odds_gap=eo_gap,
        notes=notes,
    )


def threshold_for_approval_rate(scores: np.ndarray, rate: float) -> float:
    """Umbral que aprueba exactamente `rate` de las solicitudes.

    Comparar equidad a igual tasa de aprobacion --y no a un umbral fijo-- evita
    confundir "el modelo es injusto" con "el modelo es mas estricto".
    """
    return float(np.quantile(np.asarray(scores, dtype=float), rate))
