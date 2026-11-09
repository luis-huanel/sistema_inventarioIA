"""Deteccion y clasificacion de celulares en una foto.

Metodos para encontrar los equipos (en este orden):
  1. "cajas":   el cliente envia los recuadros ya calculados.
  2. "yolo":    si esta instalado ultralytics, YOLO detecta la clase "cell phone".
  3. "opencv":  detector propio (fondo liso), no necesita instalar nada.
  4. "imagen_completa": ultimo recurso: la foto completa es un solo equipo.
Luego el clasificador entrenado (HOG + color + SVM) dice que modelo es cada uno.
"""
import base64
import os

import cv2
import joblib
import numpy as np

from entrenar_celulares import MODELOS, caracteristicas

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_MODELO = os.path.join(BASE, "modelo_celulares.joblib")
UMBRAL = float(os.environ.get("UMBRAL", "0.70"))   # bajo esto: "por revisar"
PESOS_YOLO = os.environ.get("YOLO_PESOS", "yolov8n.pt")

_modelo = None
_yolo = None
_yolo_probado = False


# Cargar el modelo entrenado desde disco toma tiempo: se hace UNA vez y se guarda
# en la variable global _modelo (patron llamado 'carga perezosa').
def modelo():
    global _modelo
    if _modelo is None:
        _modelo = joblib.load(RUTA_MODELO)
    return _modelo


# Un 'recorte' es la imagen de UN celular. predict_proba da una probabilidad por
# modelo; la mayor es la prediccion y su valor es la 'confianza'.
def clasificar_recorte(bgr):
    """Devuelve (nombre_o_None, confianza, mejor_nombre)."""
    rec = cv2.resize(bgr, (64, 128))
    rgb = cv2.cvtColor(rec, cv2.COLOR_BGR2RGB)
    prob = modelo().predict_proba([caracteristicas(rgb)])[0]
    k = int(prob.argmax())
    nombre = MODELOS[k]
    return (nombre if prob[k] >= UMBRAL else None), float(prob[k]), nombre


def _cajas_yolo(img):
    """Cajas de celulares con YOLO, o None si no esta disponible."""
    global _yolo, _yolo_probado
    if not _yolo_probado:
        _yolo_probado = True
        try:
            from ultralytics import YOLO
            _yolo = YOLO(PESOS_YOLO)
        except Exception:
            _yolo = None
    if _yolo is None:
        return None
    r = _yolo(img, conf=0.40, verbose=False)[0]
    cajas = []
    for c in r.boxes:
        if r.names[int(c.cls)] == "cell phone":
            cajas.append([int(v) for v in c.xyxy[0]])
    return cajas


def _cajas_opencv(img):
    """Detector SIN instalar nada extra (solo OpenCV): encuentra objetos sobre un
    fondo liso, como los celulares de un estante o de una mesa.

    Idea: el color que mas se repite en la foto es el fondo; todo lo que se
    aleja de ese color es "objeto". Luego se separan los objetos y se dejan los
    que tienen forma alargada, como un celular. No es tan potente como YOLO
    (con fondos muy cargados puede equivocarse), pero evita tomar la foto
    completa como un solo equipo.
    """
    alto, ancho = img.shape[:2]
    k = 1000 / max(alto, ancho)
    chica = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img.copy()
    esc = 1 / k if k < 1 else 1.0
    sh, sw = chica.shape[:2]
    suave = cv2.GaussianBlur(chica, (5, 5), 0)
    fondo = np.median(suave.reshape(-1, 3), axis=0)            # color del fondo
    mascara = ((np.linalg.norm(suave.astype(float) - fondo, axis=2) > 38) * 255).astype(np.uint8)
    # quitar las repisas: filas casi completas distintas al fondo
    mascara[mascara.mean(axis=1) / 255 > 0.85, :] = 0
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))   # quita ruido
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))  # une huecos
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cajas = []
    for c in contornos:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh / (sw * sh)
        if 0.004 < area < 0.25 and 0.9 < bh / bw < 3.5:        # tamano y forma de celular
            cajas.append([int(x * esc), int(y * esc), int((x + bw) * esc), int((y + bh) * esc)])
    cajas.sort(key=lambda b: (b[1] // max(1, alto // 4), b[0]))  # orden de lectura
    return cajas


def _anotar(img, detalle):
    out = img.copy()
    grosor = max(2, img.shape[1] // 400)
    escala = max(0.4, img.shape[1] / 2800)
    for d in detalle:
        x0, y0, x1, y1 = d["caja"]
        ok = d["estado"] == "identificado"
        color = (60, 160, 60) if ok else (130, 130, 130)
        cv2.rectangle(out, (x0, y0), (x1, y1), color, grosor)
        txt = f"{d['modelo']} {d['confianza']:.0%}" if ok else f"? {d['confianza']:.0%}"
        cv2.putText(out, txt, (x0 + 3, max(14, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    escala, color, max(1, grosor - 1), cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


# Funcion principal: 1) encontrar celulares, 2) clasificar cada uno,
# 3) contar por modelo, 4) dibujar los recuadros sobre la foto.
def analizar(img, cajas=None, margen=0.05):
    """Analiza una foto (BGR). Devuelve un dict con detalle y conteo."""
    alto, ancho = img.shape[:2]
    metodo = "cajas"
    if not cajas:
        cajas = _cajas_yolo(img)
        metodo = "yolo"
    if not cajas:
        cajas = _cajas_opencv(img)
        metodo = "opencv"
    if not cajas:
        cajas = [[0, 0, ancho, alto]]
        metodo = "imagen_completa"
    detalle = []
    for x0, y0, x1, y1 in cajas:
        bw, bh = x1 - x0, y1 - y0
        a = max(0, int(x0 - margen * bw)); b = max(0, int(y0 - margen * bh))
        c = min(ancho, int(x1 + margen * bw)); d = min(alto, int(y1 + margen * bh))
        if c - a < 8 or d - b < 8:
            continue
        nombre, conf, mejor = clasificar_recorte(img[b:d, a:c])
        detalle.append({"caja": [int(x0), int(y0), int(x1), int(y1)],
                        "modelo": nombre, "mejor_candidato": mejor,
                        "confianza": round(conf, 4),
                        "estado": "identificado" if nombre else "por_revisar"})
    conteo = {m: 0 for m in MODELOS}
    for d in detalle:
        if d["modelo"]:
            conteo[d["modelo"]] += 1
    return {"metodo": metodo, "detectados": len(detalle),
            "identificados": sum(conteo.values()),
            "por_revisar": sum(d["estado"] == "por_revisar" for d in detalle),
            "conteo": conteo, "detalle": detalle,
            "imagen_anotada": _anotar(img, detalle)}
