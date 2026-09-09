"""Auditoría de fuga por NULIDAD.

Complementa `contamination_audit`, que detecta campos cuyo *valor* se sobrescribe
tras conocerse el resultado. Este detecta el caso más sutil: campos cuyo valor es
legítimo, pero **el hecho de que falten** codifica el resultado.

Cómo aparece en HMDA. `loan_to_value_ratio` está nulo en el 6.0% de las
solicitudes aprobadas y en el 15.6% de las denegadas. La causa es operativa y
perfectamente lógica: **si una solicitud se rechaza temprano por DTI, nunca se
ordena la tasación**, así que no hay LTV. La ausencia del dato es consecuencia de
la decisión.

Un GBM trata los nulos como una rama más del árbol, así que aprende "LTV
ausente → denegado" sin que nadie lo escriba. La variable en sí es legítima -y de
hecho es la variable central de la suscripción hipotecaria-, de modo que
descartarla sería tirar señal real junto con la fuga.

LA PREGUNTA CORRECTA. ¿La señal está en el VALOR o en la AUSENCIA? Se responde con
cuatro variantes del mismo modelo:

  1. tal cual                    -- valor + ausencia
  2. imputado con la mediana     -- solo valor (la ausencia deja de distinguirse)
  3. sin la variable             -- ni valor ni ausencia
  4. solo indicador de ausencia  -- solo la fuga, aislada

La diferencia (1) - (2) es lo que aporta la ausencia. Si es grande, hay que
imputar; si es despreciable, la variable puede quedarse como está.
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass

import pandas as pd
from sklearn.metrics import roc_auc_score

from crmlops.config import resolve_path
from crmlops.models.gbm import GBMChallenger

# Muestra deliberadamente pequena. La pregunta -si la senal esta en el valor o en
# la ausencia- se responde igual con 1M de filas que con 4.3M: son diferencias de
# centesimas de AUC, no de milesimas. Entrenar cuatro modelos sobre el panel
# completo tardaba mas de una hora sin cambiar ninguna conclusion.
SAMPLE_PCT = {"train": 3, "valid": 8, "test": 8}


@dataclass
class MissingnessFinding:
    column: str
    null_rate_negative: float  # % nulo entre los casos favorables
    null_rate_positive: float  # % nulo entre los casos adversos
    gap_pp: float
    verdict: str


def nullity_gap(df: pd.DataFrame, target: str, columns: list[str]) -> pd.DataFrame:
    """Diferencia de nulidad entre clases. Primer filtro, barato."""
    rows = []
    for c in columns:
        neg = float(df.loc[df[target] == 0, c].isna().mean())
        pos = float(df.loc[df[target] == 1, c].isna().mean())
        gap = (pos - neg) * 100
        rows.append(
            MissingnessFinding(
                column=c,
                null_rate_negative=neg,
                null_rate_positive=pos,
                gap_pp=gap,
                # Umbral laxo: esto MARCA para investigar, no condena.
                verdict="revisar" if abs(gap) > 5 else "ok",
            ).__dict__
        )
    return pd.DataFrame(rows).sort_values("gap_pp", key=abs, ascending=False)


def _auc(tr, va, te, numeric, categorical, target) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = GBMChallenger(numeric, categorical, random_state=42)
        m.fit(tr, tr[target], va, va[target])
        return float(roc_auc_score(te[target], m.predict_proba(te)))


def decompose(
    splits: dict[str, pd.DataFrame],
    target: str,
    numeric: list[str],
    categorical: list[str],
    suspects: list[str],
) -> pd.DataFrame:
    """Separa cuanto del AUC viene del valor y cuanto de la ausencia."""
    tr, va, te = splits["train"], splits["valid"], splits["test"]
    sin_sospechosas = [c for c in numeric if c not in suspects]
    mediana = tr[suspects].median()

    def imputar(d: pd.DataFrame) -> pd.DataFrame:
        d = d.copy()
        d[suspects] = d[suspects].fillna(mediana)
        return d

    def indicadores(d: pd.DataFrame) -> pd.DataFrame:
        d = d.copy()
        for c in suspects:
            d[f"{c}_falta"] = d[c].isna().astype(int)
        return d

    ind_cols = [f"{c}_falta" for c in suspects]
    escenarios = [
        ("valor + ausencia", (tr, va, te), numeric),
        ("solo valor (imputado)", (imputar(tr), imputar(va), imputar(te)), numeric),
        ("ni valor ni ausencia", (tr, va, te), sin_sospechosas),
        (
            "solo ausencia",
            (indicadores(tr), indicadores(va), indicadores(te)),
            sin_sospechosas + ind_cols,
        ),
    ]

    filas = []
    for etiqueta, (a, b, c), nums in escenarios:
        filas.append({"escenario": etiqueta, "auc": _auc(a, b, c, nums, categorical, target)})
    return pd.DataFrame(filas)


def main() -> int:
    from crmlops.sources.hmda_loader import (
        CATEGORICAL_FEATURES,
        NUMERIC_FEATURES,
        TARGET,
        load_split,
    )

    print("=" * 84)
    print("AUDITORIA DE FUGA POR NULIDAD - HMDA")
    print("=" * 84)
    print("Pregunta: la senal esta en el VALOR de la variable, o en que FALTE?\n")

    splits = {
        name: load_split(name, pct=SAMPLE_PCT[name], seed=42) for name in ("train", "valid", "test")
    }
    print("Muestra: " + "  ".join(f"{k}={len(v):,}" for k, v in splits.items()))

    print("\n--- Diferencia de nulidad entre clases (test) ---")
    gaps = nullity_gap(splits["test"], TARGET, NUMERIC_FEATURES)
    print(gaps.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    suspects = gaps.loc[gaps.verdict == "revisar", "column"].tolist()
    if not suspects:
        print("\nNingun campo con nulidad diferencial relevante.")
        return 0

    print(f"\n--- Descomposicion para {', '.join(suspects)} ---")
    tabla = decompose(splits, TARGET, NUMERIC_FEATURES, CATEGORICAL_FEATURES, suspects)
    print(tabla.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    a = tabla.loc[tabla.escenario == "valor + ausencia", "auc"].iloc[0]
    b = tabla.loc[tabla.escenario == "solo valor (imputado)", "auc"].iloc[0]
    c = tabla.loc[tabla.escenario == "ni valor ni ausencia", "auc"].iloc[0]

    print("\n" + "=" * 84)
    print(f"  aporte de la AUSENCIA (fuga)   {a - b:+.4f}")
    print(f"  aporte del VALOR (legitimo)    {b - c:+.4f}")
    print("=" * 84)
    if abs(a - b) > 0.005:
        print("  RECOMENDACION: imputar. La ausencia aporta senal que no estara")
        print("  disponible al decidir, y la variable en si es legitima.")
    else:
        print("  RECOMENDACION: dejar como esta. La ausencia no aporta senal")
        print("  material; imputar solo agregaria un paso sin beneficio.")

    out = resolve_path("exports")
    gaps.to_csv(out / "hmda_nullity_gaps.csv", index=False)
    tabla.to_csv(out / "hmda_missingness_decomposition.csv", index=False)
    print(f"\nExportado a {out.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
