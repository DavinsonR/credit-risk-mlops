"""Carga de la superficie declarativa (config.yaml)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    """Raíz del repo, resuelta desde este archivo (no desde el cwd)."""
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else repo_root() / "config.yaml"
    with cfg_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_path(key: str) -> Path:
    """Resuelve una entrada de `paths:` a ruta absoluta, creando el directorio."""
    cfg = load_config()
    p = repo_root() / cfg["paths"][key]
    p.mkdir(parents=True, exist_ok=True)
    return p
