"""De donde salen los modelos de texto.

La voz va siempre con OpenAI: la Realtime API es suya y no la proxea nadie.
Pero las llamadas de texto —el extractor de memoria, el diario, la busqueda—
pueden ir por OpenRouter, que expone la misma interfaz y deja elegir entre
cientos de modelos cambiando una variable de entorno.

Es el punto donde el usuario decide con que piensa su agente sin tocar codigo.
"""
from __future__ import annotations

from . import config

_cliente_texto = None
_cliente_openai = None


def texto():
    """Cliente para las llamadas de texto. OpenRouter si hay llave."""
    global _cliente_texto
    if _cliente_texto is None:
        from openai import OpenAI

        if config.OPENROUTER_API_KEY:
            _cliente_texto = OpenAI(
                api_key=config.OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": "https://github.com/SadidRomero77/"
                                    "Dante-SecondBrain-OpenAi-Hackaton",
                    "X-Title": "Dante",
                },
            )
        else:
            _cliente_texto = OpenAI(api_key=config.API_KEY)
    return _cliente_texto


def openai():
    """Cliente de OpenAI directo, para lo que solo existe ahi."""
    global _cliente_openai
    if _cliente_openai is None:
        from openai import OpenAI
        _cliente_openai = OpenAI(api_key=config.API_KEY)
    return _cliente_openai


def modelo_texto() -> str:
    """El ID del modelo de texto, con el prefijo que pide OpenRouter."""
    m = config.MODELO_TEXTO
    if config.OPENROUTER_API_KEY and "/" not in m:
        return f"openai/{m}"
    return m


def por_donde() -> str:
    return "openrouter" if config.OPENROUTER_API_KEY else "openai"
