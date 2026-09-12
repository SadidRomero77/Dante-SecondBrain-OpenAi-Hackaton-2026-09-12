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

#include <driver/i2s_std.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <Preferences.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

/* INMP441 + MAX98357A. I2S puro: no se configuran, se conectan. Y no usan
   MCLK, con lo que desaparece toda la tabla de coeficientes del codec viejo. */
static const int PIN_I2S_BCLK = 14, PIN_I2S_WS = 13;
static const int PIN_I2S_DIN = 12, PIN_I2S_DOUT = 45;
static const int PIN_PA_EN = 48,   PIN_LUZ = 42,       PIN_BOTON = 0;
/* Botones propios en la protoboard. No se usan GPIO19 ni GPIO20, que es donde
   los pone el kit original, porque en el ESP32-S3 esos dos pines son el USB
   nativo: usarlos como botones deja al aparato sin el puerto del audio.
   El 38 era el MCLK, que con estos modulos ya no hace falta. */
static const int PIN_HABLAR = 21;
static const int PIN_DIARIO = 38;

/* Servo de la oreja. GPIO10 esta libre: no lo usan ni el audio, ni la
   pantalla, ni los botones, ni la flash, ni la PSRAM, ni los pines que quedan
   reservados por si algun dia se conecta la camara. */
static const int PIN_SERVO = 10;
static int servo_bits = 0;               // resolucion que acepto la placa (0 = sin servo)
static const int SERVO_REPOSO = 80;      // grados con la oreja caida
static const int SERVO_ARRIBA = 135;     // grados con la oreja levantada
static const int PIN_LCD_CS = 47,  PIN_LCD_DC = 39,    PIN_LCD_SCK = 41,
                 PIN_LCD_MOSI = 40;

static const uint32_t FS       = 24000;
/* El INMP441 entrega 24 bits arriba de una ranura de 32. Corriendolos 15 a la
   derecha quedan 16 bits con margen; con 14 saturaba. */
static const int      CORRIMIENTO = 15;
/* El parlante quedaba corto, asi que la salida se amplifica por software antes
   de escribirla. Se satura en vez de dar la vuelta. */
static const float    GAN_SALIDA = 2.0f;

// 20 ms: 480 cuadros. Estereo en el bus, mono por el cable.
static const size_t CUADROS   = 480;
static const size_t BYTES_I2S = CUADROS * 2 * sizeof(int32_t);   // 3840
static const size_t BYTES_CBL = CUADROS * sizeof(int16_t);       // 960

/* --- WiFi ----------------------------------------------------------------
   El aparato se conecta al PC, no al reves: necesita saber la direccion una
   sola vez y reconecta solo. Por WebSocket no hace falta la cabecera de 4
   bytes: una trama binaria es audio y una de texto es control. Ver
   PROTOCOL.md.

   Las credenciales se guardan en Preferences y las escribe el PC por el
   propio cable, con "dante setup". Nada de portal cautivo: se configura desde
   la misma terminal que corre el agente. */
static bool ok_dac = false, ok_adc = false, ok_i2s = false;

static Preferences prefs;
static WebSocketsClient wsc;
static bool wifi_configurado = false;
static bool wifi_listo = false;         // conectado al servidor
static uint32_t proximo_reintento = 0;

static const uint8_t MAGIA = 0xA5;
static const uint8_t T_AUDIO = 1, T_CONTROL = 2, T_LOG = 3;

static i2s_chan_handle_t tx = nullptr, rx = nullptr;
static int32_t bufI2S[CUADROS * 2];     // el bus, en 32 bits
static int16_t bufCable[CUADROS];      // por el cable viaja mono de 16
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
// 0 nada, 1 saludo, 2 atencion, 3 duda. Lo pide quien sea y lo ejecuta la
// tarea del nucleo 0, para que ninguna espera del servo toque el audio.
static volatile int gesto_pedido = 0;

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

    if (gesto_pedido) {
      int g = gesto_pedido;
      gesto_pedido = 0;
      hacer_gesto(g);
    }

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

// ------------------------------------------------------------------ oreja --
/* El servo se maneja con LEDC directo: 50 Hz, y el ancho del pulso entre 0.5 y
   2.5 ms decide el angulo. No hace falta ninguna libreria.

   Los movimientos corren en el nucleo 0, junto con la pantalla, para que
   ninguna espera toque el audio, que vive en el nucleo 1. */

static void servo_grados(int g) {
  if (!servo_bits) return;          // sin PWM no hay nada que escribir
  if (g < 0) g = 0; else if (g > 180) g = 180;
  // 0.5 ms a 2.5 ms sobre un periodo de 20 ms.
  uint32_t us = 500 + (uint32_t)g * 2000 / 180;
  uint32_t tope = (1UL << servo_bits) - 1;
  ledcWrite(PIN_SERVO, (uint32_t)((uint64_t)us * tope / 20000));
}

static void init_servo() {
  // El ESP32-S3 solo llega a 14 bits de resolucion en el LEDC; el ESP32
  // original llegaba a 20. Pedir 16 falla en silencio y el pin se queda
  // mudo: el servo se sacude al conectarlo pero no obedece ninguna orden.
  // Por eso buscamos la resolucion mas alta que la placa acepte de verdad.
  for (int b = 14; b >= 10 && !servo_bits; b--)
    if (ledcAttach(PIN_SERVO, 50, b)) servo_bits = b;
  if (!servo_bits) { Serial.println("servo: el LEDC no acepto ninguna resolucion"); return; }
  servo_grados(SERVO_REPOSO);
  delay(300);
  ledcWrite(PIN_SERVO, 0);               // soltar: quieto no consume ni zumba
}

/* Mueve la oreja y la suelta. Soltarla importa: un servo mantenido en
   posicion zumba y consume, y ese zumbido se cuela por el parlante. */
static void hacer_gesto(int cual) {
  switch (cual) {
    case 1:                              // saludo: dos movimientos alegres
      for (int i = 0; i < 2; i++) {
        servo_grados(SERVO_ARRIBA); vTaskDelay(pdMS_TO_TICKS(230));
        servo_grados(SERVO_REPOSO); vTaskDelay(pdMS_TO_TICKS(230));
      }
      break;
    case 2:                              // atencion: la levanta y la sostiene
      servo_grados(SERVO_ARRIBA); vTaskDelay(pdMS_TO_TICKS(900));
      servo_grados(SERVO_REPOSO); vTaskDelay(pdMS_TO_TICKS(250));
      break;
    case 3:                              // duda: media oreja
      servo_grados((SERVO_REPOSO + SERVO_ARRIBA) / 2);
      vTaskDelay(pdMS_TO_TICKS(700));
      servo_grados(SERVO_REPOSO); vTaskDelay(pdMS_TO_TICKS(250));
      break;
  }
  ledcWrite(PIN_SERVO, 0);
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
  // Por WiFi cuando lo hay, porque es el camino que sobrevive a que alguien
  // desenchufe el cable. Si no, por el cable.
  if (wifi_listo) {
    if (tipo == T_AUDIO) wsc.sendBIN((const uint8_t *)carga, largo);
    else                 wsc.sendTXT((const char *)carga, largo);
    return;
  }
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

static void atender_marco(uint8_t tipo, const uint8_t *carga, uint16_t largo);

/* Eventos del WebSocket. Los marcos entran por aqui y siguen el mismo camino
   que los del cable: el resto del firmware no sabe por donde llegaron. */
static void al_evento_ws(WStype_t tipo, uint8_t *carga, size_t largo) {
  switch (tipo) {
    case WStype_CONNECTED:
      wifi_listo = true;
      estado = LISTO;
      saludar(ok_dac, ok_adc, ok_i2s);
      break;
    case WStype_DISCONNECTED:
      wifi_listo = false;
      break;
    case WStype_BIN:
      atender_marco(T_AUDIO, carga, (uint16_t)largo);
      break;
    case WStype_TEXT:
      atender_marco(T_CONTROL, carga, (uint16_t)largo);
      break;
    default:
      break;
  }
}

/* Levanta el WiFi si hay credenciales guardadas. No bloquea: si la red no
   aparece, el aparato sigue funcionando por el cable. */
static void init_wifi() {
  prefs.begin("dante", true);
  String ssid = prefs.getString("ssid", "");
  String clave = prefs.getString("clave", "");
  String host = prefs.getString("host", "");
  String ficha = prefs.getString("ficha", "");
  uint16_t puerto = prefs.getUShort("puerto", 8770);
  prefs.end();

  if (ssid.isEmpty() || host.isEmpty()) {
    log_pc("wifi sin configurar; se usa el cable");
    return;
  }
  wifi_configurado = true;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                 // el sueno de WiFi corta el audio
  WiFi.begin(ssid.c_str(), clave.c_str());

  char m[128];
  snprintf(m, sizeof(m), "wifi: conectando a %s, servidor %s:%u",
           ssid.c_str(), host.c_str(), puerto);
  log_pc(m);

  // La ficha va en la ruta: el servidor rechaza a quien no la traiga, para
  // que el puerto de WiFi no quede abierto a toda la red local.
  String ruta = "/" + ficha;
  wsc.begin(host.c_str(), puerto, ruta.c_str());
  wsc.onEvent(al_evento_ws);
  wsc.setReconnectInterval(3000);
  wsc.enableHeartbeat(15000, 3000, 2);
}

/* Guarda credenciales que llegan por el cable y reinicia para aplicarlas. */
static void guardar_wifi(const char *ssid, const char *clave,
                         const char *host, uint16_t puerto, const char *ficha) {
  prefs.begin("dante", false);
  prefs.putString("ssid", ssid);
  prefs.putString("clave", clave);
  prefs.putString("host", host);
  prefs.putString("ficha", ficha);
  prefs.putUShort("puerto", puerto);
  prefs.end();
  log_pc("wifi guardado; reiniciando");
  mostrar_texto("WiFi", "Configurado. Reiniciando...", 3);
  delay(900);
  ESP.restart();
}

static bool init_i2s() {
  i2s_chan_config_t ch = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  ch.dma_desc_num = 8; ch.dma_frame_num = 240; ch.auto_clear = true;
  if (i2s_new_channel(&ch, &tx, &rx) != ESP_OK) return false;

  i2s_std_config_t c = {};
  c.clk_cfg.sample_rate_hz = FS;
  c.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
  c.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
  // 32 bits porque el INMP441 no entrega 16: da 24 dentro de una ranura de 32.
  c.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO);
  c.gpio_cfg.mclk = I2S_GPIO_UNUSED;          // estos modulos no lo necesitan
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
  pinMode(PIN_HABLAR, INPUT_PULLUP);
  pinMode(PIN_DIARIO, INPUT_PULLUP);

  init_pantalla();
  init_servo();

  // Ya no hay nada que configurar por I2C: los modulos nuevos solo se conectan.
  bool c = init_i2s();
  bool a = c, b = c;
  digitalWrite(PIN_PA_EN, HIGH);
  estado = (a && b && c) ? LISTO : ERROR;

  delay(300);
  saludar(a, b, c);
  init_wifi();
}

/* El aparato arranca antes de que el PC abra el puerto, asi que el saludo
   inicial se pierde casi siempre. El PC lo vuelve a pedir al conectarse. */
static void saludar(bool a, bool b, bool c) {
  ok_dac = a; ok_adc = b; ok_i2s = c;
  char hola[160];
  snprintf(hola, sizeof(hola),
           "{\"t\":\"hola\",\"fw\":\"0.2.0\",\"sr\":%lu,\"transporte\":\"%s\","
           "\"ip\":\"%s\",\"dac\":%s,\"adc\":%s,\"i2s\":%s}",
           (unsigned long)FS, wifi_listo ? "wifi" : "usb",
           wifi_listo ? WiFi.localIP().toString().c_str() : "",
           a ? "true" : "false", b ? "true" : "false", c ? "true" : "false");
  enviar(T_CONTROL, hola, strlen(hola));
}

// ------------------------------------------------------------------ loop ---
void loop() {
  // 1. botones. El de hablar y el BOOT hacen lo mismo, para que el aparato
  //    siga siendo usable si alguien todavia no cableo el suyo.
  static int previo = HIGH;
  static uint32_t rebote = 0;
  int crudo = (digitalRead(PIN_HABLAR) == LOW || digitalRead(PIN_BOTON) == LOW)
              ? LOW : HIGH;
  if (crudo != previo && millis() > rebote) {
    rebote = millis() + 30;          // los pulsadores mecanicos rebotan
    previo = crudo;
    const char *m = (crudo == LOW) ? "{\"t\":\"boton\",\"v\":\"abajo\"}"
                                   : "{\"t\":\"boton\",\"v\":\"arriba\"}";
    enviar(T_CONTROL, m, strlen(m));
  }

  // 1b. boton del diario: se avisa al SOLTARLO, para no dispararlo si alguien
  //     se apoya encima.
  static int diario_previo = HIGH;
  static uint32_t diario_desde = 0, diario_rebote = 0;
  int d = digitalRead(PIN_DIARIO);
  if (d != diario_previo && millis() > diario_rebote) {
    diario_rebote = millis() + 30;
    if (d == LOW) {
      diario_desde = millis();
    } else if (diario_desde) {
      uint32_t dur = millis() - diario_desde;
      if (dur < 2000) {
        // Toque corto: como va el dia.
        const char *m = "{\"t\":\"diario\"}";
        enviar(T_CONTROL, m, strlen(m));
        mostrar_texto("Un momento", "Voy a contarte como va el dia", 4);
      } else if (dur < 15000) {
        // Pulsacion larga: "no me acuerdo". Para alguien desorientado,
        // formular la pregunta es justamente lo dificil.
        const char *m = "{\"t\":\"quien_soy\"}";
        enviar(T_CONTROL, m, strlen(m));
        mostrar_texto("Aqui estoy", "Ya te cuento quien eres", 5);
      }
    }
    diario_previo = d;
  }

  // 2. microfono -> PC. Promedia los dos canales: suena mas limpio que uno solo.
  size_t leidos = 0;
  if (i2s_channel_read(rx, bufI2S, BYTES_I2S, &leidos, 30) == ESP_OK && leidos) {
    size_t cuadros = leidos / (2 * sizeof(int32_t));
    for (size_t i = 0; i < cuadros; i++) {
      // El microfono manda por el canal izquierdo: su L/R esta a tierra.
      bufCable[i] = (int16_t)(bufI2S[i * 2] >> CORRIMIENTO);
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
    atender_marco(tipo, marco, largo);
  }

  // 4. WiFi: los marcos entran por el callback, esto solo mantiene la conexion.
  if (wifi_configurado) {
    wsc.loop();
    if (!wifi_listo && millis() > proximo_reintento) {
      proximo_reintento = millis() + 5000;
      if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
    }
  }
}

/* Atiende un marco venga de donde venga: del cable o de la red. El resto del
   firmware no distingue, y esa es la idea. */
static void atender_marco(uint8_t tipo, const uint8_t *carga, uint16_t largo) {
  if (tipo == T_AUDIO && largo) {
    const int16_t *mono = (const int16_t *)carga;
    size_t cuadros = largo / sizeof(int16_t);
    if (cuadros > CUADROS) cuadros = CUADROS;
    for (size_t i = 0; i < cuadros; i++) {
      float v = mono[i] * GAN_SALIDA;
      if (v > 32767.0f) v = 32767.0f; else if (v < -32768.0f) v = -32768.0f;
      // Los 16 bits se corren a la izquierda para llenar la ranura de 32.
      int32_t m = ((int32_t)(int16_t)v) << 16;
      bufI2S[i * 2] = m;
      bufI2S[i * 2 + 1] = m;
    }
    size_t esc_n = 0;
    i2s_channel_write(tx, bufI2S, cuadros * 2 * sizeof(int32_t), &esc_n, 120);
    return;
  }

  if (tipo != T_CONTROL || !largo) return;

  // Copia con terminador: la carga puede venir de un buffer que no lo tiene.
  static char txt[1024];
  uint16_t n = largo < sizeof(txt) - 1 ? largo : sizeof(txt) - 1;
  memcpy(txt, carga, n);
  txt[n] = 0;

  char *em = strstr(txt, "\"emocion\"");
  if (em) {
    Estado antes = estado;
    if (strstr(em, "escuchando"))      estado = ESCUCHANDO;
    else if (strstr(em, "pensando"))   estado = PENSANDO;
    else if (strstr(em, "hablando"))   estado = HABLANDO;
    else if (strstr(em, "feliz"))      estado = FELIZ;
    else if (strstr(em, "atencion"))   estado = ATENCION;
    else                               estado = LISTO;

    // La oreja acompana al animo sola. Solo al cambiar: repetir el mismo
    // animo no debe volver a moverla, o temblaria toda la conversacion.
    if (estado != antes) {
      if (estado == FELIZ)                                gesto_pedido = 1;
      else if (estado == ESCUCHANDO || estado == ATENCION) gesto_pedido = 2;
      else if (estado == PENSANDO)                         gesto_pedido = 3;
    }

  } else if (strstr(txt, "\"texto\"")) {
    char titulo[40] = "", cuerpo[160] = "";
    int seg = 8;
    char *q;
    if ((q = strstr(txt, "\"titulo\":\""))) {
      q += 10; int i = 0;
      while (*q && *q != '"' && i < 38) titulo[i++] = *q++;
      titulo[i] = 0;
    }
    if ((q = strstr(txt, "\"cuerpo\":\""))) {
      q += 10; int i = 0;
      while (*q && *q != '"' && i < 158) cuerpo[i++] = *q++;
      cuerpo[i] = 0;
    }
    if ((q = strstr(txt, "\"seg\":"))) seg = atoi(q + 6);
    mostrar_texto(titulo, cuerpo, seg > 0 ? seg : 8);

  } else if (strstr(txt, "\"gesto\"")) {
    // Gesto pedido a proposito por el agente (la herramienta mover_oreja).
    if (strstr(txt, "saludo"))        gesto_pedido = 1;
    else if (strstr(txt, "atencion")) gesto_pedido = 2;
    else if (strstr(txt, "duda"))     gesto_pedido = 3;

  } else if (strstr(txt, "\"wifi\"")) {
    // {"t":"wifi","ssid":"...","clave":"...","host":"192.168.1.20","puerto":8770}
    char ssid[64] = "", clave[64] = "", host[64] = "", ficha[64] = "";
    int puerto = 8770;
    char *q;
    if ((q = strstr(txt, "\"ssid\":\""))) {
      q += 8; int i = 0; while (*q && *q != '"' && i < 62) ssid[i++] = *q++; ssid[i] = 0;
    }
    if ((q = strstr(txt, "\"clave\":\""))) {
      q += 9; int i = 0; while (*q && *q != '"' && i < 62) clave[i++] = *q++; clave[i] = 0;
    }
    if ((q = strstr(txt, "\"host\":\""))) {
      q += 8; int i = 0; while (*q && *q != '"' && i < 62) host[i++] = *q++; host[i] = 0;
    }
    if ((q = strstr(txt, "\"ficha\":\""))) {
      q += 9; int i = 0; while (*q && *q != '"' && i < 62) ficha[i++] = *q++; ficha[i] = 0;
    }
    if ((q = strstr(txt, "\"puerto\":"))) puerto = atoi(q + 9);
    if (ssid[0] && host[0]) guardar_wifi(ssid, clave, host, (uint16_t)puerto, ficha);

  } else if (strstr(txt, "\"hola?\"")) {
    saludar(ok_dac, ok_adc, ok_i2s);

  } else if (strstr(txt, "\"parar\"")) {
    i2s_channel_disable(tx);
    i2s_channel_enable(tx);
  }
}
