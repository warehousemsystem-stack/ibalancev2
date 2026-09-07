<#
.SYNOPSIS
    Compila ibalance.exe con PyInstaller.

.DESCRIPTION
    rtslabelscale.dll es de 32 bits, y Windows no puede cargar una DLL de 32
    bits en un proceso de 64 bits: el .exe TIENE que compilarse con un Python
    de 32 bits o fallara en el cliente con [WinError 193]. El script comprueba
    la arquitectura antes de empezar en vez de dejar que el error aparezca en
    produccion.

.EXAMPLE
    .\tools\build_exe.ps1 -Python "C:\Python312-32\python.exe"
#>
param(
    [string]$Python = "python",
    [switch]$Consola   # deja la consola visible (util para depurar)
)

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot

$bits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($bits.Trim() -ne "32") {
    Write-Error @"
El interprete '$Python' es de $bits bits.

rtslabelscale.dll es de 32 bits y solo carga en un proceso de 32 bits.
Instale Python 3.10+ de 32 bits (el instalador 'Windows installer (32-bit)'
de python.org) y vuelva a ejecutar:

    .\tools\build_exe.ps1 -Python "C:\Python312-32\python.exe"
"@
}

Write-Host "Python de 32 bits detectado. Preparando entorno..." -ForegroundColor Green
& $Python -m pip install --upgrade pip pyinstaller | Out-Null

$modo = if ($Consola) { "--console" } else { "--windowed" }

Push-Location $raiz
try {
    & $Python -m PyInstaller `
        --noconfirm --clean --onefile $modo `
        --name ibalance `
        --paths src `
        --hidden-import ibalance.gui.app `
        --collect-submodules ibalance `
        src/ibalance/__main__.py

    Copy-Item config.example.json dist/config.json -Force
    Write-Host ""
    Write-Host "Listo: dist\ibalance.exe" -ForegroundColor Green
    Write-Host "Copie dist\ibalance.exe y dist\config.json a C:\ibalance y edite el config."
    Write-Host "NO empaquete rtslabelscale.dll dentro del .exe: debe quedar suelta"
    Write-Host "junto a su carpeta RLS1000, tal como la entrega el fabricante."
}
finally {
    Pop-Location
}
