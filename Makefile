.PHONY: help setup acquire verify signal-check train economics gates card reproduce lint test clean
.DEFAULT_GOAL := help

UV := uv

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

setup:  ## Crea el entorno (Python 3.12) e instala dependencias
	$(UV) python install 3.12
	$(UV) sync --extra dev

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

gates:  ## Gates de promocion. Falla (exit 1) si el modelo no cumple
	$(UV) run python -m crmlops.governance.gates

card:  ## Regenera reports/MODEL_CARD.md desde la ultima corrida
	$(UV) run python -m crmlops.governance.model_card

reproduce:  ## Reentrena y ASSERTA que las metricas son identicas a las commiteadas
	$(UV) run python -m crmlops.governance.reproduce

audit:  ## Auditoria de contaminacion post-originacion sobre los candidatos
	$(UV) run python -m crmlops.evaluation.contamination_audit

lint:  ## ruff check + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

test:  ## pytest (excluye tests que requieren datos adquiridos)
	$(UV) run pytest -m "not data"

clean:  ## Borra artefactos locales (no borra data/raw)
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
