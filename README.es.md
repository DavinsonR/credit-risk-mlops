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
| 11 | Tres módulos definían su muestra de análisis con `glob("*.parquet")`. **El sistema de archivos decidía qué significaba "62.4M solicitudes".** Descargar tres años más para el estudio de evento habría movido en silencio la disparidad observada, el benchmark de backends y ese encabezado — y ningún test habría fallado, porque todos leen el mismo directorio que el código | Encontrado al ir a tropezarlo · la ventana sale de `config.yaml` · [tests](tests/test_hmda_shard_selection.py) |
| 12 | La instrumentación del híbrido pasaba sus campos nuevos **solo en la rama de error** de `evaluate()`. En cada éxito —o sea, en todos los casos a analizar— llegaban vacíos, pandas leyó `NaN`, `.astype(bool)` lo hizo `False`, y el reporte publicó una conclusión sobre un campo que nunca se llenó | [ADR 0009 rev. 3](docs/adr/0009-la-plantilla-gana-al-llm.md) · el análisis ahora se niega a concluir sin instrumentación |
| 13 | La demo del navegador **nunca se había pulsado.** El campo de la garantía SBA traía `step="1000"` y un valor por defecto de `187500` —el 75% del préstamo, la cifra correcta— que no es múltiplo de 1000. El formulario nacía inválido y el botón no hacía nada. El modelo ONNX cargaba, la paridad estaba verificada, y lo único que nadie había hecho era pulsar el botón | [tests/test_web_demo_form.py](tests/test_web_demo_form.py) · ahora publicada y bilingüe |
| 14 | **Nadie leía `.env`.** `.env.example` decía "copiar a .env", el harness decía "claves en .env", y los proveedores hacían `os.environ.get(...)`, que solo ve variables de entorno reales. Seguir la instrucción oficial del repo dejaba Groq y Gemini en "no disponibles" — sin error y sin pista | Encontrado al escribir [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md) · [`crmlops.env`](src/crmlops/env.py) · 8 tests |
| 15 | El `.pbip` declaraba un artefacto de informe que **no existía**: solo se había escrito el modelo semántico. Power BI Desktop no abre un proyecto cuyo informe falta, así que la primera línea de la guía era inejecutable. El test del scaffold no lo veía porque comprobaba una lista de archivos escrita a mano, no lo que el propio `.pbip` declara | Encontrado al escribir [docs/POWERBI.md](docs/POWERBI.md) · el test ahora sigue la cadena de artefactos |
| 16 | `run ci-local` copiaba el árbol de trabajo sobre un clon limpio de HEAD pero **nunca borraba nada**, así que un archivo que el commit elimina seguía vivo en el clon. Una eliminación que rompiera CI era invisible para el control hecho justo para eso. Y mirar si el archivo de origen existe tampoco basta: `git ls-files` lista el índice, y un archivo ya eliminado con `git add -A` no está ahí | Encontrado al borrar el `report.json` clásico · ahora compara contra `HEAD` |
| 17 | **Una clave real quedó escrita en tres artefactos que se commitean.** Gemini toma la clave en la query string, así que un 404 de `requests` arrastra la URL entera dentro del texto de la excepción — y ese texto se guardaba tal cual en `Generation.error`, que viaja a `llm_evals_detail.csv`, `llm_evals.json` y `llm_fallback_analysis.csv`. No llegó a git porque lo detecté antes del commit, y eso es suerte, no un control | Los errores se redactan en el borde · [22 tests](tests/test_redaccion_secretos.py), uno de los cuales recorre todos los exports |
| 18 | **El redactor nació con el defecto 4 adentro.** Escribí `"\b"` en una cadena no-raw — otra vez el carácter **backspace**, no un límite de palabra — así que el patrón de claves sueltas no detectaba nada. El mismo error que la bitácora documenta desde la semana 8, repetido dentro del arreglo de seguridad, que es el peor sitio posible | Ahora reutiliza la constante `WORD_BOUNDARY` que existe en `evals.py` justo por esto · un test exige que el patrón compilado no empiece por `\x08` |
| 19 | Los dos modelos hospedados estaban **fijados y habían caducado**: `llama-3.3-70b-versatile` y `gemini-2.0-flash`, los dos 404. El brazo se leía como "el modelo falló" cuando lo que falló era el identificador. Y `GET /v1beta/models` **lista modelos que no se pueden llamar**: `gemini-2.5-flash` aparece en el catálogo y responde *"no longer available"* | El catálogo no es la verdad, la llamada sí · ahora usa el alias `-latest`, que el proveedor reapunta |
| 20 | Con `max_tokens: 500`, `gpt-oss-120b` gastaba **1.887 tokens razonando**, terminaba en `length` y devolvía `content` vacío. El harness lo registraba como "salida vacía" y el brazo salía con **fidelidad 0.33** — mi propia configuración a punto de publicarse como propiedad del modelo, que es exactamente lo que este proyecto ya retractó dos veces | Esfuerzo de razonamiento acotado para que el presupuesto vaya a la respuesta · los 500 tokens siguen siendo iguales para todos los brazos |
| 21 | Publiqué una consistencia de **0.83 medida una sola vez** como evidencia de que la inferencia hospedada reproduce mejor que la local — y volver a correr el mismo harness en la misma máquina, minutos después, dio **0.33**. Los brazos locales dieron el mismo número las dos veces; el que se movió fue el hospedado. **Tercera vez que este proyecto publica una medición como propiedad**, y sobrevivió una hora | [ADR 0009 rev. 5](docs/adr/0009-la-plantilla-gana-al-llm.md) · retractada · ninguna cifra de consistencia se publica con n=1 |

Registro completo en [NOTES.md](NOTES.md) y [docs/AUDIT.md](docs/AUDIT.md). Doce de
estos **fallaban en silencio o reportaban éxito** — que es el modo de fallo que el
proyecto entero persigue, encontrado en su propio tooling.

---

## Qué hace

| Modelo | Fuente | Target | Ancla regulatoria |
|---|---|---|---|
| **A — Default / Pérdida** | SBA 7(a) FOIA · 1.96M préstamos, FY1991–2026 | Charge-off (PD) + severidad (LGD) | [SR 26-2](docs/adr/0012-el-ancla-regulatoria-cambio.md) |
| **B — Underwriting / Acceso** | HMDA · **62.4M solicitudes**, FY2020–2024 | Denegación | ECOA / Reg B |

El estudio de evento corre sobre una ventana más ancha —**93.4M solicitudes,
FY2018–2025**— declarada aparte en `config.yaml` para que ampliarla no pueda mover las
cifras del modelo publicado. Esa separación existe porque una vez no existió: defecto 11.

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

### El shock de tasas de 2022: la brecha no se amplió, volvió

El ADR 0013 dejó dicho que el diseño alternativo era el shock de tasas de 2022 sobre
HMDA: exógeno, grande, con clases protegidas en el dato y **con períodos previos
contra los cuales falsificar**. `run event-study` es ese diseño, sobre **93.4M
solicitudes, FY2018–2025**.

Su primer resultado no es un coeficiente: es que el hallazgo que el propio proyecto
publicó en la semana 6 estaba medido contra la línea base equivocada.

| | Brecha de denegación negros–blancos |
|---|---|
| FY2018–2019 — tasas corrientes | **15.70 pp** |
| FY2020–2021 — auge de refinanciación | 13.14 pp |
| FY2023–2025 — post-shock | **15.73 pp** |

**La brecha post-shock está a 0.03 pp de la pre-pandemia.** Contra 2021 la ampliación
es de +2.59 pp, y ese es el número que circula: mide el auge acabándose. Con cinco
años de panel había exactamente un año pre-shock comparable, así que no había forma
de verlo.

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

[ADR 0014](docs/adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md). La
conclusión se parece a la del ADR 0013 —no se publica un efecto— pero el contenido es
el contrario. En SBA no había **con qué** falsificar. Aquí sí, el test corrió, y **la
falsificación es la que cierra el caso**. Un diseño que no puede fallar su propio test
no está identificando nada: solo no ha mirado.

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

**Y cuánto costó arreglarlo.** El ADR 0011 argumentaba que armonizar el vocabulario
cuesta resolución: cuatro tramos de antigüedad colapsan en uno. Argumentar no es
medir, así que `run harmonize` entrena el modelo de producción dos veces, mismo split
y misma semilla, cambiando solo ese vocabulario:

| | AUC (test) | Cobertura de FY2024–2026 |
|---|---|---|
| Vocabulario crudo | 0.7005 | **15.4%** |
| Armonizado | 0.6990 | **90.1%** |

**0.0015 de AUC compra 74.7 puntos de cobertura.** La intuición era correcta en
dirección y despreciable en magnitud — y escrita sin medir, esa misma frase habría
servido para no hacer nada. Lo que no se mueve: el 9.7% sigue sin soporte, porque
`Change of Ownership` no es una antigüedad sino una forma de adquisición, y mapearla
sería inventar el dato.

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

**O simplemente puntúa un préstamo:** el artefacto ONNX de producción corre en el
navegador, sin servidor y sin que nada salga de la página —
[proyecto-davirson-git.vercel.app/credit-risk-demo](https://proyecto-davirson-git.vercel.app/credit-risk-demo/index.html?lang=es).
Pon la antigüedad en `Change of Ownership` para ver el defecto en vivo: la categoría
no está en el contrato, se codifica como desconocida y el modelo responde con el
mismo aplomo.

Paso a paso completo, extras opcionales y problemas conocidos:
**[docs/INSTALL.md](docs/INSTALL.md)**. Y al lado, dos procedimientos más:
**[docs/POWERBI.md](docs/POWERBI.md)** (armar el informe) y
**[docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)** (encender los brazos de Groq y
Gemini).

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

## Lo que falta

El alcance de las diez semanas está cerrado. Lo que queda está escrito y priorizado
por cuánto cambia el resultado, no por cuándo apareció —
**[docs/ROADMAP.md](docs/ROADMAP.md)**, y el paso a paso con los clics en
**[docs/CHECKLIST.md](docs/CHECKLIST.md)**.

De los once puntos originales quedan **tres, y ninguno es código**: dos claves gratuitas
de API, abrir en Power BI Desktop un informe que ya está escrito y validado contra los
esquemas de Microsoft, y veinticuatro párrafos deliberadamente vacíos en la bitácora que
solo su autor puede llenar — y que escritos por otro no servirían para lo que existen.

## Licencia

MIT (código). Los datos fuente conservan sus propias licencias — ver
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
