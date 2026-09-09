# Equivalente al Makefile para Windows sin `make`.
#
# El Makefile sigue siendo la referencia (CI corre en Linux), pero el README pedía
# `make setup` en una máquina donde `make` no existe: instrucciones que no se
# pueden ejecutar (docs/AUDIT.md, defecto 8).
#
#   .\run.ps1 setup
#   .\run.ps1 train
#   .\run.ps1 help

param([Parameter(Position = 0)][string]$Task = "help")

$ErrorActionPreference = "Stop"

$Tasks = [ordered]@{
    "setup"        = @{ desc = "Crea el entorno (Python 3.12) e instala dependencias"; cmd = { uv python install 3.12; uv sync --extra dev } }
    "setup-neural" = @{ desc = "Igual que setup, mas PyTorch (~200 MB)"; cmd = { uv sync --extra dev --extra neural } }
    "acquire"      = @{ desc = "Descubre y descarga las fuentes; escribe manifiesto SHA256"; cmd = { uv run python -m crmlops.sources.sba } }
    "verify"       = @{ desc = "Revalida los datos locales contra el manifiesto"; cmd = { uv run python -c "from crmlops.sources import sba; raise SystemExit(0 if sba.verify() else 1)" } }
    "signal-check" = @{ desc = "Gate de viabilidad: confirma poder discriminante"; cmd = { uv run python -m crmlops.evaluation.signal_check } }
    "audit"        = @{ desc = "Auditoria de contaminacion post-originacion"; cmd = { uv run python -m crmlops.evaluation.contamination_audit } }
    "train"        = @{ desc = "Entrena baseline + retadores; escribe exports/metrics.json"; cmd = { uv run python -m crmlops.models.train } }
    "economics"    = @{ desc = "Traduce el modelo a dolares: perdida evitada y corte"; cmd = { uv run python -m crmlops.models.train_economics } }
    "stress"       = @{ desc = "Aplica el modelo a cohortes fuera de su regimen"; cmd = { uv run python -m crmlops.evaluation.stress } }
    "gates"        = @{ desc = "Gates de promocion. Falla si el modelo no cumple"; cmd = { uv run python -m crmlops.governance.gates } }
    "card"         = @{ desc = "Regenera reports/MODEL_CARD.md"; cmd = { uv run python -m crmlops.governance.model_card } }
    "reproduce"    = @{ desc = "Reentrena y ASSERTA metricas identicas a las commiteadas"; cmd = { uv run python -m crmlops.governance.reproduce } }
    "lint"         = @{ desc = "ruff check + format check"; cmd = { uv run ruff check .; uv run ruff format --check . } }
    "test"         = @{ desc = "pytest"; cmd = { uv run pytest -m "not data" -q } }
    "all"          = @{ desc = "train -> gates -> card -> economics"; cmd = {
            uv run python -m crmlops.models.train
            uv run python -m crmlops.governance.gates
            uv run python -m crmlops.governance.model_card
            uv run python -m crmlops.models.train_economics
        }
    }
}

if ($Task -eq "help" -or -not $Tasks.Contains($Task)) {
    if ($Task -ne "help") { Write-Host "Tarea desconocida: $Task`n" -ForegroundColor Red }
    Write-Host "Uso: .\run.ps1 <tarea>`n"
    foreach ($k in $Tasks.Keys) {
        Write-Host ("  {0,-14} {1}" -f $k, $Tasks[$k].desc)
    }
    exit ($(if ($Task -eq "help") { 0 } else { 1 }))
}

# UTF-8 para que la salida con acentos no se rompa en la consola de Windows.
$env:PYTHONIOENCODING = "utf-8"
$env:MLFLOW_DISABLE_AGENT_HINT = "1"

Write-Host "==> $Task" -ForegroundColor Cyan
& $Tasks[$Task].cmd
exit $LASTEXITCODE
