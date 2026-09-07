"""Pruebas del lector de cadtxt.txt."""

from __future__ import annotations

from pathlib import Path

import pytest

from ibalance.config import Origen
from ibalance.sources import leer
from ibalance.sources.base import OrigenError

MUESTRA = Path(__file__).parent / "data" / "cadtxt_sample.txt"


@pytest.fixture
def origen() -> Origen:
    return Origen(ruta=str(MUESTRA))


def test_lee_los_campos_en_sus_posiciones(origen: Origen) -> None:
    lectura = leer(origen)
    primero = lectura.plus[0]
    assert primero.codigo == "002893"
    assert primero.nombre == "**PITAHAYA ROJA X KG**"
    assert primero.precio == 750
    assert primero.vida_util_dias == 0
    assert primero.pesable is True


def test_vida_util_sale_de_las_tres_ultimas_posiciones(origen: Origen) -> None:
    """El campo 36..38 son dias de vida util, no el departamento.

    La aplicacion anterior lo mandaba como 'Deptment' y fijaba ShlefTime en 15
    para todo, con lo que los perecederos salian con vencimiento equivocado.
    """
    lectura = leer(origen)
    por_codigo = {p.codigo: p for p in lectura.plus}
    assert por_codigo["000714"].vida_util_dias == 60
    assert por_codigo["002937"].vida_util_dias == 365
    assert por_codigo["009473"].vida_util_dias == 1


def test_precio_se_interpreta_en_centimos(origen: Origen) -> None:
    lectura = leer(origen)
    assert lectura.plus[0].precio_formateado() == "7.50"


def test_descarta_lineas_invalidas_sin_abortar(origen: Origen) -> None:
    lectura = leer(origen)
    codigos = {p.codigo for p in lectura.plus}
    assert "000001" not in codigos, "precio cero descartado"
    assert "000002" not in codigos, "nombre vacio descartado"
    assert "000003" not in codigos, "linea corta descartada"
    assert len(lectura.incidencias) >= 4
    assert lectura.plus, "las lineas malas no pueden dejar la corrida sin productos"


def test_codigo_repetido_conserva_el_ultimo(origen: Origen) -> None:
    lectura = leer(origen)
    repetidos = [p for p in lectura.plus if p.codigo == "000714"]
    assert len(repetidos) == 1
    assert repetidos[0].precio == 999


def test_precio_minimo_configurable(origen: Origen) -> None:
    origen.precio_minimo = 0
    lectura = leer(origen)
    assert any(p.codigo == "000001" for p in lectura.plus)


def test_nombre_se_recorta_al_ancho_de_la_etiqueta(origen: Origen) -> None:
    origen.nombre_ancho_max = 10
    lectura = leer(origen)
    assert all(len(p.nombre) <= 10 for p in lectura.plus)


def test_layout_configurable(origen: Origen) -> None:
    """Otra tienda puede exportar el mismo archivo con otros anchos."""
    origen.layout.precio = [29, 34]      # cinco digitos en vez de siete
    origen.layout.vida_util_dias = [34, 37]
    lectura = leer(origen)
    por_codigo = {p.codigo: p for p in lectura.plus}
    # "0003062365" leido como 29..33 = "00030" y 34..36 = "623"
    assert por_codigo["002937"].precio == 30
    assert por_codigo["002937"].vida_util_dias == 623


def test_archivo_ausente_da_error_claro(tmp_path: Path) -> None:
    with pytest.raises(OrigenError, match="No se encontro"):
        leer(Origen(ruta=str(tmp_path / "no_existe.txt")))


def test_huella_cambia_con_el_contenido(tmp_path: Path, origen: Origen) -> None:
    copia = tmp_path / "copia.txt"
    copia.write_bytes(MUESTRA.read_bytes())
    igual = leer(Origen(ruta=str(copia)))
    assert igual.huella == leer(origen).huella

    copia.write_bytes(MUESTRA.read_bytes() + b"\n")
    assert leer(Origen(ruta=str(copia))).huella != igual.huella
