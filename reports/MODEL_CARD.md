# Model Card - lightgbm

> Generado automaticamente por `crmlops.governance.model_card` el 2026-09-09 17:04 UTC.
> **No editar a mano**: se regenera en cada entrenamiento.

## 1. Detalles del modelo

| | |
|---|---|
| Nombre | `lightgbm` |
| Tarea | Probabilidad de charge-off (PD) en prestamos SBA 7(a) |
| Tipo | Gradient boosting (LightGBM) con recalibracion de intercepto |
| Calibrador de produccion | `intercept` |
| Semilla | 42 |
| Vintage de datos | `260630` |
| Huella de configuracion | `969867602d1192cc` |
| Version del codigo | `7ff9a077dd5a` |

## 2. Uso previsto

**Para que sirve.** Ordenar solicitudes 7(a) por riesgo de incumplimiento y
estimar la perdida esperada de una cartera. El beneficiario principal no es el
banco sino la SBA, que absorbe alrededor del 73% de las perdidas via garantia.

**Para que NO sirve.**

- No es una decision automatica de credito. Es una entrada a una decision humana.
- No estima riesgo de un negocio fuera de la distribucion de entrenamiento
  (FY2011-2015, regimen post-crisis).
- No esta validado sobre cosechas de emergencia (PPP, COVID).

## 3. Datos

| Particion | Anios fiscales | N | Tasa base |
|---|---|---|---|
| Entrenamiento | FY2011-2015 | 217,060 | 6.75% |
| Validacion | FY2016-2016 | 51,423 | 7.89% |
| Prueba | FY2017-2018 | 89,313 | 9.60% |

**Split out-of-time, nunca aleatorio.** El riesgo de credito tiene deriva
temporal y un split aleatorio la esconde.

**Criterios de inclusion de cosechas** (ver `docs/adr/0003`):

1. *Regimen homogeneo* - la tasa base del 7(a) fue 32-37% en 2006-2008 y 6-7% en
   2012-2015. Entrenar cruzando la crisis cuesta ~2 puntos de AUC.
2. *Censura acotada* - solo cosechas con >=70% de prestamos resueltos. Un
   prestamo vigente no es "no incumplio", es censura a la derecha.

**Exclusiones aplicadas:** `drop_ppp`, `require_positive_amount`, `require_positive_term`, solo estados resueltos (P I F, CHGOFF)

## 4. Variables

**Solo informacion disponible al momento de aprobar.** Cualquier campo posterior
a la decision es fuga, aunque sea anterior al resultado.

- Numericas: `gross_approval`, `sba_guaranteed`, `initial_rate`, `jobs_supported`, `guarantee_pct`, `log_gross_approval`
- Categoricas: `naics_sector`, `business_type`, `business_age`, `revolver_status`, `collateral_ind`, `rate_type`, `processing_method`, `borrower_state`, `has_franchise`

**Excluida por contaminacion:** `TermInMonths` se sobrescribe cuando el prestamo
se liquida - 84.8% de los charge-off tienen plazo no-redondo contra 9.4% de los
cancelados, que nunca se desembolsaron. Daba un AUC falso de 0.946.
Ver `docs/adr/0002`.

## 5. Desempeno

| Modelo | auc test | gini test | ks test | brier test | ece test | drop oot | psi |
|---|---|---|---|---|---|---|---|
| `neural_mlp` | 0.7054 | 0.4108 | 0.3107 | 0.2855 | 0.4372 | 0.0021 | 0.2033 |
| `lightgbm` **(produccion)** | 0.7005 | 0.4009 | 0.2883 | 0.0831 | 0.0161 | 0.0299 | 0.1746 |
| `scorecard_woe` | 0.6694 | 0.3388 | 0.2453 | 0.0847 | 0.0190 | -0.0163 | 0.1323 |

**Calibracion.** El calibrador se ajusta sobre validacion (nunca train, que el
modelo ya vio; nunca test, que seria fuga) y el metodo se declara antes de mirar
test. Se usa ajuste de intercepto: monotono, no puede alterar el ranking.

## 6. Gates de promocion

| Gate | Valor | Umbral | Resultado |
|---|---|---|---|
| `config_coherente` | n/a | >= 0 | PASA |
| `integridad` | n/a | >= 0 | PASA |
| `auc_test` | 0.7005 | >= 0.6894 | PASA |
| `drop_oot` | 0.0299 | <= 0.08 | PASA |
| `brier_test` | 0.0828 | <= 0.0868 | PASA |
| `ece_test` | 0.0107 | <= 0.02 | PASA |
| `margen_sobre_baseline` | 0.0311 | >= 0.02 | PASA |

Un modelo que no pasa estos gates no se promueve. El gate de coherencia verifica
que estas metricas correspondan al `config.yaml` actual, para que nadie cambie el
split sin reentrenar.

## 7. Limitaciones conocidas

- **Reject inference.** Solo se observan resultados de prestamos aprobados. La
  poblacion rechazada no esta representada, asi que el modelo describe el riesgo
  *condicionado a haber sido aprobado*.
- **Deriva de calibracion con el ciclo.** El ranking aguanta pero el nivel
  deriva: con la tasa base subiendo de 6.75% a 9.60%, el
  modelo sin recalibrar sub-predice. Exige recalibracion periodica.
- **Contrafactual sin experimento.** La perdida evitada se calcula sobre
  prestamos que si fueron aprobados, y supone que rechazar no altera el
  comportamiento del resto del mercado.
- **Censura residual.** Incluso con el criterio de >=70%, entre 25% y 30% de las
  cosechas de prueba sigue sin resolver.

## 8. Consideraciones eticas

Este modelo decide sobre acceso a credito para pequenas empresas. El extracto
FOIA de SBA **no incluye clases protegidas**, asi que no se puede auditar sesgo
directamente sobre estos datos. El analisis de equidad se hace sobre HMDA, que si
trae raza, etnia, sexo y edad.

`borrower_state` y `naics_sector` son proxies geograficos y sectoriales que
pueden correlacionar con caracteristicas protegidas. Su uso queda declarado, no
oculto.

## 9. Trazabilidad

Todos los numeros provienen de `exports/metrics.json`, producido por `make train`
sobre el vintage `260630`. Reproducible con `make reproduce`.
