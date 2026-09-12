# Dante — segundo cerebro

Agente de voz con memoria, que vive en un aparato físico sobre la mesa.
Hardware: kit LAFVIN AI Chatbot (ESP32-S3). Cerebro: tu PC.

Plan completo del proyecto: `PLAN.html`

> Dante no es un dispositivo médico. No diagnostica, no aconseja tratamientos
> y no reemplaza a nadie. Es un compañero de memoria cotidiana.

## Estado

En construcción. Paso actual: **fase 0 — validar entorno y hardware.**

## Instalación (Windows)

El servidor corre en **Windows**, no en WSL: WSL no ve los puertos USB.

```
cd C:\Users\sadid\SecondBrain
uv venv
uv pip install -e .
copy .env.example .env      REM y pega tu OPENAI_API_KEY
.venv\Scripts\dante doctor
.venv\Scripts\dante smoke
```

## Firmware

Sketches de Arduino en `firmware/`. Ajustes de placa en el encabezado de cada uno.

| Sketch | Para qué |
|---|---|
| `dante_scan` | Prueba de vida: luz, PSRAM, y escaneo del bus I2C |
