# Hardware de Dante — datos verificados

Todo lo de aquí está **medido en la placa real**, no leído en una hoja de datos.
Fecha: 9 de septiembre de 2026.

## Chip

| | |
|---|---|
| Modelo | ESP32-S3 (QFN56), revisión v0.2, 2 núcleos a 240 MHz |
| Flash | **16 MB** |
| PSRAM | **8 MB OPI**, embebida. Verificada con `ps_malloc(2MB)` + escritura/lectura |
| Heap interno libre | ~344 KB |
| MAC | `e8:f6:0a:89:e7:dc` |
| USB | USB-Serial/JTAG nativo, `VID:PID 303A:1001`, aparece como **COM7** |

## Configuración de compilación

FQBN completo:

```
esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,UploadMode=default
```

Equivalente en el menú Herramientas del Arduino IDE:

| Opción | Valor |
|---|---|
| Placa | ESP32S3 Dev Module |
| USB CDC On Boot | Enabled |
| PSRAM | OPI PSRAM |
| Flash Size | 16MB (128Mb) |
| Partition Scheme | 16M Flash (3MB APP/9.9MB FATFS) |
| USB Mode | Hardware CDC and JTAG |
| Upload Mode | UART0 / Hardware CDC |

## Bus I2C — confirmado por escaneo

SDA `GPIO1`, SCL `GPIO2`, a 100 kHz. Responden exactamente dos dispositivos:

| Dirección (7 bits) | Chip | Función |
|---|---|---|
| `0x18` | **ES8311** | DAC: manda al parlante |
| `0x41` | **ES7210** | ADC: lee los dos micrófonos |

## Pines

### Audio (I2S + I2C)

| Señal | GPIO |
|---|---|
| MCLK | 38 |
| BCLK | 14 |
| WS (LRCK) | 13 |
| DIN (del micrófono al ESP32) | 12 |
| DOUT (del ESP32 al parlante) | 45 |
| PA_EN (habilita el amplificador) | 48 |
| I2C SDA | 1 |
| I2C SCL | 2 |

Frecuencia de muestreo de la placa: **24000 Hz** de entrada y de salida.
Es la misma que usa la Realtime API de OpenAI, así que el audio viaja sin
convertirse en ningún punto.

**El MCLK debe ir a 12.288 MHz — 512 × fs, no 256 ×.** La tabla de coeficientes
del ES7210 no tiene ninguna entrada para 24 kHz con MCLK a 256 × fs; la más baja
que admite a esa frecuencia es 512 ×. El ES8311 acepta las dos, así que 512 × es
el único múltiplo que sirve para ambos a la vez. En el driver de I2S:
`clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_512`.

Coeficientes usados, de las filas `{12288000, 24000}` de cada tabla oficial:

| | ES8311 | ES7210 |
|---|---|---|
| divisores | `pre_div=2, pre_multi=0, adc_div=1, dac_div=1` | `adc_div=1, doubler=0, dll=1` |
| osr | `adc=0x10, dac=0x10` | `0x20` |
| lrck | `h=0x00, l=0xff` | `h=0x02, l=0x00` |
| bclk_div | `4` | — |

### Pantalla ST7789 — 320×240 apaisada

| Señal | GPIO |
|---|---|
| CS | 47 |
| DC | 39 |
| CLK (SCK) | 41 |
| SDA (MOSI) | 40 |
| Luz de fondo | 42 |
| RESET | al RST de la placa |

Orientación: `MIRROR_X`, `SWAP_XY`.

### Botones

| Botón | GPIO |
|---|---|
| BOOT (lo usamos para hablar) | 0 |
| Shield, página arriba | 20 |
| Shield, página abajo | 19 |

## Trampas descubiertas

1. **El USB-Serial/JTAG descarta la salida si el host no activa DTR.**
   Hay que fijar `dtr = True` **antes** de abrir el puerto. Si no, el sketch
   corre perfecto y el monitor se ve vacío — media hora perdida buscando un
   bug que no existe.

2. **Nunca dar pulsos de RTS en este puerto.** Reinicia el chip y lo hace
   re-enumerar por USB, con lo que el handle del puerto muere en la siguiente
   lectura. Para reiniciar hay que cerrar, esperar y reabrir.

3. **La carpeta `Arduino15/.../esp32/3.3.8` está vacía.** El core que de verdad
   está instalado es el **3.3.11**.

4. **Los dos canales del ES7210 llevan lo mismo.** El `config.h` de LAFVIN trae
   `AUDIO_INPUT_REFERENCE true`, lo que hacía pensar que el canal derecho era la
   señal de referencia del parlante para cancelación de eco. **Medido: no lo es.**
   Con ruido ambiente los dos canales dan niveles prácticamente iguales
   (izq pico 3264 / rms 878 contra der pico 3248 / rms 905), así que son los dos
   micrófonos. La referencia, si se activa, debe salir por otros canales del
   ES7210 y hay que habilitarla explícitamente.

   **Usar los dos.** Probado a oído contra cada canal por separado: la mezcla
   suena claramente más limpia que el izquierdo o el derecho solos. Para
   mandarle audio mono a OpenAI, promediar los dos canales — no tomar uno.

5. **Nunca hacer eco continuo micrófono → parlante para probar.** Se realimenta
   y chilla. Grabar un rato y reproducir después prueba las mismas dos rutas,
   sin acople, y además es como va a funcionar de verdad con el botón.
