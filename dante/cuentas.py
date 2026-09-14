"""Cuentas propias: correo y contrasena, sin depender de nadie mas.

Existe porque el login con Auth0 quedo apagado: la direccion de vuelta no
estaba dada de alta en su panel y el portal publicado quedaba abierto a
cualquiera. Un login que depende de un tercero se puede romper desde fuera
sin tocar una linea; este no.

Y hace algo que Auth0 solo no hacia: cada cuenta es duena de su memoria. En la
nube la vida de una persona colgaba de una galleta anonima que se borraba a
los ocho minutos. Ahora cuelga de una cuenta, y lo que se guarda se queda.

Lo que protege: quien abre el portal y de quien es la memoria que ve. Las
contrasenas se guardan con scrypt y sal propia, nunca en claro. Los intentos
fallidos se frenan por direccion y por correo, para que no se pueda probar un
diccionario entero contra una cuenta.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config

MIN_CLAVE = 8
# Intentos fallidos que se toleran por ventana, por direccion y por correo.
INTENTOS = 8
VENTANA = 15 * 60

# Coste de scrypt: unos 16 MB y decenas de milisegundos por intento. Barato
# para quien entra una vez, caro para quien prueba millones.
_N, _R, _P = 2 ** 14, 8, 1

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
    id      TEXT PRIMARY KEY,
    correo  TEXT NOT NULL UNIQUE,
    nombre  TEXT NOT NULL DEFAULT '',
    sal     BLOB NOT NULL,
    clave   BLOB NOT NULL,
    creado  TEXT NOT NULL
);
"""


def ruta() -> Path:
    """Al lado de la memoria: en el contenedor es el volumen que sobrevive."""
    return config.DB.parent / "cuentas.db"


def _abrir() -> sqlite3.Connection:
    r = ruta()
    r.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(r)
    c.row_factory = sqlite3.Row
    c.executescript(ESQUEMA)
    return c


def _hash(clave: str, sal: bytes) -> bytes:
    return hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=_N, r=_R, p=_P,
                          maxmem=64 * 1024 * 1024, dklen=32)


def _limpio(correo: str) -> str:
    return (correo or "").strip().lower()


def _correo_valido(correo: str) -> bool:
    if len(correo) > 200 or correo.count("@") != 1:
        return False
    usuario, dominio = correo.split("@")
    return bool(usuario) and "." in dominio and not dominio.startswith(".")


# ------------------------------------------------------------ frenar abuso --
_fallos: dict[str, list[float]] = {}
_candado = threading.Lock()


def _recientes(clave: str) -> list[float]:
    ahora = time.time()
    lista = [t for t in _fallos.get(clave, []) if ahora - t < VENTANA]
    if lista:
        _fallos[clave] = lista
    else:
        _fallos.pop(clave, None)
    return lista


def frenado(ip: str, correo: str) -> bool:
    with _candado:
        return (len(_recientes("ip:" + ip)) >= INTENTOS
                or len(_recientes("correo:" + _limpio(correo))) >= INTENTOS)


def _fallo(ip: str, correo: str) -> None:
    with _candado:
        ahora = time.time()
        _fallos.setdefault("ip:" + ip, []).append(ahora)
        _fallos.setdefault("correo:" + _limpio(correo), []).append(ahora)


# ------------------------------------------------------------------ flujo --
def permitido(correo: str) -> bool:
    """Si hay lista de correos, solo esos pueden tener cuenta."""
    from . import auth
    return not auth.PERMITIDOS or _limpio(correo) in auth.PERMITIDOS


def crear(correo: str, clave: str, nombre: str = "") -> dict:
    correo = _limpio(correo)
    if not _correo_valido(correo):
        return {"ok": False, "motivo": "Ese correo no parece valido."}
    if len(clave or "") < MIN_CLAVE:
        return {"ok": False,
                "motivo": f"La contrasena necesita al menos {MIN_CLAVE} caracteres."}
    if not permitido(correo):
        return {"ok": False, "motivo": "Ese correo no esta autorizado."}
    sal = secrets.token_bytes(16)
    cuenta = {"id": secrets.token_urlsafe(18), "correo": correo,
              "nombre": (nombre or "").strip()[:80] or correo.split("@")[0]}
    c = _abrir()
    try:
        c.execute("INSERT INTO cuentas (id, correo, nombre, sal, clave, creado) "
                  "VALUES (?,?,?,?,?,?)",
                  (cuenta["id"], correo, cuenta["nombre"], sal, _hash(clave, sal),
                   datetime.now().isoformat(timespec="seconds")))
        c.commit()
    except sqlite3.IntegrityError:
        return {"ok": False, "motivo": "Ya hay una cuenta con ese correo. Entra."}
    finally:
        c.close()
    return {"ok": True, "cuenta": cuenta}


# Se compara contra esto cuando el correo no existe, para que la respuesta
# tarde lo mismo: si no, el tiempo delataria que correos tienen cuenta.
_SAL_FALSA = secrets.token_bytes(16)
_HASH_FALSO = _hash(secrets.token_urlsafe(12), _SAL_FALSA)


def entrar(correo: str, clave: str, ip: str = "") -> dict:
    correo = _limpio(correo)
    if frenado(ip, correo):
        return {"ok": False, "motivo":
                "Demasiados intentos. Espera unos minutos y vuelve a probar."}
    c = _abrir()
    try:
        f = c.execute("SELECT id, correo, nombre, sal, clave FROM cuentas "
                      "WHERE correo=?", (correo,)).fetchone()
    finally:
        c.close()
    if f is None:
        hmac.compare_digest(_hash(clave or "", _SAL_FALSA), _HASH_FALSO)
        _fallo(ip, correo)
        return {"ok": False, "motivo": "Correo o contrasena incorrectos."}
    if not hmac.compare_digest(_hash(clave or "", f["sal"]), f["clave"]):
        _fallo(ip, correo)
        return {"ok": False, "motivo": "Correo o contrasena incorrectos."}
    if not permitido(correo):
        return {"ok": False, "motivo": "Ese correo no esta autorizado."}
    return {"ok": True, "cuenta": {"id": f["id"], "correo": f["correo"],
                                   "nombre": f["nombre"]}}


def por_correo(correo: str, nombre: str = "") -> dict:
    """La cuenta de quien entro con Google, creandola si es la primera vez.

    Asi la misma persona tiene la misma memoria entre con contrasena o con
    Google. La clave es aleatoria: esa cuenta no entra por contrasena hasta
    que alguien la ponga.
    """
    correo = _limpio(correo)
    c = _abrir()
    try:
        f = c.execute("SELECT id, correo, nombre FROM cuentas WHERE correo=?",
                      (correo,)).fetchone()
    finally:
        c.close()
    if f is not None:
        return dict(f)
    r = crear(correo, secrets.token_urlsafe(24), nombre)
    return r.get("cuenta") or {}
