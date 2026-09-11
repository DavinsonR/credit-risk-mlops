"""La madurez de la cosecha decide qué se puede medir, así que hay que medirla bien.

El test que importa es el de la ventana no alcanzada. Una cosecha que solo tiene
21 meses observables no puede reportar su tasa a 24 ni a 48: una implementación
ingenua devuelve el mismo valor que a 21 —no hay nada más que contar— y la tabla
se lee como una curva que se aplana en vez de como un dato que falta.

Le pasó a la primera versión del análisis. Ver docs/adr/0010.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from crmlops.monitoring.maturity import (
    DEFAULT_WINDOWS,
    Observabilidad,
    matched_maturity,
    observabilidad,
    reference_rates,
)

pytestmark = pytest.mark.data  # necesita los CSV crudos de SBA


# --- la regla de observabilidad, sin tocar datos ---


def test_una_cosecha_joven_no_alcanza_las_ventanas_largas():
    """FY2024 con corte a junio de 2026: 21 meses. No puede reportar 24m."""
    obs = Observabilidad(fy=2024, ultima_aprobacion=date(2024, 9, 30), meses_observables=21)
    assert obs.alcanza(12)
    assert not obs.alcanza(24)
    assert not obs.alcanza(48)


def test_una_cosecha_madura_alcanza_todas():
    obs = Observabilidad(fy=2013, ultima_aprobacion=date(2013, 9, 30), meses_observables=153)
    assert all(obs.alcanza(m) for m in DEFAULT_WINDOWS)


def test_el_limite_es_inclusivo():
    """Exactamente M meses cuenta: el prestamo tuvo la ventana completa."""
    obs = Observabilidad(fy=2024, ultima_aprobacion=date(2024, 6, 30), meses_observables=24)
    assert obs.alcanza(24)
    assert not obs.alcanza(25)


# --- sobre los datos reales ---


@pytest.fixture(scope="module")
def madurez() -> pd.DataFrame:
    return matched_maturity()


def test_las_ventanas_no_alcanzadas_quedan_vacias(madurez):
    """Lo esencial: sin numero, no con el numero de la ventana anterior."""
    no_observables = madurez[~madurez["observable"]]
    assert not no_observables.empty, "el vintage deberia tener cosechas jovenes"
    assert no_observables["tasa"].isna().all()
    assert no_observables["n_resueltos"].isna().all()


def test_ninguna_cosecha_repite_el_valor_de_la_ventana_anterior(madurez):
    """El sintoma exacto del bug: tasa_36m == tasa_48m con el mismo n.

    Si dos ventanas consecutivas dan el mismo n_resueltos, la segunda no aporto
    ningun prestamo nuevo -- o la cosecha se acabo, y entonces no deberia estar
    reportada.
    """
    for fy, g in madurez[madurez["observable"]].groupby("fy"):
        g = g.sort_values("ventana_meses")
        n = g["n_resueltos"].astype("float").to_numpy()
        repetidos = [
            (int(g["ventana_meses"].iloc[i]), int(g["ventana_meses"].iloc[i + 1]))
            for i in range(len(n) - 1)
            if n[i] == n[i + 1]
        ]
        assert not repetidos, f"FY{fy}: ventanas con el mismo n, no observables: {repetidos}"


def test_la_observabilidad_decrece_con_la_cosecha():
    obs = observabilidad()
    anios = sorted(obs)
    meses = [obs[a].meses_observables for a in anios]
    assert meses == sorted(meses, reverse=True), "una cosecha mas nueva no puede tener mas meses"


def test_el_conteo_de_chargeoffs_crece_con_la_ventana(madurez):
    """Mas tiempo de observacion no puede descubrir MENOS charge-offs.

    La monotonia vive en el conteo, no en la tasa.
    """
    for fy, g in madurez[madurez["observable"]].groupby("fy"):
        g = g.sort_values("ventana_meses")
        conteos = g["n_chargeoffs"].astype("float").to_numpy()
        assert list(conteos) == sorted(conteos), f"FY{fy}: el conteo baja: {list(conteos)}"


def test_la_tasa_a_madurez_pareja_NO_es_monotona():
    """Y no debe serlo. Este test existe para que nadie la lea como un pronostico.

    Es un cociente cuyo numerador y denominador crecen los dos con la ventana. Los
    charge-offs emergen antes que los pagos completos, asi que el cociente
    sobrepasa y luego converge: en las cosechas de entrenamiento sube a 7.22% a 48
    meses y baja a 7.14% a 60, con tasa final 6.79%.

    Si algun dia esto pasara a ser monotono, o cambio el dato o alguien convirtio
    la metrica en otra cosa. Las dos merecen enterarse.
    """
    ref = reference_rates()
    valores = [ref[m] for m in sorted(ref)]
    assert valores != sorted(valores), (
        f"la tasa resulto monotona: {ref}. Revisar si la metrica cambio de significado."
    )


def test_la_tasa_cruda_y_la_pareja_no_coinciden_en_cosechas_jovenes(madurez):
    """La razon de ser del modulo.

    FY2023 tiene ~17% de tasa cruda entre lo resuelto y ~11% a 24 meses. Si
    coincidieran, comparar a madurez pareja no aportaria nada.
    """
    fila = madurez[(madurez.fy == 2023) & (madurez.ventana_meses == 24)]
    if fila.empty or fila["tasa"].isna().all():
        pytest.skip("el vintage no llega a FY2023 con 24 meses")
    assert float(fila["tasa"].iloc[0]) < 15.0
