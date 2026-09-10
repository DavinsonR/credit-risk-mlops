"""Un extra opcional no puede ser obligatorio de hecho.

`neural` (PyTorch, 507 MB en disco) es opcional en `pyproject.toml`, pero
`train.py` lo importaba en la cabecera del módulo. Como `train_economics`,
`evaluation.stress` y `export.onnx` importan de ahí dos constantes
—`PRODUCTION_CALIBRATOR` y `TARGET`—, los cuatro morían con el mismo
`ModuleNotFoundError: No module named 'torch'`, y tres de ellos por una
dependencia que no usan en ningún momento.

Se descubrió corriendo `run all` en un clon recién instalado con `setup`, que
instala solo el extra `dev`. O sea: **siguiendo la propia guía de instalación**.

Estos tests bloquean `torch` con un finder y comprueban que los módulos importen
igual. En CI el extra `neural` no se instala, así que la ausencia es real; en local
el finder la reproduce.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

# Niega `torch` de verdad. La primera versión usaba `sys.modules["torch"] = None`
# y no servía: scipy hace `getattr(sys.modules.get("torch"), "Tensor")` y con la
# entrada puesta a None revienta con un AttributeError que NO ocurre cuando torch
# simplemente no está. La simulación mentía en la dirección peligrosa.
BLOQUEA_TORCH = """
import importlib.abc, sys

class BloqueaTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "torch" or fullname.startswith("torch."):
            raise ModuleNotFoundError(f"No module named '{fullname}'", name=fullname)
        return None

sys.meta_path.insert(0, BloqueaTorch())
assert "torch" not in sys.modules
"""

SIN_EXTRA = ["crmlops.models.train", "crmlops.models.train_economics"]


def _corre(codigo: str) -> subprocess.CompletedProcess[str]:
    """En subproceso: el finder no debe contaminar la sesión de pytest."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(codigo)],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("modulo", SIN_EXTRA)
def test_importa_sin_el_extra_neural(modulo):
    r = _corre(f"{BLOQUEA_TORCH}\nimport {modulo}\nprint('ok')")
    assert r.returncode == 0, f"{modulo} exige torch sin usarlo:\n{r.stderr}"


def test_stress_importa_sin_el_extra_neural():
    r = _corre(f"{BLOQUEA_TORCH}\nimport crmlops.evaluation.stress\nprint('ok')")
    assert r.returncode == 0, r.stderr


def test_el_export_onnx_importa_sin_el_extra_neural():
    pytest.importorskip("onnxruntime", reason="requiere el extra onnx")
    r = _corre(f"{BLOQUEA_TORCH}\nimport crmlops.export.onnx\nprint('ok')")
    assert r.returncode == 0, r.stderr


def test_entrenar_sin_torch_explica_como_arreglarlo():
    """Falla, pero con instrucciones. Un traceback de import no le sirve a nadie."""
    r = _corre(
        BLOQUEA_TORCH
        + "\nfrom crmlops.features.spec import load_spec"
        + "\nfrom crmlops.models.train import build_models"
        + "\nbuild_models(42, load_spec())\n"
    )
    assert r.returncode != 0, "entrenar sin torch debería fallar"
    salida = r.stdout + r.stderr
    assert "extra" in salida and "neural" in salida, salida
    assert "uv sync --extra dev --extra neural" in salida, salida
    assert "Traceback" not in salida.split("Falta PyTorch")[-1], (
        "el mensaje debe reemplazar al traceback, no acompañarlo"
    )
