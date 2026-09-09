# Bitácora

> Este archivo lo escribo yo, en mis palabras. Los hechos y números vienen del
> pipeline; el *por qué* de cada decisión lo pongo aquí para poder defenderlo.

## Semana 1 — Cimientos y signal gate

### Qué se construyó
- Repo con `uv` (Python 3.12), ruff, pytest, estructura `src/crmlops`.
- `config.yaml` como superficie declarativa: fuentes, exclusiones, splits, umbrales.
- Adquisición SBA 7(a) con **descubrimiento de URLs** y manifiesto SHA256 (ADR 0001).
- Panel de modelado en DuckDB con split out-of-time.
- Signal gate con umbral fijado **antes** de ver resultados.

### Hechos del dataset (vintage 260630)
- 1,961,455 préstamos 7(a) descargados (~860 MB, 4 archivos por era fiscal).
- 1,400,048 con resultado resuelto (P I F o CHGOFF). Tasa base: **15.7%**.
- Excluidos: EXEMPT (297,494), CANCLD (242,790), COMMIT (21,123 — censura a la derecha).

### El hallazgo de la semana
El primer gate dio **AUC 0.946**. No lo reporté como éxito: los modelos de crédito
reales viven en 0.70–0.80, así que un 0.95 es un síntoma, no un logro.

La investigación (detalle completo en [ADR 0002](docs/adr/0002-terminmonths-es-fuga.md))
mostró que `TermInMonths` **se sobrescribe cuando el préstamo se liquida**:

| Estado | % con plazo no redondo |
|---|---|
| CHGOFF | 84.8% |
| P I F | 16.8% |
| CANCLD (nunca desembolsado) | 9.4% |

Los cancelados nunca pasaron de la originación, así que su plazo es el original.
La diferencia 84.8% vs 9.4% no es economía: es el campo actualizado post-default.

**AUC honesto tras excluirlo: 0.6736** (train 0.7599, valid 0.6737).

### Números al cierre de la semana

| Métrica | Valor |
|---|---|
| AUC test out-of-time (FY2017-2019) | **0.6736** |
| Degradación train→test | +0.0862 |
| Umbral del gate | 0.65 → **PASA** |
| Features | 15 (sin tuning, sin macro) |

### Por qué esto es un buen punto de partida y no un mal resultado
_(escribir: por qué 0.67 sin tuning es una base sana, qué falta para 0.72-0.75)_

### Defectos encontrados y corregidos
1. URLs de SBA documentadas públicamente devolvían 404 — el portal se reestructuró
   y el slug cambió (`7-a-504-foia` → `7a-504-foia`). Resuelto con descubrimiento (ADR 0001).
2. `uv sync` instaló el paquete cuando `src/crmlops/` estaba vacío → `ModuleNotFoundError`.
   Resuelto con `--reinstall-package`.
3. Encoding cp1252 de la consola de Windows reventaba con `→`. Resuelto.
4. Diagnóstico de AUC por feature saltaba las categóricas: pandas 3.0 usa dtype `str`,
   no `object`, y el chequeo `dtype == object` fallaba en silencio.
5. **`TermInMonths` contaminado** (ADR 0002) — el defecto importante.
6. El guard anti-fuga comparaba nombres normalizados (`TermInMonths` → "terminmonths"
   vs panel `term_months` → "termmonths") y no coincidía. Reemplazado por una lista
   explícita de nombres de panel: un guard que falla en silencio es peor que ninguno.

### Auditoría de contaminación — generalización del hallazgo
Convertí el método CANCLD-vs-CHGOFF en `crmlops.evaluation.contamination_audit`.
Resultado sobre los 5 candidatos numéricos:

| Campo | ratio mediana | gap de redondez | veredicto |
|---|---|---|---|
| TermInMonths | 0.62 | **+78.1 pp** | CONTAMINADO |
| GrossApproval | 0.50 | −2.8 pp | predictivo legítimo |
| SBAGuaranteedApproval | 0.49 | +0.7 pp | predictivo legítimo |
| InitialInterestRate | 1.12 | +0.2 pp | ok |
| JobsSupported | 1.00 | 0.0 pp | ok |

La primera versión de la herramienta marcaba `GrossApproval` como sospechoso solo
por la divergencia de mediana. Estaba mal: que los préstamos chicos fallen más es
economía real. Ahora exige **dos señales** y solo su combinación condena:

1. **Divergencia de mediana** — el campo separa CHGOFF del control. Por sí sola no
   prueba nada.
2. **Divergencia de redondez** — los CHGOFF tienen valores no pactados que el control
   no tiene. Eso sí evidencia edición posterior: un valor contractual no deja de ser
   redondo solo.

_(escribir: por qué este test conjunto es defendible y dónde puede fallar)_

### Pendiente
- NAICS a 4 dígitos, identidad del banco, overlay macro de FRED.
- Extender la auditoría de contaminación a campos categóricos.

---

## Semana 2 — Baseline y diseño del split

### El split estaba mal diseñado
El primer split (train FY2000-2013) lo elegí por intuición: "usar todo y dejar lo
reciente para test". Dos síntomas lo delataron: **valid salía peor que test** (orden
imposible) y el **PSI daba 4.08**, un absurdo.

Causa: la tasa base del 7(a) es fuertemente cíclica — 36.9% en FY2007 contra 6.2% en
FY2013. Entrenar cruzando la crisis mezcla dos regímenes con un factor de 6 entre sí.
Medido, cuesta ~2.4 puntos de AUC.

Segundo criterio que faltaba: **censura por maduración**. FY2019 solo tiene 60.9% de
préstamos resueltos, así que su muestra está sesgada hacia los que resolvieron rápido.
El AUC por año lo confirma (2017: 0.717 → 2019: 0.678): la degradación sigue la
censura, no el calendario.

Diseño nuevo ([ADR 0003](docs/adr/0003-diseno-del-split-temporal.md)): train FY2011-2015,
valid FY2016, test FY2017-2018. Regla: solo cosechas con ≥70% resuelto.

| | antes | ahora |
|---|---|---|
| AUC test | 0.6669 | **0.6870** |
| PSI train→test | 4.08 | **0.1323** |
| orden valid > test | ✗ | ✓ |

Las cohortes descartadas no se tiran: la crisis 2005-2008 pasa a ser el **escenario de
estrés** que SR 11-7 exige de todas formas.

### Baseline: scorecard WoE + logística

| | train | valid | test |
|---|---|---|---|
| AUC | 0.6531 | 0.6725 | **0.6694** |
| Gini | 0.3062 | 0.3450 | 0.3388 |
| KS | 0.2236 | 0.2596 | 0.2453 |
| Brier | 0.0617 | 0.0708 | 0.0847 |

Degradación train→test: **−0.0163** (test mejor que train). El binning regulariza tanto
que no hay sobreajuste. Variables seleccionadas por IV: 10 de 15.

### Hallazgo: la calibración deriva con el ciclo
El modelo **sub-predice el riesgo en test**: predicho 7.84% vs observado 9.60%
(calibration_ratio 0.8166). Y el error crece con el decil — en el más riesgoso son
5 puntos porcentuales.

Es esperable: la tasa base subió de 6.75% (train) a 9.60% (test). El modelo está
calibrado al régimen de entrenamiento. **El ranking aguanta, la calibración no.**

Importa porque el expected loss se calcula con la probabilidad, no con el ranking: un
modelo que ordena bien pero sub-predice sistemáticamente subestima la pérdida de la
cartera. Es exactamente el punto de monitoreo continuo que exige SR 11-7.

_(escribir: por qué recalibrar es preferible a reentrenar, y cada cuánto)_

---

## Semana 3 — Retadores, recalibración y el número en dólares

### Los retadores le ganan al baseline

| Modelo | AUC test | Gini | KS | ratio crudo | seg. |
|---|---|---|---|---|---|
| red neuronal (MLP) | **0.7054** | 0.4108 | 0.3107 | **5.5553** | 61.2 |
| LightGBM | 0.7005 | 0.4009 | 0.2883 | 0.8702 | 3.5 |
| scorecard WoE | 0.6694 | 0.3388 | 0.2453 | 0.8166 | 2.4 |

### Me equivoqué y el bootstrap me corrigió
Mi primera reacción al +0.0049 de la red sobre el GBM fue "eso es ruido". Monté un
bootstrap pareado (2000 réplicas, mismos índices para ambos porque las predicciones
están correlacionadas) y **la diferencia resultó significativa**: IC95 [+0.0024,
+0.0078], p<0.0001.

Con n=89,313 hasta lo diminuto alcanza significancia. La lección no es que la red
gane: es que **significativo y relevante no son lo mismo**, y hay que decir cuál
de los dos se está afirmando.

Producción es LightGBM igual ([ADR 0004](docs/adr/0004-modelo-de-produccion.md)):
0.7% relativo de AUC no paga 17x el tiempo de entrenamiento, peor calibración de
fábrica y una superficie de fallo mayor.

### La red salía de fábrica con ratio 5.55
Predecía 5.5 veces la tasa real. Es el `pos_weight` que compensa el desbalance:
mejora el ranking y destruye el nivel. Se corrige con recalibración, pero un modelo
que necesita ese parche obligatorio es más frágil en producción que uno que no.

### Recalibración
Los tres calibradores se ajustan sobre **validación** — nunca train (el modelo ya
lo vio) ni test (fuga). El de producción se declaró **antes** de mirar test:
ajuste de intercepto, monótono, no puede alterar el ranking.

| Modelo | ECE crudo | ECE calibrado | ratio final |
|---|---|---|---|
| scorecard | 0.0190 | 0.0122 | 0.9174 |
| LightGBM | 0.0161 | 0.0107 | 0.9653 |
| red neuronal | 0.4372 | 0.0101 | 1.0186 |

_(escribir: por qué elegir el calibrador mirando test sería fuga aunque el
calibrador no vea las etiquetas de test)_

### El número en dólares

Cartera de test: **$33.0B prestados, $1.3B de pérdida realizada** (3.91%), 89,313
préstamos, 8,571 fallidos, pérdida media de $150.3K por préstamo fallido.

| Rechazo | Pérdida evitada | vs azar | Lift | % de pérdidas |
|---|---|---|---|---|
| 5% | $144.2M | $64.4M | 2.24x | 11.2% |
| **10%** | **$276.3M** | $128.8M | **2.15x** | 21.5% |
| 15% | $397.2M | $193.2M | 2.06x | 30.8% |
| 30% | $638.4M | $386.4M | 1.65x | 49.6% |

### Dos correcciones que el primer cálculo necesitaba

**1. El "corte óptimo" tocaba el borde.** A margen 2-3% decía "rechazar 50%", que
era justo el límite de mi grilla. No era un óptimo: la cartera pierde 3.91% del
monto, así que con margen menor a eso el objetivo crece de forma monótona y
rechazar más siempre mejora. Ahora el borde se marca explícitamente y se reporta
el **margen de equilibrio (3.91%)** que explica por qué.

**2. Faltaba separar quién pierde.** En 7(a) la SBA garantiza el préstamo — media
del 62.9%. El banco y el contribuyente no pierden lo mismo:

- absorbe la SBA: **$942.1M (73%)**
- absorbe el banco: **$345.8M (27%)**
- margen de equilibrio del banco: **1.05%** vs 3.91% bruto

Eso último explica el programa entero: la garantía baja el umbral de rentabilidad
del prestamista de 3.9% a 1.1%. Y cambia quién debería usar el modelo — el
beneficiario principal es el contribuyente, no el banco.

**Del titular de $276.3M, $173.8M los habría ahorrado el contribuyente.**

### Supuesto que hay que declarar
El contrafactual se calcula sobre préstamos que **sí fueron aprobados**, así que
supone que rechazar no altera el comportamiento del resto (prestatario, banco,
mercado). Sirve para dimensionar; para política de crédito real haría falta un
experimento.

---

## Semana 4 — Gobierno

### Los gates bloquean de verdad
Un gate que solo se ha visto pasar no es un control, es decoración. Probé los dos
modos de falla:

**Modo 1 — el modelo no alcanza el umbral.**
```
FALLA  auc_test    0.7005 >= 0.75
BLOQUEADO: 1 de 4 gates fallaron.        exit=1
```

**Modo 2 — alguien cambia el split sin reentrenar.** Este es el sutil, y el que
más me interesaba cubrir:
```
FALLA  config_coherente   metricas de config 73b45ff4228182d7,
                          actual 750c75a7c5623832: reentrenar
```

El segundo existe por una decisión de diseño: los gates leen
`exports/metrics.json` (commiteado) en vez de reentrenar en CI, porque entrenar
exige ~860 MB de datos crudos que no viven en el repo y cuyo vintage rota cada
trimestre. El agujero obvio de ese diseño sería que alguien edite `config.yaml` y
deje métricas que ya no corresponden. El fingerprint lo cierra: hashea solo las
claves que **cambian el significado de un número** (splits, exclusiones, target,
features, semilla), así que cambiar una ruta o un comentario no invalida nada,
pero cambiar el split sí.

Estado actual: **4 gates, todos pasan.**

### Model card generado, no escrito
Un model card escrito a mano se desincroniza en la primera iteración y nadie lo
nota. `reports/MODEL_CARD.md` se construye desde `exports/metrics.json`, así que
o refleja el modelo actual o el gate de coherencia falla. Incluye limitaciones
declaradas: reject inference, deriva de calibración con el ciclo, el supuesto del
contrafactual, y censura residual del 25-30%.

Nota ética que quedó registrada: **el extracto FOIA de SBA no trae clases
protegidas**, así que sobre estos datos no se puede auditar sesgo. Eso va a HMDA
en Semana 6. Y `borrower_state` y `naics_sector` son proxies geográficos y
sectoriales que pueden correlacionar con características protegidas — queda
declarado, no oculto.

### make reproduce
```
REPRODUCIBLE: 3 modelos, 6 metricas cada uno, identicas hasta 0.0001.
```
Incluye la red PyTorch. La tolerancia no es cero a propósito: LightGBM con
`n_jobs=-1` y PyTorch en CPU multihilo pueden diferir en el último bit según cómo
se repartan los hilos. 1e-4 es mucho más fino que cualquier diferencia capaz de
cambiar una decisión.

_(escribir: por qué un repo puede tener CI verde y aun así ser irreproducible)_

### Pendiente Semana 5
- HMDA a escala: ~50M filas, dos backends (DuckDB y PySpark) con benchmark.
- Conectar el gate de fairness, que ya está declarado pero sin datos que lo activen.

---

## Auditoría interna y cierre de los 9 defectos

Sometí el proyecto a una auditoría adversarial ([docs/AUDIT.md](docs/AUDIT.md)).
Un proyecto que afirma construir "ML que sobrevive una auditoría" tiene que
soportar una. No la soportó bien: **9 defectos, dos críticos en el mecanismo
central.**

### Lo que estaba roto

**El gate se engañaba editando el archivo que leía.** Puse AUC 0.95 a mano en
`metrics.json` y los cuatro gates pasaron. El control validaba su propia entrada
sin verificarla.

**El fingerprint no cubría el código.** Comenté una feature en `train.py` y el
hash no se movió, porque hasheaba `config.yaml` mientras el modelo usaba listas
hardcodeadas en Python — en otra convención de nombres.

**Los umbrales los elegí porque el modelo los pasaba.** El de Brier estaba en
0.20 cuando el predictor sin habilidad da 0.0868: era 2.3 veces peor que no
hacer nada. Decorativo.

### Lo que quedó

De 4 gates a 7, y los nuevos verifican **el artefacto**, no solo el modelo:
las métricas se recomputan desde predicciones guardadas, y cada umbral tiene su
derivación escrita al lado.

El gate más sólido es el relativo: el retador debe superar al scorecard
interpretable por ≥0.02. Ese no se puede acomodar eligiendo el número, porque se
mide contra un modelo entrenado en la misma corrida.

### El hallazgo que salió de arreglar config muerto

`stress_cohorts` estaba declarado con comentarios sobre SR 11-7 y ninguna línea
que lo leyera. Al implementarlo:

| Cohorte | tasa base | AUC | ratio calibración |
|---|---|---|---|
| test (referencia) | 9.60% | 0.7005 | 0.97 |
| **crisis 2005-2008** | **31.19%** | **0.5456** | **0.12** |
| covid 2020-2021 | 6.23% | 0.7231 | 1.36 |

**En un régimen tipo 2007 el modelo colapsa a casi azar y subestima el riesgo 8
veces.** Es el hallazgo más importante del proyecto, y salió de implementar algo
que yo había dejado como YAML decorativo.

### Mi plan de features estaba medio equivocado
Escribí que faltaban "NAICS a 4 dígitos, identidad del banco". Medido: NAICS-4
**empeora** (0.6890 vs 0.7009) por sobreajuste. La identidad del banco sí ayuda
(+1.3 puntos) pero la descarté por política ([ADR 0005](docs/adr/0005-features-descartadas-y-tuning.md)):
el banco no es un atributo del prestatario, y penalizar a alguien por dónde pidió
el préstamo es exactamente lo que un examen de fair lending cuestiona.

El tuning que nunca hice: 25 configuraciones, **+0.0009**. Mi afirmación de que
los hiperparámetros estaban "deliberadamente regularizados" resultó cierta por
suerte, no por verificación. Ahora está verificada.

### Un bug encontrado durante el arreglo
Escribiendo los tests apareció que `check()` usaba una sola raíz para las
predicciones y para el código. Habría llegado a producción sin los tests.

### Un hallazgo mío que estaba mal enunciado
Dije que el PSI "está mal construido". Impreciso: el PSI sobre la escala del
score *es* el estándar. El problema real es que no distingue nivel de forma.
Implementé `stability()`, que los separa:

```
PSI total 0.1746 | PSI de forma 0.0168 | nivel 1.238x
-> corrimiento de NIVEL: recalibrar basta, no hace falta reentrenar
```

_(escribir: por qué un control que no se ha intentado romper no es un control)_

---

## Semana 5 — HMDA a escala y benchmark de backends

### 62,375,170 solicitudes en 0.87 GB
Descargué HMDA FY2020-2024 por API de estado-año en vez de los snapshots
nacionales de 5.8 GB. La ventaja que importa no es la velocidad: el endpoint
`/aggregations` devuelve los conteos oficiales del CFPB, así que puedo verificar
que la descarga está **completa y no truncada**. Las 12 muestras verificadas
coinciden exacto (CA 2020: 2,325,977 local = 2,325,977 oficial).

La poda de columnas —de 99 a 32— más zstd metió 62M filas en 870 MB. Los CSV
crudos habrían sido ~18 GB.

### La misma fuga que en SBA, con otra cara
`interest_rate` está nulo en **99.4% de las denegadas y 0.0% de las originadas**.
Una solicitud rechazada no tiene tasa porque nunca hubo préstamo. Un modelo con
esa columna aprende "tiene tasa → aprobado".

Eso me obligó a distinguir **tres** clases de exclusión, no una
([ADR 0006](docs/adr/0006-exclusiones-en-hmda.md)):

1. **Solo existe si se originó** — `interest_rate`, `denial_reason-*`.
2. **La decisión del propio banco** — `aus-1..5` son los resultados de su motor de
   suscripción. Sí están disponibles al decidir, pero usarlos convierte esto en
   "predecir una decisión desde la decisión": el modelo imitaría sus sesgos con
   apariencia de objetividad.
3. **Proxy de clase protegida** — `tract_minority_population_percent` es la
   composición racial del barrio. Que el modelo no vea `derived_race` no cambia
   nada si recibe una variable que la aproxima. Es redlining.

### Benchmark: 29.1x, con resultados idénticos

| Motor | Tiempo | Filas | Grupos |
|---|---|---|---|
| **DuckDB** | **1.03s** | 62,375,170 | 6,801 |
| PySpark | 30.13s | 62,375,170 | 6,801 |

Los 6,801 grupos coinciden en las 5 métricas. Spark paga arranque de JVM,
serialización y planificación distribuida; DuckDB no. La ventaja de Spark aparece
cuando el dato no cabe en una máquina, no antes.

### La verificación de equivalencia se justificó antes de correr
El primer intento reventó, y el motivo es exactamente lo que esa verificación
existe para atrapar: **`try_cast` de DuckDB devuelve NULL con entrada inválida;
`cast` de Spark 4 LANZA** (modo ANSI por defecto desde Spark 4). HMDA codifica los
faltantes como el texto `'NA'`.

Mis dos implementaciones no eran equivalentes: DuckDB descartaba esas filas en
silencio, Spark moría. Lo arreglé usando `try_cast` explícito en ambos, para que
sean equivalentes **por construcción** y no por un flag de sesión que alguien
pueda cambiar sin notar que rompe la comparación.

Y mi manejador de error mentía: decía "requiere un JDK" ante cualquier fallo, y la
primera vez que se activó el JDK estaba perfecto. Un mensaje que adivina la causa
manda a depurar en la dirección equivocada. Corregido.

### Disparidad observada — antes de cualquier modelo

| Grupo | n | Denegación | Ingreso mediano |
|---|---|---|---|
| White | 41,238,165 | 17.66% | $95,000 |
| Asian | 3,805,069 | 17.98% | $130,000 |
| Native Hawaiian / Pacific Islander | 145,090 | 31.11% | $87,000 |
| Black or African American | 4,534,385 | **32.84%** | $77,000 |
| American Indian / Alaska Native | 353,399 | 34.13% | $73,000 |
| 2 or more minority races | 122,157 | **34.93%** | $85,000 |

**Razón de 4/5: 0.790 — no pasa el umbral del EEOC.**

Etnia: hispanos 26.83% vs no hispanos 18.38% (ratio 0.896, pasa).
Sexo: mujeres 23.91% vs hombres 22.14% (ratio 0.974, pasa).

### El hallazgo que no esperaba: la disparidad sigue al ciclo de tasas

| Año | Razón 4/5 | Brecha |
|---|---|---|
| 2020 | 0.827 | 14.8 pp |
| 2021 | 0.834 | 14.2 pp |
| 2022 | 0.771 | 18.2 pp |
| 2023 | **0.729** | **20.7 pp** |
| 2024 | 0.768 | 18.1 pp |

**La brecha se amplió justo cuando subieron las tasas.** 2020-21 fue el auge de
refinanciación con crédito fácil; 2022-24 es el shock de tasas. El endurecimiento
del crédito **no se distribuye de forma pareja**: pasa de 14.8 a 20.7 puntos
porcentuales.

_(escribir: por qué medir la disparidad observada ANTES del modelo cambia lo que
se puede afirmar después)_

### Advertencia que va en el reporte
HMDA no incluye puntaje de crédito, el determinante más fuerte de una decisión de
suscripción. Una diferencia en tasas de denegación **no prueba discriminación**:
prueba que hay una diferencia que exige explicación. Un examen de fair lending del
CFPB empieza aquí, no termina aquí.

### Pendiente Semana 6
- Modelo B sobre HMDA y el gate de fairness, que ya está declarado pero sin datos
  que lo activen.
- Medir cuánta disparidad **agrega** el modelo sobre la que ya existe.

---

## Semana 6 — El gate de equidad se enciende y bloquea

### El modelo
LightGBM sobre HMDA, test FY2024 (1.94M solicitudes): **AUC 0.8847**, Gini 0.7694,
KS 0.6078, ECE 0.0045.

Predecir denegación es genuinamente más fácil que predecir default —la decisión
del banco es bastante mecánica sobre DTI, LTV e ingreso— pero 0.88 merecía
escrutinio. Quitar `property_value` y `ltv` cuesta solo 2 puntos (0.8847 →
0.8648), nada parecido al colapso de `TermInMonths`. El AUC es real.

### El gate bloqueó

```
hmda:disparate_impact  0.7639 >= 0.8  -> NO promovido, gate cumpliendo su funcion
```

| Dimensión | DIR | |
|---|---|---|
| Raza | **0.764** | no pasa |
| Etnia | 0.903 | pasa |
| Sexo | 0.940 | pasa |

### Semántica que me importó definir bien
**Un gate bloquea promoción; no rompe el build.** El modelo se midió, se
documentó, falló el umbral y por eso no se despliega — eso *es* el sistema
funcionando. Lo que sí hace fallar CI es marcar `promoted: true` algo que no
cumple. Cuatro tests cubren ambos lados.

Si hubiera cableado el gate para reventar CI, el repo quedaría en rojo permanente
y la única salida sería bajar el umbral. Un control que empuja a relajarse a sí
mismo no es un control.

### La pregunta correcta da otra respuesta

| Dimensión | Observado | Modelo | Delta |
|---|---|---|---|
| Raza | 0.766 | 0.764 | **−0.002** |
| Etnia | 0.894 | 0.903 | +0.008 |
| Sexo | 0.909 | 0.940 | +0.031 |

**El modelo no crea la disparidad racial: la hereda casi exactamente.** Añade
−0.002 sobre decisiones humanas que ya daban 0.766, y la *reduce* en sexo y etnia.

Un análisis ingenuo habría titulado "el modelo es discriminatorio, DIR 0.764".
La lectura correcta es más incómoda: el modelo falla el test de los 4/5, y también
lo fallan las decisiones de las que aprendió. Eso no lo exculpa —automatizar una
disparidad la escala y le da apariencia de objetividad— pero cambia dónde hay que
intervenir.

Solo puedo afirmar eso **porque medí la línea base antes del modelo**. Si hubiera
empezado por el modelo, el titular habría sido cierto en la letra y equivocado en
la causa.

_(escribir: por qué el orden de medición determina qué se puede afirmar)_

### La descomposición del PSI se ganó su lugar
```
PSI total 0.1165 | de forma 0.2099 -> cambio de FORMA
```
El PSI de forma **supera** al total: nivel y forma se movieron compensándose.
Diagnóstico: recalibrar no basta, hay que reentrenar. Tiene sentido económico —
la población de 2020-22 (refinanciación) es estructuralmente distinta de la de
2024 (compra). Esa métrica salió de la auditoría, no del plan original.

### Reporte de validación
`reports/VALIDATION_REPORT.md`, generado desde los artefactos: estructura SR 11-7
más mapeo de los 11 requisitos del Anexo IV del Reglamento de IA de la UE.
Marqué uno como **parcial** en vez de inflar el cumplimiento, y le puse una
declaración de alcance explícita: esto documenta un ejercicio técnico y **no es
una evaluación de conformidad**.

En un proyecto que se vende como "ML que sobrevive una auditoría", reclamar
cumplimiento del AI Act sin organismo notificado sería exactamente el tipo de
afirmación que un revisor busca para desmontarlo.

### Pendiente Semana 7
- Export ONNX y serving por tres vías.
- Decidir el tratamiento de la nulidad diferencial de `ltv` según la auditoría.
