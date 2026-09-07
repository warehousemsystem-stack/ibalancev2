"""Comprobaciones de red previas al envio.

Sondear antes de llamar a la DLL evita quedarse colgado 15 segundos por cada
balanza apagada, y separa con claridad "la balanza no esta en la red" de "la
balanza rechazo los datos", que son incidencias con soluciones distintas.
"""

from __future__ import annotations

import os
import socket
import subprocess


def _opciones_ping(ip: str, timeout_seg: int) -> list[str]:
    if os.name == "nt":
        return ["ping", "-n", "1", "-w", str(max(1, int(timeout_seg * 1000))), ip]
    # En Linux/macOS los interruptores son otros; util para pruebas locales.
    return ["ping", "-c", "1", "-W", str(max(1, int(timeout_seg))), ip]


def ping(ip: str, timeout_seg: int = 2) -> bool:
    """``True`` si la IP responde a ICMP."""
    if not ip.strip():
        return False
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        # Sin esto, cada ping abre una consola negra sobre la interfaz grafica.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        resultado = subprocess.run(  # noqa: S603 - comando fijo, IP validada arriba
            _opciones_ping(ip, timeout_seg),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seg + 3,
            **kwargs,  # type: ignore[arg-type]
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return resultado.returncode == 0


def puerto_abierto(ip: str, puerto: int, timeout_seg: float = 2.0) -> tuple[bool, str]:
    """Comprueba el puerto TCP de la balanza.

    Devuelve ``(disponible, motivo)``. Distingue los dos casos que confunden al
    personal de tienda: nadie escucha en el puerto (balanza apagada) frente a
    conexion rechazada o ya ocupada por otro programa, que es lo que pasa
    cuando la aplicacion antigua se quedo residente reteniendo el puerto.
    """
    if not ip.strip():
        return False, "sin IP configurada"
    try:
        with socket.create_connection((ip, puerto), timeout=timeout_seg):
            return True, "puerto accesible"
    except TimeoutError:
        return False, f"tiempo de espera agotado al abrir {ip}:{puerto}"
    except ConnectionRefusedError:
        return False, (
            f"{ip}:{puerto} rechazo la conexion (la balanza esta encendida pero "
            "no acepta conexiones; suele indicar que otra aplicacion mantiene "
            "abierta la sesion)"
        )
    except OSError as exc:
        return False, f"no se pudo alcanzar {ip}:{puerto}: {exc}"


def es_ip_valida(texto: str) -> bool:
    """Valida una IPv4 sin depender de que la balanza responda."""
    partes = texto.strip().split(".")
    if len(partes) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 and (p == "0" or not p.startswith("0") or len(p) == 1) for p in partes)
