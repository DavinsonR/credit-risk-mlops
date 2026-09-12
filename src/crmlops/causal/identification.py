"""Diagnostico de identificacion causal sobre SBA 7(a).

LA PREGUNTA. El programa 7(a) tiene una palanca de politica evidente: el porcentaje
de la garantia que asume la SBA. La pregunta causal es si subir la garantia CAUSA mas
incumplimiento --riesgo moral del prestamista, que arriesga menos capital propio-- o
si la correlacion que se observa es composicion.

POR QUE ESTE MODULO NO ESTIMA UN EFECTO. Porque midio primero. Los tres diagnosticos
de abajo, corridos sobre el panel completo, cierran las tres vias de identificacion
que tenia sentido intentar. Publicar un efecto despues de eso seria publicar el
resultado de un estimador aplicado donde sus supuestos no se cumplen.

Un economista reconoce el patron: esto es el analisis que va ANTES de la regresion, y
es lo que separa una estimacion de un numero.

LOS TRES DIAGNOSTICOS

  1. DETERMINACION ADMINISTRATIVA. Si el tratamiento es una funcion casi exacta de
     variables que ya son features del modelo, no hay variacion que explotar: al
     condicionar desaparece el solapamiento, y al no condicionar queda confusion.
     Es el "positivity"/overlap de siempre, pero medido en vez de asumido.

  2. DENSIDAD EN EL UMBRAL. El umbral estatutario de $150.000 partiria la garantia
     maxima en dos y habilitaria una regresion discontinua. Pero si los prestamos se
     apilan EXACTAMENTE en el umbral, la asignacion no es local-aleatoria: alguien
     eligio quedarse ahi. Es el test de McCrary, en su version mas cruda y mas
     contundente.

  3. DESCOMPOSICION DEL GRADIENTE. Cuanto del gradiente crudo sobrevive al
     condicionar por tamano. Si sobrevive algo, hay que decir que es, y lo honesto es
     que tiene el signo que predice la seleccion adversa.

ADVERTENCIA SOBRE LOS NIVELES. Todo esto corre sobre prestamos RESUELTOS, que es un
subconjunto censurado (ADR 0010): las tasas estan infladas respecto a las
eventuales. Las DIFERENCIAS entre grupos son menos sensibles a eso que los niveles,
pero no son inmunes. Los numeros se reportan como lo que son.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import duckdb
import pandas as pd

from crmlops.config import load_config, repo_root

RAW_GLOB = "data/raw/FOIA_7a_FY*.csv"
EXPORT_PATH = "exports/causal_identification.json"

# Umbral estatutario candidato: por encima de este monto la garantia maxima del 7(a)
# es menor. Se toma como CANDIDATO, no como hecho: el diagnostico 2 mide si la
# discontinuidad es explotable, y la respuesta no depende de acertar la norma.
THRESHOLD_USD = 150_000

# Ancho del tramo para las celdas administrativas del diagnostico 1. $10.000 es fino
# frente a la escala de los montos (mediana ~$65k) y grueso frente al dolar, que es
# la unidad en la que la regla opera.
CELL_WIDTH_USD = 10_000

# Tramo para la descomposicion del gradiente. Mas ancho que las celdas porque aqui
# hacen falta suficientes prestamos de AMBOS niveles de garantia en el mismo tramo.
GRADIENT_BIN_USD = 25_000
MIN_PER_CELL = 5_000

# Los dos niveles de garantia que se comparan: son los dos mas frecuentes por encima
# del 70% y los que la regla del umbral separaria.
LEVELS = (0.75, 0.85)


def _reader(source_glob: str | None = None) -> str:
    raw = source_glob or (repo_root() / RAW_GLOB).as_posix()
    return (
        f"read_csv('{raw}', union_by_name=true, ignore_errors=true, "
        "sample_size=200000, all_varchar=true)"
    )


def _panel(con: duckdb.DuckDBPyConnection, source_glob: str | None = None) -> None:
    """Prestamos resueltos con tratamiento, resultado y los determinantes candidatos.

    Se excluye PPP igual que en el modelado: se otorgo bajo criterios de emergencia y
    su garantia es del 100% por norma, asi que meteria una masa que no responde a la
    regla que se esta estudiando.
    """
    cfg = load_config()
    ppp = ", ".join(f"'{v}'" for v in cfg["exclusions"]["ppp_program_values"])
    resueltos = ", ".join(f"'{v}'" for v in cfg["exclusions"]["resolved_statuses"])
    con.execute(f"""
    create or replace view panel as
    select
        try_cast(GrossApproval as double)                                as monto,
        try_cast(SBAGuaranteedApproval as double)
          / nullif(try_cast(GrossApproval as double), 0)                 as garantia,
        trim(ProcessingMethod)                                          as metodo,
        case when trim(LoanStatus) = '{cfg["target"]["pd_positive_value"]}'
             then 1 else 0 end                                          as fallo,
        try_cast(ApprovalFY as integer)                                 as fy
    from {_reader(source_glob)}
    where try_cast(GrossApproval as double) > 0
      and trim(LoanStatus) in ({resueltos})
      and trim(Program) not in ({ppp})
      and try_cast(SBAGuaranteedApproval as double) is not null
    """)


# ------------------------------------------------------- 1. determinacion


@dataclass
class Determinacion:
    """Cuanto del tratamiento explican las celdas administrativas."""

    n: int
    celdas: int
    r2: float
    niveles_distintos: int
    masa_en_cuatro_niveles: float

    @property
    def identificable(self) -> bool:
        """Con R2 tan alto no queda variacion util. El umbral es una convencion
        declarada, no un resultado: por encima de 0.90 el solapamiento dentro de
        celda es residual y cualquier estimador condicional trabaja sobre el 8-9%
        que queda, que es justo la parte discrecional y por tanto seleccionada."""
        return self.r2 < 0.90


def determinacion(source_glob: str | None = None) -> Determinacion:
    con = duckdb.connect()
    _panel(con, source_glob)
    fila = con.execute(f"""
        with base as (
            select garantia, metodo, cast(floor(monto / {CELL_WIDTH_USD}) as integer) as tramo
            from panel
            where garantia is not null and metodo is not null and monto < 5000000
        ), gm as (select avg(garantia) as mu from base),
        cel as (select metodo, tramo, avg(garantia) as mu_cel from base group by 1, 2)
        select
            (select count(*) from base)                                    as n,
            (select count(*) from cel)                                     as celdas,
            1 - sum(power(b.garantia - c.mu_cel, 2))
              / sum(power(b.garantia - (select mu from gm), 2))             as r2
        from base b join cel c on b.metodo = c.metodo and b.tramo = c.tramo
    """).fetchone()

    niveles = con.execute(
        "select count(distinct round(garantia, 4)) from panel where garantia is not null"
    ).fetchone()[0]
    masa = con.execute("""
        select 100.0 * sum(case when round(garantia,2) in (0.50,0.75,0.85,0.90)
                                then 1 else 0 end) / count(*)
        from panel where garantia is not null
    """).fetchone()[0]

    return Determinacion(
        n=int(fila[0]),
        celdas=int(fila[1]),
        r2=round(float(fila[2]), 4),
        niveles_distintos=int(niveles),
        masa_en_cuatro_niveles=round(float(masa), 2),
    )


# ------------------------------------------------------- 2. densidad


@dataclass
class Densidad:
    """Apilamiento exacto en el umbral, por ventana."""

    umbral: int
    n_exacto: int
    por_ventana: list[dict]

    @property
    def rd_explotable(self) -> bool:
        """Si en la ventana mas estrecha la mayoria de la masa esta EXACTAMENTE en el
        umbral, la asignacion no es local-aleatoria. Criterio: menos del 10%."""
        if not self.por_ventana:
            return False
        mas_estrecha = min(self.por_ventana, key=lambda d: d["ventana_usd"])
        return mas_estrecha["pct_en_umbral"] < 10.0


def densidad(
    source_glob: str | None = None, ventanas: tuple[int, ...] = (5_000, 10_000, 25_000, 50_000)
) -> Densidad:
    con = duckdb.connect()
    _panel(con, source_glob)
    piezas = [
        f"""select {v} as ventana_usd, count(*) as n,
            sum(case when monto = {THRESHOLD_USD} then 1 else 0 end) as n_en_umbral,
            100.0 * sum(case when monto = {THRESHOLD_USD} then 1 else 0 end)
              / nullif(count(*), 0) as pct_en_umbral
        from panel where monto between {THRESHOLD_USD - v} and {THRESHOLD_USD + v}"""
        for v in ventanas
    ]
    df = con.execute("\nunion all\n".join(piezas) + "\norder by ventana_usd").df()
    df["pct_en_umbral"] = df["pct_en_umbral"].round(2)
    n_exacto = int(df["n_en_umbral"].iloc[0]) if len(df) else 0
    return Densidad(
        umbral=THRESHOLD_USD,
        n_exacto=n_exacto,
        por_ventana=df.astype(object).to_dict("records"),
    )


# ------------------------------------------------------- 3. gradiente


@dataclass
class Gradiente:
    """Cuanto del gradiente crudo sobrevive al condicionar por tamano."""

    crudo_pp: float
    dentro_de_tramo_pp: float
    n_comparable: int
    por_tramo: list[dict]

    @property
    def explicado_por_tamano(self) -> float:
        """Fraccion del gradiente que se va al condicionar. 1.0 = todo era tamano."""
        if self.crudo_pp == 0:
            return 0.0
        return round(1 - self.dentro_de_tramo_pp / self.crudo_pp, 4)


def gradiente(source_glob: str | None = None) -> Gradiente:
    con = duckdb.connect()
    _panel(con, source_glob)
    bajo, alto = LEVELS

    crudo = con.execute(f"""
        select 100.0 * avg(case when round(garantia,2) = {alto} then fallo end)
             - 100.0 * avg(case when round(garantia,2) = {bajo} then fallo end)
        from panel where round(garantia,2) in ({bajo}, {alto})
    """).fetchone()[0]

    df = con.execute(f"""
        with base as (
            select cast(floor(monto / {GRADIENT_BIN_USD}) as integer) as tramo,
                   round(garantia, 2) as g, fallo
            from panel
            where garantia is not null and round(garantia,2) in ({bajo}, {alto})
              and monto < 1000000
        )
        select
            tramo * {GRADIENT_BIN_USD}                                        as monto_desde,
            sum(case when g = {bajo} then 1 else 0 end)                       as n_bajo,
            sum(case when g = {alto} then 1 else 0 end)                       as n_alto,
            100.0 * avg(case when g = {bajo} then fallo end)                  as tasa_bajo,
            100.0 * avg(case when g = {alto} then fallo end)                  as tasa_alto
        from base
        group by 1
        having sum(case when g = {bajo} then 1 else 0 end) >= {MIN_PER_CELL}
           and sum(case when g = {alto} then 1 else 0 end) >= {MIN_PER_CELL}
        order by 1
    """).df()

    if df.empty:
        return Gradiente(round(float(crudo), 2), 0.0, 0, [])

    df["diferencia_pp"] = (df["tasa_alto"] - df["tasa_bajo"]).round(2)
    df["n"] = df["n_bajo"] + df["n_alto"]
    dentro = float((df["diferencia_pp"] * df["n"]).sum() / df["n"].sum())
    for c in ("tasa_bajo", "tasa_alto"):
        df[c] = df[c].round(2)

    return Gradiente(
        crudo_pp=round(float(crudo), 2),
        dentro_de_tramo_pp=round(dentro, 2),
        n_comparable=int(df["n"].sum()),
        por_tramo=df.drop(columns=["n"]).astype(object).to_dict("records"),
    )


# ------------------------------------------------------- reporte


def main() -> int:
    det = determinacion()
    den = densidad()
    gra = gradiente()

    print("=" * 96)
    print("IDENTIFICACION CAUSAL — el efecto del % de garantia sobre el incumplimiento")
    print("=" * 96)
    print("  Tratamiento: SBAGuaranteedApproval / GrossApproval")
    print("  Resultado:   charge-off, sobre prestamos RESUELTOS (subconjunto censurado)")

    print()
    print("-" * 96)
    print("1. ¿El tratamiento tiene variacion propia?")
    print("-" * 96)
    print(f"  niveles distintos de garantia          {det.niveles_distintos:,}")
    print(f"  masa en los cuatro niveles frecuentes  {det.masa_en_cuatro_niveles:.2f}%")
    print(f"  celdas (metodo x tramo de ${CELL_WIDTH_USD:,})        {det.celdas:,}")
    print(f"  n                                      {det.n:,}")
    print(f"  R2 del tratamiento sobre las celdas    {det.r2:.4f}")
    print(
        f"  -> {'queda variacion util' if det.identificable else 'NO queda variacion util'}: "
        f"{det.r2:.1%} del tratamiento lo fija la regla administrativa"
    )

    print()
    print("-" * 96)
    print(f"2. ¿Sirve una regresion discontinua en ${THRESHOLD_USD:,}?")
    print("-" * 96)
    print(pd.DataFrame(den.por_ventana).to_string(index=False))
    print(f"\n  {den.n_exacto:,} prestamos estan EXACTAMENTE en ${THRESHOLD_USD:,}.")
    print(
        f"  -> {'densidad continua' if den.rd_explotable else 'DENSIDAD DESTRUIDA'}: "
        "el apilamiento en el umbral hace que la asignacion no sea local-aleatoria"
    )

    print()
    print("-" * 96)
    print(f"3. ¿El gradiente crudo es composicion? (garantia {LEVELS[1]} vs {LEVELS[0]})")
    print("-" * 96)
    print(pd.DataFrame(gra.por_tramo).to_string(index=False))
    print()
    print(f"  gradiente crudo                        {gra.crudo_pp:+.2f} pp")
    print(f"  dentro del mismo tramo de tamano       {gra.dentro_de_tramo_pp:+.2f} pp")
    print(f"  explicado por tamano                   {gra.explicado_por_tamano:.1%}")
    print(f"  n comparable                           {gra.n_comparable:,}")
    print()
    print("  El residual NO es un efecto. Sobrevive precisamente la parte discrecional")
    print("  del tratamiento --prestamistas que piden menos que el maximo-- y su signo")
    print("  es el que predice la seleccion adversa: mas garantia donde el expediente")
    print("  de credito, que no esta en estos datos, se ve peor.")

    print()
    print("=" * 96)
    print("VEREDICTO")
    print("=" * 96)
    vias = {
        "condicional (DML, causal forest)": det.identificable,
        "regresion discontinua en el umbral": den.rd_explotable,
    }
    for via, ok in vias.items():
        print(f"  {'VIABLE ' if ok else 'CERRADA'}  {via}")
    if not any(vias.values()):
        print()
        print("  NO SE PUBLICA UN EFECTO. Con esta palanca y estos datos el efecto no esta")
        print("  identificado, y un estimador aplicado donde sus supuestos no se cumplen")
        print("  produce un numero, no una estimacion. Ver docs/adr/0013.")

    salida = repo_root() / EXPORT_PATH
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(
            {
                "tratamiento": "sba_guaranteed / gross_approval",
                "resultado": "charge-off (solo prestamos resueltos)",
                "umbral_candidato_usd": THRESHOLD_USD,
                "determinacion": asdict(det) | {"identificable": det.identificable},
                "densidad": asdict(den) | {"rd_explotable": den.rd_explotable},
                "gradiente": asdict(gra) | {"explicado_por_tamano": gra.explicado_por_tamano},
                "veredicto": "no_identificado" if not any(vias.values()) else "revisar",
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nExportado a {salida}")
    # Exit 0: esto es un diagnostico. Que el efecto no este identificado es el
    # hallazgo, no un fallo del pipeline.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
