"""El scorecard es el artefacto que un validador abre primero. No puede salir roto.

`optbinning` devuelve el bin de una categorica como un ARRAY de categorias. Al
escribirlo a CSV, pandas guarda su `repr()`:

    naics_sector,0,"<ArrowStringArray>
    ['55', '52', '22', '53', '11']
    Length: 5, dtype: str",11793,...

`exports/scorecard_points.csv` tenia 35 filas asi: 166 lineas fisicas para 83
registros. Un CSV que no se puede abrir en una hoja de calculo, del modelo
interpretable, en un proyecto cuyo argumento es la auditabilidad.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from crmlops.config import repo_root
from crmlops.models.scorecard import WoEScorecard

RUTA = repo_root() / "exports" / "scorecard_points.csv"


# --- la conversion, sin datos ---


def test_una_cadena_pasa_tal_cual():
    assert WoEScorecard._bin_legible("[0.00, 10.50)") == "[0.00, 10.50)"


def test_una_lista_de_categorias_se_une_legible():
    assert WoEScorecard._bin_legible(["55", "52", "22"]) == "55 | 52 | 22"


def test_un_array_de_pandas_no_deja_su_repr():
    pd = pytest.importorskip("pandas")
    arr = pd.array(["55", "52"], dtype="string")
    salida = WoEScorecard._bin_legible(arr)
    assert "ArrowStringArray" not in salida
    assert "dtype" not in salida
    assert salida == "55 | 52"


def test_algo_no_iterable_no_revienta():
    assert WoEScorecard._bin_legible(7) == "7"


# --- el artefacto publicado ---


@pytest.mark.skipif(not RUTA.exists(), reason="falta exports/scorecard_points.csv")
def test_el_csv_publicado_no_trae_reprs_de_python():
    texto = RUTA.read_text(encoding="utf-8")
    for basura in ("ArrowStringArray", "dtype:", "Length:"):
        assert basura not in texto, f"el CSV trae un repr de Python: {basura}"


@pytest.mark.skipif(not RUTA.exists(), reason="falta exports/scorecard_points.csv")
def test_cada_registro_ocupa_una_sola_linea():
    """El sintoma que delataba el defecto: 166 lineas fisicas para 83 registros."""
    texto = RUTA.read_text(encoding="utf-8")
    fisicas = len([ln for ln in texto.splitlines() if ln.strip()])
    registros = len(list(csv.reader(io.StringIO(texto))))
    assert fisicas == registros, (
        f"{registros} registros ocupan {fisicas} lineas: hay saltos dentro de una celda"
    )


@pytest.mark.skipif(not RUTA.exists(), reason="falta exports/scorecard_points.csv")
def test_el_csv_se_lee_con_el_lector_estandar():
    with Path(RUTA).open(encoding="utf-8", newline="") as fh:
        filas = list(csv.DictReader(fh))
    assert filas, "el CSV quedo vacio"
    assert "Bin" in filas[0], f"falta la columna Bin: {list(filas[0])}"
    # Ninguna celda con salto de linea adentro.
    for i, fila in enumerate(filas, start=2):
        for col, val in fila.items():
            if isinstance(val, str):
                assert "\n" not in val, f"linea {i}, columna {col}: salto de linea en la celda"
