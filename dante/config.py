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
PUERTO_WS = int(_v("DANTE_PUERTO_WS", "8765"))

CAMARA = _v("DANTE_CAMARA")
EXA_API_KEY = _v("EXA_API_KEY")
OPENROUTER_API_KEY = _v("OPENROUTER_API_KEY")

DB = RAIZ / _v("DANTE_DB", "data/dante.db")

# El unico formato de audio del proyecto, de punta a punta.
SAMPLE_RATE = 24000
CANALES = 1
ANCHO_MUESTRA = 2  # bytes, PCM16
