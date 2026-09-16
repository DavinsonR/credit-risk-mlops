"""Cuanto cuesta armonizar `business_age`, y que no se puede armonizar.

LA PREGUNTA ABIERTA DEL ADR 0011. El SBA cambio el esquema de categorias de
`business_age` entre FY2018 y FY2021 y hoy el 84% de los valores cae en categorias
que el modelo nunca vio. El ADR dejo el problema abierto a proposito, con dos
razones escritas:

  - Reentrenar NO lo arregla. La ventana vieja tiene el vocabulario viejo, y la
    ventana nueva choca con la madurez de la etiqueta (ADR 0010): un charge-off
    tarda una mediana de 51 meses en aparecer, asi que las cosechas que hablan el
    vocabulario nuevo casi no tienen resultado observado.
  - Armonizar tampoco es mecanico, y la razon es el contenido del mapeo, no su
    implementacion.

Este modulo cierra la pregunta midiendo, no argumentando. Entrena el modelo de
produccion DOS VECES sobre el mismo split y la misma semilla --con el vocabulario
crudo y con el armonizado-- y publica las dos cifras.

EL MAPEO PIERDE RESOLUCION, Y ESO SE PUEDE MEDIR. Cuatro categorias viejas que el
modelo distinguia colapsan en una sola. La pregunta empirica es cuanto vale esa
distincion: si el costo en AUC es despreciable, la armonizacion es gratis y no
hacerla es negligencia; si es grande, hay un intercambio real entre resolucion
historica y poder puntuar el dato de hoy.

Y HAY ALGO QUE NO SE PUEDE MAPEAR. `Change of Ownership` no es una antiguedad: es
una forma de adquisicion. No existia en el esquema viejo como valor de esta
variable y no hay ninguna categoria vieja que signifique lo mismo. Mapearlo a
"existente" seria inventar el dato. Se deja sin soporte a proposito, y el residuo
que queda es el limite honesto de la armonizacion.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass

import duckdb
import pandas as pd

from crmlops.config import load_config, repo_root
from crmlops.evaluation.metrics import discrimination
from crmlops.features.spec import load_spec
from crmlops.models.gbm import GBMChallenger
from crmlops.monitoring.drift import MIN_SUPPORT
from crmlops.sources.loader import load_panel, split_out_of_time

TARGET = "is_chargeoff"
EXPORT_PATH = "exports/business_age_harmonization.json"
VARIABLE = "business_age"

# El esquema NUEVO es el destino, no el viejo. Se armoniza hacia adelante porque
# el objetivo es puntuar el dato que llega hoy; armonizar hacia atras exigiria
# partir una categoria gruesa en cuatro finas, que es informacion que no existe.
DESTINO = (
    "Existing or more than 2 years old",
    "New Business or 2 years or less",
    "Startup, Loan Funds will Open Business",
    "Change of Ownership",
)

# Cada linea dice que se pierde. El colapso no es simetrico: cuatro tramos de
# antiguedad entre 2 y 5+ anios se vuelven uno solo, mientras que "menos de 1 anio"
# sobrevive casi intacto dentro de "2 anios o menos".
MAPEO: dict[str, str] = {
    # -- colapsan cuatro en una: se pierde el gradiente de 2 a 5+ anios ---------
    "Existing, 5 or more years": "Existing or more than 2 years old",
    "Less than 5 years old but at least 4": "Existing or more than 2 years old",
    "Less than 4 years old but at least 3": "Existing or more than 2 years old",
    "Less than 3 years old but at least 2": "Existing or more than 2 years old",
    # -- casi identidad: "menos de 1 anio" cabe entero en "2 anios o menos" -----
    "New, Less than 1 Year old": "New Business or 2 years or less",
    "New Business or Less than 2 Years Old": "New Business or 2 years or less",
    # -- identidad -------------------------------------------------------------
    "Startup, Loan Funds will Open Business": "Startup, Loan Funds will Open Business",
    "Existing or more than 2 years old": "Existing or more than 2 years old",
    "New Business or 2 years or less": "New Business or 2 years or less",
    "Change of Ownership": "Change of Ownership",
}

# Categorias del dato NUEVO que el mapeo no puede resolver hacia ninguna categoria
# vieja. Se declaran aqui para que el residuo sea una afirmacion explicita del
# codigo y no un silencio.
SIN_ORIGEN = ("Change of Ownership",)

UNKNOWN = "UNKNOWN"


def armonizar(serie: pd.Series) -> pd.Series:
    """Aplica el mapeo. Lo que no esta en el mapeo queda como UNKNOWN, no se inventa."""
    return serie.map(lambda v: MAPEO.get(v, UNKNOWN) if isinstance(v, str) else UNKNOWN)


# --------------------------------------------------------------------------
# Cobertura: cuanto del dato de hoy queda dentro del vocabulario del modelo
# --------------------------------------------------------------------------
@dataclass
class Cobertura:
    """Cobertura sobre la ventana RECIENTE, con el mismo criterio que `drift`.

    SOPORTE NO ES PRESENCIA, y la distincion ya costo una correccion en el ADR
    0011. `Existing or more than 2 years old` SI existe en el vocabulario de
    entrenamiento -- con 22 prestamos de 217.060, el 0.01% -- asi que contar
    "categorias presentes" la daba por cubierta y el 84% real se leia como 30%.
    Aqui se usa el mismo umbral que `crmlops.monitoring.drift`: soportada es la
    categoria con al menos MIN_SUPPORT de la masa de entrenamiento.

    La primera version de este modulo volvio a contar presencia, y sobre la
    ventana equivocada. Daba 81.4% de cobertura donde el ADR reporta 16%.
    """

    fy_desde: int
    fy_hasta: int
    n: int
    soportado_crudo: float
    soportado_armonizado: float
    sin_origen: float  # masa de categorias que el mapeo declara irreducibles
    min_support: float
    por_fy: list[dict]

    @property
    def recuperado_pp(self) -> float:
        return (self.soportado_armonizado - self.soportado_crudo) * 100


def cobertura(
    vocab_soporte: dict[str, float], cfg: dict | None = None, *, ventana: int = 3
) -> Cobertura:
    """Que fraccion del dato RECIENTE cae en categorias con soporte de entrenamiento.

    La ventana son los ultimos `ventana` anios fiscales con datos, no `watch_from_fy`.
    El ADR 0011 mide sobre FY2024-2026 y esta cifra tiene que ser comparable: promediar
    desde FY2016 mezcla anios que todavia hablaban el vocabulario viejo y diluye el
    hallazgo hasta invertirlo.
    """
    cfg = cfg or load_config()
    raw = (repo_root() / "data/raw/FOIA_7a_FY*.csv").as_posix()
    df = (
        duckdb.connect()
        .execute(f"""
        select try_cast(ApprovalFY as integer) as fy, trim(BusinessAge) as cat, count(*) n
        from read_csv('{raw}', union_by_name=true, ignore_errors=true,
                      sample_size=200000, all_varchar=true)
        where try_cast(ApprovalFY as integer) is not null
        group by 1, 2
        """)
        .fetchdf()
    )
    fy_max = int(df["fy"].max())
    fy_min = fy_max - ventana + 1

    soportadas = {k for k, v in vocab_soporte.items() if v >= MIN_SUPPORT}
    # El vocabulario armonizado hereda el soporte SUMADO de sus origenes: cuatro
    # categorias del 5% se vuelven una del 20%, no cuatro del 5%.
    soporte_arm: dict[str, float] = {}
    for cat, prop in vocab_soporte.items():
        destino = MAPEO.get(cat, UNKNOWN)
        soporte_arm[destino] = soporte_arm.get(destino, 0.0) + prop
    soportadas_arm = {k for k, v in soporte_arm.items() if v >= MIN_SUPPORT and k != UNKNOWN}

    def _tasas(part: pd.DataFrame) -> tuple[float, float, float]:
        total = float(part["n"].sum())
        crudo = float(part[part["cat"].isin(soportadas)]["n"].sum()) / total
        arm = float(part[part["cat"].map(lambda v: MAPEO.get(v) in soportadas_arm)]["n"].sum())
        huer = float(part[part["cat"].isin(SIN_ORIGEN)]["n"].sum()) / total
        return crudo, arm / total, huer

    por_fy = []
    for fy, part in df.groupby("fy"):
        if int(fy) < 2011:
            continue
        c, a, h = _tasas(part)
        por_fy.append(
            {
                "fy": int(fy),
                "n": int(part["n"].sum()),
                "soportado_crudo": c,
                "soportado_armonizado": a,
                "sin_origen": h,
            }
        )

    reciente = df[df["fy"].between(fy_min, fy_max)]
    c, a, h = _tasas(reciente)
    return Cobertura(
        fy_desde=fy_min,
        fy_hasta=fy_max,
        n=int(reciente["n"].sum()),
        soportado_crudo=c,
        soportado_armonizado=a,
        sin_origen=h,
        min_support=MIN_SUPPORT,
        por_fy=por_fy,
    )


# --------------------------------------------------------------------------
# El costo en discriminacion
# --------------------------------------------------------------------------
@dataclass
class Costo:
    auc_crudo: float
    auc_armonizado: float
    categorias_crudo: int
    categorias_armonizado: int
    n_train: int
    n_test: int
    seed: int

    @property
    def costo_auc(self) -> float:
        return self.auc_crudo - self.auc_armonizado


def costo_de_armonizar(cfg: dict | None = None) -> tuple[Costo, dict[str, float]]:
    """Entrena el modelo de produccion dos veces: mismo split, misma semilla.

    Solo cambia UNA cosa entre las dos corridas -- el vocabulario de una variable --
    asi que la diferencia de AUC es atribuible a eso y no a la varianza del
    entrenamiento. Es el mismo principio de la ablacion del ADR 0002.
    """
    cfg = cfg or load_config()
    seed = int(cfg["project"]["random_seed"])
    spec = load_spec(cfg)
    panel = load_panel(cfg)
    sp = split_out_of_time(panel, cfg)
    tr, va, te = sp["train"], sp["valid"], sp["test"]
    # Proporciones, no solo presencia: ver Cobertura.
    vocab = tr[VARIABLE].value_counts(normalize=True, dropna=True).to_dict()

    num, cat = list(spec.numeric), list(spec.categorical)
    resultados = {}
    for etiqueta, transformar in (("crudo", False), ("armonizado", True)):
        d = {}
        for k, frame in (("tr", tr), ("va", va), ("te", te)):
            f = frame.copy()
            if transformar:
                f[VARIABLE] = armonizar(f[VARIABLE])
            d[k] = f
        modelo = GBMChallenger(num, cat, random_state=seed)
        modelo.fit(d["tr"], d["tr"][TARGET], d["va"], d["va"][TARGET])
        p = modelo.predict_proba(d["te"])
        resultados[etiqueta] = (
            discrimination(d["te"][TARGET].to_numpy(), p).auc,
            int(d["tr"][VARIABLE].nunique()),
        )

    return (
        Costo(
            auc_crudo=resultados["crudo"][0],
            auc_armonizado=resultados["armonizado"][0],
            categorias_crudo=resultados["crudo"][1],
            categorias_armonizado=resultados["armonizado"][1],
            n_train=len(tr),
            n_test=len(te),
            seed=seed,
        ),
        vocab,
    )


def main() -> int:
    cfg = load_config()
    print("=" * 90)
    print("ARMONIZAR business_age - cuanto cuesta la resolucion que se pierde")
    print("=" * 90)
    print("\nEl mapeo, categoria por categoria:")
    ancho = max(len(k) for k in MAPEO)
    for viejo, nuevo in MAPEO.items():
        marca = "  =  " if viejo == nuevo else "  ->  "
        print(f"  {viejo:{ancho}s}{marca}{nuevo}")
    print(f"\n  Sin origen en el esquema viejo: {', '.join(SIN_ORIGEN)}")
    print("  No es una antiguedad sino una forma de adquisicion. Mapearla seria")
    print("  inventar el dato, asi que queda sin soporte a proposito.")

    print("\nEntrenando dos veces (mismo split, misma semilla)...", flush=True)
    costo, vocab = costo_de_armonizar(cfg)
    cob = cobertura(vocab, cfg)

    print("\n" + "-" * 90)
    print("COSTO EN DISCRIMINACION")
    print("-" * 90)
    print(
        f"  crudo       AUC {costo.auc_crudo:.4f}   "
        f"{costo.categorias_crudo} categorias en entrenamiento"
    )
    print(
        f"  armonizado  AUC {costo.auc_armonizado:.4f}   {costo.categorias_armonizado} categorias"
    )
    print(f"  costo       {costo.costo_auc:+.4f}")

    print("\n" + "-" * 90)
    print(
        f"COBERTURA SOBRE FY{cob.fy_desde}-{cob.fy_hasta} ({cob.n:,} prestamos) - "
        f"soporte minimo {cob.min_support:.1%}"
    )
    print("-" * 90)
    print(f"  con el vocabulario crudo       {cob.soportado_crudo:6.1%}")
    print(f"  con el vocabulario armonizado  {cob.soportado_armonizado:6.1%}")
    print(f"  recuperado                     {cob.recuperado_pp:+6.1f} pp")
    print(f"  irreducible (sin origen)       {cob.sin_origen:6.1%}")
    print("\n  El acantilado, anio por anio:")
    print("    FY     prestamos   crudo   armonizado   sin origen")
    for r in cob.por_fy:
        print(
            f"    {r['fy']}  {r['n']:>10,}  {r['soportado_crudo']:6.1%}   "
            f"{r['soportado_armonizado']:8.1%}   {r['sin_origen']:8.1%}"
        )

    print("\n" + "=" * 90)
    print("LECTURA")
    print("=" * 90)
    print(
        f"  Armonizar cuesta {abs(costo.costo_auc):.4f} de AUC sobre la ventana historica\n"
        f"  y recupera {cob.recuperado_pp:.1f} pp de cobertura sobre el dato de hoy."
    )
    print("\n  Las dos versiones se publican. Elegir una y callar la otra seria")
    print("  presentar una decision de diseno como si fuera un hecho.")
    print(
        f"\n  Queda {cob.sin_origen:.1%} irreducible: es el limite de lo que un mapeo\n"
        "  puede arreglar, y la razon por la que el ADR 0011 sigue abierto en su\n"
        "  parte de fondo -- la fuente cambio de concepto, no de etiqueta."
    )

    payload = {
        "variable": VARIABLE,
        "mapeo": MAPEO,
        "destino": list(DESTINO),
        "sin_origen": list(SIN_ORIGEN),
        "vocabulario_entrenamiento": {k: round(v, 6) for k, v in sorted(vocab.items())},
        "costo": {**asdict(costo), "costo_auc": costo.costo_auc},
        "cobertura": {**asdict(cob), "recuperado_pp": cob.recuperado_pp},
        "conclusion": (
            f"Armonizar cuesta {abs(costo.costo_auc):.4f} de AUC y recupera "
            f"{cob.recuperado_pp:.1f} pp de cobertura. Queda {cob.sin_origen:.1%} "
            "irreducible porque 'Change of Ownership' no es una antiguedad."
        ),
    }
    out = repo_root() / EXPORT_PATH
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"\n  -> {EXPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
