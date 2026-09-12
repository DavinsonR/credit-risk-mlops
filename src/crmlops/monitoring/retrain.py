"""Decision de reentrenamiento: disparadores y gate de promocion.

EL DISPARADOR NO PUEDE SER "CAYO EL AUC". Ese numero no esta disponible a tiempo:
la etiqueta tarda 51 meses medianos en existir (ADR 0010). Un sistema que espera a
que caiga el AUC para reentrenar espera cuatro anios.

Asi que los disparadores son tres, todos medibles el dia que llega el vintage:

  1. VOCABULARIO. Una categorica cuya masa cae en categorias sin soporte en
     entrenamiento. Es la mas grave de las tres, porque el modelo no se degrada:
     pierde la variable entera y sigue respondiendo con aplomo.
  2. FORMA DEL SCORE. PSI de forma sobre el umbral: la mezcla cambio, no solo el
     nivel. Un corrimiento de nivel se arregla recalibrando, y por eso se separan.
  3. MADUREZ PAREJA. La cosecha mas joven que alcanzo la ventana de 24 meses falla
     fuera de la tolerancia derivada de la variacion natural entre las cosechas de
     entrenamiento.

Y UNA HONESTIDAD QUE EL MODULO IMPRIME EN VEZ DE ESCONDER: que el disparador se
active no significa que reentrenar arregle el problema. Si el vocabulario de la
fuente cambio, reentrenar sobre la misma ventana no cambia nada, y reentrenar sobre
la ventana nueva choca con la madurez de la etiqueta. El modulo dice cual es el
caso; la decision es humana y queda documentada.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from crmlops.config import load_config, repo_root

DECISION_PATH = "exports/retrain_decision.json"


@dataclass
class Trigger:
    name: str
    fired: bool
    detail: str
    action: str


def _drift_payload() -> dict:
    ruta = repo_root() / "exports" / "drift.json"
    if not ruta.exists():
        raise FileNotFoundError(
            f"Falta {ruta}. Correr primero:  uv run python -m crmlops.monitoring.drift"
        )
    return json.loads(ruta.read_text(encoding="utf-8"))


def _maturity_payload() -> dict:
    ruta = repo_root() / "exports" / "maturity.json"
    if not ruta.exists():
        raise FileNotFoundError(
            f"Falta {ruta}. Correr primero:  uv run python -m crmlops.monitoring.maturity"
        )
    return json.loads(ruta.read_text(encoding="utf-8"))


def trigger_vocabulario(drift: dict) -> Trigger:
    """La mas grave: el modelo pierde la variable, no la degrada."""
    afectadas: dict[str, float] = {}
    for c in drift["cohorts"]:
        for feat, masa in (c.get("sin_soporte") or {}).items():
            afectadas[feat] = max(afectadas.get(feat, 0.0), float(masa))
    if not afectadas:
        return Trigger("vocabulario", False, "ninguna categorica sin soporte", "ninguna")
    detalle = ", ".join(f"{k} {v:.1%}" for k, v in sorted(afectadas.items(), key=lambda x: -x[1]))
    return Trigger(
        "vocabulario",
        True,
        detalle,
        "REENTRENAR NO ALCANZA: hay que armonizar el vocabulario o cambiar la ventana",
    )


def trigger_forma_del_score(drift: dict, umbral: float) -> Trigger:
    """PSI de forma: la mezcla cambio, no solo el nivel."""
    peor, cosecha = 0.0, None
    for c in drift["cohorts"]:
        v = c.get("score_psi_forma")
        if v is not None and float(v) > peor:
            peor, cosecha = float(v), c["approval_fy"]
    if peor < umbral:
        return Trigger(
            "forma_del_score", False, f"maximo PSI de forma {peor:.4f} < {umbral}", "ninguna"
        )
    return Trigger(
        "forma_del_score",
        True,
        f"PSI de forma {peor:.4f} en FY{cosecha} (umbral {umbral})",
        "reentrenar: recalibrar no corrige un cambio de mezcla",
    )


def trigger_madurez_pareja(maturity: dict, ventana: int, tolerancia: float) -> Trigger:
    """La cosecha mas joven que alcanzo la ventana, contra la referencia."""
    ref = maturity["referencia_madurez_pareja"].get(str(ventana))
    if ref is None:
        return Trigger(
            "madurez_pareja", False, f"sin referencia para la ventana de {ventana}m", "ninguna"
        )
    ref = float(ref)

    candidatas = [
        r
        for r in maturity["madurez_pareja"]
        if r["ventana_meses"] == ventana and r.get("observable") and r.get("tasa") is not None
    ]
    if not candidatas:
        return Trigger("madurez_pareja", False, "ninguna cosecha alcanza la ventana", "ninguna")

    mas_joven = max(candidatas, key=lambda r: r["fy"])
    tasa = float(mas_joven["tasa"])
    desvio = (tasa - ref) / ref
    fuera = abs(desvio) > tolerancia
    detalle = (
        f"FY{mas_joven['fy']} a {ventana}m: {tasa:.2f}% vs referencia {ref:.2f}% "
        f"({desvio:+.0%}, tolerancia +-{tolerancia:.0%})"
    )
    return Trigger(
        "madurez_pareja",
        fuera,
        detalle,
        "reentrenar con una ventana que incluya el regimen nuevo" if fuera else "ninguna",
    )


def evaluate() -> list[Trigger]:
    cfg = load_config()
    mon = cfg["monitoring"]
    drift = _drift_payload()
    maturity = _maturity_payload()
    return [
        trigger_vocabulario(drift),
        trigger_forma_del_score(drift, float(mon["psi_warn"])),
        trigger_madurez_pareja(
            maturity,
            int(mon["matched_maturity_window_months"]),
            float(mon["matched_maturity_tolerance"]),
        ),
    ]


def main() -> int:
    triggers = evaluate()
    print("=" * 92)
    print("DECISION DE REENTRENAMIENTO")
    print("=" * 92)
    for t in triggers:
        marca = "DISPARA" if t.fired else "   ok  "
        print(f"  {marca}  {t.name:18s} {t.detail}")
        if t.fired:
            print(f"           -> {t.action}")

    disparados = [t for t in triggers if t.fired]
    print("=" * 92)
    if not disparados:
        print("Sin señales: el modelo sigue aplicandose a la poblacion para la que se valido.")
    else:
        print(f"{len(disparados)} de {len(triggers)} disparadores activos.")
        print()
        print("LO QUE REENTRENAR SI Y NO ARREGLA — y esto no es un detalle:")
        print("  - Si cambio el VOCABULARIO de una categorica, reentrenar sobre la misma")
        print("    ventana no cambia nada: esa ventana tiene el vocabulario viejo.")
        print("  - Reentrenar sobre la ventana nueva choca con la madurez de la etiqueta:")
        print("    FY2019 esta al 60.9% resuelto y de ahi hacia adelante baja. Un modelo")
        print("    entrenado ahi aprende de los que resolvieron rapido, que son los que")
        print("    fallan (ADR 0003 y 0010).")
        print("  - La salida es armonizar el vocabulario --mapear las categorias nuevas a")
        print("    las viejas donde describan lo mismo-- y recien entonces reentrenar.")
        print()
        print("El modelo NO se promueve solo. `crmlops.governance.gates` sigue siendo el")
        print("juez, y hoy ya bloquea el modelo de acceso por disparate impact.")

    salida = repo_root() / DECISION_PATH
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(
            {
                "should_retrain": bool(disparados),
                "triggers": [asdict(t) for t in triggers],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nExportado a {salida}")
    # Exit 0 siempre: esto es un diagnostico, no un gate. El que bloquea es
    # `gates.py`, y confundirlos haria que un workflow de monitoreo falle en rojo
    # cada vez que detecta algo, que es justamente cuando tiene que funcionar.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
