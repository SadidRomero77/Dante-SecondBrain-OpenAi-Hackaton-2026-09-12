/* Dante · diagnostico minimo. Solo imprime. Nada de I2C, GPIO ni Serial0.
   Si esto se ve, el problema esta en el sketch grande.
   Si esto tampoco se ve, el problema es la configuracion USB. */
void setup() {
  Serial.begin(115200);
  delay(3000);              // margen para que la PC abra el puerto
  Serial.println();
  Serial.println("HOLA-DESDE-DANTE");
  Serial.printf("chip=%s psram=%lu flash=%lu\n",
                ESP.getChipModel(),
                (unsigned long)ESP.getPsramSize(),
                (unsigned long)ESP.getFlashChipSize());
}

void loop() {
  static uint32_t n = 0;
  Serial.printf("vivo %lu\n", (unsigned long)++n);
  delay(1000);
}
