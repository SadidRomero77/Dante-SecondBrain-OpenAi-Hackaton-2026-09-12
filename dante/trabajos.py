"""Dispara las tareas de Trigger.dev desde el agente.

La division es deliberada: lo que Dante DICE en voz alta lo maneja el PC de la
casa, porque es inmediato y no depende de nadie. Lo que SALE hacia la familia
—el resumen semanal, el aviso de que algo no se confirmo— lo maneja Trigger.dev,
porque necesita reintentos, esperas largas y llegar aunque el computador este
dormido. Un temporizador local no hace ninguna de las tres.

Los datos de la persona no salen de su casa: solo viaja el texto que su familia
iba a leer de todas formas.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# Importar config carga el .env. Sin esto, este modulo lee variables
# vacias cuando alguien lo importa antes que a config, y la integracion
# queda apagada sin que nadie entienda por que.
from . import config  # noqa: F401

API = "https://api.trigger.dev/api/v1/tasks/{tarea}/trigger"

CLAVE = (os.getenv("TRIGGER_SECRET_KEY") or "").strip()
PROYECTO = (os.getenv("TRIGGER_PROJECT_REF") or "").strip()
CORREO_FAMILIA = (os.getenv("TRIGGER_CORREO_FAMILIA") or "").strip()


def activo() -> bool:
    return bool(CLAVE)


def disparar(tarea: str, carga: dict) -> dict:
    """Encola una tarea. Nunca revienta al que la llama.

    Si Trigger.dev no esta configurado o no responde, se devuelve el motivo y
    el agente sigue como si nada: un resumen que no sale no puede tumbar una
    conversacion en curso.
    """
    if not activo():
        return {"ok": False, "motivo": "Trigger.dev sin configurar"}

    datos = json.dumps({"payload": carga}).encode()
    r = urllib.request.Request(API.format(tarea=tarea), data=datos, method="POST")
    r.add_header("Authorization", f"Bearer {CLAVE}")
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=15) as f:
            d = json.loads(f.read())
        return {"ok": True, "id": d.get("id"), "tarea": tarea}
    except urllib.error.HTTPError as e:
        return {"ok": False, "motivo": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"}


def resumen_semanal(persona: str, desde: str, hasta: str, resumen: str,
                    conversaciones: int, senales: list[str] | None = None,
                    correo: str = "") -> dict:
    return disparar("resumen-semanal", {
        "persona": persona,
        "correoFamilia": correo or CORREO_FAMILIA,
        "desde": desde, "hasta": hasta,
        "resumen": resumen,
        "conversaciones": conversaciones,
        "señales": senales or [],
    })


def vigilar_medicacion(persona: str, medicamento: str, minutos: int,
                       url_confirmacion: str, correo: str = "") -> dict:
    return disparar("vigilar-medicacion", {
        "persona": persona,
        "medicamento": medicamento,
        "correoFamilia": correo or CORREO_FAMILIA,
        "minutosDeGracia": minutos,
        "urlConfirmacion": url_confirmacion,
    })
