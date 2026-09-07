# `rtslabelscale.dll` — lo que se sabe y de dónde salió

El fabricante no publica documentación de esta librería. Todo lo que hay aquí
está reconstruido a partir de dos fuentes verificables:

1. **La propia DLL** (`C:\ibalance\rtslabelscale.dll`): cabecera PE y tabla de
   exportaciones, leídas con `tools/inspect_dll.py`.
2. **La aplicación original** `ibalance.exe` 1.0.0.84 (.NET, ClickOnce): tablas
   de metadatos `ImplMap` (declaraciones P/Invoke) y `MethodDef`, más el
   cuerpo IL de los métodos que arman el envío.

Cuando algo de este documento no esté verificado, se dice explícitamente.

---

## 1. Identidad del binario

| Dato | Valor |
|---|---|
| Arquitectura | **x86 (32 bits)** |
| Compilador | Delphi / RAD Studio (exporta `TMethodImplementationIntercept`, `__dbk_fcall_wrapper`, `dbkFCallWrapperAddr`) |
| Convención | **`stdcall`** en las 9 funciones que usa la aplicación |
| Cadenas | **ANSI** (`CharSet` sin especificar en P/Invoke ⇒ ANSI) |
| Exportaciones | 78 en `C:\ibalance\`, 55 en `C:\ibalance\RLS1000\` |

### 1.1 Hay dos DLL con el mismo nombre

`C:\ibalance\rtslabelscale.dll` y `C:\ibalance\RLS1000\rtslabelscale.dll` son
**archivos distintos** (MD5 distinto, 78 contra 55 exportaciones). La de
`RLS1000\` es más antigua y **no exporta `rtscaleDownLoadDeletePlu`**.

Consecuencia práctica: cargue siempre por ruta absoluta, y ponga
`C:\ibalance` **antes** que `C:\ibalance\RLS1000` en el `PATH`. La aplicación
lo hace en `RtsLabelScaleDLL._preparar_dependencias`, y `ibalance dll` informa
cuál está viendo.

---

## 2. Firmas (tabla `MethodDef` de `ibalance.exe`)

```c
int rtscaleLoadIniFile(char* configFile);
int rtscaleConnect(char* addr, int baudRate, char* connId);
int rtscaleDisConnect(char* connId);
int rtscaleClearPLUData(char* connId);
int rtscaleDownLoadPLU(char* connId, char* pluJson, int ipack);
int rtscaleDownLoadHotkey(char* connId, int* hotkeyTable, int tableIndex);
int rtscaleDownLoadDeletePlu(int connId, int lfCode);   /* connId entero, no cadena */
int rtscaleGetScaleType(char* connId, char* retJson, int len);
int rtscaleUploadPluData(char* connId, void* records);
```

Todas devuelven `int`; `0` es éxito (configurable en `rongta.codigo_exito`).

Nótese la inconsistencia del fabricante en `rtscaleDownLoadDeletePlu`: ahí el
identificador de conexión es un **entero**, mientras que en el resto es una
cadena. Se replica tal cual.

### 2.1 `stdcall`, no `cdecl`

Los metadatos declaran `pmCallConvStdcall`, es decir `ctypes.WinDLL`.
Usar `ctypes.CDLL` en x86 desbalancea la pila: no falla en el momento, falla
varias llamadas después y en otro sitio. El envoltorio acepta
`convencion_llamada: "auto"`, que carga los dos manejadores y usa el
`ValueError` que ctypes lanza al detectar el desbalance para quedarse con el
bueno.

---

## 3. El JSON de PLU

### 3.1 Esquema real

Del DTO `EgoDeno.funciones.Romgta.PluDataRomgta`:

| Campo | Tipo .NET | Origen en `cadtxt.txt` |
|---|---|---|
| `PluName` | `string` | nombre (posiciones 7–28) |
| `Code` | `string` | código sin ceros a la izquierda |
| `LFCode` | `int` | ídem |
| `BarCode` | `int` | ídem |
| `UnitPrice` | `int` | precio en céntimos (29–35) |
| `ShlefTime` | `int` | vida útil en días (36–38) |
| `Deptment` | `int` | configurable |
| `WeightUnit` | `int` | configurable |
| `Tare` | `double` | configurable |
| `PackageWeight` | `double` | configurable |
| `PackageType`, `Tolerance`, `Message1`, `QtyUnit`, `Account` | `int` | configurables |
| `Message2`, `Reserved2`, `LabelId`, `Rebate` | `byte` | configurables |
| `HotKey` | `int` | sin usar por la app original |

### 3.2 Cadena que emite la aplicación original

```
[{"PackageWeight": 0,"PackageType": 0,"Message2": 0,"Message1": 0,
  "BarCode": 2893,"WeightUnit": 0,"PluName": "**PITAHAYA ROJA X KG**",
  "LabelId": 0,"Tolerance": 0,"UnitPrice": 750,"LFCode": 2893,
  "Rebate": 0,"Deptment": 0,"Tare": 0,"Code": 2893,"ShlefTime": 0,
  "QtyUnit": 0,},]
```

Tres cosas que no son obvias y que rompen una implementación hecha a ojo:

1. **Solo `PluName` va entrecomillado.** Todo lo demás son números desnudos.
   `"UnitPrice": "750"` deja el precio en cero en los firmwares que no
   convierten tipos.
2. **Las erratas son parte del contrato.** `ShlefTime` (no *ShelfTime*) y
   `Deptment` (no *Department*). Corregirlas hace que el campo se ignore.
3. **La cadena original no es JSON válido**: lleva coma antes de `}` y antes
   de `]`. El parser de la DLL las tolera. Esta aplicación emite JSON correcto
   —que cualquier parser tolerante también acepta— y deja
   `rongta.formato_legacy: true` para reproducir la cadena original byte a byte
   si algún firmware resultara quisquilloso.

### 3.3 `ipack` es la cantidad de registros

En el IL:

```
IL_0030:  ldarg.0          // datos (string[])
IL_0031:  ldlen
IL_0032:  conv.i4
IL_0033:  stloc.3          // V_3 = datos.Length
...
IL_01b7:  ldloc.3          // ipack = V_3
IL_01b8:  call int32 Rongta::rtscaleDownLoadPLU(string, string, int32)
```

`ipack` **no** es un índice de paquete: es el número de productos que lleva la
cadena. Enviar `0` hace que la balanza acepte la trama y no grabe nada, que es
el fallo más difícil de diagnosticar porque la DLL devuelve éxito.

---

## 4. Teclas rápidas

```c
rtscaleDownLoadHotkey(connId, tabla, indiceTabla)   // indiceTabla = 0, 1, 2
```

Tres páginas de 28 teclas = 84 accesos directos. En el IL de la aplicación
original aparecen las comparaciones contra `0x54` (84) que separan una página
de la siguiente.

Las páginas se rellenan con `0` hasta completar 28: la balanza espera el array
completo.

---

## 5. Ciclo de una sesión

```
rtscaleLoadIniFile(ini)          una vez al arrancar (opcional, plantillas de etiqueta)
    │
    ├─ rtscaleConnect(ip, 0, connId)      ─┐
    │     rtscaleClearPLUData(connId)      │  una balanza cada vez:
    │     rtscaleDownLoadPLU(connId, …) ×N │  la RLS-1000 acepta UNA sola
    │     rtscaleDownLoadHotkey(…) ×3      │  conexión simultánea
    └─ rtscaleDisConnect(connId)          ─┘
```

`rtscaleDisConnect` va siempre en un `finally`. Si el proceso muere con la
conexión abierta, la balanza queda ocupada hasta que expira su propio
temporizador y la siguiente corrida falla sin motivo aparente.

---

## 6. El puerto TCP es el 5001, y está compilado dentro

`rtscaleConnect(addr, baudRate, connId)` **no recibe el puerto**. La DLL lo
lleva fijo. Se ve desensamblando la función (base de imagen `0x00400000`,
`rtscaleConnect` en RVA `0x232d74`):

```asm
00632e4d  add    eax, 0x1a0            ; campo Host del cliente Indy
00632e52  mov    edx, dword ptr [ebp+8] ; arg1 = la IP que le pasamos
00632e55  call   0x40ad40              ; asigna el host
00632e5a  push   0x1389                ; <-- puerto 5001
00632e65  call   0x40ad40
00632e76  call   0x60e600              ; conecta
00632e82  mov    dword ptr [eax+0x60], 0x4b0   ; 1200, tiempo de espera
```

`0x1389` = **5001**. La DLL es Delphi y usa **Indy** (`TIdTCPClient`), lo que
explica que el puerto sea una constante numérica y no aparezca como cadena.

### 6.1 El segundo argumento no es un baudrate

Se llama `BaudRate` en la declaración de la aplicación original, pero la DLL lo
usa como **selector de transporte**:

```asm
00632df6  mov    eax, dword ptr [ebp+0xc]   ; arg2
00632df9  sub    eax, 1
00632dfc  jb     0x632e02                   ; 0  -> modo 0
00632dfe  je     0x632e0f                   ; 1  -> modo 1
00632e00  jmp    0x632e1c                   ; >1 -> modo 2
```

La aplicación original pasa **siempre `0`** en las cuatro llamadas que hace, y
`0` es el modo de red. Esta aplicación pasa lo mismo (`rongta.baudrate: 0`).
No lo cambie sin motivo: otro valor selecciona otro transporte.

### 6.2 El `Port=` de `SYSTEM.CFG` es el puerto serie

En `C:\ibalance\RLS1000\SYSTEM.CFG` hay una sección que despista:

```ini
[Comm]
CommType=1
Port=
BaudRate=9600
IP=10.23.18.253
```

Ese `Port=` es el puerto **COM**, como delata el `BaudRate=9600` de al lado.
El puerto TCP no está ahí ni en ningún otro archivo de configuración: solo en
el código de la DLL.

### 6.3 Consecuencia práctica

El campo `puerto` del `config.json` **no cambia a dónde se conecta la DLL**.
Sirve únicamente para el sondeo TCP de diagnóstico, que comprueba si algo
escucha en esa dirección. Por eso el sondeo está desactivado por defecto en la
sincronización (`sincronizacion.verificar_puerto: false`): abre y cierra una
conexión, y estas balanzas admiten una sola.

## 7. Exportaciones no usadas que podrían servir

`C:\ibalance\rtslabelscale.dll` exporta 78 funciones. Además de las nueve que
usa la aplicación, hay algunas con potencial:

| Función | Para qué serviría |
|---|---|
| `rtscaleUpDatePrice` | actualizar solo precios, mucho más rápido que reenviar el catálogo |
| `rtscaleDownLoadDepartment` | cargar la tabla de departamentos |
| `rtscaleDownLoadMessage` | mensajes de la etiqueta |
| `rtscaleCheckFirmwareVer` / `rtscaleUploadFirmwareVersion` | inventario del parque de balanzas |
| `rtscaleUploadSaleData` | leer las ventas de la balanza |
| `rtscaleDownloadLabelFile` | enviar plantillas `.scr` |

**No están implementadas**: sus firmas no aparecen en la aplicación original,
así que habría que deducirlas, y una firma equivocada en `stdcall` corrompe la
pila. Si el fabricante facilita el SDK, añadirlas es directo.

---

## 8. Cómo reproducir este análisis

```bash
# Exportaciones, arquitectura y puerto TCP (sin cargar la DLL, en cualquier SO)
python tools/inspect_dll.py C:\ibalance\rtslabelscale.dll

# Declaraciones P/Invoke de la aplicación original
pip install dnfile
python -c "
import dnfile
pe = dnfile.dnPE('ibalance.exe')
for r in pe.net.mdtables.ImplMap.rows:
    print(r.ImportName, r.MappingFlags.pmCallConvStdcall)"

# Cuerpo IL de los métodos de envío
monodis --output=ibalance.il ibalance.exe
```
