"""Motor de sincronizacion: lee el origen y lo reparte entre las balanzas."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import net, procesos
from .config import Balanza, Config
from .logging_setup import obtener
from .models import Plu, ResultadoBalanza, ResultadoSincronizacion
from .report import Estado, guardar_reporte
from .rongta import (
    BackendBalanza,
    BackendSimulado,
    ConexionError,
    RongtaError,
    RtsLabelScaleDLL,
    conexion,
    construir_hotkeys,
    construir_lotes_plu,
)
from .sources import Lectura, OrigenError, leer

log = obtener("motor")

#: Firma de los avisos de progreso: (balanza, estado, detalle).
Progreso = Callable[[Balanza, str, str], None]


class MotorSincronizacion:
    """Orquesta una corrida completa.

    Reglas de diseno que vienen del comportamiento real del equipo:

    * Cada balanza acepta **una sola conexion**, y la DLL guarda estado interno
      por ``conn_id``. Por defecto se trabaja de una en una; el paralelismo es
      configurable para quien tenga muchas balanzas y lo haya probado.
    * La conexion se abre lo mas tarde posible y se cierra siempre, tambien
      cuando el envio falla a la mitad.
    * Una balanza apagada no puede hacer fracasar a las demas: cada una lleva
      su propio resultado y sus propios reintentos.
    """

    def __init__(
        self,
        config: Config,
        backend: BackendBalanza | None = None,
        progreso: Progreso | None = None,
    ) -> None:
        self.config = config
        self._backend = backend
        self._progreso = progreso
        self._cancelar = threading.Event()
        self._lock_dll = threading.Lock()
        self._sincronizando = threading.Event()
        self.estado = Estado(self._dir_logs() / "estado.json")

    # ------------------------------------------------------------------ #
    # Infraestructura
    # ------------------------------------------------------------------ #

    def _dir_logs(self) -> Path:
        directorio = Path(self.config.registro.directorio)
        if not directorio.is_absolute():
            directorio = self.config.dir_base() / directorio
        return directorio

    def _avisar(self, balanza: Balanza, estado: str, detalle: str = "") -> None:
        if self._progreso is not None:
            try:
                self._progreso(balanza, estado, detalle)
            except Exception:  # noqa: BLE001 - la UI no puede romper la corrida
                log.debug("fallo un callback de progreso", exc_info=True)

    @property
    def backend(self) -> BackendBalanza:
        """Backend en uso; se crea el real la primera vez que hace falta."""
        if self._backend is None:
            self._backend = RtsLabelScaleDLL(
                self.config.resolver(self.config.rongta.dll_path),
                convencion=self.config.rongta.convencion_llamada,
                baudrate=self.config.rongta.baudrate,
                directorios_dependencias=self.config.rongta.directorios_dependencias,
            )
        return self._backend

    def abrir_backend(self) -> None:
        """Carga la DLL (o el simulador) y aplica el .ini del fabricante."""
        self.backend.abrir()
        log.info("Backend listo: %s", self.backend.descripcion)
        ini = self.config.rongta.ini_path.strip()
        if ini:
            ruta = self.config.resolver(ini)
            try:
                codigo = self.backend.cargar_ini(str(ruta))
                log.info("rtscaleLoadIniFile(%s) devolvio %s", ruta, codigo)
            except (NotImplementedError, RongtaError) as exc:
                log.warning("No se pudo cargar el .ini de etiquetas: %s", exc)

    def cancelar(self) -> None:
        self._cancelar.set()
        log.warning("Cancelacion solicitada; se terminara la balanza en curso")

    @property
    def sincronizando(self) -> bool:
        return self._sincronizando.is_set()

    # ------------------------------------------------------------------ #
    # Lectura
    # ------------------------------------------------------------------ #

    def leer_origen(self) -> Lectura:
        ruta = self.config.resolver(self.config.origen.ruta)
        log.info("Leyendo %s", ruta)
        lectura = leer(self.config.origen, str(ruta))
        log.info(
            "Origen leido: %d productos validos de %d lineas (%d incidencias)",
            lectura.total,
            lectura.lineas_totales,
            len(lectura.incidencias),
        )
        for incidencia in lectura.incidencias[:10]:
            log.warning("  %s", incidencia)
        if len(lectura.incidencias) > 10:
            log.warning("  ... y %d incidencias mas", len(lectura.incidencias) - 10)
        return lectura

    # ------------------------------------------------------------------ #
    # Corrida completa
    # ------------------------------------------------------------------ #

    def sincronizar(
        self,
        solo_ids: Sequence[int] | None = None,
        forzar: bool = False,
    ) -> ResultadoSincronizacion:
        """Ejecuta una sincronizacion y devuelve el resultado detallado."""
        self._cancelar.clear()
        self._sincronizando.set()
        inicio = datetime.now()
        resultado = ResultadoSincronizacion(
            inicio=inicio, fin=inicio, origen=str(self.config.resolver(self.config.origen.ruta)),
            plus_leidos=0,
        )
        try:
            self._ejecutar(resultado, solo_ids, forzar)
        except OrigenError as exc:
            resultado.error_global = str(exc)
            log.error("No se pudo leer el origen: %s", exc)
        except RongtaError as exc:
            resultado.error_global = str(exc)
            log.error("Fallo la capa Rongta: %s", exc)
        except Exception as exc:  # noqa: BLE001 - una corrida nunca tumba el proceso
            resultado.error_global = f"error inesperado: {exc}"
            log.exception("Error inesperado durante la sincronizacion")
        finally:
            resultado.fin = datetime.now()
            resultado.cancelada = self._cancelar.is_set()
            self._sincronizando.clear()
            self.estado.guardar()
            if self.config.registro.guardar_reportes:
                try:
                    destino = guardar_reporte(resultado, self._dir_logs() / "reportes")
                    log.info("Reporte guardado en %s", destino)
                except OSError as exc:
                    log.warning("No se pudo guardar el reporte: %s", exc)
            log.info(
                "Sincronizacion terminada en %.1f s: %d correctas, %d con error, %d omitidas",
                resultado.duracion_seg,
                resultado.exitosas,
                resultado.fallidas,
                resultado.omitidas,
            )
        return resultado

    def _ejecutar(
        self,
        resultado: ResultadoSincronizacion,
        solo_ids: Sequence[int] | None,
        forzar: bool,
    ) -> None:
        lectura = self.leer_origen()
        resultado.plus_leidos = lectura.total
        resultado.errores_lectura = lectura.incidencias
        if not lectura.plus:
            resultado.error_global = "el origen no contiene productos validos"
            log.error(resultado.error_global)
            return

        balanzas = self._balanzas_objetivo(solo_ids)
        if not balanzas:
            resultado.error_global = "no hay balanzas activas con IP configurada"
            log.error(resultado.error_global)
            return

        if self.config.sincronizacion.cerrar_procesos_legacy:
            cerrados = procesos.cerrar_procesos(self.config.sincronizacion.procesos_legacy)
            if cerrados:
                log.warning(
                    "Se cerro la aplicacion antigua para liberar el puerto: %s",
                    ", ".join(cerrados),
                )

        lotes = construir_lotes_plu(
            lectura.plus,
            self.config.rongta.tamano_lote_plu,
            self.config.rongta.plu_defaults,
            self.config.rongta.formato_legacy,
        )
        paginas = (
            construir_hotkeys(lectura.plus, self.config.rongta.hotkeys)
            if self.config.rongta.enviar_hotkeys
            else []
        )
        log.info(
            "Preparados %d lotes (%d bytes en total) y %d paginas de hotkeys",
            len(lotes),
            sum(len(j) for j, _ in lotes),
            len(paginas),
        )

        self.abrir_backend()

        paralelo = max(1, self.config.sincronizacion.balanzas_en_paralelo)
        if paralelo == 1:
            for balanza in balanzas:
                if self._cancelar.is_set():
                    break
                resultado.balanzas.append(
                    self._procesar(balanza, lotes, paginas, lectura.huella, forzar)
                )
        else:
            log.warning(
                "Enviando a %d balanzas en paralelo; la DLL comparte estado "
                "entre conexiones, use esta opcion solo si la probo en su instalacion",
                paralelo,
            )
            with ThreadPoolExecutor(max_workers=paralelo, thread_name_prefix="balanza") as pool:
                futuros = [
                    pool.submit(self._procesar, b, lotes, paginas, lectura.huella, forzar)
                    for b in balanzas
                ]
                resultado.balanzas.extend(f.result() for f in futuros)

        resultado.balanzas.sort(key=lambda r: r.balanza_id)

    def _balanzas_objetivo(self, solo_ids: Sequence[int] | None) -> list[Balanza]:
        balanzas = self.config.balanzas_activas()
        if solo_ids is None:
            return balanzas
        pedidas = set(solo_ids)
        seleccion = [b for b in self.config.balanzas if b.id in pedidas]
        for balanza in seleccion:
            if not balanza.utilizable:
                log.warning(
                    "La balanza %d (%s) se pidio explicitamente pero esta inactiva "
                    "o sin IP; se intenta igualmente",
                    balanza.id,
                    balanza.nombre,
                )
        return seleccion or balanzas

    # ------------------------------------------------------------------ #
    # Una balanza
    # ------------------------------------------------------------------ #

    def _procesar(
        self,
        balanza: Balanza,
        lotes: list[tuple[str, int]],
        paginas: list[list[int]],
        huella: str,
        forzar: bool,
    ) -> ResultadoBalanza:
        sinc = self.config.sincronizacion

        if (
            sinc.omitir_si_sin_cambios
            and not forzar
            and huella
            and self.estado.huella_de(balanza.id) == huella
        ):
            mensaje = "sin cambios en el origen desde el ultimo envio correcto"
            log.info("[%s] %s", balanza.nombre, mensaje)
            self._avisar(balanza, "omitida", mensaje)
            return ResultadoBalanza(
                balanza_id=balanza.id, nombre=balanza.nombre, ip=balanza.ip,
                ok=False, omitida=True, mensaje=mensaje,
            )

        intentos = max(1, sinc.reintentos + 1)
        ultimo: ResultadoBalanza | None = None

        for intento in range(1, intentos + 1):
            if self._cancelar.is_set():
                return ResultadoBalanza(
                    balanza_id=balanza.id, nombre=balanza.nombre, ip=balanza.ip,
                    ok=False, mensaje="cancelada antes de enviar", intentos=intento,
                )
            ultimo = self._intentar(balanza, lotes, paginas)
            ultimo.intentos = intento
            if ultimo.ok:
                self.estado.marcar_enviada(balanza.id, huella, ultimo.plus_enviados)
                self._avisar(balanza, "ok", ultimo.mensaje)
                return ultimo
            if intento < intentos and not self._cancelar.is_set():
                log.warning(
                    "[%s] intento %d/%d fallido (%s); reintentando en %.0f s",
                    balanza.nombre, intento, intentos, ultimo.mensaje,
                    sinc.espera_reintento_seg,
                )
                self._avisar(balanza, "reintentando", ultimo.mensaje)
                time.sleep(sinc.espera_reintento_seg)

        assert ultimo is not None
        self._avisar(balanza, "error", ultimo.mensaje)
        return ultimo

    def _intentar(
        self,
        balanza: Balanza,
        lotes: list[tuple[str, int]],
        paginas: list[list[int]],
    ) -> ResultadoBalanza:
        sinc = self.config.sincronizacion
        rongta = self.config.rongta
        inicio = time.monotonic()

        def resultado(ok: bool, mensaje: str, **extra) -> ResultadoBalanza:
            return ResultadoBalanza(
                balanza_id=balanza.id, nombre=balanza.nombre, ip=balanza.ip,
                ok=ok, mensaje=mensaje, duracion_seg=time.monotonic() - inicio, **extra
            )

        self._avisar(balanza, "verificando", balanza.ip)

        if sinc.verificar_ping and not net.ping(balanza.ip, sinc.timeout_ping_seg):
            return resultado(False, f"{balanza.ip} no responde al ping")

        if sinc.verificar_puerto:
            disponible, motivo = net.puerto_abierto(
                balanza.ip, balanza.puerto, float(sinc.timeout_ping_seg)
            )
            if not disponible:
                return resultado(False, motivo)

        enviados = lotes_ok = hotkeys_ok = 0
        try:
            # El bloqueo cubre toda la sesion con la balanza: la DLL mantiene
            # estado por conn_id y dos hilos dentro de ella se pisan.
            with self._lock_dll:
                self._avisar(balanza, "conectando", balanza.ip)
                with conexion(
                    self.backend, balanza.ip, balanza.conn_id,
                    rongta.codigo_exito, sinc.pausa_tras_desconectar_seg,
                ):
                    log.info("[%s] conectada (%s)", balanza.nombre, balanza.ip)

                    if rongta.limpiar_antes_de_enviar:
                        codigo = self.backend.limpiar_plu(balanza.conn_id)
                        log.info("[%s] limpieza previa: codigo %s", balanza.nombre, codigo)
                        if codigo != rongta.codigo_exito:
                            return resultado(
                                False, f"no se pudo limpiar el catalogo (codigo {codigo})"
                            )

                    for numero, (lote_json, registros) in enumerate(lotes, start=1):
                        if self._cancelar.is_set():
                            return resultado(
                                False, "cancelada durante el envio",
                                plus_enviados=enviados, lotes_enviados=lotes_ok,
                            )
                        self._avisar(
                            balanza, "enviando", f"lote {numero}/{len(lotes)}"
                        )
                        codigo = self.backend.enviar_plu(
                            balanza.conn_id, lote_json, registros
                        )
                        if codigo != rongta.codigo_exito:
                            return resultado(
                                False,
                                f"la balanza rechazo el lote {numero} de {len(lotes)} "
                                f"({registros} productos, codigo {codigo})",
                                plus_enviados=enviados, lotes_enviados=lotes_ok,
                            )
                        enviados += registros
                        lotes_ok += 1
                        if sinc.pausa_entre_lotes_seg > 0:
                            time.sleep(sinc.pausa_entre_lotes_seg)

                    for indice, pagina in enumerate(paginas):
                        self._avisar(balanza, "enviando", f"hotkeys {indice + 1}/{len(paginas)}")
                        codigo = self.backend.enviar_hotkey(balanza.conn_id, pagina, indice)
                        if codigo != rongta.codigo_exito:
                            # Las teclas rapidas son un extra: el catalogo ya
                            # esta grabado y no vale la pena dar por fallida la
                            # balanza entera por esto.
                            log.warning(
                                "[%s] la pagina de hotkeys %d fue rechazada (codigo %s)",
                                balanza.nombre, indice, codigo,
                            )
                            continue
                        hotkeys_ok += 1

        except ConexionError as exc:
            return resultado(False, str(exc))
        except RongtaError as exc:
            return resultado(
                False, f"error de la DLL: {exc}",
                plus_enviados=enviados, lotes_enviados=lotes_ok,
            )
        except OSError as exc:
            return resultado(
                False, f"error de sistema al comunicar con {balanza.ip}: {exc}",
                plus_enviados=enviados, lotes_enviados=lotes_ok,
            )

        return resultado(
            True,
            f"{enviados} productos en {lotes_ok} lotes"
            + (f" y {hotkeys_ok} paginas de hotkeys" if hotkeys_ok else ""),
            plus_enviados=enviados, lotes_enviados=lotes_ok, hotkeys_enviadas=hotkeys_ok,
        )

    # ------------------------------------------------------------------ #
    # Operaciones sueltas
    # ------------------------------------------------------------------ #

    def limpiar_balanza(self, balanza: Balanza) -> ResultadoBalanza:
        """Borra el catalogo de una balanza (``rtscaleClearPLUData``).

        Es la salida cuando una balanza queda con datos corruptos: se vacia y
        se vuelve a sincronizar desde cero.
        """
        inicio = time.monotonic()
        sinc = self.config.sincronizacion
        try:
            self.abrir_backend()
            with self._lock_dll, conexion(
                self.backend, balanza.ip, balanza.conn_id,
                self.config.rongta.codigo_exito, sinc.pausa_tras_desconectar_seg,
            ):
                codigo = self.backend.limpiar_plu(balanza.conn_id)
            ok = codigo == self.config.rongta.codigo_exito
            mensaje = (
                "catalogo borrado" if ok else f"la balanza rechazo el borrado (codigo {codigo})"
            )
        except RongtaError as exc:
            ok, mensaje = False, str(exc)

        if ok:
            self.estado.olvidar(balanza.id)  # forzar reenvio completo
        log.info("[%s] limpieza: %s", balanza.nombre, mensaje)
        return ResultadoBalanza(
            balanza_id=balanza.id, nombre=balanza.nombre, ip=balanza.ip,
            ok=ok, mensaje=mensaje, duracion_seg=time.monotonic() - inicio,
        )

    def probar_balanza(self, balanza: Balanza) -> tuple[bool, str]:
        """Comprueba la red de la balanza y explica cada parte por separado.

        Son dos comprobaciones distintas y conviene no confundirlas: el ping es
        ICMP y no tiene puertos, mientras que el sondeo abre una conexion TCP
        al puerto. Una balanza que responde al ping pero rechaza el puerto esta
        encendida y en la red; lo que falla es el servicio.

        El sondeo no decide por si solo: la conexion real la abre la DLL, asi
        que una balanza que responde al ping se da por alcanzable aunque el
        sondeo falle, y el motivo queda en el mensaje.
        """
        sinc = self.config.sincronizacion
        partes: list[str] = []

        responde_ping = None
        if sinc.verificar_ping:
            responde_ping = net.ping(balanza.ip, sinc.timeout_ping_seg)
            partes.append("ping OK" if responde_ping else "sin respuesta al ping")

        abierto, motivo = net.puerto_abierto(
            balanza.ip, balanza.puerto, float(sinc.timeout_ping_seg)
        )
        partes.append(
            f"puerto {balanza.puerto} accesible" if abierto else motivo
        )

        # El sondeo abre y cierra una conexion TCP. Como la balanza admite una
        # sola, se le da un momento para liberarla antes de que alguien pulse
        # «Sincronizar» a continuacion.
        if abierto and sinc.pausa_tras_desconectar_seg > 0:
            time.sleep(sinc.pausa_tras_desconectar_seg)

        alcanzable = abierto or bool(responde_ping)
        return alcanzable, " · ".join(partes)


def crear_backend(config: Config, simular: bool = False) -> BackendBalanza:
    """Backend real o simulado, segun se pida."""
    if simular:
        directorio = Path(config.registro.directorio)
        if not directorio.is_absolute():
            directorio = config.dir_base() / directorio
        return BackendSimulado(directorio_volcado=directorio / "simulacion")
    return RtsLabelScaleDLL(
        config.resolver(config.rongta.dll_path),
        convencion=config.rongta.convencion_llamada,
        baudrate=config.rongta.baudrate,
        directorios_dependencias=config.rongta.directorios_dependencias,
    )


__all__ = ["MotorSincronizacion", "Progreso", "crear_backend", "Plu"]
