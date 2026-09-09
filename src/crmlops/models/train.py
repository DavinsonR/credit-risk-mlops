"""Arnes unificado: baseline vs retadores, con recalibracion.

Entrena scorecard (baseline), LightGBM y red neuronal sobre el MISMO split
out-of-time y los compara con las mismas metricas.

Sobre la eleccion del calibrador: se ajustan los tres sobre VALIDACION y se
reportan los tres sobre test, pero el de produccion se declara POR ADELANTADO
--el ajuste de intercepto-- porque es monotono y no puede alterar el ranking.
Elegir el calibrador mirando test seria seleccion sobre el conjunto de prueba,
que es fuga aunque no lo parezca.
"""

from __future__ import annotations

import json
import sys
import time

import mlflow
import numpy as np
import pandas as pd

from crmlops.config import load_config, repo_root, resolve_path
from crmlops.evaluation.metrics import calibration, discrimination, psi
from crmlops.models.calibration import CALIBRATORS, fit_calibrator
from crmlops.models.gbm import GBMChallenger
from crmlops.models.neural import NeuralChallenger
from crmlops.models.scorecard import WoEScorecard
from crmlops.sources.contracts import validate_panel
from crmlops.sources.loader import load_panel, split_out_of_time

TARGET = "is_chargeoff"
PRODUCTION_CALIBRATOR = "intercept"  # declarado ANTES de ver test

NUMERIC = [
    "gross_approval",
    "sba_guaranteed",
    "initial_rate",
    "jobs_supported",
    "guarantee_pct",
    "log_gross_approval",
]
CATEGORICAL = [
    "naics_sector",
    "business_type",
    "business_age",
    "revolver_status",
    "collateral_ind",
    "rate_type",
    "processing_method",
    "borrower_state",
    "has_franchise",
]


def build_models(seed: int) -> dict:
    return {
        "scorecard_woe": WoEScorecard(NUMERIC, CATEGORICAL, random_state=seed),
        "lightgbm": GBMChallenger(NUMERIC, CATEGORICAL, random_state=seed),
        "neural_mlp": NeuralChallenger(NUMERIC, CATEGORICAL, random_state=seed),
    }


def _fit(name, model, tr, va):
    """El scorecard no usa early stopping; los retadores si."""
    if name == "scorecard_woe":
        return model.fit(tr, tr[TARGET])
    return model.fit(tr, tr[TARGET], va, va[TARGET])


def main() -> int:
    cfg = load_config()
    seed = cfg["project"]["random_seed"]
    vintage = json.loads((resolve_path("manifests") / "sba_7a.json").read_text(encoding="utf-8"))[
        "resources"
    ][0]["vintage"]

    panel = validate_panel(load_panel(cfg))
    sp = split_out_of_time(panel, cfg)
    tr, va, te = sp["train"], sp["valid"], sp["test"]

    print("=" * 92)
    print("BASELINE vs RETADORES — split out-of-time")
    print(
        f"train {len(tr):,} (tasa {tr[TARGET].mean():.2%})   "
        f"valid {len(va):,} ({va[TARGET].mean():.2%})   "
        f"test {len(te):,} ({te[TARGET].mean():.2%})"
    )
    print("=" * 92)

    mlflow.set_tracking_uri(f"sqlite:///{(repo_root() / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("sba-pd")

    rows, calib_rows, preds = [], [], {}

    for name, model in build_models(seed).items():
        with mlflow.start_run(run_name=name):
            t0 = time.perf_counter()
            _fit(name, model, tr, va)
            secs = time.perf_counter() - t0

            p = {k: model.predict_proba(d) for k, d in (("train", tr), ("valid", va), ("test", te))}
            preds[name] = p

            # --- crudo (sin calibrar) ---
            d_te = discrimination(te[TARGET].to_numpy(), p["test"])
            d_tr = discrimination(tr[TARGET].to_numpy(), p["train"])
            d_va = discrimination(va[TARGET].to_numpy(), p["valid"])
            c_te = calibration(te[TARGET].to_numpy(), p["test"])

            # --- calibradores, TODOS ajustados sobre valid ---
            for cname in CALIBRATORS:
                cal = fit_calibrator(cname, va[TARGET].to_numpy(), p["valid"])
                pc = cal.transform(p["test"])
                cc = calibration(te[TARGET].to_numpy(), pc)
                dc = discrimination(te[TARGET].to_numpy(), pc)
                calib_rows.append(
                    {
                        "modelo": name,
                        "calibrador": cname,
                        "auc": dc.auc,
                        "brier": cc.brier,
                        "ece": cc.ece,
                        "ratio": cc.calibration_ratio,
                        "produccion": cname == PRODUCTION_CALIBRATOR,
                    }
                )

            rows.append(
                {
                    "modelo": name,
                    "auc_train": d_tr.auc,
                    "auc_valid": d_va.auc,
                    "auc_test": d_te.auc,
                    "gini_test": d_te.gini,
                    "ks_test": d_te.ks,
                    "brier_test": c_te.brier,
                    "ece_test": c_te.ece,
                    "ratio_test": c_te.calibration_ratio,
                    "drop_oot": d_tr.auc - d_te.auc,
                    "psi": psi(p["train"], p["test"]),
                    "segundos": secs,
                }
            )
            mlflow.log_params(
                {"model": name, "seed": seed, "data_vintage": vintage, "split": "out_of_time"}
            )
            mlflow.log_metrics({k: v for k, v in rows[-1].items() if isinstance(v, float)})
            print(f"  {name:15s} entrenado en {secs:6.1f}s  AUC test {d_te.auc:.4f}")

    res = pd.DataFrame(rows).sort_values("auc_test", ascending=False)
    cal = pd.DataFrame(calib_rows)

    print("\n" + "=" * 92)
    print("COMPARACION (probabilidades crudas)")
    print("=" * 92)
    print(res.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    print("\n" + "=" * 92)
    print(f"RECALIBRACION (ajustada sobre valid; produccion = '{PRODUCTION_CALIBRATOR}')")
    print("=" * 92)
    print(cal.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    base = res.loc[res.modelo == "scorecard_woe", "auc_test"].iloc[0]
    print("\n" + "=" * 92)
    print(f"VEREDICTO — baseline (scorecard) AUC test = {base:.4f}")
    for r in res.itertuples():
        if r.modelo == "scorecard_woe":
            continue
        delta = r.auc_test - base
        verdict = "gana" if delta > 0.01 else "empata" if delta > -0.01 else "pierde"
        print(f"  {r.modelo:15s} {r.auc_test:.4f}  ({delta:+.4f})  {verdict} vs baseline")
    print("=" * 92)

    out = resolve_path("exports")
    res.to_csv(out / "model_comparison.csv", index=False)
    cal.to_csv(out / "calibration_comparison.csv", index=False)
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "vintage": vintage,
                "seed": seed,
                "splits": {
                    k: [int(sp[k]["approval_fy"].min()), int(sp[k]["approval_fy"].max())]
                    for k in ("train", "valid", "test")
                },
                "models": res.to_dict(orient="records"),
                "production_calibrator": PRODUCTION_CALIBRATOR,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    np.save(out / "_preds_test.npy", np.vstack([preds[m]["test"] for m in res.modelo]))
    print(f"\nExportado a {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
