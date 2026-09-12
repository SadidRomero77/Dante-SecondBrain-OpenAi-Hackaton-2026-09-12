/* ===========================================================================
   Dante · prueba de los modulos nuevos
   ---------------------------------------------------------------------------
   Verifica de una sola pasada las tres cosas que acabas de cablear:
     1. La pantalla, dibujando los ojos.
     2. El amplificador, tocando un tono.
     3. El microfono, midiendo el nivel y reproduciendolo.

   Lo que ya NO esta, comparado con el codec viejo:
     - Nada de I2C: estos modulos no se configuran, se conectan.
     - Nada de MCLK: generan su reloj del BCLK. Se acabo la tabla de
       coeficientes y el reloj a 512 veces la frecuencia de muestreo.

   EL DETALLE QUE IMPORTA: el INMP441 entrega 24 bits dentro de una ranura de
   32, no 16. Si se lee como 16 bits sale basura. Por eso el bus va a 32 bits y
   la conversion se hace por software: al microfono se le corren los bits a la
   derecha, y al amplificador se los corremos a la izquierda.
   =========================================================================== */

#include <driver/i2s_std.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <math.h>

// --- audio ---
static const int PIN_BCLK = 14;   // a SCK del microfono y BCLK del amplificador
static const int PIN_WS   = 13;   // a WS del microfono y LRC del amplificador
static const int PIN_DIN  = 12;   // SD del microfono -> entra al ESP32
static const int PIN_DOUT = 45;   // sale del ESP32 -> DIN del amplificador
static const int PIN_SD_AMP = 48; // SD del amplificador: en alto = encendido

// --- pantalla ---
static const int PIN_LCD_CS = 47, PIN_LCD_DC = 39,
                 PIN_LCD_SCK = 41, PIN_LCD_MOSI = 40;

static const uint32_t FS = 24000;
static const size_t CUADROS = 480;             // 20 ms

static i2s_chan_handle_t tx = nullptr, rx = nullptr;
static SPIClass spiLCD(HSPI);
static Adafruit_ST7789 tft(&spiLCD, PIN_LCD_CS, PIN_LCD_DC, -1);

// El bus va en 32 bits por el microfono; el amplificador lo acepta igual.
static int32_t buf32[CUADROS * 2];

static bool init_i2s() {
  i2s_chan_config_t ch = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  ch.dma_desc_num = 8;
  ch.dma_frame_num = 240;
  ch.auto_clear = true;
  if (i2s_new_channel(&ch, &tx, &rx) != ESP_OK) return false;

  i2s_std_config_t c = {};
  c.clk_cfg.sample_rate_hz = FS;
  c.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
  // Ni el INMP441 ni el MAX98357A usan MCLK.
  c.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
  c.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO);
  c.gpio_cfg.mclk = I2S_GPIO_UNUSED;
  c.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
  c.gpio_cfg.ws   = (gpio_num_t)PIN_WS;
  c.gpio_cfg.dout = (gpio_num_t)PIN_DOUT;
  c.gpio_cfg.din  = (gpio_num_t)PIN_DIN;

  return i2s_channel_init_std_mode(tx, &c) == ESP_OK &&
         i2s_channel_init_std_mode(rx, &c) == ESP_OK &&
         i2s_channel_enable(tx) == ESP_OK &&
         i2s_channel_enable(rx) == ESP_OK;
}

static void ojos(uint16_t color, int alto) {
  tft.fillRect(0, 60, 320, 130, ST77XX_BLACK);
  int w = 74, r = alto < 40 ? alto / 2 : 20;
  tft.fillRoundRect(104 - w/2, 118 - alto/2, w, alto, r, color);
  tft.fillRoundRect(216 - w/2, 118 - alto/2, w, alto, r, color);
}

static void titulo(const char *t, uint16_t color) {
  tft.fillRect(0, 0, 320, 40, ST77XX_BLACK);
  tft.setTextSize(2);
  tft.setTextColor(color);
  tft.setCursor((320 - (int)strlen(t) * 12) / 2, 12);
  tft.print(t);
}

static void tono(int hz, int ms) {
  static float fase = 0;
  const float paso = 2.0f * PI * hz / FS;
  size_t esc;
  for (int b = 0; b < ms / 20; b++) {
    for (size_t i = 0; i < CUADROS; i++) {
      int16_t v = (int16_t)(sinf(fase) * 9000);
      // 16 bits corridos a la izquierda para llenar la ranura de 32.
      buf32[i*2] = buf32[i*2+1] = ((int32_t)v) << 16;
      fase += paso;
      if (fase > 2*PI) fase -= 2*PI;
    }
    i2s_channel_write(tx, buf32, sizeof(buf32), &esc, 200);
  }
}

void setup() {
  Serial.begin(115200);
  delay(2200);

  pinMode(PIN_SD_AMP, OUTPUT);
  digitalWrite(PIN_SD_AMP, LOW);          // amplificador callado al arrancar

  spiLCD.begin(PIN_LCD_SCK, -1, PIN_LCD_MOSI, PIN_LCD_CS);
  tft.init(240, 320);
  tft.setRotation(3);
  tft.fillScreen(ST77XX_BLACK);
  titulo("PANTALLA OK", tft.color565(80, 200, 255));
  ojos(tft.color565(80, 200, 255), 62);

  Serial.println();
  Serial.println("=== Dante · prueba de los modulos nuevos ===");
  Serial.println("  pantalla ....... si ves dos ojos, funciona");

  Serial.print("  I2S 24 kHz ..... ");
  bool ok = init_i2s();
  Serial.println(ok ? "OK (32 bits, sin MCLK)" : "FALLO");
  if (!ok) {
    titulo("I2S FALLO", ST77XX_RED);
    while (true) delay(1000);
  }

  digitalWrite(PIN_SD_AMP, HIGH);         // encender amplificador
  delay(60);
  titulo("SUENA UN TONO", tft.color565(255, 190, 70));
  ojos(tft.color565(255, 190, 70), 62);
  Serial.println("  >>> tono de 440 Hz por 1 segundo <<<");
  tono(440, 1000);
  Serial.println("  (si no lo oiste, revisa el amplificador y el parlante)");

  Serial.println();
  Serial.println("Ahora: graba 2 s y los reproduce, en bucle. HABLA CERCA.");
}

void loop() {
  static int16_t voz[FS * 2];             // 2 s de audio mono
  size_t n = 0, leidos = 0, esc = 0;
  int32_t pico = 0;

  titulo("TE ESCUCHO", tft.color565(80, 230, 140));
  ojos(tft.color565(80, 230, 140), 62);
  Serial.println();
  Serial.println(">> GRABANDO 2 s ... habla ahora");

  while (n < FS * 2) {
    if (i2s_channel_read(rx, buf32, sizeof(buf32), &leidos, 300) != ESP_OK) break;
    size_t c = leidos / (2 * sizeof(int32_t));
    for (size_t i = 0; i < c && n < FS * 2; i++) {
      // El microfono manda por el canal izquierdo (su L/R esta a tierra).
      // 24 bits utiles arriba de la ranura de 32: los bajamos a 16.
      int16_t v = (int16_t)(buf32[i*2] >> 14);
      voz[n++] = v;
      if (abs(v) > pico) pico = abs(v);
    }
  }

  Serial.printf("   pico %ld   %s\n", (long)pico,
                pico < 100 ? "<-- el microfono no capta nada"
                : pico > 30000 ? "<-- saturado" : "bien");

  titulo("HABLANDO", tft.color565(255, 140, 80));
  ojos(tft.color565(255, 140, 80), 62);
  Serial.println(">> REPRODUCIENDO");
  for (size_t i = 0; i < FS * 2; i += CUADROS) {
    size_t c = (i + CUADROS <= FS * 2) ? CUADROS : (FS * 2 - i);
    for (size_t k = 0; k < c; k++)
      buf32[k*2] = buf32[k*2+1] = ((int32_t)voz[i+k]) << 16;
    i2s_channel_write(tx, buf32, c * 2 * sizeof(int32_t), &esc, 400);
  }

  delay(900);
}
