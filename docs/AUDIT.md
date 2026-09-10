# Auditoría interna — Semanas 1 a 4

**Fecha:** 2026-09-09
**Alcance:** todo lo construido hasta el cierre de Semana 4.
**Método:** ejecución adversarial contra el propio código, no revisión de memoria.

> Este proyecto afirma construir "ML que sobrevive una auditoría". Someterlo a una
> es la prueba mínima de que esa afirmación significa algo. Nueve defectos, dos de
> ellos en el mecanismo central.

---

## A. Defectos críticos — el gate se puede engañar

### A1. Editar `exports/metrics.json` a mano burla los gates por completo

Los gates leen un archivo commiteado en vez de reentrenar. Ese diseño está
justificado (entrenar exige 860 MB que no viven en el repo), pero **nunca verifiqué
que el artefacto fuera confiable**.

Prueba ejecutada:

```
AUC real: 0.7005 -> inventado a mano: 0.9500
$ python -m crmlops.governance.gates
APROBADO: 4 gates pasaron.        exit=0
```

Un número inventado pasó el control. El gate de coherencia protege contra cambiar
`config.yaml` sin reentrenar, pero no contra editar el resultado.

**Severidad: crítica.** Es el fallo más grave posible en un proyecto de gobierno de
modelos: el control valida su propia entrada sin verificarla.

**Arreglo:** grabar en `metrics.json` un hash del código de modelado y de las
predicciones, y que CI recompute las métricas sobre el fixture y compare la forma
del resultado. Alternativa más fuerte: firmar el artefacto y verificar la firma en CI.

### A2. El fingerprint no cubre el código, solo el `config.yaml`

`config_fingerprint()` hashea `config.yaml`. Pero las features que el modelo usa
**están hardcodeadas en `train.py`**, no en config.

Prueba ejecutada:

```
fingerprint actual                          : 73b45ff4228182d7
tras comentar una feature en train.py       : 73b45ff4228182d7   <-- IDÉNTICO
```

Se puede agregar o quitar una variable del modelo y el gate no se entera.

**Severidad: crítica.** El gate da una garantía que no cumple.

**Arreglo:** que `train.py` **lea** las listas de features desde `config.yaml`, y
que el fingerprint hashee lo que realmente se usó (registrado en la corrida), no lo
que el config declara.

---

## B. `config.yaml` no es la superficie declarativa que dice ser

### B1. Dos listas de features paralelas, en convenciones distintas

```
config.features.numeric : ['GrossApproval', 'SBAGuaranteedApproval',
                           'InitialInterestRate', 'JobsSupported']
train.py NUMERIC        : ['gross_approval', 'sba_guaranteed', 'initial_rate',
                           'jobs_supported', 'guarantee_pct', 'log_gross_approval']
```

Nombres fuente contra nombres de panel, con contenidos distintos. El config
describe una intención; el código hace otra cosa. Es la causa raíz de A2.

### B2. Config muerto

Claves declaradas que ningún módulo lee:

| Clave | Estado |
|---|---|
| `stress_cohorts` | **muerta** — declarada en ADR 0003 como característica, nunca implementada |
| `target.pd_column` | **muerta** — el nombre está hardcodeado |
| `target.lgd_numerator` | **muerta** — hardcodeado en `train_economics.py` |

`stress_cohorts` es la peor: la presenté como "convertir la limitación en
característica" y solo escribí YAML que parece funcionalidad.

**Arreglo:** implementar o borrar. Config que no se lee es documentación que miente.

---

## C. Los umbrales de gobierno no están justificados

```yaml
min_auc_test: 0.68
max_auc_drop_oot: 0.08
max_brier: 0.20
min_disparate_impact_ratio: 0.80
```

Solo el último tiene fundamento real (regla de los 4/5, EEOC). Los otros tres los
elegí porque el modelo los pasaba.

**Severidad: alta, y conceptualmente la peor del proyecto.** En gobierno de modelos
**el umbral es el artefacto**, más que el modelo. Un umbral fijado después de ver el
resultado no es un control: es una racionalización.

**Arreglo:** derivar cada umbral de algo externo — el desempeño del sistema que
reemplaza, el mínimo con el que la economía es positiva, o literatura de la
industria — y escribir esa derivación al lado del número.

---

## D. Defectos técnicos

### D1. PSI calculado sobre probabilidades crudas

`psi()` compara distribuciones de probabilidad entre train y test. Cuando la tasa
base se mueve (6.75% → 9.60%), el PSI mide **el cambio de nivel**, no el cambio de
población. Por eso el primer diseño dio 4.08.

Lo interpreté como síntoma de un split mal diseñado —lo era— pero la métrica sigue
mal construida. Debe calcularse sobre bandas de score o sobre rangos.

### D2. Comparación injusta contra la red neuronal

En ADR 0004 usé "sale de fábrica con ratio 5.55" como argumento contra la red. Pero
esa descalibración **la causé yo** al ponerle `pos_weight`; el GBM no lo lleva. Es
una desventaja de mi configuración, no una propiedad de las redes.

La conclusión (LightGBM a producción) se sostiene por otras razones — 17x el tiempo,
explicabilidad, export a ONNX — pero ese argumento concreto hay que retirarlo.

### D3. Deuda de ingeniería menor

- `GBMChallenger.fit` llama a `_prep(X)` sobre el DataFrame completo solo para leer
  los dtypes.
- `train.py` y `train_economics.py` recargan el panel de 1.4M filas por separado.
- `exports/` mezcla resultados versionables con artefactos de trabajo (ya corregido
  a medias con el prefijo `_`).

---

## E. Modelado: 1.4 puntos de AUC sobre la mesa, y mi plan estaba medio equivocado

Medido (test FY2017-2018):

| Configuración | AUC |
|---|---|
| Actual (15 features) | 0.7009 |
| + NAICS a 4 dígitos | **0.6890** (empeora) |
| + identidad del banco | **0.7140** |
| + oficina distrital y estado del proyecto | 0.6975 (empeora) |
| + todas | 0.7149 |

En `NOTES.md` escribí que faltaba "NAICS a 4 dígitos, identidad del banco". **Solo
una de las dos ayuda.** NAICS-4 empeora el modelo: demasiadas categorías, sobreajuste.

Y la que sí funciona abre una pregunta de gobierno que no había considerado:
**¿es legítimo penalizar a un solicitante por el banco al que fue?** El banco no es
un atributo del prestatario. Mejora el AUC 1.3 puntos y podría ser inaceptable en
política de crédito. Esa decisión pertenece al model card, no a una búsqueda de
features.

Tampoco hice **tuning de hiperparámetros**. Presenté los del GBM como
"deliberadamente regularizados"; la verdad es que nunca los busqué.

---

## F. Cómo debí haber trabajado

### F1. Auditar el propio control antes de celebrarlo
Escribí "el gate bloquea de verdad, lo probé fallando" y mostré dos modos de falla.
Ambos eran modos que **yo mismo diseñé**. No intenté engañarlo hasta que me lo
pidieron, y cuando lo intenté cayó en dos minutos. En un proyecto sobre auditoría,
la prueba adversarial contra el propio control debía venir antes del anuncio.

### F2. Diseñar el split antes de correr el signal gate
Declaré "PASA: AUC 0.6736" en Semana 1 y en Semana 2 rediseñé el split, cambiando el
número a 0.6870. Un gate cuyo criterio se recalcula después no cumplió su función de
gate. Debí fijar el diseño temporal primero.

### F3. Terminar el modelo antes de traducirlo a dólares
Corrí la economía —el titular de $276.3M— sobre un modelo con feature engineering
incompleto y cero tuning. Con las features que faltan el número cambia. Fui a lo
vistoso antes que a lo fundamental.

### F4. Dejar de parchear archivos con reemplazo de strings
Tres fallos de edición (`train.py` dos veces, `train_economics.py` una, que además
rompió un f-string y dejó el archivo sin compilar) porque insistí en reemplazo de
texto sobre archivos que `ruff format` reescribía entre operaciones. Debí cambiar a
edición estructurada tras el primer fallo, no tras el tercero.

### F5. No escribir config que aparenta funcionalidad
`stress_cohorts` con comentarios elaborados sobre SR 11-7, y ninguna línea de código
que lo lea. Eso es peor que no tenerlo: promete una capacidad que no existe.

---

## G. Qué sí resistió la auditoría

Para calibrar: no todo salió mal.

- **El hallazgo de fuga en `TermInMonths`** se sostiene. El método —comparar contra
  préstamos cancelados como grupo de control— es correcto y reutilizable, y la
  herramienta que lo generaliza se auto-corrigió cuando marcaba falsos positivos.
- **El rediseño del split** está bien fundamentado y medido, no intuido.
- **`make reproduce`** funciona de verdad: 3 modelos, 6 métricas, idénticas a 1e-4,
  incluida la red PyTorch.
- **El patrón de desconfiar de los números buenos** funcionó tres veces: AUC 0.946
  (fuga), PSI 4.08 (split mal diseñado), corte óptimo al 50% (borde de grilla).
- **El fixture sin PII** fue la decisión correcta y no la pidió nadie.

---

## H. Orden de arreglo propuesto

| # | Defecto | Severidad | Esfuerzo |
|---|---|---|---|
| 1 | A1 — metrics.json editable a mano | Crítica | Medio |
| 2 | A2 + B1 — fingerprint no cubre el código | Crítica | Bajo |
| 3 | C — umbrales sin derivación | Alta | Bajo |
| 4 | B2 — config muerto | Media | Bajo |
| 5 | E — features faltantes + decisión sobre `bank` | Media | Medio |
| 6 | D1 — PSI mal construido | Media | Bajo |
| 7 | D2 — retirar el argumento del `pos_weight` del ADR 0004 | Baja | Bajo |
| 8 | README/Makefile inusables en Windows sin `make` | Baja | Bajo |
| 9 | D3 — deuda de ingeniería | Baja | Bajo |

Los dos primeros son los que hay que hacer antes de seguir con HMDA: mientras el
gate se pueda engañar, todo lo que se construya encima hereda esa debilidad.

---

# Resolución — 2026-09-09

Los nueve defectos, cerrados. Cada uno con la prueba que antes fallaba.

| # | Defecto | Estado | Verificación |
|---|---|---|---|
| A1 | `metrics.json` editable a mano | **Cerrado** | El gate **recomputa** las métricas desde predicciones guardadas. `tests/test_integrity.py` |
| A2 | Fingerprint no cubre el código | **Cerrado** | Huella del código de modelado + features leídas de config |
| B1 | Dos listas de features paralelas | **Cerrado** | `crmlops.features.spec` es la única fuente; no hay copia en Python |
| B2 | Config muerto | **Cerrado** | `stress_cohorts` implementado; `pd_column`/`lgd_*` eliminados |
| C | Umbrales sin derivar | **Cerrado** | Cada umbral con su derivación en `config.yaml` |
| D1 | PSI mal enunciado | **Corregido y ampliado** | Ver nota abajo |
| D2 | Argumento injusto contra la red | **Retirado** | ADR 0004, sección de corrección |
| D3 | Deuda de ingeniería | Parcial | `_preds_test.npy` fuera; recarga duplicada del panel sigue |
| E | Features y tuning | **Cerrado** | Medido, decidido y documentado en ADR 0005 |
| 8 | README con comandos inejecutables | **Cerrado** | `run.cmd` para Windows (ver NOTES: reabierto y vuelto a cerrar dos veces) |

## Sobre el defecto D1: mi hallazgo estaba mal enunciado

Escribí que el PSI "está mal construido" por calcularse sobre probabilidades
crudas. **Eso era impreciso**: el PSI sobre la escala del score *es* el estándar de
la industria, y el 4.08 de la Semana 2 estaba señalando un problema real.

El problema verdadero es otro: el PSI a secas no distingue **corrimiento de nivel**
(la tasa base se movió con el ciclo, se arregla recalibrando) de **cambio de forma**
(la mezcla de solicitantes cambió, exige revisar el modelo). Se implementó
`stability()`, que separa ambos re-centrando en escala logit:

```
PSI total          0.1746   -> "vigilar"
PSI de forma       0.0168   -> estable
corrimiento nivel  1.238x
-> corrimiento de NIVEL: recalibrar basta, no hace falta reentrenar
```

Esa es la respuesta accionable que el PSI solo no daba.

## Un bug encontrado *durante* el arreglo

Al escribir los tests de integridad apareció que `check()` usaba una sola raíz para
las predicciones y para el código. Verificar artefactos en un directorio temporal
hacía que el fingerprint buscara los `.py` ahí y no los encontrara, marcando
"código cambiado" siempre. Se separaron en `artifacts_root` y `code_root`.

Habría llegado a producción sin los tests.

## Lo que la auditoría produjo, además de arreglos

**Pruebas de estrés** (`stress_cohorts`, que era config muerto) sobre cohortes
fuera del régimen de entrenamiento:

| Cohorte | FY | tasa base | AUC | ratio calibración |
|---|---|---|---|---|
| test (referencia) | 2017-2018 | 9.60% | 0.7005 | 0.97 |
| **crisis** | 2005-2008 | **31.19%** | **0.5456** | **0.12** |
| covid | 2020-2021 | 6.23% | 0.7231 | 1.36 |
| reciente | 2019 | 9.66% | 0.6742 | 1.17 |

**En un régimen tipo 2007 el modelo colapsa a AUC 0.5456 —apenas mejor que el
azar— y subestima el riesgo por un factor de 8** (predice 3.85% cuando la tasa real
es 31.19%).

Es el hallazgo más importante del proyecto y salió de implementar config que yo
había dejado muerto. El ordenamiento y el nivel se degradan de forma independiente,
y el expected loss se calcula con el nivel.

## Estado del gate

De 4 gates a 7, y los tres nuevos son de naturaleza distinta: verifican **el
artefacto**, no solo el modelo.

```
PASA   config_coherente         las métricas corresponden a este config
PASA   integridad               recomputadas desde predicciones, no creídas
PASA   auc_test          0.7005 >= 0.6894
PASA   drop_oot          0.0299 <= 0.08
PASA   brier_test        0.0828 <= 0.0868   (le gana al predictor sin habilidad)
PASA   ece_test          0.0107 <= 0.02
PASA   margen_sobre_baseline 0.0311 >= 0.02  (relativo, no se puede acomodar)
```

31 tests.
