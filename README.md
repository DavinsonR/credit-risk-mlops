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

```bash
make setup          # entorno con uv (Python 3.12)
make acquire        # descarga fuentes + verifica hashes
make signal-check   # ¿existe poder discriminante? gate de viabilidad
```

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
