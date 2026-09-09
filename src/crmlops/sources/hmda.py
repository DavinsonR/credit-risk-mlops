"""Adquisicion de HMDA (Home Mortgage Disclosure Act).

Es el laboratorio de equidad del proyecto: a diferencia del extracto FOIA de SBA,
HMDA SI trae clases protegidas -- raza, etnia, sexo y edad -- porque la ley obliga
a reportarlas justamente para poder auditar discriminacion crediticia.

ESTRATEGIA DE DESCARGA. Se usa la API del data browser por estado-anio en vez de
los snapshots nacionales de 5.8 GB. Ventajas concretas:

  - Reanudable: si se corta, se reintenta solo el estado-anio que falto.
  - Verificable: el endpoint /aggregations devuelve los conteos oficiales, asi
    que se puede confirmar que la descarga esta COMPLETA y no truncada.
  - Poda inmediata: cada CSV se convierte a Parquet con las columnas que
    importan y se borra. Pico de disco: un estado-anio, no el dataset entero.

TRES CLASES DE EXCLUSION, no una. Ver `FORBIDDEN_*` mas abajo.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import requests

from crmlops.config import repo_root, resolve_path

API = "https://ffiec.cfpb.gov/v2/data-browser-api/view"
TIMEOUT = 600
RETRIES = 3

# Los 50 estados, DC y Puerto Rico.
STATES = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "PR",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
]

# --- 1. Campos que SOLO existen si el prestamo se origino -------------------
# Medido sobre DC 2023: interest_rate esta nulo en 99.4% de las denegadas y en
# 0.0% de las originadas. Un modelo con estas columnas aprende "tiene tasa ->
# aprobado" y alcanza un AUC irreal. Es el mismo mecanismo que TermInMonths en
# SBA (ADR 0002), en otro dataset.
FORBIDDEN_OUTCOME_ONLY = (
    "interest_rate",
    "rate_spread",
    "total_loan_costs",
    "total_points_and_fees",
    "origination_charges",
    "discount_points",
    "lender_credits",
    "purchaser_type",
    "denial_reason-1",
    "denial_reason-2",
    "denial_reason-3",
    "denial_reason-4",
)

# --- 2. La decision del propio prestamista ----------------------------------
# aus-1..5 son los resultados del motor de suscripcion automatica del banco.
# Estan disponibles al momento de decidir, pero usarlos convierte el ejercicio en
# "predecir una decision a partir de la decision". El modelo aprenderia a imitar
# al motor existente, incluidos sus sesgos, en vez de modelar el riesgo.
FORBIDDEN_LENDER_DECISION = ("aus-1", "aus-2", "aus-3", "aus-4", "aus-5")

# --- 3. Proxies de caracteristicas protegidas -------------------------------
# tract_minority_population_percent es la composicion racial del vecindario.
# Usarla como feature es modelar sobre raza por via geografica: es la definicion
# operativa de redlining. Se conserva en el panel para MEDIR disparidad
# territorial, nunca para entrenar.
FORBIDDEN_PROXY = ("tract_minority_population_percent",)

# --- Clases protegidas: se conservan para AUDITAR, jamas para entrenar -------
# Esta es la distincion central del trabajo de equidad. Sin ellas en el panel no
# se puede medir disparate impact; con ellas en el modelo se discrimina de forma
# explicita.
PROTECTED = (
    "derived_race",
    "derived_ethnicity",
    "derived_sex",
    "applicant_age",
    "applicant_age_above_62",
)

# --- Features candidatas: informacion del solicitante y del prestamo ---------
CANDIDATE_FEATURES = (
    "loan_amount",
    "income",
    "debt_to_income_ratio",
    "loan_to_value_ratio",
    "property_value",
    "loan_type",
    "loan_purpose",
    "lien_status",
    "occupancy_type",
    "construction_method",
    "total_units",
    "conforming_loan_limit",
    "preapproval",
    "open-end_line_of_credit",
    "business_or_commercial_purpose",
    "reverse_mortgage",
    "derived_dwelling_category",
    "derived_loan_product_type",
    "submission_of_application",
    # Contexto censal del tract. Legitimo (es informacion economica del area) y
    # disponible al decidir. NO incluye la composicion racial: ver FORBIDDEN_PROXY.
    "tract_population",
    "tract_to_msa_income_percentage",
    "tract_owner_occupied_units",
    "ffiec_msa_md_median_family_income",
)

KEY_COLUMNS = ("activity_year", "state_code", "county_code", "action_taken")
KEEP = KEY_COLUMNS + PROTECTED + CANDIDATE_FEATURES


@dataclass(frozen=True)
class Shard:
    year: int
    state: str

    @property
    def name(self) -> str:
        return f"hmda_{self.year}_{self.state}.parquet"


def _get(url: str, **params) -> requests.Response:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT, stream=True)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:  # red inestable, no error logico
            last = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"fallo tras {RETRIES} intentos: {url} {params}") from last


def official_counts(year: int, state: str) -> dict[str, int]:
    """Conteos oficiales por action_taken, para verificar que la descarga esta completa.

    Es la diferencia entre "descargue un archivo" y "descargue TODO el archivo".
    """
    r = _get(f"{API}/aggregations", years=year, states=state, actions_taken="1,3")
    return {a["actions_taken"]: int(a["count"]) for a in r.json().get("aggregations", [])}


def fetch_shard(shard: Shard, dest_dir: Path, *, force: bool = False) -> dict:
    """Descarga un estado-anio, poda columnas y escribe Parquet. Borra el CSV."""
    out = dest_dir / shard.name
    if out.exists() and not force:
        n = (
            duckdb.connect()
            .execute(f"select count(*) from read_parquet('{out.as_posix()}')")
            .fetchone()[0]
        )
        return {"shard": shard.name, "rows": int(n), "cached": True}

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.csv"
        r = _get(f"{API}/csv", years=shard.year, states=shard.state)
        with raw.open("wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)

        con = duckdb.connect()
        available = {
            row[0]
            for row in con.execute(
                f"describe select * from read_csv('{raw.as_posix()}', "
                "all_varchar=true, sample_size=1000) limit 1"
            ).fetchall()
        }
        cols = [c for c in KEEP if c in available]
        select = ", ".join(f'"{c}"' for c in cols)
        con.execute(f"""
            copy (
                select {select}
                from read_csv('{raw.as_posix()}', all_varchar=true,
                              sample_size=200000, ignore_errors=true)
                where action_taken in ('1', '3')
            ) to '{out.as_posix()}' (format parquet, compression zstd)
        """)
        n = con.execute(f"select count(*) from read_parquet('{out.as_posix()}')").fetchone()[0]

    return {
        "shard": shard.name,
        "rows": int(n),
        "columns": len(cols),
        "cached": False,
        "bytes": out.stat().st_size,
    }


def acquire(
    years: tuple[int, ...], states: tuple[str, ...] = tuple(STATES), *, force: bool = False
) -> dict:
    dest = resolve_path("parquet") / "hmda"
    dest.mkdir(parents=True, exist_ok=True)

    shards = [Shard(y, s) for y in years for s in states]
    print(f"HMDA: {len(shards)} particiones ({len(years)} anios x {len(states)} estados)")
    print(f"Destino: {dest.relative_to(repo_root())}\n")

    entries, total_rows, total_bytes = [], 0, 0
    t0 = time.perf_counter()
    for i, shard in enumerate(shards, 1):
        info = fetch_shard(shard, dest, force=force)
        entries.append(info)
        total_rows += info["rows"]
        total_bytes += info.get("bytes", 0)
        flag = "cache" if info["cached"] else "nuevo"
        print(
            f"  [{i:3d}/{len(shards)}] {shard.name:28s} {info['rows']:>9,} filas  {flag}",
            flush=True,
        )

    manifest = {
        "source": "hmda",
        "acquired_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "years": list(years),
        "n_states": len(states),
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "seconds": round(time.perf_counter() - t0, 1),
        "columns_kept": len(KEEP),
        "excluded": {
            "outcome_only": list(FORBIDDEN_OUTCOME_ONLY),
            "lender_decision": list(FORBIDDEN_LENDER_DECISION),
            "protected_proxy": list(FORBIDDEN_PROXY),
        },
        "shards": entries,
    }
    path = resolve_path("manifests") / "hmda.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\n{total_rows:,} filas, {total_bytes / 1e9:.2f} GB en Parquet")
    print(f"Manifiesto -> {path.relative_to(repo_root())}")
    return manifest


def verify_completeness(years: tuple[int, ...], sample_states: tuple[str, ...]) -> bool:
    """Contrasta lo descargado contra los conteos oficiales de la API.

    Se verifica una MUESTRA de estados, no todos: cada verificacion es una llamada
    de red, y el objetivo es detectar truncamiento sistematico, no auditar cada
    particion.
    """
    dest = resolve_path("parquet") / "hmda"
    con = duckdb.connect()
    ok = True
    for year in years:
        for state in sample_states:
            path = dest / Shard(year, state).name
            if not path.exists():
                print(f"  FALTA    {path.name}")
                ok = False
                continue
            local = con.execute(
                f"select count(*) from read_parquet('{path.as_posix()}')"
            ).fetchone()[0]
            official = sum(official_counts(year, state).values())
            match = local == official
            ok &= match
            print(
                f"  {'OK      ' if match else 'DIFIERE '} {path.name:28s} "
                f"local={local:>9,}  oficial={official:>9,}"
            )
    return ok


def main() -> int:
    from crmlops.config import load_config

    cfg = load_config()
    years = tuple(cfg["sources"]["hmda"]["years"])
    acquire(years)
    return 0


if __name__ == "__main__":
    sys.exit(main())
