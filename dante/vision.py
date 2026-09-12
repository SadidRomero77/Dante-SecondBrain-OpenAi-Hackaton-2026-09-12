"""Los ojos de Dante: la camara del PC.

Deliberadamente opcional. Si no hay camara configurada, todo lo demas del
agente funciona igual: la identidad de una persona en la memoria es su NOMBRE,
y la cara es solo un identificador que se le engancha encima. Dante aprende
nombres conversando y puede pasar la vida sin ver a nadie.

Dos niveles, muy distintos en costo:
  - Reconocer una cara conocida: local, instantaneo, sin llamar a nadie.
  - Describir lo que hay enfrente: se manda el cuadro al modelo. Se hace solo
    cuando alguien lo pide.
"""
from __future__ import annotations

import base64
import threading
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np

from . import config, memoria


def _callar_opencv() -> None:
    """OpenCV 5 avisa en cada carga que el motor nuevo ignora setPreferableTarget.
    No podemos hacer nada al respecto y ensucia la consola."""
    import os
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    try:
        import cv2
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass

CARAS = config.RAIZ / "data" / "caras"
MODELO_CARAS = config.RAIZ / "data" / "caras" / "modelo.yml"

# Cuanto tiene que confiar el reconocedor para decir un nombre. LBPH devuelve
# distancia: mas bajo es mas parecido. Por encima de esto preferimos decir "no
# se quien es" antes que equivocarnos de persona, que con este usuario es una
# equivocacion cara.
UMBRAL = 70.0


class Camara:
    """Captura en un hilo aparte y guarda siempre el ultimo cuadro.

    Si leyeramos la camara cuando alguien pregunta, la primera lectura tarda
    cerca de un segundo. Asi el cuadro siempre esta listo.
    """

    def __init__(self, indice: int | str = 0):
        self.indice = int(indice) if str(indice).isdigit() else indice
        self.cap = None
        self.cuadro = None
        self.corriendo = False
        self.hilo: threading.Thread | None = None
        self.error = ""
        self._lock = threading.Lock()

    def arrancar(self) -> bool:
        import cv2

        try:
            # DirectShow solo sirve para camaras conectadas al PC. Con una
            # direccion de red (una ESP32-CAM, por ejemplo) no falla rapido:
            # se queda esperando. Por eso ni lo intentamos en ese caso.
            if isinstance(self.indice, int):
                self.cap = cv2.VideoCapture(self.indice, cv2.CAP_DSHOW)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.indice)
            else:
                self.cap = cv2.VideoCapture(self.indice)
            if not self.cap.isOpened():
                self.error = f"no pude abrir la camara {self.indice}"
                return False
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            return False

        self.corriendo = True
        self.hilo = threading.Thread(target=self._bucle, daemon=True)
        self.hilo.start()

        # Esperar al primer cuadro, no un rato fijo: tras fijar la resolucion
        # la camara puede tardar mas de un segundo en dar el primero.
        limite = time.time() + 5.0
        while time.time() < limite:
            if self.ultimo() is not None:
                return True
            time.sleep(0.1)
        self.error = "la camara abrio pero no entrego ningun cuadro en 5 s"
        return False

    def _bucle(self) -> None:
        while self.corriendo:
            ok, c = self.cap.read()
            if ok:
                with self._lock:
                    self.cuadro = c
            else:
                time.sleep(0.05)

    def ultimo(self):
        with self._lock:
            return None if self.cuadro is None else self.cuadro.copy()

    def parar(self) -> None:
        self.corriendo = False
        if self.hilo:
            self.hilo.join(timeout=1.0)
        if self.cap:
            self.cap.release()


MODELOS = config.RAIZ / "data" / "modelos"
YUNET = MODELOS / "yunet.onnx"
SFACE = MODELOS / "sface.onnx"

URLS = {
    YUNET: "https://github.com/opencv/opencv_zoo/raw/main/models/"
           "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    SFACE: "https://github.com/opencv/opencv_zoo/raw/main/models/"
           "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def descargar_modelos() -> bool:
    """Baja los dos modelos si faltan. Son 38 MB y no van al repositorio."""
    import urllib.request

    MODELOS.mkdir(parents=True, exist_ok=True)
    for destino, url in URLS.items():
        if destino.exists() and destino.stat().st_size > 1000:
            continue
        print(f"  bajando {destino.name}...")
        urllib.request.urlretrieve(url, destino)
    return all(p.exists() for p in URLS)


class Rostros:
    """Detecta caras con YuNet y las identifica con SFace.

    SFace devuelve un vector de 128 numeros por cara. Dos vectores de la misma
    persona se parecen; de personas distintas, no. Eso permite guardar la cara
    como un dato mas en la base, junto al nombre, en vez de tener que
    reentrenar un modelo cada vez que se registra a alguien.
    """

    # Umbral de coseno recomendado por opencv para SFace. Deliberadamente
    # exigente: ante duda preferimos decir que no sabemos quien es antes que
    # equivocarnos de persona, que con este usuario es una equivocacion cara.
    UMBRAL = 0.363

    def __init__(self):
        import cv2

        _callar_opencv()
        if not (YUNET.exists() and SFACE.exists()):
            descargar_modelos()
        self.detector = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.8, 0.3, 5000)
        self.identificador = cv2.FaceRecognizerSF.create(str(SFACE), "")
        self.conocidas: list[tuple[str, np.ndarray]] = []
        self.cargar()

    # ---------------------------------------------------------- registro --
    def cargar(self) -> int:
        """Trae de la base los vectores de las caras ya registradas."""
        c = memoria.abrir()
        self.conocidas = []
        for f in c.execute("SELECT nombre, cara FROM personas WHERE cara IS NOT NULL"):
            self.conocidas.append((f["nombre"], np.frombuffer(f["cara"], dtype="float32")))
        c.close()
        return len(self.conocidas)

    def registrar(self, cuadro, nombre: str) -> dict:
        """Guarda el vector de la cara mas grande del cuadro, contra un nombre."""
        caras = self._detectar_crudo(cuadro)
        if caras is None or len(caras) == 0:
            return {"ok": False, "motivo": "no veo ninguna cara"}
        if len(caras) > 1:
            return {"ok": False, "motivo": f"veo {len(caras)} caras; que quede una sola"}

        v = self._vector(cuadro, caras[0])
        c = memoria.abrir()
        memoria.registrar_persona(c, nombre)
        c.execute("UPDATE personas SET cara=? WHERE lower(nombre)=lower(?)",
                  (v.tobytes(), nombre.strip()))
        c.commit()
        c.close()
        self.cargar()
        return {"ok": True, "nombre": nombre, "registradas": len(self.conocidas)}

    # ------------------------------------------------------------- mirar --
    def _detectar_crudo(self, cuadro):
        h, w = cuadro.shape[:2]
        self.detector.setInputSize((w, h))
        _, caras = self.detector.detect(cuadro)
        return caras

    def _vector(self, cuadro, cara) -> np.ndarray:
        alineada = self.identificador.alignCrop(cuadro, cara)
        return self.identificador.feature(alineada).flatten().astype("float32")

    def detectar(self, cuadro) -> list[tuple[int, int, int, int]]:
        caras = self._detectar_crudo(cuadro)
        if caras is None:
            return []
        return [tuple(int(v) for v in c[:4]) for c in caras]

    def quien(self, cuadro) -> list[dict]:
        """Caras del cuadro, con nombre cuando el parecido es suficiente."""
        caras = self._detectar_crudo(cuadro)
        if caras is None:
            return []

        salida = []
        for cara in caras:
            x, y, w, h = (int(v) for v in cara[:4])
            item = {"caja": [x, y, w, h], "nombre": None, "certeza": 0.0}
            if self.conocidas:
                try:
                    v = self._vector(cuadro, cara)
                    mejor, punto = None, -1.0
                    for nombre, ref in self.conocidas:
                        d = float(v @ ref / (np.linalg.norm(v) * np.linalg.norm(ref)))
                        if d > punto:
                            mejor, punto = nombre, d
                    if punto >= self.UMBRAL:
                        item["nombre"] = mejor
                        item["certeza"] = round(punto, 3)
                except Exception:
                    pass
            salida.append(item)
        return salida


def _limpio(nombre: str) -> str:
    t = nombre.strip().lower()
    for a, b in zip("áéíóúñü", "aeiounu"):
        t = t.replace(a, b)
    return "".join(ch if ch.isalnum() else "_" for ch in t).strip("_") or "sin_nombre"


def a_base64(cuadro, ancho: int = 768) -> str:
    """El cuadro como JPEG en base64, listo para mandarselo al modelo."""
    import cv2

    h, w = cuadro.shape[:2]
    if w > ancho:
        cuadro = cv2.resize(cuadro, (ancho, int(h * ancho / w)))
    ok, buf = cv2.imencode(".jpg", cuadro, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


class Ojos:
    """Lo que el resto del agente usa. Nunca falla por no haber camara."""

    def __init__(self, indice: str = ""):
        self.indice = indice or config.CAMARA
        self.camara: Camara | None = None
        self.rostros: Rostros | None = None
        self.activa = False
        self.motivo = "sin camara configurada (pon DANTE_CAMARA en el .env)"

    def arrancar(self) -> bool:
        if not self.indice:
            return False
        self.camara = Camara(self.indice)
        if not self.camara.arrancar():
            self.motivo = self.camara.error
            return False
        try:
            self.rostros = Rostros()
        except Exception as e:
            self.motivo = f"no pude cargar el detector de caras: {e}"
            return False
        self.activa = True
        self.motivo = ""
        return True

    def parar(self) -> None:
        if self.camara:
            self.camara.parar()
        self.activa = False

    def quien_esta(self) -> dict:
        if not self.activa:
            return {"camara": False, "motivo": self.motivo}
        cuadro = self.camara.ultimo()
        if cuadro is None:
            return {"camara": True, "personas": [], "motivo": "sin imagen"}

        caras = self.rostros.quien(cuadro)
        conocidas = [c["nombre"] for c in caras if c["nombre"]]
        return {
            "camara": True,
            "caras_detectadas": len(caras),
            "conocidas": conocidas,
            "desconocidas": len(caras) - len(conocidas),
        }

    def cuadro_base64(self) -> str | None:
        if not self.activa:
            return None
        c = self.camara.ultimo()
        return a_base64(c) if c is not None else None
