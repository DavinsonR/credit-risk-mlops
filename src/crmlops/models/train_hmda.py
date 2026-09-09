"""Modelo B: predicción de denegación sobre HMDA, con auditoría de equidad.

La pregunta NO es "¿el modelo es justo?". Es más precisa y más difícil:

    ¿cuánta disparidad AGREGA el modelo sobre la que ya existe en los datos?

Un modelo entrenado sobre decisiones históricas puede reproducir una desigualdad
preexistente sin haberla creado. Medir la línea base primero
(`crmlops.fairness.observed`) y el modelo después es lo que permite separar
ambas cosas. Sin ese orden, cualquier brecha se le atribuye al modelo.

El modelo NUNCA ve raza, etnia, sexo ni edad. Esas columnas viven en el panel
solo para calcular las métricas de equidad.
"""

from __future__ import annotations

import json
import sys
import time

import pandas as pd

from crmlops.config import load_config, resolve_path
from crmlops.evaluation.metrics import calibration, discrimination, stability
from crmlops.fairness.metrics import FOUR_FIFTHS, evaluate, threshold_for_approval_rate
from crmlops.models.calibration import fit_calibrator
from crmlops.models.gbm import GBMChallenger
from crmlops.sources.hmda_loader import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    PROTECTED,
    TARGET,
    load_splits,
)

# Tasa de aprobación a la que se compara la equidad. Fijarla iguala el "cuán
# estricto es el modelo" entre escenarios: sin eso se confunde un modelo injusto
# con uno simplemente más duro.
APPROVAL_RATE = 0.75
CALIBRATOR = "intercept"


def _fairness_block(report, etiqueta: str) -> None:
    print(f"\n--- {etiqueta} ---")
    if not report.groups:
        print("  sin grupos evaluables")
        return
    print(f"  {'grupo':44s} {'n':>10} {'aprobacion':>11} {'denegacion real':>16}")
    for g in report.groups:
        print(f"  {g.group[:44]:44s} {g.n:>10,} {g.selection_rate:>10.2%} {g.positive_rate:>15.2%}")
    estado = "PASA" if report.passes_four_fifths else "NO PASA"
    print(
        f"  -> disparate impact ratio {report.disparate_impact_ratio:.3f} ({estado} {FOUR_FIFTHS})"
        f"   | peor grupo: {report.worst_group}"
    )
    if report.equalized_odds_gap is not None:
        print(f"  -> brecha de equalized odds: {report.equalized_odds_gap:.3f}")
    for n in report.notes:
        print(f"     nota: {n}")


def main() -> int:
    cfg = load_config()
    seed = cfg["project"]["random_seed"]

    print("=" * 96)
    print("MODELO B - denegación de hipoteca (HMDA), con auditoría de equidad")
    print("=" * 96)

    t0 = time.perf_counter()
    sp = load_splits(seed=seed)
    tr, va, te = sp["train"], sp["valid"], sp["test"]
    print(f"\nCargado en {time.perf_counter() - t0:.1f}s")
    for name, part in sp.items():
        anios = f"{int(part['activity_year'].min())}-{int(part['activity_year'].max())}"
        print(f"  {name:6s} FY{anios}  n={len(part):>9,}  denegacion={part[TARGET].mean():.2%}")

    # --- guarda dura: ninguna clase protegida puede entrar al modelo ---
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    leaked = sorted(set(features) & set(PROTECTED))
    if leaked:
        raise AssertionError(f"FUGA: clase protegida entre las features: {leaked}")
    print(f"\nFeatures: {len(features)}  |  protegidas retenidas solo para medir: {PROTECTED}")

    print("\nEntrenando LightGBM...", flush=True)
    t0 = time.perf_counter()
    model = GBMChallenger(NUMERIC_FEATURES, CATEGORICAL_FEATURES, random_state=seed)
    model.fit(tr, tr[TARGET], va, va[TARGET])
    print(f"  {time.perf_counter() - t0:.1f}s, mejor iteracion {model.best_iteration_}")

    cal = fit_calibrator(CALIBRATOR, va[TARGET].to_numpy(), model.predict_proba(va))
    p_test = cal.transform(model.predict_proba(te))
    y_test = te[TARGET].to_numpy()

    d, c = discrimination(y_test, p_test), calibration(y_test, p_test)
    st = stability(model.predict_proba(tr), model.predict_proba(te))
    print("\n" + "=" * 96)
    print("DESEMPENO (test out-of-time)")
    print("=" * 96)
    print(f"  AUC {d.auc:.4f}  Gini {d.gini:.4f}  KS {d.ks:.4f}")
    print(f"  Brier {c.brier:.4f}  ECE {c.ece:.4f}  ratio calibracion {c.calibration_ratio:.4f}")
    print(f"  PSI total {st.psi_total:.4f} | de forma {st.psi_shape:.4f} -> {st.interpretation}")

    print("\n" + "=" * 96)
    print(f"EQUIDAD DEL MODELO a tasa de aprobacion fija del {APPROVAL_RATE:.0%}")
    print("=" * 96)
    thr = threshold_for_approval_rate(p_test, APPROVAL_RATE)
    print(f"  umbral de score: {thr:.4f}")

    reports = {}
    for col, etiqueta in (("race", "RAZA"), ("ethnicity", "ETNIA"), ("sex", "SEXO")):
        rep = evaluate(y_test, p_test, te[col], threshold=thr)
        reports[col] = rep
        _fairness_block(rep, etiqueta)

    # --- lo que de verdad importa: cuanta disparidad AGREGA el modelo ---
    print("\n" + "=" * 96)
    print("DISPARIDAD OBSERVADA vs DISPARIDAD DEL MODELO")
    print("=" * 96)
    filas = []
    for col, etiqueta in (("race", "RAZA"), ("ethnicity", "ETNIA"), ("sex", "SEXO")):
        rep = reports[col]
        if not rep.groups:
            continue
        # Linea base: lo que hicieron los prestamistas, en la MISMA poblacion.
        base = te.groupby(col, observed=True)[TARGET].mean()
        base = base[[g.group for g in rep.groups]]
        aprob_base = 1 - base
        dir_observado = float(aprob_base.min() / aprob_base.max())
        filas.append(
            {
                "dimension": etiqueta,
                "dir_observado": dir_observado,
                "dir_modelo": rep.disparate_impact_ratio,
                "delta": rep.disparate_impact_ratio - dir_observado,
            }
        )
    tabla = pd.DataFrame(filas)
    print(tabla.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print("\n  delta > 0: el modelo es MENOS dispar que las decisiones historicas")
    print("  delta < 0: el modelo AMPLIFICA la disparidad existente")

    out = resolve_path("exports")
    for col, rep in reports.items():
        rep.to_frame().to_csv(out / f"hmda_fairness_{col}.csv", index=False)
    tabla.to_csv(out / "hmda_fairness_delta.csv", index=False)

    peor = min(reports.values(), key=lambda r: r.disparate_impact_ratio)
    metrics = {
        "model": "hmda_lightgbm",
        "seed": seed,
        "approval_rate": APPROVAL_RATE,
        "n_test": len(te),
        "auc_test": d.auc,
        "gini_test": d.gini,
        "ks_test": d.ks,
        "brier_test": c.brier,
        "ece_test": c.ece,
        "psi": st.psi_total,
        "psi_shape": st.psi_shape,
        "disparate_impact_ratio": float(peor.disparate_impact_ratio),
        "worst_dimension_group": peor.worst_group,
        "fairness_delta": tabla.set_index("dimension")["delta"].to_dict(),
    }
    (out / "hmda_metrics.json").write_text(
        json.dumps(metrics, indent=2, default=float) + "\n", encoding="utf-8"
    )

    print("\n" + "=" * 96)
    estado = "PASA" if peor.disparate_impact_ratio >= FOUR_FIFTHS else "NO PASA"
    print(f"GATE DE FAIRNESS: DIR minimo {peor.disparate_impact_ratio:.3f} -> {estado}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
