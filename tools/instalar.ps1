<#
.SYNOPSIS
    Instala ibalance 2 en C:\ibalance y, opcionalmente, crea la tarea programada.

.DESCRIPTION
    No hace falta para usar la aplicacion: basta con doble clic en
    ibalance2.exe. Este script sirve para dejarla instalada como toca en un
    equipo de tienda: carpeta fija, acceso directo en el escritorio y
    sincronizacion automatica aunque nadie abra la ventana.

    Es idempotente: se puede volver a ejecutar sobre una instalacion existente
    para actualizar el ejecutable, y no pisa el config.json que ya haya.

.EXAMPLE
    .\instalar.ps1
    Copia la aplicacion a C:\ibalance y crea el acceso directo.

.EXAMPLE
    .\instalar.ps1 -CrearTarea -Intervalo 60
    Ademas programa una sincronizacion cada 60 minutos.

.EXAMPLE
    .\instalar.ps1 -Destino "D:\ibalance" -SinAccesoDirecto
#>
[CmdletBinding()]
param(
    [string]$Destino = "C:\ibalance",
    [switch]$CrearTarea,
    [int]$Intervalo = 60,
    [switch]$SinAccesoDirecto
)

$ErrorActionPreference = "Stop"
$origen = $PSScriptRoot

function Escribir($texto, $color = "Gray") { Write-Host "  $texto" -ForegroundColor $color }

Write-Host ""
Write-Host "Instalando ibalance 2" -ForegroundColor Cyan
Write-Host "---------------------"

# --- 1. Carpeta destino ----------------------------------------------------
if (-not (Test-Path $Destino)) {
    New-Item -ItemType Directory -Path $Destino -Force | Out-Null
    Escribir "Creada la carpeta $Destino" "Green"
} else {
    Escribir "La carpeta $Destino ya existe"
}

# --- 2. Ejecutables --------------------------------------------------------
$ejecutables = @("ibalance2.exe", "ibalance2-consola.exe")
foreach ($nombre in $ejecutables) {
    $ruta = Join-Path $origen $nombre
    if (-not (Test-Path $ruta)) {
        throw "No se encontro $nombre junto a este script. Ejecutelo desde la carpeta descomprimida."
    }
    Copy-Item $ruta $Destino -Force
    Escribir "Copiado $nombre" "Green"
}

foreach ($extra in @("LEEME.txt")) {
    $ruta = Join-Path $origen $extra
    if (Test-Path $ruta) { Copy-Item $ruta $Destino -Force }
}
$docs = Join-Path $origen "docs"
if (Test-Path $docs) {
    Copy-Item $docs $Destino -Recurse -Force
    Escribir "Copiada la documentacion"
}

# --- 3. Configuracion ------------------------------------------------------
# El config guarda las IP de las balanzas y la ruta del archivo del ERP:
# sobrescribirlo en una actualizacion obligaria a reconfigurar la tienda.
$configDestino = Join-Path $Destino "config.json"
if (Test-Path $configDestino) {
    Escribir "Se conserva el config.json existente" "Yellow"
} else {
    $configOrigen = Join-Path $origen "config.json"
    if (Test-Path $configOrigen) {
        Copy-Item $configOrigen $configDestino
        Escribir "Copiado config.json" "Green"
    }
}

# --- 4. Comprobar la libreria del fabricante -------------------------------
$dll = Join-Path $Destino "rtslabelscale.dll"
if (Test-Path $dll) {
    Escribir "rtslabelscale.dll encontrada en el destino" "Green"
} else {
    Escribir "AVISO: no hay rtslabelscale.dll en $Destino" "Yellow"
    Escribir "       Copie la del fabricante junto a su carpeta RLS1000," "Yellow"
    Escribir "       o indique su ubicacion desde la ventana de la aplicacion." "Yellow"
}

# --- 5. Acceso directo -----------------------------------------------------
if (-not $SinAccesoDirecto) {
    $escritorio = [Environment]::GetFolderPath("Desktop")
    $enlace = Join-Path $escritorio "ibalance 2.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $acceso = $shell.CreateShortcut($enlace)
    $acceso.TargetPath = Join-Path $Destino "ibalance2.exe"
    $acceso.WorkingDirectory = $Destino
    $acceso.Description = "Sincronizacion de balanzas Rongta"
    $acceso.Save()
    Escribir "Acceso directo creado en el escritorio" "Green"
}

# --- 6. Tarea programada ---------------------------------------------------
if ($CrearTarea) {
    $nombreTarea = "ibalance2 - sincronizacion"
    # Se usa el ejecutable de consola: el de ventana abriria la interfaz en
    # cada disparo. -q evita que aparezca texto en pantalla.
    $accion = New-ScheduledTaskAction `
        -Execute (Join-Path $Destino "ibalance2-consola.exe") `
        -Argument "-c `"$configDestino`" sync -q" `
        -WorkingDirectory $Destino

    $disparador = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes $Intervalo)

    $opciones = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -DontStopOnIdleEnd `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    try {
        Register-ScheduledTask -TaskName $nombreTarea -Action $accion `
            -Trigger $disparador -Settings $opciones -Force `
            -Description "Envia el catalogo de productos a las balanzas Rongta" | Out-Null
        Escribir "Tarea programada cada $Intervalo minutos" "Green"
    } catch {
        Escribir "No se pudo crear la tarea: $_" "Red"
        Escribir "Ejecute PowerShell como administrador para poder crearla." "Yellow"
    }
}

Write-Host ""
Write-Host "Listo." -ForegroundColor Green
Write-Host "  Abra la aplicacion desde el acceso directo, o ejecute:"
Write-Host "      $Destino\ibalance2.exe"
Write-Host ""
Write-Host "  Antes de la primera sincronizacion real conviene un ensayo:"
Write-Host "      $Destino\ibalance2-consola.exe -c `"$configDestino`" check"
Write-Host "      $Destino\ibalance2-consola.exe -c `"$configDestino`" sync --simular"
Write-Host ""
