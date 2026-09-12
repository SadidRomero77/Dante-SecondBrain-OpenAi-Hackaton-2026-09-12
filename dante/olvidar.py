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


TODAS = ["hechos", "episodios", "eventos", "senales", "personas"]


def vaciar(de_verdad: bool = False) -> int:
    """Deja la memoria en blanco, conservando la configuracion.

    Hace falta porque buena parte de los datos de ejemplo no llevan el nombre
    de nadie -"trabajo treinta anos como maestra"- y por nombre no hay forma
    de alcanzarlos. Borrar por palabra deja justo esos, que son los que
    despues aparecen en una conversacion sin que se entienda de donde salen.

    Los ajustes se quedan, y lo que se escribio en el portal sobre la persona
    se vuelve a grabar enseguida: eso no es un recuerdo aprendido, es lo que
    la familia dio por bueno.
    """
    from . import ajustes
    c = memoria.abrir()
    try:
        cuenta = {t: c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
                  for t in TODAS}
        total = sum(cuenta.values())
        print("En la memoria hay ahora:")
        for t, n in cuenta.items():
            print(f"  {t}: {n}")
        if not total:
            print("\nYa esta vacia.")
            return 0
        if not de_verdad:
            print(f"\nSon {total} registros. Esto fue solo una mirada: no "
                  f"borre nada.")
            print("Si estas seguro:  dante olvidar --todo --si")
            return 0
        for t in TODAS:
            c.execute(f"DELETE FROM {t}")
        c.commit()
        ajustes._a_la_memoria(c, ajustes.leer(c))
        quedan = c.execute("SELECT COUNT(*) n FROM hechos").fetchone()["n"]
        print(f"\nMemoria en blanco. {total} registros borrados.")
        if quedan:
            print(f"Se volvieron a grabar {quedan} hechos desde lo que "
                  f"escribiste en el portal.")
        print("Ojo: tambien se fueron las caras. Hay que volver a ensenarselas.")
        return 0
    finally:
        c.close()


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
