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

### Pendiente para Semana 2
- Auditar `InitialInterestRate`, `SBAGuaranteedApproval` y `JobsSupported` con el mismo
  método CANCLD-vs-CHGOFF: cualquier campo que se actualice durante la vida del
  préstamo es sospechoso.
- Baseline scorecard WoE + logística.
- NAICS a 4 dígitos, identidad del banco, overlay macro de FRED.
