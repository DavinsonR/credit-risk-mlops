# ADR 0011 — La fuente cambió el vocabulario y el modelo perdió su mejor variable

**Fecha:** 2026-09-11
**Estado:** Aceptada — con el problema **abierto** y documentado
**Detectado por:** `crmlops.monitoring.drift`, primera corrida

## El hallazgo

El SBA cambió las categorías de `business_age` entre FY2018 y FY2021. No las
renombró: cambió el esquema de clasificación.

| Categoría | FY2015 | FY2019 | FY2023 |
|---|---|---|---|
| `Existing, 5 or more years` | **48.5%** | 0.0% | 0.0% |
| `New, Less than 1 Year old` | 12.2% | 0.0% | 0.0% |
| `Less than 3 years old but at least 2` | 6.6% | 0.0% | 0.0% |
| `Less than 4 years old but at least 3` | 5.0% | 0.0% | 0.0% |
| `Less than 5 years old but at least 4` | 5.1% | 0.0% | 0.0% |
| `Existing or more than 2 years old` | 0.0% | **52.3%** | **52.5%** |
| `Change of Ownership` | 0.0% | 12.3% | 9.0% |
| `New Business or 2 years or less` | 0.0% | 0.0% | 20.6% |
| `Startup, Loan Funds will Open Business` | 16.0% | 16.6% | 17.9% |

El modelo se entrenó en FY2011-2015. **En FY2024-2026, el 84% de los valores de
`business_age` cae en categorías sobre las que el modelo no tiene evidencia.**

## Por qué importa tanto

`business_age` no es una variable cualquiera:

- Es el **primer driver de SHAP** en los avisos de adverse action. Los ejemplos del
  [ADR 0009](0009-la-plantilla-gana-al-llm.md) citan *"la antigüedad del negocio"*
  como razón principal.
- El contrato de serving mapea las categorías no vistas a `UNKNOWN_CODE`. Así que
  el modelo **no se degrada: pierde la variable entera** y sigue respondiendo con
  la misma confianza aparente.
- Y esto no aparece en ninguna métrica de desempeño, porque el desempeño no se
  puede medir en cosechas jóvenes ([ADR 0010](0010-monitoreo-a-madurez-pareja.md)).
  Sin monitoreo de deriva, habría seguido invisible durante años.

El smoke test de `ci.yml` usa `"business_age": "Existing or more than 2 years old"`
—la categoría nueva— así que llevaba tiempo puntuando con un código desconocido y
devolviendo un 200 perfectamente creíble.

## La métrica: masa sin soporte, no PSI

El PSI de `business_age` da **18.5**, y ese número no significa nada. Un bucket con
proporción de referencia cero hace que el PSI quede fijado por el epsilon elegido
para no dividir por cero: con `EPS = 1e-6`, una categoría nueva con el 52% de la
masa aporta `0.52 · log(0.52 / 1e-6) ≈ 6.9`. Tres categorías así dan 18.5. Cambiar
el epsilon cambia el titular.

Así que la alarma que se lee es **la masa sin soporte**: la proporción del dato
nuevo que cae en categorías con menos de 0.5% de la masa de entrenamiento. Es una
proporción, es interpretable y no depende de ninguna constante arbitraria.

**Sin soporte es más que no vista, y la diferencia era el 52%.** `Existing or more
than 2 years old` SÍ existe en el vocabulario de entrenamiento —con el 0.01%, unos
22 préstamos de 217.060— así que no cuenta como categoría nueva. Contar solo las
inexistentes daba 30% donde el problema real es 84%. La primera versión de la
métrica hacía exactamente eso.

## Decisión

**No se reentrena todavía, y no por pereza: reentrenar no arregla esto.**

| Camino | Por qué no alcanza |
|---|---|
| Reentrenar en FY2011-2015 | Esa ventana tiene el vocabulario **viejo**. El modelo nuevo tendría el mismo problema |
| Reentrenar en FY2019+ | Choca con la madurez de la etiqueta: FY2019 está al 60.9% resuelto y de ahí baja. Aprendería de los que resolvieron rápido, que son los que fallan ([ADR 0003](0003-diseno-del-split-temporal.md)) |
| Sacar `business_age` del modelo | Pierde el driver principal a cambio de nada: hoy ya está perdido de hecho, pero al menos el gate de margen sobre baseline mide con él |

**Lo que corresponde es armonizar el vocabulario**: mapear las categorías nuevas a
las viejas donde describan lo mismo, y solo entonces reentrenar. Eso no es
mecánico:

- `Existing or more than 2 years old` agrupa lo que antes eran cuatro buckets
  (`≥2`, `≥3`, `≥4`, `≥5 años`). El mapeo pierde resolución en la dirección
  correcta —de fino a grueso—, así que el modelo nuevo tendría **menos**
  información que el viejo, no la misma.
- `Change of Ownership` **no existía** como categoría de antigüedad. No es un
  renombre: es un concepto nuevo, y agruparlo con cualquiera de los viejos sería
  inventar.

Por eso queda **abierto y escrito** en vez de resuelto con un diccionario de mapeo
que aparente equivalencia donde no la hay. Un validador tiene que poder ver que la
decisión se tomó, con qué evidencia, y qué se sabe que no se sabe.

## Lo que sí se hizo

1. El monitoreo lo detecta y lo reporta con una métrica interpretable
   (`masa_sin_soporte`), en su propia banda —`VOCABULARIO`— que manda sobre la del
   PSI: una variable cuyo vocabulario cambió no está "vigilar", está rota.
2. `crmlops.monitoring.retrain` dispara el trigger y **dice explícitamente que
   reentrenar no alcanza**, en vez de recomendar un reentrenamiento que no
   cambiaría nada.
3. Queda como el riesgo número uno del modelo en
   `reports/VALIDATION_REPORT.md`.

## Lo que esto enseña sobre el proyecto

Es el tercer defecto de la misma familia y el más caro: el modelo llevaba desde el
día uno aplicándose a una población cuya variable principal ya no hablaba su
idioma. No lo encontró ningún test, ni el gate de fairness, ni el de integridad, ni
los 131 tests de la suite. **Lo encontró la primera corrida del monitoreo, mirando
datos que el modelado nunca mira: las cosechas que no tienen etiqueta.**
