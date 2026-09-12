# Reporte de Validación de Modelos

> Generado por `crmlops.governance.validation_report` el 2026-09-12 05:12 UTC.
> **No editar a mano**: se regenera en cada corrida.
>
> Vintage de datos `260630` · configuración `969867602d1192cc` ·
> código `7feae6905ddae543`
>
> Los tres identificadores salen de `exports/metrics.json`: son la procedencia de
> los números que este reporte describe. La versión anterior calculaba el de código
> **en vivo**, así que el reporte declaraba el código del momento en que se generó
> y no el que produjo las métricas — y al primer cambio en el modelado los dos
> dejaban de coincidir sin que nada avisara. El gate `reportes_al_dia` ahora lo
> verifica.

Estructura según **SR 11-7** (Federal Reserve, *Guidance on Model Risk
Management*). El mapeo al **Anexo IV del Reglamento de IA de la UE** está en la
sección 4: la evaluación de solvencia crediticia figura como sistema de alto
riesgo en el Anexo III, punto 5.b.

## Modelos en alcance

| Modelo | Fuente | Objetivo | Algoritmo | Estado |
|---|---|---|---|---|
| **A — Riesgo de crédito** | SBA 7(a) FOIA | Charge-off (PD) | lightgbm | **Producción** |
| **B — Suscripción** | HMDA | Denegación | hmda_lightgbm | **Bloqueado por equidad** |

---

## 1. Solidez conceptual

### 1.1 Diseño del conjunto de validación

Split **out-of-time**, nunca aleatorio. El riesgo de crédito tiene deriva temporal
y un split aleatorio la esconde.

| Modelo | Entrenamiento | Validación | Prueba | n prueba |
|---|---|---|---|---|
| A (SBA) | FY2011-2015 | FY2016 | FY2017-2018 | 89,313 |
| B (HMDA) | FY2020-2022 | FY2023 | FY2024 | 1,941,270 |

Las ventanas se eligieron por dos criterios **medidos**, no por intuición
(ADR 0003): régimen homogéneo —la tasa base del 7(a) fue 32-37% en 2006-2008 y
6-7% en 2012-2015— y censura acotada, admitiendo solo cosechas con ≥70% de
préstamos resueltos.

### 1.2 Control de fuga de información

Se identificaron y excluyeron **tres clases distintas** de variable contaminada:

| Clase | Ejemplo | Evidencia | Referencia |
|---|---|---|---|
| Resultado codificado en el campo | `TermInMonths` (SBA), `interest_rate` (HMDA) | 84.8% de los charge-off tienen plazo no-redondo vs 9.4% de los cancelados; `interest_rate` está nulo en 99.4% de las denegadas | ADR 0002, 0006 |
| Decisión del propio prestamista | `aus-1..5` (HMDA) | Predecir una decisión desde el motor que la tomó: el modelo imitaría sus sesgos | ADR 0006 |
| Proxy de característica protegida | `tract_minority_population_percent` | Composición racial del vecindario: usarla como feature es redlining | ADR 0006 |

### 1.3 Modelo de referencia

El baseline permanente es un **scorecard WoE + regresión logística**, interpretable
y aceptado sin discusión por un validador. Un retador que no lo supere por un
margen material no se despliega: el gate `margen_sobre_baseline` lo hace
obligatorio, y es relativo, así que no se puede acomodar eligiendo la cifra.

---

## 2. Análisis de resultados

### 2.1 Discriminación y calibración — Modelo A (producción)

| Métrica | Valor |
|---|---|
| AUC (out-of-time) | 0.7005 |
| Gini | 0.4009 |
| KS | 0.2883 |
| Brier | 0.0828 |
| ECE | 0.0107 |
| Razón de calibración | 0.9653 |
| Degradación AUC train→test | +0.0299 |

El calibrador se ajusta sobre **validación** —nunca train, que el modelo ya vio;
nunca test, que sería fuga— y el método se declara **antes** de mirar test.

### 2.2 Traducción a decisiones

| Concepto | Valor |
|---|---|
| Monto prestado en la ventana de prueba | $33.0B |
| Pérdida realizada | $1.29B (3.91% del monto) |
| Absorbida por la SBA (garantía) | $942.1M |
| Absorbida por el banco | $345.8M |
| Pérdida evitada rechazando el 10% más riesgoso | $276.3M |
| Lift sobre rechazo aleatorio | 2.15x |
| Margen de equilibrio bruto | 3.91% |

**Supuesto declarado.** El contrafactual se calcula sobre préstamos que **sí fueron
aprobados**, y supone que rechazar no altera el comportamiento del resto del
mercado. Sirve para dimensionar; para política de crédito real haría falta un
experimento.

### 2.3 Equidad — Modelo B

| Métrica | Valor |
|---|---|
| AUC | 0.8847 |
| Disparate impact ratio (mínimo) | **0.764** |
| Peor grupo | Native Hawaiian or Other Pacific Islander |
| Umbral (regla de 4/5, EEOC) | 0.8 |
| Promovido a producción | **No** |

**La pregunta no es si el modelo es justo, sino cuánta disparidad AGREGA** sobre la
que ya existe en las decisiones históricas:

| Dimensión | Delta vs observado |
|---|---|
| RAZA | -0.002 |
| ETNIA | +0.008 |
| SEXO | +0.031 |

Un delta cercano a cero significa que el modelo **reproduce** la disparidad
existente en vez de crearla. Eso no lo exculpa —automatizar una disparidad la
escala y le da apariencia de objetividad— pero cambia dónde debe intervenirse.

**Sesgo de selección declarado (ADR 0007).** Los filtros del panel eliminan 5.1%
de los solicitantes nativos hawaianos y 4.8% de los negros, contra 3.1% de los
blancos. En la comparación estándar de fair lending eso mueve la razón de 4/5 de
0.802 (población completa) a 0.795 (panel filtrado): **una decisión técnica de
limpieza cruza el umbral legal.** Toda cifra de equidad de este reporte lleva
adjunta la población sobre la que se calculó.

**Limitación material.** HMDA no incluye puntaje de crédito, el determinante más
fuerte de una decisión de suscripción. Estas cifras muestran diferencias que
exigen explicación; no prueban discriminación.

---

## 3. Monitoreo continuo

### 3.1 Gates de promoción

| Gate | Valor | Umbral | Resultado |
|---|---|---|---|
| `config_coherente` | n/a | ≥ 0 | PASA |
| `integridad` | n/a | ≥ 0 | PASA |
| `auc_test` | 0.7005 | ≥ 0.6894 | PASA |
| `drop_oot` | 0.0299 | ≤ 0.08 | PASA |
| `brier_test` | 0.0828 | ≤ 0.0868 | PASA |
| `ece_test` | 0.0107 | ≤ 0.02 | PASA |
| `margen_sobre_baseline` | 0.0311 | ≥ 0.02 | PASA |
| `hmda:disparate_impact` | 0.7639 | ≥ 0.8 | NO CUMPLE (build ok: no se promueve) |

Cada umbral tiene su derivación escrita en `config.yaml`. Ninguno se eligió porque
el modelo lo pasara: el de Brier, por ejemplo, sale del predictor sin habilidad
—constante igual a la tasa base— cuyo Brier es p(1-p) = 0.0868.

### 3.2 Integridad del artefacto

Las métricas **se recomputan** desde las predicciones guardadas; no se leen del
archivo publicado. Editar `exports/metrics.json` a mano no altera el veredicto.
Se verifica además que el código de modelado no haya cambiado desde el
entrenamiento.

### 3.3 Estabilidad poblacional

El PSI se **descompone** en corrimiento de nivel y cambio de forma, porque exigen
respuestas distintas: el nivel se corrige recalibrando, la forma obliga a evaluar
reentrenamiento.

| Modelo | PSI total | PSI de forma |
|---|---|---|
| A (SBA) | ver metrics.json | — |
| B (HMDA) | 0.1165 | 0.2099 |

### 3.4 Pruebas de estrés

El modelo A se aplica, **sin reentrenar**, a cohortes fuera de su régimen. En un
escenario tipo 2007 (tasa base 31.19%) el AUC cae a 0.5456 —apenas mejor que el
azar— y la razón de calibración baja a 0.12: **subestima el riesgo por un factor
de ocho.** Ver `exports/stress_test.csv`.

---

## 4. Mapeo al Anexo IV del Reglamento de IA de la UE

La evaluación de solvencia crediticia es sistema de **alto riesgo** (Anexo III,
punto 5.b) y exige documentación técnica.

| Requisito del Anexo IV | Dónde | Estado |
|---|---|---|
| 1. Descripción general del sistema | `reports/MODEL_CARD.md` §1-2 | Cubierto |
| 2. Elementos del sistema y proceso de desarrollo | §1 de este reporte; `docs/adr/` | Cubierto |
| 2.b Especificaciones de diseño y supuestos | ADR 0003-0007 | Cubierto |
| 2.d Datos de entrenamiento: procedencia y preparación | `docs/DATA_SOURCES.md`, `data/manifests/` | Cubierto |
| 2.e Evaluación de sesgo y medidas adoptadas | §2.3; ADR 0006, 0007 | Cubierto |
| 2.g Métricas de exactitud y robustez | §2.1, §3.4 | Cubierto |
| 3. Vigilancia y control humano | El modelo es entrada a una decisión humana, no una decisión automática | Declarado |
| 4. Especificaciones de exactitud, robustez y ciberseguridad | §3.1 gates; §3.2 integridad | Cubierto |
| 5. Sistema de gestión de riesgos | §3 completa | Cubierto |
| 6. Cambios a lo largo del ciclo de vida | Historial de git; fingerprints de configuración y código | Cubierto |
| 8. Registro automático de eventos (logs) | MLflow; artefactos versionados en `exports/` | Parcial |

**Declaración honesta de alcance.** Este mapeo documenta un ejercicio técnico; no
constituye una evaluación de conformidad. Un despliegue real requiere evaluación
por un organismo notificado, sistema de gestión de calidad conforme al Artículo 17
y registro en la base de datos de la UE.

---

## 5. Conclusión de la validación

| Modelo | Dictamen | Fundamento |
|---|---|---|
| Modelo A (SBA) | **Apto para producción** | Pasa los gates de desempeño, calibración e integridad |
| Modelo B (HMDA) | **No apto — promoción bloqueada** | Disparate impact ratio 0.764 < 0.8 |

Que el modelo B esté bloqueado **no es un fallo del proceso: es el proceso
funcionando.** Se midió, se documentó y no se despliega.
