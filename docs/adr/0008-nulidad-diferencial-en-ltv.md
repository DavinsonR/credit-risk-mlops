# ADR 0008 — `ltv` y `property_value` se conservan sin imputar

**Fecha:** 2026-09-09
**Estado:** Aceptada

## Contexto

El modelo de HMDA dio **AUC 0.8847**, alto para un modelo de crédito. Siguiendo la
regla que este proyecto ya aplicó dos veces —desconfiar de los números buenos—
busqué de dónde venía.

`loan_to_value_ratio` está nulo en el **6.0% de las solicitudes aprobadas y el
15.6% de las denegadas**. `property_value`, en 3.4% y 9.2%.

La causa es operativa y perfectamente lógica: **si una solicitud se rechaza
temprano por DTI, nunca se ordena la tasación**, así que no hay LTV ni valor de
propiedad. La ausencia del dato es *consecuencia* de la decisión.

Un GBM trata los nulos como una rama más del árbol, así que puede aprender
"LTV ausente → denegado" sin que nadie lo escriba.

## El problema con las dos respuestas obvias

**Descartar las variables** tira señal real: el LTV es la variable central de la
suscripción hipotecaria. Un modelo de crédito sin LTV no es más honesto, es peor.

**Conservarlas sin más** deja entrar información posterior a la decisión.

## La pregunta correcta

¿La señal está en el **valor** o en la **ausencia**? Se responde con cuatro
variantes del mismo modelo (`crmlops.evaluation.missingness_audit`):

| Escenario | AUC |
|---|---|
| valor + ausencia | 0.8835 |
| solo valor (imputado con mediana de train) | 0.8825 |
| ni valor ni ausencia | 0.8645 |
| solo ausencia (indicadores, sin valores) | 0.8708 |

**Aporte de la ausencia: +0.0010. Aporte del valor: +0.0180.**

## Decisión

**Se conservan `ltv` y `property_value` sin imputar.**

Imputar la mediana costaría 0.0010 de AUC y agregaría un paso de preprocesamiento
—con su estado que ajustar sobre train, su riesgo de fuga si se hace mal— a cambio
de eliminar una fuga de una milésima. El paso cuesta más de lo que arregla.

## El matiz que hay que registrar

Los cuatro escenarios muestran algo que dos no habrían mostrado: **aislada, la
ausencia sí discrimina.** Solo los indicadores de nulidad, sin ningún valor,
levantan el AUC de 0.8645 a 0.8708 (+0.0063).

Es decir: la fuga es **real pero redundante**. Cuando los valores están presentes,
la información que llevaba la ausencia ya viene contenida en ellos —un LTV
faltante correlaciona con el tipo de solicitud que también tiene valores atípicos
en otras variables—. Por eso el aporte neto cae de 0.0063 a 0.0010.

Registrarlo importa porque **la conclusión depende del contexto**: en un modelo con
menos variables, o con otras fuentes, esa misma ausencia podría aportar los 0.0063
completos y sí justificar la imputación. La decisión no es "la nulidad diferencial
nunca importa", es "en este modelo no importa, y aquí está la medición".

## Consecuencias

- `missingness_audit` queda como herramienta permanente, junto a
  `contamination_audit`. Cubren dos mecanismos distintos: valor sobrescrito
  después del resultado, y ausencia causada por el resultado.
- La auditoría corre sobre una muestra del 3%/8%/8%. La primera versión usaba el
  panel completo y tardaba más de una hora sin cambiar ninguna conclusión: la
  respuesta se juega en centésimas de AUC, no en milésimas.
- El model card debe declarar la nulidad diferencial y su magnitud medida. No
  declararla sería ocultar una fuga conocida, aunque sea pequeña.
