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
  dante semilla        Carga una persona de ejemplo con su pasado.
  dante memoria        Muestra que recuerda Dante ahora mismo.
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

    se = sub.add_parser("semilla", help="cargar datos de ejemplo")
    se.add_argument("--borrar", action="store_true", help="vaciar antes de sembrar")
    sub.add_parser("memoria", help="ver que recuerda Dante")

    h = sub.add_parser("hablar", help="conversar con Dante")
    h.add_argument("--simular", type=float, default=0.0, metavar="SEG",
                   help="finge apretar el boton N segundos, para probar sin la placa")
    h.add_argument("--limite", type=float, default=0.0, metavar="SEG",
                   help="salir solo despues de N segundos")

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

    if args.comando == "semilla":
        from .semilla import correr as sembrar
        return sembrar(borrar=args.borrar)

    if args.comando == "memoria":
        from .semilla import mostrar
        return mostrar()

    if args.comando == "hablar":
        from .sesion import correr as hablar
        return hablar(simular=args.simular, limite=args.limite)

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
