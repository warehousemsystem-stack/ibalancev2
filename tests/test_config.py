"""Pruebas de configuracion, validacion y migracion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ibalance.config import Config, ConfigError, config_por_defecto, migrar


def test_ida_y_vuelta(tmp_path: Path) -> None:
    original = config_por_defecto(4)
    destino = original.guardar(tmp_path / "config.json")
    recargada = Config.cargar(destino)
    assert recargada.to_dict() == original.to_dict()


def test_json_invalido_da_error_legible(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    ruta.write_text("{ esto no es json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON invalido"):
        Config.cargar(ruta)


def test_reporta_todos_los_problemas_juntos() -> None:
    cfg = config_por_defecto(2)
    cfg.balanzas[0].activa = True          # activa pero sin IP
    cfg.balanzas[1].puerto = 0             # puerto invalido
    cfg.rongta.convencion_llamada = "pascal"
    with pytest.raises(ConfigError) as error:
        cfg.validar()
    mensaje = str(error.value)
    assert "sin IP" in mensaje
    assert "puerto 0" in mensaje
    assert "convencion_llamada" in mensaje


def test_conn_id_duplicado_es_error() -> None:
    cfg = config_por_defecto(2)
    cfg.balanzas[1].conn_id = cfg.balanzas[0].conn_id
    with pytest.raises(ConfigError, match="conn_id"):
        cfg.validar()


def test_migra_config_de_la_version_anterior() -> None:
    viejo = {
        "origen": {"ruta": "X:\\cadtxt.txt", "tipo": "TXT"},
        "balanzas": [{"id": 1, "ip": "10.0.0.1", "activa": True, "nombre": "B1"}],
        "sincronizacion": {"intervalo_minutos": 30, "timeout_ping_seg": 2},
        "dll_path": "C:\\ibalance\\rtslabelscale.dll",
    }
    cfg = Config.from_dict(viejo)
    cfg.validar()
    assert cfg.origen.tipo == "txt_ancho_fijo"
    assert cfg.rongta.dll_path == "C:\\ibalance\\rtslabelscale.dll"
    assert cfg.sincronizacion.intervalo_minutos == 30
    assert cfg.balanzas[0].conn_id == "1"


def test_migrar_no_toca_una_config_actual() -> None:
    actual = config_por_defecto(1).to_dict()
    assert migrar(json.loads(json.dumps(actual))) == actual


def test_claves_desconocidas_no_rompen() -> None:
    """Un config escrito por una version mas nueva debe seguir abriendo."""
    datos = config_por_defecto(1).to_dict()
    datos["origen"]["campo_del_futuro"] = 42
    datos["balanzas"][0]["otro_campo"] = "x"
    Config.from_dict(datos).validar()


def test_rutas_relativas_se_resuelven_junto_al_config(tmp_path: Path) -> None:
    cfg = config_por_defecto(1)
    cfg.guardar(tmp_path / "config.json")
    assert cfg.resolver("logs") == tmp_path / "logs"

    # La ruta absoluta se construye a partir de tmp_path en vez de escribirla a
    # mano: en Windows "/tmp/abs" no es absoluta (le falta la unidad) y se
    # resolveria como relativa, que es justo lo contrario de lo que se prueba.
    absoluta = tmp_path / "fuera" / "cadtxt.txt"
    assert absoluta.is_absolute()
    assert cfg.resolver(str(absoluta)) == absoluta
