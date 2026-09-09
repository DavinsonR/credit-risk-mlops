# Fuentes de datos

| Fuente | Cobertura | Licencia | Registro |
|---|---|---|---|
| [SBA 7(a) FOIA](https://data.sba.gov/dataset/7a-504-foia) | FY1991–presente, ~1.96M préstamos | Obra del Gobierno de EE.UU. / FOIA — dominio público | No |
| [HMDA Snapshot](https://ffiec.cfpb.gov/data-publication/snapshot-national-loan-level-dataset/) | ~10M solicitudes/año | Dato público federal | No |
| [FRED](https://fred.stlouisfed.org/) | Series macro | Uso libre con atribución | API key gratis |
| [Census ACS](https://www.census.gov/data/developers.html) | Demografía por tract | Dominio público | API key gratis |
| Fannie Mae SF Loan Performance | Opcional | **Prohíbe redistribución** | Sí |

## Reglas

1. **Ningún dato crudo se commitea.** `make acquire` los descarga; `.gitignore` los bloquea.
2. **Los vintages se fijan por SHA256** en `data/manifests/`. Ese manifiesto sí se commitea.
3. **Fannie Mae**: solo código, nunca datos. Requiere credenciales propias del usuario.
4. El nombre de archivo de SBA incluye el vintage (`asof_YYMMDD`) y cambia cada
   trimestre — por eso las URLs se descubren en vez de hardcodearse (ADR 0001).
