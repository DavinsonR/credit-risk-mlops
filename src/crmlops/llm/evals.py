"""Evaluación de los avisos de adverse action.

CUATRO MÉTRICAS, TODAS PROGRAMÁTICAS. Ninguna usa un LLM como juez.

Un LLM-as-judge introduce el mismo tipo de error que se quiere detectar: si el
generador alucina un factor, el juez puede considerarlo razonable. Aquí la fuente
de verdad son los valores SHAP, que son un vector de números, y todas las
comprobaciones se hacen contra él.

  1. *Fidelidad*  -- ¿las razones citadas son las que el modelo usó? Se mide
     cobertura (¿están todas?) y precisión (¿inventó alguna?). Una razón
     inventada en un aviso legal no es un error de estilo: es una afirmación
     falsa sobre por qué se negó un crédito.

  2. *Cumplimiento* -- ¿evita las bases prohibidas por Reg B? Mencionar raza o
     edad en este documento, aunque sea para negarlas, no corresponde.

  3. *Legibilidad* -- el aviso lo lee un solicitante, no un analista. Para
     español se usa Fernández-Huerta, no Flesch-Kincaid: las fórmulas
     anglosajonas penalizan el español, que tiene más sílabas por palabra por
     construcción, y darían una nota artificialmente mala.

  4. *Consistencia* -- la misma solicitud debe producir el mismo aviso. Un
     documento legal que cambia entre ejecuciones es indefendible.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from crmlops.explain.reasons import FEATURE_LABELS, Reason
from crmlops.llm.adverse_action import PROHIBITED_TERMS

MAX_WORDS = 150

# Limite de palabra del regex, como cadena RAW. Definirlo aqui y una sola vez
# evita el error de escribirlo inline sin prefijo r: "\b" en una cadena normal de
# Python es el caracter BACKSPACE, y el chequeo de cumplimiento deja de detectar
# nada -- en silencio, que es lo peligroso.
WORD_BOUNDARY = r"\b"


def _norm(text: str) -> str:
    """Minúsculas sin acentos: la comparación no debe fallar por tildes."""
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _content_words(label: str) -> set[str]:
    """Palabras con carga semántica de una etiqueta, sin artículos ni preposiciones."""
    stop = {
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "un",
        "una",
        "y",
        "o",
        "en",
        "the",
        "of",
        "a",
        "an",
        "and",
        "or",
        "in",
        "to",
    }
    return {w for w in re.findall(r"\w+", _norm(label)) if w not in stop and len(w) > 2}


@dataclass
class Faithfulness:
    recall: float  # de las razones reales, cuantas aparecen
    precision: float  # de los factores mencionados, cuantos son reales
    hallucinated: list[str]
    missing: list[str]

    @property
    def score(self) -> float:
        """Media armónica. Castiga que cualquiera de las dos sea baja."""
        if self.recall + self.precision == 0:
            return 0.0
        return 2 * self.recall * self.precision / (self.recall + self.precision)


@dataclass
class EvalResult:
    provider: str
    language: str
    faithfulness: float
    recall: float
    precision: float
    hallucinated: list[str]
    compliant: bool
    prohibited_found: list[str]
    readability: float
    words: int
    within_length: bool
    consistent: bool
    seconds: float
    error: str | None = None

    @property
    def passes(self) -> bool:
        """Un aviso solo sirve si es fiel, cumple y es legible."""
        return (
            self.error is None
            and self.faithfulness >= 0.75
            and self.compliant
            and self.within_length
            and self.consistent
        )

    def as_dict(self) -> dict:
        return asdict(self)


def faithfulness(text: str, reasons: list[Reason], language: str = "es") -> Faithfulness:
    """Compara el texto contra las razones que SHAP realmente atribuyó."""
    norm_text = _norm(text)
    attr = "label_es" if language == "es" else "label_en"

    citadas = {getattr(r, attr) for r in reasons}
    presentes = {
        label
        for label in citadas
        if _content_words(label) and _content_words(label) & set(re.findall(r"\w+", norm_text))
    }
    recall = len(presentes) / len(citadas) if citadas else 1.0

    # Un factor "alucinado" es una etiqueta del vocabulario del modelo que NO
    # estuvo entre las razones y aun asi aparece en el texto. Solo se buscan
    # etiquetas conocidas: cualquier otra frase es redaccion, no un factor.
    idx = 0 if language == "es" else 1
    otras = {v[idx] for v in FEATURE_LABELS.values()} - citadas
    alucinadas = [
        label for label in otras if _content_words(label) <= set(re.findall(r"\w+", norm_text))
    ]
    total_mencionados = len(presentes) + len(alucinadas)
    precision = len(presentes) / total_mencionados if total_mencionados else 1.0

    return Faithfulness(
        recall=recall,
        precision=precision,
        hallucinated=sorted(alucinadas),
        missing=sorted(citadas - presentes),
    )


def _contains_term(norm_text: str, term: str) -> bool:
    """Busca el termino con LIMITES DE PALABRA.

    La comparacion por subcadena da falsos positivos que importan: "la
    ANTIGUEDAD del negocio" contiene "edad", y con subcadena la propia plantilla
    del Apendice C fallaba el chequeo de cumplimiento. Un control que bloquea
    avisos correctos se termina desactivando, que es peor que no tenerlo.
    """
    # Los limites se construyen desde una constante para no depender de que la
    # secuencia \b sobreviva a las capas de escape de quien edite este archivo:
    # escrita como cadena normal, "\b" es un BACKSPACE, no un limite de palabra,
    # y el chequeo deja de encontrar nada sin fallar ruidosamente.
    return re.search(WORD_BOUNDARY + re.escape(_norm(term)) + WORD_BOUNDARY, norm_text) is not None


def compliance(text: str) -> tuple[bool, list[str]]:
    """Bases prohibidas por Reg B presentes en el texto."""
    norm = _norm(text)
    hallados = sorted({t for t in PROHIBITED_TERMS if _contains_term(norm, t)})
    return (not hallados), hallados


def _syllables_es(word: str) -> int:
    """Conteo aproximado de sílabas en español: grupos vocálicos."""
    return max(1, len(re.findall(r"[aeiouáéíóúü]+", _norm(word))))


def readability(text: str, language: str = "es") -> float:
    """Índice de legibilidad. 0-100, más alto = más fácil.

    Español: Fernández-Huerta. Inglés: Flesch Reading Ease.
    Usar la fórmula anglosajona sobre español penaliza sin motivo: el español
    tiene más sílabas por palabra por construcción del idioma, no por dificultad.
    """
    frases = max(1, len(re.findall(r"[.!?]+", text)))
    palabras = re.findall(r"\w+", text)
    if not palabras:
        return 0.0
    silabas = sum(_syllables_es(w) for w in palabras)
    n = len(palabras)

    if language == "es":
        return 206.84 - 60.0 * (silabas / n) - 1.02 * (n / frases)
    return 206.835 - 1.015 * (n / frases) - 84.6 * (silabas / n)


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def evaluate(
    text: str,
    reasons: list[Reason],
    *,
    provider: str,
    language: str = "es",
    seconds: float = 0.0,
    second_run: str | None = None,
    error: str | None = None,
) -> EvalResult:
    """Evalúa un aviso. `second_run` permite medir consistencia."""
    if error or not text.strip():
        return EvalResult(
            provider=provider,
            language=language,
            faithfulness=0.0,
            recall=0.0,
            precision=0.0,
            hallucinated=[],
            compliant=False,
            prohibited_found=[],
            readability=0.0,
            words=0,
            within_length=False,
            consistent=False,
            seconds=seconds,
            error=error or "salida vacia",
        )

    f = faithfulness(text, reasons, language)
    ok, hallados = compliance(text)
    n = word_count(text)

    return EvalResult(
        provider=provider,
        language=language,
        faithfulness=round(f.score, 4),
        recall=round(f.recall, 4),
        precision=round(f.precision, 4),
        hallucinated=f.hallucinated,
        compliant=ok,
        prohibited_found=hallados,
        readability=round(readability(text, language), 1),
        words=n,
        within_length=n <= MAX_WORDS,
        # Sin segunda corrida no se puede afirmar consistencia; se asume True
        # solo para la plantilla, que es determinista por construccion.
        consistent=(second_run is None and provider == "template")
        or (second_run is not None and _norm(second_run) == _norm(text)),
        seconds=round(seconds, 2),
    )
