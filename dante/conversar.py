"""De que hablar hoy.

Un perro que llega con algo que contar es mas compania que uno que espera
preguntas. Para alguien que pasa el dia solo, la diferencia entre "hola, que
necesitas" y "hola, hoy esta fresco y salio algo de lo tuyo" es la diferencia
entre un asistente y alguien que vino a verla.

Junta tres cosas y se las pasa al modelo como semillas, no como guion: que
tiempo hace, algo del mundo relacionado con lo que a ella le gusta, y un
recuerdo suyo para volver sobre el. Dante elige una y arranca por ahi.
"""

from __future__ import annotations

import random

from . import ajustes, memoria, mundo


def semillas(c) -> dict:
    a = ajustes.leer(c)
    fuera: dict = {}

    tiempo = mundo.clima(a["ciudad"] or "Bogota")
    if isinstance(tiempo, dict) and not tiempo.get("error"):
        fuera["el_tiempo"] = tiempo

    # Del mundo, pero de LO SUYO. Las noticias generales no son conversacion:
    # son ruido, y a menudo malas noticias que nadie pidio.
    temas = [t.strip() for t in (a["temas_queridos"] or "").replace("\n", ",")
             .split(",") if t.strip()]
    if temas:
        tema = random.choice(temas)
        r = mundo.buscar_web(f"algo interesante y reciente sobre {tema}")
        if isinstance(r, dict) and r.get("respuesta"):
            fuera["de_lo_suyo"] = {"tema": tema, "encontre": r["respuesta"]}

    # Y algo de ella. Volver sobre lo que ya conto vale mas que cualquier
    # noticia: le demuestra que alguien la escucho.
    suyos = c.execute("SELECT texto FROM hechos WHERE confianza >= 0.6 "
                      "ORDER BY RANDOM() LIMIT 2").fetchall()
    if suyos:
        fuera["algo_que_te_conto"] = [h["texto"] for h in suyos]

    if not fuera:
        fuera["_nota"] = ("No tienes de donde sacar nada todavia. Pregúntale "
                          "algo de ella y escucha; NO te inventes una noticia.")
    else:
        fuera["_nota"] = ("Elige UNA sola y arranca por ahi, en una frase. No "
                          "las cuentes todas ni leas esto como una lista.")
    return fuera
