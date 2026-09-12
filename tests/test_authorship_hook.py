"""El hook de autoría tiene que rechazar lo que dice rechazar.

La restricción del repo es que ningún commit lleve atribución a un asistente de
IA. Eso lo sostiene un archivo corto en `scripts/hooks/commit-msg` que hasta ahora
nunca se probó con un mensaje malo. Un control no verificado es una afirmación, no
un control -- el mismo argumento que este proyecto ya usó para justificar tests
sobre el harness de avisos.

Escribir estos tests encontró el defecto de inmediato: el hook **fallaba
abierto**. `grep` devuelve un código distinto de cero cuando no encuentra nada y
también cuando no pudo buscar, y la versión original no distinguía los dos casos.
Con `sh.exe` de Git for Windows y sin `/usr/bin` en el PATH, `grep` no existía, el
hook salía 0 y el trailer pasaba en silencio. Git lo invoca con su propio PATH,
así que en uso normal nunca se veía.

Hay dos defensas y cubren momentos distintos: el hook rechaza el commit ANTES de
que exista, y CI revisa el historial DESPUÉS del push. CI ya tiene su propio paso
en `ci.yml`; este archivo cubre el hook, incluido el caso contrario --que no
bloquee mensajes legítimos--, porque un control que rechaza commits válidos se
termina desactivando y entonces no protege nada.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "commit-msg"

TRAILER_CLAUDE = "Co-Authored-By: Claude <noreply@anthropic.com>"


def _find_shell() -> str | None:
    """Un `sh` con el que ejecutar el hook.

    La primera versión de este archivo solo miraba el PATH y en Windows los tests
    se saltaban en silencio: el control quedaba sin verificar justo en la máquina
    donde se hacen los commits. Git for Windows SIEMPRE trae su propio `sh.exe`,
    solo que no lo publica en el PATH -- así que se busca donde está.
    """
    for name in ("sh", "bash"):
        if p := shutil.which(name):
            return p
    if git := shutil.which("git"):
        raiz = Path(git).resolve().parent.parent  # ...\\Git\\cmd\\git.exe -> ...\\Git
        for rel in ("usr/bin/sh.exe", "bin/sh.exe", "usr/bin/bash.exe", "bin/bash.exe"):
            if (cand := raiz / rel).is_file():
                return str(cand)
    return None


SHELL = _find_shell()

pytestmark = pytest.mark.skipif(
    SHELL is None, reason="no se encontró sh/bash ni junto a git para ejecutar el hook"
)


def _env_utilizable() -> dict[str, str]:
    """PATH que incluye el directorio del propio `sh`, donde vive su `grep`.

    Sin esto el test mediría el fallo del entorno y no la lógica del hook.
    """
    env = dict(os.environ)
    if SHELL:
        env["PATH"] = str(Path(SHELL).parent) + os.pathsep + env.get("PATH", "")
    return env


def run_hook(
    mensaje: str,
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    escribir: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Ejecuta el hook como lo ejecuta git: ruta relativa, desde el directorio."""
    f = tmp_path / "COMMIT_EDITMSG"
    if escribir:
        f.write_text(mensaje, encoding="utf-8")
    return subprocess.run(
        [SHELL, str(HOOK), f.name],
        cwd=tmp_path,
        env=env if env is not None else _env_utilizable(),
        capture_output=True,
        text=True,
    )


def test_el_hook_existe():
    """Propiedad del REPO: vale en cualquier copia, con setup o sin el."""
    assert HOOK.is_file(), f"falta {HOOK}"


def test_core_hooksPath_apunta_al_hook():
    """Propiedad de la COPIA LOCAL, no del repo: solo es cierta despues de `setup`.

    ESTE TEST TUVO CI EN ROJO DESDE LA SEMANA 8 y no me di cuenta. Falla en
    cualquier clon que no haya corrido `setup`, que es exactamente lo que hace CI en
    cada push. Mientras tanto reporte "lint verde, N tests" en cinco mensajes de
    commit, mirando solo mi propia maquina -- donde `core.hooksPath` estaba
    configurado a mano desde la semana 1.

    Sexta vez del mismo patron en este proyecto: mi entorno tenia algo que el
    entorno de destino no tiene. Y esta vez el defecto estaba en el test, no en el
    codigo.

    El arreglo no fue saltarlo: `ci.yml` ahora corre la linea de `setup` que apunta
    el hook, asi que la propiedad se verifica donde se verifica todo lo demas. Si
    esto falla en tu clon, la respuesta esta en el mensaje: te falta `setup`.
    """
    configurado = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    assert configurado == "scripts/hooks", (
        f"core.hooksPath es {configurado!r} y deberia ser 'scripts/hooks'.\n"
        "En un clon nuevo: correr `.\\run setup` (Windows) o `make setup`.\n"
        "Sin eso, git ignora el hook de autoria y un trailer de IA solo se veria "
        "en CI, despues del push."
    )


def test_el_hook_esta_marcado_ejecutable_en_git():
    """En Linux y macOS git IGNORA un hook sin bit de ejecución, en silencio.

    Estuvo en modo 100644 desde el primer commit. En Windows funcionaba igual
    --Git for Windows no mira el bit-- así que el defecto era invisible en la
    máquina donde se hacen los commits y total en cualquier clon de Linux: la
    protección de autoría simplemente no corría.

    El modo se arregla con `git update-index --chmod=+x scripts/hooks/commit-msg`.
    """
    salida = subprocess.run(
        ["git", "ls-files", "-s", "scripts/hooks/commit-msg"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert salida, "el hook no está trackeado por git"
    assert salida[0] == "100755", (
        f"el hook está en modo {salida[0]}; git lo ignoraría en Linux y macOS. "
        "Arreglar con: git update-index --chmod=+x scripts/hooks/commit-msg"
    )


@pytest.mark.parametrize(
    "mensaje",
    [
        f"feat: algo\n\n{TRAILER_CLAUDE}\n",
        # Minúsculas: git no normaliza los trailers y el hook usa -i por eso.
        "fix: algo\n\nco-authored-by: claude opus 5 <noreply@anthropic.com>\n",
        "docs: algo\n\nCo-Authored-By: Anthropic <noreply@anthropic.com>\n",
        "chore: algo\n\nCo-authored-by: Copilot <copilot@github.com>\n",
        "chore: algo\n\nCo-Authored-By: GPT-5 <bot@example.com>\n",
        "feat: algo\n\n\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)\n",
        "feat: algo\n\nGenerated with Claude Code\n",
    ],
)
def test_rechaza_la_atribucion_a_ia(mensaje, tmp_path):
    r = run_hook(mensaje, tmp_path)
    assert r.returncode != 0, f"el hook dejó pasar:\n{mensaje}"
    assert "atribucion a IA" in r.stderr


@pytest.mark.parametrize(
    "mensaje",
    [
        # Mensajes reales del historial de este repo.
        "fix(llm): calentamiento antes de medir; dos conclusiones mias corregidas\n",
        "feat(llm): hibrido -- la plantilla fija los hechos, el LLM solo redacta\n",
        "docs: ADR 0009 -- la plantilla determinista gana al LLM\n",
        # El cuerpo puede nombrar a los modelos y proveedores evaluados: el
        # proyecto los compara, y bloquear eso haría inservible el hook.
        "docs: comparar Ollama local con la API de Anthropic en el ADR\n",
        "feat: brazo de Claude en el harness de avisos, detras de una clave opcional\n",
        # Un co-autor humano es legítimo y no debe bloquearse.
        "feat: algo\n\nCo-Authored-By: Alguien Real <alguien@example.com>\n",
    ],
)
def test_no_bloquea_mensajes_legitimos(mensaje, tmp_path):
    r = run_hook(mensaje, tmp_path)
    assert r.returncode == 0, f"el hook bloqueó indebidamente:\n{mensaje}\n{r.stderr}"


# --- falla cerrado: "no pude revisar" no es "esta limpio" ---


def test_falla_cerrado_si_el_mensaje_no_existe(tmp_path):
    r = run_hook("", tmp_path, escribir=False)
    assert r.returncode != 0
    assert "no puedo leer" in r.stderr


def test_falla_cerrado_sin_grep_en_el_path(tmp_path):
    """El defecto real que estos tests encontraron.

    Sin `grep`, la versión original salía 0 y aceptaba cualquier trailer sin
    imprimir nada. Ahora rechaza y dice por qué.
    """
    env = dict(os.environ)
    env["PATH"] = ""
    r = run_hook(f"feat: algo\n\n{TRAILER_CLAUDE}\n", tmp_path, env=env)
    assert r.returncode != 0, "sin grep el hook volvió a fallar abierto"
    assert "grep" in r.stderr
