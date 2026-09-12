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

DOMINIO = (os.getenv("AUTH0_DOMAIN") or "").strip().replace("https://", "").rstrip("/")
CLIENTE = (os.getenv("AUTH0_CLIENT_ID") or "").strip()
SECRETO = (os.getenv("AUTH0_CLIENT_SECRET") or "").strip()
PERMITIDOS = [c.strip().lower() for c in (os.getenv("AUTH0_CORREOS") or "").split(",") if c.strip()]

COOKIE = "dante_sesion"
DURACION = 60 * 60 * 24 * 14          # dos semanas
_FIRMA = (os.getenv("DANTE_SECRETO") or SECRETO or "dante-local").encode()


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


def nuevo_estado() -> str:
    return secrets.token_urlsafe(16)
