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
import pandas as pd

from crmlops.config import load_config, repo_root, resolve_path
from crmlops.evaluation.metrics import calibration, discrimination, psi, stability
from crmlops.features.spec import load_spec
from crmlops.governance.gates import config_fingerprint
from crmlops.governance.integrity import code_fingerprint, save_predictions
from crmlops.models.calibration import CALIBRATORS, fit_calibrator
from crmlops.models.gbm import GBMChallenger
from crmlops.models.neural import NeuralChallenger
from crmlops.models.scorecard import WoEScorecard
from crmlops.sources.contracts import validate_panel
from crmlops.sources.loader import load_panel, split_out_of_time

TARGET = "is_chargeoff"
PRODUCTION_CALIBRATOR = "intercept"  # declarado ANTES de ver test
# LightGBM y no la red neuronal, pese a que la red gana 0.0049 de AUC de forma
# estadisticamente significativa. Ver docs/adr/0004-modelo-de-produccion.md.
PRODUCTION_MODEL = "lightgbm"

# Las listas de features viven en config.yaml y se leen con load_spec().
# Antes estaban hardcodeadas aqui, en otra convencion de nombres que la del
# config, y el fingerprint del gate hasheaba la de config: se podia quitar una
# variable del modelo sin que el control lo notara. Ver docs/AUDIT.md defecto A2.


def build_models(seed: int, spec) -> dict:
    num, cat = list(spec.numeric), list(spec.categorical)
    return {
        "scorecard_woe": WoEScorecard(num, cat, random_state=seed),
        "lightgbm": GBMChallenger(num, cat, random_state=seed),
        "neural_mlp": NeuralChallenger(num, cat, random_state=seed),
    }


def _production_block(y_test, p_test, res, model_name: str) -> dict:
    """Metricas de la configuracion que realmente se despacha (modelo + calibrador)."""
    d, c = discrimination(y_test, p_test), calibration(y_test, p_test)
    raw = res.loc[res.modelo == model_name].iloc[0]
    return {
        "auc_test": d.auc,
        "gini_test": d.gini,
        "ks_test": d.ks,
        "brier_test": c.brier,
        "ece_test": c.ece,
        "calibration_ratio": c.calibration_ratio,
        # La degradacion out-of-time se mide sobre el modelo crudo: el calibrador
        # se ajusta con valid y no interviene en como el modelo envejece.
        "drop_oot": float(raw["drop_oot"]),
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

    spec = load_spec(cfg)
    panel = validate_panel(load_panel(cfg))
    spec.validate_against(panel)
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

    for name, model in build_models(seed, spec).items():
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
                    # Descompone el PSI: un corrimiento de nivel (ciclo) se
                    # arregla recalibrando; un cambio de forma exige revisar el
                    # modelo. El PSI a secas no los distingue.
                    "psi_shape": stability(p["train"], p["test"]).psi_shape,
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

    # Predicciones de test: permiten que el gate RECOMPUTE las metricas en vez
    # de creerlas. Sin esto, editar metrics.json a mano burla los cuatro gates.
    prod_cal = fit_calibrator(
        PRODUCTION_CALIBRATOR, va[TARGET].to_numpy(), preds[PRODUCTION_MODEL]["valid"]
    )
    prod_test = prod_cal.transform(preds[PRODUCTION_MODEL]["test"])
    to_save = {name: p["test"] for name, p in preds.items()}
    # La configuracion de PRODUCCION es modelo + calibrador. El gate la evalua a
    # ella, no al modelo crudo: antes se controlaba algo distinto de lo que se
    # despachaba (docs/AUDIT.md, defecto C).
    to_save["produccion"] = prod_test
    pred_path = save_predictions(te[TARGET].to_numpy(), to_save)
    print(f"Predicciones de verificacion -> {pred_path.relative_to(repo_root())}")

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
                "split_sizes": {k: len(sp[k]) for k in ("train", "valid", "test")},
                "split_rates": {k: float(sp[k][TARGET].mean()) for k in ("train", "valid", "test")},
                "models": res.to_dict(orient="records"),
                "production_model": PRODUCTION_MODEL,
                "production_metrics": _production_block(
                    te[TARGET].to_numpy(), prod_test, res, PRODUCTION_MODEL
                ),
                "production_calibrator": PRODUCTION_CALIBRATOR,
                # Ata estas metricas a la configuracion que las produjo. Si alguien
                # cambia el split o las exclusiones sin reentrenar, el gate lo ve.
                "config_fingerprint": config_fingerprint(cfg),
                # Huella del codigo de modelado. El gate recomputa las metricas
                # desde las predicciones guardadas y ademas exige que el codigo
                # no haya cambiado. Ver docs/AUDIT.md defecto A1.
                "code_fingerprint": code_fingerprint(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nExportado a {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
