"""Las herramientas que miran hacia afuera: hora, clima y busqueda.

Regla que las separa de la memoria: aqui Dante puede equivocarse y decir "creo
que". Sobre la vida de la persona no. Son dos registros distintos de verdad y
esa frontera se sostiene en el prompt.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

# Ciudades que alguien nombraria hablando, sin tener que saber zonas horarias.
ZONAS = {
    "bogota": "America/Bogota", "colombia": "America/Bogota",
    "medellin": "America/Bogota", "cali": "America/Bogota",
    "barranquilla": "America/Bogota", "cartagena": "America/Bogota",
    "santa marta": "America/Bogota", "bucaramanga": "America/Bogota",
    "madrid": "Europe/Madrid", "espana": "Europe/Madrid",
    "barcelona": "Europe/Madrid", "londres": "Europe/London",
    "paris": "Europe/Paris", "roma": "Europe/Rome", "berlin": "Europe/Berlin",
    "nueva york": "America/New_York", "new york": "America/New_York",
    "miami": "America/New_York", "washington": "America/New_York",
    "los angeles": "America/Los_Angeles", "california": "America/Los_Angeles",
    "chicago": "America/Chicago", "houston": "America/Chicago",
    "mexico": "America/Mexico_City", "ciudad de mexico": "America/Mexico_City",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago", "chile": "America/Santiago",
    "lima": "America/Lima", "peru": "America/Lima",
    "quito": "America/Guayaquil", "ecuador": "America/Guayaquil",
    "caracas": "America/Caracas", "venezuela": "America/Caracas",
    "montevideo": "America/Montevideo", "sao paulo": "America/Sao_Paulo",
    "brasil": "America/Sao_Paulo", "panama": "America/Panama",
    "san jose": "America/Costa_Rica", "la habana": "America/Havana",
    "tokio": "Asia/Tokyo", "japon": "Asia/Tokyo", "pekin": "Asia/Shanghai",
    "china": "Asia/Shanghai", "sidney": "Australia/Sydney",
    "australia": "Australia/Sydney", "moscu": "Europe/Moscow",
    "dubai": "Asia/Dubai", "india": "Asia/Kolkata",
}

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _normalizar(t: str) -> str:
    t = t.strip().lower()
    for a, b in zip("áéíóúü", "aeiouu"):
        t = t.replace(a, b)
    return t


def fecha_larga(d: datetime) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def hora_en(lugar: str = "") -> dict:
    """Hora en una ciudad. Sin API: se resuelve en el PC, es instantaneo."""
    if not lugar:
        ahora = datetime.now()
        return {"lugar": "aqui", "hora": ahora.strftime("%H:%M"),
                "fecha": fecha_larga(ahora)}

    clave = _normalizar(lugar)
    zona = ZONAS.get(clave)
    if not zona:
        for k, v in ZONAS.items():
            if k in clave or clave in k:
                zona, clave = v, k
                break
    if not zona:
        return {"error": f"no se en que zona horaria queda {lugar}",
                "sugerencia": "puedes decir el pais o una ciudad grande"}

    ahora = datetime.now(ZoneInfo(zona))
    aqui = datetime.now()
    dif = round((ahora.utcoffset().total_seconds()
                 - aqui.astimezone().utcoffset().total_seconds()) / 3600)
    return {"lugar": lugar, "hora": ahora.strftime("%H:%M"),
            "fecha": fecha_larga(ahora), "diferencia_horas": dif}


def _pedir(url: str, cabeceras: dict | None = None, cuerpo: dict | None = None,
           segundos: float = 8.0) -> dict:
    datos = json.dumps(cuerpo).encode() if cuerpo else None
    r = urllib.request.Request(url, data=datos, headers=cabeceras or {})
    if datos:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=segundos) as f:
        return json.loads(f.read().decode())


def clima(lugar: str = "Bogota") -> dict:
    """Clima de hoy. Open-Meteo es gratis y no pide llave."""
    try:
        g = _pedir("https://geocoding-api.open-meteo.com/v1/search?"
                   + urllib.parse.urlencode({"name": lugar, "count": 1, "language": "es"}))
        if not g.get("results"):
            return {"error": f"no encontre el lugar {lugar}"}
        p = g["results"][0]

        d = _pedir("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
            "latitude": p["latitude"], "longitude": p["longitude"],
            "current": "temperature_2m,precipitation,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "forecast_days": 1,
        }))
        ahora, dia = d["current"], d["daily"]
        return {
            "lugar": p["name"],
            "temperatura_ahora": f"{ahora['temperature_2m']} grados",
            "maxima": f"{dia['temperature_2m_max'][0]} grados",
            "minima": f"{dia['temperature_2m_min'][0]} grados",
            "probabilidad_lluvia": f"{dia['precipitation_probability_max'][0]} por ciento",
        }
    except Exception as e:
        return {"error": f"no pude consultar el clima: {type(e).__name__}"}


# Como debe sonar una respuesta buscada, dicha en voz alta a una persona mayor.
GUIA_VOZ = (
    "Responde en espanol, en dos o tres frases cortas, para leerlas en voz alta "
    "a una persona mayor. Nada de listas, vinetas, comillas ni simbolos. Si el "
    "dato tiene fecha, dila. Si las fuentes se contradicen o no hay informacion "
    "clara, dilo en vez de elegir una."
)


def _para_voz(texto: str) -> str:
    """Deja el texto listo para decirlo en voz alta.

    Los buscadores devuelven markdown con enlaces incrustados. Si eso llega al
    modelo de voz, lo lee: "parentesis el pais punto com corchete http dos
    puntos barra barra...". Las fuentes se mandan aparte, en su propio campo.
    """
    import re

    t = texto or ""
    t = re.sub(r"\[([^\]]*)\]\((?:https?://)?[^)]*\)", r"\1", t)  # [texto](url) -> texto
    t = re.sub(r"\(?\s*https?://\S+\s*\)?", "", t)                  # urls sueltas
    t = re.sub(r"[*_`#>]+", "", t)                                    # restos de markdown
    t = re.sub(r"\(\s*\)", "", t)                                    # parentesis vacios
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    return t.strip()


def _exa(consulta: str) -> dict:
    """Endpoint /answer de Exa: respuesta ya sintetizada, con citas y fechas.

    Usamos /answer y no /search porque para voz una lista de paginas no sirve:
    habria que resumirla con otra llamada y sumar otro par de segundos de
    silencio. El modelo exa-fast va por la latencia, que es lo que se nota en
    una conversacion hablada.
    """
    r = _pedir(
        "https://api.exa.ai/answer",
        {"x-api-key": config.EXA_API_KEY},
        {"query": consulta, "model": "exa-fast", "stream": False, "text": False,
         "systemPrompt": GUIA_VOZ, "userLocation": "CO"},
        segundos=20.0,
    )
    fuentes = []
    for c in (r.get("citations") or [])[:3]:
        f = {"titulo": c.get("title") or "", "url": c.get("url") or ""}
        if c.get("publishedDate"):
            f["fecha"] = str(c["publishedDate"])[:10]
        fuentes.append(f)

    salida = {"buscador": "exa", "respuesta": _para_voz(r.get("answer") or "")}
    if fuentes:
        salida["fuentes"] = fuentes
    costo = (r.get("costDollars") or {}).get("total")
    if costo is not None:
        salida["_costo_usd"] = costo
    return salida


def _openai_busca(consulta: str) -> dict:
    from openai import OpenAI

    c = OpenAI(api_key=config.API_KEY)
    r = c.responses.create(
        model=config.MODELO_TEXTO,
        tools=[{"type": "web_search"}],
        input=f"{consulta}\n\n{GUIA_VOZ}",
    )
    return {"buscador": "openai", "respuesta": _para_voz(r.output_text)}


def buscar_web(consulta: str) -> dict:
    """Busca en la web. Exa si hay llave; si no, el buscador de OpenAI.

    Solo para cosas de HOY: noticias, resultados, precios. Lo que el modelo ya
    sabe no necesita pasar por aqui — una busqueda mete segundos de silencio en
    una conversacion hablada.
    """
    if config.EXA_API_KEY:
        try:
            return _exa(consulta)
        except Exception as e:
            print(f"   [mundo] Exa fallo ({type(e).__name__}), voy con OpenAI")

    try:
        return _openai_busca(consulta)
    except Exception as e:
        return {"error": f"no pude buscar: {type(e).__name__}"}
