"""dante puente — prueba el camino completo: microfono -> PC -> parlante.

Manten apretado el boton BOOT y habla. Al soltarlo, el PC te devuelve lo
grabado. Si te escuchas, el paso 3 esta cerrado: el audio cruzo el cable en
las dos direcciones y el PC estuvo en el medio.

Guarda lo grabado en data/puente.wav para poder revisarlo despues.
"""
from __future__ import annotations

import sys
import time
import wave

from . import config
from .transporte import T_AUDIO, T_CONTROL, T_LOG, TransporteSerie

VID_ESPRESSIF = 0x303A
TROZO = 960          # 20 ms de PCM16 mono a 24 kHz


def _puerto() -> str | None:
    from serial.tools import list_ports

    if config.PUERTO_SERIE:
        return config.PUERTO_SERIE
    for p in list_ports.comports():
        if p.vid == VID_ESPRESSIF:
            return p.device
    return None


def _nivel(pcm: bytes) -> tuple[int, float]:
    import numpy as np

    if not pcm:
        return 0, 0.0
    a = np.frombuffer(pcm, dtype="<i2").astype("float32")
    return int(abs(a).max()), float((a ** 2).mean() ** 0.5)


def _guardar(pcm: bytes) -> str:
    destino = config.RAIZ / "data" / "puente.wav"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)
    return str(destino)


def correr(segundos: float = 60.0) -> int:
    puerto = _puerto()
    if not puerto:
        print("No encontre el aparato. Conectalo por USB.")
        return 1

    print(f"\n=== dante puente ===  ({puerto})\n")
    try:
        t = TransporteSerie(puerto)
    except Exception as e:
        print(f"No pude abrir {puerto}: {e}")
        print("Cierra el Monitor Serie del Arduino IDE si lo tienes abierto.")
        return 1

    t.enviar_control({"t": "hola?"})   # el saludo del arranque siempre se pierde

    grabando = False
    grabado = bytearray()
    recibidos = 0
    saludo = False
    fin = time.time() + segundos

    print("Manten apretado el boton BOOT y habla. Sueltalo para oirte.")
    print("Ctrl-C para salir.\n")

    with t:
        # El aparato arranca antes de que abramos el puerto, asi que su saludo
        # inicial siempre se pierde. Se lo volvemos a pedir.
        t.enviar_control({"t": "hola?"})

        while time.time() < fin:
            try:
                marcos = t.leer()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nel puerto se corto: {type(e).__name__}: {e}")
                return 1

            for m in marcos:
                if m.tipo == T_LOG:
                    print(f"  [aparato] {m.texto}")

                elif m.tipo == T_CONTROL:
                    ev = m.json
                    if ev.get("t") == "hola":
                        saludo = True
                        print(f"  saludo del aparato: {m.texto}")
                        if not (ev.get("dac") and ev.get("adc") and ev.get("i2s")):
                            print("  [ojo] algo no inicializo bien en la placa")
                        print()
                    elif ev.get("t") == "boton":
                        if ev.get("v") == "abajo":
                            grabando = True
                            grabado.clear()
                            print(">> GRABANDO (boton apretado)")
                        else:
                            grabando = False
                            pico, rms = _nivel(bytes(grabado))
                            seg = len(grabado) / (config.SAMPLE_RATE * 2)
                            print(f"   {seg:.1f} s | pico {pico} | rms {rms:.0f}")
                            print(">> DEVOLVIENDO por el cable")
                            for i in range(0, len(grabado), TROZO):
                                t.enviar_audio(bytes(grabado[i:i + TROZO]))
                                time.sleep(0.018)   # un poco mas rapido que 20 ms
                            print(f"   guardado en {_guardar(bytes(grabado))}\n")

                elif m.tipo == T_AUDIO:
                    recibidos += 1
                    if grabando:
                        grabado.extend(m.carga)

    print(f"\n--- fin. {recibidos} trozos de audio recibidos, "
          f"{t.descartados} bytes descartados por desincronizacion ---")
    return 0 if recibidos else 1
