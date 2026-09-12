# credit-risk-mlops

Sistema de decisión crediticia con gobierno de modelos, sobre datos públicos reales
de EE.UU. El modelo no es el punto. **El punto es que sobrevive una auditoría — y que
la auditoría la corrí primero contra mí mismo.**

> 🇬🇧 [English version](README.md) · Bitácora: [NOTES.md](NOTES.md) ·
> Decisiones de arquitectura: [docs/adr/](docs/adr/)

El README en inglés es el principal porque el mercado objetivo es empleo remoto en
EE.UU. Los ADRs, la bitácora y los comentarios del código están en español: ahí está
la profundidad, y ahí es donde un revisor hispanohablante va a entrar.

---

## Lo que encontró

Todo proyecto muestra la corrida que funcionó. Este publica el registro de lo que se
rompió, porque es la parte que no se puede falsificar y la que predice cómo trabaja
alguien. Cada fila enlaza al artefacto que lo prueba.

| # | Qué se rompió | Por qué importa |
|---|---|---|
| 1 | **AUC 0.9461** se veía bien. `TermInMonths` se sobrescribe al liquidar el préstamo: el campo filtraba el resultado. Quitarlo baja la ablación a **0.6621** | [ADR 0002](docs/adr/0002-terminmonths-es-fuga.md) · borré mi mejor número a propósito |
| 2 | El split temporal cruzaba una tasa base cíclica. Validación puntuaba *peor* que test y el PSI llegó a **4.08**. Rediseñado con dos criterios medidos | [ADR 0003](docs/adr/0003-diseno-del-split-temporal.md) |
| 3 | `exports/metrics.json` era editable a mano. **Escribí AUC 0.95 y todos los gates pasaron.** El fingerprint tampoco cubría el código | [docs/AUDIT.md](docs/AUDIT.md) · los dos cerrados |
| 4 | El verificador de cumplimiento de los avisos usaba `"\b"` en una cadena no-raw: eso es el carácter **backspace**, no un límite de palabra. El control no detectaba nada, en silencio | Semana 8 · lo encontró probar el verificador contra salida mala |
| 5 | Reporté la inconsistencia del LLM como hallazgo sobre inferencia local. Era **mi medición**: la primera generación tras cargar el modelo no es determinista. Con calentamiento, un brazo pasó de 0% a 83% | [ADR 0009](docs/adr/0009-la-plantilla-gana-al-llm.md) |
| 6 | El hook de autoría **fallaba abierto**. `grep` devuelve ≠0 tanto si no encuentra nada como si no pudo buscar. Con `sh.exe` sin `/usr/bin` en el PATH: `grep: command not found`, salida 0, **trailer de IA aceptado en silencio** | Ahora falla cerrado · 18 tests |
| 7 | `run all` imprimió **`APROBADO: 8 gates pasaron`** después de que el entrenamiento reventara. Los gates leen métricas commiteadas, así que pasaron sin modelo nuevo | [tests/test_run_aborta.py](tests/test_run_aborta.py) |
| 8 | **CI estuvo rojo 8 commits seguidos** mientras yo escribía "lint verde, N tests" en cinco mensajes. Un test asertaba configuración local de git que CI nunca pone | Corregido · y [`run ci-local`](scripts/ci_local.py), que reproduce CI antes de empujar |
| 9 | Dos números publicados **no replicaron en otra máquina**: el benchmark DuckDB/PySpark (29.3x → 14.3x) y la consistencia del LLM (0.83 → 0.33). Había presentado mediciones de un equipo como propiedades del sistema | Los dos retractados y reformulados como rangos |
| 10 | `MODEL_CARD.md` listaba **7 gates de 8**: su generador nunca llamaba al de equidad, el único que el modelo no cumple. Y `VALIDATION_REPORT.md` imprimía `PASA` para ese gate en §3.1 mientras §5 decía "promoción bloqueada" | La causa era mía: un booleano significaba dos cosas. Ahora `passed` ≠ `threshold_met` |

Registro completo en [NOTES.md](NOTES.md) y [docs/AUDIT.md](docs/AUDIT.md). Tres de
estos **fallaban en silencio o reportaban éxito** — que es el modo de fallo que el
proyecto entero persigue, encontrado en su propio tooling.

---

## Qué hace

| Modelo | Fuente | Target | Ancla regulatoria |
|---|---|---|---|
| **A — Default / Pérdida** | SBA 7(a) FOIA · 1.96M préstamos, FY1991–2026 | Charge-off (PD) + severidad (LGD) | [SR 26-2](docs/adr/0012-el-ancla-regulatoria-cambio.md) |
| **B — Underwriting / Acceso** | HMDA · **62.4M solicitudes**, FY2020–2024 | Denegación | ECOA / Reg B |

Los conteos de HMDA se verifican contra las agregaciones publicadas por el CFPB: una
descarga que termina no es una descarga **completa**.

## Los números, con su contrapeso

Rechazar el 10% más riesgoso de la cartera de prueba FY2017–2018 habría evitado
**$276.3M** en charge-offs — 2.15x lo que logra rechazar al azar — y **$942.1M** de la
pérdida realizada del período los absorbió la SBA, es decir el contribuyente.

Y la parte que una presentación de ventas omite: hacerlo **renuncia a $1.99B de
volumen sano**, 7.2x la pérdida evitada. Los dos números viajan en el mismo payload
([`exports/web/resumen.json`](exports/web/resumen.json)), porque un titular que
muestra solo el numerador no es un titular.

| | |
|---|---|
| AUC (test, out-of-time) | **0.7005** |
| Margen sobre el scorecard WoE interpretable | **+0.0311** |
| Error de calibración (ECE) | **0.0107** |
| En un régimen tipo 2007 | **AUC 0.5456**, y subestima el riesgo 8x |

Esa última fila no es una salvedad, es un entregable: `run stress` existe para
responder qué pasa cuando cambia el régimen.

## Inferencia causal

El modelo responde *"¿quién va a incumplir?"*. La palanca que la SBA controla de
verdad exige otra pregunta — *"¿qué pasa si cambiamos el % de garantía?"* — porque
**la SBA no origina préstamos, garantiza**.

`run causal` la responde, y la respuesta es que **no se puede responder con estos
datos**. Tres diagnósticos sobre 1.398.416 préstamos:

| Diagnóstico | Medición | Consecuencia |
|---|---|---|
| ¿El tratamiento tiene variación propia? | **R² = 0.9145** sobre celdas (método × tramo de $10k) | Sin solapamiento: DML y causal forests no tienen qué explotar |
| ¿Sirve un RD en el umbral de $150.000? | **83.1%** de la ventana ±$5k está *exactamente* en $150.000 | Densidad destruida: la asignación no es local-aleatoria |
| ¿El gradiente crudo es composición? | **+7.76 pp** crudo → **+4.79 pp** dentro del mismo tramo | Sobrevive un residual, y su signo es el que predice la selección adversa |

**No se publica un efecto.** Un estimador aplicado donde sus supuestos no se cumplen
produce un número, no una estimación. Lo que se publica es la no-identificación con
sus tres mediciones — [ADR 0013](docs/adr/0013-el-efecto-de-la-garantia-no-esta-identificado.md).

Esto también nombra el supuesto dentro del propio titular del proyecto: los $276.3M
se calculan rankeando por PD predicha y suponiendo que rechazar elimina la pérdida.
Dos afirmaciones causales dentro de un número presentado como predicción.

## Monitoreo

Un charge-off tarda una **mediana de 51 meses** en aparecer. A los 12 meses se ve
alrededor del **1%** de los que esa cosecha acabará teniendo. Así que monitorear
desempeño en cosechas jóvenes es imposible, y el proyecto **se niega a fingirlo**.

| Señal | `run <tarea>` | Qué detecta |
|---|---|---|
| Madurez de la etiqueta | `maturity` | Qué cosechas se pueden evaluar, comparando tasas a **madurez pareja** |
| Deriva de población | `drift` | PSI por feature y del score, más **masa sin soporte** en las categóricas |
| Decisión | `retrain-check` | Los tres disparadores, y qué arregla y qué no reentrenar |

**Lo que encontró en su primera corrida:** el SBA cambió el esquema de categorías de
`business_age` entre FY2018 y FY2021. Hoy el **84%** de sus valores cae en categorías
que el modelo nunca vio. Es el **segundo information value** del baseline
interpretable (0.0536, detrás de `initial_rate` con 0.1461), y el serving manda lo no
visto a "desconocido" — así que el modelo no se degrada: **pierde la variable entera y
sigue respondiendo con el mismo aplomo**.
[ADR 0011](docs/adr/0011-la-fuente-cambio-el-vocabulario.md).

## Gates de promoción

Diez gates. Un modelo no se promueve si no los pasa, y CI los corre en cada PR.
Detalle completo en el [README en inglés](README.md#promotion-gates) y las
derivaciones de cada umbral en `config.yaml`.

El veredicto distingue dos cosas que antes se confundían: **`passed`** es "el build no
se rompe" y **`threshold_met`** es "el modelo cumple". Para el gate de equidad no
coinciden, y hoy se lee `NO CUMPLE (build ok: no se promueve)` con un disparate impact
de 0.7639.

## Verifícalo

Ningún número de este README vale más que el comando que lo reproduce. Un solo
prerrequisito: [`uv`](https://docs.astral.sh/uv/).

```powershell
.\run setup      # Python 3.12 + dependencias + hook de autoría
.\run test       # la suite. Imprime su propio conteo; no le creas al mío
.\run gates      # los diez gates, recomputados desde las predicciones guardadas
```

Esos tres **no descargan nada**: `exports/metrics.json` está commiteado y el gate de
integridad recomputa sus métricas desde las predicciones guardadas, así que el modelo
se puede auditar sin acceso a las fuentes. Es la razón por la que CI no descarga nada.

Paso a paso completo, extras opcionales y problemas conocidos:
**[docs/INSTALL.md](docs/INSTALL.md)**.

## Qué NO es

- **No está en producción y su exposición es nula.** Bajo SR 26-2 la materialidad
  sigue al propósito y a la exposición; esto es un ejercicio de referencia y lo dice
  en su propio reporte de validación.
- **No es una evaluación de conformidad.** SR 26-2 y el Anexo IV del Reglamento de IA
  de la UE se usan como estructura y vocabulario, no como certificación.
- **No es una decisión automática de crédito.** Es una entrada a una decisión humana.
- **El reject inference no está resuelto.** Solo los préstamos aprobados tienen
  resultado, así que el modelo describe el riesgo *condicionado a haber sido
  aprobado*. Se discute, no se arregla.
- **El artefacto ONNX no es hash-estable.** El modelo reproduce —5 nodos idénticos,
  predicciones bit a bit iguales sobre 20.000 filas— pero re-exportar da bytes
  distintos. La distinción importa en un proyecto que vende auditabilidad, así que
  queda escrita.

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
