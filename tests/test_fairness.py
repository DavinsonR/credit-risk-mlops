"""Las métricas de equidad tienen que detectar disparidad, y no inventarla."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crmlops.fairness.metrics import (
    FOUR_FIFTHS,
    evaluate,
    threshold_for_approval_rate,
)


def _mundo(n: int = 20_000, sesgo: float = 0.0, seed: int = 0):
    """Dos grupos. `sesgo` desplaza el score del grupo B hacia mas riesgo."""
    rng = np.random.default_rng(seed)
    grupo = np.where(rng.random(n) < 0.5, "A", "B")
    base = rng.random(n)
    score = np.clip(base + np.where(grupo == "B", sesgo, 0.0), 0.001, 0.999)
    y = (rng.random(n) < score).astype(int)
    return y, score, pd.Series(grupo)


def test_sin_sesgo_el_ratio_es_cercano_a_uno():
    y, s, g = _mundo(sesgo=0.0)
    rep = evaluate(y, s, g, threshold=threshold_for_approval_rate(s, 0.75))
    assert rep.disparate_impact_ratio > 0.95
    assert rep.passes_four_fifths


def test_detecta_disparidad_severa():
    y, s, g = _mundo(sesgo=0.35)
    rep = evaluate(y, s, g, threshold=threshold_for_approval_rate(s, 0.75))
    assert rep.disparate_impact_ratio < FOUR_FIFTHS
    assert not rep.passes_four_fifths
    assert rep.worst_group == "B"


def test_el_umbral_produce_la_tasa_de_aprobacion_pedida():
    _, s, _ = _mundo()
    for rate in (0.5, 0.75, 0.9):
        thr = threshold_for_approval_rate(s, rate)
        assert abs(float(np.mean(s < thr)) - rate) < 0.01


def test_excluye_categorias_que_no_son_grupos():
    """'Race Not Available' agrupa a quienes no declararon: no es demografia."""
    y, s, g = _mundo(n=6000)
    g = g.copy()
    g.iloc[:2000] = "Race Not Available"
    rep = evaluate(y, s, g, threshold=threshold_for_approval_rate(s, 0.75))
    assert "Race Not Available" not in {o.group for o in rep.groups}
    assert any("Race Not Available" in n for n in rep.notes)


def test_excluye_grupos_demasiado_pequenos_y_lo_declara():
    y, s, g = _mundo(n=6000)
    g = g.copy()
    g.iloc[:50] = "Diminuto"
    rep = evaluate(y, s, g, threshold=threshold_for_approval_rate(s, 0.75), min_group_size=500)
    assert "Diminuto" not in {o.group for o in rep.groups}
    assert any("Diminuto" in n for n in rep.notes)


def test_la_referencia_es_el_grupo_con_mayor_aprobacion():
    """Como en un examen de fair lending: cuanto peor le va al resto."""
    y, s, g = _mundo(sesgo=0.3)
    rep = evaluate(y, s, g, threshold=threshold_for_approval_rate(s, 0.75))
    tasas = {o.group: o.selection_rate for o in rep.groups}
    assert rep.reference_group == max(tasas, key=tasas.get)


def test_sin_grupos_evaluables_no_revienta():
    y, s, g = _mundo(n=600)
    rep = evaluate(y, s, g, threshold=0.5, min_group_size=10_000)
    assert rep.groups == []
    assert rep.disparate_impact_ratio != rep.disparate_impact_ratio  # NaN


@pytest.mark.parametrize("rate", [0.6, 0.8])
def test_comparar_a_igual_tasa_de_aprobacion_aisla_la_equidad(rate):
    """Un modelo mas estricto no debe parecer mas injusto solo por serlo.

    Con la misma disparidad subyacente, el ratio no debe cambiar mucho al mover
    la tasa de aprobacion: si cambiara, se estaria midiendo severidad y no equidad.
    """
    y, s, g = _mundo(sesgo=0.2)
    rep = evaluate(y, s, g, threshold=threshold_for_approval_rate(s, rate))
    assert 0.5 < rep.disparate_impact_ratio < 1.0
