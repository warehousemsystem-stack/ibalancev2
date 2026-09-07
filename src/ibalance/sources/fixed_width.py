"""Lector del ``cadtxt.txt``: un registro por linea, campos por posicion.

Formato observado en produccion (79 caracteres por linea)::

    002893P**PITAHAYA ROJA X KG**0000750000                       2 1 1
    |____||||____________________||_____||_|
    0    6 7                    29     36 39
      |   |         |               |     |
      |   |         |               |     +-- 36..38 vida util en dias
      |   |         |               +-------- 29..35 precio sin punto decimal
      |   |         +------------------------  7..28 nombre (22 caracteres)
      |   +----------------------------------      6 marca de tipo (P = pesable)
      +--------------------------------------  0..5 codigo PLU

Los rangos no estan cableados: salen de ``origen.layout``, porque otra tienda
puede exportar el mismo archivo con anchos distintos.
"""

from __future__ import annotations

from pathlib import Path

from ..config import Origen
from ..models import Plu, normalizar_nombre
from .base import Lectura, OrigenError, huella_archivo


def _campo(linea: str, rangos: dict[str, tuple[int, int]], nombre: str) -> str:
    """Recorta un campo de la linea segun el layout configurado."""
    rango = rangos.get(nombre)
    return linea[rango[0]:rango[1]] if rango else ""


def _entero(texto: str) -> int | None:
    texto = texto.strip()
    if not texto:
        return 0
    if texto.lstrip("+-").isdigit():
        return int(texto)
    return None


def leer_txt_ancho_fijo(origen: Origen, ruta: str | None = None) -> Lectura:
    """Parsea un archivo de ancho fijo y devuelve los PLUs validos."""
    destino = Path(ruta or origen.ruta)
    if not destino.is_file():
        raise OrigenError(f"No se encontro el archivo de origen: {destino}")

    rangos = origen.layout.rangos()
    if "codigo" not in rangos or "precio" not in rangos or "nombre" not in rangos:
        raise OrigenError(
            "origen.layout debe definir al menos 'codigo', 'nombre' y 'precio'"
        )
    ancho_minimo = max(fin for _, fin in rangos.values())

    lectura = Lectura(ruta=str(destino), huella=huella_archivo(destino))
    filtro_tipo = origen.solo_marca_tipo.strip().upper()
    vistos: dict[str, int] = {}

    with open(destino, encoding=origen.encoding, errors="replace", newline="") as fh:
        for numero, linea in enumerate(fh, start=1):
            linea = linea.rstrip("\r\n")
            lectura.lineas_totales += 1
            if not linea.strip():
                continue
            if len(linea) < ancho_minimo:
                lectura.incidencias.append(
                    f"linea {numero}: mide {len(linea)} caracteres y se esperaban "
                    f"al menos {ancho_minimo}; omitida"
                )
                continue

            def campo(nombre: str, _linea: str = linea) -> str:
                return _campo(_linea, rangos, nombre)

            codigo = campo("codigo").strip()
            if not codigo.isdigit():
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo!r} no es numerico; omitida"
                )
                continue

            marca = campo("tipo").strip().upper()
            if filtro_tipo and marca != filtro_tipo:
                continue

            nombre = normalizar_nombre(
                campo("nombre"), origen.nombre_ancho_max, origen.quitar_acentos
            )
            if not nombre:
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo} sin descripcion; omitida"
                )
                continue

            precio = _entero(campo("precio"))
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

            vida_util = _entero(campo("vida_util_dias")) or 0
            departamento = _entero(campo("departamento")) or 0

            if codigo in vistos:
                lectura.incidencias.append(
                    f"linea {numero}: codigo {codigo} repetido "
                    f"(ya aparecio en la linea {vistos[codigo]}); se conserva el ultimo"
                )
                indice = next(
                    i for i, p in enumerate(lectura.plus) if p.codigo == codigo
                )
                lectura.plus.pop(indice)
            vistos[codigo] = numero

            lectura.plus.append(
                Plu(
                    codigo=codigo,
                    nombre=nombre,
                    precio=precio,
                    vida_util_dias=vida_util,
                    pesable=(marca == "P") if marca else True,
                    departamento=departamento,
                    extra={"linea": numero, "marca": marca},
                )
            )

    return lectura
