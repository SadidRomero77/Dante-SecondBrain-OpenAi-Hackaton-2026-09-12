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
