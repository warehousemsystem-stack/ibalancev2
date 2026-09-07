"""Ventana principal de ibalance.

tkinter no es seguro entre hilos: solo el hilo de la interfaz puede tocar los
widgets. La sincronizacion corre en un hilo aparte para que la ventana no se
congele, asi que todo lo que llega desde ese hilo (lineas de log, cambios de
estado, el resultado final) pasa por una cola que el hilo de la interfaz vacia
con ``after``. Llamar a los widgets directamente desde el hilo de trabajo
funciona casi siempre y cuelga la aplicacion de vez en cuando, que es peor.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from ..config import Balanza, Config, ConfigError, config_por_defecto, ruta_config_por_defecto
from ..engine import MotorSincronizacion, crear_backend
from ..logging_setup import ManejadorCallback, configurar, obtener
from ..models import ResultadoSincronizacion
from ..report import resumen_texto
from ..scheduler import Temporizador

log = obtener("gui")

COLORES = {
    "ERROR": "#f44747",
    "CRITICAL": "#f44747",
    "WARNING": "#dcdcaa",
    "INFO": "#d4d4d4",
    "DEBUG": "#808080",
}

ESTADOS = {
    "verificando": ("comprobando red...", "#569cd6"),
    "conectando": ("conectando...", "#569cd6"),
    "enviando": ("enviando", "#569cd6"),
    "reintentando": ("reintentando", "#dcdcaa"),
    "ok": ("correcta", "#6a9955"),
    "error": ("con error", "#f44747"),
    "omitida": ("sin cambios", "#808080"),
}


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

        self.raiz = tk.Tk()
        self.raiz.title(
            "ibalance - sincronizacion de balanzas Rongta"
            + ("  [MODO SIMULACION]" if simular else "")
        )
        self.raiz.geometry("900x650")
        self.raiz.minsize(780, 520)
        self._construir()
        self._enganchar_log()
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.raiz.after(100, self._vaciar_cola)

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
    # Construccion de la interfaz
    # ------------------------------------------------------------------ #

    def _construir(self) -> None:
        self.cuaderno = ttk.Notebook(self.raiz)
        self.cuaderno.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._pestana_log()
        self._pestana_balanzas()
        self._pestana_config()

        self.estado_var = tk.StringVar(value="Listo")
        ttk.Label(
            self.raiz, textvariable=self.estado_var, relief=tk.SUNKEN, anchor=tk.W
        ).pack(fill=tk.X, side=tk.BOTTOM, padx=6, pady=(0, 4))

    def _pestana_log(self) -> None:
        pestana = ttk.Frame(self.cuaderno)
        self.cuaderno.add(pestana, text="  Actividad  ")

        barra = ttk.Frame(pestana)
        barra.pack(fill=tk.X, padx=6, pady=6)

        self.btn_sync = ttk.Button(barra, text="Sincronizar ahora", command=self._sincronizar)
        self.btn_sync.pack(side=tk.LEFT)
        self.btn_detener = ttk.Button(
            barra, text="Detener", command=self._detener, state=tk.DISABLED
        )
        self.btn_detener.pack(side=tk.LEFT, padx=4)

        ttk.Separator(barra, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        self.btn_timer = ttk.Button(
            barra, text="Iniciar automatico", command=self._alternar_temporizador
        )
        self.btn_timer.pack(side=tk.LEFT)
        self.timer_var = tk.StringVar(value="")
        ttk.Label(barra, textvariable=self.timer_var).pack(side=tk.LEFT, padx=8)

        ttk.Button(barra, text="Limpiar vista", command=self._limpiar_log).pack(side=tk.RIGHT)

        marco = ttk.Frame(pestana)
        marco.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.texto = tk.Text(
            marco, wrap=tk.WORD, font=("Consolas", 9), state=tk.DISABLED,
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
        )
        barra_v = ttk.Scrollbar(marco, orient=tk.VERTICAL, command=self.texto.yview)
        self.texto.configure(yscrollcommand=barra_v.set)
        barra_v.pack(side=tk.RIGHT, fill=tk.Y)
        self.texto.pack(fill=tk.BOTH, expand=True)
        for nivel, color in COLORES.items():
            self.texto.tag_configure(nivel, foreground=color)

    def _pestana_balanzas(self) -> None:
        pestana = ttk.Frame(self.cuaderno)
        self.cuaderno.add(pestana, text="  Balanzas  ")

        cabecera = ttk.Frame(pestana)
        cabecera.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(
            cabecera, text="Balanzas de la red", font=("Segoe UI", 11, "bold")
        ).pack(side=tk.LEFT)
        ttk.Button(cabecera, text="Guardar cambios", command=self._guardar_balanzas).pack(
            side=tk.RIGHT
        )
        ttk.Button(cabecera, text="Probar todas", command=self._probar_todas).pack(
            side=tk.RIGHT, padx=4
        )

        lienzo = tk.Canvas(pestana, highlightthickness=0)
        barra_v = ttk.Scrollbar(pestana, orient=tk.VERTICAL, command=lienzo.yview)
        interior = ttk.Frame(lienzo)
        interior.bind(
            "<Configure>", lambda e: lienzo.configure(scrollregion=lienzo.bbox("all"))
        )
        lienzo.create_window((0, 0), window=interior, anchor="nw")
        lienzo.configure(yscrollcommand=barra_v.set)
        barra_v.pack(side=tk.RIGHT, fill=tk.Y)
        lienzo.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        for balanza in self.config.balanzas:
            self._fila_balanza(interior, balanza)

    def _fila_balanza(self, padre: ttk.Frame, balanza: Balanza) -> None:
        marco = ttk.LabelFrame(padre, text=f"{balanza.id}. {balanza.nombre}", padding=6)
        marco.pack(fill=tk.X, pady=3, padx=2)

        activa = tk.BooleanVar(value=balanza.activa)
        ttk.Checkbutton(marco, text="Activa", variable=activa).pack(side=tk.LEFT)

        ttk.Label(marco, text="IP:").pack(side=tk.LEFT, padx=(10, 2))
        ip = tk.StringVar(value=balanza.ip)
        ttk.Entry(marco, textvariable=ip, width=16).pack(side=tk.LEFT)

        ttk.Label(marco, text="Puerto:").pack(side=tk.LEFT, padx=(10, 2))
        puerto = tk.StringVar(value=str(balanza.puerto))
        ttk.Entry(marco, textvariable=puerto, width=7).pack(side=tk.LEFT)

        etiqueta = ttk.Label(marco, text="", width=26)
        etiqueta.pack(side=tk.LEFT, padx=10)

        ttk.Button(
            marco, text="Probar", width=8,
            command=lambda b=balanza.id: self._probar(b),
        ).pack(side=tk.RIGHT)
        ttk.Button(
            marco, text="Sincronizar", width=12,
            command=lambda b=balanza.id: self._sincronizar(solo=[b]),
        ).pack(side=tk.RIGHT, padx=4)
        ttk.Button(
            marco, text="Forzar limpieza", width=15,
            command=lambda b=balanza.id: self._limpiar_balanza(b),
        ).pack(side=tk.RIGHT)

        self.filas[balanza.id] = {
            "activa": activa, "ip": ip, "puerto": puerto, "etiqueta": etiqueta,
        }

    def _pestana_config(self) -> None:
        pestana = ttk.Frame(self.cuaderno)
        self.cuaderno.add(pestana, text="  Configuracion  ")
        marco = ttk.Frame(pestana, padding=12)
        marco.pack(fill=tk.BOTH, expand=True)

        origen = ttk.LabelFrame(marco, text="Origen de datos", padding=10)
        origen.pack(fill=tk.X, pady=4)
        fila = ttk.Frame(origen)
        fila.pack(fill=tk.X)
        ttk.Label(fila, text="Archivo:").pack(side=tk.LEFT)
        self.var_ruta = tk.StringVar(value=self.config.origen.ruta)
        ttk.Entry(fila, textvariable=self.var_ruta).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(fila, text="Examinar...", command=self._elegir_origen).pack(side=tk.LEFT)

        dll = ttk.LabelFrame(marco, text="Libreria del fabricante", padding=10)
        dll.pack(fill=tk.X, pady=4)
        fila = ttk.Frame(dll)
        fila.pack(fill=tk.X)
        ttk.Label(fila, text="rtslabelscale.dll:").pack(side=tk.LEFT)
        self.var_dll = tk.StringVar(value=self.config.rongta.dll_path)
        ttk.Entry(fila, textvariable=self.var_dll).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(fila, text="Examinar...", command=self._elegir_dll).pack(side=tk.LEFT)
        ttk.Label(
            dll,
            text="La DLL es de 32 bits: la aplicacion debe ejecutarse con Python de 32 bits.",
            foreground="#666",
        ).pack(anchor=tk.W, pady=(6, 0))

        sinc = ttk.LabelFrame(marco, text="Sincronizacion", padding=10)
        sinc.pack(fill=tk.X, pady=4)
        self.var_intervalo = self._campo(sinc, "Intervalo automatico (minutos):",
                                         self.config.sincronizacion.intervalo_minutos)
        self.var_ping = self._campo(sinc, "Timeout de ping (segundos):",
                                    self.config.sincronizacion.timeout_ping_seg)
        self.var_reintentos = self._campo(sinc, "Reintentos por balanza:",
                                          self.config.sincronizacion.reintentos)
        self.var_lote = self._campo(sinc, "Productos por lote (0 = todos juntos):",
                                    self.config.rongta.tamano_lote_plu)

        self.var_omitir = tk.BooleanVar(value=self.config.sincronizacion.omitir_si_sin_cambios)
        ttk.Checkbutton(
            sinc, text="Omitir balanzas cuyo catalogo ya esta al dia",
            variable=self.var_omitir,
        ).pack(anchor=tk.W, pady=2)

        self.var_legacy = tk.BooleanVar(value=self.config.sincronizacion.cerrar_procesos_legacy)
        ttk.Checkbutton(
            sinc,
            text="Cerrar la aplicacion antigua (ibalance.exe) antes de sincronizar",
            variable=self.var_legacy,
        ).pack(anchor=tk.W, pady=2)

        ttk.Button(marco, text="Guardar configuracion", command=self._guardar_config).pack(
            anchor=tk.E, pady=10
        )

    @staticmethod
    def _campo(padre: ttk.Widget, etiqueta: str, valor: Any) -> tk.StringVar:
        fila = ttk.Frame(padre)
        fila.pack(fill=tk.X, pady=2)
        ttk.Label(fila, text=etiqueta, width=38, anchor=tk.W).pack(side=tk.LEFT)
        var = tk.StringVar(value=str(valor))
        ttk.Entry(fila, textvariable=var, width=10).pack(side=tk.LEFT)
        return var

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
            self.timer_var.set(f"proxima corrida en {restantes // 60:02d}:{restantes % 60:02d}")
        self.raiz.after(200, self._vaciar_cola)

    def _escribir(self, linea: str, nivel: str) -> None:
        self.texto.configure(state=tk.NORMAL)
        self.texto.insert(tk.END, linea + "\n", nivel)
        self.texto.see(tk.END)
        self.texto.configure(state=tk.DISABLED)

    def _pintar_estado(self, balanza_id: int, estado: str, detalle: str) -> None:
        fila = self.filas.get(balanza_id)
        if not fila:
            return
        texto, color = ESTADOS.get(estado, (estado, "#d4d4d4"))
        if detalle and estado == "enviando":
            texto = f"{texto} {detalle}"
        fila["etiqueta"].configure(text=texto, foreground=color)

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
        self.btn_sync.configure(state=tk.DISABLED)
        self.btn_detener.configure(state=tk.NORMAL)
        self.estado_var.set("Trabajando...")
        self.hilo.start()
        return True

    def _sincronizar(self, solo: list[int] | None = None) -> None:
        self._aplicar_balanzas()
        self._lanzar(lambda: self._trabajo_sincronizar(solo), "sincronizacion")

    def _sincronizar_en_hilo(self) -> None:
        """Punto de entrada del temporizador (ya corre fuera de la interfaz)."""
        if self._ocupado():
            log.warning("El temporizador se salta esta corrida: hay otra en marcha")
            return
        self._trabajo_sincronizar(None)

    def _trabajo_sincronizar(self, solo: list[int] | None) -> None:
        resultado = self.motor.sincronizar(solo_ids=solo)
        self.cola.put(("fin", resultado))

    def _detener(self) -> None:
        self.motor.cancelar()
        self.estado_var.set("Cancelando; se termina la balanza en curso...")

    def _al_terminar(self, resultado: ResultadoSincronizacion) -> None:
        self.btn_sync.configure(state=tk.NORMAL)
        self.btn_detener.configure(state=tk.DISABLED)
        self.estado_var.set(
            f"Ultima corrida {resultado.fin:%H:%M:%S}: {resultado.exitosas} correctas, "
            f"{resultado.fallidas} con error, {resultado.omitidas} omitidas"
        )
        if resultado.error_global:
            messagebox.showerror("La sincronizacion no pudo completarse",
                                 resultado.error_global)
        elif resultado.fallidas:
            messagebox.showwarning(
                "Sincronizacion con incidencias", resumen_texto(resultado)
            )

    def _probar(self, balanza_id: int) -> None:
        self._aplicar_balanzas()
        balanza = self.config.balanza_por_id(balanza_id)
        if balanza is None:
            return

        def trabajo() -> None:
            ok, motivo = self.motor.probar_balanza(balanza)
            self.cola.put(("estado", (balanza_id, "ok" if ok else "error", motivo)))
            log.info("[%s] prueba: %s", balanza.nombre, motivo)
            self.cola.put(("fin", self._resultado_vacio()))

        self._lanzar(trabajo, f"probar-{balanza_id}")

    def _probar_todas(self) -> None:
        self._aplicar_balanzas()

        def trabajo() -> None:
            for balanza in self.config.balanzas_activas():
                ok, motivo = self.motor.probar_balanza(balanza)
                self.cola.put(("estado", (balanza.id, "ok" if ok else "error", motivo)))
                log.info("[%s] prueba: %s", balanza.nombre, motivo)
            self.cola.put(("fin", self._resultado_vacio()))

        self._lanzar(trabajo, "probar-todas")

    def _limpiar_balanza(self, balanza_id: int) -> None:
        self._aplicar_balanzas()
        balanza = self.config.balanza_por_id(balanza_id)
        if balanza is None:
            return
        if not messagebox.askyesno(
            "Forzar limpieza",
            f"Se borrara TODO el catalogo de {balanza.nombre} ({balanza.ip}).\n\n"
            "Uselo cuando la balanza quedo con datos corruptos. Despues habra que "
            "sincronizar de nuevo.\n\n¿Continuar?",
        ):
            return

        def trabajo() -> None:
            resultado = self.motor.limpiar_balanza(balanza)
            self.cola.put(
                ("estado", (balanza_id, "ok" if resultado.ok else "error", resultado.mensaje))
            )
            self.cola.put(("fin", self._resultado_vacio()))

        self._lanzar(trabajo, f"limpiar-{balanza_id}")

    def _alternar_temporizador(self) -> None:
        if self.temporizador.activo:
            self.temporizador.detener()
            self.btn_timer.configure(text="Iniciar automatico")
            self.timer_var.set("")
        else:
            self._guardar_config(silencioso=True)
            self.temporizador.intervalo_minutos = self.config.sincronizacion.intervalo_minutos
            self.temporizador.iniciar(ejecutar_ahora=False)
            self.btn_timer.configure(text="Detener automatico")

    # ------------------------------------------------------------------ #
    # Persistencia
    # ------------------------------------------------------------------ #

    def _aplicar_balanzas(self) -> None:
        for balanza in self.config.balanzas:
            fila = self.filas.get(balanza.id)
            if not fila:
                continue
            balanza.activa = bool(fila["activa"].get())
            balanza.ip = fila["ip"].get().strip()
            texto = fila["puerto"].get().strip()
            if texto.isdigit() and 0 < int(texto) < 65536:
                balanza.puerto = int(texto)

    def _guardar_balanzas(self) -> None:
        self._aplicar_balanzas()
        self._persistir()

    @staticmethod
    def _entero(var: tk.StringVar, actual: int) -> int:
        texto = var.get().strip()
        return int(texto) if texto.lstrip("-").isdigit() else actual

    def _guardar_config(self, silencioso: bool = False) -> None:
        origen = self.config.origen
        origen.ruta = self.var_ruta.get().strip() or origen.ruta
        self.config.rongta.dll_path = self.var_dll.get().strip() or self.config.rongta.dll_path
        sinc = self.config.sincronizacion
        sinc.intervalo_minutos = max(1, self._entero(self.var_intervalo, sinc.intervalo_minutos))
        sinc.timeout_ping_seg = max(1, self._entero(self.var_ping, sinc.timeout_ping_seg))
        sinc.reintentos = max(0, self._entero(self.var_reintentos, sinc.reintentos))
        sinc.omitir_si_sin_cambios = bool(self.var_omitir.get())
        sinc.cerrar_procesos_legacy = bool(self.var_legacy.get())
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
        if not silencioso:
            messagebox.showinfo("Guardado", f"Configuracion guardada en {destino}")

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
        self.texto.configure(state=tk.NORMAL)
        self.texto.delete("1.0", tk.END)
        self.texto.configure(state=tk.DISABLED)

    @staticmethod
    def _resultado_vacio() -> ResultadoSincronizacion:
        from datetime import datetime

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
        log.info("ibalance iniciado (%s)", self.motor.backend.descripcion)
        self.raiz.mainloop()
        return 0


def ejecutar(ruta_config: Path | None = None, simular: bool = False) -> int:
    """Abre la ventana principal."""
    return Aplicacion(ruta_config, simular).ejecutar()
