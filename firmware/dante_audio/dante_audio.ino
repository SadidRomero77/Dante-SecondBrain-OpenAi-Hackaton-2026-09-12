/* ===========================================================================
   Dante · paso 2 — audio de punta a punta en la placa
   ---------------------------------------------------------------------------
   Prueba las dos rutas por separado, sin realimentacion:

     1. Tono de 440 Hz al arrancar  -> prueba DAC (ES8311) + amplificador
     2. Ciclo de grabar 2 s y reproducir 2 s -> prueba micros (ES7210) + DAC

   Un eco continuo se realimenta y chilla. Grabar y reproducir por turnos
   evita eso, y ademas es como va a funcionar de verdad: se habla apretando
   el boton, no todo el tiempo.

   Imprime el nivel del microfono en cada grabacion, asi se puede diagnosticar
   la entrada aunque el parlante no suene.

   ---------------------------------------------------------------------------
   POR QUE EL MCLK VA A 12.288 MHz Y NO A 6.144

   La tabla de coeficientes del ES7210 no tiene entrada para 24 kHz con MCLK a
   256xfs; la mas baja que soporta a esa frecuencia es 512xfs. El ES8311 admite
   las dos. Asi que los dos van a 512xfs = 12.288 MHz, que es lo unico que
   funciona para ambos a la vez.

   Registros sacados de los drivers oficiales de Espressif (esp-bsp), con los
   coeficientes de las filas {12288000, 24000} de cada tabla.

   Configuracion de placa: ver HARDWARE.md
   =========================================================================== */

#include <Wire.h>
#include <driver/i2s_std.h>
#include <math.h>

// ---------------------------------------------------------------- pines ----
static const int PIN_I2C_SDA = 1;
static const int PIN_I2C_SCL = 2;
static const int PIN_I2S_MCLK = 38;
static const int PIN_I2S_BCLK = 14;
static const int PIN_I2S_WS   = 13;
static const int PIN_I2S_DIN  = 12;   // del ES7210 hacia el ESP32
static const int PIN_I2S_DOUT = 45;   // del ESP32 hacia el ES8311
static const int PIN_PA_EN    = 48;   // habilita el amplificador
static const int PIN_LUZ      = 42;

static const uint8_t DIR_ES8311 = 0x18;
static const uint8_t DIR_ES7210 = 0x41;

// ---------------------------------------------------------------- audio ----
/* --- perillas de nivel ---------------------------------------------------
   GANANCIA_MIC : ganancia analogica del ES7210. 0..14, donde 14 = 37.5 dB.
   VOLUMEN_DAC  : volumen del ES8311, 0..100.
   GANANCIA_SW  : multiplicador digital antes de reproducir. Se satura en vez
                  de dar la vuelta, para que un exceso suene fuerte y no roto.
   El nivel del microfono importa mas que el del parlante: es lo que se le
   manda a OpenAI. El parlante solo lo escuchamos nosotros. */
static const uint8_t GANANCIA_MIC = 12;     // 34.5 dB. La "saturacion" que medi
                                            //  antes era la senal de referencia
                                            //  del parlante, no el microfono.
static const int     VOLUMEN_DAC  = 78;     // 100 quedaba demasiado fuerte
static const float   GANANCIA_SW  = 1.5f;   // solo para escuchar la prueba;
                                            //  a OpenAI le va el audio crudo

static const uint32_t FS         = 24000;   // igual que la Realtime API
static const int      CANALES    = 2;       // el bus I2S va en estereo
static const int      SEG_GRABAR = 2;
static const size_t   MUESTRAS   = FS * SEG_GRABAR * CANALES;
static const size_t   BYTES_BUF  = MUESTRAS * sizeof(int16_t);

static i2s_chan_handle_t tx = nullptr;
static i2s_chan_handle_t rx = nullptr;
static int16_t *buffer = nullptr;

// ------------------------------------------------------------ I2C helpers --
static bool escribir(uint8_t dir, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

static uint8_t leer(uint8_t dir, uint8_t reg) {
  Wire.beginTransmission(dir);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom((int)dir, 1) != 1) return 0;
  return Wire.read();
}

// -------------------------------------------------------------- ES8311 -----
/* Salida al parlante. Esclavo I2S, 16 bits, MCLK por su propio pin.
   Coeficientes de la fila {12288000, 24000}:
     pre_div=2  pre_multi=0  adc_div=1  dac_div=1  fs_mode=0
     lrck_h=0x00  lrck_l=0xff  bclk_div=4  adc_osr=0x10  dac_osr=0x10  */
static bool init_es8311(int volumen_pct) {
  escribir(DIR_ES8311, 0x00, 0x1F);          // reset
  delay(20);
  escribir(DIR_ES8311, 0x00, 0x00);
  escribir(DIR_ES8311, 0x00, 0x80);          // encender

  escribir(DIR_ES8311, 0x01, 0x3F);          // todos los relojes, MCLK del pin

  uint8_t r06 = leer(DIR_ES8311, 0x06);
  r06 &= ~(1 << 5);                          // SCLK sin invertir
  escribir(DIR_ES8311, 0x06, r06);

  uint8_t r02 = leer(DIR_ES8311, 0x02);
  r02 &= 0x07;
  r02 |= (2 - 1) << 5;                       // pre_div = 2
  r02 |= 0 << 3;                             // pre_multi = 0
  escribir(DIR_ES8311, 0x02, r02);

  escribir(DIR_ES8311, 0x03, (0 << 6) | 0x10);   // fs_mode | adc_osr
  escribir(DIR_ES8311, 0x04, 0x10);              // dac_osr
  escribir(DIR_ES8311, 0x05, ((1 - 1) << 4) | (1 - 1));  // adc_div | dac_div

  r06 = leer(DIR_ES8311, 0x06);
  r06 &= 0xE0;
  r06 |= (4 - 1);                            // bclk_div = 4
  escribir(DIR_ES8311, 0x06, r06);

  uint8_t r07 = leer(DIR_ES8311, 0x07);
  r07 &= 0xC0;
  r07 |= 0x00;                               // lrck_h
  escribir(DIR_ES8311, 0x07, r07);
  escribir(DIR_ES8311, 0x08, 0xFF);          // lrck_l

  uint8_t r00 = leer(DIR_ES8311, 0x00);
  escribir(DIR_ES8311, 0x00, r00 & 0xBF);    // modo esclavo

  escribir(DIR_ES8311, 0x09, (3 << 2));      // entrada SDP a 16 bits
  escribir(DIR_ES8311, 0x0A, (3 << 2));      // salida SDP a 16 bits

  escribir(DIR_ES8311, 0x0D, 0x01);          // encender analogico
  escribir(DIR_ES8311, 0x0E, 0x02);          // PGA + modulador del ADC
  escribir(DIR_ES8311, 0x12, 0x00);          // encender DAC
  escribir(DIR_ES8311, 0x13, 0x10);          // salida al driver
  escribir(DIR_ES8311, 0x1C, 0x6A);          // ecualizador ADC en bypass
  escribir(DIR_ES8311, 0x37, 0x08);          // ecualizador DAC en bypass

  int v = constrain(volumen_pct, 0, 100);
  escribir(DIR_ES8311, 0x32, v == 0 ? 0 : (v * 256 / 100) - 1);

  return leer(DIR_ES8311, 0x32) != 0;
}

// -------------------------------------------------------------- ES7210 -----
/* Entrada de los microfonos. Coeficientes de la fila {12288000, 24000}:
     adc_div=0x01  dll=0x01  doubler=0x00  osr=0x20  lrck_h=0x02  lrck_l=0x00 */
static bool init_es7210(uint8_t ganancia) {
  escribir(DIR_ES7210, 0x00, 0xFF);          // reset
  escribir(DIR_ES7210, 0x00, 0x32);

  escribir(DIR_ES7210, 0x09, 0x30);          // tiempos de arranque
  escribir(DIR_ES7210, 0x0A, 0x30);

  escribir(DIR_ES7210, 0x23, 0x2A);          // filtro pasa-altos ADC1-2
  escribir(DIR_ES7210, 0x22, 0x0A);
  escribir(DIR_ES7210, 0x21, 0x2A);          // filtro pasa-altos ADC3-4
  escribir(DIR_ES7210, 0x20, 0x0A);

  escribir(DIR_ES7210, 0x11, 0x60);          // I2S estandar, 16 bits
  escribir(DIR_ES7210, 0x12, 0x00);          // sin TDM

  escribir(DIR_ES7210, 0x40, 0xC3);          // alimentacion analogica y VMID
  escribir(DIR_ES7210, 0x41, 0x70);          // bias de microfonos a 2.87 V
  escribir(DIR_ES7210, 0x42, 0x70);

  for (uint8_t r = 0x43; r <= 0x46; r++) {   // ganancia de los 4 canales
    escribir(DIR_ES7210, r, ganancia | 0x10);
  }
  for (uint8_t r = 0x47; r <= 0x4A; r++) {   // encender microfonos
    escribir(DIR_ES7210, r, 0x08);
  }

  escribir(DIR_ES7210, 0x07, 0x20);          // osr
  escribir(DIR_ES7210, 0x02, 0x01 | (0 << 6) | (1 << 7));  // adc_div | doubler | dll
  escribir(DIR_ES7210, 0x04, 0x02);          // lrck alto
  escribir(DIR_ES7210, 0x05, 0x00);          // lrck bajo

  escribir(DIR_ES7210, 0x06, 0x04);          // apagar DLL
  escribir(DIR_ES7210, 0x4B, 0x0F);          // encender bias, ADC y PGA
  escribir(DIR_ES7210, 0x4C, 0x0F);

  escribir(DIR_ES7210, 0x00, 0x71);          // habilitar
  escribir(DIR_ES7210, 0x00, 0x41);

  return leer(DIR_ES7210, 0x00) == 0x41;
}

// ----------------------------------------------------------------- I2S -----
static bool init_i2s() {
  i2s_chan_config_t ch = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  ch.dma_desc_num = 6;
  ch.dma_frame_num = 240;               // 10 ms por descriptor
  ch.auto_clear = true;
  if (i2s_new_channel(&ch, &tx, &rx) != ESP_OK) return false;

  i2s_std_config_t cfg = {};
  cfg.clk_cfg.sample_rate_hz = FS;
  cfg.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
  // 512xfs: es el unico multiplo que sirve para los dos codecs a 24 kHz.
  cfg.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_512;

  cfg.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);

  cfg.gpio_cfg.mclk = (gpio_num_t)PIN_I2S_MCLK;
  cfg.gpio_cfg.bclk = (gpio_num_t)PIN_I2S_BCLK;
  cfg.gpio_cfg.ws   = (gpio_num_t)PIN_I2S_WS;
  cfg.gpio_cfg.dout = (gpio_num_t)PIN_I2S_DOUT;
  cfg.gpio_cfg.din  = (gpio_num_t)PIN_I2S_DIN;
  cfg.gpio_cfg.invert_flags.mclk_inv = false;
  cfg.gpio_cfg.invert_flags.bclk_inv = false;
  cfg.gpio_cfg.invert_flags.ws_inv   = false;

  if (i2s_channel_init_std_mode(tx, &cfg) != ESP_OK) return false;
  if (i2s_channel_init_std_mode(rx, &cfg) != ESP_OK) return false;
  if (i2s_channel_enable(tx) != ESP_OK) return false;
  if (i2s_channel_enable(rx) != ESP_OK) return false;
  return true;
}

// -------------------------------------------------------------- pruebas ----
static void tono(int hz, int ms) {
  const int n = 480;                    // 20 ms por bloque
  int16_t bloque[n * CANALES];
  static float fase = 0.0f;
  const float paso = 2.0f * PI * hz / FS;
  size_t escrito;

  for (int b = 0; b < ms / 20; b++) {
    for (int i = 0; i < n; i++) {
      int16_t v = (int16_t)(sinf(fase) * 8000);
      bloque[i * 2] = v;
      bloque[i * 2 + 1] = v;
      fase += paso;
      if (fase > 2.0f * PI) fase -= 2.0f * PI;
    }
    i2s_channel_write(tx, bloque, sizeof(bloque), &escrito, 200);
  }
}

/* El ES7210 entrega dos canales, pero en esta placa NO son dos microfonos.
   El config.h de LAFVIN trae AUDIO_INPUT_REFERENCE en true: el canal derecho
   lleva la senal de referencia del parlante, la que usaria el cancelador de
   eco. Reproducir los dos mezclados suena a ruido. Nos quedamos con el
   izquierdo y lo duplicamos. */
static void solo_microfono(int16_t *d, size_t muestras) {
  for (size_t i = 0; i + 1 < muestras; i += 2) d[i + 1] = d[i];
}

/* Cuenta silencios sospechosamente largos en el canal del microfono.
   Un hueco de mas de 1 ms de ceros seguidos no es voz baja: es la DMA
   quedandose sin datos, que es exactamente lo que se oye entrecortado. */
static int huecos(const int16_t *d, size_t muestras) {
  int cortes = 0, seguidos = 0;
  for (size_t i = 0; i < muestras; i += 2) {
    if (d[i] == 0) {
      if (++seguidos == 24) cortes++;   // 24 muestras = 1 ms a 24 kHz
    } else {
      seguidos = 0;
    }
  }
  return cortes;
}

/* Multiplica con saturacion: al pasarse se queda en el tope en vez de dar la
   vuelta y convertirse en un chasquido. */
static void amplificar(int16_t *d, size_t muestras, float g) {
  for (size_t i = 0; i < muestras; i++) {
    float v = d[i] * g;
    if (v > 32767.0f) v = 32767.0f;
    else if (v < -32768.0f) v = -32768.0f;
    d[i] = (int16_t)v;
  }
}

static void nivel(const int16_t *d, size_t muestras, int32_t *pico, double *rms) {
  int64_t suma = 0;
  int32_t p = 0;
  for (size_t i = 0; i < muestras; i += 2) {   // solo canal izquierdo
    int32_t v = d[i];
    if (abs(v) > p) p = abs(v);
    suma += (int64_t)v * v;
  }
  *pico = p;
  *rms = sqrt((double)suma / (muestras / 2));
}

// ----------------------------------------------------------------- setup ---
void setup() {
  Serial.begin(115200);
  delay(2500);
  Serial.println();
  Serial.println("=========================================");
  Serial.println(" Dante - paso 2: audio en la placa");
  Serial.println("=========================================");

  pinMode(PIN_LUZ, OUTPUT);
  digitalWrite(PIN_LUZ, HIGH);
  pinMode(PIN_PA_EN, OUTPUT);
  digitalWrite(PIN_PA_EN, LOW);          // amplificador apagado por ahora

  buffer = (int16_t *)ps_malloc(BYTES_BUF);
  if (!buffer) {
    Serial.println("FALLO: no hay PSRAM para el buffer");
    while (true) delay(1000);
  }
  Serial.printf("  buffer de %u bytes en PSRAM (%d s)\n",
                (unsigned)BYTES_BUF, SEG_GRABAR);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000);

  Serial.print("  ES8311 (parlante) ... ");
  Serial.println(init_es8311(VOLUMEN_DAC) ? "OK" : "FALLO");

  Serial.print("  ES7210 (micros) ..... ");
  Serial.println(init_es7210(GANANCIA_MIC) ? "OK" : "FALLO");

  Serial.print("  I2S 24 kHz duplex ... ");
  Serial.println(init_i2s() ? "OK (MCLK 12.288 MHz)" : "FALLO");

  digitalWrite(PIN_PA_EN, HIGH);         // encender amplificador
  delay(50);

  Serial.println();
  Serial.println("  >>> suena un tono de 440 Hz durante 1 segundo <<<");
  tono(440, 1000);
  Serial.println("  (si no lo escuchaste, el problema esta en la salida)");
  Serial.println();
  Serial.println("  >>> ahora 2 s de tono DESDE EL BUFFER GRANDE <<<");
  Serial.println("      misma ruta que la reproduccion de tu voz.");
  {
    float fase = 0.0f;
    const float paso = 2.0f * PI * 440.0f / FS;
    for (size_t i = 0; i < MUESTRAS; i += 2) {
      int16_t v = (int16_t)(sinf(fase) * 8000);
      buffer[i] = v; buffer[i + 1] = v;
      fase += paso;
      if (fase > 2.0f * PI) fase -= 2.0f * PI;
    }
    size_t esc;
    i2s_channel_write(tx, buffer, BYTES_BUF, &esc, 5000);
  }
  Serial.println("      Si ESE tono sono limpio, la salida esta bien y el");
  Serial.println("      problema esta en la grabacion. Si sono entrecortado,");
  Serial.println("      el problema es la salida.");
  Serial.println();
  Serial.println("Ahora: graba 2 s, reproduce 2 s, en bucle. HABLA CERCA.");
}

// ------------------------------------------------------------------ loop ---
void loop() {
  size_t leidos = 0, escritos = 0;

  static bool primera = true;

  Serial.println();
  Serial.println(">> GRABANDO 2 s ... habla ahora");
  digitalWrite(PIN_LUZ, LOW);            // luz apagada = grabando
  i2s_channel_read(rx, buffer, BYTES_BUF, &leidos, 5000);
  digitalWrite(PIN_LUZ, HIGH);

  size_t n = leidos / sizeof(int16_t);

  if (primera) {
    primera = false;
    Serial.println("   (primera vuelta descartada: transitorio del ES7210)");
    delay(300);
    return;
  }

  int cortes = huecos(buffer, n);
  solo_microfono(buffer, n);

  int32_t pico; double rms;
  nivel(buffer, n, &pico, &rms);
  Serial.printf("   captado   pico %5ld  rms %5.0f   %s\n", (long)pico, rms,
                pico < 50    ? "<-- el microfono no capta nada"
                : pico < 800 ? "<-- muy bajo, sube GANANCIA_MIC"
                : pico > 30000 ? "<-- saturado, baja GANANCIA_MIC"
                : "bien");

  Serial.printf("   huecos    %d  %s\n", cortes,
                cortes == 0 ? "sin cortes de DMA"
                            : "<-- la DMA se queda sin datos: eso es lo entrecortado");

  amplificar(buffer, n, GANANCIA_SW);
  int32_t pico2; double rms2;
  nivel(buffer, n, &pico2, &rms2);
  Serial.printf("   x%.1f       pico %5ld  rms %5.0f   %s\n",
                GANANCIA_SW, (long)pico2, rms2,
                pico2 >= 32767 ? "<-- recortando, baja GANANCIA_SW" : "sin recorte");

  Serial.println(">> REPRODUCIENDO");
  i2s_channel_write(tx, buffer, leidos, &escritos, 5000);

  delay(1200);
}
