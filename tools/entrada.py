"""Punto de entrada para PyInstaller.

``src/ibalance/__main__.py`` sirve para ``python -m ibalance``, donde Python
sabe que el modulo pertenece al paquete y sus imports relativos funcionan.
PyInstaller, en cambio, ejecuta el script de entrada como modulo suelto: alli
``from .cli import main`` falla con «attempted relative import with no known
parent package» y el ejecutable no arranca. De ahi este archivo, que usa un
import absoluto.
"""

from __future__ import annotations

import sys

from ibalance.cli import main

if __name__ == "__main__":
    sys.exit(main())
