"""Modelos de dominio: producto (PLU) y resultado de sincronizacion."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def normalizar_nombre(texto: str, ancho_max: int = 0, quitar_acentos: bool = False) -> str:
    """Limpia el nombre de un producto para que la balanza lo acepte.

    Las RLS-1000 muestran el nombre en una pantalla LCD y lo imprimen en la
    etiqueta con una fuente de ancho fijo: los caracteres no latinos se ven como
    basura. Ademas el archivo de origen suele traer espacios duros (``\\xa0``)
    heredados de exportaciones desde el ERP.
    """
    texto = texto.replace("\xa0", " ").replace("\t", " ")
    texto = " ".join(texto.split())
    if quitar_acentos:
        descompuesto = unicodedata.normalize("NFKD", texto)
        texto = "".join(c for c in descompuesto if not unicodedata.combining(c))
    if ancho_max > 0:
        texto = texto[:ancho_max]
    return texto.strip()


@dataclass(slots=True)
class Plu:
    """Un producto tal como se envia a la balanza.

    Atributos:
        codigo: Codigo tal cual viene del origen, con ceros a la izquierda.
        nombre: Descripcion que se imprime en la etiqueta.
        precio: Precio en la unidad minima (centimos). ``1482`` == ``14,82``.
        vida_util_dias: Dias de vida util; la balanza calcula la fecha de
            vencimiento a partir de este valor (campo ``ShlefTime`` de la DLL).
        pesable: ``True`` cuando el articulo se vende por peso (marca ``P``).
        departamento: Departamento configurado para el articulo.
        extra: Campos sueltos del origen que se conservan para diagnostico.
    """

    codigo: str
    nombre: str
    precio: int
    vida_util_dias: int = 0
    pesable: bool = True
    departamento: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def codigo_corto(self) -> str:
        """Codigo sin ceros a la izquierda (``LFCode`` en la DLL)."""
        codigo = self.codigo.strip()
        if codigo.isdigit():
            return str(int(codigo))
        return codigo

    @property
    def codigo_numerico(self) -> int:
        """Codigo como entero, o ``0`` si no es numerico (para hotkeys)."""
        codigo = self.codigo.strip()
        return int(codigo) if codigo.isdigit() else 0

    def precio_formateado(self, decimales: int = 2) -> str:
        """Precio legible para logs y reportes (``1482`` -> ``14.82``)."""
        if decimales <= 0:
            return str(self.precio)
        divisor = 10 ** decimales
        return f"{self.precio / divisor:.{decimales}f}"

    def __str__(self) -> str:  # pragma: no cover - solo presentacion
        return f"{self.codigo} {self.nombre!r} {self.precio_formateado()}"


@dataclass(slots=True)
class ResultadoBalanza:
    """Resultado del envio a una balanza concreta."""

    balanza_id: int
    nombre: str
    ip: str
    ok: bool
    mensaje: str
    duracion_seg: float = 0.0
    plus_enviados: int = 0
    lotes_enviados: int = 0
    hotkeys_enviadas: int = 0
    intentos: int = 1
    omitida: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "balanza_id": self.balanza_id,
            "nombre": self.nombre,
            "ip": self.ip,
            "ok": self.ok,
            "omitida": self.omitida,
            "mensaje": self.mensaje,
            "duracion_seg": round(self.duracion_seg, 3),
            "plus_enviados": self.plus_enviados,
            "lotes_enviados": self.lotes_enviados,
            "hotkeys_enviadas": self.hotkeys_enviadas,
            "intentos": self.intentos,
        }


@dataclass(slots=True)
class ResultadoSincronizacion:
    """Resumen de una corrida completa de sincronizacion."""

    inicio: datetime
    fin: datetime
    origen: str
    plus_leidos: int
    errores_lectura: list[str] = field(default_factory=list)
    balanzas: list[ResultadoBalanza] = field(default_factory=list)
    cancelada: bool = False
    error_global: str = ""

    @property
    def duracion_seg(self) -> float:
        return (self.fin - self.inicio).total_seconds()

    @property
    def exitosas(self) -> int:
        return sum(1 for r in self.balanzas if r.ok)

    @property
    def fallidas(self) -> int:
        return sum(1 for r in self.balanzas if not r.ok and not r.omitida)

    @property
    def omitidas(self) -> int:
        return sum(1 for r in self.balanzas if r.omitida)

    @property
    def ok(self) -> bool:
        return not self.error_global and not self.cancelada and self.fallidas == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "inicio": self.inicio.isoformat(timespec="seconds"),
            "fin": self.fin.isoformat(timespec="seconds"),
            "duracion_seg": round(self.duracion_seg, 3),
            "origen": self.origen,
            "plus_leidos": self.plus_leidos,
            "errores_lectura": self.errores_lectura,
            "cancelada": self.cancelada,
            "error_global": self.error_global,
            "resumen": {
                "exitosas": self.exitosas,
                "fallidas": self.fallidas,
                "omitidas": self.omitidas,
            },
            "balanzas": [b.to_dict() for b in self.balanzas],
        }
