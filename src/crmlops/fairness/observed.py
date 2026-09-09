"""Disparidad OBSERVADA en HMDA, antes de cualquier modelo.

Esto no evalua un modelo: mide lo que los prestamistas efectivamente hicieron.
Es el punto de partida obligatorio del analisis de equidad, y el orden importa.

Si se empieza por el modelo, cualquier disparidad que aparezca se lee como
"el modelo es injusto". Pero un modelo entrenado sobre decisiones historicas
puede simplemente estar reproduciendo una disparidad que ya existia. Separar
ambas preguntas -- cuanta desigualdad hay en los datos, y cuanta AGREGA el
modelo -- es la diferencia entre auditar y adivinar.

Advertencia sobre la interpretacion: HMDA no incluye puntaje de credito, que es
el determinante mas fuerte de una decision de suscripcion. Una diferencia en
tasas de denegacion NO prueba discriminacion; prueba que existe una diferencia
que hay que explicar. Los examenes de fair lending del CFPB parten de aqui, no
terminan aqui.
"""

from __future__ import annotations

import sys

import duckdb
import pandas as pd

from crmlops.config import resolve_path
from crmlops.fairness.metrics import FOUR_FIFTHS

# Categorias que no son grupos demograficos coherentes: agrupan a quienes no
# declararon, o a solicitudes conjuntas de personas de razas distintas.
NON_GROUPS = ("Race Not Available", "Joint", "Free Form Text Only")


def _shards() -> str:
    files = sorted((resolve_path("parquet") / "hmda").glob("*.parquet"))
    return "[" + ", ".join(f"'{f.as_posix()}'" for f in files) + "]"


def denial_rates_by(dimension: str, *, min_n: int = 5000) -> pd.DataFrame:
    """Tasa de denegacion por categoria de una dimension protegida."""
    listed = _shards()
    excl = ", ".join(f"'{g}'" for g in NON_GROUPS)
    return (
        duckdb.connect()
        .execute(f"""
        select
            "{dimension}"                                        as grupo,
            count(*)                                             as n,
            avg(case when action_taken = '3' then 1.0 else 0 end) as tasa_denegacion,
            median(try_cast(income as double)) * 1000            as ingreso_mediano,
            median(try_cast(loan_amount as double))              as monto_mediano
        from read_parquet({listed})
        where "{dimension}" is not null
          and "{dimension}" not in ({excl})
        group by 1
        having count(*) >= {min_n}
        order by tasa_denegacion
    """)
        .fetchdf()
    )


def disparity_over_time(dimension: str = "derived_race", *, min_n: int = 5000) -> pd.DataFrame:
    """Razon de 4/5 por anio: la disparidad se amplia o se cierra con el ciclo?"""
    listed = _shards()
    excl = ", ".join(f"'{g}'" for g in NON_GROUPS)
    raw = (
        duckdb.connect()
        .execute(f"""
        select try_cast(activity_year as int) anio, "{dimension}" grupo,
               count(*) n,
               avg(case when action_taken = '3' then 1.0 else 0 end) tasa_denegacion
        from read_parquet({listed})
        where "{dimension}" is not null and "{dimension}" not in ({excl})
        group by 1, 2
        having count(*) >= {min_n}
    """)
        .fetchdf()
    )

    rows = []
    for anio, part in raw.groupby("anio"):
        aprob = 1 - part["tasa_denegacion"]
        mejor, peor = aprob.max(), aprob.min()
        rows.append(
            {
                "anio": int(anio),
                "grupos": len(part),
                "ratio_4_5": float(peor / mejor) if mejor else float("nan"),
                "grupo_mas_denegado": part.loc[part["tasa_denegacion"].idxmax(), "grupo"],
                "brecha_pp": float(
                    (part["tasa_denegacion"].max() - part["tasa_denegacion"].min()) * 100
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("anio")


def main() -> int:
    print("=" * 86)
    print("DISPARIDAD OBSERVADA EN HMDA - lo que los prestamistas hicieron")
    print("Antes de cualquier modelo. 62.4M solicitudes, FY2020-2024.")
    print("=" * 86)

    for dim, etiqueta in (
        ("derived_race", "RAZA"),
        ("derived_ethnicity", "ETNIA"),
        ("derived_sex", "SEXO"),
    ):
        print(f"\n--- {etiqueta} ---")
        df = denial_rates_by(dim)
        if df.empty:
            print("  sin grupos por encima del minimo")
            continue
        aprob = 1 - df["tasa_denegacion"]
        ratio = float(aprob.min() / aprob.max())
        for r in df.itertuples():
            print(
                f"  {r.grupo[:44]:44s} n={r.n:>10,}  "
                f"denegacion={r.tasa_denegacion:6.2%}  "
                f"ingreso mediano=${r.ingreso_mediano:>9,.0f}"
            )
        estado = "PASA" if ratio >= FOUR_FIFTHS else "NO PASA"
        print(f"  -> razon de 4/5: {ratio:.3f}  ({estado} el umbral de {FOUR_FIFTHS})")

    print("\n" + "=" * 86)
    print("EVOLUCION DE LA DISPARIDAD RACIAL POR ANIO")
    print("=" * 86)
    ev = disparity_over_time()
    print(ev.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    out = resolve_path("exports")
    denial_rates_by("derived_race").to_csv(out / "observed_disparity_race.csv", index=False)
    ev.to_csv(out / "observed_disparity_over_time.csv", index=False)

    print("\n" + "=" * 86)
    print("COMO LEER ESTO")
    print("=" * 86)
    print("  HMDA no incluye puntaje de credito, el determinante mas fuerte de una")
    print("  decision de suscripcion. Una diferencia en tasas de denegacion NO prueba")
    print("  discriminacion: prueba que hay una diferencia que exige explicacion.")
    print("  Un examen de fair lending del CFPB EMPIEZA aqui; no termina aqui.")
    print("\n  Estas cifras son la LINEA BASE. La pregunta del modelo es distinta:")
    print("  cuanta disparidad AGREGA sobre la que ya existe en los datos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
