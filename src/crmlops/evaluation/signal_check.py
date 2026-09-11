"""GATE DE VIABILIDAD — Semana 1.

Pregunta unica: existe poder discriminante en SBA 7(a) para predecir charge-off
usando SOLO informacion disponible al momento de aprobar?

El umbral (config.yaml: signal_gate.min_auc) se fija ANTES de ver el resultado.
Eso lo convierte en de-risking, no en p-hacking. Si no pasa, se pivotea el target
en la semana 1 en vez de descubrirlo en la semana 8.
"""

from __future__ import annotations

import sys

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import roc_auc_score

from crmlops.config import load_config
from crmlops.sources.loader import load_panel, split_out_of_time

TARGET = "is_chargeoff"
# Columnas que existen en el panel pero no son features
NON_FEATURES = {TARGET, "chargeoff_amount", "approval_fy"}

CATEGORICALS = [
    "naics_sector",
    "business_type",
    "business_age",
    "revolver_status",
    "collateral_ind",
    "rate_type",
    "processing_method",
    "borrower_state",
]


def feature_columns(df: pd.DataFrame, cfg: dict) -> list[str]:
    """Features = todo menos target, eje temporal y la lista prohibida.

    La lista prohibida se compara contra nombres de PANEL declarados
    explicitamente en config (features.forbidden_panel). No se derivan por
    normalizacion del nombre fuente: TermInMonths -> term_months no coincide,
    y un guard que falla en silencio es peor que no tenerlo.
    """
    forbidden = set(cfg["features"]["forbidden_panel"])
    cols = [c for c in df.columns if c not in NON_FEATURES]
    leaked = sorted(set(cols) & forbidden)
    if leaked:
        raise AssertionError(
            f"FUGA: columnas prohibidas en features: {leaked}. "
            "Ver config.yaml features.forbidden_panel y docs/adr/0002."
        )
    return cols


def prepare(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    X = df[cols].copy()
    for c in CATEGORICALS:
        if c in X.columns:
            X[c] = X[c].astype("category")
    return X


def main() -> int:
    cfg = load_config()
    gate = cfg["signal_gate"]

    print("=" * 68)
    print("SIGNAL GATE — SBA 7(a) charge-off")
    print("=" * 68)

    print("\nCargando panel...")
    df = load_panel(cfg)
    print(f"  filas resueltas       {len(df):,}")
    print(f"  tasa base charge-off  {df[TARGET].mean():.2%}")

    splits = split_out_of_time(df, cfg)
    print("\nSplit OUT-OF-TIME (por año fiscal de aprobación):")
    for name, part in splits.items():
        w = cfg["splits"][name]
        print(
            f"  {name:6s} FY{w['start']}-{w['end']}  "
            f"n={len(part):>9,}  tasa={part[TARGET].mean():.2%}"
        )

    cols = feature_columns(df, cfg)
    print(f"\nFeatures ({len(cols)}): {', '.join(cols)}")

    tr, va, te = splits["train"], splits["valid"], splits["test"]
    if min(len(tr), len(va), len(te)) == 0:
        print("\nERROR: algún split quedó vacío. Revisar config.splits.")
        return 1

    Xtr, Xva, Xte = (prepare(p, cols) for p in (tr, va, te))

    print("\nEntrenando LightGBM (configuración rápida, sin tuning)...")
    model = lgb.LGBMClassifier(
        n_estimators=400,
        learning_rate=0.05,
        num_leaves=63,
        min_child_samples=100,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=cfg["project"]["random_seed"],
        n_jobs=-1,
        verbose=-1,
    )
    model.fit(
        Xtr,
        tr[TARGET],
        eval_X=Xva,  # eval_set quedó deprecado en LightGBM 4.7
        eval_y=va[TARGET],
        eval_metric="auc",
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )

    auc = {
        "train": roc_auc_score(tr[TARGET], model.predict_proba(Xtr)[:, 1]),
        "valid": roc_auc_score(va[TARGET], model.predict_proba(Xva)[:, 1]),
        "test": roc_auc_score(te[TARGET], model.predict_proba(Xte)[:, 1]),
    }

    print("\nAUC:")
    for k, v in auc.items():
        print(f"  {k:6s} {v:.4f}")
    print(f"  degradacion train->test (out-of-time): {auc['train'] - auc['test']:+.4f}")

    imp = pd.Series(model.feature_importances_, index=cols).sort_values(ascending=False).head(10)
    print("\nTop 10 features por ganancia:")
    for name, val in imp.items():
        print(f"  {name:22s} {val:>8,}")

    passed = auc["test"] >= gate["min_auc"]
    print("\n" + "=" * 68)
    verdict = "PASA" if passed else "NO PASA"
    print(f"{verdict}: AUC test {auc['test']:.4f} vs umbral {gate['min_auc']:.2f}")
    if not passed:
        print(">> Pivotear el target antes de continuar (ver config.signal_gate).")
    print("=" * 68)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
