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
