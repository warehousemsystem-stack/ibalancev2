"""Errores de la capa Rongta."""

from __future__ import annotations


class RongtaError(Exception):
    """Error generico de comunicacion con una balanza Rongta."""


class DllNoEncontradaError(RongtaError):
    """No se pudo localizar o cargar ``rtslabelscale.dll``."""


class ArquitecturaIncorrectaError(DllNoEncontradaError):
    """El proceso de Python no tiene la misma arquitectura que la DLL.

    ``rtslabelscale.dll`` es de 32 bits: solo puede cargarse desde un Python de
    32 bits. Es el fallo mas frecuente al instalar la aplicacion, y el mensaje
    de Windows (``%1 is not a valid Win32 application``) no lo deja claro.
    """


class ConexionError(RongtaError):
    """La balanza no acepto la conexion."""

    def __init__(self, mensaje: str, codigo: int | None = None) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


class OperacionError(RongtaError):
    """La DLL devolvio un codigo de error en una operacion de envio."""

    def __init__(self, operacion: str, codigo: int, detalle: str = "") -> None:
        mensaje = f"{operacion} devolvio codigo {codigo}"
        if detalle:
            mensaje = f"{mensaje}: {detalle}"
        super().__init__(mensaje)
        self.operacion = operacion
        self.codigo = codigo
