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
    """Resultado de un gate. DOS HECHOS DISTINTOS, y confundirlos costo caro.

    `passed`        el BUILD pasa: el control funciono y no hay nada que bloquear.
    `threshold_met` el MODELO cumple el umbral.

    Para casi todos los gates coinciden. Para el de equidad NO: un modelo con
    disparate impact 0.7639 no cumple el umbral de 0.80, y sin embargo el build
    pasa porque el modelo esta marcado `promoted: false` -- se midio, se documento
    y no se despliega. Eso es el sistema funcionando.

    El problema fue tener un solo campo llamado `passed` para las dos cosas:
    `reports/VALIDATION_REPORT.md` imprimia `hmda:disparate_impact | 0.7639 | >= 0.8
    | PASA` en su seccion 3.1 y "No apto -- promocion bloqueada" en la seccion 5,
    del mismo gate y en el mismo documento. Un validador que lee eso concluye que el
    reporte no es confiable, y tiene razon.

    Cualquier consumidor que quiera decir "el modelo cumple" tiene que leer
    `threshold_met`. `passed` solo responde "¿rompe el build?".
    """

    name: str
    value: float | None
    threshold: float
    direction: str  # "min" | "max"
    passed: bool
    detail: str = ""
    threshold_met: bool | None = None

    def __post_init__(self) -> None:
        if self.threshold_met is None:
            self.threshold_met = self.passed

    @property
    def veredicto(self) -> str:
        """Lo que hay que imprimir en un documento, sin ambiguedad."""
        if not self.passed:
            return "FALLA"
        if not self.threshold_met:
            return "NO CUMPLE (build ok: no se promueve)"
        return "PASA"

    def render(self) -> str:
        if not self.passed:
            mark = "FALLA"
        elif not self.threshold_met:
            mark = "MIDE "  # el control corrio; el modelo no cumple
        else:
            mark = "PASA "
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

    if "promoted" not in data:
        # El control descansaba en un campo que nunca se escribia: `.get("promoted",
        # False)` hacia que el gate pasara por DEFECTO y no por diseno. Si alguien
        # promoviera el modelo sin escribir la bandera, el gate seguiria en verde.
        return [
            GateResult(
                "hmda:disparate_impact",
                dir_ratio,
                thr,
                "min",
                passed=False,
                detail="hmda_metrics.json no declara `promoted`: el gate no puede decidir",
                threshold_met=cumple,
            )
        ]

    return [
        GateResult(
            "hmda:disparate_impact",
            dir_ratio,
            thr,
            "min",
            # Solo falla el build si se pretende promover algo que no cumple.
            passed=cumple or not promovido,
            detail=detalle,
            # Y por separado: el MODELO cumple o no, sin importar si se promueve.
            threshold_met=cumple,
        )
    ]


def evaluate_reports(cfg: dict | None = None, root: Path | None = None) -> list[GateResult]:
    """Los documentos de gobierno tienen que describir las metricas publicadas.

    POR QUE ESTE GATE EXISTE. `reports/MODEL_CARD.md` estuvo congelado desde la
    semana 4: declaraba un commit de entonces y listaba 7 gates cuando ya habia 8
    --faltaba el de equidad, el unico que el modelo no cumple--. Y
    `reports/VALIDATION_REPORT.md` traia una huella de codigo que no era la de
    `metrics.json`, porque se calculaba en vivo al generar el documento.

    Nada avisaba. Los dos archivos son el producto estrella del proyecto: lo primero
    que abre un validador. Un reporte rancio es peor que no tener reporte, porque se
    cita.

    El gate es barato: los documentos estampan la huella de codigo de metrics.json y
    aqui se compara. Si difiere, hay que regenerarlos.
    """
    cfg = cfg or load_config()
    root = root or repo_root()
    metrics_path = root / "exports" / "metrics.json"
    if not metrics_path.exists():
        return []

    esperada = json.loads(metrics_path.read_text(encoding="utf-8")).get("code_fingerprint")
    if not esperada:
        return []

    out: list[GateResult] = []
    for nombre in ("MODEL_CARD.md", "VALIDATION_REPORT.md"):
        ruta = root / "reports" / nombre
        if not ruta.exists():
            out.append(
                GateResult(
                    f"reporte:{nombre}",
                    None,
                    0,
                    "min",
                    passed=False,
                    detail=f"falta {ruta.relative_to(root).as_posix()}: correr card y validation",
                )
            )
            continue
        texto = ruta.read_text(encoding="utf-8")
        al_dia = esperada in texto
        out.append(
            GateResult(
                f"reporte:{nombre}",
                None,
                0,
                "min",
                passed=al_dia,
                detail=""
                if al_dia
                else f"no menciona la huella {esperada} de metrics.json: esta rancio, regenerar",
            )
        )
    return out


def main() -> int:
    cfg = load_config()
    results = evaluate(cfg=cfg) + evaluate_fairness(cfg) + evaluate_reports(cfg)

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
