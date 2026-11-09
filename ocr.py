"""
ocr.py  -  Lectura OCR de la CAJA de un celular.

IDEA GENERAL (para Ricardo)
===========================
Le sacas una foto a la caja y el sistema hace esto, en orden:

    1. leer_texto()          La foto se convierte en texto (OCR con Tesseract).
    2. identificar_modelo()  Del texto se deduce QUE celular es (Galaxy A15,
                             iPhone 13...) comparandolo con el catalogo.
    3. extraer_cantidad()    Del texto se saca CUANTAS unidades trae la caja
                             (la linea "CANTIDAD EN CAJA: 6 UNIDADES").
    4. calcular()            subtotal = cantidad leida x precio del catalogo.
    5. (en app.py)           Si el usuario lo confirma, se suma la cantidad al
                             stock y se guarda el movimiento en SQLite.

Todo lo que esta en este archivo es "logica pura": NO toca la base de datos ni
Flask. Por eso se puede probar solo:

        python ocr.py cajas_de_prueba/caja_iPhone_13.png

OCR = Optical Character Recognition = "reconocimiento optico de caracteres".
Un OCR NO entiende el texto, solo reconoce letras. Por eso hay que
"entenderlo" despues con las funciones 2 y 3.

FORMATOS ACEPTADOS: IMAGEN O DOCUMENTO PDF
==========================================
  * Cada IMAGEN (png, jpg, webp, bmp, tiff) es UNA caja.
  * Cada PAGINA de un PDF es UNA caja (un PDF de 3 paginas = 3 cajas).
  El formato se detecta por el CONTENIDO del archivo (sus primeros bytes), no
  por la extension, asi que un PDF renombrado a .jpg igual se reconoce.
  Los archivos nunca se mezclan: cada caja se lee, se calcula y se ingresa
  por separado. Ver detectar_formato() y extraer_cajas().

REQUISITOS
==========
  * pip install pytesseract opencv-python-headless numpy pymupdf
  * El programa Tesseract instalado en el computador:
      - Windows: instalador de UB Mannheim, https://github.com/UB-Mannheim/tesseract/wiki
                 Luego, si no queda en el PATH, define la variable de entorno
                 TESSERACT_CMD = C:\\Program Files\\Tesseract-OCR\\tesseract.exe
      - Linux:   sudo apt install tesseract-ocr tesseract-ocr-spa
"""
import difflib
import hashlib
import os
import re
import unicodedata

import cv2
import numpy as np

try:                      # Tesseract (programa externo). Es opcional.
    import pytesseract
except ImportError:
    pytesseract = None

try:                      # PyMuPDF: lee PDF sin instalar nada mas (funciona en Windows)
    import pymupdf
except ImportError:       # nombre antiguo del mismo paquete
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

# Si Tesseract no esta en el PATH (tipico en Windows), se indica aqui su ruta.

class OCRNoDisponible(RuntimeError):
    """No hay ningun motor OCR instalado (se muestra con instrucciones claras)."""


# Rutas donde el instalador de Tesseract suele dejar el programa en Windows
_RUTAS_TESSERACT = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


def _buscar_tesseract():
    """Ubica tesseract.exe: variable TESSERACT_CMD, luego el PATH, luego las
    rutas tipicas de Windows. Devuelve True si lo encontro y lo configura."""
    import shutil
    candidatos = [os.environ.get("TESSERACT_CMD"), shutil.which("tesseract")] + _RUTAS_TESSERACT
    for ruta in candidatos:
        if pytesseract is not None and ruta and os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            return True
    return False


_MOTOR = []        # se calcula una sola vez


def motor_ocr():
    """Elige el motor OCR disponible: 'tesseract', si no 'rapidocr' (se instala
    solo con pip, sin programas extra), y si no None.
    Se puede forzar con la variable de entorno OCR_MOTOR."""
    if _MOTOR:
        return _MOTOR[0]
    forzado = os.environ.get("OCR_MOTOR", "").lower()
    elegido = None
    if forzado != "rapidocr" and pytesseract is not None and _buscar_tesseract():
        try:
            pytesseract.get_tesseract_version()
            elegido = "tesseract"
        except Exception:
            elegido = None
    if elegido is None:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            elegido = "rapidocr"
        except ImportError:
            elegido = None
    _MOTOR.append(elegido)
    return elegido


def estado_ocr():
    """Resumen para /api/health y el panel."""
    m = motor_ocr()
    return {"disponible": m is not None, "motor": m, "pdf": pymupdf is not None,
            "ayuda": None if m else MENSAJE_INSTALAR}


MENSAJE_INSTALAR = ("No hay un motor OCR instalado. Solucion mas simple: ejecuta  "
                    "pip install rapidocr-onnxruntime  y reinicia el servidor. "
                    "Alternativa: instala Tesseract (https://github.com/UB-Mannheim/tesseract/wiki) "
                    "y reinicia; si no lo encuentra, define TESSERACT_CMD con la ruta de tesseract.exe.")

# Con que seguridad (0 a 1) aceptamos un modelo. Si es menor, se pide revision
# humana en vez de adivinar. Es la misma idea del umbral 0,70 del clasificador.
UMBRAL_MODELO = 0.70


# =====================================================================
# 0. Utilidades pequenas
# =====================================================================
def normalizar(texto):
    """Deja el texto en MAYUSCULAS y sin tildes, para poder compararlo.

    "Cantidad en caja: 6 Unidades"  ->  "CANTIDAD EN CAJA: 6 UNIDADES"
    (Tesseract a veces pierde las tildes, asi que las quitamos a proposito.)
    """
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.upper()


def hash_imagen(contenido_bytes):
    """Huella digital (SHA-256) de la foto.

    Sirve para NO sumar dos veces la misma caja: si alguien sube la misma
    foto otra vez, la huella es igual y el sistema lo detecta.
    """
    return hashlib.sha256(contenido_bytes).hexdigest()


def _idiomas():
    """Usa espanol+ingles si esta instalado el paquete 'spa'; si no, ingles."""
    try:
        return "spa+eng" if "spa" in pytesseract.get_languages() else "eng"
    except Exception:
        return "eng"


# =====================================================================
# 0b. FORMATO del archivo: imagen o documento (PDF)
# =====================================================================
def detectar_formato(contenido):
    r"""Mira los primeros bytes del archivo ("firma") y dice que es.

    Devuelve "pdf", "imagen" o None (formato no soportado).
    Cada formato empieza siempre con los mismos bytes:
        PDF  -> %PDF        PNG -> \x89PNG      JPG -> \xff\xd8\xff
        WEBP -> RIFF....WEBP  BMP -> BM         TIFF -> II*\x00 o MM\x00*
    """
    if contenido[:5] == b"%PDF-":
        return "pdf"
    if (contenido[:8] == b"\x89PNG\r\n\x1a\n" or contenido[:3] == b"\xff\xd8\xff"
            or (contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP")
            or contenido[:2] == b"BM" or contenido[:4] in (b"II*\x00", b"MM\x00*")):
        return "imagen"
    return None


def extraer_cajas(contenido, nombre="archivo", dpi=200):
    """Convierte UN archivo en una lista de cajas a leer (cada una por separado).

    - Imagen -> 1 caja.
    - PDF    -> 1 caja por pagina. Si la pagina ya trae texto digital (PDF
               creado en Word, etc.) se usa ese texto directamente, porque es
               exacto y mas rapido; si es una pagina escaneada o una foto
               dentro de un PDF, se convierte en imagen y se aplica el OCR.

    Cada caja es un diccionario:
        nombre, formato, pagina, img (OpenCV BGR), texto_previo (o None),
        huella (SHA-256 unica de ESA caja, para no ingresarla dos veces).
    Lanza ValueError con un mensaje claro si el archivo no sirve.
    """
    formato = detectar_formato(contenido)
    if formato is None:
        raise ValueError(f"'{nombre}': formato no soportado. Usa imagen (png, jpg, webp) o PDF.")
    if formato == "imagen":
        img = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"'{nombre}': no se pudo leer la imagen.")
        return [dict(nombre=nombre, formato="imagen", pagina=None, img=img,
                     texto_previo=None, huella=hash_imagen(contenido))]

    # ---- PDF ----
    if pymupdf is None:
        raise ValueError("Para leer PDF instala PyMuPDF:  pip install pymupdf")
    try:
        doc = pymupdf.open(stream=contenido, filetype="pdf")
    except Exception:
        raise ValueError(f"'{nombre}': el PDF esta danado o protegido con clave.")
    if doc.page_count == 0 or doc.page_count > 50:
        raise ValueError(f"'{nombre}': el PDF debe tener entre 1 y 50 paginas.")
    base = hash_imagen(contenido)
    cajas = []
    for n, pagina in enumerate(doc, start=1):
        texto = pagina.get_text().strip()
        pix = pagina.get_pixmap(dpi=dpi)                      # pagina -> imagen
        img = cv2.imdecode(np.frombuffer(pix.tobytes("png"), np.uint8), cv2.IMREAD_COLOR)
        cajas.append(dict(
            nombre=f"{nombre} (pagina {n})", formato="pdf", pagina=n, img=img,
            # texto digital solo si trae algo util; si no, se hace OCR
            texto_previo=texto if len(texto) > 15 else None,
            huella=f"{base}:p{n}"))
    return cajas


# =====================================================================
# 1. De la FOTO al TEXTO
# =====================================================================
def quitar_lineas(gris):
    """Borra las lineas largas (bordes de recuadros) de la imagen.

    Problema real: la etiqueta "CANTIDAD EN CAJA" esta dentro de un recuadro y
    Tesseract, al ver el borde, a veces ignora todo lo que hay adentro.
    Solucion: detectar las lineas rectas largas (horizontales y verticales)
    y pintarlas del color del fondo. Las letras no se tocan porque sus
    trazos son cortos.
    """
    alto, ancho = gris.shape
    invertida = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    lineas = np.zeros_like(invertida)
    # un "kernel" es una regla: aqui una barra horizontal y otra vertical larga
    for regla in [(ancho // 12, 1), (1, alto // 12)]:
        lineas |= cv2.morphologyEx(invertida, cv2.MORPH_OPEN,
                                   cv2.getStructuringElement(cv2.MORPH_RECT, regla))
    lineas = cv2.dilate(lineas, np.ones((3, 3), np.uint8))   # engrosar un poco
    limpia = gris.copy()
    limpia[lineas > 0] = int(np.median(gris))                # color del fondo
    return limpia


def preparar(img_bgr):
    """Mejora la foto para que Tesseract lea mejor. Devuelve varias versiones.

    Una foto real tiene sombras, poca luz, desenfoque, recuadros... Probamos
    varias "limpiezas" y juntamos todo lo que se logro leer.
    """
    # a) llevar la foto a un tamano "comodo" (lado mayor entre 1600 y 2400 px).
    #    Tesseract lee mal las letras muy chicas, pero tambien las gigantes
    #    (por ejemplo una pagina de PDF renderizada a alta resolucion).
    alto, ancho = img_bgr.shape[:2]
    lado = max(alto, ancho)
    if lado < 1600 or lado > 2400:
        k = 2000 / lado
        img_bgr = cv2.resize(img_bgr, None, fx=k, fy=k,
                             interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)

    # b) pasar a gris (el color no ayuda a leer letras)
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # c) version "contraste local" (CLAHE): reparte mejor luces y sombras
    contraste = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gris)

    # d) version "luz pareja": se divide la foto por su propio fondo borroso.
    #    Asi una sombra o poca luz de un lado deja de oscurecer las letras.
    fondo = cv2.GaussianBlur(gris, (0, 0), max(alto, ancho) / 25)
    pareja = cv2.divide(gris, fondo, scale=235)

    # e) version sin las lineas de los recuadros (ver quitar_lineas)
    sin_lineas = quitar_lineas(pareja)
    return [("gris", gris), ("contraste", contraste), ("luz_pareja", pareja),
            ("sin_lineas", sin_lineas)]


def _enderezar(img_bgr):
    """Corrige una foto inclinada (ej. sacada con el telefono torcido).

    Como: buscamos lineas rectas largas (el borde de la caja, los recuadros,
    las lineas de texto), medimos cuanto se alejan de la horizontal y giramos
    la foto en sentido contrario. Se usa la MEDIANA de los angulos para que
    una linea rara no estropee el resultado. Solo corrige hasta 25 grados.
    """
    gris = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    alto, ancho = gris.shape
    bordes = cv2.Canny(cv2.GaussianBlur(gris, (5, 5), 0), 50, 150)
    lineas = cv2.HoughLinesP(bordes, 1, np.pi / 720, threshold=100,
                             minLineLength=ancho // 6, maxLineGap=20)
    if lineas is None:
        return img_bgr
    angulos = []
    for x1, y1, x2, y2 in lineas.reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) <= 25:                      # solo lineas casi horizontales
            angulos.append(a)
    if len(angulos) < 3:
        return img_bgr
    angulo = float(np.median(angulos))
    if abs(angulo) < 0.5:
        return img_bgr
    giro = cv2.getRotationMatrix2D((ancho / 2, alto / 2), angulo, 1.0)
    return cv2.warpAffine(img_bgr, giro, (ancho, alto), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


_RAPID = []


def _texto_rapidocr(img_bgr):
    """Lee con RapidOCR (modelos ONNX incluidos en el paquete). Devuelve las
    lineas de texto ordenadas de arriba hacia abajo."""
    if not _RAPID:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID.append(RapidOCR())
    resultado, _ = _RAPID[0](img_bgr)
    if not resultado:
        return ""
    # cada elemento: [caja con 4 puntos, texto, confianza]; ordenar por altura (y)
    filas = sorted(resultado, key=lambda r: (min(p[1] for p in r[0]) // 20, min(p[0] for p in r[0])))
    return "\n".join(r[1] for r in filas)


def leer_texto(img_bgr):
    """Foto (matriz de OpenCV) -> texto. Devuelve (texto, motor_y_versiones).

    Con Tesseract se lee la foto con cada version preparada y se JUNTA todo
    el texto (cada version acierta en cosas distintas). Con RapidOCR se lee
    la foto enderezada y la version sin recuadros.
    """
    motor = motor_ocr()
    if motor is None:
        raise OCRNoDisponible(MENSAJE_INSTALAR)
    img_bgr = _enderezar(img_bgr)
    if motor == "rapidocr":
        versiones = preparar(img_bgr)
        textos = [_texto_rapidocr(cv2.cvtColor(dict(versiones)["luz_pareja"], cv2.COLOR_GRAY2BGR)),
                  _texto_rapidocr(img_bgr)]
        return "\n".join(textos), "rapidocr"
    config = "--oem 3 --psm 6"       # psm 6 = "un bloque uniforme de texto"
    textos, usadas = [], []
    for nombre, version in preparar(img_bgr):
        textos.append(pytesseract.image_to_string(version, lang=_idiomas(), config=config))
        usadas.append(nombre)
    return "\n".join(textos), "+".join(usadas)


# =====================================================================
# 2. Del TEXTO al MODELO de celular
# =====================================================================
def _parecido(a, b):
    """Numero de 0 a 1: que tan parecidos son dos textos (1 = iguales)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _mejor_ventana(nombre, texto_norm):
    """Busca en el texto el trozo que mas se parece a 'nombre'.

    Ejemplo: nombre = "IPHONE 13"; el OCR leyo "IPH0NE 13" -> parecido 0,89.
    Recorremos el texto por "ventanas" de tantas palabras como tiene el nombre.
    """
    palabras = texto_norm.split()
    n = len(nombre.split())
    mejor = 0.0
    for i in range(max(1, len(palabras) - n + 1)):
        ventana = " ".join(palabras[i:i + n])
        mejor = max(mejor, _parecido(nombre, ventana))
    return mejor


def identificar_modelo(texto, catalogo):
    """Decide a que celular del catalogo corresponde el texto.

    'catalogo' es una lista de diccionarios con al menos nombre y marca
    (las filas de la tabla celulares).

    Puntaje de cada celular = 80 % parecido del NOMBRE + 20 % parecido de la MARCA.
    Devuelve (celular, confianza, ranking). Si nada se parece, celular = None.
    """
    t = normalizar(texto)
    ranking = []
    for c in catalogo:
        p_nombre = _mejor_ventana(normalizar(c["nombre"]), t)
        p_marca = _mejor_ventana(normalizar(c["marca"]), t)
        ranking.append((round(0.8 * p_nombre + 0.2 * p_marca, 3), c))
    ranking.sort(key=lambda x: x[0], reverse=True)
    if not ranking:
        return None, 0.0, []
    confianza, mejor = ranking[0]
    # Si el segundo lugar esta casi empatado, no estamos seguros: restamos confianza.
    if len(ranking) > 1 and confianza - ranking[1][0] < 0.10:
        confianza -= 0.20
    confianza = max(0.0, round(confianza, 3))
    tabla = [{"nombre": c["nombre"], "puntaje": p} for p, c in ranking]
    return (mejor if confianza >= UMBRAL_MODELO else None), confianza, tabla


# =====================================================================
# 3. Del TEXTO a la CANTIDAD
# =====================================================================
# El OCR confunde a veces letras con numeros. Esta tabla las corrige SOLO
# dentro del trozo que deberia ser un numero.
_COMO_DIGITO = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                              "|": "1", "S": "5", "B": "8", "Z": "2"})


def extraer_cantidad(texto):
    """Busca 'CANTIDAD EN CAJA: N UNIDADES' y devuelve N (int) o None.

    Expresion regular (regex) explicada:
        CANTIDAD            la palabra
        \\W*(?:EN)?\\W*CAJA   "EN CAJA" (el "EN" es opcional)
        \\W*                 separadores cualquiera (: . espacios)
        ([0-9OQDILS|BZ]{1,4}) 1 a 4 caracteres que parecen digitos
    Si no encuentra esa frase, prueba con "N UNIDADES" a secas.
    """
    t = normalizar(texto)
    patrones = [
        r"CANTIDAD\W*(?:EN\W*)?CAJA\W*([0-9OQDILS|BZ]{1,4})\b",
        r"\b([0-9OQDILS|BZ]{1,4})\s*(?:UNIDADES|UNIDAD|UNID|UDS|UN)\b",
    ]
    for patron in patrones:
        m = re.search(patron, t)
        if m:
            texto_num = m.group(1).translate(_COMO_DIGITO)
            if texto_num.isdigit() and 0 < int(texto_num) <= 5000:
                return int(texto_num)
    return None


# =====================================================================
# 4. El CALCULO
# =====================================================================
def calcular(cantidad, precio):
    """subtotal = cantidad x precio (en pesos chilenos, entero)."""
    return int(cantidad) * int(precio)


# =====================================================================
# Funcion principal: junta los pasos 1 a 4
# =====================================================================
def leer_caja(img_bgr, catalogo, texto_previo=None):
    """Procesa UNA caja y devuelve un diccionario con todo.

    texto_previo: si el PDF ya trae texto digital, se usa en vez de hacer OCR.

    Campos del resultado:
        texto_leido   lo que el OCR logro leer (util para depurar)
        modelo        nombre del celular o None si no se pudo decidir
        confianza     0 a 1 (seguridad en el modelo)
        cantidad_leida   unidades que dice la caja, o None
        precio, subtotal    del catalogo y cantidad x precio
        estado        "identificado" (todo bien) o "por_revisar" (falta algo)
        motivo        explicacion si queda por revisar
    """
    if texto_previo:
        texto, version = texto_previo, "texto_del_pdf"
    else:
        texto, version = leer_texto(img_bgr)
    celular, confianza, ranking = identificar_modelo(texto, catalogo)
    cantidad = extraer_cantidad(texto)

    res = {"texto_leido": texto.strip(), "version_imagen": version,
           "confianza": confianza, "ranking": ranking,
           "modelo": None, "marca": None, "celular_id": None,
           "cantidad_leida": cantidad, "precio": None, "subtotal": None,
           "estado": "por_revisar", "motivo": ""}
    if celular is not None:
        res.update(modelo=celular["nombre"], marca=celular["marca"],
                   celular_id=celular["id"], precio=celular["precio"])
    if celular is not None and cantidad is not None:
        res["subtotal"] = calcular(cantidad, celular["precio"])
        res["estado"] = "identificado"
    elif celular is None:
        res["motivo"] = "No se reconocio el modelo con suficiente seguridad."
    else:
        res["motivo"] = "No se encontro la linea 'CANTIDAD EN CAJA' en la foto."
    return res


# =====================================================================
# Prueba desde la terminal:  python ocr.py foto_de_la_caja.png
# =====================================================================
if __name__ == "__main__":
    import json
    import sys

    import db  # solo para tomar el catalogo de la base de datos

    db.iniciar()
    if len(sys.argv) < 2:
        sys.exit("Uso: python ocr.py <foto_de_la_caja.png>")
    foto = cv2.imread(sys.argv[1])
    if foto is None:
        sys.exit("No se pudo abrir la imagen.")
    with db.conectar() as con:
        catalogo = [dict(f) for f in con.execute("SELECT * FROM celulares")]
    r = leer_caja(foto, catalogo)
    r["texto_leido"] = r["texto_leido"][:200] + "..."
    print(json.dumps(r, indent=2, ensure_ascii=False))
