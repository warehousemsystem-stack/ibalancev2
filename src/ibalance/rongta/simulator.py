"""Backend simulado: reproduce el protocolo sin balanzas ni Windows.

Sirve para tres cosas: probar la aplicacion en el equipo de desarrollo, validar
los payloads antes de tocar una balanza en produccion, y ejecutar la bateria de
pruebas en cualquier sistema operativo.

Modela la restriccion que de verdad importa: **una sola conexion simultanea por
balanza**. Si el codigo intenta enviar sin conectar, o conectar dos veces sobre
la misma IP, el simulador falla igual que el equipo real.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .backend import BackendBalanza


@dataclass
class Llamada:
    """Registro de una operacion, para inspeccionarla en las pruebas."""

    operacion: str
    conn_id: str
    detalle: str = ""
    tamano: int = 0


@dataclass
class BackendSimulado(BackendBalanza):
    """Balanza de mentira con contabilidad de conexiones y volcado opcional."""

    #: IPs que deben fallar al conectar (para ensayar reintentos).
    ips_que_fallan: set[str] = field(default_factory=set)
    #: Operaciones que devuelven codigo de error, por nombre de operacion.
    operaciones_que_fallan: set[str] = field(default_factory=set)
    #: Directorio donde volcar los payloads enviados. ``None`` = no volcar.
    directorio_volcado: Path | None = None
    codigo_error: int = -1

    llamadas: list[Llamada] = field(default_factory=list)
    lotes_recibidos: list[str] = field(default_factory=list)
    conexiones_abiertas: dict[str, str] = field(default_factory=dict)
    max_conexiones_simultaneas: int = 0
    descripcion: str = "simulador (sin balanzas reales)"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------ #

    def abrir(self) -> None:
        if self.directorio_volcado is not None:
            self.directorio_volcado.mkdir(parents=True, exist_ok=True)

    def conectar(self, ip: str, conn_id: str) -> int:
        with self._lock:
            self.llamadas.append(Llamada("conectar", conn_id, ip))
            if ip in self.ips_que_fallan:
                return self.codigo_error
            if ip in self.conexiones_abiertas.values():
                # La balanza real rechaza la segunda conexion, no la encola.
                return self.codigo_error
            self.conexiones_abiertas[conn_id] = ip
            self.max_conexiones_simultaneas = max(
                self.max_conexiones_simultaneas, len(self.conexiones_abiertas)
            )
            return 0

    def desconectar(self, conn_id: str) -> int:
        with self._lock:
            self.llamadas.append(Llamada("desconectar", conn_id))
            self.conexiones_abiertas.pop(conn_id, None)
            return 0

    def _exigir_conexion(self, conn_id: str) -> str | None:
        return self.conexiones_abiertas.get(conn_id)

    def enviar_plu(self, conn_id: str, lote_json: str, registros: int) -> int:
        with self._lock:
            self.llamadas.append(
                Llamada("enviar_plu", conn_id, f"{registros} registros", len(lote_json))
            )
            if self._exigir_conexion(conn_id) is None:
                return self.codigo_error
            if "enviar_plu" in self.operaciones_que_fallan:
                return self.codigo_error
            # La balanza real ignora el lote si ipack no coincide con el
            # contenido; aqui se comprueba para que las pruebas lo detecten.
            try:
                reales = len(json.loads(lote_json))
            except json.JSONDecodeError:
                reales = registros  # formato legacy con comas finales
            if reales != registros:
                return self.codigo_error
            self.lotes_recibidos.append(lote_json)
            self._volcar(f"plu_{conn_id}_{len(self.lotes_recibidos):04d}.json", lote_json)
            return 0

    def enviar_hotkey(self, conn_id: str, pagina: Sequence[int], indice: int) -> int:
        with self._lock:
            self.llamadas.append(
                Llamada("enviar_hotkey", conn_id, f"pagina {indice}", len(pagina))
            )
            if self._exigir_conexion(conn_id) is None:
                return self.codigo_error
            if "enviar_hotkey" in self.operaciones_que_fallan:
                return self.codigo_error
            self._volcar(
                f"hotkey_{conn_id}_{indice}.json", json.dumps(list(pagina))
            )
            return 0

    def limpiar_plu(self, conn_id: str) -> int:
        with self._lock:
            self.llamadas.append(Llamada("limpiar_plu", conn_id))
            if self._exigir_conexion(conn_id) is None:
                return self.codigo_error
            return 0 if "limpiar_plu" not in self.operaciones_que_fallan else self.codigo_error

    def eliminar_plu(self, conn_id: str, lf_code: int) -> int:
        with self._lock:
            self.llamadas.append(Llamada("eliminar_plu", conn_id, str(lf_code)))
            return 0 if self._exigir_conexion(conn_id) else self.codigo_error

    def cargar_ini(self, ruta_ini: str) -> int:
        self.llamadas.append(Llamada("cargar_ini", "", ruta_ini))
        return 0

    def tipo_balanza(self, conn_id: str, longitud: int = 512) -> str:
        self.llamadas.append(Llamada("tipo_balanza", conn_id))
        return '{"model":"RLS-1000 (simulada)","version":"0.0"}'

    def cerrar(self) -> None:
        with self._lock:
            self.conexiones_abiertas.clear()

    # ------------------------------------------------------------------ #

    def _volcar(self, nombre: str, contenido: str) -> None:
        if self.directorio_volcado is None:
            return
        (self.directorio_volcado / nombre).write_text(contenido, encoding="utf-8")

    def operaciones(self, nombre: str) -> list[Llamada]:
        return [ll for ll in self.llamadas if ll.operacion == nombre]

    @property
    def hay_fugas(self) -> bool:
        """``True`` si quedo alguna conexion sin cerrar (bug grave)."""
        return bool(self.conexiones_abiertas)
