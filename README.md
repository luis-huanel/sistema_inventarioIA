# Sistema de inventario de celulares

Proyecto de **Aplicaciones de Inteligencia Artificial (TI2082)**. Cuenta celulares a partir de una fotografía, guarda el inventario en **SQLite** y lo entrega por una **API REST** que consume el chatbot.

| Capa | Tecnología | Archivos |
|---|---|---|
| Base de datos | SQLite | `db.py` → crea `inventario.db` |
| Servidor y API | Python + Flask | `app.py` |
| Visión por computador | OpenCV + scikit-learn (HOG + color + SVM), YOLO opcional | `clasificador.py`, `entrenar_celulares.py` |
| Lectura OCR de cajas | RapidOCR (pip) o Tesseract + OpenCV | `ocr.py`, `herramientas/` |
| Panel web | HTML + CSS + JavaScript | `static/` |
| Ejemplo de chatbot | Python (solo biblioteca estándar) | `ejemplo_chatbot_cliente.py` |

Los 3 celulares del catálogo son **Samsung Galaxy A15**, **Apple iPhone 13** y **Xiaomi Redmi Note 13**. Los precios son ficticios (los del informe) y las especificaciones son referenciales.

> Las imágenes del catálogo y del entrenamiento son **ilustraciones esquemáticas** hechas para este proyecto: no copian el diseño real de cada equipo. Para usar fotos reales ver "Entrenar con fotos reales" más abajo.

## 1. Ponerlo en marcha

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (en Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Abre **http://localhost:5000**. La primera vez se crea `inventario.db` con los 3 celulares (6, 3 y 5 unidades).

- Panel: `http://localhost:5000/`
- Documentación de la API con botones de prueba: `http://localhost:5000/docs`

## 2. Para tu amigo: cómo consumir la API desde su chatbot

El servidor escucha en `0.0.0.0`, así que otro computador de la misma red puede usarlo con la IP de este equipo (en Windows: `ipconfig`, por ejemplo `192.168.1.20`). La URL base queda `http://192.168.1.20:5000/api`. Si el firewall pregunta, permitir Python en redes privadas. CORS está habilitado, por lo que también sirve desde una página web (`fetch`).

Lo que más le va a servir:

| Necesita… | Llamada |
|---|---|
| Todo el inventario con totales | `GET /api/inventario` |
| Texto listo para el prompt de un chatbot con IA | `GET /api/contexto` → campo `texto` |
| Buscar un modelo por nombre o marca | `GET /api/celulares?q=iphone` |
| Un celular por id | `GET /api/celulares/2` |
| Descontar una venta | `PATCH /api/celulares/2/stock` con `{"delta": -1}` |

Ejemplo en Python:

```python
import requests
BASE = "http://192.168.1.20:5000/api"
c = requests.get(f"{BASE}/celulares", params={"q": "redmi"}).json()[0]
print(c["nombre"], c["precio"], c["cantidad"], c["precio_x_cantidad"], c["imagen_url"])
```

Ejemplo en JavaScript:

```js
const r = await fetch("http://192.168.1.20:5000/api/celulares?q=galaxy");
const [celular] = await r.json();
```

Cada celular entrega: `id, nombre, marca, precio, cantidad, precio_x_cantidad, pantalla, ram, almacenamiento, bateria, camara, color, imagen_url, actualizado`. `imagen_url` es una URL completa a la foto del producto, para mostrarla en el chat.

Hay un chatbot de ejemplo que usa estas llamadas: `python ejemplo_chatbot_cliente.py http://IP:5000`. Todos los endpoints están en `docs/API.md`.

## 3. Contar por fotografía

En el panel, **Contar por fotografía** → sube una foto o usa la foto de ejemplo → **Aplicar este conteo al inventario**. Por API: `POST /api/detectar` (ver `docs/API.md`).

- Un equipo con confianza menor a 70 % queda **por revisar** y no se cuenta.
- Para encontrar **varios celulares en un estante** instala YOLO: `pip install ultralytics` (la primera vez descarga el modelo `yolov8n.pt`; necesita internet). Sin YOLO, la foto completa se toma como **un** equipo, o puedes enviar los recuadros en el campo `cajas`.

## 4. Leer una caja con OCR (cantidad automática)

1. **Instala Tesseract** (el programa que lee texto): en Windows, instalador de [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) (marca el idioma *Spanish* si quieres). Si no queda en el PATH, define `TESSERACT_CMD`, por ejemplo `set TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`. En Linux: `sudo apt install tesseract-ocr tesseract-ocr-spa`.
2. **Imprime** `cajas_de_prueba/cajas_de_prueba.pdf` (o míralas en pantalla). También sirven las imágenes sueltas `caja_*.png`. Cada caja dice, por ejemplo, `CANTIDAD EN CAJA: 3 UNIDADES`. Son **ficticias**: no tienen logos reales.
3. En el panel, sección **Leer cajas con OCR**: elige **una o varias imágenes** (una por caja) **o un PDF** (una caja por página), o usa **Tomar foto** en el celular → **Leer cajas** → aparece **una tarjeta por caja** con modelo, cantidad y el cálculo `cantidad × precio` → **Ingresar cajas al inventario**. El sistema detecta solo si cada archivo es imagen o PDF y nunca mezcla las cajas: cada una se calcula y se suma al stock por separado.
4. El chatbot de tu amigo hace lo mismo con `POST /api/ocr` (ver `docs/API.md`).

Para probar sin cámara: `python herramientas/probar_ocr.py` ensucia las cajas (giro, perspectiva, poca luz, ruido, JPG) y comprueba que se lean bien. Para regenerar las cajas: `python herramientas/generar_cajas.py`.

Si una caja real no se lee: sácala de frente, con buena luz y sin reflejos, que la línea de cantidad se vea grande. Lo que no se pueda leer queda **por revisar** y no cambia el stock.

> Para entender el código, empieza por **`docs/GUIA_CODIGO.md`**.

## 5. Entrenar con fotos reales

1. Pon recortes de cada modelo en `dataset/<Modelo>/` (por ejemplo `dataset/Galaxy_A15/`), idealmente 50 a 100 por modelo y con luces y fondos distintos.
2. Ejecuta `python entrenar_celulares.py`. Imprime la exactitud en entrenamiento, validación y prueba y vuelve a escribir `modelo_celulares.joblib`.
3. Reinicia `python app.py`.

Para agregar un modelo nuevo al reconocimiento, súmalo a la lista `MODELOS` de `entrenar_celulares.py` (el nombre debe coincidir con el del catálogo) y reentrena. Cualquier celular nuevo se puede agregar al catálogo desde el panel o con `POST /api/celulares`, pero solo se reconoce en fotos si el modelo fue entrenado con él.

## 6. Estructura

```
app.py                      servidor Flask + API
db.py                       esquema SQLite y datos iniciales
clasificador.py             detección y clasificación en fotos
entrenar_celulares.py       entrenamiento del clasificador
modelo_celulares.joblib     modelo entrenado
dataset/                    imágenes de entrenamiento (una carpeta por modelo)
static/                     panel web (index.html, css, js), docs.html, imágenes y ejemplos
uploads/                    fotos subidas desde el panel
docs/API.md                 documentación de la API
ejemplo_chatbot_cliente.py  ejemplo de chatbot que consume la API
ocr.py                      lectura OCR de la caja (modelo + cantidad + calculo)
cajas_de_prueba/            cajas ficticias para imprimir (PNG y PDF)
herramientas/               generar_cajas.py y probar_ocr.py
docs/GUIA_CODIGO.md         guia para leer el codigo (paso a paso)
```

Tablas de `inventario.db`: `celulares`, `movimientos` (historial de stock), `detecciones` (fotos analizadas), `lecturas_ocr` (cajas leídas) y `estado`. Para volver al estado inicial, cierra el servidor y borra `inventario.db`.

La API no tiene autenticación: es para uso académico en una red local. Si se publica en internet habría que agregar login y HTTPS.


## Si algo no funciona

- **"El servidor tuvo un error interno" al leer una caja**: falta un motor OCR. Ejecuta
  `pip install rapidocr-onnxruntime` y reinicia `python app.py` (no necesita instalar programas aparte).
  Si prefieres Tesseract, instalalo y, si no lo encuentra, define la variable `TESSERACT_CMD`.
- **"Contar por fotografia" no separa los celulares**: sin YOLO usa un detector propio de OpenCV,
  que funciona mejor con fondo liso. Para fondos complicados: `pip install ultralytics`.
  Para fotos de cajas usa la seccion "Leer cajas con OCR".
- Revisa el estado con `http://localhost:5000/api/health`.
