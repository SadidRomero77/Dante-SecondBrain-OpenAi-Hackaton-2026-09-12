"""Transporte: mueve marcos entre el PC y el aparato.

Implementa PROTOCOL.md. Hoy por USB; el WebSocket va detras de la misma
interfaz, para que el agente no se entere de por donde entro el audio.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass

MAGIA = 0xA5
T_AUDIO = 1
T_CONTROL = 2
T_LOG = 3

NOMBRES = {T_AUDIO: "audio", T_CONTROL: "control", T_LOG: "log"}
LARGO_MAXIMO = 4096


@dataclass
class Marco:
    tipo: int
    carga: bytes

    @property
    def json(self) -> dict:
        try:
            return json.loads(self.carga.decode("utf-8", "replace"))
        except ValueError:
            return {}

    @property
    def texto(self) -> str:
        return self.carga.decode("utf-8", "replace")


class TransporteSerie:
    """Marcos sobre el puerto serie, con resincronizacion.

    El puerto serie es un flujo sin fronteras: si se pierde un byte, todo lo
    que sigue queda corrido. Por eso cada marco lleva un 0xA5 al frente y, al
    desincronizarse, se descartan bytes hasta encontrar uno con largo creible.
    """

    def __init__(self, puerto: str, baudios: int = 115200):
        import serial

        s = serial.Serial()
        s.port = puerto
        s.baudrate = baudios
        s.timeout = 0.05
        # Sin DTR activo, el USB-Serial/JTAG del ESP32-S3 descarta lo que
        # manda el aparato. Hay que fijarlo ANTES de abrir. Ver HARDWARE.md.
        s.dtr = True
        s.rts = False
        s.open()
        s.reset_input_buffer()   # descartar el marco a medias que quedo del arranque
        self.s = s
        self._buf = bytearray()
        self.descartados = 0

    def cerrar(self) -> None:
        try:
            self.s.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    # ------------------------------------------------------------ enviar --
    def enviar(self, tipo: int, carga: bytes) -> None:
        self.s.write(struct.pack("<BBH", MAGIA, tipo, len(carga)) + carga)

    def enviar_control(self, obj: dict) -> None:
        self.enviar(T_CONTROL, json.dumps(obj, separators=(",", ":")).encode())

    def enviar_audio(self, pcm: bytes) -> None:
        self.enviar(T_AUDIO, pcm)

    # -------------------------------------------------------------- leer --
    def leer(self) -> list[Marco]:
        """Devuelve los marcos completos que hayan llegado. No bloquea."""
        pendiente = self.s.in_waiting
        if pendiente:
            self._buf.extend(self.s.read(pendiente))
        else:
            self._buf.extend(self.s.read(1))

        marcos: list[Marco] = []
        while True:
            # resincronizar: descartar hasta el proximo 0xA5
            i = self._buf.find(MAGIA)
            if i < 0:
                self.descartados += len(self._buf)
                self._buf.clear()
                break
            if i:
                self.descartados += i
                del self._buf[:i]
            if len(self._buf) < 4:
                break

            tipo = self._buf[1]
            largo = self._buf[2] | (self._buf[3] << 8)
            if tipo not in NOMBRES or largo > LARGO_MAXIMO:
                self.descartados += 1
                del self._buf[:1]       # cabecera absurda: seguir buscando
                continue
            if len(self._buf) < 4 + largo:
                break

            marcos.append(Marco(tipo, bytes(self._buf[4:4 + largo])))
            del self._buf[:4 + largo]
        return marcos


class TransporteWebSocket:
    """El mismo contrato, por WiFi.

    Por el cable hay que enmarcar a mano porque el puerto serie es un flujo sin
    fronteras. WebSocket ya delimita, asi que aqui no hace falta cabecera: una
    trama binaria es audio y una de texto es control. Ver PROTOCOL.md.

    El servidor escucha y el aparato se conecta, no al reves: asi el aparato no
    necesita saber la IP del PC de antemano mas que una vez, y puede reconectar
    solo si el PC se reinicia.
    """

    def __init__(self, puerto: int = 8765):
        self.puerto = puerto
        self.cliente = None          # el aparato, cuando llega
        self.entrada: list[Marco] = []
        self.descartados = 0
        self._servidor = None
        self._bucle = None
        self._lock = __import__("threading").Lock()

    # ------------------------------------------------------------ servir --
    async def escuchar(self):
        """Levanta el servidor. Devuelve cuando esta listo, no cuando termina."""
        # La API nueva de websockets; la vieja (websockets.serve) esta obsoleta.
        from websockets.asyncio.server import serve

        async def atender(ws):
            if self.cliente is not None:
                await ws.close(1013, "ya hay un aparato conectado")
                return
            self.cliente = ws
            try:
                async for m in ws:
                    with self._lock:
                        if isinstance(m, (bytes, bytearray)):
                            self.entrada.append(Marco(T_AUDIO, bytes(m)))
                        else:
                            self.entrada.append(Marco(T_CONTROL, m.encode()))
            except Exception:
                pass
            finally:
                if self.cliente is ws:
                    self.cliente = None

        import asyncio
        self._bucle = asyncio.get_running_loop()
        # Buscar un puerto libre en vez de rendirse: en una maquina ajena
        # cualquier puerto puede estar tomado por un servicio del sistema, y
        # que el WiFi no arranque por eso seria absurdo.
        ultimo = None
        for intento in range(8):
            try:
                self._servidor = await serve(atender, "0.0.0.0", self.puerto,
                                             max_size=None)
                return self._servidor
            except OSError as e:
                ultimo = e
                self.puerto += 1
        raise ultimo

    @property
    def conectado(self) -> bool:
        return self.cliente is not None

    # ------------------------------------------------------------ enviar --
    def _mandar(self, dato) -> None:
        import asyncio

        ws = self.cliente
        if ws is None or self._bucle is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(ws.send(dato), self._bucle)
        except Exception:
            pass

    def enviar(self, tipo: int, carga: bytes) -> None:
        self._mandar(carga if tipo == T_AUDIO else carga.decode("utf-8", "replace"))

    def enviar_control(self, obj: dict) -> None:
        self._mandar(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))

    def enviar_audio(self, pcm: bytes) -> None:
        self._mandar(pcm)

    # -------------------------------------------------------------- leer --
    def leer(self) -> list[Marco]:
        with self._lock:
            m, self.entrada = self.entrada, []
        return m

    def cerrar(self) -> None:
        if self._servidor:
            self._servidor.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()


class TransporteDoble:
    """Cable y WiFi a la vez, sin que el agente se entere de cual esta usando.

    Se manda por los dos: si solo hay uno conectado, el otro no hace nada. Asi
    se puede desenchufar el cable a mitad de una conversacion y seguir por red,
    o al reves, sin reiniciar.
    """

    def __init__(self, *transportes):
        self.hijos = [t for t in transportes if t is not None]

    @property
    def descartados(self) -> int:
        return sum(getattr(t, "descartados", 0) for t in self.hijos)

    def enviar(self, tipo: int, carga: bytes) -> None:
        for t in self.hijos:
            t.enviar(tipo, carga)

    def enviar_control(self, obj: dict) -> None:
        for t in self.hijos:
            t.enviar_control(obj)

    def enviar_audio(self, pcm: bytes) -> None:
        for t in self.hijos:
            t.enviar_audio(pcm)

    def leer(self) -> list[Marco]:
        salida: list[Marco] = []
        for t in self.hijos:
            salida.extend(t.leer())
        return salida

    def cerrar(self) -> None:
        for t in self.hijos:
            t.cerrar()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()
