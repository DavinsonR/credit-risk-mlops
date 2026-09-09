"""Harness: compara proveedores sobre los mismos casos y las mismas métricas.

Estructura deliberadamente idéntica a la del modelo: hay un **baseline** que los
retadores tienen que superar. Allí era el scorecard WoE frente al GBM; aquí es una
plantilla determinista frente a los LLM.

Si ningún LLM supera a la plantilla, la plantilla gana. No alucina, no depende de
red, cuesta cero y un validador la lee entera en un minuto. Ese resultado sería
publicable, no un fracaso: la pregunta del ejercicio es si el LLM aporta algo, y
"no" es una respuesta.

CONSISTENCIA. Cada proveedor genera DOS veces el mismo caso con la misma semilla.
Un aviso legal que cambia entre ejecuciones es indefendible ante un regulador, y
sin la segunda corrida no hay forma de saberlo.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from crmlops.config import resolve_path
from crmlops.explain.reasons import Reason
from crmlops.llm.adverse_action import NoticeRequest
from crmlops.llm.evals import EvalResult, evaluate
from crmlops.llm.hybrid import generate as hybrid_generate
from crmlops.llm.providers import Provider, available_providers

# Casos sintéticos que cubren situaciones distintas: muchas razones y pocas,
# montos grandes y chicos. Son fijos a propósito -- comparar proveedores sobre
# casos distintos no compara nada.
CASES: list[tuple[str, float, list[Reason]]] = [
    (
        "startup_alto_riesgo",
        250_000,
        [
            Reason(
                "business_age",
                "la antigüedad del negocio",
                "the age of the business",
                0.45,
                "Startup",
                1,
            ),
            Reason(
                "initial_rate",
                "la tasa de interés inicial",
                "the initial interest rate",
                0.43,
                6.5,
                2,
            ),
            Reason(
                "guarantee_pct",
                "el porcentaje de garantía del préstamo",
                "the loan guarantee percentage",
                0.28,
                0.85,
                3,
            ),
            Reason(
                "borrower_state", "la ubicación del negocio", "the business location", 0.27, "TN", 4
            ),
        ],
    ),
    (
        "monto_alto_una_razon",
        1_500_000,
        [
            Reason(
                "gross_approval",
                "el monto solicitado",
                "the requested loan amount",
                0.62,
                1_500_000,
                1,
            ),
        ],
    ),
    (
        "sin_colateral",
        80_000,
        [
            Reason(
                "collateral_ind",
                "la garantía colateral aportada",
                "the collateral provided",
                0.38,
                "N",
                1,
            ),
            Reason(
                "naics_sector",
                "el sector de actividad del negocio",
                "the business industry sector",
                0.21,
                "72",
                2,
            ),
        ],
    ),
]

LANGUAGES = ("es", "en")


def run_case(
    provider: Provider,
    name: str,
    amount: float,
    reasons: list[Reason],
    language: str,
    *,
    hybrid: bool = False,
) -> EvalResult:
    request = NoticeRequest(amount=amount, reasons=reasons, language=language)

    if hybrid:
        # El hibrido valida la reescritura antes de usarla y cae a la plantilla
        # si falla: por construccion nunca es peor que el baseline.
        a = hybrid_generate(request, provider)
        b = hybrid_generate(request, provider)
        return evaluate(
            a.text,
            reasons,
            provider=provider.name,
            language=language,
            seconds=a.seconds,
            second_run=b.text,
        )

    if provider.name == "template":
        texto = request.build_template()
        return evaluate(texto, reasons, provider=provider.name, language=language)

    primera = provider.run(request.build_prompt())
    if not primera.ok:
        return evaluate(
            "",
            reasons,
            provider=provider.name,
            language=language,
            seconds=primera.seconds,
            error=primera.error,
        )
    segunda = provider.run(request.build_prompt())

    return evaluate(
        primera.text,
        reasons,
        provider=provider.name,
        language=language,
        seconds=primera.seconds,
        second_run=segunda.text if segunda.ok else "",
    )


def run(providers: list[Provider] | None = None) -> pd.DataFrame:
    providers = providers if providers is not None else available_providers()
    filas = []
    for p in providers:
        # Calentar antes de medir: la primera generacion tras cargar el modelo
        # no es determinista, y sin descartarla la metrica de consistencia mide
        # el arranque en frio en vez del modelo.
        if p.name != "template":
            p.warm_up()
        # Cada LLM se evalua de dos formas: solo, y como reescritor dentro del
        # hibrido. Comparar ambos aisla cuanto del fallo viene del modelo y
        # cuanto de dejarlo elegir los hechos.
        modos = (
            [(False, p.model)]
            if p.name == "template"
            else [(False, p.model), (True, f"{p.model} (hibrido)")]
        )
        for hib, etiqueta in modos:
            for name, amount, reasons in CASES:
                for lang in LANGUAGES:
                    r = run_case(p, name, amount, reasons, lang, hybrid=hib)
                    filas.append(
                        {"caso": name, "modelo": etiqueta, **r.as_dict(), "pasa": r.passes}
                    )
    return pd.DataFrame(filas)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.assign(arm=df["provider"] + " / " + df["modelo"])
        .groupby("arm", observed=True)
        .agg(
            casos=("caso", "size"),
            fidelidad=("faithfulness", "mean"),
            cumple=("compliant", "mean"),
            legibilidad=("readability", "mean"),
            palabras=("words", "mean"),
            consistente=("consistent", "mean"),
            segundos=("seconds", "mean"),
            pasa=("pasa", "mean"),
        )
        .sort_values("pasa", ascending=False)
        .round(4)
    )


def main() -> int:
    providers = available_providers()
    print("=" * 92)
    print("HARNESS DE AVISOS DE ADVERSE ACTION")
    print("=" * 92)
    print("Brazos: " + ", ".join(f"{p.name}/{p.model}" for p in providers))
    print(
        f"Casos: {len(CASES)} x {len(LANGUAGES)} idiomas = {len(CASES) * len(LANGUAGES)} avisos c/u"
    )

    faltantes = {"groq", "gemini"} - {p.name for p in providers}
    if faltantes:
        print(f"No disponibles: {', '.join(sorted(faltantes))}")
        print("  (claves en .env; ver .env.example)")

    print("\nGenerando y evaluando...\n", flush=True)
    df = run(providers)
    resumen = summarize(df)

    print(resumen.to_string())

    base_key = next((k for k in resumen.index if k.startswith("template")), None)
    base = resumen.loc[base_key] if base_key else None
    print("\n" + "=" * 92)
    print("VEREDICTO")
    print("=" * 92)
    if base is None:
        print("  Sin baseline: no hay contra que comparar.")
    else:
        print(
            f"  Baseline (plantilla determinista): fidelidad {base.fidelidad:.4f}, "
            f"pasa {base.pasa:.0%}"
        )
        for name, row in resumen.iterrows():
            if name == base_key:
                continue
            delta = row.fidelidad - base.fidelidad
            veredicto = (
                "SUPERA al baseline"
                if row.pasa > base.pasa
                else "empata"
                if row.pasa == base.pasa
                else "NO supera al baseline"
            )
            print(
                f"  {name:26s} fidelidad {row.fidelidad:.4f} ({delta:+.4f})  "
                f"pasa {row.pasa:.0%}  {row.segundos:.1f}s  ->  {veredicto}"
            )
        print("\n  La plantilla no alucina, no depende de red y cuesta cero.")
        print("  Un LLM solo se justifica si aporta algo medible sobre eso.")

    out = resolve_path("exports")
    df.to_csv(out / "llm_evals_detail.csv", index=False)
    resumen.to_csv(out / "llm_evals_summary.csv")
    (out / "llm_evals.json").write_text(
        json.dumps(
            {
                "providers": [p.name for p in providers],
                "n_cases": len(CASES) * len(LANGUAGES),
                "summary": resumen.reset_index().to_dict(orient="records"),
            },
            indent=2,
            default=float,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nExportado a {out.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
