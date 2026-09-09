"""Híbrido: la plantilla fija los hechos, el LLM solo redacta mejor.

El ADR 0009 cerró con un resultado incómodo. La plantilla determinista gana en
fidelidad (1.00 vs 0.50) y consistencia, pero pierde claramente en legibilidad
(44.8 vs 73.2). Para un documento que lee un solicitante sin formación
financiera, esa diferencia de legibilidad es real y no da lo mismo ignorarla.

La pregunta que queda: ¿se puede quedar con las dos cosas?

CÓMO. El LLM **no elige** los factores ni los descubre: recibe la plantilla ya
armada y su única tarea es reescribirla en lenguaje más simple. Los hechos entran
fijados desde fuera.

Y —esto es lo que lo hace seguro— **su salida se valida antes de usarse**:

  1. ¿Menciona todos los factores que la plantilla mencionaba?
  2. ¿No introdujo ningún factor nuevo?
  3. ¿Evita las bases prohibidas por Reg B?
  4. ¿Cabe en el límite de palabras?

Si falla cualquiera, se devuelve la plantilla. El peor caso del híbrido es
exactamente el baseline, nunca algo peor. Eso convierte el LLM en una mejora
opcional en vez de una dependencia: si el modelo no está, si alucina o si se
niega, el sistema sigue emitiendo un aviso legalmente válido.
"""

from __future__ import annotations

from dataclasses import dataclass

from crmlops.explain.reasons import Reason
from crmlops.llm.adverse_action import NoticeRequest
from crmlops.llm.evals import MAX_WORDS, compliance, faithfulness, word_count
from crmlops.llm.providers import Provider

# Fidelidad minima para aceptar la reescritura. No es 1.0 estricto porque la
# comparacion es lexica: una reformulacion valida puede no repetir la etiqueta
# palabra por palabra. Por debajo de esto, se descarta.
MIN_FAITHFULNESS = 0.99

REWRITE_PROMPT = {
    "es": """Reescribe este aviso legal en español más simple y claro.

REGLAS ABSOLUTAS:
- NO agregues, quites ni cambies ninguna de las razones listadas.
- NO inventes explicaciones sobre por qué cada razón importa.
- NO menciones características personales del solicitante.
- Mantén el aviso legal final sobre igualdad de oportunidades de crédito.
- Máximo {max_words} palabras. Frases cortas.

AVISO ORIGINAL:
{original}

Devuelve solo el aviso reescrito.""",
    "en": """Rewrite this legal notice in simpler, clearer English.

ABSOLUTE RULES:
- Do NOT add, remove or change any of the listed reasons.
- Do NOT invent explanations about why each reason matters.
- Do NOT mention personal characteristics of the applicant.
- Keep the final legal notice about equal credit opportunity.
- Maximum {max_words} words. Short sentences.

ORIGINAL NOTICE:
{original}

Return only the rewritten notice.""",
}


@dataclass
class HybridResult:
    text: str
    used_llm: bool
    rejection_reason: str | None
    seconds: float


def validate_rewrite(
    rewritten: str, reasons: list[Reason], language: str
) -> tuple[bool, str | None]:
    """¿La reescritura conserva los hechos? Devuelve (aceptar, motivo del rechazo)."""
    if not rewritten.strip():
        return False, "salida vacia"

    n = word_count(rewritten)
    if n > MAX_WORDS:
        return False, f"demasiado largo ({n} > {MAX_WORDS} palabras)"

    ok, prohibidas = compliance(rewritten)
    if not ok:
        return False, f"bases prohibidas: {', '.join(prohibidas)}"

    f = faithfulness(rewritten, reasons, language)
    if f.hallucinated:
        return False, f"factores inventados: {', '.join(f.hallucinated)}"
    if f.recall < MIN_FAITHFULNESS:
        return False, f"razones omitidas: {', '.join(f.missing)}"

    return True, None


def generate(request: NoticeRequest, provider: Provider, *, seed: int = 42) -> HybridResult:
    """Plantilla, y encima una reescritura del LLM solo si pasa la validacion."""
    base = request.build_template()

    if provider.name == "template":
        return HybridResult(base, used_llm=False, rejection_reason=None, seconds=0.0)

    prompt = REWRITE_PROMPT[request.language].format(max_words=MAX_WORDS, original=base)
    gen = provider.run(prompt, seed=seed)

    if not gen.ok:
        return HybridResult(base, False, gen.error or "sin salida", gen.seconds)

    aceptar, motivo = validate_rewrite(gen.text, request.reasons, request.language)
    if not aceptar:
        # Fallback silencioso al baseline: el sistema nunca emite un aviso peor
        # que la plantilla, pase lo que pase con el modelo.
        return HybridResult(base, False, motivo, gen.seconds)

    return HybridResult(gen.text, used_llm=True, rejection_reason=None, seconds=gen.seconds)
