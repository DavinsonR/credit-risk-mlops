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
import os
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
        # Las dos decisiones de compuerta se REGISTRAN. Antes se descartaban, y
        # con ellas la unica evidencia que podia contestar la pregunta abierta
        # del ADR 0009: por que el hibrido sale menos consistente que el LLM
        # solo. Si las corridas de un mismo caso difieren en `used_llm`, la
        # varianza la mete la compuerta, no el modelo.
        return evaluate(
            a.text,
            reasons,
            provider=provider.name,
            language=language,
            seconds=a.seconds,
            second_run=b.text,
            used_llm_a=a.used_llm,
            used_llm_b=b.used_llm,
            rejection_reason=a.rejection_reason or b.rejection_reason,
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


def sin_medir(df: pd.DataFrame) -> set[str]:
    """Brazos donde NINGUNA llamada devolvio texto.

    POR QUE ESTO IMPORTA. Un brazo que nunca respondio sale de `summarize` con
    fidelidad 0.00, cumplimiento 0.00 y "pasa 0%" -- cifras que se leen como *el
    modelo es pesimo* cuando lo cierto es *el modelo no dijo nada*. Son dos
    afirmaciones distintas y solo una es una medicion.

    Paso con Gemini: 24 llamadas, todas 429 por cuota del tier gratuito, y la tabla
    lo mostraba en el ultimo puesto como si hubiera competido.
    """
    solos = df[~df["modelo"].str.contains(r"\(hibrido\)", regex=True)]
    fuera = set()
    for arm, part in solos.groupby("modelo", observed=True):
        if part["error"].notna().all():
            fuera.add(arm)
    return fuera


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


def fallback_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Cierra la pregunta abierta del ADR 0009 con datos en vez de hipotesis.

    La hipotesis escrita era: el hibrido sale menos consistente que el LLM solo
    porque la compuerta de validacion cambia de opinion entre corridas --acepta la
    reescritura una vez y la rechaza la otra-- y entonces un caso devuelve texto
    del LLM y el otro devuelve la plantilla. Dos textos completamente distintos por
    una decision binaria, no por la temperatura del modelo.

    La prueba es directa: entre los casos hibridos INCONSISTENTES, que fraccion
    tuvo `fallback_flip`. Si es alta, la varianza la mete la compuerta. Si es baja,
    la hipotesis era falsa y la varianza es del modelo reescribiendo distinto
    dentro del mismo camino.
    """
    hib = df[df["modelo"].str.contains(r"\(hibrido\)", regex=True)]
    if hib.empty:
        return pd.DataFrame()
    filas = []
    for arm, part in hib.groupby("modelo", observed=True):
        # SIN INSTRUMENTACION NO HAY CONCLUSION. La primera version leia una columna
        # que `evaluate` no estaba llenando --el kwarg solo llegaba a la rama de
        # error-- y los NaN se convertian en False: el reporte concluyo "la
        # hipotesis del ADR 0009 no se sostiene" a partir de un campo vacio. Ahora
        # la ausencia se declara en vez de promediarse.
        instrumentado = part["used_llm_a"].notna().all()
        inconsist = part[~part["consistent"].astype(bool)]
        flips = part[part["fallback_flip"].astype(bool)] if instrumentado else part.iloc[:0]
        filas.append(
            {
                "brazo": arm,
                "casos": len(part),
                "inconsistentes": len(inconsist),
                "con_flip": int(flips.shape[0]),
                # La cifra que contesta la pregunta.
                "instrumentado": bool(instrumentado),
                "inconsistencias_explicadas_por_flip": (
                    float(inconsist["fallback_flip"].astype(bool).mean())
                    if instrumentado and len(inconsist)
                    else float("nan")
                ),
                "uso_llm": (
                    float(part["used_llm_a"].astype(bool).mean()) if instrumentado else float("nan")
                ),
                "motivo_rechazo_mas_comun": (
                    part["rejection_reason"].dropna().mode().iloc[0]
                    if part["rejection_reason"].notna().any()
                    else None
                ),
            }
        )
    return pd.DataFrame(filas)


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
        # Distinguir "no hay archivo" de "hay archivo y la clave no sirve": son dos
        # problemas distintos y antes los dos se leian igual.
        from crmlops.config import repo_root

        env = repo_root() / ".env"
        print(f"No disponibles: {', '.join(sorted(faltantes))}")
        if env.exists():
            claves = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}
            sin = [claves[n] for n in sorted(faltantes) if not os.environ.get(claves[n])]
            print(
                f"  .env existe. {'Sin valor: ' + ', '.join(sin) if sin else 'Claves cargadas pero el proveedor no respondio.'}"
            )
        else:
            print(f"  No hay {env.name} en la raiz del repo. Ver docs/LLM_PROVIDERS.md")

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
        # NO MEDIDO no es NO SUPERA, y la tabla los mostraba igual.
        mudos = sin_medir(df)
        for name, row in resumen.iterrows():
            if name == base_key:
                continue
            modelo = name.split(" / ", 1)[-1]
            if modelo in mudos:
                print(f"  {name:26s} ->  NO MEDIDO: ninguna llamada devolvio texto")
                continue
            # Un hibrido cuyo LLM nunca respondio devuelve la plantilla las seis
            # veces: sus cifras SON las del baseline, y empatar consigo mismo no
            # significa nada.
            if modelo.removesuffix(" (hibrido)") in mudos:
                print(
                    f"  {name:26s} ->  NO MEDIDO: es la plantilla, el fallback "
                    "disparo en todos los casos"
                )
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
        if mudos:
            print(
                f"\n  Sin medir: {', '.join(sorted(mudos))}. Sus cifras de 0.00 NO son"
                "\n  una medicion del modelo, son la ausencia de una. Ver la columna"
                "\n  `error` del detalle."
            )
        print("\n  La plantilla no alucina, no depende de red y cuesta cero.")
        print("  Un LLM solo se justifica si aporta algo medible sobre eso.")

    fb = fallback_analysis(df)
    if not fb.empty:
        print("\n" + "=" * 92)
        print("POR QUE EL HIBRIDO ES MENOS CONSISTENTE - la compuerta, o el modelo?")
        print("=" * 92)
        for r in fb.itertuples():
            print(f"  {r.brazo}")
            print(
                f"    casos={r.casos}  inconsistentes={r.inconsistentes}  "
                f"corridas que cambiaron de camino={r.con_flip}"
            )
            if r.instrumentado:
                print(f"    reescritura del LLM aceptada en {r.uso_llm:.0%} de las corridas")
            if r.motivo_rechazo_mas_comun:
                print(f"    motivo de rechazo mas comun: {r.motivo_rechazo_mas_comun}")
            frac = r.inconsistencias_explicadas_por_flip
            if not r.instrumentado:
                print(
                    "    -> SIN INSTRUMENTACION: la decision de la compuerta no llego "
                    "al registro.\n"
                    "       No se concluye nada; ver crmlops.llm.evals.evaluate."
                )
            elif r.inconsistentes == 0:
                print("    -> sin inconsistencias que explicar en esta corrida")
            elif frac >= 0.5:
                print(
                    f"    -> {frac:.0%} de las inconsistencias vienen de que la compuerta "
                    "cambio de opinion."
                )
                print(
                    "       La varianza es del CONTROL, no del modelo: la hipotesis del "
                    "ADR 0009 se sostiene."
                )
            else:
                print(
                    f"    -> solo {frac:.0%} de las inconsistencias coinciden con un cambio "
                    "de camino."
                )
                print(
                    "       La hipotesis del ADR 0009 NO se sostiene: la varianza esta "
                    "dentro del mismo camino."
                )

    out = resolve_path("exports")
    df.to_csv(out / "llm_evals_detail.csv", index=False)
    resumen.to_csv(out / "llm_evals_summary.csv")
    if not fb.empty:
        fb.to_csv(out / "llm_fallback_analysis.csv", index=False)
    (out / "llm_evals.json").write_text(
        json.dumps(
            {
                "providers": [p.name for p in providers],
                "n_cases": len(CASES) * len(LANGUAGES),
                "summary": resumen.reset_index().to_dict(orient="records"),
                "fallback_analysis": fb.to_dict(orient="records") if not fb.empty else [],
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
