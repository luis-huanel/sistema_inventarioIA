"""
generar_cajas.py  -  Crea las CAJAS DE PRUEBA (ficticias) para practicar el OCR.

Para que sirve
--------------
Para probar la lectura OCR necesitas "una caja de celular" que puedas
fotografiar. Este programa dibuja la cara frontal de una caja por cada modelo
del catalogo y la guarda como imagen (PNG) y como PDF para imprimir.

Que dice cada caja (y por que)
------------------------------
  * Marca y modelo grandes     -> el OCR las usa para saber QUE celular es.
  * "CANTIDAD EN CAJA: N"      -> el OCR la usa para saber CUANTOS vienen.
  * SKU y codigo de barras     -> adorno realista (el codigo de barras NO se
                                  lee, es solo dibujo y su numero es inventado).
  * "CAJA DE PRUEBA - FICTICIA"-> aclara que no es un producto real.

Las cajas no tienen logos ni disenos de las marcas reales: solo texto.

Como usarlo
-----------
    python herramientas/generar_cajas.py
Crea la carpeta  cajas_de_prueba/  con un PNG por modelo y un PDF con las tres.
"""
import os
import random

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- rutas
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "cajas_de_prueba")
IMAGENES = os.path.join(RAIZ, "static", "imagenes")
EJEMPLOS = os.path.join(RAIZ, "static", "ejemplos")
FUENTE_NEGRITA = "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf"
FUENTE_NORMAL = "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf"
# Si ejecutas esto en Windows, cambia las rutas anteriores por una fuente
# instalada, por ejemplo  "C:/Windows/Fonts/calibrib.ttf"  y  "calibri.ttf".

# ---------------------------------------------------------------- datos de las cajas
# "cantidad" es lo que dice la etiqueta "CANTIDAD EN CAJA". Es el dato que el
# sistema suma al stock cuando la caja se ingresa.
CAJAS = [
    dict(archivo="caja_Galaxy_A15", marca="SAMSUNG", modelo="Galaxy A15",
         specs="128 GB  |  4 GB RAM  |  6,5 pulgadas", color="Color: Negro",
         cantidad=6, sku="SAM-A15-128-NEG", barras="0 780123 456781",
         acento=(20, 40, 120), imagen="Galaxy_A15_frente.png"),
    dict(archivo="caja_iPhone_13", marca="APPLE", modelo="iPhone 13",
         specs="128 GB  |  4 GB RAM  |  6,1 pulgadas", color="Color: Rosa",
         cantidad=3, sku="APL-IP13-128-ROS", barras="0 780123 456798",
         acento=(150, 40, 80), imagen="iPhone_13_frente.png"),
    dict(archivo="caja_Redmi_Note_13", marca="XIAOMI", modelo="Redmi Note 13",
         specs="128 GB  |  6 GB RAM  |  6,67 pulgadas", color="Color: Verde azulado",
         cantidad=5, sku="XIA-RN13-128-VAZ", barras="0 780123 456804",
         acento=(0, 110, 100), imagen="Redmi_Note_13_frente.png"),
]

ANCHO, ALTO = 1200, 1700


def fuente(nombre, tam):
    return ImageFont.truetype(nombre, tam)


def centrar(dib, y, texto, f, color=(0, 0, 0)):
    """Escribe 'texto' centrado horizontalmente en la altura y."""
    ancho = dib.textlength(texto, font=f)
    dib.text(((ANCHO - ancho) / 2, y), texto, font=f, fill=color)


def codigo_de_barras(dib, x, y, ancho, alto, semilla):
    """Dibuja barras negras de grosor aleatorio (solo decoracion)."""
    azar = random.Random(semilla)
    pos = x
    while pos < x + ancho:
        grosor = azar.choice([3, 3, 6, 9])
        dib.rectangle((pos, y, min(pos + grosor, x + ancho), y + alto), fill=(0, 0, 0))
        pos += grosor + azar.choice([3, 6, 9])


def dibujar_caja(c):
    """Devuelve la imagen (PIL) de una caja."""
    img = Image.new("RGB", (ANCHO, ALTO), (246, 243, 236))      # carton claro
    d = ImageDraw.Draw(img)
    acento = c["acento"]

    # marco y franja superior de color
    d.rectangle((30, 30, ANCHO - 30, ALTO - 30), outline=acento, width=10)
    d.rectangle((40, 40, ANCHO - 40, 170), fill=acento)
    centrar(d, 70, "CAJA DE PRUEBA  -  FICTICIA", fuente(FUENTE_NEGRITA, 64), (255, 255, 255))

    # marca y modelo (texto grande y negro: lo mas facil de leer para el OCR)
    centrar(d, 230, c["marca"], fuente(FUENTE_NEGRITA, 120))
    centrar(d, 380, c["modelo"], fuente(FUENTE_NEGRITA, 170))

    # dibujo esquematico del celular (adorno)
    ruta = os.path.join(IMAGENES, c["imagen"])
    if os.path.exists(ruta):
        tel = Image.open(ruta).convert("RGBA")
        tel = tel.resize((int(tel.width * 560 / tel.height), 560))
        img.paste(tel, ((ANCHO - tel.width) // 2, 620), tel)

    # especificaciones
    centrar(d, 1210, c["specs"], fuente(FUENTE_NORMAL, 64))
    centrar(d, 1290, c["color"], fuente(FUENTE_NORMAL, 64))

    # etiqueta blanca con la cantidad (el dato que se calcula)
    d.rectangle((90, 1390, ANCHO - 90, 1500), fill=(255, 255, 255), outline=(0, 0, 0), width=4)
    centrar(d, 1419, f"CANTIDAD EN CAJA: {c['cantidad']} UNIDADES", fuente(FUENTE_NEGRITA, 62))

    # SKU y codigo de barras
    d.text((100, 1540), f"SKU: {c['sku']}", font=fuente(FUENTE_NORMAL, 48), fill=(0, 0, 0))
    codigo_de_barras(d, 640, 1535, 440, 75, semilla=c["sku"])
    d.text((640, 1612), c["barras"], font=fuente(FUENTE_NORMAL, 32), fill=(0, 0, 0))
    return img


def main():
    os.makedirs(SALIDA, exist_ok=True)
    os.makedirs(EJEMPLOS, exist_ok=True)
    paginas = []
    for c in CAJAS:
        img = dibujar_caja(c)
        img.save(os.path.join(SALIDA, c["archivo"] + ".png"))
        # copia para el boton "Usar caja de ejemplo" del panel web
        img.resize((ANCHO // 2, ALTO // 2), Image.LANCZOS).save(
            os.path.join(EJEMPLOS, c["archivo"] + ".png"))
        paginas.append(img)
    # PDF: una caja por pagina, lista para imprimir
    paginas[0].save(os.path.join(SALIDA, "cajas_de_prueba.pdf"), save_all=True,
                    append_images=paginas[1:], resolution=150.0)
    print("Cajas creadas en", SALIDA)


if __name__ == "__main__":
    main()
