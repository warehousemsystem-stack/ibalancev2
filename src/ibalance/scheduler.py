"""Temporizador de sincronizaciones automaticas."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from .logging_setup import obtener

log = obtener("temporizador")


class Temporizador:
    """Dispara una funcion cada N minutos, en un hilo aparte.

    Usa ``Event.wait`` en lugar de ``time.sleep`` para que detenerlo sea
    inmediato: con ``sleep`` habria que esperar hasta una hora a que el hilo
    despertara para poder cerrar la aplicacion.
    """

    def __init__(self, intervalo_minutos: int, accion: Callable[[], None]) -> None:
        self.intervalo_minutos = max(1, intervalo_minutos)
        self.accion = accion
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._proxima: datetime | None = None

    @property
    def activo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    @property
    def proxima_ejecucion(self) -> datetime | None:
        return self._proxima

    def segundos_restantes(self) -> int:
        if self._proxima is None:
            return 0
        return max(0, int((self._proxima - datetime.now()).total_seconds()))

    def iniciar(self, ejecutar_ahora: bool = False) -> None:
        if self.activo:
            return
        self._parar.clear()
        self._hilo = threading.Thread(
            target=self._bucle, args=(ejecutar_ahora,), name="temporizador", daemon=True
        )
        self._hilo.start()
        log.info("Temporizador iniciado: cada %d minutos", self.intervalo_minutos)

    def detener(self, esperar: bool = False) -> None:
        self._parar.set()
        self._proxima = None
        if esperar and self._hilo is not None:
            self._hilo.join(timeout=5)
        log.info("Temporizador detenido")

    def _bucle(self, ejecutar_ahora: bool) -> None:
        if ejecutar_ahora:
            self._disparar()
        while not self._parar.is_set():
            self._proxima = datetime.now() + timedelta(minutes=self.intervalo_minutos)
            if self._parar.wait(self.intervalo_minutos * 60):
                return
            self._disparar()

    def _disparar(self) -> None:
        try:
            self.accion()
        except Exception:  # noqa: BLE001 - un fallo no puede matar el temporizador
            log.exception("La sincronizacion programada termino con error")
