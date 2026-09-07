"""Paleta y estilos de la interfaz.

tkinter no trae nada parecido a una hoja de estilos, asi que todo el aspecto
de la aplicacion se define aqui: un tema es un puñado de colores y una funcion
que los traduce a estilos ``ttk``. Concentrarlo en un sitio es lo que permite
cambiar de claro a oscuro sin tocar la ventana.

Se parte del tema ``clam`` porque es el unico de los incorporados cuyos
elementos aceptan colores planos; el tema nativo de Windows dibuja bordes y
degradados propios que no se pueden quitar.
"""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

#: Familias tipograficas por orden de preferencia. La primera disponible gana.
FAMILIAS = ("Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans", "Helvetica", "TkDefaultFont")
FAMILIAS_MONO = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo", "TkFixedFont")


@dataclass(frozen=True)
class Tema:
    """Los colores de la aplicacion.

    Nombres por funcion y no por color: ``superficie`` sigue siendo la
    superficie cuando el tema es oscuro y el color real es casi negro.
    """

    nombre: str
    fondo: str          # lienzo de la ventana
    superficie: str     # tarjetas y paneles
    superficie_alt: str # franjas y zonas hundidas
    campo: str          # fondo de las cajas de texto
    borde: str
    borde_suave: str
    texto: str
    texto_tenue: str
    acento: str
    acento_hover: str
    acento_texto: str
    exito: str
    aviso: str
    error: str
    neutro: str
    seleccion: str

    @property
    def oscuro(self) -> bool:
        return self.nombre == "oscuro"


CLARO = Tema(
    nombre="claro",
    fondo="#F6F6F7",
    superficie="#FFFFFF",
    superficie_alt="#FAFAFB",
    campo="#FFFFFF",
    borde="#E4E4E7",
    borde_suave="#EFEFF1",
    texto="#18181B",
    texto_tenue="#71717A",
    acento="#2563EB",
    acento_hover="#1D4ED8",
    acento_texto="#FFFFFF",
    exito="#16A34A",
    aviso="#CA8A04",
    error="#DC2626",
    neutro="#A1A1AA",
    seleccion="#EFF4FE",
)

OSCURO = Tema(
    nombre="oscuro",
    fondo="#151518",
    superficie="#1D1D21",
    superficie_alt="#232328",
    # En oscuro los campos van MAS oscuros que la tarjeta: un campo mas claro
    # que su fondo parece un bloque resaltado, no una caja donde escribir.
    campo="#141417",
    borde="#2E2E34",
    borde_suave="#26262B",
    texto="#F4F4F5",
    texto_tenue="#9C9CA5",
    acento="#3B82F6",
    acento_hover="#60A5FA",
    acento_texto="#0B0B0D",
    exito="#4ADE80",
    aviso="#FBBF24",
    error="#F87171",
    neutro="#71717A",
    seleccion="#1E293B",
)

TEMAS = {"claro": CLARO, "oscuro": OSCURO}


def elegir_familia(opciones: tuple[str, ...]) -> str:
    """Primera familia instalada, para no depender de una fuente concreta."""
    disponibles = {f.lower() for f in tkfont.families()}
    for familia in opciones:
        if familia.lower() in disponibles:
            return familia
    return opciones[-1]


class Fuentes:
    """Escala tipografica de la aplicacion."""

    def __init__(self) -> None:
        base = elegir_familia(FAMILIAS)
        mono = elegir_familia(FAMILIAS_MONO)
        self.titulo = (base, 15, "bold")
        self.seccion = (base, 12, "bold")
        self.cuerpo = (base, 10)
        self.cuerpo_fuerte = (base, 10, "bold")
        self.pequena = (base, 9)
        self.etiqueta = (base, 8)
        self.metrica = (base, 20, "bold")
        self.mono = (mono, 9)


def aplicar(estilo: ttk.Style, tema: Tema, fuentes: Fuentes) -> None:
    """Traduce el tema a estilos ttk."""
    estilo.theme_use("clam")

    estilo.configure(".", background=tema.fondo, foreground=tema.texto,
                     font=fuentes.cuerpo, borderwidth=0, focuscolor=tema.fondo)

    # --- contenedores ---------------------------------------------------
    for nombre, color in (
        ("TFrame", tema.fondo),
        ("Superficie.TFrame", tema.superficie),
        ("Alterna.TFrame", tema.superficie_alt),
        ("Barra.TFrame", tema.superficie),
        ("Lateral.TFrame", tema.fondo),
    ):
        estilo.configure(nombre, background=color)

    estilo.configure("Separador.TFrame", background=tema.borde)

    # --- textos ---------------------------------------------------------
    for nombre, fuente, color, fondo in (
        ("TLabel", fuentes.cuerpo, tema.texto, tema.fondo),
        ("Sup.TLabel", fuentes.cuerpo, tema.texto, tema.superficie),
        ("Titulo.TLabel", fuentes.titulo, tema.texto, tema.superficie),
        ("Seccion.TLabel", fuentes.seccion, tema.texto, tema.fondo),
        ("SeccionSup.TLabel", fuentes.seccion, tema.texto, tema.superficie),
        ("Tenue.TLabel", fuentes.pequena, tema.texto_tenue, tema.fondo),
        ("TenueSup.TLabel", fuentes.pequena, tema.texto_tenue, tema.superficie),
        ("Etiqueta.TLabel", fuentes.etiqueta, tema.texto_tenue, tema.superficie),
        ("Metrica.TLabel", fuentes.metrica, tema.texto, tema.superficie),
        ("Fuerte.TLabel", fuentes.cuerpo_fuerte, tema.texto, tema.superficie),
        ("Mono.TLabel", fuentes.mono, tema.texto_tenue, tema.superficie),
    ):
        estilo.configure(nombre, font=fuente, foreground=color, background=fondo)

    for nombre, color in (
        ("Exito.TLabel", tema.exito), ("Aviso.TLabel", tema.aviso),
        ("Error.TLabel", tema.error), ("Neutro.TLabel", tema.neutro),
        ("Acento.TLabel", tema.acento),
    ):
        estilo.configure(nombre, font=fuentes.pequena, foreground=color,
                         background=tema.superficie)

    # --- botones --------------------------------------------------------
    # clam dibuja el relieve con cuatro colores; igualarlos lo deja plano.
    def boton(nombre: str, fondo: str, texto: str, hover: str,
              fuente=fuentes.cuerpo, relleno=(14, 7)) -> None:
        estilo.configure(nombre, background=fondo, foreground=texto, font=fuente,
                         padding=relleno, borderwidth=0, relief="flat",
                         bordercolor=fondo, lightcolor=fondo, darkcolor=fondo,
                         focuscolor=fondo, anchor="center")
        estilo.map(
            nombre,
            background=[("disabled", tema.borde_suave), ("pressed", hover), ("active", hover)],
            foreground=[("disabled", tema.neutro)],
            bordercolor=[("disabled", tema.borde_suave), ("active", hover)],
            lightcolor=[("disabled", tema.borde_suave), ("active", hover)],
            darkcolor=[("disabled", tema.borde_suave), ("active", hover)],
            relief=[("pressed", "flat"), ("active", "flat")],
        )

    boton("Primario.TButton", tema.acento, tema.acento_texto, tema.acento_hover,
          fuentes.cuerpo_fuerte)
    boton("Secundario.TButton", tema.superficie_alt, tema.texto, tema.borde)
    boton("Sutil.TButton", tema.superficie, tema.texto_tenue, tema.superficie_alt,
          fuentes.pequena, (10, 5))
    boton("Peligro.TButton", tema.superficie, tema.error, tema.superficie_alt,
          fuentes.pequena, (10, 5))
    boton("Icono.TButton", tema.superficie_alt, tema.texto_tenue, tema.borde,
          fuentes.pequena, (12, 7))
    boton("Nav.TButton", tema.fondo, tema.texto_tenue, tema.superficie,
          fuentes.cuerpo, (14, 9))
    estilo.configure("Nav.TButton", anchor="w")
    boton("NavActiva.TButton", tema.superficie, tema.texto, tema.superficie,
          fuentes.cuerpo_fuerte, (14, 9))
    estilo.configure("NavActiva.TButton", anchor="w")

    # --- campos ---------------------------------------------------------
    estilo.configure("TEntry", fieldbackground=tema.campo, background=tema.campo,
                     foreground=tema.texto, insertcolor=tema.texto, borderwidth=1,
                     relief="flat", bordercolor=tema.borde, lightcolor=tema.borde,
                     darkcolor=tema.borde, padding=(8, 6))
    estilo.map("TEntry",
               bordercolor=[("focus", tema.acento)],
               lightcolor=[("focus", tema.acento)],
               darkcolor=[("focus", tema.acento)])

    estilo.configure("TCheckbutton", background=tema.superficie, foreground=tema.texto,
                     font=fuentes.cuerpo, focuscolor=tema.superficie,
                     indicatorbackground=tema.superficie_alt,
                     indicatorforeground=tema.acento_texto,
                     bordercolor=tema.borde, lightcolor=tema.superficie,
                     darkcolor=tema.superficie, padding=4)
    estilo.map("TCheckbutton",
               background=[("active", tema.superficie)],
               indicatorbackground=[("selected", tema.acento), ("active", tema.superficie_alt)],
               bordercolor=[("selected", tema.acento)])

    # --- barras de desplazamiento ---------------------------------------
    # Sin flechas: el layout por defecto de clam las dibuja siempre.
    estilo.layout("Fina.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {
            "sticky": "ns",
            "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
        })
    ])
    estilo.configure("Fina.Vertical.TScrollbar", troughcolor=tema.fondo,
                     background=tema.borde, bordercolor=tema.fondo,
                     lightcolor=tema.borde, darkcolor=tema.borde,
                     arrowsize=0, width=8)
    estilo.map("Fina.Vertical.TScrollbar", background=[("active", tema.neutro)])

    # --- barra de progreso ----------------------------------------------
    estilo.configure("Fina.Horizontal.TProgressbar", troughcolor=tema.borde_suave,
                     background=tema.acento, bordercolor=tema.borde_suave,
                     lightcolor=tema.acento, darkcolor=tema.acento, thickness=3)
