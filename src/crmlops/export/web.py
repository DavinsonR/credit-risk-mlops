"""Bundle JSON para el sitio: pequeno, estable y sin un solo numero propio.

REGLA QUE GOBIERNA TODO ESTE MODULO: aqui no se calcula nada. Cada valor se LEE de un
export existente y se copia. Si este modulo promediara, redondeara a criterio propio o
derivara un indicador, el sitio podria mostrar una cifra que no existe en ningun
artefacto auditable, y la trazabilidad --que es el argumento del proyecto-- se
rompe en el ultimo metro.

De ahi salen tres consecuencias de diseno:

  1. `check_coherence()` verifica que lo que sale coincida con la fuente. Es
     redundante por construccion, y ese es el punto: si algun dia alguien agrega una
     transformacion aqui, el chequeo la delata.

  2. Cada payload declara `fuente`: el archivo de `exports/` de donde salio. Un
     revisor puede ir del grafico al artefacto sin preguntar.

  3. `manifest.json` lleva la huella de codigo de `metrics.json`. Si el sitio publica
     un bundle y el modelo se reentrena, la huella cambia y se nota.

POR QUE JSON COMMITEADO Y NO UNA API. Presupuesto cero y un sitio estatico en Vercel.
Un JSON de ~30 KB en el repo no tiene cold start, no tiene cuenta que expire y se
versiona con git: el sitio puede apuntar a un tag y no romperse cuando cambie un
numero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crmlops.config import repo_root

WEB_DIR = "exports/web"
SCHEMA_VERSION = 1

# Cuanto se permite que pese el bundle. No es estetico: el sitio lo carga en el
# navegador de un reclutador que puede estar en datos moviles.
MAX_BYTES_POR_ARCHIVO = 40_000
MAX_BYTES_BUNDLE = 120_000


@dataclass(frozen=True)
class Fuente:
    """Un export de origen, con su ruta relativa para que el sitio la cite."""

    nombre: str
    datos: dict

    @property
    def ruta(self) -> str:
        return f"exports/{self.nombre}"


def _leer(nombre: str, raiz: Path | None = None) -> Fuente | None:
    ruta = (raiz or repo_root()) / "exports" / nombre
    if not ruta.exists():
        return None
    return Fuente(nombre, json.loads(ruta.read_text(encoding="utf-8")))


def cargar(raiz: Path | None = None) -> dict[str, Fuente]:
    """Los exports que alimentan el bundle. Los ausentes se omiten, no se inventan."""
    nombres = (
        "metrics.json",
        "headline_economics.json",
        "hmda_metrics.json",
        "drift.json",
        "maturity.json",
        "retrain_decision.json",
        "causal_identification.json",
    )
    fuentes = {}
    for n in nombres:
        f = _leer(n, raiz)
        if f is not None:
            fuentes[n.removesuffix(".json")] = f
    return fuentes


# --------------------------------------------------------------- payloads


def build_resumen(f: dict[str, Fuente]) -> dict[str, Any]:
    """Los cuatro numeros de arriba del fold, cada uno con su fuente."""
    m, e = f.get("metrics"), f.get("headline_economics")
    h = f.get("hmda_metrics")
    items: list[dict] = []
    if m:
        items.append(
            {
                "clave": "auc_test",
                "valor": m.datos["production_metrics"]["auc_test"],
                "fuente": m.ruta,
            }
        )
    if e:
        d10 = e.datos["at_10pct_decline"]
        # `volumen_bueno_sacrificado` va ARRIBA, junto a la perdida evitada, y no
        # escondido en una nota: para evitar $276.3M se renuncia a $1.99B de volumen
        # sano. Un titular que muestre solo el numerador no es un titular, es una
        # ficha de venta.
        for clave, origen in (
            ("perdida_evitada_usd", "loss_avoided"),
            ("lift_vs_azar", "lift_vs_random"),
            ("volumen_bueno_sacrificado_usd", "good_volume_foregone"),
        ):
            if origen in d10:
                items.append({"clave": clave, "valor": d10[origen], "fuente": e.ruta})
    if h:
        items.append(
            {
                "clave": "disparate_impact_ratio",
                "valor": h.datos["disparate_impact_ratio"],
                "fuente": h.ruta,
            }
        )
    return {"schema_version": SCHEMA_VERSION, "items": items}


def build_modelos(f: dict[str, Fuente]) -> dict[str, Any]:
    m = f.get("metrics")
    if not m:
        return {"schema_version": SCHEMA_VERSION, "modelos": []}
    cols = ("modelo", "auc_test", "gini_test", "ks_test", "brier_test", "ece_test", "drop_oot")
    return {
        "schema_version": SCHEMA_VERSION,
        "fuente": m.ruta,
        "produccion": m.datos["production_model"],
        "baseline": "scorecard_woe",
        "modelos": [{c: r[c] for c in cols if c in r} for r in m.datos["models"]],
    }


def build_economia(f: dict[str, Fuente]) -> dict[str, Any]:
    e = f.get("headline_economics")
    if not e:
        return {"schema_version": SCHEMA_VERSION}
    d = e.datos
    return {
        "schema_version": SCHEMA_VERSION,
        "fuente": e.ruta,
        "ventana": d["test_window"],
        "n_prestamos": d["n_loans"],
        "monto_prestado_usd": d["total_lent"],
        "perdida_realizada_usd": d["realized_loss"],
        "absorbe_sba_usd": d["sba_absorbed_loss"],
        "absorbe_banco_usd": d["lender_absorbed_loss"],
        "al_10_por_ciento": d["at_10pct_decline"],
        # El supuesto viaja CON el numero. Sin el, "se habrian evitado $276.3M" es una
        # afirmacion causal disfrazada de prediccion (ver docs/adr/0013).
        "supuesto": d["assumption"],
    }


def build_equidad(f: dict[str, Fuente]) -> dict[str, Any]:
    h = f.get("hmda_metrics")
    if not h:
        return {"schema_version": SCHEMA_VERSION}
    d = h.datos
    return {
        "schema_version": SCHEMA_VERSION,
        "fuente": h.ruta,
        "auc_test": d["auc_test"],
        "disparate_impact_ratio": d["disparate_impact_ratio"],
        "peor_grupo": d["worst_dimension_group"],
        "promovido": d.get("promoted"),
        "bloqueado_por": d.get("promotion_blocked_by"),
        "delta_vs_observado": d.get("fairness_delta"),
    }


def build_monitoreo(f: dict[str, Fuente]) -> dict[str, Any]:
    dr, ma, re = f.get("drift"), f.get("maturity"), f.get("retrain_decision")
    salida: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if dr:
        salida["deriva"] = {
            "fuente": dr.ruta,
            "as_of": dr.datos["as_of"],
            "referencia": dr.datos["reference"],
            "cohortes": [
                {
                    "approval_fy": c["approval_fy"],
                    "n": c["n"],
                    "peor_feature": c["peor_feature"],
                    "peor_psi": c["peor_psi"],
                    "sin_soporte": c.get("sin_soporte") or {},
                    "score_psi_forma": c.get("score_psi_forma"),
                }
                for c in dr.datos["cohorts"]
            ],
        }
    if ma:
        salida["madurez"] = {
            "fuente": ma.ruta,
            "meses_a_chargeoff": ma.datos["meses_a_chargeoff"],
            "referencia": ma.datos["referencia_madurez_pareja"],
            "por_cosecha": [
                r for r in ma.datos["madurez_pareja"] if r.get("observable") and r.get("tasa")
            ],
        }
    if re:
        salida["decision"] = {
            "fuente": re.ruta,
            "reentrenar": re.datos["should_retrain"],
            "disparadores": re.datos["triggers"],
        }
    return salida


def build_causal(f: dict[str, Fuente]) -> dict[str, Any]:
    c = f.get("causal_identification")
    if not c:
        return {"schema_version": SCHEMA_VERSION}
    d = c.datos
    return {
        "schema_version": SCHEMA_VERSION,
        "fuente": c.ruta,
        "tratamiento": d["tratamiento"],
        "veredicto": d["veredicto"],
        "determinacion": {k: d["determinacion"][k] for k in ("n", "celdas", "r2", "identificable")},
        "densidad": {
            "umbral_usd": d["densidad"]["umbral"],
            "n_exacto": d["densidad"]["n_exacto"],
            "por_ventana": d["densidad"]["por_ventana"],
            "rd_explotable": d["densidad"]["rd_explotable"],
        },
        "gradiente": {
            k: d["gradiente"][k]
            for k in ("crudo_pp", "dentro_de_tramo_pp", "explicado_por_tamano", "n_comparable")
        },
    }


PAYLOADS = {
    "resumen": build_resumen,
    "modelos": build_modelos,
    "economia": build_economia,
    "equidad": build_equidad,
    "monitoreo": build_monitoreo,
    "causal": build_causal,
}


# --------------------------------------------------------------- coherencia


def check_coherence(bundle: dict[str, dict], fuentes: dict[str, Fuente]) -> list[str]:
    """Que lo publicado coincida con su fuente. Redundante a proposito.

    Si alguien agrega una transformacion en un `build_*`, esto la delata. Es el mismo
    principio del gate de integridad: no creerle al artefacto, recomputar contra el
    origen.
    """
    problemas: list[str] = []

    m = fuentes.get("metrics")
    if m and bundle.get("modelos", {}).get("modelos"):
        origen = {r["modelo"]: r["auc_test"] for r in m.datos["models"]}
        for fila in bundle["modelos"]["modelos"]:
            esperado = origen.get(fila["modelo"])
            if esperado is not None and fila["auc_test"] != esperado:
                problemas.append(
                    f"modelos: {fila['modelo']} auc {fila['auc_test']} != {esperado} en {m.ruta}"
                )

    e = fuentes.get("headline_economics")
    eco = bundle.get("economia", {})
    if (
        e
        and eco.get("al_10_por_ciento") != e.datos["at_10pct_decline"]
        and "al_10_por_ciento" in eco
    ):
        problemas.append("economia: el bloque al 10% no coincide con su fuente")

    h = fuentes.get("hmda_metrics")
    eq = bundle.get("equidad", {})
    if (
        h
        and "disparate_impact_ratio" in eq
        and eq["disparate_impact_ratio"] != h.datos["disparate_impact_ratio"]
    ):
        problemas.append("equidad: el disparate impact no coincide con su fuente")

    for nombre, payload in bundle.items():
        peso = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if peso > MAX_BYTES_POR_ARCHIVO:
            problemas.append(f"{nombre}: {peso:,} bytes > {MAX_BYTES_POR_ARCHIVO:,}")

    return problemas


def build_manifest(bundle: dict[str, dict], fuentes: dict[str, Fuente]) -> dict[str, Any]:
    m = fuentes.get("metrics")
    return {
        "schema_version": SCHEMA_VERSION,
        # NO se pone una marca de tiempo de reloj: haria que el bundle cambiara en
        # cada corrida y el diff de git dejaria de significar algo. La procedencia la
        # dan las huellas, que si cambian cuando cambia el modelo.
        "vintage": m.datos["vintage"] if m else None,
        "config_fingerprint": m.datos["config_fingerprint"] if m else None,
        "code_fingerprint": m.datos["code_fingerprint"] if m else None,
        "archivos": {
            nombre: {
                "bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                "fuentes": sorted({f.ruta for f in fuentes.values()} & _fuentes_citadas(payload)),
            }
            for nombre, payload in bundle.items()
        },
    }


def _fuentes_citadas(payload: Any) -> set[str]:
    """Recolecta los valores de las claves `fuente` en cualquier nivel."""
    encontradas: set[str] = set()
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "fuente" and isinstance(v, str):
                encontradas.add(v)
            else:
                encontradas |= _fuentes_citadas(v)
    elif isinstance(payload, list):
        for item in payload:
            encontradas |= _fuentes_citadas(item)
    return encontradas


# --------------------------------------------------------------- escritura


def build(raiz: Path | None = None) -> tuple[dict[str, dict], dict[str, Fuente]]:
    fuentes = cargar(raiz)
    bundle = {nombre: fn(fuentes) for nombre, fn in PAYLOADS.items()}
    return bundle, fuentes


def write(bundle: dict[str, dict], manifest: dict, raiz: Path | None = None) -> Path:
    destino = (raiz or repo_root()) / WEB_DIR
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, payload in bundle.items():
        (destino / f"{nombre}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    (destino / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return destino


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = argv if argv is not None else sys.argv[1:]
    solo_chequeo = "--check" in argv

    bundle, fuentes = build()
    problemas = check_coherence(bundle, fuentes)
    manifest = build_manifest(bundle, fuentes)
    total = sum(v["bytes"] for v in manifest["archivos"].values())

    print("=" * 88)
    print("BUNDLE WEB — JSON para el sitio, sin un solo numero propio")
    print("=" * 88)
    for nombre, info in sorted(manifest["archivos"].items()):
        citadas = ", ".join(Path(r).name for r in info["fuentes"]) or "-"
        print(f"  {nombre:12s} {info['bytes']:>7,} bytes   <- {citadas}")
    print(f"  {'TOTAL':12s} {total:>7,} bytes   (limite {MAX_BYTES_BUNDLE:,})")

    if total > MAX_BYTES_BUNDLE:
        problemas.append(f"bundle: {total:,} bytes > {MAX_BYTES_BUNDLE:,}")

    if problemas:
        print()
        print("PROBLEMAS:")
        for p in problemas:
            print(f"  - {p}")
        return 1

    if solo_chequeo:
        print("\nCoherente con las fuentes. (--check: no se escribio nada)")
        return 0

    destino = write(bundle, manifest)
    print(f"\nEscrito en {destino}")
    print("Cada payload cita el export del que salio; el manifiesto lleva las huellas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
