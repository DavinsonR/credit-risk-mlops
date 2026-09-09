"""Adquisición del dataset SBA 7(a) FOIA.

El portal de SBA renombra los archivos cada trimestre con un sufijo de vintage
(``asof_YYMMDD``). Hardcodear las URLs rompe el pipeline cada 90 dias, asi que
aqui se DESCUBREN desde la pagina del dataset. Ver docs/adr/0001.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from crmlops.config import load_config, resolve_path

TIMEOUT = 60
CHUNK = 1 << 20  # 1 MiB
_HREF_RE = re.compile(r'https?://[^"\'<>\s]+', re.IGNORECASE)


@dataclass(frozen=True)
class Resource:
    """Un archivo descargable descubierto en la pagina del dataset."""

    filename: str
    url: str
    fiscal_years: str  # p.ej. "FY2010_FY2019"

    @property
    def vintage(self) -> str:
        """Sufijo ``asof_YYMMDD`` que identifica la version del corte."""
        m = re.search(r"asof_(\d{6})", self.filename)
        return m.group(1) if m else "unknown"


def discover(source: str = "sba_7a") -> list[Resource]:
    """Descubre los CSV del dataset scrapeando la pagina oficial."""
    cfg = load_config()["sources"][source]
    resp = requests.get(cfg["dataset_page"], timeout=TIMEOUT)
    resp.raise_for_status()

    pattern = re.compile(cfg["file_pattern"])
    found: dict[str, Resource] = {}
    for url in _HREF_RE.findall(resp.text):
        name = url.rsplit("/", 1)[-1]
        if not pattern.search(name):
            continue
        fy = re.search(r"(FY\d{4}(?:_(?:FY\d{4}|Present))?)", name)
        found[name] = Resource(
            filename=name,
            url=url,
            fiscal_years=fy.group(1) if fy else "unknown",
        )

    if not found:
        raise RuntimeError(
            f"No se descubrio ningun recurso en {cfg['dataset_page']} "
            f"con el patron {cfg['file_pattern']!r}. La pagina pudo cambiar de "
            "estructura: revisar docs/adr/0001."
        )
    return sorted(found.values(), key=lambda r: r.filename)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def download(res: Resource, dest_dir: Path, *, force: bool = False) -> tuple[Path, str]:
    """Descarga un recurso si falta y devuelve (ruta, sha256)."""
    dest = dest_dir / res.filename
    if dest.exists() and not force:
        return dest, _sha256(dest)

    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(res.url, stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(CHUNK):
                fh.write(chunk)
    tmp.replace(dest)
    return dest, _sha256(dest)


def acquire(*, force: bool = False, source: str = "sba_7a") -> dict:
    """Descarga todos los recursos y escribe el manifiesto de vintages.

    El manifiesto SI se commitea (es pequeno y fija la reproducibilidad);
    los CSV NO.
    """
    raw_dir = resolve_path("raw")
    manifest_dir = resolve_path("manifests")

    entries = []
    for res in discover(source):
        path, digest = download(res, raw_dir, force=force)
        entries.append(
            {
                **asdict(res),
                "vintage": res.vintage,
                "sha256": digest,
                "bytes": path.stat().st_size,
            }
        )
        print(f"  {res.filename}  {path.stat().st_size / 1048576:8.1f} MB  {digest[:12]}")

    manifest = {
        "source": source,
        "acquired_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "resources": entries,
    }
    out = manifest_dir / f"{source}.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nManifiesto -> {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}"
    )
    return manifest


def verify(source: str = "sba_7a") -> bool:
    """Revalida los SHA256 locales contra el manifiesto commiteado."""
    manifest_path = resolve_path("manifests") / f"{source}.json"
    if not manifest_path.exists():
        print(f"No hay manifiesto en {manifest_path}; corre `make acquire` primero.")
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_dir = resolve_path("raw")
    ok = True
    for entry in manifest["resources"]:
        path = raw_dir / entry["filename"]
        if not path.exists():
            print(f"  FALTA    {entry['filename']}")
            ok = False
        elif (digest := _sha256(path)) != entry["sha256"]:
            print(
                f"  MISMATCH {entry['filename']}  esperado {entry['sha256'][:12]} vs {digest[:12]}"
            )
            ok = False
        else:
            print(f"  OK       {entry['filename']}")
    return ok


if __name__ == "__main__":
    acquire()
