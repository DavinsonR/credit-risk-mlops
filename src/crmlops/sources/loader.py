"""Carga del panel SBA 7(a) listo para modelar.

IMPORTANTE: TermInMonths NO se selecciona. Esta contaminado -- el campo se
sobrescribe cuando el prestamo se liquida, asi que filtra el resultado.
Ver docs/adr/0002-terminmonths-es-fuga.md.

Aplica las reglas de exclusion declaradas en config.yaml y deriva las features
de originacion. Toda la logica pesada corre en DuckDB sobre los CSV crudos.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from crmlops.config import load_config, repo_root

RAW_GLOB = "data/raw/FOIA_7a_FY*.csv"


def _sql_list(values: list[str]) -> str:
    escaped = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"({escaped})"


def build_query(cfg: dict | None = None, source_glob: str | None = None) -> str:
    """Construye la query del panel. `source_glob` permite apuntar a un fixture en CI."""
    cfg = cfg or load_config()
    exc = cfg["exclusions"]
    tgt = cfg["target"]
    raw = source_glob or (repo_root() / RAW_GLOB).as_posix()

    reader = (
        f"read_csv('{raw}', union_by_name=true, ignore_errors=true, "
        "sample_size=200000, all_varchar=true)"
    )

    conds = [f"trim(LoanStatus) in {_sql_list(exc['resolved_statuses'])}"]
    if exc.get("require_positive_amount"):
        conds.append("try_cast(GrossApproval as double) > 0")
    if exc.get("require_positive_term"):
        conds.append("try_cast(TermInMonths as double) > 0")
    if exc.get("drop_ppp"):
        conds.append(f"trim(Program) not in {_sql_list(exc['ppp_program_values'])}")

    where = "\n      and ".join(conds)
    pos = tgt["pd_positive_value"]

    return f"""
    select
        -- target
        case when trim(LoanStatus) = '{pos}' then 1 else 0 end            as is_chargeoff,
        try_cast(GrossChargeOffAmount as double)                          as chargeoff_amount,
        -- eje temporal (para el split, NO como feature)
        try_cast(ApprovalFY as integer)                                   as approval_fy,
        -- numericas de originacion
        try_cast(GrossApproval as double)                                 as gross_approval,
        try_cast(SBAGuaranteedApproval as double)                         as sba_guaranteed,
        try_cast(InitialInterestRate as double)                           as initial_rate,
        try_cast(JobsSupported as double)                                 as jobs_supported,
        -- derivadas
        try_cast(SBAGuaranteedApproval as double)
            / nullif(try_cast(GrossApproval as double), 0)                as guarantee_pct,
        ln(try_cast(GrossApproval as double))                             as log_gross_approval,
        substr(trim(NaicsCode), 1, 2)                                     as naics_sector,
        case when coalesce(trim(FranchiseCode), '') <> '' then 1 else 0 end as has_franchise,
        -- categoricas de originacion
        trim(BusinessType)                                                as business_type,
        trim(BusinessAge)                                                 as business_age,
        trim(RevolverStatus)                                              as revolver_status,
        trim(CollateralInd)                                               as collateral_ind,
        trim(FixedorVariableInterestInd)                                  as rate_type,
        trim(ProcessingMethod)                                            as processing_method,
        trim(BorrState)                                                   as borrower_state
    from {reader}
    where {where}
    """


def load_panel(cfg: dict | None = None, source_glob: str | None = None) -> pd.DataFrame:
    """Devuelve el panel filtrado y con features derivadas.

    `source_glob` permite cargar desde un fixture muestreado (CI) en vez de los
    CSV completos, que no se commitean.
    """
    cfg = cfg or load_config()
    df = duckdb.connect().execute(build_query(cfg, source_glob)).fetchdf()
    return df.dropna(subset=["approval_fy"])


def split_out_of_time(df: pd.DataFrame, cfg: dict | None = None) -> dict[str, pd.DataFrame]:
    """Split OUT-OF-TIME por anio fiscal de aprobacion. Nunca aleatorio."""
    cfg = cfg or load_config()
    out = {}
    for name in ("train", "valid", "test"):
        w = cfg["splits"][name]
        mask = df["approval_fy"].between(w["start"], w["end"])
        out[name] = df.loc[mask].copy()
    return out
