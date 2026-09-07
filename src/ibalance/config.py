"""Carga, validacion y migracion del archivo de configuracion."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

VERSION_CONFIG = 2

# Nombre de archivo por defecto, junto al ejecutable o al paquete.
NOMBRE_CONFIG = "config.json"


class ConfigError(Exception):
    """La configuracion es invalida o no se pudo leer."""


# --------------------------------------------------------------------------- #
# Secciones
# --------------------------------------------------------------------------- #


@dataclass
class LayoutTxt:
    """Posiciones (inicio, fin) de cada campo dentro de una linea de ancho fijo.

    Los rangos son medio abiertos, igual que un ``slice`` de Python:
    ``[29, 36]`` toma los caracteres 29..35.
    """

    codigo: list[int] = field(default_factory=lambda: [0, 6])
    tipo: list[int] = field(default_factory=lambda: [6, 7])
    nombre: list[int] = field(default_factory=lambda: [7, 29])
    precio: list[int] = field(default_factory=lambda: [29, 36])
    vida_util_dias: list[int] = field(default_factory=lambda: [36, 39])
    departamento: list[int] = field(default_factory=list)

    def rangos(self) -> dict[str, tuple[int, int]]:
        salida: dict[str, tuple[int, int]] = {}
        for f in fields(self):
            valor = getattr(self, f.name)
            if valor:
                salida[f.name] = (int(valor[0]), int(valor[1]))
        return salida


@dataclass
class Origen:
    """De donde salen los productos."""

    tipo: str = "txt_ancho_fijo"  # txt_ancho_fijo | csv
    ruta: str = r"X:\cadtxt.txt"
    encoding: str = "latin-1"
    layout: LayoutTxt = field(default_factory=LayoutTxt)
    # Solo para tipo "csv"
    csv_delimitador: str = ";"
    csv_tiene_cabecera: bool = True
    csv_columnas: dict[str, str] = field(default_factory=dict)
    # Filtros
    solo_marca_tipo: str = ""       # p.ej. "P" para quedarse solo con pesables
    precio_minimo: int = 1          # descarta precios en cero (errores del ERP)
    nombre_ancho_max: int = 22
    quitar_acentos: bool = False
    precio_decimales: int = 2


@dataclass
class Balanza:
    """Una balanza de la red."""

    id: int
    ip: str = ""
    nombre: str = ""
    activa: bool = False
    conn_id: str = ""       # identificador que se le pasa a la DLL
    puerto: int = 4000      # puerto TCP de la balanza (sondeo previo)

    def __post_init__(self) -> None:
        if not self.nombre:
            self.nombre = f"Balanza {self.id}"
        if not self.conn_id:
            self.conn_id = str(self.id)

    @property
    def utilizable(self) -> bool:
        return bool(self.activa and self.ip.strip())


@dataclass
class Hotkeys:
    """Teclas de acceso directo de la balanza."""

    habilitado: bool = True
    teclas_por_pagina: int = 28
    paginas: int = 3
    # Lista explicita de codigos PLU en el orden en que deben aparecer.
    # Vacia => se toman los primeros N productos del origen, ordenados por codigo.
    codigos: list[str] = field(default_factory=list)


@dataclass
class Rongta:
    """Parametros de la DLL nativa."""

    dll_path: str = r"C:\ibalance\rtslabelscale.dll"
    # Directorios extra que se agregan al PATH antes de cargar la DLL; la
    # libreria del fabricante busca ahi sus dependencias.
    directorios_dependencias: list[str] = field(
        default_factory=lambda: [r"C:\ibalance", r"C:\ibalance\RLS1000"]
    )
    # "auto" prueba stdcall y cae a cdecl si ctypes detecta el desbalance de
    # pila. Fijelo a mano solo si ya sabe cual usa su version de la DLL.
    convencion_llamada: str = "auto"  # auto | stdcall | cdecl
    baudrate: int = 0                    # sin uso en TCP, la DLL lo exige igual
    codigo_exito: int = 0
    tamano_lote_plu: int = 200           # 0 => todo en un unico paquete
    limpiar_antes_de_enviar: bool = False
    enviar_hotkeys: bool = True
    hotkeys: Hotkeys = field(default_factory=Hotkeys)
    # .ini de etiquetas del fabricante; se carga una vez al abrir la DLL.
    ini_path: str = ""
    # Reproduce la cadena JSON de la app antigua (con las comas finales que no
    # son JSON valido). Solo si algun firmware rechaza el JSON correcto.
    formato_legacy: bool = False
    # Valores por defecto de los campos del PLU que el archivo de origen no
    # trae. Son numeros: asi los declara el DTO de la aplicacion original y asi
    # los emite en la cadena que recibe la DLL.
    plu_defaults: dict[str, Any] = field(
        default_factory=lambda: {
            "Deptment": 0,
            "LabelId": 0,
            "Tare": 0,
            "Tolerance": 0,
            "Rebate": 0,
            "Message1": 0,
            "Message2": 0,
            "PackageType": 0,
            "PackageWeight": 0,
            "QtyUnit": 0,
            "WeightUnit": 0,
        }
    )


@dataclass
class Sincronizacion:
    """Politica de la corrida."""

    intervalo_minutos: int = 60
    verificar_ping: bool = True
    timeout_ping_seg: int = 2
    verificar_puerto: bool = False
    timeout_conexion_seg: int = 15
    reintentos: int = 2
    espera_reintento_seg: float = 5.0
    # Las RLS-1000 aceptan UNA sola conexion a la vez, y la DLL guarda estado
    # global por conn_id: por defecto se trabaja balanza por balanza.
    balanzas_en_paralelo: int = 1
    pausa_tras_desconectar_seg: float = 1.0
    pausa_entre_lotes_seg: float = 0.0
    omitir_si_sin_cambios: bool = False
    # La app antigua (ClickOnce en C#) a veces queda residente y retiene el
    # puerto TCP de la balanza; con esto se cierra antes de sincronizar.
    cerrar_procesos_legacy: bool = False
    procesos_legacy: list[str] = field(default_factory=lambda: ["ibalance.exe"])


@dataclass
class Registro:
    """Logs y reportes."""

    directorio: str = "logs"
    nivel: str = "INFO"
    max_bytes: int = 2_000_000
    copias: int = 5
    guardar_reportes: bool = True
    guardar_payloads: bool = False  # util para depurar; genera archivos grandes


@dataclass
class Config:
    """Configuracion completa de la aplicacion."""

    version: int = VERSION_CONFIG
    origen: Origen = field(default_factory=Origen)
    balanzas: list[Balanza] = field(default_factory=list)
    rongta: Rongta = field(default_factory=Rongta)
    sincronizacion: Sincronizacion = field(default_factory=Sincronizacion)
    registro: Registro = field(default_factory=Registro)
    ruta_archivo: Path | None = field(default=None, compare=False, repr=False)

    # ---------------------------------------------------------------- #
    # Serializacion
    # ---------------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        datos = {
            "version": self.version,
            "origen": asdict(self.origen),
            "balanzas": [asdict(b) for b in self.balanzas],
            "rongta": asdict(self.rongta),
            "sincronizacion": asdict(self.sincronizacion),
            "registro": asdict(self.registro),
        }
        return datos

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> Config:
        datos = migrar(datos)
        cfg = cls()
        cfg.version = int(datos.get("version", VERSION_CONFIG))
        cfg.origen = _construir(Origen, datos.get("origen", {}), {"layout": LayoutTxt})
        cfg.rongta = _construir(Rongta, datos.get("rongta", {}), {"hotkeys": Hotkeys})
        cfg.sincronizacion = _construir(Sincronizacion, datos.get("sincronizacion", {}))
        cfg.registro = _construir(Registro, datos.get("registro", {}))
        cfg.balanzas = []
        for i, bruto in enumerate(datos.get("balanzas", []) or [], start=1):
            if not isinstance(bruto, dict):
                raise ConfigError(f"balanzas[{i - 1}] deberia ser un objeto JSON")
            bruto = dict(bruto)
            bruto.setdefault("id", i)
            cfg.balanzas.append(_construir(Balanza, bruto))
        return cfg

    # ---------------------------------------------------------------- #
    # Archivos
    # ---------------------------------------------------------------- #

    @classmethod
    def cargar(cls, ruta: str | os.PathLike[str]) -> Config:
        ruta = Path(ruta)
        if not ruta.is_file():
            raise ConfigError(f"No se encontro el archivo de configuracion: {ruta}")
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{ruta}: JSON invalido ({exc})") from exc
        if not isinstance(datos, dict):
            raise ConfigError(f"{ruta}: se esperaba un objeto JSON en la raiz")
        cfg = cls.from_dict(datos)
        cfg.ruta_archivo = ruta
        cfg.validar()
        return cfg

    def guardar(self, ruta: str | os.PathLike[str] | None = None) -> Path:
        destino = Path(ruta) if ruta is not None else self.ruta_archivo
        if destino is None:
            raise ConfigError("No hay ruta destino para guardar la configuracion")
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Escritura atomica: si el proceso muere a medias no se pierde el config.
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        temporal.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporal, destino)
        self.ruta_archivo = destino
        return destino

    # ---------------------------------------------------------------- #
    # Validacion
    # ---------------------------------------------------------------- #

    def validar(self) -> None:
        """Revisa la configuracion y lanza ``ConfigError`` con TODOS los fallos."""
        problemas: list[str] = []

        if self.origen.tipo not in ("txt_ancho_fijo", "csv"):
            problemas.append(
                f"origen.tipo '{self.origen.tipo}' no soportado "
                "(use 'txt_ancho_fijo' o 'csv')"
            )
        if not self.origen.ruta.strip():
            problemas.append("origen.ruta esta vacio")
        try:
            "".encode(self.origen.encoding)
        except LookupError:
            problemas.append(f"origen.encoding '{self.origen.encoding}' no existe")

        for nombre, (inicio, fin) in self.origen.layout.rangos().items():
            if inicio < 0 or fin <= inicio:
                problemas.append(
                    f"origen.layout.{nombre} = [{inicio}, {fin}] no es un rango valido"
                )

        if self.rongta.convencion_llamada not in ("auto", "stdcall", "cdecl"):
            problemas.append(
                f"rongta.convencion_llamada '{self.rongta.convencion_llamada}' "
                "debe ser 'auto', 'stdcall' o 'cdecl'"
            )
        if self.rongta.tamano_lote_plu < 0:
            problemas.append("rongta.tamano_lote_plu no puede ser negativo")
        if self.rongta.hotkeys.teclas_por_pagina <= 0:
            problemas.append("rongta.hotkeys.teclas_por_pagina debe ser mayor que 0")
        if self.rongta.hotkeys.paginas < 0:
            problemas.append("rongta.hotkeys.paginas no puede ser negativo")

        vistos: set[int] = set()
        conn_ids: set[str] = set()
        for balanza in self.balanzas:
            if balanza.id in vistos:
                problemas.append(f"balanza id={balanza.id} duplicada")
            vistos.add(balanza.id)
            if balanza.conn_id in conn_ids:
                problemas.append(
                    f"balanza id={balanza.id}: conn_id '{balanza.conn_id}' duplicado "
                    "(la DLL identifica cada conexion por este valor)"
                )
            conn_ids.add(balanza.conn_id)
            if balanza.activa and not balanza.ip.strip():
                problemas.append(f"balanza id={balanza.id} esta activa pero sin IP")
            if not 0 < balanza.puerto < 65536:
                problemas.append(f"balanza id={balanza.id}: puerto {balanza.puerto} invalido")

        if self.sincronizacion.balanzas_en_paralelo < 1:
            problemas.append("sincronizacion.balanzas_en_paralelo debe ser >= 1")
        if self.sincronizacion.reintentos < 0:
            problemas.append("sincronizacion.reintentos no puede ser negativo")
        if self.sincronizacion.intervalo_minutos < 1:
            problemas.append("sincronizacion.intervalo_minutos debe ser >= 1")

        if problemas:
            raise ConfigError(
                "Configuracion invalida:\n  - " + "\n  - ".join(problemas)
            )

    # ---------------------------------------------------------------- #
    # Utilidades
    # ---------------------------------------------------------------- #

    def balanzas_activas(self) -> list[Balanza]:
        return [b for b in self.balanzas if b.utilizable]

    def balanza_por_id(self, balanza_id: int) -> Balanza | None:
        for balanza in self.balanzas:
            if balanza.id == balanza_id:
                return balanza
        return None

    def dir_base(self) -> Path:
        """Directorio contra el que se resuelven las rutas relativas."""
        if self.ruta_archivo is not None:
            return self.ruta_archivo.resolve().parent
        return Path.cwd()

    def resolver(self, ruta: str) -> Path:
        candidata = Path(ruta)
        if candidata.is_absolute():
            return candidata
        return self.dir_base() / candidata


# --------------------------------------------------------------------------- #
# Construccion y migracion
# --------------------------------------------------------------------------- #


def _construir(clase: type, datos: dict[str, Any], anidados: dict[str, type] | None = None):
    """Instancia un dataclass ignorando claves desconocidas del JSON.

    Las claves que sobran no son un error: permiten que un config escrito por
    una version mas nueva siga abriendo en una version vieja.
    """
    if not isinstance(datos, dict):
        raise ConfigError(f"Se esperaba un objeto JSON para {clase.__name__}")
    anidados = anidados or {}
    validos = {f.name for f in fields(clase)}
    kwargs: dict[str, Any] = {}
    for clave, valor in datos.items():
        if clave not in validos:
            continue
        if clave in anidados:
            sub = anidados[clave]
            kwargs[clave] = _construir(sub, valor) if isinstance(valor, dict) else sub()
        else:
            kwargs[clave] = valor
    try:
        return clase(**kwargs)
    except TypeError as exc:
        raise ConfigError(f"{clase.__name__}: {exc}") from exc


def migrar(datos: dict[str, Any]) -> dict[str, Any]:
    """Traduce configuraciones de ibalance v1/v2 al esquema actual.

    El config viejo tenia ``dll_path`` en la raiz y no distinguia origen por
    tipo. Se respeta lo que ya exista para no pisar ajustes del usuario.
    """
    if int(datos.get("version", 0)) >= VERSION_CONFIG:
        return datos

    datos = json.loads(json.dumps(datos))  # copia profunda barata
    rongta = datos.setdefault("rongta", {})
    if "dll_path" in datos and "dll_path" not in rongta:
        rongta["dll_path"] = datos.pop("dll_path")

    origen = datos.setdefault("origen", {})
    tipo_viejo = str(origen.get("tipo", "")).upper()
    if tipo_viejo in ("TXT", ""):
        origen["tipo"] = "txt_ancho_fijo"
    elif tipo_viejo == "CSV":
        origen["tipo"] = "csv"

    datos["version"] = VERSION_CONFIG
    return datos


def config_por_defecto(balanzas: int = 12) -> Config:
    """Configuracion inicial con N balanzas desactivadas y listas para editar."""
    cfg = Config()
    cfg.balanzas = [Balanza(id=i) for i in range(1, balanzas + 1)]
    return cfg


#: Sitios donde suele acabar la DLL del fabricante, por orden de preferencia.
#: El directorio propio va antes que RLS1000 a proposito: son dos archivos
#: distintos con el mismo nombre y el de RLS1000 exporta menos funciones.
CANDIDATOS_DLL = (
    r"C:\ibalance\rtslabelscale.dll",
    r"C:\ibalance\RLS1000\rtslabelscale.dll",
    r"C:\Program Files (x86)\ibalance\rtslabelscale.dll",
)


def autodetectar_dll(dir_base: Path | None = None) -> str:
    """Busca ``rtslabelscale.dll`` sin obligar al operador a localizarla.

    Mira primero junto al ejecutable, que es donde queda si se instalo todo en
    la misma carpeta, y despues en las rutas habituales del fabricante.
    """
    candidatos: list[Path] = []
    if dir_base is not None:
        candidatos += [dir_base / "rtslabelscale.dll",
                       dir_base / "RLS1000" / "rtslabelscale.dll"]
    candidatos += [Path(c) for c in CANDIDATOS_DLL]
    for ruta in candidatos:
        try:
            if ruta.is_file():
                return str(ruta)
        except OSError:
            continue
    return ""


def preparar_primer_arranque(ruta: Path) -> tuple[Config, bool]:
    """Devuelve la configuracion y si acaba de crearse.

    La primera vez que se ejecuta la aplicacion no hay ``config.json``: en vez
    de fallar, se escribe uno con valores por defecto y la DLL ya localizada,
    para que el operador solo tenga que indicar el archivo de productos y las
    IP de sus balanzas.
    """
    if ruta.is_file():
        return Config.cargar(ruta), False

    cfg = config_por_defecto()
    cfg.ruta_archivo = ruta
    detectada = autodetectar_dll(ruta.parent)
    if detectada:
        cfg.rongta.dll_path = detectada
    with suppress(OSError):
        cfg.guardar(ruta)
    return cfg, True


def ruta_config_por_defecto(dir_base: Path | None = None) -> Path:
    """Ubicacion esperada de ``config.json`` (junto al .exe o al proyecto)."""
    import sys

    if dir_base is not None:
        return dir_base / NOMBRE_CONFIG
    if getattr(sys, "frozen", False):  # empaquetado con PyInstaller
        return Path(sys.executable).resolve().parent / NOMBRE_CONFIG
    return Path.cwd() / NOMBRE_CONFIG


assert is_dataclass(Config)
