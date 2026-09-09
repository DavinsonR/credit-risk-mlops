"""Auditoria de contaminacion post-originacion.

Generaliza el metodo que descubrio la fuga de TermInMonths (ADR 0002).

La idea: los prestamos CANCELADOS (CANCLD) nunca se desembolsaron, asi que sus
campos conservan el valor de originacion, sin oportunidad de que nadie los
actualice. Son un grupo de control natural.

Si la distribucion de un campo difiere mucho entre CANCLD y CHGOFF, hay dos
explicaciones posibles:
  (a) el campo predice genuinamente el default, o
  (b) el campo se sobrescribe durante la vida del prestamo.

Para separarlas comparamos tambien CANCLD contra P I F. Un campo legitimo separa
CHGOFF de PIF de forma gradual; un campo contaminado hace que CHGOFF sea un
outlier frente a CANCLD *y* PIF a la vez.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import pandas as pd

from crmlops.config import repo_root

RAW_GLOB = "data/raw/FOIA_7a_FY*.csv"
CONTROL = "CANCLD"  # nunca desembolsado -> valores de originacion intactos

# Campos candidatos a feature, con el modulo de "redondez" apropiado para cada uno.
# Un plazo pactado cae en multiplos de 6 meses; un monto en multiplos de 1000 USD.
# Usar el modulo equivocado hace inutil el test.
NUMERIC_CANDIDATES: dict[str, float] = {
    "TermInMonths": 6,
    "InitialInterestRate": 0.25,
    "GrossApproval": 1000,
    "SBAGuaranteedApproval": 1000,
    "JobsSupported": 1,
}


@dataclass
class Finding:
    column: str
    ratio_chgoff_vs_control: float  # mediana CHGOFF / mediana CANCLD
    roundness_control: float  # % no-redondo en CANCLD
    roundness_chgoff: float  # % no-redondo en CHGOFF
    roundness_gap: float  # puntos porcentuales
    verdict: str


def _reader() -> str:
    raw = (repo_root() / RAW_GLOB).as_posix()
    return (
        f"read_csv('{raw}', union_by_name=true, ignore_errors=true, "
        "sample_size=200000, all_varchar=true)"
    )


def _stats(col: str, modulus: float, fy_from: int, fy_to: int) -> pd.DataFrame:
    con = duckdb.connect()
    return (
        con.execute(f"""
        select trim(LoanStatus) estado, count(*) n,
               median(try_cast({col} as double)) mediana,
               round(100.0 * avg(case
                   when abs(try_cast({col} as double) - {modulus} *
                        round(try_cast({col} as double) / {modulus})) < 1e-6
                   then 0.0 else 1 end), 1) pct_no_redondo
        from {_reader()}
        where try_cast(ApprovalFY as int) between {fy_from} and {fy_to}
          and try_cast({col} as double) > 0
          and trim(LoanStatus) in ('CANCLD', 'P I F', 'CHGOFF')
        group by 1
    """)
        .fetchdf()
        .set_index("estado")
    )


def audit(
    candidates: dict[str, float] | None = None,
    fy_from: int = 2000,
    fy_to: int = 2019,
) -> pd.DataFrame:
    """Test CONJUNTO de contaminacion.

    Dos senales distintas, y solo su combinacion es concluyente:

    1. *Divergencia de mediana* -- el campo separa CHGOFF del control. Por si
       sola NO prueba contaminacion: que los prestamos chicos fallen mas es
       economia real, no un dato editado.

    2. *Divergencia de redondez* -- los CHGOFF tienen valores no pactados
       (no redondos) que el control no tiene. Eso SI evidencia edicion
       posterior, porque un valor contractual no deja de ser redondo solo.

    Contaminado = ambas. Predictivo legitimo = solo (1).
    """
    candidates = candidates or NUMERIC_CANDIDATES
    rows: list[Finding] = []

    for col, modulus in candidates.items():
        df = _stats(col, modulus, fy_from, fy_to)
        if CONTROL not in df.index or "CHGOFF" not in df.index:
            continue
        ctrl_med = df.loc[CONTROL, "mediana"]
        if not ctrl_med:
            continue

        ratio = df.loc["CHGOFF", "mediana"] / ctrl_med
        r_ctrl = df.loc[CONTROL, "pct_no_redondo"]
        r_chg = df.loc["CHGOFF", "pct_no_redondo"]
        gap = r_chg - r_ctrl

        median_diverge = abs(ratio - 1.0) > 0.30
        edited = gap > 25.0  # puntos porcentuales de exceso de valores no pactados

        if edited:
            verdict = "CONTAMINADO"
        elif median_diverge:
            verdict = "predictivo"
        else:
            verdict = "ok"

        rows.append(Finding(col, ratio, r_ctrl, r_chg, gap, verdict))

    return pd.DataFrame([r.__dict__ for r in rows])


def main() -> None:
    print("=" * 78)
    print("AUDITORIA DE CONTAMINACION POST-ORIGINACION")
    print("Control: CANCLD (nunca desembolsado -> valores de originacion intactos)")
    print("=" * 78)
    print()

    res = audit()
    print(res.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    bad = res.loc[res.verdict == "CONTAMINADO", "column"].tolist()
    pred = res.loc[res.verdict == "predictivo", "column"].tolist()

    print()
    print("=" * 78)
    if bad:
        print(f"CONTAMINADOS (excluir como feature): {', '.join(bad)}")
    else:
        print("Ningun campo contaminado.")
    if pred:
        print(f"Predictivos legitimos (mediana diverge, valores NO editados): {', '.join(pred)}")
    print("Metodo: docs/adr/0002-terminmonths-es-fuga.md")
    print("=" * 78)


if __name__ == "__main__":
    main()
