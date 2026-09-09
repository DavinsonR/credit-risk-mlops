# ADR 0007 — Un filtro de limpieza cambia el veredicto legal

**Fecha:** 2026-09-09
**Estado:** Aceptada

## Contexto

El panel de HMDA aplica dos filtros que parecen inocuos:

```sql
where try_cast(loan_amount as double) > 0
  and try_cast(income as double) is not null
```

Sin ingreso no se puede calcular DTI ni razón préstamo/ingreso, así que la
exclusión tiene justificación técnica. El problema es que **no elimina gente al
azar**.

## Cómo se descubrió

Al validar el parseo de `applicant_age` noté algo raro: de las 218,323
solicitudes de 2024 con `applicant_age = 8888` ("no proporcionado"), solo 2,446
sobrevivían al panel. **El filtro estaba borrando el 98.9% de un subgrupo entero.**

Los registros sin edad son casi siempre también registros sin ingreso: son un tipo
particular de presentación (instituciones exentas, préstamos comprados) donde no
se reportan datos del solicitante.

## La medición

Porcentaje de solicitudes eliminadas por los filtros, FY2024:

| Grupo | Total | Eliminadas | % |
|---|---|---|---|
| Native Hawaiian / Pacific Islander | 20,088 | 1,018 | **5.1%** |
| Black or African American | 724,268 | 35,101 | **4.8%** |
| 2 or more minority races | 20,868 | 828 | 4.0% |
| Asian | 503,312 | 18,882 | 3.8% |
| American Indian / Alaska Native | 59,610 | 2,226 | 3.7% |
| White | 5,309,638 | 165,812 | **3.1%** |

El filtro elimina proporcionalmente **más solicitantes minoritarios**.

## Por qué importa: cruza el umbral legal

Tasa de denegación en la comparación estándar de fair lending:

| Población | Negros | Blancos | Razón de 4/5 |
|---|---|---|---|
| Completa | 37.79% | 22.46% | **0.802** — pasa |
| Filtrada (el panel) | 38.39% | 22.54% | **0.795** — no pasa |

**Una decisión técnica de limpieza mueve el resultado de un lado al otro del
umbral del EEOC.** Nadie eligió ese efecto; salió de una cláusula `where` escrita
para que el DTI fuera calculable.

## Decisión

1. **Los filtros se quedan.** Un panel sin ingreso no permite calcular las
   features centrales, y quitar los filtros produciría un modelo peor, no uno más
   justo.
2. **El sesgo de selección se reporta junto a toda métrica de equidad.** El
   reporte declara qué porcentaje de cada grupo quedó fuera y cómo se mueve la
   razón de 4/5 entre ambas poblaciones. Publicar 0.795 sin decir que la población
   completa da 0.802 sería técnicamente cierto y sustantivamente engañoso.
3. **La línea base se calcula sobre la población COMPLETA**
   (`crmlops.fairness.observed`), no sobre el panel filtrado. Comparar el modelo
   contra una línea base que comparte su sesgo de selección escondería el efecto.

## Consecuencias

- Toda cifra de equidad de este proyecto lleva adjunta la población sobre la que
  se calculó. No es una nota al pie: es parte del número.
- Generaliza a cualquier auditoría de equidad: **antes de medir disparidad hay que
  medir a quién dejó fuera el preprocesamiento.** Un pipeline puede introducir el
  sesgo que después dice estar midiendo.
- El model card debe registrar los porcentajes de exclusión por grupo.

## Lo que este ADR no dice

No afirma que exista discriminación. HMDA no incluye puntaje de crédito, el
determinante más fuerte de una decisión de suscripción. Estas cifras muestran
diferencias que exigen explicación, y muestran además que **la explicación puede
depender de decisiones del analista** — que es exactamente por qué un examen de
fair lending revisa la metodología y no solo el resultado.
