"""El shock de tasas de 2022 y la brecha racial de denegacion en HMDA.

LA PREGUNTA. Entre 2021 y 2023 la razon de cuatro quintos de HMDA cayo de 0.827 a
0.729: la brecha de denegacion entre solicitantes negros y blancos se amplio. El
proyecto ya publico ese gradiente en la semana 6, como descripcion. La pregunta de
este modulo es la siguiente: el shock de tasas AMPLIO la brecha, o la brecha
agregada se movio porque cambio quien solicita y para que?

POR QUE ESTE ES EL MEJOR DISENO CAUSAL DEL PROYECTO. El ADR 0013 cerro la
estimacion del efecto de la garantia de la SBA por no-identificacion: sin
solapamiento, sin densidad en el umbral. Se dejo dicho que el shock de tasas era la
alternativa, y estas son las razones:

  - El shock es EXOGENO a la brecha. La Fed subio de 0.25% a 4.50% en 2022 por
    inflacion agregada; nadie sostendria que lo hizo en respuesta a las tasas de
    denegacion por raza.
  - Es GRANDE. La tasa hipotecaria a 30 anios paso de ~3.1% a ~6.4%. No hace falta
    exprimir una variacion marginal.
  - Hay CLASES PROTEGIDAS en el dato, que es lo que SBA no tiene.
  - Hay PERIODOS PREVIOS para falsificar. Y aqui esta la diferencia con lo que el
    panel publicado permitia: con 2020-2024 hay un solo ano pre-shock comparable, o
    sea una sola diferencia previa, y ademas 2020-21 es el auge de refinanciacion.
    Tomarlo como linea base es suponer que lo anormal era lo normal. Por eso el
    estudio corre sobre 2018-2025 y 2018-2019 --tasas corrientes-- son la base real.

LO QUE ESTE MODULO NO ASUME. No asume que el shock es el unico cambio de 2022. Es
un shock COMUN: no hay un grupo sin tratar en el corte transversal. La segunda
diferencia es entre grupos raciales, no entre tratados y controles, asi que el
supuesto de identificacion es que, sin el shock, la brecha DENTRO de celda habria
seguido su tendencia previa. Eso es falsificable con 2018-2021, y se falsifica.

LOS CUATRO PASOS, en orden y por una razon:

  1. REGIMEN. 2020-21 fue anomalo? Si la brecha de 2023 vuelve al nivel de 2018-19,
     no hubo ampliacion: hubo una compresion transitoria que revirtio. Esta pregunta
     va PRIMERO porque puede invertir el signo del titular descriptivo.

  2. DESCOMPOSICION. Cuanto del cambio de la brecha agregada es cambio de tasas
     dentro de segmento y cuanto es recomposicion de quien solicita que. Identidad
     exacta de Kitagawa, sin residuo.

  3. ESTIMADOR INTRA-CELDA. Brecha dentro de condado x proposito x gravamen x
     ocupacion, sobre un panel BALANCEADO de celdas, con errores agrupados por
     condado. El coeficiente de cada ano previo es el test de tendencias paralelas.

  4. SELECCION. El paso 3 solo vale si el shock no cambio QUIEN solicita de forma
     distinta por grupo. Es el supuesto que puede matar al estimador, asi que se
     mide en vez de invocarse.

MAGNITUD ANTES QUE SIGNIFICANCIA. Con 92.9M solicitudes, cualquier efecto es
estadisticamente significativo y el p-valor no informa nada. El umbral que importa
esta declarado en config.yaml (`event_study.meaningful_pp`) y su derivacion es
regulatoria, no estadistica.

ADVERTENCIA QUE NO SE PUEDE OMITIR. HMDA no trae puntaje de credito, que es el
determinante mas fuerte de una decision de suscripcion. Nada de lo que sigue prueba
discriminacion. Prueba que hay una diferencia, y de donde NO viene.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field

import duckdb
import numpy as np
import pandas as pd

from crmlops.config import load_config, repo_root
from crmlops.sources.hmda import shard_list_sql

EXPORT_PATH = "exports/event_study_hmda.json"
CELLS_CSV = "exports/event_study_cells.csv"

# Condados sin codigo: 0.3-0.5% de las filas. Se excluyen porque la celda es el
# mercado local y una celda "sin condado" agrupa solicitudes de todo el pais.
BAD_COUNTY = ("", "NA")


# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------
def _connect(threads: int = 6) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"set threads to {threads}")
    return con


def build_panel(
    con: duckdb.DuckDBPyConnection, cfg: dict | None = None, source: str | None = None
) -> None:
    cfg = cfg or load_config()
    es = cfg["event_study"]
    listed = source or shard_list_sql(tuple(es["years"]))
    bad = ", ".join(f"'{c}'" for c in BAD_COUNTY)
    con.execute(f"""
    create or replace view panel as
    select
        try_cast(activity_year as int)                   as anio,
        case when action_taken = '3' then 1 else 0 end   as denegado,
        derived_race                                     as raza,
        derived_ethnicity                                as etnia,
        county_code, loan_purpose, lien_status, occupancy_type,
        try_cast(loan_amount as double)                  as monto,
        try_cast(income as double) * 1000                as ingreso
    from read_parquet({listed})
    where county_code is not null and county_code not in ({bad})
    """)


# --------------------------------------------------------------------------
# 1. Regimen: 2020-21 fue la anomalia?
# --------------------------------------------------------------------------
@dataclass
class Regimen:
    """Brecha agregada por ano y la comparacion que el panel de 5 anios no permitia."""

    por_anio: list[dict]
    brecha_prepandemia: float  # promedio 2018-2019, pp
    brecha_auge: float  # promedio 2020-2021, pp
    brecha_post: float  # promedio 2023-2025, pp

    @property
    def compresion_del_auge_pp(self) -> float:
        """Cuanto comprimio el auge la brecha respecto de la base pre-pandemia."""
        return self.brecha_auge - self.brecha_prepandemia

    @property
    def ampliacion_vs_auge_pp(self) -> float:
        return self.brecha_post - self.brecha_auge

    @property
    def ampliacion_vs_prepandemia_pp(self) -> float:
        """La comparacion honesta: post-shock contra el ultimo regimen NORMAL."""
        return self.brecha_post - self.brecha_prepandemia

    @property
    def es_reversion(self) -> bool:
        """La brecha post-shock vuelve al nivel pre-pandemia en vez de superarlo.

        Si es cierto, el titular descriptivo --"la brecha se amplio"-- mide el auge
        de refinanciacion, no el shock de tasas.
        """
        return abs(self.ampliacion_vs_prepandemia_pp) < abs(self.ampliacion_vs_auge_pp)


def regimen(con: duckdb.DuckDBPyConnection, cfg: dict | None = None) -> Regimen:
    cfg = cfg or load_config()
    es = cfg["event_study"]
    focal, ref = es["focal_group"], es["reference_group"]
    df = con.execute(
        """
        select anio, raza, count(*) n, avg(denegado) tasa
        from panel where raza in (?, ?) group by 1, 2 order by 1, 2
        """,
        [focal, ref],
    ).fetchdf()

    filas = []
    for anio, part in df.groupby("anio"):
        p = part.set_index("raza")
        filas.append(
            {
                "anio": int(anio),
                "n_focal": int(p.loc[focal, "n"]),
                "n_ref": int(p.loc[ref, "n"]),
                "tasa_focal": float(p.loc[focal, "tasa"]),
                "tasa_ref": float(p.loc[ref, "tasa"]),
                "brecha_pp": float((p.loc[focal, "tasa"] - p.loc[ref, "tasa"]) * 100),
                # Razon de cuatro quintos entre estos dos grupos, que es como la
                # lee un examen de fair lending: aprobacion focal / aprobacion ref.
                "ratio_4_5": float((1 - p.loc[focal, "tasa"]) / (1 - p.loc[ref, "tasa"])),
            }
        )

    def media(desde: int, hasta: int) -> float:
        vals = [f["brecha_pp"] for f in filas if desde <= f["anio"] <= hasta]
        return float(np.mean(vals)) if vals else float("nan")

    return Regimen(
        por_anio=filas,
        brecha_prepandemia=media(2018, 2019),
        brecha_auge=media(2020, 2021),
        brecha_post=media(2023, 2025),
    )


# --------------------------------------------------------------------------
# 2. Descomposicion: tasas dentro de segmento vs. recomposicion
# --------------------------------------------------------------------------
@dataclass
class Descomposicion:
    """Identidad exacta de Kitagawa sobre el cambio de la brecha agregada.

    Para cada grupo g, la tasa agregada es una media ponderada sobre segmentos:
    d^g = sum_s w^g_s * d^g_s. El cambio entre dos anios se parte SIN residuo:

        delta d^g = sum_s (delta w^g_s) * dbar^g_s   <- composicion
                  + sum_s wbar^g_s * (delta d^g_s)   <- tasas

    donde bar es el promedio de los dos periodos. Es algebra, no un modelo: se
    verifica que las dos partes suman el total observado.

    El cambio de la BRECHA es la diferencia de los dos cambios, asi que hereda la
    misma particion.
    """

    anio_base: int
    anio_final: int
    segmentos: int
    cambio_brecha_pp: float
    composicion_pp: float
    tasas_pp: float
    detalle: list[dict] = field(default_factory=list)

    @property
    def cuadra(self) -> bool:
        return abs(self.composicion_pp + self.tasas_pp - self.cambio_brecha_pp) < 1e-8

    @property
    def share_composicion(self) -> float:
        """Fraccion del cambio de la brecha atribuible a recomposicion."""
        return (
            self.composicion_pp / self.cambio_brecha_pp
            if abs(self.cambio_brecha_pp) > 1e-12
            else float("nan")
        )


def descomposicion(
    con: duckdb.DuckDBPyConnection,
    anio_final: int,
    cfg: dict | None = None,
    anio_base: int | None = None,
) -> Descomposicion:
    cfg = cfg or load_config()
    es = cfg["event_study"]
    focal, ref = es["focal_group"], es["reference_group"]
    base = anio_base if anio_base is not None else int(es["base_year"])

    df = con.execute(
        """
        select anio, raza, loan_purpose, lien_status, occupancy_type,
               count(*) n, avg(denegado) d
        from panel
        where raza in (?, ?) and anio in (?, ?)
        group by all
        """,
        [focal, ref, base, anio_final],
    ).fetchdf()
    df["seg"] = (
        df["loan_purpose"].astype(str)
        + "|"
        + df["lien_status"].astype(str)
        + "|"
        + df["occupancy_type"].astype(str)
    )

    segs = sorted(df["seg"].unique())
    partes: dict[str, dict[str, float]] = {}
    detalle_por_seg: dict[str, dict[str, float]] = {s: {"seg": s} for s in segs}

    for g in (focal, ref):
        sub = df[df["raza"] == g]
        w, d = {}, {}
        for yr in (base, anio_final):
            part = sub[sub["anio"] == yr].set_index("seg")
            total = part["n"].sum()
            w[yr] = {s: float(part["n"].get(s, 0)) / total for s in segs}
            # Un segmento sin solicitudes no tiene tasa. Se usa 0 y su peso es 0,
            # asi que no aporta al termino de tasas; el de composicion sí, via dbar.
            d[yr] = {s: float(part["d"].get(s, np.nan)) for s in segs}
        comp = rate = 0.0
        for s in segs:
            dw = w[anio_final][s] - w[base][s]
            d0, d1 = d[base][s], d[anio_final][s]
            # dbar cuando solo un periodo observa el segmento: el unico valido.
            if np.isnan(d0) and np.isnan(d1):
                continue
            dbar = np.nanmean([d0, d1])
            wbar = (w[base][s] + w[anio_final][s]) / 2
            dd = 0.0 if (np.isnan(d0) or np.isnan(d1)) else (d1 - d0)
            comp += dw * dbar
            rate += wbar * dd
            detalle_por_seg[s][f"dw_{'focal' if g == focal else 'ref'}"] = dw
            detalle_por_seg[s][f"comp_{'focal' if g == focal else 'ref'}_pp"] = dw * dbar * 100
            detalle_por_seg[s][f"tasa_{'focal' if g == focal else 'ref'}_pp"] = wbar * dd * 100
        obs = float(
            sub[sub["anio"] == anio_final]["n"].mul(sub[sub["anio"] == anio_final]["d"]).sum()
            / sub[sub["anio"] == anio_final]["n"].sum()
            - sub[sub["anio"] == base]["n"].mul(sub[sub["anio"] == base]["d"]).sum()
            / sub[sub["anio"] == base]["n"].sum()
        )
        partes[g] = {"comp": comp, "rate": rate, "observado": obs}

    # float() explicito: dbar sale de np.nanmean, asi que comp es np.float64 y
    # arrastra el tipo hasta `cuadra`, que termina siendo np.bool_ y revienta
    # json.dumps DESPUES de diez minutos de computo. El cast va aqui, en el borde.
    comp_pp = float((partes[focal]["comp"] - partes[ref]["comp"]) * 100)
    rate_pp = float((partes[focal]["rate"] - partes[ref]["rate"]) * 100)
    total_pp = float((partes[focal]["observado"] - partes[ref]["observado"]) * 100)

    detalle = sorted(
        detalle_por_seg.values(),
        key=lambda r: -abs(r.get("comp_focal_pp", 0) - r.get("comp_ref_pp", 0)),
    )
    return Descomposicion(
        anio_base=base,
        anio_final=anio_final,
        segmentos=len(segs),
        cambio_brecha_pp=total_pp,
        composicion_pp=comp_pp,
        tasas_pp=rate_pp,
        detalle=detalle[:12],
    )


# --------------------------------------------------------------------------
# 3. Estudio de evento intra-celda
# --------------------------------------------------------------------------
def celdas(
    con: duckdb.DuckDBPyConnection, cfg: dict | None = None, *, balanceado: bool = True
) -> pd.DataFrame:
    """Celda-ano con conteos de los dos grupos.

    BALANCEADO importa. Si el conjunto de celdas cambia de ano en ano, el estimador
    mezcla "la brecha dentro de celda cambio" con "las celdas cambiaron", que es
    exactamente el confusor que este modulo estudia. Con el panel balanceado las
    celdas son las MISMAS en los ocho anios, asi que lo unico que se mueve es la
    brecha.

    El costo es real y se reporta: las celdas de refinanciacion casi no sobreviven
    --el segmento se desplomo 92%-- de modo que el panel balanceado esta poblado
    sobre todo por compra de vivienda. Eso NO es un defecto del filtro: es el
    hallazgo. La comparacion intra-celda solo existe donde todavia hay algo con que
    comparar.
    """
    cfg = cfg or load_config()
    es = cfg["event_study"]
    focal, ref = es["focal_group"], es["reference_group"]
    keys = ", ".join(es["cell_keys"])
    minimo = int(es["min_per_cell_group"])
    n_anios = len(es["years"])

    df = con.execute(
        f"""
        with base as (
            select anio, {keys},
                   sum(case when raza = ? then 1 else 0 end)        as n_focal,
                   sum(case when raza = ? then denegado else 0 end) as k_focal,
                   sum(case when raza = ? then 1 else 0 end)        as n_ref,
                   sum(case when raza = ? then denegado else 0 end) as k_ref
            from panel where raza in (?, ?)
            group by all
            having n_focal >= {minimo} and n_ref >= {minimo}
        )
        select * from base
        """,
        [focal, focal, ref, ref, focal, ref],
    ).fetchdf()

    df["celda"] = df[list(es["cell_keys"])].astype(str).agg("|".join, axis=1)
    if balanceado:
        completas = df.groupby("celda")["anio"].nunique()
        df = df[df["celda"].isin(completas[completas == n_anios].index)].copy()
    return df.reset_index(drop=True)


@dataclass
class Coeficiente:
    anio: int
    theta_pp: float  # nivel: brecha intra-celda ponderada, pp
    gamma_pp: float  # respecto al ano base
    se_pp: float  # error estandar agrupado por condado, del gamma
    celdas: int
    n: int

    @property
    def ic95(self) -> tuple[float, float]:
        return (self.gamma_pp - 1.96 * self.se_pp, self.gamma_pp + 1.96 * self.se_pp)


@dataclass
class EstudioEvento:
    """Coeficientes por ano y el veredicto sobre tendencias paralelas.

    IDENTIDAD DEL ESTIMADOR. Con dos grupos y efectos fijos de celda-ano saturados,
    el estimador de MCO ponderado tiene forma cerrada:

        theta_t = sum_k h_k * brecha_k / sum_k h_k,   h_k = n_f*n_r / (n_f + n_r)

    o sea la media de las brechas intra-celda con peso de media armonica. No es una
    aproximacion: es la solucion exacta del problema de minimos cuadrados, y hay un
    test que la compara contra una regresion por fuerza bruta.
    """

    base_year: int
    balanceado: bool
    coeficientes: list[Coeficiente]
    meaningful_pp: float

    def _por_anio(self, anio: int) -> Coeficiente | None:
        return next((c for c in self.coeficientes if c.anio == anio), None)

    @property
    def previos(self) -> list[Coeficiente]:
        return [c for c in self.coeficientes if c.anio < self.base_year]

    @property
    def posteriores(self) -> list[Coeficiente]:
        return [c for c in self.coeficientes if c.anio > self.base_year + 1]

    @property
    def tendencias_paralelas(self) -> bool:
        """Ningun coeficiente PREVIO supera en magnitud el umbral economico.

        El test no es "no se rechaza el cero": con esta n, se rechaza siempre. Es
        que los coeficientes previos sean economicamente indistinguibles de cero
        segun el mismo umbral con el que se juzgaran los posteriores. Usar dos varas
        distintas seria elegir la que conviene.
        """
        return all(abs(c.gamma_pp) < self.meaningful_pp for c in self.previos)

    @property
    def efecto_maximo_pp(self) -> float:
        post = self.posteriores
        return max((c.gamma_pp for c in post), key=abs, default=float("nan"))

    @property
    def veredicto(self) -> str:
        if not self.previos:
            return "SIN FALSIFICACION (no hay anios previos en la ventana)"
        if not self.tendencias_paralelas:
            peor = max(self.previos, key=lambda c: abs(c.gamma_pp))
            return (
                f"NO IDENTIFICADO: el coeficiente previo de {peor.anio} vale "
                f"{peor.gamma_pp:+.2f} pp, por encima del umbral de "
                f"{self.meaningful_pp} pp. La tendencia previa no es plana, "
                "asi que el post-shock no se puede leer como efecto."
            )
        if abs(self.efecto_maximo_pp) < self.meaningful_pp:
            return (
                f"NULO IDENTIFICADO: tendencias previas planas y efecto maximo de "
                f"{self.efecto_maximo_pp:+.2f} pp, por debajo del umbral de "
                f"{self.meaningful_pp} pp."
            )
        return (
            f"EFECTO: tendencias previas planas y efecto maximo de "
            f"{self.efecto_maximo_pp:+.2f} pp, por encima del umbral de "
            f"{self.meaningful_pp} pp."
        )


def estudio_evento(df: pd.DataFrame, cfg: dict | None = None) -> EstudioEvento:
    """Forma cerrada del estimador intra-celda, con errores agrupados por condado."""
    cfg = cfg or load_config()
    es = cfg["event_study"]
    base = int(es["base_year"])

    d = df.copy()
    d["h"] = d["n_focal"] * d["n_ref"] / (d["n_focal"] + d["n_ref"])
    d["brecha"] = d["k_focal"] / d["n_focal"] - d["k_ref"] / d["n_ref"]

    # Influencia por condado para cada ano: psi_c = sum_{k in c} h_k (brecha_k - theta) / H
    infl: dict[int, pd.Series] = {}
    niveles: dict[int, float] = {}
    meta: dict[int, tuple[int, int]] = {}
    for anio, part in d.groupby("anio"):
        H = part["h"].sum()
        theta = float((part["h"] * part["brecha"]).sum() / H)
        score = part["h"] * (part["brecha"] - theta)
        infl[int(anio)] = score.groupby(part["county_code"]).sum() / H
        niveles[int(anio)] = theta
        meta[int(anio)] = (len(part), int(part["n_focal"].sum() + part["n_ref"].sum()))

    base_infl = infl[base]
    coefs = []
    for anio in sorted(niveles):
        gamma = niveles[anio] - niveles[base]
        if anio == base:
            se = 0.0
        else:
            dif = infl[anio].subtract(base_infl, fill_value=0.0)
            se = float(np.sqrt((dif**2).sum()))
        n_celdas, n = meta[anio]
        coefs.append(
            Coeficiente(
                anio=anio,
                theta_pp=niveles[anio] * 100,
                gamma_pp=gamma * 100,
                se_pp=se * 100,
                celdas=n_celdas,
                n=n,
            )
        )
    return EstudioEvento(
        base_year=base,
        balanceado=True,
        coeficientes=coefs,
        meaningful_pp=float(es["meaningful_pp"]),
    )


# --------------------------------------------------------------------------
# 3b. El arreglo estandar cuando la tendencia previa no es plana, y por que
#     aqui FABRICA un efecto en vez de descubrirlo
# --------------------------------------------------------------------------
@dataclass
class TendenciaAjustada:
    """Ajuste por tendencia lineal previa. Se calcula para poder rechazarlo.

    El manual dice: si la tendencia previa no es plana, estimala y mide la
    DESVIACION respecto de su extrapolacion. La tecnica es correcta y aqui esta
    implementada. Lo que no es correcto es aplicarla sin mirar QUE tendencia se
    extrapola.

    La tendencia previa de este panel es la compresion de la brecha durante el auge
    de refinanciacion: -0.8 pp por anio entre 2018 y 2021, empujada por una ola de
    refinanciaciones baratas que por definicion se iba a acabar. Extrapolarla a
    2025 supone que la brecha habria seguido cayendo hasta desaparecer, y contra esa
    linea CUALQUIER cosa que pase parece un efecto enorme.

    O sea: el ajuste convierte el fin del auge en el efecto del shock. Por eso el
    numero se publica junto a su refutacion y no como resultado.
    """

    pendiente_pp_anio: float
    r2: float
    anios_previos: list[int]
    desviaciones: list[dict]

    @property
    def desviacion_maxima_pp(self) -> float:
        return max((d["desviacion_pp"] for d in self.desviaciones), key=abs, default=float("nan"))

    @property
    def extrapolacion_creible(self) -> bool:
        """La extrapolacion solo vale si la tendencia previa no es la del regimen
        que el shock termina. Aqui lo es, asi que se declara falso por construccion
        y el numero queda como ilustracion."""
        return False


def tendencia_ajustada(ev: EstudioEvento, cfg: dict | None = None) -> TendenciaAjustada:
    cfg = cfg or load_config()
    shock = int(cfg["event_study"]["shock_year"])
    previos = [c for c in ev.coeficientes if c.anio < shock]
    x = np.array([c.anio for c in previos], dtype=float)
    y = np.array([c.theta_pp for c in previos], dtype=float)
    pendiente, intercepto = np.polyfit(x, y, 1)
    pred = pendiente * x + intercepto
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())

    desv = []
    for c in ev.coeficientes:
        if c.anio < shock:
            continue
        contrafactual = pendiente * c.anio + intercepto
        desv.append(
            {
                "anio": c.anio,
                "observado_pp": c.theta_pp,
                "contrafactual_pp": float(contrafactual),
                "desviacion_pp": float(c.theta_pp - contrafactual),
            }
        )
    return TendenciaAjustada(
        pendiente_pp_anio=float(pendiente),
        r2=1 - ss_res / ss_tot if ss_tot else float("nan"),
        anios_previos=[int(v) for v in x],
        desviaciones=desv,
    )


# --------------------------------------------------------------------------
# 4. Seleccion diferencial: el supuesto que puede matar al paso 3
# --------------------------------------------------------------------------
@dataclass
class Seleccion:
    """Cambio la composicion del grupo focal de forma distinta a la del referencia?

    El estimador intra-celda compara dos POOLS DE SOLICITANTES, no dos personas
    iguales. Si el shock saco de la fila a los solicitantes marginales de un grupo
    mas que del otro, la brecha observada cambia sin que ningun prestamista haya
    cambiado de criterio.

    Se miden dos cosas dentro de las mismas celdas balanceadas:
      - RETENCION: cuanto cayo el volumen de cada grupo respecto del ano base.
      - CARGA: el prestamo/ingreso mediano, que es el margen por el que un
        solicitante deja de calificar cuando sube la tasa.
    """

    por_anio: list[dict]
    retencion_diferencial_pp: float  # max |caida_focal - caida_ref| post-shock, pp
    carga_diferencial: float  # max |delta LTI focal - delta LTI ref| post-shock

    @property
    def contamina(self) -> bool:
        """Umbral declarado: 10 pp de retencion diferencial.

        Es una convencion, y se declara como tal. Por debajo, los dos pools se
        vaciaron a un ritmo parecido y la comparacion intra-celda mantiene sentido.
        Por encima, el estimador del paso 3 compara poblaciones distintas y su
        coeficiente ya no es un efecto sobre las mismas personas.
        """
        return self.retencion_diferencial_pp >= 10.0


def seleccion(
    con: duckdb.DuckDBPyConnection, df_celdas: pd.DataFrame, cfg: dict | None = None
) -> Seleccion:
    cfg = cfg or load_config()
    es = cfg["event_study"]
    focal, ref = es["focal_group"], es["reference_group"]
    base, shock = int(es["base_year"]), int(es["shock_year"])

    con.register("celdas_balanceadas", df_celdas[["anio", *es["cell_keys"]]].drop_duplicates())
    joins = " and ".join(f"p.{k} = c.{k}" for k in es["cell_keys"])
    carga = con.execute(
        f"""
        select p.anio, p.raza,
               count(*) n,
               median(p.monto / nullif(p.ingreso, 0)) lti_mediano
        from panel p
        join celdas_balanceadas c on p.anio = c.anio and {joins}
        where p.raza in (?, ?) and p.ingreso > 0
        group by 1, 2
        """,
        [focal, ref],
    ).fetchdf()

    filas, base_row = [], {}
    for anio, part in carga.groupby("anio"):
        p = part.set_index("raza")
        row = {
            "anio": int(anio),
            "n_focal": int(p.loc[focal, "n"]),
            "n_ref": int(p.loc[ref, "n"]),
            "lti_focal": float(p.loc[focal, "lti_mediano"]),
            "lti_ref": float(p.loc[ref, "lti_mediano"]),
        }
        filas.append(row)
        if int(anio) == base:
            base_row = row

    ret_dif, carga_dif = 0.0, 0.0
    for row in filas:
        cf = (row["n_focal"] / base_row["n_focal"] - 1) * 100
        cr = (row["n_ref"] / base_row["n_ref"] - 1) * 100
        row["retencion_focal_pct"], row["retencion_ref_pct"] = cf, cr
        row["retencion_dif_pp"] = cf - cr
        row["lti_dif"] = (row["lti_focal"] - row["lti_ref"]) - (
            base_row["lti_focal"] - base_row["lti_ref"]
        )
        if row["anio"] > shock:
            ret_dif = max(ret_dif, abs(cf - cr))
            carga_dif = max(carga_dif, abs(row["lti_dif"]))

    return Seleccion(
        por_anio=filas,
        retencion_diferencial_pp=ret_dif,
        carga_diferencial=carga_dif,
    )


# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------
def _jsonable(o):
    """Ultima linea de defensa para escalares de numpy.

    Los casts van en el borde de cada calculo, pero un tipo de numpy que se cuele no
    debe costar una corrida entera: el export es lo ULTIMO que pasa despues de leer
    92.9M filas, y la primera version murio ahi con todo el computo ya hecho.
    """
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(f"no serializable: {type(o).__name__}")


def _linea(c: Coeficiente, base: int, umbral: float) -> str:
    if c.anio == base:
        return f"  {c.anio}   {c.theta_pp:7.2f}      (base)              celdas={c.celdas:>6,}"
    lo, hi = c.ic95
    marca = "*" if abs(c.gamma_pp) >= umbral else " "
    fase = "previo" if c.anio < base else "post"
    return (
        f"  {c.anio}   {c.theta_pp:7.2f}   {c.gamma_pp:+7.2f} +-{c.se_pp:5.2f}  "
        f"[{lo:+6.2f},{hi:+6.2f}] {marca} {fase:6s} celdas={c.celdas:>6,}"
    )


def main() -> int:
    cfg = load_config()
    es = cfg["event_study"]
    con = _connect()
    print("=" * 88)
    print("ESTUDIO DE EVENTO: el shock de tasas de 2022 y la brecha racial de denegacion")
    print(
        f"HMDA {min(es['years'])}-{max(es['years'])} - "
        f"{es['focal_group']} vs {es['reference_group']}"
    )
    print("=" * 88)

    build_panel(con, cfg)
    n_total = con.execute("select count(*) from panel").fetchone()[0]
    print(f"\nPanel: {n_total:,} solicitudes con condado identificado.")

    # --- 1 ---
    print("\n" + "-" * 88)
    print("1. REGIMEN - 2020-21 fue la anomalia, o la base?")
    print("-" * 88)
    reg = regimen(con, cfg)
    print("  anio        n focal      n ref   den.focal  den.ref   brecha   4/5")
    for r in reg.por_anio:
        print(
            f"  {r['anio']}  {r['n_focal']:>12,} {r['n_ref']:>12,}  "
            f"{r['tasa_focal']:8.2%} {r['tasa_ref']:8.2%}  "
            f"{r['brecha_pp']:6.2f}pp  {r['ratio_4_5']:.3f}"
        )
    print(f"\n  brecha media 2018-2019 (tasas normales) : {reg.brecha_prepandemia:6.2f} pp")
    print(f"  brecha media 2020-2021 (auge de refi)    : {reg.brecha_auge:6.2f} pp")
    print(f"  brecha media 2023-2025 (post-shock)      : {reg.brecha_post:6.2f} pp")
    print(f"\n  vs. auge          : {reg.ampliacion_vs_auge_pp:+6.2f} pp")
    print(f"  vs. pre-pandemia  : {reg.ampliacion_vs_prepandemia_pp:+6.2f} pp")
    if reg.es_reversion:
        print("\n  -> La brecha post-shock esta MAS CERCA del nivel pre-pandemia que del")
        print("     nivel del auge. Medir el shock contra 2021 mide el auge, no el shock.")

    # --- 2 ---
    print("\n" + "-" * 88)
    print("2. DESCOMPOSICION - recomposicion del pool vs. cambio de tasas")
    print("-" * 88)
    descs = []
    for anio in sorted(y for y in es["years"] if y > es["shock_year"]):
        dc = descomposicion(con, anio, cfg)
        descs.append(dc)
        assert dc.cuadra, "la identidad de Kitagawa no cuadra"
        print(
            f"  {es['base_year']}->{anio}  cambio {dc.cambio_brecha_pp:+6.2f} pp  =  "
            f"composicion {dc.composicion_pp:+6.2f}  +  tasas {dc.tasas_pp:+6.2f}   "
            f"(composicion = {dc.share_composicion:5.1%})"
        )

    # --- 3 ---
    print("\n" + "-" * 88)
    print("3. ESTIMADOR INTRA-CELDA - panel balanceado, errores agrupados por condado")
    print("-" * 88)
    cel = celdas(con, cfg, balanceado=True)
    cel_desb = celdas(con, cfg, balanceado=False)
    print(
        f"  celdas que sobreviven los {len(es['years'])} anios: "
        f"{cel['celda'].nunique():,} de {cel_desb['celda'].nunique():,} "
        f"({cel['celda'].nunique() / max(cel_desb['celda'].nunique(), 1):.1%})"
    )
    mix = cel.groupby("loan_purpose")["celda"].nunique().sort_values(ascending=False)
    print(f"  composicion por proposito: {dict(mix)}")

    ev = estudio_evento(cel, cfg)
    print(f"\n  anio   nivel pp     gamma vs {ev.base_year}        IC95")
    for c in ev.coeficientes:
        print(_linea(c, ev.base_year, ev.meaningful_pp))
    print(f"\n  (* = magnitud >= {ev.meaningful_pp} pp, el umbral declarado en config.yaml)")
    print(f"\n  Tendencias paralelas: {'PASA' if ev.tendencias_paralelas else 'NO PASA'}")
    print(f"  {ev.veredicto}")

    # --- 3b ---
    ta = tendencia_ajustada(ev, cfg)
    print("\n" + "-" * 88)
    print("3b. AJUSTE POR TENDENCIA PREVIA - la tecnica de manual, y por que no aplica")
    print("-" * 88)
    print(
        f"  Tendencia previa ({min(ta.anios_previos)}-{max(ta.anios_previos)}): "
        f"{ta.pendiente_pp_anio:+.2f} pp por anio  (R2 = {ta.r2:.3f})"
    )
    print("  anio   observado   contrafactual   desviacion")
    for d in ta.desviaciones:
        print(
            f"  {d['anio']}    {d['observado_pp']:7.2f}       {d['contrafactual_pp']:7.2f}     "
            f"{d['desviacion_pp']:+7.2f} pp"
        )
    print(f"\n  Desviacion maxima: {ta.desviacion_maxima_pp:+.2f} pp -- un 'efecto' grande y")
    print("  significativo que NO se publica como efecto. La tendencia que extrapola es la")
    print("  compresion del auge de refinanciacion, y el auge acabandose es justo lo que se")
    print("  esta midiendo: el ajuste convierte el fin del regimen en el efecto del shock.")

    # --- 4 ---
    print("\n" + "-" * 88)
    print("4. SELECCION DIFERENCIAL - el supuesto que puede invalidar el paso 3")
    print("-" * 88)
    sel = seleccion(con, cel, cfg)
    print("  anio    volumen focal    volumen ref   dif. de retencion   LTI (dif-en-dif)")
    for r in sel.por_anio:
        print(
            f"  {r['anio']}   {r['retencion_focal_pct']:+8.1f}%     "
            f"{r['retencion_ref_pct']:+8.1f}%       {r['retencion_dif_pp']:+7.1f} pp"
            f"        {r['lti_dif']:+6.3f}"
        )
    print(
        f"\n  Retencion diferencial maxima post-shock: {sel.retencion_diferencial_pp:.1f} pp"
        f"  -> {'CONTAMINA' if sel.contamina else 'tolerable'}"
    )

    # --- conclusion ---
    print("\n" + "=" * 88)
    print("CONCLUSION")
    print("=" * 88)
    print(
        f"  1. La brecha post-shock ({reg.brecha_post:.2f} pp) esta a "
        f"{abs(reg.ampliacion_vs_prepandemia_pp):.2f} pp de la brecha pre-pandemia "
        f"({reg.brecha_prepandemia:.2f} pp)."
    )
    print(
        f"     Contra 2021 la ampliacion es de {reg.ampliacion_vs_auge_pp:+.2f} pp, y ese es "
        "el numero que circula:"
    )
    print("     mide el auge de refinanciacion, no el shock de tasas.")
    if descs:
        print(
            f"  2. De ese movimiento, el {descs[0].share_composicion:.0%} es recomposicion "
            "del pool: cambio quien"
        )
        print("     solicita y para que, no cuanto se deniega dentro de cada segmento.")
    print("  3. El efecto causal NO esta identificado, y por tres razones medidas:")
    print(
        f"     - tendencias previas no planas ({ev.previos[0].gamma_pp:+.2f} pp en "
        f"{ev.previos[0].anio}, umbral {ev.meaningful_pp} pp);"
    )
    print(
        f"     - retencion diferencial de {sel.retencion_diferencial_pp:.1f} pp entre los "
        "dos pools de solicitantes;"
    )
    print("     - y el ajuste que corregiria lo primero extrapola el regimen que el shock termina.")
    print("\n  No se publica un efecto. Se publica la reversion, su descomposicion y las tres")
    print("  razones por las que un estimador aqui daria un numero y no una estimacion. Es la")
    print("  misma conclusion del ADR 0013 en otro dataset -- con la diferencia de que aqui SI")
    print("  hubo con que falsificar, y la falsificacion es la que cierra el caso.")

    # --- exportar ---
    payload = {
        "pregunta": (
            "El shock de tasas de 2022 amplio la brecha racial de denegacion, "
            "o la brecha agregada se movio por recomposicion del pool?"
        ),
        "ventana": list(es["years"]),
        "grupos": {"focal": es["focal_group"], "referencia": es["reference_group"]},
        "n_solicitudes": int(n_total),
        "umbral_economico_pp": float(es["meaningful_pp"]),
        "regimen": {
            **{k: v for k, v in asdict(reg).items()},
            "compresion_del_auge_pp": reg.compresion_del_auge_pp,
            "ampliacion_vs_auge_pp": reg.ampliacion_vs_auge_pp,
            "ampliacion_vs_prepandemia_pp": reg.ampliacion_vs_prepandemia_pp,
            "es_reversion": reg.es_reversion,
        },
        "descomposicion": [
            {**asdict(d), "share_composicion": d.share_composicion, "cuadra": d.cuadra}
            for d in descs
        ],
        "estudio_evento": {
            "base_year": ev.base_year,
            "balanceado": True,
            "celdas_balanceadas": int(cel["celda"].nunique()),
            "celdas_sin_balancear": int(cel_desb["celda"].nunique()),
            "coeficientes": [
                {**asdict(c), "ic95_lo": c.ic95[0], "ic95_hi": c.ic95[1]} for c in ev.coeficientes
            ],
            "tendencias_paralelas": ev.tendencias_paralelas,
            "efecto_maximo_pp": ev.efecto_maximo_pp,
            "veredicto": ev.veredicto,
        },
        "tendencia_ajustada": {
            **asdict(ta),
            "desviacion_maxima_pp": ta.desviacion_maxima_pp,
            "extrapolacion_creible": ta.extrapolacion_creible,
            "por_que_no": (
                "La tendencia previa es la compresion de la brecha durante el auge de "
                "refinanciacion. Extrapolarla supone que la brecha habria seguido cayendo, "
                "y contra esa linea el fin del auge aparece como efecto del shock."
            ),
        },
        "seleccion": {
            **asdict(sel),
            "contamina": sel.contamina,
        },
        "conclusion": {
            "reversion_no_ampliacion": reg.es_reversion,
            "brecha_prepandemia_pp": reg.brecha_prepandemia,
            "brecha_post_pp": reg.brecha_post,
            "distancia_pp": reg.ampliacion_vs_prepandemia_pp,
            "ampliacion_vs_2021_pp": reg.ampliacion_vs_auge_pp,
            "share_composicion_2023": descs[0].share_composicion if descs else None,
            "efecto_publicado": None,
            "razones_de_no_identificacion": [
                "tendencias previas no planas",
                "retencion diferencial entre los pools de solicitantes",
                "el ajuste por tendencia extrapola el regimen que el shock termina",
            ],
        },
        "limitaciones": [
            "HMDA no trae puntaje de credito, el determinante mas fuerte de la "
            "suscripcion. Nada de esto prueba discriminacion.",
            "El shock es comun: no hay grupo sin tratar. La segunda diferencia es "
            "entre grupos raciales, no entre tratados y controles.",
            "derived_race='White' incluye solicitantes hispanos blancos; etnia es "
            "una dimension separada en HMDA.",
            "El panel balanceado esta poblado sobre todo por compra de vivienda: "
            "las celdas de refinanciacion no sobreviven porque el segmento se "
            "desplomo. El efecto se estima donde queda con que comparar.",
        ],
    }
    out = repo_root() / EXPORT_PATH
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=_jsonable) + "\n",
        encoding="utf-8",
    )
    cel.to_csv(repo_root() / CELLS_CSV, index=False)
    print(f"\n  -> {EXPORT_PATH}")
    print(f"  -> {CELLS_CSV}  ({len(cel):,} celda-anio)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
