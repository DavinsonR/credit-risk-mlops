# ADR 0002 — `TermInMonths` está contaminado: se excluye como feature

**Fecha:** 2026-09-08
**Estado:** Aceptada
**Impacto:** AUC reportado cae de 0.946 a 0.662–0.725. Es la corrección correcta.

## Contexto

El primer signal gate sobre SBA 7(a) dio **AUC 0.946** out-of-time. Los modelos de
riesgo crediticio reales viven entre 0.70 y 0.80. Un 0.95 no es una victoria: es
un síntoma.

## Investigación

**Paso 1 — Ablación.** Quitar una sola feature colapsó el modelo:

| Modelo | AUC test (FY2017-2019) |
|---|---|
| Completo | 0.9461 |
| Sin `term_months` | 0.6621 |
| Solo cohorte madura (sin censura), completo | 0.9464 |
| Solo cohorte madura, sin `term_months` | 0.7248 |

La censura por maduración **no** era la causa: la cohorte madura da el mismo AUC.
Todo el efecto venía de `term_months`.

**Paso 2 — ¿Es el plazo realizado?** No. La correlación entre `TermInMonths` y la
duración real (aprobación → resolución) es 0.14–0.23, y solo 2–13% coinciden.

**Paso 3 — Valores exactos.** Aquí apareció el patrón:

| Plazo | n | % charge-off |
|---|---|---|
| 120 (redondo) | 35,477 | 0.95% |
| 84 (redondo) | 26,307 | 0.78% |
| 300 (redondo) | 10,562 | 0.06% |
| 83 | 782 | 12.9% |
| 87 | 567 | 20.6% |
| 66 | 545 | 21.1% |

Agregado: **plazo redondo → 1.91% de charge-off; no redondo → 49.88%.** 26x.

**Paso 4 — La prueba decisiva.** Si el plazo se sobrescribe al reestructurar o
liquidar, los préstamos que nunca llegaron a ese punto deben tener plazos limpios:

| Estado | n | % plazo no redondo |
|---|---|---|
| CHGOFF | 177,636 | **84.8%** |
| P I F | 854,681 | 16.8% |
| CANCLD (nunca desembolsado) | 149,019 | **9.4%** |
| COMMIT (activo) | 44 | **0.0%** |

Los cancelados nunca pasaron de la originación y su plazo es prístino (9.4%).
Los charge-off están en 84.8%.

## Decisión

`TermInMonths` pasa a `features.forbidden`. **No se usa como feature en ningún modelo
de originación**, ni cruda ni derivada ni bucketizada.

Se descartó bucketizar a plazos estándar: dio AUC 0.8821, todavía irreal. El
bucketizado no elimina la contaminación porque el valor modificado sigue arrastrando
información del evento de default.

## Consecuencias

- **El AUC honesto es 0.66–0.72**, no 0.95. Es el rango donde viven los modelos de
  crédito reales, y es el número que se reporta.
- Se pierde señal económica legítima (un préstamo inmobiliario a 25 años sí es
  distinto de uno de capital de trabajo a 5). No es recuperable de este dataset:
  el plazo original de los préstamos que fallaron no está.
- Se agrega `tests/test_no_leakage.py` para que `term` no pueda reentrar por
  descuido.
- **Generalización:** cualquier campo del extracto FOIA que se actualice durante la
  vida del préstamo es sospechoso. Auditar `InitialInterestRate`,
  `SBAGuaranteedApproval` y `JobsSupported` con el mismo método CANCLD-vs-CHGOFF
  antes de usarlos (pendiente, Semana 2).

## Por qué esto importa

Si esto no se detecta en la Semana 1, el proyecto habría publicado un AUC de 0.95
y cualquier entrevistador con experiencia en crédito lo habría desmontado en dos
preguntas. El hallazgo vale más que el modelo.
