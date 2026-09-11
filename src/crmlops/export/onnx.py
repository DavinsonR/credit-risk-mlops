"""Export a ONNX del modelo de produccion, con su contrato de serving.

POR QUE ONNX. El mismo artefacto sirve por tres vias -- FastAPI local, funcion
serverless y WASM en el navegador -- sin reinstalar LightGBM, pandas ni scikit en
cada destino. Y resuelve el hosting a costo cero: onnxruntime-web corre en el
navegador del visitante, sin servidor.

EL PROBLEMA QUE HAY QUE RESOLVER PRIMERO. El modelo entrena con categoricas de
pandas (`dtype='category'`), y LightGBM las maneja nativamente por codigo interno.
ONNX solo acepta tensores numericos. Asi que el mapeo categoria -> codigo deja de
ser un detalle de entrenamiento y **pasa a ser parte del contrato de serving**: si
el servidor lo aplica distinto que el entrenamiento, el modelo devuelve numeros
sin sentido y nada falla ruidosamente.

Por eso el export produce DOS archivos, y ninguno sirve sin el otro:

  model.onnx      el grafo
  contract.json   orden de features, mapeo de categorias, calibrador y el hash
                  de una prueba de paridad

PARIDAD, NO "deberia funcionar". `verify_parity` compara las predicciones de
LightGBM y de ONNX sobre una muestra real y falla si difieren mas que la
tolerancia. Un export que no se verifica es una copia que se supone fiel.
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from crmlops.config import repo_root, resolve_path

# float32 en el grafo contra float64 en LightGBM: la diferencia esperada esta en
# el sexto decimal. Un umbral de 1e-5 sobre la probabilidad es dos ordenes mas
# fino que cualquier diferencia capaz de mover una decision de corte.
PARITY_TOLERANCE = 1e-5
UNKNOWN_CODE = -1  # categoria no vista en entrenamiento


@dataclass
class ServingContract:
    """Todo lo que el servidor necesita para reproducir el entrenamiento."""

    numeric: list[str]
    categorical: list[str]
    categories: dict[str, list[str]]  # orden = codigo entero
    calibrator: str
    calibrator_shift: float
    parity_max_diff: float
    n_parity_rows: int
    notes: list[str] = field(default_factory=list)

    @property
    def feature_order(self) -> list[str]:
        """El orden importa: ONNX recibe un tensor posicional, no un dict."""
        return [*self.numeric, *self.categorical]

    def to_json(self) -> str:
        return json.dumps(
            {
                "feature_order": self.feature_order,
                "numeric": self.numeric,
                "categorical": self.categorical,
                "categories": self.categories,
                "unknown_code": UNKNOWN_CODE,
                "calibrator": self.calibrator,
                "calibrator_shift": self.calibrator_shift,
                "parity": {
                    "max_abs_diff": self.parity_max_diff,
                    "tolerance": PARITY_TOLERANCE,
                    "n_rows": self.n_parity_rows,
                },
                "notes": self.notes,
            },
            indent=2,
        )


def build_categories(df: pd.DataFrame, categorical: list[str]) -> dict[str, list[str]]:
    """Vocabulario de cada categorica, tomado SOLO de entrenamiento.

    El orden de esta lista define el codigo entero. Congelarlo es lo que permite
    que el servidor produzca los mismos codigos meses despues.
    """
    return {
        c: sorted(pd.Series(df[c]).astype("string").dropna().unique().tolist()) for c in categorical
    }


def encode(df: pd.DataFrame, contract: ServingContract) -> np.ndarray:
    """Aplica el contrato: devuelve el tensor float32 que espera ONNX.

    Esta funcion es la referencia. El servidor la reimplementa en su lenguaje, y
    los tests verifican que ambas produzcan lo mismo.
    """
    cols = []
    for c in contract.numeric:
        cols.append(pd.to_numeric(df[c], errors="coerce").to_numpy(dtype="float32"))
    for c in contract.categorical:
        vocab = {v: i for i, v in enumerate(contract.categories[c])}
        codes = pd.Series(df[c]).astype("string").map(vocab)
        cols.append(codes.fillna(UNKNOWN_CODE).to_numpy(dtype="float32"))
    return np.column_stack(cols)


def to_onnx(model, n_features: int):
    """Convierte el LGBMClassifier entrenado a un grafo ONNX."""
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType

    return convert_lightgbm(
        model,
        initial_types=[("input", FloatTensorType([None, n_features]))],
        target_opset=None,
        zipmap=False,  # sin zipmap la salida es un tensor limpio, no una lista de dicts
    )


def probability_output(session) -> str:
    """Nombre de la salida de probabilidades. El grafo trae dos y solo se usa una.

    `label` (la clase predicha, 1D) nunca se lee: la decision de corte la toma el
    consumidor con su propio umbral economico, no el grafo.
    """
    for out in session.get_outputs():
        if len(out.shape) == 2:
            return out.name
    encontradas = [(o.name, o.shape) for o in session.get_outputs()]
    raise RuntimeError(f"No se hallo la salida de probabilidades en {encontradas}")


def onnx_predict(session, X: np.ndarray) -> np.ndarray:
    """Probabilidad de la clase positiva desde una sesion de onnxruntime."""
    name = session.get_inputs()[0].name
    # Se pide SOLO la salida de probabilidades, no `None` (que las pide todas).
    # onnxmltools declara `label` con forma [1] en vez de [None], asi que
    # onnxruntime avisaba en cada lote grande:
    #   Expected shape from model of {1} does not match actual shape of {20000}
    # Era inofensivo --nunca se leia `label`-- pero salia en cada `run onnx` y
    # parecia un problema de paridad, que es justo lo que ese comando existe para
    # descartar. Una advertencia que hay que aprender a ignorar termina tapando a
    # la que no habia que ignorar.
    (probs,) = session.run([probability_output(session)], {name: X.astype("float32")})
    return np.asarray(probs)[:, 1]


def verify_parity(
    model, onnx_bytes: bytes, df: pd.DataFrame, contract: ServingContract
) -> tuple[float, int]:
    """Compara LightGBM contra ONNX sobre datos reales. Devuelve (max_diff, n)."""
    import onnxruntime as ort

    X = encode(df, contract)
    session = ort.InferenceSession(onnx_bytes, providers=["CPUExecutionProvider"])
    p_onnx = onnx_predict(session, X)

    # LightGBM recibe el MISMO tensor codificado, no el DataFrame original: si se
    # le pasara el DataFrame, se compararian dos pipelines distintos y la prueba
    # dejaria de medir la fidelidad del grafo.
    #
    # Por eso mismo sklearn avisa "X does not have valid feature names": el modelo
    # se ajusto con nombres y aqui entra una matriz posicional. El aviso es
    # correcto y la situacion es deliberada, asi que se silencia SOLO este mensaje
    # y SOLO en esta llamada. Dejarlo visible entrenaria a ignorar la salida de
    # `run onnx`, que es precisamente donde hay que mirar si la paridad falla.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="X does not have valid feature names")
        p_lgbm = model.predict_proba(X)[:, 1]
    return float(np.max(np.abs(p_onnx - p_lgbm))), len(df)


def export(
    model,
    train_df: pd.DataFrame,
    parity_df: pd.DataFrame,
    numeric: list[str],
    categorical: list[str],
    calibrator_name: str,
    calibrator_shift: float,
    out_dir: Path | None = None,
) -> dict:
    """Exporta grafo + contrato y verifica paridad antes de escribir nada."""
    out_dir = out_dir or (resolve_path("exports") / "onnx")
    out_dir.mkdir(parents=True, exist_ok=True)

    contract = ServingContract(
        numeric=list(numeric),
        categorical=list(categorical),
        categories=build_categories(train_df, categorical),
        calibrator=calibrator_name,
        calibrator_shift=calibrator_shift,
        parity_max_diff=float("nan"),
        n_parity_rows=0,
        notes=[
            "Las categorias no vistas en entrenamiento se codifican como "
            f"{UNKNOWN_CODE}, que es como se comportarian en produccion.",
            "El calibrador se aplica DESPUES del grafo: es un desplazamiento de "
            "intercepto en escala logit, monotono, y por eso no altera el ranking.",
        ],
    )

    onnx_model = to_onnx(model, len(contract.feature_order))
    onnx_bytes = onnx_model.SerializeToString()

    max_diff, n = verify_parity(model, onnx_bytes, parity_df, contract)
    contract.parity_max_diff = max_diff
    contract.n_parity_rows = n
    if max_diff > PARITY_TOLERANCE:
        raise AssertionError(
            f"PARIDAD FALLIDA: diferencia maxima {max_diff:.2e} > {PARITY_TOLERANCE:g} "
            f"sobre {n:,} filas. El grafo no reproduce al modelo; no se exporta."
        )

    (out_dir / "model.onnx").write_bytes(onnx_bytes)
    (out_dir / "contract.json").write_text(contract.to_json() + "\n", encoding="utf-8")

    return {
        "onnx_bytes": len(onnx_bytes),
        "n_features": len(contract.feature_order),
        "parity_max_diff": max_diff,
        "parity_rows": n,
        "dir": str(out_dir.relative_to(repo_root())),
    }


def main() -> int:
    from crmlops.config import load_config
    from crmlops.features.spec import load_spec
    from crmlops.models.calibration import fit_calibrator
    from crmlops.models.gbm import GBMChallenger
    from crmlops.models.train import PRODUCTION_CALIBRATOR, TARGET
    from crmlops.sources.contracts import validate_panel
    from crmlops.sources.loader import load_panel, split_out_of_time

    cfg = load_config()
    spec = load_spec(cfg)
    sp = split_out_of_time(validate_panel(load_panel(cfg)), cfg)
    tr, va, te = sp["train"], sp["valid"], sp["test"]

    print("=" * 78)
    print("EXPORT A ONNX - modelo de produccion")
    print("=" * 78)

    model = GBMChallenger(
        list(spec.numeric), list(spec.categorical), random_state=cfg["project"]["random_seed"]
    )
    model.fit(tr, tr[TARGET], va, va[TARGET])
    cal = fit_calibrator(PRODUCTION_CALIBRATOR, va[TARGET].to_numpy(), model.predict_proba(va))

    info = export(
        model.model,  # el LGBMClassifier interno
        tr,
        te.sample(n=min(20_000, len(te)), random_state=42),
        list(spec.numeric),
        list(spec.categorical),
        PRODUCTION_CALIBRATOR,
        float(getattr(cal, "shift", 0.0)),
    )

    print(f"\n  features        {info['n_features']}")
    print(f"  grafo           {info['onnx_bytes'] / 1024:,.0f} KB")
    print(f"  paridad         {info['parity_max_diff']:.2e} sobre {info['parity_rows']:,} filas")
    print(f"                  (tolerancia {PARITY_TOLERANCE:g})")
    print(f"  destino         {info['dir']}")
    print("\nPARIDAD VERIFICADA: el grafo reproduce al modelo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
