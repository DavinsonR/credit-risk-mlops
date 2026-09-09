"""Gates de promocion: bloquean modelos que no cumplen el estandar.

Un gate solo sirve si puede FALLAR el build. Si es un reporte que alguien lee
cuando se acuerda, no es un control: es documentacion.

DISENO -- por que el gate lee un artefacto commiteado y no reentrena en CI.
Entrenar exige ~860 MB de datos crudos que no se commitean y cuyo vintage rota
cada trimestre. Un CI que descargue eso seria lento y no determinista. En vez de
eso, `make train` produce exports/metrics.json localmente, ESE archivo se
commitea, y CI verifica que los numeros publicados cumplen los umbrales.

El agujero obvio de ese diseno seria que alguien cambie config.yaml (el split,
la semilla) sin reentrenar, dejando metricas que ya no corresponden. Por eso el
gate tambien verifica COHERENCIA: el hash de la configuracion relevante grabado
en metrics.json tiene que coincidir con el config.yaml actual.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from crmlops.config import load_config, repo_root


@dataclass
class GateResult:
    name: str
    value: float | None
    threshold: float
    direction: str  # "min" | "max"
    passed: bool
    detail: str = ""

    def render(self) -> str:
        mark = "PASA " if self.passed else "FALLA"
        shown = "n/a" if self.value is None else f"{self.value:.4f}"
        op = ">=" if self.direction == "min" else "<="
        extra = f"  {self.detail}" if self.detail else ""
        return f"  {mark}  {self.name:22s} {shown:>8} {op} {self.threshold}{extra}"


def config_fingerprint(cfg: dict | None = None) -> str:
    """Hash de las partes de config.yaml que cambian el significado de una metrica.

    Solo entran las claves que afectan al numero. Cambiar un comentario o una
    ruta no debe invalidar un entrenamiento; cambiar el split o las exclusiones si.
    """
    cfg = cfg or load_config()
    material = {
        "splits": cfg["splits"],
        "exclusions": cfg["exclusions"],
        "target": cfg["target"],
        "features": {
            k: cfg["features"][k]
            for k in ("numeric", "categorical", "derived", "forbidden_panel")
            if k in cfg["features"]
        },
        "seed": cfg["project"]["random_seed"],
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _metric(record: dict, key: str) -> float | None:
    v = record.get(key)
    return float(v) if isinstance(v, int | float) else None


def evaluate(metrics_path: Path | None = None, cfg: dict | None = None) -> list[GateResult]:
    """Evalua los gates sobre el modelo de produccion registrado."""
    cfg = cfg or load_config()
    gates = cfg["gates"]
    path = metrics_path or (repo_root() / "exports" / "metrics.json")

    if not path.exists():
        return [
            GateResult(
                "metrics.json",
                None,
                0,
                "min",
                False,
                f"no existe {path.name}; correr `make train` y commitear el resultado",
            )
        ]

    data = json.loads(path.read_text(encoding="utf-8"))
    results: list[GateResult] = []

    # --- coherencia: las metricas corresponden a ESTA configuracion ---
    recorded = data.get("config_fingerprint")
    current = config_fingerprint(cfg)
    results.append(
        GateResult(
            "config_coherente",
            None,
            0,
            "min",
            recorded == current,
            ""
            if recorded == current
            else f"metricas de config {recorded}, actual {current}: reentrenar",
        )
    )

    prod_name = data.get("production_model")
    models = {m["modelo"]: m for m in data.get("models", [])}
    prod = models.get(prod_name)
    if prod is None:
        results.append(
            GateResult(
                "modelo_produccion",
                None,
                0,
                "min",
                False,
                f"production_model={prod_name!r} no esta en models",
            )
        )
        return results

    checks = [
        ("auc_test", _metric(prod, "auc_test"), gates["min_auc_test"], "min"),
        ("drop_oot", _metric(prod, "drop_oot"), gates["max_auc_drop_oot"], "max"),
        ("brier_test", _metric(prod, "brier_test"), gates["max_brier"], "max"),
    ]
    # El gate de fairness solo aplica cuando hay un modelo con clases protegidas
    # (HMDA, Semana 6). Se declara aqui para que no se olvide de conectarlo.
    dir_ratio = _metric(prod, "disparate_impact_ratio")
    if dir_ratio is not None:
        checks.append(("disparate_impact", dir_ratio, gates["min_disparate_impact_ratio"], "min"))

    for name, value, thr, direction in checks:
        if value is None:
            results.append(GateResult(name, None, thr, direction, False, "metrica ausente"))
            continue
        ok = value >= thr if direction == "min" else value <= thr
        results.append(GateResult(name, value, thr, direction, ok))

    return results


def main() -> int:
    cfg = load_config()
    results = evaluate(cfg=cfg)

    print("=" * 78)
    print("GATES DE PROMOCION")
    print("=" * 78)
    for r in results:
        print(r.render())

    failed = [r for r in results if not r.passed]
    print("=" * 78)
    if failed:
        print(f"BLOQUEADO: {len(failed)} de {len(results)} gates fallaron.")
        for r in failed:
            print(f"  - {r.name}: {r.detail or 'fuera de umbral'}")
        print("\nUn modelo que no pasa los gates no se promueve. Ver config.yaml: gates")
        return 1
    print(f"APROBADO: {len(results)} gates pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
