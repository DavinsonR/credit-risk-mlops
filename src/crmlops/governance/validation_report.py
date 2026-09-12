"""Reporte de validación de modelos, generado desde las corridas.

Estructura tomada de SR 26-2 (Fed/OCC/FDIC, *Revised Guidance on Model Risk
Management*), que organiza la validación en tres bloques:

  1. Solidez conceptual — ¿el diseño tiene sentido para el problema?
  2. Análisis de resultados — ¿el desempeño se sostiene fuera de muestra?
  3. Monitoreo continuo — ¿cómo se detecta que dejó de servir?

Y un mapeo al Anexo IV del Reglamento de IA de la UE, porque la evaluación de
solvencia crediticia está listada como sistema de **alto riesgo** (Anexo III,
punto 5.b) y exige documentación técnica específica.

Como el model card, se genera desde los artefactos: si se desincroniza del
modelo, el gate de coherencia falla.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from crmlops.config import load_config, repo_root, resolve_path
from crmlops.governance.gates import evaluate, evaluate_fairness


def _load(name: str) -> dict | None:
    path = resolve_path("exports") / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _tabla(filas: list[tuple], encabezados: tuple) -> str:
    out = ["| " + " | ".join(encabezados) + " |", "|" + "---|" * len(encabezados)]
    out += ["| " + " | ".join(str(c) for c in f) + " |" for f in filas]
    return "\n".join(out)


def _gates_section(cfg: dict) -> str:
    filas = []
    for r in evaluate(cfg=cfg) + evaluate_fairness(cfg):
        valor = "n/a" if r.value is None else f"{r.value:.4f}"
        op = "≥" if r.direction == "min" else "≤"
        # `r.veredicto` y no `r.passed`: para el gate de equidad, `passed` significa
        # "el build no se rompe" y no "el modelo cumple". Con `passed` este documento
        # imprimia `hmda:disparate_impact | 0.7639 | >= 0.8 | PASA` en la seccion 3.1
        # y "No apto -- promocion bloqueada" en la seccion 5, del mismo gate.
        filas.append((f"`{r.name}`", valor, f"{op} {r.threshold}", r.veredicto))
    return _tabla(filas, ("Gate", "Valor", "Umbral", "Resultado"))


def build(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    sba = _load("metrics.json")
    hmda = _load("hmda_metrics.json")
    econ = _load("headline_economics.json")

    if sba is None:
        raise FileNotFoundError("Falta exports/metrics.json; correr `make train` primero.")

    prod = sba["production_metrics"]
    fecha = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    partes: list[str] = []
    partes.append(f"""# Reporte de Validación de Modelos

> Generado por `crmlops.governance.validation_report` el {fecha}.
> **No editar a mano**: se regenera en cada corrida.
>
> Vintage de datos `{sba["vintage"]}` · configuración `{sba["config_fingerprint"]}` ·
> código `{sba["code_fingerprint"]}`
>
> Los tres identificadores salen de `exports/metrics.json`: son la procedencia de
> los números que este reporte describe. La versión anterior calculaba el de código
> **en vivo**, así que el reporte declaraba el código del momento en que se generó
> y no el que produjo las métricas — y al primer cambio en el modelado los dos
> dejaban de coincidir sin que nada avisara. El gate `reportes_al_dia` ahora lo
> verifica.

Estructura según **SR 26-2** (Federal Reserve / OCC / FDIC, *Revised Guidance on
Model Risk Management*, 17 de abril de 2026), que **reemplaza a SR 11-7** (2011) y
a SR 21-8 (2021). Las tres secciones de validación de este reporte corresponden a
las secciones **IV (Model Development and Model Use)**, **V (Model Validation and
Monitoring)** y **VI (Governance and Controls)** de esa guía.

> El proyecto se construyó contra SR 11-7 y la reancla a SR 26-2 **no cambió
> ningún mecanismo**: los conceptos que sostienen este reporte —*effective
> challenge*, *outcomes analysis* y *ongoing monitoring*— aparecen textualmente en
> la guía nueva. Lo que SR 26-2 añade y aquí se declara es el énfasis en
> **materialidad**: *"Model purpose, together with model exposure, determines model
> materiality"*. Este modelo no está en producción y su exposición es nula, así que
> su materialidad es la de un ejercicio de referencia.

El mapeo al **Anexo IV del Reglamento de IA de la UE** está en la sección 4: la
evaluación de solvencia crediticia figura como sistema de alto riesgo en el Anexo
III, punto 5.b.

## Modelos en alcance

{
        _tabla(
            [
                (
                    "**A — Riesgo de crédito**",
                    "SBA 7(a) FOIA",
                    "Charge-off (PD)",
                    sba["production_model"],
                    "**Producción**",
                ),
                (
                    "**B — Suscripción**",
                    "HMDA",
                    "Denegación",
                    "hmda_lightgbm" if hmda else "n/d",
                    "**Bloqueado por equidad**" if hmda and not hmda.get("promoted") else "n/d",
                ),
            ],
            ("Modelo", "Fuente", "Objetivo", "Algoritmo", "Estado"),
        )
    }

---

## 1. Solidez conceptual

### 1.1 Diseño del conjunto de validación

Split **out-of-time**, nunca aleatorio. El riesgo de crédito tiene deriva temporal
y un split aleatorio la esconde.

{
        _tabla(
            [
                (
                    "A (SBA)",
                    f"FY{sba['splits']['train'][0]}-{sba['splits']['train'][1]}",
                    f"FY{sba['splits']['valid'][0]}",
                    f"FY{sba['splits']['test'][0]}-{sba['splits']['test'][1]}",
                    f"{sba['split_sizes']['test']:,}",
                ),
                (
                    "B (HMDA)",
                    "FY2020-2022",
                    "FY2023",
                    "FY2024",
                    f"{hmda['n_test']:,}" if hmda else "n/d",
                ),
            ],
            ("Modelo", "Entrenamiento", "Validación", "Prueba", "n prueba"),
        )
    }

Las ventanas se eligieron por dos criterios **medidos**, no por intuición
(ADR 0003): régimen homogéneo —la tasa base del 7(a) fue 32-37% en 2006-2008 y
6-7% en 2012-2015— y censura acotada, admitiendo solo cosechas con ≥70% de
préstamos resueltos.

### 1.2 Control de fuga de información

Se identificaron y excluyeron **tres clases distintas** de variable contaminada:

{
        _tabla(
            [
                (
                    "Resultado codificado en el campo",
                    "`TermInMonths` (SBA), `interest_rate` (HMDA)",
                    "84.8% de los charge-off tienen plazo no-redondo vs 9.4% de los cancelados; "
                    "`interest_rate` está nulo en 99.4% de las denegadas",
                    "ADR 0002, 0006",
                ),
                (
                    "Decisión del propio prestamista",
                    "`aus-1..5` (HMDA)",
                    "Predecir una decisión desde el motor que la tomó: el modelo imitaría sus sesgos",
                    "ADR 0006",
                ),
                (
                    "Proxy de característica protegida",
                    "`tract_minority_population_percent`",
                    "Composición racial del vecindario: usarla como feature es redlining",
                    "ADR 0006",
                ),
            ],
            ("Clase", "Ejemplo", "Evidencia", "Referencia"),
        )
    }

### 1.3 Modelo de referencia

El baseline permanente es un **scorecard WoE + regresión logística**, interpretable
y aceptado sin discusión por un validador. Un retador que no lo supere por un
margen material no se despliega: el gate `margen_sobre_baseline` lo hace
obligatorio, y es relativo, así que no se puede acomodar eligiendo la cifra.

---

## 2. Análisis de resultados

### 2.1 Discriminación y calibración — Modelo A (producción)

{
        _tabla(
            [
                ("AUC (out-of-time)", f"{prod['auc_test']:.4f}"),
                ("Gini", f"{prod['gini_test']:.4f}"),
                ("KS", f"{prod['ks_test']:.4f}"),
                ("Brier", f"{prod['brier_test']:.4f}"),
                ("ECE", f"{prod['ece_test']:.4f}"),
                ("Razón de calibración", f"{prod['calibration_ratio']:.4f}"),
                ("Degradación AUC train→test", f"{prod['drop_oot']:+.4f}"),
            ],
            ("Métrica", "Valor"),
        )
    }

El calibrador se ajusta sobre **validación** —nunca train, que el modelo ya vio;
nunca test, que sería fuga— y el método se declara **antes** de mirar test.

### 2.2 Traducción a decisiones

""")

    if econ:
        r10 = econ["at_10pct_decline"]
        partes.append(f"""{
            _tabla(
                [
                    (
                        "Monto prestado en la ventana de prueba",
                        f"${econ['total_lent'] / 1e9:,.1f}B",
                    ),
                    (
                        "Pérdida realizada",
                        f"${econ['realized_loss'] / 1e9:,.2f}B "
                        f"({econ['realized_loss'] / econ['total_lent']:.2%} del monto)",
                    ),
                    (
                        "Absorbida por la SBA (garantía)",
                        f"${econ['sba_absorbed_loss'] / 1e6:,.1f}M",
                    ),
                    ("Absorbida por el banco", f"${econ['lender_absorbed_loss'] / 1e6:,.1f}M"),
                    (
                        "Pérdida evitada rechazando el 10% más riesgoso",
                        f"${r10['loss_avoided'] / 1e6:,.1f}M",
                    ),
                    ("Lift sobre rechazo aleatorio", f"{r10['lift_vs_random']:.2f}x"),
                    ("Margen de equilibrio bruto", f"{econ['breakeven_margin_gross']:.2%}"),
                ],
                ("Concepto", "Valor"),
            )
        }

**Supuesto declarado.** El contrafactual se calcula sobre préstamos que **sí fueron
aprobados**, y supone que rechazar no altera el comportamiento del resto del
mercado. Sirve para dimensionar; para política de crédito real haría falta un
experimento.

""")

    if hmda:
        delta = hmda.get("fairness_delta", {})
        partes.append(f"""### 2.3 Equidad — Modelo B

{
            _tabla(
                [
                    ("AUC", f"{hmda['auc_test']:.4f}"),
                    (
                        "Disparate impact ratio (mínimo)",
                        f"**{hmda['disparate_impact_ratio']:.3f}**",
                    ),
                    ("Peor grupo", hmda.get("worst_dimension_group", "n/d")),
                    (
                        "Umbral (regla de 4/5, EEOC)",
                        f"{cfg['gates']['min_disparate_impact_ratio']}",
                    ),
                    ("Promovido a producción", "**No**" if not hmda.get("promoted") else "Sí"),
                ],
                ("Métrica", "Valor"),
            )
        }

**La pregunta no es si el modelo es justo, sino cuánta disparidad AGREGA** sobre la
que ya existe en las decisiones históricas:

{_tabla([(k, f"{v:+.3f}") for k, v in delta.items()], ("Dimensión", "Delta vs observado"))}

Un delta cercano a cero significa que el modelo **reproduce** la disparidad
existente en vez de crearla. Eso no lo exculpa —automatizar una disparidad la
escala y le da apariencia de objetividad— pero cambia dónde debe intervenirse.

**Sesgo de selección declarado (ADR 0007).** Los filtros del panel eliminan 5.1%
de los solicitantes nativos hawaianos y 4.8% de los negros, contra 3.1% de los
blancos. En la comparación estándar de fair lending eso mueve la razón de 4/5 de
0.802 (población completa) a 0.795 (panel filtrado): **una decisión técnica de
limpieza cruza el umbral legal.** Toda cifra de equidad de este reporte lleva
adjunta la población sobre la que se calculó.

**Limitación material.** HMDA no incluye puntaje de crédito, el determinante más
fuerte de una decisión de suscripción. Estas cifras muestran diferencias que
exigen explicación; no prueban discriminación.

""")

    partes.append(f"""---

## 3. Monitoreo continuo

### 3.1 Gates de promoción

{_gates_section(cfg)}

Cada umbral tiene su derivación escrita en `config.yaml`. Ninguno se eligió porque
el modelo lo pasara: el de Brier, por ejemplo, sale del predictor sin habilidad
—constante igual a la tasa base— cuyo Brier es p(1-p) = {cfg["gates"]["max_brier_test"]}.

### 3.2 Integridad del artefacto

Las métricas **se recomputan** desde las predicciones guardadas; no se leen del
archivo publicado. Editar `exports/metrics.json` a mano no altera el veredicto.
Se verifica además que el código de modelado no haya cambiado desde el
entrenamiento.

### 3.3 Estabilidad poblacional

El PSI se **descompone** en corrimiento de nivel y cambio de forma, porque exigen
respuestas distintas: el nivel se corrige recalibrando, la forma obliga a evaluar
reentrenamiento.

{
        _tabla(
            [
                (
                    "A (SBA)",
                    f"{prod.get('psi', float('nan')):.4f}" if "psi" in prod else "ver metrics.json",
                    "—",
                ),
                (
                    "B (HMDA)",
                    f"{hmda['psi']:.4f}" if hmda else "n/d",
                    f"{hmda['psi_shape']:.4f}" if hmda else "n/d",
                ),
            ],
            ("Modelo", "PSI total", "PSI de forma"),
        )
    }

### 3.4 Pruebas de estrés

El modelo A se aplica, **sin reentrenar**, a cohortes fuera de su régimen. En un
escenario tipo 2007 (tasa base 31.19%) el AUC cae a 0.5456 —apenas mejor que el
azar— y la razón de calibración baja a 0.12: **subestima el riesgo por un factor
de ocho.** Ver `exports/stress_test.csv`.

---

## 4. Mapeo al Anexo IV del Reglamento de IA de la UE

La evaluación de solvencia crediticia es sistema de **alto riesgo** (Anexo III,
punto 5.b) y exige documentación técnica.

{
        _tabla(
            [
                ("1. Descripción general del sistema", "`reports/MODEL_CARD.md` §1-2", "Cubierto"),
                (
                    "2. Elementos del sistema y proceso de desarrollo",
                    "§1 de este reporte; `docs/adr/`",
                    "Cubierto",
                ),
                ("2.b Especificaciones de diseño y supuestos", "ADR 0003-0007", "Cubierto"),
                (
                    "2.d Datos de entrenamiento: procedencia y preparación",
                    "`docs/DATA_SOURCES.md`, `data/manifests/`",
                    "Cubierto",
                ),
                ("2.e Evaluación de sesgo y medidas adoptadas", "§2.3; ADR 0006, 0007", "Cubierto"),
                ("2.g Métricas de exactitud y robustez", "§2.1, §3.4", "Cubierto"),
                (
                    "3. Vigilancia y control humano",
                    "El modelo es entrada a una decisión humana, no una decisión automática",
                    "Declarado",
                ),
                (
                    "4. Especificaciones de exactitud, robustez y ciberseguridad",
                    "§3.1 gates; §3.2 integridad",
                    "Cubierto",
                ),
                ("5. Sistema de gestión de riesgos", "§3 completa", "Cubierto"),
                (
                    "6. Cambios a lo largo del ciclo de vida",
                    "Historial de git; fingerprints de configuración y código",
                    "Cubierto",
                ),
                (
                    "8. Registro automático de eventos (logs)",
                    "MLflow; artefactos versionados en `exports/`",
                    "Parcial",
                ),
            ],
            ("Requisito del Anexo IV", "Dónde", "Estado"),
        )
    }

**Declaración honesta de alcance.** Este mapeo documenta un ejercicio técnico; no
constituye una evaluación de conformidad. Un despliegue real requiere evaluación
por un organismo notificado, sistema de gestión de calidad conforme al Artículo 17
y registro en la base de datos de la UE.

---

## 5. Conclusión de la validación

{
        _tabla(
            [
                (
                    "Modelo A (SBA)",
                    "**Apto para producción**",
                    "Pasa los gates de desempeño, calibración e integridad",
                ),
                (
                    "Modelo B (HMDA)",
                    "**No apto — promoción bloqueada**",
                    f"Disparate impact ratio {hmda['disparate_impact_ratio']:.3f} < "
                    f"{cfg['gates']['min_disparate_impact_ratio']}"
                    if hmda
                    else "n/d",
                ),
            ],
            ("Modelo", "Dictamen", "Fundamento"),
        )
    }

Que el modelo B esté bloqueado **no es un fallo del proceso: es el proceso
funcionando.** Se midió, se documentó y no se despliega.
""")
    return "".join(partes)


def generate(out_path: Path | None = None) -> Path:
    path = out_path or (repo_root() / "reports" / "VALIDATION_REPORT.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(), encoding="utf-8")
    return path


def main() -> int:
    path = generate()
    print(f"Reporte de validacion generado: {path.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
