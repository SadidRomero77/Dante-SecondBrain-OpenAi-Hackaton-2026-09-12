"""La memoria de Dante. Un archivo SQLite en el disco del usuario.

La regla que gobierna todo este modulo: **cada hecho lleva de donde salio y
cuando**. Dante solo puede afirmar cosas de la vida de la persona si vinieron
de aqui, con su fecha. Un segundo cerebro que inventa recuerdos es peor que
no tener ninguno.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

import numpy as np

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS personas (
    id            INTEGER PRIMARY KEY,
    nombre        TEXT NOT NULL,
    relacion      TEXT,
    notas         TEXT,
    cara          BLOB,          -- vector SFace de 128 numeros, opcional
    ultima_visita TEXT,
    creado        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hechos (
    id         INTEGER PRIMARY KEY,
    texto      TEXT NOT NULL,
    sujeto     TEXT,
    fuente     TEXT NOT NULL,      -- semilla | conversacion | cuidador
    confianza  REAL NOT NULL,      -- 0..1
    fecha      TEXT NOT NULL,      -- cuando se supo
    vector     BLOB
);

CREATE TABLE IF NOT EXISTS episodios (
    id            INTEGER PRIMARY KEY,
    inicio        TEXT NOT NULL,
    fin           TEXT,
    resumen       TEXT,
    transcripcion TEXT
);

CREATE TABLE IF NOT EXISTS eventos (
    id     INTEGER PRIMARY KEY,
    que    TEXT NOT NULL,
    cuando TEXT NOT NULL,          -- ISO, o 'diario HH:MM'
    tipo   TEXT,                   -- medicacion | cita | visita
    hecho  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS senales (
    id        INTEGER PRIMARY KEY,
    tipo      TEXT NOT NULL,       -- dolor | caida | confusion | animo | sueno | apetito
    texto     TEXT NOT NULL,       -- lo que dijo, en sus palabras
    fecha     TEXT NOT NULL,
    episodio  INTEGER,
    avisado   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mensajes (
    id            INTEGER PRIMARY KEY,
    de            TEXT NOT NULL,   -- quien lo dejo
    para          TEXT,            -- vacio = para el propietario
    archivo       TEXT NOT NULL,   -- WAV en data/mensajes/
    transcripcion TEXT,
    segundos      REAL,
    creado        TEXT NOT NULL,
    escuchado     TEXT             -- cuando se reprodujo, o vacio
);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def abrir() -> sqlite3.Connection:
    config.DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB)
    c.row_factory = sqlite3.Row
    c.executescript(ESQUEMA)
    # Bases creadas antes de que existiera el reconocimiento de caras.
    if "cara" not in {f[1] for f in c.execute("PRAGMA table_info(personas)")}:
        c.execute("ALTER TABLE personas ADD COLUMN cara BLOB")
        c.commit()
    # Quien es la persona a la que acompana, entre toda la gente que conoce.
    if "principal" not in {f[1] for f in c.execute("PRAGMA table_info(personas)")}:
        c.execute("ALTER TABLE personas ADD COLUMN principal INTEGER NOT NULL "
                  "DEFAULT 0")
        c.commit()
    # Cuando se aviso por ultima vez de un recordatorio, para no repetirlo.
    if "avisado" not in {f[1] for f in c.execute("PRAGMA table_info(eventos)")}:
        c.execute("ALTER TABLE eventos ADD COLUMN avisado TEXT")
        c.commit()
    return c


# --------------------------------------------------------- quien es quien --
def principal(c: sqlite3.Connection) -> sqlite3.Row | None:
    """La persona a la que Dante acompana.

    Se distingue del resto a proposito: su cara es la que importa reconocer
    al entrar, y sus recuerdos son los que Dante puede contarle a ella misma.
    De los demas guarda quienes son, no su vida.
    """
    return c.execute("SELECT * FROM personas WHERE principal=1 "
                     "ORDER BY id LIMIT 1").fetchone()


def hacer_principal(c: sqlite3.Connection, nombre: str) -> int:
    """Marca a alguien como la persona acompanada. Solo puede haber una."""
    nombre = nombre.strip()
    if not nombre:
        return 0
    c.execute("UPDATE personas SET principal=0")
    f = c.execute("SELECT id FROM personas WHERE nombre=? COLLATE NOCASE",
                  (nombre,)).fetchone()
    if f:
        c.execute("UPDATE personas SET principal=1 WHERE id=?", (f["id"],))
        c.commit()
        return f["id"]
    cur = c.execute(
        "INSERT INTO personas(nombre,relacion,notas,ultima_visita,creado,"
        "principal) VALUES(?,?,?,?,?,1)",
        (nombre, "a quien acompano", "", "", date.today().isoformat()))
    c.commit()
    return int(cur.lastrowid)


# ------------------------------------------------------------ avisar solo --
def recordatorios_vencidos(c: sqlite3.Connection) -> list[sqlite3.Row]:
    """Recordatorios cuya hora ya paso y de los que todavia no se aviso.

    Un recordatorio que nadie da no sirve de nada: la persona que lo necesita
    es justamente la que no se va a acordar de preguntar.
    """
    from datetime import datetime
    ahora = datetime.now()
    hoy = ahora.date().isoformat()
    fuera = []
    for e in c.execute("SELECT * FROM eventos WHERE hecho=0").fetchall():
        cu = (e["cuando"] or "").strip()
        if cu.startswith("diario"):
            hora = cu.split()[-1]
            try:
                h, m = (int(x) for x in hora.split(":"))
            except ValueError:
                continue
            vencio = ahora.hour * 60 + ahora.minute >= h * 60 + m
            # Los diarios se avisan una vez por dia, no una vez y nunca mas.
            if vencio and (e["avisado"] or "")[:10] != hoy:
                fuera.append(e)
        else:
            if e["avisado"]:
                continue
            try:
                cuando = datetime.fromisoformat(cu)
            except ValueError:
                continue
            # Solo el mismo dia: no tiene sentido avisar hoy de algo de la
            # semana pasada que quedo sin marcar.
            if cuando <= ahora and cuando.date() == ahora.date():
                fuera.append(e)
    return fuera


def marcar_avisado(c: sqlite3.Connection, id_: int) -> None:
    from datetime import datetime
    c.execute("UPDATE eventos SET avisado=? WHERE id=?",
              (datetime.now().isoformat(timespec="minutes"), id_))
    c.commit()


def ajuste(c: sqlite3.Connection, clave: str, defecto: str = "") -> str:
    f = c.execute("SELECT valor FROM ajustes WHERE clave=?", (clave,)).fetchone()
    return f["valor"] if f else defecto


def poner_ajuste(c: sqlite3.Connection, clave: str, valor: str) -> None:
    c.execute("INSERT INTO ajustes(clave,valor) VALUES(?,?) "
              "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, valor))
    c.commit()


# ------------------------------------------------------------- embeddings --
def _vector(texto: str) -> bytes | None:
    """Vector del texto, para poder buscar por significado y no por palabra.

    Si falla, devolvemos None: la busqueda cae a coincidencia de texto y la
    memoria sigue funcionando. Nunca se pierde un hecho por un problema de red.
    """
    try:
        from . import proveedor
        r = proveedor.openai().embeddings.create(
            model=config.MODELO_EMBEDDINGS, input=texto)
        return np.asarray(r.data[0].embedding, dtype="float32").tobytes()
    except Exception:
        return None


def _parecido(a: bytes, b: bytes) -> float:
    x = np.frombuffer(a, dtype="float32")
    y = np.frombuffer(b, dtype="float32")
    n = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(x @ y / n) if n else 0.0


# ------------------------------------------------------------------ leer ---
def tarjeta_de_perfil(c: sqlite3.Connection) -> str:
    """Lo que Dante sabe siempre, sin tener que preguntar.

    Va al principio del prompt y no cambia entre turnos, asi el cache lo puede
    reusar. Solo lo esencial: quien es, quienes lo rodean, que hay hoy.
    """
    partes: list[str] = []

    nombre = ajuste(c, "nombre_usuario")
    if nombre:
        partes.append(f"La persona con la que hablas se llama {nombre}.")

    gente = c.execute(
        "SELECT nombre, relacion, ultima_visita FROM personas ORDER BY id"
    ).fetchall()
    if gente:
        filas = []
        for p in gente:
            t = f"- {p['nombre']}"
            if p["relacion"]:
                t += f" ({p['relacion']})"
            if p["ultima_visita"]:
                t += f", ultima visita {p['ultima_visita']}"
            filas.append(t)
        partes.append("Personas que conoces:\n" + "\n".join(filas))

    altos = c.execute(
        "SELECT texto, fecha FROM hechos WHERE confianza >= 0.8 "
        "ORDER BY fecha DESC LIMIT 12"
    ).fetchall()
    if altos:
        partes.append("Lo que sabes de su vida:\n" +
                      "\n".join(f"- {h['texto']} (anotado el {h['fecha']})" for h in altos))

    hoy = agenda_de(c, "hoy")
    if hoy:
        partes.append("Hoy:\n" + "\n".join(f"- {e}" for e in hoy))

    try:
        from .mensajes import pendientes_texto
        m = pendientes_texto(c)
        if m:
            partes.append(m)
    except Exception:
        pass

    if not partes:
        return ("Todavia no tienes ningun recuerdo de esta persona. "
                "No inventes ninguno: preguntale y usa la herramienta anotar.")

    return ("Esto es lo unico que sabes de la vida de esta persona. "
            "Si te preguntan algo que no este aqui ni te devuelva la herramienta "
            "recordar, di que no lo tienes anotado.\n\n" + "\n\n".join(partes))


# Por debajo de esto, el parecido es ruido. Medido con la semilla: una
# pregunta cuya respuesta NO esta en la memoria devuelve 0.23, mientras que
# las que si estan devuelven entre 0.47 y 0.53. Si el corte fuera mas bajo,
# Dante recibiria hechos ajenos a la pregunta y podria armar con ellos una
# respuesta falsa. Preferimos devolver vacio y que diga que no lo tiene.
CORTE = 0.35


def recordar(c: sqlite3.Connection, consulta: str, tope: int = 6) -> list[dict]:
    """Busca hechos por significado; si no hay vectores, por texto."""
    filas = c.execute("SELECT id,texto,fuente,confianza,fecha,vector FROM hechos").fetchall()
    if not filas:
        return []

    v = _vector(consulta)
    puntuados: list[tuple[float, sqlite3.Row]] = []
    if v:
        for f in filas:
            if f["vector"]:
                puntuados.append((_parecido(v, f["vector"]), f))
    if not puntuados:
        palabras = [p for p in consulta.lower().split() if len(p) > 3]
        for f in filas:
            t = f["texto"].lower()
            puntuados.append((sum(1 for p in palabras if p in t) / (len(palabras) or 1), f))

    puntuados.sort(key=lambda x: x[0], reverse=True)
    return [
        {"hecho": f["texto"], "fecha": f["fecha"], "fuente": f["fuente"],
         "confianza": round(f["confianza"], 2), "parecido": round(s, 3)}
        for s, f in puntuados[:tope] if s >= CORTE
    ]


def agenda_de(c: sqlite3.Connection, cuando: str = "hoy") -> list[str]:
    hoy = date.today().isoformat()
    filas = c.execute(
        "SELECT que, cuando, tipo FROM eventos WHERE hecho=0 ORDER BY cuando"
    ).fetchall()
    salida = []
    for e in filas:
        cu = e["cuando"]
        if cu.startswith("diario"):
            salida.append(f"{e['que']} — todos los dias a las {cu.split()[-1]}")
        elif cu.startswith(hoy) or cuando == "todo":
            salida.append(f"{e['que']} — {cu}")
    return salida


# ---------------------------------------------------------------- escribir --
def anotar(c: sqlite3.Connection, texto: str, sujeto: str = "",
           fuente: str = "conversacion", confianza: float = 0.7) -> int:
    """Guarda un hecho con su procedencia. La fecha es la de hoy, siempre."""
    hoy = date.today().isoformat()
    cur = c.execute(
        "INSERT INTO hechos(texto,sujeto,fuente,confianza,fecha,vector) "
        "VALUES(?,?,?,?,?,?)",
        (texto.strip(), sujeto.strip(), fuente, confianza, hoy, _vector(texto)),
    )
    c.commit()
    return cur.lastrowid


def registrar_persona(c: sqlite3.Connection, nombre: str, relacion: str = "",
                      notas: str = "") -> int:
    ya = c.execute("SELECT id FROM personas WHERE lower(nombre)=lower(?)",
                   (nombre.strip(),)).fetchone()
    if ya:
        if relacion:
            c.execute("UPDATE personas SET relacion=? WHERE id=?", (relacion, ya["id"]))
            c.commit()
        return ya["id"]
    cur = c.execute(
        "INSERT INTO personas(nombre,relacion,notas,creado) VALUES(?,?,?,?)",
        (nombre.strip(), relacion.strip(), notas.strip(), datetime.now().isoformat(timespec="seconds")),
    )
    c.commit()
    return cur.lastrowid


def abrir_episodio(c: sqlite3.Connection) -> int:
    cur = c.execute("INSERT INTO episodios(inicio) VALUES(?)",
                    (datetime.now().isoformat(timespec="seconds"),))
    c.commit()
    return cur.lastrowid


def cerrar_episodio(c: sqlite3.Connection, id_: int, transcripcion: str) -> None:
    c.execute("UPDATE episodios SET fin=?, transcripcion=? WHERE id=?",
              (datetime.now().isoformat(timespec="seconds"), transcripcion, id_))
    c.commit()


# ------------------------------------------------------------- senales ----
# Categorias que vale la pena que la familia sepa. Deliberadamente cortas y
# sin nada clinico: describen lo que la persona DIJO, no lo que le pasa.
SENALES = {
    "dolor":     "mencionó dolor o molestia",
    "caida":     "mencionó una caída o un tropiezo",
    "confusion": "se mostró desorientada o no recordó algo cotidiano",
    "animo":     "expresó tristeza, miedo o soledad",
    "sueno":     "mencionó dormir mal",
    "apetito":   "mencionó no tener hambre o no haber comido",
}


def anotar_senal(c: sqlite3.Connection, tipo: str, texto: str,
                 episodio: int = 0) -> int:
    if tipo not in SENALES:
        tipo = "animo"
    cur = c.execute(
        "INSERT INTO senales(tipo,texto,fecha,episodio) VALUES(?,?,date('now'),?)",
        (tipo, texto.strip()[:300], episodio or None))
    c.commit()
    return cur.lastrowid


def senales_recientes(c: sqlite3.Connection, dias: int = 7) -> list[dict]:
    """Agrupa por tipo y cuenta. Lo que le importa a la familia no es un
    comentario suelto, es que algo se repita."""
    from datetime import timedelta
    desde = (date.today() - timedelta(days=dias)).isoformat()
    filas = c.execute(
        "SELECT tipo, count(*) veces, max(fecha) ultima, "
        "       group_concat(texto, ' | ') textos "
        "FROM senales WHERE fecha >= ? GROUP BY tipo ORDER BY veces DESC",
        (desde,)).fetchall()
    salida = []
    for f in filas:
        salida.append({
            "tipo": f["tipo"],
            "que": SENALES.get(f["tipo"], f["tipo"]),
            "veces": f["veces"],
            "ultima": f["ultima"],
            "ejemplos": [t.strip() for t in (f["textos"] or "").split("|")][:3],
        })
    return salida


# ------------------------------------------------------------- mensajes ---
def guardar_mensaje(c: sqlite3.Connection, de: str, archivo: str,
                    segundos: float, transcripcion: str = "",
                    para: str = "") -> int:
    cur = c.execute(
        "INSERT INTO mensajes(de,para,archivo,transcripcion,segundos,creado) "
        "VALUES(?,?,?,?,?,?)",
        (de.strip(), para.strip(), archivo, transcripcion.strip(), segundos,
         datetime.now().isoformat(timespec="seconds")))
    c.commit()
    return cur.lastrowid


def mensajes_pendientes(c: sqlite3.Connection, de: str = "") -> list[dict]:
    q = "SELECT * FROM mensajes WHERE escuchado IS NULL"
    a: tuple = ()
    if de:
        q += " AND lower(de) = lower(?)"
        a = (de.strip(),)
    q += " ORDER BY id"
    return [dict(f) for f in c.execute(q, a)]


def marcar_escuchado(c: sqlite3.Connection, id_: int) -> None:
    c.execute("UPDATE mensajes SET escuchado=? WHERE id=?",
              (datetime.now().isoformat(timespec="seconds"), id_))
    c.commit()


def resumen(c: sqlite3.Connection) -> dict:
    def n(t: str) -> int:
        return c.execute(f"SELECT count(*) k FROM {t}").fetchone()["k"]
    return {"personas": n("personas"), "hechos": n("hechos"),
            "episodios": n("episodios"), "eventos": n("eventos"),
            "senales": n("senales"), "mensajes": n("mensajes"),
            "usuario": ajuste(c, "nombre_usuario", "(sin nombre)")}
