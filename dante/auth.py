"""Auth0 para el portal. Opcional: si no esta configurado, no estorba.

Que protege y que no, porque la diferencia importa: el login protege el
PORTAL, que es lo que abre la familia y puede quedar expuesto en la red. La
memoria sigue siendo un archivo en el disco del usuario. Autenticar no mueve
ni un dato a la nube; solo decide quien puede abrir la ventana.

Sin AUTH0_DOMAIN el portal queda abierto, que es lo correcto cuando corre en
127.0.0.1 y nadie mas lo ve.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

# Importar config carga el .env. Sin esto, este modulo lee variables
# vacias cuando alguien lo importa antes que a config, y la integracion
# queda apagada sin que nadie entienda por que.
from . import config  # noqa: F401

DOMINIO = (os.getenv("AUTH0_DOMAIN") or "").strip().replace("https://", "").rstrip("/")
CLIENTE = (os.getenv("AUTH0_CLIENT_ID") or "").strip()
SECRETO = (os.getenv("AUTH0_CLIENT_SECRET") or "").strip()
PERMITIDOS = [c.strip().lower() for c in (os.getenv("AUTH0_CORREOS") or "").split(",") if c.strip()]

COOKIE = "dante_sesion"
DURACION = 60 * 60 * 24 * 14          # dos semanas
VIDA_ESTADO = 600                     # 10 min para completar un login


def _secreto_de_firma() -> bytes:
    """La llave con la que se firman las galletitas de sesion.

    Si el usuario no puso DANTE_SECRETO, se genera uno al azar y se guarda en
    disco. Antes habia un valor por defecto en el codigo, y eso significa que
    cualquiera que lea el repositorio podria falsificar una sesion en una
    instalacion que no lo hubiera cambiado.

    No se reusa el secreto de Auth0: si ese se rota, no queremos que ademas se
    invaliden las sesiones, ni que un secreto sirva para dos cosas.
    """
    puesto = (os.getenv("DANTE_SECRETO") or "").strip()
    if puesto:
        return puesto.encode()

    from pathlib import Path
    archivo = Path(__file__).resolve().parent.parent / "data" / ".secreto"
    try:
        if archivo.exists():
            return archivo.read_bytes()
        archivo.parent.mkdir(parents=True, exist_ok=True)
        nuevo = secrets.token_bytes(32)
        archivo.write_bytes(nuevo)
        try:
            os.chmod(archivo, 0o600)
        except Exception:
            pass
        return nuevo
    except Exception:
        # Sin disco donde escribir, uno de memoria: las sesiones no sobreviven
        # a un reinicio, que es molesto pero no inseguro.
        return secrets.token_bytes(32)


_FIRMA = _secreto_de_firma()


def activo() -> bool:
    return bool(DOMINIO and CLIENTE and SECRETO)


# ------------------------------------------------------------- galletita --
def _firmar(datos: dict) -> str:
    cuerpo = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
    mac = hmac.new(_FIRMA, cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{cuerpo}.{mac}"


def _abrir(galleta: str) -> dict | None:
    try:
        cuerpo, mac = galleta.split(".", 1)
        esperado = hmac.new(_FIRMA, cuerpo.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac, esperado):
            return None
        relleno = "=" * (-len(cuerpo) % 4)
        d = json.loads(base64.urlsafe_b64decode(cuerpo + relleno))
        if d.get("exp", 0) < time.time():
            return None
        return d
    except Exception:
        return None


def usuario_de(peticion) -> dict | None:
    if not activo():
        return {"correo": "local", "nombre": "modo local", "local": True}
    g = peticion.cookies.get(COOKIE)
    return _abrir(g) if g else None


# ----------------------------------------------------------------- flujo --
def url_de_login(volver_a: str, estado: str) -> str:
    q = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENTE,
        "redirect_uri": volver_a,
        "scope": "openid profile email",
        "state": estado,
        # Google directo: para el cuidador es un boton menos.
        "connection": "google-oauth2",
    })
    return f"https://{DOMINIO}/authorize?{q}"


def canjear(codigo: str, volver_a: str) -> dict | None:
    """Cambia el codigo por el perfil del usuario."""
    try:
        datos = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "client_id": CLIENTE,
            "client_secret": SECRETO,
            "code": codigo,
            "redirect_uri": volver_a,
        }).encode()
        r = urllib.request.Request(f"https://{DOMINIO}/oauth/token", data=datos,
                                   method="POST")
        r.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(r, timeout=12) as f:
            tok = json.loads(f.read())

        r2 = urllib.request.Request(f"https://{DOMINIO}/userinfo")
        r2.add_header("Authorization", f"Bearer {tok['access_token']}")
        with urllib.request.urlopen(r2, timeout=12) as f:
            perfil = json.loads(f.read())
    except Exception:
        return None

    correo = (perfil.get("email") or "").lower()
    if PERMITIDOS and correo not in PERMITIDOS:
        return {"rechazado": correo}

    return {"correo": correo, "nombre": perfil.get("name") or correo,
            "foto": perfil.get("picture", ""), "exp": time.time() + DURACION}


def galleta_de(usuario: dict) -> str:
    return _firmar(usuario)


def url_de_salida(volver_a: str) -> str:
    q = urllib.parse.urlencode({"client_id": CLIENTE, "returnTo": volver_a})
    return f"https://{DOMINIO}/v2/logout?{q}"


# Estados de login pendientes: valor -> cuando se creo. Se limpian solos para
# que no crezcan sin fin y para cerrar la ventana de reuso.
_estados: dict[str, float] = {}


def nuevo_estado() -> str:
    e = secrets.token_urlsafe(24)
    ahora = time.time()
    for k, t in list(_estados.items()):
        if ahora - t > VIDA_ESTADO:
            del _estados[k]
    _estados[e] = ahora
    return e


def gastar_estado(e: str) -> bool:
    """Valida un estado y lo quema: cada uno sirve una sola vez."""
    t = _estados.pop(e, None)
    return t is not None and (time.time() - t) <= VIDA_ESTADO


def avisos() -> list[str]:
    """Lo que esta mal configurado y conviene decir al arrancar."""
    fuera = []
    from . import config as _c
    expuesto = _c.PANEL_HOST not in ("127.0.0.1", "localhost")
    if not activo():
        if expuesto:
            fuera.append("EL PORTAL ESTA EXPUESTO A LA RED Y SIN LOGIN. "
                         "Cualquiera que alcance este puerto puede oir las "
                         "conversaciones y cambiar la configuracion. "
                         "Configura Auth0 antes de dejarlo asi.")
        else:
            fuera.append("el portal esta abierto, pero solo escucha en esta "
                         "maquina (sin Auth0)")
    elif not PERMITIDOS:
        fuera.append("AUTH0_CORREOS esta vacio: CUALQUIERA con cuenta de "
                     "Google puede entrar")
    return fuera
