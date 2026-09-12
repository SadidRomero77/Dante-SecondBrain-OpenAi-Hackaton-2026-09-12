"""El demo publico: un Dante propio para cada visitante.

Dante es de un solo inquilino por diseno -un perro, una persona, una memoria-
y eso es correcto para el producto. Pero un portal que evalua gente de todo el
mundo necesita lo contrario: si diez jueces entran a la vez y comparten una
sola sesion, se pisan al hablar y el segundo lee la conversacion del primero.

Aqui cada navegador recibe lo suyo: su sesion, su memoria y su conexion con
OpenAI. La memoria arranca EN BLANCO a proposito. No es que falte cargarla: es
que asi Dante hace su propia presentacion por voz y el visitante lo configura
conversando, que es la mejor forma de ensenar lo que hace.

Dos limites que no son opcionales. El audio del Realtime cuesta dinero de
verdad, y una direccion publica sin freno vacia una cuenta en una tarde: hay
tope de visitas a la vez y tope de minutos por visita.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from . import config, memoria

GALLETA = "dante_visita"


def activo() -> bool:
    return str(config._v("DANTE_DEMO", "")).strip().lower() in ("1", "si", "true")


def _n(clave: str, defecto: int) -> int:
    try:
        return int(str(config._v(clave, "")).strip() or defecto)
    except ValueError:
        return defecto


MINUTOS = lambda: _n("DANTE_DEMO_MINUTOS", 8)      # noqa: E731
MAXIMO = lambda: _n("DANTE_DEMO_MAX", 4)           # noqa: E731


# Todas las visitas viven aqui debajo, una carpeta cada una. Se llama por el
# identificador de la galleta para que el navegador encuentre lo suyo antes
# incluso de abrir la conversacion.
RAIZ = Path(tempfile.gettempdir()) / "dante-visitas"


def ruta_de(id_: str) -> Path:
    """Donde vive la memoria de este visitante.

    Existe separado de Visita porque el navegador pide cosas -los ajustes, la
    agenda- antes de abrir el websocket. Si en ese hueco no tuviera ruta
    propia, caeria en la base del dueno del aparato y el visitante veria una
    vida que no es la suya. Eso paso, y por eso esto esta aqui.
    """
    limpio = "".join(c for c in (id_ or "") if c.isalnum() or c in "-_")[:40]
    if not limpio:
        limpio = "anonimo"
    carpeta = RAIZ / limpio
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / "memoria.db"


class Visita:
    """Lo que dura un visitante: su carpeta, su sesion y sus tareas."""

    def __init__(self, id_: str):
        self.id = id_
        self.ruta = ruta_de(id_)
        self.carpeta = self.ruta.parent
        self.sesion = None
        self.ws = None
        self.tareas: list[asyncio.Task] = []
        self.db = None
        self.reparte = False
        self.nacio = time.time()
        self.clientes: set = set()

    @property
    def minutos_vividos(self) -> float:
        return (time.time() - self.nacio) / 60

    @property
    def vencida(self) -> bool:
        return self.minutos_vividos >= MINUTOS()

    @property
    def quedan(self) -> int:
        return max(0, int(MINUTOS() - self.minutos_vividos))


_visitas: dict[str, Visita] = {}


def cuantas() -> int:
    return len(_visitas)


def hay_sitio() -> bool:
    return cuantas() < MAXIMO()


def de(id_: str) -> Visita | None:
    return _visitas.get(id_)


def nueva_id() -> str:
    return secrets.token_urlsafe(16)


async def abrir(id_: str) -> Visita:
    """Levanta un Dante entero, solo para este visitante."""
    from .sesion import Sesion, TransporteNulo, _abrir_ws, _presentarse

    v = Visita(id_)
    _visitas[id_] = v
    memoria.RUTA.set(v.ruta)

    db = v.db = memoria.abrir(v.ruta)          # nace vacia: sin nadie, sin nada
    v.ws = await _abrir_ws(config.MODELO_VOZ, config.API_KEY)
    s = Sesion(TransporteNulo(), v.ws, db)
    s.bucle = asyncio.get_running_loop()
    v.sesion = s

    await s.configurar()
    v.tareas = [
        asyncio.create_task(s.leer_modelo()),
        asyncio.create_task(s.reproducir()),
        # Con la memoria en blanco, lo primero que hace es presentarse y
        # preguntar quien es. El visitante configura el producto usandolo.
        asyncio.create_task(_presentarse(s)),
        asyncio.create_task(_cerrar_cuando_venza(id_)),
    ]
    print(f"  [demo] visita {id_[:6]} abierta ({cuantas()}/{MAXIMO()})")
    return v


async def _cerrar_cuando_venza(id_: str) -> None:
    while True:
        v = _visitas.get(id_)
        if v is None:
            return
        if v.vencida:
            print(f"  [demo] visita {id_[:6]} vencio a los {MINUTOS()} min")
            await cerrar(id_)
            return
        await asyncio.sleep(10)


async def cerrar(id_: str) -> None:
    """Se lleva todo: tareas, conexion y la memoria del visitante."""
    v = _visitas.pop(id_, None)
    if v is None:
        return
    for t in v.tareas:
        t.cancel()
    for t in v.tareas:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await t
    if v.ws is not None:
        with contextlib.suppress(Exception):
            await v.ws.close()
    # Windows no deja borrar un fichero que sigue abierto, asi que la base se
    # cierra antes. Sin esto la carpeta se queda para siempre y el servidor se
    # va llenando de memorias de gente que ya se fue.
    if v.db is not None:
        with contextlib.suppress(Exception):
            v.db.close()
    # Lo que conto el visitante se va con el. No hay por que conservarlo, y
    # conservarlo sin que lo sepa seria lo contrario de lo que predica esto.
    shutil.rmtree(v.carpeta, ignore_errors=True)
    print(f"  [demo] visita {id_[:6]} cerrada ({cuantas()} abiertas)")


async def cerrar_todas() -> None:
    for id_ in list(_visitas):
        await cerrar(id_)
