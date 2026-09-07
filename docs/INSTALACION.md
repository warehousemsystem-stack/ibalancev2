# Instrucciones de instalación

Documento pensado para entregárselo a quien vaya a instalar la aplicación en el
equipo de la tienda: una persona o un asistente con acceso a esa máquina. Es
autocontenido; no hace falta leer el resto del repositorio.

---

## 0. Qué es esto y qué NO hay que hacer

`ibalance 2` envía el catálogo de productos (PLU) del ERP a las balanzas
etiquetadoras **Rongta RLS-1000/1100** de la tienda.

No se comunica por sockets propios: usa la librería nativa del fabricante
**`rtslabelscale.dll`**, que es **de 32 bits**. De ahí las tres reglas que hay
que respetar:

| No haga esto | Por qué |
|---|---|
| Compilar o ejecutar con Python de **64 bits** | Windows no puede cargar una DLL de 32 bits en un proceso de 64. Da `[WinError 193]`. El `.exe` que se descarga ya viene compilado en 32 bits, así que basta con no recompilarlo. |
| Meter `rtslabelscale.dll` **dentro** del `.exe` | La DLL busca sus dependencias por ruta en disco. Debe quedar suelta, junto a su carpeta `RLS1000`, tal como la entrega el fabricante. |
| Borrar o mover `C:\ibalance\RLS1000\` | Son las dependencias de la DLL (fuentes, plantillas de etiqueta, base de datos). |
| Renombrar el ejecutable a `ibalance.exe` | Ese es el nombre de la **aplicación antigua**, en C#. Conviven; confundirlos causa problemas. |

**Requisitos de la máquina**: Windows 7 o superior. Nada más. El `.exe` lleva
Python dentro: **no hay que instalar Python**.

---

## 1. Descargar el paquete

El repositorio es privado, así que la descarga exige estar identificado en
GitHub con la cuenta propietaria.

**Opción A — desde una release** (preferible, el enlace es permanente):

1. Vaya a `https://github.com/warehousemsystem-stack/ibalancev2/releases`
2. Descargue `ibalance2-windows-x86.zip` de la versión más reciente.

Si todavía no hay ninguna release publicada, créela una vez: *Releases* →
*Draft a new release* → *Choose a tag* → escriba `v1.0.0` → *Create new tag* →
*Publish release*. La compilación se dispara sola y adjunta el zip en unos
minutos.

**Opción B — desde la última compilación** (si no hay release):

1. Vaya a `https://github.com/warehousemsystem-stack/ibalancev2/actions`
2. Abra la ejecución más reciente de **«Compilar ejecutable»** que aparezca en
   verde.
3. Al final de la página, en *Artifacts*, descargue **`ibalance2-windows-x86`**.
4. Ese archivo es un zip que contiene otro zip: descomprima los dos.

---

## 2. Instalar

1. Descomprima el paquete. Debe contener:

   ```
   ibalance2.exe            la aplicación (ventana)
   ibalance2-consola.exe    la misma, en consola
   config.json              configuración de ejemplo
   instalar.ps1             instalador opcional
   LEEME.txt                guía breve
   docs\                    documentación
   ```

2. Copie **todo** el contenido a `C:\ibalance`

   Esa carpeta suele existir ya, porque es donde vive la librería del
   fabricante. **No borre lo que haya**: `rtslabelscale.dll` y la carpeta
   `RLS1000` tienen que seguir ahí. La estructura final debe quedar así:

   ```
   C:\ibalance\
       ibalance2.exe            <- nuevo
       ibalance2-consola.exe    <- nuevo
       config.json              <- nuevo
       rtslabelscale.dll        <- del fabricante, YA ESTABA
       RLS1000\                 <- del fabricante, YA ESTABA
       logs\                    <- se crea solo
   ```

   Si `C:\ibalance` no existe, créela y copie ahí la aplicación; en el paso 3
   se indicará dónde está la DLL.

3. Opcionalmente, en PowerShell **como administrador**, desde esa carpeta:

   ```powershell
   .\instalar.ps1 -CrearTarea -Intervalo 60
   ```

   Crea el acceso directo en el escritorio y programa la sincronización
   automática cada 60 minutos. Es idempotente y **no sobrescribe un
   `config.json` existente**, así que sirve también para actualizar.

---

## 3. Configurar (2 minutos, desde la ventana)

Doble clic en **`ibalance2.exe`**.

La primera vez crea su `config.json`, busca sola la DLL y muestra una tarjeta
**«Puesta en marcha»** con tres puntos pendientes:

| Punto | Qué hacer |
|---|---|
| **Archivo de productos** | Botón *Elegir*. Seleccione el `cadtxt.txt` que exporta el ERP (suele estar en una unidad de red, p. ej. `X:\cadtxt.txt`). |
| **Librería rtslabelscale.dll** | Normalmente ya aparece en verde. Si no, *Buscar* y señale `C:\ibalance\rtslabelscale.dll`. **Elija la de `C:\ibalance`, no la de `C:\ibalance\RLS1000`**: son archivos distintos con el mismo nombre y la de `RLS1000` es una versión más antigua. |
| **Balanzas activas con IP** | *Configurar*. Por cada balanza: marque **Activa** y escriba su **IP**. El puerto es 4000 salvo que el instalador lo cambiara. Pulse *Guardar*. |

La tarjeta desaparece sola cuando los tres están resueltos. No hay que editar
ningún archivo a mano.

---

## 4. Verificar ANTES de tocar las balanzas

Este paso no es opcional. Abra PowerShell en `C:\ibalance`:

```powershell
# 1. Valida configuración, arquitectura de la DLL, y hace ping a cada balanza
.\ibalance2-consola.exe check

# 2. Genera los datos EXACTOS que recibirían las balanzas, sin enviarlos.
#    Quedan en logs\simulacion\ para poder revisarlos.
.\ibalance2-consola.exe sync --simular

# 3. Primera prueba real: UNA sola balanza
.\ibalance2-consola.exe sync -b 1
```

`check` debe terminar en **«Sin problemas bloqueantes»**. Si dice otra cosa,
resuélvalo antes de seguir; el apartado 6 cubre los casos habituales.

Sólo cuando la balanza 1 haya salido bien, sincronice todas:

```powershell
.\ibalance2-consola.exe sync
```

Devuelve `0` si todas quedaron al día y `1` si alguna falló.

---

## 5. Sincronización automática

**Desde la ventana**: botón *Automatico* en la barra superior. Usa el intervalo
configurado en *Ajustes*. Requiere que la aplicación quede abierta.

**Como tarea de Windows** (funciona sin la ventana abierta, es lo recomendable
en un equipo de tienda):

```powershell
.\instalar.ps1 -CrearTarea -Intervalo 60
```

O manualmente, en el Programador de tareas, con esta acción:

```
Programa:    C:\ibalance\ibalance2-consola.exe
Argumentos:  -c "C:\ibalance\config.json" sync -q
Iniciar en:  C:\ibalance
```

Use el ejecutable **de consola**: el de ventana abriría la interfaz en cada
disparo.

---

## 6. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `[WinError 193] no es una aplicación Win32 válida` | Se está ejecutando algo de 64 bits contra una DLL de 32. Use el `ibalance2.exe` del paquete, que ya viene en 32 bits; no lo recompile. |
| Al cargar la DLL: «no se encuentra el módulo» | Falta la carpeta `RLS1000` junto a la DLL, o el Visual C++ Runtime. Restaure la carpeta del fabricante. |
| **Todas** las balanzas dan «no aceptó la conexión», pero responden al ping | La aplicación antigua (`ibalance.exe`, la de C#) quedó residente en segundo plano y retiene la única conexión que admite cada balanza. Ciérrela: `taskkill /F /IM ibalance.exe`. Para que se cierre sola antes de cada corrida, marque la casilla correspondiente en *Ajustes*. |
| Una balanza concreta no responde al ping | Red, VLAN o balanza apagada. No es un problema de la aplicación. |
| La balanza acepta todo pero no cambia nada | Revise `logs\reportes\` y contraste con `docs\DLL_RTSLABELSCALE.md` §3.3. |
| Precios en cero en la etiqueta | Campos numéricos enviados como texto. Ver `docs\DLL_RTSLABELSCALE.md` §3.2. |
| Fechas de vencimiento equivocadas | El campo de vida útil. Ver `docs\FORMATO_CADTXT.md`. |
| Una balanza quedó con datos corruptos | Vista *Balanzas* → botón **Vaciar** de esa balanza. Borra su catálogo; después sincronice de nuevo. |

**Dónde mirar siempre**: `C:\ibalance\logs\ibalance.log` para el detalle
cronológico, y `C:\ibalance\logs\reportes\sync_AAAAMMDD_HHMMSS.json` para el
resultado por balanza de cada corrida (intentos, lotes enviados, duración y el
mensaje exacto del fallo).

---

## 7. Qué reportar si hay que pedir ayuda

Adjunte estas tres cosas; con menos no se puede diagnosticar:

1. La salida completa de `.\ibalance2-consola.exe check`
2. El archivo `logs\ibalance.log`
3. El reporte más reciente de `logs\reportes\`

Y la información de la librería, que se obtiene con:

```powershell
.\ibalance2-consola.exe dll
```

---

## 8. Aviso importante sobre el estado del proyecto

La aplicación está probada de extremo a extremo con el archivo real de
producción (1.839 productos, 6 balanzas) usando un backend simulado, y el
formato de los datos está reconstruido a partir de la aplicación original en
.NET, no de suposiciones (ver `docs\DLL_RTSLABELSCALE.md`).

**Lo que no se ha podido probar es el envío a balanzas físicas.** Por eso el
apartado 4 insiste en sincronizar primero **una sola balanza**. Si esa primera
corrida real devuelve un código distinto de `0`, guarde lo que indica el
apartado 7 antes de seguir intentando: ahí aparece el código exacto que devuelve
la DLL en cada llamada, que es lo que hace falta para ajustar `codigo_exito` o
`formato_legacy` en `config.json` si el firmware de esas balanzas se comporta
distinto.
