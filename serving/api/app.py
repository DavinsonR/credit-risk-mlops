"""Servicio de scoring crediticio sobre ONNX.

Implementacion de REFERENCIA de las tres vias de serving. Las otras dos --funcion
serverless en Vercel y WASM en el navegador-- reimplementan el mismo contrato en
otro entorno, y los tests verifican que las tres den el mismo numero.

NO CARGA LightGBM NI PANDAS. Solo onnxruntime y numpy. Esa es la razon de exportar
a ONNX: el entorno de serving no necesita reproducir el de entrenamiento, que pesa
cientos de megabytes y arrastra su propia cadena de versiones.

EL CONTRATO ES OBLIGATORIO. El servicio no adivina como codificar una categorica:
lee `contract.json`, que fija el orden de las features y el vocabulario de cada
categorica. Si el contrato falta, el servicio no arranca -- prefiere no responder
a responder numeros sin sentido.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ARTIFACT_DIR = Path(os.environ.get("CRMLOPS_ARTIFACTS", "exports/onnx"))

# Bandas de score, convencion de la industria. Se derivan de la probabilidad
# calibrada, no de un puntaje interno, para que el corte signifique lo mismo
# aunque el modelo se reentrene.
BANDS = (
    (0.03, "A", "riesgo muy bajo"),
    (0.06, "B", "riesgo bajo"),
    (0.12, "C", "riesgo moderado"),
    (0.20, "D", "riesgo alto"),
    (1.01, "E", "riesgo muy alto"),
)


class LoanApplication(BaseModel):
    """Una solicitud 7(a). Todos los campos son de ORIGINACION."""

    gross_approval: float = Field(..., gt=0, description="Monto aprobado, USD")
    sba_guaranteed: float = Field(..., ge=0, description="Porcion garantizada por SBA, USD")
    initial_rate: float | None = Field(None, ge=0, le=50, description="Tasa inicial, %")
    jobs_supported: float | None = Field(None, ge=0)
    naics_sector: str | None = Field(None, description="2 primeros digitos del NAICS")
    business_type: str | None = None
    business_age: str | None = None
    revolver_status: str | None = None
    collateral_ind: str | None = None
    rate_type: str | None = None
    processing_method: str | None = None
    borrower_state: str | None = None
    has_franchise: int = Field(0, ge=0, le=1)

    model_config = {
        "json_schema_extra": {
            "example": {
                "gross_approval": 250000,
                "sba_guaranteed": 187500,
                "initial_rate": 8.5,
                "jobs_supported": 6,
                "naics_sector": "72",
                "business_type": "CORPORATION",
                "business_age": "Existing or more than 2 years old",
                "revolver_status": "N",
                "collateral_ind": "Y",
                "rate_type": "V",
                "processing_method": "Preferred Lenders Program",
                "borrower_state": "TX",
                "has_franchise": 0,
            }
        }
    }


class ScoreResponse(BaseModel):
    probability_of_default: float
    score_band: str
    band_label: str
    expected_loss_usd: float
    guaranteed_share: float
    expected_loss_sba_usd: float
    expected_loss_lender_usd: float
    model_version: dict[str, Any]


@lru_cache(maxsize=1)
def _artifacts() -> tuple[ort.InferenceSession, dict]:
    """Carga grafo y contrato. Falla ruidosamente si falta cualquiera."""
    graph = ARTIFACT_DIR / "model.onnx"
    contract = ARTIFACT_DIR / "contract.json"
    if not graph.exists() or not contract.exists():
        raise RuntimeError(
            f"Faltan artefactos en {ARTIFACT_DIR}. Correr: uv run python -m crmlops.export.onnx"
        )
    session = ort.InferenceSession(graph.read_bytes(), providers=["CPUExecutionProvider"])
    return session, json.loads(contract.read_text(encoding="utf-8"))


def encode(payload: dict, contract: dict) -> np.ndarray:
    """Aplica el contrato. Misma logica que crmlops.export.onnx.encode.

    Las derivadas (`guarantee_pct`, `log_gross_approval`) se calculan aqui y no se
    piden al cliente: exponerlas invitaria a que las mande inconsistentes con los
    montos, y el modelo no tendria como detectarlo.
    """
    gross = float(payload["gross_approval"])
    derived = {
        "guarantee_pct": float(payload["sba_guaranteed"]) / gross if gross else None,
        "log_gross_approval": math.log(gross) if gross > 0 else None,
    }

    row: list[float] = []
    for name in contract["numeric"]:
        v = derived.get(name, payload.get(name))
        row.append(float("nan") if v is None else float(v))

    unknown = float(contract["unknown_code"])
    for name in contract["categorical"]:
        v = payload.get(name)
        vocab = contract["categories"].get(name, [])
        if v is None:
            row.append(unknown)
            continue
        v = str(v)
        row.append(float(vocab.index(v)) if v in vocab else unknown)

    return np.array([row], dtype="float32")


def apply_calibrator(p: float, contract: dict) -> float:
    """Desplazamiento de intercepto en escala logit, monotono."""
    if contract.get("calibrator") != "intercept":
        return p
    shift = float(contract.get("calibrator_shift", 0.0))
    p = min(max(p, 1e-6), 1 - 1e-6)
    logit = math.log(p / (1 - p)) + shift
    return 1.0 / (1.0 + math.exp(-logit))


def band(pd_value: float) -> tuple[str, str]:
    for threshold, letter, label in BANDS:
        if pd_value < threshold:
            return letter, label
    return BANDS[-1][1], BANDS[-1][2]


app = FastAPI(
    title="credit-risk-mlops — scoring 7(a)",
    version="0.1.0",
    description=(
        "Probabilidad de charge-off y pérdida esperada para préstamos SBA 7(a).\n\n"
        "**No es una decisión automática de crédito.** Es una entrada a una "
        "decisión humana. El modelo se entrenó sobre FY2011-2015 y no está "
        "validado para regímenes de crisis: en un escenario tipo 2007 su AUC cae "
        "a 0.55 y subestima el riesgo por un factor de ocho. Ver "
        "`reports/VALIDATION_REPORT.md`."
    ),
)


@app.get("/")
def index() -> dict:
    """Indice del servicio.

    Existe porque abrir http://localhost:8000 en el navegador --lo primero que
    hace cualquiera-- devolvia 404 y ninguna pista de que /docs existe. Un
    servicio cuyo primer contacto es un error parece roto aunque funcione.
    """
    return {
        "service": "credit-risk-mlops",
        "endpoints": {"docs": "/docs", "health": "/health", "score": "POST /score"},
        "aviso": (
            "No es una decision automatica de credito, es una entrada a una "
            "decision humana. Ver reports/VALIDATION_REPORT.md."
        ),
    }


@app.get("/health")
def health() -> dict:
    try:
        _, contract = _artifacts()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "ok",
        "features": len(contract["feature_order"]),
        "parity_max_diff": contract["parity"]["max_abs_diff"],
    }


@app.post("/score", response_model=ScoreResponse)
def score(application: LoanApplication) -> ScoreResponse:
    # Modulo local, no crmlops: la imagen de serving no instala el paquete de
    # entrenamiento. tests/test_serving_parity.py verifica que coincidan.
    from onnx_runtime import onnx_predict

    try:
        session, contract = _artifacts()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = application.model_dump()
    X = encode(payload, contract)
    raw = float(onnx_predict(session, X)[0])
    pd_value = apply_calibrator(raw, contract)

    letter, label = band(pd_value)
    gross = payload["gross_approval"]
    # Severidad media observada en los charge-off del panel: 73.5% del monto
    # aprobado. Es un promedio, no un modelo de LGD -- se declara como tal.
    lgd = 0.735
    expected_loss = pd_value * lgd * gross
    guaranteed = payload["sba_guaranteed"] / gross if gross else 0.0

    return ScoreResponse(
        probability_of_default=round(pd_value, 6),
        score_band=letter,
        band_label=label,
        expected_loss_usd=round(expected_loss, 2),
        guaranteed_share=round(guaranteed, 4),
        expected_loss_sba_usd=round(expected_loss * guaranteed, 2),
        expected_loss_lender_usd=round(expected_loss * (1 - guaranteed), 2),
        model_version={
            "calibrator": contract.get("calibrator"),
            "parity_max_diff": contract["parity"]["max_abs_diff"],
            "n_features": len(contract["feature_order"]),
        },
    )
