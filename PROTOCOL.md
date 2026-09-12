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
| Trozo | 20 ms = 480 muestras = **960 bytes** |
| Caudal | 48 000 bytes/s por dirección |

Es el mismo formato que pide la Realtime API de OpenAI. Por eso no hay ni
remuestreo ni códec en el camino.

El bus I2S de la placa trabaja en estéreo con los dos micrófonos, pero por el
cable viaja **mono**: el aparato promedia los dos canales antes de enviar, y
duplica el mono a los dos canales al reproducir. Probado a oído — la mezcla de
los dos micrófonos suena claramente más limpia que cualquiera de los dos solo.

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
| `0x01` | `AUDIO` | ambas | 960 bytes de PCM16 mono |
| `0x02` | `CONTROL` | ambas | JSON en UTF-8 |
| `0x03` | `LOG` | aparato → PC | texto plano, para depurar |

Si el receptor se desincroniza, descarta bytes hasta encontrar el siguiente
`0xA5` cuyo largo sea coherente. El campo largo nunca pasa de 4096.

### Por WiFi (WebSocket)

WebSocket ya delimita, así que no se usa cabecera:

- **Trama binaria** → audio PCM16 crudo.
- **Trama de texto** → el mismo JSON de control.

**El servidor escucha y el aparato se conecta**, no al revés. Así el aparato
necesita saber la dirección del PC una sola vez, y puede reconectar solo si el
PC se reinicia. El puerto por defecto es el `8770`; si está ocupado, el servidor
busca el siguiente libre — en una máquina ajena cualquier puerto puede estar
tomado por un servicio del sistema.

Solo se admite **un aparato a la vez**: el segundo recibe un cierre con el
código 1013.

### Los dos a la vez

El servidor abre cable y WiFi al mismo tiempo y manda por los dos. Si solo hay
uno conectado, el otro no hace nada. Se puede **desenchufar el cable a mitad de
una conversación y seguir por red**, o al revés, sin reiniciar.

El agente no sabe por cuál está hablando, y esa es justamente la idea.

## Mensajes de control

### Del aparato al PC

```json
{"t":"hola", "fw":"0.2.0", "sr":24000, "transporte":"usb|wifi", "ip":"192.168.1.33"}
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

```json
{"t":"wifi", "ssid":"MiRed", "clave":"...", "host":"192.168.1.12", "puerto":8770}
```

`wifi` guarda la red y la dirección del PC en la memoria no volátil del aparato
y lo reinicia. Se manda **por el cable**, con `dante setup`. No hay portal
cautivo: se configura desde la misma terminal que corre el agente, y después se
puede desenchufar.

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
