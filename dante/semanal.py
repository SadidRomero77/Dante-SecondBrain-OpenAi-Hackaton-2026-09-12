"""El resumen que Dante le manda a la familia.

Cierra el circulo del proyecto. Dante acompana todos los dias; una vez por
semana les cuenta a los hijos como estuvo, sin que nadie tenga que preguntar
-que es justo lo que no pasa cuando alguien vive lejos: uno llama el domingo,
pregunta "como estas" y le contestan "bien"-.

Dos cosas que el resumen no hace, a proposito:

No diagnostica. Cuenta lo que paso y lo que cambio, con numeros. "Esta semana
pregunto cinco veces que dia era; antes, una" es un dato que sirve para hablar
con un medico. "Esta empeorando" es una conclusion que no nos toca sacar, y
que ademas asusta.

No repite conversaciones. La familia no tiene derecho a leer todo lo que ella
dijo: le confia sus cosas a un perro, no a un altavoz. Va lo que hace falta
para cuidarla, no la transcripcion.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from . import config, memoria, trabajos

MODELO = "gpt-5"

INSTRUCCIONES = """\
Escribes el resumen semanal que un perro acompanante le manda a la familia de
la persona mayor a la que cuida. Lo leen sus hijos, que viven lejos y no
pudieron estar.

Como debe ser:
- Calido y directo. Escribes a una familia preocupada, no a un comite.
- Cuatro o cinco frases. Si no paso gran cosa, dos.
- En espanol, tratando a la familia de tu.
- Nombra a la persona por su nombre.

Lo que NO puedes hacer:
- NO diagnostiques ni interpretes. No digas "esta decayendo", "parece
  depresion" ni "deberian llevarla al medico". Cuenta lo que paso.
- NO inventes nada. Si los datos son pocos, di que fue una semana tranquila.
- NO cites frases textuales de sus conversaciones. Lo que ella le cuenta a
  Dante es suyo.
- NO uses listas ni vinetas. Es una nota, no un informe.

Si hay cambios respecto de semanas anteriores, mencionalos con el numero al
lado, sin adornar: "esta semana converso dos veces; suele conversar cinco".
Eso es lo que le sirve a un hijo para saber si llamar.
"""


def _datos(c, dias: int = 7) -> dict:
    hoy = date.today()
    desde = (hoy - timedelta(days=dias)).isoformat()
    eps = c.execute("SELECT inicio, resumen FROM episodios WHERE inicio >= ? "
                    "ORDER BY inicio", (desde,)).fetchall()
    hechos = c.execute("SELECT texto FROM hechos WHERE fecha >= ? AND "
                       "fuente != 'configuracion' ORDER BY id", (desde,)).fetchall()
    p = memoria.principal(c)
    return {
        "persona": (p["nombre"] if p else "") or "la persona",
        "desde": desde, "hasta": hoy.isoformat(),
        "conversaciones": len(eps),
        "de_que_hablaron": [e["resumen"] for e in eps if e["resumen"]][:12],
        "cosas_nuevas_que_aprendio": [h["texto"] for h in hechos][:10],
        "senales": memoria.senales_recientes(c, dias),
        "cambios": memoria.cambios(c),
        "agenda": memoria.agenda_de(c, "todo")[:8],
    }


def redactar(datos: dict) -> str:
    """Le pide al modelo la nota. Si no hay llave, arma una version sobria."""
    if not config.API_KEY:
        return _sin_modelo(datos)
    try:
        from openai import OpenAI
        r = OpenAI(api_key=config.API_KEY).responses.create(
            model=MODELO,
            instructions=INSTRUCCIONES,
            input=json.dumps(datos, ensure_ascii=False, indent=1),
        )
        return (r.output_text or "").strip() or _sin_modelo(datos)
    except Exception as e:
        print(f"  aviso: no pude redactar con el modelo ({e}). Voy con lo basico.")
        return _sin_modelo(datos)


def _sin_modelo(d: dict) -> str:
    """Sin llave o sin red, la familia igual recibe algo cierto.

    Es feo a proposito: son los datos pelados. Prefiero eso a no mandar nada,
    porque el domingo que no llega el resumen nadie sabe si es que no paso
    nada o que el aparato dejo de funcionar.
    """
    p = d["persona"]
    t = [f"{p} conversó {d['conversaciones']} " +
         ("vez" if d["conversaciones"] == 1 else "veces") + " esta semana."]
    for s in d["senales"]:
        t.append(f"{s['veces']} " + ("vez" if s["veces"] == 1 else "veces") +
                 f" {s['que']}.")
    for c in d["cambios"]:
        t.append(f"{c['que']}: {c['esta_semana']} frente a {c['antes']}.")
    return " ".join(t)


def correr(enviar: bool = False, dias: int = 7) -> int:
    c = memoria.abrir()
    try:
        datos = _datos(c, dias)
        if not datos["conversaciones"]:
            print("No hubo ninguna conversación esta semana. No hay nada que contar.")
            return 0
        nota = redactar(datos)
        print(f"\n--- resumen del {datos['desde']} al {datos['hasta']} ---\n")
        print(nota)
        if datos["cambios"]:
            print("\nlo que cambió:")
            for x in datos["cambios"]:
                print(f"  - {x['que']} ({x['cuanto']}): "
                      f"{x['esta_semana']} vs {x['antes']}")
        if not enviar:
            print("\n(Esto fue solo una vista. Para mandárselo a la familia: "
                  "dante resumen --enviar)")
            return 0
        if not trabajos.activo():
            print("\nTrigger.dev no está configurado: pon TRIGGER_SECRET_KEY "
                  "en el .env. El resumen de arriba es válido igual.")
            return 1
        r = trabajos.resumen_semanal(
            persona=datos["persona"], desde=datos["desde"], hasta=datos["hasta"],
            resumen=nota, conversaciones=datos["conversaciones"],
            senales=[f"{s['veces']}x {s['que']}" for s in datos["senales"]])
        print(f"\nenviado: {r}")
        return 0 if r.get("ok") else 1
    finally:
        c.close()
