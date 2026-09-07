"""Pruebas del motor de sincronizacion usando el backend simulado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ibalance.config import Balanza, Config, Origen
from ibalance.engine import MotorSincronizacion
from ibalance.rongta import BackendSimulado

MUESTRA = Path(__file__).parent / "data" / "cadtxt_sample.txt"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.origen = Origen(ruta=str(MUESTRA))
    cfg.balanzas = [
        Balanza(id=1, ip="10.0.0.1", activa=True, nombre="Balanza 1"),
        Balanza(id=2, ip="10.0.0.2", activa=True, nombre="Balanza 2"),
        Balanza(id=3, ip="", activa=False, nombre="Balanza 3"),
    ]
    cfg.sincronizacion.verificar_ping = False
    cfg.sincronizacion.verificar_puerto = False
    cfg.sincronizacion.reintentos = 0
    cfg.sincronizacion.pausa_tras_desconectar_seg = 0
    cfg.registro.guardar_reportes = False
    cfg.rongta.tamano_lote_plu = 2
    cfg.ruta_archivo = tmp_path / "config.json"
    cfg.validar()
    return cfg


@pytest.fixture
def backend() -> BackendSimulado:
    return BackendSimulado()


def _motor(config: Config, backend: BackendSimulado) -> MotorSincronizacion:
    return MotorSincronizacion(config, backend=backend)


def test_sincroniza_las_balanzas_activas(config: Config, backend: BackendSimulado) -> None:
    resultado = _motor(config, backend).sincronizar()
    assert resultado.ok
    assert resultado.exitosas == 2
    assert {r.balanza_id for r in resultado.balanzas} == {1, 2}


def test_siempre_desconecta(config: Config, backend: BackendSimulado) -> None:
    """Una conexion abierta deja la balanza inservible hasta que expira su
    propio temporizador: la desconexion tiene que ocurrir siempre."""
    _motor(config, backend).sincronizar()
    assert not backend.hay_fugas
    assert len(backend.operaciones("conectar")) == len(backend.operaciones("desconectar"))


def test_desconecta_aunque_el_envio_falle(config: Config, backend: BackendSimulado) -> None:
    backend.operaciones_que_fallan.add("enviar_plu")
    resultado = _motor(config, backend).sincronizar()
    assert resultado.fallidas == 2
    assert not backend.hay_fugas


def test_nunca_dos_conexiones_a_la_vez(config: Config, backend: BackendSimulado) -> None:
    """Las RLS-1000 aceptan una sola sesion; el motor no puede solaparlas."""
    _motor(config, backend).sincronizar()
    assert backend.max_conexiones_simultaneas == 1


def test_una_balanza_caida_no_arrastra_a_las_demas(
    config: Config, backend: BackendSimulado
) -> None:
    backend.ips_que_fallan.add("10.0.0.1")
    resultado = _motor(config, backend).sincronizar()
    assert resultado.exitosas == 1
    assert resultado.fallidas == 1
    fallida = next(r for r in resultado.balanzas if r.balanza_id == 1)
    assert "no acepto la conexion" in fallida.mensaje


def test_reintenta_las_veces_configuradas(config: Config, backend: BackendSimulado) -> None:
    config.sincronizacion.reintentos = 2
    config.sincronizacion.espera_reintento_seg = 0
    backend.ips_que_fallan.add("10.0.0.1")
    resultado = _motor(config, backend).sincronizar()
    fallida = next(r for r in resultado.balanzas if r.balanza_id == 1)
    assert fallida.intentos == 3


def test_el_ipack_coincide_con_el_contenido(config: Config, backend: BackendSimulado) -> None:
    """El simulador rechaza el lote si ipack no cuadra, igual que la balanza."""
    resultado = _motor(config, backend).sincronizar()
    assert resultado.ok
    for lote in backend.lotes_recibidos:
        assert json.loads(lote)


def test_trocea_el_catalogo(config: Config, backend: BackendSimulado) -> None:
    config.rongta.tamano_lote_plu = 2
    resultado = _motor(config, backend).sincronizar()
    primera = resultado.balanzas[0]
    assert primera.lotes_enviados >= 2
    assert primera.plus_enviados == resultado.plus_leidos


def test_solo_una_balanza(config: Config, backend: BackendSimulado) -> None:
    resultado = _motor(config, backend).sincronizar(solo_ids=[2])
    assert [r.balanza_id for r in resultado.balanzas] == [2]


def test_omite_si_no_hubo_cambios(config: Config, backend: BackendSimulado) -> None:
    config.sincronizacion.omitir_si_sin_cambios = True
    motor = _motor(config, backend)
    assert motor.sincronizar().exitosas == 2
    segunda = motor.sincronizar()
    assert segunda.omitidas == 2


def test_forzar_ignora_el_estado(config: Config, backend: BackendSimulado) -> None:
    config.sincronizacion.omitir_si_sin_cambios = True
    motor = _motor(config, backend)
    motor.sincronizar()
    assert motor.sincronizar(forzar=True).exitosas == 2


def test_la_balanza_fallida_se_reintenta_en_la_corrida_siguiente(
    config: Config, backend: BackendSimulado
) -> None:
    """Omitir por huella es por balanza: la que estaba apagada debe reintentarse
    aunque el archivo de origen no haya cambiado."""
    config.sincronizacion.omitir_si_sin_cambios = True
    backend.ips_que_fallan.add("10.0.0.1")
    motor = _motor(config, backend)
    motor.sincronizar()

    backend.ips_que_fallan.clear()
    segunda = motor.sincronizar()
    assert segunda.exitosas == 1
    assert next(r for r in segunda.balanzas if r.balanza_id == 1).ok
    assert next(r for r in segunda.balanzas if r.balanza_id == 2).omitida


def test_origen_ausente_no_lanza_excepcion(config: Config, backend: BackendSimulado) -> None:
    config.origen.ruta = "/no/existe/cadtxt.txt"
    resultado = _motor(config, backend).sincronizar()
    assert not resultado.ok
    assert "No se encontro" in resultado.error_global
    assert not backend.operaciones("conectar"), "no debe tocar la red sin datos"


def test_limpieza_previa_opcional(config: Config, backend: BackendSimulado) -> None:
    config.rongta.limpiar_antes_de_enviar = True
    _motor(config, backend).sincronizar()
    assert len(backend.operaciones("limpiar_plu")) == 2


def test_forzar_limpieza(config: Config, backend: BackendSimulado) -> None:
    motor = _motor(config, backend)
    resultado = motor.limpiar_balanza(config.balanzas[0])
    assert resultado.ok
    assert backend.operaciones("limpiar_plu")
    assert not backend.hay_fugas


def test_hotkeys_fallidas_no_invalidan_el_catalogo(
    config: Config, backend: BackendSimulado
) -> None:
    """El catalogo ya quedo grabado: unas teclas rapidas rechazadas son un
    aviso, no un fallo de la balanza entera."""
    backend.operaciones_que_fallan.add("enviar_hotkey")
    resultado = _motor(config, backend).sincronizar()
    assert resultado.exitosas == 2
    assert all(r.hotkeys_enviadas == 0 for r in resultado.balanzas)


def test_paralelo_respeta_una_conexion_por_balanza(
    config: Config, backend: BackendSimulado
) -> None:
    config.sincronizacion.balanzas_en_paralelo = 2
    resultado = _motor(config, backend).sincronizar()
    assert resultado.exitosas == 2
    assert not backend.hay_fugas


def test_probar_informa_de_ping_y_puerto_por_separado(
    config: Config, backend: BackendSimulado, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Son dos comprobaciones distintas: el ping es ICMP y no tiene puertos."""
    from ibalance import net

    config.sincronizacion.verificar_ping = True
    monkeypatch.setattr(net, "ping", lambda ip, t=2: True)
    monkeypatch.setattr(net, "puerto_abierto", lambda ip, p, t=2.0: (False, "rechazada"))

    ok, motivo = _motor(config, backend).probar_balanza(config.balanzas[0])
    assert "ping OK" in motivo
    assert "rechazada" in motivo


def test_un_sondeo_fallido_no_declara_inalcanzable_a_la_balanza(
    config: Config, backend: BackendSimulado, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La conexion real la abre la DLL, no el sondeo: si responde al ping, la
    balanza esta en la red aunque el puerto sondeado no acepte."""
    from ibalance import net

    config.sincronizacion.verificar_ping = True
    config.sincronizacion.pausa_tras_desconectar_seg = 0
    monkeypatch.setattr(net, "ping", lambda ip, t=2: True)
    monkeypatch.setattr(net, "puerto_abierto", lambda ip, p, t=2.0: (False, "cerrado"))

    ok, _ = _motor(config, backend).probar_balanza(config.balanzas[0])
    assert ok is True


def test_sin_ping_ni_puerto_si_es_inalcanzable(
    config: Config, backend: BackendSimulado, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ibalance import net

    config.sincronizacion.verificar_ping = True
    monkeypatch.setattr(net, "ping", lambda ip, t=2: False)
    monkeypatch.setattr(net, "puerto_abierto", lambda ip, p, t=2.0: (False, "cerrado"))

    ok, motivo = _motor(config, backend).probar_balanza(config.balanzas[0])
    assert ok is False
    assert "sin respuesta al ping" in motivo
