<#
.SYNOPSIS
    Compila los ejecutables de ibalance 2 en el equipo local.

.DESCRIPTION
    Normalmente NO hace falta: cada etiqueta v* publica los ejecutables ya
    compilados en la pestaña Releases del repositorio, y el flujo de
    integracion continua garantiza que salgan de un Python de 32 bits.
    Este script es para compilar sin pasar por GitHub.

    rtslabelscale.dll es de 32 bits, y Windows no puede cargar una DLL de 32
    bits en un proceso de 64 bits: el script se niega a compilar con un
    interprete que no sea x86, en vez de dejar que el error [WinError 193]
    aparezca en la tienda.

.EXAMPLE
    .\tools\build_exe.ps1 -Python "C:\Python312-32\python.exe"
#>
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot

$bits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($bits.Trim() -ne "32") {
    Write-Error @"
El interprete '$Python' es de $bits bits.

rtslabelscale.dll es de 32 bits y solo carga en un proceso de 32 bits.
Instale Python 3.10+ de 32 bits ('Windows installer (32-bit)' en python.org) y
vuelva a ejecutar:

    .\tools\build_exe.ps1 -Python "C:\Python312-32\python.exe"
"@
}

Write-Host "Python de 32 bits detectado. Preparando entorno..." -ForegroundColor Green
& $Python -m pip install --upgrade pip pyinstaller | Out-Null

Push-Location $raiz
try {
    # Dos ejecutables: el de ventana no tiene consola y no podria mostrar la
    # salida de 'check' ni de 'sync'; el de consola sirve para diagnostico y
    # para el Programador de tareas.
    & $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name ibalance2 --paths src --collect-submodules ibalance `
        tools/entrada.py

    & $Python -m PyInstaller --noconfirm --clean --onefile --console `
        --name ibalance2-consola --paths src --collect-submodules ibalance `
        tools/entrada.py

    Copy-Item config.example.json dist/config.json -Force
    Copy-Item tools/LEEME.txt     dist/ -Force
    Copy-Item tools/instalar.ps1  dist/ -Force

    Write-Host ""
    Write-Host "Listo: dist\ibalance2.exe y dist\ibalance2-consola.exe" -ForegroundColor Green
    Write-Host "NO empaquete rtslabelscale.dll dentro del .exe: debe quedar suelta"
    Write-Host "junto a su carpeta RLS1000, tal como la entrega el fabricante."
}
finally {
    Pop-Location
}
