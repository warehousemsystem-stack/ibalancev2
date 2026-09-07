"""Lector CSV, por si el ERP deja de exportar el TXT de ancho fijo."""

from __future__ import annotations

import csv
from pathlib import Path

from ..config import Origen
from ..models import Plu, normalizar_nombre
from .base import Lectura, OrigenError, huella_archivo

# Nombres de columna aceptados cuando el config no mapea explicitamente.
ALIAS = {
    "codigo": ("codigo", "code", "plu", "codigo_plu"),
    "nombre": ("nombre", "descripcion", "name", "descripcion_producto"),
    "precio": ("precio", "price", "unitprice", "precio_venta"),
    "vida_util_dias": ("vida_util_dias", "vida_util", "shelf_life", "dias"),
    "departamento": ("departamento", "dept", "deptment"),
}


def _resolver_columnas(origen: Origen, cabecera: list[str]) -> dict[str, str]:
    normalizada = {c.strip().lower(): c for c in cabecera}
    columnas: dict[str, str] = {}
    for campo, opciones in ALIAS.items():
        explicito = origen.csv_columnas.get(campo)
        if explicito:
            if explicito not in cabecera:
                raise OrigenError(
                    f"La columna {explicito!r} configurada para {campo!r} no existe "
                    f"en el CSV (columnas: {', '.join(cabecera)})"
                )
            columnas[campo] = explicito
            continue
        for opcion in opciones:
            if opcion in normalizada:
                columnas[campo] = normalizada[opcion]
                break
    faltan = [c for c in ("codigo", "nombre", "precio") if c not in columnas]
    if faltan:
        raise OrigenError(
            "El CSV no tiene columnas para: " + ", ".join(faltan)
            + f" (columnas encontradas: {', '.join(cabecera)})"
        )
    return columnas


def _a_entero(valor: str) -> int | None:
    valor = (valor or "").strip().replace(" ", "")
    if not valor:
        return 0
    # Acepta "14,82" y "14.82" y los convierte a centimos.
    if "," in valor or "." in valor:
        valor = valor.replace(".", "").replace(",", ".") if valor.count(",") == 1 else valor
        try:
            return int(round(float(valor) * 100))
        except ValueError:
            return None
    return int(valor) if valor.lstrip("+-").isdigit() else None


def leer_csv(origen: Origen, ruta: str | None = None) -> Lectura:
    """Parsea un CSV con cabecera y devuelve los PLUs validos."""
    destino = Path(ruta or origen.ruta)
    if not destino.is_file():
        raise OrigenError(f"No se encontro el archivo de origen: {destino}")

    lectura = Lectura(ruta=str(destino), huella=huella_archivo(destino))
    with open(destino, encoding=origen.encoding, errors="replace", newline="") as fh:
        lector = csv.reader(fh, delimiter=origen.csv_delimitador or ";")
        filas = iter(lector)
        try:
            cabecera = next(filas)
        except StopIteration:
            return lectura
        if not origen.csv_tiene_cabecera:
            raise OrigenError("El lector CSV requiere csv_tiene_cabecera = true")

        cabecera = [c.lstrip("﻿") for c in cabecera]
        columnas = _resolver_columnas(origen, cabecera)
        indices = {campo: cabecera.index(col) for campo, col in columnas.items()}

        for numero, fila in enumerate(filas, start=2):
            lectura.lineas_totales += 1
            if not any(c.strip() for c in fila):
                continue

            def campo(nombre: str, _fila: list[str] = fila) -> str:
                indice = indices.get(nombre)
                if indice is None or indice >= len(_fila):
                    return ""
                return _fila[indice]

            codigo = campo("codigo").strip()
            if not codigo.isdigit():
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo!r} no es numerico; omitida"
                )
                continue
            nombre = normalizar_nombre(
                campo("nombre"), origen.nombre_ancho_max, origen.quitar_acentos
            )
            if not nombre:
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo} sin descripcion; omitida"
                )
                continue
            precio = _a_entero(campo("precio"))
            if precio is None:
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo} con precio ilegible "
                    f"{campo('precio')!r}; omitida"
                )
                continue
            if precio < origen.precio_minimo:
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo} con precio {precio} por debajo "
                    f"del minimo ({origen.precio_minimo}); omitida"
                )
                continue

            lectura.plus.append(
                Plu(
                    codigo=codigo,
                    nombre=nombre,
                    precio=precio,
                    vida_util_dias=_a_entero(campo("vida_util_dias")) or 0,
                    departamento=_a_entero(campo("departamento")) or 0,
                    extra={"linea": numero},
                )
            )
    return lectura
