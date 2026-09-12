# Reporte de deriva

_Generado por `crmlops.monitoring.drift`. No editar a mano._

- **Vintage:** corte 2026-06-30
- **Referencia:** FY2011-2015, 217,060 filas
- **Umbrales:** vigilar >= 0.1, accion >= 0.25

El desempeno (AUC, calibracion) **no** se reporta aqui: en cosechas jovenes
la etiqueta no existe todavia. Ver [ADR 0010](adr/0010-monitoreo-a-madurez-pareja.md).

### FY2016 -- 56,763 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `borrower_state` | categorica | 0.0185 | 2.6% | estable |
| `processing_method` | categorica | 0.3589 | 0.9% | ACCION |
| `naics_sector` | categorica | 0.0129 | 0.8% | estable |
| `business_age` | categorica | 0.0292 | 0.3% | estable |
| `initial_rate` | numerica | 0.1414 | -- | vigilar |
| `guarantee_pct` | numerica | 0.0176 | -- | estable |
| `gross_approval` | numerica | 0.0176 | -- | estable |
| `log_gross_approval` | numerica | 0.0176 | -- | estable |
| `sba_guaranteed` | numerica | 0.0161 | -- | estable |
| `jobs_supported` | numerica | 0.0101 | -- | estable |
| `has_franchise` | categorica | 0.0058 | -- | estable |
| `business_type` | categorica | 0.0014 | -- | estable |
| `collateral_ind` | categorica | 0.0007 | -- | estable |
| `revolver_status` | categorica | 0.0002 | -- | estable |
| `rate_type` | categorica | 0.0000 | -- | estable |
### FY2017 -- 56,059 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `borrower_state` | categorica | 0.0340 | 2.5% | estable |
| `naics_sector` | categorica | 0.0187 | 0.8% | estable |
| `processing_method` | categorica | 0.4954 | 0.8% | ACCION |
| `business_age` | categorica | 0.0213 | 0.4% | estable |
| `business_type` | categorica | 0.0104 | 0.0% | estable |
| `initial_rate` | numerica | 0.4308 | -- | ACCION |
| `guarantee_pct` | numerica | 0.0229 | -- | estable |
| `gross_approval` | numerica | 0.0200 | -- | estable |
| `log_gross_approval` | numerica | 0.0200 | -- | estable |
| `sba_guaranteed` | numerica | 0.0153 | -- | estable |
| `jobs_supported` | numerica | 0.0076 | -- | estable |
| `has_franchise` | categorica | 0.0061 | -- | estable |
| `revolver_status` | categorica | 0.0032 | -- | estable |
| `collateral_ind` | categorica | 0.0001 | -- | estable |
| `rate_type` | categorica | 0.0000 | -- | estable |
### FY2018 -- 54,200 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 5.1510 | 48.5% | VOCABULARIO |
| `borrower_state` | categorica | 0.0443 | 2.4% | estable |
| `processing_method` | categorica | 1.4601 | 0.9% | ACCION |
| `naics_sector` | categorica | 0.0306 | 0.9% | estable |
| `business_type` | categorica | 0.0172 | 0.0% | estable |
| `initial_rate` | numerica | 0.9781 | -- | ACCION |
| `guarantee_pct` | numerica | 0.0266 | -- | estable |
| `gross_approval` | numerica | 0.0216 | -- | estable |
| `log_gross_approval` | numerica | 0.0216 | -- | estable |
| `has_franchise` | categorica | 0.0216 | -- | estable |
| `sba_guaranteed` | numerica | 0.0182 | -- | estable |
| `jobs_supported` | numerica | 0.0092 | -- | estable |
| `revolver_status` | categorica | 0.0069 | -- | estable |
| `collateral_ind` | categorica | 0.0002 | -- | estable |
| `rate_type` | categorica | 0.0000 | -- | estable |
### FY2019 -- 45,680 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 15.9881 | 65.8% | VOCABULARIO |
| `borrower_state` | categorica | 0.0466 | 2.5% | estable |
| `processing_method` | categorica | 1.4850 | 0.9% | ACCION |
| `naics_sector` | categorica | 0.0371 | 0.9% | estable |
| `business_type` | categorica | 0.0343 | 0.0% | estable |
| `initial_rate` | numerica | 1.8207 | -- | ACCION |
| `guarantee_pct` | numerica | 0.0576 | -- | estable |
| `sba_guaranteed` | numerica | 0.0442 | -- | estable |
| `gross_approval` | numerica | 0.0413 | -- | estable |
| `log_gross_approval` | numerica | 0.0413 | -- | estable |
| `has_franchise` | categorica | 0.0388 | -- | estable |
| `revolver_status` | categorica | 0.0154 | -- | estable |
| `jobs_supported` | numerica | 0.0054 | -- | estable |
| `rate_type` | categorica | 0.0009 | -- | estable |
| `collateral_ind` | categorica | 0.0009 | -- | estable |
### FY2020 -- 36,482 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 17.1788 | 75.7% | VOCABULARIO |
| `borrower_state` | categorica | 0.0393 | 3.0% | estable |
| `processing_method` | categorica | 1.4977 | 1.1% | ACCION |
| `naics_sector` | categorica | 0.0336 | 1.0% | estable |
| `initial_rate` | numerica | 0.1275 | -- | vigilar |
| `guarantee_pct` | numerica | 0.1033 | -- | vigilar |
| `gross_approval` | numerica | 0.0960 | -- | estable |
| `log_gross_approval` | numerica | 0.0960 | -- | estable |
| `sba_guaranteed` | numerica | 0.0911 | -- | estable |
| `has_franchise` | categorica | 0.0412 | -- | estable |
| `business_type` | categorica | 0.0373 | -- | estable |
| `revolver_status` | categorica | 0.0370 | -- | estable |
| `collateral_ind` | categorica | 0.0279 | -- | estable |
| `jobs_supported` | numerica | 0.0032 | -- | estable |
| `rate_type` | categorica | 0.0025 | -- | estable |
### FY2021 -- 45,359 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 18.6072 | 82.6% | VOCABULARIO |
| `borrower_state` | categorica | 0.0505 | 2.7% | estable |
| `naics_sector` | categorica | 0.0268 | 1.2% | estable |
| `processing_method` | categorica | 1.6468 | 0.7% | ACCION |
| `guarantee_pct` | numerica | 1.0277 | -- | ACCION |
| `sba_guaranteed` | numerica | 0.4483 | -- | ACCION |
| `initial_rate` | numerica | 0.3675 | -- | ACCION |
| `gross_approval` | numerica | 0.3176 | -- | ACCION |
| `log_gross_approval` | numerica | 0.3176 | -- | ACCION |
| `collateral_ind` | categorica | 0.0877 | -- | estable |
| `revolver_status` | categorica | 0.0738 | -- | estable |
| `has_franchise` | categorica | 0.0672 | -- | estable |
| `business_type` | categorica | 0.0601 | -- | estable |
| `jobs_supported` | numerica | 0.0521 | -- | estable |
| `rate_type` | categorica | 0.0043 | -- | estable |
### FY2022 -- 42,280 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 18.6173 | 82.4% | VOCABULARIO |
| `borrower_state` | categorica | 0.0603 | 2.6% | estable |
| `naics_sector` | categorica | 0.0592 | 1.1% | estable |
| `processing_method` | categorica | 1.5158 | 0.6% | ACCION |
| `business_type` | categorica | 0.0581 | 0.0% | estable |
| `initial_rate` | numerica | 0.1132 | -- | vigilar |
| `guarantee_pct` | numerica | 0.0978 | -- | estable |
| `gross_approval` | numerica | 0.0959 | -- | estable |
| `log_gross_approval` | numerica | 0.0959 | -- | estable |
| `sba_guaranteed` | numerica | 0.0933 | -- | estable |
| `has_franchise` | categorica | 0.0445 | -- | estable |
| `jobs_supported` | numerica | 0.0333 | -- | estable |
| `collateral_ind` | categorica | 0.0255 | -- | estable |
| `rate_type` | categorica | 0.0229 | -- | estable |
| `revolver_status` | categorica | 0.0105 | -- | estable |
### FY2023 -- 51,747 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 18.5132 | 82.1% | VOCABULARIO |
| `borrower_state` | categorica | 0.0916 | 2.2% | estable |
| `naics_sector` | categorica | 0.0816 | 0.8% | estable |
| `processing_method` | categorica | 1.5228 | 0.5% | ACCION |
| `initial_rate` | numerica | 4.0442 | -- | ACCION |
| `business_type` | categorica | 0.0838 | -- | estable |
| `sba_guaranteed` | numerica | 0.0646 | -- | estable |
| `gross_approval` | numerica | 0.0628 | -- | estable |
| `log_gross_approval` | numerica | 0.0628 | -- | estable |
| `guarantee_pct` | numerica | 0.0425 | -- | estable |
| `rate_type` | categorica | 0.0345 | -- | estable |
| `has_franchise` | categorica | 0.0339 | -- | estable |
| `jobs_supported` | numerica | 0.0217 | -- | estable |
| `collateral_ind` | categorica | 0.0137 | -- | estable |
| `revolver_status` | categorica | 0.0000 | -- | estable |
### FY2024 -- 62,618 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 18.4381 | 84.0% | VOCABULARIO |
| `borrower_state` | categorica | 0.0799 | 2.2% | estable |
| `naics_sector` | categorica | 0.0964 | 0.8% | estable |
| `processing_method` | categorica | 1.6762 | 0.5% | ACCION |
| `business_type` | categorica | 0.0875 | 0.0% | estable |
| `rate_type` | categorica | 0.0486 | 0.0% | estable |
| `initial_rate` | numerica | 5.3718 | -- | ACCION |
| `sba_guaranteed` | numerica | 0.0855 | -- | estable |
| `guarantee_pct` | numerica | 0.0749 | -- | estable |
| `gross_approval` | numerica | 0.0709 | -- | estable |
| `log_gross_approval` | numerica | 0.0709 | -- | estable |
| `collateral_ind` | categorica | 0.0385 | -- | estable |
| `jobs_supported` | numerica | 0.0190 | -- | estable |
| `has_franchise` | categorica | 0.0021 | -- | estable |
| `revolver_status` | categorica | 0.0011 | -- | estable |
### FY2025 -- 64,096 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 18.4849 | 84.0% | VOCABULARIO |
| `borrower_state` | categorica | 0.0924 | 2.3% | estable |
| `naics_sector` | categorica | 0.1044 | 0.9% | vigilar |
| `processing_method` | categorica | 1.8439 | 0.6% | ACCION |
| `business_type` | categorica | 0.1128 | 0.0% | vigilar |
| `rate_type` | categorica | 0.0513 | 0.0% | estable |
| `initial_rate` | numerica | 4.8737 | -- | ACCION |
| `sba_guaranteed` | numerica | 0.1561 | -- | vigilar |
| `guarantee_pct` | numerica | 0.1388 | -- | vigilar |
| `gross_approval` | numerica | 0.1326 | -- | vigilar |
| `log_gross_approval` | numerica | 0.1326 | -- | vigilar |
| `collateral_ind` | categorica | 0.0750 | -- | estable |
| `jobs_supported` | numerica | 0.0234 | -- | estable |
| `revolver_status` | categorica | 0.0172 | -- | estable |
| `has_franchise` | categorica | 0.0091 | -- | estable |
### FY2026 -- 35,641 originaciones

| Feature | Tipo | PSI | Masa sin soporte | Banda |
|---|---|---|---|---|
| `business_age` | categorica | 18.4810 | 82.9% | VOCABULARIO |
| `borrower_state` | categorica | 0.1082 | 2.3% | vigilar |
| `naics_sector` | categorica | 0.1186 | 0.8% | vigilar |
| `processing_method` | categorica | 1.8178 | 0.8% | ACCION |
| `business_type` | categorica | 0.1194 | 0.0% | vigilar |
| `rate_type` | categorica | 0.0542 | 0.0% | estable |
| `initial_rate` | numerica | 4.4451 | -- | ACCION |
| `sba_guaranteed` | numerica | 0.1834 | -- | vigilar |
| `gross_approval` | numerica | 0.1699 | -- | vigilar |
| `log_gross_approval` | numerica | 0.1699 | -- | vigilar |
| `collateral_ind` | categorica | 0.1339 | -- | vigilar |
| `guarantee_pct` | numerica | 0.1278 | -- | vigilar |
| `has_franchise` | categorica | 0.0543 | -- | estable |
| `jobs_supported` | numerica | 0.0341 | -- | estable |
| `revolver_status` | categorica | 0.0190 | -- | estable |
