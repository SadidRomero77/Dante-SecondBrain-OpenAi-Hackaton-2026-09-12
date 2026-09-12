/* Dante · diagnostico fisico.
   Prende y apaga la luz de la pantalla una vez por segundo.
   No depende del USB para nada: si parpadea, el sketch corre. */
static const int PIN_LUZ = 42;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LUZ, OUTPUT);
}

void loop() {
  digitalWrite(PIN_LUZ, HIGH);
  Serial.println("luz ON");
  delay(700);
  digitalWrite(PIN_LUZ, LOW);
  Serial.println("luz OFF");
  delay(700);
}
