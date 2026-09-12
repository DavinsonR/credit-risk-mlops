"""El bundle web no puede tener numeros propios.

Es el ultimo metro de la trazabilidad: el sitio muestra un numero y alguien pregunta
de donde salio. Si este modulo promediara, redondeara o derivara algo, la respuesta
seria "de un script", y el argumento del proyecto se cae justo donde mas se ve.

`check_coherence` es redundante por construccion --compara la salida contra la fuente
que acaba de copiar-- y ese es el punto: delata cualquier transformacion que alguien
agregue despues. Estos tests verifican que el chequeo NO sea decorativo: le meten una
divergencia y comprueban que la encuentre.
"""

from __future__ import annotations

import json

import pytest

from crmlops.export.web import (
    MAX_BYTES_POR_ARCHIVO,
    SCHEMA_VERSION,
    Fuente,
    build,
    build_manifest,
    build_modelos,
    build_resumen,
    check_coherence,
    write,
)


@pytest.fixture
def fuentes() -> dict[str, Fuente]:
    return {
        "metrics": Fuente(
            "metrics.json",
            {
                "vintage": "260630",
                "config_fingerprint": "cfg123",
                "code_fingerprint": "code456",
                "production_model": "lightgbm",
                "production_metrics": {"auc_test": 0.7005},
                "models": [
                    {"modelo": "lightgbm", "auc_test": 0.7005, "gini_test": 0.4009},
                    {"modelo": "scorecard_woe", "auc_test": 0.6694, "gini_test": 0.3388},
                ],
            },
        ),
        "headline_economics": Fuente(
            "headline_economics.json",
            {
                "test_window": "FY2017-2018",
                "n_loans": 89_313,
                "total_lent": 33_000_000_000,
                "realized_loss": 1_300_000_000,
                "sba_absorbed_loss": 942_100_000,
                "lender_absorbed_loss": 345_800_000,
                "at_10pct_decline": {
                    "loss_avoided": 276_300_000,
                    "lift_vs_random": 2.15,
                    "good_volume_foregone": 1_992_446_200,
                },
                "assumption": "rechazar elimina la perdida",
            },
        ),
        "hmda_metrics": Fuente(
            "hmda_metrics.json",
            {
                "auc_test": 0.8847,
                "disparate_impact_ratio": 0.7639,
                "worst_dimension_group": "NHPI",
                "promoted": False,
                "promotion_blocked_by": "dir < 0.8",
            },
        ),
    }


# --- el chequeo de coherencia detecta lo que dice detectar ---


def test_un_bundle_fiel_no_tiene_problemas(fuentes):
    bundle, _ = {n: f for n, f in [("modelos", build_modelos(fuentes))]}, None
    assert check_coherence(bundle, fuentes) == []


def test_detecta_un_auc_alterado(fuentes):
    bundle = {"modelos": build_modelos(fuentes)}
    bundle["modelos"]["modelos"][0]["auc_test"] = 0.95  # alguien "mejoro" el numero
    problemas = check_coherence(bundle, fuentes)
    assert problemas and "auc" in problemas[0]


def test_detecta_un_bloque_de_economia_alterado(fuentes):
    from crmlops.export.web import build_economia

    bundle = {"economia": build_economia(fuentes)}
    bundle["economia"]["al_10_por_ciento"] = {"loss_avoided": 999_000_000}
    assert any("economia" in p for p in check_coherence(bundle, fuentes))


def test_detecta_un_disparate_impact_alterado(fuentes):
    from crmlops.export.web import build_equidad

    bundle = {"equidad": build_equidad(fuentes)}
    bundle["equidad"]["disparate_impact_ratio"] = 0.81  # justo por encima del umbral
    assert any("equidad" in p for p in check_coherence(bundle, fuentes))


def test_detecta_un_payload_demasiado_grande(fuentes):
    bundle = {"gordo": {"relleno": ["x" * 100] * 1000}}
    problemas = check_coherence(bundle, fuentes)
    assert any("bytes" in p for p in problemas)
    assert str(MAX_BYTES_POR_ARCHIVO) in " ".join(problemas).replace(",", "")


# --- procedencia ---


def test_cada_numero_del_resumen_cita_su_fuente(fuentes):
    r = build_resumen(fuentes)
    assert r["items"], "el resumen quedo vacio"
    for item in r["items"]:
        assert item["fuente"].startswith("exports/"), item
        assert item["valor"] is not None


def test_el_manifiesto_lleva_las_huellas_del_modelo(fuentes):
    bundle = {"modelos": build_modelos(fuentes)}
    man = build_manifest(bundle, fuentes)
    assert man["code_fingerprint"] == "code456"
    assert man["config_fingerprint"] == "cfg123"
    assert man["vintage"] == "260630"


def test_el_manifiesto_no_lleva_marca_de_tiempo(fuentes):
    """Una marca de reloj haria que el bundle cambiara en cada corrida.

    El diff de git dejaria de significar algo: no se podria distinguir "se
    republico" de "cambio un numero". La procedencia la dan las huellas.
    """
    man = build_manifest({"modelos": build_modelos(fuentes)}, fuentes)
    texto = json.dumps(man).lower()
    for prohibido in ("generated_at", "timestamp", "created_at"):
        assert prohibido not in texto


def test_la_economia_publica_el_supuesto_junto_al_numero(fuentes):
    from crmlops.export.web import build_economia

    eco = build_economia(fuentes)
    assert eco["supuesto"], "el supuesto causal tiene que viajar con la cifra"
    assert eco["al_10_por_ciento"]["loss_avoided"] == 276_300_000


def test_el_resumen_muestra_el_volumen_sacrificado_junto_a_la_perdida_evitada(fuentes):
    """El contrapeso del titular no puede quedar en una nota al pie.

    Para evitar $276.3M se renuncia a $1.99B de volumen sano: 7.2x. Un titular que
    muestre solo el numerador no es un titular, es una ficha de venta.
    """
    claves = {i["clave"] for i in build_resumen(fuentes)["items"]}
    assert "perdida_evitada_usd" in claves
    assert "volumen_bueno_sacrificado_usd" in claves


def test_una_clave_ausente_se_omite_en_vez_de_reventar(fuentes):
    """Un export viejo sin `good_volume_foregone` no debe tumbar el bundle."""
    del fuentes["headline_economics"].datos["at_10pct_decline"]["good_volume_foregone"]
    claves = {i["clave"] for i in build_resumen(fuentes)["items"]}
    assert "volumen_bueno_sacrificado_usd" not in claves
    assert "perdida_evitada_usd" in claves


# --- escritura ---


def test_se_escribe_JSON_valido_y_sin_no_finitos(fuentes, tmp_path):
    bundle, _ = build(tmp_path)  # sin exports: payloads vacios pero validos
    bundle["modelos"] = build_modelos(fuentes)
    destino = write(bundle, build_manifest(bundle, fuentes), tmp_path)

    for archivo in destino.glob("*.json"):
        texto = archivo.read_text(encoding="utf-8")
        assert "Infinity" not in texto and "NaN" not in texto, archivo.name
        datos = json.loads(texto)
        if archivo.name != "manifest.json":
            assert datos.get("schema_version") == SCHEMA_VERSION, archivo.name


def test_sin_exports_no_se_inventa_nada(tmp_path):
    """Un export ausente produce un payload vacio, no un cero ni un placeholder."""
    bundle, fuentes = build(tmp_path)
    assert fuentes == {}
    assert bundle["resumen"]["items"] == []
    assert bundle["modelos"]["modelos"] == []
