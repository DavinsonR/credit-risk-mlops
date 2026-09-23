"""Ninguna clave puede llegar a un artefacto.

EL INCIDENTE. La API de Gemini toma la clave en la QUERY STRING. Un 404 de
`requests` trae la URL completa dentro del texto de la excepcion, ese texto se
guardaba tal cual en `Generation.error`, y de ahi viajaba a
`exports/llm_evals_detail.csv`, `llm_evals.json` y `llm_fallback_analysis.csv`.
**Esos tres archivos se commitean.**

Paso de verdad: una clave real quedo impresa en consola y escrita en los tres. No
llego a git porque se detecto antes del commit, y eso no es un control -- es suerte.

Y EL ARREGLO NACIO ROTO. La primera version del redactor usaba `"\\b"` dentro de una
cadena NO RAW: eso es el caracter BACKSPACE, no un limite de palabra, asi que el
regex de claves sueltas no detectaba nada. Es el defecto 4 de la bitacora repetido
dentro del arreglo de seguridad, que es el peor sitio posible para repetirlo.

Por eso estos tests existen y por eso uno de ellos comprueba el patron compilado y no
solo el comportamiento: un regex que no encuentra nada se ve igual que un texto sin
secretos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from crmlops.llm.providers import _CLAVE_SUELTA, _SECRETO, redactar

REPO = Path(__file__).resolve().parents[1]

# Formatos reales, con la forma que tienen de verdad. Los valores son inventados.
GROQ = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
GEMINI_VIEJO = "AIza" + "SyD1234567890abcdefghijklmnopqrs"
GEMINI_NUEVO = "AQ.Ab8" + "RN6Jv6ganEo_8pCLXq8uEaMjI8yAWVyFP96guCMZj065nNg"


@pytest.mark.parametrize("clave", [GROQ, GEMINI_VIEJO, GEMINI_NUEVO])
@pytest.mark.parametrize(
    "plantilla",
    [
        "HTTPError: 404 for url: https://x/v1beta/models/m:generateContent?key={c}",
        "Unauthorized: Bearer {c}",
        "algo fallo con la clave {c} en medio del texto",
        "{c}",
        "api_key={c}&otra=cosa",
    ],
)
def test_ninguna_forma_de_clave_sobrevive(clave, plantilla):
    salida = redactar(plantilla.format(c=clave))
    assert clave not in salida, f"la clave sobrevivio: {salida}"
    assert "[REDACTADO]" in salida


def test_el_limite_de_palabra_es_un_limite_de_palabra():
    """El patron NO puede empezar con el caracter backspace.

    Es la comprobacion que habria atrapado el bug de la primera version. El
    comportamiento solo no basta: un regex roto y un texto limpio dan el mismo
    resultado visible.
    """
    assert "\x08" not in _CLAVE_SUELTA.pattern, (
        r'el patron empieza con BACKSPACE: alguien escribio "\b" en una cadena no-raw'
    )
    assert _CLAVE_SUELTA.pattern.startswith("\\b")
    assert "\x08" not in _SECRETO.pattern


def test_un_error_sin_secretos_no_se_toca():
    """Redactar de mas destruye el diagnostico, que es para lo que existe el campo."""
    for texto in (
        "ConnectionError: connection refused",
        "HTTPError: 503 Server Error: Service Unavailable",
        "salida vacia",
        "demasiado largo (180 > 150 palabras)",
    ):
        assert redactar(texto) == texto


def test_una_palabra_corta_no_se_confunde_con_una_clave():
    """`key=` seguido de algo corto es un parametro, no un secreto."""
    assert redactar("sort_key=asc") == "sort_key=asc"


def test_los_artefactos_commiteados_no_tienen_claves():
    """El control de verdad: mirar lo que se va a subir.

    Cubre los tres archivos donde la clave llego de verdad, y cualquier otro export
    que aparezca despues sin que nadie se acuerde de este test.
    """
    patrones = re.compile(r"(gsk_[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_\-]{20,}|AQ\.[A-Za-z0-9_\-]{20,})")
    sospechosos = []
    for archivo in sorted((REPO / "exports").rglob("*")):
        if not archivo.is_file() or archivo.suffix not in {".json", ".csv", ".md", ".txt"}:
            continue
        texto = archivo.read_text(encoding="utf-8", errors="ignore")
        if patrones.search(texto):
            sospechosos.append(str(archivo.relative_to(REPO)))
    assert not sospechosos, f"hay claves en artefactos que se commitean: {sospechosos}"


def test_el_env_no_esta_trackeado():
    """`.env` lleva las claves y `.gitignore` tiene que cubrirlo.

    `git add -f` lo salta igual, pero eso ya es una decision explicita de alguien.
    """
    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "!.env.example" in gitignore, "el ejemplo SI tiene que subirse"


def test_el_ejemplo_no_trae_una_clave_de_verdad():
    """`.env.example` se commitea: es el sitio mas facil de contaminar."""
    ejemplo = REPO / ".env.example"
    if not ejemplo.exists():
        pytest.skip("no hay .env.example")
    # Se usa el parser de verdad en vez de un regex sobre el texto crudo: la primera
    # version pegaba las lineas con un replace y leia "FRED_API_KEY=CENSUS_API_KEY="
    # como si la primera tuviera valor. El test fallaba con el archivo correcto.
    from crmlops.env import parse

    con_valor = {k: v for k, v in parse(ejemplo.read_text(encoding="utf-8")).items() if v}
    assert not con_valor, f"`.env.example` trae valores y se commitea: {sorted(con_valor)}"


def test_el_export_del_harness_declara_el_proveedor_sin_la_clave():
    """Si el harness corrio, su JSON no puede traer nada que parezca un secreto."""
    ruta = REPO / "exports" / "llm_evals.json"
    if not ruta.exists():
        pytest.skip("no hay corrida del harness")
    crudo = ruta.read_text(encoding="utf-8")
    json.loads(crudo)
    assert "gsk_" not in crudo
    assert "key=AQ." not in crudo
    assert "key=AIza" not in crudo
