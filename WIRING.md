# Cableado: INMP441 + MAX98357A sobre el shield LAFVIN

Reemplaza al módulo de audio original (ES8311 + ES7210). Los dos módulos nuevos
son **I2S puro**: no llevan configuración por I2C, y **no necesitan MCLK**.

## ⚠️ Lo único que puede romper algo

**El INMP441 no tolera 5 V.** Y el pin `VCC` del zócalo del códec en el shield
**es de 5 V** (así lo pedía el módulo viejo). Si conectás el micrófono ahí, lo
quemás.

> El micrófono va al pin **3V3** de la placa ESP32-S3, no al `VCC` del zócalo.

El MAX98357A sí acepta de 2.5 a 5.5 V, así que ese puede usar el `VCC` del
zócalo — y a 5 V suena más fuerte, que es lo que nos faltaba antes.

## El mapa

Las señales salen del zócalo donde estaba el módulo viejo. Es el mismo bus:
solo cambia quién lo escucha.

### INMP441 — el micrófono

| Pin del módulo | Va a | En el shield |
|---|---|---|
| `VDD` | **3V3** | ⚠️ pin 3V3 de la placa, **NO** el `VCC` del zócalo |
| `GND` | GND | `GND` del zócalo |
| `SCK` | `GPIO14` | `BCLK` del zócalo |
| `WS` | `GPIO13` | `WS` del zócalo |
| `SD` | `GPIO12` | `DIN` del zócalo |
| `L/R` | GND | canal izquierdo |

`L/R` a tierra pone al micrófono en el canal izquierdo. Con eso el audio llega
siempre en la ranura izquierda y el firmware sabe dónde buscarlo.

### MAX98357A — el amplificador

| Pin del módulo | Va a | En el shield |
|---|---|---|
| `VIN` | **5V** | `VCC` del zócalo |
| `GND` | GND | `GND` del zócalo |
| `BCLK` | `GPIO14` | `BCLK` del zócalo — compartido con el micrófono |
| `LRC` | `GPIO13` | `WS` del zócalo — compartido con el micrófono |
| `DIN` | `GPIO45` | `DOUT` del zócalo |
| `SD` | `GPIO48` | `PA_EN` del zócalo |
| `GAIN` | *(sin conectar)* | deja 9 dB, que está bien |
| `+` `−` | al parlante | polaridad indistinta |

**`SD` hace dos cosas a la vez** y por eso reusamos `PA_EN`:

| Voltaje en `SD` | Qué hace |
|---|---|
| 0 V (GPIO48 en bajo) | apagado, silencio total |
| 3.3 V (GPIO48 en alto) | encendido, canal izquierdo |

Así el firmware puede callar el amplificador con la misma línea de siempre, y
además queda en el canal izquierdo, que es donde manda el micrófono.

## ST7789 — la pantalla

Tiene su **propio bus SPI** y no comparte ninguna señal con el audio. Solo
comparte la alimentación de 3.3 V y la tierra.

| Pin | Va a | Nota |
|---|---|---|
| `VCC` | 3V3 | riel de arriba, con el micrófono |
| `GND` | GND | riel de arriba |
| `DC` | `GPIO39` | dato o comando |
| `CS` | `GPIO47` | selección de chip |
| `CLK` | `GPIO41` | reloj SPI — **no** es el `BCLK` del audio |
| `SDA` | `GPIO40` | datos SPI |
| `BLK` | `GPIO42` | luz de fondo |
| `RES` | `RST` | al reset de la placa |

## En protoboard: dos rieles, no uno

El amplificador puede pedir **picos de unos 400 mA**. Si sale del mismo
regulador de 3.3 V que alimenta al ESP32 con WiFi y la luz de la pantalla, la
tensión se hunde en los golpes de audio: distorsión, parpadeo de pantalla y
reinicios al subir el volumen.

| Riel | Qué lleva | Quién toma de ahí |
|---|---|---|
| **arriba +** | 3.3 V | micrófono y pantalla |
| **arriba −** | GND | los dos |
| **abajo +** | 5 V | solo el amplificador |
| **abajo −** | GND | el amplificador |

**Las dos tierras van unidas con un puente.** Sin eso no funciona nada, y es el
olvido más común.

Los 5 V vienen directo del USB sin pasar por el regulador de la placa, así que
tienen margen. Y como los rieles quedan en extremos opuestos, poner el
micrófono en el equivocado deja de ser un descuido posible.

### Cómo se une una señal que va a dos sitios

Las filas de la protoboard **son el empalme**: cada fila de cinco huecos está
unida por dentro.

```
shield BCLK ──→ [una fila libre] ──→ micrófono SCK
                       └──────────→ amplificador BCLK
```

Un cable entra, dos salen. Lo mismo con `WS`. Las señales que van a un solo
sitio —`DIN`, `DOUT`, `PA_EN` y todo el SPI de la pantalla— van directas.

> Los módulos suelen venir con la tira de pines **suelta**. Para pincharlos en
> la protoboard hay que soldarles esa tira: 6 y 7 puntos. Si ya vienen con los
> pines puestos, no hay nada que soldar en todo el montaje.

## Pines que quedan libres

| Antes | Ahora |
|---|---|
| `MCLK` — GPIO38 | **sin usar**. Estos módulos no lo necesitan. |
| `SCL` — GPIO2 | libre (queda para una cámara DVP) |
| `SDA` — GPIO1 | libre |

**Adiós al problema del reloj.** El ES7210 obligaba a un MCLK de 512 × fs; estos
módulos generan su reloj del BCLK. Se acabó la tabla de coeficientes.

## Comprobaciones antes de dar corriente

1. `VDD` del micrófono **no** está en 5 V.
2. Todos los `GND` compartidos: el de los módulos y el del shield.
3. `BCLK` y `WS` van **a los dos** módulos.
4. El micrófono manda por `GPIO12`; el amplificador recibe por `GPIO45`. **No
   se cruzan.**
5. El parlante está en la bornera del amplificador, no en el shield.

## Si algo no suena

| Síntoma | Dónde mirar |
|---|---|
| Silencio total | `SD` del amplificador — sin 3.3 V está apagado |
| Suena pero el micrófono da cero | `L/R` del micrófono, y que `SD` vaya a `GPIO12` |
| Zumbido o ruido | tierras sin unir, o el micrófono a 5 V (ya dañado) |
| Se oye entrecortado | `BCLK` o `WS` mal conectados en uno de los dos |
| El amplificador se calienta | parlante de menos de 4 Ω, o `+` y `−` en corto |
