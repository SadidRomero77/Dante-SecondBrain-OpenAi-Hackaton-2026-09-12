"""dante monitor — lee el puerto serie del aparato y lo muestra.

Sirve para depurar la placa sin depender de que alguien copie y pegue.
Reinicia el aparato con las lineas de control antes de escuchar, asi
siempre se ve el arranque completo.
"""
from __future__ import annotations

import sys
import time

from . import config

VID_ESPRESSIF = 0x303A


def _buscar_puerto() -> str | None:
    from serial.tools import list_ports

    if config.PUERTO_SERIE:
        return config.PUERTO_SERIE
    for p in list_ports.comports():
        if p.vid == VID_ESPRESSIF:
            return p.device
    # Sin identificador de Espressif: probamos el USB serial generico.
    for p in list_ports.comports():
        if "Bluetooth" not in (p.description or ""):
            return p.device
    return None


def _abrir(puerto: str):
    """Abre el puerto con DTR activo.

    El USB-Serial/JTAG del ESP32-S3 DESCARTA lo que imprime el sketch si el
    host no tiene DTR activado. Hay que fijarlo antes de abrir, no despues.
    Y no hay que tocar RTS: en este puerto un pulso de RTS reinicia el chip y
    lo hace re-enumerar, con lo que el handle muere.
    """
    import serial

    s = serial.Serial()
    s.port = puerto
    s.baudrate = 115200
    s.timeout = 0.4
    s.dtr = True
    s.rts = False
    s.open()
    return s


def correr(segundos: float = 15.0, reiniciar: bool = False) -> int:
    puerto = _buscar_puerto()
    if not puerto:
        print("No encontre el puerto del aparato. Conectalo, o pon "
              "DANTE_PUERTO_SERIE en el .env")
        return 1

    print(f"--- escuchando {puerto} a 115200, {segundos:.0f} s ---")
    try:
        s = _abrir(puerto)
    except Exception as e:
        print(f"No pude abrir {puerto}: {e}")
        print("Cierra el Monitor Serie del Arduino IDE: solo un programa "
              "puede tener el puerto abierto a la vez.")
        return 1

    lineas = 0
    fin = time.time() + segundos
    with s:
        while time.time() < fin:
            try:
                crudo = s.readline()
            except Exception as e:
                print(f"--- el puerto se corto: {type(e).__name__} ---")
                break
            if crudo:
                sys.stdout.write(crudo.decode("utf-8", "replace").rstrip() + "\n")
                sys.stdout.flush()
                lineas += 1

    print(f"--- fin: {lineas} linea(s) ---")
    if lineas == 0:
        print()
        print("Silencio. Las causas tipicas, en orden:")
        print("  1. El sketch se cuelga antes de imprimir.")
        print("  2. 'USB CDC On Boot' quedo en Disabled.")
        print("  3. El Monitor Serie del Arduino IDE tiene el puerto tomado.")
        return 1
    return 0
