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

from . import config, consolidar, diario, memoria, mundo, panel, vision
from .transporte import T_AUDIO, T_CONTROL, T_LOG, TransporteSerie

VID_ESPRESSIF = 0x303A
TROZO = 960                 # 20 ms de PCM16 mono a 24 kHz
RITMO = 0.020               # exactamente tiempo real
PRECARGA = 6                # trozos en cola antes de empezar: 120 ms de colchon


def _reloj_fino() -> None:
    """Pide a Windows un temporizador de 1 ms.

    Por defecto la resolucion es de 15.6 ms, asi que dormir 20 ms duerme entre
    16 y 31. Esa irregularidad se oye como audio sucio.
    """
    try:
        import ctypes
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
    except Exception:
        pass

PERSONALIDAD = """\
RESPONDE SIEMPRE EN ESPANOL. Aunque el audio se oiga mal, aunque no entiendas \
nada, aunque te hablen en otro idioma: tu contestas en espanol. Sin excepcion.

Eres Dante, un perro que acompana a una persona en su casa. Hablas espanol \
de America Latina, con acento neutro y calido.

Como hablas:
- Frases cortas. Estas hablando en voz alta, no escribiendo.
- Sin listas, sin vinetas, sin emojis. Nunca leas simbolos en voz alta.
- Directo al grano: responde primero, explica despues solo si hace falta.
- Trata a la persona con carino, sin ser meloso ni infantilizarla.

Que puedes afirmar, en orden de importancia:

1. NO INVENTES LO QUE VES. Tienes camara, pero solo ves cuando usas las \
herramientas mirar o quien_esta. Nunca describas un lugar, una persona ni una \
escena sin haber usado una de las dos. Si la herramienta dice que no hay \
camara, di que por ahora solo escuchas.

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


HERRAMIENTAS = [
    {
        "type": "function",
        "name": "recordar",
        "description": (
            "Busca en la memoria de esta persona. USALA SIEMPRE antes de "
            "responder cualquier cosa sobre su vida, su familia, su pasado o "
            "sus rutinas. Devuelve cada hecho con la fecha en que se anoto y "
            "de donde salio. Si vuelve vacia, di que no lo tienes anotado: "
            "nunca completes con algo que suene razonable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Que estas buscando, en lenguaje natural.",
                }
            },
            "required": ["consulta"],
        },
    },
    {
        "type": "function",
        "name": "anotar",
        "description": (
            "Guarda un hecho nuevo sobre la vida de esta persona, para "
            "recordarlo en proximas conversaciones. Usala cuando te cuenten "
            "algo que valga la pena conservar, o cuando te lo pidan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hecho": {
                    "type": "string",
                    "description": "El hecho en una frase corta y clara, en tercera persona.",
                },
                "sujeto": {
                    "type": "string",
                    "description": "De quien trata, si es de otra persona. Opcional.",
                },
            },
            "required": ["hecho"],
        },
    },
    {
        "type": "function",
        "name": "agenda",
        "description": "Que hay hoy: medicamentos, citas, visitas.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "quien_esta",
        "description": (
            "Mira por la camara y dice quien esta enfrente. Usala cuando "
            "pregunten quien esta, quien llego, o si te saluda alguien que no "
            "identificas. Si devuelve una cara desconocida, NO adivines quien "
            "es: pregunta el nombre y ofrece registrarla."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "mirar",
        "description": (
            "Toma una foto de lo que hay enfrente y la pone en la conversacion "
            "para que puedas verla. Usala cuando pregunten que ves, que es "
            "esto, de que color es algo, o que dice un papel."
        ),
        "parameters": {
            "type": "object",
            "properties": {"pregunta": {
                "type": "string",
                "description": "que hay que mirar en la imagen"}},
        },
    },
    {
        "type": "function",
        "name": "recordar_cara",
        "description": (
            "Registra la cara de quien esta enfrente con su nombre, para "
            "reconocerla la proxima vez. Solo con una persona en cuadro."
        ),
        "parameters": {
            "type": "object",
            "properties": {"nombre": {"type": "string"}},
            "required": ["nombre"],
        },
    },
    {
        "type": "function",
        "name": "buscar_web",
        "description": (
            "Busca en internet. USALA SOLO para cosas de HOY que no puedes "
            "saber: noticias, resultados deportivos, precios, el estado de "
            "algo ahora mismo. NO la uses para conocimiento general (quien "
            "pinto la Mona Lisa, cuanto mide el Everest): eso ya lo sabes y "
            "buscarlo mete segundos de silencio en la conversacion."
        ),
        "parameters": {
            "type": "object",
            "properties": {"consulta": {"type": "string"}},
            "required": ["consulta"],
        },
    },
    {
        "type": "function",
        "name": "hora_en",
        "description": ("Que hora y que dia es. Con una ciudad, la hora alli. "
                        "Sin ciudad, la hora local. Es instantaneo."),
        "parameters": {
            "type": "object",
            "properties": {"lugar": {"type": "string",
                                     "description": "ciudad o pais. Opcional."}},
        },
    },
    {
        "type": "function",
        "name": "clima",
        "description": "El clima de hoy en una ciudad.",
        "parameters": {
            "type": "object",
            "properties": {"lugar": {"type": "string"}},
            "required": ["lugar"],
        },
    },
    {
        "type": "function",
        "name": "registrar_persona",
        "description": "Da de alta a alguien nuevo en la memoria, con su relacion.",
        "parameters": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string"},
                "relacion": {"type": "string",
                             "description": "hija, vecino, medico..."},
            },
            "required": ["nombre"],
        },
    },
]


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
    def __init__(self, t: TransporteSerie, ws, db):
        self.t = t
        self.ws = ws
        self.db = db
        self.episodio = memoria.abrir_episodio(db)
        self.ojos = vision.Ojos()
        # El panel se cuelga de aqui: cada cosa que pasa se le avisa. Si no hay
        # panel, la lista esta vacia y no cuesta nada.
        self.oyentes: list = []
        self.estado = "idle"
        self.bucle = None
        self.dialogo: list[str] = []
        self.cola = asyncio.Queue()      # audio hacia el parlante, ya troceado
        self.hablando_usuario = False
        self.enviados = 0
        self.recibidos = 0
        self.t0 = 0.0
        self.respondiendo = False

    # ------------------------------------------------------------ enviar --
    def avisar(self, tipo: str, **datos) -> None:
        """Le cuenta al panel lo que esta pasando. Nunca revienta la sesion."""
        if tipo == "estado":
            self.estado = datos.get("v", self.estado)
        for f in list(self.oyentes):
            try:
                f({"t": tipo, **datos})
            except Exception:
                pass

    def cara(self, v: str) -> None:
        """Cambia el estado en la pantalla del aparato y avisa al panel."""
        self.t.enviar_control({"t": "emocion", "v": v})
        self.avisar("estado", v=v)

    def pantalla(self, titulo: str, cuerpo: str, seg: int = 8) -> None:
        self.t.enviar_control({"t": "texto", "titulo": titulo,
                               "cuerpo": cuerpo[:150], "seg": seg})
        self.avisar("pantalla", titulo=titulo, cuerpo=cuerpo)

    async def _ev(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj))

    # ------------------------------------------------- entradas del panel --
    async def decir_texto(self, texto: str) -> None:
        """Alguien escribio desde el panel. Mismo camino que la voz."""
        if not texto.strip():
            return
        self.avisar("dijo", quien="usuario", texto=texto)
        self.dialogo.append(f"Usuario: {texto}")
        await self._ev({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": texto}]},
        })
        self.cara("pensando")
        self.t0 = time.time()
        self.respondiendo = True
        await self._ev({"type": "response.create", "response": {}})

    async def audio_del_panel(self, pcm: bytes) -> None:
        if self.hablando_usuario and pcm:
            self.enviados += 1
            await self._ev({"type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm).decode()})

    async def configurar(self) -> None:
        # La tarjeta va al final y no cambia entre turnos: es lo que el cache
        # de prompt puede reusar.
        instrucciones = PERSONALIDAD + "\n\n--- LO QUE RECUERDAS ---\n" + \
            memoria.tarjeta_de_perfil(self.db)
        await self._ev({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": instrucciones,
                "tools": HERRAMIENTAS,
                "tool_choice": "auto",
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
            self.cara("escuchando")
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
                self.cara("idle")
                return
            self.cara("pensando")
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
                    self.cara("hablando")
                pcm = base64.b64decode(ev["delta"])
                self.recibidos += 1
                for i in range(0, len(pcm), TROZO):
                    await self.cola.put(pcm[i:i + TROZO])

            elif tipo == "response.function_call_arguments.done":
                await self._herramienta(ev.get("name", ""),
                                        ev.get("arguments", "{}"),
                                        ev.get("call_id", ""))

            elif tipo == "response.output_audio_transcript.done":
                txt = ev.get("transcript", "").strip()
                print(f"   Dante: {txt}")
                self.dialogo.append(f"Dante: {txt}")
                self.avisar("dijo", quien="dante", texto=txt)

            elif tipo == "response.done":
                self.respondiendo = False
                self.recibidos = 0
                await self.cola.put(None)     # marca de fin

    async def _herramienta(self, nombre: str, argumentos: str, call_id: str) -> None:
        """Ejecuta una herramienta y le devuelve el resultado al modelo.

        Todo lo que Dante puede afirmar sobre la vida de la persona pasa por
        aqui. Si esto devuelve vacio, la respuesta correcta es "no lo tengo
        anotado", no una suposicion.
        """
        try:
            a = json.loads(argumentos or "{}")
        except ValueError:
            a = {}
        self.avisar("herramienta", nombre=nombre, argumentos=a)

        if nombre == "recordar":
            r = memoria.recordar(self.db, a.get("consulta", ""))
            salida = {"encontrados": len(r), "hechos": r}
            print(f"   [memoria] recordar({a.get('consulta','')!r}) -> {len(r)}")

        elif nombre == "anotar":
            hecho = a.get("hecho", "")
            id_ = memoria.anotar(self.db, hecho, a.get("sujeto", ""))
            salida = {"guardado": True, "id": id_}
            print(f"   [memoria] anotado: {hecho}")
            # Que se vea en la pantalla que quedo guardado. Con este usuario,
            # una confirmacion que solo se dice se olvida; una que se lee, no.
            self.pantalla("Anotado", hecho, 7)
            self.cara("feliz")

        elif nombre == "agenda":
            e = memoria.agenda_de(self.db, "hoy")
            salida = {"hoy": e}
            print(f"   [memoria] agenda -> {len(e)}")
            if e:
                self.pantalla("Hoy", " · ".join(e), 9)

        elif nombre == "quien_esta":
            salida = self.ojos.quien_esta()
            print(f"   [vision] {salida}")

        elif nombre == "registrar_persona":
            id_ = memoria.registrar_persona(self.db, a.get("nombre", ""),
                                            a.get("relacion", ""))
            salida = {"registrada": True, "id": id_}
            print(f"   [memoria] persona: {a.get('nombre','')}")
            self.cara("atencion")

        elif nombre == "recordar_cara":
            cuadro = self.ojos.camara.ultimo() if self.ojos.activa else None
            if cuadro is None:
                salida = {"ok": False, "motivo": "no hay camara"}
            else:
                salida = self.ojos.rostros.registrar(cuadro, a.get("nombre", ""))
            print(f"   [vision] registrar cara -> {salida}")

        elif nombre == "mirar":
            b64 = self.ojos.cuadro_base64()
            if not b64:
                salida = {"veo": False, "motivo": self.ojos.motivo or "sin camara"}
            else:
                # La imagen entra como un mensaje mas de la conversacion: el
                # modelo de voz acepta imagenes en el mismo socket, asi que no
                # hace falta un segundo modelo ni una segunda llamada.
                await self._ev({
                    "type": "conversation.item.create",
                    "item": {"type": "message", "role": "user", "content": [
                        {"type": "input_image",
                         "image_url": f"data:image/jpeg;base64,{b64}"}]},
                })
                salida = {"veo": True,
                          "nota": "la foto ya esta en la conversacion, describela"}
                print(f"   [vision] foto enviada ({len(b64)} caracteres)")

        elif nombre == "buscar_web":
            q = a.get("consulta", "")
            print(f"   [mundo] buscando: {q!r}")
            salida = mundo.buscar_web(q)

        elif nombre == "hora_en":
            salida = mundo.hora_en(a.get("lugar", ""))
            print(f"   [mundo] hora {a.get('lugar','aqui')} -> {salida.get('hora','?')}")

        elif nombre == "clima":
            salida = mundo.clima(a.get("lugar", "Bogota"))
            print(f"   [mundo] clima {a.get('lugar','')}")

        else:
            salida = {"error": f"herramienta desconocida: {nombre}"}

        # Los campos que empiezan con guion bajo son nuestros: costos, tiempos,
        # diagnostico. Si se los pasamos al modelo, puede decirlos en voz alta.
        if isinstance(salida, dict):
            interno = {k: v for k, v in salida.items() if k.startswith("_")}
            salida = {k: v for k, v in salida.items() if not k.startswith("_")}
            if interno:
                print(f"   [interno] {interno}")

        await self._ev({
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id,
                     "output": json.dumps(salida, ensure_ascii=False)},
        })
        await self._ev({"type": "response.create", "response": {}})

    # ---------------------------------------------------- reproduccion ----
    async def reproducir(self) -> None:
        """Le da el audio al aparato al ritmo real, con reloj absoluto.

        El modelo genera mucho mas rapido que tiempo real, asi que hay que
        dosificar. Pero dormir 20 ms en cada vuelta no sirve: cada espera se
        pasa un poco y los errores se suman hasta desbordar al aparato o
        dejarlo seco. En vez de eso llevamos la hora a la que le toca a cada
        trozo y dormimos hasta ella, asi el error nunca se acumula.
        """
        proximo = 0.0
        sonando = False

        while True:
            trozo = await self.cola.get()

            if trozo is None:                       # fin de la respuesta
                sonando = False
                self.cara("idle")
                continue

            if not sonando:
                # Esperar a tener colchon antes de arrancar: si empezamos con
                # la cola vacia, cualquier demora de red se oye como un corte.
                while self.cola.qsize() < PRECARGA:
                    await asyncio.sleep(0.005)
                    if self.cola.qsize() == 0:
                        break
                sonando = True
                proximo = time.perf_counter()

            self.t.enviar_audio(trozo)

            proximo += RITMO
            falta = proximo - time.perf_counter()
            if falta > 0:
                await asyncio.sleep(falta)
            else:
                proximo = time.perf_counter()       # nos atrasamos: resincronizar


async def _dar_diario(s: "Sesion") -> None:
    """Dante arranca hablando el. Nadie le pregunto nada."""
    await asyncio.sleep(1.2)
    print(">> EL DIARIO")
    s.t.enviar_control({"t": "emocion", "v": "hablando"})
    s.respondiendo = True
    s.t0 = time.time()
    await s._ev({
        "type": "response.create",
        "response": {"instructions": diario.instrucciones(s.db)},
    })
    diario.marcar(s.db)


async def _simular(s: "Sesion", segundos: float) -> None:
    """Finge que alguien apreta el boton, para poder probar sin tener la placa
    delante. Abre el microfono, espera, y cierra el turno."""
    await asyncio.sleep(2.0)
    print(f"  [simulado] boton abajo por {segundos:.0f} s")
    await s._boton(True)
    await asyncio.sleep(segundos)
    await s._boton(False)


async def _correr(simular: float = 0.0, limite: float = 0.0,
                  con_diario: bool | None = None, con_panel: int = 0) -> int:
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

        db = memoria.abrir()
        r = memoria.resumen(db)
        print(f"  memoria: {r['personas']} personas, {r['hechos']} hechos, "
              f"usuario {r['usuario']}\n")

        async with ws:
            s = Sesion(t, ws, db)
            if s.ojos.arrancar():
                n = len(s.ojos.rostros.conocidas)
                print(f"  camara: activa, {n} cara(s) registrada(s)\n")
            else:
                print(f"  camara: {s.ojos.motivo}\n")
            if con_panel:
                try:
                    url = panel.arrancar(s, con_panel)
                    print(f"  panel: {url}\n")
                except Exception as e:
                    print(f"  panel: no arranco ({type(e).__name__}: {e})\n")

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
            if con_diario if con_diario is not None else diario.toca_hoy(db):
                aparte.append(asyncio.create_task(_dar_diario(s)))
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
                texto = "\n".join(s.dialogo)
                s.ojos.parar()
                memoria.cerrar_episodio(db, s.episodio, texto)
                if texto.strip():
                    print("\n  consolidando la conversacion...")
                    r = consolidar.de_transcripcion(db, texto, s.episodio)
                    if r.get("resumen"):
                        print(f"  resumen: {r['resumen']}")
                    print(f"  hechos nuevos: {r['hechos']}"
                          + (f", eventos {r['eventos']}" if r.get("eventos") else "")
                          + (f", repetidos {r['repetidos']}" if r.get("repetidos") else "")
                          + (f"  ({r['motivo']})" if r.get("motivo") else ""))
                db.close()
    return 0


def correr(simular: float = 0.0, limite: float = 0.0,
           con_diario: bool | None = None, con_panel: int = 0) -> int:
    _reloj_fino()
    try:
        return asyncio.run(_correr(simular, limite, con_diario, con_panel))
    except KeyboardInterrupt:
        print("\nhasta luego")
        return 0
