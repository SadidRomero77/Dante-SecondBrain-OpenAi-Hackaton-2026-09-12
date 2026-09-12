"""dante hablar — Dante conversando de verdad.

Une las dos mitades que ya funcionan: el puente USB y la Realtime API.
El audio no se convierte en ningun punto — PCM16 mono a 24 kHz de punta a
punta — asi que esto es mover bytes de un socket al otro.

Los turnos los marca el boton: apretado abre el microfono, soltado cierra el
turno y le pide la respuesta al modelo. Sin deteccion automatica, porque sin
cancelacion de eco Dante se oiria a si mismo y se cortaria solo.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import websockets

from . import config
from .transporte import T_AUDIO, T_CONTROL, T_LOG, TransporteSerie

VID_ESPRESSIF = 0x303A
TROZO = 960                 # 20 ms de PCM16 mono a 24 kHz
RITMO = 0.018               # apenas mas rapido que 20 ms, para no quedarse corto

PERSONALIDAD = """\
Eres Dante, un perro que acompana a una persona en su casa. Hablas espanol \
con acento neutro y calido.

Como hablas:
- Frases cortas. Estas hablando en voz alta, no escribiendo.
- Sin listas, sin vinetas, sin emojis. Nunca leas simbolos en voz alta.
- Directo al grano: responde primero, explica despues solo si hace falta.
- Trata a la persona con carino, sin ser meloso ni infantilizarla.

Que puedes afirmar, en orden de importancia:

1. NO TIENES OJOS. No hay camara conectada. Nunca digas que ves algo, ni \
describas un lugar, una persona o una escena. Si te preguntan que ves, di que \
por ahora solo escuchas.

2. Si no entendiste el audio, o solo se oia ruido, DILO. "No te escuche bien, \
me lo repites?" Jamas rellenes el silencio inventando algo.

3. Sobre la vida de esta persona todavia no tienes memoria. Si te preguntan \
algo personal, di que aun no lo tienes anotado y ofrece anotarlo. NUNCA \
inventes un recuerdo, una fecha ni una persona.

4. Sobre el mundo si puedes responder de lo que sabes, y puedes equivocarte. \
Cuando no estes seguro, dilo con naturalidad: "creo que", "no estoy seguro".

Inventar es la unica falla grave que puedes cometer. Una respuesta segura y \
falsa es peor que decir que no sabes.
"""


def _puerto() -> str | None:
    from serial.tools import list_ports

    if config.PUERTO_SERIE:
        return config.PUERTO_SERIE
    for p in list_ports.comports():
        if p.vid == VID_ESPRESSIF:
            return p.device
    return None


async def _abrir_ws(modelo: str, key: str):
    url = f"wss://api.openai.com/v1/realtime?model={modelo}"
    cab = {"Authorization": f"Bearer {key}"}
    try:
        return await websockets.connect(url, additional_headers=cab, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=cab, max_size=None)


class Sesion:
    def __init__(self, t: TransporteSerie, ws):
        self.t = t
        self.ws = ws
        self.cola = asyncio.Queue()      # audio hacia el parlante, ya troceado
        self.hablando_usuario = False
        self.enviados = 0
        self.recibidos = 0
        self.t0 = 0.0
        self.respondiendo = False

    # ------------------------------------------------------------ enviar --
    async def _ev(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj))

    async def configurar(self) -> None:
        await self._ev({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": PERSONALIDAD,
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE},
                        # Turnos manuales: manda el boton, no la voz.
                        "turn_detection": None,
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE},
                        "voice": config.VOZ,
                    },
                },
            },
        })

    # ------------------------------------------------- aparato -> modelo --
    async def leer_aparato(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            marcos = await loop.run_in_executor(None, self.t.leer)
            for m in marcos:
                if m.tipo == T_AUDIO:
                    if self.hablando_usuario:
                        self.enviados += 1
                        await self._ev({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(m.carga).decode(),
                        })

                elif m.tipo == T_LOG:
                    print(f"  [aparato] {m.texto}")

                elif m.tipo == T_CONTROL:
                    ev = m.json
                    if ev.get("t") == "hola":
                        print(f"  aparato listo: {m.texto}\n")
                    elif ev.get("t") == "boton":
                        await self._boton(ev.get("v") == "abajo")

    async def _boton(self, abajo: bool) -> None:
        if abajo:
            # Cortar lo que Dante estuviera diciendo: el usuario tiene prioridad.
            while not self.cola.empty():
                self.cola.get_nowait()
            self.t.enviar_control({"t": "parar"})
            self.t.enviar_control({"t": "emocion", "v": "escuchando"})
            if self.respondiendo:
                await self._ev({"type": "response.cancel"})
                self.respondiendo = False
            await self._ev({"type": "input_audio_buffer.clear"})
            self.hablando_usuario = True
            self.enviados = 0
            print("\n>> te escucho...")
        else:
            self.hablando_usuario = False
            ms = self.enviados * 20
            print(f">> turno cerrado ({ms} ms de audio)")
            if self.enviados < 5:
                print("   (muy corto, lo ignoro)")
                await self._ev({"type": "input_audio_buffer.clear"})
                self.t.enviar_control({"t": "emocion", "v": "idle"})
                return
            self.t.enviar_control({"t": "emocion", "v": "pensando"})
            self.t0 = time.time()
            self.respondiendo = True
            await self._ev({"type": "input_audio_buffer.commit"})
            await self._ev({"type": "response.create", "response": {}})

    # ------------------------------------------------- modelo -> aparato --
    async def leer_modelo(self) -> None:
        async for crudo in self.ws:
            ev = json.loads(crudo)
            tipo = ev.get("type", "")

            if tipo == "error":
                e = ev.get("error", {})
                print(f"  [API] {e.get('type')}: {e.get('message')}")

            elif tipo == "response.output_audio.delta":
                if self.recibidos == 0:
                    print(f"   primera voz en {time.time() - self.t0:.1f} s")
                    self.t.enviar_control({"t": "emocion", "v": "hablando"})
                pcm = base64.b64decode(ev["delta"])
                self.recibidos += 1
                for i in range(0, len(pcm), TROZO):
                    await self.cola.put(pcm[i:i + TROZO])

            elif tipo == "response.output_audio_transcript.done":
                print(f"   Dante: {ev.get('transcript', '').strip()}")

            elif tipo == "response.done":
                self.respondiendo = False
                self.recibidos = 0
                await self.cola.put(None)     # marca de fin

    # ---------------------------------------------------- reproduccion ----
    async def reproducir(self) -> None:
        """Le da el audio al aparato al ritmo real.

        El modelo genera mucho mas rapido que tiempo real. Si le mandaramos
        todo de golpe, el aparato se quedaria sin espacio y se oiria cortado.
        """
        while True:
            trozo = await self.cola.get()
            if trozo is None:
                self.t.enviar_control({"t": "emocion", "v": "idle"})
                continue
            self.t.enviar_audio(trozo)
            await asyncio.sleep(RITMO)


async def _simular(s: "Sesion", segundos: float) -> None:
    """Finge que alguien apreta el boton, para poder probar sin tener la placa
    delante. Abre el microfono, espera, y cierra el turno."""
    await asyncio.sleep(2.0)
    print(f"  [simulado] boton abajo por {segundos:.0f} s")
    await s._boton(True)
    await asyncio.sleep(segundos)
    await s._boton(False)


async def _correr(simular: float = 0.0, limite: float = 0.0) -> int:
    if not config.API_KEY:
        print("Falta OPENAI_API_KEY en .env. Corre 'dante doctor'.")
        return 1

    puerto = _puerto()
    if not puerto:
        print("No encontre el aparato. Conectalo por USB.")
        return 1

    print(f"\n=== dante hablar ===  ({puerto}, {config.MODELO_VOZ}, voz {config.VOZ})\n")

    try:
        t = TransporteSerie(puerto)
    except Exception as e:
        print(f"No pude abrir {puerto}: {e}")
        print("Cierra el Monitor Serie del Arduino IDE si lo tienes abierto.")
        return 1

    with t:
        try:
            ws = await _abrir_ws(config.MODELO_VOZ, config.API_KEY)
        except Exception as e:
            print(f"No pude conectar con OpenAI: {e}")
            return 1

        async with ws:
            s = Sesion(t, ws)
            await s.configurar()
            t.enviar_control({"t": "hola?"})
            t.enviar_control({"t": "emocion", "v": "idle"})

            print("Manten apretado el boton BOOT, habla, y sueltalo.")
            print("Ctrl-C para salir.\n")

            tareas = [
                asyncio.create_task(s.leer_aparato()),
                asyncio.create_task(s.leer_modelo()),
                asyncio.create_task(s.reproducir()),
            ]
            aparte = []
            if simular:
                # Fuera del grupo de espera: si estuviera dentro, terminar el
                # turno simulado cerraria la sesion antes de oir la respuesta.
                aparte.append(asyncio.create_task(_simular(s, simular)))
            if limite:
                # Salir solo, sin depender de que alguien mate el proceso.
                # En Windows, matar el cmd no mata al nieto: queda tomando el
                # puerto serie y no se puede volver a abrir.
                tareas.append(asyncio.create_task(asyncio.sleep(limite)))
            try:
                await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            except websockets.exceptions.ConnectionClosed as e:
                print(f"\nOpenAI cerro la conexion: {str(e)[:120]}")
            finally:
                for x in tareas + aparte:
                    x.cancel()
    return 0


def correr(simular: float = 0.0, limite: float = 0.0) -> int:
    try:
        return asyncio.run(_correr(simular, limite))
    except KeyboardInterrupt:
        print("\nhasta luego")
        return 0
