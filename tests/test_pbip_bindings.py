"""El modelo semantico de Power BI no puede referenciar columnas que no existen.

En Power BI un enlace roto no se ve al abrir el archivo: se ve al REFRESCAR, y el
mensaje habla de la consulta, no del export que cambio de nombre. Si alguien renombra
una columna en `exports/`, el tablero se rompe en la maquina de quien lo abra y no en
CI.

Esto es lo que SI se puede verificar sin Power BI instalado: que cada `sourceColumn` del
TMDL exista en el encabezado real del CSV, y que cada archivo que el modelo lee exista.
No verifica que Desktop cargue el proyecto -- eso queda declarado en powerbi/README.md.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from crmlops.config import repo_root

PBIP = repo_root() / "powerbi"
TABLAS = PBIP / "credit-risk-mlops.SemanticModel" / "definition" / "tables"

pytestmark = pytest.mark.skipif(not TABLAS.exists(), reason="no hay proyecto PBIP")


def _tmdl() -> list[Path]:
    return sorted(TABLAS.glob("*.tmdl"))


def _bloques_de_tabla(texto: str) -> list[tuple[str, str]]:
    """Devuelve (nombre_tabla, cuerpo) por cada `table X` del archivo.

    Un .tmdl puede declarar mas de una tabla; `Equidad.tmdl` declara dos.
    """
    indices = [m.start() for m in re.finditer(r"^table\s+(\S+)", texto, re.M)]
    nombres = re.findall(r"^table\s+(\S+)", texto, re.M)
    bloques = []
    for i, inicio in enumerate(indices):
        fin = indices[i + 1] if i + 1 < len(indices) else len(texto)
        bloques.append((nombres[i], texto[inicio:fin]))
    return bloques


def _encabezado_csv(nombre: str) -> list[str]:
    ruta = repo_root() / "exports" / nombre
    with ruta.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


# --- estructura minima ---


def test_existe_el_scaffold_completo():
    faltan = [
        p
        for p in (
            PBIP / "credit-risk-mlops.pbip",
            PBIP / "credit-risk-mlops.SemanticModel" / "definition.pbism",
            PBIP / "credit-risk-mlops.SemanticModel" / ".platform",
            PBIP / "credit-risk-mlops.SemanticModel" / "definition" / "model.tmdl",
            PBIP / "credit-risk-mlops.SemanticModel" / "definition" / "database.tmdl",
            PBIP / "credit-risk-mlops.SemanticModel" / "definition" / "expressions.tmdl",
        )
        if not p.exists()
    ]
    assert not faltan, f"faltan archivos del proyecto: {[p.name for p in faltan]}"


def test_los_json_del_scaffold_son_validos():
    for nombre in ("credit-risk-mlops.pbip",):
        json.loads((PBIP / nombre).read_text(encoding="utf-8"))
    base = PBIP / "credit-risk-mlops.SemanticModel"
    for nombre in ("definition.pbism", ".platform"):
        json.loads((base / nombre).read_text(encoding="utf-8"))


def test_el_modelo_referencia_todas_las_tablas_declaradas():
    """Una tabla sin `ref table` en model.tmdl no se carga, y no avisa."""
    modelo = (PBIP / "credit-risk-mlops.SemanticModel" / "definition" / "model.tmdl").read_text(
        encoding="utf-8"
    )
    referenciadas = set(re.findall(r"^ref table\s+(\S+)", modelo, re.M))
    declaradas: set[str] = set()
    for archivo in _tmdl():
        for nombre, _ in _bloques_de_tabla(archivo.read_text(encoding="utf-8")):
            declaradas.add(nombre)

    assert declaradas - referenciadas == set(), (
        f"tablas declaradas y no referenciadas en model.tmdl: {sorted(declaradas - referenciadas)}"
    )
    assert referenciadas - declaradas == set(), (
        f"model.tmdl referencia tablas que no existen: {sorted(referenciadas - declaradas)}"
    )


# --- lo que importa: los enlaces ---


def test_cada_csv_que_el_modelo_lee_existe():
    faltan = []
    for archivo in _tmdl():
        for nombre in re.findall(r'LeerExport\("([^"]+)"\)', archivo.read_text(encoding="utf-8")):
            if not (repo_root() / "exports" / nombre).exists():
                faltan.append(f"{archivo.name} -> exports/{nombre}")
    assert not faltan, f"el modelo lee exports que no existen: {faltan}"


def test_cada_json_que_el_modelo_lee_existe():
    faltan = []
    for archivo in _tmdl():
        for rel in re.findall(
            r'RutaRepo\s*&\s*"\\(exports\\[^"]+)"', archivo.read_text(encoding="utf-8")
        ):
            ruta = repo_root() / rel.replace("\\", "/")
            if not ruta.exists():
                faltan.append(f"{archivo.name} -> {rel}")
    assert not faltan, f"el modelo lee JSON que no existen: {faltan}"


def test_cada_columna_enlazada_existe_en_su_csv():
    """El test que justifica este archivo.

    Compara cada `sourceColumn` contra el encabezado real del CSV. Es el unico modo de
    que un renombre en `exports/` rompa CI en vez de romper el tablero de quien lo abra.
    """
    problemas: list[str] = []
    for archivo in _tmdl():
        texto = archivo.read_text(encoding="utf-8")
        for tabla, cuerpo in _bloques_de_tabla(texto):
            csvs = re.findall(r'LeerExport\("([^"]+)"\)', cuerpo)
            if len(csvs) != 1:
                continue  # tabla que no viene de un CSV (Config, Umbrales, Medidas)
            encabezado = _encabezado_csv(csvs[0])
            for col in re.findall(r"^\s*sourceColumn:\s*(.+?)\s*$", cuerpo, re.M):
                if col not in encabezado:
                    problemas.append(f"{tabla} ({csvs[0]}): sourceColumn '{col}' no esta en el CSV")
    assert not problemas, "enlaces roto(s):\n  " + "\n  ".join(problemas)


def test_ninguna_medida_hardcodea_un_umbral():
    """Los umbrales viven en config.yaml y llegan por `exports/web/umbrales.json`.

    Una medida con el numero escrito adentro podria mostrar "cumple" sobre algo que el
    gate bloquea, y el tablero es lo que alguien mira en una reunion.
    """
    medidas = (TABLAS / "Medidas.tmdl").read_text(encoding="utf-8")
    cuerpo = "\n".join(
        ln for ln in medidas.splitlines() if not ln.strip().startswith(("///", "//"))
    )
    sospechosos = re.findall(r"(?<![\w.])0\.(?:0[1-9]|[1-9]\d*)", cuerpo)
    assert not sospechosos, (
        f"hay constantes decimales en las medidas: {sorted(set(sospechosos))}. "
        "Los umbrales tienen que leerse de la tabla Umbrales."
    )


def test_ningun_nombre_de_modelo_esta_escrito_en_el_TMDL():
    """El defecto A2 del AUDIT en otra capa.

    La primera version de Modelos.tmdl tenia `IF([modelo] = "lightgbm", ...)`: el
    tablero seguiria marcando LightGBM como produccion despues de que el proyecto
    promoviera otro. El nombre sale de `Config`.
    """
    for archivo in _tmdl():
        texto = archivo.read_text(encoding="utf-8")
        cuerpo = "\n".join(
            ln for ln in texto.splitlines() if not ln.strip().startswith(("///", "//"))
        )
        for prohibido in ('"lightgbm"', '"scorecard_woe"', '"neural_mlp"'):
            assert prohibido not in cuerpo, (
                f"{archivo.name} escribe {prohibido} a mano; usar Config[produccion]/[baseline]"
            )
