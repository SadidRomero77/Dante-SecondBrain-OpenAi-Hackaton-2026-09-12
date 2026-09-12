"""Punto de entrada: dante <comando>"""
from __future__ import annotations

import argparse
import sys

AYUDA = """\
Comandos de Dante:

  dante doctor          Revisa que el entorno este listo. No gasta creditos.
  dante smoke           Prueba la Realtime API con una conversacion de texto.
  dante smoke --audio   Igual, pero pide la respuesta hablada y la guarda en WAV.
  dante monitor        Reinicia el aparato y muestra lo que imprime por serie.
  dante puente         Microfono -> PC -> parlante. Aprieta BOOT y habla.
  dante hablar         Dante conversando. Aprieta BOOT, habla, suelta.
  dante hablar --panel Ademas abre el panel web en el navegador.
  dante semilla        Carga una persona de ejemplo con su pasado.
  dante memoria        Muestra que recuerda Dante ahora mismo.
  dante setup          Le pasa al aparato la red WiFi y la IP del PC.
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dante", description="Segundo cerebro Dante",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=AYUDA)
    sub = p.add_subparsers(dest="comando")

    sub.add_parser("doctor", help="revisa el entorno")

    s = sub.add_parser("smoke", help="prueba la Realtime API")
    s.add_argument("--audio", action="store_true",
                   help="pedir la respuesta hablada y guardarla en WAV")

    st = sub.add_parser("setup", help="configurar el WiFi del aparato")
    st.add_argument("--ssid", default="", help="nombre de la red")
    st.add_argument("--clave", default="", help="contrasena de la red")
    st.add_argument("--host", default="", help="IP de este PC (se detecta sola)")
    st.add_argument("--puerto", type=int, default=0)
    st.add_argument("--borrar", action="store_true", help="olvidar la red guardada")

    se = sub.add_parser("semilla", help="cargar datos de ejemplo")
    se.add_argument("--borrar", action="store_true", help="vaciar antes de sembrar")
    sub.add_parser("memoria", help="ver que recuerda Dante")

    h = sub.add_parser("hablar", help="conversar con Dante")
    h.add_argument("--simular", type=float, default=0.0, metavar="SEG",
                   help="finge apretar el boton N segundos, para probar sin la placa")
    h.add_argument("--limite", type=float, default=0.0, metavar="SEG",
                   help="salir solo despues de N segundos")
    h.add_argument("--panel", nargs="?", type=int, const=8800, default=0,
                   metavar="PUERTO",
                   help="abrir el panel web (por defecto en el 8800)")
    h.add_argument("--solo-cara", action="store_true",
                   help="el aparato solo pone la cara; el audio va por el panel")
    h.add_argument("--diario", dest="diario", action="store_true", default=None,
                   help="forzar el saludo del dia aunque ya lo haya dado")
    h.add_argument("--sin-diario", dest="diario", action="store_false",
                   help="arrancar callado")

    pu = sub.add_parser("puente", help="prueba el camino completo por USB")
    pu.add_argument("--segundos", type=float, default=60.0)

    m = sub.add_parser("monitor", help="lee el puerto serie del aparato")
    m.add_argument("--segundos", type=float, default=15.0,
                   help="cuanto escuchar (por defecto 15)")
    m.add_argument("--sin-reinicio", action="store_true",
                   help="no reiniciar la placa antes de escuchar")

    args = p.parse_args(argv)

    if args.comando == "doctor":
        from .doctor import revisar
        return 1 if revisar() else 0

    if args.comando == "smoke":
        from .smoke import correr
        return correr(con_audio=args.audio)

    if args.comando == "setup":
        from .setup import correr as configurar
        return configurar(ssid=args.ssid, clave=args.clave, host=args.host,
                          puerto=args.puerto, borrar=args.borrar)

    if args.comando == "semilla":
        from .semilla import correr as sembrar
        return sembrar(borrar=args.borrar)

    if args.comando == "memoria":
        from .semilla import mostrar
        return mostrar()

    if args.comando == "hablar":
        from .sesion import correr as hablar
        return hablar(simular=args.simular, limite=args.limite,
                      con_diario=args.diario, con_panel=args.panel,
                      solo_cara=args.solo_cara)

    if args.comando == "puente":
        from .puente import correr as puentear
        return puentear(segundos=args.segundos)

    if args.comando == "monitor":
        from .monitor import correr as monitorear
        return monitorear(segundos=args.segundos, reiniciar=not args.sin_reinicio)

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
