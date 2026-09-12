"""Mensajes de voz de la familia.

Ana graba treinta segundos desde el navegador; cuando Rosa pregunta por ella,
Dante se los reproduce con la voz de Ana, no con la suya.

Es lo que convierte al aparato en un puente entre personas y no solo en un
asistente. Y para alguien que se olvida de las caras, oír la voz de su hija
vale mucho más que oír a un modelo contándole que llamó.
"""
from __future__ import annotations

import wave
from datetime import datetime
from pathlib import Path

from . import config, memoria

CARPETA = config.RAIZ / "data" / "mensajes"


def guardar(de: str, pcm: bytes, transcripcion: str = "", para: str = "") -> dict:
    """Guarda un mensaje en WAV y lo deja pendiente de escuchar."""
    if not de.strip():
        return {"ok": False, "motivo": "falta de quien es el mensaje"}
    if len(pcm) < config.SAMPLE_RATE:      # menos de medio segundo
        return {"ok": False, "motivo": "el mensaje es demasiado corto"}

    CARPETA.mkdir(parents=True, exist_ok=True)
    nombre = f"{datetime.now():%Y%m%d-%H%M%S}-{_limpio(de)}.wav"
    destino = CARPETA / nombre
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(config.CANALES)
        w.setsampwidth(config.ANCHO_MUESTRA)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)

    segundos = len(pcm) / (config.SAMPLE_RATE * config.ANCHO_MUESTRA)
    c = memoria.abrir()
    try:
        id_ = memoria.guardar_mensaje(c, de, nombre, segundos, transcripcion, para)
        # La persona a la que le hablan queda registrada, aunque no estuviera.
        memoria.registrar_persona(c, de)
    finally:
        c.close()
    return {"ok": True, "id": id_, "segundos": round(segundos, 1), "archivo": nombre}


def leer_pcm(archivo: str) -> bytes:
    ruta = CARPETA / archivo
    if not ruta.exists():
        return b""
    with wave.open(str(ruta), "rb") as w:
        return w.readframes(w.getnframes())


def transcribir(pcm: bytes) -> str:
    """Transcribe el mensaje para poder buscarlo después y mostrarlo escrito.

    Si falla, no pasa nada: el audio es lo que importa y se guarda igual.
    """
    import io as _io

    try:
        from . import proveedor
        buf = _io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(config.CANALES)
            w.setsampwidth(config.ANCHO_MUESTRA)
            w.setframerate(config.SAMPLE_RATE)
            w.writeframes(pcm)
        buf.seek(0)
        buf.name = "mensaje.wav"
        r = proveedor.openai().audio.transcriptions.create(
            model="gpt-transcribe", file=buf, language="es")
        return (r.text or "").strip()
    except Exception:
        return ""


def pendientes_texto(c) -> str:
    """Una línea para la tarjeta de perfil, si hay mensajes sin oír."""
    m = memoria.mensajes_pendientes(c)
    if not m:
        return ""
    quienes = []
    for x in m:
        if x["de"] not in quienes:
            quienes.append(x["de"])
    lista = ", ".join(quienes)
    return (f"Hay {len(m)} mensaje(s) de voz sin escuchar, de {lista}. "
            f"Menciónalo con naturalidad y ofrece reproducirlo.")


def _limpio(t: str) -> str:
    t = t.strip().lower()
    for a, b in zip("áéíóúñü", "aeiounu"):
        t = t.replace(a, b)
    return "".join(ch if ch.isalnum() else "_" for ch in t).strip("_") or "alguien"
