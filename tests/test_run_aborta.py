"""`run all` tiene que detenerse en la primera etapa que falle.

El defecto que motiva este archivo terminó **en verde**: con `train` reventando
por falta de torch, la tubería siguió adelante e imprimió
`APROBADO: 8 gates pasaron.` Los gates leen el `exports/metrics.json` commiteado,
así que pasaron sin que existiera un modelo nuevo.

La causa: `$ErrorActionPreference = "Stop"` NO cubre los comandos nativos. Un
scriptblock con varios `uv run ...` sigue después de que uno devuelva un código
distinto de cero, y el `exit $LASTEXITCODE` final reporta el del ÚLTIMO comando.

Una tubería que reporta éxito cuando su primera etapa falló es peor que una que no
reporta nada: da por auditado un modelo que no se entrenó.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUN_CMD = REPO / "run.cmd"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="run.cmd es el entry point de Windows"
)


@pytest.fixture
def uv_que_falla(tmp_path: Path) -> dict[str, str]:
    """Un `uv` falso que siempre sale con 1, al frente del PATH.

    Hace determinista la primera etapa: no depende de que falten datos, ni de
    torch, ni de la red.
    """
    (tmp_path / "uv.cmd").write_text(
        "@echo off\r\necho FAKE UV: fallo simulado 1>&2\r\nexit /b 1\r\n",
        encoding="ascii",
    )
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    return env


def test_all_no_sigue_despues_de_que_falle_train(uv_que_falla):
    r = subprocess.run(
        [str(RUN_CMD), "all"],
        cwd=REPO,
        env=uv_que_falla,
        capture_output=True,
        text=True,
    )
    salida = r.stdout + r.stderr

    assert r.returncode != 0, f"`run all` reportó éxito con train roto:\n{salida}"
    assert "FALLO en 'train'" in salida, salida

    # Lo que de verdad importa: que NO haya llegado a los gates. Ese era el
    # mensaje tranquilizador que aparecía después del fallo.
    assert "GATES DE PROMOCION" not in salida, "corrió los gates tras fallar train"
    assert "APROBADO" not in salida, "declaró aprobado un modelo que no se entrenó"


def test_lint_tampoco_encadena_con_punto_y_coma(uv_que_falla):
    """Mismo defecto, otra tarea: `ruff check` en rojo seguido de format en verde
    devolvía exit 0."""
    r = subprocess.run(
        [str(RUN_CMD), "lint"],
        cwd=REPO,
        env=uv_que_falla,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "FALLO en 'ruff check'" in (r.stdout + r.stderr)
