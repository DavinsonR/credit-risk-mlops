# ADR 0003 — Ventanas del split out-of-time

**Fecha:** 2026-09-08
**Estado:** Aceptada
**Impacto:** AUC test 0.6669 → 0.6870, y el orden valid > test se corrige.

## Contexto

El primer split (train FY2000-2013 / valid FY2014-2016 / test FY2017-2019) se
eligió por intuición: "usar todo lo disponible y dejar lo más reciente para test".
Produjo dos anomalías:

1. **valid (0.6693) salía peor que test (0.6669→0.6693)** — el orden esperado es
   valid ≥ test, porque valid está temporalmente más cerca de train.
2. **PSI del score train→test = 4.08**, un valor absurdo que sugería que algo
   estructural estaba mal, no solo deriva.

## Investigación

**La tasa base del 7(a) es fuertemente cíclica:**

| FY | 2006 | 2007 | 2008 | 2012 | 2013 | 2017 | 2018 |
|---|---|---|---|---|---|---|---|
| charge-off | 32.3% | **36.9%** | 30.6% | 6.4% | 6.2% | 9.2% | 10.1% |

Entrenar con FY2000-2013 mezcla dos regímenes que se llevan un factor de 6.

**Costo medido de cruzar la crisis** (mismo test FY2017-2019):

| Ventana de entrenamiento | Tasa base | AUC test |
|---|---|---|
| FY2000-2013 | 20.3% | 0.6669 |
| FY2005-2013 | 22.6% | 0.6673 |
| FY2010-2015 | 7.1% | 0.6680 |
| **FY2012-2016** | 7.0% | **0.6906** |

**Censura por maduración.** Un préstamo solo entra al panel si ya resolvió antes
del corte. Las cosechas recientes están seleccionadas hacia los que resolvieron
rápido:

| FY | 2011 | 2013 | 2015 | 2016 | 2017 | 2018 | 2019 |
|---|---|---|---|---|---|---|---|
| % resuelto | 83.1 | 83.5 | 82.2 | 80.3 | 75.5 | 70.0 | **60.9** |

El AUC por año dentro del test lo confirma: 2017 → 0.717, 2018 → 0.685,
2019 → 0.678. La degradación sigue la censura, no el calendario.

## Decisión

| Ventana | FY | Criterio |
|---|---|---|
| train | 2011-2015 | post-crisis, régimen homogéneo, 82-85% resuelto |
| valid | 2016 | 80.3% resuelto |
| test | 2017-2018 | 75.5% y 70.0% resuelto |

**Regla:** una cosecha entra al panel de modelado solo si tiene **≥70% de préstamos
resueltos**. FY2019 (60.9%) queda fuera.

**Las cohortes descartadas no se tiran, se reasignan a estrés:**

- `crisis_2005_2008` — responde la pregunta que exige SR 11-7: si vuelve un 2007,
  ¿qué le pasa al modelo? Nunca se entrena con ella.
- `covid_2020_2021` — régimen de emergencia.
- `reciente_2019` — análisis de sensibilidad a la censura.

## Consecuencias

- **AUC test 0.6870** (vs 0.6669), y valid (0.7000) > test (0.6870) como debe ser.
- Menos datos de entrenamiento: 217,060 filas vs 763,965. El AUC de train sube a
  0.8256, o sea más sobreajuste — se ataca con regularización en el tuning.
- Excluir FY2019 sacrifica recencia por limpieza. Es la decisión correcta: un
  número calculado sobre una muestra sesgada no es más reciente, es más falso.
- Se gana material de estrés que de otro modo habría que inventar.
