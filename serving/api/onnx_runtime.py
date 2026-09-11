"""Extraccion de la probabilidad positiva desde una sesion de onnxruntime.

Duplica `crmlops.export.onnx.onnx_predict` a proposito: la imagen de serving no
instala el paquete de entrenamiento, y hacerlo solo por esta funcion traeria
pandas, LightGBM y scikit-learn con ella.

`tests/test_serving_parity.py` verifica que ambas implementaciones coincidan, asi
que la duplicacion es explicita y esta cubierta, no accidental.
"""

from __future__ import annotations

import numpy as np


def probability_output(session) -> str:
    """Nombre de la salida de probabilidades. El grafo trae dos y solo se usa una."""
    for out in session.get_outputs():
        if len(out.shape) == 2:
            return out.name
    raise RuntimeError("No se hallo la salida de probabilidades en el grafo ONNX")


def onnx_predict(session, X: np.ndarray) -> np.ndarray:
    # Solo la salida de probabilidades: `label` viene declarada con forma [1] y
    # onnxruntime avisa sobre ella en cualquier lote mayor que uno. Ver el
    # comentario largo en crmlops/export/onnx.py.
    name = session.get_inputs()[0].name
    (probs,) = session.run([probability_output(session)], {name: X.astype("float32")})
    return np.asarray(probs)[:, 1]
