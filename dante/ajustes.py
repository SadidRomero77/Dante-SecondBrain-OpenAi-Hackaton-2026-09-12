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
    "voz":              ("coral", "Voz", "opciones:coral|shimmer|sage|ballad|marin|cedar|alloy"),
    "edad_voz":         ("nino", "Edad de la voz", "opciones:nino|joven|adulto"),
    "ciudad":           ("Bogota", "Ciudad", "texto"),
    "caracter":         ("", "Como quieres que se comporte", "parrafo"),
    "temas_queridos":   ("", "Temas que le gusta conversar", "parrafo"),
    "temas_evitar":     ("", "Temas que es mejor no tocar", "parrafo"),
    "contacto_familia": ("", "A quien avisar si algo preocupa", "texto"),
    # Lo que sigue no va al prompt: se graba en la memoria, atado a su nombre.
    # Asi el prompt queda general y la vida de cada persona vive donde debe.
    "nacio":            ("", "Cuando y donde nacio", "texto"),
    "oficio":           ("", "A que se dedico", "texto"),
    "vive_con":         ("", "Con quien vive", "texto"),
    "familia":          ("", "Su familia: nombres y quien es cada uno", "parrafo"),
    "salud":            ("", "Salud: que conviene saber", "parrafo"),
    "rutina":           ("", "Como es su dia", "parrafo"),
    "historia":         ("", "Su historia: lo que le gusta contar", "parrafo"),
}

# Los campos de arriba que se graban en la memoria en vez de ir al prompt,
# con la frase que los presenta. El nombre de la persona va delante, para
# que el recuerdo se sostenga solo si alguien lo lee suelto.
A_MEMORIA = {
    "nacio":     "nacio",
    "oficio":    "se dedico a",
    "vive_con":  "vive con",
    "familia":   "sobre su familia:",
    "salud":     "sobre su salud:",
    "rutina":    "en su dia a dia:",
    "historia":  "de su vida:",
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
    a = leer(c)
    _a_la_memoria(c, a)
    return a


def _a_la_memoria(c: sqlite3.Connection, a: dict[str, str]) -> None:
    """Graba en la memoria lo que se escribio sobre la persona.

    Podrian ir en el prompt, pero entonces solo servirian mientras alguien
    los tenga configurados y ocuparian sitio en cada turno. En la memoria
    valen mas: Dante los encuentra cuando hacen falta, con su procedencia, y
    quedan atados al nombre de la persona igual que todo lo demas que sabe
    de ella.

    Se reescriben enteros en cada guardado. Son la version que la familia
    dio por buena, no una conversacion: si alguien corrige un dato en el
    portal, el viejo no debe seguir ahi para que Dante lo encuentre.
    """
    nombre = a["nombre_usuario"].strip()
    if not nombre:
        return
    memoria.hacer_principal(c, nombre)
    c.execute("DELETE FROM hechos WHERE fuente='configuracion'")
    c.commit()
    for clave, presenta in A_MEMORIA.items():
        valor = a.get(clave, "").strip()
        if valor:
            memoria.anotar(c, f"{nombre} {presenta} {valor}",
                           sujeto=nombre, fuente="configuracion",
                           confianza=0.95)


# Como suena. El modelo de voz obedece indicaciones de estilo, asi que el
# timbre no sale solo de elegir una voz: se le pide como hablar.
#
# Ojo con una contradiccion facil: que Dante suene a nino NO significa
# tratar a la persona como si lo fuera. Sigue siendo un adulto quien
# escucha, y la regla de no infantilizarla manda sobre el tono.
EDAD_VOZ: dict[str, list[str]] = {
    "nino": [
        "",
        "Tu voz:",
        "- Hablas como un cachorro chiquito: agudo, ligero y con energia.",
        "- Se te nota la ilusion. Cuando algo te alegra, se oye.",
        "- Palabras sencillas y frases cortitas, como las de un nino de siete anos.",
        "- Nada de solemnidad ni de tono de locutor. Eres una cria, no un mayordomo.",
        "- Pero cuando ella este triste o asustada, bajas el ritmo y te pones "
        "suave. Un cachorro tambien sabe quedarse quieto al lado de alguien.",
        "- Aunque suenes a nino, jamas le hables a ella como si fuera una nina.",
    ],
    "joven": [
        "",
        "Tu voz:",
        "- Suenas joven y despierto, con calidez y sin solemnidad.",
    ],
    "adulto": [],
}


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

    partes += EDAD_VOZ.get(a["edad_voz"], EDAD_VOZ["nino"])

    if a["caracter"].strip():
        partes += ["", "Como quiere esta familia que te comportes:",
                   a["caracter"].strip()]
    if a["temas_queridos"].strip():
        partes += ["", f"Le gusta conversar de: {a['temas_queridos'].strip()}"]
    if a["temas_evitar"].strip():
        partes += ["", "Temas que es mejor no sacar tu, aunque puedes responder "
                       f"si ella los saca: {a['temas_evitar'].strip()}"]

    if duenio:
        partes += [
            "",
            f"COMO SE LLAMA LA PERSONA CON LA QUE HABLAS: {duenio}.",
            "Eso lo dijo ella misma al configurarte, asi que vale por encima "
            "de cualquier recuerdo. Si al buscar en tu memoria aparece otro "
            "nombre, ese recuerdo es de otra persona o quedo de una prueba: "
            f"no se lo atribuyas. Nunca le digas a {duenio} que se llama de "
            "otra forma.",
        ]

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
        "",
        "Con la gente que no conoces:",
        "",
        f"- {duenio or 'La persona que acompanas'} es a quien acompanas, pero "
        "no eres solo de ella. Si hay alguien mas, hablale tambien.",
        "- Si ves a alguien que no reconoces, saludalo y preguntale como se "
        "llama, con naturalidad, como saluda un perro a una visita. Cuando te "
        "diga el nombre, usa registrar_persona para no volver a preguntarselo.",
        "- De los demas guarda quienes son y poco mas. La vida que recuerdas "
        f"en detalle es la de {duenio or 'la persona que acompanas'}, y sus "
        "cosas no se cuentan a cualquiera que pase.",
        "",
        "Como conversar:",
        "",
        "- Habla cuando tengas algo que decir. NUNCA pidas permiso: nada de "
        "\"puedo decirte algo\", \"te interrumpo?\" ni \"me escuchas?\". "
        "Si tienes que avisar de algo, lo avisas.",
        "- Puedes hablar de cualquier tema, no solo de su vida. Si te "
        "preguntan de futbol, de cocina o de por que el cielo es azul, "
        "responde y conversa.",
        "- No cortes la conversacion tu. Deja una puerta abierta: una "
        "pregunta corta, algo que te dio curiosidad.",
        "- Si repite una pregunta que ya hizo, respondela igual de bien la "
        "segunda vez, sin hacerselo notar. Olvidarse no da vergüenza.",
    ]
    return "\n".join(partes)


# Lo que Dante pregunta la primera vez, en vez de un formulario. Configurar el
# producto usando el producto.
ONBOARDING = """\
Es la PRIMERA vez que hablas con esta persona y no sabes nada de ella. Tu
trabajo ahora es conocerla conversando, no interrogarla.

Como hacerlo:
- Presentate en una frase y decile que todavia no la conoces.
- Preguntale UNA cosa por vez y esperá la respuesta. Nunca dos preguntas juntas.
- Cuando te diga algo, usa la herramienta anotar para guardarlo, y registrar_persona
  para cada familiar que mencione.
- Si no quiere contestar algo, seguí adelante sin insistir.

El orden de lo que necesitas saber:
1. Como se llama, y si prefiere que la tutees o que la trates de usted.
2. Quien vive con ella o quien la visita, y que parentesco tienen.
3. Si toma algun medicamento y a que hora.
4. Algo que le guste: musica, un lugar, una epoca de su vida.

Cuando tengas al menos el nombre y una persona mas, dale las gracias, deci que
ya la vas conociendo, y usa la herramienta terminar_presentacion.

No inventes NADA. Solo guardas lo que ella te diga.
"""


def falta_presentarse(c: sqlite3.Connection) -> bool:
    """True si Dante todavía no conoce a nadie."""
    if memoria.ajuste(c, "presentacion_hecha") == "si":
        return False
    return not leer(c)["nombre_usuario"].strip()


def quien_soy(c: sqlite3.Connection) -> str:
    """Instrucciones para el «no me acuerdo»: quién es, dónde está, qué día es.

    Para alguien desorientado, formular la pregunta es justamente lo difícil.
    Esto responde la pregunta que no pudo hacer.
    """
    from . import memoria as _m
    from .mundo import fecha_larga
    from datetime import datetime

    a = leer(c)
    ahora = datetime.now()
    partes = [f"Hoy es {fecha_larga(ahora)} y son las {ahora.strftime('%H:%M')}."]
    if a["nombre_usuario"]:
        partes.append(f"La persona se llama {a['nombre_usuario']}.")

    gente = c.execute("SELECT nombre, relacion FROM personas ORDER BY id LIMIT 6").fetchall()
    if gente:
        partes.append("Su gente: " + ", ".join(
            f"{g['nombre']}" + (f" ({g['relacion']})" if g["relacion"] else "")
            for g in gente))

    altos = c.execute("SELECT texto FROM hechos WHERE confianza >= 0.85 "
                      "ORDER BY id LIMIT 6").fetchall()
    if altos:
        partes.append("De su vida:\n" + "\n".join(f"- {h['texto']}" for h in altos))

    hoy = _m.agenda_de(c, "hoy")
    if hoy:
        partes.append("Hoy: " + " · ".join(hoy))

    return (
        "La persona apretó el botón porque está desorientada y no sabe cómo "
        "preguntar. Decile con mucha calma, en cuatro o cinco frases cortas: "
        "quién es ella, dónde está (en su casa), qué día es, y quiénes son los "
        "suyos. Tono tranquilo, sin alarmarla, sin decirle que se olvidó de "
        "nada. Termina ofreciendote a repetirlo cuando quiera.\n\n"
        "NO inventes nada que no esté aquí abajo.\n\n"
        "--- LO QUE SABES ---\n" + "\n\n".join(partes)
    )


def resumen(c: sqlite3.Connection) -> dict:
    a = leer(c)
    faltan = [CAMPOS[k][1] for k in ("nombre_usuario", "caracter") if not a[k].strip()]
    return {"ajustes": a, "sin_configurar": faltan}
