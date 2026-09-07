"""Construccion de los payloads que espera ``rtslabelscale.dll``.

El formato NO esta documentado por el fabricante: esta reconstruido a partir de
la aplicacion original en .NET (``ibalance.exe`` 1.0.0.84), leyendo tanto el DTO
``EgoDeno.funciones.Romgta.PluDataRomgta`` como la cadena que la aplicacion
concatena antes de llamar a ``rtscaleDownLoadPLU``::

    [{"PackageWeight": 0,"PackageType": 0,"Message2": 0,"Message1": 0,
      "BarCode": 2893,"WeightUnit": 0,"PluName": "PITAHAYA ROJA X KG",
      "LabelId": 0,"Tolerance": 0,"UnitPrice": 750,"LFCode": 2893,
      "Rebate": 0,"Deptment": 0,"Tare": 0,"Code": 2893,"ShlefTime": 0,
      "QtyUnit": 0,},]

De ahi salen tres reglas que no son evidentes:

1. **Los valores son numeros, no cadenas.** El unico campo entrecomillado es
   ``PluName``. Mandar ``"UnitPrice": "750"`` deja el precio en cero en las
   balanzas cuyo firmware no convierte tipos.
2. **Los nombres de clave llevan las erratas del fabricante** (``ShlefTime``
   por *ShelfTime*, ``Deptment`` por *Department*). Corregirlas hace que el
   campo se ignore en silencio.
3. **La cadena original incluye comas finales** (``,},]``), que no son JSON
   valido. El parser de la DLL las tolera; aqui se emite JSON correcto, que
   cualquier parser tolerante tambien acepta. ``formato_legacy=True`` reproduce
   la cadena original byte a byte por si algun firmware resultara quisquilloso.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from ..config import Hotkeys
from ..models import Plu

#: Claves del objeto PLU en el orden exacto en que las emite la app original.
CLAVES_PLU: tuple[str, ...] = (
    "PackageWeight",
    "PackageType",
    "Message2",
    "Message1",
    "BarCode",
    "WeightUnit",
    "PluName",
    "LabelId",
    "Tolerance",
    "UnitPrice",
    "LFCode",
    "Rebate",
    "Deptment",
    "Tare",
    "Code",
    "ShlefTime",
    "QtyUnit",
)

#: Campos que el DTO .NET declara pero la app original no llegaba a enviar.
CLAVES_OPCIONALES: tuple[str, ...] = ("HotKey", "Account", "Reserved2")

#: Valores por defecto, con los tipos que declara ``PluDataRomgta``.
DEFAULTS: dict[str, Any] = {
    "PackageWeight": 0,   # double
    "PackageType": 0,     # int
    "Message2": 0,        # byte
    "Message1": 0,        # int
    "WeightUnit": 0,      # int
    "LabelId": 0,         # byte
    "Tolerance": 0,       # int
    "Rebate": 0,          # byte
    "Deptment": 0,        # int
    "Tare": 0,            # double
    "ShlefTime": 0,       # int
    "QtyUnit": 0,         # int
}


def _numero_o_texto(valor: str) -> int | str:
    """Codigos numericos van sin comillas, como hace la aplicacion original."""
    return int(valor) if valor.isdigit() else valor


def plu_a_dict(plu: Plu, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convierte un :class:`Plu` en el objeto que entiende la DLL.

    ``vida_util_dias`` del archivo de origen alimenta ``ShlefTime``: son los
    dias que la balanza suma a la fecha de envasado para imprimir el
    vencimiento.
    """
    valores: dict[str, Any] = dict(DEFAULTS)
    if defaults:
        permitidas = set(CLAVES_PLU) | set(CLAVES_OPCIONALES)
        valores.update({k: v for k, v in defaults.items() if k in permitidas})

    codigo = _numero_o_texto(plu.codigo_corto)
    valores["Code"] = codigo
    valores["LFCode"] = codigo
    valores["BarCode"] = codigo
    valores["PluName"] = plu.nombre
    valores["UnitPrice"] = plu.precio
    valores["ShlefTime"] = plu.vida_util_dias
    if plu.departamento:
        valores["Deptment"] = plu.departamento

    objeto = {clave: valores[clave] for clave in CLAVES_PLU}
    # Los opcionales van al final, solo si alguien los configuro.
    for clave in CLAVES_OPCIONALES:
        if clave in valores:
            objeto[clave] = valores[clave]
    return objeto


def _serializar_legacy(objetos: Sequence[dict[str, Any]]) -> str:
    """Reproduce la cadena de la aplicacion original, comas finales incluidas."""
    partes = []
    for objeto in objetos:
        campos = ",".join(
            f'"{clave}": {json.dumps(valor, ensure_ascii=False)}'
            for clave, valor in objeto.items()
        )
        partes.append("{" + campos + ",}")
    return "[" + ",".join(partes) + ("," if partes else "") + "]"


def serializar_lote(
    plus: Sequence[Plu],
    defaults: dict[str, Any] | None = None,
    formato_legacy: bool = False,
) -> str:
    """Serializa un lote de PLUs como el array JSON que recibe la DLL.

    ``ensure_ascii=False`` es deliberado: la DLL recibe la cadena como ANSI
    (los metadatos del ejecutable original declaran ``CharSet`` sin
    especificar, que en P/Invoke equivale a ANSI) y un nombre con ``Ñ``
    escapado a ``\\u00d1`` se imprimiria literalmente en la etiqueta.
    """
    objetos = [plu_a_dict(plu, defaults) for plu in plus]
    if formato_legacy:
        return _serializar_legacy(objetos)
    return json.dumps(objetos, ensure_ascii=False, separators=(",", ":"))


def construir_lotes_plu(
    plus: Sequence[Plu],
    tamano_lote: int = 200,
    defaults: dict[str, Any] | None = None,
    formato_legacy: bool = False,
) -> list[tuple[str, int]]:
    """Parte el catalogo en lotes y devuelve ``(json, cantidad_de_registros)``.

    La cantidad importa: el tercer argumento de ``rtscaleDownLoadPLU`` (``ipack``)
    es el **numero de registros que lleva la cadena**, no un indice de paquete.
    En la aplicacion original es literalmente ``datos.Length``. Mandar cero hace
    que la balanza acepte la trama y no grabe nada.

    Trocear tambien evita el otro fallo clasico: 1.800 articulos son mas de medio
    megabyte de JSON en una sola llamada y las RLS-1000 cortan la conexion antes
    de terminar de recibirlo.

    ``tamano_lote <= 0`` envia todo en un unico paquete.
    """
    if not plus:
        return []
    if tamano_lote <= 0:
        return [(serializar_lote(plus, defaults, formato_legacy), len(plus))]
    lotes = []
    for i in range(0, len(plus), tamano_lote):
        trozo = plus[i:i + tamano_lote]
        lotes.append((serializar_lote(trozo, defaults, formato_legacy), len(trozo)))
    return lotes


def construir_hotkeys(plus: Iterable[Plu], config: Hotkeys) -> list[list[int]]:
    """Arma las paginas de teclas rapidas como listas de enteros.

    La balanza espera las teclas repartidas en paginas de tamano fijo
    (28 teclas x 3 paginas = 84 accesos directos en las RLS-1000), y cada
    pagina se envia con su indice: ``rtscaleDownLoadHotkey(conn, tabla, 0..2)``.

    Si ``config.codigos`` trae una lista, se respeta ese orden exacto: son las
    teclas fisicas del teclado y la tienda decide que producto va en cada una.
    Sin lista explicita se toman los primeros productos ordenados por codigo,
    que al menos es estable entre corridas (el orden del archivo del ERP no lo
    es, y las teclas cambiarian solas de un dia para otro).
    """
    if not config.habilitado or config.paginas <= 0:
        return []

    por_pagina = config.teclas_por_pagina
    total = por_pagina * config.paginas

    if config.codigos:
        indice = {p.codigo_corto: p.codigo_numerico for p in plus}
        indice.update({p.codigo: p.codigo_numerico for p in plus})
        codigos: list[int] = []
        for bruto in config.codigos[:total]:
            clave = str(bruto).strip()
            if clave in indice:
                codigos.append(indice[clave])
            elif clave.isdigit():
                codigos.append(int(clave))
            else:
                codigos.append(0)
    else:
        ordenados = sorted(plus, key=lambda p: p.codigo_numerico)
        codigos = [p.codigo_numerico for p in ordenados[:total]]

    paginas: list[list[int]] = []
    for i in range(config.paginas):
        pagina = codigos[i * por_pagina:(i + 1) * por_pagina]
        pagina.extend([0] * (por_pagina - len(pagina)))
        paginas.append(pagina)
    return paginas
