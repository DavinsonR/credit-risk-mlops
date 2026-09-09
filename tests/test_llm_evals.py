"""El harness de avisos tiene que detectar lo que dice detectar.

Un eval que nunca se probó con una salida mala no mide nada: pasa siempre, y esa
apariencia de rigor es peor que no tener eval. Estos tests le dan al harness
textos deliberadamente defectuosos y verifican que los marque.
"""

from __future__ import annotations

import pytest

from crmlops.explain.reasons import Reason
from crmlops.llm.adverse_action import NoticeRequest
from crmlops.llm.evals import (
    MAX_WORDS,
    compliance,
    evaluate,
    faithfulness,
    readability,
)


@pytest.fixture
def razones() -> list[Reason]:
    return [
        Reason(
            "business_age",
            "la antigüedad del negocio",
            "the age of the business",
            0.45,
            "Startup",
            1,
        ),
        Reason(
            "initial_rate", "la tasa de interés inicial", "the initial interest rate", 0.43, 6.5, 2
        ),
    ]


@pytest.fixture
def aviso(razones) -> str:
    return NoticeRequest(amount=250_000, reasons=razones).build_template()


# --- fidelidad ---


def test_la_plantilla_es_fiel_por_construccion(aviso, razones):
    """No puede inventar un factor: rellena las razones que recibe."""
    f = faithfulness(aviso, razones)
    assert f.recall == 1.0
    assert f.precision == 1.0
    assert f.hallucinated == []


def test_detecta_un_factor_alucinado(aviso, razones):
    """Una razón inventada en un aviso legal es una afirmación falsa."""
    malo = aviso + "\nAdemás, la garantía colateral aportada fue insuficiente."
    f = faithfulness(malo, razones)
    assert "la garantía colateral aportada" in f.hallucinated
    assert f.precision < 1.0


def test_detecta_una_razon_omitida(razones):
    """Si el aviso calla una de las razones principales, no cumple Reg B."""
    parcial = "Su solicitud fue negada por la antigüedad del negocio."
    f = faithfulness(parcial, razones)
    assert f.recall < 1.0
    assert "la tasa de interés inicial" in f.missing


def test_la_media_armonica_castiga_el_desbalance(razones):
    """Recall alto con precisión baja no debe dar buena nota."""
    inflado = (
        "Se consideró la antigüedad del negocio, la tasa de interés inicial, "
        "la garantía colateral aportada, el sector de actividad del negocio "
        "y la ubicación del negocio."
    )
    f = faithfulness(inflado, razones)
    assert f.recall == 1.0
    assert f.score < 0.75  # la media armonica lo hunde


# --- cumplimiento ---


@pytest.mark.parametrize(
    "frase",
    [
        "Se consideró su edad.",
        "Consideramos la edad del solicitante.",
        "We considered the applicant age.",
        "Se evaluó su raza.",
        "Influyó su estado civil.",
        "Debido a una discapacidad.",
    ],
)
def test_bloquea_las_bases_prohibidas(frase):
    ok, hallados = compliance(frase)
    assert not ok, f"no bloqueó: {frase}"
    assert hallados


@pytest.mark.parametrize(
    "frase",
    [
        "La antigüedad del negocio es corta.",
        "Su antigüedad en el negocio influyó.",
        "El sector de actividad del negocio.",
        "La tasa de interés inicial.",
    ],
)
def test_permite_factores_legitimos(frase):
    """La ANTIGÜEDAD DEL NEGOCIO no es la EDAD DEL SOLICITANTE.

    La primera es un factor de suscripción legítimo; la segunda es una base
    protegida. La versión inicial las confundía por comparar subcadenas, y hacía
    fallar la propia plantilla del Apéndice C. Un control que bloquea avisos
    correctos se termina desactivando.
    """
    ok, hallados = compliance(frase)
    assert ok, f"bloqueó indebidamente: {frase} -> {hallados}"


def test_la_plantilla_cumple(aviso):
    ok, hallados = compliance(aviso)
    assert ok, hallados


# --- legibilidad ---


def test_el_indice_espanol_no_es_el_ingles():
    """El español tiene más sílabas por palabra por construcción del idioma.

    Aplicarle Flesch-Kincaid lo penaliza sin que sea más difícil de leer.
    """
    texto = "Su solicitud no fue aprobada. Las razones fueron dos."
    assert readability(texto, "es") != readability(texto, "en")


def test_un_texto_simple_puntua_mejor_que_uno_denso():
    simple = "Su solicitud fue negada. El negocio es nuevo. Puede pedir más datos."
    denso = (
        "La determinación adversa correspondiente a su solicitud de financiamiento "
        "se fundamentó en consideraciones relativas a la antigüedad operacional."
    )
    assert readability(simple, "es") > readability(denso, "es")


# --- resultado agregado ---


def test_un_aviso_correcto_pasa(aviso, razones):
    r = evaluate(aviso, razones, provider="template")
    assert r.passes


def test_un_aviso_demasiado_largo_no_pasa(razones):
    largo = "palabra " * (MAX_WORDS + 50)
    r = evaluate(largo, razones, provider="template")
    assert not r.within_length
    assert not r.passes


def test_una_salida_vacia_no_pasa_y_declara_el_error(razones):
    r = evaluate("", razones, provider="ollama")
    assert not r.passes
    assert r.error


def test_la_inconsistencia_entre_corridas_no_pasa(aviso, razones):
    """Un documento legal que cambia entre ejecuciones es indefendible."""
    r = evaluate(aviso, razones, provider="ollama", second_run="un texto distinto")
    assert not r.consistent
    assert not r.passes


def test_dos_corridas_identicas_si_pasan(aviso, razones):
    r = evaluate(aviso, razones, provider="ollama", second_run=aviso)
    assert r.consistent


# --- bilingüe ---


@pytest.mark.parametrize("lang", ["es", "en"])
def test_ambos_idiomas_generan_aviso_valido(razones, lang):
    texto = NoticeRequest(amount=250_000, reasons=razones, language=lang).build_template()
    r = evaluate(texto, razones, provider="template", language=lang)
    assert r.passes, r.as_dict()
