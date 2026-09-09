"""Gates de promocion: bloquean modelos que no cumplen el estandar.

Un gate solo sirve si puede FALLAR el build. Si es un reporte que alguien lee
cuando se acuerda, no es un control: es documentacion.

TRES PROPIEDADES QUE ESTE GATE SI GARANTIZA (las tres nacieron de docs/AUDIT.md):

1. *Integridad* -- las metricas se RECOMPUTAN desde las predicciones guardadas, no
   se creen. Editar exports/metrics.json a mano ya no burla nada.
2. *Coherencia* -- el config y el codigo que produjeron las metricas tienen que
   ser los actuales. Cambiar el split o las features sin reentrenar falla.
3. *Umbrales derivados* -- cada umbral sale de una cantidad medible, no de un
   numero que el modelo casualmente pasaba.

Y evalua la CONFIGURACION DE PRODUCCION (modelo + calibrador), no el modelo
crudo: antes se controlaba algo distinto de lo que se despachaba.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from crmlops.config import load_config, repo_root
from crmlops.governance.integrity import check as integrity_check


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
        return f"  {mark}  {self.name:26s} {shown:>8} {op} {self.threshold}{extra}"


def config_fingerprint(cfg: dict | None = None) -> str:
    """Hash de las partes de config.yaml que cambian el significado de una metrica.

    Solo entran las claves que afectan al numero. Cambiar un comentario o una ruta
    no debe invalidar un entrenamiento; cambiar el split o las features si.
    """
    cfg = cfg or load_config()
    material = {
        "splits": cfg["splits"],
        "exclusions": cfg["exclusions"],
        "target": cfg["target"],
        # Las listas de PANEL son las que el modelo realmente consume
        # (crmlops.features.spec las lee de aqui). Hashearlas significa que
        # agregar o quitar una variable invalida el entrenamiento anterior.
        "features": {
            k: cfg["features"][k]
            for k in ("numeric", "categorical", "forbidden_panel")
            if k in cfg["features"]
        },
        "seed": cfg["project"]["random_seed"],
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _num(record: dict, key: str) -> float | None:
    v = record.get(key)
    return float(v) if isinstance(v, int | float) else None


def evaluate(metrics_path: Path | None = None, cfg: dict | None = None) -> list[GateResult]:
    cfg = cfg or load_config()
    g = cfg["gates"]
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

    # ---------- 1. Coherencia con la configuracion ----------
    recorded, current = data.get("config_fingerprint"), config_fingerprint(cfg)
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

    # ---------- 2. Integridad: recomputar, no creer ----------
    # exports/metrics.json -> la raiz de artefactos es el padre de exports/
    artifacts_root = path.parent.parent
    issues = integrity_check(data, artifacts_root=artifacts_root)
    for issue in issues:
        results.append(GateResult(f"integridad:{issue.kind}", None, 0, "min", False, issue.detail))
    if not issues:
        results.append(
            GateResult(
                "integridad", None, 0, "min", True, "metricas recomputadas desde predicciones"
            )
        )

    # ---------- 3. Desempeno de la configuracion de PRODUCCION ----------
    prod_name = data.get("production_model")
    models = {m["modelo"]: m for m in data.get("models", [])}
    if prod_name not in models:
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

    # Se evalua modelo + calibrador. Si falta el bloque de produccion se cae al
    # modelo crudo, pero se deja constancia: no es lo que se despacha.
    prod = data.get("production_metrics")
    if prod is None:
        prod = models[prod_name]
        results.append(
            GateResult(
                "metricas_de_produccion",
                None,
                0,
                "min",
                False,
                "falta production_metrics; se evaluo el modelo CRUDO, no el calibrado",
            )
        )

    checks: list[tuple[str, float | None, float, str]] = [
        ("auc_test", _num(prod, "auc_test"), g["min_auc_test"], "min"),
        ("drop_oot", _num(prod, "drop_oot"), g["max_auc_drop_oot"], "max"),
        ("brier_test", _num(prod, "brier_test"), g["max_brier_test"], "max"),
        ("ece_test", _num(prod, "ece_test"), g["max_ece_test"], "max"),
    ]

    # Gate RELATIVO: el retador tiene que superar al baseline interpretable.
    # Es el unico que no se puede acomodar eligiendo el numero, porque se mide
    # contra un modelo entrenado en la misma corrida.
    baseline = models.get(g["baseline_model"])
    auc = _num(prod, "auc_test")
    if baseline is not None and auc is not None:
        margin = auc - float(baseline["auc_test"])
        checks.append(("margen_sobre_baseline", margin, g["min_margin_over_baseline"], "min"))

    dir_ratio = _num(prod, "disparate_impact_ratio")
    if dir_ratio is not None:
        checks.append(("disparate_impact", dir_ratio, g["min_disparate_impact_ratio"], "min"))

    for name, value, thr, direction in checks:
        if value is None:
            results.append(GateResult(name, None, thr, direction, False, "metrica ausente"))
            continue
        ok = value >= thr if direction == "min" else value <= thr
        results.append(GateResult(name, value, thr, direction, ok))

    return results


def evaluate_fairness(cfg: dict | None = None, path: Path | None = None) -> list[GateResult]:
    """Gate de equidad sobre el modelo de HMDA.

    Semantica deliberada: un gate BLOQUEA PROMOCION, no rompe el build. Un modelo
    que falla el umbral y esta marcado `promoted: false` es el sistema
    funcionando -- se midio, se documento y no se despliega. Lo que SI falla el
    build es marcar `promoted: true` un modelo que no cumple.
    """
    cfg = cfg or load_config()
    path = path or (repo_root() / "exports" / "hmda_metrics.json")
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    dir_ratio = _num(data, "disparate_impact_ratio")
    thr = cfg["gates"]["min_disparate_impact_ratio"]
    cumple = dir_ratio is not None and dir_ratio >= thr
    promovido = bool(data.get("promoted", False))

    detalle = "" if cumple else f"peor grupo: {data.get('worst_dimension_group', '?')}"
    if not cumple and not promovido:
        detalle += "  -> NO promovido, gate cumpliendo su funcion"

    return [
        GateResult(
            "hmda:disparate_impact",
            dir_ratio,
            thr,
            "min",
            # Solo falla el build si se pretende promover algo que no cumple.
            passed=cumple or not promovido,
            detail=detalle,
        )
    ]


def main() -> int:
    cfg = load_config()
    results = evaluate(cfg=cfg) + evaluate_fairness(cfg)

    print("=" * 84)
    print("GATES DE PROMOCION")
    print("=" * 84)
    for r in results:
        print(r.render())

    failed = [r for r in results if not r.passed]
    print("=" * 84)
    if failed:
        print(f"BLOQUEADO: {len(failed)} de {len(results)} gates fallaron.")
        for r in failed:
            print(f"  - {r.name}: {r.detail or 'fuera de umbral'}")
        print("\nUn modelo que no pasa los gates no se promueve.")
        print("Cada umbral tiene su derivacion escrita en config.yaml: gates")
        return 1
    print(f"APROBADO: {len(results)} gates pasaron.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
