# ADR 0014 — La brecha no se amplió: volvió. Y el efecto del shock sigue sin identificarse

**Fecha:** 2026-09-16
**Estado:** Aceptada
**Reproduce:** `run event-study` → [`exports/event_study_hmda.json`](../../exports/event_study_hmda.json)
**Relacionada:** [ADR 0013](0013-el-efecto-de-la-garantia-no-esta-identificado.md) ·
[ADR 0006](0006-exclusiones-en-hmda.md)

## Por qué existe este estudio

El [ADR 0013](0013-el-efecto-de-la-garantia-no-esta-identificado.md) cerró la
estimación del efecto de la garantía de la SBA por no-identificación, y dejó escrito
que el shock de tasas de 2022 sobre HMDA era la alternativa: shock exógeno y grande,
clases protegidas en el dato, períodos previos para falsificar.

Este ADR es esa alternativa, ejecutada. Y su primer resultado no es un coeficiente:
es que **el hecho descriptivo que el proyecto publicó en la semana 6 estaba medido
contra la línea base equivocada.**

## La ventana de cinco años no podía contestar la pregunta

El panel publicado es FY2020–2024 (`sources.hmda.years`). Con él hay **un solo año
pre-shock comparable** —2021— y por tanto una sola diferencia previa: cero grados de
libertad para falsificar tendencias paralelas.

Y hay algo peor que la falta de potencia: **2020 y 2021 son el auge de
refinanciación**, un régimen anómalo. Tomarlos como línea base supone que lo anormal
era lo normal.

Así que el estudio corre sobre **FY2018–2025, 93.4M solicitudes** (92.9M con condado
identificado). 2018 y 2019 son años de tasas corrientes —~4.5% y ~3.9%— y son la
única base contra la cual se puede distinguir *"el shock amplió la brecha"* de *"el
auge la había comprimido y revirtió"*.

Descargar esos tres años reveló un defecto previo, en el que este ADR no entra
porque tiene su propia entrada en la bitácora: tres módulos definían su muestra con
`glob("*.parquet")`, así que los años nuevos habrían cambiado en silencio tres
números ya publicados.

## 1. El régimen: la brecha volvió, no creció

Brecha de denegación entre solicitantes negros y blancos, sobre el panel completo:

| FY | Denegación (negros) | Denegación (blancos) | Brecha | 4/5 |
|---|---|---|---|---|
| 2018 | 38.29% | 22.05% | **16.24 pp** | 0.792 |
| 2019 | 34.15% | 18.98% | 15.16 pp | 0.813 |
| 2020 | 27.89% | 14.44% | 13.45 pp | 0.843 |
| 2021 | 27.23% | 14.39% | **12.84 pp** | 0.850 |
| 2022 | 35.38% | 20.22% | 15.16 pp | 0.810 |
| 2023 | 39.55% | 23.47% | **16.08 pp** | 0.790 |
| 2024 | 37.60% | 22.36% | 15.24 pp | 0.804 |
| 2025 | 36.67% | 20.79% | 15.88 pp | 0.799 |

| | Brecha media |
|---|---|
| 2018–2019 — tasas corrientes | **15.70 pp** |
| 2020–2021 — auge de refinanciación | 13.14 pp |
| 2023–2025 — post-shock | **15.73 pp** |

**La brecha post-shock está a 0.03 pp de la brecha pre-pandemia.** Tres centésimas de
punto sobre una brecha de quince y medio.

Contra 2021 la ampliación es de +2.59 pp, y ese es el número que circula —el proyecto
mismo lo publicó como *"la razón de cuatro quintos cayó de 0.827 a 0.729"*—. Mide el
auge de refinanciación acabándose. No mide el shock.

> El anclaje al año equivocado no es un error aritmético: las dos cifras son
> correctas. Es que **elegir 2021 como base convierte una reversión en una tendencia**,
> y con cinco años de datos no había forma de verlo.

## 2. Descomposición: dos tercios es recomposición, no denegación

Identidad exacta de Kitagawa sobre el cambio de la brecha, con segmentos
propósito × gravamen × ocupación. Sin residuo: las partes suman el total observado y
hay un test que lo verifica.

| | Cambio | = Composición | + Tasas | Composición |
|---|---|---|---|---|
| 2021 → 2023 | +3.24 pp | **+2.10** | +1.14 | **65%** |
| 2021 → 2024 | +2.41 pp | **+2.91** | −0.50 | 121% |
| 2021 → 2025 | +3.04 pp | **+2.42** | +0.63 | 79% |

El mecanismo es visible en el volumen: la refinanciación pasó de 7.77M solicitudes en
FY2020 a 0.60M en FY2023, un desplome del 92%, y era el segmento con la denegación
más baja. La refinanciación con extracción de efectivo —donde los solicitantes negros
están sobrerrepresentados— más que duplicó su tasa de denegación.

En 2024 el término de tasas es **negativo**: dentro de segmento la brecha se cerró un
poco, y aun así la brecha agregada subió. Un titular construido sobre el agregado
habría dicho exactamente lo contrario de lo que pasó dentro de los segmentos.

## 3. El estimador intra-celda, y su falsificación

Efectos fijos saturados de celda-año sobre condado × propósito × gravamen × ocupación,
panel **balanceado** (2.284 celdas presentes en los ocho años, de 5.243), errores
agrupados por condado.

Con dos grupos y celda-año saturado el estimador de MCO ponderado tiene forma cerrada
—media de las brechas intra-celda con peso de media armónica— y hay un test que la
compara contra mínimos cuadrados por fuerza bruta con los efectos fijos escritos como
columnas de diseño. No es una aproximación.

| FY | Nivel | γ vs 2021 | IC95 | |
|---|---|---|---|---|
| 2018 | 14.49 pp | **+2.37 ± 0.14** | [+2.09, +2.64] | previo |
| 2019 | 13.49 pp | **+1.36 ± 0.13** | [+1.11, +1.62] | previo |
| 2020 | 12.44 pp | +0.32 ± 0.10 | [+0.11, +0.52] | previo |
| 2021 | 12.13 pp | base | | |
| 2022 | 13.88 pp | +1.76 ± 0.14 | [+1.48, +2.04] | shock |
| 2023 | 14.08 pp | +1.95 ± 0.22 | [+1.53, +2.38] | post |
| 2024 | 13.36 pp | +1.24 ± 0.22 | [+0.80, +1.68] | post |
| 2025 | 14.26 pp | +2.14 ± 0.22 | [+1.70, +2.58] | post |

**Tendencias paralelas: NO PASA.** El coeficiente de 2018 vale +2.37 pp, muy por
encima del umbral de 1.0 pp declarado en `config.yaml` **antes** de estimar. Y la
violación no es ruido: es monótona (+2.37, +1.36, +0.32, 0), o sea una tendencia.

El umbral es el mismo para los años previos y los posteriores, a propósito. Usar una
vara para falsificar y otra para concluir es elegir la que conviene.

Nótese además que los niveles post-shock (13.36–14.26) caen **dentro** del rango
pre-shock (12.13–14.49). No hay un salto que explicar.

## 3b. El arreglo de manual fabrica un efecto de +5.61 pp

Cuando la tendencia previa no es plana, el procedimiento estándar es estimarla y medir
la desviación respecto de su extrapolación. Está implementado:

- Tendencia previa 2018–2021: **−0.815 pp por año**, R² = 0.957.
- Desviaciones: 2022 **+2.78 pp**, 2023 **+3.79**, 2024 **+3.89**, 2025 **+5.61**.

Grandes, monótonas y con la n de este panel, significativas a cualquier nivel. **No se
publican como efecto.**

La razón es qué tendencia se extrapola: la caída de −0.8 pp por año es la compresión
de la brecha durante el auge de refinanciación. Extrapolarla a 2025 supone que la
brecha habría seguido cayendo hasta 8.66 pp —por debajo de cualquier valor observado
en ocho años— porque una ola de refinanciaciones al 3% habría continuado
indefinidamente.

**El ajuste convierte el fin del régimen en el efecto del shock.** Es la ilustración
más limpia que tiene el proyecto de por qué una corrección mecánica de tendencia
previa puede manufacturar un resultado: la técnica es correcta y el número está mal.

## 4. Selección diferencial: los dos pools no se vaciaron igual

El estimador del paso 3 compara **pools de solicitantes**, no personas iguales. Si el
shock sacó de la fila a los solicitantes marginales de un grupo más que del otro, la
brecha observada cambia sin que ningún prestamista haya cambiado de criterio.

Volumen dentro de las mismas celdas balanceadas, respecto de 2021:

| FY | Negros | Blancos | Diferencia |
|---|---|---|---|
| 2022 | −20.7% | −38.8% | **+18.2 pp** |
| 2023 | −40.0% | −57.2% | **+17.2 pp** |
| 2024 | −40.0% | −56.2% | +16.2 pp |
| 2025 | −41.7% | −54.1% | +12.4 pp |

Diecisiete puntos de retención diferencial, por encima del umbral declarado de 10 pp.
Los solicitantes blancos —con más deuda hipotecaria vieja y barata que refinanciar—
abandonaron el mercado mucho más que los negros. El pool que queda en 2023 no es el
pool de 2021 con menos gente: es otro pool.

## Decisión

**No se publica un efecto causal del shock de tasas sobre la brecha racial de
denegación.** Se publican tres cosas:

1. **La reversión**, que es un hecho descriptivo sólido y corrige el encuadre de la
   cifra que el propio proyecto venía citando.
2. **La descomposición**, que atribuye dos tercios del movimiento a recomposición del
   pool y no a cambios de criterio dentro de segmento.
3. **Las tres razones medidas** por las que un estimador aquí produciría un número y
   no una estimación: tendencias previas no planas, retención diferencial de 17 pp, y
   un ajuste por tendencia que extrapola el régimen que el shock termina.

## Por qué esto no es el ADR 0013 otra vez

La conclusión se parece —no se publica un efecto— pero el contenido es distinto, y la
diferencia es el punto.

En SBA no había **con qué** falsificar: sin solapamiento y con la densidad destruida en
el umbral, los diagnósticos cerraban las vías de identificación *antes* de que hubiera
un test que correr. Aquí sí hubo: cuatro períodos previos, un test de tendencias
paralelas con un umbral declarado de antemano, y un resultado que lo rechaza.

**La falsificación es la que cierra el caso, y es el entregable.** Un diseño que no
puede fallar su propio test no está identificando nada; solo no ha mirado.

Y el estudio no salió vacío: el hallazgo de que la brecha post-shock está a 0.03 pp de
la pre-pandemia solo se puede afirmar porque hay un contrafactual observado, y ese
contrafactual es exactamente lo que el panel de cinco años no tenía.

## Límites, sin los cuales nada de lo anterior se sostiene

- **HMDA no trae puntaje de crédito**, el determinante más fuerte de una decisión de
  suscripción. Nada de esto prueba discriminación: prueba que hay una diferencia y de
  dónde **no** viene.
- El shock es **común**: no hay grupo sin tratar en el corte transversal. La segunda
  diferencia es entre grupos raciales, no entre tratados y controles.
- `derived_race = 'White'` incluye solicitantes hispanos blancos; la etnia es una
  dimensión separada en HMDA.
- El panel balanceado está poblado sobre todo por compra de vivienda (1.019 de 2.284
  celdas): **las celdas de refinanciación casi no sobreviven porque el segmento se
  desplomó**. No es un defecto del filtro, es el hallazgo — la comparación intra-celda
  solo existe donde todavía queda con qué comparar.
- Las 4/5 de este ADR son **negros contra blancos**. Las que el README cita (0.827 →
  0.729) son peor grupo contra mejor grupo sobre todas las categorías raciales, que es
  otra cantidad y también correcta.
