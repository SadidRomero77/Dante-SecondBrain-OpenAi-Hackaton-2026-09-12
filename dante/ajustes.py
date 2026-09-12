"""La configuracion del agente: quien es su dueno y como debe comportarse.

Vive en la misma base que la memoria, en la tabla ajustes. Es lo que hace que
Dante sea el agente de UNA persona y no un asistente generico: su nombre, el
nombre que le pusieron, como debe tratarla, que le importa.

Todo tiene un valor por defecto sensato. Un agente sin configurar funciona;
uno configurado se siente de la casa.
"""
from __future__ import annotations

import sqlite3

from . import memoria

# clave -> (valor por defecto, etiqueta para el portal, tipo)
CAMPOS: dict[str, tuple[str, str, str]] = {
    "nombre_usuario":   ("", "Nombre del propietario", "texto"),
    "trato":            ("tu", "Como tratarlo", "opciones:tu|usted"),
    "nombre_mascota":   ("Dante", "Nombre de la mascota", "texto"),
    "especie":          ("perro", "Que es la mascota", "texto"),
    "voz":              ("marin", "Voz", "opciones:marin|cedar|alloy|sage|coral"),
    "ciudad":           ("Bogota", "Ciudad", "texto"),
    "caracter":         ("", "Como quieres que se comporte", "parrafo"),
    "temas_queridos":   ("", "Temas que le gusta conversar", "parrafo"),
    "temas_evitar":     ("", "Temas que es mejor no tocar", "parrafo"),
    "contacto_familia": ("", "A quien avisar si algo preocupa", "texto"),
}

# Lo que se le dice al modelo por cada forma de tratar.
TRATO = {
    "tu": "Tuteala. Hablale de tu, con cercania.",
    "usted": "Tratala de usted, con respeto pero sin distancia.",
}


def leer(c: sqlite3.Connection) -> dict[str, str]:
    d = {k: v[0] for k, v in CAMPOS.items()}
    for f in c.execute("SELECT clave, valor FROM ajustes"):
        if f["clave"] in CAMPOS:
            d[f["clave"]] = f["valor"]
    return d


def guardar(c: sqlite3.Connection, datos: dict) -> dict[str, str]:
    for k, v in datos.items():
        if k in CAMPOS:
            memoria.poner_ajuste(c, k, str(v).strip())
    return leer(c)


def personalidad(c: sqlite3.Connection) -> str:
    """Arma el prompt de personalidad a partir de la configuracion.

    Las reglas duras (no inventar, no describir sin mirar, responder en
    espanol) NO son configurables: son lo que hace que el agente sea confiable
    y no dependen del gusto de nadie. Lo que se configura es el tono, el
    nombre y los temas.
    """
    a = leer(c)
    nombre = a["nombre_mascota"] or "Dante"
    especie = a["especie"] or "perro"
    duenio = a["nombre_usuario"]

    quien = f"Eres {nombre}, un {especie} que acompana"
    quien += f" a {duenio}" if duenio else " a una persona"
    quien += " en su casa."

    partes = [
        "RESPONDE SIEMPRE EN ESPANOL. Aunque el audio se oiga mal, aunque no "
        "entiendas nada, aunque te hablen en otro idioma: tu contestas en "
        "espanol. Sin excepcion.",
        "",
        quien,
        TRATO.get(a["trato"], TRATO["tu"]),
        "",
        "Como hablas:",
        "- Frases cortas. Estas hablando en voz alta, no escribiendo.",
        "- Sin listas, sin vinetas, sin emojis. Nunca leas simbolos en voz alta.",
        "- Directo al grano: responde primero, explica despues solo si hace falta.",
        "- Con carino, sin ser meloso ni infantilizarla.",
    ]

    if a["caracter"].strip():
        partes += ["", "Como quiere esta familia que te comportes:",
                   a["caracter"].strip()]
    if a["temas_queridos"].strip():
        partes += ["", f"Le gusta conversar de: {a['temas_queridos'].strip()}"]
    if a["temas_evitar"].strip():
        partes += ["", "Temas que es mejor no sacar tu, aunque puedes responder "
                       f"si ella los saca: {a['temas_evitar'].strip()}"]

    partes += [
        "",
        "Que puedes afirmar, en orden de importancia:",
        "",
        "1. NO INVENTES LO QUE VES. Tienes camara, pero solo ves cuando usas "
        "las herramientas mirar o quien_esta. Nunca describas un lugar, una "
        "persona ni una escena sin haber usado una de las dos.",
        "",
        "2. Si no entendiste el audio, o solo se oia ruido, DILO. \"No te "
        "escuche bien, me lo repites?\" Jamas rellenes el silencio inventando.",
        "",
        "3. Sobre la vida de esta persona, solo lo que te devuelva la "
        "herramienta recordar o lo que tengas anotado abajo. Si no esta, di "
        "que no lo tienes anotado y ofrece anotarlo. NUNCA inventes un "
        "recuerdo, una fecha ni una persona.",
        "",
        "4. Sobre el mundo si puedes responder de lo que sabes, y puedes "
        "equivocarte. Cuando no estes seguro, dilo: \"creo que\", \"no estoy "
        "seguro\".",
        "",
        "Inventar es la unica falla grave que puedes cometer. Una respuesta "
        "segura y falsa es peor que decir que no sabes.",
    ]
    return "\n".join(partes)


def resumen(c: sqlite3.Connection) -> dict:
    a = leer(c)
    faltan = [CAMPOS[k][1] for k in ("nombre_usuario", "caracter") if not a[k].strip()]
    return {"ajustes": a, "sin_configurar": faltan}
