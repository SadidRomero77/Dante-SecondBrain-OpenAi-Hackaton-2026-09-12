"""dante smoke — prueba que la Realtime API responde y descubre que modelo existe.

Deja un registro completo de eventos en data/smoke-log.jsonl.
Ese archivo es lo que hay que mandarle al arquitecto cuando algo falle.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import wave
from pathlib import Path

import websockets

from . import config

CANDIDATOS = ["gpt-realtime-2.1", "gpt-realtime-2", "gpt-realtime"]
LOG = config.RAIZ / "data" / "smoke-log.jsonl"


def _apuntar(direccion: str, evento: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    recortado = dict(evento)
    # El audio en base64 ensucia el registro y no aporta nada al diagnostico.
    for campo in ("delta", "audio"):
        if isinstance(recortado.get(campo), str) and len(recortado[campo]) > 80:
            recortado[campo] = f"<{len(recortado[campo])} caracteres de base64>"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "dir": direccion,
                            "ev": recortado}, ensure_ascii=False) + "\n")


async def _abrir(modelo: str, key: str):
    url = f"wss://api.openai.com/v1/realtime?model={modelo}"
    cabeceras = {"Authorization": f"Bearer {key}"}
    try:
        return await websockets.connect(url, additional_headers=cabeceras, max_size=None)
    except TypeError:  # websockets < 13 usaba otro nombre
        return await websockets.connect(url, extra_headers=cabeceras, max_size=None)


async def _enviar(ws, evento: dict) -> None:
    _apuntar("->", evento)
    await ws.send(json.dumps(evento))


async def _probar_modelo(modelo: str, key: str) -> bool:
    try:
        ws = await _abrir(modelo, key)
    except Exception as e:
        print(f"  [no]  {modelo:20s} {type(e).__name__}: {str(e)[:70]}")
        return False
    await ws.close()
    print(f"  [SI]  {modelo:20s} conecta")
    return True


async def _conversar(modelo: str, key: str, con_audio: bool) -> int:
    modalidades = ["audio"] if con_audio else ["text"]
    print(f"\nAbriendo sesion con {modelo}, respuesta en {modalidades[0]}...")

    ws = await _abrir(modelo, key)
    async with ws:
        await _enviar(ws, {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": (
                    "Eres Dante, un perro asistente. Responde en espanol, "
                    "en una sola frase corta y calida."
                ),
                "output_modalities": modalidades,
                "audio": {
                    "input": {"format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE}},
                    "output": {"format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE},
                               "voice": config.VOZ},
                },
                # Turnos manuales: nosotros decidimos cuando empieza y termina de hablar.
                "turn_detection": None,
            },
        })
        await _enviar(ws, {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text",
                             "text": "Hola Dante, presentate en una frase."}],
            },
        })
        await _enviar(ws, {"type": "response.create", "response": {}})

        texto: list[str] = []
        audio = bytearray()
        vistos: set[str] = set()
        inicio = time.time()

        while True:
            try:
                crudo = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("\n  [MAL] Se acabo el tiempo esperando la respuesta.")
                return 1

            ev = json.loads(crudo)
            tipo = ev.get("type", "?")
            _apuntar("<-", ev)
            vistos.add(tipo)

            if tipo == "error":
                err = ev.get("error", {})
                print(f"\n  [MAL] La API devolvio un error:")
                print(f"        {err.get('type')}: {err.get('message')}")
                return 1

            if tipo.endswith(".delta") and isinstance(ev.get("delta"), str):
                if "audio" in tipo:
                    audio.extend(base64.b64decode(ev["delta"]))
                else:
                    texto.append(ev["delta"])
                    print(ev["delta"], end="", flush=True)

            if tipo == "response.done":
                break

        tardanza = time.time() - inicio
        print(f"\n\n  Tardo {tardanza:.1f} s.")
        print(f"  Tipos de evento vistos: {len(vistos)}")

        if audio:
            destino = config.RAIZ / "data" / "dante-dice-hola.wav"
            with wave.open(str(destino), "wb") as w:
                w.setnchannels(config.CANALES)
                w.setsampwidth(config.ANCHO_MUESTRA)
                w.setframerate(config.SAMPLE_RATE)
                w.writeframes(bytes(audio))
            segundos = len(audio) / (config.SAMPLE_RATE * config.ANCHO_MUESTRA)
            print(f"  Audio guardado: {destino}  ({segundos:.1f} s, {len(audio)} bytes)")
            print("  Abrelo y escuchalo. Esa es la voz de Dante.")

        if not texto and not audio:
            print("  [ojo] No llego ni texto ni audio. Revisa el registro.")
            return 1
    return 0


async def _correr(con_audio: bool) -> int:
    if not config.API_KEY:
        print("Falta OPENAI_API_KEY en .env. Corre 'dante doctor' primero.")
        return 1

    if LOG.exists():
        LOG.unlink()

    print("\n=== dante smoke ===\n")
    print("1) Buscando que modelo de voz existe en tu cuenta:")

    candidatos = [config.MODELO_VOZ] + [c for c in CANDIDATOS if c != config.MODELO_VOZ]
    disponibles = [m for m in candidatos if await _probar_modelo(m, config.API_KEY)]

    if not disponibles:
        print("\n  [MAL] Ninguno conecta. Puede ser la llave, la facturacion, "
              "o que los IDs cambiaron.")
        print(f"        Registro completo en {LOG}")
        return 1

    elegido = disponibles[0]
    if elegido != config.MODELO_VOZ:
        print(f"\n  [ojo] {config.MODELO_VOZ} no sirve. Pon DANTE_MODELO_VOZ={elegido} en .env")

    print("\n2) Conversacion de prueba:")
    codigo = await _conversar(elegido, config.API_KEY, con_audio)

    print(f"\n  Registro de eventos: {LOG}")
    if codigo == 0:
        print("\n=== funciona. Siguiente paso: el aparato. ===\n")
    else:
        print("\n=== fallo. Mandale el registro al arquitecto. ===\n")
    return codigo


def correr(con_audio: bool = False) -> int:
    return asyncio.run(_correr(con_audio))
