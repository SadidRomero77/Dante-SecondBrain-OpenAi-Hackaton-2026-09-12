"""dante semilla — carga una persona de ejemplo con su familia y su pasado.

Sin pasado no hay nada que recordar, y sin nada que recordar no hay demo.
Estos datos son inventados a proposito: sirven para probar sin usar la vida
real de nadie.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import memoria

USUARIO = "Rosa"

PERSONAS = [
    ("Ana", "hija", "Vive en Bogota. Viene casi todos los martes."),
    ("Miguel", "hijo", "Vive en Madrid. Llama los domingos."),
    ("Lucia", "nieta", "Hija de Ana. Doce anos."),
    ("Carmen", "vecina", "Vive en el 302. Tiene llave del apartamento."),
]

HECHOS = [
    ("Rosa nacio en Santa Marta y se mudo a Bogota a los veinte anos.", 0.95),
    ("Trabajo treinta anos como maestra de escuela primaria.", 0.95),
    ("Su esposo se llamaba Alberto y murio hace seis anos.", 0.95),
    ("Tuvieron un perro llamado Canela cuando los ninos estaban chiquitos.", 0.9),
    ("Le gusta el cafe con leche, sin azucar, por la manana.", 0.85),
    ("Toca el piano desde nina, aunque ya casi no lo hace.", 0.85),
    ("No le gusta la television por la noche, prefiere la radio.", 0.8),
    ("Ana le trajo un pastel de tres leches el martes pasado.", 0.9),
    ("Estuvieron hablando del viaje a Villa de Leyva de 1998.", 0.8),
    ("Le cuesta acordarse de los nombres de las personas nuevas.", 0.9),
    ("Camina hasta la panaderia de la esquina casi todas las tardes.", 0.85),
    ("Lucia esta aprendiendo a tocar guitarra y le manda videos.", 0.8),
]

EVENTOS = [
    ("Pastilla azul de la presion", "diario 09:00", "medicacion"),
    ("Pastilla blanca del corazon", "diario 21:00", "medicacion"),
    ("Visita de Ana", f"{(date.today()).isoformat()} 16:00", "visita"),
    ("Control con el doctor Restrepo",
     f"{(date.today() + timedelta(days=3)).isoformat()} 10:30", "cita"),
]


def correr(borrar: bool = False) -> int:
    c = memoria.abrir()

    if borrar:
        for t in ("personas", "hechos", "episodios", "eventos", "ajustes"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
        print("  memoria vaciada")

    memoria.poner_ajuste(c, "nombre_usuario", USUARIO)

    for nombre, relacion, notas in PERSONAS:
        memoria.registrar_persona(c, nombre, relacion, notas)
    c.execute("UPDATE personas SET ultima_visita=? WHERE nombre='Ana'",
              ((date.today() - timedelta(days=7)).isoformat(),))
    c.commit()

    print(f"  {len(PERSONAS)} personas")
    print(f"  sembrando {len(HECHOS)} hechos (calculando vectores)...")
    for texto, conf in HECHOS:
        memoria.anotar(c, texto, fuente="semilla", confianza=conf)

    for que, cuando, tipo in EVENTOS:
        c.execute("INSERT INTO eventos(que,cuando,tipo) VALUES(?,?,?)",
                  (que, cuando, tipo))
    c.commit()
    print(f"  {len(EVENTOS)} eventos")

    r = memoria.resumen(c)
    print(f"\n  listo: usuario {r['usuario']}, {r['personas']} personas, "
          f"{r['hechos']} hechos, {r['eventos']} eventos")
    c.close()
    return 0


def mostrar() -> int:
    c = memoria.abrir()
    r = memoria.resumen(c)
    print(f"\n=== memoria de Dante ===  ({config_db()})\n")
    print(f"  usuario: {r['usuario']}")
    print(f"  {r['personas']} personas · {r['hechos']} hechos · "
          f"{r['eventos']} eventos · {r['episodios']} conversaciones\n")
    print("--- tarjeta de perfil (lo que Dante sabe siempre) ---\n")
    print(memoria.tarjeta_de_perfil(c))
    c.close()
    return 0


def config_db() -> str:
    from . import config
    return str(config.DB)
