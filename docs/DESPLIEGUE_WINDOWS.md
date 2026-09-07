# Despliegue en Windows

## 1. El requisito que rompe todo lo demás: 32 bits

`rtslabelscale.dll` es de 32 bits. Windows **no puede** cargar una DLL de 32
bits en un proceso de 64 bits, y el mensaje que da no ayuda:

```
[WinError 193] %1 no es una aplicación Win32 válida
```

Por tanto:

- el Python que ejecute la aplicación debe ser **de 32 bits**;
- el `.exe` de PyInstaller debe compilarse con ese mismo Python de 32 bits.

Descargue *Windows installer (32-bit)* de python.org (3.10 o superior). Para
comprobarlo:

```powershell
python -c "import struct; print(struct.calcsize('P') * 8)"   # debe decir 32
```

`tools\build_exe.ps1` se niega a compilar si el intérprete no es de 32 bits, y
`ibalance check` avisa antes de intentar cargar la DLL.

## 2. Estructura recomendada

```
C:\ibalance\
    ibalance.exe            <- esta aplicación
    config.json
    rtslabelscale.dll       <- del fabricante (NO empaquetar dentro del .exe)
    RLS1000\                <- dependencias del fabricante
        rtslabelscale.dll   <- versión antigua: no la use como principal
        *.fnt, *.scr, DB\, imageformats\, ...
    logs\
        ibalance.log
        estado.json
        reportes\sync_AAAAMMDD_HHMMSS.json
```

La DLL se deja **suelta**, no dentro del `.exe`: busca sus dependencias por
ruta en disco y PyInstaller las extraería a un directorio temporal donde no las
encuentra.

## 3. Instalación

```powershell
# Desde el código
py -3.12-32 -m pip install -e .
ibalance init --config C:\ibalance\config.json
notepad C:\ibalance\config.json
ibalance -c C:\ibalance\config.json check

# O compilar el ejecutable
.\tools\build_exe.ps1 -Python "C:\Python312-32\python.exe"
```

`check` valida config, archivo de origen, arquitectura y exportaciones de la
DLL, y hace ping y sondeo de puerto a cada balanza. **Ejecútelo siempre antes
de la primera sincronización real.**

## 4. Prueba sin tocar las balanzas

```powershell
ibalance -c C:\ibalance\config.json preview --json
ibalance -c C:\ibalance\config.json sync --simular
```

El modo simulado escribe en `logs\simulacion\` exactamente los payloads que
recibiría la DLL. Sirve para validar precios y nombres antes de grabar nada.

## 5. Sincronización automática

Dos opciones:

**Interfaz gráfica** — pestaña *Actividad* → *Iniciar automático*. Usa el
intervalo de `sincronizacion.intervalo_minutos`.

**Programador de tareas de Windows** (recomendado si el equipo no tiene sesión
abierta): tarea que ejecute

```
C:\ibalance\ibalance.exe -c C:\ibalance\config.json sync -q
```

Devuelve `0` si todas las balanzas quedaron al día y `1` si alguna falló, así
que el Programador puede reintentar. `-q` evita la consola.

## 6. El puerto 4000 y la aplicación antigua

La versión anterior (`ibalance.exe` en C#/ClickOnce) a veces queda residente
después de cerrar su ventana y **retiene la única conexión** que admite la
balanza. Síntoma: todas las balanzas dan «no aceptó la conexión» aunque
respondan al ping.

```powershell
tasklist | findstr /i ibalance
taskkill /F /IM ibalance.exe
```

Para automatizarlo, en `config.json`:

```json
"sincronizacion": {
  "cerrar_procesos_legacy": true,
  "procesos_legacy": ["ibalance.exe"]
}
```

Está **desactivado por defecto**: cerrar procesos ajenos es intrusivo y solo
debe hacerse si el operador lo decide. `ibalance check` avisa cuando detecta la
aplicación antigua en memoria, aunque la opción esté apagada.

Ojo con el nombre: si compila esta aplicación también como `ibalance.exe`, se
cerraría a sí misma. Use otro nombre, o ponga en la lista el nombre real del
ejecutable antiguo.

## 7. Cuando una balanza queda con datos corruptos

Pestaña *Balanzas* → **Forzar limpieza** en esa balanza, o:

```powershell
ibalance -c C:\ibalance\config.json clear -b 3
```

Llama a `rtscaleClearPLUData`, borra el catálogo completo y olvida su huella,
de modo que la siguiente corrida le reenvía todo desde cero.

## 8. Diagnóstico

| Síntoma | Dónde mirar |
|---|---|
| `[WinError 193]` | `ibalance check` → arquitectura de DLL y Python |
| «no se encuentra el módulo» al cargar la DLL | falta `RLS1000\` o el Visual C++ Runtime |
| Todas las balanzas rechazan la conexión | aplicación antigua residente (sección 6) |
| Una balanza no responde al ping | red, VLAN o balanza apagada |
| La balanza acepta todo pero no cambia nada | `ipack`: ver `docs/DLL_RTSLABELSCALE.md` §3.3 |
| Precios en cero en la etiqueta | campos numéricos enviados como texto: §3.2 |
| Vencimientos equivocados | `ShlefTime`: ver `docs/FORMATO_CADTXT.md` |

Cada corrida deja un reporte JSON en `logs\reportes\` con el detalle por
balanza: intentos, lotes enviados, duración y el mensaje exacto del fallo.
