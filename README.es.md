# credit-risk-mlops

Un sistema de decisión crediticia gobernado como lo gobierna la función de riesgo de
modelos de un banco, construido de punta a punta sobre **más de 64M de registros
públicos reales de EE.UU.**: ingesta, modelado, inferencia causal, auditoría de
préstamo justo, serving, monitoreo y una capa LLM para avisos regulatorios.

El modelo no es el punto. **El punto es que sobrevive una auditoría — y que la
auditoría la corrí primero contra mí mismo.**

> 🇬🇧 [English version](README.md) · Decisiones de arquitectura: [docs/adr/](docs/adr/) ·
> Registro de defectos: [docs/DEFECTS.es.md](docs/DEFECTS.es.md) · Bitácora: [NOTES.md](NOTES.md)

Los ADRs, la bitácora y los comentarios del código están en español: ahí está la
profundidad.

**Stack:** Python 3.12 · DuckDB · LightGBM · scikit-learn · optbinning (scorecard WoE) ·
PyTorch · MLflow · ONNX Runtime · FastAPI · Docker · PySpark · Power BI (PBIP/TMDL) ·
GitHub Actions · `uv`

---

## De un vistazo

| | |
|---|---|
| Datos | **1.96M** préstamos SBA 7(a) (FY1991–2026) · **62.4M** solicitudes HMDA (FY2020–2024) · **93.4M** para el estudio de evento (FY2018–2025) |
| Discriminación | **AUC 0.7005** out-of-time, **+0.0311** sobre un scorecard WoE interpretable |
| Calibración | **ECE 0.0107** |
| Impacto de negocio | **$276.3M** en charge-offs evitados rechazando el 10% más riesgoso — **2.15x** el azar |
| Gobierno | **10 gates de promoción** en CI; las métricas se **recomputan** desde las predicciones guardadas, nunca se creen |
| Documentación | **14 ADRs**, model card y reporte de validación estructurado sobre SR 26-2 y el Anexo IV del Reglamento de IA de la UE |
| Serving | Un artefacto ONNX, **tres runtimes** (FastAPI, serverless, WASM en el navegador), con paridad probada |
| Pruébalo | [Puntúa un préstamo en el navegador](https://davirson.com/es/projects/credit-risk#demo): cuatro campos, sin servidor y sin que nada salga de la página |

## Qué demuestra

| Capacidad | Evidencia |
|---|---|
| **Gobierno de riesgo de modelos** | Gates de promoción que recomputan métricas y toman la huella del config *y* del código de modelado; cambiar cualquiera sin reentrenar rompe el build |
| **Detección de fugas** | Una auditoría de contaminación que atrapó un campo post-originación que inflaba el AUC a 0.946 — [ADR 0002](docs/adr/0002-terminmonths-es-fuga.md) |
| **Validación out-of-time y estrés** | Split diseñado alrededor de tasas base cíclicas y censura de la etiqueta; un régimen tipo 2007 puntuado como entregable — [ADR 0003](docs/adr/0003-diseno-del-split-temporal.md) |
| **Inferencia causal** | Dos diseños, dos no-identificaciones medidas, cero efectos publicados sin identificación — [ADR 0013](docs/adr/0013-el-efecto-de-la-garantia-no-esta-identificado.md), [ADR 0014](docs/adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md) |
| **Préstamo justo** | Regla de los cuatro quintos por clase protegida; el modelo de acceso queda **bloqueado para promoción** con 0.7639 |
| **Monitoreo en producción** | Madurez de la etiqueta, deriva por PSI y masa sin soporte, y una decisión explícita de reentrenamiento |
| **Ingeniería de LLM** | Avisos de adverse action con respaldo determinista, evaluaciones programáticas y ningún LLM como juez — [ADR 0009](docs/adr/0009-la-plantilla-gana-al-llm.md) |
| **Reproducibilidad** | `run reproduce` reentrena y exige métricas idénticas a las commiteadas; `run ci-local` reproduce CI antes de empujar |

---

## Dos modelos, dos regímenes regulatorios

| Modelo | Fuente | Target | Ancla regulatoria |
|---|---|---|---|
| **A — Default / Pérdida** | SBA 7(a) FOIA · 1.96M préstamos, FY1991–2026 | Charge-off (PD) + severidad (LGD) | [SR 26-2](docs/adr/0012-el-ancla-regulatoria-cambio.md) |
| **B — Underwriting / Acceso** | HMDA · **62.4M solicitudes**, FY2020–2024 | Denegación | ECOA / Reg B |

Los archivos de SBA se adquieren con descubrimiento de URLs y se verifican contra un
manifiesto SHA256. Los conteos de HMDA se verifican contra las agregaciones publicadas
por el CFPB: una descarga que termina no es una descarga **completa**. Cada ventana de
análisis está declarada en `config.yaml`, así que ampliar la del estudio de evento no
puede mover las cifras del modelo publicado.

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

### El shock de tasas de 2022: la brecha no se amplió, volvió

El diseño alternativo es el shock de tasas de 2022 sobre HMDA: exógeno, grande, con
clases protegidas en el dato y **con períodos previos contra los cuales falsificar**.
`run event-study` lo corre sobre **93.4M solicitudes, FY2018–2025**, y su primer
resultado es que un hallazgo anterior del propio proyecto estaba medido contra la
línea base equivocada.

| | Brecha de denegación negros–blancos |
|---|---|
| FY2018–2019 — tasas corrientes | **15.70 pp** |
| FY2020–2021 — auge de refinanciación | 13.14 pp |
| FY2023–2025 — post-shock | **15.73 pp** |

**La brecha post-shock está a 0.03 pp de la pre-pandemia.** Contra 2021 la ampliación
es de +2.59 pp, y ese es el número que circula: mide el auge acabándose.

De ese movimiento, una descomposición de Kitagawa —exacta, sin residuo— atribuye el
**65% a la recomposición del pool**: la refinanciación se desplomó 92% y era el
segmento con la denegación más baja. En FY2024 el término de tasas es **negativo**: la
brecha se cerró dentro de los segmentos mientras el agregado subía.

Y no se publica ningún efecto causal, por tres razones medidas:

| Comprobación | Resultado |
|---|---|
| Tendencias previas paralelas (umbral declarado **antes** de estimar) | **Falla**: +2.37 pp en 2018, y monótona — una tendencia, no ruido |
| El arreglo de manual: extrapolar la tendencia previa | Fabrica **+5.61 pp**, porque lo que extrapola *es* el auge que el shock termina |
| Selección diferencial en el pool de solicitantes | **17.2 pp**: las solicitudes negras cayeron 40%, las blancas 57% |

[ADR 0014](docs/adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md). En SBA
no había **con qué** falsificar. Aquí sí, el test corrió, y **la falsificación es la
que cierra el caso**. Un diseño que no puede fallar su propio test no está
identificando nada: solo no ha mirado.

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

**Y cuánto cuesta arreglarlo.** `run harmonize` entrena el modelo de producción dos
veces, mismo split y misma semilla, cambiando solo ese vocabulario:

| | AUC (test) | Cobertura de FY2024–2026 |
|---|---|---|
| Vocabulario crudo | 0.7005 | **15.4%** |
| Armonizado | 0.6990 | **90.1%** |

**0.0015 de AUC compra 74.7 puntos de cobertura.** Lo que no se mueve: el 9.7% sigue
sin soporte, porque `Change of Ownership` no es una antigüedad sino una forma de
adquisición, y mapearla sería inventar el dato.

## La capa LLM

Denegar crédito bajo ECOA/Reg B **obliga legalmente** a dar las razones principales
específicas. Es el único sitio donde un modelo de lenguaje tiene un trabajo real aquí:
SHAP elige los factores y el modelo solo los reescribe en lenguaje claro — y **su salida
se valida contra la plantilla antes de usarse**, así que el peor caso es exactamente el
baseline.

El harness compara cinco brazos sobre los mismos seis avisos, con cuatro métricas
programáticas (ningún LLM como juez) y **dos corridas por caso**, porque un documento
legal que cambia entre ejecuciones es indefendible.

| Brazo | Fidelidad | Cumple | Legibilidad | Consistencia | Pasa |
|---|---|---|---|---|---|
| **Plantilla determinista** | 1.00 | 1.00 | 44.8 | **1.00** | **100%** |
| **gpt-oss-120b · híbrido (Groq)** | 1.00 | 1.00 | **52.3** | **1.00** | **100%** |
| gemini-flash-lite · solo | 1.00 | 1.00 | 57.8 | **0.00** | 0% |
| qwen2.5:7b · híbrido (local) | 1.00 | 1.00 | 53.4 | 0.67 | 67% |
| llama3.2:3b · solo (local) | 0.50 | 1.00 | 74.6 | 0.50 | 0% |

**Gemini contestó las doce llamadas con fidelidad perfecta y nunca produjo el mismo
texto dos veces**, con temperatura 0. Para un documento cuya obligatoriedad es legal eso
descalifica por sí solo, sin necesidad de discutir la calidad de la prosa.

El híbrido sobre Groq es el único brazo que empata a la plantilla en todas las métricas
de la compuerta y la supera en legibilidad, en los dos idiomas. **La plantilla se queda
en producción**: el retador es igual de bueno y más frágil — necesita red, un tercero y
una cuota.

Las cifras de consistencia se publican solo desde corridas repetidas, nunca desde una
sola.

## Gates de promoción

Diez gates. Un modelo no se promueve si no los pasa, y CI los corre en cada PR.
Detalle completo en el [README en inglés](README.md#promotion-gates) y las
derivaciones de cada umbral en `config.yaml`.

El veredicto separa dos preguntas: **`passed`** es "el build no se rompe" y
**`threshold_met`** es "el modelo cumple". Para el gate de equidad no coinciden, y hoy
se lee `NO CUMPLE (build ok: no se promueve)` con un disparate impact de 0.7639.

## Disciplina de ingeniería

Cada defecto encontrado durante la construcción está registrado con su causa raíz y el
control que hoy lo impide — **[docs/DEFECTS.es.md](docs/DEFECTS.es.md)**. La auditoría
adversarial de la capa de gobierno está en [docs/AUDIT.md](docs/AUDIT.md), y cada
decisión de diseño tiene su [ADR](docs/adr/).

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

En Linux/macOS cada tarea es un target de `make`.

**O simplemente puntúa un préstamo:** el artefacto ONNX de producción corre en el
navegador, sin servidor y sin que nada salga de la página —
[davirson.com/es/projects/credit-risk](https://davirson.com/es/projects/credit-risk#demo).
Cuatro campos bastan y el resultado se recalcula en cada cambio; los otros nueve arrancan
con valores típicos, y el cálculo completo enseña el vector exacto que recibe el modelo.
Pon la antigüedad en `Change of Ownership` para ver en vivo el hallazgo del monitoreo:
la categoría no está en el contrato, se codifica como desconocida y el modelo responde
con el mismo aplomo.

Paso a paso completo, extras opcionales y problemas conocidos:
**[docs/INSTALL.md](docs/INSTALL.md)**. Y al lado, dos procedimientos más:
**[docs/POWERBI.md](docs/POWERBI.md)** (abrir el informe en Desktop) y
**[docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)** (los brazos hospedados).

## Alcance

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

Lo que sigue está priorizado por cuánto cambia el resultado:
**[docs/ROADMAP.md](docs/ROADMAP.md)**.

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
