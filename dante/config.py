"""Configuracion: lee .env y expone valores con defaults sensatos."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _v(clave: str, defecto: str = "") -> str:
    return (os.getenv(clave) or defecto).strip()


API_KEY = _v("OPENAI_API_KEY")

MODELO_VOZ = _v("DANTE_MODELO_VOZ", "gpt-realtime-2")
MODELO_TEXTO = _v("DANTE_MODELO_TEXTO", "gpt-5.6-terra")
MODELO_EMBEDDINGS = _v("DANTE_MODELO_EMBEDDINGS", "text-embedding-3-small")
VOZ = _v("DANTE_VOZ", "marin")

TRANSPORTE = _v("DANTE_TRANSPORTE", "auto")
PUERTO_SERIE = _v("DANTE_PUERTO_SERIE")
PUERTO_WS = int(_v("DANTE_PUERTO_WS", "8770"))

CAMARA = _v("DANTE_CAMARA")
EXA_API_KEY = _v("EXA_API_KEY")
OPENROUTER_API_KEY = _v("OPENROUTER_API_KEY")

DB = RAIZ / _v("DANTE_DB", "data/dante.db")

def ficha_aparato() -> str:
    """Contrasena compartida con el aparato, para el transporte por WiFi.

    Se genera sola la primera vez y se guarda al lado de la memoria. Sin esto
    el puerto de WiFi queda abierto a toda la red local.
    """
    puesta = _v("DANTE_FICHA")
    if puesta:
        return puesta
    archivo = DB.parent / ".ficha"
    try:
        if archivo.exists():
            return archivo.read_text(encoding="utf-8").strip()
        import secrets
        nueva = secrets.token_urlsafe(18)
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(nueva, encoding="utf-8")
        return nueva
    except Exception:
        return ""


# El unico formato de audio del proyecto, de punta a punta.
SAMPLE_RATE = 24000
CANALES = 1
ANCHO_MUESTRA = 2  # bytes, PCM16
