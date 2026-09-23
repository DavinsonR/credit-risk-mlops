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


def test_el_pbism_declara_una_version_que_admite_TMDL():
    """La version del `.pbism` decide que formato busca Desktop, y solo hay dos.

    Segun la tabla de Microsoft: la version 1.0 obliga a que el modelo este en
    `model.bim` (TMSL); de la 4.0 en adelante se admite tambien la carpeta
    `definition/` (TMDL). Este proyecto envia la carpeta.

    Lo aprendimos por el camino largo. El `.pbism` decia 1.0 con una carpeta
    `definition/` al lado, y Desktop no abrio el proyecto: pidio un `model.bim`
    que no existe ni tiene por que existir. Un archivo de cuatro lineas, valido
    como JSON, coherente consigo mismo, y contradictorio con la carpeta que tenia
    al lado. Ninguna prueba miraba esa contradiccion porque ninguna pieza estaba
    mal por separado.

    https://learn.microsoft.com/power-bi/developer/projects/projects-dataset
    """
    base = PBIP / "credit-risk-mlops.SemanticModel"
    pbism = json.loads((base / "definition.pbism").read_text(encoding="utf-8"))
    version = pbism.get("version", "")
    mayor = int(version.split(".")[0]) if version.split(".")[0].isdigit() else 0

    if (base / "definition").is_dir():
        assert mayor >= 4, (
            f"el modelo esta en TMDL (definition/) pero definition.pbism declara "
            f"version {version!r}: Desktop exigira un model.bim inexistente"
        )
    else:
        assert (base / "model.bim").exists(), "sin definition/ hace falta model.bim"


def test_cada_archivo_del_andamiaje_declara_su_esquema():
    """Sin `$schema` un archivo no se valida contra nada, y eso no es aprobar.

    El validador de `build_pbir_report.py` saltaba los archivos que no declaran
    esquema. Un archivo se libraba de la revision con solo no pedirla.
    """
    base = PBIP / "credit-risk-mlops.SemanticModel"
    informe = PBIP / "credit-risk-mlops.Report"
    sin_esquema = [
        ruta.name
        for ruta in (
            base / "definition.pbism",
            base / ".platform",
            informe / "definition.pbir",
            informe / ".platform",
        )
        if "$schema" not in json.loads(ruta.read_text(encoding="utf-8"))
    ]
    assert not sin_esquema, f"no declaran $schema: {sin_esquema}"


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


# --- la cadena de artefactos del .pbip resuelve ---


def test_el_pbip_apunta_a_artefactos_que_existen():
    """El `.pbip` declara sus artefactos por ruta, y esa ruta tiene que existir.

    EL DEFECTO. El `.pbip` listaba `credit-risk-mlops.Report` y esa carpeta **no
    estaba**: solo se habia escrito el modelo semantico. Power BI Desktop no puede
    abrir un proyecto cuyo artefacto de informe no existe, asi que la primera
    instruccion de la guia --"abrir el .pbip"-- era inejecutable.

    `test_existe_el_scaffold_completo` no lo veia porque comprobaba una lista de
    archivos escrita a mano, no lo que el propio `.pbip` declara. Un control que
    verifica su propia lista en vez de la del artefacto no verifica el artefacto.
    """
    pbip = json.loads((PBIP / "credit-risk-mlops.pbip").read_text(encoding="utf-8"))
    rutas = [
        art[tipo]["path"]
        for art in pbip["artifacts"]
        for tipo in art
        if isinstance(art[tipo], dict) and "path" in art[tipo]
    ]
    assert rutas, "el .pbip no declara ningun artefacto con ruta"
    faltan = [r for r in rutas if not (PBIP / r).exists()]
    assert not faltan, (
        f"el .pbip apunta a artefactos inexistentes: {faltan}. "
        "Power BI Desktop no abre el proyecto."
    )


def test_el_informe_referencia_al_modelo_semantico_por_ruta_relativa():
    """Una ruta absoluta aqui ata el proyecto a una maquina.

    Es el mismo motivo por el que existe el parametro `RutaRepo`: lo unico que puede
    depender del equipo es ese parametro, y esta referencia no.
    """
    pbir = PBIP / "credit-risk-mlops.Report" / "definition.pbir"
    ref = json.loads(pbir.read_text(encoding="utf-8"))["datasetReference"]
    assert "byPath" in ref, "el informe deberia referenciar el modelo local, no uno remoto"
    ruta = ref["byPath"]["path"]
    assert not Path(ruta).is_absolute(), f"ruta absoluta en definition.pbir: {ruta}"
    assert (pbir.parent / ruta).resolve().exists(), f"el modelo no esta en {ruta}"


def test_el_informe_declara_su_tipo_en_platform():
    p = json.loads((PBIP / "credit-risk-mlops.Report" / ".platform").read_text(encoding="utf-8"))
    assert p["metadata"]["type"] == "Report"


# --- el informe PBIR: cada campo que dibuja existe en el modelo ---

REPORTE = PBIP / "credit-risk-mlops.Report"
PAGINAS = REPORTE / "definition" / "pages"


def _visuales_pbir() -> list[tuple[Path, dict]]:
    return [
        (p, json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(PAGINAS.rglob("visuals/*/visual.json"))
    ]


def _campos_referenciados(obj) -> set[tuple[str, str]]:
    fuera: set[tuple[str, str]] = set()
    if isinstance(obj, dict):
        for clave in ("Column", "Measure"):
            if clave in obj:
                ent = obj[clave]["Expression"]["SourceRef"]["Entity"]
                fuera.add((ent, obj[clave]["Property"]))
        for v in obj.values():
            fuera |= _campos_referenciados(v)
    elif isinstance(obj, list):
        for v in obj:
            fuera |= _campos_referenciados(v)
    return fuera


def _campos_del_modelo() -> dict[str, set[str]]:
    modelo: dict[str, set[str]] = {}
    tablas = PBIP / "credit-risk-mlops.SemanticModel" / "definition" / "tables"
    for archivo in sorted(tablas.glob("*.tmdl")):
        tabla = None
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"^table\s+'?([^'\s]+)'?", linea):
                tabla = m.group(1)
                modelo.setdefault(tabla, set())
            elif tabla and (m := re.match(r"^\tcolumn\s+'?([^'\n]+?)'?\s*$", linea)):
                modelo[tabla].add(m.group(1))
            elif tabla and (m := re.match(r"^\tmeasure\s+'?([^'=]+?)'?\s*=", linea)):
                modelo[tabla].add(m.group(1).strip())
    return modelo


def test_el_informe_solo_dibuja_campos_que_existen():
    """Cada columna y cada medida del informe existe en el TMDL.

    Es el mismo principio que `test_cada_columna_enlazada_existe_en_su_csv` una capa
    mas arriba: el modelo se enlaza al CSV y el informe se enlaza al modelo. Sin esto,
    renombrar una medida deja un visual roto que solo se ve al abrir Desktop.
    """
    visuales = _visuales_pbir()
    assert visuales, "el informe PBIR no tiene visuales"
    modelo = _campos_del_modelo()

    rotos = []
    for ruta, v in visuales:
        for ent, prop in sorted(_campos_referenciados(v)):
            if ent not in modelo:
                rotos.append(f"{ruta.parent.name}: tabla '{ent}' no existe")
            elif prop not in modelo[ent]:
                rotos.append(f"{ruta.parent.name}: {ent}[{prop}] no existe")
    assert not rotos, "campos rotos en el informe:\n  " + "\n  ".join(rotos)


def test_cada_visual_cabe_en_su_pagina():
    """Un visual que se sale del lienzo no da error: queda cortado y nadie lo nota."""
    for ruta, v in _visuales_pbir():
        assert v["visual"]["visualType"], ruta
        pos = v["position"]
        assert all(k in pos for k in ("x", "y", "width", "height")), ruta
        pagina = json.loads((ruta.parents[2] / "page.json").read_text(encoding="utf-8"))
        assert pos["x"] + pos["width"] <= pagina["width"], f"{v['name']} se sale a la derecha"
        assert pos["y"] + pos["height"] <= pagina["height"], f"{v['name']} se sale abajo"


def test_los_nombres_de_visual_son_unicos_en_todo_el_informe():
    nombres = [v["name"] for _, v in _visuales_pbir()]
    dup = sorted({n for n in nombres if nombres.count(n) > 1})
    assert not dup, f"nombres repetidos: {dup}"


def test_el_orden_de_paginas_coincide_con_las_carpetas():
    meta = json.loads((PAGINAS / "pages.json").read_text(encoding="utf-8"))
    carpetas = {p.name for p in PAGINAS.iterdir() if p.is_dir()}
    assert set(meta["pageOrder"]) == carpetas, (
        f"pageOrder {meta['pageOrder']} no coincide con las carpetas {sorted(carpetas)}"
    )
    assert meta["activePageName"] in carpetas


def test_las_cuatro_paginas_llevan_la_procedencia():
    """El pie con vintage y huellas va en TODAS.

    Es lo que permite a un validador cruzar el tablero con exports/metrics.json y con
    el commit. Una pagina sin el es una captura de pantalla.
    """
    carpetas = sorted(p for p in PAGINAS.iterdir() if p.is_dir())
    assert len(carpetas) == 4, f"se esperaban cuatro paginas, hay {len(carpetas)}"
    for pagina in carpetas:
        campos: set[tuple[str, str]] = set()
        for v in (pagina / "visuals").rglob("visual.json"):
            campos |= _campos_referenciados(json.loads(v.read_text(encoding="utf-8")))
        assert ("Medidas", "Procedencia") in campos, f"{pagina.name} no muestra la procedencia"


def test_el_informe_no_conserva_el_formato_clasico():
    """PBIR reemplaza a `report.json`. Dejar los dos deja que Desktop elija, y el que
    elija no tiene por que ser el que este repositorio revisa en el diff."""
    assert not (REPORTE / "report.json").exists()
    assert (REPORTE / "definition" / "report.json").exists()
