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

### Benchmark: DuckDB gana por un factor que depende de la máquina

| Motor | Máquina A | Máquina B | Filas | Grupos |
|---|---|---|---|---|
| **DuckDB** | **1.03s** | **1.23s** | 62,375,170 | 6,801 |
| PySpark | 30.13s | 17.61s | 62,375,170 | 6,801 |
| | **29.3x** | **14.3x** | | |

Los 6,801 grupos coinciden en las 5 métricas, en las dos máquinas.

**El multiplicador no viaja; la conclusión sí.** La primera versión de esta nota
titulaba "29.1x" como si fuera una propiedad de los motores. Correrlo en un
segundo equipo dio 14.3x: más del doble de diferencia, mismo código y mismos
datos. Lo que varía es sobre todo el costo fijo de Spark —arranque de JVM,
serialización, planificación—, que pesa distinto según CPU y disco.

Así que el número que vale es cualitativo y ese sí se sostiene: **en un solo nodo,
sobre 62M filas, DuckDB es entre 14 y 29 veces más rápido, y Spark paga un costo
fijo que solo se amortiza cuando el dato no cabe en una máquina.** Citar "29.1x"
a secas sería vender como constante algo que medí una vez en un equipo.

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

### Auditoría de fuga por nulidad
Convertí el chequeo en herramienta permanente. `ltv` está nulo en 6.0% de las
aprobadas y 15.6% de las denegadas, con causa operativa clara: **si una solicitud
se rechaza temprano por DTI, nunca se ordena la tasación**.

| Escenario | AUC |
|---|---|
| valor + ausencia | 0.8835 |
| solo valor (imputado) | 0.8825 |
| ni valor ni ausencia | 0.8645 |
| solo ausencia | 0.8708 |

**Ausencia: +0.0010. Valor: +0.0180.** Decisión: conservar sin imputar
([ADR 0008](docs/adr/0008-nulidad-diferencial-en-ltv.md)). El paso de imputación
cuesta más de lo que arregla.

El matiz que los cuatro escenarios revelan y que dos no habrían mostrado: aislada,
la ausencia **sí** discrimina (+0.0063). La fuga es real pero **redundante** — con
los valores presentes, esa información ya viene contenida en ellos. En un modelo
con menos variables podría aportar los 0.0063 completos y sí justificar imputar.
La conclusión es contextual, no universal.

_(escribir: cuándo una fuga pequeña se tolera y cuándo no)_

### Pendiente Semana 7
- Export ONNX y serving por tres vías.


---

## Semana 8 — La plantilla le gana al LLM

### El resultado
Seis avisos por proveedor (3 casos × 2 idiomas):

| Proveedor | Fidelidad | Cumple | Legibilidad | Consistencia | Pasa |
|---|---|---|---|---|---|
| **plantilla** | **1.00** | 1.00 | 44.8 | **1.00** | **100%** |
| llama3.2:3b | 0.50 | 1.00 | **73.2** | 0.50 | **0%** |

### El hallazgo está en el detalle, no en el promedio
El fallo no está repartido: **está entero en español.**

| Idioma | Fidelidad | Palabras |
|---|---|---|
| Inglés | 1.00 | 86–149 |
| Español | **0.00** | **18** |

Y las 18 palabras son siempre las mismas:

> No puedo redactar un aviso de acción adversa de crédito. ¿Hay algo más en lo que
> pueda ayudarte?

**No es un fallo de capacidad: es un rechazo de seguridad.** Mismo modelo, mismo
prompt traducido, misma temperatura, misma semilla — redacta en inglés y rechaza
en español. El alineamiento del modelo es **asimétrico entre idiomas**.

Una evaluación monolingüe habría reportado fidelidad 1.00 y recomendado desplegar.

_(escribir: por qué evaluar en un solo idioma es evaluar a medias)_

### Lo que el LLM sí aporta, y por qué no alcanza
Legibilidad **73.2 contra 44.8**: la plantilla queda en "difícil", el modelo en
"bastante fácil". Para un documento que lee alguien sin formación financiera, esa
diferencia es real.

El precio: fidelidad a la mitad, y **texto distinto entre ejecuciones idénticas**
con temperatura 0. Un aviso legal que cambia entre corridas es indefendible ante
un regulador.

Decisión: la plantilla va a producción
([ADR 0009](docs/adr/0009-la-plantilla-gana-al-llm.md)).

### Tres bugs que el harness encontró en mi propio código
1. **La plantilla fallaba el chequeo de cumplimiento.** "La ANTIGÜEDAD del
   negocio" contiene "edad" y yo comparaba subcadenas.
2. **Más de fondo: confundí antigüedad del negocio con edad del solicitante.** La
   primera es un factor de suscripción legítimo; la segunda, una base protegida.
3. **`""` en una cadena normal de Python es un BACKSPACE**, no un límite de
   palabra. El chequeo dejó de detectar nada **en silencio**, que es lo peligroso.

### Una limitación de mi propia métrica, declarada
La fidelidad mide **qué** factores se citan, no si lo que se dice **sobre** ellos
es correcto. El aviso en inglés sacó 1.00 y aun así afirma que el solicitante
"pidió" la tasa de interés, que es falso. Cerrarlo exigiría verificar afirmaciones
causales, no solo presencia. No está implementado, y decir 1.00 sin esta nota
vendería una garantía que la métrica no da.

### Ampliación: cinco brazos, y dos conclusiones mías caídas

**1. El rechazo en español era del modelo de 3B, no de la tarea.** qwen2.5:7b no
se niega: fidelidad 1.00 en ambos idiomas.

**2. La inconsistencia era un bug de medición mío.** Verifiqué antes de publicar:

| Condición | Corridas | Únicas |
|---|---|---|
| Prompt corto | 4 | **1** |
| Prompt real, sin calentar | 3 | 2 — *la primera difiere* |
| Prompt real, con calentamiento | 3 | **1** |

La primera generación tras cargar el modelo no es determinista; las siguientes sí.
El harness medía el arranque en frío. Con `warm_up()`, qwen2.5:7b pasó de 0% a 83%.

| Brazo | Fidelidad | Legibilidad | Consistencia | Pasa |
|---|---|---|---|---|
| **plantilla** | 1.00 | 44.8 | **1.00** | **100%** |
| qwen2.5:7b | 1.00 | 57.8 | 0.83 | 83% |
| qwen2.5:7b (híbrido) | 1.00 | 53.4 | 0.50 | 50% |
| llama3.2:3b (híbrido) | 1.00 | 53.2 | 0.33 | 33% |
| llama3.2:3b | 0.50 | 74.6 | 0.50 | 0% |

La decisión no cambia —la plantilla va a producción— pero el margen ya no es
abismal y la razón es una sola: consistencia.

> **Este 0.83 tampoco sobrevivió.** Correr el mismo harness en otro equipo dio
> **0.33** para qwen2.5:7b. Ver la segunda revisión de
> [ADR 0009](docs/adr/0009-la-plantilla-gana-al-llm.md): arreglé un artefacto real
> y publiqué en su lugar una medición puntual disfrazada de propiedad del modelo.

### Una pregunta que dejo abierta, sin inventarle respuesta
Los híbridos resuelven la fidelidad y salen **menos consistentes que el modelo
solo**. Mi hipótesis es que validar-y-caer introduce varianza en el borde: si una
corrida acepta la reescritura y la otra la rechaza, se emiten dos documentos
distintos, ambos válidos. Sería un defecto de mi diseño, no del modelo.

Confirmarlo exige registrar por caso si se usó LLM o fallback y comparar esa
decisión entre corridas. **No está implementado, y afirmar la causa sin medirla
sería repetir el error que esta misma revisión corrige.**

_(escribir: por qué un eval de un solo modelo produce conclusiones que se leen
razonables y son falsas)_

### Pendiente Semana 9
- Monitoreo de drift con datos trimestrales reales de SBA.
- Reentrenamiento automático con gate de promoción.
- Cerrar la pregunta abierta del híbrido (instrumentar la decisión de fallback).

---

## Documentar la instalación — y los diez defectos que salieron al hacerlo

Escribir [docs/INSTALL.md](docs/INSTALL.md) no era trabajo de modelado. Encontró
diez cosas, cuatro de ellas serias, y ninguna se habría visto revisando la lógica
del modelo.

Seis salieron **escribiendo** la guía. Las cuatro últimas salieron **siguiéndola
de principio a fin en una máquina limpia**, y entre ellas están las peores: un
entry point que no arrancaba, una tubería que terminaba en verde con el
entrenamiento roto, y dos números publicados que en otro equipo dan otra cosa.
Ninguna de las seis primeras las habría encontrado.

### 1. Las instrucciones del README no se podían ejecutar

El bloque de PowerShell decía, literalmente:

```
.
un.ps1 setup       # entorno con uv
```

Un `\r` escrito sin escapar se volvió un salto de línea real y partió `.\run.ps1`
en dos. La ironía es exacta: el defecto 8 de [docs/AUDIT.md](docs/AUDIT.md) era
*"el README pide `make setup` en una máquina donde `make` no existe: instrucciones
que no se pueden ejecutar"*. Lo arreglé, y al arreglarlo lo rompí de otra forma.

Se encontró porque escribir una guía de instalación obliga a leer lo que ya está
escrito como lo lee quien llega por primera vez. No hay test que cubra esto.

### 2. `setup` no instalaba el hook de autoría

`.git/hooks` no se clona. El hook vive en `scripts/hooks/` y solo funciona si
`core.hooksPath` apunta ahí — y eso estaba configurado **en mi máquina**, a mano,
nunca en `setup`. En un clon nuevo la restricción que más me importa del proyecto
no existía, y un trailer de IA solo lo habría detectado CI, después del push.

Ahora `make setup` y `.\run.ps1 setup` lo apuntan, e imprimen que lo hicieron.

### 3. El hook fallaba abierto — el defecto serio

El hook era una línea:

```sh
if grep -qiE 'co-authored-by:.*(claude|anthropic|...)' "$1"; then exit 1; fi
```

`grep` devuelve un código distinto de cero en **dos** situaciones que no son la
misma: cuando no encuentra nada, y cuando no pudo buscar. Escrito así, el hook
leía "no pude revisar" como "está limpio".

Verificado, no supuesto: invocándolo con el `sh.exe` de Git for Windows sin
`/usr/bin` en el PATH, `grep: command not found`, salida 0, **trailer aceptado sin
imprimir nada**. Git lo llama con su propio PATH, así que en uso normal nunca
fallaba. Eso es lo que lo hacía peligroso: un control que solo se cae en silencio
y en el momento en que hace falta.

Ahora rechaza si no puede leer el mensaje y rechaza si no hay `grep`. Y hay 17
tests (`tests/test_authorship_hook.py`) que le pasan siete mensajes con atribución,
seis legítimos —incluidos los que nombran a Anthropic u Ollama en prosa, porque
este proyecto los compara— y los casos de fallo cerrado.

**Los tests encontraron el defecto en la primera corrida.** El hook llevaba desde
la semana 1 sin que nadie le pasara un mensaje malo.

### 4. El hook estaba en modo 100644 desde el primer commit

Encontrado escribiendo el test anterior. **git ignora un hook que no tenga bit de
ejecución, y lo ignora en silencio.** En Windows daba igual —Git for Windows no
mira el bit— así que funcionaba justo en la máquina donde hago los commits, y no
existía en ningún clon de Linux o macOS.

Sumado al defecto 2, la conclusión es incómoda: **la restricción de autoría, que
es la que más me importa del proyecto, estaba sostenida por la configuración local
de una sola máquina.** No viajaba con el repo por dos razones independientes.

`git update-index --chmod=+x`, y un test que asserta el modo en el índice.

### 5. CI estaba en rojo y no me había dado cuenta

`ruff check` falla en `providers.py`: el `try/except Exception: pass` del
`warm_up()` que agregué en la semana 8 dispara `SIM105`. Está commiteado y
pusheado, así que el CI de la semana 8 está rojo desde entonces.

Empujé sin correr `lint`. La lección no es sutil: el proyecto tiene el comando,
está en el Makefile y en `run.ps1`, y no lo corrí.

### 6. El README anunciaba siete gates y son ocho

Faltaba `hmda:disparate_impact`, que es justamente el que hoy **no** promueve el
modelo de acceso (0.7639 contra un umbral de 0.80). El gate más interesante del
repo era el que no estaba en la tabla.

### 7. El primer comando de la guía no arrancaba en un Windows por defecto

Lo encontró Davirson clonando el repo limpio en otra carpeta y siguiendo la guía
al pie de la letra — que es la única forma de probar una guía de instalación.

```
.\run.ps1 : File ...\run.ps1 cannot be loaded because running scripts is
disabled on this system.
```

La ExecutionPolicy por defecto en Windows cliente es `Restricted`: **ningún `.ps1`
corre**. El entry point que escribí en la semana 7 para arreglar *"el README pide
`make` en una máquina sin `make`"* tenía el mismo problema con otro nombre.

Por qué no lo vi: `Get-ExecutionPolicy -List` en mi entorno da `Process = Bypass`.
El scope de proceso estaba abierto, así que desde aquí **el defecto era invisible**
— igual que los extras de CI en la semana 7. Tercera vez que aparece el mismo
patrón, y las tres veces la diferencia la hizo ejecutar en el entorno del otro, no
releer el código.

`run.cmd`: un `.cmd` no está sujeto a la ExecutionPolicy y le pasa a `run.ps1` un
bypass acotado a esa invocación. No cambia configuración del sistema ni de la
cuenta y no persiste nada.

#### El primer arreglo no funcionó — y falló exactamente por lo mismo

Publiqué `run.cmd` y le dije a Davirson que escribiera `.\run setup`. Volvió a
fallar, con el mismo error.

**PowerShell resuelve `.\run` al `.ps1`, no al `.cmd`.** Lo prefiere. Con los dos
archivos juntos en la raíz, el comando corto de la guía seguía cayendo en el
archivo que no arranca:

```
PS> Get-Command .\run
Name        : run.ps1
CommandType : ExternalScript
```

Yo lo había "verificado" corriendo `.\run help` en mi terminal — y funcionó,
porque ahí `Process = Bypass` ejecuta el `.ps1` sin chistar. **Mi verificación
tenía el mismo defecto que estaba arreglando: probé el arreglo en el único
entorno donde el bug no existe.**

Dos cosas salieron de ahí:

1. **`run.ps1` se movió a `scripts/`.** Sin dos archivos con el mismo nombre en la
   raíz no hay ambigüedad que documentar. `.\run` solo puede ser el `.cmd`.
2. **Ahora reproduzco la política, no la asumo.** Un proceso hijo con
   `powershell -NoProfile -ExecutionPolicy Restricted` es el entorno del usuario,
   y ahí verifiqué el arreglo: `.\run help` desde la raíz y `run.cmd lint` desde
   `C:\`, ambos con salida 0.

Es la diferencia entre "no vi que fallara" y "lo ejecuté donde fallaba y ya no
falla" — la misma distinción que el proyecto le exige a sus métricas.

Queda dicho sin adornos en la cabecera del archivo: **esto rodea la
ExecutionPolicy.** Microsoft la documenta como protección contra ejecución
*accidental* de scripts, no como límite de seguridad, y aquí la ejecución no tiene
nada de accidental. Para quien prefiera no rodearla, la guía trae la alternativa
—`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`— marcada como lo que es: un
cambio permanente en su cuenta, y por eso su decisión, no la mía.

### 8. `run all` terminó en verde con el entrenamiento roto

El peor de los ocho, y el más fácil de no ver.

Davirson corrió `.\run all` en el clon nuevo. `train` murió con
`ModuleNotFoundError: No module named 'torch'` — y la tubería **siguió**:

```
ModuleNotFoundError: No module named 'torch'
====================================================================
GATES DE PROMOCION
  PASA   auc_test    0.7005 >= 0.6894
  ...
APROBADO: 8 gates pasaron.
```

Los gates leen el `exports/metrics.json` commiteado, así que **pasaron sin que
existiera un modelo nuevo**. La última línea de la salida declaraba aprobado un
modelo que no se entrenó.

Dos causas independientes, y las dos son mías.

**a) `$ErrorActionPreference = "Stop"` no cubre comandos nativos.** Un scriptblock
con varios `uv run ...` sigue después de que uno devuelva código distinto de cero,
y el `exit $LASTEXITCODE` final reporta el del **último**. `all`, `lint` y `web`
tenían el mismo encadenado. En `lint` el efecto era: `ruff check` en rojo seguido
de `format` en verde → **exit 0**. CI no lo veía porque el Makefile pone cada
comando en su línea y `make` sí aborta.

Ahora hay un `Invoke-Step` que aborta con el nombre de la etapa y su código.

**b) Un extra opcional que era obligatorio de hecho.** `train.py` importaba
`torch` en la cabecera. Y como `train_economics`, `evaluation.stress` y
`export.onnx` importan de ahí dos constantes —`PRODUCTION_CALIBRATOR` y `TARGET`—,
**los cuatro** exigían PyTorch; tres de ellos por una dependencia que no usan en
ningún momento. Import perezoso dentro de `build_models`, que es la única función
que lo necesita.

Cuando falta, ahora dice qué correr en vez de escupir un traceback. `train` falla
en vez de saltarse el brazo neuronal en silencio, y eso es deliberado: la
comparación publicada lo incluye, así que sin él no se reproduce
`exports/metrics.json`.

**Cómo salió:** siguiendo la guía. `setup` instala solo `dev`, y la guía mandaba a
`all` justo después. El defecto estaba en la costura entre dos instrucciones que
por separado eran correctas.

`tests/test_run_aborta.py` y `tests/test_extras_opcionales.py`, 7 tests entre los
dos. El primero mete un `uv` falso que siempre falla y verifica que `all` **no
llegue a imprimir `APROBADO`**.

Y una nota sobre cómo lo verifiqué, porque el primer intento no valía: simulé la
ausencia de torch con `sys.modules["torch"] = None` y scipy reventó con un
`AttributeError` que no ocurre cuando torch de verdad no está. La simulación
mentía en la dirección peligrosa. Un finder que niega el módulo reproduce la
ausencia real.

### 9. Las advertencias que había aprendido a ignorar

Recorrer la guía hasta el final no rompió nada más, pero dejó a la vista cuatro
avisos que salían en cada corrida y que yo ya no leía. Ese es justamente el
problema: **una advertencia que hay que ignorar tapa a la que no había que
ignorar.**

| Aviso | Qué era de verdad | Qué se hizo |
|---|---|---|
| `Expected shape from model of {1} does not match actual shape of {20000} for output label` | `onnxmltools` declara la salida `label` con forma `[1]` en vez de `[None]`. Nunca se lee —el umbral es económico y lo pone el consumidor— pero `session.run(None, ...)` la pedía igual | Pedir **solo** `probabilities`. La advertencia desaparece y salía en el comando cuyo trabajo es descartar problemas de paridad |
| `The argument 'eval_set' is deprecated` | LightGBM 4.7 lo deprecó. Iba a romper, no solo a avisar | `eval_X`/`eval_y` en los dos sitios, y el piso de `pyproject` sube a `>=4.7` |
| `X does not have valid feature names` | Correcto y **deliberado**: la paridad le pasa a LightGBM la misma matriz posicional que al grafo, porque comparar contra el DataFrame mediría dos pipelines distintos | Silenciado ese mensaje, solo en esa llamada, con el porqué escrito al lado |
| `PySpark does not yet fully support pandas >= 3.0.0` | No es del proyecto: la emite **MLflow**, que importa `pyspark` si lo encuentra. Verificado con un trazador de imports | Documentado. No se toca lo que no es nuestro |

Y un 404 que no era un aviso sino la primera impresión: abrir
`http://localhost:8000` —lo primero que hace cualquiera— devolvía **404** sin
pista de que `/docs` existe. Ahora la raíz responde con los endpoints y con el
aviso de uso, que así viaja con el servicio en vez de vivir solo en el README.

#### El gate de integridad hizo su trabajo sobre mí

Cambiar `gbm.py` movió el `code_fingerprint`, y el gate `integridad` compara el
registrado contra el actual: *"metricas producidas por codigo X, actual Y:
reentrenar"*. No hay forma de tocar el entrenamiento y dejar las métricas viejas
publicadas sin que CI lo cante.

Así que reentrené con `reproduce`, que es el mecanismo del proyecto para esto:

```
REPRODUCIBLE: 3 modelos, 6 metricas cada uno, identicas hasta 0.0001.
```

El diff de `exports/metrics.json` lo confirma mejor que el mensaje: **cambiaron
`segundos` y el fingerprint, y nada más.** AUC, Brier, ECE y PSI de los tres
modelos, idénticos hasta el último dígito. El cambio de API de LightGBM era
semánticamente nulo, y ahora eso está demostrado en vez de supuesto.

#### Un límite que encontré y no voy a vender como virtud

Re-exportar produce un `model.onnx` con **bytes distintos**. Lo verifiqué antes de
asumir nada: los 5 nodos del grafo son idénticos y las predicciones coinciden
**bit a bit** sobre 20.000 filas. La diferencia vive en la serialización, fuera de
los nodos.

O sea: **el modelo es reproducible; el archivo no es hash-estable.** Es una
distinción que importa en un proyecto que se vende como auditable, y por eso la
escribo: en ningún lado se afirma que el artefacto ONNX tenga hash estable —los
SHA256 del repo son de los datos fuente— y la paridad se verifica numéricamente en
cada export, no por hash. Si algún día hiciera falta esa garantía, habría que
investigarla de verdad, no darla por hecha.

### 10. La corrida completa en otra máquina: qué reprodujo y qué no

Davirson clonó limpio y corrió **toda** la guía de punta a punta: `setup`,
`acquire`, `all`, `hmda`, `disparity`, `hmda-train`, `benchmark`, `llm-evals`,
`onnx`, `serve`, `web`. Es la única prueba que vale para un proyecto que se vende
como auditable, y separó los resultados en dos grupos.

**Reprodujo exacto, en un equipo que no es el mío:**

| Qué | Publicado | Su corrida |
|---|---|---|
| AUC test (LightGBM) | 0.7005 | **0.7005** |
| Margen sobre baseline | +0.0311 | **+0.0311** |
| AUC del scorecard | 0.6694 | **0.6694** |
| AUC HMDA (test FY2024) | 0.8847 | **0.8847** |
| Disparate impact del modelo | 0.764 | **0.764** |
| Filas HMDA | 62,375,170 | **62,375,170** |
| Grupos del benchmark | 6,801 idénticos | **6,801 idénticos** |

Esa columna es el proyecto entero funcionando: **las métricas del modelo viajan.**

**No reprodujo:**

| Qué | Publicado | Su corrida | Por qué importa |
|---|---|---|---|
| DuckDB vs PySpark | 29.3x | **14.3x** | Lo titulé como propiedad de los motores; es una medición de un equipo |
| Consistencia qwen2.5:7b | 0.83 | **0.33** | Es la métrica sobre la que descansa la decisión del ADR 0009 |

Los dos están corregidos arriba y en el ADR. El patrón es el mismo de siempre, y
van tres capas distintas: primero el entorno de ejecución, después las
advertencias que dejé de leer, ahora **los números que medí una vez y presenté
como constantes**.

La distinción que me llevo: hay métricas **deterministas por construcción** —las
del modelo, con semilla fija y datos pinneados— y métricas **de desempeño o de
inferencia local**, que dependen de la máquina. Las primeras se publican como
valor; las segundas, como rango con el número de equipos donde se midieron.
Promediarlas daría una cifra más presentable y menos cierta.

**Y una tercera cosa, que salió de leer su salida con cuidado:** `run test` con
solo el extra `dev` marcó **12 tests como saltados** —los de paridad de serving,
que necesitan `onnx` y `serve`—. No es un defecto, es el diseño; pero la guía
vendía el nivel 1 como "verifica el proyecto entero sin descargar nada". Con la
suite de hoy son **117 de 131**: se saltan los 13 de paridad de serving más uno
del export. Corregido en INSTALL.md, con el comando para correrlos todos.

### Lo que esto dice del proyecto

Ocho de los diez viven en la capa que nadie audita: instrucciones, scripts de
arranque, hooks, permisos de archivo, políticas de ejecución, dependencias
opcionales, advertencias de consola. El modelo tiene 8 gates, 131 tests y un
reporte de validación; la instalación tenía un README que no se podía copiar y
pegar, un entry point que no arrancaba, una garantía de autoría sostenida por dos
ajustes locales de una sola máquina, una tubería que declaraba `APROBADO` sin
haber entrenado, y una API cuya primera respuesta a un navegador era un 404.

**Tres fallaban en silencio o en verde** —el hook sin `grep`, `lint` con `;`,
`all` tras un `train` roto—. Ese es el patrón que el proyecto persigue en los
modelos desde la semana 1 y que no se estaba aplicando a su propio tooling: *el
defecto no está en lo que mide, está en lo que da por medido.*

Y los dos últimos son de otra clase, más incómoda: **números que medí una vez y
publiqué como si fueran propiedades del sistema.** El 29.1x del benchmark y el
0.83 de consistencia del LLM. Ninguno era falso; los dos eran una medición de un
equipo presentada sin decirlo. Un revisor que corriera el repo y viera 14.3x
tendría razón en desconfiar de todo lo demás.

Y cuatro —los extras de CI en la semana 7, el `grep` ausente del PATH, la
ExecutionPolicy, el `torch` que yo tenía instalado— tienen exactamente la misma
forma: mi entorno tenía algo configurado que el entorno de destino no tiene.
Ninguno se cae leyendo el código. **Todos se caen ejecutando en la máquina del
otro**, que es literalmente lo que este proyecto le exige a sus modelos:
validación out-of-time, nunca split aleatorio.

Lo que cambió como método, y es lo que me llevo: ahora **reproduzco el entorno de
destino en vez de asumirlo**. Un proceso hijo con `-ExecutionPolicy Restricted`,
un `uv` falso que siempre falla, un finder que niega `torch`. Los tres arreglos
que antes "verifiqué" mirando mi propia terminal ahora tienen un test que corre
donde el defecto existía.

_(escribir: por qué la documentación de instalación es un test de integración del
proyecto y no una tarea de redacción)_
