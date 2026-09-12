"""Punto de entrada: dante <comando>"""
from __future__ import annotations

import argparse
import sys

AYUDA = """\
Comandos de Dante:

  dante doctor          Revisa que el entorno este listo. No gasta creditos.
  dante smoke           Prueba la Realtime API con una conversacion de texto.
  dante smoke --audio   Igual, pero pide la respuesta hablada y la guarda en WAV.
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

    args = p.parse_args(argv)

    if args.comando == "doctor":
        from .doctor import revisar
        return 1 if revisar() else 0

    if args.comando == "smoke":
        from .smoke import correr
        return correr(con_audio=args.audio)

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
