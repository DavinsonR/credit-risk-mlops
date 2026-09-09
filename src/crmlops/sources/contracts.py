"""Contratos de datos del panel SBA.

Un contrato no es un test de calidad de datos: es una afirmacion de que el panel
que sale del loader cumple lo que el resto del pipeline asume. Si se rompe, el
error aparece aqui y no cinco pasos despues como un modelo raro.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.typing import Series


class PanelSBA(pa.DataFrameModel):
    """Panel de modelado listo para features."""

    # --- targets ---
    is_chargeoff: Series[int] = pa.Field(isin=[0, 1])
    chargeoff_amount: Series[float] = pa.Field(ge=0, nullable=True)

    # --- eje temporal del split (nunca feature) ---
    approval_fy: Series[int] = pa.Field(ge=1991, le=2100)

    # --- numericas de originacion ---
    gross_approval: Series[float] = pa.Field(gt=0)
    sba_guaranteed: Series[float] = pa.Field(ge=0, nullable=True)
    initial_rate: Series[float] = pa.Field(ge=0, le=50, nullable=True)
    jobs_supported: Series[float] = pa.Field(ge=0, nullable=True)
    guarantee_pct: Series[float] = pa.Field(ge=0, le=1.5, nullable=True)
    log_gross_approval: Series[float] = pa.Field(nullable=True)

    # --- categoricas ---
    naics_sector: Series[str] = pa.Field(nullable=True)
    has_franchise: Series[int] = pa.Field(isin=[0, 1])
    business_type: Series[str] = pa.Field(nullable=True)
    business_age: Series[str] = pa.Field(nullable=True)
    revolver_status: Series[str] = pa.Field(nullable=True)
    collateral_ind: Series[str] = pa.Field(nullable=True)
    rate_type: Series[str] = pa.Field(nullable=True)
    processing_method: Series[str] = pa.Field(nullable=True)
    borrower_state: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = True  # ninguna columna extra: asi term_months no puede colarse
        coerce = True

    @pa.dataframe_check(name="tasa_base_plausible")
    def tasa_base_en_rango(cls, df: pd.DataFrame) -> bool:
        """La tasa de charge-off historica del 7(a) vive entre 5% y 35%.

        Fuera de ese rango casi siempre significa que el filtro de estados
        resueltos se rompio (p.ej. entraron CANCLD o COMMIT).
        """
        return 0.05 <= df["is_chargeoff"].mean() <= 0.35

    @pa.dataframe_check(name="sin_columna_contaminada")
    def sin_term_months(cls, df: pd.DataFrame) -> bool:
        """term_months esta contaminado (ADR 0002) y no puede estar en el panel."""
        return "term_months" not in df.columns


def validate_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Valida el panel y devuelve el DataFrame. Lanza SchemaError si falla."""
    return PanelSBA.validate(df, lazy=True)
