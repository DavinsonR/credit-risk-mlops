# ADR 0004 — LightGBM es el modelo de producción, aunque la red gane

**Fecha:** 2026-09-09
**Estado:** Aceptada

## Contexto

Tres modelos sobre el mismo split out-of-time (train FY2011-2015 / valid FY2016 /
test FY2017-2018):

| Modelo | AUC test | Gini | KS | Brier | ECE crudo | ratio crudo | seg. |
|---|---|---|---|---|---|---|---|
| red neuronal (MLP) | **0.7054** | 0.4108 | 0.3107 | 0.2855 | 0.4372 | **5.5553** | 61.2 |
| LightGBM | 0.7005 | 0.4009 | 0.2883 | 0.0831 | 0.0161 | 0.8702 | **3.5** |
| scorecard WoE | 0.6694 | 0.3388 | 0.2453 | 0.0847 | 0.0190 | 0.8166 | 2.4 |

## La diferencia es real, no ruido

Mi primera reacción fue que +0.0049 de AUC era ruido. **El bootstrap pareado me
contradijo** (2000 réplicas, mismos índices para ambos modelos porque las
predicciones están correlacionadas):

| Comparación | diff | IC95 | p |
|---|---|---|---|
| red vs LightGBM | +0.0049 | [+0.0024, +0.0078] | <0.0001 |
| LightGBM vs scorecard | +0.0311 | [+0.0274, +0.0350] | <0.0001 |
| red vs scorecard | +0.0360 | [+0.0315, +0.0406] | <0.0001 |

Con n=89,313 hasta diferencias diminutas alcanzan significancia. **Significativo
no es lo mismo que relevante**, y confundirlos es un error clásico.

## Decisión

**LightGBM va a producción.** La red gana 0.0049 de AUC — 0.7% relativo — y a cambio:

| | LightGBM | red neuronal |
|---|---|---|
| entrenamiento | 3.5 s | 61.2 s (**17x**) |
| calibración cruda | ratio 0.87 | ratio **5.56** |
| explicabilidad | SHAP sobre árboles, exacto | atribución aproximada |
| export a ONNX | directo | requiere trazado |
| superficie de fallo | determinista | semilla, épocas, batch |

El `ratio 5.56` de la red merece atención: predecía **5.5 veces** la tasa real de
incumplimiento. Es consecuencia del `pos_weight` que compensa el desbalance, y se
corrige con recalibración — pero un modelo que sale de fábrica tan descalibrado
exige un paso extra que nunca puede fallar en producción.

## Sobre la recalibración

Los tres calibradores se ajustan sobre **validación** (nunca train, donde el modelo
ya vio los datos; nunca test, que sería fuga). El de producción se declaró **antes**
de mirar test: **ajuste de intercepto**, porque es monótono y por construcción no
puede alterar ningún ranking — el AUC queda idéntico.

| Modelo | ECE crudo | ECE con intercepto | ratio final |
|---|---|---|---|
| scorecard | 0.0190 | 0.0122 | 0.9174 |
| LightGBM | 0.0161 | 0.0107 | 0.9653 |
| red neuronal | 0.4372 | 0.0101 | 1.0186 |

Platt e isotónica dan ECE algo mejor, pero elegir el calibrador mirando test es
selección sobre el conjunto de prueba: fuga, aunque no lo parezca.

## Por qué el scorecard sigue en el repo

Pierde por 3 puntos de AUC y no va a producción, pero se mantiene como baseline
permanente: si un retador futuro no le gana, no merece desplegarse. Además es el
único de los tres cuya lógica se puede leer línea por línea ante un validador.

## Consecuencias

- La red neuronal queda documentada como experimento con resultado publicable:
  *en tabular, un GBM regularizado sigue siendo la elección correcta*.
- El paso de recalibración es obligatorio en el pipeline de producción, no opcional.
- El gate de CI `min_auc_test: 0.68` lo pasa LightGBM (0.7005) y lo falla el
  scorecard (0.6694). Correcto: el gate aplica al modelo final, no al baseline.
