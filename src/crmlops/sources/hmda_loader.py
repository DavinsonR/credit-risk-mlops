"""Panel HMDA listo para modelar.

Separa explicitamente dos bloques que NUNCA deben mezclarse:

  - `FEATURES` -- lo que el modelo ve.
  - `PROTECTED` -- raza, etnia, sexo y edad. Se cargan en el panel para MEDIR
    equidad y jamas se pasan al modelo. Ver docs/adr/0006.

PARSEO NO TRIVIAL. HMDA no guarda numeros limpios:

  - `debt_to_income_ratio` viene mezclado. Por exigencia regulatoria se reporta
    EXACTO solo entre 36 y 49 ("44", "49"), y en rangos fuera de ese tramo
    ("<20%", "30%-<36%", ">60%"). Hay que mapear ambos a un valor numerico y
    aceptar que la precision no es uniforme a lo largo de la escala.
  - `income` esta en miles de dolares y admite negativos (perdidas declaradas).
  - `loan_to_value_ratio` y `property_value` traen 'NA' y 'Exempt' como texto.
  - `applicant_age` usa 8888 para "no proporcionado".

MUESTREO -- dos errores antes de acertar. El panel completo son 62.4M filas.

  1. La primera version traia todo a pandas y muestreaba despues: materializar
     62M filas para descartar el 90% es trabajo puro desperdiciado.
  2. La segunda uso `using sample N rows (reservoir)`. El muestreo por reservorio
     tiene que mantener las N filas elegidas en memoria durante todo el escaneo:
     con N=5M sobre 37M filas llego a 7 GB de RAM y no termino en 45 minutos.

La version que funciona usa muestreo BERNOULLI por porcentaje, que es en
streaming: cada fila se acepta o descarta al vuelo, sin estado acumulado. Y las
particiones se podan por nombre de archivo antes de tocar disco.

Se muestrean los TRES splits, no solo el de entrenamiento. Con 2M filas de prueba,
el grupo protegido mas pequeno (2 o mas razas minoritarias, ~0.2% de las
solicitudes) conserva ~4,000 observaciones: error estandar de ~0.8 puntos
porcentuales sobre su tasa de denegacion. Suficiente para el umbral de 4/5, que
se juega en decimas.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from crmlops.config import load_config, resolve_path

TARGET = "is_denied"
YEAR = "activity_year"

# Punto medio de cada tramo de DTI. Los valores exactos (36-49) se parsean como
# numero; estos cubren los tramos que HMDA agrupa.
DTI_BUCKETS = {
    "<20%": 15.0,
    "20%-<30%": 25.0,
    "30%-<36%": 33.0,
    "50%-60%": 55.0,
    ">60%": 65.0,
}

AGE_BUCKETS = {
    "<25": 22.0,
    "25-34": 30.0,
    "35-44": 40.0,
    "45-54": 50.0,
    "55-64": 60.0,
    "65-74": 70.0,
    ">74": 80.0,
}

NUMERIC_FEATURES = [
    "loan_amount",
    "income",
    "dti",
    "ltv",
    "property_value",
    "loan_to_income",
    "log_loan_amount",
    "tract_to_msa_income_percentage",
    "tract_owner_occupied_units",
    "msa_median_income",
]

CATEGORICAL_FEATURES = [
    "state_code",
    "loan_type",
    "loan_purpose",
    "lien_status",
    "occupancy_type",
    "construction_method",
    "conforming_loan_limit",
    "preapproval",
    "open_end_line",
    "business_purpose",
    "dwelling_category",
    "loan_product_type",
    "submission_of_application",
]

PROTECTED = ["race", "ethnicity", "sex", "age_bucket", "age"]

FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _shards(years: tuple[int, ...] | None = None, root: Path | None = None) -> str:
    """Archivos a leer, filtrados por anio DESDE EL NOMBRE.

    Los shards se llaman hmda_YYYY_SS.parquet, asi que se puede podar por
    particion antes de tocar disco. Sin esto, cargar el split de prueba leia y
    transformaba las 62.4M filas para despues descartar el 88%: la primera
    version tardaba mas de 15 minutos y no terminaba.
    """
    root = root or (resolve_path("parquet") / "hmda")
    files = sorted(root.glob("*.parquet"))
    if years:
        wanted = {str(y) for y in years}
        files = [f for f in files if f.stem.split("_")[1] in wanted]
    if not files:
        raise FileNotFoundError(
            "No hay particiones HMDA para esos anios. Correr: uv run python -m crmlops.sources.hmda"
        )
    return "[" + ", ".join(f"'{f.as_posix()}'" for f in files) + "]"


def _dti_case() -> str:
    """SQL que unifica tramos de texto y valores exactos en una sola escala."""
    whens = "\n".join(
        f"                 when debt_to_income_ratio = '{k}' then {v}"
        for k, v in DTI_BUCKETS.items()
    )
    return f"""case
{whens}
                 else try_cast(debt_to_income_ratio as double)
             end"""


def _age_case() -> str:
    whens = "\n".join(
        f"                 when applicant_age = '{k}' then {v}" for k, v in AGE_BUCKETS.items()
    )
    # 8888 = "no proporcionado". Dejarlo como numero lo convertiria en un
    # outlier de 8888 anios que el modelo tomaria en serio.
    return f"""case
{whens}
                 else null
             end"""


def build_query(years: tuple[int, ...] | None = None, root: Path | None = None) -> str:
    """Query del panel para los anios dados. El muestreo se aplica afuera.

    `root` permite apuntar a un directorio de fixtures en CI, donde no existen
    los 260 shards reales.
    """
    listed = _shards(years, root)
    return f"""
    select
        try_cast(activity_year as int)                       as activity_year,
        case when action_taken = '3' then 1 else 0 end       as is_denied,

        -- clases protegidas: para MEDIR, nunca como features
        derived_race                                          as race,
        derived_ethnicity                                     as ethnicity,
        derived_sex                                           as sex,
        applicant_age                                         as age_bucket,
        {_age_case()}                                         as age,

        -- numericas
        try_cast(loan_amount as double)                       as loan_amount,
        try_cast(income as double) * 1000                     as income,
        {_dti_case()}                                         as dti,
        try_cast(loan_to_value_ratio as double)               as ltv,
        try_cast(property_value as double)                    as property_value,
        try_cast(loan_amount as double)
            / nullif(try_cast(income as double) * 1000, 0)    as loan_to_income,
        ln(nullif(try_cast(loan_amount as double), 0))        as log_loan_amount,
        try_cast(tract_to_msa_income_percentage as double)    as tract_to_msa_income_percentage,
        try_cast(tract_owner_occupied_units as double)        as tract_owner_occupied_units,
        try_cast(ffiec_msa_md_median_family_income as double) as msa_median_income,

        -- categoricas
        state_code, loan_type, loan_purpose, lien_status, occupancy_type,
        construction_method, conforming_loan_limit, preapproval,
        "open-end_line_of_credit"                             as open_end_line,
        business_or_commercial_purpose                        as business_purpose,
        derived_dwelling_category                             as dwelling_category,
        derived_loan_product_type                             as loan_product_type,
        submission_of_application
    from read_parquet({listed})
    where try_cast(loan_amount as double) > 0
      and try_cast(income as double) is not null
    """


def load_split(
    name: str,
    *,
    pct: float | None = None,
    seed: int = 42,
    cfg: dict | None = None,
    root: Path | None = None,
) -> pd.DataFrame:
    """Carga UN split, con muestreo Bernoulli en DuckDB."""
    cfg = cfg or load_config()
    window = cfg["sources"]["hmda"]["splits"][name]
    # Poda por particion: los shards se llaman hmda_YYYY_SS.parquet, asi que se
    # leen solo los anios del split en vez de escanear las 62.4M filas.
    years = tuple(range(window["start"], window["end"] + 1))
    query = build_query(years, root)
    if pct and pct < 100:
        # Bernoulli, no reservorio: decide fila por fila sin acumular estado.
        # El reservorio mantiene las N filas elegidas en memoria durante todo el
        # escaneo, y con N=5M sobre 37M filas llego a 7 GB sin terminar.
        query += f" using sample {pct}% (bernoulli, {seed})"

    con = duckdb.connect()
    con.execute("pragma disable_progress_bar")
    df = con.execute(query).fetchdf()
    # Las categoricas como texto dominan la memoria; category las colapsa a
    # codigos enteros mas un diccionario.
    for c in CATEGORICAL_FEATURES:
        if c in df.columns:
            df[c] = df[c].astype("category")
    return df


def load_splits(*, seed: int = 42, cfg: dict | None = None) -> dict[str, pd.DataFrame]:
    """Los tres splits, con el porcentaje de muestreo declarado en config."""
    cfg = cfg or load_config()
    pcts = cfg["sources"]["hmda"]["sample_pct"]
    return {
        name: load_split(name, pct=pcts[name], seed=seed, cfg=cfg)
        for name in ("train", "valid", "test")
    }


def frame_for_model(df: pd.DataFrame) -> pd.DataFrame:
    """Solo las features. Falla si una protegida se coló."""
    leaked = sorted(set(FEATURES) & set(PROTECTED))
    if leaked:
        raise AssertionError(f"FUGA: clase protegida declarada como feature: {leaked}")
    out = df[FEATURES].copy()
    for c in CATEGORICAL_FEATURES:
        out[c] = out[c].astype("category")
    return out
