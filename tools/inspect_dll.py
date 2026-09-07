#!/usr/bin/env python3
"""Inspecciona rtslabelscale.dll sin cargarla.

Lee la cabecera PE y la tabla de exportaciones directamente del archivo, asi
que funciona en cualquier sistema operativo: sirve para comprobar por correo
que la DLL que tiene el cliente es la correcta antes de pisarla.

    python tools/inspect_dll.py "C:\\ibalance\\rtslabelscale.dll"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ibalance.rongta.dll import (  # noqa: E402
    FUNCIONES,
    FUNCIONES_OPCIONALES,
    arquitectura_pe,
    arquitectura_proceso,
    listar_exportaciones,
)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    ruta = Path(argv[1])
    if not ruta.is_file():
        print(f"No existe: {ruta}")
        return 1

    bits = arquitectura_pe(ruta)
    print(f"Archivo      : {ruta}")
    print(f"Tamano       : {ruta.stat().st_size} bytes")
    print(f"Arquitectura : {bits} bits (este Python: {arquitectura_proceso()} bits)")
    if bits and bits != arquitectura_proceso():
        print("               AVISO: no podria cargarse desde este interprete")

    exportaciones = listar_exportaciones(ruta)
    print(f"Exportaciones: {len(exportaciones)}")

    faltan = [f for f in FUNCIONES if f not in exportaciones]
    print("\nFunciones obligatorias:")
    for nombre in FUNCIONES:
        print(f"  [{'OK' if nombre in exportaciones else '  ':2}] {nombre}")
    print("\nFunciones opcionales:")
    for nombre in FUNCIONES_OPCIONALES:
        print(f"  [{'OK' if nombre in exportaciones else '  ':2}] {nombre}")

    if faltan:
        print(f"\nFALTAN funciones obligatorias: {', '.join(faltan)}")
        return 1
    print("\nLa DLL tiene todo lo que la aplicacion necesita.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
