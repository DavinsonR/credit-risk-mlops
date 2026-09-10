# credit-risk-mlops

Sistema de decisión crediticia con gobierno de modelos, construido sobre datos
públicos reales de EE.UU. El diferenciador no es el modelo: es que **sobrevive
una auditoría**.

> 🚧 En construcción. Ver [NOTES.md](NOTES.md) para la bitácora y
> [docs/adr/](docs/adr/) para las decisiones de arquitectura.

## Qué hace

| Modelo | Fuente | Target | Ancla regulatoria |
|---|---|---|---|
| **A — Default / Pérdida** | SBA 7(a) FOIA · 1.96M préstamos, FY1991–2026 | Charge-off (PD) + severidad (LGD) | SR 11-7 |
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
.\run.ps1 setup       # Python 3.12 + dependencias + hook de autoría
.\run.ps1 test        # verifica la instalación sin descargar nada
.\run.ps1 acquire     # descarga fuentes + verifica hashes (~860 MB)
.\run.ps1 all         # train -> gates -> model card -> economía
.\run.ps1 help        # todas las tareas
```

**Linux / macOS** (lo que corre CI):

```bash
make setup
make test
make acquire
make train && make gates && make card
```

Paso a paso completo —extras opcionales, LLM local, PySpark, Docker, y qué debe
imprimir cada comando— en **[docs/INSTALL.md](docs/INSTALL.md)**.

## Gates de promoción

El modelo no se promueve si no pasa los ocho gates, y CI los ejecuta en cada PR:

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

Cada umbral tiene su derivación escrita al lado en `config.yaml`. Ninguno se eligió
porque el modelo lo pasaba — ver [docs/AUDIT.md](docs/AUDIT.md).

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
