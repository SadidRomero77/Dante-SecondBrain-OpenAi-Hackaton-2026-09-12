/* ===========================================================================
   Dante · paso 3 — el puente: el audio viaja al PC y vuelve
   ---------------------------------------------------------------------------
   El aparato deja de pensar. Solo hace tres cosas:
     - captura del microfono y manda al PC
     - reproduce lo que el PC le manda
     - avisa cuando se aprieta o se suelta el boton

   Implementa PROTOCOL.md: cabecera de 4 bytes por el puerto serie.
       byte 0  0xA5
       byte 1  tipo: 1=AUDIO  2=CONTROL  3=LOG
       bytes 2-3  largo de la carga, little endian

   El audio va MONO a 24 kHz: el bus I2S es estereo con los dos microfonos,
   se promedian antes de enviar y se duplica al reproducir.

   Configuracion de placa: ver HARDWARE.md
   =========================================================================== */

#include <Wire.h>
#include <driver/i2s_std.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

static const int PIN_I2C_SDA = 1,  PIN_I2C_SCL = 2;
static const int PIN_I2S_MCLK = 38, PIN_I2S_BCLK = 14, PIN_I2S_WS = 13;
static const int PIN_I2S_DIN = 12, PIN_I2S_DOUT = 45;
static const int PIN_PA_EN = 48,   PIN_LUZ = 42,       PIN_BOTON = 0;
static const int PIN_LCD_CS = 47,  PIN_LCD_DC = 39,    PIN_LCD_SCK = 41,
                 PIN_LCD_MOSI = 40;

static const uint8_t DIR_ES8311 = 0x18, DIR_ES7210 = 0x41;

static const uint32_t FS       = 24000;
static const uint8_t  GAN_MIC  = 10;    // 30 dB
static const int      VOL_DAC  = 92;

// 20 ms: 480 cuadros. Estereo en el bus, mono por el cable.
static const size_t CUADROS   = 480;
static const size_t BYTES_I2S = CUADROS * 2 * sizeof(int16_t);   // 1920
static const size_t BYTES_CBL = CUADROS * sizeof(int16_t);       // 960

static const uint8_t MAGIA = 0xA5;
static const uint8_t T_AUDIO = 1, T_CONTROL = 2, T_LOG = 3;

static i2s_chan_handle_t tx = nullptr, rx = nullptr;
static int16_t bufI2S[CUADROS * 2];
static int16_t bufCable[CUADROS];
static void saludar(bool a, bool b, bool c);

// ---------------------------------------------------------------- pantalla --
/* La cara de Dante: dos ojos.

   No es un perro dibujado. La carcasa va a ser el perro; la pantalla es solo
   la mirada, como en un reloj o un robot de juguete. Eso ademas envejece
   mejor: unos ojos bien animados se leen desde lejos y no dependen de que el
   dibujo sea bonito.

   El aparato no decide ningun estado. Los recibe del PC y los pinta. */
enum Estado {
  ARRANCANDO, LISTO, ESCUCHANDO, PENSANDO, HABLANDO,
  FELIZ, ATENCION, INFO, ERROR
};

static SPIClass spiLCD(HSPI);
static Adafruit_ST7789 tft(&spiLCD, PIN_LCD_CS, PIN_LCD_DC, -1);

static const int ANCHO = 320, ALTO = 240;
static const int OJO_IZQ = 104, OJO_DER = 216, OJO_Y = 118;

static uint16_t COLOR, FONDO;

static volatile Estado estado = ARRANCANDO;
static volatile int nivel_mic = 0;
static volatile bool redibujar = true;

// Texto que Dante muestra: recordatorios, confirmaciones, lo que sea.
static char txt_titulo[40] = "";
static char txt_cuerpo[160] = "";
static volatile uint32_t txt_hasta = 0;      // millis en que se quita
static volatile bool txt_nuevo = false;

static uint16_t color_de(Estado e) {
  switch (e) {
    case ESCUCHANDO: return tft.color565(60, 220, 255);   // cian brillante
    case PENSANDO:   return tft.color565(255, 190, 70);   // ambar
    case HABLANDO:   return tft.color565(120, 200, 255);
    case FELIZ:      return tft.color565(120, 255, 190);
    case ATENCION:   return tft.color565(255, 120, 150);
    case ERROR:      return tft.color565(255, 90, 80);
    default:         return tft.color565(70, 170, 235);   // reposo, mas apagado
  }
}

/* --- formas de ojo -------------------------------------------------------
   Cada una dibuja UN ojo centrado en (cx, cy). El parpadeo se logra pasando
   una altura menor: no hay animacion aparte, es el mismo dibujo aplastado. */

static void ojo_normal(int cx, int cy, int alto) {
  int w = 74, r = 20;
  if (alto < 2 * r) r = alto / 2;
  tft.fillRoundRect(cx - w / 2, cy - alto / 2, w, alto, r, COLOR);
}

static void ojo_anillo(int cx, int cy, int alto) {
  if (alto < 20) { ojo_normal(cx, cy, alto); return; }
  tft.fillCircle(cx, cy, 42, COLOR);
  tft.fillCircle(cx, cy, 26, FONDO);
}

static void ojo_arriba(int cx, int cy, int alto) {
  // Mirando hacia arriba: pensando.
  ojo_normal(cx, cy - 14, alto * 3 / 4);
}

static void ojo_feliz(int cx, int cy, int alto) {
  // Media luna abierta hacia arriba, que es como se ve una sonrisa con los ojos.
  if (alto < 20) { ojo_normal(cx, cy, alto); return; }
  tft.fillCircle(cx, cy + 6, 40, COLOR);
  tft.fillCircle(cx, cy + 34, 44, FONDO);
}

static void ojo_corazon(int cx, int cy, int alto) {
  if (alto < 20) { ojo_normal(cx, cy, alto); return; }
  int r = 20;
  tft.fillCircle(cx - r / 2 - 4, cy - 8, r, COLOR);
  tft.fillCircle(cx + r / 2 + 4, cy - 8, r, COLOR);
  tft.fillTriangle(cx - r - 8, cy - 2, cx + r + 8, cy - 2, cx, cy + 34, COLOR);
}

static void dibujar_ojos(Estado e, int alto) {
  void (*forma)(int, int, int) = ojo_normal;
  switch (e) {
    case ESCUCHANDO: forma = ojo_anillo;  break;
    case PENSANDO:   forma = ojo_arriba;  break;
    case FELIZ:      forma = ojo_feliz;   break;
    case ATENCION:   forma = ojo_corazon; break;
    default:         forma = ojo_normal;  break;
  }
  forma(OJO_IZQ, OJO_Y, alto);
  forma(OJO_DER, OJO_Y, alto);
}

/* Boca: solo una linea, y solo cuando habla. Da mucha vida por muy poco. */
static void dibujar_boca(Estado e, int abertura) {
  if (e != HABLANDO) return;
  int w = 54, y = 196;
  tft.fillRoundRect(ANCHO / 2 - w / 2, y - abertura / 2, w,
                    abertura < 6 ? 6 : abertura, 3, COLOR);
}

/* Barra del microfono: la prueba visible de que la voz esta entrando. */
static void dibujar_nivel(int n) {
  int ancho = 240 * n / 100;
  int x = (ANCHO - 240) / 2, y = 214;
  tft.fillRect(x, y, ancho, 10, COLOR);
  tft.fillRect(x + ancho, y, 240 - ancho, 10, tft.color565(22, 28, 34));
}

/* Modo texto: titulo arriba, mensaje partido en lineas. */
static void dibujar_texto() {
  tft.fillScreen(FONDO);
  tft.fillRect(0, 0, ANCHO, 6, COLOR);

  tft.setFont(nullptr);
  tft.setTextSize(2);
  tft.setTextColor(COLOR);
  int w = strlen(txt_titulo) * 12;
  tft.setCursor((ANCHO - w) / 2, 26);
  tft.print(txt_titulo);

  // Partir el cuerpo por palabras, 26 caracteres por linea.
  tft.setTextSize(2);
  tft.setTextColor(tft.color565(235, 240, 245));
  char buf[160];
  strncpy(buf, txt_cuerpo, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = 0;

  int y = 80;
  char *p = buf;
  while (*p && y < ALTO - 24) {
    int largo = strlen(p);
    int corte = largo > 26 ? 26 : largo;
    if (largo > 26) {
      int k = corte;
      while (k > 0 && p[k] != ' ') k--;
      if (k > 8) corte = k;
    }
    char guardado = p[corte];
    p[corte] = 0;
    int lw = strlen(p) * 12;
    tft.setCursor((ANCHO - lw) / 2, y);
    tft.print(p);
    p[corte] = guardado;
    p += corte;
    while (*p == ' ') p++;
    y += 28;
  }
}

/* Dibuja en el nucleo 0 para no robarle tiempo al audio, que corre en el 1. */
static void tarea_pantalla(void *) {
  Estado ultimo = (Estado)-1;
  int ultimo_nivel = -1, ultimo_alto = -1, ultima_boca = -1;
  uint32_t proximo_parpadeo = millis() + 3000;
  bool en_texto = false;

  for (;;) {
    uint32_t ahora = millis();

    // --- modo texto: manda sobre todo lo demas ---
    if (txt_nuevo) {
      txt_nuevo = false;
      en_texto = true;
      COLOR = color_de(estado == LISTO ? INFO : estado);
      if (estado == LISTO) COLOR = tft.color565(90, 190, 255);
      dibujar_texto();
    }
    if (en_texto) {
      if (ahora > txt_hasta) {
        en_texto = false;
        ultimo = (Estado)-1;          // forzar repintado de la cara
      }
      vTaskDelay(pdMS_TO_TICKS(60));
      continue;
    }

    Estado e = estado;
    COLOR = color_de(e);

    // --- parpadeo: solo en reposo, y a intervalos irregulares ---
    int alto = 62;
    if (e == LISTO || e == HABLANDO || e == FELIZ) {
      if (ahora > proximo_parpadeo) {
        uint32_t t = ahora - proximo_parpadeo;
        if (t < 90)       alto = 62 - (int)(t * 56 / 90);      // cerrando
        else if (t < 180) alto = 6 + (int)((t - 90) * 56 / 90); // abriendo
        else proximo_parpadeo = ahora + 2600 + (esp_random() % 3200);
      }
    }

    bool cambio = (e != ultimo) || (alto != ultimo_alto) || redibujar;
    if (redibujar || e != ultimo) {
      tft.fillScreen(FONDO);
      ultimo_nivel = -1;
      ultima_boca = -1;
      redibujar = false;
    }

    if (cambio) {
      // Borrar solo la banda de los ojos, no la pantalla entera: repintar
      // todo cada vuelta parpadearia feo y comeria SPI.
      tft.fillRect(0, OJO_Y - 56, ANCHO, 112, FONDO);
      dibujar_ojos(e, alto);
      ultimo = e;
      ultimo_alto = alto;
    }

    if (e == HABLANDO) {
      int abertura = 6 + (int)(esp_random() % 22);   // la boca se mueve sola
      if (abertura != ultima_boca) {
        tft.fillRect(ANCHO / 2 - 36, 178, 72, 40, FONDO);
        dibujar_boca(e, abertura);
        ultima_boca = abertura;
      }
    }

    if (e == ESCUCHANDO) {
      int n = nivel_mic;
      if (n != ultimo_nivel) {
        dibujar_nivel(n);
        ultimo_nivel = n;
      }
    }

    vTaskDelay(pdMS_TO_TICKS(e == HABLANDO ? 90 : 45));
  }
}

static void init_pantalla() {
  spiLCD.begin(PIN_LCD_SCK, -1, PIN_LCD_MOSI, PIN_LCD_CS);
  tft.init(240, 320);
  tft.setRotation(3);
  FONDO = tft.color565(8, 12, 16);
  COLOR = color_de(ARRANCANDO);
  tft.fillScreen(FONDO);
  digitalWrite(PIN_LUZ, HIGH);
  xTaskCreatePinnedToCore(tarea_pantalla, "pantalla", 6144, nullptr, 1, nullptr, 0);
}

static void mostrar_texto(const char *titulo, const char *cuerpo, uint32_t seg) {
  strncpy(txt_titulo, titulo, sizeof(txt_titulo) - 1);
  txt_titulo[sizeof(txt_titulo) - 1] = 0;
  strncpy(txt_cuerpo, cuerpo, sizeof(txt_cuerpo) - 1);
  txt_cuerpo[sizeof(txt_cuerpo) - 1] = 0;
  txt_hasta = millis() + seg * 1000;
  txt_nuevo = true;
}

// ------------------------------------------------------------ marco serie --
static void enviar(uint8_t tipo, const void *carga, uint16_t largo) {
  uint8_t cab[4] = {MAGIA, tipo, (uint8_t)(largo & 0xFF), (uint8_t)(largo >> 8)};
  Serial.write(cab, 4);
  if (largo) Serial.write((const uint8_t *)carga, largo);
}

static void log_pc(const char *txt) { enviar(T_LOG, txt, strlen(txt)); }

/* Arma marcos entrantes por partes.

   ANTES esperabamos a que estuvieran disponibles los 964 bytes completos de
   un marco de audio. El buffer de recepcion del USB CDC en Arduino es de 256
   bytes por defecto, asi que esa condicion NUNCA se cumplia y todo el audio
   que mandaba el PC se descartaba en silencio.

   Ahora se acumula lo que va llegando, byte a byte si hace falta, y el buffer
   se agranda al arrancar. Si se pierde la sincronia, se descarta hasta el
   proximo 0xA5 con una cabecera creible. */
static uint8_t marco[4096];
static uint16_t marco_largo = 0;      // cuanto de la carga ya llego
static uint16_t marco_espera = 0;     // cuanto mide la carga
static uint8_t  marco_tipo = 0;
static uint8_t  cab[4];
static int      cab_tengo = 0;

static uint8_t recibir(uint16_t *largo_out) {
  while (Serial.available()) {
    if (cab_tengo < 4) {
      int b = Serial.read();
      if (b < 0) return 0;
      if (cab_tengo == 0 && b != MAGIA) continue;      // resincronizar
      cab[cab_tengo++] = (uint8_t)b;
      if (cab_tengo == 4) {
        marco_tipo = cab[1];
        marco_espera = cab[2] | (cab[3] << 8);
        marco_largo = 0;
        if (marco_espera > sizeof(marco) || marco_tipo == 0 || marco_tipo > T_LOG) {
          cab_tengo = 0;                                // cabecera absurda
        } else if (marco_espera == 0) {
          cab_tengo = 0;
          *largo_out = 0;
          return marco_tipo;
        }
      }
      continue;
    }

    // cabecera lista: ir juntando la carga con lo que haya
    int hay = Serial.available();
    int falta = marco_espera - marco_largo;
    int tomar = hay < falta ? hay : falta;
    if (tomar > 0) {
      marco_largo += Serial.readBytes(marco + marco_largo, tomar);
    }
    if (marco_largo >= marco_espera) {
      cab_tengo = 0;
      *largo_out = marco_espera;
      return marco_tipo;
    }
    return 0;                                           // seguimos esperando
  }
  return 0;
}

// ------------------------------------------------------------------- I2C ---
static void esc(uint8_t d, uint8_t r, uint8_t v) {
  Wire.beginTransmission(d); Wire.write(r); Wire.write(v); Wire.endTransmission();
}
static uint8_t lee(uint8_t d, uint8_t r) {
  Wire.beginTransmission(d); Wire.write(r);
  if (Wire.endTransmission(false)) return 0;
  if (Wire.requestFrom((int)d, 1) != 1) return 0;
  return Wire.read();
}

// ---------------------------------------------------------------- codecs ---
// Coeficientes de la fila {12288000, 24000}. Ver HARDWARE.md.
static bool init_es8311(int vol) {
  esc(DIR_ES8311, 0x00, 0x1F); delay(20);
  esc(DIR_ES8311, 0x00, 0x00); esc(DIR_ES8311, 0x00, 0x80);
  esc(DIR_ES8311, 0x01, 0x3F);
  uint8_t r06 = lee(DIR_ES8311, 0x06); r06 &= ~(1 << 5); esc(DIR_ES8311, 0x06, r06);
  uint8_t r02 = lee(DIR_ES8311, 0x02); r02 &= 0x07; r02 |= (2 - 1) << 5; esc(DIR_ES8311, 0x02, r02);
  esc(DIR_ES8311, 0x03, 0x10);
  esc(DIR_ES8311, 0x04, 0x10);
  esc(DIR_ES8311, 0x05, 0x00);
  r06 = lee(DIR_ES8311, 0x06); r06 &= 0xE0; r06 |= 3; esc(DIR_ES8311, 0x06, r06);
  uint8_t r07 = lee(DIR_ES8311, 0x07); r07 &= 0xC0; esc(DIR_ES8311, 0x07, r07);
  esc(DIR_ES8311, 0x08, 0xFF);
  uint8_t r00 = lee(DIR_ES8311, 0x00); esc(DIR_ES8311, 0x00, r00 & 0xBF);
  esc(DIR_ES8311, 0x09, 0x0C); esc(DIR_ES8311, 0x0A, 0x0C);
  esc(DIR_ES8311, 0x0D, 0x01); esc(DIR_ES8311, 0x0E, 0x02);
  esc(DIR_ES8311, 0x12, 0x00); esc(DIR_ES8311, 0x13, 0x10);
  esc(DIR_ES8311, 0x1C, 0x6A); esc(DIR_ES8311, 0x37, 0x08);
  int v = constrain(vol, 0, 100);
  esc(DIR_ES8311, 0x32, v == 0 ? 0 : (v * 256 / 100) - 1);
  return lee(DIR_ES8311, 0x32) != 0;
}

static bool init_es7210(uint8_t g) {
  esc(DIR_ES7210, 0x00, 0xFF); esc(DIR_ES7210, 0x00, 0x32);
  esc(DIR_ES7210, 0x09, 0x30); esc(DIR_ES7210, 0x0A, 0x30);
  esc(DIR_ES7210, 0x23, 0x2A); esc(DIR_ES7210, 0x22, 0x0A);
  esc(DIR_ES7210, 0x21, 0x2A); esc(DIR_ES7210, 0x20, 0x0A);
  esc(DIR_ES7210, 0x11, 0x60); esc(DIR_ES7210, 0x12, 0x00);
  esc(DIR_ES7210, 0x40, 0xC3); esc(DIR_ES7210, 0x41, 0x70); esc(DIR_ES7210, 0x42, 0x70);
  for (uint8_t r = 0x43; r <= 0x46; r++) esc(DIR_ES7210, r, g | 0x10);
  for (uint8_t r = 0x47; r <= 0x4A; r++) esc(DIR_ES7210, r, 0x08);
  esc(DIR_ES7210, 0x07, 0x20);
  esc(DIR_ES7210, 0x02, 0x01 | (1 << 7));
  esc(DIR_ES7210, 0x04, 0x02); esc(DIR_ES7210, 0x05, 0x00);
  esc(DIR_ES7210, 0x06, 0x04);
  esc(DIR_ES7210, 0x4B, 0x0F); esc(DIR_ES7210, 0x4C, 0x0F);
  esc(DIR_ES7210, 0x00, 0x71); esc(DIR_ES7210, 0x00, 0x41);
  return lee(DIR_ES7210, 0x00) == 0x41;
}

static bool init_i2s() {
  i2s_chan_config_t ch = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  ch.dma_desc_num = 8; ch.dma_frame_num = 240; ch.auto_clear = true;
  if (i2s_new_channel(&ch, &tx, &rx) != ESP_OK) return false;

  i2s_std_config_t c = {};
  c.clk_cfg.sample_rate_hz = FS;
  c.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
  c.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_512;   // obligatorio: ver HARDWARE.md
  c.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
  c.gpio_cfg.mclk = (gpio_num_t)PIN_I2S_MCLK;
  c.gpio_cfg.bclk = (gpio_num_t)PIN_I2S_BCLK;
  c.gpio_cfg.ws   = (gpio_num_t)PIN_I2S_WS;
  c.gpio_cfg.dout = (gpio_num_t)PIN_I2S_DOUT;
  c.gpio_cfg.din  = (gpio_num_t)PIN_I2S_DIN;
  return i2s_channel_init_std_mode(tx, &c) == ESP_OK &&
         i2s_channel_init_std_mode(rx, &c) == ESP_OK &&
         i2s_channel_enable(tx) == ESP_OK &&
         i2s_channel_enable(rx) == ESP_OK;
}

// ----------------------------------------------------------------- setup ---
void setup() {
  // Sin esto el buffer de entrada es de 256 bytes y un marco de audio de
  // 964 no cabe nunca. Es lo que hacia que Dante no sonara.
  Serial.setRxBufferSize(16384);
  Serial.begin(115200);
  pinMode(PIN_LUZ, OUTPUT);   digitalWrite(PIN_LUZ, HIGH);
  pinMode(PIN_PA_EN, OUTPUT); digitalWrite(PIN_PA_EN, LOW);
  pinMode(PIN_BOTON, INPUT_PULLUP);

  init_pantalla();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000);
  bool a = init_es8311(VOL_DAC);
  bool b = init_es7210(GAN_MIC);
  bool c = init_i2s();
  digitalWrite(PIN_PA_EN, HIGH);
  estado = (a && b && c) ? LISTO : ERROR;

  delay(300);
  saludar(a, b, c);
}

static bool ok_dac, ok_adc, ok_i2s;

/* El aparato arranca antes de que el PC abra el puerto, asi que el saludo
   inicial se pierde casi siempre. El PC lo vuelve a pedir al conectarse. */
static void saludar(bool a, bool b, bool c) {
  ok_dac = a; ok_adc = b; ok_i2s = c;
  char hola[160];
  snprintf(hola, sizeof(hola),
           "{\"t\":\"hola\",\"fw\":\"0.1.0\",\"sr\":%lu,\"transporte\":\"usb\","
           "\"dac\":%s,\"adc\":%s,\"i2s\":%s}",
           (unsigned long)FS, a ? "true" : "false", b ? "true" : "false",
           c ? "true" : "false");
  enviar(T_CONTROL, hola, strlen(hola));
}

// ------------------------------------------------------------------ loop ---
void loop() {
  // 1. boton -> avisar cambios de estado
  static int previo = HIGH;
  int ahora = digitalRead(PIN_BOTON);
  if (ahora != previo) {
    previo = ahora;
    const char *m = (ahora == LOW) ? "{\"t\":\"boton\",\"v\":\"abajo\"}"
                                   : "{\"t\":\"boton\",\"v\":\"arriba\"}";
    enviar(T_CONTROL, m, strlen(m));
  }

  // 2. microfono -> PC. Promedia los dos canales: suena mas limpio que uno solo.
  size_t leidos = 0;
  if (i2s_channel_read(rx, bufI2S, BYTES_I2S, &leidos, 30) == ESP_OK && leidos) {
    size_t cuadros = leidos / (2 * sizeof(int16_t));
    for (size_t i = 0; i < cuadros; i++) {
      bufCable[i] = (int16_t)(((int32_t)bufI2S[i * 2] + bufI2S[i * 2 + 1]) / 2);
    }
    if (estado == ESCUCHANDO) {
      int32_t pico = 0;
      for (size_t i = 0; i < cuadros; i += 4) {   // uno de cada cuatro alcanza
        int32_t v = abs(bufCable[i]);
        if (v > pico) pico = v;
      }
      int n = (int)(pico * 100L / 12000L);        // 12000 ya es voz fuerte
      nivel_mic = n > 100 ? 100 : n;
    }
    enviar(T_AUDIO, bufCable, cuadros * sizeof(int16_t));
  }

  // 3. PC -> parlante. Varios marcos por vuelta: el PC manda uno cada 18 ms
  //    y esta vuelta puede tardar mas, asi que hay que poder alcanzarlo.
  for (int k = 0; k < 8; k++) {
    uint16_t largo = 0;
    uint8_t tipo = recibir(&largo);
    if (!tipo) break;

    if (tipo == T_AUDIO && largo) {
      const int16_t *mono = (const int16_t *)marco;
      size_t cuadros = largo / sizeof(int16_t);
      if (cuadros > CUADROS) cuadros = CUADROS;
      for (size_t i = 0; i < cuadros; i++) {
        bufI2S[i * 2] = mono[i];
        bufI2S[i * 2 + 1] = mono[i];
      }
      size_t esc_n = 0;
      i2s_channel_write(tx, bufI2S, cuadros * 2 * sizeof(int16_t), &esc_n, 120);

    } else if (tipo == T_CONTROL && largo) {
      marco[largo] = 0;
      char *em = strstr((char *)marco, "\"emocion\"");
      if (em) {
        if (strstr(em, "escuchando"))      estado = ESCUCHANDO;
        else if (strstr(em, "pensando"))   estado = PENSANDO;
        else if (strstr(em, "hablando"))   estado = HABLANDO;
        else if (strstr(em, "feliz"))      estado = FELIZ;
        else if (strstr(em, "atencion"))   estado = ATENCION;
        else                               estado = LISTO;
      } else if (strstr((char *)marco, "\"texto\"")) {
        // {"t":"texto","titulo":"...","cuerpo":"...","seg":8}
        char titulo[40] = "", cuerpo[160] = "";
        int seg = 8;
        char *q;
        if ((q = strstr((char *)marco, "\"titulo\":\""))) {
          q += 10; int i = 0;
          while (*q && *q != '"' && i < 38) titulo[i++] = *q++;
          titulo[i] = 0;
        }
        if ((q = strstr((char *)marco, "\"cuerpo\":\""))) {
          q += 10; int i = 0;
          while (*q && *q != '"' && i < 158) cuerpo[i++] = *q++;
          cuerpo[i] = 0;
        }
        if ((q = strstr((char *)marco, "\"seg\":"))) seg = atoi(q + 6);
        mostrar_texto(titulo, cuerpo, seg > 0 ? seg : 8);

      } else if (strstr((char *)marco, "\"hola?\"")) {
        saludar(ok_dac, ok_adc, ok_i2s);
      } else if (strstr((char *)marco, "\"parar\"")) {
        i2s_channel_disable(tx);
        i2s_channel_enable(tx);
      }
    }
  }
}
