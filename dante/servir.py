"""Dante como servicio: solo el portal, sin aparato y sin camara.

Es la forma de correrlo en un servidor, donde no hay un USB al que enchufar
un perrito ni una webcam mirando a nadie. Cada cuenta trae lo suyo por el
navegador y recibe su propio Kibo, con su memoria, desde 'demo.py'.

El aparato NO desaparece del proyecto: el firmware marca hacia afuera por
WebSocket, asi que un perrito de verdad puede conectarse a este mismo
servidor desde cualquier WiFi. Deja de ser obligatorio, que es distinto de
dejar de existir.
"""

from __future__ import annotations

import asyncio

from . import config, demo, panel


class _SinCuerpo:
    """Lo minimo que el portal le pide a una sesion cuando no hay ninguna.

    En el demo cada mensaje va a la sesion del visitante, no a esta. Esta solo
    existe para que las pantallas que preguntan por la camara o el estado
    contesten algo honesto en vez de reventar.
    """

    estado = "idle"
    bucle = None

    def __init__(self):
        self.oyentes: list = []
        self.oyentes_audio: list = []
        self.ojos = _SinOjos()

    def pantalla(self, *a, **k): pass
    def cara(self, *a, **k): pass
    async def configurar(self): pass


class _SinOjos:
    activa = False
    motivo = "este Dante vive en un servidor: la camara la pone tu navegador"
    rostros = None

    def quien_esta(self): return {"camara": False, "motivo": self.motivo}
    def cuadro_base64(self): return None
    def arrancar(self): return False
    def parar(self): pass


def correr(puerto: int = 0) -> int:
    import uvicorn

    puerto = puerto or int(config._v("PORT", "") or config._v("DANTE_PUERTO_PANEL", "") or 8800)
    if not config.API_KEY:
        print("Falta OPENAI_API_KEY. Sin eso no hay con quien hablar.")
        return 1

    print("\n=== dante servir ===")
    print(f"  modo demo: {'si' if demo.activo() else 'NO'}")
    if demo.activo():
        print(f"  cada cuenta tiene su propio Kibo; memorias en {demo.RAIZ}")
        print(f"  {demo.MAXIMO()} conversaciones a la vez como maximo, "
              f"{demo.MINUTOS()} minutos cada una")
    else:
        print("  OJO: sin DANTE_DEMO=1 todos los visitantes comparten UNA "
              "sesion y UNA memoria.")
    from . import auth
    for a in auth.avisos():
        print(f"  [seguridad] {a}")
    print(f"  escuchando en {config.PANEL_HOST}:{puerto}\n")

    app = panel.crear_app(_SinCuerpo(), None)

    @app.get("/salud")
    def salud():
        """Para que el servidor sepa si seguimos vivos y nos reinicie si no."""
        return {"ok": True, "visitas": demo.cuantas(), "demo": demo.activo()}

    uvicorn.run(app, host=config.PANEL_HOST, port=puerto,
                log_level="warning", access_log=False)
    return 0
