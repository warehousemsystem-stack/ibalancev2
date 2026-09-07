"""Configuracion del registro: consola + archivo rotativo."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from .config import Registro

FORMATO = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"

_configurado = False


def configurar(registro: Registro, dir_base: Path, consola: bool = True) -> Path:
    """Prepara el logging global y devuelve la ruta del archivo de log.

    Es idempotente: la interfaz grafica y la CLI comparten proceso en algunos
    modos y no deben duplicar manejadores (ni cada linea del log).
    """
    global _configurado

    directorio = Path(registro.directorio)
    if not directorio.is_absolute():
        directorio = dir_base / directorio
    directorio.mkdir(parents=True, exist_ok=True)
    archivo = directorio / "ibalance.log"

    raiz = logging.getLogger("ibalance")
    if _configurado:
        return archivo

    raiz.setLevel(getattr(logging, registro.nivel.upper(), logging.INFO))
    raiz.propagate = False
    formato = logging.Formatter(FORMATO, FORMATO_FECHA)

    manejador = logging.handlers.RotatingFileHandler(
        archivo,
        maxBytes=max(registro.max_bytes, 100_000),
        backupCount=max(registro.copias, 1),
        encoding="utf-8",
    )
    manejador.setFormatter(formato)
    raiz.addHandler(manejador)

    if consola:
        consola_h = logging.StreamHandler()
        consola_h.setFormatter(logging.Formatter("%(message)s"))
        raiz.addHandler(consola_h)

    _configurado = True
    return archivo


def obtener(nombre: str) -> logging.Logger:
    """Logger hijo del arbol ``ibalance``."""
    return logging.getLogger(f"ibalance.{nombre}")


class ManejadorCallback(logging.Handler):
    """Reenvia cada linea de log a una funcion (la usa la interfaz grafica)."""

    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.callback(self.format(record), record.levelname)
        except Exception:  # noqa: BLE001 - un fallo de la UI no puede tumbar el log
            self.handleError(record)
