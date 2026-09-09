# ADR 0006 — Tres clases de exclusión en HMDA, no una

**Fecha:** 2026-09-09
**Estado:** Aceptada

## Contexto

HMDA trae 99 columnas y 62.4 millones de solicitudes (FY2020-2024). Decidir cuáles
pueden ser features exige distinguir tres problemas distintos que suelen mezclarse
bajo la etiqueta genérica de "fuga".

## Clase 1 — Campos que solo existen si el préstamo se originó

Medido sobre DC 2023:

| Columna | % nulo si originado | % nulo si denegado |
|---|---|---|
| `interest_rate` | **0.0%** | **99.4%** |
| `rate_spread` | 9.4% | 99.5% |
| `total_loan_costs` | 22.4% | 99.4% |
| `origination_charges` | 22.0% | 99.4% |

Una solicitud rechazada no tiene tasa de interés porque nunca hubo préstamo. Un
modelo con estas columnas aprende *"tiene tasa → aprobado"* y alcanza un AUC
irreal.

Es el mismo mecanismo que `TermInMonths` en SBA ([ADR 0002](0002-terminmonths-es-fuga.md)),
en otro dataset y con otra apariencia. La generalización: **cualquier campo que se
llene como consecuencia del resultado es fuga, aunque el nombre no lo sugiera.**

También entran aquí `denial_reason-1..4` (obvio) y `purchaser_type`, que indica
quién compró el préstamo en el mercado secundario.

## Clase 2 — La decisión del propio prestamista

`aus-1` a `aus-5` son los resultados del motor de suscripción automática del banco:
*Approve/Eligible*, *Refer*, *Out of Scope*.

**Sí están disponibles al momento de decidir.** No son fuga en sentido temporal. El
problema es otro: usarlos convierte el ejercicio en *predecir una decisión a partir
de la decisión*. El modelo aprendería a imitar al motor existente —incluidos sus
sesgos— en vez de modelar el riesgo del solicitante.

Un modelo entrenado así reproduce cualquier discriminación histórica del sistema que
copia, y lo hace con la apariencia de objetividad que da un algoritmo. Para un
proyecto cuyo objeto es auditar equidad, incluirlos sería contradictorio.

## Clase 3 — Proxies de características protegidas

`tract_minority_population_percent` es el porcentaje de población minoritaria del
censo tract donde está la propiedad.

Es información legítima del área y está disponible al decidir. Pero usarla como
feature es **modelar sobre raza por vía geográfica**: la definición operativa de
redlining. Que el modelo nunca vea `derived_race` no cambia nada si recibe una
variable que la aproxima con alta fidelidad.

Se conserva en el panel para **medir** disparidad territorial. Nunca como feature.

Las demás variables del tract sí entran: `tract_population`,
`tract_to_msa_income_percentage`, `tract_owner_occupied_units` y
`ffiec_msa_md_median_family_income` describen la economía del área, no su
composición racial.

## La distinción central: medir vs. entrenar

Las clases protegidas —`derived_race`, `derived_ethnicity`, `derived_sex`,
`applicant_age`— **se conservan en el panel y jamás se pasan al modelo**.

Sostener ambas cosas a la vez es todo el trabajo de equidad:

- Sin los atributos en el panel, no se puede calcular disparate impact. Un modelo
  "ciego al color" que nadie puede auditar no es más justo: es menos verificable.
- Con los atributos en el modelo, se discrimina de forma explícita.

HMDA existe precisamente porque la ley obliga a reportar estos campos para poder
auditar discriminación crediticia. Descartarlos del panel sería desperdiciar la
razón de ser del dataset.

## Consecuencias

- El modelo de HMDA tendrá un AUC más bajo que uno que use las columnas prohibidas.
  Eso es correcto: el otro número sería falso.
- `crmlops.sources.hmda` declara las tres listas por separado, con el motivo de cada
  una, para que nadie las reincorpore viendo solo que "mejoran el AUC".
- El model card debe registrar la decisión sobre `aus-*`: es la menos obvia de las
  tres y la que un revisor cuestionaría primero.
