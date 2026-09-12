"""dante doctor — revisa que el entorno este listo. No gasta creditos."""
from __future__ import annotations

import sys
from pathlib import Path

from . import config

OK = "  [ok]  "
MAL = "  [MAL] "
AVISO = "  [ojo] "

# VID de Espressif: asi reconocemos la placa entre los puertos serie.
VID_ESPRESSIF = 0x303A


def _linea(estado: str, texto: str, detalle: str = "") -> bool:
    print(f"{estado}{texto}")
    if detalle:
        print(f"         {detalle}")
    return estado == OK


def revisar() -> int:
    print("\n=== dante doctor ===\n")
    fallos = 0

    # --- Python ---
    v = sys.version_info
    if v >= (3, 11):
        _linea(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fallos += 1
        _linea(MAL, f"Python {v.major}.{v.minor}", "Se necesita 3.11 o mas nuevo.")

    # --- .env ---
    env = config.RAIZ / ".env"
    if not env.exists():
        fallos += 1
        _linea(MAL, "Falta el archivo .env", "Copia .env.example a .env y pega tu llave.")
    else:
        _linea(OK, "Archivo .env encontrado")

    # --- llave ---
    k = config.API_KEY
    if not k:
        fallos += 1
        _linea(MAL, "OPENAI_API_KEY vacia", "Pegala en .env. No la pegues en el chat.")
    elif not k.startswith("sk-"):
        fallos += 1
        _linea(MAL, "OPENAI_API_KEY no parece una llave", "Deberia empezar con 'sk-'.")
    else:
        _linea(OK, f"OPENAI_API_KEY presente ({k[:7]}...{k[-4:]}, {len(k)} caracteres)")

    # --- modelos configurados ---
    _linea(OK, "Modelos configurados",
           f"voz={config.MODELO_VOZ}  texto={config.MODELO_TEXTO}  "
           f"embeddings={config.MODELO_EMBEDDINGS}  voz_tts={config.VOZ}")

    # --- claves que el .env no tiene y el ejemplo si ---
    ejemplo = config.RAIZ / ".env.example"
    if env.exists() and ejemplo.exists():
        import re

        def _claves(t):
            return {m.group(1) for m in re.finditer(r"^\s*([A-Z0-9_]+)\s*=", t,
                                                    re.MULTILINE)}
        faltan = _claves(ejemplo.read_text(encoding="utf-8")) - \
                 _claves(env.read_text(encoding="utf-8"))
        if faltan:
            _linea(AVISO, f"Al .env le faltan {len(faltan)} clave(s) nuevas",
                   ", ".join(sorted(faltan)) +
                   "\n         Copialas de .env.example. Sin ellas esas "
                   "funciones quedan apagadas, no rotas.")
        else:
            _linea(OK, "El .env tiene todas las claves del ejemplo")

    # --- integraciones opcionales ---
    from . import auth, proveedor, trabajos
    partes = [
        f"modelos de texto: {proveedor.por_donde()}",
        f"busqueda: {'exa' if config.EXA_API_KEY else 'openai (mas lenta)'}",
        f"portal: {'con login de Auth0' if auth.activo() else 'abierto (solo local)'}",
        f"camara: {'activa' if config.CAMARA else 'apagada'}",
        f"trabajos: {'trigger.dev' if trabajos.activo() else 'solo locales'}",
    ]
    _linea(OK, "Integraciones", "  ·  ".join(partes))

    # --- carpeta de datos ---
    try:
        config.DB.parent.mkdir(parents=True, exist_ok=True)
        _linea(OK, f"Carpeta de datos lista ({config.DB.parent})")
    except OSError as e:
        fallos += 1
        _linea(MAL, "No se pudo crear la carpeta de datos", str(e))

    # --- puertos serie ---
    print()
    try:
        from serial.tools import list_ports
    except ImportError:
        fallos += 1
        _linea(MAL, "pyserial no instalado", "Corre la instalacion de dependencias otra vez.")
        return fallos

    puertos = list(list_ports.comports())
    if not puertos:
        _linea(AVISO, "No hay ningun puerto serie visible",
               "Normal si el aparato no esta conectado. "
               "Si SI esta conectado y estas en WSL, los puertos USB no se ven desde WSL: "
               "corre dante desde Windows.")
    else:
        _linea(OK, f"{len(puertos)} puerto(s) serie visible(s)")
        candidatos = []
        for p in puertos:
            marca = "  <-- parece la placa" if p.vid == VID_ESPRESSIF else ""
            if marca:
                candidatos.append(p.device)
            print(f"         {p.device:10s} {(p.description or '')[:46]:46s}{marca}")
        if candidatos:
            print()
            _linea(OK, f"Placa detectada en {', '.join(candidatos)}",
                   "Ponlo en DANTE_PUERTO_SERIE del .env, o dejalo vacio para autodetectar.")
        else:
            _linea(AVISO, "Ninguno tiene el identificador de Espressif",
                   "Conecta el aparato por el puerto USB nativo y vuelve a correr esto.")

    print()
    if fallos:
        print(f"=== {fallos} cosa(s) por arreglar ===\n")
    else:
        print("=== todo listo. Siguiente: dante smoke ===\n")
    return fallos
