# ADR 0009 — La plantilla determinista gana al LLM

**Fecha:** 2026-09-09
**Estado:** Aceptada
**Modelo evaluado:** llama3.2:3b vía Ollama local

## Contexto

Bajo ECOA / Reg B, denegar crédito obliga a entregar las razones principales
específicas. El plan del proyecto incluía generar esos avisos con un LLM, en
español e inglés, con un harness que midiera fidelidad contra los valores SHAP.

Siguiendo la regla que ya rige el modelado —el retador debe superar a un baseline
interpretable— se incluyó una **plantilla determinista** que rellena el formulario
del Apéndice C. Sin ese brazo, el ejercicio habría reportado "construimos un
generador de avisos con LLM" sin evidencia de que fuera mejor que una carta tipo.

## Resultado

Seis avisos por proveedor (3 casos × 2 idiomas):

| Proveedor | Fidelidad | Cumple | Legibilidad | Palabras | Consistencia | Pasa |
|---|---|---|---|---|---|---|
| **plantilla** | **1.00** | 1.00 | 44.8 | 73 | **1.00** | **100%** |
| llama3.2:3b | 0.50 | 1.00 | **73.2** | 68 | 0.50 | **0%** |

**La plantilla gana.** Pero el promedio esconde el hallazgo, que está en el detalle
por idioma.

## El hallazgo: rechazo asimétrico entre idiomas

| Idioma | Fidelidad | Palabras |
|---|---|---|
| Inglés | **1.00** | 86–149 |
| Español | **0.00** | **18** |

La salida en español, idéntica en los tres casos:

> No puedo redactar un aviso de acción adversa de crédito. ¿Hay algo más en lo que
> pueda ayudarte?

**No es un fallo de capacidad: es un rechazo de seguridad.** El mismo modelo, con
el mismo prompt traducido, la misma temperatura y la misma semilla, redacta el
aviso en inglés sin objeción y lo rechaza en español.

El comportamiento de alineamiento del modelo es **asimétrico entre idiomas**. Para
un documento cuya obligatoriedad es legal y cuya versión en español existe
precisamente para servir a solicitantes con dominio limitado del inglés, eso es
descalificante.

Solo se descubre corriendo el harness con un brazo que no sea inglés. Una
evaluación monolingüe habría reportado fidelidad 1.00 y recomendado desplegar.

## Lo que el LLM sí aporta

**Legibilidad: 73.2 contra 44.8** en Fernández-Huerta. La plantilla queda en el
rango "difícil"; el texto del modelo, en "bastante fácil". Para un documento que
lee un solicitante sin formación financiera, esa diferencia es real y significativa.

El problema es el precio: fidelidad a la mitad y consistencia a la mitad.

## Decisión

**La plantilla determinista va a producción.** El LLM queda documentado como
experimento con resultado negativo y reproducible.

Razones, en orden:

1. **Un aviso legal no puede variar entre ejecuciones.** Con temperatura 0 y
   semilla fija, la versión en inglés produjo texto distinto en las tres
   repeticiones. Un regulador que pida el aviso emitido y reciba otro texto tiene
   un problema, y el emisor también.
2. **El rechazo en español elimina el caso de uso bilingüe**, que era la mitad del
   argumento para usar un LLM.
3. La plantilla no alucina por construcción, no depende de red, cuesta cero y un
   validador la lee entera en un minuto.

## Una limitación de mi propia métrica

La fidelidad mide **qué factores** se mencionan, no si la explicación **sobre**
ellos es correcta. El aviso en inglés obtuvo 1.00 y aun así dice:

> The initial interest rate you requested is also a factor... We typically require
> a lower interest rate for loans to businesses with a longer history.

El solicitante no elige la tasa, y la segunda frase es una racionalización
inventada. El harness no lo detecta porque los factores citados sí son los
correctos.

Cerrar ese hueco exigiría verificar afirmaciones causales sobre cada factor, no
solo su presencia. No está implementado, y decir que la fidelidad es 1.00 sin esta
nota sería vender una garantía que la métrica no da.

## Qué reabriría esta decisión

- Un modelo mayor (70B vía Groq) que no rechace en español y sea consistente.
- Un enfoque híbrido: plantilla para la estructura legal, LLM solo para simplificar
  el lenguaje, con la lista de factores fijada fuera del modelo.

El harness ya está montado; reevaluar es correr un comando.

---

# Revisión — 2026-09-09, tras ampliar el harness

La versión original evaluó **un** modelo (llama3.2:3b) en **un** modo. Ampliar a
cinco brazos corrigió dos conclusiones y dejó una pregunta abierta.

## Corrección 1 — el rechazo en español era del modelo, no de la tarea

qwen2.5:7b **no se niega**: fidelidad 1.00 en ambos idiomas. La afirmación de que
"el alineamiento del modelo es asimétrico entre idiomas" es cierta **de
llama3.2:3b**, no de los LLM en general. Un modelo mayor hace la tarea.

## Corrección 2 — la inconsistencia era un artefacto mío

La versión original reportó que ningún LLM alcanza consistencia pese a
temperatura 0 y semilla fija. **Eso era un bug de medición.**

Verificado directamente:

| Condición | Corridas | Salidas únicas |
|---|---|---|
| Prompt corto | 4 | **1** |
| Prompt real, sin calentamiento | 3 | 2 — *la primera difiere* |
| Prompt real, con calentamiento | 3 | **1** |

**La primera generación tras cargar el modelo no es determinista; las siguientes
sí.** El harness medía el arranque en frío y se lo atribuía al modelo.

Con `Provider.warm_up()` descartando una generación antes de medir, qwen2.5:7b
pasó de **0% a 83%** de casos aprobados.

## Resultados corregidos

| Brazo | Fidelidad | Legibilidad | Consistencia | Pasa |
|---|---|---|---|---|
| **plantilla** | 1.00 | 44.8 | **1.00** | **100%** |
| qwen2.5:7b | 1.00 | 57.8 | 0.83 | 83% |
| qwen2.5:7b (híbrido) | 1.00 | 53.4 | 0.50 | 50% |
| llama3.2:3b (híbrido) | 1.00 | 53.2 | 0.33 | 33% |
| llama3.2:3b | 0.50 | 74.6 | 0.50 | 0% |

**La decisión no cambia: la plantilla va a producción.** Pero el margen ya no es
abismal, y la razón es una sola: consistencia. Un aviso legal que cambia entre
ejecuciones es indefendible, y 0.83 no es 1.00.

## El híbrido resolvió la fidelidad y creó otro problema

Los dos brazos híbridos alcanzan fidelidad 1.00 —por construcción, ya que una
reescritura inválida cae a la plantilla— pero salen **menos consistentes que el
modelo solo** (0.50 y 0.33 contra 0.83).

Hipótesis con la que trabajo, **no verificada**: el mecanismo de validar-y-caer
introduce su propia varianza en el borde. Si una corrida acepta la reescritura y
la siguiente la rechaza, se emiten dos documentos distintos, ambos individualmente
válidos. Sería un defecto de **mi diseño**, no del modelo.

Confirmarlo exige registrar por caso si se usó el LLM o el fallback, y comparar
esa decisión entre corridas. No está implementado. Afirmar la causa sin esa
medición sería repetir el error que esta misma revisión corrige.

## Lo que esta revisión enseña sobre el harness

Un eval con un solo modelo y un solo modo produjo dos conclusiones equivocadas que
se leían perfectamente razonables. Ninguna se cayó por revisar el código: se
cayeron al agregar brazos y al verificar el número que sostenía la conclusión.
