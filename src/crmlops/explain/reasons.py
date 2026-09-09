"""Razones principales de una decisión, con SHAP.

Bajo ECOA / Regulation B (12 CFR 1002.9), denegar crédito **obliga legalmente** a
comunicar las razones principales específicas. No es una funcionalidad opcional
del producto: es un requisito, y una razón vaga ("no cumple nuestros criterios")
no satisface la norma.

POR QUE SHAP Y NO IMPORTANCIA DE VARIABLES. La importancia global dice qué mueve
al modelo *en promedio*; el aviso tiene que decir qué movió **esta** solicitud.
Un solicitante con DTI excelente y sector riesgoso recibe un aviso distinto a uno
con el patrón inverso, aunque el modelo sea el mismo.

DIRECCIÓN, NO SOLO MAGNITUD. Solo entran los factores que EMPUJARON HACIA LA
DENEGACIÓN (SHAP positivo sobre la probabilidad de incumplimiento). Listar un
factor favorable como "razón del rechazo" sería incorrecto y, en un aviso legal,
engañoso.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Traducción de nombre técnico a lenguaje que un solicitante entiende. El aviso
# no puede decir `log_gross_approval`.
FEATURE_LABELS: dict[str, tuple[str, str]] = {
    "gross_approval": ("el monto solicitado", "the requested loan amount"),
    "log_gross_approval": ("el monto solicitado", "the requested loan amount"),
    "sba_guaranteed": ("la porción garantizada", "the guaranteed portion"),
    "guarantee_pct": (
        "el porcentaje de garantía del préstamo",
        "the loan guarantee percentage",
    ),
    "initial_rate": ("la tasa de interés inicial", "the initial interest rate"),
    "jobs_supported": ("el número de empleos sostenidos", "the number of jobs supported"),
    "naics_sector": ("el sector de actividad del negocio", "the business industry sector"),
    "business_type": ("la forma jurídica del negocio", "the business legal structure"),
    "business_age": ("la antigüedad del negocio", "the age of the business"),
    "revolver_status": ("el tipo de línea de crédito", "the credit line type"),
    "collateral_ind": ("la garantía colateral aportada", "the collateral provided"),
    "rate_type": ("el tipo de tasa (fija o variable)", "the rate type (fixed or variable)"),
    "processing_method": ("el programa de originación", "the origination program"),
    "borrower_state": ("la ubicación del negocio", "the business location"),
    "has_franchise": ("la condición de franquicia", "the franchise status"),
}

# Reg B no fija un número, pero el Apéndice C del modelo de formulario lista
# hasta cuatro razones. Más de eso deja de ser informativo.
MAX_REASONS = 4


@dataclass
class Reason:
    feature: str
    label_es: str
    label_en: str
    shap_value: float
    feature_value: float | str
    rank: int

    @property
    def share(self) -> float:
        """Peso relativo entre las razones adversas seleccionadas."""
        return self._share

    def as_dict(self) -> dict:
        return {
            "feature": self.feature,
            "label_es": self.label_es,
            "label_en": self.label_en,
            "shap_value": round(self.shap_value, 6),
            "feature_value": self.feature_value,
            "rank": self.rank,
        }


class ReasonExtractor:
    """Extrae las razones adversas de una decisión concreta."""

    def __init__(self, model, feature_names: list[str]) -> None:
        import shap

        # TreeExplainer sobre un GBM es exacto y rapido: no aproxima por muestreo.
        self.explainer = shap.TreeExplainer(model)
        self.feature_names = list(feature_names)

    def explain(self, X: np.ndarray | pd.DataFrame, max_reasons: int = MAX_REASONS) -> list[Reason]:
        values = self.explainer.shap_values(X)
        arr = np.asarray(values)
        # Segun la version, shap devuelve (n, f) o (n, f, clases).
        if arr.ndim == 3:
            arr = arr[:, :, -1]
        row = arr[0]

        raw = X.iloc[0] if isinstance(X, pd.DataFrame) else X[0]
        orden = np.argsort(-row)  # de mas adverso a mas favorable

        razones: list[Reason] = []
        for i in orden:
            if row[i] <= 0:
                break  # a partir de aqui los factores FAVORECEN al solicitante
            name = self.feature_names[i]
            es, en = FEATURE_LABELS.get(name, (name, name))
            valor = raw[i] if not isinstance(raw, pd.Series) else raw.iloc[i]
            razones.append(
                Reason(
                    feature=name,
                    label_es=es,
                    label_en=en,
                    shap_value=float(row[i]),
                    feature_value=float(valor)
                    if isinstance(valor, int | float | np.number)
                    else str(valor),
                    rank=len(razones) + 1,
                )
            )
            if len(razones) >= max_reasons:
                break

        total = sum(r.shap_value for r in razones) or 1.0
        for r in razones:
            r._share = r.shap_value / total
        return razones


def dedupe_labels(reasons: list[Reason]) -> list[Reason]:
    """Colapsa razones que comparten etiqueta.

    `gross_approval` y `log_gross_approval` son la misma variable en dos escalas,
    y el modelo reparte atribución entre ambas. Un aviso que diga dos veces "el
    monto solicitado" se lee como un error, y con razón: lo es.
    """
    vistas: dict[str, Reason] = {}
    for r in reasons:
        if r.label_es in vistas:
            vistas[r.label_es].shap_value += r.shap_value
        else:
            vistas[r.label_es] = r
    salida = sorted(vistas.values(), key=lambda r: -r.shap_value)
    for i, r in enumerate(salida, 1):
        r.rank = i
    return salida
