"""Interfaz de linea de comandos.

Todos los subcomandos comparten la misma configuracion y el mismo motor que la
interfaz grafica, de modo que lo que se prueba desde consola es exactamente lo
que hara la aplicacion en produccion (y lo que ejecute el Programador de tareas
de Windows).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, net, procesos
from .config import Config, ConfigError, config_por_defecto, ruta_config_por_defecto
from .engine import MotorSincronizacion, crear_backend
from .logging_setup import configurar, obtener
from .report import resumen_texto
from .rongta import construir_hotkeys, construir_lotes_plu, serializar_lote
from .rongta.dll import diagnostico
from .scheduler import Temporizador
from .sources import OrigenError, leer

log = obtener("cli")

OK, ERROR, USO = 0, 1, 2


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _cargar(args: argparse.Namespace, exigir: bool = True) -> Config | None:
    ruta = Path(args.config) if args.config else ruta_config_por_defecto()
    try:
        config = Config.cargar(ruta)
    except ConfigError as exc:
        if not exigir:
            return None
        print(f"ERROR: {exc}", file=sys.stderr)
        if not ruta.is_file():
            print(
                f"\nCree uno con:  ibalance init --config {ruta}",
                file=sys.stderr,
            )
        return None
    configurar(config.registro, config.dir_base(), consola=not args.silencioso)
    return config


def _motor(config: Config, args: argparse.Namespace) -> MotorSincronizacion:
    backend = crear_backend(config, simular=getattr(args, "simular", False))
    return MotorSincronizacion(config, backend=backend)


# --------------------------------------------------------------------------- #
# Subcomandos
# --------------------------------------------------------------------------- #


def cmd_init(args: argparse.Namespace) -> int:
    """Crea un config.json de ejemplo."""
    ruta = Path(args.config) if args.config else ruta_config_por_defecto()
    if ruta.exists() and not args.sobrescribir:
        print(f"Ya existe {ruta}. Use --sobrescribir para reemplazarlo.", file=sys.stderr)
        return ERROR
    config = config_por_defecto(args.balanzas)
    config.guardar(ruta)
    print(f"Configuracion creada en {ruta}")
    print("Edite 'origen.ruta', 'rongta.dll_path' y las IP de las balanzas.")
    return OK


def cmd_check(args: argparse.Namespace) -> int:
    """Valida configuracion, origen, DLL y red sin enviar nada."""
    config = _cargar(args)
    if config is None:
        return ERROR

    problemas = 0
    print(f"Configuracion: {config.ruta_archivo}  [OK]")

    try:
        lectura = leer(config.origen, str(config.resolver(config.origen.ruta)))
        print(
            f"Origen: {lectura.ruta}\n"
            f"  {lectura.total} productos validos de {lectura.lineas_totales} lineas, "
            f"{len(lectura.incidencias)} incidencias"
        )
        for incidencia in lectura.incidencias[:5]:
            print(f"    - {incidencia}")
        if len(lectura.incidencias) > 5:
            print(f"    ... y {len(lectura.incidencias) - 5} mas")
    except OrigenError as exc:
        print(f"Origen: ERROR - {exc}")
        problemas += 1

    info = diagnostico(config.resolver(config.rongta.dll_path))
    print(f"DLL: {info['ruta']}")
    if not info["existe"]:
        print("  ERROR - no se encontro el archivo")
        problemas += 1
    else:
        print(
            f"  {info['tamano_bytes']} bytes, arquitectura {info['arquitectura_dll']} bits; "
            f"Python de {info['arquitectura_python']} bits"
        )
        if info["arquitectura_dll"] and info["arquitectura_dll"] != info["arquitectura_python"]:
            print(
                "  ERROR - arquitecturas incompatibles: Windows no puede cargar una "
                "DLL de 32 bits en un proceso de 64 bits ([WinError 193])"
            )
            problemas += 1
        faltantes = info.get("faltantes") or []
        if faltantes:
            print(f"  ERROR - faltan exportaciones: {', '.join(faltantes)}")
            problemas += 1
        elif info.get("exportaciones"):
            print(f"  {len(info['exportaciones'])} exportaciones, todas las necesarias presentes")

    residentes = procesos.procesos_activos(config.sincronizacion.procesos_legacy)
    if residentes:
        print(
            "AVISO: la aplicacion antigua sigue en memoria y puede estar reteniendo "
            f"el puerto de las balanzas: {', '.join(residentes)}"
        )

    activas = config.balanzas_activas()
    print(f"Balanzas activas: {len(activas)}")
    for balanza in activas:
        if args.sin_red:
            print(f"  [{balanza.id}] {balanza.nombre} {balanza.ip}:{balanza.puerto}")
            continue
        responde = net.ping(balanza.ip, config.sincronizacion.timeout_ping_seg)
        abierto, motivo = net.puerto_abierto(balanza.ip, balanza.puerto, 2.0)
        estado = "OK" if abierto else ("ping OK" if responde else "SIN RESPUESTA")
        print(f"  [{balanza.id}] {balanza.nombre} {balanza.ip}:{balanza.puerto} - {estado}")
        if not abierto:
            print(f"        {motivo}")

    print("\nSin problemas bloqueantes." if not problemas else f"\n{problemas} problema(s).")
    return OK if not problemas else ERROR


def cmd_preview(args: argparse.Namespace) -> int:
    """Muestra lo que se enviaria, sin tocar la red."""
    config = _cargar(args)
    if config is None:
        return ERROR
    try:
        lectura = leer(config.origen, str(config.resolver(config.origen.ruta)))
    except OrigenError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return ERROR

    print(f"{lectura.total} productos leidos de {lectura.ruta}\n")
    for plu in lectura.plus[:args.limite]:
        print(
            f"  {plu.codigo}  {plu.nombre:<24} {plu.precio_formateado():>10}  "
            f"vida util {plu.vida_util_dias:>3} d"
        )
    if lectura.total > args.limite:
        print(f"  ... y {lectura.total - args.limite} mas")

    lotes = construir_lotes_plu(
        lectura.plus, config.rongta.tamano_lote_plu,
        config.rongta.plu_defaults, config.rongta.formato_legacy,
    )
    print(
        f"\n{len(lotes)} lote(s) de PLU, "
        f"{sum(len(j) for j, _ in lotes)} bytes en total"
    )
    if args.json and lectura.plus:
        print("\nPrimer producto tal como lo recibe la DLL:")
        print(serializar_lote(lectura.plus[:1], config.rongta.plu_defaults,
                              config.rongta.formato_legacy))

    paginas = construir_hotkeys(lectura.plus, config.rongta.hotkeys)
    if paginas:
        print(f"\n{len(paginas)} paginas de hotkeys de {len(paginas[0])} teclas:")
        for i, pagina in enumerate(paginas):
            usadas = [c for c in pagina if c]
            print(f"  pagina {i}: {len(usadas)} teclas asignadas -> {usadas[:10]}...")
    return OK


def cmd_sync(args: argparse.Namespace) -> int:
    """Ejecuta una sincronizacion."""
    config = _cargar(args)
    if config is None:
        return ERROR
    motor = _motor(config, args)
    resultado = motor.sincronizar(solo_ids=args.balanza or None, forzar=args.forzar)
    print()
    print(resumen_texto(resultado))
    if args.json_salida:
        Path(args.json_salida).write_text(
            json.dumps(resultado.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nDetalle guardado en {args.json_salida}")
    return OK if resultado.ok else ERROR


def cmd_clear(args: argparse.Namespace) -> int:
    """Borra el catalogo de una o varias balanzas."""
    config = _cargar(args)
    if config is None:
        return ERROR
    objetivos = [b for b in config.balanzas if b.id in set(args.balanza)]
    if not objetivos:
        print(f"Ninguna balanza con id {args.balanza} en la configuracion", file=sys.stderr)
        return USO
    if not args.si:
        nombres = ", ".join(f"{b.nombre} ({b.ip})" for b in objetivos)
        respuesta = input(
            f"Se borrara TODO el catalogo de: {nombres}\nEsta operacion no se puede "
            "deshacer; habra que volver a sincronizar. Escriba 'si' para continuar: "
        )
        if respuesta.strip().lower() not in ("si", "sí"):
            print("Cancelado.")
            return OK

    motor = _motor(config, args)
    fallos = 0
    for balanza in objetivos:
        resultado = motor.limpiar_balanza(balanza)
        print(f"[{'OK' if resultado.ok else 'ERROR'}] {resultado.nombre}: {resultado.mensaje}")
        fallos += 0 if resultado.ok else 1
    return OK if not fallos else ERROR


def cmd_daemon(args: argparse.Namespace) -> int:
    """Sincroniza periodicamente hasta que se interrumpa."""
    config = _cargar(args)
    if config is None:
        return ERROR
    motor = _motor(config, args)
    intervalo = args.intervalo or config.sincronizacion.intervalo_minutos

    def corrida() -> None:
        resultado = motor.sincronizar(forzar=args.forzar)
        print(resumen_texto(resultado))

    temporizador = Temporizador(intervalo, corrida)
    temporizador.iniciar(ejecutar_ahora=not args.esperar)
    print(f"Sincronizando cada {intervalo} minutos. Ctrl+C para salir.")
    try:
        while True:
            if not temporizador.activo:
                break
            temporizador._parar.wait(1)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
    finally:
        motor.cancelar()
        temporizador.detener(esperar=True)
    return OK


def cmd_dll(args: argparse.Namespace) -> int:
    """Diagnostico de la DLL nativa."""
    config = _cargar(args, exigir=False)
    ruta = Path(args.ruta) if args.ruta else (
        config.resolver(config.rongta.dll_path) if config else Path("rtslabelscale.dll")
    )
    info = diagnostico(ruta)
    exportaciones = info.pop("exportaciones", [])
    print(json.dumps(info, indent=2, ensure_ascii=False))
    if exportaciones:
        print(f"\n{len(exportaciones)} exportaciones:")
        for nombre in exportaciones:
            print(f"  {nombre}")
    return OK if info.get("existe") and not info.get("faltantes") else ERROR


def cmd_gui(args: argparse.Namespace) -> int:
    """Abre la interfaz grafica."""
    try:
        from .gui.app import ejecutar
    except ImportError as exc:  # tkinter ausente en algunas instalaciones minimas
        _avisar_sin_consola(
            "No se pudo abrir la interfaz grafica",
            f"{exc}\n\nInstale Python con soporte de tkinter o use los "
            "subcomandos de consola.",
        )
        return ERROR
    return ejecutar(Path(args.config) if args.config else None, simular=args.simular)


def _avisar_sin_consola(titulo: str, mensaje: str) -> None:
    """Muestra un error tambien cuando el .exe se compilo sin consola.

    Un ejecutable de ventana no tiene stdout: si algo falla al arrancar, sin
    esto el programa se cerraria sin decir nada.
    """
    print(f"ERROR: {titulo}: {mensaje}", file=sys.stderr)
    if getattr(sys, "frozen", False):
        try:
            from tkinter import messagebox

            messagebox.showerror(titulo, mensaje)
        except Exception:  # noqa: BLE001 - ya estamos informando de un fallo
            pass


# --------------------------------------------------------------------------- #
# Analizador de argumentos
# --------------------------------------------------------------------------- #


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibalance",
        description="Sincroniza productos con balanzas Rongta RLS-1000/1100.",
    )
    parser.add_argument("--version", action="version", version=f"ibalance {__version__}")
    parser.add_argument("-c", "--config", default=None, help="ruta al config.json")
    parser.add_argument("-q", "--silencioso", action="store_true",
                        help="no escribir el log en consola (solo en archivo)")

    # Las mismas opciones, aceptadas tambien despues del subcomando: escribir
    # "ibalance sync -q" es lo natural, y argparse solo las admite antes del
    # subcomando salvo que se hereden asi. SUPPRESS evita que el valor por
    # defecto del subcomando pise al que se paso antes.
    comunes = argparse.ArgumentParser(add_help=False)
    comunes.add_argument("-c", "--config", default=argparse.SUPPRESS,
                         help=argparse.SUPPRESS)
    comunes.add_argument("-q", "--silencioso", action="store_true",
                         default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("init", parents=[comunes], help="crear un config.json de ejemplo")
    p.add_argument("--balanzas", type=int, default=12, help="cuantas balanzas dejar preparadas")
    p.add_argument("--sobrescribir", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", parents=[comunes], help="validar configuracion, origen, DLL y red")
    p.add_argument("--sin-red", action="store_true", help="no hacer ping ni sondear puertos")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("preview", parents=[comunes], help="ver los productos y el payload sin enviar nada")
    p.add_argument("-n", "--limite", type=int, default=20)
    p.add_argument("--json", action="store_true", help="mostrar el JSON del primer producto")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("sync", parents=[comunes], help="sincronizar ahora")
    p.add_argument("-b", "--balanza", type=int, action="append",
                   help="sincronizar solo esta balanza (repetible)")
    p.add_argument("--forzar", action="store_true",
                   help="enviar aunque el origen no haya cambiado")
    p.add_argument("--simular", action="store_true",
                   help="no tocar las balanzas: usar el backend simulado")
    p.add_argument("--json-salida", help="guardar el resultado detallado en este archivo")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("clear", parents=[comunes], help="borrar el catalogo de una balanza")
    p.add_argument("-b", "--balanza", type=int, action="append", required=True)
    p.add_argument("--si", action="store_true", help="no pedir confirmacion")
    p.add_argument("--simular", action="store_true")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("daemon", parents=[comunes], help="sincronizar periodicamente")
    p.add_argument("--intervalo", type=int, help="minutos entre corridas")
    p.add_argument("--esperar", action="store_true",
                   help="no sincronizar al arrancar, esperar al primer intervalo")
    p.add_argument("--forzar", action="store_true")
    p.add_argument("--simular", action="store_true")
    p.set_defaults(func=cmd_daemon)

    p = sub.add_parser("dll", parents=[comunes], help="diagnostico de rtslabelscale.dll")
    p.add_argument("ruta", nargs="?", help="ruta a la DLL (por defecto, la del config)")
    p.set_defaults(func=cmd_dll)

    p = sub.add_parser("gui", parents=[comunes], help="abrir la interfaz grafica")
    p.add_argument("--simular", action="store_true")
    p.set_defaults(func=cmd_gui)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # Sin argumentos se abre la ventana: el caso normal es que alguien haga
    # doble clic en el ejecutable, y ahi un mensaje de uso de argparse no
    # ayuda a nadie. Los subcomandos y --help siguen funcionando igual.
    if not argv:
        argv = ["gui"]

    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
