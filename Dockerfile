# Dante, empaquetado para correr en cualquier parte.
#
# Que hace el contenedor y que no:
#   SI  el agente, la memoria, el portal, la busqueda y los trabajos
#   SI  el aparato conectado por WiFi
#   NO  el aparato por cable USB, salvo en Linux pasando el dispositivo
#   NO  la camara del anfitrion en Windows o Mac (Docker no la ve)
#
# En una casa, lo natural es correrlo sin contenedor y que el aparato entre por
# el cable. El contenedor es para hostearlo: el aparato llega por WiFi y la
# familia entra al portal desde donde sea.

FROM python:3.12-slim AS base

# opencv necesita estas dos; sin ellas importa pero revienta al primer cuadro.
# tzdata es para la hora local: sin ella el contenedor vive en UTC y un
# recordatorio de las 8:00 suena a las 3 de la madrugada en Bogota.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# Un usuario sin privilegios: si alguien se escapa del proceso, que no sea root.
RUN useradd --create-home --uid 10001 dante
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Las dependencias primero y el codigo despues: asi editar el codigo no obliga
# a reinstalar todo.
COPY pyproject.toml README.md ./
RUN uv pip install --system --no-cache -e . || \
    uv pip install --system --no-cache \
        "openai>=1.60" "websockets>=13" "pyserial>=3.5" "python-dotenv>=1.0" \
        "numpy>=1.26" "tzdata>=2024.1" "opencv-contrib-python-headless>=4.10" \
        "pillow>=10.0" "fastapi>=0.115" "uvicorn>=0.32"

# Los dos modelos de caras (38 MB) se bajan aqui, no al arrancar. Bajarlos en
# caliente falla en silencio si la red del servidor no coopera, y el sintoma
# es "nadie a la vista" con una cara perfectamente visible en pantalla.
RUN mkdir -p /app/data/modelos \
 && curl -fsSL -o /app/data/modelos/yunet.onnx \
      https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx \
 && curl -fsSL -o /app/data/modelos/sface.onnx \
      https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

COPY dante/ ./dante/
COPY .env.example ./

# La memoria de cada cuenta, las cuentas, los recados y el secreto de las
# sesiones viven aqui. Montalo como
# volumen o se pierden al recrear el contenedor.
RUN mkdir -p /datos && chown -R dante:dante /app /datos
USER dante

# TZ se puede cambiar al lanzar el contenedor (-e TZ=...) para otra ciudad.
ENV DANTE_DB=/datos/dante.db \
    DANTE_PANEL_HOST=0.0.0.0 \
    TZ=America/Bogota \
    PYTHONUNBUFFERED=1

EXPOSE 8800 8770

# Sin cable: el aparato entra por WiFi y la gente por el portal.
# En un servidor no hay aparato al que enchufarse ni camara que mirar: se
# sirve solo el portal, y cada visitante trae lo suyo por el navegador.
CMD ["python", "-m", "dante", "servir", "--puerto", "8800"]
