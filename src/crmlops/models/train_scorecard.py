"""Entrena el baseline (scorecard WoE) y registra todo en MLflow.

Reporta discriminacion, calibracion y estabilidad sobre un split OUT-OF-TIME.
El numero que importa no es el AUC de train sino cuanto se degrada hacia test:
un modelo de credito vive o muere por como envejece.
"""

from __future__ import annotations

import json
import sys

import mlflow

from crmlops.config import load_config, repo_root, resolve_path
from crmlops.evaluation.metrics import psi, reliability_table, summarize
from crmlops.models.scorecard import WoEScorecard
from crmlops.sources.contracts import validate_panel
from crmlops.sources.loader import load_panel, split_out_of_time

TARGET = "is_chargeoff"
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


def _fmt(block: dict[str, float]) -> str:
    return "  ".join(f"{k}={v:.4f}" for k, v in block.items())


def main() -> int:
    cfg = load_config()
    seed = cfg["project"]["random_seed"]

    print("=" * 78)
    print("BASELINE — Scorecard WoE + regresion logistica")
    print("=" * 78)

    panel = validate_panel(load_panel(cfg))
    splits = split_out_of_time(panel, cfg)
    tr, va, te = splits["train"], splits["valid"], splits["test"]
    print(f"\ntrain {len(tr):>9,}  valid {len(va):>9,}  test {len(te):>9,}")

    # Backend SQLite: MLflow 3.x deprecó el file store. Sigue siendo local y
    # gratuito; la BD no se commitea, las métricas exportadas sí.
    mlflow.set_tracking_uri(f"sqlite:///{(repo_root() / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("sba-pd")

    with mlflow.start_run(run_name="scorecard-woe"):
        mlflow.log_params(
            {
                "model": "woe_scorecard",
                "seed": seed,
                "n_train": len(tr),
                "split": "out_of_time",
                "train_fy": f"{cfg['splits']['train']['start']}-{cfg['splits']['train']['end']}",
                "test_fy": f"{cfg['splits']['test']['start']}-{cfg['splits']['test']['end']}",
                "data_vintage": json.loads(
                    (resolve_path("manifests") / "sba_7a.json").read_text(encoding="utf-8")
                )["resources"][0]["vintage"],
            }
        )

        print("\nAjustando binning y logistica SOLO sobre train...")
        sc = WoEScorecard(NUMERIC, CATEGORICAL, random_state=seed).fit(tr, tr[TARGET])

        # Guarda anti-fuga: un IV muy alto en credito casi siempre es fuga.
        warn = sc.high_iv_warnings()
        if not warn.empty:
            print("\n!! Variables con IV sospechosamente alto (posible fuga):")
            print(warn.to_string(index=False))
            mlflow.log_param("high_iv_warnings", ",".join(warn["name"]))

        art = sc.artifacts()
        print(f"\nVariables seleccionadas ({len(art.selected_features)}) por Information Value:")
        print(art.binning_table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

        scores = {}
        for name, part in (("train", tr), ("valid", va), ("test", te)):
            p = sc.predict_proba(part)
            scores[name] = p
            block = summarize(part[TARGET].to_numpy(), p)
            mlflow.log_metrics({f"{name}_{k}": v for k, v in block.items()})
            print(f"\n{name:5s}  {_fmt(block)}")

        drop = (
            summarize(tr[TARGET].to_numpy(), scores["train"])["auc"]
            - summarize(te[TARGET].to_numpy(), scores["test"])["auc"]
        )
        stability = psi(scores["train"], scores["test"])
        mlflow.log_metrics({"auc_drop_oot": drop, "psi_train_test": stability})
        print(f"\ndegradacion AUC train->test : {drop:+.4f}")
        print(
            f"PSI del score train->test    : {stability:.4f}  "
            f"({'estable' if stability < 0.10 else 'vigilar' if stability < 0.25 else 'ACCION'})"
        )

        print("\nTabla de confiabilidad (test) — predicho vs observado por decil:")
        rel = reliability_table(te[TARGET].to_numpy(), scores["test"])
        print(rel.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

        out = resolve_path("exports")
        art.points_table.to_csv(out / "scorecard_points.csv", index=False)
        rel.to_csv(out / "scorecard_reliability.csv", index=False)
        mlflow.log_artifacts(str(out))

        gates = cfg["gates"]
        checks = {
            "auc_test": (
                summarize(te[TARGET].to_numpy(), scores["test"])["auc"],
                gates["min_auc_test"],
                "min",
            ),
            "auc_drop_oot": (drop, gates["max_auc_drop_oot"], "max"),
            "brier": (
                summarize(te[TARGET].to_numpy(), scores["test"])["brier"],
                gates["max_brier"],
                "max",
            ),
        }
        print("\n" + "=" * 78)
        print("GATES (aplican al modelo final, no al baseline):")
        for k, (val, thr, direction) in checks.items():
            ok = val >= thr if direction == "min" else val <= thr
            print(f"  {'PASA' if ok else 'FALLA'}  {k:14s} {val:.4f} vs {thr} ({direction})")
        print("=" * 78)

    print(f"\nMLflow: {(repo_root() / 'mlruns')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
