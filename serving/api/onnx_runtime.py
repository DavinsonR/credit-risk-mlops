"""Extraccion de la probabilidad positiva desde una sesion de onnxruntime.

Duplica `crmlops.export.onnx.onnx_predict` a proposito: la imagen de serving no
instala el paquete de entrenamiento, y hacerlo solo por esta funcion traeria
pandas, LightGBM y scikit-learn con ella.

`tests/test_serving_parity.py` verifica que ambas implementaciones coincidan, asi
que la duplicacion es explicita y esta cubierta, no accidental.
"""

from __future__ import annotations

import numpy as np


def onnx_predict(session, X: np.ndarray) -> np.ndarray:
    name = session.get_inputs()[0].name
    outputs = session.run(None, {name: X.astype("float32")})
    for out in outputs:
        arr = np.asarray(out)
        if arr.ndim == 2 and arr.shape[1] >= 2:
            return arr[:, 1]
    raise RuntimeError("No se hallo el tensor de probabilidades en la salida ONNX")
