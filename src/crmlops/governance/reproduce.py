"""Verificacion de reproducibilidad.

Reentrena desde cero y compara contra las metricas commiteadas. Si no coinciden,
falla.

Por que importa mas de lo que parece: un repo puede tener tests verdes, CI verde
y numeros bonitos en el README, y aun asi ser irreproducible -- porque una semilla
quedo suelta, porque el vintage de datos cambio en silencio, o porque alguien
edito exports/metrics.json a mano. Esta verificacion cierra esas tres puertas a
la vez.

La tolerancia no es cero. LightGBM con n_jobs=-1 puede diferir en el ultimo bit
entre corridas segun como se repartan los hilos, y PyTorch tampoco garantiza
determinismo exacto en CPU multihilo. Se exige coincidencia hasta 1e-4, que es
mucho mas fino que cualquier diferencia que cambie una decision.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from crmlops.config import repo_root, resolve_path

TOLERANCE = 1e-4
COMPARED = ["auc_test", "auc_valid", "gini_test", "ks_test", "brier_test", "drop_oot"]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compare(before: dict, after: dict, tol: float = TOLERANCE) -> list[str]:
    """Devuelve la lista de discrepancias. Vacia significa reproducible."""
    problems: list[str] = []

    for key in ("vintage", "seed", "config_fingerprint", "production_model"):
        if before.get(key) != after.get(key):
            problems.append(f"{key}: commiteado={before.get(key)!r} nuevo={after.get(key)!r}")

    b = {m["modelo"]: m for m in before.get("models", [])}
    a = {m["modelo"]: m for m in after.get("models", [])}
    if set(b) != set(a):
        problems.append(f"modelos distintos: commiteado={sorted(b)} nuevo={sorted(a)}")

    for name in sorted(set(b) & set(a)):
        for metric in COMPARED:
            vb, va = b[name].get(metric), a[name].get(metric)
            if vb is None or va is None:
                continue
            if abs(vb - va) > tol:
                problems.append(
                    f"{name}.{metric}: commiteado={vb:.6f} nuevo={va:.6f} "
                    f"(delta {abs(vb - va):.2e} > {tol:g})"
                )
    return problems


def main() -> int:
    metrics_path = resolve_path("exports") / "metrics.json"
    if not metrics_path.exists():
        print("No hay exports/metrics.json commiteado contra el cual comparar.")
        return 1

    committed = _load(metrics_path)
    backup = metrics_path.with_suffix(".json.reproduce-backup")
    backup.write_text(json.dumps(committed, indent=2) + "\n", encoding="utf-8")

    print("=" * 78)
    print("VERIFICACION DE REPRODUCIBILIDAD")
    print(f"  vintage   {committed.get('vintage')}")
    print(f"  config    {committed.get('config_fingerprint')}")
    print(f"  tolerancia {TOLERANCE:g}")
    print("=" * 78)
    print("\nReentrenando desde cero...\n")

    proc = subprocess.run(
        [sys.executable, "-m", "crmlops.models.train"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("El entrenamiento fallo:")
        print(proc.stderr[-2000:])
        backup.unlink(missing_ok=True)
        return 1

    problems = compare(committed, _load(metrics_path))

    print("=" * 78)
    if problems:
        print(f"NO REPRODUCIBLE: {len(problems)} discrepancias")
        for p in problems:
            print(f"  - {p}")
        print("\nSe restauro exports/metrics.json commiteado.")
        metrics_path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        backup.unlink(missing_ok=True)
        print("=" * 78)
        return 1

    n_models = len(committed.get("models", []))
    print(
        f"REPRODUCIBLE: {n_models} modelos, {len(COMPARED)} metricas cada uno, "
        f"identicas hasta {TOLERANCE:g}."
    )
    print("=" * 78)
    backup.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
