# ADR 0013 — El efecto de la garantía no está identificado, y eso es el resultado

**Fecha:** 2026-09-12
**Estado:** Aceptada
**Entregable:** una no-identificación demostrada, no un efecto estimado

## La pregunta

El programa 7(a) tiene una palanca de política evidente: **el porcentaje de la
garantía que asume la SBA**. Un prestamista con el 85% garantizado arriesga 15
centavos por dólar; con el 75%, arriesga 25. La pregunta causal es si esa diferencia
**causa** más incumplimiento —riesgo moral clásico— o si la correlación observada es
composición.

Importa porque es la única palanca que la SBA controla de verdad. **La SBA no
origina préstamos: garantiza.** El titular del proyecto —*"rechazando el 10% más
riesgoso se habrían evitado $276.3M"*— responde una pregunta que la SBA no puede
ejecutar, porque la decisión de rechazar es del banco.

## Lo que se midió antes de estimar

Tres diagnósticos sobre el panel completo, **1.398.416 préstamos resueltos**
(`crmlops.causal.identification`).

### 1. El tratamiento no tiene variación propia

| | |
|---|---|
| Niveles distintos de garantía | **3.832** |
| Masa en los cuatro niveles frecuentes (0.50 / 0.75 / 0.85 / 0.90) | **90.95%** |
| Celdas (método de procesamiento × tramo de $10.000) | 3.015 |
| **R² del tratamiento sobre esas celdas** | **0.9145** |

**El 91.5% del tratamiento lo fija la regla administrativa**, y sus dos
determinantes —método de procesamiento y monto— ya son features del modelo de
producción.

Eso cierra la vía condicional por los dos lados a la vez, y conviene verlo escrito
porque es contraintuitivo:

- **Condicionando** por monto y método, el solapamiento desaparece. La propensión se
  va a 0 o a 1 dentro de cada celda y el score ortogonal de DML divide por casi cero.
- **Sin condicionar** por monto, hay confusión: el monto causa incumplimiento por su
  cuenta, y la auditoría de contaminación de la semana 1 ya lo había medido.

No hay conjunto de controles que resuelva las dos cosas. **Doble machine learning,
causal forests y policy trees no arreglan esto**: todos requieren solapamiento, y el
solapamiento no está.

### 2. La discontinuidad existe y la densidad está destruida

El umbral de **$150.000** separaría dos garantías máximas y habilitaría una
regresión discontinua. La densidad dice que no:

| Ventana alrededor de $150.000 | Préstamos | Exactamente en $150.000 | % |
|---|---|---|---|
| ±$5.000 | 63.484 | 52.770 | **83.1%** |
| ±$10.000 | 78.432 | 52.770 | **67.3%** |
| ±$25.000 | 126.449 | 52.770 | 41.7% |
| ±$50.000 | 284.988 | 52.770 | 18.5% |

**52.770 préstamos están exactamente en $150.000.** En la ventana estrecha —la única
donde un RD sería creíble— cuatro de cada cinco préstamos están en el punto exacto
del corte.

Eso no es una muestra local-aleatoria: es gente **eligiendo** quedarse en el umbral.
Es el test de McCrary en su versión más cruda, y falla de forma tan contundente que
no hace falta el test formal. Un *donut* que excluya el apilamiento tira el 83% de la
ventana y deja de ser local.

### 3. El gradiente crudo no es todo composición — y eso lo empeora

| Tramo (desde) | n a 0.75 | n a 0.85 | Tasa 0.75 | Tasa 0.85 | Diferencia |
|---|---|---|---|---|---|
| $100.000 | 10.900 | 25.211 | 11.90% | 15.86% | +3.96 pp |
| $125.000 | 10.497 | 18.535 | 13.34% | 17.70% | +4.36 pp |
| $150.000 | 20.786 | 26.597 | 14.33% | 20.02% | +5.69 pp |

| | |
|---|---|
| Gradiente crudo (0.85 vs 0.75) | **+7.76 pp** |
| Dentro del mismo tramo de tamaño | **+4.79 pp** |
| Explicado por tamaño | **38.3%** |

Condicionar por tamaño quita **38%** del gradiente. Queda un residual de +4.79 pp,
consistente en signo en los tres tramos.

**Ese residual no es un efecto, y la razón es precisamente por qué sobrevive.** Lo
que queda tras condicionar por la regla es la parte **discrecional**: prestamistas
que pidieron menos que el máximo permitido. Esa elección la toman mirando el
expediente de crédito —score del solicitante, estados financieros, garantías
colaterales— que **no está en estos datos**. Y el signo es exactamente el que predice
la selección adversa: más garantía donde el expediente se ve peor.

Un estimador condicional aplicado a esta variación recuperaría el efecto de la
selección y lo reportaría como efecto del tratamiento.

## Decisión

**No se publica un efecto causal de la garantía.** Se publica el diagnóstico.

Con esta palanca y estos datos el efecto no está identificado. Correr DoubleML sobre
este panel produciría un coeficiente con su intervalo de confianza, y ese intervalo
sería una medida de precisión sobre un parámetro que no es el que dice ser. Un número
con barras de error no es una estimación si el supuesto de identificación no se
sostiene.

## Por qué esto vale más que un efecto

Un resultado nulo mal identificado no dice nada. **Una no-identificación demostrada
sí dice algo**, y tres cosas a la vez:

1. **Sobre el dato.** El programa 7(a) asigna su palanca por regla, no por decisión
   caso a caso. Quien quiera evaluar el 7(a) causalmente necesita otra fuente de
   variación: un cambio de norma con fecha, no la sección transversal.
2. **Sobre el método.** Es la demostración de que *machine learning causal no es
   machine learning con vocabulario causal*. DML, causal forests y policy learning
   son estimadores correctos aplicados a un problema de identificación que hay que
   resolver **antes**, y con datos administrativos a menudo no se puede.
3. **Sobre el titular del propio proyecto.** El `$276.3M` se calcula rankeando por PD
   predicha y suponiendo que rechazar elimina la pérdida. Son dos supuestos causales
   en un número presentado como predicción, y el model card ya declara el segundo
   como limitación. Este ADR nombra el primero.

## Lo que sí queda abierto, con la vía nombrada

El diseño con mejor pinta **no es la garantía**: es un estudio de evento sobre HMDA
en el shock de tasas de 2022. Tiene 62,4M de solicitudes, un shock exógeno a mitad
del panel, dos períodos previos para falsificar tendencias paralelas, y clases
protegidas que SBA no trae. El proyecto ya midió el gradiente descriptivo —la razón
de cuatro quintos cayó de 0.827 en 2020 a 0.729 en 2023— y ya midió que la
composición del pool cambió estructuralmente (PSI de forma 0.2099), que es
justamente donde el ajuste por covariables de alta dimensión aporta algo.

No está implementado. Se nombra para que se vea que la decisión de no estimar aquí
fue por identificación y no por falta de alternativas.

## Nota sobre la procedencia de estos números

Los tres diagnósticos corren sobre préstamos **resueltos**, que es un subconjunto
censurado ([ADR 0010](0010-monitoreo-a-madurez-pareja.md)): las tasas de charge-off
están infladas respecto a las eventuales. Las **diferencias** entre grupos son menos
sensibles a eso que los niveles, pero no son inmunes, y las tasas de las tablas de
arriba no deben compararse con la tasa base del modelo (6.75% en entrenamiento).

Reproducible con `run causal`. Los números se recalculan desde los CSV crudos, no se
leen de ninguna parte.
