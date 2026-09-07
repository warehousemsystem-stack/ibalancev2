"""Lectores de origenes de datos de productos."""

from __future__ import annotations

from ..config import Origen
from .base import Lectura, OrigenError
from .csv_source import leer_csv
from .fixed_width import leer_txt_ancho_fijo

__all__ = ["Lectura", "OrigenError", "leer", "leer_csv", "leer_txt_ancho_fijo"]

_LECTORES = {
    "txt_ancho_fijo": leer_txt_ancho_fijo,
    "csv": leer_csv,
}


def leer(origen: Origen, ruta: str | None = None) -> Lectura:
    """Lee el origen configurado y devuelve los PLUs junto con las incidencias."""
    lector = _LECTORES.get(origen.tipo)
    if lector is None:
        raise OrigenError(f"Tipo de origen no soportado: {origen.tipo!r}")
    return lector(origen, ruta or origen.ruta)
