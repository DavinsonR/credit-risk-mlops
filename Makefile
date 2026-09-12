.PHONY: help setup acquire verify signal-check train economics gates card validation reproduce audit causal maturity drift drift-build retrain-check monitor hmda hmda-train disparity benchmark onnx llm-evals serve web lint test ci-local clean
.DEFAULT_GOAL := help

UV := uv

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

setup:  ## Crea el entorno (Python 3.12), instala dependencias y el hook de autoria
	$(UV) python install 3.12
	$(UV) sync --extra dev
	@# El hook vive en scripts/hooks/ porque .git/hooks NO se clona. Sin este
	@# apuntado, un clon nuevo no tiene la proteccion de autoria y el trailer
	@# solo se detectaria en CI, despues del push: tarde.
	@git rev-parse --git-dir >/dev/null 2>&1 \
		&& git config core.hooksPath scripts/hooks \
		&& echo "hook de autoria instalado (core.hooksPath=scripts/hooks)" \
		|| echo "sin repo git: hook de autoria NO instalado"

acquire:  ## Descubre y descarga las fuentes; escribe manifiesto con SHA256
	$(UV) run python -m crmlops.sources.sba

verify:  ## Revalida los datos locales contra el manifiesto commiteado
	$(UV) run python -c "from crmlops.sources import sba; raise SystemExit(0 if sba.verify() else 1)"

signal-check:  ## GATE SEMANA 1: confirma que existe poder discriminante
	$(UV) run python -m crmlops.evaluation.signal_check

train:  ## Entrena baseline + retadores; escribe exports/metrics.json
	$(UV) run python -m crmlops.models.train

economics:  ## Traduce el modelo a dolares: perdida evitada y corte optimo
	$(UV) run python -m crmlops.models.train_economics

causal:  ## Identificacion causal: se puede estimar el efecto de la garantia?
	$(UV) run python -m crmlops.causal.identification

maturity:  ## Que se puede monitorear: madurez de la etiqueta por cosecha
	$(UV) run python -m crmlops.monitoring.maturity

drift:  ## Deriva de poblacion contra el perfil de referencia commiteado
	$(UV) run python -m crmlops.monitoring.drift

drift-build:  ## Regenera exports/reference_profile.json desde el entrenamiento
	$(UV) run python -m crmlops.monitoring.drift --build

retrain-check:  ## Disparadores de reentrenamiento. NO reentrena: decide y explica
	$(UV) run python -m crmlops.monitoring.retrain

monitor: maturity drift retrain-check  ## El ciclo completo de monitoreo

gates:  ## Gates de promocion. Falla (exit 1) si el modelo no cumple
	$(UV) run python -m crmlops.governance.gates

card:  ## Regenera reports/MODEL_CARD.md desde la ultima corrida
	$(UV) run python -m crmlops.governance.model_card

validation:  ## Regenera el reporte de validacion (SR 26-2 + EU AI Act Anexo IV)
	$(UV) run python -m crmlops.governance.validation_report

hmda:  ## Descarga HMDA por estado-anio y verifica contra conteos oficiales
	$(UV) run python -m crmlops.sources.hmda

hmda-train:  ## Modelo de denegacion + auditoria de equidad
	$(UV) run python -m crmlops.models.train_hmda

disparity:  ## Disparidad observada en HMDA, antes de cualquier modelo
	$(UV) run python -m crmlops.fairness.observed

benchmark:  ## DuckDB vs PySpark sobre el mismo trabajo de features
	$(UV) run python -m crmlops.features.benchmark

onnx:  ## Exporta a ONNX; falla si el grafo no reproduce al modelo
	$(UV) run python -m crmlops.export.onnx

llm-evals:  ## Avisos de adverse action: plantilla determinista vs LLM
	$(UV) run python -m crmlops.llm.harness

serve:  ## Levanta la API de scoring en :8000
	$(UV) run uvicorn app:app --app-dir serving/api --port 8000

web:  ## Demo en el navegador (modelo en WASM) en :8899
	$(UV) run python serving/web/build.py
	$(UV) run python -m http.server 8899 --directory serving/web

reproduce:  ## Reentrena y ASSERTA que las metricas son identicas a las commiteadas
	$(UV) run python -m crmlops.governance.reproduce

audit:  ## Auditoria de contaminacion post-originacion sobre los candidatos
	$(UV) run python -m crmlops.evaluation.contamination_audit

lint:  ## ruff check + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

ci-local:  ## Corre lo que corre CI, en un clon limpio del HEAD y sin setup
	$(UV) run python scripts/ci_local.py

test:  ## pytest (excluye tests que requieren datos adquiridos)
	$(UV) run pytest -m "not data"

clean:  ## Borra artefactos locales (no borra data/raw)
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
