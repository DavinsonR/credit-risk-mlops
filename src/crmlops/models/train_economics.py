"""El titular: de probabilidades a dolares evitados.

Entrena el modelo de produccion (GBM calibrado), lo aplica al periodo de test y
responde la pregunta que un comite de credito si entiende: si hubieramos usado
este modelo, cuanta perdida se habria evitado y a que costo.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from crmlops.config import load_config, resolve_path
from crmlops.evaluation.economics import (
    breakeven_margin,
    decision_curve,
    optimal_cutoff,
    random_baseline,
    summarize_at,
)
from crmlops.models.calibration import fit_calibrator
from crmlops.models.gbm import GBMChallenger
from crmlops.models.train import CATEGORICAL, NUMERIC, PRODUCTION_CALIBRATOR, TARGET
from crmlops.sources.contracts import validate_panel
from crmlops.sources.loader import load_panel, split_out_of_time

# Margen neto sobre un prestamo bueno, como fraccion del monto. Es un SUPUESTO.
# Se barre un rango en vez de fijar uno: la sensibilidad es informacion.
MARGINS = [0.02, 0.03, 0.05, 0.08]
DEFAULT_GUARANTEE = 0.75  # fallback cuando falta el dato


def money(x: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= div:
            return f"${x / div:,.1f}{unit}"
    return f"${x:,.0f}"


def main() -> int:
    cfg = load_config()
    seed = cfg["project"]["random_seed"]
    panel = validate_panel(load_panel(cfg))
    sp = split_out_of_time(panel, cfg)
    tr, va, te = sp["train"], sp["valid"], sp["test"]

    print("=" * 88)
    print("ECONOMIA DE LA DECISION - que habria pasado con el modelo")
    print("=" * 88)

    model = GBMChallenger(NUMERIC, CATEGORICAL, random_state=seed)
    model.fit(tr, tr[TARGET], va, va[TARGET])
    cal = fit_calibrator(PRODUCTION_CALIBRATOR, va[TARGET].to_numpy(), model.predict_proba(va))
    pd_test = cal.transform(model.predict_proba(te))

    y = te[TARGET].to_numpy()
    exposure = te["gross_approval"].to_numpy()
    loss = np.nan_to_num(te["chargeoff_amount"].to_numpy()) * (y == 1)

    # En 7(a) la SBA garantiza una fraccion del prestamo, asi que el banco y el
    # contribuyente NO pierden lo mismo. Separarlos no es un detalle: cambia
    # quien deberia usar el modelo y con que umbral.
    guarantee = np.clip(
        np.nan_to_num(te["guarantee_pct"].to_numpy(), nan=DEFAULT_GUARANTEE), 0.0, 1.0
    )
    loss_sba = loss * guarantee
    loss_lender = loss * (1.0 - guarantee)

    total_lent, total_loss = exposure.sum(), loss.sum()
    n_bad = max(int(y.sum()), 1)
    window = f"FY{cfg['splits']['test']['start']}-{cfg['splits']['test']['end']}"

    print(f"\nCartera de test ({len(te):,} prestamos, {window}):")
    print(f"  monto prestado        {money(total_lent)}")
    print(f"  perdida realizada     {money(total_loss)}  ({total_loss / total_lent:.2%} del monto)")
    print(f"  prestamos fallidos    {int(y.sum()):,}  ({y.mean():.2%})")
    print(f"  perdida media         {money(total_loss / n_bad)} por prestamo fallido")

    print(f"\n  garantia SBA media    {guarantee.mean():.1%} del monto")
    print(f"    absorbe la SBA      {money(loss_sba.sum())}  ({loss_sba.sum() / total_loss:.0%})")
    print(
        f"    absorbe el banco    {money(loss_lender.sum())}  "
        f"({loss_lender.sum() / total_loss:.0%})"
    )

    be_all = breakeven_margin(loss, exposure)
    be_lender = breakeven_margin(loss_lender, exposure)
    print(f"\n  margen de equilibrio, perdida bruta         {be_all:.2%}")
    print(f"  margen de equilibrio, solo riesgo del banco {be_lender:.2%}")
    print("  Debajo de ese margen la cartera pierde sin modelo alguno, y")
    print("  rechazar mas siempre mejora: el optimo se va al borde de la grilla.")

    grid = np.arange(0.01, 0.51, 0.01)
    curve = decision_curve(y, pd_test, loss, exposure, grid=grid)
    base = random_baseline(y, loss, exposure, grid)
    curve["loss_avoided_random"] = base["loss_avoided"].to_numpy()
    curve["lift"] = curve["loss_avoided"] / curve["loss_avoided_random"]

    print("\n" + "=" * 88)
    print("SI HUBIERAMOS RECHAZADO EL k% MAS RIESGOSO")
    print("=" * 88)
    print(
        f"{'rechazo':>8}  {'perdida evitada':>16}  {'vs azar':>9}  "
        f"{'lift':>5}  {'% perdidas':>10}  {'buenos sacrificados':>19}"
    )
    for k in (0.05, 0.10, 0.15, 0.20, 0.30):
        r = summarize_at(curve, k)
        print(
            f"{r.decline_rate:>7.0%}  {money(r.loss_avoided):>16}  "
            f"{money(r.loss_avoided_random):>9}  {r.lift:>5.2f}x  "
            f"{r.loss_capture:>9.1%}  {money(r.good_volume_foregone):>19}"
        )

    print("\n" + "=" * 88)
    print("CORTE OPTIMO SEGUN EL MARGEN SUPUESTO SOBRE UN PRESTAMO BUENO")
    print("=" * 88)
    opt_rows = []
    for m in MARGINS:
        b = optimal_cutoff(curve, m)
        opt_rows.append(b)
        flag = "   <-- EN EL BORDE, no es recomendacion" if b.at_boundary else ""
        print(
            f"  margen {m:>4.0%}  ->  rechazar {b.decline_rate:>4.0%}  "
            f"beneficio neto {money(b.net_benefit):>9}{flag}"
        )
    print(f"\n  Todo margen por debajo de {be_all:.1%} toca el borde por construccion.")

    out = resolve_path("exports")
    curve.to_csv(out / "decision_curve.csv", index=False)
    pd.DataFrame(opt_rows).to_csv(out / "optimal_cutoffs.csv", index=False)

    r10 = summarize_at(curve, 0.10)
    (out / "headline_economics.json").write_text(
        json.dumps(
            {
                "test_window": [int(te["approval_fy"].min()), int(te["approval_fy"].max())],
                "n_loans": len(te),
                "total_lent": float(total_lent),
                "realized_loss": float(total_loss),
                "sba_absorbed_loss": float(loss_sba.sum()),
                "lender_absorbed_loss": float(loss_lender.sum()),
                "mean_guarantee_pct": float(guarantee.mean()),
                "breakeven_margin_gross": float(be_all),
                "breakeven_margin_lender": float(be_lender),
                "at_10pct_decline": {
                    "loss_avoided": float(r10.loss_avoided),
                    "loss_avoided_random": float(r10.loss_avoided_random),
                    "lift_vs_random": float(r10.lift),
                    "share_of_all_losses": float(r10.loss_capture),
                    "good_volume_foregone": float(r10.good_volume_foregone),
                },
                "assumption": (
                    "Contrafactual sobre prestamos que SI fueron aprobados. Supone "
                    "que rechazar no altera el comportamiento del resto del mercado."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 88)
    print(
        f"TITULAR: rechazando el 10% mas riesgoso se habrian evitado "
        f"{money(r10.loss_avoided)} en charge-offs"
    )
    print(
        f"         ({r10.loss_capture:.0%} de toda la perdida del periodo, "
        f"{r10.lift:.2f}x lo que lograria rechazar al azar)"
    )
    print(
        f"         De eso, {money(r10.loss_avoided * guarantee.mean())} los habria "
        f"ahorrado el contribuyente."
    )
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
