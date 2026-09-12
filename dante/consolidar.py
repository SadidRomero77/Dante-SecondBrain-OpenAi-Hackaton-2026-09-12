"""Consolidacion: convertir una conversacion en hechos que valga la pena guardar.

Corre al cerrar la sesion, no durante. Escribir es caro y se hace por lotes;
leer pasa en cada turno y tiene que costar casi nada.

Lo que aqui se guarda es lo unico que Dante va a poder afirmar despues, asi que
el extractor es deliberadamente exigente: prefiere no guardar antes que guardar
algo que la persona no dijo.
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np

from . import config, memoria, proveedor

INSTRUCCION = """\
Hoy es %%HOY%% (%%DIA%%).

Vas a leer la transcripcion de una conversacion entre Dante (un asistente) y \
una persona mayor en su casa. Extrae los hechos sobre la vida de ESA PERSONA \
que valga la pena recordar en futuras conversaciones.

Reglas estrictas:
- Solo lo que la persona dijo o confirmo. Nada de lo que dijo Dante por su cuenta.
- Cada hecho en UNA frase corta, en tercera persona, que se entienda sola dentro \
de un ano. CONVIERTE las referencias relativas a fechas concretas usando la \
fecha de hoy: "ayer" -> la fecha de ayer, "el sabado" -> el sabado que viene \
con su fecha. No omitas un hecho por ser relativo; conviertelo.
- Nada de trivialidades de la conversacion ("saludo", "dijo que estaba bien").
- Si la conversacion no tiene nada que valga la pena, devuelve una lista vacia. \
Es un resultado correcto y frecuente.
- confianza: 0.9 si la persona lo afirmo claramente, 0.7 si se deduce, 0.5 si es dudoso.

Ademas, si aparecen citas, visitas o medicamentos con fecha y hora, sacalos \
como eventos para la agenda. Solo los que tengan un momento concreto.

Devuelve JSON:
{"hechos": [{"texto": "...", "sujeto": "...", "confianza": 0.9}],
 "eventos": [{"que": "...", "cuando": "AAAA-MM-DD HH:MM", "tipo": "cita|visita|medicacion"}],
 "resumen": "una o dos frases sobre de que hablaron"}
"""

# Dos hechos con un parecido por encima de esto son el mismo dicho de otra forma.
DUPLICADO = 0.92


def _ya_existe(c: sqlite3.Connection, texto: str, vector: bytes | None) -> bool:
    if not vector:
        return bool(c.execute("SELECT 1 FROM hechos WHERE lower(texto)=lower(?)",
                              (texto,)).fetchone())
    v = np.frombuffer(vector, dtype="float32")
    for f in c.execute("SELECT vector FROM hechos WHERE vector IS NOT NULL"):
        w = np.frombuffer(f["vector"], dtype="float32")
        n = float(np.linalg.norm(v) * np.linalg.norm(w))
        if n and float(v @ w / n) >= DUPLICADO:
            return True
    return False


def de_transcripcion(c: sqlite3.Connection, transcripcion: str,
                     episodio: int = 0, hablado: bool = True) -> dict:
    """Extrae hechos de una conversacion y los guarda sin duplicar."""
    if not transcripcion.strip() or len(transcripcion) < 60:
        return {"hechos": 0, "resumen": "", "motivo": "conversacion muy corta"}

    try:
        cli = proveedor.texto()
        from datetime import date as _d
        from .mundo import DIAS
        hoy = _d.today()
        # Sustitucion simple y no .format(): el texto trae llaves del ejemplo
        # JSON y format se atraganta con ellas.
        sistema = (INSTRUCCION.replace("%%HOY%%", hoy.isoformat())
                              .replace("%%DIA%%", DIAS[hoy.weekday()]))
        r = cli.chat.completions.create(
            model=proveedor.modelo_texto(),
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": sistema},
                      {"role": "user", "content": transcripcion[:12000]}],
        )
        datos = json.loads(r.choices[0].message.content or "{}")
    except Exception as e:
        return {"hechos": 0, "resumen": "", "motivo": f"fallo el extractor: {type(e).__name__}"}

    resumen = (datos.get("resumen") or "").strip()
    if episodio and resumen:
        c.execute("UPDATE episodios SET resumen=? WHERE id=?", (resumen, episodio))
        c.commit()

    guardados, repetidos = 0, 0
    for h in datos.get("hechos", []):
        texto = (h.get("texto") or "").strip()
        if not texto:
            continue
        conf = float(h.get("confianza", 0.7))
        vector = memoria._vector(texto)
        if _ya_existe(c, texto, vector):
            repetidos += 1
            continue
        c.execute(
            "INSERT INTO hechos(texto,sujeto,fuente,confianza,fecha,vector) "
            "VALUES(?,?,?,?,date('now'),?)",
            (texto, (h.get("sujeto") or "").strip(), "conversacion", conf, vector))
        guardados += 1
    # Eventos: la agenda se actualiza sola con lo que se hablo.
    eventos = 0
    for e in datos.get("eventos", []):
        que, cuando = (e.get("que") or "").strip(), (e.get("cuando") or "").strip()
        if not que or not cuando:
            continue
        if c.execute("SELECT 1 FROM eventos WHERE lower(que)=lower(?) AND cuando=?",
                     (que, cuando)).fetchone():
            continue
        c.execute("INSERT INTO eventos(que,cuando,tipo) VALUES(?,?,?)",
                  (que, cuando, (e.get("tipo") or "").strip()))
        eventos += 1
    c.commit()

    return {"hechos": guardados, "repetidos": repetidos,
            "eventos": eventos, "resumen": resumen}
