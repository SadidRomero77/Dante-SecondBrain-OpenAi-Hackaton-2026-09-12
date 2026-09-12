/* Dante · prueba aislada del servo (GPIO10).
   El ESP32-S3 admite como maximo 14 bits de resolucion en el LEDC, no 16.
   Por eso buscamos la resolucion mas alta que la placa acepte en vez de
   suponerla, y calculamos el pulso a partir de la que consiguio. */

static const int PIN_SERVO = 10;
static int bits = 0;             // la que acepto la placa

static bool servo_grados(int g) {
  if (g < 0) g = 0; else if (g > 180) g = 180;
  uint32_t us   = 500 + (uint32_t)g * 2000 / 180;   // 0.5 ms .. 2.5 ms
  uint32_t tope = (1UL << bits) - 1;
  return ledcWrite(PIN_SERVO, (uint32_t)((uint64_t)us * tope / 20000));
}

void setup() {
  Serial.begin(115200);
  delay(2500);
  Serial.println("\n=== prueba del servo en GPIO10 ===");

  for (int b = 16; b >= 10 && !bits; b--)
    if (ledcAttach(PIN_SERVO, 50, b)) bits = b;

  if (!bits) { Serial.println("  NINGUNA resolucion funciono."); return; }

  Serial.printf("  resolucion aceptada: %d bits  (tope %lu)\n",
                bits, (unsigned long)((1UL << bits) - 1));
  servo_grados(90);
  delay(400);
  Serial.printf("  frecuencia real: %lu Hz   (deben ser 50)\n",
                (unsigned long)ledcReadFreq(PIN_SERVO));
  Serial.println("\n  barriendo 60 -> 140 -> 60, sin parar.");
}

void loop() {
  if (!bits) { delay(1000); return; }
  for (int g = 60; g <= 140; g += 40) { servo_grados(g); Serial.printf("  %3d grados\n", g); delay(700); }
  for (int g = 100; g >= 60; g -= 40) { servo_grados(g); Serial.printf("  %3d grados\n", g); delay(700); }
}
