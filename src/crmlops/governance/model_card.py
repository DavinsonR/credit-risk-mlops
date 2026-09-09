"""Model card generado desde la corrida, no escrito a mano.

Un model card escrito a mano se desincroniza del modelo en la primera iteracion y
nadie lo nota. Este se construye desde los artefactos que produjo el
entrenamiento -- metricas, vintage de datos, huella de configuracion -- asi que o
refleja el modelo actual, o el gate de coherencia falla.

Estructura basada en Model Cards for Model Reporting (Mitchell et al., 2019) y en
lo que SR 11-7 espera de la documentacion de un modelo.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from crmlops.config import load_config, repo_root, resolve_path

TEMPLATE = """# Model Card - {model_name}

> Generado automaticamente por `crmlops.governance.model_card` el {generated}.
> **No editar a mano**: se regenera en cada entrenamiento.

## 1. Detalles del modelo

| | |
|---|---|
| Nombre | `{model_name}` |
| Tarea | Probabilidad de charge-off (PD) en prestamos SBA 7(a) |
| Tipo | {model_type} |
| Calibrador de produccion | `{calibrator}` |
| Semilla | {seed} |
| Vintage de datos | `{vintage}` |
| Huella de configuracion | `{fingerprint}` |
| Version del codigo | `{git_sha}` |

## 2. Uso previsto

**Para que sirve.** Ordenar solicitudes 7(a) por riesgo de incumplimiento y
estimar la perdida esperada de una cartera. El beneficiario principal no es el
banco sino la SBA, que absorbe alrededor del 73% de las perdidas via garantia.

**Para que NO sirve.**

- No es una decision automatica de credito. Es una entrada a una decision humana.
- No estima riesgo de un negocio fuera de la distribucion de entrenamiento
  (FY{train_from}-{train_to}, regimen post-crisis).
- No esta validado sobre cosechas de emergencia (PPP, COVID).

## 3. Datos

| Particion | Anios fiscales | N | Tasa base |
|---|---|---|---|
| Entrenamiento | FY{train_from}-{train_to} | {n_train:,} | {rate_train:.2%} |
| Validacion | FY{valid_from}-{valid_to} | {n_valid:,} | {rate_valid:.2%} |
| Prueba | FY{test_from}-{test_to} | {n_test:,} | {rate_test:.2%} |

**Split out-of-time, nunca aleatorio.** El riesgo de credito tiene deriva
temporal y un split aleatorio la esconde.

**Criterios de inclusion de cosechas** (ver `docs/adr/0003`):

1. *Regimen homogeneo* - la tasa base del 7(a) fue 32-37% en 2006-2008 y 6-7% en
   2012-2015. Entrenar cruzando la crisis cuesta ~2 puntos de AUC.
2. *Censura acotada* - solo cosechas con >=70% de prestamos resueltos. Un
   prestamo vigente no es "no incumplio", es censura a la derecha.

**Exclusiones aplicadas:** {exclusions}

## 4. Variables

**Solo informacion disponible al momento de aprobar.** Cualquier campo posterior
a la decision es fuga, aunque sea anterior al resultado.

- Numericas: {numeric}
- Categoricas: {categorical}

**Excluida por contaminacion:** `TermInMonths` se sobrescribe cuando el prestamo
se liquida - 84.8% de los charge-off tienen plazo no-redondo contra 9.4% de los
cancelados, que nunca se desembolsaron. Daba un AUC falso de 0.946.
Ver `docs/adr/0002`.

## 5. Desempeno

{metrics_table}

**Calibracion.** El calibrador se ajusta sobre validacion (nunca train, que el
modelo ya vio; nunca test, que seria fuga) y el metodo se declara antes de mirar
test. Se usa ajuste de intercepto: monotono, no puede alterar el ranking.

## 6. Gates de promocion

{gates_table}

Un modelo que no pasa estos gates no se promueve. El gate de coherencia verifica
que estas metricas correspondan al `config.yaml` actual, para que nadie cambie el
split sin reentrenar.

## 7. Limitaciones conocidas

- **Reject inference.** Solo se observan resultados de prestamos aprobados. La
  poblacion rechazada no esta representada, asi que el modelo describe el riesgo
  *condicionado a haber sido aprobado*.
- **Deriva de calibracion con el ciclo.** El ranking aguanta pero el nivel
  deriva: con la tasa base subiendo de {rate_train:.2%} a {rate_test:.2%}, el
  modelo sin recalibrar sub-predice. Exige recalibracion periodica.
- **Contrafactual sin experimento.** La perdida evitada se calcula sobre
  prestamos que si fueron aprobados, y supone que rechazar no altera el
  comportamiento del resto del mercado.
- **Censura residual.** Incluso con el criterio de >=70%, entre 25% y 30% de las
  cosechas de prueba sigue sin resolver.

## 8. Consideraciones eticas

Este modelo decide sobre acceso a credito para pequenas empresas. El extracto
FOIA de SBA **no incluye clases protegidas**, asi que no se puede auditar sesgo
directamente sobre estos datos. El analisis de equidad se hace sobre HMDA, que si
trae raza, etnia, sexo y edad.

`borrower_state` y `naics_sector` son proxies geograficos y sectoriales que
pueden correlacionar con caracteristicas protegidas. Su uso queda declarado, no
oculto.

## 9. Trazabilidad

Todos los numeros provienen de `exports/metrics.json`, producido por `make train`
sobre el vintage `{vintage}`. Reproducible con `make reproduce`.
"""


def _git_sha() -> str:
    head = repo_root() / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            return (repo_root() / ".git" / ref[5:]).read_text(encoding="utf-8").strip()[:12]
        return ref[:12]
    except OSError:
        return "desconocido"


def _metrics_table(models: list[dict], production: str) -> str:
    cols = ["auc_test", "gini_test", "ks_test", "brier_test", "ece_test", "drop_oot", "psi"]
    head = "| Modelo | " + " | ".join(c.replace("_", " ") for c in cols) + " |"
    sep = "|---" * (len(cols) + 1) + "|"
    rows = []
    for m in sorted(models, key=lambda r: -r["auc_test"]):
        mark = " **(produccion)**" if m["modelo"] == production else ""
        vals = " | ".join(f"{m[c]:.4f}" for c in cols)
        rows.append(f"| `{m['modelo']}`{mark} | {vals} |")
    return "\n".join([head, sep, *rows])


def _gates_table(cfg: dict) -> str:
    from crmlops.governance.gates import evaluate

    rows = ["| Gate | Valor | Umbral | Resultado |", "|---|---|---|---|"]
    for r in evaluate(cfg=cfg):
        val = "n/a" if r.value is None else f"{r.value:.4f}"
        op = ">=" if r.direction == "min" else "<="
        estado = "PASA" if r.passed else "FALLA"
        rows.append(f"| `{r.name}` | {val} | {op} {r.threshold} | {estado} |")
    return "\n".join(rows)


def _exclusions_text(cfg: dict) -> str:
    exc = cfg["exclusions"]
    flags = [f"`{k}`" for k, v in exc.items() if v is True]
    estados = ", ".join(exc["resolved_statuses"])
    return ", ".join(flags) + f", solo estados resueltos ({estados})"


def generate(out_path: Path | None = None) -> Path:
    cfg = load_config()
    data = json.loads((resolve_path("exports") / "metrics.json").read_text(encoding="utf-8"))

    production = data["production_model"]
    sp = data["splits"]
    counts = data.get("split_sizes", {})
    rates = data.get("split_rates", {})

    text = TEMPLATE.format(
        model_name=production,
        model_type="Gradient boosting (LightGBM) con recalibracion de intercepto",
        calibrator=data["production_calibrator"],
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        seed=data["seed"],
        vintage=data["vintage"],
        fingerprint=data["config_fingerprint"],
        git_sha=_git_sha(),
        train_from=sp["train"][0],
        train_to=sp["train"][1],
        valid_from=sp["valid"][0],
        valid_to=sp["valid"][1],
        test_from=sp["test"][0],
        test_to=sp["test"][1],
        n_train=counts.get("train", 0),
        n_valid=counts.get("valid", 0),
        n_test=counts.get("test", 0),
        rate_train=rates.get("train", 0.0),
        rate_valid=rates.get("valid", 0.0),
        rate_test=rates.get("test", 0.0),
        exclusions=_exclusions_text(cfg),
        numeric=", ".join(f"`{c}`" for c in cfg["features"]["numeric"]),
        categorical=", ".join(f"`{c}`" for c in cfg["features"]["categorical"]),
        metrics_table=_metrics_table(data["models"], production),
        gates_table=_gates_table(cfg),
    )

    path = out_path or (repo_root() / "reports" / "MODEL_CARD.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    path = generate()
    print(f"Model card generado: {path.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
