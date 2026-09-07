"""Tipos comunes a todos los lectores de origen."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from ..models import Plu


class OrigenError(Exception):
    """No se pudo leer el origen de datos."""


@dataclass
class Lectura:
    """Resultado de leer un origen.

    Las lineas con problemas nunca abortan la corrida: se acumulan en
    ``incidencias`` y se reportan. Un archivo del ERP con 3 lineas rotas no
    puede dejar 6 balanzas sin precios actualizados.
    """

    plus: list[Plu] = field(default_factory=list)
    incidencias: list[str] = field(default_factory=list)
    ruta: str = ""
    huella: str = ""
    lineas_totales: int = 0

    @property
    def total(self) -> int:
        return len(self.plus)


def huella_archivo(ruta: str | Path) -> str:
    """SHA-256 del archivo, para saltarse envios cuando nada cambio."""
    digest = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for bloque in iter(lambda: fh.read(65536), b""):
            digest.update(bloque)
    return digest.hexdigest()
