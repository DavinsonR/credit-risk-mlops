# ADR 0001 — Descubrir las URLs de SBA en vez de hardcodearlas

**Fecha:** 2026-09-08
**Estado:** Aceptada

## Contexto

Al arrancar el proyecto, las URLs de SBA que aparecían documentadas en fuentes
secundarias devolvían **404**:

```
https://data.sba.gov/dataset/0ff8e8e9-.../download/foia-7a-fy2020-present-as-of-251231.csv
-> HTTP 404
```

Investigando, el portal `data.sba.gov` fue reestructurado. Los archivos reales viven en:

```
https://data.sba.gov/sites/default/files/uploaded_resources/FOIA_7a_FY2010_FY2019_asof_260630.csv
```

El slug del dataset también cambió: `7-a-504-foia` (404) → `7a-504-foia` (200).

Y lo más importante: **el nombre del archivo incluye un sufijo de vintage**
(`asof_260630` = 30 de junio de 2026) que **cambia cada trimestre**, porque SBA
republica el corte FOIA trimestralmente.

## Decisión

`make acquire` **descubre** las URLs scrapeando la página del dataset y filtrando
por expresión regular (`FOIA_7a_FY.*\.csv$`), en vez de leer una lista fija.

El vintage descubierto se registra en `data/manifests/sba_7a.json` junto con el
SHA256 de cada archivo. **Ese manifiesto sí se commitea**; los CSV no.

## Consecuencias

**A favor:**
- El pipeline sobrevive los renombrados trimestrales sin intervención — requisito
  de autonomía del proyecto.
- El manifiesto convierte un dataset móvil en uno **reproducible**: cualquiera puede
  verificar que corrió sobre exactamente los mismos bytes vía `make verify`.
- Un cambio de vintage se vuelve visible como un diff en el manifiesto, no como un
  cambio silencioso de resultados.

**En contra:**
- Si SBA rediseña la página, el scraping se rompe. Mitigación: `discover()` lanza un
  error explícito que apunta a este ADR en vez de devolver una lista vacía en silencio.
- Los resultados publicados quedan atados a un vintage concreto. Es intencional: es
  la diferencia entre "el modelo da 0.72" y "el modelo da 0.72 sobre el corte 260630".
