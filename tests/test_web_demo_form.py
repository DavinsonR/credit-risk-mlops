"""La demo del navegador tiene que poder enviarse tal como nace.

EL DEFECTO QUE ESTE ARCHIVO EVITA. El campo de la garantia SBA traia
`step="1000"` y `value="187500"` -- el 75% de 250.000, que es el porcentaje
estandar del 7(a) y por tanto el valor correcto. 187.500 no es multiplo de 1.000,
asi que el formulario nacia INVALIDO: pulsar "Calcular riesgo" no hacia nada y el
navegador mostraba una burbuja de validacion.

La demo estaba construida, el modelo ONNX cargaba, la paridad numerica estaba
verificada... y nadie la habia pulsado nunca. Es el mismo modo de fallo que el
resto de la bitacora --algo que reporta normalidad sin haberse ejercido-- pero en
la capa que un reclutador toca primero.

El test no ejecuta un navegador: replica las reglas de validacion de HTML sobre
los atributos del propio archivo. Es suficiente para lo unico que hay que
garantizar aqui: **el estado inicial es enviable**.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "serving" / "web" / "index.html"
INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')


def _inputs() -> list[dict[str, str]]:
    html = DEMO.read_text(encoding="utf-8")
    return [dict(ATTR_RE.findall(tag)) for tag in INPUT_RE.findall(html)]


@pytest.fixture(scope="module")
def numericos() -> list[dict[str, str]]:
    campos = [i for i in _inputs() if i.get("type") == "number"]
    assert campos, "la demo perdio sus campos numericos"
    return campos


def test_el_valor_por_defecto_respeta_su_propio_step(numericos):
    """La regla de HTML: (value - min) tiene que ser multiplo de step.

    Es exactamente la comprobacion que el navegador hace y que aqui fallaba.
    """
    for campo in numericos:
        paso = campo.get("step", "1")
        if paso == "any":
            continue
        valor = float(campo["value"])
        base = float(campo.get("min", 0))
        resto = (valor - base) % float(paso)
        assert min(resto, float(paso) - resto) < 1e-9, (
            f"#{campo.get('id')}: value={valor} no cae en la rejilla "
            f"min={base} step={paso}; el formulario nace invalido y el boton no responde"
        )


def test_el_valor_por_defecto_respeta_min_y_max(numericos):
    for campo in numericos:
        valor = float(campo["value"])
        if "min" in campo:
            assert valor >= float(campo["min"]), f"#{campo.get('id')} por debajo de min"
        if "max" in campo:
            assert valor <= float(campo["max"]), f"#{campo.get('id')} por encima de max"


def test_los_montos_no_viven_en_una_rejilla_arbitraria(numericos):
    """Un importe en dolares no tiene por que ser multiplo de nada.

    La tasa y los empleos si: 0.25 puntos y 1 empleo son unidades reales. El monto
    y la garantia no, y forzarlos fue lo que rompio la demo.
    """
    por_id = {c.get("id"): c for c in numericos}
    for campo in ("gross", "guar"):
        assert por_id[campo].get("step") == "any", (
            f"#{campo} volvio a tener un paso fijo: cualquier porcentaje de garantia "
            "que no caiga en la rejilla vuelve a dejar el formulario invalido"
        )


def test_la_garantia_no_puede_superar_al_monto(numericos):
    """El limite que SI importa esta validado, y no lo puede expresar el HTML.

    El modelo consume guarantee_pct = garantia / monto; por encima de 1 deja de
    significar nada. Como es una restriccion entre dos campos, el navegador no
    puede declararla: tiene que estar en el handler.
    """
    html = DEMO.read_text(encoding="utf-8")
    assert "gar > bruto" in html, "se perdio la validacion cruzada garantia <= monto"
    por_id = {c.get("id"): c for c in numericos}
    assert float(por_id["guar"]["value"]) <= float(por_id["gross"]["value"])


def test_el_aviso_de_uso_sigue_en_la_pagina():
    """La demo puntua credito. El aviso de que no es una decision automatica no es
    decoracion: es la misma linea que el reporte de validacion sostiene."""
    html = DEMO.read_text(encoding="utf-8")
    for frase in ("No es una decisión automática", "decisión humana", "VALIDATION_REPORT"):
        assert frase in html, f"la demo perdio: {frase}"


# --------------------------------------------------------------------------
# Bilingue: la pagina en ingles del portafolio no puede enlazar un formulario
# que solo habla espanol
# --------------------------------------------------------------------------
KEY_RE = re.compile(r'data-i18n(?:-html)?="([^"]+)"')
DICT_RE = re.compile(r"\n  (es|en): \{(.*?)\n  \},", re.DOTALL)
# Una clave arranca en principio de linea o despues de una coma o una llave. La
# primera version solo miraba el principio de linea, y el diccionario empaqueta
# varias claves por linea: el test daba por no traducidas dieciseis que si lo
# estaban. Un test que falla por como esta formateado el archivo no mide nada.
ENTRY_RE = re.compile(r"(?:^\s*|[{,]\s*)(\w+):", re.MULTILINE)


def _diccionarios() -> dict[str, set[str]]:
    html = DEMO.read_text(encoding="utf-8")
    return {lang: set(ENTRY_RE.findall(cuerpo)) for lang, cuerpo in DICT_RE.findall(html)}


def test_los_dos_idiomas_tienen_la_misma_forma():
    """El invariante que el sitio ya aplica a su diccionario, aquí también.

    Una clave presente en un idioma y ausente en el otro no falla: deja el texto
    original en pantalla, que es el modo de fallo silencioso de siempre.
    """
    d = _diccionarios()
    assert set(d) == {"es", "en"}, f"faltan idiomas: {sorted(d)}"
    assert d["es"] == d["en"], (
        f"solo en es: {sorted(d['es'] - d['en'])} · solo en en: {sorted(d['en'] - d['es'])}"
    )


def test_cada_clave_del_marcado_existe_en_los_dos_idiomas():
    html = DEMO.read_text(encoding="utf-8")
    usadas = set(KEY_RE.findall(html))
    assert usadas, "el marcado perdio sus claves de traduccion"
    d = _diccionarios()
    for lang in ("es", "en"):
        faltan = usadas - d[lang]
        assert not faltan, f"{lang} no traduce: {sorted(faltan)}"


def test_el_aviso_de_uso_esta_en_los_dos_idiomas():
    """El aviso no es decoración y no puede quedarse sin traducir: es la frase que
    impide leer la demo como una decisión de crédito."""
    html = DEMO.read_text(encoding="utf-8")
    assert "No es una decisión automática de crédito" in html
    assert "This is not an automated credit decision" in html
