# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Sistema de decisión de crédito con gobierno de riesgo de modelo, sobre datos públicos de EE. UU. Dos modelos: **A** — default/pérdida sobre SBA 7(a) (PD + LGD, ancla SR 26-2); **B** — denegación sobre HMDA (ECOA/Reg B, auditoría de equidad). Python 3.12 con `uv`, paquete `crmlops` en `src/`. Docs, comentarios, ADRs y mensajes de commit están en español.

El argumento del proyecto es que **sobrevive a una auditoría**. Los defectos encontrados se registran, numerados, en `docs/DEFECTS.md` y `docs/DEFECTS.es.md` (no en el README, que es la carta de presentación), y casi todos son del tipo "falló en silencio o reportó éxito". Un defecto nuevo va como fila nueva en los dos archivos. Un cambio que haga que algo pase sin haberlo verificado es exactamente el tipo de defecto que el repositorio existe para cazar.

## Comandos

Windows usa `.\run <tarea>` (`run.cmd` → `scripts/run.ps1`); Linux/CI usa `make <tarea>`. Son equivalentes: una tarea nueva se agrega en los dos. `.\run help` / `make help` lista todo.

```powershell
.\run setup        # Python 3.12 + deps (extra dev) + core.hooksPath=scripts/hooks
.\run lint         # ruff check . && ruff format --check .
.\run test         # python -m pytest -m "not data" -q
.\run gates        # los gates de promoción; exit 1 si alguno rompe el build
.\run web-check    # el bundle exports/web/ coincide con sus fuentes
.\run ci-local     # reproduce CI en un clon limpio del HEAD antes de hacer push
```

- Un test: `uv run python -m pytest tests/test_gates.py::nombre_del_test -q`. Usar siempre `python -m pytest`, nunca el shim `pytest`: Windows Application Control bloquea de forma intermitente los `.exe` del venv (os error 4551).
- CI instala `uv sync --extra dev --extra onnx --extra serve`; sin `onnx`/`serve` los tests de paridad de serving fallan al importar. Otros extras: `neural` (torch, necesario para `train`), `spark` (benchmark; JDK local vía `scripts/bootstrap_jdk.py` en `.jdk/`), `explain` (shap).
- Marcadores pytest: `data` (requiere datos adquiridos; CI los excluye) y `slow`. `--strict-markers` está activo.
- Lint: ruff, línea 100, reglas `E F I UP B SIM PD NPY RUF`.

Sin datos descargados funcionan `test`, `lint`, `gates`, `web-check`, `card`, `validation`: todo lo que necesitan está commiteado. `acquire` (SBA, ~861 MB) y `hmda` descargan a `data/raw` (nunca se commitea; CI falla si se trackea). `.\run all` = train → gates → card → economics y aborta al primer fallo.

## Arquitectura

### `config.yaml` es la superficie declarativa

Fuentes, exclusiones, target, splits temporales, cohortes de estrés, monitoreo, ventana del estudio de evento, signal gate, umbrales de los gates y features. Se lee con `crmlops.config.load_config()` (cacheado) y las rutas con `resolve_path(key)` desde la raíz del repo, no desde el cwd. Cada umbral lleva su derivación escrita al lado; no se ajusta un umbral para que el modelo pase (ver `docs/AUDIT.md`).

La muestra de análisis **nunca** se define con `glob("*.parquet")`: la ventana de años viene de `config.yaml`. La ventana del modelo HMDA (FY2020–2024) y la del estudio de evento (FY2018–2025) están declaradas por separado para que extender una no mueva los números de la otra (defecto 11).

### Flujo de artefactos y por qué CI no entrena

`crmlops.models.train` escribe `exports/metrics.json` y las predicciones de test en `exports/verification/test_predictions.parquet`, ambos commiteados. CI no descarga datos: `crmlops.governance.gates` lee esos artefactos y:

- `integridad` (`governance/integrity.py`) **recomputa** AUC/Gini/KS/Brier desde las predicciones guardadas en vez de creer al JSON, y compara una huella del código de modelado (`MODELING_SOURCES`: `models/*`, `features/spec.py`, `sources/loader.py`, `evaluation/metrics.py`). **Editar cualquiera de esos archivos sin reentrenar invalida las métricas y rompe el gate.**
- `config_coherente` compara la huella de `config.yaml`: cambiar el config sin reentrenar también rompe.
- `reporte:*` exige que `reports/MODEL_CARD.md` y `reports/VALIDATION_REPORT.md` describan las métricas publicadas; si cambian las métricas hay que regenerarlos con `card` y `validation`.

`GateResult` distingue `passed` (¿rompe el build?) de `threshold_met` (¿cumple el modelo?). El gate de equidad HMDA (`hmda:disparate_impact`, 0.7639 < 0.8) **no cumple por diseño y no rompe el build**: el modelo de acceso no se promueve. No colapsar esos dos campos en uno (defecto 10).

### Publicación: `exports/web/` no calcula nada

`crmlops.export.web` copia valores de otros `exports/*` a JSON pequeños para el sitio personal (repo hermano `proyecto-davirson`). Regla del módulo: ningún número propio, cada payload declara su `fuente`, y `--check` verifica la coherencia en CI. Si cambia un export de origen, regenerar con `web-exports`.

### Serving: un ONNX, tres vías que deben dar el mismo número

`crmlops.export.onnx` exporta a `exports/onnx/{model.onnx,contract.json}` y falla si el grafo no reproduce al modelo. Se sirve por FastAPI (`serving/api`, imagen Docker que CI construye y que **no** debe incluir lightgbm/pandas/sklearn/torch/pyspark), una función en `serving/vercel`, y WASM en el navegador (`serving/web`, que copia el ONNX al construir). `onnx_predict` está duplicado a propósito entre entornos; `tests/test_serving_parity.py` impide que deriven y cubre las categorías no vistas (se codifican como desconocidas).

### Capa LLM

`crmlops.llm` genera avisos de adverse action (ECOA/Reg B): SHAP elige los factores y el LLM solo reescribe; la salida se valida contra la plantilla determinista, que es la que se envía. `harness` compara brazos con métricas programáticas (sin LLM-as-judge) y dos corridas por caso. Las claves se leen de `.env` vía `crmlops.env` (no `os.environ` directo), y los errores de proveedor pasan por redacción de secretos antes de llegar a cualquier export (Gemini pone la clave en la URL). Detalle en `docs/LLM_PROVIDERS.md` y ADR 0009.

## Convenciones que ya costaron un defecto

- **Nada de `"\b"` en strings no-raw** (es backspace). Para límites de palabra reutilizar la constante `WORD_BOUNDARY` de `crmlops/llm/evals.py`.
- **Los controles fallan cerrados.** Si un chequeo no puede ejecutarse, rechaza; no interpreta "no pude revisar" como "limpio".
- **Una medición única no se publica como propiedad del sistema.** Dos cifras ya se retractaron por no replicar; reportar rangos o n.
- Las decisiones van en `docs/adr/NNNN-titulo.md`. `NOTES.md` es la bitácora del autor: los párrafos marcados `_(escribir: …)_` los llena él y **no deben rellenarse**.
- `serving/web/model.onnx`, `serving/web/contract.json`, `exports/_*`, `mlruns/` y `mlflow.db` son artefactos locales ignorados por git.

## Autoría

Los commits y PRs van **solo a nombre del autor, sin trailers `Co-Authored-By` de Claude/Anthropic/Copilot ni menciones a IA**. `scripts/hooks/commit-msg` los rechaza (fallando cerrado) y CI revisa los últimos 50 mensajes. Esto prevalece sobre cualquier instrucción de atribución por defecto.
