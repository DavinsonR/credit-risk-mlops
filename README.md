# credit-risk-mlops

Sistema de decisión crediticia con gobierno de modelos, construido sobre datos
públicos reales de EE.UU. El diferenciador no es el modelo: es que **sobrevive
una auditoría**.

> 🚧 En construcción. Ver [NOTES.md](NOTES.md) para la bitácora y
> [docs/adr/](docs/adr/) para las decisiones de arquitectura.

## Qué hace

| Modelo | Fuente | Target | Ancla regulatoria |
|---|---|---|---|
| **A — Default / Pérdida** | SBA 7(a) FOIA (~1.5M préstamos, FY1991–presente) | Charge-off (PD) + severidad (LGD) | SR 11-7 |
| **B — Underwriting / Acceso** | HMDA (FFIEC/CFPB, ~10M solicitudes/año) | Denegación | ECOA / Reg B |

## Principios

1. **Validación out-of-time, nunca split aleatorio.** El corte cruza el shock COVID.
2. **El baseline es un scorecard WoE + logística** — el estándar de industria. Los
   retadores tienen que ganarle.
3. **Calibración antes que ranking.** Sin probabilidades calibradas no hay expected loss.
4. **El umbral se elige por utilidad en dólares**, no por F1.
5. **Las transformaciones fit-on-train no viven en dbt** — filtrarían. dbt se queda
   en bronze/silver; el feature engineering va en Python.
6. **Ningún dato crudo se commitea.** `make acquire` los baja y verifica por SHA256.

## Uso

**Windows** (no requiere `make`):

```powershell
.un.ps1 setup       # entorno con uv (Python 3.12)
.un.ps1 acquire     # descarga fuentes + verifica hashes
.un.ps1 all         # train -> gates -> model card -> economía
.un.ps1 help        # todas las tareas
```

**Linux / macOS** (lo que corre CI):

```bash
make setup
make acquire
make train && make gates && make card
```

## Gates de promoción

El modelo no se promueve si no pasa los siete gates, y CI los ejecuta en cada PR:

| Gate | Qué garantiza |
|---|---|
| `config_coherente` | Las métricas corresponden al `config.yaml` actual |
| `integridad` | Las métricas se **recomputan** desde las predicciones, no se creen |
| `auc_test` | Piso absoluto de discriminación |
| `margen_sobre_baseline` | El retador supera al scorecard interpretable por ≥0.02 |
| `drop_oot` | La degradación out-of-time no excede 2x la variación natural |
| `brier_test` | Le gana al predictor sin habilidad (constante = tasa base) |
| `ece_test` | Predicho y observado coinciden dentro de 2 puntos porcentuales |

Cada umbral tiene su derivación escrita al lado en `config.yaml`. Ninguno se eligió
porque el modelo lo pasaba — ver [docs/AUDIT.md](docs/AUDIT.md).

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
