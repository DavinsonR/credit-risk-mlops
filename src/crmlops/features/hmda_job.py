"""El mismo trabajo de features, en dos motores.

Especifica UNA transformacion --limpieza, derivacion y agregacion sobre el panel
HMDA-- e implementa la misma logica en DuckDB y en PySpark.

POR QUE ESTA COMPARACION VALE ALGO. Un benchmark donde los dos motores producen
resultados distintos no mide velocidad: mide dos programas diferentes. Por eso
`compare_outputs` verifica igualdad numerica antes de reportar cualquier tiempo.
Si los resultados difieren, el benchmark se declara invalido.

QUE SE ESPERA. En un solo nodo, DuckDB deberia ganar con holgura: no paga
arranque de JVM, ni serializacion, ni planificacion distribuida. Spark existe
para cuando el dataset no cabe en una maquina. Publicar ese resultado -- en vez
de forzar una victoria de la herramienta de moda -- es el punto del ejercicio.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from crmlops.config import resolve_path

# HMDA codifica DTI y LTV como texto con rangos ("20%-<30%"), asi que la logica
# de limpieza no es trivial y el benchmark no queda midiendo solo lectura de IO.
JOB_DESCRIPTION = """
1. Leer todas las particiones Parquet de HMDA.
2. Castear montos e ingresos, que vienen como texto.
3. Derivar: tasa prestamo/ingreso, indicador de denegacion, tramo de monto.
4. Filtrar registros con monto e ingreso validos.
5. Agregar por anio x estado x raza derivada: n, tasa de denegacion,
   monto medio, ingreso medio.
"""


@dataclass
class BackendResult:
    backend: str
    seconds: float
    rows_in: int
    rows_out: int
    frame: pd.DataFrame


def hmda_glob() -> str:
    return (resolve_path("parquet") / "hmda" / "*.parquet").as_posix()


def resolve_shards() -> list[str]:
    """Lista CONCRETA de archivos, fijada una sola vez.

    Los dos motores tienen que leer exactamente el mismo conjunto. Con un glob,
    cada uno lo expande cuando le toca correr; si el directorio se esta
    escribiendo --por ejemplo, una descarga en curso-- ven conjuntos distintos y
    la verificacion de equivalencia falla por una razon que no tiene nada que ver
    con los motores.
    """
    files = sorted((resolve_path("parquet") / "hmda").glob("*.parquet"))
    return [f.as_posix() for f in files]


def shard_count() -> int:
    return len(resolve_shards())


# --------------------------------------------------------------------------
# DuckDB
# --------------------------------------------------------------------------
def run_duckdb(shards: list[str] | None = None) -> BackendResult:
    import time

    import duckdb

    shards = shards if shards is not None else resolve_shards()
    listed = "[" + ", ".join(f"'{f}'" for f in shards) + "]"
    con = duckdb.connect()
    sql = f"""
    with base as (
        select
            try_cast(activity_year as integer)      as year,
            state_code                              as state,
            derived_race                            as race,
            try_cast(loan_amount as double)         as loan_amount,
            try_cast(income as double) * 1000       as income,
            case when action_taken = '3' then 1 else 0 end as denied
        from read_parquet({listed})
    ),
    clean as (
        select *,
               loan_amount / nullif(income, 0) as loan_to_income,
               case when loan_amount < 150000 then 'bajo'
                    when loan_amount < 400000 then 'medio'
                    else 'alto' end as tramo
        from base
        where loan_amount > 0 and income > 0
    )
    select year, state, race, tramo,
           count(*)                as n,
           avg(denied)             as tasa_denegacion,
           avg(loan_amount)        as monto_medio,
           avg(income)             as ingreso_medio,
           avg(loan_to_income)     as prestamo_ingreso_medio
    from clean
    group by 1, 2, 3, 4
    order by 1, 2, 3, 4
    """
    t0 = time.perf_counter()
    frame = con.execute(sql).fetchdf()
    secs = time.perf_counter() - t0
    rows_in = con.execute(f"select count(*) from read_parquet({listed})").fetchone()[0]
    return BackendResult("duckdb", secs, int(rows_in), len(frame), frame)


# --------------------------------------------------------------------------
# PySpark
# --------------------------------------------------------------------------
def _ensure_java() -> None:
    """Apunta JAVA_HOME al JDK local del proyecto si no hay uno en el sistema."""
    import os
    import shutil

    if os.environ.get("JAVA_HOME") or shutil.which("java"):
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from bootstrap_jdk import jdk_home

    home = jdk_home()
    if home is None:
        raise RuntimeError("No hay JDK. Correr: uv run python scripts/bootstrap_jdk.py")
    os.environ["JAVA_HOME"] = str(home)
    os.environ["PATH"] = f"{home / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"


def run_spark(shards: list[str] | None = None, *, shuffle_partitions: int = 8) -> BackendResult:
    import time

    _ensure_java()

    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    shards = shards if shards is not None else resolve_shards()
    spark = (
        SparkSession.builder.appName("hmda-benchmark")
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", shuffle_partitions)
        .config("spark.driver.memory", "4g")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    t0 = time.perf_counter()
    df = spark.read.parquet(*shards)
    # try_cast, no cast. HMDA codifica los numericos faltantes como el texto
    # 'NA', y las semanticas difieren: try_cast de DuckDB devuelve NULL, mientras
    # que cast de Spark 4 LANZA (modo ANSI activado por defecto desde Spark 4).
    # Usar try_cast explicito hace las dos implementaciones equivalentes POR
    # CONSTRUCCION, en vez de depender de spark.sql.ansi.enabled=false, que es un
    # flag de sesion que alguien puede cambiar sin notar que rompe la comparacion.
    base = df.select(
        F.expr("try_cast(activity_year as int)").alias("year"),
        F.col("state_code").alias("state"),
        F.col("derived_race").alias("race"),
        F.expr("try_cast(loan_amount as double)").alias("loan_amount"),
        (F.expr("try_cast(income as double)") * 1000).alias("income"),
        F.when(F.col("action_taken") == "3", 1).otherwise(0).alias("denied"),
    )
    clean = (
        base.where((F.col("loan_amount") > 0) & (F.col("income") > 0))
        .withColumn("loan_to_income", F.col("loan_amount") / F.col("income"))
        .withColumn(
            "tramo",
            F.when(F.col("loan_amount") < 150000, "bajo")
            .when(F.col("loan_amount") < 400000, "medio")
            .otherwise("alto"),
        )
    )
    agg = (
        clean.groupBy("year", "state", "race", "tramo")
        .agg(
            F.count(F.lit(1)).alias("n"),
            F.avg("denied").alias("tasa_denegacion"),
            F.avg("loan_amount").alias("monto_medio"),
            F.avg("income").alias("ingreso_medio"),
            F.avg("loan_to_income").alias("prestamo_ingreso_medio"),
        )
        .orderBy("year", "state", "race", "tramo")
    )
    frame = agg.toPandas()
    secs = time.perf_counter() - t0
    rows_in = df.count()
    spark.stop()
    return BackendResult("pyspark", secs, int(rows_in), len(frame), frame)


# --------------------------------------------------------------------------
# Verificacion de equivalencia
# --------------------------------------------------------------------------
KEYS = ["year", "state", "race", "tramo"]
METRICS = ["n", "tasa_denegacion", "monto_medio", "ingreso_medio", "prestamo_ingreso_medio"]


def compare_outputs(a: pd.DataFrame, b: pd.DataFrame, tol: float = 1e-6) -> list[str]:
    """Diferencias entre las salidas de ambos motores. Vacia = equivalentes."""
    problems: list[str] = []
    if len(a) != len(b):
        problems.append(f"filas distintas: {len(a)} vs {len(b)}")

    ja = a.set_index(KEYS).sort_index()
    jb = b.set_index(KEYS).sort_index()
    if not ja.index.equals(jb.index):
        solo_a = len(ja.index.difference(jb.index))
        solo_b = len(jb.index.difference(ja.index))
        problems.append(f"grupos distintos: {solo_a} solo en A, {solo_b} solo en B")
        comunes = ja.index.intersection(jb.index)
        ja, jb = ja.loc[comunes], jb.loc[comunes]

    for m in METRICS:
        if m not in ja.columns or m not in jb.columns:
            continue
        diff = (ja[m].astype(float) - jb[m].astype(float)).abs()
        # tolerancia relativa para promedios grandes, absoluta para tasas
        escala = ja[m].astype(float).abs().clip(lower=1.0)
        peor = float((diff / escala).max())
        if peor > tol:
            problems.append(f"{m}: diferencia relativa maxima {peor:.2e} > {tol:g}")
    return problems


def write_report(
    results: list[BackendResult], problems: list[str], path: Path | None = None
) -> Path:
    path = path or (resolve_path("exports") / "backend_benchmark.csv")
    frame = pd.DataFrame(
        [
            {
                "backend": r.backend,
                "segundos": round(r.seconds, 2),
                "filas_entrada": r.rows_in,
                "grupos_salida": r.rows_out,
                "equivalente": not problems,
            }
            for r in results
        ]
    )
    frame.to_csv(path, index=False)
    return path
