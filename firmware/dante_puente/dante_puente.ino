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

static const int PIN_I2C_SDA = 1,  PIN_I2C_SCL = 2;
static const int PIN_I2S_MCLK = 38, PIN_I2S_BCLK = 14, PIN_I2S_WS = 13;
static const int PIN_I2S_DIN = 12, PIN_I2S_DOUT = 45;
static const int PIN_PA_EN = 48,   PIN_LUZ = 42,       PIN_BOTON = 0;

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
static void saludar(bool a, bool b, bool c);
static int16_t bufI2S[CUADROS * 2];
static int16_t bufCable[CUADROS];

// ------------------------------------------------------------ marco serie --
static void enviar(uint8_t tipo, const void *carga, uint16_t largo) {
  uint8_t cab[4] = {MAGIA, tipo, (uint8_t)(largo & 0xFF), (uint8_t)(largo >> 8)};
  Serial.write(cab, 4);
  if (largo) Serial.write((const uint8_t *)carga, largo);
}

static void log_pc(const char *txt) { enviar(T_LOG, txt, strlen(txt)); }

/* Lee un marco entrante sin bloquear. Devuelve el tipo, o 0 si no hay nada
   completo todavia. Si se pierde la sincronia, descarta hasta el proximo
   0xA5 con un largo creible. */
static uint8_t recibir(uint8_t *destino, uint16_t tope, uint16_t *largo_out) {
  static uint8_t cab[4];
  static int tengo = 0;

  while (Serial.available()) {
    if (tengo < 4) {
      int b = Serial.read();
      if (b < 0) return 0;
      if (tengo == 0 && b != MAGIA) continue;           // resincronizar
      cab[tengo++] = (uint8_t)b;
      if (tengo == 4) {
        uint16_t l = cab[2] | (cab[3] << 8);
        if (l > 4096 || cab[1] > T_LOG) { tengo = 0; }  // cabecera absurda
      }
      continue;
    }
    uint16_t largo = cab[2] | (cab[3] << 8);
    if (largo > tope) { tengo = 0; return 0; }
    if ((uint16_t)Serial.available() < largo) return 0;  // todavia no llego
    Serial.readBytes(destino, largo);
    tengo = 0;
    *largo_out = largo;
    return cab[1];
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
  Serial.begin(115200);
  pinMode(PIN_LUZ, OUTPUT);   digitalWrite(PIN_LUZ, HIGH);
  pinMode(PIN_PA_EN, OUTPUT); digitalWrite(PIN_PA_EN, LOW);
  pinMode(PIN_BOTON, INPUT_PULLUP);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000);
  bool a = init_es8311(VOL_DAC);
  bool b = init_es7210(GAN_MIC);
  bool c = init_i2s();
  digitalWrite(PIN_PA_EN, HIGH);

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
    digitalWrite(PIN_LUZ, ahora == LOW ? LOW : HIGH);
  }

  // 2. microfono -> PC. Promedia los dos canales: suena mas limpio que uno solo.
  size_t leidos = 0;
  if (i2s_channel_read(rx, bufI2S, BYTES_I2S, &leidos, 30) == ESP_OK && leidos) {
    size_t cuadros = leidos / (2 * sizeof(int16_t));
    for (size_t i = 0; i < cuadros; i++) {
      bufCable[i] = (int16_t)(((int32_t)bufI2S[i * 2] + bufI2S[i * 2 + 1]) / 2);
    }
    enviar(T_AUDIO, bufCable, cuadros * sizeof(int16_t));
  }

  // 3. PC -> parlante
  static uint8_t entrada[4096];
  uint16_t largo = 0;
  uint8_t tipo = recibir(entrada, sizeof(entrada), &largo);
  if (tipo == T_AUDIO && largo) {
    const int16_t *mono = (const int16_t *)entrada;
    size_t cuadros = largo / sizeof(int16_t);
    for (size_t i = 0; i < cuadros && i < CUADROS; i++) {
      bufI2S[i * 2] = mono[i];
      bufI2S[i * 2 + 1] = mono[i];
    }
    size_t esc_n = 0;
    i2s_channel_write(tx, bufI2S, cuadros * 2 * sizeof(int16_t), &esc_n, 60);
  } else if (tipo == T_CONTROL && largo) {
    entrada[largo] = 0;
    if (strstr((char *)entrada, "\"hola?\"")) {
      saludar(ok_dac, ok_adc, ok_i2s);
    } else if (strstr((char *)entrada, "\"parar\"")) {
      i2s_channel_disable(tx);
      i2s_channel_enable(tx);
      log_pc("cola de audio vaciada");
    }
  }
}
