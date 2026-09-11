"""Funcion serverless de Vercel: la misma logica, otro entorno.

POR QUE VERCEL Y NO UN CONTENEDOR. Hugging Face Spaces dejo de ofrecer Docker en
su tier gratuito durante 2026, y Railway y Fly.io eliminaron el suyo. Vercel Hobby
sigue siendo gratuito, ya aloja el portafolio, y una funcion Python cabe en el
limite de 250 MB **porque el runtime es onnxruntime y no LightGBM**.

Es el mismo contrato que `serving/api/app.py`. La diferencia es el envoltorio:
aqui no hay FastAPI ni pydantic, solo un handler HTTP, para que el bundle quepa.
"""

from __future__ import annotations

import json
import math
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import numpy as np
import onnxruntime as ort

ARTIFACTS = Path(os.environ.get("CRMLOPS_ARTIFACTS", Path(__file__).parent / "artifacts"))
_SESSION = None
_CONTRACT = None

BANDS = ((0.03, "A"), (0.06, "B"), (0.12, "C"), (0.20, "D"), (1.01, "E"))
LGD = 0.735  # severidad media observada en los charge-off del panel


def _load():
    """Carga perezosa: en serverless el arranque en frio se paga por invocacion."""
    global _SESSION, _CONTRACT
    if _SESSION is None:
        _SESSION = ort.InferenceSession(
            (ARTIFACTS / "model.onnx").read_bytes(), providers=["CPUExecutionProvider"]
        )
        _CONTRACT = json.loads((ARTIFACTS / "contract.json").read_text(encoding="utf-8"))
    return _SESSION, _CONTRACT


def encode(payload: dict, contract: dict) -> np.ndarray:
    gross = float(payload["gross_approval"])
    derived = {
        "guarantee_pct": float(payload.get("sba_guaranteed", 0)) / gross if gross else None,
        "log_gross_approval": math.log(gross) if gross > 0 else None,
    }
    row = []
    for name in contract["numeric"]:
        v = derived.get(name, payload.get(name))
        row.append(float("nan") if v is None else float(v))
    unknown = float(contract["unknown_code"])
    for name in contract["categorical"]:
        v = payload.get(name)
        vocab = contract["categories"].get(name, [])
        row.append(float(vocab.index(str(v))) if v is not None and str(v) in vocab else unknown)
    return np.array([row], dtype="float32")


def score(payload: dict) -> dict:
    session, contract = _load()
    # Solo la salida de probabilidades. `label` viene declarada con forma [1] y
    # onnxruntime avisa sobre ella; ademas aqui no se usa, porque el umbral es
    # economico y lo pone el consumidor.
    salida = next(o.name for o in session.get_outputs() if len(o.shape) == 2)
    (probs,) = session.run([salida], {session.get_inputs()[0].name: encode(payload, contract)})
    raw = float(np.asarray(probs)[0, 1])

    p = min(max(raw, 1e-6), 1 - 1e-6)
    shift = float(contract.get("calibrator_shift", 0.0))
    pd_value = 1.0 / (1.0 + math.exp(-(math.log(p / (1 - p)) + shift)))

    gross = float(payload["gross_approval"])
    guaranteed = float(payload.get("sba_guaranteed", 0)) / gross if gross else 0.0
    el = pd_value * LGD * gross
    return {
        "probability_of_default": round(pd_value, 6),
        "score_band": next(b for t, b in BANDS if pd_value < t),
        "expected_loss_usd": round(el, 2),
        "expected_loss_sba_usd": round(el * guaranteed, 2),
        "expected_loss_lender_usd": round(el * (1 - guaranteed), 2),
        "disclaimer": (
            "No es una decision automatica de credito. El modelo no esta validado "
            "para regimenes de crisis."
        ),
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n = int(self.headers.get("content-length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            if not payload.get("gross_approval"):
                raise ValueError("gross_approval es obligatorio y debe ser > 0")
            body, status = score(payload), 200
        except Exception as exc:
            body, status = {"error": f"{type(exc).__name__}: {exc}"}, 400

        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()
