"""Interfaz comun de los backends de balanza (DLL real y simulador)."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress

from .errors import ConexionError


class BackendBalanza(ABC):
    """Operaciones que la aplicacion necesita de una balanza.

    Existe para que el motor de sincronizacion no dependa de Windows: el
    backend real habla con ``rtslabelscale.dll`` y el simulado escribe a disco,
    de modo que toda la logica se puede probar en cualquier sistema operativo.

    Las firmas replican las declaraciones P/Invoke de la aplicacion original::

        int rtscaleLoadIniFile(char* configFile)
        int rtscaleConnect(char* addr, int baudRate, char* connId)
        int rtscaleDisConnect(char* connId)
        int rtscaleClearPLUData(char* connId)
        int rtscaleDownLoadPLU(char* connId, char* pluJson, int ipack)
        int rtscaleDownLoadHotkey(char* connId, int* tabla, int indiceTabla)
        int rtscaleDownLoadDeletePlu(int connId, int lfCode)
        int rtscaleGetScaleType(char* connId, char* retJson, int len)
    """

    #: Texto corto para los logs ("rtslabelscale.dll (stdcall)" / "simulador").
    descripcion: str = "backend"

    @abstractmethod
    def abrir(self) -> None:
        """Prepara el backend (carga la DLL). Idempotente."""

    @abstractmethod
    def conectar(self, ip: str, conn_id: str) -> int:
        """Abre la conexion TCP con la balanza y devuelve el codigo de la DLL."""

    @abstractmethod
    def desconectar(self, conn_id: str) -> int:
        """Cierra la conexion. Nunca debe lanzar excepcion."""

    @abstractmethod
    def enviar_plu(self, conn_id: str, lote_json: str, registros: int) -> int:
        """Envia un lote de PLUs ya serializado.

        ``registros`` es la cantidad de productos que contiene ``lote_json``:
        es el argumento ``ipack`` de la DLL, y la balanza no graba nada si no
        coincide con lo que trae la cadena.
        """

    @abstractmethod
    def enviar_hotkey(self, conn_id: str, pagina: Sequence[int], indice: int) -> int:
        """Envia una pagina de teclas rapidas (indices 0, 1 y 2)."""

    @abstractmethod
    def limpiar_plu(self, conn_id: str) -> int:
        """Borra el catalogo completo de la balanza."""

    def eliminar_plu(self, conn_id: str, lf_code: int) -> int:
        """Borra un unico producto. Opcional segun el modelo de balanza."""
        raise NotImplementedError("Este backend no implementa el borrado individual")

    def cargar_ini(self, ruta_ini: str) -> int:
        """Carga el .ini de configuracion de etiquetas del fabricante."""
        raise NotImplementedError("Este backend no implementa la carga de .ini")

    def tipo_balanza(self, conn_id: str, longitud: int = 512) -> str:
        """Consulta modelo y firmware. Devuelve JSON crudo o cadena vacia."""
        return ""

    def cerrar(self) -> None:  # noqa: B027 - opcional a proposito
        """Libera recursos del backend. Por defecto no hace nada."""
        return None


@contextmanager
def conexion(
    backend: BackendBalanza,
    ip: str,
    conn_id: str,
    codigo_exito: int = 0,
    pausa_al_salir: float = 0.0,
) -> Iterator[None]:
    """Conecta, cede el control y desconecta pase lo que pase.

    Las RLS-1000 aceptan una unica conexion simultanea: si el proceso termina
    sin desconectar, la balanza queda ocupada hasta que expira su propio
    temporizador y la siguiente corrida falla sin motivo aparente. Por eso la
    desconexion va en un ``finally`` y, opcionalmente, se espera un momento
    antes de tocar la siguiente balanza.
    """
    codigo = backend.conectar(ip, conn_id)
    if codigo != codigo_exito:
        raise ConexionError(
            f"la balanza {ip} no acepto la conexion (codigo {codigo}); "
            "suele indicar que esta apagada, en otra subred, o que otra "
            "aplicacion mantiene abierta la unica sesion que admite",
            codigo=codigo,
        )
    try:
        yield
    finally:
        # Desconectar nunca debe propagar: taparia el error real del envio.
        with suppress(Exception):
            backend.desconectar(conn_id)
        if pausa_al_salir > 0:
            time.sleep(pausa_al_salir)
