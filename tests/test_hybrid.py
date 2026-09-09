"""El híbrido nunca puede ser peor que la plantilla.

Esa es toda su garantía, y es la que hay que probar: si el modelo no está, si
alucina, si omite una razón o si se niega, el sistema devuelve la plantilla y
emite un aviso legalmente válido igual.

Un fallback que solo se probó cuando el modelo funcionaba no es un fallback.
"""

from __future__ import annotations

import pytest

from crmlops.explain.reasons import Reason
from crmlops.llm.adverse_action import NoticeRequest
from crmlops.llm.evals import MAX_WORDS
from crmlops.llm.hybrid import generate, validate_rewrite
from crmlops.llm.providers import Generation, Provider, TemplateProvider


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
def request_es(razones) -> NoticeRequest:
    return NoticeRequest(amount=250_000, reasons=razones, language="es")


class FakeProvider(Provider):
    """Proveedor controlado: devuelve exactamente lo que se le indique."""

    name = "fake"
    model = "fake"

    def __init__(self, salida: str = "", error: str | None = None) -> None:
        self.salida = salida
        self.error = error

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, **kw) -> str:
        if self.error:
            raise RuntimeError(self.error)
        return self.salida

    def run(self, prompt: str, **kw) -> Generation:
        if self.error:
            return Generation(self.name, self.model, "", 0.0, self.error)
        return Generation(self.name, self.model, self.salida, 0.1)


# --- validacion de la reescritura ---


def test_acepta_una_reescritura_fiel(request_es, razones):
    ok, motivo = validate_rewrite(request_es.build_template(), razones, "es")
    assert ok, motivo


def test_rechaza_si_omite_una_razon(razones):
    parcial = "Su solicitud fue negada por la antigüedad del negocio."
    ok, motivo = validate_rewrite(parcial, razones, "es")
    assert not ok
    assert "omitidas" in motivo


def test_rechaza_si_inventa_un_factor(request_es, razones):
    inflado = request_es.build_template() + " También pesó la garantía colateral aportada."
    ok, motivo = validate_rewrite(inflado, razones, "es")
    assert not ok
    assert "inventados" in motivo


def test_rechaza_una_base_prohibida(request_es, razones):
    malo = request_es.build_template() + " Se consideró su edad."
    ok, motivo = validate_rewrite(malo, razones, "es")
    assert not ok
    assert "prohibidas" in motivo


def test_rechaza_un_texto_demasiado_largo(razones):
    ok, motivo = validate_rewrite("palabra " * (MAX_WORDS + 20), razones, "es")
    assert not ok
    assert "largo" in motivo


def test_rechaza_una_salida_vacia(razones):
    ok, motivo = validate_rewrite("   ", razones, "es")
    assert not ok
    assert motivo == "salida vacia"


# --- la garantia: nunca peor que la plantilla ---


def test_si_el_modelo_falla_devuelve_la_plantilla(request_es):
    r = generate(request_es, FakeProvider(error="ConnectionError: sin red"))
    assert not r.used_llm
    assert r.text == request_es.build_template()
    assert r.rejection_reason


def test_si_el_modelo_omite_una_razon_devuelve_la_plantilla(request_es):
    r = generate(request_es, FakeProvider(salida="Negado por la antigüedad del negocio."))
    assert not r.used_llm
    assert r.text == request_es.build_template()
    assert "omitidas" in r.rejection_reason


def test_si_el_modelo_alucina_devuelve_la_plantilla(request_es):
    inflado = request_es.build_template() + " Y la garantía colateral aportada."
    r = generate(request_es, FakeProvider(salida=inflado))
    assert not r.used_llm
    assert "inventados" in r.rejection_reason


def test_si_el_modelo_se_niega_devuelve_la_plantilla(request_es):
    """El caso real: llama3.2:3b rechaza redactar avisos de crédito en español."""
    r = generate(request_es, FakeProvider(salida="No puedo ayudarte con eso."))
    assert not r.used_llm
    assert r.text == request_es.build_template()


def test_acepta_una_reescritura_valida(request_es, razones):
    """Si el modelo hace bien su trabajo, su texto SÍ se usa."""
    buena = (
        "Su solicitud de $250,000 no fue aprobada. Las razones fueron la "
        "antigüedad del negocio y la tasa de interés inicial. Puede pedir la "
        "información específica que usamos. La ley prohíbe discriminar a quienes "
        "solicitan crédito."
    )
    r = generate(request_es, FakeProvider(salida=buena))
    assert r.used_llm
    assert r.text == buena


def test_con_la_plantilla_como_proveedor_no_llama_a_nadie(request_es):
    r = generate(request_es, TemplateProvider())
    assert not r.used_llm
    assert r.rejection_reason is None
    assert r.seconds == 0.0


@pytest.mark.parametrize("lang", ["es", "en"])
def test_el_fallback_funciona_en_ambos_idiomas(razones, lang):
    req = NoticeRequest(amount=250_000, reasons=razones, language=lang)
    r = generate(req, FakeProvider(error="timeout"))
    assert r.text == req.build_template()
    assert not r.used_llm
