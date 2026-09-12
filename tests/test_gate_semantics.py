"""Un gate que dice "PASA" cuando el modelo no cumple es peor que no tener gate.

`GateResult` tenia un solo campo booleano, `passed`, para dos hechos distintos: si
el build pasa y si el modelo cumple el umbral. Coinciden en casi todos los gates y
NO coinciden en el de equidad, donde un modelo con disparate impact 0.7639 no cumple
el 0.80 y sin embargo el build pasa porque el modelo esta marcado `promoted: false`.

El resultado se publico: `reports/VALIDATION_REPORT.md` imprimia

    | `hmda:disparate_impact` | 0.7639 | >= 0.8 | PASA |

en la seccion 3.1 y "No apto -- promocion bloqueada" en la seccion 5. Mismo gate,
mismo documento. Y `reports/MODEL_CARD.md` listaba 7 gates porque su generador nunca
llamaba a `evaluate_fairness`: omitia justo el unico que el modelo no cumple.

Estos tests fijan las dos cosas.
"""

from __future__ import annotations

import json

import pytest

from crmlops.governance.gates import GateResult, evaluate_fairness, evaluate_reports

# --- la semantica de los dos campos ---


def test_un_gate_normal_tiene_los_dos_hechos_alineados():
    r = GateResult("auc_test", 0.70, 0.6894, "min", passed=True)
    assert r.threshold_met is True, "sin especificar, threshold_met sigue a passed"
    assert r.veredicto == "PASA"


def test_un_gate_que_rompe_el_build_dice_FALLA():
    r = GateResult("auc_test", 0.60, 0.6894, "min", passed=False)
    assert r.veredicto == "FALLA"


def test_el_caso_del_gate_de_equidad_no_dice_PASA():
    """El defecto exacto: build ok, modelo no cumple. No puede leerse como exito."""
    r = GateResult("hmda:disparate_impact", 0.7639, 0.8, "min", passed=True, threshold_met=False)
    assert r.veredicto != "PASA"
    assert "NO CUMPLE" in r.veredicto
    assert "PASA" not in r.render(), f"el render sigue diciendo PASA: {r.render()!r}"


# --- el gate de equidad sobre el artefacto real ---


def test_el_gate_de_equidad_separa_cumplimiento_de_promocion():
    resultados = evaluate_fairness()
    if not resultados:
        pytest.skip("falta exports/hmda_metrics.json")
    g = resultados[0]
    assert g.value is not None
    if g.value < g.threshold:
        assert g.threshold_met is False, "no cumple el umbral y threshold_met dice que si"


def test_el_gate_exige_que_el_artefacto_declare_promoted(tmp_path):
    """El control descansaba en `.get('promoted', False)`: pasaba por DEFECTO.

    Si nadie escribe la bandera, el gate no puede distinguir "no se promueve" de
    "no se sabe", y elegir el caso benigno es exactamente el fallo silencioso que
    este proyecto persigue.
    """
    ruta = tmp_path / "hmda_metrics.json"
    ruta.write_text(json.dumps({"disparate_impact_ratio": 0.70}), encoding="utf-8")
    g = evaluate_fairness(path=ruta)[0]
    assert not g.passed
    assert "promoted" in g.detail


# --- reportes rancios ---


def test_detecta_un_reporte_que_no_corresponde_a_las_metricas(tmp_path):
    """`MODEL_CARD.md` estuvo congelado desde la semana 4 y nada avisaba."""
    (tmp_path / "exports").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "exports" / "metrics.json").write_text(
        json.dumps({"code_fingerprint": "abc123def456"}), encoding="utf-8"
    )
    (tmp_path / "reports" / "MODEL_CARD.md").write_text(
        "codigo `huella_vieja_0000`", encoding="utf-8"
    )
    (tmp_path / "reports" / "VALIDATION_REPORT.md").write_text(
        "codigo `abc123def456`", encoding="utf-8"
    )

    resultados = {r.name: r for r in evaluate_reports(root=tmp_path)}
    assert not resultados["reporte:MODEL_CARD.md"].passed
    assert "rancio" in resultados["reporte:MODEL_CARD.md"].detail
    assert resultados["reporte:VALIDATION_REPORT.md"].passed


def test_un_reporte_ausente_tambien_falla(tmp_path):
    (tmp_path / "exports").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "exports" / "metrics.json").write_text(
        json.dumps({"code_fingerprint": "abc123"}), encoding="utf-8"
    )
    resultados = {r.name: r for r in evaluate_reports(root=tmp_path)}
    assert all(not r.passed for r in resultados.values())
    assert "falta" in resultados["reporte:MODEL_CARD.md"].detail


def test_los_reportes_publicados_estan_al_dia():
    """Sobre el repo real: si esto falla, correr `card` y `validation`."""
    for r in evaluate_reports():
        assert r.passed, f"{r.name}: {r.detail}"
