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
            self.cap = cv2.VideoCapture(self.indice, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
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


class Rostros:
    """Detecta caras y reconoce las que estan registradas.

    Detector: Haar, que viene dentro de opencv. Reconocedor: LBPH, de
    opencv-contrib. Los dos corren en el PC: ni una llamada a la red, asi que
    saber quien esta enfrente no cuesta ni dinero ni segundos.
    """

    def __init__(self):
        import cv2

        self.detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.reconocedor = cv2.face.LBPHFaceRecognizer_create()
        self.etiquetas: dict[int, str] = {}
        self.entrenado = False
        self.cargar()

    # ---------------------------------------------------------- registro --
    def guardar_muestra(self, cuadro, nombre: str) -> int:
        """Recorta la cara mas grande del cuadro y la guarda como muestra."""
        import cv2

        caras = self.detectar(cuadro)
        if not caras:
            return 0
        x, y, w, h = max(caras, key=lambda r: r[2] * r[3])
        gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
        recorte = cv2.resize(gris[y:y + h, x:x + w], (200, 200))

        carpeta = CARAS / _limpio(nombre)
        carpeta.mkdir(parents=True, exist_ok=True)
        n = len(list(carpeta.glob("*.png")))
        cv2.imwrite(str(carpeta / f"{n:03d}.png"), recorte)
        return n + 1

    def entrenar(self) -> int:
        import cv2

        muestras, etiquetas = [], []
        self.etiquetas = {}
        for i, carpeta in enumerate(sorted(p for p in CARAS.glob("*") if p.is_dir())):
            self.etiquetas[i] = carpeta.name.replace("_", " ")
            for f in carpeta.glob("*.png"):
                img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    muestras.append(img)
                    etiquetas.append(i)

        if len(set(etiquetas)) < 1 or not muestras:
            self.entrenado = False
            return 0

        self.reconocedor.train(muestras, np.array(etiquetas))
        MODELO_CARAS.parent.mkdir(parents=True, exist_ok=True)
        self.reconocedor.write(str(MODELO_CARAS))
        (CARAS / "etiquetas.txt").write_text(
            "\n".join(f"{k}\t{v}" for k, v in self.etiquetas.items()), encoding="utf-8")
        self.entrenado = True
        return len(muestras)

    def cargar(self) -> bool:
        if not MODELO_CARAS.exists():
            return False
        try:
            self.reconocedor.read(str(MODELO_CARAS))
            f = CARAS / "etiquetas.txt"
            if f.exists():
                for linea in f.read_text(encoding="utf-8").splitlines():
                    if "\t" in linea:
                        k, v = linea.split("\t", 1)
                        self.etiquetas[int(k)] = v
            self.entrenado = True
            return True
        except Exception:
            return False

    # ------------------------------------------------------------- mirar --
    def detectar(self, cuadro) -> list[tuple[int, int, int, int]]:
        import cv2

        gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
        gris = cv2.equalizeHist(gris)
        caras = self.detector.detectMultiScale(gris, 1.15, 6, minSize=(80, 80))
        return [tuple(int(v) for v in c) for c in caras]

    def quien(self, cuadro) -> list[dict]:
        """Caras en el cuadro, con nombre cuando hay confianza suficiente."""
        import cv2

        salida = []
        caras = self.detectar(cuadro)
        if not caras:
            return salida

        gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
        for (x, y, w, h) in caras:
            item = {"caja": [x, y, w, h], "nombre": None, "certeza": 0.0}
            if self.entrenado:
                try:
                    recorte = cv2.resize(gris[y:y + h, x:x + w], (200, 200))
                    etiqueta, distancia = self.reconocedor.predict(recorte)
                    if distancia <= UMBRAL:
                        item["nombre"] = self.etiquetas.get(etiqueta)
                        item["certeza"] = round(max(0.0, 1.0 - distancia / 100.0), 2)
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
