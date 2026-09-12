/* ===========================================================================
   Dante · paso 1 — prueba de vida y escaneo del bus I2C
   ---------------------------------------------------------------------------
   Que hace:
     - Enciende la luz de la pantalla (senal visible de que arranco).
     - Apaga el amplificador, para que no truene el parlante.
     - Recorre el bus I2C del codec e imprime las direcciones que contestan.
     - Imprime PSRAM, flash y modelo de chip, para confirmar la configuracion.

   Que esperamos ver:
     0x18  ->  ES8311  (el que manda al parlante)
     0x41  ->  ES7210  (el que lee los microfonos)
   Si aparecen otras, no importa: lo que necesito es la lista real.

   ---------------------------------------------------------------------------
   AJUSTES OBLIGATORIOS en el menu Herramientas del Arduino IDE:

     Placa .......................... ESP32S3 Dev Module
     USB CDC On Boot ................ Enabled        <-- sin esto no ves nada
     PSRAM .......................... OPI PSRAM      <-- 8 MB de la placa
     Flash Size ..................... 16MB (128Mb)
     Partition Scheme ............... 16M Flash (3MB APP/9.9MB FATFS)
     Upload Mode .................... UART0 / Hardware CDC
     USB Mode ....................... Hardware CDC and JTAG

   Conecta el cable al puerto USB-C que esta MAS CERCA del modulo metalico
   (ese es el nativo). Si no aparece ningun puerto, prueba el otro.
   =========================================================================== */

#include <Wire.h>

// Pines confirmados en el config.h de la placa LAFVIN.
static const int PIN_SDA        = 1;
static const int PIN_SCL        = 2;
static const int PIN_LUZ        = 42;  // retroiluminacion del ST7789
static const int PIN_AMPLI      = 48;  // PA_EN del modulo de audio

static const uint32_t I2C_HZ    = 100000;

void escanear() {
  Serial.println();
  Serial.println("--- escaneando bus I2C (SDA=1, SCL=2) ---");
  int encontrados = 0;

  for (uint8_t dir = 1; dir < 127; dir++) {
    Wire.beginTransmission(dir);
    uint8_t r = Wire.endTransmission();
    if (r == 0) {
      encontrados++;
      Serial.printf("  responde: 0x%02X", dir);
      if (dir == 0x18) Serial.print("   <-- ES8311 (parlante), como esperabamos");
      else if (dir == 0x41) Serial.print("   <-- ES7210 (microfonos), como esperabamos");
      else if (dir >= 0x40 && dir <= 0x43) Serial.print("   <-- podria ser el ES7210");
      else if (dir == 0x19) Serial.print("   <-- podria ser el ES8311");
      Serial.println();
    }
  }

  if (encontrados == 0) {
    Serial.println("  NADA respondio.");
    Serial.println("  Revisa: el modulo de audio bien encajado, y VCC del modulo a 5V.");
  } else {
    Serial.printf("  total: %d dispositivo(s)\n", encontrados);
  }
  Serial.println("--- fin del escaneo ---");
}

void setup() {
  Serial.begin(115200);

  // Con USB CDC hay que esperar a que la PC abra el puerto, pero sin colgarse
  // para siempre si nadie lo abre.
  uint32_t limite = millis() + 4000;
  while (!Serial && millis() < limite) { delay(50); }
  delay(400);

  pinMode(PIN_AMPLI, OUTPUT);
  digitalWrite(PIN_AMPLI, LOW);      // amplificador apagado: silencio limpio
  pinMode(PIN_LUZ, OUTPUT);
  digitalWrite(PIN_LUZ, HIGH);       // luz encendida: se ve que arranco

  Serial.println();
  Serial.println("===========================================");
  Serial.println(" Dante · paso 1 — prueba de vida");
  Serial.println("===========================================");
  Serial.printf("  chip .......... %s, %d nucleo(s), rev %d\n",
                ESP.getChipModel(), ESP.getChipCores(), ESP.getChipRevision());
  Serial.printf("  cpu ........... %lu MHz\n", (unsigned long)getCpuFrequencyMhz());
  Serial.printf("  flash ......... %lu bytes\n", (unsigned long)ESP.getFlashChipSize());
  Serial.printf("  PSRAM ......... %lu bytes", (unsigned long)ESP.getPsramSize());
  if (ESP.getPsramSize() == 0) {
    Serial.println("   <-- MAL: pon PSRAM en 'OPI PSRAM' y vuelve a subir");
  } else {
    Serial.println("   (bien)");
  }
  Serial.printf("  RAM libre ..... %lu bytes\n", (unsigned long)ESP.getFreeHeap());
  Serial.println();
  Serial.println("  La luz de la pantalla deberia estar encendida.");

  Wire.begin(PIN_SDA, PIN_SCL, I2C_HZ);
  escanear();

  Serial.println();
  Serial.println("Repito el escaneo cada 5 segundos. Copia todo esto y mandalo.");
}

void loop() {
  delay(5000);
  escanear();
}
