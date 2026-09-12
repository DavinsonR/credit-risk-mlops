# Modelo semántico en Power BI (PBIP)

Proyecto Power BI en formato **PBIP**: texto, versionado, revisable en un diff. El
modelo semántico está en **TMDL** y el informe se arma en Power BI Desktop.

## Lo que está aquí, y lo que no

| | Estado |
|---|---|
| Modelo semántico en TMDL: 9 tablas, ~20 medidas DAX, parámetro de ruta | **Escrito y verificado por test** |
| Enlace de cada tabla a su export, columna por columna | **Verificado**: `tests/test_pbip_bindings.py` compara cada `sourceColumn` contra el encabezado real del CSV |
| Layout del informe (páginas, visuales, formato) | **No está.** Requiere Power BI Desktop |

**Declaración honesta:** este modelo **no se ha abierto en Power BI Desktop.** Se
escribió a mano porque TMDL es texto y porque el enlace a los datos sí es verificable
sin Power BI — y eso es lo que los tests comprueban. Pero que el TMDL sea válido para
los tests de este repo no garantiza que Desktop lo cargue sin ajustes.

Decir "tablero de Power BI listo" sin haberlo abierto sería exactamente el tipo de
afirmación que este proyecto documenta como defecto —ver el registro en
[NOTES.md](../NOTES.md)—. Así que: el modelo está, el informe es el paso que falta, y
lo tiene que dar alguien con Desktop instalado.

## Primer uso

1. Abrir `credit-risk-mlops.pbip` en Power BI Desktop.
2. Ajustar el parámetro **`RutaRepo`** a la ruta local del repo. Es el único valor
   que depende de la máquina.
3. Refrescar. Si un export falta, correr `run all` y `run web-exports` antes.

## Las tablas, y de dónde sale cada una

| Tabla | Fuente | Qué responde |
|---|---|---|
| `Config` | `exports/web/modelos.json` + `manifest.json` | Cuál es el modelo de producción, el baseline, y las huellas de procedencia |
| `Umbrales` | `exports/web/umbrales.json` (desde `config.yaml`) | Los umbrales de los gates |
| `Modelos` | `exports/model_comparison.csv` | Desempeño de los tres modelos, baseline incluido |
| `Decision` | `exports/decision_curve.csv` | Pérdida evitada **y volumen sano sacrificado** por tasa de rechazo |
| `EquidadRaza` | `exports/hmda_fairness_race.csv` | Aprobación y tasas reales por grupo protegido |
| `EquidadDelta` | `exports/hmda_fairness_delta.csv` | Cuánta disparidad **agrega** el modelo sobre la histórica |
| `Estres` | `exports/stress_test.csv` | El modelo fuera de su régimen |
| `ScorecardPuntos` | `exports/scorecard_points.csv` | Puntos por bin e Information Value del modelo interpretable |
| `Medidas` | — | Solo medidas DAX |

## Tres decisiones de modelado que un revisor va a mirar

**1. Ningún umbral vive en una medida DAX.** Todos se leen de `Umbrales`, que sale de
`config.yaml`. Si el tablero tuviera su propia copia podría mostrar "cumple" sobre algo
que el gate bloquea, y el tablero es lo que alguien mira en una reunión.

**2. Ningún nombre de modelo está escrito a mano.** La primera versión de
`Modelos.tmdl` tenía `IF([modelo] = "lightgbm", ...)` con un comentario que decía "no
escrita a mano" justo encima. Es el defecto A2 de [docs/AUDIT.md](../docs/AUDIT.md) en
otra capa: el tablero seguiría marcando LightGBM como producción después de que el
proyecto promoviera otro modelo. Ahora sale de `Config`.

**3. No hay relaciones entre tablas de hechos, a propósito.** Son análisis distintos
sobre poblaciones distintas — modelo A sobre SBA, modelo B sobre HMDA, estrés sobre
cohortes no entrenadas. Unirlas inventaría una relación que no existe en el dominio y
permitiría cruces sin sentido, como filtrar el disparate impact de HMDA por el corte de
decisión de SBA. Cada página es un análisis, no un cubo navegable.

## Páginas propuestas para el informe

Especificación, no implementación.

**1 · Desempeño.** Tabla `Modelos` con la marca de `Es produccion`. Tarjetas de
`AUC produccion`, `Margen sobre baseline` y `Margen cumple`. Curva de confiabilidad
desde `scorecard_reliability.csv` si se agrega la tabla.

**2 · Pérdida en dólares.** Línea doble sobre `Decision`: `loss_avoided` y
`good_volume_foregone` **en el mismo eje visual**, no en pestañas separadas. Tarjeta de
`Costo por dolar evitado` (7.2x al 10%). El corte óptimo de `optimal_cutoffs.csv` con
su bandera `at_boundary`, que es lo que evita vender un óptimo que está en el borde de
la grilla.

**3 · Equidad.** `EquidadRaza` completa —los seis grupos, no los que quedan bien— con
`Veredicto equidad` en grande. Y al lado `EquidadDelta`, que es la comparación que casi
nadie hace: el modelo **reproduce** la disparidad histórica en vez de crearla.

**4 · Estrés y monitoreo.** `Estres` con `AUC en crisis` y `Subestimacion en crisis`
(8.1x) del mismo tamaño que el AUC de producción. Un AUC citado sin régimen es un
número de un solo escenario.

**Pie de página en todas:** la medida `Procedencia`, que imprime vintage y las dos
huellas. Un validador cruza eso con `exports/metrics.json` y con el commit.

## Lo que NO debe mostrar

- **El modelo de acceso como aprobado.** No lo está: disparate impact 0.7639 contra un
  umbral de 0.80, y `promoted: false` en el artefacto.
- **La pérdida evitada sin el volumen sacrificado.** Son el mismo análisis.
- **Números que el proyecto retractó:** el benchmark de 29.3x (no replicó: 14.3x en
  otra máquina) y la consistencia de 0.83 del LLM (0.33 en otra máquina).
