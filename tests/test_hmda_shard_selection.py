"""La muestra de analisis la define config.yaml, no el sistema de archivos.

EL DEFECTO QUE ESTE ARCHIVO EVITA. Tres consumidores de HMDA hacian
`glob("*.parquet")` sin filtrar por anio: la disparidad observada, el benchmark de
backends y el cargador del panel. Funcionaba mientras el directorio contuviera
exactamente los cinco anios publicados, y esa coincidencia no era una garantia sino
una casualidad -- el codigo no la afirmaba en ningun lado.

Se descubrio al ir a descargar 2018, 2019 y 2025 para el estudio de evento. Esos
tres anios habrian cambiado en silencio tres numeros ya publicados, incluido el
encabezado "62.4M solicitudes", sin que ninguna prueba fallara: todas leen el mismo
directorio que el codigo.

Es la misma familia que el resto de la bitacora -- un control cuya correccion
dependia de que nadie hiciera algo razonable.
"""

from __future__ import annotations

import pytest

from crmlops.config import load_config
from crmlops.sources import hmda


@pytest.fixture
def directorio(tmp_path):
    """Directorio con MAS anios de los que la configuracion declara."""
    for year in (2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025):
        for state in ("CA", "TX"):
            (tmp_path / f"hmda_{year}_{state}.parquet").write_bytes(b"")
    return tmp_path


def test_selecciona_solo_los_anios_de_la_configuracion(directorio):
    publicados = hmda.default_years()
    elegidos = {int(p.stem.split("_")[1]) for p in hmda.shard_paths(root=directorio)}
    assert elegidos == set(publicados)


def test_los_anios_extra_en_disco_no_entran(directorio):
    elegidos = {int(p.stem.split("_")[1]) for p in hmda.shard_paths(root=directorio)}
    for intruso in (2018, 2019, 2025):
        if intruso not in hmda.default_years():
            assert intruso not in elegidos, (
                f"{intruso} esta en disco y se colo en la seleccion: "
                "un anio descargado para otro analisis cambiaria las cifras publicadas"
            )


def test_una_ventana_explicita_manda_sobre_la_configuracion(directorio):
    """El estudio de evento pide su propia ventana sin mover el panel publicado."""
    elegidos = {int(p.stem.split("_")[1]) for p in hmda.shard_paths((2018, 2019), directorio)}
    assert elegidos == {2018, 2019}


def test_sin_particiones_falla_con_instruccion(directorio):
    with pytest.raises(FileNotFoundError, match=r"crmlops.sources.hmda"):
        hmda.shard_paths((1999,), directorio)


def test_la_lista_sql_es_la_misma_seleccion(directorio):
    sql = hmda.shard_list_sql((2020,), directorio)
    assert sql.startswith("[") and sql.endswith("]")
    assert sql.count("'") == 2 * len(hmda.shard_paths((2020,), directorio))
    assert "2021" not in sql


def test_los_tres_consumidores_no_globean_por_su_cuenta():
    """Ninguno vuelve a expandir el directorio a mano.

    Sin este test, arreglar los tres sitios y que alguien agregue un cuarto deja el
    defecto reintroducido sin aviso.
    """
    import inspect

    from crmlops.fairness import observed
    from crmlops.features import hmda_job
    from crmlops.sources import hmda_loader

    for modulo in (observed, hmda_job, hmda_loader):
        fuente = inspect.getsource(modulo)
        assert 'glob("*.parquet")' not in fuente, (
            f"{modulo.__name__} vuelve a expandir el directorio: la muestra tiene que "
            "salir de crmlops.sources.hmda.shard_paths"
        )


def test_la_ventana_del_estudio_contiene_a_la_publicada():
    """El estudio de evento amplia el panel publicado; no lo reemplaza.

    Si las dos ventanas se separaran, los coeficientes del estudio dejarian de ser
    comparables con la disparidad observada que el README cita.
    """
    cfg = load_config()
    publicada = set(cfg["sources"]["hmda"]["years"])
    estudio = set(cfg["event_study"]["years"])
    assert publicada < estudio, "la ventana del estudio debe ser un superconjunto estricto"
    assert cfg["event_study"]["base_year"] in publicada
    assert cfg["event_study"]["shock_year"] in publicada
