"""Escribe el informe de Power BI como PBIR, y lo valida contra los esquemas de Microsoft.

POR QUE ESTO EXISTE. El modelo semantico se escribio a mano en TMDL porque es texto,
versionado y revisable en un diff. El informe se quedo fuera por una razon buena --el
layout no se puede escribir a ciegas-- y por una mala: el formato clasico de PBIP
guarda el informe como un `report.json` donde la configuracion de cada visual es una
CADENA de JSON escapado dentro de otro JSON. Eso no se escribe a mano de forma
defendible.

PBIR --el formato mejorado de metadatos-- si: un archivo por pagina, un archivo por
visual, y ESQUEMAS PUBLICADOS contra los cuales validar. Asi que el informe se genera
aqui y se valida antes de escribirse.

LO QUE ESTE SCRIPT NO PUEDE HACER. Validar contra un esquema NO es abrirlo en Power BI
Desktop. Un archivo puede cumplir el esquema y aun asi no cargar --por un tipo de
visual mal escrito, por un rol que ese visual no acepta, o porque la vista previa de
PBIR exige una version de Desktop mas nueva--. Esa comprobacion sigue siendo de quien
tenga Desktop, y docs/POWERBI.md dice que hacer si falla.

Lo que sI garantiza: que cada campo referenciado EXISTE en el modelo semantico (se
comprueba contra el TMDL, no contra una lista escrita a mano) y que cada archivo cumple
el esquema publicado de su tipo.

    uv run python scripts/build_pbir_report.py            # escribe y valida
    uv run python scripts/build_pbir_report.py --check    # solo valida, no escribe
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PBIP = REPO / "powerbi"
REPORT = PBIP / "credit-risk-mlops.Report"
MODEL = PBIP / "credit-risk-mlops.SemanticModel" / "definition"

S = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
SCHEMA = {
    "report": f"{S}/report/1.0.0/schema.json",
    "pagesMetadata": f"{S}/pagesMetadata/1.0.0/schema.json",
    "page": f"{S}/page/1.0.0/schema.json",
    "visualContainer": f"{S}/visualContainer/1.0.0/schema.json",
    "version": f"{S}/versionMetadata/1.0.0/schema.json",
}

# Lienzo de 16:9 a 1280x720, que es el que Desktop usa por defecto. Las posiciones se
# escriben en esa rejilla y no en porcentajes: el formato las guarda en pixeles.
W, H = 1280, 720
PIE_Y = 655  # franja de procedencia, comun a las cuatro paginas


# --------------------------------------------------------------------------
# El modelo semantico es la fuente de verdad de que campos existen
# --------------------------------------------------------------------------
def campos_del_modelo() -> dict[str, set[str]]:
    """Tabla -> {columnas y medidas} leidas del TMDL.

    No se escribe una lista aqui. Si alguien renombra una columna en el TMDL, este
    script falla en vez de generar un informe que Desktop abrira con un campo roto --
    que es el modo de fallo silencioso que el proyecto persigue.
    """
    fuera: dict[str, set[str]] = {}
    for archivo in sorted((MODEL / "tables").glob("*.tmdl")):
        tabla = None
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"^table\s+'?([^'\s]+)'?", linea):
                tabla = m.group(1)
                fuera.setdefault(tabla, set())
            elif tabla and (m := re.match(r"^\tcolumn\s+'?([^'\n]+?)'?\s*$", linea)):
                fuera[tabla].add(m.group(1))
            elif tabla and (m := re.match(r"^\tmeasure\s+'?([^'=]+?)'?\s*=", linea)):
                fuera[tabla].add(m.group(1).strip())
    return fuera


# --------------------------------------------------------------------------
# Constructores
# --------------------------------------------------------------------------
def col(tabla: str, campo: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": campo}}


def med(campo: str, tabla: str = "Medidas") -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": tabla}}, "Property": campo}}


def proj(tabla: str, campo: str, *, medida: bool = False) -> dict:
    return {
        "field": med(campo, tabla) if medida else col(tabla, campo),
        "queryRef": f"{tabla}.{campo}",
        "nativeQueryRef": campo,
    }


def visual(
    nombre: str,
    tipo: str,
    pos: tuple[int, int, int, int],
    roles: dict[str, list[dict]],
    *,
    titulo: str | None = None,
    z: int = 0,
) -> dict:
    x, y, w, h = pos
    v: dict = {
        "$schema": SCHEMA["visualContainer"],
        "name": nombre,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h},
        "visual": {
            "visualType": tipo,
            "query": {"queryState": {r: {"projections": p} for r, p in roles.items()}},
            "drillFilterOtherVisuals": True,
        },
    }
    if titulo:
        v["visual"]["visualContainerObjects"] = {
            "title": [
                {
                    "properties": {
                        "text": {"expr": {"Literal": {"Value": f"'{titulo}'"}}},
                        "show": {"expr": {"Literal": {"Value": "true"}}},
                    }
                }
            ]
        }
    return v


def pie_de_procedencia(pagina: str) -> dict:
    """La medida `Procedencia` en las cuatro paginas.

    No es decoracion: imprime el vintage de los datos y las dos huellas, y es lo que
    permite a un validador cruzar el tablero con `exports/metrics.json` y con el
    commit. Un tablero sin procedencia es una captura de pantalla.
    """
    return visual(
        f"{pagina}-pie-procedencia",
        "card",
        (24, PIE_Y, W - 48, 48),
        {"Values": [proj("Medidas", "Procedencia", medida=True)]},
        titulo="Procedencia",
    )


# --------------------------------------------------------------------------
# Las cuatro paginas
# --------------------------------------------------------------------------
def paginas() -> list[dict]:
    return [
        {
            "name": "p1-desempeno",
            "displayName": "1 · Desempeño",
            "visuals": [
                visual(
                    "p1-tabla-modelos",
                    "tableEx",
                    (24, 96, 760, 400),
                    {
                        "Values": [
                            proj("Modelos", "modelo"),
                            proj("Modelos", "auc_test"),
                            proj("Modelos", "drop_oot"),
                            proj("Modelos", "brier_test"),
                            proj("Modelos", "ece_test"),
                            proj("Medidas", "Es produccion", medida=True),
                        ]
                    },
                    # Los TRES modelos, baseline incluido. Ensenar solo al ganador
                    # convierte una comparacion en una afirmacion.
                    titulo="Los tres modelos, baseline incluido",
                ),
                visual(
                    "p1-card-auc",
                    "card",
                    (808, 96, 448, 124),
                    {"Values": [proj("Medidas", "AUC produccion", medida=True)]},
                    titulo="AUC de producción",
                ),
                visual(
                    "p1-card-margen",
                    "card",
                    (808, 236, 448, 124),
                    {"Values": [proj("Medidas", "Margen sobre baseline", medida=True)]},
                    titulo="Margen sobre el baseline",
                ),
                visual(
                    "p1-card-cumple",
                    "card",
                    (808, 376, 448, 120),
                    {"Values": [proj("Medidas", "Margen cumple", medida=True)]},
                    titulo="¿Cumple el gate de margen?",
                ),
                pie_de_procedencia("p1"),
            ],
        },
        {
            "name": "p2-perdida",
            "displayName": "2 · Pérdida en dólares",
            "visuals": [
                # LAS DOS LINEAS EN EL MISMO VISUAL. Son el mismo analisis: rechazar
                # el 10% mas riesgoso evita $276M y renuncia a $1.99B de volumen sano.
                # Separarlas en dos pestanas es vender, no informar.
                visual(
                    "p2-curva",
                    "lineChart",
                    (24, 96, 848, 480),
                    {
                        "Category": [proj("Decision", "decline_rate")],
                        "Y": [
                            proj("Medidas", "Perdida evitada al corte", medida=True),
                            proj("Medidas", "Volumen bueno sacrificado", medida=True),
                        ],
                    },
                    titulo="Pérdida evitada y volumen sano sacrificado, en el mismo eje",
                ),
                visual(
                    "p2-card-costo",
                    "card",
                    (896, 96, 360, 140),
                    {"Values": [proj("Medidas", "Costo por dolar evitado", medida=True)]},
                    titulo="Costo por dólar evitado",
                ),
                visual(
                    "p2-tabla-decision",
                    "tableEx",
                    (896, 256, 360, 320),
                    {
                        "Values": [
                            proj("Decision", "decline_rate"),
                            proj("Decision", "loss_avoided"),
                            proj("Decision", "good_volume_foregone"),
                            proj("Decision", "lift"),
                        ]
                    },
                    titulo="La curva, en números",
                ),
                pie_de_procedencia("p2"),
            ],
        },
        {
            "name": "p3-equidad",
            "displayName": "3 · Equidad",
            "visuals": [
                # LOS SEIS GRUPOS, no los que quedan bien.
                visual(
                    "p3-tabla-raza",
                    "tableEx",
                    (24, 96, 760, 300),
                    {
                        "Values": [
                            proj("EquidadRaza", "grupo"),
                            proj("EquidadRaza", "n"),
                            proj("EquidadRaza", "tasa_aprobacion"),
                            proj("EquidadRaza", "tasa_denegacion_real"),
                            proj("EquidadRaza", "ratio_calibracion"),
                        ]
                    },
                    titulo="Todos los grupos protegidos",
                ),
                # La comparacion que casi nadie hace: cuanta disparidad AGREGA el
                # modelo sobre la que ya habia en los datos historicos.
                visual(
                    "p3-tabla-delta",
                    "tableEx",
                    (24, 420, 760, 200),
                    {
                        "Values": [
                            proj("EquidadDelta", "dimension"),
                            proj("EquidadDelta", "dir_observado"),
                            proj("EquidadDelta", "dir_modelo"),
                            proj("EquidadDelta", "delta"),
                        ]
                    },
                    titulo="Cuánta disparidad AGREGA el modelo sobre la histórica",
                ),
                visual(
                    "p3-card-veredicto",
                    "card",
                    (808, 96, 448, 180),
                    {"Values": [proj("Medidas", "Veredicto equidad", medida=True)]},
                    titulo="Veredicto del gate de equidad",
                ),
                visual(
                    "p3-card-dir",
                    "card",
                    (808, 292, 448, 140),
                    {"Values": [proj("Medidas", "Disparate impact modelo", medida=True)]},
                    titulo="Razón de impacto dispar",
                ),
                visual(
                    "p3-tabla-umbrales",
                    "tableEx",
                    (808, 448, 448, 172),
                    {
                        "Values": [
                            proj("Umbrales", "gate"),
                            proj("Umbrales", "direccion"),
                            proj("Umbrales", "valor"),
                        ]
                    },
                    titulo="Umbrales, leídos de config.yaml",
                ),
                pie_de_procedencia("p3"),
            ],
        },
        {
            "name": "p4-estres",
            "displayName": "4 · Estrés",
            "visuals": [
                visual(
                    "p4-tabla-estres",
                    "tableEx",
                    (24, 96, 760, 420),
                    {
                        "Values": [
                            proj("Estres", "cohorte"),
                            proj("Estres", "n"),
                            proj("Estres", "tasa_base"),
                            proj("Estres", "auc"),
                            proj("Estres", "predicho"),
                            proj("Estres", "ratio_calibracion"),
                        ]
                    },
                    titulo="El modelo fuera de su régimen",
                ),
                # Del MISMO tamano que el AUC de la pagina 1: un AUC citado sin
                # regimen es un numero de un solo escenario.
                visual(
                    "p4-card-auc-crisis",
                    "card",
                    (808, 96, 448, 124),
                    {"Values": [proj("Medidas", "AUC en crisis", medida=True)]},
                    titulo="AUC en un régimen tipo 2007",
                ),
                visual(
                    "p4-card-subestima",
                    "card",
                    (808, 236, 448, 124),
                    {"Values": [proj("Medidas", "Subestimacion en crisis", medida=True)]},
                    titulo="Cuánto subestima el riesgo",
                ),
                visual(
                    "p4-card-modelo",
                    "card",
                    (808, 376, 448, 140),
                    {"Values": [proj("Medidas", "Modelo de produccion", medida=True)]},
                    titulo="Modelo evaluado",
                ),
                pie_de_procedencia("p4"),
            ],
        },
    ]


# --------------------------------------------------------------------------
# Verificacion
# --------------------------------------------------------------------------
def campos_usados(pags: list[dict]) -> set[tuple[str, str]]:
    usados: set[tuple[str, str]] = set()

    def recorrer(o):
        if isinstance(o, dict):
            for clave in ("Column", "Measure"):
                if clave in o:
                    ent = o[clave]["Expression"]["SourceRef"]["Entity"]
                    usados.add((ent, o[clave]["Property"]))
            for v in o.values():
                recorrer(v)
        elif isinstance(o, list):
            for v in o:
                recorrer(v)

    recorrer(pags)
    return usados


def verificar_campos(pags: list[dict]) -> list[str]:
    modelo = campos_del_modelo()
    problemas = []
    for tabla, campo in sorted(campos_usados(pags)):
        if tabla not in modelo:
            problemas.append(f"tabla inexistente en el TMDL: {tabla}")
        elif campo not in modelo[tabla]:
            problemas.append(f"{tabla}[{campo}] no existe en el TMDL")
    return problemas


# JSON que no termina en `.json`. Son los cuatro archivos del andamiaje, los
# unicos que escribi a mano, y por eso son exactamente los que hay que mirar.
ANDAMIAJE = ("*.pbip", "*.pbism", "*.pbir", ".platform")

# El `.pbip` es un archivo de Desktop, no un item de Fabric: Microsoft no publica
# esquema para el. Es la unica excepcion, y esta escrita, no supuesta.
SIN_ESQUEMA_PUBLICADO = (".pbip",)


def archivos_json(raiz: Path) -> list[Path]:
    hallados: set[Path] = set()
    for patron in ("*.json", *ANDAMIAJE):
        hallados.update(raiz.rglob(patron))
    return sorted(hallados)


def validar_esquemas(raiz: Path) -> list[str]:
    """Valida cada archivo contra el esquema que el propio archivo declara.

    Dos reglas que este validador no tenia, y que le costaron al proyecto el
    defecto 22 --Desktop rechazo el proyecto entero por una linea--:

    1. Mira TODO el JSON del proyecto, no solo lo que termina en `.json`. Los
       cuatro archivos del andamiaje no terminan en `.json`, asi que el validador
       anterior comprobaba unicamente lo que el generador escribia: justo lo que
       ya estaba bien.
    2. Un archivo sin `$schema` es un problema, no un archivo aprobado. Antes se
       hacia `continue`, y un archivo se libraba de la revision con solo no
       pedirla.

    Los esquemas se descargan; sin red, se salta y se dice que se salto en vez de
    dar un visto bueno que no se comprobo.
    """
    try:
        import jsonschema
        import requests
    except ImportError:
        return ["SALTADO: falta jsonschema (uv run --with jsonschema ...)"]

    cache: dict[str, dict] = {}
    problemas = []
    for archivo in archivos_json(raiz):
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        url = datos.get("$schema")
        if not url:
            if archivo.suffix not in SIN_ESQUEMA_PUBLICADO:
                problemas.append(f"{archivo.relative_to(raiz)}: no declara $schema")
            continue
        if url not in cache:
            try:
                cache[url] = requests.get(url, timeout=30).json()
            except Exception as exc:  # sin red: se declara, no se aprueba
                return [f"SALTADO: no se pudo descargar {url} ({type(exc).__name__})"]
        try:
            jsonschema.Draft7Validator(cache[url]).validate(datos)
        except jsonschema.ValidationError as exc:
            ruta = "/".join(str(p) for p in exc.absolute_path)
            problemas.append(f"{archivo.relative_to(raiz)}: {ruta or '(raiz)'} -> {exc.message}")
    return problemas


# --------------------------------------------------------------------------
def escribir(pags: list[dict]) -> None:
    definicion = REPORT / "definition"
    if definicion.exists():
        shutil.rmtree(definicion)
    (definicion / "pages").mkdir(parents=True)

    def volcar(ruta: Path, datos: dict) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    volcar(
        definicion / "report.json",
        {
            "$schema": SCHEMA["report"],
            "themeCollection": {
                "baseTheme": {
                    "name": "CY24SU10",
                    "reportVersionAtImport": "5.55",
                    "type": "SharedResources",
                }
            },
            "layoutOptimization": "None",
            "publicCustomVisuals": [],
        },
    )
    # "1.0" no vale: el esquema exige MAYOR.MENOR.0 y el validador lo atrapo.
    volcar(definicion / "version.json", {"$schema": SCHEMA["version"], "version": "1.0.0"})
    volcar(
        definicion / "pages" / "pages.json",
        {
            "$schema": SCHEMA["pagesMetadata"],
            "pageOrder": [p["name"] for p in pags],
            "activePageName": pags[0]["name"],
        },
    )
    for p in pags:
        carpeta = definicion / "pages" / p["name"]
        volcar(
            carpeta / "page.json",
            {
                "$schema": SCHEMA["page"],
                "name": p["name"],
                "displayName": p["displayName"],
                "displayOption": "FitToPage",
                "height": H,
                "width": W,
            },
        )
        for v in p["visuals"]:
            volcar(carpeta / "visuals" / v["name"] / "visual.json", v)

    # El report.json del formato clasico ya no aplica: PBIR lo reemplaza.
    viejo = REPORT / "report.json"
    if viejo.exists():
        viejo.unlink()

    (REPORT / "definition.pbir").write_text(
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/1.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {"byPath": {"path": "../credit-risk-mlops.SemanticModel"}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    solo_check = "--check" in (argv or sys.argv[1:])
    pags = paginas()

    print("=" * 84)
    print("INFORME PBIR - generar y validar")
    print("=" * 84)

    rotos = verificar_campos(pags)
    n_campos = len(campos_usados(pags))
    n_vis = sum(len(p["visuals"]) for p in pags)
    print(f"\n{len(pags)} paginas, {n_vis} visuales, {n_campos} campos distintos")
    if rotos:
        print("\nCAMPOS QUE NO EXISTEN EN EL MODELO SEMANTICO:")
        for r in rotos:
            print(f"  {r}")
        return 1
    print("  Todos los campos existen en el TMDL.")

    if not solo_check:
        escribir(pags)
        print(f"\nEscrito en {REPORT.relative_to(REPO)}/definition/")

    problemas = validar_esquemas(PBIP)
    saltado = [p for p in problemas if p.startswith("SALTADO")]
    print()
    if saltado:
        print(f"  Validacion de esquema: {saltado[0]}")
    elif problemas:
        print("  NO CUMPLE EL ESQUEMA:")
        for p in problemas:
            print(f"    {p}")
        return 1
    else:
        print("  Cada archivo cumple el esquema publicado que declara.")

    print("\n" + "=" * 84)
    print("LO QUE ESTO NO DEMUESTRA")
    print("=" * 84)
    print("  Cumplir el esquema no es abrir en Power BI Desktop. Un archivo valido")
    print("  puede no cargar -- por un tipo de visual, por un rol que ese visual no")
    print("  acepta, o porque PBIR exige una version de Desktop mas nueva.")
    print("  Esa verificacion sigue pendiente: ver docs/POWERBI.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
