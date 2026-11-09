"""
probar_ocr.py  -  Prueba el OCR con FOTOS SIMULADAS de las cajas.

No siempre tienes la caja impresa a mano, asi que este programa "ensucia" las
imagenes limpias para parecerse a una foto de celular: inclinada, en
perspectiva, con poca luz, desenfocada, con ruido y comprimida como JPG.
Luego comprueba que el OCR igual encuentre el modelo y la cantidad correctos.

    python herramientas/probar_ocr.py
"""
import os
import sys

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import ocr  # noqa: E402

CAJAS = {  # archivo: (modelo esperado, cantidad esperada)
    "caja_Galaxy_A15.png": ("Galaxy A15", 6),
    "caja_iPhone_13.png": ("iPhone 13", 3),
    "caja_Redmi_Note_13.png": ("Redmi Note 13", 5),
}
CATALOGO = [
    {"id": 1, "nombre": "Galaxy A15", "marca": "Samsung", "precio": 129990},
    {"id": 2, "nombre": "iPhone 13", "marca": "Apple", "precio": 599990},
    {"id": 3, "nombre": "Redmi Note 13", "marca": "Xiaomi", "precio": 159990},
]


# ---- cada funcion recibe una imagen y devuelve la imagen "ensuciada" ----
def reducir(img):                      # foto de baja resolucion
    return cv2.resize(img, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)


def girar(img, grados=7):              # telefono inclinado
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), grados, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderValue=(90, 90, 90))


def perspectiva(img):                  # foto tomada "de costado"
    h, w = img.shape[:2]
    origen = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    destino = np.float32([[60, 40], [w - 20, 0], [w - 70, h - 30], [30, h]])
    m = cv2.getPerspectiveTransform(origen, destino)
    return cv2.warpPerspective(img, m, (w, h), borderValue=(90, 90, 90))


def poca_luz(img):                     # habitacion oscura + sombra al costado
    h, w = img.shape[:2]
    sombra = np.tile(np.linspace(0.35, 1.0, w), (h, 1))[..., None]
    return (img * 0.6 * sombra).astype(np.uint8)


def desenfocar(img):                   # movimiento de la mano
    return cv2.GaussianBlur(img, (0, 0), 2.2)


def ruido(img):                        # sensor de camara barato
    r = np.random.default_rng(1).normal(0, 14, img.shape)
    return np.clip(img.astype(float) + r, 0, 255).astype(np.uint8)


def jpg(img):                          # compresion fuerte, como WhatsApp
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 40])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def combinada(img):                    # varias cosas a la vez (caso dificil)
    return jpg(ruido(poca_luz(girar(reducir(img), -5))))


PRUEBAS = [("limpia", lambda i: i), ("baja resolucion", reducir), ("girada 7 grados", girar),
           ("perspectiva", perspectiva), ("poca luz", poca_luz), ("desenfocada", desenfocar),
           ("ruido", ruido), ("jpg comprimido", jpg), ("todo junto", combinada)]


def main(guardar=None):
    ok = total = 0
    for archivo, (modelo, cant) in CAJAS.items():
        base = cv2.imread(os.path.join(RAIZ, "cajas_de_prueba", archivo))
        for nombre, f in PRUEBAS:
            foto = f(base)
            if guardar:
                cv2.imwrite(os.path.join(guardar, f"{archivo[:-4]}__{nombre.replace(' ', '_')}.jpg"), foto)
            r = ocr.leer_caja(foto, CATALOGO)
            bien = r["modelo"] == modelo and r["cantidad_leida"] == cant
            ok += bien
            total += 1
            print(f"{'OK ' if bien else 'FALLA'} {archivo:24s} {nombre:16s} -> "
                  f"{r['modelo']} x {r['cantidad_leida']}  (confianza {r['confianza']})")
    print(f"\nAciertos: {ok}/{total}")
    return ok, total


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
