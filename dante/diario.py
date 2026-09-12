"""El Diario: lo primero que Dante dice cuando arranca el dia.

No lo pide el usuario. Dante despierta, saluda por su nombre y cuenta que dia
es, que paso ayer, quien viene y que pastilla toca. Es la escena del demo, y
la razon por la que la memoria vale la pena.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import memoria, mundo


def toca_hoy(c: sqlite3.Connection) -> bool:
    """True si todavia no hubo diario hoy. Se cuenta una vez por dia."""
    return memoria.ajuste(c, "ultimo_diario") != date.today().isoformat()


def marcar(c: sqlite3.Connection) -> None:
    memoria.poner_ajuste(c, "ultimo_diario", date.today().isoformat())


def contexto(c: sqlite3.Connection) -> str:
    """Junta lo que Dante tiene que contar. Solo hechos de la base, nada mas."""
    hoy = datetime.now()
    partes = [f"Hoy es {mundo.fecha_larga(hoy)} y son las {hoy.strftime('%H:%M')}."]

    nombre = memoria.ajuste(c, "nombre_usuario")
    if nombre:
        partes.append(f"La persona se llama {nombre}.")

    # Ayer: la ultima conversacion, si la hubo
    ayer = (date.today() - timedelta(days=1)).isoformat()
    ep = c.execute(
        "SELECT resumen, transcripcion, inicio FROM episodios "
        "WHERE date(inicio) = ? AND transcripcion IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", (ayer,)).fetchone()
    if ep:
        texto = (ep["resumen"] or ep["transcripcion"] or "")[:700]
        if texto.strip():
            partes.append(f"Ayer conversaron de esto:\n{texto}")
    else:
        partes.append("Ayer no conversaron.")

    # Hechos anotados en los ultimos tres dias
    desde = (date.today() - timedelta(days=3)).isoformat()
    nuevos = c.execute(
        "SELECT texto, fecha FROM hechos WHERE fecha >= ? ORDER BY fecha DESC LIMIT 6",
        (desde,)).fetchall()
    if nuevos:
        partes.append("Anotado en los ultimos dias:\n" +
                      "\n".join(f"- {h['texto']} ({h['fecha']})" for h in nuevos))

    agenda = memoria.agenda_de(c, "hoy")
    partes.append("Hoy:\n" + ("\n".join(f"- {e}" for e in agenda)
                              if agenda else "- nada anotado"))

    visitas = c.execute(
        "SELECT nombre, relacion, ultima_visita FROM personas "
        "WHERE ultima_visita IS NOT NULL ORDER BY ultima_visita DESC LIMIT 3"
    ).fetchall()
    if visitas:
        partes.append("Ultimas visitas:\n" + "\n".join(
            f"- {v['nombre']} ({v['relacion']}) el {v['ultima_visita']}" for v in visitas))

    return "\n\n".join(partes)


def instrucciones(c: sqlite3.Connection) -> str:
    return (
        "Estas empezando el dia con la persona. Saludala por su nombre y dale "
        "el resumen del dia, hablando, de corrido, sin listas ni numeracion.\n\n"
        "Reglas:\n"
        "- Maximo cinco frases. Es un saludo, no un informe.\n"
        "- Di que dia es hoy.\n"
        "- Menciona lo que pasó ayer SOLO si esta abajo. Si no hubo, no lo inventes.\n"
        "- Di que hay hoy y que medicamento toca, si lo hay.\n"
        "- Termina con una pregunta corta y calida.\n"
        "- NO inventes nada que no este en la informacion de abajo.\n\n"
        "--- LO QUE SABES ---\n" + contexto(c)
    )
