"""El mapeo de `business_age`: que se afirma y que se deja sin afirmar.

Estos tests no comprueban un AUC --eso exige los datos descargados-- sino las
propiedades del MAPEO, que es donde vive la decision. Un diccionario de equivalencias
que nadie contrasta es exactamente el artefacto que el ADR 0011 se negaba a escribir.
"""

from __future__ import annotations

import pandas as pd
import pytest

from crmlops.monitoring import harmonize as h
from crmlops.monitoring.drift import MIN_SUPPORT


def test_todo_destino_esta_declarado():
    """Ninguna categoria se mapea a un bucket que el modulo no declaro."""
    assert set(h.MAPEO.values()) <= set(h.DESTINO)


def test_el_esquema_nuevo_es_punto_fijo():
    """Armonizar dos veces da lo mismo que armonizar una.

    Si no fuera idempotente, aplicarlo al dato ya nuevo lo movería otra vez y el
    serving daria resultados distintos segun por donde entro el registro.
    """
    for cat in h.DESTINO:
        assert h.MAPEO[cat] == cat, f"{cat} no es punto fijo"
    s = pd.Series(list(h.MAPEO))
    assert h.armonizar(h.armonizar(s)).tolist() == h.armonizar(s).tolist()


def test_lo_desconocido_no_se_inventa():
    """Una categoria fuera del mapeo va a UNKNOWN, nunca a una adivinada."""
    s = pd.Series(["Existing, 5 or more years", "Una categoria que no existe", None, 42])
    out = h.armonizar(s).tolist()
    assert out[0] == "Existing or more than 2 years old"
    assert out[1] == h.UNKNOWN
    assert out[2] == h.UNKNOWN
    assert out[3] == h.UNKNOWN


def test_change_of_ownership_no_se_mapea_a_una_antiguedad():
    """El limite honesto del mapeo, afirmado como test y no solo como comentario.

    'Change of Ownership' es una forma de adquisicion, no una antiguedad. Si alguien
    lo mapeara a 'Existing or more than 2 years old' para subir la cobertura, este
    test lo bloquea: el 9.7% irreducible que publica el ADR 0011 dejaria de ser
    cierto sin que nadie lo notara.
    """
    assert "Change of Ownership" in h.SIN_ORIGEN
    assert h.MAPEO["Change of Ownership"] == "Change of Ownership"
    origenes = [k for k, v in h.MAPEO.items() if v == "Change of Ownership"]
    assert origenes == ["Change of Ownership"], (
        f"algo mas se mapea a Change of Ownership: {origenes}"
    )


def test_el_colapso_va_de_fino_a_grueso():
    """Cuatro tramos de antiguedad caen en uno. Nunca al reves."""
    finos = [
        "Existing, 5 or more years",
        "Less than 5 years old but at least 4",
        "Less than 4 years old but at least 3",
        "Less than 3 years old but at least 2",
    ]
    assert {h.MAPEO[c] for c in finos} == {"Existing or more than 2 years old"}
    # Y ninguna categoria gruesa se parte en varias: el mapeo es una funcion.
    assert len(set(h.MAPEO.values())) < len(h.MAPEO)


def test_cobertura_usa_soporte_y_no_presencia():
    """Una categoria presente pero marginal NO cuenta como soportada.

    Es la correccion que el ADR 0011 ya tuvo que hacer una vez:
    'Existing or more than 2 years old' existe en entrenamiento con el 0.01% de la
    masa, asi que contarla como cubierta convertia un 84% de problema en un 30%.
    """
    vocab = {"Existing, 5 or more years": 0.80, "Existing or more than 2 years old": 0.0001}
    soportadas = {k for k, v in vocab.items() if v >= MIN_SUPPORT}
    assert soportadas == {"Existing, 5 or more years"}
    assert vocab["Existing or more than 2 years old"] < MIN_SUPPORT


def test_el_soporte_armonizado_suma_el_de_sus_origenes():
    """Cuatro categorias del 4% se vuelven una del 16%, no cuatro del 4%.

    Sin la suma, un mapeo correcto seguiria pareciendo sin soporte y la cobertura
    recuperada saldria en cero.
    """
    vocab = {
        "Existing, 5 or more years": 0.004,
        "Less than 5 years old but at least 4": 0.004,
        "Less than 4 years old but at least 3": 0.004,
        "Less than 3 years old but at least 2": 0.004,
    }
    agregado: dict[str, float] = {}
    for cat, prop in vocab.items():
        destino = h.MAPEO[cat]
        agregado[destino] = agregado.get(destino, 0.0) + prop
    assert all(v < MIN_SUPPORT for v in vocab.values())
    assert agregado["Existing or more than 2 years old"] == pytest.approx(0.016)
    assert agregado["Existing or more than 2 years old"] >= MIN_SUPPORT
