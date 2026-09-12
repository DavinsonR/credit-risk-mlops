"""Reproduce las condiciones de CI en local, antes de empujar.

POR QUE EXISTE ESTE ARCHIVO

Seis veces en este proyecto un cambio paso en mi maquina y fallo en el entorno de
destino. Siempre la misma forma: mi entorno tenia algo configurado que el otro no.

  1. Semana 7  — CI sin los extras `onnx` y `serve`: los tests de paridad no
                 importaban y el fallo no decia que faltaba una dependencia.
  2. Semana 9  — el hook de autoria con `sh.exe` sin /usr/bin en el PATH: `grep`
                 no existia, el hook salia 0 y aceptaba el trailer en silencio.
  3. Semana 9  — ExecutionPolicy `Restricted`: el primer comando de la guia no
                 arrancaba. Mi scope de proceso estaba en Bypass.
  4. Semana 9  — `.\run` resolviendo al .ps1 en vez del .cmd. "Verifique" el
                 arreglo en una terminal con Bypass, donde el bug no existe.
  5. Semana 9  — `torch` instalado aqui y ausente alla: `train`, `economics`,
                 `stress` y `onnx` exigian un extra opcional.
  6. Semana 10 — `core.hooksPath` configurado a mano desde la semana 1, asi que un
                 test lo daba por hecho. CI en rojo desde la semana 8 mientras yo
                 reportaba "lint verde, N tests" en cinco mensajes de commit.

El patron no se arregla con cuidado. Se arregla haciendolo ejecutable: este script
monta lo que CI monta y corre lo que CI corre, en un clon limpio del HEAD.

QUE REPRODUCE, Y QUE NO

  reproduce   clon sin `setup`, solo los extras de ci.yml, la misma linea de
              configuracion del hook, lint, la suite con `-m "not data"` y los gates
  NO reproduce el sistema operativo. CI corre en ubuntu y esto en Windows, asi que
              los tests marcados como solo-Windows corren aqui y se saltan alla, y
              al reves. Se declara en vez de fingirse.

SE PRUEBA EL ARBOL DE TRABAJO, NO HEAD. La primera version clonaba HEAD, y eso no
sirve para lo unico que este script hace: avisar ANTES de commitear. Lo que se va a
empujar son los archivos trackeados como estan ahora, asi que el clon se sobrescribe
con ellos. Un chequeo pre-push que mira el commit anterior no chequea nada.

Uso:  uv run python scripts/ci_local.py        (o `.\run ci-local`)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Los mismos extras que instala .github/workflows/ci.yml. Si alli cambian, aqui
# tambien: un chequeo que instala mas de lo que instala CI no chequea nada.
EXTRAS = ("dev", "onnx", "serve")

REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], cwd: Path, env: dict[str, str], etapa: str) -> bool:
    """Captura la salida en vez de heredarla.

    Heredandola, los `print` de este script salian bufereados y el error de una etapa
    aparecia junto a la salida de otra: al diagnosticar un fallo de `uv run` perdi
    varios intentos leyendo el orden equivocado. Con captura, cada etapa imprime lo
    suyo en su lugar.
    """
    print(f"\n--> {etapa}", flush=True)
    print(f"    {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    salida = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        print(salida.rstrip(), flush=True)
        print(f"\nFALLO en '{etapa}' (codigo {r.returncode}).", flush=True)
        return False
    # En verde se muestran solo las ultimas lineas: el interes esta en el fallo.
    cola = [ln for ln in salida.splitlines() if ln.strip()][-3:]
    for ln in cola:
        print(f"    {ln}", flush=True)
    return True


def _sobrescribir_con_arbol_de_trabajo(clon: Path) -> bool:
    """Copia al clon los archivos TRACKEADOS tal como estan ahora.

    Es lo que un commit incluiria. Sin esto el script probaria HEAD, que es
    exactamente lo que ya se sabe que paso o fallo.
    """
    print("\n--> sobrescribir con el arbol de trabajo")
    r = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=False
    )
    if r.returncode != 0:
        print("    no se pudo listar los archivos trackeados")
        return False

    rutas = [p for p in r.stdout.split("\0") if p]
    copiados = 0
    for rel in rutas:
        origen = REPO / rel
        if not origen.is_file():  # borrado en el arbol de trabajo
            continue
        destino = clon / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, destino)
        copiados += 1
    print(f"    {copiados} archivos trackeados copiados")
    return True


def main() -> int:
    if shutil.which("git") is None or shutil.which("uv") is None:
        print("Hacen falta git y uv en el PATH.")
        return 2

    print("=" * 88)
    print("CI LOCAL — clon limpio del HEAD, sin `setup`, solo los extras de ci.yml")
    print("=" * 88)
    print(f"  repo     {REPO}")
    print(f"  extras   {', '.join(EXTRAS)}")
    print(f"  sistema  {platform.system()} (CI corre en Linux: los tests de plataforma difieren)")

    raiz = Path(tempfile.mkdtemp(prefix="crmlops-ci-"))
    clon = raiz / "repo"
    venv = raiz / "venv"
    try:
        if not _run(
            ["git", "clone", "--quiet", str(REPO), str(clon)], REPO, dict(os.environ), "clonar HEAD"
        ):
            return 1

        if not _sobrescribir_con_arbol_de_trabajo(clon):
            return 1

        env = dict(os.environ)
        env["UV_PROJECT_ENVIRONMENT"] = str(venv)  # entorno propio: no toca el .venv del repo
        env["PYTHONIOENCODING"] = "utf-8"
        env["MLFLOW_DISABLE_AGENT_HINT"] = "1"
        env["CI"] = "true"
        # Este script corre DENTRO del .venv del repo (`uv run python scripts/...`),
        # asi que hereda VIRTUAL_ENV apuntando ahi. Con UV_PROJECT_ENVIRONMENT
        # tambien puesto, uv veia dos entornos, avisaba en cada etapa que ignoraba
        # uno, y hubo un `Failed to spawn: pytest` que aparecio y desaparecio entre
        # corridas. No llegue a explicar el mecanismo exacto; lo que si se puede
        # hacer es quitar la ambiguedad, que es la causa de que hubiera algo que
        # explicar. Sin VIRTUAL_ENV heredado, uv tiene un solo entorno posible.
        env.pop("VIRTUAL_ENV", None)

        # `--no-sync` en cada `uv run`: el entorno se acaba de montar en el paso
        # anterior y no hay que re-resolverlo. Sin esto, `uv run` volvia a
        # sincronizar en cada etapa y en Windows aparecia un
        # `error: Failed to spawn: pytest` intermitente -- el ejecutable estaba a
        # medio escribir. Un chequeo pre-push que falla al azar se deja de usar.
        run = ["uv", "run", "--no-sync"]
        etapas: list[tuple[str, list[str]]] = [
            ("instalar dependencias", ["uv", "sync", *[f"--extra={e}" for e in EXTRAS]]),
            ("configurar el hook de autoria", ["git", "config", "core.hooksPath", "scripts/hooks"]),
            ("ruff check", [*run, "ruff", "check", "."]),
            ("ruff format", [*run, "ruff", "format", "--check", "."]),
            ("pytest", [*run, "pytest", "-m", "not data", "-q"]),
            ("gates de promocion", [*run, "python", "-m", "crmlops.governance.gates"]),
        ]
        for etapa, cmd in etapas:
            if not _run(cmd, clon, env, etapa):
                print("\nEsto habria fallado en CI. No empujes todavia.")
                return 1

        print("\n" + "=" * 88)
        print("PASA en condiciones de CI.")
        print("Recordatorio honesto: esto NO cubre la diferencia de sistema operativo")
        print("ni el job de Docker, que solo corre en Actions.")
        print("=" * 88)
        return 0
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
