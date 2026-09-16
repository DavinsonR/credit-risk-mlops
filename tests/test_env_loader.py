"""`.env` se lee de verdad.

EL DEFECTO QUE ESTE ARCHIVO EVITA. `.env.example` decia "Copiar a .env", el harness
imprimia "claves en .env; ver .env.example", y ningun modulo leia ese archivo. Seguir
la instruccion oficial del repo dejaba Groq y Gemini en "no disponibles", sin error y
sin pista: la unica salida visible era la misma que si no existiera el archivo.

Es la familia de siempre --una instruccion que no se puede ejecutar-- y ya costo un
defecto en la semana de la instalacion. Estos tests son el control que faltaba.
"""

from __future__ import annotations

import os

import pytest

from crmlops import env as envmod


def test_parsea_las_cuatro_reglas_del_formato():
    d = envmod.parse(
        "\n".join(
            [
                "# comentario",
                "",
                "GROQ_API_KEY=gsk_abc123",
                'GEMINI_API_KEY="quoted"',
                "export FRED_API_KEY='exported'",
                "  CENSUS_API_KEY = con espacios  ",
                "esta linea no tiene igual",
            ]
        )
    )
    assert d == {
        "GROQ_API_KEY": "gsk_abc123",
        "GEMINI_API_KEY": "quoted",
        "FRED_API_KEY": "exported",
        "CENSUS_API_KEY": "con espacios",
    }


def test_una_linea_rota_no_impide_arrancar():
    """Un `.env` a medio escribir no debe reventar el import de los proveedores."""
    assert envmod.parse("BASURA\n=sin_clave\nOK=1") == {"OK": "1"}


def test_carga_al_entorno(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("GROQ_API_KEY=gsk_desde_archivo\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    aplicadas = envmod.load(f)
    assert aplicadas == {"GROQ_API_KEY": "gsk_desde_archivo"}
    assert os.environ["GROQ_API_KEY"] == "gsk_desde_archivo"


def test_el_entorno_real_le_gana_al_archivo(tmp_path, monkeypatch):
    """Quien exporto la variable a mano --o la puso como secreto de CI-- decidio.

    Que un archivo del disco pise esa decision es la clase de sorpresa que hace
    perder una tarde: la clave correcta esta en el shell y el repo usa otra.
    """
    f = tmp_path / ".env"
    f.write_text("GROQ_API_KEY=del_archivo\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "del_entorno")
    assert envmod.load(f) == {}
    assert os.environ["GROQ_API_KEY"] == "del_entorno"
    assert envmod.load(f, override=True) == {"GROQ_API_KEY": "del_archivo"}


def test_una_clave_vacia_no_cuenta_como_configurada(tmp_path, monkeypatch):
    """`.env.example` trae `GROQ_API_KEY=` sin valor. Copiarlo tal cual no puede
    hacer que el proveedor se declare disponible."""
    f = tmp_path / ".env"
    f.write_text("GROQ_API_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert envmod.load(f) == {}
    assert "GROQ_API_KEY" not in os.environ


def test_sin_archivo_no_falla(tmp_path):
    assert envmod.load(tmp_path / "no-existe") == {}


def test_los_proveedores_hospedados_leen_el_entorno(monkeypatch):
    """La cadena completa: variable presente -> el proveedor se declara disponible.

    Sin esto, el loader podria funcionar y seguir sin conectarse con quien lo
    necesita, que es exactamente lo que pasaba.
    """
    from crmlops.llm.providers import GeminiProvider, GroqProvider

    for cls, clave in ((GroqProvider, "GROQ_API_KEY"), (GeminiProvider, "GEMINI_API_KEY")):
        monkeypatch.delenv(clave, raising=False)
        assert not cls().available()
        monkeypatch.setenv(clave, "una-clave")
        assert cls().available()


def test_el_ejemplo_declara_las_dos_claves_del_harness():
    from crmlops.config import repo_root

    ejemplo = repo_root() / ".env.example"
    if not ejemplo.exists():
        pytest.skip("no hay .env.example")
    d = envmod.parse(ejemplo.read_text(encoding="utf-8"))
    for clave in ("GROQ_API_KEY", "GEMINI_API_KEY"):
        assert clave in d, f"{clave} no esta en .env.example y el harness la busca"
