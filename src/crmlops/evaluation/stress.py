"""Pruebas de estres sobre cohortes fuera del regimen de entrenamiento.

SR 11-7 exige responder que le pasa al modelo cuando cambian las condiciones. En
este dataset la pregunta no es hipotetica: la tasa base del 7(a) fue 36.9% en
FY2007 y 6.2% en FY2013, un factor de seis.

El modelo se entrena SOLO en el regimen post-crisis (FY2011-2015). Las cohortes
descartadas por el ADR 0003 no se tiran: se usan aqui, sin reentrenar, para medir
cuanto de su desempeno sobrevive fuera de su mundo.

Este modulo existe porque `stress_cohorts` estaba declarado en config.yaml con
comentarios elaborados sobre SR 11-7 y ninguna linea de codigo que lo leyera
(docs/AUDIT.md, defecto B2). Config que aparenta funcionalidad es peor que
config ausente: promete una capacidad que no existe.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from crmlops.config import load_config, resolve_path
from crmlops.evaluation.metrics import calibration, discrimination
from crmlops.features.spec import load_spec
from crmlops.models.calibration import fit_calibrator
from crmlops.models.gbm import GBMChallenger
from crmlops.sources.contracts import validate_panel
from crmlops.sources.loader import load_panel, split_out_of_time

TARGET = "is_chargeoff"


def evaluate_cohorts(cfg: dict | None = None) -> pd.DataFrame:
    """Aplica el modelo de produccion a cada cohorte de estres, sin reentrenar."""
    from crmlops.models.train import PRODUCTION_CALIBRATOR

    cfg = cfg or load_config()
    spec = load_spec(cfg)
    panel = validate_panel(load_panel(cfg))
    spec.validate_against(panel)

    sp = split_out_of_time(panel, cfg)
    tr, va, te = sp["train"], sp["valid"], sp["test"]

    model = GBMChallenger(
        list(spec.numeric), list(spec.categorical), random_state=cfg["project"]["random_seed"]
    )
    model.fit(tr, tr[TARGET], va, va[TARGET])
    cal = fit_calibrator(PRODUCTION_CALIBRATOR, va[TARGET].to_numpy(), model.predict_proba(va))

    def score(df: pd.DataFrame, label: str) -> dict:
        if len(df) < 500 or df[TARGET].nunique() < 2:
            return {"cohorte": label, "n": len(df), "nota": "muestra insuficiente"}
        y = df[TARGET].to_numpy()
        p = cal.transform(model.predict_proba(df))
        d, c = discrimination(y, p), calibration(y, p)
        return {
            "cohorte": label,
            "fy": f"{int(df['approval_fy'].min())}-{int(df['approval_fy'].max())}",
            "n": len(df),
            "tasa_base": float(y.mean()),
            "auc": d.auc,
            "ks": d.ks,
            "brier": c.brier,
            "predicho": c.predicted_rate,
            "ratio_calibracion": c.calibration_ratio,
        }

    rows = [score(te, "test (referencia)")]
    for name, window in cfg.get("stress_cohorts", {}).items():
        mask = panel["approval_fy"].between(window["start"], window["end"])
        rows.append(score(panel.loc[mask], name))
    return pd.DataFrame(rows)


def main() -> int:
    cfg = load_config()
    print("=" * 96)
    print("PRUEBAS DE ESTRES - el modelo aplicado fuera de su regimen, sin reentrenar")
    print("=" * 96)

    res = evaluate_cohorts(cfg)
    print()
    print(res.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    ref = res.iloc[0]
    print("\n" + "=" * 96)
    print("LECTURA")
    print("=" * 96)
    for r in res.iloc[1:].itertuples():
        if not hasattr(r, "auc") or pd.isna(getattr(r, "auc", np.nan)):
            print(f"  {r.cohorte}: {getattr(r, 'nota', 'sin datos')}")
            continue
        d_auc = r.auc - ref.auc
        print(
            f"  {r.cohorte:22s} AUC {r.auc:.4f} ({d_auc:+.4f} vs test)  "
            f"ratio calibracion {r.ratio_calibracion:.2f}"
        )
        if r.ratio_calibracion < 0.6:
            print("      -> SUBESTIMA el riesgo de forma severa en este regimen")
        elif r.ratio_calibracion > 1.6:
            print("      -> SOBRESTIMA el riesgo en este regimen")

    out = resolve_path("exports")
    res.to_csv(out / "stress_test.csv", index=False)
    print(f"\nExportado a {out / 'stress_test.csv'}")

    print("\nEl ordenamiento (AUC) y el nivel (calibracion) se degradan de forma")
    print("independiente. Un modelo puede seguir ordenando bien y aun asi equivocarse")
    print("por un factor de dos en cuanta perdida espera: el expected loss se")
    print("calcula con la probabilidad, no con el orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
