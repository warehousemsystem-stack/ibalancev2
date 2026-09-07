# Qué cambia respecto a las versiones anteriores

Comparación con el prototipo `ibalance_v2` en Python y con la aplicación
original en .NET. Los puntos marcados **(corrige un fallo)** son errores
verificables, no cuestión de gusto.

## Comunicación con la DLL

| Tema | `ibalance_v2` | Aquí |
|---|---|---|
| Convención de llamada | `ctypes.CDLL` (cdecl) | `WinDLL` (stdcall), como declara la app original **(corrige un fallo)** |
| Arquitectura | sin comprobar | se lee la cabecera PE y se compara con el proceso antes de cargar |
| `ipack` | siempre `0` | número de registros del lote **(corrige un fallo)** |
| Tamaño del envío | los 1.839 productos en una sola llamada (≈465 KB) | lotes configurables, 200 por defecto |
| Funciones | 5 | 8, incluidas `rtscaleLoadIniFile`, `rtscaleGetScaleType` y `rtscaleDownLoadDeletePlu` |
| Dependencias | `PATH` con `RLS1000` primero | `os.add_dll_directory` + `PATH`, con `C:\ibalance` antes que `RLS1000\` (son DLL distintas) |
| Resultado de `rtscaleDownLoadPLU` | ignorado | se comprueba y se corta el envío si la balanza rechaza un lote **(corrige un fallo)** |

## Contenido del PLU

| Campo | `ibalance_v2` | Aquí |
|---|---|---|
| `UnitPrice` | `"750"` (texto) | `750` (número) **(corrige un fallo)** |
| `LFCode`, `BarCode`, `Code` | texto | número, como emite la app original |
| `ShlefTime` | `"15"` fijo para todo | días de vida útil del artículo **(corrige un fallo)** |
| `Deptment` | recibía la vida útil | configurable, por defecto `0` **(corrige un fallo)** |
| `WeightUnit` | `"0"` (texto) | `0` (número) |
| Acentos | `json.dumps` por defecto escapaba `Ñ` a `\u00d1` | `ensure_ascii=False`, la DLL recibe ANSI **(corrige un fallo)** |

## Teclas rápidas

`ibalance_v2` tomaba los primeros 84 productos **en el orden del archivo del
ERP**, que no es estable: las teclas del mostrador cambiaban solas de un día
para otro. Aquí se puede fijar la lista exacta en `rongta.hotkeys.codigos`, y
sin lista se ordena por código, que sí es estable.

## Concurrencia y conexiones

- `ibalance_v2` lanzaba un hilo por balanza y los serializaba con un candado
  global: el paralelismo era aparente y el candado no cubría la desconexión.
- Aquí es secuencial por defecto (`balanzas_en_paralelo: 1`), el candado cubre
  la sesión completa —conectar, enviar, desconectar— y el paralelismo es una
  opción consciente para quien lo haya probado en su instalación.
- La desconexión va en un `finally` con pausa configurable, y hay una prueba
  automática que falla si alguna ruta de código deja una conexión abierta.

## Robustez

- **Ping multiplataforma (corrige un fallo).** `ibalance_v2` usaba `ping -n -w`
  y `subprocess.CREATE_NO_WINDOW` sin comprobar el sistema: lanzaba
  `AttributeError` fuera de Windows, así que ni sus propias pruebas podían
  correr en el equipo de desarrollo.
- **Reintentos** por balanza con espera configurable; una balanza apagada ya no
  arrastra a las demás.
- **`except Exception` genérico** sustituido por errores tipados
  (`ConexionError`, `OperacionError`, `DllNoEncontradaError`,
  `ArquitecturaIncorrectaError`) con mensajes que dicen qué hacer.
- **Configuración validada** al cargar, informando de *todos* los problemas a
  la vez, y migrando automáticamente el `config.json` de la versión anterior.

## Interfaz

- **tkinter desde hilos (corrige un fallo).** `ibalance_v2` escribía en los
  widgets desde los hilos de trabajo. Funciona casi siempre y cuelga la
  aplicación de vez en cuando. Aquí todo pasa por una cola que vacía el hilo de
  la interfaz.
- Botón **Vaciar** por balanza (`rtscaleClearPLUData`), *Probar* individual y
  masivo, y estado en vivo por balanza.
- Aviso al cerrar si hay una corrida en marcha, para no dejar una conexión
  abierta.
- **Rediseño completo**: barra lateral en vez de pestañas, tarjeta por balanza
  con indicador de estado, métricas de la corrida, vista previa del archivo de
  origen y tema claro/oscuro. El aspecto está aislado en `gui/tema.py`, sobre
  el tema `clam` (el único de los incorporados cuyos elementos aceptan colores
  planos; el tema nativo de Windows dibuja bordes y degradados propios que no
  se pueden quitar).

## Operación

Nuevo respecto a ambas versiones:

- **CLI completa** (`check`, `preview`, `sync`, `clear`, `daemon`, `dll`,
  `gui`) con códigos de salida, para el Programador de tareas de Windows.
- **Modo simulado** (`--simular`): vuelca a disco los payloads exactos sin
  tocar la red. Permite probar en cualquier sistema operativo.
- **Reporte JSON por corrida** y estado por balanza, de modo que la que estaba
  apagada se reintenta aunque el archivo de origen no haya cambiado.
- **54 pruebas automáticas** que cubren el parseo, el formato del payload y la
  restricción de una conexión por balanza.
- **`tools/inspect_dll.py`**: verifica la DLL del cliente sin cargarla, desde
  cualquier sistema operativo.
