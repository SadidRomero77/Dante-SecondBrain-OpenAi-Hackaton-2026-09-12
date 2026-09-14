"""En la nube: un Kibo propio para cada cuenta, con memoria que se queda.

Dante es de un solo inquilino por diseno -un perro, una persona, una memoria-
y eso es correcto para el producto. Pero un portal publicado lo abre gente de
muchas casas: si comparten una sola sesion, se pisan al hablar y el segundo
lee la vida del primero.

Aqui cada cuenta recibe lo suyo: su sesion, su memoria y su conexion con
OpenAI. La memoria nace en blanco -asi Kibo se presenta por voz y la persona
lo configura conversando- pero NO se borra. Antes colgaba de una galleta
anonima y se tiraba a los ocho minutos: se configuraba el perro, se
registraba una cara, se dejaba un recado, y al volver no habia nada. Una
memoria que se borra sola es exactamente lo contrario de lo que promete esto.

Lo que si se corta es la conversacion. El audio del Realtime cuesta dinero de
verdad y una direccion publica sin freno vacia una cuenta en una tarde: hay
tope de conversaciones a la vez y de minutos por conversacion. Al cortarse,
lo hablado se consolida en la memoria y volver a hablar abre otra.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import time
from pathlib import Path

from . import config, memoria


def activo() -> bool:
    return str(config._v("DANTE_DEMO", "")).strip().lower() in ("1", "si", "true")


def _n(clave: str, defecto: int) -> int:
    try:
        return int(str(config._v(clave, "")).strip() or defecto)
    except ValueError:
        return defecto


MINUTOS = lambda: _n("DANTE_DEMO_MINUTOS", 8)      # noqa: E731
MAXIMO = lambda: _n("DANTE_DEMO_MAX", 4)           # noqa: E731


# Una carpeta por cuenta, al lado de la memoria principal. En el contenedor
# eso es el volumen /datos, que sobrevive a reinicios y despliegues. Antes
# vivia en /tmp: cada despliegue se llevaba la vida de todos.
RAIZ = config.DB.parent / "cuentas"

# Para peticiones sin cuenta, que no deberian tocar memoria. Si alguna lo
# hace, cae en un sitio desechable y nunca en la base del dueno del aparato.
SIN_CUENTA = Path(tempfile.gettempdir()) / "kibo-sin-cuenta" / "memoria.db"


def ruta_de(id_: str) -> Path:
    """Donde vive la memoria de esta cuenta.

    Existe separado de Visita porque el navegador pide cosas -los ajustes, la
    agenda- antes de abrir el websocket. Si en ese hueco no tuviera ruta
    propia, caeria en la base del dueno del aparato y veria una vida que no es
    la suya. Eso paso, y por eso esto esta aqui.
    """
    limpio = "".join(c for c in (id_ or "") if c.isalnum() or c in "-_")[:40]
    carpeta = RAIZ / limpio if limpio else SIN_CUENTA.parent
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
        # Su propio reconocedor de caras: uno compartido le enseñaria a este
        # visitante las caras que registro otro.
        self.rostros = None
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


async def abrir(id_: str) -> Visita:
    """Levanta un Kibo entero, solo para esta cuenta, sobre su memoria."""
    from . import ajustes
    from .sesion import (Sesion, TransporteNulo, _abrir_ws, _dar_recados,
                         _presentarse, _vigilar_recordatorios)

    v = Visita(id_)
    _visitas[id_] = v
    memoria.RUTA.set(v.ruta)

    db = v.db = memoria.abrir(v.ruta)
    try:
        v.ws = await _abrir_ws(config.MODELO_VOZ, config.API_KEY)
    except Exception:
        _visitas.pop(id_, None)
        db.close()
        raise
    s = Sesion(TransporteNulo(), v.ws, db)
    s.bucle = asyncio.get_running_loop()
    v.sesion = s

    await s.configurar()
    v.tareas = [
        asyncio.create_task(s.leer_modelo()),
        asyncio.create_task(s.reproducir()),
        # Los recordatorios los dice el cuando llega la hora. En la nube no
        # corria: se creaban, se veian en la lista, y nunca sonaban.
        asyncio.create_task(_vigilar_recordatorios(s)),
        asyncio.create_task(_cerrar_cuando_venza(id_)),
    ]
    # Lo mismo que en casa: si todavia no conoce a nadie, se presenta; si
    # alguien dejo un recado, abre con eso. Antes se presentaba siempre, como
    # si la memoria estuviera vacia aunque ya supiera quien era.
    if ajustes.falta_presentarse(db):
        v.tareas.append(asyncio.create_task(_presentarse(s)))
    elif memoria.mensajes_pendientes(db):
        v.tareas.append(asyncio.create_task(_dar_recados(s)))
    print(f"  [demo] visita {id_[:6]} abierta ({cuantas()}/{MAXIMO()})")
    return v


async def _cerrar_cuando_venza(id_: str) -> None:
    while True:
        v = _visitas.get(id_)
        if v is None:
            return
        # Solo el tiempo cierra una visita. Cerrarla al desconectar el
        # navegador borraba lo que el visitante acababa de guardar en cuanto
        # recargaba la pagina, que es lo primero que hace cualquiera.
        if v.vencida:
            print(f"  [demo] visita {id_[:6]} vencio a los {MINUTOS()} min")
            await cerrar(id_)
            return
        await asyncio.sleep(10)


# Codigo de cierre que el portal entiende como "se acabo el tiempo": no
# reconecta solo, espera a que la persona vuelva a hablar.
VENCIDA = 4000


async def cerrar(id_: str) -> None:
    """Corta la conversacion y guarda lo hablado. La memoria se queda."""
    v = _visitas.pop(id_, None)
    if v is None:
        return
    # Cuando cierra el reloj, quien llama es una de estas tareas: cancelarse a
    # si misma cortaria el cierre por la mitad, antes de guardar lo hablado.
    otras = [t for t in v.tareas if t is not asyncio.current_task()]
    for t in otras:
        t.cancel()
    for t in otras:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await t
    if v.ws is not None:
        with contextlib.suppress(Exception):
            await v.ws.close()
    for c in list(v.clientes):
        with contextlib.suppress(Exception):
            await c.close(VENCIDA, "pausa")
    s = v.sesion
    texto = "\n".join(s.dialogo) if s is not None else ""
    if v.db is not None:
        with contextlib.suppress(Exception):
            memoria.cerrar_episodio(v.db, s.episodio, texto)
        with contextlib.suppress(Exception):
            v.db.close()
    # Lo que se hablo pasa a la memoria, igual que en casa al cerrar. Sin esto
    # lo que la persona contaba de viva voz se perdia al cortarse. Va en otro
    # hilo y con su propia conexion: llama a OpenAI y tarda.
    if texto.strip() and s is not None:
        asyncio.create_task(asyncio.to_thread(_consolidar, v.ruta, texto,
                                              s.episodio))
    print(f"  [demo] conversacion {id_[:6]} cerrada ({cuantas()} abiertas)")


def _consolidar(ruta: Path, texto: str, episodio: int) -> None:
    from . import consolidar
    c = memoria.abrir(ruta)
    try:
        r = consolidar.de_transcripcion(c, texto, episodio)
        print(f"  [demo] consolidado: {r.get('hechos', 0)} hechos nuevos")
    except Exception as e:
        print(f"  [demo] no pude consolidar la conversacion: {e}")
    finally:
        c.close()


async def cerrar_todas() -> None:
    for id_ in list(_visitas):
        await cerrar(id_)
