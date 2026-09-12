"""Sacar de la memoria lo que quedo de una prueba o de otra persona.

Existe por un choque real: la persona de ejemplo se llama Rosa, y cuando
alguien configura el agente con su propio nombre, los recuerdos de Rosa
siguen ahi. Dante los encuentra al buscar y los cuenta como si fueran de
quien tiene enfrente, porque hace bien su trabajo: sobre la vida de alguien
solo afirma lo que la memoria le devuelve.

Por eso borra de verdad, y por eso no borra sin que se lo pidan dos veces:
primero muestra que se llevaria, y solo con --si lo hace.
"""

from __future__ import annotations

from . import memoria

# Cada tabla guarda el texto en una columna con distinto nombre.
TABLAS = [
    ("hechos", "texto"),
    ("episodios", "resumen"),
    ("episodios", "transcripcion"),
    ("eventos", "que"),
    ("senales", "texto"),
]


def correr(que: str, de_verdad: bool = False) -> int:
    if not que.strip():
        print("Dime que olvidar. Ej: dante olvidar Rosa")
        return 1

    patron = f"%{que.strip()}%"
    c = memoria.abrir()
    try:
        total = 0
        for tabla, campo in TABLAS:
            filas = c.execute(
                f"SELECT id, {campo} AS t FROM {tabla} WHERE {campo} LIKE ?",
                (patron,)).fetchall()
            if not filas:
                continue
            print(f"\n{tabla} ({len(filas)}):")
            for f in filas[:6]:
                print(f"  - {f['t'][:96]}")
            if len(filas) > 6:
                print(f"  ... y {len(filas) - 6} mas")
            total += len(filas)

        gente = c.execute("SELECT id, nombre, relacion FROM personas "
                          "WHERE nombre LIKE ?", (patron,)).fetchall()
        if gente:
            print(f"\npersonas ({len(gente)}):")
            for g in gente:
                print(f"  - {g['nombre']}" +
                      (f" ({g['relacion']})" if g["relacion"] else ""))
            total += len(gente)

        if not total:
            print(f"No hay nada que mencione «{que}».")
            return 0

        if not de_verdad:
            print(f"\nSon {total} recuerdos. Esto fue solo una mirada: no "
                  f"borre nada.")
            print(f"Si estas seguro:  dante olvidar {que} --si")
            return 0

        for tabla, campo in TABLAS:
            c.execute(f"DELETE FROM {tabla} WHERE {campo} LIKE ?", (patron,))
        c.execute("DELETE FROM personas WHERE nombre LIKE ?", (patron,))
        c.commit()
        print(f"\nListo: {total} recuerdos olvidados.")
        return 0
    finally:
        c.close()
