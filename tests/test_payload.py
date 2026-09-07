"""Pruebas del formato que recibe rtslabelscale.dll.

Las expectativas salen de la cadena que la aplicacion original concatena antes
de llamar a rtscaleDownLoadPLU, no de suposiciones.
"""

from __future__ import annotations

import json

import pytest

from ibalance.config import Hotkeys
from ibalance.models import Plu
from ibalance.rongta.payload import (
    CLAVES_PLU,
    construir_hotkeys,
    construir_lotes_plu,
    plu_a_dict,
    serializar_lote,
)


@pytest.fixture
def plu() -> Plu:
    return Plu(codigo="002893", nombre="PITAHAYA ROJA X KG", precio=750, vida_util_dias=30)


def test_claves_y_orden_identicos_a_la_app_original(plu: Plu) -> None:
    assert tuple(plu_a_dict(plu)) == CLAVES_PLU


def test_conserva_las_erratas_del_fabricante(plu: Plu) -> None:
    """'ShlefTime' y 'Deptment' estan mal escritos en la DLL; corregirlos
    hace que la balanza ignore el campo en silencio."""
    objeto = plu_a_dict(plu)
    assert "ShlefTime" in objeto and "ShelfTime" not in objeto
    assert "Deptment" in objeto and "Department" not in objeto


def test_los_valores_numericos_no_van_entrecomillados(plu: Plu) -> None:
    objeto = plu_a_dict(plu)
    for clave in ("UnitPrice", "LFCode", "BarCode", "Code", "ShlefTime", "WeightUnit"):
        assert isinstance(objeto[clave], int), f"{clave} debe viajar como numero"
    assert isinstance(objeto["PluName"], str), "PluName es el unico campo de texto"


def test_vida_util_alimenta_shleftime(plu: Plu) -> None:
    assert plu_a_dict(plu)["ShlefTime"] == 30


def test_codigo_pierde_los_ceros_a_la_izquierda(plu: Plu) -> None:
    objeto = plu_a_dict(plu)
    assert objeto["LFCode"] == 2893
    assert objeto["Code"] == 2893


def test_los_acentos_no_se_escapan(plu: Plu) -> None:
    """La DLL recibe ANSI: un \\u00d1 escapado se imprimiria literal."""
    plu.nombre = "PIÑA X KG"
    assert "PIÑA" in serializar_lote([plu])
    assert "\\u00d1" not in serializar_lote([plu])


def test_el_json_es_valido(plu: Plu) -> None:
    datos = json.loads(serializar_lote([plu, plu]))
    assert len(datos) == 2


def test_formato_legacy_reproduce_la_cadena_original(plu: Plu) -> None:
    salida = serializar_lote([plu], formato_legacy=True)
    assert salida.startswith('[{"PackageWeight": 0,"PackageType": 0,')
    assert salida.endswith(",},]"), "la app original deja comas finales"


def test_ipack_es_la_cantidad_de_registros() -> None:
    """El tercer argumento de rtscaleDownLoadPLU es datos.Length, no un indice."""
    plus = [Plu(codigo=f"{i:06d}", nombre=f"P{i}", precio=100) for i in range(450)]
    lotes = construir_lotes_plu(plus, tamano_lote=200)
    assert [n for _, n in lotes] == [200, 200, 50]
    for texto, cantidad in lotes:
        assert len(json.loads(texto)) == cantidad


def test_lote_cero_envia_todo_junto() -> None:
    plus = [Plu(codigo=f"{i:06d}", nombre=f"P{i}", precio=100) for i in range(30)]
    lotes = construir_lotes_plu(plus, tamano_lote=0)
    assert len(lotes) == 1 and lotes[0][1] == 30


def test_hotkeys_en_tres_paginas_de_28() -> None:
    plus = [Plu(codigo=f"{i:06d}", nombre=f"P{i}", precio=100) for i in range(1, 200)]
    paginas = construir_hotkeys(plus, Hotkeys())
    assert len(paginas) == 3
    assert all(len(p) == 28 for p in paginas)
    assert paginas[0][0] == 1


def test_hotkeys_se_rellenan_con_ceros() -> None:
    plus = [Plu(codigo="000001", nombre="UNO", precio=100)]
    paginas = construir_hotkeys(plus, Hotkeys())
    assert paginas[0] == [1] + [0] * 27
    assert paginas[1] == [0] * 28


def test_hotkeys_respetan_el_orden_configurado() -> None:
    plus = [Plu(codigo=f"{i:06d}", nombre=f"P{i}", precio=100) for i in range(1, 10)]
    config = Hotkeys(codigos=["5", "3", "9"])
    paginas = construir_hotkeys(plus, config)
    assert paginas[0][:3] == [5, 3, 9]


def test_hotkeys_desactivadas_no_generan_paginas() -> None:
    assert construir_hotkeys([], Hotkeys(habilitado=False)) == []
