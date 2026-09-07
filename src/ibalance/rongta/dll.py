"""Envoltorio ctypes de ``rtslabelscale.dll``.

Firmas extraidas de los metadatos de ``ibalance.exe`` 1.0.0.84, la aplicacion
original en .NET (tabla ``ImplMap``, todas declaradas ``stdcall`` y con
``CharSet`` sin especificar, que en P/Invoke equivale a ANSI)::

    int rtscaleLoadIniFile(char* configFile);
    int rtscaleConnect(char* addr, int baudRate, char* connId);
    int rtscaleDisConnect(char* connId);
    int rtscaleClearPLUData(char* connId);
    int rtscaleDownLoadPLU(char* connId, char* pluJson, int iPack);
    int rtscaleDownLoadHotkey(char* connId, int* tabla, int indiceTabla);
    int rtscaleDownLoadDeletePlu(int connId, int lfCode);
    int rtscaleGetScaleType(char* connId, char* retJson, int len);
    int rtscaleUploadPluData(char* connId, void* records);

Dos detalles hacen que el envoltorio funcione o corrompa la pila:

1. **Arquitectura.** La DLL es de 32 bits, asi que solo carga en un Python de
   32 bits. Se comprueba antes de intentarlo para dar un mensaje entendible.
2. **Convencion de llamada.** Los metadatos de la aplicacion original dicen
   ``stdcall``, que en ctypes es ``WinDLL`` y **no** ``CDLL``. Equivocarse
   desbalancea la pila y produce fallos erraticos varias llamadas despues del
   error real. Por si una version distinta de la DLL cambiara de criterio, el
   modo ``auto`` carga los dos manejadores y aprovecha el desbalance que
   ctypes detecta en la primera llamada (``ValueError: Procedure probably
   called with ...``) para quedarse con el correcto.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from .backend import BackendBalanza
from .errors import ArquitecturaIncorrectaError, DllNoEncontradaError

#: Nombres exportados que la aplicacion necesita.
FUNCIONES = (
    "rtscaleConnect",
    "rtscaleDisConnect",
    "rtscaleDownLoadPLU",
    "rtscaleDownLoadHotkey",
    "rtscaleClearPLUData",
)

#: Exportaciones opcionales: mejoran el diagnostico pero no son imprescindibles.
FUNCIONES_OPCIONALES = (
    "rtscaleLoadIniFile",
    "rtscaleGetScaleType",
    "rtscaleDownLoadDeletePlu",
)

#: La DLL marshala las cadenas como ANSI; latin-1 cubre el castellano.
CODIFICACION = "latin-1"


def arquitectura_proceso() -> int:
    """Bits del interprete actual (32 o 64)."""
    return struct.calcsize("P") * 8


def arquitectura_pe(ruta: str | os.PathLike[str]) -> int | None:
    """Lee la cabecera PE de la DLL y devuelve 32, 64 o ``None``.

    Permite avisar de un desajuste de arquitectura sin depender de Windows,
    tambien util para diagnosticar desde otra maquina.
    """
    try:
        with open(ruta, "rb") as fh:
            if fh.read(2) != b"MZ":
                return None
            fh.seek(0x3C)
            offset = int.from_bytes(fh.read(4), "little")
            fh.seek(offset)
            if fh.read(4) != b"PE\0\0":
                return None
            maquina = int.from_bytes(fh.read(2), "little")
    except OSError:
        return None
    return {0x014C: 32, 0x8664: 64, 0xAA64: 64, 0x01C4: 32}.get(maquina)


def listar_exportaciones(ruta: str | os.PathLike[str]) -> list[str]:
    """Lee la tabla de exportaciones del PE sin cargar la DLL.

    Sirve para verificar en instalacion que la DLL entregada por el proveedor
    trae realmente las funciones que la aplicacion invoca.
    """
    try:
        datos = Path(ruta).read_bytes()
    except OSError as exc:
        raise DllNoEncontradaError(f"No se pudo leer {ruta}: {exc}") from exc

    if datos[:2] != b"MZ":
        raise DllNoEncontradaError(f"{ruta} no es un ejecutable de Windows")
    pe = int.from_bytes(datos[0x3C:0x40], "little")
    if datos[pe:pe + 4] != b"PE\0\0":
        raise DllNoEncontradaError(f"{ruta} no tiene cabecera PE valida")

    coff = pe + 4
    numero_secciones = int.from_bytes(datos[coff + 2:coff + 4], "little")
    tamano_opcional = int.from_bytes(datos[coff + 16:coff + 18], "little")
    opcional = coff + 20
    magia = int.from_bytes(datos[opcional:opcional + 2], "little")
    directorios = opcional + (96 if magia == 0x10B else 112)
    rva_export = int.from_bytes(datos[directorios:directorios + 4], "little")
    if not rva_export:
        return []

    secciones = opcional + tamano_opcional
    tabla = []
    for i in range(numero_secciones):
        base = secciones + i * 40
        virtual = int.from_bytes(datos[base + 12:base + 16], "little")
        tamano = int.from_bytes(datos[base + 8:base + 12], "little")
        crudo = int.from_bytes(datos[base + 20:base + 24], "little")
        tabla.append((virtual, tamano, crudo))

    def a_offset(rva: int) -> int | None:
        for virtual, tamano, crudo in tabla:
            if virtual <= rva < virtual + max(tamano, 1):
                return crudo + (rva - virtual)
        return None

    inicio = a_offset(rva_export)
    if inicio is None:
        return []
    cantidad = int.from_bytes(datos[inicio + 24:inicio + 28], "little")
    rva_nombres = int.from_bytes(datos[inicio + 32:inicio + 36], "little")
    offset_nombres = a_offset(rva_nombres)
    if offset_nombres is None:
        return []

    nombres: list[str] = []
    for i in range(cantidad):
        rva = int.from_bytes(datos[offset_nombres + i * 4:offset_nombres + i * 4 + 4], "little")
        pos = a_offset(rva)
        if pos is None:
            continue
        fin = datos.index(b"\0", pos)
        nombres.append(datos[pos:fin].decode("ascii", "replace"))
    return sorted(nombres)


class RtsLabelScaleDLL(BackendBalanza):
    """Backend real: llama a la DLL nativa de Rongta."""

    def __init__(
        self,
        dll_path: str | os.PathLike[str],
        convencion: str = "auto",
        baudrate: int = 0,
        directorios_dependencias: Sequence[str] | None = None,
    ) -> None:
        self.dll_path = Path(dll_path)
        self.convencion = convencion
        self.baudrate = baudrate
        self.directorios_dependencias = list(directorios_dependencias or ())
        self._dll: ctypes.CDLL | None = None
        self._alterno: ctypes.CDLL | None = None  # solo en modo "auto"
        self._convencion_activa = "stdcall" if convencion == "auto" else convencion
        self.descripcion = f"rtslabelscale.dll ({convencion})"

    @property
    def convencion_activa(self) -> str:
        """Convencion realmente en uso (relevante cuando se configuro 'auto')."""
        return self._convencion_activa

    # ------------------------------------------------------------------ #
    # Carga
    # ------------------------------------------------------------------ #

    @property
    def cargada(self) -> bool:
        return self._dll is not None

    def abrir(self) -> None:
        if self._dll is not None:
            return

        if not self.dll_path.is_file():
            raise DllNoEncontradaError(
                f"No se encontro la DLL en {self.dll_path}. Copie "
                "rtslabelscale.dll (y la carpeta RLS1000 que la acompana) a esa "
                "ruta, o corrija 'rongta.dll_path' en config.json."
            )

        bits_dll = arquitectura_pe(self.dll_path)
        bits_python = arquitectura_proceso()
        if bits_dll and bits_dll != bits_python:
            raise ArquitecturaIncorrectaError(
                f"{self.dll_path.name} es de {bits_dll} bits y este Python es de "
                f"{bits_python} bits. Instale Python de {bits_dll} bits "
                "(o empaquete el .exe con esa version); Windows no puede cargar "
                "una DLL de 32 bits en un proceso de 64 bits."
            )

        if os.name != "nt":
            raise DllNoEncontradaError(
                "rtslabelscale.dll solo puede cargarse en Windows. Use el "
                "backend simulado (--simular) para probar en otro sistema."
            )

        self._preparar_dependencias()

        try:
            if self.convencion == "cdecl":
                principal, alterno = ctypes.CDLL(str(self.dll_path)), None
            elif self.convencion == "stdcall":
                principal, alterno = ctypes.WinDLL(str(self.dll_path)), None
            else:  # auto: se resuelve en la primera llamada real
                principal = ctypes.WinDLL(str(self.dll_path))
                alterno = ctypes.CDLL(str(self.dll_path))
        except OSError as exc:
            pista = ""
            if getattr(exc, "winerror", None) == 193:
                pista = (
                    " [WinError 193] significa desajuste de arquitectura: "
                    "rtslabelscale.dll es de 32 bits y necesita un Python "
                    "(o un .exe de PyInstaller) tambien de 32 bits."
                )
            raise DllNoEncontradaError(
                f"Windows no pudo cargar {self.dll_path}: {exc}.{pista} Tambien "
                "puede deberse a una dependencia ausente (Visual C++ Runtime o "
                "la carpeta RLS1000)."
            ) from exc

        self._declarar_firmas(principal)
        if alterno is not None:
            self._declarar_firmas(alterno)
        self._dll = principal
        self._alterno = alterno

    def _preparar_dependencias(self) -> None:
        r"""Publica los directorios de la DLL para que encuentre sus dependencias.

        Sin esto ``LoadLibrary`` falla con "no se encuentra el modulo" aunque la
        ruta de la DLL principal sea correcta, porque las librerias auxiliares
        del fabricante viven en su propio directorio (``C:\ibalance\RLS1000``).
        """
        propio = str(self.dll_path.resolve().parent)
        candidatos = [propio, os.path.join(propio, "RLS1000")]
        candidatos.extend(self.directorios_dependencias)

        directorios: list[str] = []
        for ruta in candidatos:
            if ruta and os.path.isdir(ruta) and ruta not in directorios:
                directorios.append(ruta)

        for ruta in directorios:
            if hasattr(os, "add_dll_directory"):
                with suppress(OSError):
                    os.add_dll_directory(ruta)
        os.environ["PATH"] = os.pathsep.join(directorios + [os.environ.get("PATH", "")])

    def _invocar(self, nombre: str, *args: object) -> int:
        """Llama a una exportacion resolviendo la convencion en modo 'auto'.

        ctypes valida el puntero de pila tras cada llamada en x86: si la
        convencion no coincide lanza ``ValueError`` antes de que la memoria se
        corrompa, y ese es justo el momento de cambiar al otro manejador.
        """
        dll = self._exigir_dll()
        try:
            return int(getattr(dll, nombre)(*args))
        except ValueError:
            if self._alterno is None:
                raise
            alterno, self._alterno = self._alterno, None
            self._dll = alterno
            self._convencion_activa = "cdecl" if self._convencion_activa == "stdcall" else "stdcall"
            self.descripcion = f"rtslabelscale.dll ({self._convencion_activa}, autodetectada)"
            return int(getattr(alterno, nombre)(*args))

    @staticmethod
    def _declarar_firmas(dll: ctypes.CDLL) -> None:
        """Fija argtypes/restype: sin esto ctypes trunca punteros en 64 bits."""
        faltantes = [n for n in FUNCIONES if not hasattr(dll, n)]
        if faltantes:
            raise DllNoEncontradaError(
                "La DLL no exporta: " + ", ".join(faltantes)
                + ". Verifique que sea la rtslabelscale.dll de las RLS-1000."
            )

        dll.rtscaleConnect.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
        dll.rtscaleConnect.restype = ctypes.c_int

        dll.rtscaleDisConnect.argtypes = [ctypes.c_char_p]
        dll.rtscaleDisConnect.restype = ctypes.c_int

        dll.rtscaleDownLoadPLU.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        dll.rtscaleDownLoadPLU.restype = ctypes.c_int

        dll.rtscaleDownLoadHotkey.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        dll.rtscaleDownLoadHotkey.restype = ctypes.c_int

        dll.rtscaleClearPLUData.argtypes = [ctypes.c_char_p]
        dll.rtscaleClearPLUData.restype = ctypes.c_int

        if hasattr(dll, "rtscaleLoadIniFile"):
            dll.rtscaleLoadIniFile.argtypes = [ctypes.c_char_p]
            dll.rtscaleLoadIniFile.restype = ctypes.c_int
        if hasattr(dll, "rtscaleGetScaleType"):
            dll.rtscaleGetScaleType.argtypes = [
                ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int
            ]
            dll.rtscaleGetScaleType.restype = ctypes.c_int
        if hasattr(dll, "rtscaleDownLoadDeletePlu"):
            # Ojo: aqui el identificador de conexion es un entero, no una
            # cadena. Asi lo declara la aplicacion original.
            dll.rtscaleDownLoadDeletePlu.argtypes = [ctypes.c_int, ctypes.c_int]
            dll.rtscaleDownLoadDeletePlu.restype = ctypes.c_int

    def _exigir_dll(self) -> ctypes.CDLL:
        if self._dll is None:
            raise DllNoEncontradaError("La DLL no esta cargada; llame a abrir() primero")
        return self._dll

    @staticmethod
    def _texto(valor: str) -> bytes:
        return valor.encode(CODIFICACION, errors="replace")

    # ------------------------------------------------------------------ #
    # Operaciones
    # ------------------------------------------------------------------ #

    def conectar(self, ip: str, conn_id: str) -> int:
        return self._invocar(
            "rtscaleConnect", self._texto(ip), self.baudrate, self._texto(conn_id)
        )

    def desconectar(self, conn_id: str) -> int:
        if self._dll is None:
            return -1
        # Desconectar se llama desde bloques finally: aqui nada puede propagar,
        # o un fallo al cerrar taparia el error real del envio.
        try:
            return self._invocar("rtscaleDisConnect", self._texto(conn_id))
        except (OSError, ValueError):
            return -1

    def enviar_plu(self, conn_id: str, lote_json: str, registros: int) -> int:
        return self._invocar(
            "rtscaleDownLoadPLU",
            self._texto(conn_id),
            self._texto(lote_json),
            int(registros),
        )

    def enviar_hotkey(self, conn_id: str, pagina: Sequence[int], indice: int) -> int:
        arreglo = (ctypes.c_int * len(pagina))(*pagina)
        return self._invocar(
            "rtscaleDownLoadHotkey", self._texto(conn_id), arreglo, int(indice)
        )

    def limpiar_plu(self, conn_id: str) -> int:
        return self._invocar("rtscaleClearPLUData", self._texto(conn_id))

    def eliminar_plu(self, conn_id: str, lf_code: int) -> int:
        dll = self._exigir_dll()
        if not hasattr(dll, "rtscaleDownLoadDeletePlu"):
            raise NotImplementedError(
                "esta version de rtslabelscale.dll no exporta rtscaleDownLoadDeletePlu"
            )
        entero = int(conn_id) if str(conn_id).isdigit() else 0
        return self._invocar("rtscaleDownLoadDeletePlu", entero, int(lf_code))

    def cargar_ini(self, ruta_ini: str) -> int:
        """Carga el .ini de etiquetas del fabricante.

        La aplicacion original lo llamaba una sola vez al arrancar, antes de
        cualquier conexion; sin el, algunos modelos imprimen con la plantilla
        de etiqueta equivocada.
        """
        dll = self._exigir_dll()
        if not hasattr(dll, "rtscaleLoadIniFile"):
            raise NotImplementedError(
                "esta version de rtslabelscale.dll no exporta rtscaleLoadIniFile"
            )
        return self._invocar("rtscaleLoadIniFile", self._texto(ruta_ini))

    def tipo_balanza(self, conn_id: str, longitud: int = 512) -> str:
        """Consulta modelo y firmware; cadena vacia si la DLL no lo soporta."""
        dll = self._exigir_dll()
        if not hasattr(dll, "rtscaleGetScaleType"):
            return ""
        bufer = ctypes.create_string_buffer(longitud)
        try:
            self._invocar("rtscaleGetScaleType", self._texto(conn_id), bufer, longitud)
        except (OSError, ValueError):
            return ""
        return bufer.value.decode(CODIFICACION, errors="replace")

    def cerrar(self) -> None:
        # ctypes no ofrece FreeLibrary portable; se deja que el proceso lo libere.
        self._dll = None
        self._alterno = None


def diagnostico(dll_path: str | os.PathLike[str]) -> dict[str, object]:
    """Datos utiles para soporte: arquitectura, exportaciones y entorno."""
    ruta = Path(dll_path)
    info: dict[str, object] = {
        "ruta": str(ruta),
        "existe": ruta.is_file(),
        "tamano_bytes": ruta.stat().st_size if ruta.is_file() else 0,
        "arquitectura_dll": arquitectura_pe(ruta) if ruta.is_file() else None,
        "arquitectura_python": arquitectura_proceso(),
        "python": sys.version.split()[0],
        "sistema": os.name,
    }
    if ruta.is_file():
        try:
            exportaciones = listar_exportaciones(ruta)
            info["exportaciones"] = exportaciones
            info["faltantes"] = [f for f in FUNCIONES if f not in exportaciones]
        except DllNoEncontradaError as exc:
            info["exportaciones_error"] = str(exc)
    return info
