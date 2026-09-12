# Protocolo Dante · aparato ⇄ PC

Contrato entre la placa ESP32-S3 y el servidor. Lo escribimos nosotros y es
deliberadamente mínimo: el aparato no interpreta nada, solo mueve audio y dibuja.

Vale igual por los dos transportes. Lo único que cambia es cómo se delimitan
los mensajes.

## Audio

Un solo formato, de punta a punta, sin conversiones en ningún punto de la cadena:

| | |
|---|---|
| Codificación | PCM lineal, 16 bits con signo, little endian |
| Frecuencia | 24000 Hz |
| Canales | 1 (mono) |
| Trozo | 20 ms = 480 muestras = **1920 bytes** |
| Caudal | 48 000 bytes/s por dirección |

Es el mismo formato que pide la Realtime API de OpenAI. Por eso no hay ni
remuestreo ni códec en el camino.

## Delimitación de mensajes

### Por USB (puerto serie nativo)

El puerto serie es un flujo de bytes sin fronteras, así que cada mensaje lleva
una cabecera de 4 bytes:

```
 byte 0     byte 1     bytes 2-3        bytes 4..n
+--------+----------+----------------+---------------+
|  0xA5  |   tipo   | largo (uint16) |    carga      |
+--------+----------+----------------+---------------+
           little endian, largo = tamaño de la carga
```

| tipo | nombre | dirección | carga |
|---|---|---|---|
| `0x01` | `AUDIO` | ambas | 1920 bytes de PCM16 |
| `0x02` | `CONTROL` | ambas | JSON en UTF-8 |
| `0x03` | `LOG` | aparato → PC | texto plano, para depurar |

Si el receptor se desincroniza, descarta bytes hasta encontrar el siguiente
`0xA5` cuyo largo sea coherente. El campo largo nunca pasa de 4096.

### Por WiFi (WebSocket)

WebSocket ya delimita, así que no se usa cabecera:

- **Trama binaria** → audio PCM16 crudo.
- **Trama de texto** → el mismo JSON de control.

## Mensajes de control

### Del aparato al PC

```json
{"t":"hola", "fw":"0.1.0", "sr":24000, "transporte":"usb"}
{"t":"boton", "v":"abajo"}
{"t":"boton", "v":"arriba"}
{"t":"listo"}
```

`hola` se manda al conectar. El PC no envía audio hasta recibirlo.

`boton` es lo que marca los turnos: **abajo** abre el micrófono, **arriba** lo
cierra y le pide la respuesta al modelo. Mientras el botón está arriba el
aparato no transmite audio, y por eso no hace falta cancelación de eco.

`listo` avisa que terminó de reproducir todo lo que tenía en cola.

### Del PC al aparato

```json
{"t":"emocion", "v":"escuchando"}
{"t":"volumen", "v":80}
{"t":"parar"}
{"t":"texto", "v":"Es Ana, tu hija"}
```

`emocion` cambia la animación. Valores: `idle`, `escuchando`, `pensando`,
`hablando`, `feliz`, `dormido`, `cariñoso`, `confundido`, `alerta`, `sorpresa`.

`parar` vacía la cola de reproducción de inmediato. Hoy se usa al cancelar un
turno; mañana, para poder interrumpir hablando.

`texto` es opcional: un subtítulo corto bajo Dante, útil si el usuario oye mal.

## Ciclo de una conversación

```
aparato                        PC                         OpenAI
   |-- hola ------------------>|
   |<-- emocion: idle ---------|
   |                           |
   |-- boton: abajo ---------->|  abre el buffer de entrada
   |<-- emocion: escuchando ---|
   |-- AUDIO x N ------------->|-- input_audio_buffer.append -->
   |-- boton: arriba --------->|-- commit + response.create --->
   |<-- emocion: pensando -----|
   |                           |<-- response.output_audio.delta
   |<-- emocion: hablando -----|
   |<-- AUDIO x N -------------|
   |-- listo ----------------->|
   |<-- emocion: idle ---------|
```

## Reglas

1. **El aparato nunca decide nada.** No sabe qué es una conversación ni una
   emoción; recibe órdenes y las ejecuta.
2. **El audio no espera.** Se envía en cuanto hay 1920 bytes. Nada de acumular
   una frase entera.
3. **Todo lo que el aparato quiera decir va por `LOG`**, nunca por el flujo de
   audio ni impreso suelto al puerto serie.
4. **El PC tolera que el aparato se caiga** y reconecta solo. Al revés también.
