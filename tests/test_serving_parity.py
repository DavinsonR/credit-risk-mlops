"""Las tres vías de serving tienen que dar el MISMO número.

El proyecto exporta un artefacto ONNX y lo sirve por tres caminos: FastAPI local,
función serverless en Vercel y WASM en el navegador. Cada uno reimplementa el
contrato en su entorno, y una divergencia silenciosa entre ellos es el fallo más
peligroso posible: nadie ve un error, solo respuestas distintas según por dónde
entró la solicitud.

Estos tests cubren:
  1. paridad LightGBM ↔ ONNX (el export)
  2. paridad crmlops.encode ↔ serving.encode (el contrato)
  3. el manejo de categorías no vistas
  4. que la duplicación deliberada de `onnx_predict` no derive
"""

from __future__ import annotations

import json
import math
import sys
from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from crmlops.config import repo_root

ARTIFACTS = repo_root() / "exports" / "onnx"
pytestmark = pytest.mark.skipif(
    not (ARTIFACTS / "model.onnx").exists(),
    reason="Falta el export ONNX; correr `uv run python -m crmlops.export.onnx`",
)


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads((ARTIFACTS / "contract.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def serving_app():
    sys.path.insert(0, str(repo_root() / "serving" / "api"))
    import app as serving

    return serving


@pytest.fixture
def solicitud() -> dict:
    return {
        "gross_approval": 250000.0,
        "sba_guaranteed": 187500.0,
        "initial_rate": 8.5,
        "jobs_supported": 6.0,
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


# --- el contrato ---


def test_el_contrato_declara_paridad_verificada(contract):
    """El export no debe escribirse si la paridad falla."""
    parity = contract["parity"]
    assert parity["max_abs_diff"] <= parity["tolerance"]
    assert parity["n_rows"] > 1000


def test_el_orden_de_features_es_numericas_y_luego_categoricas(contract):
    """ONNX recibe un tensor posicional: el orden es parte del contrato."""
    assert contract["feature_order"] == contract["numeric"] + contract["categorical"]


def test_cada_categorica_tiene_vocabulario(contract):
    for c in contract["categorical"]:
        assert contract["categories"].get(c), f"sin vocabulario para {c}"


# --- paridad entre las dos implementaciones del encoder ---


def test_los_dos_encoders_producen_el_mismo_tensor(contract, serving_app, solicitud):
    """crmlops.export.onnx.encode (entrenamiento) vs serving.encode (produccion)."""
    from crmlops.export.onnx import ServingContract
    from crmlops.export.onnx import encode as encode_ref

    ref_contract = ServingContract(
        numeric=contract["numeric"],
        categorical=contract["categorical"],
        categories=contract["categories"],
        calibrator=contract["calibrator"],
        calibrator_shift=contract["calibrator_shift"],
        parity_max_diff=0.0,
        n_parity_rows=0,
    )
    # El encoder de referencia espera las derivadas ya calculadas; el de serving
    # las deriva de los montos. Se replican aqui para comparar lo mismo.
    fila = {
        **solicitud,
        "guarantee_pct": solicitud["sba_guaranteed"] / solicitud["gross_approval"],
        "log_gross_approval": math.log(solicitud["gross_approval"]),
    }
    a = encode_ref(pd.DataFrame([fila]), ref_contract)
    b = serving_app.encode(solicitud, contract)
    np.testing.assert_allclose(a, b, rtol=0, atol=0)


def test_las_derivadas_no_se_piden_al_cliente(serving_app, contract, solicitud):
    """El servicio las calcula: pedirlas invitaria a mandarlas inconsistentes."""
    X = serving_app.encode(solicitud, contract)
    i = contract["numeric"].index("guarantee_pct")
    esperado = solicitud["sba_guaranteed"] / solicitud["gross_approval"]
    assert X[0, i] == pytest.approx(esperado, rel=1e-6)


def test_una_categoria_no_vista_cae_al_codigo_desconocido(serving_app, contract, solicitud):
    X = serving_app.encode({**solicitud, "borrower_state": "NO_EXISTE"}, contract)
    i = len(contract["numeric"]) + contract["categorical"].index("borrower_state")
    assert X[0, i] == contract["unknown_code"]


def test_un_campo_ausente_no_revienta(serving_app, contract, solicitud):
    X = serving_app.encode({**solicitud, "business_type": None}, contract)
    assert X.shape == (1, len(contract["feature_order"]))


# --- la duplicacion deliberada de onnx_predict ---


def test_las_dos_implementaciones_de_onnx_predict_coinciden(contract, serving_app, solicitud):
    """`serving/api/onnx_runtime.py` duplica la funcion a proposito, para que la
    imagen no instale el paquete de entrenamiento. Esto verifica que no derive."""
    import onnxruntime as ort
    from onnx_runtime import onnx_predict as predict_serving

    from crmlops.export.onnx import onnx_predict as predict_ref

    session = ort.InferenceSession(
        (ARTIFACTS / "model.onnx").read_bytes(), providers=["CPUExecutionProvider"]
    )
    X = serving_app.encode(solicitud, contract)
    np.testing.assert_allclose(predict_ref(session, X), predict_serving(session, X), atol=0)


# --- calibrador y bandas ---


def test_el_calibrador_es_monotono(serving_app, contract):
    """Un desplazamiento de intercepto no puede alterar el ranking."""
    crudas = np.linspace(0.001, 0.999, 200)
    calibradas = [serving_app.apply_calibrator(float(p), contract) for p in crudas]
    assert all(a < b for a, b in pairwise(calibradas))


def test_las_bandas_son_monotonas(serving_app):
    bandas = [serving_app.band(p)[0] for p in (0.01, 0.05, 0.10, 0.15, 0.50)]
    assert bandas == sorted(bandas)


def test_la_perdida_esperada_se_reparte_entre_sba_y_banco(serving_app, solicitud):
    from fastapi.testclient import TestClient

    r = TestClient(serving_app.app).post("/score", json=solicitud)
    assert r.status_code == 200
    d = r.json()
    assert d["expected_loss_sba_usd"] + d["expected_loss_lender_usd"] == pytest.approx(
        d["expected_loss_usd"], rel=1e-4
    )
    assert d["guaranteed_share"] == pytest.approx(0.75, rel=1e-6)


def test_el_servicio_rechaza_montos_invalidos(serving_app, solicitud):
    from fastapi.testclient import TestClient

    c = TestClient(serving_app.app)
    assert c.post("/score", json={**solicitud, "gross_approval": -1}).status_code == 422
    assert c.post("/score", json={**solicitud, "initial_rate": 200}).status_code == 422
