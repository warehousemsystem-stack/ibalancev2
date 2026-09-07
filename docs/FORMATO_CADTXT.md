# Formato de `cadtxt.txt`

Archivo de ancho fijo que exporta el ERP. Un producto por línea, 79 caracteres
por línea, sin cabecera. Codificación **latin-1** (aparecen `Ñ` y espacios
duros `\xa0`).

```
002893P**PITAHAYA ROJA X KG**0000750000                       2 1 1
|____|||____________________||_____||_|
0    6 7                   29     36 39
```

| Posiciones | Campo | Ejemplo | Notas |
|---|---|---|---|
| 0–5 | Código PLU | `002893` | 6 dígitos con ceros a la izquierda |
| 6 | Marca de tipo | `P` | `P` = pesable. En la muestra de 1.839 líneas, todas son `P` |
| 7–28 | Nombre | `**PITAHAYA ROJA X KG**` | 22 caracteres, rellenado con espacios |
| 29–35 | Precio | `0000750` | entero, **sin punto decimal**: `750` = `7,50` |
| 36–38 | Vida útil | `000` | días hasta el vencimiento |
| 39–78 | Sin identificar | `      2 1 1      ` | constante en toda la muestra |

## El campo 36–38 es vida útil, no departamento

Los valores observados son `0, 1, 3, 5, 10, 15, 30, 45, 60, 90, 180, 365`: una
escala de días (365 = un año, 180 = seis meses), no una numeración de
departamentos. Alimenta `ShlefTime` del JSON de la balanza, que es lo que usa
para calcular la fecha de vencimiento impresa.

La aplicación anterior lo mandaba en `Deptment` y fijaba `ShlefTime` en `"15"`
para **todos** los artículos, con lo que los perecederos salían con fecha de
vencimiento equivocada.

## Posiciones 39–78

Constantes en las 1.839 líneas de la muestra (`2 1 1` rodeado de espacios), así
que no hay forma de deducir qué significan sin más datos. No se envían. Si
aparece un archivo donde varíen, se pueden mapear añadiendo el rango a
`origen.layout` sin tocar código.

## El layout es configurable

Los rangos no están cableados: salen de `origen.layout` en `config.json`, con
la misma semántica que un `slice` de Python (`[29, 36]` toma los caracteres
29 a 35). Otra tienda con anchos distintos solo edita el config.

```json
"layout": {
  "codigo":         [0, 6],
  "tipo":           [6, 7],
  "nombre":         [7, 29],
  "precio":         [29, 36],
  "vida_util_dias": [36, 39],
  "departamento":   []
}
```

Un rango vacío (`[]`) desactiva el campo.

## Líneas que se descartan

Nunca abortan la corrida: se registran como incidencias y el resto de productos
se envía igual. Un archivo con tres líneas rotas no puede dejar seis balanzas
sin precios actualizados.

- líneas más cortas que el último campo definido;
- código no numérico;
- nombre vacío;
- precio ilegible o por debajo de `origen.precio_minimo` (por defecto `1`,
  para filtrar artículos que el ERP exporta con precio cero);
- código repetido: se conserva **la última** aparición, que es la vigente.

`ibalance check` y `ibalance preview` muestran el recuento y las primeras
incidencias antes de tocar ninguna balanza.

## Alternativa CSV

Si el ERP deja de exportar el ancho fijo, `origen.tipo: "csv"` lee un CSV con
cabecera. Reconoce por sí solo columnas llamadas `codigo`/`code`/`plu`,
`nombre`/`descripcion`, `precio`/`price`, `vida_util_dias`, `departamento`; si
se llaman de otro modo, se mapean en `origen.csv_columnas`. Acepta precios con
coma o punto (`14,82` → `1482`).
