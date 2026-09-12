/* Dante · diagnostico: el ES7210 quedo bien configurado, o el problema es fisico?

   Si el chip contesta por I2C y ademas sus registros tienen los valores que le
   escribimos, la configuracion esta bien y el silencio viene del cable de datos
   (DIN, GPIO12) o del propio microfono. Si los registros salen en cero o en su
   valor de fabrica, el problema es que las escrituras no estan llegando. */

#include <Wire.h>

static const int PIN_SDA = 1, PIN_SCL = 2, PIN_AMPLI = 48, PIN_LUZ = 42;
static const uint8_t ES7210 = 0x41, ES8311 = 0x18;

static void esc(uint8_t d, uint8_t r, uint8_t v) {
  Wire.beginTransmission(d); Wire.write(r); Wire.write(v); Wire.endTransmission();
}
static int lee(uint8_t d, uint8_t r) {
  Wire.beginTransmission(d); Wire.write(r);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom((int)d, 1) != 1) return -1;
  return Wire.read();
}

struct Reg { uint8_t dir; uint8_t reg; uint8_t esperado; const char *que; };

void setup() {
  Serial.begin(115200);
  delay(2500);
  pinMode(PIN_LUZ, OUTPUT);   digitalWrite(PIN_LUZ, HIGH);
  pinMode(PIN_AMPLI, OUTPUT); digitalWrite(PIN_AMPLI, LOW);
  Wire.begin(PIN_SDA, PIN_SCL, 100000);

  Serial.println();
  Serial.println("=== configurando el ES7210 igual que siempre ===");
  esc(ES7210, 0x00, 0xFF); esc(ES7210, 0x00, 0x32);
  esc(ES7210, 0x09, 0x30); esc(ES7210, 0x0A, 0x30);
  esc(ES7210, 0x11, 0x60); esc(ES7210, 0x12, 0x00);
  esc(ES7210, 0x40, 0xC3); esc(ES7210, 0x41, 0x70); esc(ES7210, 0x42, 0x70);
  for (uint8_t r = 0x43; r <= 0x46; r++) esc(ES7210, r, 10 | 0x10);
  for (uint8_t r = 0x47; r <= 0x4A; r++) esc(ES7210, r, 0x08);
  esc(ES7210, 0x07, 0x20);
  esc(ES7210, 0x02, 0x01 | (1 << 7));
  esc(ES7210, 0x04, 0x02); esc(ES7210, 0x05, 0x00);
  esc(ES7210, 0x06, 0x04);
  esc(ES7210, 0x4B, 0x0F); esc(ES7210, 0x4C, 0x0F);
  esc(ES7210, 0x00, 0x71); esc(ES7210, 0x00, 0x41);
  delay(100);

  static const Reg tabla[] = {
    {ES7210, 0x00, 0x41, "estado general"},
    {ES7210, 0x11, 0x60, "formato I2S 16 bits"},
    {ES7210, 0x02, 0x81, "reloj del ADC"},
    {ES7210, 0x07, 0x20, "osr"},
    {ES7210, 0x43, 0x1A, "ganancia mic 1"},
    {ES7210, 0x44, 0x1A, "ganancia mic 2"},
    {ES7210, 0x47, 0x08, "encendido mic 1"},
    {ES7210, 0x4B, 0x0F, "alimentacion mic 1-2"},
    {ES8311, 0x00, 0x00, "ES8311 vivo (valor libre)"},
  };

  Serial.println();
  Serial.println("=== leyendo de vuelta lo que quedo escrito ===");
  int malos = 0;
  for (auto &t : tabla) {
    int v = lee(t.dir, t.reg);
    bool ok = (v >= 0) && (t.esperado == 0x00 || v == t.esperado);
    if (!ok) malos++;
    Serial.printf("  0x%02X reg 0x%02X = %s  (esperaba 0x%02X)  %-22s %s\n",
                  t.dir, t.reg,
                  v < 0 ? "  --" : (String("0x") + String(v, HEX)).c_str(),
                  t.esperado, t.que, ok ? "bien" : "<-- MAL");
  }

  Serial.println();
  if (malos == 0) {
    Serial.println(">>> El ES7210 esta bien configurado y responde.");
    Serial.println(">>> Si aun asi no entra audio, el problema NO es el chip:");
    Serial.println(">>> es la linea de datos DIN (GPIO12) o el microfono mismo.");
    Serial.println(">>> ACCION: reasienta el modulo de audio en el shield.");
  } else {
    Serial.printf(">>> %d registro(s) no quedaron escritos.\n", malos);
    Serial.println(">>> Las escrituras I2C no estan llegando bien.");
  }
}

void loop() { delay(5000); }
