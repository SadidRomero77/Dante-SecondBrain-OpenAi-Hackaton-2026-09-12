/* Dante · verificacion de PSRAM, por tres vias distintas. */
void setup() {
  Serial.begin(115200);
  delay(2500);
  Serial.println();
  Serial.println("=== PSRAM ===");

  Serial.print("psramFound() ......... ");
  Serial.println(psramFound() ? "SI" : "NO");

  Serial.print("ESP.getPsramSize() ... ");
  Serial.println((unsigned long)ESP.getPsramSize());

  Serial.print("ESP.getFreePsram() ... ");
  Serial.println((unsigned long)ESP.getFreePsram());

  // Prueba real: pedir 2 MB en PSRAM y escribir/leer.
  size_t n = 2 * 1024 * 1024;
  uint8_t *p = (uint8_t *)ps_malloc(n);
  if (!p) {
    Serial.println("ps_malloc(2MB) ....... FALLO");
  } else {
    p[0] = 0xAB; p[n - 1] = 0xCD;
    bool ok = (p[0] == 0xAB && p[n - 1] == 0xCD);
    Serial.print("ps_malloc(2MB) ....... ");
    Serial.println(ok ? "OK, lectura/escritura verificada" : "corrupto");
    free(p);
  }

  Serial.print("heap interno libre ... ");
  Serial.println((unsigned long)ESP.getFreeHeap());
  Serial.println("=== fin ===");
}

void loop() { delay(2000); Serial.println("."); }
