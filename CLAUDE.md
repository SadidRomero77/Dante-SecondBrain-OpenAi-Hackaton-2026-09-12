# Kibo

Kibo es un agente de voz que acompana a una persona mayor en su casa y **recuerda su
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

## Donde vive

**En produccion: https://kibo.kibosecondbrain.com**

```
navegador -> Cloudflare (HTTPS) -> EC2 -> Caddy :443 -> contenedor :8800
```

EC2 `t3.small` en `us-east-1`, nombre `kibo`. **No hay SSH**: la red desde
donde se desplego bloquea el 22, asi que se administra con
`aws ssm send-command`, que va por HTTPS. Quedo mejor asi. Para desplegar:
entrar a /opt/kibo, `git reset --hard origin/main`, `docker build`, relanzar.

Las llaves viven en el almacen de AWS (`/kibo/openai`, `/kibo/exa-api-key`,
`/kibo/auth0-*`), no dentro del contenedor.

**El login esta ENCENDIDO y no depende de nadie**: cuentas propias con correo
y contrasena (`dante/cuentas.py`, scrypt, freno de intentos). Google por Auth0
es un boton extra que solo aparece con Auth0 configurado y sin
`DANTE_DEMO_LOGIN=0`; sigue apagado hasta dar de alta la direccion de vuelta.

**Cada cuenta es duena de su memoria, y no se borra.** Vive en
`/datos/cuentas/<id>/`: memoria, caras, recados. Antes colgaba de una galleta
anonima en `/tmp` y se tiraba a los 8 minutos. Lo que se corta a los
`DANTE_DEMO_MINUTOS` es la conversacion con OpenAI, no la memoria.
**El contenedor necesita `-v kibo-datos:/datos`** o todo se va en cada
despliegue.

## Que funciona hoy

Todo esto esta probado en hardware, no solo compilado.

| | |
|---|---|
| **Voz** | OpenAI Realtime, PCM16 a 24 kHz de punta a punta. Sin Opus, sin ASR, sin TTS. |
| **Memoria** | SQLite con procedencia (fecha, fuente, confianza) + embeddings. Corte de recuerdo en 0.35, medido. |
| **Vision** | Camara del PC o de red. Reconoce caras y **guarda el nombre**, no solo el rostro. |
| **Pantalla** | Ojos con seis estados. Tambien muestra texto. |
| **Oreja** | Un servo. Tres gestos, y ademas acompana al animo sola. |
| **Recordatorios** | Diarios, anuales o de un dia. Los dice EL cuando llega la hora, sin boton. Se crean y se corrigen hablando o en el portal. |
| **Recados** | La familia deja un mensaje -grabado o escrito- y Dante lo entrega al abrir la conversacion, sin que se lo pidan. |
| **Objetos** | Donde quedaron los lentes, las llaves. Con historial: el sitio de antes es la mejor pista cuando algo no esta. |
| **Resumen semanal** | Una nota para los hijos por Trigger.dev. Ademas compara con las semanas previas: cuanto hablo, que se repitio. |
| **Panel** | FastAPI. Audio y texto, lo que ve la camara, caras, y toda la configuracion. |
| **Login** | Cuentas propias (correo y contrasena) y Google opcional. Cookies firmadas, sin dependencias externas. |
| **Transporte** | USB y WiFi a la vez, o ninguno: **sin hardware el agente funciona igual**. |

Las cuatro funciones que dan el corazon del proyecto: **senales que preocupan**,
**mensajes de voz de la familia**, **onboarding por voz** y **modo "no me
acuerdo"**.

## Que falta

- **Botones fisicos** (GPIO21 hablar, GPIO38 diario). El firmware ya los
  escucha; faltan los cables. **No hacen falta**: el boton BOOT de la placa
  hace lo mismo que el de hablar.
- `TRIGGER_SECRET_KEY` sin poner. Proyecto `proj_slhciwuoxapsrziamieq`.
- `DANTE_CORREOS` vacio: cualquiera puede crearse una cuenta. Cada una ve
  solo su memoria, pero para una sola familia conviene poner sus correos.

---

## Comandos

```
uv run kibo doctor            # revisa entorno y llaves
uv run kibo hablar --panel    # lo de siempre: conversar, con portal
uv run kibo puente            # prueba el camino de audio por USB
uv run kibo monitor           # lee el puerto serie crudo
uv run kibo memoria           # ver que recuerda
uv run kibo resumen           # la nota semanal para la familia (--enviar)
uv run kibo olvidar Rosa      # sacar algo de la memoria (--si para borrar)
uv run kibo olvidar --todo    # vaciarla entera, conservando los ajustes
```

Para grabar la placa, siempre con esta configuracion:

```
esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,PSRAM=disabled,
FlashSize=16M,PartitionScheme=app3M_fat9M_16MB,UploadMode=default
```

---

## Como piensa Dante

Esto es el corazon del proyecto y no se toca sin pensarlo dos veces.

**Dos registros de verdad.** Sobre el mundo puede responder de lo que sabe y
puede equivocarse. Sobre la vida de la persona, solo lo que le devuelva la
memoria. Inventar un recuerdo es la unica falla grave que puede cometer.

**La configuracion no es memoria, pero manda sobre ella en una cosa.** El
nombre que la persona escribio en el portal vale mas que cualquier recuerdo
viejo con otro nombre. Todo lo demas que se escribe en "Su vida" se graba
como hechos atados a su nombre, no va al prompt: asi el prompt queda general
y la vida de cada persona vive donde recordar la encuentra.

**Hay una persona principal.** Es a quien acompana: su cara es la que importa
reconocer, y sus recuerdos son los unicos que puede contarle a ella misma. De
los demas guarda quienes son, no su vida.

**Numeros, nunca conclusiones.** Cuando compara semanas dice "hablo un 40%
menos", jamas "esta decayendo". Y calla si no tiene con que comparar: un
aviso falso a una familia preocupada cuesta mas que no avisar.

**Habla sin que le pregunten.** Los recordatorios y los recados los da el.
Quien los necesita es justamente quien no se va a acordar de pedirlos.

## Trampas del despliegue

Todas se ven igual desde fuera -"el portal no anda"- y ninguna se puede
descubrir en local.

**`ws://` en una pagina servida por https.** El navegador corta la conexion
por contenido inseguro y NO la deja ni salir: al servidor no llega ni una
peticion. Parece que el portal no hace nada.

**Una ruta que no contesta se lleva el sitio entero.** La de la camara
giraba para siempre sin enviar nada; cada peticion se quedaba con un hilo del
servidor, que son finitos. Con unas pocas visitas dejaba de responder todo.

**El tope de 8.000 caracteres por mensaje.** Un cuadro de camara en base64
pesa 60.000: se tiraban todos antes de leerlos, y Kibo decia "no te veo" con
la camara encendida y la imagen en pantalla.

**Los modelos de caras se bajaban al arrancar.** 38 MB que fallaban en
silencio, y el resultado se veia como "nadie a la vista". Van dentro de la
imagen.

**Cloudflare responde 403 a clientes automaticos.** Un curl o un script
reciben 403 en todas las rutas mientras un navegador recibe 200: al probar el
despliegue parece roto y no lo esta.

**Auth0 rechaza direcciones de vuelta no registradas.** Las llaves correctas
no bastan; es la proteccion central de OAuth y solo se arregla en su panel.

**Guardar en el portal reconfiguraba una sesion que no existe.** En la nube la
sesion global es un cascaron: hay que avisar a la conversacion de la cuenta
(`_aplicar` en panel.py). Se veia como "no guarda" con los datos guardados.

**El contenedor vive en UTC** si no se le dice otra cosa. La imagen trae
`TZ=America/Bogota`; sin eso un recordatorio de las 8:00 suena a las 3.

**fetch sigue las redirecciones en silencio.** Una API que redirige al login
devuelve 200 con el HTML de la pagina de entrar, y el portal decia "Guardado".
Por eso `/api/*` sin cuenta contesta 401.

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
dante/sesion.py      el nucleo: Realtime, las 19 herramientas, transporte
dante/memoria.py     SQLite, recuerdo por similitud, agenda, objetos, cambios
dante/ajustes.py     configuracion -> personalidad. Las reglas duras
                     (no inventar, no describir sin mirar) NO se configuran
dante/semanal.py     la nota para la familia
dante/conversar.py   con que llegar a hablar: tiempo, lo suyo, lo que conto
dante/olvidar.py     borrar recuerdos, de a uno o todos
dante/panel.py       el portal y la puerta
dante/cuentas.py     cuentas propias: correo, contrasena, freno de intentos
dante/demo.py        en la nube: un Kibo por cuenta, memoria en /datos/cuentas
dante/vision.py      caras
firmware/dante_puente/   el firmware de verdad
firmware/dante_servo/    barre la oreja: separa fallo de PWM de fallo de cable
firmware/dante_pines/    dice que GPIO es cada agujero, tocando con un jumper
```

Publicar el portal para un demo: `HOSTING.md`. Cableado en `WIRING.md` y `HARDWARE.md`. El protocolo del cable,
en `PROTOCOL.md`. Lo de datos personales, en `SECURITY.md`.
