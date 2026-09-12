# Dante

Un agente de voz que acompana a una persona mayor en su casa y **recuerda su
vida**: quien la visito, que le preocupa, que le gusta. Vive en un perrito de
juguete con ojos en la pantalla y una oreja que se mueve.

La idea viene de *Como si fuera la primera vez*: alguien que cada dia vuelve a
contarte quien sos. Por eso la memoria no es un accesorio del proyecto, es el
proyecto.

Corre en el PC del usuario, con sus propias llaves. Hackathon *Agents
Everywhere* (Bogota, AI Tinkerers).

---

## Como se trabaja aca

- **Los commits son de Sadid.** Nunca agregues `Co-Authored-By`.
- **El `.env` no se sube jamas.** Los cambios van a `.env.example`, vacio.
- **Un cambio a la vez sobre algo que ya funciona.** Se rompio asi mas de una
  vez: se tocaron tres cosas juntas y despues no habia forma de saber cual.
- **Se mide, no se recuerda.** Los dos errores mas caros del proyecto salieron
  de confiar en un numero que se creia saber. Si se puede comprobar en la
  placa en dos minutos, se comprueba.
- Todo el codigo, los comentarios y los mensajes de commit van **en espanol**.

---

## Que funciona hoy

Todo esto esta probado en hardware, no solo compilado.

| | |
|---|---|
| **Voz** | OpenAI Realtime, PCM16 a 24 kHz de punta a punta. Sin Opus, sin ASR, sin TTS. |
| **Memoria** | SQLite con procedencia (fecha, fuente, confianza) + embeddings. Corte de recuerdo en 0.35, medido. |
| **Vision** | Camara del PC o de red. Reconoce caras y **guarda el nombre**, no solo el rostro. |
| **Pantalla** | Ojos con seis estados. Tambien muestra texto. |
| **Oreja** | Un servo. Tres gestos, y ademas acompana al animo sola. |
| **Panel** | FastAPI. Audio y texto, lo que ve la camara, caras, y toda la configuracion. |
| **Auth0** | Login con Google, cookies firmadas, sin dependencias externas. |
| **Transporte** | USB y WiFi a la vez, o ninguno: **sin hardware el agente funciona igual**. |

Las cuatro funciones que dan el corazon del proyecto: **senales que preocupan**,
**mensajes de voz de la familia**, **onboarding por voz** y **modo "no me
acuerdo"**.

## Que falta

- **Resumen semanal para la familia.** Es lo que Trigger.dev esta esperando
  entregar: las tareas existen, pero nadie genera todavia el texto. Lo mas
  valioso que queda, y no toca hardware.
- **Botones fisicos** (GPIO21 hablar, GPIO38 diario). El firmware ya los
  escucha; faltan los cables. **No hacen falta**: el boton BOOT de la placa
  hace lo mismo que el de hablar.
- `TRIGGER_SECRET_KEY` sin poner. Proyecto `proj_slhciwuoxapsrziamieq`.
- `AUTH0_CORREOS` vacio: hoy entra cualquiera con cuenta de Google. El agente
  avisa al arrancar.

---

## Comandos

```
uv run dante doctor            # revisa entorno y llaves
uv run dante hablar --panel    # lo de siempre: conversar, con portal
uv run dante puente            # prueba el camino de audio por USB
uv run dante monitor           # lee el puerto serie crudo
uv run dante memoria           # ver que recuerda
```

Para grabar la placa, siempre con esta configuracion:

```
esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,PSRAM=disabled,
FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,UploadMode=default
```

---

## Trampas que ya costaron caro

Cada una de estas se pago con una hora o mas. Estan aca para no repetirlas.

**GPIO33 a GPIO37 son la memoria flash.** El chip lee de ahi su propio codigo.
Tocarlos lo mata a los pocos instantes de arrancar, pero **el USB sigue
apareciendo** porque es un periferico aparte. Se ve identico a un cable mal
puesto: pantalla negra, puerto presente, ni una linea impresa.

**El LEDC del S3 llega a 14 bits, no a 20.** Pedir 16 falla, y si no se mira lo
que devuelve `ledcAttach` el pin queda mudo sin avisar. El servo se sacude al
conectarlo pero ignora toda orden.

**La PSRAM queda apagada.** El firmware nunca la uso, y apagada hace que un
cable suelto sobre GPIO35/36/37 deje de poder tumbar el arranque.

**GPIO19 y GPIO20 son el USB.** Amarrarlos deja la placa invisible en Windows.

**DTR antes de abrir el puerto**, o no sale nada. Y **pulsar RTS reenumera el
USB** y mata el descriptor: no se usa para reiniciar.

**El buffer de entrada antes de `Serial.begin()`.** Con los 256 bytes por
defecto, un marco de 964 no se completa nunca y el audio no llega.

**El INMP441 entrega 24 bits dentro de una ranura de 32.** Bus a 32 bits,
lectura corrida 15. Los dos canales traen lo mismo; la mezcla suena mejor.

**`turn_detection` va dentro de `session.audio.input`**, no en la raiz.

Cuando la placa no arranca y no se sabe por que: **graba un sketch que solo
imprima**. Si ese tampoco corre, el problema no esta en el codigo de Dante, y
eso ahorra buscar en el lugar equivocado.

---

## Donde esta cada cosa

```
dante/sesion.py      el nucleo: Realtime, herramientas, transporte
dante/memoria.py     SQLite y recuerdo por similitud
dante/ajustes.py     configuracion -> personalidad. Las reglas duras
                     (no inventar, no describir sin mirar) NO se configuran
dante/panel.py       el portal
dante/vision.py      caras y objetos
firmware/dante_puente/   el firmware de verdad
firmware/dante_servo/    barre la oreja: separa fallo de PWM de fallo de cable
firmware/dante_pines/    dice que GPIO es cada agujero, tocando con un jumper
```

Detalles de cableado en `WIRING.md` y `HARDWARE.md`. El protocolo del cable,
en `PROTOCOL.md`. Lo de datos personales, en `SECURITY.md`.
