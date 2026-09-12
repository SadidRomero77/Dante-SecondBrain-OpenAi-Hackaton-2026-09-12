# Dante — segundo cerebro

Un agente de voz con memoria que vive en un aparato físico sobre la mesa.
Escucha, recuerda, ve, y tiene cara.

Pensado para personas mayores y para quien empieza a olvidar: recuerda quién es
cada quien, qué pasó ayer y qué toca hoy — y **dice cuando no sabe**, en vez de
inventar.

> Dante no es un dispositivo médico. No diagnostica, no aconseja tratamientos y
> no reemplaza a nadie. Es un compañero de memoria cotidiana y una herramienta
> para quien cuida.

**El hardware es opcional.** Todo funciona desde el navegador. Ver
[Sin hardware](#sin-hardware).

---

## Qué hace

| | |
|---|---|
| **Conversa** | Voz a voz con `gpt-realtime-2`. Primera respuesta en menos de un segundo. |
| **Recuerda** | Cada hecho con su fecha, su fuente y su confianza. Búsqueda por significado. |
| **No inventa** | Sobre la vida de la persona solo afirma lo que devuelve la memoria. Si no lo tiene, lo dice. |
| **Ve** | Reconoce caras registradas y describe lo que hay enfrente, cuando se lo piden. |
| **Se entera** | Hora en cualquier ciudad, clima, y búsqueda web con Exa. |
| **Saluda** | Al empezar el día cuenta qué pasó ayer, quién viene y qué medicamento toca. |
| **Tiene cara** | Dos ojos animados, y texto para recordatorios y confirmaciones. |
| **Avisa a la familia** | Resumen semanal y alerta si algo no se confirmó, por Trigger.dev. |

---

## Instalación

Hace falta **Python 3.11 o más nuevo** y [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/SadidRomero77/Dante-SecondBrain-OpenAi-Hackaton.git
cd Dante-SecondBrain-OpenAi-Hackaton
uv sync
```

Copiá el ejemplo de configuración y poné tus llaves:

```bash
cp .env.example .env        # en Windows: copy .env.example .env
```

Abrí el `.env` y pegá al menos `OPENAI_API_KEY`. Todo lo demás es opcional.

> **En Windows corré el agente desde PowerShell, no desde WSL.** WSL no ve los
> puertos USB, así que desde ahí el aparato no aparece.

Verificá que quedó bien:

```bash
uv run dante doctor
```

Te dice qué falta y qué integraciones están activas. No gasta créditos.

### Las llaves

| Variable | Para qué | ¿Obligatoria? |
|---|---|---|
| `OPENAI_API_KEY` | Voz, visión, memoria | **Sí** |
| `EXA_API_KEY` | Búsqueda web rápida | No — sin ella usa OpenAI, cinco veces más lento |
| `OPENROUTER_API_KEY` | Elegir otro modelo de texto | No |
| `AUTH0_*` | Login con Google en el portal | No — sin ellas el portal queda abierto |
| `TRIGGER_*` | Avisos a la familia | No |
| `DANTE_CAMARA` | Índice de cámara (`0`, `1`...) | No — vacío = sin visión |

La API de OpenAI **se paga aparte de ChatGPT Plus**. Cargá crédito en
[platform.openai.com/billing](https://platform.openai.com/settings/organization/billing)
y ponete un tope de gasto.

---

## Correr sin hardware

**No tener la placa no limita nada.** El panel es una entrada y salida de voz
completa: captura por el micrófono del computador y reproduce por sus parlantes.

```bash
uv run dante hablar --panel
```

Abrí **http://127.0.0.1:8800**. Ahí tenés:

- **Conversación** — hablale manteniendo la **barra espaciadora**, o escribile
- **Personas** — registrar caras con la cámara del computador
- **Configuración** — nombre, trato, personalidad, voz, temas

Funciona la memoria, la visión, el reconocimiento de caras, el diario, la
búsqueda web y toda la configuración. Lo único que falta es la cara en la
pantalla física.

Probá con datos de ejemplo:

```bash
uv run dante semilla       # carga una persona con su familia y su pasado
uv run dante memoria       # mira qué recuerda
uv run dante hablar --panel --diario
```

---

## Correr con hardware

Kit **LAFVIN AI Chatbot** (ESP32-S3). Los datos medidos de la placa están en
[`HARDWARE.md`](HARDWARE.md), el contrato con el aparato en
[`PROTOCOL.md`](PROTOCOL.md), y el cableado de los módulos de audio en
[`WIRING.md`](WIRING.md).

### 1. Flashear

Abrí `firmware/dante_puente/dante_puente.ino` en el Arduino IDE. Los ajustes de
placa están en el encabezado del archivo; los dos que no podés equivocar son
**USB CDC On Boot = Enabled** y **PSRAM = OPI PSRAM**.

### 2. Conectar

```bash
uv run dante hablar --panel
```

El aparato aparece solo. Mantené **BOOT** apretado para hablar.

### 3. Pasarlo a WiFi (opcional)

Con el cable puesto:

```bash
uv run dante setup
```

Pregunta la red, la contraseña, y detecta sola la IP de este PC. Se la escribe
al aparato por el mismo cable y lo reinicia. **No hay portal cautivo ni
hotspot.** Después podés desenchufar.

> El ESP32 no ve redes de 5 GHz. Tiene que ser una de 2.4.

El servidor abre cable y WiFi a la vez y manda por ambos, así que se puede
desenchufar el cable a mitad de una conversación y seguir por red.

### Si el audio del aparato falla

```bash
uv run dante hablar --panel --solo-cara
```

El aparato conserva pantalla y botón pero su audio no se usa: la voz va por el
computador. Sigue habiendo demo físico sin depender del módulo de audio.

---

## Comandos

```
dante doctor           Revisa el entorno y las integraciones. No gasta créditos.
dante smoke            Prueba la Realtime API con una conversación de texto.
dante semilla          Carga una persona de ejemplo con su pasado.
dante memoria          Muestra qué recuerda Dante ahora mismo.

dante hablar           Conversar.
       --panel         ...y abrir el portal en el 8800
       --solo-cara     ...ignorando el audio del aparato
       --diario        ...forzando el saludo del día

dante setup            Le pasa al aparato la red WiFi y la IP del PC.
dante monitor          Lee el puerto serie del aparato.
dante puente           Micrófono → PC → parlante, sin modelo de por medio.
```

---

## El portal

`--panel` abre una página con tres pestañas.

**Conversación** — el video de lo que Dante ve con las caras marcadas, la charla
en vivo con las herramientas que va usando, chat por texto y micrófono.

**Personas** — poné a alguien frente a la cámara, escribí "Ana / hija", un botón.
Dante la reconoce y la nombra en voz alta la próxima vez.

**Configuración** — propietario, tú o usted, nombre de la mascota, voz, ciudad,
cómo debe comportarse, temas que le gustan y cuáles no. Se aplica sin reiniciar.

> **Lo que no es configurable**: no inventar, no describir sin haber mirado, y
> responder en español. Esas reglas son lo que hace confiable al agente y no
> dependen del gusto de nadie. Se configura el tono, no la honestidad.

### Login con Auth0

Sin configurar, el portal queda abierto — que es lo correcto en `127.0.0.1`. Si
va a salir de tu máquina, creá una *Regular Web Application* en
[manage.auth0.com](https://manage.auth0.com), habilitá Google, y poné
`http://127.0.0.1:8800/callback` en *Allowed Callback URLs*.

Después llená `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET` y —
importante — `AUTH0_CORREOS` con los correos autorizados, separados por coma.
**Vacío significa que cualquiera con cuenta de Google puede entrar.**

El login protege **el portal**, no los datos: la memoria sigue siendo un archivo
en tu disco. Autenticar no mueve nada a la nube, solo decide quién abre la
ventana.

---

## Trabajos en la nube

`src/trigger/` es un proyecto de [Trigger.dev](https://trigger.dev) al lado del
agente. La división es deliberada:

| | |
|---|---|
| **El PC de la casa** | lo que Dante **dice**: la pastilla, la cita, el diario |
| **Trigger.dev** | lo que **sale** hacia la familia: el resumen semanal, el aviso de que algo no se confirmó |

Un temporizador local no sobrevive a que el PC se duerma, no reintenta si falla
el correo y no espera tres horas de forma confiable. La nube no puede llamar a
tu portátil. Por eso cada uno hace su mitad.

Los datos de la persona **no salen de su casa**: a la nube solo viaja el texto
que su familia iba a leer de todas formas.

```bash
npm install
npx trigger.dev@latest login
npx trigger.dev@latest dev
```

---

## Docker

Para hostearlo en cualquier parte:

```bash
cp .env.example .env      # pon tus llaves
docker compose up -d
```

El portal queda en el `8800` y el aparato entra por WiFi al `8770`.

| El contenedor | |
|---|---|
| ✅ | el agente, la memoria, el portal, la búsqueda, los trabajos |
| ✅ | el aparato conectado por **WiFi** |
| ❌ | el aparato por **cable USB**, salvo en Linux pasando el dispositivo |
| ❌ | la **cámara** del anfitrión en Windows o Mac — Docker no la ve |

En una casa lo natural es correrlo sin contenedor y que el aparato entre por el
cable. El contenedor es para **hostearlo**: el aparato llega por WiFi y la
familia entra al portal desde donde sea.

> Al exponerlo, `DANTE_PANEL_HOST=0.0.0.0` y **Auth0 deja de ser opcional**. El
> agente avisa fuerte al arrancar si queda expuesto sin login.

## Privacidad

- La memoria es **un archivo SQLite** en tu disco. Se respalda copiándolo y se
  borra eliminándolo.
- Solo el turno de conversación viaja a la API. Las transcripciones, los rostros
  y los hechos se quedan.
- El `.env` está en `.gitignore` y **nunca** debe subirse. Para compartir el
  proyecto está `.env.example`, que no tiene ningún valor real.
- La cara **no se guarda como foto**: solo un vector de 128 números del que no
  se puede reconstruir el rostro.

Lo que se protege, lo que se corrigió en la auditoría y lo que todavía falta
está en [`SECURITY.md`](SECURITY.md).

---

## Estructura

```
dante/
  cli.py          comandos
  config.py       lee el .env
  proveedor.py    de dónde salen los modelos (OpenAI u OpenRouter)
  transporte.py   marcos entre el PC y el aparato: cable y WiFi
  sesion.py       el agente: orquesta voz, herramientas y memoria
  memoria.py      SQLite: personas, hechos, episodios, eventos
  consolidar.py   convierte una conversación en hechos, al cerrar
  diario.py       el saludo del día
  mundo.py        hora, clima, búsqueda web
  vision.py       cámara, detección y reconocimiento de rostros
  ajustes.py      la configuración que arma la personalidad
  panel.py        el portal
  auth.py         login con Auth0, opcional
  trabajos.py     dispara las tareas de Trigger.dev
  setup.py        configura el WiFi del aparato

firmware/         sketches de Arduino
src/trigger/      tareas de Trigger.dev
```

| Sketch | Para qué |
|---|---|
| `dante_puente` | **El de verdad**: audio por USB y WiFi, botón, y la cara |
| `dante_scan` | Prueba de vida: luz, PSRAM, escaneo del bus I2C |
| `dante_audio` | Audio en la placa: tono, grabar y reproducir |
| `dante_regs` | Diagnóstico: lee de vuelta los registros del ES7210 |

### Si el micrófono deja de captar

Sirve para distinguir un chip dañado de un cable flojo, que se ven igual desde
afuera:

1. `dante_scan` — ¿responden `0x18` y `0x41` por I2C? Si sí, los chips viven.
2. `dante_regs` — ¿los registros quedan escritos? Si sí, está bien configurado.
3. `dante_audio` — ¿el nivel del micrófono es cero?

Si los tres dan eso, el problema **no es electrónico**: el control y los datos
van por conectores distintos del mismo módulo. Reasentar el módulo de audio.
