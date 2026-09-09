"""Copia el artefacto ONNX al demo web.

Los binarios no se versionan dos veces: `exports/onnx/` es la fuente y
`serving/web/` recibe una copia al construir. Asi no hay riesgo de que el demo
sirva un modelo viejo porque alguien olvido actualizar la copia.
"""

from __future__ import annotations

import shutil
import sys

from crmlops.config import repo_root


def main() -> int:
    src = repo_root() / "exports" / "onnx"
    dst = repo_root() / "serving" / "web"
    if not (src / "model.onnx").exists():
        print("Falta el export. Correr: uv run python -m crmlops.export.onnx")
        return 1
    for name in ("model.onnx", "contract.json"):
        shutil.copy2(src / name, dst / name)
        print(f"  {name}  {(dst / name).stat().st_size / 1024:,.0f} KB")
    print(f"\nDemo listo en {dst.relative_to(repo_root())}/index.html")
    print("Servir con: uv run python -m http.server 8899 --directory serving/web")
    return 0


if __name__ == "__main__":
    sys.exit(main())
