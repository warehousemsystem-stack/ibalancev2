"""Reportes de cada corrida y estado persistente entre corridas."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ResultadoSincronizacion

NOMBRE_ESTADO = "estado.json"


def guardar_reporte(resultado: ResultadoSincronizacion, directorio: Path) -> Path:
    """Escribe el detalle de la corrida como JSON, con marca de tiempo."""
    directorio.mkdir(parents=True, exist_ok=True)
    marca = resultado.inicio.strftime("%Y%m%d_%H%M%S")
    destino = directorio / f"sync_{marca}.json"
    destino.write_text(
        json.dumps(resultado.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return destino


def resumen_texto(resultado: ResultadoSincronizacion) -> str:
    """Resumen de una corrida en texto plano, para consola o correo."""
    lineas = [
        f"Sincronizacion {resultado.inicio:%Y-%m-%d %H:%M:%S} "
        f"({resultado.duracion_seg:.1f} s)",
        f"Origen: {resultado.origen}",
        f"Productos leidos: {resultado.plus_leidos}",
    ]
    if resultado.errores_lectura:
        lineas.append(f"Incidencias de lectura: {len(resultado.errores_lectura)}")
    if resultado.error_global:
        lineas.append(f"ERROR: {resultado.error_global}")
    if resultado.cancelada:
        lineas.append("La corrida fue cancelada por el operador")
    lineas.append(
        f"Balanzas: {resultado.exitosas} correctas, {resultado.fallidas} con error, "
        f"{resultado.omitidas} omitidas"
    )
    for balanza in resultado.balanzas:
        if balanza.omitida:
            estado = "OMITIDA"
        elif balanza.ok:
            estado = "OK"
        else:
            estado = "ERROR"
        lineas.append(
            f"  [{estado:>7}] {balanza.nombre} ({balanza.ip}) "
            f"{balanza.plus_enviados} PLU en {balanza.duracion_seg:.1f} s - {balanza.mensaje}"
        )
    return "\n".join(lineas)


class Estado:
    """Recuerda que se envio a cada balanza para no repetir trabajo inutil.

    Se guarda por balanza y no de forma global: si una balanza estaba apagada
    durante la ultima corrida, la siguiente debe reenviarle el catalogo aunque
    el archivo de origen no haya cambiado.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self.datos: dict[str, Any] = {"balanzas": {}}
        self.cargar()

    def cargar(self) -> None:
        if not self.ruta.is_file():
            return
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # un estado corrupto solo implica reenviar; nunca es fatal
        if isinstance(datos, dict) and isinstance(datos.get("balanzas"), dict):
            self.datos = datos

    def guardar(self) -> None:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(
                json.dumps(self.datos, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def huella_de(self, balanza_id: int) -> str:
        registro = self.datos["balanzas"].get(str(balanza_id)) or {}
        return str(registro.get("huella", ""))

    def marcar_enviada(self, balanza_id: int, huella: str, plus: int) -> None:
        self.datos["balanzas"][str(balanza_id)] = {
            "huella": huella,
            "plus": plus,
            "fecha": datetime.now().isoformat(timespec="seconds"),
        }

    def olvidar(self, balanza_id: int | None = None) -> None:
        """Fuerza el reenvio en la proxima corrida."""
        if balanza_id is None:
            self.datos["balanzas"] = {}
        else:
            self.datos["balanzas"].pop(str(balanza_id), None)
