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


# Motivos de cierre que sabemos explicar en cristiano.
EXPLICACIONES = {
    "billing_not_active": (
        "la cuenta no tiene facturacion activa",
        "Carga credito en https://platform.openai.com/settings/organization/billing\n"
        "        La API se paga aparte de ChatGPT Plus. Con 5 USD sobra para el hackaton.",
    ),
    "insufficient_quota": (
        "se acabo el credito o el tope de gasto",
        "Revisa https://platform.openai.com/settings/organization/limits",
    ),
    "invalid_api_key": (
        "la llave no es valida",
        "Genera otra en https://platform.openai.com/api-keys y pegala en .env",
    ),
    "model_not_found": (
        "ese modelo no existe para tu cuenta",
        "Probamos con otro automaticamente.",
    ),
}


def _explicar(texto: str) -> tuple[str, str] | None:
    for clave, par in EXPLICACIONES.items():
        if clave in texto:
            return par
    return None


async def _probar_modelo(modelo: str, key: str) -> tuple[bool, str]:
    """Conecta de verdad: espera el primer evento del servidor.

    El handshake solo no prueba nada — la API acepta el WebSocket y recien
    despues rechaza por facturacion o por modelo inexistente.
    """
    try:
        ws = await _abrir(modelo, key)
    except Exception as e:
        motivo = f"{type(e).__name__}: {str(e)[:60]}"
        print(f"  [no]  {modelo:20s} {motivo}")
        return False, motivo

    try:
        crudo = await asyncio.wait_for(ws.recv(), timeout=15)
        ev = json.loads(crudo)
        _apuntar("<-", ev)
        if ev.get("type") == "error":
            motivo = str(ev.get("error", {}).get("message", "error"))[:70]
            print(f"  [no]  {modelo:20s} {motivo}")
            return False, motivo
        print(f"  [SI]  {modelo:20s} sesion abierta ({ev.get('type')})")
        return True, ""
    except asyncio.TimeoutError:
        print(f"  [no]  {modelo:20s} no contesto en 15 s")
        return False, "sin respuesta"
    except Exception as e:
        motivo = str(e)[:90]
        print(f"  [no]  {modelo:20s} {motivo}")
        return False, motivo
    finally:
        await ws.close()


async def _conversar(modelo: str, key: str, con_audio: bool) -> int:
    try:
        return await _conversar_inner(modelo, key, con_audio)
    except websockets.exceptions.ConnectionClosed as e:
        texto = str(e)
        print(f"\n  [MAL] El servidor cerro la conexion.")
        par = _explicar(texto)
        if par:
            causa, arreglo = par
            print(f"        Causa: {causa}.")
            print(f"        Que hacer: {arreglo}")
        else:
            print(f"        {texto[:160]}")
        return 1


async def _conversar_inner(modelo: str, key: str, con_audio: bool) -> int:
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
                    "input": {
                        "format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE},
                        # Turnos manuales: el boton decide cuando empieza y termina
                        # de hablar. Va anidado aqui, no al nivel de la sesion.
                        "turn_detection": None,
                    },
                    "output": {"format": {"type": "audio/pcm", "rate": config.SAMPLE_RATE},
                               "voice": config.VOZ},
                },
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
    disponibles: list[str] = []
    motivos: list[str] = []
    for m in candidatos:
        sirve, motivo = await _probar_modelo(m, config.API_KEY)
        if sirve:
            disponibles.append(m)
        else:
            motivos.append(motivo)

    if not disponibles:
        print("\n  [MAL] Ningun modelo de voz quedo utilizable.")
        par = _explicar(" ".join(motivos))
        if par:
            causa, arreglo = par
            print(f"\n  Causa: {causa}.")
            print(f"  Que hacer: {arreglo}")
        else:
            print("        Puede ser la llave, la facturacion, o que los IDs cambiaron.")
        print(f"\n  Registro completo en {LOG}")
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
