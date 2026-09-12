"""Deriva de poblacion: lo unico que se puede medir sin esperar anios.

El ADR 0010 deja el monitoreo de desempeno fuera de alcance para cosechas jovenes
--la etiqueta tarda 51 meses medianos en existir--. Lo que si se puede medir el
mismo dia que llega un vintage nuevo es si la POBLACION cambio: las features se
conocen en la originacion.

DOS DECISIONES QUE NO SON OBVIAS.

1. EL PERFIL DE REFERENCIA SE COMMITEA. No los datos: los cortes de bin y las
   proporciones de entrenamiento, unas pocas decenas de KB. Con eso, medir deriva
   no exige tener los 861 MB del vintage con que se entreno, y un validador puede
   recalcular el PSI con el repo y el vintage nuevo. Es la misma razon por la que
   los gates leen metrics.json en vez de reentrenar.

2. LA DERIVA DE FEATURES NO SE MIDE SOBRE EL PANEL DE MODELADO. El panel filtra a
   prestamos RESUELTOS, y en FY2023 eso es el 17.4% de la cosecha --sesgado hacia
   los que resolvieron rapido--. Las features, en cambio, se conocen para todas las
   originaciones. Medir deriva sobre el panel mediria la composicion de lo resuelto
   y no la de quien esta entrando. Aqui se lee la cosecha completa.

   Lo unico que se excluye es CANCLD: un prestamo cancelado nunca se desembolso, no
   forma parte de la poblacion que el modelo puntua. EXEMPT y COMMIT si entran: son
   prestamos vivos o sin estado publicado, pero sus features existen. Es un
   supuesto y se declara: si EXEMPT fuera algo distinto de "booked sin divulgar",
   la poblacion de referencia estaria contaminada por unos 297 mil registros.

CONVENCION DEL PSI. Los cortes se definen SOBRE LA REFERENCIA y se aplican al dato
nuevo. Recalcularlos sobre el dato nuevo esconderia justo la deriva que se busca.
Es la misma convencion que `crmlops.evaluation.metrics.psi`, y hay un test que
verifica que las dos implementaciones coinciden cuando se les da lo mismo.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from crmlops.config import load_config, repo_root
from crmlops.features.spec import FeatureSpec, load_spec
from crmlops.monitoring.maturity import as_of_date

PROFILE_PATH = "exports/reference_profile.json"
DRIFT_PATH = "exports/drift.json"
REPORT_PATH = "reports/DRIFT_REPORT.md"

# Bins del PSI. 10 es la convencion de la industria y la que ya usa
# evaluation.metrics; cambiarlo cambiaria el valor y rompe la comparabilidad con
# los numeros publicados.
N_BINS = 10
EPS = 1e-6  # evita log(0) en bins vacios

PREDICTIONS_PATH = "exports/verification/test_predictions.parquet"

# Soporte minimo para considerar que el modelo APRENDIO algo de una categoria.
# 0.5% de las 217.060 filas de entrenamiento son ~1.085 prestamos: suficiente para
# que un arbol abra un corte con sentido. Por debajo de eso la categoria existe en
# el vocabulario pero el modelo no tiene evidencia sobre ella, y recibir masa nueva
# ahi es casi tan malo como recibirla en una categoria inexistente.
MIN_SUPPORT = 0.005


# --------------------------------------------------------------------------- perfil


@dataclass
class NumericProfile:
    name: str
    edges: list[float]
    proportions: list[float]
    mean: float
    kind: str = "numeric"


@dataclass
class CategoricalProfile:
    name: str
    categories: list[str]
    proportions: list[float]
    kind: str = "categorical"


@dataclass
class ScoreProfile:
    edges: list[float]
    proportions: list[float]
    mean_logit: float


@dataclass
class ReferenceProfile:
    """Resumen de la poblacion de entrenamiento. Lo que se commitea."""

    created_at: str
    as_of: str
    config_fingerprint: str
    train_window: list[int]
    n: int
    numeric: dict[str, NumericProfile] = field(default_factory=dict)
    categorical: dict[str, CategoricalProfile] = field(default_factory=dict)
    score: ScoreProfile | None = None

    def to_json(self, path: Path | None = None) -> Path:
        path = path or (repo_root() / PROFILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_json(cls, path: Path | None = None) -> ReferenceProfile:
        path = path or (repo_root() / PROFILE_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"Falta el perfil de referencia en {path}. Generarlo con:\n"
                "  uv run python -m crmlops.monitoring.drift --build"
            )
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            created_at=d["created_at"],
            as_of=d["as_of"],
            config_fingerprint=d["config_fingerprint"],
            train_window=d["train_window"],
            n=d["n"],
            numeric={k: NumericProfile(**v) for k, v in d.get("numeric", {}).items()},
            categorical={k: CategoricalProfile(**v) for k, v in d.get("categorical", {}).items()},
            score=ScoreProfile(**d["score"]) if d.get("score") else None,
        )


def _proportions(values: np.ndarray, edges: np.ndarray) -> list[float]:
    counts = np.histogram(values, bins=edges)[0]
    total = counts.sum()
    if total == 0:
        return [0.0] * len(counts)
    return (counts / total).tolist()


def _edges_from(values: np.ndarray) -> np.ndarray:
    edges = np.unique(np.quantile(values, np.linspace(0, 1, N_BINS + 1)))
    if len(edges) < 3:
        # Variable casi constante: dos bins alrededor del unico valor. PSI dara ~0
        # salvo que el dato nuevo se mueva de verdad, que es lo que se quiere.
        edges = np.array([values.min(), values.min(), values.max()], dtype=float)
    edges = edges.astype(float)
    edges[0], edges[-1] = -np.inf, np.inf
    return edges


def build_reference(
    df: pd.DataFrame,
    spec: FeatureSpec,
    scores: np.ndarray | None = None,
    cfg: dict | None = None,
) -> ReferenceProfile:
    """Construye el perfil desde la poblacion de entrenamiento."""
    from crmlops.governance.gates import config_fingerprint

    cfg = cfg or load_config()
    tr = cfg["splits"]["train"]

    perfil = ReferenceProfile(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        as_of=as_of_date().isoformat(),
        config_fingerprint=config_fingerprint(cfg),
        train_window=[tr["start"], tr["end"]],
        n=len(df),
    )

    for col in spec.numeric:
        vals = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
        if vals.size == 0:
            continue
        edges = _edges_from(vals)
        perfil.numeric[col] = NumericProfile(
            name=col,
            edges=edges.tolist(),
            proportions=_proportions(vals, edges),
            mean=float(vals.mean()),
        )

    for col in spec.categorical:
        vc = df[col].astype("string").fillna("NULO").value_counts(normalize=True)
        perfil.categorical[col] = CategoricalProfile(
            name=col,
            categories=vc.index.tolist(),
            proportions=vc.to_numpy(dtype=float).tolist(),
        )

    if scores is not None and len(scores):
        s = np.clip(np.asarray(scores, dtype=float), EPS, 1 - EPS)
        edges = _edges_from(s)
        perfil.score = ScoreProfile(
            edges=edges.tolist(),
            proportions=_proportions(s, edges),
            mean_logit=float(np.mean(np.log(s / (1 - s)))),
        )

    return perfil


# --------------------------------------------------------------------------- PSI


def psi_numeric(profile: NumericProfile, values: np.ndarray) -> float:
    """PSI contra un perfil persistido. Los cortes vienen de la referencia."""
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return 0.0
    e = np.clip(np.asarray(profile.proportions, dtype=float), EPS, None)
    a = np.clip(np.asarray(_proportions(values, np.asarray(profile.edges)), dtype=float), EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def psi_categorical(profile: CategoricalProfile, values: pd.Series) -> tuple[float, float]:
    """PSI de una categorica y masa en categorias no vistas. Devuelve (psi, masa).

    POR QUE SE DEVUELVEN LAS DOS COSAS. Las categorias nuevas van a un bucket
    propio --mandarlas a la mas parecida seria inventar, ignorarlas haria que una
    poblacion con mitad de categorias nuevas diera PSI cero--. Pero ese bucket
    tiene proporcion de referencia cero, y el PSI de un bucket con referencia cero
    no esta acotado: queda fijado por el EPS que se use para no dividir por cero.

    Con EPS = 1e-6 y una categoria nueva que se lleva el 52% de la masa, el termino
    es 0.52 * log(0.52 / 1e-6) ~ 6.9. Tres categorias asi dan PSI ~18.5. Ese 18.5
    no mide la magnitud de nada: mide el EPS elegido.

    Asi que el PSI se reporta igual --sirve para ordenar-- pero la alarma que se lee
    es la MASA SIN SOPORTE: la proporcion del dato nuevo que cae en categorias sobre
    las que el modelo no tiene evidencia. Es una proporcion, es interpretable y no
    depende de ninguna constante arbitraria: "el 82% de los valores de esta variable
    caen en categorias que el modelo practicamente no vio".

    SIN SOPORTE ES MAS QUE NO VISTA, y la diferencia importa. Una categoria que
    existe en el vocabulario con el 0.01% de la masa de entrenamiento --22 prestamos
    de 217.060-- y que hoy se lleva el 52% no aparece como "nueva": el modelo tiene
    un codigo para ella y no aprendio nada. Contar solo las inexistentes daria 30%
    donde el problema real es 82%.
    """
    obs = values.astype("string").fillna("NULO").value_counts(normalize=True)
    cats = list(profile.categories)
    soporte = dict(zip(cats, profile.proportions, strict=True))

    e = np.clip(np.asarray(profile.proportions, dtype=float), EPS, None)
    a = np.clip(np.asarray([obs.get(c, 0.0) for c in cats], dtype=float), EPS, None)

    no_vista = float(sum(v for k, v in obs.items() if k not in soporte))
    if no_vista > 0:
        e = np.append(e, EPS)
        a = np.append(a, no_vista)

    sin_soporte = float(sum(v for k, v in obs.items() if soporte.get(k, 0.0) < MIN_SUPPORT))
    return float(np.sum((a - e) * np.log(a / e))), sin_soporte


@dataclass
class ScoreDrift:
    psi_total: float
    psi_shape: float
    level_shift: float

    @property
    def interpretation(self) -> str:
        if self.psi_total < 0.10:
            return "estable"
        if self.psi_shape < 0.10:
            return "corrimiento de NIVEL: recalibrar basta"
        return "cambio de FORMA: la mezcla cambio, evaluar reentrenamiento"


def score_drift(profile: ScoreProfile, scores: np.ndarray) -> ScoreDrift:
    """PSI del score, separando nivel de forma.

    Replica la logica de `evaluation.metrics.stability` pero trabajando contra un
    perfil persistido en vez de contra el array de referencia, que no se guarda.
    `tests/test_drift.py` verifica que las dos coincidan con los mismos datos.
    """
    s = np.clip(np.asarray(scores, dtype=float), EPS, 1 - EPS)
    edges = np.asarray(profile.edges)
    e = np.clip(np.asarray(profile.proportions, dtype=float), EPS, None)

    a = np.clip(np.asarray(_proportions(s, edges), dtype=float), EPS, None)
    psi_total = float(np.sum((a - e) * np.log(a / e)))

    logit = np.log(s / (1 - s))
    desplazamiento = float(logit.mean() - profile.mean_logit)
    recentrado = 1.0 / (1.0 + np.exp(-(logit - desplazamiento)))
    a2 = np.clip(np.asarray(_proportions(recentrado, edges), dtype=float), EPS, None)
    psi_shape = float(np.sum((a2 - e) * np.log(a2 / e)))

    return ScoreDrift(psi_total=psi_total, psi_shape=psi_shape, level_shift=desplazamiento)


# --------------------------------------------------------------------- poblacion


def origination_panel(
    fy_from: int, fy_to: int, source_glob: str | None = None, cfg: dict | None = None
) -> pd.DataFrame:
    """Features de originacion de las cosechas pedidas, sin filtrar por resultado.

    Se reusa `build_query` con `require_resolved=False` en vez de escribir una
    query propia: duplicar las derivaciones de features seria exactamente el
    defecto A2 del AUDIT --dos listas paralelas que se desincronizan--.

    El `is_chargeoff` que viene aqui NO es un target valido: vale 0 tambien para lo
    que todavia no fallo. Se elimina antes de devolver, para que no pueda usarse
    por accidente.
    """
    from crmlops.sources.loader import build_query

    cfg = cfg or load_config()
    q = build_query(cfg, source_glob, require_resolved=False)
    con = duckdb.connect()
    df = con.execute(f"""
        select * from ({q}) where approval_fy between {fy_from} and {fy_to}
    """).df()
    return df.drop(columns=["is_chargeoff", "chargeoff_amount"], errors="ignore")


# ------------------------------------------------------------------------ reporte


@dataclass
class DriftResult:
    feature: str
    kind: str
    psi: float
    unsupported_mass: float = 0.0

    @property
    def band(self) -> str:
        # La masa no vista manda: una variable cuyo vocabulario cambio no esta
        # "vigilar", esta rota. El modelo manda todo eso al codigo desconocido.
        if self.unsupported_mass >= 0.05:
            return "VOCABULARIO"
        if self.psi < 0.10:
            return "estable"
        return "vigilar" if self.psi < 0.25 else "ACCION"


def compute_drift(
    df: pd.DataFrame, profile: ReferenceProfile, spec: FeatureSpec
) -> list[DriftResult]:
    out: list[DriftResult] = []
    for col, p in profile.numeric.items():
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
            out.append(DriftResult(col, "numerica", psi_numeric(p, vals)))
    for col, pc in profile.categorical.items():
        if col in df.columns:
            psi, no_vista = psi_categorical(pc, df[col])
            out.append(DriftResult(col, "categorica", psi, no_vista))
    # Primero lo que tiene vocabulario roto, luego por PSI.
    return sorted(out, key=lambda r: (-r.unsupported_mass, -r.psi))


def reference_scores(path: Path | None = None) -> np.ndarray:
    """Scores de referencia: los del conjunto de TEST, no los de entrenamiento.

    Es deliberado. Lo que interesa no es la distribucion sobre la que el modelo
    aprendio sino la que sostiene las metricas publicadas: AUC, Brier y ECE se
    midieron sobre test. Si los scores de hoy se alejan de esa distribucion, esas
    cifras dejan de describir lo que el modelo esta haciendo.
    """
    path = path or (repo_root() / PREDICTIONS_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Faltan las predicciones de verificacion en {path}. Correr train.")
    return pd.read_parquet(path)["produccion"].to_numpy(dtype=float)


def score_with_onnx(df: pd.DataFrame) -> np.ndarray | None:
    """Puntua la cosecha con el grafo ONNX commiteado. None si falta el extra.

    Se usa el artefacto exportado y no un modelo reentrenado: monitorear con un
    modelo distinto del que esta desplegado mediria otra cosa.
    """
    try:
        import onnxruntime as ort

        from crmlops.export.onnx import ServingContract, encode, onnx_predict
    except ImportError:
        return None

    modelo = repo_root() / "exports" / "onnx" / "model.onnx"
    contrato = repo_root() / "exports" / "onnx" / "contract.json"
    if not (modelo.exists() and contrato.exists()):
        return None

    d = json.loads(contrato.read_text(encoding="utf-8"))
    contract = ServingContract(
        numeric=d["numeric"],
        categorical=d["categorical"],
        categories=d["categories"],
        calibrator=d["calibrator"],
        calibrator_shift=d["calibrator_shift"],
        parity_max_diff=d["parity"]["max_abs_diff"],
        n_parity_rows=d["parity"]["n_rows"],
    )
    faltan = [c for c in contract.feature_order if c not in df.columns]
    if faltan:
        return None

    sesion = ort.InferenceSession(modelo.read_bytes(), providers=["CPUExecutionProvider"])
    crudo = onnx_predict(sesion, encode(df, contract))
    # Se aplica el mismo ajuste de intercepto que usa el serving: comparar scores
    # sin calibrar contra una referencia calibrada seria una deriva inventada.
    p = np.clip(crudo, EPS, 1 - EPS)
    logit = np.log(p / (1 - p)) + contract.calibrator_shift
    return 1.0 / (1.0 + np.exp(-logit))


# --------------------------------------------------------------------------- main


def _build(cfg: dict, spec: FeatureSpec) -> Path:
    from crmlops.sources.loader import load_panel

    tr = cfg["splits"]["train"]
    panel = load_panel(cfg)
    entrenamiento = panel[panel["approval_fy"].between(tr["start"], tr["end"])]
    perfil = build_reference(entrenamiento, spec, reference_scores(), cfg)
    ruta = perfil.to_json()
    print(f"Perfil de referencia: {len(entrenamiento):,} filas de FY{tr['start']}-{tr['end']}")
    print(
        f"  {len(perfil.numeric)} numericas, {len(perfil.categorical)} categoricas, score incluido"
    )
    print(f"  -> {ruta}")
    return ruta


def _tabla_drift(resultados: list[DriftResult]) -> str:
    lineas = [
        "| Feature | Tipo | PSI | Masa sin soporte | Banda |",
        "|---|---|---|---|---|",
    ]
    for r in resultados:
        masa = f"{r.unsupported_mass:.1%}" if r.unsupported_mass else "--"
        lineas.append(f"| `{r.feature}` | {r.kind} | {r.psi:.4f} | {masa} | {r.band} |")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    cfg = load_config()
    spec = load_spec(cfg)

    if "--build" in argv:
        _build(cfg, spec)
        return 0

    perfil = ReferenceProfile.from_json()
    mon = cfg["monitoring"]
    desde = int(mon["watch_from_fy"])
    corte = as_of_date()

    print("=" * 92)
    print("DERIVA DE POBLACION -- lo que se puede medir sin esperar la etiqueta")
    print("=" * 92)
    print(f"  referencia   FY{perfil.train_window[0]}-{perfil.train_window[1]}, {perfil.n:,} filas")
    print(f"  vintage      corte {corte}")
    print(f"  config       {perfil.config_fingerprint}")

    from crmlops.governance.gates import config_fingerprint

    if perfil.config_fingerprint != config_fingerprint(cfg):
        print("\n  AVISO: el perfil se construyo con otro config. Regenerar con --build.")

    filas: list[dict] = []
    secciones: list[str] = []

    for fy in range(desde, corte.year + 1):
        df = origination_panel(fy, fy, cfg=cfg)
        if df.empty:
            continue
        resultados = compute_drift(df, perfil, spec)
        peor = resultados[0] if resultados else None
        sd = None
        if perfil.score is not None:
            scores = score_with_onnx(df)
            if scores is not None:
                sd = score_drift(perfil.score, scores)

        print()
        print(f"--- FY{fy}  ({len(df):,} originaciones) " + "-" * 40)
        for r in resultados[:5]:
            masa = f"  sin soporte {r.unsupported_mass:5.1%}" if r.unsupported_mass else ""
            print(f"    {r.feature:24s} {r.kind:11s} PSI {r.psi:8.4f}  {r.band}{masa}")
        if sd:
            print(
                f"    {'SCORE':24s} {'modelo':11s} PSI {sd.psi_total:7.4f}  "
                f"forma {sd.psi_shape:.4f}  nivel {sd.level_shift:+.3f}  -> {sd.interpretation}"
            )

        filas.append(
            {
                "approval_fy": fy,
                "n": len(df),
                "peor_feature": peor.feature if peor else None,
                "peor_psi": round(peor.psi, 6) if peor else None,
                "features_en_accion": [r.feature for r in resultados if r.psi >= mon["psi_action"]],
                "sin_soporte": {
                    r.feature: round(r.unsupported_mass, 4)
                    for r in resultados
                    if r.unsupported_mass >= 0.05
                },
                "score_psi_total": round(sd.psi_total, 6) if sd else None,
                "score_psi_forma": round(sd.psi_shape, 6) if sd else None,
                "score_nivel": round(sd.level_shift, 6) if sd else None,
                "score_lectura": sd.interpretation if sd else None,
            }
        )
        secciones.append(f"### FY{fy} -- {len(df):,} originaciones\n\n{_tabla_drift(resultados)}")

    salida = repo_root() / DRIFT_PATH
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(
            {
                "as_of": corte.isoformat(),
                "reference": {
                    "train_window": perfil.train_window,
                    "n": perfil.n,
                    "config_fingerprint": perfil.config_fingerprint,
                },
                "thresholds": {"psi_warn": mon["psi_warn"], "psi_action": mon["psi_action"]},
                "cohorts": filas,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    reporte = repo_root() / REPORT_PATH
    reporte.parent.mkdir(parents=True, exist_ok=True)
    reporte.write_text(
        "\n".join(
            [
                "# Reporte de deriva",
                "",
                "_Generado por `crmlops.monitoring.drift`. No editar a mano._",
                "",
                f"- **Vintage:** corte {corte}",
                f"- **Referencia:** FY{perfil.train_window[0]}-{perfil.train_window[1]}, "
                f"{perfil.n:,} filas",
                f"- **Umbrales:** vigilar >= {mon['psi_warn']}, accion >= {mon['psi_action']}",
                "",
                "El desempeno (AUC, calibracion) **no** se reporta aqui: en cosechas jovenes",
                "la etiqueta no existe todavia. Ver [ADR 0010](adr/0010-monitoreo-a-madurez-pareja.md).",
                "",
                *secciones,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 92)
    print(f"Exportado a {salida} y {reporte}")
    print("La decision de reentrenar la toma `crmlops.monitoring.retrain`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
