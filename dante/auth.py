"""La puerta del portal: quien entra y con que cuenta.

Hay dos formas de entrar y las dos terminan en la misma galleta firmada:
correo y contrasena (cuentas.py, siempre disponible) o Google por Auth0, que
es opcional y solo aparece si esta configurado.

Que protege y que no, porque la diferencia importa: el login protege el
PORTAL, que es lo que abre la familia y puede quedar expuesto en la red, y
decide de quien es la memoria que se ve. En casa la memoria sigue siendo un
archivo en el disco del usuario.

En la propia maquina, sin direccion publica, no se pide cuenta: es lo correcto
cuando corre en 127.0.0.1 y nadie mas lo ve.
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
# Correos que pueden tener cuenta. Vale para las dos formas de entrar; el
# nombre viejo se sigue leyendo para no romper un .env que ya lo tenga.
PERMITIDOS = [c.strip().lower() for c in
              (os.getenv("DANTE_CORREOS") or os.getenv("AUTH0_CORREOS") or "").split(",")
              if c.strip()]

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

    # Al lado de la memoria, no del codigo. En el contenedor el codigo se
    # reconstruye en cada despliegue y el secreto se iba con el: todas las
    # sesiones abiertas quedaban invalidas sin que nadie supiera por que.
    archivo = config.DB.parent / ".secreto"
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
    """Si Auth0 esta configurado. Ya no decide si hay login: solo si hay Google."""
    return bool(DOMINIO and CLIENTE and SECRETO)


def google() -> bool:
    """Si se ofrece entrar con Google.

    DANTE_DEMO_LOGIN=0 lo apaga sin tocar codigo: si la direccion de vuelta no
    esta dada de alta en Auth0, el boton lleva a una pantalla de error. Las
    cuentas propias no dependen de eso y siguen funcionando.
    """
    return activo() and (os.getenv("DANTE_DEMO_LOGIN") or "1").strip().lower() \
        not in ("0", "no", "false")


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


LOCAL = {"id": "", "correo": "local", "nombre": "modo local", "local": True}


def en_casa(peticion) -> bool:
    """Si quien pregunta esta sentado en la misma maquina, sin nada publicado.

    No basta con mirar el nombre de la direccion: ese lo escribe el cliente, y
    cualquiera puede mandar 'Host: localhost' desde internet. Tiene que venir
    ademas de la propia maquina. Con una direccion publica o en la nube nunca
    cuenta como casa, porque un tunel local tambien llega desde 127.0.0.1.
    """
    from . import demo
    if config.PANEL_URL or demo.activo():
        return False
    cliente = getattr(getattr(peticion, "client", None), "host", "") or ""
    return (peticion.url.hostname in ("127.0.0.1", "localhost")
            and cliente in ("127.0.0.1", "::1"))


def usuario_de(peticion) -> dict | None:
    """La cuenta de quien pregunta, o None si no entro."""
    if en_casa(peticion):
        return LOCAL
    g = peticion.cookies.get(COOKIE)
    d = _abrir(g) if g else None
    # Las galletas de antes no llevaban cuenta: sin 'id' no hay memoria a la
    # que apuntar, asi que se vuelve a entrar.
    if not d or not d.get("id"):
        return None
    return d


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

    from . import cuentas
    cuenta = cuentas.por_correo(correo, perfil.get("name") or "")
    if not cuenta:
        return None
    return {**cuenta, "foto": perfil.get("picture", "")}


def galleta_de(usuario: dict) -> str:
    return _firmar({"id": usuario["id"], "correo": usuario.get("correo", ""),
                    "nombre": usuario.get("nombre", ""),
                    "exp": time.time() + DURACION})


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
    # Un tunel expone el portal aunque uvicorn solo escuche en localhost:
    # mirar el host no alcanza para saber si esta a la vista de internet.
    expuesto = (_c.PANEL_HOST not in ("127.0.0.1", "localhost")
                or bool(_c.PANEL_URL))
    if not expuesto:
        fuera.append("el portal solo escucha en esta maquina: ahi no se pide "
                     "cuenta")
    elif not PERMITIDOS:
        fuera.append("DANTE_CORREOS esta vacio: cualquiera puede crearse una "
                     "cuenta. Cada cuenta ve solo su propia memoria, pero si "
                     "el portal es de una sola familia, pon sus correos.")
    return fuera
