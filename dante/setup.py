"""dante setup — le pasa al aparato la red y la direccion del PC.

Nada de portal cautivo ni de conectarse a un hotspot del aparato: con el cable
puesto, se le escriben las credenciales por el mismo puerto serie y se reinicia.
Se configura desde la misma terminal que corre el agente, y despues se puede
desenchufar el cable.
"""
from __future__ import annotations

import socket
import time

from . import config
from .transporte import T_CONTROL, T_LOG, TransporteSerie

VID_ESPRESSIF = 0x303A


def _puerto() -> str | None:
    from serial.tools import list_ports

    if config.PUERTO_SERIE:
        return config.PUERTO_SERIE
    for p in list_ports.comports():
        if p.vid == VID_ESPRESSIF:
            return p.device
    return None


def ip_local() -> str:
    """La IP de este PC en la red local.

    Se abre un socket UDP hacia afuera sin mandar nada: es la forma fiable de
    saber por cual interfaz saldria el trafico, cuando hay varias.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def correr(ssid: str = "", clave: str = "", host: str = "",
           puerto: int = 0, borrar: bool = False) -> int:
    serie = _puerto()
    if not serie:
        print("No encontre el aparato. Conectalo por USB para configurarlo.")
        return 1

    if borrar:
        ssid = clave = "borrar"
        host = ""

    if not ssid:
        ssid = input("  Nombre de la red WiFi: ").strip()
    if not clave:
        import getpass
        clave = getpass.getpass("  Contrasena de la red (no se muestra): ")
    if not host:
        sugerida = ip_local()
        host = input(f"  Direccion de este PC [{sugerida}]: ").strip() or sugerida
    puerto = puerto or config.PUERTO_WS

    if not ssid or not host:
        print("Faltan datos. No cambio nada.")
        return 1

    print(f"\n  aparato en {serie}")
    print(f"  red       {ssid}")
    print(f"  servidor  {host}:{puerto}")
    print(f"  ficha     {'si' if config.ficha_aparato() else 'NO (revisa data/)'}\n")

    try:
        t = TransporteSerie(serie)
    except Exception as e:
        print(f"No pude abrir {serie}: {e}")
        print("Cierra el Monitor Serie del Arduino IDE si lo tienes abierto.")
        return 1

    with t:
        ficha = config.ficha_aparato()
        t.enviar_control({"t": "wifi", "ssid": ssid, "clave": clave,
                          "host": host, "puerto": puerto, "ficha": ficha})
        print("  enviado. El aparato se reinicia y se conecta solo.")

        # Escuchar un rato lo que diga al arrancar.
        fin = time.time() + 14
        visto = False
        while time.time() < fin:
            for m in t.leer():
                if m.tipo == T_LOG:
                    print(f"  [aparato] {m.texto}")
                elif m.tipo == T_CONTROL:
                    ev = m.json
                    if ev.get("t") == "hola":
                        visto = True
                        via = ev.get("transporte", "?")
                        ip = ev.get("ip", "")
                        print(f"\n  el aparato saludo por {via.upper()}"
                              + (f", con IP {ip}" if ip else ""))
                        if via == "wifi":
                            print("  listo: ya puedes desconectar el cable.")
                        else:
                            print("  todavia por cable. Si no levanta el WiFi en "
                                  "unos segundos, revisa el nombre de la red y "
                                  "que sea de 2.4 GHz: el ESP32 no ve las de 5 GHz.")
                        break
            time.sleep(0.1)

        if not visto:
            print("\n  no alcance a ver el saludo. Corre 'dante hablar' y "
                  "mira si dice wifi conectado.")
    return 0
