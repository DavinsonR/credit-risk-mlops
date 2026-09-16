"""Carga de `.env`, sin dependencia nueva.

EL DEFECTO QUE ESTE MODULO CIERRA. `.env.example` decia "Copiar a .env", el harness
imprimia "claves en .env; ver .env.example", y **nada leia ese archivo**. Los
proveedores hacen `os.environ.get("GROQ_API_KEY", "")`, que solo ve variables de
entorno reales. Crear el `.env` y correr el harness dejaba Groq y Gemini en "no
disponibles" -- sin error, sin aviso, con la instruccion oficial del repo seguida al
pie de la letra.

Es el modo de fallo de siempre: una instruccion que no se puede ejecutar y un control
que informa ausencia cuando lo que hay es un archivo no leido.

POR QUE NO `python-dotenv`. El presupuesto del proyecto es cero y la dependencia
tampoco es gratis en otro sentido: son treinta lineas de parseo para un formato de
cuatro reglas. Estas treinta se pueden leer enteras en un minuto, que es lo que el
proyecto pide de cualquier control.

LO QUE NO HACE. No sobreescribe una variable que ya exista en el entorno. Si alguien
exporto `GROQ_API_KEY` en su shell o la puso como secreto de CI, esa gana: el archivo
del disco no debe pisar lo que el operador decidio explicitamente.
"""

from __future__ import annotations

import os
from pathlib import Path

from crmlops.config import repo_root

ENV_FILE = ".env"


def parse(texto: str) -> dict[str, str]:
    """Las cuatro reglas del formato, y ninguna mas.

    `CLAVE=valor` por linea; `#` inicia comentario de linea completa; se permite el
    prefijo `export`; y las comillas envolventes se quitan. Una linea sin `=` se
    ignora en vez de reventar: un `.env` a medio escribir no debe impedir arrancar.
    """
    fuera: dict[str, str] = {}
    for linea in texto.splitlines():
        s = linea.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        clave, _, valor = s.partition("=")
        clave = clave.removeprefix("export ").strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if clave:
            fuera[clave] = valor
    return fuera


def load(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Vuelca `.env` en os.environ. Devuelve lo que efectivamente aplico."""
    archivo = path or (repo_root() / ENV_FILE)
    if not archivo.exists():
        return {}
    aplicadas = {}
    for clave, valor in parse(archivo.read_text(encoding="utf-8")).items():
        if not valor:
            continue
        if override or clave not in os.environ:
            os.environ[clave] = valor
            aplicadas[clave] = valor
    return aplicadas
