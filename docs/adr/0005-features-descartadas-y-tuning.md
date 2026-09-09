# ADR 0005 — Features descartadas por política, y qué da el tuning

**Fecha:** 2026-09-09
**Estado:** Aceptada
**Origen:** docs/AUDIT.md, defecto E

## Contexto

En `NOTES.md` escribí que faltaba "NAICS a 4 dígitos, identidad del banco" como si
ambas fueran a ayudar. La auditoría exigió medirlo en vez de suponerlo.

## Medición (test FY2017-2018)

| Configuración | AUC |
|---|---|
| Actual, 15 features | 0.7009 |
| + NAICS a 4 dígitos | **0.6890** |
| + identidad del banco | **0.7140** |
| + oficina distrital y estado del proyecto | 0.6975 |
| + todas | 0.7149 |

**Mi plan estaba medio equivocado.** NAICS-4 *empeora* el modelo: ~1,000 categorías
sobre 217k filas de entrenamiento, y el GBM memoriza nichos que no sobreviven a la
cosecha siguiente. La granularidad de 2 dígitos ya captura la señal sectorial.

La oficina distrital y el estado del proyecto tampoco aportan: son redundantes con
`borrower_state`.

## Decisión 1 — `NaicsCode` se queda en 2 dígitos

Medido, no supuesto. La versión de 4 dígitos queda descartada con evidencia.

## Decisión 2 — La identidad del banco NO entra al modelo

Es la única que aporta de verdad: **+1.3 puntos de AUC**. Aun así se descarta.

**Razón.** El banco no es un atributo del prestatario. Un modelo que use
`BankName` penaliza a un solicitante por la calidad histórica de la cartera del
banco al que fue, algo que el solicitante no controla y que frecuentemente
correlaciona con geografía, tamaño de la empresa y perfil demográfico. Convierte
una decisión sobre *este negocio* en una decisión sobre *dónde pidió el préstamo*.

Es exactamente el tipo de variable que un examen de fair lending del CFPB
cuestiona: mejora la predicción por una vía que no es el riesgo del prestatario.

**Esto es una decisión de política, no técnica, y por eso vive en un ADR y no en
una búsqueda de features.** Un comité de riesgo podría decidir lo contrario para
un modelo de *monitoreo de cartera* — donde no hay solicitante afectado — y sería
razonable. Para un modelo de originación, no.

El costo de la decisión está cuantificado: 1.3 puntos de AUC. Renunciar a ellos es
una elección informada, no un descuido.

## Decisión 3 — Los hiperparámetros se quedan como están

Presenté los del GBM como "deliberadamente regularizados" sin haberlo verificado.
Búsqueda aleatoria de 25 configuraciones, seleccionando por **validación**:

| | AUC test |
|---|---|
| Actual (sin tuning) | 0.7005 |
| Mejor de 25 configuraciones | **0.7014** |

**+0.0009.** El tuning no compra nada aquí, y la mejor configuración encontrada
(`num_leaves=127`, `min_child_samples=50`) es *menos* regularizada y por tanto más
frágil ante cambio de régimen, a cambio de una diferencia en el cuarto decimal.

Se conservan los parámetros actuales. La afirmación original resultó correcta,
pero era suerte hasta ahora: ya está medida.

## Consecuencias

- El techo del modelo con las features actuales está cerca de 0.70. Subir de ahí
  exige datos externos (macro de FRED, demografía del Census por condado), no más
  granularidad de lo que ya hay.
- La decisión sobre `BankName` queda registrada en el model card como limitación
  deliberada, para que nadie la "arregle" más adelante viendo el AUC.
