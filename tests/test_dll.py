"""Pruebas del envoltorio de la DLL que no requieren Windows."""

from __future__ import annotations

from pathlib import Path

import pytest

from ibalance.rongta.dll import (
    FUNCIONES,
    RtsLabelScaleDLL,
    arquitectura_pe,
    arquitectura_proceso,
    diagnostico,
    listar_exportaciones,
)
from ibalance.rongta.errors import DllNoEncontradaError


def test_dll_ausente_da_instrucciones(tmp_path: Path) -> None:
    backend = RtsLabelScaleDLL(tmp_path / "rtslabelscale.dll")
    with pytest.raises(DllNoEncontradaError, match="No se encontro la DLL"):
        backend.abrir()


def test_arquitectura_del_proceso() -> None:
    assert arquitectura_proceso() in (32, 64)


def test_archivo_que_no_es_pe(tmp_path: Path) -> None:
    falsa = tmp_path / "rtslabelscale.dll"
    falsa.write_bytes(b"no soy una dll")
    assert arquitectura_pe(falsa) is None
    with pytest.raises(DllNoEncontradaError, match="no es un ejecutable"):
        listar_exportaciones(falsa)


def test_diagnostico_de_archivo_ausente(tmp_path: Path) -> None:
    info = diagnostico(tmp_path / "no_existe.dll")
    assert info["existe"] is False
    assert info["arquitectura_python"] == arquitectura_proceso()


def test_lista_de_funciones_obligatorias() -> None:
    assert set(FUNCIONES) == {
        "rtscaleConnect",
        "rtscaleDisConnect",
        "rtscaleDownLoadPLU",
        "rtscaleDownLoadHotkey",
        "rtscaleClearPLUData",
    }
