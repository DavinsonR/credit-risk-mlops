"""Instala un JDK local al proyecto para PySpark.

PySpark necesita una JVM. En vez de exigir un JDK en el sistema --que en Windows
implica un instalador, permisos y una variable de entorno global-- se descarga uno
en `.jdk/` dentro del repo. Queda gitignoreado y no toca nada fuera del proyecto.

Es una decision de reproducibilidad: cualquiera que clone el repo corre un comando
y tiene el mismo JDK, sin instrucciones de instalacion que dependan del sistema
operativo de quien lea el README.
"""

from __future__ import annotations

import platform
import shutil
import sys
import zipfile
from pathlib import Path

import requests

from crmlops.config import repo_root

# Microsoft Build of OpenJDK 17: gratuito, sin registro, soporte a largo plazo.
# Spark 4 exige Java 17 o superior.
URLS = {
    ("Windows", "AMD64"): "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip",
    ("Linux", "x86_64"): "https://aka.ms/download-jdk/microsoft-jdk-17-linux-x64.tar.gz",
    ("Darwin", "arm64"): "https://aka.ms/download-jdk/microsoft-jdk-17-macos-aarch64.tar.gz",
    ("Darwin", "x86_64"): "https://aka.ms/download-jdk/microsoft-jdk-17-macos-x64.tar.gz",
}


def jdk_home() -> Path | None:
    """Ruta del JDK local si ya esta instalado."""
    root = repo_root() / ".jdk"
    if not root.exists():
        return None
    for candidate in root.iterdir():
        exe = candidate / "bin" / ("java.exe" if platform.system() == "Windows" else "java")
        if exe.exists():
            return candidate
    return None


def install(force: bool = False) -> Path:
    if (existing := jdk_home()) and not force:
        print(f"JDK ya instalado: {existing}")
        return existing

    key = (platform.system(), platform.machine())
    url = URLS.get(key)
    if url is None:
        raise RuntimeError(
            f"No hay JDK preconfigurado para {key}. "
            "Instalar Java 17+ manualmente y definir JAVA_HOME."
        )

    root = repo_root() / ".jdk"
    if force and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    archive = root / url.rsplit("/", 1)[-1]
    print(f"Descargando {url}")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with archive.open("wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()

    print("Extrayendo...")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(root)
    else:
        import tarfile

        with tarfile.open(archive) as t:
            t.extractall(root, filter="data")
    archive.unlink()

    home = jdk_home()
    if home is None:
        raise RuntimeError(f"El JDK se extrajo pero no se encontro bin/java en {root}")
    print(f"JDK listo: {home}")
    return home


def main() -> int:
    home = install(force="--force" in sys.argv)
    print("\nPara usarlo en esta sesion:")
    if platform.system() == "Windows":
        print(f'  $env:JAVA_HOME = "{home}"')
    else:
        print(f"  export JAVA_HOME={home}")
    print("\nEl benchmark lo detecta solo; no hace falta exportarlo a mano.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
