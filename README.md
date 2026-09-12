# credit-risk-mlops

Sistema de decisión crediticia con gobierno de modelos, construido sobre datos
públicos reales de EE.UU. El diferenciador no es el modelo: es que **sobrevive
una auditoría**.

> 🚧 En construcción. Ver [NOTES.md](NOTES.md) para la bitácora y
> [docs/adr/](docs/adr/) para las decisiones de arquitectura.

## Qué hace

| Modelo | Fuente | Target | Ancla regulatoria |
|---|---|---|---|
| **A — Default / Pérdida** | SBA 7(a) FOIA · 1.96M préstamos, FY1991–2026 | Charge-off (PD) + severidad (LGD) | SR 26-2 |
| **B — Underwriting / Acceso** | HMDA · **62.4M solicitudes**, FY2020–2024 | Denegación | ECOA / Reg B |

Los datos de HMDA se verifican contra los conteos oficiales del CFPB: no basta con
que la descarga termine, tiene que estar **completa**.

## Principios

1. **Validación out-of-time, nunca split aleatorio.** El corte cruza el shock COVID.
2. **El baseline es un scorecard WoE + logística** — el estándar de industria. Los
   retadores tienen que ganarle.
3. **Calibración antes que ranking.** Sin probabilidades calibradas no hay expected loss.
4. **El umbral se elige por utilidad en dólares**, no por F1.
5. **Las transformaciones fit-on-train no viven en dbt** — filtrarían. dbt se queda
   en bronze/silver; el feature engineering va en Python.
6. **Ningún dato crudo se commitea.** `make acquire` los baja y verifica por SHA256.
7. **Las clases protegidas se conservan para medir, jamás para entrenar.** Sin ellas
   en el panel no se puede calcular disparate impact; con ellas en el modelo se
   discrimina. Ver [ADR 0006](docs/adr/0006-exclusiones-en-hmda.md).

## Instalación

El único prerrequisito es [`uv`](https://docs.astral.sh/uv/). Python 3.12 y todas
las dependencias las instala el propio proyecto — no hace falta tener Python.

**Windows** (no requiere `make`):

```powershell
.\run setup       # Python 3.12 + dependencias + hook de autoría
.\run test        # verifica la instalación sin descargar nada
.\run acquire     # descarga fuentes + verifica hashes (~860 MB)
.\run all         # train -> gates -> model card -> economía
.\run help        # todas las tareas
```

`.\run` es `run.cmd`: en un Windows por defecto la ExecutionPolicy es `Restricted`
y ningún `.ps1` arranca. El script real vive en `scripts/run.ps1` —fuera de la
raíz a propósito, porque PowerShell resuelve `.\run` al `.ps1` si están juntos— y
el `.cmd` lo invoca sin cambiar nada de tu sistema. Detalle en
[docs/INSTALL.md](docs/INSTALL.md).

**Linux / macOS** (lo que corre CI):

```bash
make setup
make test
make acquire
make train && make gates && make card
```

Paso a paso completo —extras opcionales, LLM local, PySpark, Docker, y qué debe
imprimir cada comando— en **[docs/INSTALL.md](docs/INSTALL.md)**.

## Inferencia causal

El modelo responde *"¿quién va a incumplir?"*. La palanca que la SBA controla de
verdad exige otra pregunta: *"¿qué pasa si cambiamos el % de garantía?"* — porque
**la SBA no origina préstamos, garantiza**.

`run causal` la responde, y la respuesta es que **no se puede responder con estos
datos**. Tres diagnósticos sobre 1.398.416 préstamos:

| Diagnóstico | Medición | Consecuencia |
|---|---|---|
| ¿El tratamiento tiene variación propia? | **R² = 0.9145** sobre celdas (método × tramo de $10k) | Sin solapamiento: DML y causal forests quedan sin variación que explotar |
| ¿Sirve un RD en el umbral de $150.000? | **83.1%** de la ventana ±$5k está *exactamente* en $150.000 | Densidad destruida: la asignación no es local-aleatoria |
| ¿El gradiente crudo es composición? | **+7.76 pp** crudo → **+4.79 pp** dentro del mismo tramo de tamaño | Queda un residual, y su signo es el que predice la **selección adversa** |

**No se publica un efecto.** Un estimador aplicado donde sus supuestos no se cumplen
produce un número, no una estimación. Lo que se publica es la no-identificación, con
sus tres mediciones y la vía alternativa nombrada — ver
[ADR 0013](docs/adr/0013-el-efecto-de-la-garantia-no-esta-identificado.md).

Esto también nombra el supuesto del titular del proyecto: los **$276.3M evitados** se
calculan rankeando por PD predicha y suponiendo que rechazar elimina la pérdida. Son
dos supuestos causales dentro de un número presentado como predicción.

## Monitoreo

En crédito la etiqueta tarda **51 meses medianos** en existir, así que el monitoreo
de desempeño sobre cosechas jóvenes es imposible y el proyecto **se niega a
fingirlo**. Se monitorea lo que sí se puede medir el día que llega el vintage:

| Señal | `run <tarea>` | Qué detecta |
|---|---|---|
| Madurez de la etiqueta | `maturity` | Qué cosechas se pueden evaluar, y compara tasas a **madurez pareja** |
| Deriva de población | `drift` | PSI por feature y del score, más **masa sin soporte** en las categóricas |
| Decisión | `retrain-check` | Los tres disparadores, y qué arregla y qué no reentrenar |

**Lo que encontró en su primera corrida:** el SBA cambió el vocabulario de
`business_age` entre FY2018 y FY2021, y hoy el **84%** de sus valores cae en
categorías que el modelo no vio. Es el primer driver de SHAP, y el serving lo manda
a "desconocido" sin avisar — ver
[ADR 0011](docs/adr/0011-la-fuente-cambio-el-vocabulario.md).

`.github/workflows/monitor.yml` revisa cada mes si hay vintage nuevo y solo entonces
recalcula.

## Gates de promoción

El modelo no se promueve si no pasa los diez gates, y CI los ejecuta en cada PR:

| Gate | Qué garantiza |
|---|---|
| `config_coherente` | Las métricas corresponden al `config.yaml` actual |
| `integridad` | Las métricas se **recomputan** desde las predicciones, no se creen |
| `auc_test` | Piso absoluto de discriminación |
| `margen_sobre_baseline` | El retador supera al scorecard interpretable por ≥0.02 |
| `drop_oot` | La degradación out-of-time no excede 2x la variación natural |
| `brier_test` | Le gana al predictor sin habilidad (constante = tasa base) |
| `ece_test` | Predicho y observado coinciden dentro de 2 puntos porcentuales |
| `hmda:disparate_impact` | Criterio de los cuatro quintos por clase protegida. **Hoy da 0.7639 y por eso el modelo de acceso no está promovido** |
| `reporte:MODEL_CARD.md` | El model card describe las métricas publicadas, no unas viejas |
| `reporte:VALIDATION_REPORT.md` | Idem para el reporte de validación |

Los dos últimos existen porque **hicieron falta**: el model card estuvo congelado
seis semanas, listando 7 gates y omitiendo justamente el que no cumple, y el reporte
de validación imprimía `PASA` en una sección y "promoción bloqueada" en otra, del
mismo gate. Un reporte rancio es peor que no tener reporte, porque se cita.

El veredicto distingue dos cosas que antes se confundían: **`passed`** es "el build
no se rompe" y **`threshold_met`** es "el modelo cumple". Para el gate de equidad no
coinciden, y ahora se lee `NO CUMPLE (build ok: no se promueve)`.

Cada umbral tiene su derivación escrita al lado en `config.yaml`. Ninguno se eligió
porque el modelo lo pasaba — ver [docs/AUDIT.md](docs/AUDIT.md).

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
