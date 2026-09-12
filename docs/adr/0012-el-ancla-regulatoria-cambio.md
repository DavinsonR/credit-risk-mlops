# ADR 0012 — El ancla regulatoria cambió: SR 11-7 → SR 26-2

**Fecha:** 2026-09-12
**Estado:** Aceptada
**Verificado contra:** fuente primaria (federalreserve.gov), no contra un resumen

## El hecho

El **17 de abril de 2026** la Reserva Federal, la OCC y la FDIC emitieron
[**SR 26-2, *Revised Guidance on Model Risk Management***](https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm),
que **reemplaza a SR 11-7** (2011) y a SR 21-8 (2021).

El proyecto se construyó citando SR 11-7 como ancla regulatoria del Modelo A —
`README.md`, `reports/VALIDATION_REPORT.md`, `config.yaml`, `stress.py`,
`model_card.py` y el ADR 0003. Esa cita quedó obsoleta cinco meses antes de que el
proyecto empezara.

## Cómo se verificó, y por qué importa el cómo

La señal vino de un análisis secundario que afirmaba, además del reemplazo, que
SR 26-2 exige *"tiering por materialidad, champion/challenger, pruebas de
sensibilidad versionadas y reproducibles, y monitoreo continuo con umbrales atados
a materialidad"* — es decir, casi exactamente lo que este proyecto ya tiene. Un
encaje así de conveniente es motivo para desconfiar, no para celebrar.

Se descargó el documento y se buscaron los términos uno por uno:

| Término | Ocurrencias en SR 26-2 |
|---|---|
| `materiality` | **7** |
| `ongoing monitoring` | **5** |
| `benchmark` | 1 |
| `tier` | **0** |
| `challenger` | **0** |
| `reproduc*` | **0** |
| `version` | **0** |
| `machine learning` | **0** |
| `artificial intelligence` | **0** |
| `sensitivity` | **0** |

**Lo que el documento sí dice** y es citable: *"Model purpose, together with model
exposure, determines model materiality"*, y que evaluar la materialidad es una
consideración importante. También conserva *effective challenge* y *outcomes
analysis* como conceptos centrales, y su sección V se llama *Model Validation and
Monitoring*.

**Lo que el análisis secundario inventó:** tiering, champion/challenger,
reproducibilidad y versionado como exigencias explícitas de SR 26-2. No están.
Citarlas habría sido presentar como requisito regulatorio algo que el regulador no
escribió — en un repo cuyo argumento es la trazabilidad.

## Decisión

1. **Se actualiza la cita**, no los mecanismos. El reporte de validación declara
   ahora SR 26-2 y mapea sus tres secciones de validación a las secciones **IV
   (Model Development and Model Use)**, **V (Model Validation and Monitoring)** y
   **VI (Governance and Controls)** de la guía nueva.

2. **No se reclama que el proyecto fue construido para SR 26-2.** Fue construido
   contra SR 11-7 y los conceptos que lo sostienen —*effective challenge*,
   *outcomes analysis*, *ongoing monitoring*— sobreviven textualmente en la guía
   nueva. Eso es continuidad, no previsión.

3. **Se añade una declaración de materialidad**, porque es el énfasis real de
   SR 26-2 y porque la respuesta honesta es incómoda: este modelo **no está en
   producción y su exposición es nula**, así que su materialidad es la de un
   ejercicio de referencia. Un proyecto de portafolio que se declarara material
   estaría mintiendo sobre su propio alcance.

4. **La aplicabilidad se declara.** SR 26-2 dice ser *"most relevant to banking
   organizations with over $30 billion"* en activos. Este repo no es una
   institución supervisada; usa la guía como marco de estructura y vocabulario, no
   como cumplimiento.

## Lo que NO se toca

`NOTES.md` conserva sus menciones a SR 11-7: es una bitácora fechada y reescribir
el pasado para que parezca que siempre se citó la guía correcta sería falsificar el
registro. El ADR 0003 sí se actualiza porque su texto describe una decisión vigente.

## La lección, que es la de siempre

Un ancla regulatoria es un dato externo con fecha de caducidad, y este proyecto no
tenía ningún mecanismo para notarlo. El monitoreo de la semana 9 vigila la deriva de
los **datos**; nada vigila la deriva de las **normas**. Queda anotado como límite
conocido: la próxima vez que una guía se reemplace, este repo se va a enterar igual
que esta vez — porque alguien lo mire.
