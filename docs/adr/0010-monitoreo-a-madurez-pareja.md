# ADR 0010 — Monitorear a madurez pareja, no a fecha de calendario

**Fecha:** 2026-09-11
**Estado:** Aceptada
**Vintage de referencia:** `asof_260630` (corte 2026-06-30)

## Contexto

La semana 9 pide monitoreo de deriva con los datos trimestrales reales de SBA. La
primera pregunta no es *cómo* monitorear sino **qué se puede monitorear**, y en
crédito la respuesta no es obvia: la etiqueta tarda años en existir.

[ADR 0003](0003-diseno-del-split-temporal.md) ya usó este hecho para elegir las
ventanas del split —solo cosechas con ≥70% de préstamos resueltos—. Esto lo
extiende a monitoreo, donde el problema es peor: ahí las cosechas que interesan
son justamente las jóvenes.

## Lo que se midió

**Tiempo entre aprobación y charge-off** (220.630 casos):

| p10 | p25 | mediana | p75 | p90 |
|---|---|---|---|---|
| 24m | 35m | **51m** | 75m | 103m |

**Cuánto de una cosecha se ve a los M meses** (% de sus charge-offs finales, en
cosechas ya maduras):

| Meses | 12 | 24 | 36 | 48 | 60 | 84 |
|---|---|---|---|---|---|---|
| FY2013 | 0.9% | 8.7% | 21.6% | 38.2% | 51.9% | 77.0% |
| FY2018 | 1.6% | 11.4% | 21.8% | 41.3% | 59.6% | 86.4% |

**A los 12 meses se ha manifestado alrededor del 1% de los charge-offs. Para ver
la mitad hacen falta unos 5 años.**

**Resolución por cosecha con este vintage:**

| Cosecha | FY2013 | FY2018 | FY2021 | FY2023 | FY2025 |
|---|---|---|---|---|---|
| % resuelto | 83.5% | 70.0% | 40.4% | 17.4% | 2.8% |

## La decisión

**Las cosechas se comparan a madurez pareja: fijando la ventana de observación,
no la fecha de calendario.** Para cada cosecha se mira solo lo resuelto dentro de
los primeros M meses desde la aprobación.

La comparación ingenua —tasa de charge-off entre lo resuelto, sin más— da esto:

| Cosecha | % resuelto | Tasa cruda |
|---|---|---|
| FY2013 | 83.5% | 6.25% |
| FY2023 | 17.4% | **17.40%** |

Leído así, FY2023 falla casi tres veces más que FY2013. Pero no se está comparando
riesgo: se está comparando antigüedad. Entre los pocos resueltos de una cosecha
joven, la mezcla no es la de la cosecha.

## Y sin embargo, la señal es real

A madurez pareja la alarma no desaparece, se vuelve defendible. Referencia: las
cosechas de entrenamiento FY2011-2015.

| Ventana | Referencia | FY2020 | FY2021 | FY2022 | FY2023 |
|---|---|---|---|---|---|
| 12m | 1.79% | 0.18% | 0.26% | 2.38% | 2.25% |
| 24m | **4.96%** | 2.15% | 2.05% | **7.28%** | **11.35%** |
| 36m | 6.63% | 3.58% | 3.54% | 10.33% | — |

**FY2023 falla al 11.35% a 24 meses contra el 4.96% de las cosechas con las que se
entrenó el modelo: 2.3 veces.** FY2022, 1.5 veces. Y en la otra dirección,
FY2020-2021 fallan a menos de la mitad, lo que es coherente con el alivio
crediticio de la pandemia.

Ese es el hallazgo que justifica reentrenar, y ahora es una comparación entre
iguales en vez de un número que depende de cuándo se miró.

## Qué se monitorea y qué no

| Señal | ¿Disponible ya? | Sobre qué cosecha |
|---|---|---|
| Deriva de features (PSI/KS) | **Sí, de inmediato** | Cualquiera, incluso la del trimestre |
| Deriva del score | **Sí, de inmediato** | Cualquiera |
| Tasa a madurez pareja | Sí, con retraso de M meses | La que alcanzó la ventana |
| AUC / calibración | **No en cosechas jóvenes** | Solo ≥70% resuelto ([ADR 0003](0003-diseno-del-split-temporal.md)) |

Un tablero que muestre AUC sobre las originaciones del último trimestre está
mostrando ruido con nombre de métrica. El monitoreo **se niega a calcularlo** en
vez de calcularlo con una advertencia al pie: una cifra publicada se cita sola.

## La trampa de implementación, que sí mordió

Una cosecha no puede reportar una ventana que no alcanzó. FY2024 se aprobó hasta
septiembre de 2024 y el vintage corta en junio de 2026: tiene **21 meses
observables**. Pedirle su tasa a 24 o 48 meses, en una implementación ingenua,
devuelve el mismo valor que a 21 —porque no hay nada más que contar— y en la tabla
se lee como una curva que se aplana.

Le pasó a la primera versión de este análisis, en un script de exploración: FY2024
mostraba `tasa_36m = tasa_48m = 10.28` con `n` idéntico, y eso es lo único que
delató el error. `matched_maturity()` deja esas celdas vacías y marca
`observable = False`. Cubierto por `tests/test_maturity.py`.

El criterio es **estricto**: la ventana cuenta solo si *todos* los préstamos de la
cosecha la tuvieron completa. Contar los que sí la alcanzaron metería sesgo de
composición dentro de la cosecha —para FY2024 entrarían solo las aprobaciones de
octubre a diciembre, que no son una muestra de la cosecha.

## Lo que el número NO es

No es una estimación de la tasa final de la cosecha, aunque invite a leerse así.
Es un cociente cuyo numerador y denominador crecen los dos con la ventana, y **no
es monótono**: en las cosechas de entrenamiento sube hasta 7.22% a 48 meses y baja
a 7.14% a 60, con tasa final 6.79%. Los charge-offs emergen antes que los pagos
completos, así que el cociente sobrepasa y luego converge.

Sirve para comparar cosechas distintas **en la misma ventana**, que es para lo que
se construyó. Un test fija la no-monotonía a propósito: si algún día el número
resultara monótono, o cambió el dato o alguien convirtió la métrica en otra cosa,
y las dos merecen enterarse.

## Consecuencia para el reentrenamiento

El disparador no puede ser "cayó el AUC": ese número no existe a tiempo. El
disparador es **deriva de población medible hoy** (PSI de features y de score) más
**tasa a madurez pareja fuera de rango** en la cosecha más joven que alcanzó la
ventana de 24 meses. El modelo nuevo se promueve solo si pasa los gates, que ya
existen.

## Lo que esto no resuelve

La tasa a madurez pareja usa los préstamos **resueltos** dentro de la ventana. En
una cosecha joven eso sigue siendo una fracción de la cosecha, y su composición no
es idéntica a la de la ventana equivalente en una cosecha vieja —los plazos
cambian con el tiempo, y el plazo es justamente la variable que este proyecto no
puede usar ([ADR 0002](0002-terminmonths-es-fuga.md))—. El sesgo se reduce mucho;
no se elimina. Un análisis de supervivencia con censura a la derecha sería la
respuesta completa y no está implementado.
