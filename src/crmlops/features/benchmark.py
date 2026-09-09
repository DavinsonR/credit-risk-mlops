"""Benchmark DuckDB vs PySpark sobre el mismo trabajo de features.

El resultado esperado es que DuckDB gane en un solo nodo. Publicarlo asi -- en
vez de forzar una victoria de la herramienta de moda -- es el punto: elegir el
motor correcto para el tamano real del problema es criterio de ingenieria, y vale
mas que saber usar el mas grande.
"""

from __future__ import annotations

import sys

from crmlops.features.hmda_job import (
    JOB_DESCRIPTION,
    compare_outputs,
    resolve_shards,
    run_duckdb,
    run_spark,
    write_report,
)


def main() -> int:
    # Se fija la lista UNA vez y se pasa a ambos motores: si el directorio
    # cambiara entre corridas, la comparacion mediria otra cosa.
    shards = resolve_shards()
    n_shards = len(shards)
    if n_shards == 0:
        print("No hay particiones HMDA. Correr primero la adquisicion.")
        return 1

    print("=" * 78)
    print("BENCHMARK DE BACKENDS - DuckDB vs PySpark")
    print("=" * 78)
    print(f"Particiones: {n_shards}")
    print(f"Ruta: {shards[0].rsplit(chr(47), 1)[0] if shards else '-'}")
    print(f"\nTrabajo:{JOB_DESCRIPTION}")

    print("Ejecutando DuckDB...", flush=True)
    duck = run_duckdb(shards)
    print(f"  {duck.seconds:6.2f}s  {duck.rows_in:,} filas -> {duck.rows_out:,} grupos")

    try:
        print("\nEjecutando PySpark...", flush=True)
        spark = run_spark(shards)
        print(f"  {spark.seconds:6.2f}s  {spark.rows_in:,} filas -> {spark.rows_out:,} grupos")
    except Exception as exc:  # JDK ausente o Spark mal configurado
        print(f"  PySpark no disponible: {type(exc).__name__}: {exc}")
        print("\n  Requiere un JDK. El benchmark queda incompleto.")
        write_report([duck], ["pyspark no ejecutado"])
        return 1

    print("\n" + "=" * 78)
    print("EQUIVALENCIA DE RESULTADOS")
    print("=" * 78)
    problems = compare_outputs(duck.frame, spark.frame)
    if problems:
        print("  LOS MOTORES NO PRODUCEN EL MISMO RESULTADO:")
        for p in problems:
            print(f"    - {p}")
        print("\n  El benchmark queda INVALIDO: comparar tiempos de dos programas")
        print("  distintos no mide velocidad, mide otra cosa.")
    else:
        print(f"  Identicos: {duck.rows_out:,} grupos coinciden en las 5 metricas.")

    print("\n" + "=" * 78)
    print("TIEMPOS")
    print("=" * 78)
    ratio = spark.seconds / duck.seconds if duck.seconds else float("inf")
    print(f"  DuckDB   {duck.seconds:7.2f}s")
    print(f"  PySpark  {spark.seconds:7.2f}s   ({ratio:.1f}x mas lento)")
    print(f"\n  {duck.rows_in:,} filas en un solo nodo.")
    print("  Spark paga arranque de JVM, serializacion y planificacion distribuida;")
    print("  DuckDB no. La ventaja de Spark aparece cuando el dato no cabe en una")
    print("  maquina, no antes.")

    path = write_report([duck, spark], problems)
    print(f"\nExportado a {path.name}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
