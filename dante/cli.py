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

    if args.comando == "monitor":
        from .monitor import correr as monitorear
        return monitorear(segundos=args.segundos, reiniciar=not args.sin_reinicio)

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
