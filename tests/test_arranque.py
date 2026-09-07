"""Pruebas del arranque: doble clic, primer uso y empaquetado.

Cubren fallos que solo se manifiestan en el ejecutable compilado, donde no hay
consola donde leer el error.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ibalance import cli, procesos
from ibalance.config import autodetectar_dll, preparar_primer_arranque

RAIZ = Path(__file__).resolve().parents[1]


def test_sin_argumentos_abre_la_ventana(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doble clic en el .exe no puede terminar en un mensaje de uso."""
    llamado: dict[str, object] = {}

    def falso_gui(args):
        llamado["comando"] = args.comando
        return 0

    monkeypatch.setattr(cli, "cmd_gui", falso_gui)
    # El parser resuelve func en tiempo de construccion, asi que hay que
    # interceptar sobre el Namespace ya montado.
    parser = cli.construir_parser()
    args = parser.parse_args(["gui"])
    assert args.comando == "gui"

    monkeypatch.setattr(sys, "argv", ["ibalance2.exe"])
    monkeypatch.setattr(cli, "construir_parser", lambda: parser)
    parser.set_defaults(func=falso_gui)
    assert cli.main() == 0
    assert llamado["comando"] == "gui"


def test_los_subcomandos_siguen_funcionando() -> None:
    parser = cli.construir_parser()
    assert parser.parse_args(["check"]).comando == "check"
    assert parser.parse_args(["sync", "--simular"]).simular is True


def test_primer_arranque_crea_la_configuracion(tmp_path: Path) -> None:
    ruta = tmp_path / "config.json"
    config, nuevo = preparar_primer_arranque(ruta)
    assert nuevo is True
    assert ruta.is_file()
    assert len(config.balanzas) == 12
    config.validar()


def test_segundo_arranque_no_pisa_la_configuracion(tmp_path: Path) -> None:
    """El config guarda las IP de la tienda: recrearlo seria perderlas."""
    ruta = tmp_path / "config.json"
    config, _ = preparar_primer_arranque(ruta)
    config.balanzas[0].ip = "10.46.18.99"
    config.balanzas[0].activa = True
    config.guardar(ruta)

    recargada, nuevo = preparar_primer_arranque(ruta)
    assert nuevo is False
    assert recargada.balanzas[0].ip == "10.46.18.99"


def test_autodeteccion_encuentra_la_dll_junto_al_ejecutable(tmp_path: Path) -> None:
    (tmp_path / "rtslabelscale.dll").write_bytes(b"MZ")
    assert autodetectar_dll(tmp_path) == str(tmp_path / "rtslabelscale.dll")


def test_autodeteccion_prefiere_la_dll_principal(tmp_path: Path) -> None:
    """La de RLS1000 es otra version, con menos exportaciones."""
    (tmp_path / "RLS1000").mkdir()
    (tmp_path / "RLS1000" / "rtslabelscale.dll").write_bytes(b"MZ")
    (tmp_path / "rtslabelscale.dll").write_bytes(b"MZ")
    assert autodetectar_dll(tmp_path) == str(tmp_path / "rtslabelscale.dll")


def test_autodeteccion_sin_dll(tmp_path: Path) -> None:
    assert autodetectar_dll(tmp_path) in ("", *(str(p) for p in tmp_path.iterdir()))


def test_nunca_se_cierra_a_si_mismo(monkeypatch: pytest.MonkeyPatch) -> None:
    """La opcion de cerrar la app antigua no puede matar a esta aplicacion."""
    monkeypatch.setattr(procesos, "_nombre_propio", lambda: "ibalance2.exe")
    monkeypatch.setattr(procesos.os, "name", "nt")
    assert procesos.procesos_activos(["ibalance2.exe"]) == []
    assert procesos.cerrar_procesos(["ibalance2.exe"]) == []


def test_el_punto_de_entrada_de_pyinstaller_usa_imports_absolutos() -> None:
    """PyInstaller ejecuta el script de entrada como modulo suelto.

    Con un import relativo el ejecutable arranca y muere con «attempted
    relative import with no known parent package», sin consola donde leerlo.
    """
    import ast

    arbol = ast.parse((RAIZ / "tools" / "entrada.py").read_text(encoding="utf-8"))
    relativos = [
        n for n in ast.walk(arbol)
        if isinstance(n, ast.ImportFrom) and n.level > 0
    ]
    assert not relativos, "el punto de entrada no puede usar imports relativos"
    modulos = {
        n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert "ibalance.cli" in modulos


def test_el_punto_de_entrada_arranca_de_verdad() -> None:
    """Se ejecuta como script suelto, igual que hara PyInstaller."""
    resultado = subprocess.run(
        [sys.executable, str(RAIZ / "tools" / "entrada.py"), "--version"],
        capture_output=True, text=True, timeout=60,
        env={"PYTHONPATH": str(RAIZ / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "ibalance" in resultado.stdout
