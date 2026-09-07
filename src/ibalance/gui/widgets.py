"""Piezas reutilizables de la interfaz.

tkinter no tiene tarjetas, insignias ni indicadores de estado, asi que se
construyen aqui sobre ``tk.Frame`` y ``tk.Canvas``. Cada pieza sabe repintarse
cuando cambia el tema, y se registra para que la ventana pueda recorrerlas.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .tema import Fuentes, Tema

#: Firma de los repintados diferidos que ejecuta la ventana al cambiar de tema.
Repintar = Callable[[Tema], None]


class Tarjeta(tk.Frame):
    """Panel con borde de un pixel.

    ``highlightthickness`` es la unica forma de dibujar un borde fino y de
    color propio en tkinter: ``relief`` da bordes con volumen que estropean un
    diseño plano.
    """

    def __init__(self, padre: tk.Misc, tema: Tema, relleno: int = 16, **kwargs) -> None:
        super().__init__(
            padre,
            background=tema.superficie,
            highlightbackground=tema.borde,
            highlightcolor=tema.borde,
            highlightthickness=1,
            bd=0,
            padx=relleno,
            pady=relleno,
            **kwargs,
        )

    def repintar(self, tema: Tema) -> None:
        self.configure(
            background=tema.superficie,
            highlightbackground=tema.borde,
            highlightcolor=tema.borde,
        )


class Punto(tk.Canvas):
    """Circulo de estado. Dice de un vistazo como esta cada balanza."""

    def __init__(self, padre: tk.Misc, tema: Tema, diametro: int = 10) -> None:
        super().__init__(padre, width=diametro, height=diametro,
                         highlightthickness=0, bd=0, background=tema.superficie)
        self._diametro = diametro
        self._color = tema.neutro
        self._circulo = self.create_oval(1, 1, diametro - 1, diametro - 1,
                                         fill=self._color, outline="")

    def pintar(self, color: str) -> None:
        self._color = color
        self.itemconfigure(self._circulo, fill=color)

    def repintar(self, tema: Tema) -> None:
        self.configure(background=tema.superficie)


class Insignia(tk.Label):
    """Etiqueta pequeña con fondo tenue, para contadores y estados."""

    def __init__(self, padre: tk.Misc, tema: Tema, fuentes: Fuentes,
                 texto: str = "", color: str | None = None) -> None:
        self._color = color or tema.texto_tenue
        super().__init__(padre, text=texto, font=fuentes.etiqueta,
                         background=tema.superficie_alt, foreground=self._color,
                         padx=8, pady=3, bd=0)

    def actualizar(self, texto: str, color: str | None = None) -> None:
        self._color = color or self._color
        self.configure(text=texto, foreground=self._color)

    def repintar(self, tema: Tema) -> None:
        self.configure(background=tema.superficie_alt)


class Metrica(ttk.Frame):
    """Cifra grande con su rotulo debajo. Se usa en la vista de resumen."""

    def __init__(self, padre: tk.Misc, rotulo: str, valor: str = "—") -> None:
        super().__init__(padre, style="Superficie.TFrame")
        self.var = tk.StringVar(value=valor)
        self._etiqueta_valor = ttk.Label(self, textvariable=self.var, style="Metrica.TLabel")
        self._etiqueta_valor.pack(anchor="w")
        ttk.Label(self, text=rotulo.upper(), style="Etiqueta.TLabel").pack(anchor="w", pady=(2, 0))

    def actualizar(self, valor: str, estilo: str = "Metrica.TLabel") -> None:
        self.var.set(valor)
        self._etiqueta_valor.configure(style=estilo)


class PanelDesplazable(ttk.Frame):
    """Contenedor con barra de desplazamiento vertical discreta.

    El truco es que el marco interior siga el ancho del lienzo: sin eso las
    tarjetas no se estiran y queda una franja vacia a la derecha.
    """

    def __init__(self, padre: tk.Misc, tema: Tema, estilo: str = "TFrame") -> None:
        super().__init__(padre, style=estilo)
        self._lienzo = tk.Canvas(self, highlightthickness=0, bd=0,
                                 background=tema.fondo)
        self.barra = ttk.Scrollbar(self, orient="vertical", style="Fina.Vertical.TScrollbar",
                                   command=self._lienzo.yview)
        self.interior = ttk.Frame(self._lienzo, style=estilo)

        self._ventana = self._lienzo.create_window((0, 0), window=self.interior, anchor="nw")
        self._lienzo.configure(yscrollcommand=self._al_desplazar)

        self.interior.bind(
            "<Configure>",
            lambda e: self._lienzo.configure(scrollregion=self._lienzo.bbox("all")),
        )
        self._lienzo.bind(
            "<Configure>",
            lambda e: self._lienzo.itemconfigure(self._ventana, width=e.width),
        )
        self._lienzo.bind("<Enter>", self._activar_rueda)
        self._lienzo.bind("<Leave>", self._desactivar_rueda)

        self.barra.pack(side="right", fill="y")
        self._lienzo.pack(side="left", fill="both", expand=True)

    def _al_desplazar(self, inicio: str, fin: str) -> None:
        # La barra solo aparece si hace falta: una barra siempre visible en un
        # panel que cabe entero es ruido.
        if float(inicio) <= 0.0 and float(fin) >= 1.0:
            self.barra.pack_forget()
        else:
            self.barra.pack(side="right", fill="y")
        self.barra.set(inicio, fin)

    def _activar_rueda(self, _evento: tk.Event) -> None:
        self._lienzo.bind_all("<MouseWheel>", self._rueda)
        self._lienzo.bind_all("<Button-4>", self._rueda)
        self._lienzo.bind_all("<Button-5>", self._rueda)

    def _desactivar_rueda(self, _evento: tk.Event) -> None:
        for secuencia in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._lienzo.unbind_all(secuencia)

    def _rueda(self, evento: tk.Event) -> None:
        if getattr(evento, "num", None) == 4:
            paso = -1
        elif getattr(evento, "num", None) == 5:
            paso = 1
        else:
            paso = -1 if evento.delta > 0 else 1
        self._lienzo.yview_scroll(paso, "units")

    def repintar(self, tema: Tema) -> None:
        self._lienzo.configure(background=tema.fondo)


def separador(padre: tk.Misc, horizontal: bool = True) -> ttk.Frame:
    """Linea de un pixel. Mas discreta que ``ttk.Separator``, que dibuja dos."""
    marco = ttk.Frame(padre, style="Separador.TFrame",
                      height=1 if horizontal else 0, width=0 if horizontal else 1)
    return marco


def campo(padre: tk.Misc, rotulo: str, variable: tk.StringVar,
          ancho: int | None = None, ayuda: str = "") -> ttk.Frame:
    """Rotulo pequeño encima de la caja de texto, no al lado.

    En vertical los formularios se leen mejor y no dependen de que todos los
    rotulos midan lo mismo.
    """
    marco = ttk.Frame(padre, style="Superficie.TFrame")
    ttk.Label(marco, text=rotulo.upper(), style="Etiqueta.TLabel").pack(anchor="w")
    entrada = ttk.Entry(marco, textvariable=variable)
    if ancho:
        entrada.configure(width=ancho)
        entrada.pack(anchor="w", pady=(4, 0))
    else:
        entrada.pack(fill="x", pady=(4, 0))
    if ayuda:
        ttk.Label(marco, text=ayuda, style="TenueSup.TLabel",
                  wraplength=460, justify="left").pack(anchor="w", pady=(4, 0))
    return marco
