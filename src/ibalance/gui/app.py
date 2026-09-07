"""Ventana principal de ibalance.

Dos decisiones estructurales explican el resto del archivo:

**Hilos.** tkinter solo puede tocarse desde el hilo que creo la ventana. La
sincronizacion corre aparte para que la interfaz no se congele, asi que todo lo
que vuelve de ese hilo —lineas de log, cambios de estado, el resultado final—
pasa por una cola que el hilo de la interfaz vacia con ``after``. Escribir en
los widgets desde el hilo de trabajo funciona casi siempre y cuelga la
aplicacion de vez en cuando, que es peor que fallar siempre.

**Aspecto.** No hay pestañas: una barra lateral cambia la vista y el contenido
se apila con ``grid`` en la misma celda. Los colores viven en ``tema.py`` y las
piezas visuales en ``widgets.py``, de modo que cambiar de claro a oscuro es
recorrer una lista de repintados y no tocar esta ventana.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from ..config import Balanza, Config, ConfigError, config_por_defecto, ruta_config_por_defecto
from ..engine import MotorSincronizacion, crear_backend
from ..logging_setup import ManejadorCallback, configurar, obtener
from ..models import ResultadoSincronizacion
from ..report import resumen_texto
from ..scheduler import Temporizador
from ..sources import OrigenError, leer
from .tema import TEMAS, Fuentes, Tema, aplicar
from .widgets import Insignia, Metrica, PanelDesplazable, Punto, Tarjeta, campo, separador

log = obtener("gui")

#: Estado de cada balanza: (rotulo, atributo de color del tema).
ESTADOS: dict[str, tuple[str, str]] = {
    "inactiva": ("Inactiva", "neutro"),
    "espera": ("En espera", "neutro"),
    "verificando": ("Comprobando red", "acento"),
    "conectando": ("Conectando", "acento"),
    "enviando": ("Enviando", "acento"),
    "reintentando": ("Reintentando", "aviso"),
    "ok": ("Al dia", "exito"),
    "error": ("Con error", "error"),
    "omitida": ("Sin cambios", "neutro"),
}

VISTAS = (
    ("resumen", "Resumen"),
    ("balanzas", "Balanzas"),
    ("origen", "Origen"),
    ("ajustes", "Ajustes"),
)


def _ruta_corta(ruta: Path, segmentos: int = 3) -> str:
    """Ultimos tramos de una ruta, para que no desborde la ventana."""
    partes = ruta.parts
    if len(partes) <= segmentos:
        return str(ruta)
    return "…" + str(Path(*partes[-segmentos:]))


class Aplicacion:
    """Ventana principal."""

    def __init__(self, ruta_config: Path | None = None, simular: bool = False) -> None:
        self.ruta_config = ruta_config or ruta_config_por_defecto()
        self.simular = simular
        self.config = self._cargar_config()
        configurar(self.config.registro, self.config.dir_base(), consola=False)

        self.cola: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.motor = MotorSincronizacion(
            self.config,
            backend=crear_backend(self.config, simular=simular),
            progreso=self._progreso_desde_hilo,
        )
        self.temporizador = Temporizador(
            self.config.sincronizacion.intervalo_minutos, self._sincronizar_en_hilo
        )
        self.hilo: threading.Thread | None = None
        self.filas: dict[int, dict[str, Any]] = {}
        self.vistas: dict[str, ttk.Frame] = {}
        self.botones_nav: dict[str, ttk.Button] = {}
        self._repintables: list[Any] = []
        self._vista_actual = "resumen"
        self._marcador = True

        self.raiz = tk.Tk()
        self.raiz.title("ibalance" + ("  ·  simulacion" if simular else ""))
        self.raiz.geometry("1060x700")
        self.raiz.minsize(940, 600)

        self.fuentes = Fuentes()
        self.tema: Tema = TEMAS["claro"]
        self.estilo = ttk.Style(self.raiz)
        aplicar(self.estilo, self.tema, self.fuentes)
        self.raiz.configure(background=self.tema.fondo)

        self._construir()
        self._enganchar_log()
        self._volcar_config_a_ui()
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.raiz.after(120, self._vaciar_cola)

    # ------------------------------------------------------------------ #
    # Configuracion
    # ------------------------------------------------------------------ #

    def _cargar_config(self) -> Config:
        try:
            return Config.cargar(self.ruta_config)
        except ConfigError as exc:
            if self.ruta_config.exists():
                messagebox.showerror(
                    "Configuracion invalida",
                    f"{exc}\n\nSe abrira con valores por defecto; revise el archivo "
                    "antes de sincronizar.",
                )
            config = config_por_defecto()
            config.ruta_archivo = self.ruta_config
            return config

    # ------------------------------------------------------------------ #
    # Estructura
    # ------------------------------------------------------------------ #

    def _construir(self) -> None:
        self.raiz.columnconfigure(0, weight=1)
        self.raiz.rowconfigure(1, weight=1)

        self._cabecera()

        cuerpo = ttk.Frame(self.raiz)
        cuerpo.grid(row=1, column=0, sticky="nsew")
        cuerpo.columnconfigure(1, weight=1)
        cuerpo.rowconfigure(0, weight=1)

        self._lateral(cuerpo)

        self.contenido = ttk.Frame(cuerpo)
        self.contenido.grid(row=0, column=1, sticky="nsew")
        self.contenido.columnconfigure(0, weight=1)
        self.contenido.rowconfigure(0, weight=1)

        self.vistas["resumen"] = self._vista_resumen()
        self.vistas["balanzas"] = self._vista_balanzas()
        self.vistas["origen"] = self._vista_origen()
        self.vistas["ajustes"] = self._vista_ajustes()
        for vista in self.vistas.values():
            vista.grid(row=0, column=0, sticky="nsew")

        self._pie()
        self._mostrar("resumen")

    def _cabecera(self) -> None:
        barra = ttk.Frame(self.raiz, style="Barra.TFrame", padding=(20, 14))
        barra.grid(row=0, column=0, sticky="ew")
        barra.columnconfigure(1, weight=1)

        marca = ttk.Frame(barra, style="Barra.TFrame")
        marca.grid(row=0, column=0, sticky="w")
        ttk.Label(marca, text="ibalance", style="Titulo.TLabel").pack(side="left")
        subtitulo = "modo simulacion" if self.simular else "balanzas Rongta RLS-1000"
        ttk.Label(marca, text=subtitulo, style="TenueSup.TLabel").pack(
            side="left", padx=(10, 0), pady=(5, 0)
        )

        acciones = ttk.Frame(barra, style="Barra.TFrame")
        acciones.grid(row=0, column=2, sticky="e")

        self.btn_tema = ttk.Button(acciones, text="Oscuro", style="Icono.TButton",
                                   command=self._alternar_tema, width=7)
        self.btn_tema.pack(side="left", padx=(0, 8))

        self.btn_timer = ttk.Button(acciones, text="Automatico", style="Secundario.TButton",
                                    command=self._alternar_temporizador)
        self.btn_timer.pack(side="left", padx=(0, 8))

        self.btn_detener = ttk.Button(acciones, text="Detener", style="Secundario.TButton",
                                      command=self._detener, state="disabled")
        self.btn_detener.pack(side="left", padx=(0, 8))

        self.btn_sync = ttk.Button(acciones, text="Sincronizar", style="Primario.TButton",
                                   command=self._sincronizar)
        self.btn_sync.pack(side="left")

        linea = separador(self.raiz)
        linea.grid(row=0, column=0, sticky="sew")

    def _lateral(self, padre: ttk.Frame) -> None:
        lateral = ttk.Frame(padre, style="Lateral.TFrame", padding=(12, 18, 12, 18))
        lateral.grid(row=0, column=0, sticky="nsw")

        for clave, rotulo in VISTAS:
            boton = ttk.Button(lateral, text=rotulo, style="Nav.TButton", width=15,
                               command=lambda c=clave: self._mostrar(c))
            boton.pack(fill="x", pady=1)
            self.botones_nav[clave] = boton

        relleno = ttk.Frame(lateral, style="Lateral.TFrame")
        relleno.pack(fill="both", expand=True)

        self.lbl_backend = ttk.Label(lateral, text="", style="Tenue.TLabel",
                                     wraplength=150, justify="left")
        self.lbl_backend.pack(anchor="w", pady=(12, 0))

        separador(padre, horizontal=False).grid(row=0, column=0, sticky="nse")

    def _pie(self) -> None:
        separador(self.raiz).grid(row=2, column=0, sticky="ew")
        pie = ttk.Frame(self.raiz, style="Barra.TFrame", padding=(20, 8))
        pie.grid(row=3, column=0, sticky="ew")
        pie.columnconfigure(1, weight=1)

        self.punto_global = Punto(pie, self.tema, 8)
        self.punto_global.grid(row=0, column=0, padx=(0, 8))
        self._repintables.append(self.punto_global)

        self.estado_var = tk.StringVar(value="Listo")
        ttk.Label(pie, textvariable=self.estado_var, style="TenueSup.TLabel").grid(
            row=0, column=1, sticky="w"
        )

        self.timer_var = tk.StringVar(value="")
        ttk.Label(pie, textvariable=self.timer_var, style="TenueSup.TLabel").grid(
            row=0, column=2, sticky="e"
        )

    def _mostrar(self, clave: str) -> None:
        self._vista_actual = clave
        self.vistas[clave].tkraise()
        for nombre, boton in self.botones_nav.items():
            boton.configure(style="NavActiva.TButton" if nombre == clave else "Nav.TButton")

    # ------------------------------------------------------------------ #
    # Vista: resumen
    # ------------------------------------------------------------------ #

    def _vista_resumen(self) -> ttk.Frame:
        vista = ttk.Frame(self.contenido, padding=(20, 18))
        vista.columnconfigure(0, weight=1)
        vista.rowconfigure(2, weight=1)

        tarjeta = Tarjeta(vista, self.tema, relleno=18)
        tarjeta.grid(row=0, column=0, sticky="ew")
        self._repintables.append(tarjeta)
        for i in range(4):
            tarjeta.columnconfigure(i, weight=1, uniform="metricas")

        self.met_productos = Metrica(tarjeta, "productos en el origen")
        self.met_balanzas = Metrica(tarjeta, "balanzas activas")
        self.met_ok = Metrica(tarjeta, "al dia")
        self.met_ultima = Metrica(tarjeta, "ultima sincronizacion")
        for i, metrica in enumerate(
            (self.met_productos, self.met_balanzas, self.met_ok, self.met_ultima)
        ):
            metrica.grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else 12, 0))

        self.progreso = ttk.Progressbar(vista, style="Fina.Horizontal.TProgressbar",
                                        mode="indeterminate")
        self.progreso.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        self.progreso.grid_remove()

        registro = Tarjeta(vista, self.tema, relleno=0)
        registro.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        registro.columnconfigure(0, weight=1)
        registro.rowconfigure(1, weight=1)
        self._repintables.append(registro)

        encabezado = ttk.Frame(registro, style="Superficie.TFrame", padding=(16, 12))
        encabezado.grid(row=0, column=0, sticky="ew")
        encabezado.columnconfigure(1, weight=1)
        ttk.Label(encabezado, text="Actividad", style="SeccionSup.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(encabezado, text="Limpiar", style="Sutil.TButton",
                   command=self._limpiar_log).grid(row=0, column=2, sticky="e")

        marco = ttk.Frame(registro, style="Superficie.TFrame")
        marco.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(0, weight=1)

        self.texto = tk.Text(
            marco, wrap="word", font=self.fuentes.mono, state="disabled",
            background=self.tema.superficie_alt, foreground=self.tema.texto,
            insertbackground=self.tema.texto, relief="flat", bd=0,
            padx=14, pady=12, spacing1=1, spacing3=1, height=10,
            highlightthickness=0,
        )
        barra = ttk.Scrollbar(marco, orient="vertical", style="Fina.Vertical.TScrollbar",
                              command=self.texto.yview)
        self.texto.configure(yscrollcommand=barra.set)
        self.texto.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        self._aplicar_tema_al_log()
        self._mostrar_marcador()

        return vista

    # ------------------------------------------------------------------ #
    # Vista: balanzas
    # ------------------------------------------------------------------ #

    def _vista_balanzas(self) -> ttk.Frame:
        vista = ttk.Frame(self.contenido, padding=(20, 18))
        vista.columnconfigure(0, weight=1)
        vista.rowconfigure(1, weight=1)

        encabezado = ttk.Frame(vista)
        encabezado.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        encabezado.columnconfigure(1, weight=1)
        ttk.Label(encabezado, text="Balanzas", style="Seccion.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(encabezado, text="Guardar", style="Secundario.TButton",
                   command=self._guardar_balanzas).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(encabezado, text="Probar todas", style="Secundario.TButton",
                   command=self._probar_todas).grid(row=0, column=3, padx=(8, 0))

        panel = PanelDesplazable(vista, self.tema)
        panel.grid(row=1, column=0, sticky="nsew")
        self._repintables.append(panel)

        for balanza in self.config.balanzas:
            self._tarjeta_balanza(panel.interior, balanza)

        return vista

    def _tarjeta_balanza(self, padre: ttk.Frame, balanza: Balanza) -> None:
        """Tarjeta de una balanza, en dos filas.

        Identidad y acciones arriba, campos abajo. En una sola fila los tres
        bloques no caben en la anchura minima de la ventana y las acciones se
        recortaban; separados, cada fila necesita la mitad de ancho y la
        tarjeta aguanta cualquier tamaño.
        """
        tarjeta = Tarjeta(padre, self.tema, relleno=14)
        tarjeta.pack(fill="x", pady=(0, 8), padx=(0, 4))
        # El hueco elastico va en una columna vacia: grid encoge primero las
        # columnas con peso, y si ese peso lo llevara un bloque con contenido,
        # ese contenido se recortaria al estrechar la ventana.
        tarjeta.columnconfigure(2, weight=1)
        self._repintables.append(tarjeta)

        punto = Punto(tarjeta, self.tema)
        punto.grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(4, 0))
        self._repintables.append(punto)

        identidad = ttk.Frame(tarjeta, style="Superficie.TFrame")
        identidad.grid(row=0, column=1, sticky="w")
        ttk.Label(identidad, text=balanza.nombre, style="Fuerte.TLabel").pack(anchor="w")
        estado = ttk.Label(identidad, text="En espera", style="Neutro.TLabel")
        estado.pack(anchor="w", pady=(1, 0))

        acciones = ttk.Frame(tarjeta, style="Superficie.TFrame")
        acciones.grid(row=0, column=3, sticky="e")
        # Ancho explicito: sin el, clam reserva mucho mas del que ocupa el
        # texto y los tres botones quedan desperdigados.
        ttk.Button(acciones, text="Probar", style="Sutil.TButton", width=7,
                   command=lambda b=balanza.id: self._probar(b)).pack(side="left", padx=(0, 4))
        ttk.Button(acciones, text="Enviar", style="Sutil.TButton", width=7,
                   command=lambda b=balanza.id: self._sincronizar([b])).pack(side="left", padx=(0, 4))
        ttk.Button(acciones, text="Vaciar", style="Peligro.TButton", width=7,
                   command=lambda b=balanza.id: self._limpiar_balanza(b)).pack(side="left")

        formulario = ttk.Frame(tarjeta, style="Superficie.TFrame")
        formulario.grid(row=1, column=1, columnspan=3, sticky="w", pady=(12, 0))

        activa = tk.BooleanVar(value=balanza.activa)
        # pady baja la casilla hasta la linea de las cajas de texto, que van
        # bajo su rotulo; centrada quedaria flotando entre rotulo y caja.
        ttk.Checkbutton(formulario, text="Activa", variable=activa,
                        command=self._refrescar_metricas).pack(
            side="left", padx=(0, 20), pady=(14, 0), anchor="n")

        ip = tk.StringVar(value=balanza.ip)
        campo(formulario, "direccion ip", ip, ancho=16).pack(side="left", padx=(0, 16))

        puerto = tk.StringVar(value=str(balanza.puerto))
        campo(formulario, "puerto", puerto, ancho=8).pack(side="left")

        self.filas[balanza.id] = {
            "activa": activa, "ip": ip, "puerto": puerto,
            "estado": estado, "punto": punto, "tarjeta": tarjeta,
        }

    # ------------------------------------------------------------------ #
    # Vista: origen
    # ------------------------------------------------------------------ #

    def _vista_origen(self) -> ttk.Frame:
        vista = ttk.Frame(self.contenido, padding=(20, 18))
        vista.columnconfigure(0, weight=1)
        vista.rowconfigure(1, weight=1)

        tarjeta = Tarjeta(vista, self.tema, relleno=18)
        tarjeta.grid(row=0, column=0, sticky="ew")
        tarjeta.columnconfigure(0, weight=1)
        self._repintables.append(tarjeta)

        ttk.Label(tarjeta, text="Archivo de productos", style="SeccionSup.TLabel").grid(
            row=0, column=0, sticky="w", columnspan=3
        )

        self.var_ruta = tk.StringVar()
        fila = ttk.Frame(tarjeta, style="Superficie.TFrame")
        fila.grid(row=1, column=0, sticky="ew", columnspan=3, pady=(12, 0))
        fila.columnconfigure(0, weight=1)
        ttk.Entry(fila, textvariable=self.var_ruta).grid(row=0, column=0, sticky="ew")
        ttk.Button(fila, text="Examinar", style="Secundario.TButton",
                   command=self._elegir_origen).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(fila, text="Analizar", style="Primario.TButton",
                   command=self._analizar_origen).grid(row=0, column=2, padx=(8, 0))

        self.lbl_origen = ttk.Label(tarjeta, text="Pulse «Analizar» para leer el archivo.",
                                    style="TenueSup.TLabel")
        self.lbl_origen.grid(row=2, column=0, sticky="w", columnspan=3, pady=(12, 0))

        previa = Tarjeta(vista, self.tema, relleno=0)
        previa.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        previa.columnconfigure(0, weight=1)
        previa.rowconfigure(1, weight=1)
        self._repintables.append(previa)

        encabezado = ttk.Frame(previa, style="Superficie.TFrame", padding=(16, 12))
        encabezado.grid(row=0, column=0, sticky="ew")
        ttk.Label(encabezado, text="Vista previa", style="SeccionSup.TLabel").pack(side="left")
        self.insignia_previa = Insignia(encabezado, self.tema, self.fuentes, "sin datos")
        self.insignia_previa.pack(side="left", padx=(10, 0))
        self._repintables.append(self.insignia_previa)

        marco = ttk.Frame(previa, style="Superficie.TFrame")
        marco.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(0, weight=1)

        self.tabla = tk.Text(
            marco, wrap="none", font=self.fuentes.mono, state="disabled",
            background=self.tema.superficie_alt, foreground=self.tema.texto,
            relief="flat", bd=0, padx=14, pady=12, height=12, highlightthickness=0,
        )
        barra = ttk.Scrollbar(marco, orient="vertical", style="Fina.Vertical.TScrollbar",
                              command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        self.tabla.tag_configure("cabecera", foreground=self.tema.texto_tenue)
        self.tabla.tag_configure("incidencia", foreground=self.tema.aviso)

        return vista

    # ------------------------------------------------------------------ #
    # Vista: ajustes
    # ------------------------------------------------------------------ #

    def _vista_ajustes(self) -> ttk.Frame:
        vista = ttk.Frame(self.contenido)
        vista.columnconfigure(0, weight=1)
        vista.rowconfigure(0, weight=1)

        panel = PanelDesplazable(vista, self.tema)
        panel.grid(row=0, column=0, sticky="nsew", padx=20, pady=18)
        self._repintables.append(panel)
        interior = panel.interior
        interior.columnconfigure(0, weight=1)

        # --- libreria ---
        dll = Tarjeta(interior, self.tema, relleno=18)
        dll.pack(fill="x", pady=(0, 12), padx=(0, 4))
        dll.columnconfigure(0, weight=1)
        self._repintables.append(dll)
        ttk.Label(dll, text="Libreria del fabricante", style="SeccionSup.TLabel").grid(
            row=0, column=0, sticky="w", columnspan=2
        )
        self.var_dll = tk.StringVar()
        fila = ttk.Frame(dll, style="Superficie.TFrame")
        fila.grid(row=1, column=0, sticky="ew", columnspan=2, pady=(12, 0))
        fila.columnconfigure(0, weight=1)
        ttk.Entry(fila, textvariable=self.var_dll).grid(row=0, column=0, sticky="ew")
        ttk.Button(fila, text="Examinar", style="Secundario.TButton",
                   command=self._elegir_dll).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            dll,
            text="rtslabelscale.dll es de 32 bits: la aplicacion debe ejecutarse "
                 "con Python o un .exe de 32 bits.",
            style="TenueSup.TLabel", wraplength=560, justify="left",
        ).grid(row=2, column=0, sticky="w", columnspan=2, pady=(10, 0))

        # --- sincronizacion ---
        sinc = Tarjeta(interior, self.tema, relleno=18)
        sinc.pack(fill="x", pady=(0, 12), padx=(0, 4))
        self._repintables.append(sinc)
        ttk.Label(sinc, text="Sincronizacion", style="SeccionSup.TLabel").pack(anchor="w")

        rejilla = ttk.Frame(sinc, style="Superficie.TFrame")
        rejilla.pack(fill="x", pady=(12, 0))
        self.var_intervalo = tk.StringVar()
        self.var_ping = tk.StringVar()
        self.var_reintentos = tk.StringVar()
        self.var_lote = tk.StringVar()
        for i, (rotulo, var) in enumerate((
            ("intervalo (min)", self.var_intervalo),
            ("timeout ping (s)", self.var_ping),
            ("reintentos", self.var_reintentos),
            ("productos por lote", self.var_lote),
        )):
            campo(rejilla, rotulo, var, ancho=10).grid(row=0, column=i, sticky="w",
                                                       padx=(0 if i == 0 else 18, 0))

        self.var_omitir = tk.BooleanVar()
        self.var_legacy = tk.BooleanVar()
        self.var_limpiar = tk.BooleanVar()
        for texto, var in (
            ("Omitir las balanzas cuyo catalogo ya esta al dia", self.var_omitir),
            ("Vaciar el catalogo antes de cada envio", self.var_limpiar),
            ("Cerrar la aplicacion antigua (ibalance.exe) antes de sincronizar",
             self.var_legacy),
        ):
            ttk.Checkbutton(sinc, text=texto, variable=var).pack(anchor="w", pady=(10, 0))

        # --- guardar ---
        acciones = ttk.Frame(interior)
        acciones.pack(fill="x", padx=(0, 4))
        ttk.Button(acciones, text="Guardar configuracion", style="Primario.TButton",
                   command=self._guardar_config).pack(side="right")
        self.lbl_config = ttk.Label(acciones, text="", style="Tenue.TLabel",
                                    wraplength=460, justify="left")
        self.lbl_config.pack(side="left", anchor="w")

        return vista

    # ------------------------------------------------------------------ #
    # Tema
    # ------------------------------------------------------------------ #

    def _alternar_tema(self) -> None:
        self.tema = TEMAS["oscuro" if self.tema.nombre == "claro" else "claro"]
        aplicar(self.estilo, self.tema, self.fuentes)
        self.raiz.configure(background=self.tema.fondo)
        self.btn_tema.configure(text="Claro" if self.tema.oscuro else "Oscuro")
        for pieza in self._repintables:
            with suppress(tk.TclError):
                pieza.repintar(self.tema)
        self._aplicar_tema_al_log()
        for datos in self.filas.values():
            self._repintar_estado(datos)

    def _aplicar_tema_al_log(self) -> None:
        for widget in (self.texto, getattr(self, "tabla", None)):
            if widget is None:
                continue
            widget.configure(background=self.tema.superficie_alt, foreground=self.tema.texto,
                             insertbackground=self.tema.texto)
        for nivel, color in (
            ("DEBUG", self.tema.neutro), ("INFO", self.tema.texto_tenue),
            ("WARNING", self.tema.aviso), ("ERROR", self.tema.error),
            ("CRITICAL", self.tema.error),
        ):
            self.texto.tag_configure(nivel, foreground=color)
        tabla = getattr(self, "tabla", None)
        if tabla is not None:
            tabla.tag_configure("cabecera", foreground=self.tema.texto_tenue)
            tabla.tag_configure("incidencia", foreground=self.tema.aviso)

    def _repintar_estado(self, datos: dict[str, Any]) -> None:
        rotulo, color = datos.get("ultimo_estado", ("En espera", "neutro"))
        datos["estado"].configure(text=rotulo, style=f"{color.capitalize()}.TLabel")
        datos["punto"].pintar(getattr(self.tema, color))

    # ------------------------------------------------------------------ #
    # Puente entre hilos
    # ------------------------------------------------------------------ #

    def _enganchar_log(self) -> None:
        manejador = ManejadorCallback(
            lambda linea, nivel: self.cola.put(("log", (linea, nivel)))
        )
        logging.getLogger("ibalance").addHandler(manejador)

    def _progreso_desde_hilo(self, balanza: Balanza, estado: str, detalle: str) -> None:
        self.cola.put(("estado", (balanza.id, estado, detalle)))

    def _vaciar_cola(self) -> None:
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "log":
                    self._escribir(*dato)
                elif tipo == "estado":
                    self._pintar_estado(*dato)
                elif tipo == "fin":
                    self._al_terminar(dato)
        except queue.Empty:
            pass

        if self.temporizador.activo:
            restantes = self.temporizador.segundos_restantes()
            self.timer_var.set(
                f"proxima corrida en {restantes // 60:02d}:{restantes % 60:02d}"
            )
        self.raiz.after(200, self._vaciar_cola)

    def _mostrar_marcador(self) -> None:
        """Texto de bienvenida mientras no haya ninguna linea de log."""
        self._marcador = True
        self.texto.configure(state="normal")
        self.texto.delete("1.0", "end")
        self.texto.insert(
            "1.0",
            "Sin actividad todavia. Pulse «Sincronizar» para enviar el catalogo "
            "a las balanzas activas.\n",
            "DEBUG",
        )
        self.texto.configure(state="disabled")

    def _escribir(self, linea: str, nivel: str) -> None:
        self.texto.configure(state="normal")
        if self._marcador:
            # La primera linea real sustituye al texto de bienvenida en vez de
            # empujarlo hacia abajo, donde se quedaria para siempre.
            self.texto.delete("1.0", "end")
            self._marcador = False
        self.texto.insert("end", linea + "\n", nivel)
        self.texto.see("end")
        self.texto.configure(state="disabled")

    def _pintar_estado(self, balanza_id: int, estado: str, detalle: str) -> None:
        datos = self.filas.get(balanza_id)
        if not datos:
            return
        rotulo, color = ESTADOS.get(estado, (estado, "texto_tenue"))
        if detalle and estado == "enviando":
            rotulo = f"{rotulo} · {detalle}"
        datos["ultimo_estado"] = (rotulo, color)
        self._repintar_estado(datos)

    # ------------------------------------------------------------------ #
    # Acciones
    # ------------------------------------------------------------------ #

    def _ocupado(self) -> bool:
        return self.hilo is not None and self.hilo.is_alive()

    def _lanzar(self, funcion: Callable[[], None], nombre: str) -> bool:
        if self._ocupado():
            messagebox.showinfo("En curso", "Ya hay una operacion en marcha.")
            return False
        self.hilo = threading.Thread(target=funcion, name=nombre, daemon=True)
        self.btn_sync.configure(state="disabled")
        self.btn_detener.configure(state="normal")
        self.estado_var.set("Trabajando…")
        self.punto_global.pintar(self.tema.acento)
        self.progreso.grid()
        self.progreso.start(14)
        self.hilo.start()
        return True

    def _sincronizar(self, solo: list[int] | None = None) -> None:
        self._aplicar_balanzas()
        self._lanzar(lambda: self._trabajo_sincronizar(solo), "sincronizacion")

    def _sincronizar_en_hilo(self) -> None:
        """Entrada del temporizador; ya corre fuera del hilo de la interfaz."""
        if self._ocupado():
            log.warning("El temporizador se salta esta corrida: hay otra en marcha")
            return
        self._trabajo_sincronizar(None)

    def _trabajo_sincronizar(self, solo: list[int] | None) -> None:
        resultado = self.motor.sincronizar(solo_ids=solo)
        self.cola.put(("fin", resultado))

    def _detener(self) -> None:
        self.motor.cancelar()
        self.estado_var.set("Cancelando; se termina la balanza en curso…")

    def _al_terminar(self, resultado: ResultadoSincronizacion) -> None:
        self.btn_sync.configure(state="normal")
        self.btn_detener.configure(state="disabled")
        self.progreso.stop()
        self.progreso.grid_remove()

        if resultado.plus_leidos or resultado.balanzas:
            self.met_ultima.actualizar(f"{resultado.fin:%H:%M}")
            self.met_productos.actualizar(str(resultado.plus_leidos))
            self.estado_var.set(
                f"{resultado.exitosas} correctas · {resultado.fallidas} con error · "
                f"{resultado.omitidas} omitidas"
            )
        else:
            self.estado_var.set("Listo")
        self._refrescar_metricas()

        if resultado.error_global:
            self.punto_global.pintar(self.tema.error)
            messagebox.showerror("La sincronizacion no pudo completarse",
                                 resultado.error_global)
        elif resultado.fallidas:
            self.punto_global.pintar(self.tema.aviso)
            messagebox.showwarning("Sincronizacion con incidencias",
                                   resumen_texto(resultado))
        else:
            self.punto_global.pintar(self.tema.exito)

    def _probar(self, balanza_id: int) -> None:
        self._aplicar_balanzas()
        balanza = self.config.balanza_por_id(balanza_id)
        if balanza is None:
            return

        def trabajo() -> None:
            self.cola.put(("estado", (balanza_id, "verificando", "")))
            ok, motivo = self.motor.probar_balanza(balanza)
            self.cola.put(("estado", (balanza_id, "ok" if ok else "error", "")))
            log.info("[%s] %s", balanza.nombre, motivo)
            self.cola.put(("fin", self._resultado_vacio()))

        self._lanzar(trabajo, f"probar-{balanza_id}")

    def _probar_todas(self) -> None:
        self._aplicar_balanzas()

        def trabajo() -> None:
            for balanza in self.config.balanzas_activas():
                self.cola.put(("estado", (balanza.id, "verificando", "")))
                ok, motivo = self.motor.probar_balanza(balanza)
                self.cola.put(("estado", (balanza.id, "ok" if ok else "error", "")))
                log.info("[%s] %s", balanza.nombre, motivo)
            self.cola.put(("fin", self._resultado_vacio()))

        self._lanzar(trabajo, "probar-todas")

    def _limpiar_balanza(self, balanza_id: int) -> None:
        self._aplicar_balanzas()
        balanza = self.config.balanza_por_id(balanza_id)
        if balanza is None:
            return
        if not messagebox.askyesno(
            "Vaciar la balanza",
            f"Se borrara TODO el catalogo de {balanza.nombre} ({balanza.ip}).\n\n"
            "Uselo cuando la balanza quedo con datos corruptos. Despues habra que "
            "sincronizar de nuevo.\n\n¿Continuar?",
        ):
            return

        def trabajo() -> None:
            resultado = self.motor.limpiar_balanza(balanza)
            self.cola.put(("estado", (balanza_id, "ok" if resultado.ok else "error", "")))
            self.cola.put(("fin", self._resultado_vacio()))

        self._lanzar(trabajo, f"limpiar-{balanza_id}")

    def _alternar_temporizador(self) -> None:
        if self.temporizador.activo:
            self.temporizador.detener()
            self.btn_timer.configure(text="Automatico")
            self.timer_var.set("")
            return
        self._guardar_config(silencioso=True)
        self.temporizador.intervalo_minutos = self.config.sincronizacion.intervalo_minutos
        self.temporizador.iniciar(ejecutar_ahora=False)
        self.btn_timer.configure(text="Detener automatico")

    def _analizar_origen(self) -> None:
        self.config.origen.ruta = self.var_ruta.get().strip() or self.config.origen.ruta
        try:
            lectura = leer(self.config.origen, str(self.config.resolver(self.config.origen.ruta)))
        except OrigenError as exc:
            self.lbl_origen.configure(text=str(exc), style="Error.TLabel")
            self.insignia_previa.actualizar("error", self.tema.error)
            return

        self.lbl_origen.configure(
            text=f"{lectura.total} productos validos de {lectura.lineas_totales} lineas · "
                 f"{len(lectura.incidencias)} incidencias",
            style="TenueSup.TLabel",
        )
        self.insignia_previa.actualizar(f"{lectura.total} productos", self.tema.texto_tenue)
        self.met_productos.actualizar(str(lectura.total))

        lineas = [f"{'CODIGO':<8}{'DESCRIPCION':<26}{'PRECIO':>10}   VIDA UTIL"]
        for plu in lectura.plus[:200]:
            lineas.append(
                f"{plu.codigo:<8}{plu.nombre[:24]:<26}{plu.precio_formateado():>10}"
                f"   {plu.vida_util_dias:>3} d"
            )
        if lectura.incidencias:
            lineas.append("")
            lineas.append("INCIDENCIAS")
            lineas.extend(f"  {i}" for i in lectura.incidencias[:20])

        self.tabla.configure(state="normal")
        self.tabla.delete("1.0", "end")
        self.tabla.insert("1.0", "\n".join(lineas))
        self.tabla.tag_add("cabecera", "1.0", "1.end")
        if lectura.incidencias:
            inicio = len(lectura.plus[:200]) + 3
            self.tabla.tag_add("incidencia", f"{inicio}.0", "end")
        self.tabla.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # Persistencia
    # ------------------------------------------------------------------ #

    def _volcar_config_a_ui(self) -> None:
        self.var_ruta.set(self.config.origen.ruta)
        self.var_dll.set(self.config.rongta.dll_path)
        sinc = self.config.sincronizacion
        self.var_intervalo.set(str(sinc.intervalo_minutos))
        self.var_ping.set(str(sinc.timeout_ping_seg))
        self.var_reintentos.set(str(sinc.reintentos))
        self.var_lote.set(str(self.config.rongta.tamano_lote_plu))
        self.var_omitir.set(sinc.omitir_si_sin_cambios)
        self.var_legacy.set(sinc.cerrar_procesos_legacy)
        self.var_limpiar.set(self.config.rongta.limpiar_antes_de_enviar)
        self.lbl_config.configure(text=_ruta_corta(self.ruta_config))
        self.lbl_backend.configure(text=self.motor.backend.descripcion)
        self._refrescar_metricas()

    def _refrescar_metricas(self) -> None:
        activas = sum(1 for d in self.filas.values() if d["activa"].get() and d["ip"].get().strip())
        al_dia = sum(
            1 for d in self.filas.values() if d.get("ultimo_estado", ("", ""))[1] == "exito"
        )
        self.met_balanzas.actualizar(str(activas))
        self.met_ok.actualizar(str(al_dia))

    def _aplicar_balanzas(self) -> None:
        for balanza in self.config.balanzas:
            datos = self.filas.get(balanza.id)
            if not datos:
                continue
            balanza.activa = bool(datos["activa"].get())
            balanza.ip = datos["ip"].get().strip()
            texto = datos["puerto"].get().strip()
            if texto.isdigit() and 0 < int(texto) < 65536:
                balanza.puerto = int(texto)
        self._refrescar_metricas()

    @staticmethod
    def _entero(var: tk.StringVar, actual: int) -> int:
        texto = var.get().strip()
        return int(texto) if texto.lstrip("-").isdigit() else actual

    def _guardar_balanzas(self) -> None:
        self._aplicar_balanzas()
        self._persistir()

    def _guardar_config(self, silencioso: bool = False) -> None:
        self.config.origen.ruta = self.var_ruta.get().strip() or self.config.origen.ruta
        self.config.rongta.dll_path = self.var_dll.get().strip() or self.config.rongta.dll_path
        sinc = self.config.sincronizacion
        sinc.intervalo_minutos = max(1, self._entero(self.var_intervalo, sinc.intervalo_minutos))
        sinc.timeout_ping_seg = max(1, self._entero(self.var_ping, sinc.timeout_ping_seg))
        sinc.reintentos = max(0, self._entero(self.var_reintentos, sinc.reintentos))
        sinc.omitir_si_sin_cambios = bool(self.var_omitir.get())
        sinc.cerrar_procesos_legacy = bool(self.var_legacy.get())
        self.config.rongta.limpiar_antes_de_enviar = bool(self.var_limpiar.get())
        self.config.rongta.tamano_lote_plu = max(
            0, self._entero(self.var_lote, self.config.rongta.tamano_lote_plu)
        )
        self._aplicar_balanzas()
        self._persistir(silencioso)

    def _persistir(self, silencioso: bool = False) -> None:
        try:
            self.config.validar()
            destino = self.config.guardar(self.ruta_config)
        except ConfigError as exc:
            messagebox.showerror("Configuracion invalida", str(exc))
            return
        except OSError as exc:
            messagebox.showerror("No se pudo guardar", str(exc))
            return
        log.info("Configuracion guardada en %s", destino)
        self.estado_var.set(f"Configuracion guardada · {datetime.now():%H:%M:%S}")
        if not silencioso:
            self.punto_global.pintar(self.tema.exito)

    def _elegir_origen(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Seleccione el archivo de productos",
            filetypes=[("Texto", "*.txt"), ("CSV", "*.csv"), ("Todos", "*.*")],
        )
        if ruta:
            self.var_ruta.set(ruta)

    def _elegir_dll(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Seleccione rtslabelscale.dll", filetypes=[("DLL", "*.dll")]
        )
        if ruta:
            self.var_dll.set(ruta)

    def _limpiar_log(self) -> None:
        self._mostrar_marcador()

    @staticmethod
    def _resultado_vacio() -> ResultadoSincronizacion:
        ahora = datetime.now()
        return ResultadoSincronizacion(inicio=ahora, fin=ahora, origen="", plus_leidos=0)

    # ------------------------------------------------------------------ #

    def _cerrar(self) -> None:
        if self._ocupado() and not messagebox.askyesno(
            "Hay una operacion en curso",
            "Cerrar ahora puede dejar una balanza con la conexion abierta y "
            "obligar a esperar a que expire su temporizador.\n\n¿Cerrar de todos modos?",
        ):
            return
        self.temporizador.detener()
        self.motor.cancelar()
        with suppress(Exception):
            self.motor.backend.cerrar()
        self.raiz.destroy()

    def ejecutar(self) -> int:
        log.info("ibalance iniciado · %s", self.motor.backend.descripcion)
        self.raiz.mainloop()
        return 0


def ejecutar(ruta_config: Path | None = None, simular: bool = False) -> int:
    """Abre la ventana principal."""
    return Aplicacion(ruta_config, simular).ejecutar()
