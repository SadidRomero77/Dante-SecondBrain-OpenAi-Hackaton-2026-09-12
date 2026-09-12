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

from . import (ajustes, config, consolidar, diario, memoria, mensajes,
               mundo, panel, vision)
from .transporte import (T_AUDIO, T_CONTROL, T_LOG, TransporteDoble,
                         TransporteSerie, TransporteWebSocket)

VID_ESPRESSIF = 0x303A
TROZO = 960                 # 20 ms de PCM16 mono a 24 kHz
RITMO = 0.020               # exactamente tiempo real
PRECARGA = 6                # trozos en cola antes de empezar: 120 ms de colchon


def _callar_ruido_de_windows(bucle) -> None:
    """Silencia una aserción conocida de asyncio en Windows.

    El bucle Proactor lanza AssertionError desde _loop_writing cuando queda una
    escritura pendiente al cerrarse un transporte. Es un fallo conocido de
    CPython, no nuestro, y no rompe nada: la conversación sigue igual. Pero
    aparece en la consola con toda la traza y en medio de un demo asusta.

    Se silencia SOLO ese caso. Cualquier otro error sigue mostrándose entero:
    tapar errores de verdad es peor que la traza que estamos escondiendo.
    """
    def manejar(_bucle, ctx):
        e = ctx.get("exception")
        traza = str(ctx.get("source_traceback", "")) + str(ctx.get("message", ""))
        if isinstance(e, AssertionError) and "_loop_writing" in (
                traza + str(ctx.get("handle", ""))):
            return
        _bucle.default_exception_handler(ctx)

    bucle.set_exception_handler(manejar)


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
        "description": (
            "Los recordatorios: medicamentos, citas, visitas y fechas "
            "importantes. Usala siempre que te pregunten que hay hoy, que "
            "tiene que hacer, o si tiene algo pendiente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cuando": {
                    "type": "string", "enum": ["hoy", "todo"],
                    "description": "hoy (lo normal) o todo para la lista entera",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "poner_recordatorio",
        "description": (
            "Anota un recordatorio nuevo. Usala cuando te pidan que le "
            "recuerdes algo, o cuando te cuenten una cita, una visita o una "
            "fecha importante."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "que": {
                    "type": "string",
                    "description": "Que hay que recordar, en pocas palabras",
                },
                "cuando": {
                    "type": "string",
                    "description": (
                        "Exactamente una de estas tres formas:\n"
                        "  'diario HH:MM' para todos los dias (una pastilla)\n"
                        "  'anual MM-DD' para todos los anos (un cumpleanos)\n"
                        "  'YYYY-MM-DDTHH:MM' para una sola vez (una cita)\n"
                        "Calcula la fecha a partir del dia de hoy, que sabes."
                    ),
                },
                "tipo": {
                    "type": "string",
                    "enum": ["medicacion", "cita", "visita", "fecha", "otro"],
                },
            },
            "required": ["que", "cuando"],
        },
    },
    {
        "type": "function",
        "name": "quitar_recordatorio",
        "description": (
            "Borra un recordatorio. Usala cuando te pidan que ya no le "
            "recuerdes algo. Si hay varios parecidos te los devuelve para que "
            "preguntes cual, en vez de borrar el que no era."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "que": {
                    "type": "string",
                    "description": "Palabras del recordatorio. Ej: pastilla azul",
                },
            },
            "required": ["que"],
        },
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
        "name": "mover_oreja",
        "description": (
            "Mueve la oreja del perrito. Usala cuando saludes, cuando te "
            "alegres de algo, o cuando quieras llamar su atencion antes de "
            "decir algo importante. Con moderacion: si se mueve todo el rato, "
            "deja de significar nada."
        ),
        "parameters": {
            "type": "object",
            "properties": {"gesto": {"type": "string",
                                     "enum": ["saludo", "atencion", "duda"]}},
            "required": ["gesto"],
        },
    },
    {
        "type": "function",
        "name": "terminar_presentacion",
        "description": ("Usala solo la primera vez, cuando ya sepas el nombre "
                        "de la persona y el de alguien cercano."),
        "parameters": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "como se llama"},
                "trato": {"type": "string", "enum": ["tu", "usted"]},
            },
            "required": ["nombre"],
        },
    },
    {
        "type": "function",
        "name": "mensajes_de_voz",
        "description": (
            "Mira si alguien de la familia dejo un mensaje de voz sin escuchar. "
            "Usala cuando pregunten por alguien, cuando pregunten si alguien "
            "llamo, o al empezar el dia."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "reproducir_mensaje",
        "description": (
            "Reproduce un mensaje de voz de la familia con la voz de quien lo "
            "dejo. Antes de usarla, avisa en una frase corta de quien es. "
            "Despues de reproducirlo NO lo repitas de memoria: ya lo oyo."
        ),
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "integer",
                                  "description": "el id que devolvio mensajes_de_voz"}},
            "required": ["id"],
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


class TransporteNulo:
    """Un aparato que no esta. Deja usar el agente solo desde el panel.

    Sirve para probar sin hardware, y sobre todo para que el sistema no sea
    inutil si el aparato se desconecta: la persona puede seguir hablandole
    desde el navegador.
    """

    descartados = 0

    def enviar(self, *_):        pass
    def enviar_control(self, *_): pass
    def enviar_audio(self, *_):   pass
    def leer(self):               return []
    def cerrar(self):             pass
    def __enter__(self):          return self
    def __exit__(self, *_):       pass


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
        self.oyentes_audio: list = []
        self.solo_cara = False
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
    def avisar_audio(self, pcm: bytes) -> None:
        """Le manda el audio de Dante al navegador, ademas de al aparato.

        Con esto el panel es una salida de voz completa: si el parlante del
        aparato no sirve, la conversacion sigue por el computador y el aparato
        se queda de cara. El demo no depende del audio del hardware.
        """
        for f in list(self.oyentes_audio):
            try:
                f(pcm)
            except Exception:
                pass

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
        """Audio que entra desde el navegador. Mismo camino que el del aparato."""
        if self.hablando_usuario and pcm:
            self.enviados += 1
            await self._ev({"type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm).decode()})

    async def configurar(self) -> None:
        # La tarjeta va al final y no cambia entre turnos: es lo que el cache
        # de prompt puede reusar.
        from .mundo import fecha_larga
        from datetime import datetime
        ahora = datetime.now()
        instrucciones = (ajustes.personalidad(self.db)
                         + f"\n\nHoy es {fecha_larga(ahora)}, "
                           f"{ahora.strftime('%Y-%m-%d')}."
                         + "\n\n--- LO QUE RECUERDAS ---\n"
                         + memoria.tarjeta_de_perfil(self.db))
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
                        "voice": ajustes.leer(self.db)["voz"] or config.VOZ,
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
                    if self.solo_cara:
                        continue          # su microfono no sirve; manda el panel
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
                    elif ev.get("t") == "quien_soy":
                        print(">> QUIEN SOY (pulsacion larga)")
                        self.cara("atencion")
                        self.respondiendo = True
                        self.t0 = time.time()
                        await self._ev({
                            "type": "response.create",
                            "response": {"instructions": ajustes.quien_soy(self.db)},
                        })
                    elif ev.get("t") == "diario":
                        # El boton fisico del diario. Para alguien desorientado,
                        # formular la pregunta es justamente lo dificil.
                        print(">> EL DIARIO (a pedido)")
                        await self.dar_diario()

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

    async def dar_diario(self) -> None:
        """Cuenta como va el dia. Lo dispara la hora o el boton."""
        self.cara("hablando")
        self.respondiendo = True
        self.t0 = time.time()
        await self._ev({
            "type": "response.create",
            "response": {"instructions": diario.instrucciones(self.db)},
        })
        diario.marcar(self.db)

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
            cuando = a.get("cuando") or "hoy"
            e = memoria.agenda_de(self.db, cuando)
            salida = {cuando: e} if e else {
                cuando: [],
                "_nota": "No hay nada anotado. Dilo tal cual: no te lo inventes.",
            }
            print(f"   [memoria] agenda({cuando}) -> {len(e)}")
            if e:
                self.pantalla("Hoy", " · ".join(e), 9)

        elif nombre == "poner_recordatorio":
            id_ = memoria.poner_evento(self.db, a.get("que", ""),
                                       a.get("cuando", ""), a.get("tipo", ""))
            if id_:
                salida = {"anotado": a.get("que"), "cuando": a.get("cuando")}
                print(f"   [agenda] + {a.get('que')} ({a.get('cuando')})")
                self.pantalla("Anotado", a.get("que", ""), 7)
            else:
                salida = {"error": "no entendi cuando. Usa 'diario HH:MM', "
                                   "'anual MM-DD' o 'YYYY-MM-DDTHH:MM'."}

        elif nombre == "quitar_recordatorio":
            hallados = memoria.buscar_eventos(self.db, a.get("que", ""))
            if not hallados:
                salida = {"error": "no encontre ningun recordatorio asi"}
            elif len(hallados) > 1:
                # Borrar el que no era es peor que preguntar una vez mas.
                salida = {"hay_varios": [h["que"] for h in hallados],
                          "_nota": "Preguntale cual antes de borrar."}
            else:
                memoria.quitar_evento(self.db, hallados[0]["id"])
                salida = {"borrado": hallados[0]["que"]}
                print(f"   [agenda] - {hallados[0]['que']}")

        elif nombre == "quien_esta":
            salida = self.ojos.quien_esta()
            # Distinguir a quien acompana del resto. Sin esto, ve una lista de
            # nombres y trata igual a la persona de la casa que a una visita,
            # y son dos cosas muy distintas: a una le cuenta su vida, a la
            # otra le pregunta como se llama.
            if isinstance(salida, dict) and salida.get("camara"):
                p = memoria.principal(self.db)
                suya = p["nombre"] if p else ""
                conocidas = salida.get("conocidas") or []
                salida["a_quien_acompanas"] = suya
                salida["esta_ella"] = bool(suya and suya in conocidas)
                otras = [n for n in conocidas if n != suya]
                if otras:
                    salida["tambien_hay"] = otras
                if salida.get("desconocidas"):
                    salida["sin_reconocer"] = (
                        "Hay alguien que no conoces. Saludalo y preguntale su "
                        "nombre, y despues usa registrar_persona.")
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

        elif nombre == "mover_oreja":
            g = a.get("gesto", "saludo")
            self.t.enviar_control({"t": "gesto", "v": g})
            self.avisar("gesto", v=g)
            salida = {"ok": True}
            print(f"   [oreja] {g}")

        elif nombre == "terminar_presentacion":
            ajustes.guardar(self.db, {"nombre_usuario": a.get("nombre", ""),
                                      "trato": a.get("trato", "tu")})
            memoria.poner_ajuste(self.db, "presentacion_hecha", "si")
            await self.configurar()      # recargar con lo que acaba de aprender
            salida = {"listo": True}
            self.pantalla("Mucho gusto", f"Ya te conozco, {a.get('nombre','')}", 8)
            self.cara("feliz")
            print(f"   [presentacion] terminada: {a.get('nombre','')}")

        elif nombre == "mensajes_de_voz":
            m = memoria.mensajes_pendientes(self.db)
            salida = {"pendientes": [
                {"id": x["id"], "de": x["de"], "segundos": round(x["segundos"] or 0, 1),
                 "dice": x["transcripcion"] or ""} for x in m]}
            print(f"   [mensajes] pendientes: {len(m)}")

        elif nombre == "reproducir_mensaje":
            salida = await self._reproducir_mensaje(int(a.get("id", 0)))

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

    async def _reproducir_mensaje(self, id_: int) -> dict:
        """Mete el mensaje en la misma cola que la voz de Dante.

        Va por el mismo camino que todo lo demas, asi que suena en el aparato y
        en el panel a la vez, y la pantalla lo acompana.
        """
        fila = self.db.execute("SELECT * FROM mensajes WHERE id=?", (id_,)).fetchone()
        if not fila:
            return {"ok": False, "motivo": "no encuentro ese mensaje"}

        # Un recado escrito no tiene audio: lo lee Dante con su voz.
        if not fila["archivo"]:
            memoria.marcar_escuchado(self.db, id_)
            self.pantalla(f"Recado de {fila['de']}", fila["transcripcion"] or "", 12)
            self.avisar("mensaje", de=fila["de"], id=id_)
            print(f"   [mensajes] recado escrito de {fila['de']}")
            return {"ok": True, "de": fila["de"], "escrito": True,
                    "texto": fila["transcripcion"],
                    "nota": "Es un recado escrito: leelo en voz alta tal como "
                            "esta, diciendo primero de quien es."}

        pcm = mensajes.leer_pcm(fila["archivo"])
        if not pcm:
            return {"ok": False, "motivo": "el archivo del mensaje no esta"}

        self.pantalla(f"Mensaje de {fila['de']}",
                      fila["transcripcion"] or "escuchando...", 12)
        self.cara("atencion")
        for i in range(0, len(pcm), TROZO):
            await self.cola.put(pcm[i:i + TROZO])
        await self.cola.put(None)

        memoria.marcar_escuchado(self.db, id_)
        self.avisar("mensaje", de=fila["de"], id=id_)
        print(f"   [mensajes] reproduciendo el de {fila['de']}")
        return {"ok": True, "de": fila["de"],
                "nota": "ya se reprodujo, no lo repitas de memoria"}

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
            self.avisar_audio(trozo)

            proximo += RITMO
            falta = proximo - time.perf_counter()
            if falta > 0:
                await asyncio.sleep(falta)
            else:
                proximo = time.perf_counter()       # nos atrasamos: resincronizar


async def _presentarse(s: "Sesion") -> None:
    """La primera vez, Dante conoce a la persona conversando."""
    await asyncio.sleep(1.2)
    print(">> PRESENTACION (primera vez)")
    s.cara("atencion")
    s.respondiendo = True
    s.t0 = time.time()
    await s._ev({"type": "response.create",
                 "response": {"instructions": ajustes.ONBOARDING}})


async def _dar_recados(s: "Sesion") -> None:
    """Si la familia dejo algo, Dante lo dice al empezar.

    Un recado que hay que ir a buscar no es un recado. Quien lo dejo confia
    en que llegue, y quien lo recibe no sabe que existe para preguntarlo.
    """
    await asyncio.sleep(1.4)
    pend = memoria.mensajes_pendientes(s.db)
    if not pend:
        return
    quienes = []
    for m in pend:
        if m["de"] not in quienes:
            quienes.append(m["de"])
    print(f">> RECADOS de {', '.join(quienes)}")
    s.cara("feliz")
    s.respondiendo = True
    s.t0 = time.time()
    await s._ev({"type": "response.create", "response": {"instructions":
        "Saluda corto y dile enseguida que le dejaron un recado, de quien es, "
        "y usa reproducir_mensaje para dárselo. Sin preguntar si quiere oírlo "
        "primero: se lo das, y después ya vera que hace.\n\n"
        f"Hay {len(pend)} recado(s), de: {', '.join(quienes)}."}})


async def _vigilar_recordatorios(s: "Sesion") -> None:
    """Dante avisa solo cuando llega la hora. Nadie aprieta ningun boton.

    Es la razon de ser de los recordatorios: la persona que los necesita es
    justamente la que no se va a acordar de preguntar por ellos. Un
    recordatorio que hay que ir a buscar no es un recordatorio.

    Espera a que haya silencio. Interrumpir a alguien a mitad de una frase
    para hablarle de una pastilla es peor que avisarle un minuto mas tarde.
    """
    await asyncio.sleep(20)
    while True:
        try:
            if not s.respondiendo and not getattr(s, "hablando_usuario", False):
                pendientes = memoria.recordatorios_vencidos(s.db)
                if pendientes:
                    e = pendientes[0]
                    print(f"\n>> RECORDATORIO: {e['que']}")
                    memoria.marcar_avisado(s.db, e["id"])
                    s.cara("atencion")
                    s.respondiendo = True
                    s.t0 = time.time()
                    await s._ev({"type": "response.create", "response": {
                        "instructions":
                            "Es la hora de un recordatorio y se lo dices tu, "
                            "sin que nadie te lo pida. Dilo con naturalidad, "
                            "en una o dos frases, como quien se acuerda en voz "
                            "alta. No pidas permiso para hablar ni preguntes "
                            "si te puede escuchar: simplemente dilo.\n\n"
                            "NO busques nada en tu memoria: el recordatorio te "
                            "lo estoy dando entero aqui abajo, y es cierto. "
                            "Buscarlo y no encontrarlo te haria empezar "
                            "diciendo que no lo tienes anotado, que es "
                            "justo lo contrario de lo que pasa.\n\n"
                            f"Lo que toca ahora: {e['que']}"}})
        except Exception as err:
            print(f"  aviso: no pude dar un recordatorio ({err})")
        await asyncio.sleep(30)


async def _dar_diario(s: "Sesion") -> None:
    """Dante arranca hablando el. Nadie le pregunto nada."""
    await asyncio.sleep(1.2)
    print(">> EL DIARIO")
    await s.dar_diario()


async def _simular(s: "Sesion", segundos: float) -> None:
    """Finge que alguien apreta el boton, para poder probar sin tener la placa
    delante. Abre el microfono, espera, y cierra el turno."""
    await asyncio.sleep(2.0)
    print(f"  [simulado] boton abajo por {segundos:.0f} s")
    await s._boton(True)
    await asyncio.sleep(segundos)
    await s._boton(False)


async def _correr(simular: float = 0.0, limite: float = 0.0,
                  con_diario: bool | None = None, con_panel: int = 0,
                  solo_cara: bool = False) -> int:
    if not config.API_KEY:
        print("Falta OPENAI_API_KEY en .env. Corre 'dante doctor'.")
        return 1

    _callar_ruido_de_windows(asyncio.get_running_loop())

    puerto = _puerto()
    donde = puerto or "sin aparato"
    print(f"\n=== dante hablar ===  ({donde}, {config.MODELO_VOZ})\n")

    # Modo "solo cara": el aparato conserva pantalla y boton, pero su audio no
    # se usa. Sirve cuando el modulo de audio esta averiado: la conversacion va
    # por el navegador y el demo fisico se salva igual.
    # Cable y WiFi a la vez. El agente no se entera de por cual entro el audio:
    # se puede desenchufar el cable a mitad de una conversacion y seguir por
    # red, o al reves, sin reiniciar nada.
    cable = None
    if puerto:
        try:
            cable = TransporteSerie(puerto)
            print(f"  cable: {puerto}")
        except Exception as e:
            corto = str(e).split(":")[-1].strip()[:60]
            print(f"  cable: {puerto} no responde ({corto})")
    else:
        print("  cable: sin aparato conectado")

    red = TransporteWebSocket(config.PUERTO_WS, config.ficha_aparato())
    try:
        await red.escuchar()
        print(f"  wifi: escuchando en el puerto {red.puerto}"
              + ("" if red.ficha else "  [ojo] SIN ficha: abierto a la red local"))
    except Exception as e:
        print(f"  wifi: no pude escuchar ({type(e).__name__})")
        red = None

    if cable is None and red is None:
        if not con_panel:
            print("No encontre el aparato. Conectalo por USB, o usa --panel "
                  "para hablarle desde el navegador.")
            return 1
        print("  sin aparato: se puede hablar desde el panel")
        t = TransporteNulo()
    else:
        t = TransporteDoble(cable, red)
    print()

    if solo_cara and not isinstance(t, TransporteNulo):
        print("  modo solo cara: el aparato pone la cara, el audio va por el panel\n")

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
            s.solo_cara = solo_cara
            if s.ojos.arrancar():
                n = len(s.ojos.rostros.conocidas)
                print(f"  camara: activa, {n} cara(s) registrada(s)\n")
            else:
                print(f"  camara: {s.ojos.motivo}\n")
            if con_panel:
                from . import auth as _auth
                for a in _auth.avisos():
                    print(f"  [seguridad] {a}")
                try:
                    url = panel.arrancar(s, con_panel)
                    print(f"  panel: {url}\n")
                except Exception as e:
                    print(f"  panel: no arranco ({type(e).__name__}: {e})\n")

            await s.configurar()
            t.enviar_control({"t": "hola?"})
            t.enviar_control({"t": "emocion", "v": "idle"})

            hay_aparato = not isinstance(t, TransporteNulo) and cable is not None
            if hay_aparato:
                print("Manten apretado el boton BOOT del aparato, habla, y sueltalo.")
            if con_panel:
                print("En el panel: manten la barra espaciadora para hablar, "
                      "o escribile.")
            if not hay_aparato and not con_panel:
                print("Sin aparato y sin panel no hay por donde hablarle. "
                      "Usa --panel.")
            print("Ctrl-C para salir.\n")

            tareas = [
                asyncio.create_task(s.leer_aparato()),
                asyncio.create_task(s.leer_modelo()),
                asyncio.create_task(s.reproducir()),
            ]
            aparte = []
            if ajustes.falta_presentarse(db):
                # Todavia no conoce a nadie: primero preguntar, no saludar.
                aparte.append(asyncio.create_task(_presentarse(s)))
            elif con_diario if con_diario is not None else diario.toca_hoy(db):
                aparte.append(asyncio.create_task(_dar_diario(s)))
            elif memoria.mensajes_pendientes(db):
                # Ni presentacion ni diario: si hay recados, se abren con eso.
                aparte.append(asyncio.create_task(_dar_recados(s)))
            aparte.append(asyncio.create_task(_vigilar_recordatorios(s)))
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
           con_diario: bool | None = None, con_panel: int = 0,
           solo_cara: bool = False) -> int:
    _reloj_fino()
    try:
        return asyncio.run(_correr(simular, limite, con_diario, con_panel, solo_cara))
    except KeyboardInterrupt:
        print("\nhasta luego")
        return 0
