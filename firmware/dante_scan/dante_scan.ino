/* ===========================================================================
   Dante · paso 1 — prueba de vida y escaneo del bus I2C
   ---------------------------------------------------------------------------
   Que hace:
     - Enciende la luz de la pantalla (senal visible de que arranco).
     - Apaga el amplificador, para que no truene el parlante.
     - Recorre el bus I2C del codec e imprime las direcciones que contestan.
     - Imprime PSRAM, flash y modelo de chip, para confirmar la configuracion.

   Imprime por los DOS puertos USB a la vez, asi que no importa en cual estes.

   Que esperamos ver:
     0x18  ->  ES8311  (el que manda al parlante)
     0x41  ->  ES7210  (el que lee los microfonos)
   Si aparecen otras, no importa: lo que necesito es la lista real.

   ---------------------------------------------------------------------------
   AJUSTES en el menu Herramientas (Arduino IDE 2.x, core esp32 3.3.11):

     Placa .......................... ESP32S3 Dev Module
     USB CDC On Boot ................ Enabled
     PSRAM .......................... OPI PSRAM
     Flash Size ..................... 16MB (128Mb)
     Partition Scheme ............... 16M Flash (3MB APP/9.9MB FATFS)
     USB Mode ....................... Hardware CDC and JTAG
     Upload Mode .................... UART0 / Hardware CDC
     Upload Speed ................... 921600

   Confirmado en la placa real: 16 MB de flash y 8 MB de PSRAM OPI.
   Ver HARDWARE.md.
   =========================================================================== */

#include <Wire.h>
#include <stdarg.h>

// Pines confirmados en el config.h de la placa LAFVIN.
static const int PIN_SDA   = 1;
static const int PIN_SCL   = 2;
static const int PIN_LUZ   = 42;  // retroiluminacion del ST7789
static const int PIN_AMPLI = 48;  // PA_EN del modulo de audio

static const uint32_t I2C_HZ = 100000;

/* Imprime por el USB nativo y por el puerto UART al mismo tiempo.
   Asi el Monitor Serie muestra algo sin importar a cual puerto conectaste. */
static void say(const char *fmt, ...) {
  char buf[220];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.println(buf);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.println(buf);
#endif
}

void escanear() {
  say("");
  say("--- escaneando bus I2C (SDA=%d, SCL=%d) ---", PIN_SDA, PIN_SCL);
  int encontrados = 0;

  for (uint8_t dir = 1; dir < 127; dir++) {
    Wire.beginTransmission(dir);
    if (Wire.endTransmission() == 0) {
      encontrados++;
      const char *pista = "";
      if (dir == 0x18)                        pista = "  <-- ES8311 (parlante), como esperabamos";
      else if (dir == 0x41)                   pista = "  <-- ES7210 (microfonos), como esperabamos";
      else if (dir >= 0x40 && dir <= 0x43)    pista = "  <-- podria ser el ES7210";
      else if (dir == 0x19)                   pista = "  <-- podria ser el ES8311";
      say("  responde: 0x%02X%s", dir, pista);
    }
  }

  if (encontrados == 0) {
    say("  NADA respondio.");
    say("  Revisa: el modulo de audio bien encajado, y VCC del modulo a 5V.");
  } else {
    say("  total: %d dispositivo(s)", encontrados);
  }
  say("--- fin del escaneo ---");
}

void setup() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.begin(115200);
#endif

  // Con USB CDC hay que esperar a que la PC abra el puerto, pero sin colgarse
  // para siempre si nadie lo abre.
  uint32_t limite = millis() + 4000;
  while (!Serial && millis() < limite) { delay(50); }
  delay(400);

  pinMode(PIN_AMPLI, OUTPUT);
  digitalWrite(PIN_AMPLI, LOW);   // amplificador apagado: silencio limpio
  pinMode(PIN_LUZ, OUTPUT);
  digitalWrite(PIN_LUZ, HIGH);    // luz encendida: se ve que arranco

  say("");
  say("===========================================");
  say(" Dante - paso 1: prueba de vida");
  say("===========================================");
  say("  chip .......... %s, %d nucleo(s), rev %d",
      ESP.getChipModel(), ESP.getChipCores(), ESP.getChipRevision());
  say("  cpu ........... %lu MHz", (unsigned long)getCpuFrequencyMhz());
  say("  flash ......... %lu bytes (%lu MB)",
      (unsigned long)ESP.getFlashChipSize(),
      (unsigned long)ESP.getFlashChipSize() / (1024UL * 1024UL));
  if (ESP.getPsramSize() == 0) {
    say("  PSRAM ......... 0   <-- MAL: pon PSRAM en 'OPI PSRAM' y sube otra vez");
  } else {
    say("  PSRAM ......... %lu bytes (%lu MB)  bien",
        (unsigned long)ESP.getPsramSize(),
        (unsigned long)ESP.getPsramSize() / (1024UL * 1024UL));
  }
  say("  RAM libre ..... %lu bytes", (unsigned long)ESP.getFreeHeap());
#if ARDUINO_USB_CDC_ON_BOOT
  say("  USB CDC ....... activado (bien)");
#else
  say("  USB CDC ....... APAGADO  <-- pon 'USB CDC On Boot' en Enabled");
#endif
  say("");
  say("  La luz de la pantalla deberia estar encendida ahora.");

  Wire.begin(PIN_SDA, PIN_SCL, I2C_HZ);
  escanear();

  say("");
  say("Repito el escaneo cada 5 segundos. Copia todo esto y mandalo.");
}

void loop() {
  delay(5000);
  escanear();
}
