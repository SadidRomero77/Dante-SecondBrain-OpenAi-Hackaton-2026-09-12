# Dante — segundo cerebro

Un agente de voz con memoria que vive en un aparato físico sobre la mesa.
Escucha, recuerda, ve, y tiene cara.

Hardware: kit LAFVIN AI Chatbot (ESP32-S3). Cerebro: tu PC. Modelos: OpenAI.

- Plan del proyecto: `PLAN.html`
- Datos medidos de la placa: `HARDWARE.md`
- Contrato aparato ⇄ PC: `PROTOCOL.md`

> Dante no es un dispositivo médico. No diagnostica, no aconseja tratamientos
> y no reemplaza a nadie. Es un compañero de memoria cotidiana y una
> herramienta para quien cuida.

## Qué hace

| | |
|---|---|
| **Conversa** | Voz a voz por `gpt-realtime-2`. Primera respuesta en menos de un segundo. |
| **Recuerda** | Cada hecho con su fecha, su fuente y su confianza. Búsqueda por significado. |
| **No inventa** | Sobre la vida de la persona solo afirma lo que devuelve la memoria. Si no lo tiene, lo dice. |
| **Ve** | Reconoce caras registradas y describe lo que hay enfrente, cuando se lo piden. |
| **Se entera** | Hora en cualquier ciudad, clima y búsqueda web con Exa. |
| **Saluda** | Al empezar el día cuenta qué pasó ayer, quién viene y qué medicamento toca. |
| **Tiene cara** | Dos ojos animados en la pantalla, y texto para recordatorios y confirmaciones. |

## Instalación (Windows)

El servidor corre en **Windows**, no en WSL: WSL no ve los puertos USB.

```
cd C:\Users\sadid\SecondBrain
uv sync
copy .env.example .env      REM y pega tu OPENAI_API_KEY
uv run dante doctor
```

## Comandos

```
dante doctor           Revisa el entorno. No gasta creditos.
dante smoke            Prueba la Realtime API con una conversacion de texto.
dante monitor          Lee el puerto serie del aparato.
dante puente           Microfono -> PC -> parlante, sin modelo de por medio.
dante semilla          Carga una persona de ejemplo con su pasado.
dante memoria          Muestra que recuerda Dante ahora mismo.

dante hablar           Conversar. Manten apretado BOOT, habla, suelta.
dante hablar --panel   Ademas abre el panel web en http://127.0.0.1:8800
dante hablar --diario  Fuerza el saludo del dia
```

## El panel

`dante hablar --panel` abre una página donde se ve **lo que Dante está
viendo**, con las caras marcadas y con nombre, la conversación en vivo, y dos
formas de hablarle: escribiendo, o manteniendo apretada la barra espaciadora
para usar el micrófono del computador.

Corre dentro del mismo proceso que la sesión: ni la cámara ni el puerto serie
se pueden abrir dos veces, así que el panel no es otro programa sino una
ventana sobre el que ya está corriendo.

## Firmware

Sketches de Arduino en `firmware/`. Los ajustes de placa están en el
encabezado de cada uno y en `HARDWARE.md`.

| Sketch | Para qué |
|---|---|
| `dante_scan` | Prueba de vida: luz, PSRAM, escaneo del bus I2C |
| `dante_audio` | Audio en la placa: tono, grabar y reproducir |
| `dante_puente` | **El de verdad**: audio por USB, botón, y la cara |

## Estructura

```
dante/
  cli.py          comandos
  config.py       lee el .env
  transporte.py   marcos entre el PC y el aparato (PROTOCOL.md)
  sesion.py       el agente: orquesta voz, herramientas y memoria
  memoria.py      SQLite: personas, hechos, episodios, eventos
  consolidar.py   convierte una conversacion en hechos, al cerrar
  diario.py       el saludo del dia
  mundo.py        hora, clima, busqueda web
  vision.py       camara, deteccion y reconocimiento de rostros
  panel.py        el panel web
```
