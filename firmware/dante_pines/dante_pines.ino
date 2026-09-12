/* Dante · buscador de pines.
   Vigila a la vez todos los pines seguros de tocar y dice cual se activo.
   Se usa asi: un jumper con un extremo en GND y con el otro se toca el
   agujero que uno quiere identificar. La placa responde con el numero.

   Sirve para dejar de contar filas de memoria, que es lo que ya nos costo
   dos sustos: se mide el agujero en vez de deducirlo.

   Quedan FUERA a proposito:
     19 y 20  son las lineas de datos del USB; tocarlas deja la placa muda
     0,3,45,46 deciden como arranca el chip; tocarlas impide que encienda
     43 y 44  son el puerto serie
     33 a 37  son la memoria flash de este modulo: el chip lee de ahi su
              propio codigo, y tocarlos lo mata a los pocos instantes de
              arrancar. El USB sigue apareciendo, porque es un periferico
              aparte, asi que parece un problema de cableado y no lo es.
              Esa confusion nos costo una hora larga; de ahi este aviso.
   Tocar esos grupos es justo lo que no hay que hacer, y por eso el
   buscador ni los ofrece. */

static const int PINES[] = {
  1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
  21, 38, 39, 40, 41, 42, 47, 48
};
static const int CUANTOS = sizeof(PINES) / sizeof(PINES[0]);
static bool antes[CUANTOS];

void setup() {
  Serial.begin(115200);
  delay(2500);
  for (int i = 0; i < CUANTOS; i++) {
    pinMode(PINES[i], INPUT_PULLUP);
    antes[i] = true;
  }
  Serial.println("\n=== buscador de pines ===");
  Serial.println("  Un extremo del jumper en GND. Con el otro toca un agujero.");
  Serial.println("  Te digo que pin es.\n");

  delay(600);                       // dejar que los pullups se asienten
  bool sucio = false;
  for (int i = 0; i < CUANTOS; i++)
    if (digitalRead(PINES[i]) == LOW) {
      Serial.printf("  ojo: GPIO%d ya esta en tierra sin tocar nada\n", PINES[i]);
      sucio = true;
    }
  if (!sucio) Serial.println("  (en reposo no hay ningun pin en tierra: limpio)\n");
}

void loop() {
  for (int i = 0; i < CUANTOS; i++) {
    bool alto = digitalRead(PINES[i]) == HIGH;
    if (!alto && antes[i]) Serial.printf("  >>> GPIO%d  <<<\n", PINES[i]);
    antes[i] = alto;
  }
  delay(25);
}
