"""Madurez de la etiqueta: que se puede monitorear y que no.

EL PROBLEMA, EN UN NUMERO. La mediana entre aprobacion y charge-off en el 7(a) es
de **51 meses**. A los 12 meses solo se ha manifestado alrededor del 1% de los
charge-offs que esa cosecha acabara teniendo. Medir AUC o tasa de fallo sobre las
originaciones del ultimo trimestre no mide el modelo: mide cuanto tiempo ha
pasado.

POR QUE ESTO ES UN MODULO Y NO UNA NOTA. Un tablero de monitoreo que compare la
tasa de charge-off de FY2023 contra la de FY2013 va a mostrar una alarma. Con el
vintage asof_260630, FY2023 tiene 17.4% de sus prestamos resueltos y FY2013 tiene
83.5%: no se esta comparando riesgo, se esta comparando antiguedad. La comparacion
correcta fija la VENTANA DE OBSERVACION --solo lo resuelto dentro de los primeros
M meses desde la aprobacion-- y entonces todas las cosechas se miran al mismo
punto de su vida.

LA TRAMPA QUE ESTE MODULO SE NIEGA A CAER. Una cosecha no puede reportar una
ventana que todavia no alcanzo. Si FY2024 se aprobo hasta septiembre de 2024 y el
vintage corta en junio de 2026, esa cosecha tiene 21 meses observables: pedirle su
tasa a 24 o 48 meses devuelve, en una implementacion ingenua, el mismo valor que a
21 --porque no hay nada mas que contar-- y en la tabla se lee como una curva que
se aplana. Aqui esas celdas quedan vacias y se declaran no observables. La primera
version de este analisis, en un script de exploracion, SI cayo en eso.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from crmlops.config import load_config, repo_root

RAW_GLOB = "data/raw/FOIA_7a_FY*.csv"

# Ventanas de observacion en meses desde la aprobacion. 12 y 24 son las que un
# monitoreo trimestral puede usar de verdad; 36 y 48 sirven para confirmar la
# tendencia una vez que la cosecha madura.
DEFAULT_WINDOWS = (12, 24, 36, 48, 60)

RESOLVED = ("P I F", "CHGOFF")  # 'P I F' viene con espacios en la fuente
CHARGED_OFF = "CHGOFF"


def _reader(source_glob: str | None = None) -> str:
    raw = source_glob or (repo_root() / RAW_GLOB).as_posix()
    return (
        f"read_csv('{raw}', union_by_name=true, ignore_errors=true, "
        "sample_size=200000, all_varchar=true)"
    )


def _base_view(con: duckdb.DuckDBPyConnection, source_glob: str | None = None) -> None:
    """Prestamos resueltos, con la fecha en que se resolvieron."""
    con.execute(f"""
    create or replace view prestamos as
    select
        try_cast(ApprovalFY as integer)   as fy,
        try_cast(ApprovalDate as date)    as aprobado,
        trim(LoanStatus)                  as estado,
        case when trim(LoanStatus) = '{CHARGED_OFF}' then try_cast(ChargeOffDate as date)
             when trim(LoanStatus) = 'P I F'         then try_cast(PaidInFullDate as date)
        end                               as resuelto_en
    from {_reader(source_glob)}
    where try_cast(GrossApproval as double) > 0
      and trim(LoanStatus) in ('P I F', '{CHARGED_OFF}')
    """)


def as_of_date(source_glob: str | None = None) -> date:
    """Fecha de corte del vintage, leida del propio dato.

    Se toma de la columna AsOfDate y no del nombre del archivo: el sufijo
    `asof_YYMMDD` es una convencion del portal y ya cambio una vez (ADR 0001).
    """
    con = duckdb.connect()
    valor = con.execute(f"""
        select max(try_cast(AsOfDate as date)) from {_reader(source_glob)}
    """).fetchone()[0]
    if valor is None:
        raise RuntimeError("El vintage no trae AsOfDate legible; no se puede fechar el corte.")
    return valor


@dataclass(frozen=True)
class Observabilidad:
    """Hasta que ventana puede mirarse una cosecha con este vintage."""

    fy: int
    ultima_aprobacion: date
    meses_observables: int

    def alcanza(self, ventana_meses: int) -> bool:
        """Estricto a proposito: TODOS los prestamos de la cosecha deben haber
        tenido la ventana completa.

        La alternativa --contar los que si la alcanzaron-- mete sesgo de
        composicion dentro de la cosecha: para FY2024 solo entrarian las
        aprobaciones de octubre a diciembre, que no son una muestra de la cosecha.
        """
        return self.meses_observables >= ventana_meses


def observabilidad(source_glob: str | None = None) -> dict[int, Observabilidad]:
    con = duckdb.connect()
    _base_view(con, source_glob)
    corte = as_of_date(source_glob)
    df = con.execute("""
        select fy, max(aprobado) as ultima
        from prestamos where aprobado is not null and fy is not null
        group by fy order by fy
    """).df()
    salida: dict[int, Observabilidad] = {}
    for _, r in df.iterrows():
        ultima = pd.Timestamp(r["ultima"]).date()
        meses = (corte.year - ultima.year) * 12 + (corte.month - ultima.month)
        salida[int(r["fy"])] = Observabilidad(int(r["fy"]), ultima, meses)
    return salida


def cohort_resolution(source_glob: str | None = None) -> pd.DataFrame:
    """Que fraccion de cada cosecha ya tiene resultado final."""
    con = duckdb.connect()
    return con.execute(f"""
        with todas as (
            select try_cast(ApprovalFY as integer) as fy, trim(LoanStatus) as estado
            from {_reader(source_glob)}
            where try_cast(GrossApproval as double) > 0
        )
        select
            fy,
            count(*) as n,
            round(100.0 * sum(case when estado in {RESOLVED} then 1 else 0 end)
                  / count(*), 1) as pct_resuelto,
            round(100.0 * sum(case when estado = '{CHARGED_OFF}' then 1 else 0 end)
                  / nullif(sum(case when estado in {RESOLVED} then 1 else 0 end), 0), 2)
                  as tasa_chgoff_entre_resueltos
        from todas
        where fy is not null
        group by fy order by fy
    """).df()


def emergence_curve(
    source_glob: str | None = None, cohorts: tuple[int, int] = (2005, 2018)
) -> pd.DataFrame:
    """Que porcentaje de los charge-offs de una cosecha ya se ve a los M meses.

    Solo tiene sentido en cosechas maduras: es la referencia de cuanto hay que
    esperar, medida donde ya se conoce la respuesta.
    """
    con = duckdb.connect()
    _base_view(con, source_glob)
    tramos = ", ".join(
        f"round(100.0 * sum(case when meses <= {m} then 1 else 0 end) / count(*), 1) as pct_{m}m"
        for m in (12, 24, 36, 48, 60, 84, 120)
    )
    return con.execute(f"""
        with co as (
            select fy, datediff('month', aprobado, resuelto_en) as meses
            from prestamos
            where estado = '{CHARGED_OFF}' and aprobado is not null and resuelto_en is not null
              and datediff('month', aprobado, resuelto_en) between 0 and 400
              and fy between {cohorts[0]} and {cohorts[1]}
        )
        select fy, count(*) as n_chargeoffs, {tramos}
        from co group by fy order by fy
    """).df()


def months_to_chargeoff(source_glob: str | None = None) -> pd.DataFrame:
    """Distribucion del tiempo entre aprobacion y charge-off."""
    con = duckdb.connect()
    _base_view(con, source_glob)
    return con.execute(f"""
        select
            count(*) as n,
            round(quantile_cont(meses, 0.10), 1) as p10,
            round(quantile_cont(meses, 0.25), 1) as p25,
            round(quantile_cont(meses, 0.50), 1) as mediana,
            round(quantile_cont(meses, 0.75), 1) as p75,
            round(quantile_cont(meses, 0.90), 1) as p90
        from (
            select datediff('month', aprobado, resuelto_en) as meses
            from prestamos
            where estado = '{CHARGED_OFF}' and aprobado is not null and resuelto_en is not null
              and datediff('month', aprobado, resuelto_en) between 0 and 400
        )
    """).df()


def matched_maturity(
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    source_glob: str | None = None,
    min_fy: int = 2005,
) -> pd.DataFrame:
    """Tasa de charge-off por cosecha a madurez pareja.

    Devuelve formato largo: (fy, ventana_meses, n_resueltos, n_chargeoffs, tasa,
    observable). Donde la cosecha no alcanza la ventana, los tres numeros son NaN
    y `observable` es False.

    NO ES UNA ESTIMACION DE LA TASA FINAL, y conviene tenerlo claro porque el
    numero invita a leerse asi. Es un cociente cuyo numerador y denominador crecen
    los dos con M, y no es monotono: en las cosechas de entrenamiento sube hasta
    7.22% a 48 meses y baja a 7.14% a 60, con tasa final 6.79%. Los charge-offs
    aparecen antes que los pagos completos, asi que el cociente sobrepasa y luego
    converge.

    Sirve para lo que se construyo: comparar cosechas distintas EN LA MISMA
    ventana. Usarlo como pronostico del resultado final seria otra cosa, y estaria
    mal. Un test lo fija (`test_maturity.py`).
    """
    con = duckdb.connect()
    _base_view(con, source_glob)
    obs = observabilidad(source_glob)

    piezas = []
    for m in windows:
        piezas.append(f"""
        select
            fy,
            {m} as ventana_meses,
            sum(case when datediff('month', aprobado, resuelto_en) <= {m} then 1 else 0 end)
                as n_resueltos,
            sum(case when datediff('month', aprobado, resuelto_en) <= {m}
                      and estado = '{CHARGED_OFF}' then 1 else 0 end) as n_chargeoffs,
            100.0 * sum(case when datediff('month', aprobado, resuelto_en) <= {m}
                              and estado = '{CHARGED_OFF}' then 1 else 0 end)
                / nullif(sum(case when datediff('month', aprobado, resuelto_en) <= {m}
                              then 1 else 0 end), 0) as tasa
        from prestamos
        where aprobado is not null and resuelto_en is not null and fy >= {min_fy}
        group by fy""")

    df = con.execute("\nunion all\n".join(piezas)).df()
    df["observable"] = [
        bool(obs.get(int(fy)) and obs[int(fy)].alcanza(int(v)))
        for fy, v in zip(df["fy"], df["ventana_meses"], strict=True)
    ]
    # La cosecha que no alcanzo la ventana NO reporta numero. Dejar el valor
    # calculado seria repetir el de la ultima ventana que si alcanzo y leerse
    # como una meseta.
    df.loc[~df["observable"], ["tasa", "n_resueltos", "n_chargeoffs"]] = pd.NA
    return df.sort_values(["fy", "ventana_meses"]).reset_index(drop=True)


def reference_rates(
    windows: tuple[int, ...] = DEFAULT_WINDOWS, source_glob: str | None = None
) -> dict[int, float]:
    """Tasa a madurez pareja de las cosechas de ENTRENAMIENTO: la referencia.

    Es contra esto que se compara una cosecha nueva, y no contra su propia tasa
    cruda, que depende de cuanto lleva viva.
    """
    cfg = load_config()
    tr = cfg["splits"]["train"]
    con = duckdb.connect()
    _base_view(con, source_glob)
    salida: dict[int, float] = {}
    for m in windows:
        valor = con.execute(f"""
            select 100.0 * sum(case when datediff('month', aprobado, resuelto_en) <= {m}
                                     and estado = '{CHARGED_OFF}' then 1 else 0 end)
                   / nullif(sum(case when datediff('month', aprobado, resuelto_en) <= {m}
                                     then 1 else 0 end), 0)
            from prestamos
            where aprobado is not null and resuelto_en is not null
              and fy between {tr["start"]} and {tr["end"]}
        """).fetchone()[0]
        if valor is not None:
            salida[m] = round(float(valor), 2)
    return salida


def main() -> None:
    corte = as_of_date()
    print("=" * 96)
    print(f"MADUREZ DE LA ETIQUETA — vintage con corte {corte}")
    print("=" * 96)

    print("\nMeses entre aprobacion y charge-off:")
    print(months_to_chargeoff().to_string(index=False))

    print("\n" + "=" * 96)
    print("CUANTO DE UNA COSECHA YA SE VE (% de sus charge-offs finales)")
    print("=" * 96)
    print(emergence_curve().to_string(index=False))

    print("\n" + "=" * 96)
    print("RESOLUCION POR COSECHA")
    print("=" * 96)
    res = cohort_resolution()
    print(res[res.fy >= 2011].to_string(index=False))

    ref = reference_rates()
    print("\n" + "=" * 96)
    print("TASA DE CHARGE-OFF A MADUREZ PAREJA")
    print("=" * 96)
    print(
        "  Referencia (cosechas de entrenamiento): "
        + ", ".join(f"{m}m={t}%" for m, t in ref.items())
    )
    print("  Vacio = la cosecha aun no alcanza esa ventana con este vintage.\n")

    mm = matched_maturity()
    tabla = mm[mm.fy >= 2011].pivot_table(
        index="fy", columns="ventana_meses", values="tasa", dropna=False
    )
    print(tabla.round(2).to_string())

    salida = repo_root() / "exports" / "maturity.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(
            {
                "as_of": corte.isoformat(),
                "meses_a_chargeoff": months_to_chargeoff().to_dict("records")[0],
                "referencia_madurez_pareja": ref,
                "resolucion_por_cosecha": res.to_dict("records"),
                "madurez_pareja": mm.astype(object).where(mm.notna(), None).to_dict("records"),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nExportado a {salida}")


if __name__ == "__main__":
    main()
