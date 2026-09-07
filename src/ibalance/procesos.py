"""Deteccion y cierre de la aplicacion antigua que retiene el puerto.

La version anterior (C# / ClickOnce, ``ibalance.exe``) queda a veces residente
tras cerrar su ventana y conserva abierta la sesion TCP con la balanza. Como
las RLS-1000 aceptan una sola conexion, la nueva aplicacion se encuentra el
puerto ocupado y todos los envios fallan sin motivo aparente.

Cerrar procesos ajenos es intrusivo, asi que esta desactivado por defecto
(``sincronizacion.cerrar_procesos_legacy``) y solo actua sobre los nombres que
el operador liste explicitamente.
"""

from __future__ import annotations

import os
import subprocess

#: Nombre del proceso de la aplicacion anterior.
PROCESOS_LEGACY = ("ibalance.exe",)


def _sin_ventana() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def procesos_activos(nombres: list[str] | tuple[str, ...] = PROCESOS_LEGACY) -> list[str]:
    """Devuelve cuales de esos procesos estan corriendo ahora mismo."""
    if os.name != "nt" or not nombres:
        return []
    try:
        salida = subprocess.run(  # noqa: S603 - comando fijo del sistema
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            **_sin_ventana(),  # type: ignore[arg-type]
        ).stdout
    except (subprocess.TimeoutExpired, OSError):
        return []

    activos = []
    minusculas = salida.lower()
    for nombre in nombres:
        if f'"{nombre.lower()}"' in minusculas:
            activos.append(nombre)
    return activos


def cerrar_procesos(
    nombres: list[str] | tuple[str, ...] = PROCESOS_LEGACY,
) -> list[str]:
    """Cierra los procesos indicados y devuelve los que efectivamente se cerraron.

    Nunca lanza excepcion: que no se pueda cerrar la app antigua (por permisos,
    por ejemplo) no debe impedir el intento de sincronizar.
    """
    if os.name != "nt":
        return []
    cerrados = []
    for nombre in procesos_activos(nombres):
        try:
            resultado = subprocess.run(  # noqa: S603 - comando fijo del sistema
                ["taskkill", "/F", "/IM", nombre],
                capture_output=True,
                text=True,
                timeout=15,
                **_sin_ventana(),  # type: ignore[arg-type]
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        if resultado.returncode == 0:
            cerrados.append(nombre)
    return cerrados
