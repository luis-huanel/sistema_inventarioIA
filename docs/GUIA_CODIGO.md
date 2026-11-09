# Guía del código (para Ricardo)

Esta guía explica **qué hace cada archivo y en qué orden se ejecuta**, usando como ejemplo el caso principal: *fotografiar la caja de un celular y que el stock se actualice solo*. Todos los archivos `.py` tienen comentarios en español; empieza leyendo esta guía y luego abre `ocr.py`.

## 1. Los archivos

| Archivo | Para qué sirve | Se lee junto con |
|---|---|---|
| `app.py` | Servidor Flask. Cada función con `@app.get/@app.post` es una "puerta" de la API. | `docs/API.md` |
| `db.py` | Crea y consulta la base SQLite (`inventario.db`). | `app.py` |
| `ocr.py` | **Lee la caja**: detecta si es imagen o PDF (`detectar_formato`, `extraer_cajas`) → texto → modelo → cantidad → cálculo. | `app.py` (`/api/ocr`) |
| `clasificador.py` | Reconoce el modelo mirando el equipo (IA). | `entrenar_celulares.py` |
| `entrenar_celulares.py` | Entrena esa IA con `dataset/`. | |
| `static/index.html`, `css/`, `js/app.js` | Panel web. El JS llama a la API con `fetch`. | |
| `herramientas/generar_cajas.py` | Dibuja las cajas de prueba. | |
| `herramientas/probar_ocr.py` | Prueba el OCR con fotos simuladas. | |
| `ejemplo_chatbot_cliente.py` | Muestra cómo un chatbot consume la API. | |

## 2. Qué pasa cuando fotografías una caja

```
 Celular / panel web                     Servidor (app.py)                     ocr.py
 ───────────────────                     ─────────────────                     ──────
 1. Foto de la caja  ──POST /api/ocr──►  2. Lee los bytes de la foto
                                         3. Pide el catalogo a SQLite (db.py)
                                                 │
                                                 └───────────────►  4. leer_texto(): limpia la foto
                                                                        y Tesseract la convierte en texto
                                                                     5. identificar_modelo(): compara el
                                                                        texto con el catalogo (difflib)
                                                                     6. extraer_cantidad(): regex sobre
                                                                        "CANTIDAD EN CAJA: N UNIDADES"
                                                                     7. calcular(): N x precio
                                         ◄─────────── resultado ──────┘
 8. Muestra modelo, cantidad,  ◄─JSON──  9. Si aplicar=1: suma N al stock,
    cálculo y botón "Ingresar"              guarda el movimiento y la huella de la foto (SQLite)
```

Dos pasos a propósito: primero **vista previa** (no cambia nada) y luego **Ingresar** (aplicar=1). Así una persona revisa antes de guardar, y si la lectura es dudosa el sistema no adivina: queda `por_revisar`.

## 3. Ideas clave de `ocr.py`

- **Imagen o PDF**: `detectar_formato()` mira los primeros bytes del archivo (la "firma": `%PDF`, `\x89PNG`...), no la extensión. `extraer_cajas()` devuelve **una caja por imagen y una por página de PDF**; así nunca se mezclan. Si una página de PDF ya trae texto digital se usa ese texto; si es escaneada, se aplica OCR.
- **OCR** solo convierte la imagen en letras. No entiende nada. Por eso hay que interpretarlo después.
- **Preparar la foto** (`preparar`, `_enderezar`, `quitar_lineas`): se endereza, se mejora el contraste, se corrige la luz despareja y se borran los bordes de los recuadros (a Tesseract le molestan). Se lee con varias versiones y se junta el texto.
- **Comparación aproximada** (`difflib.SequenceMatcher`): el OCR puede leer `iPH0NE 13` en vez de `iPhone 13`; el parecido sigue siendo alto y se acepta. Si el modelo no llega al 70 %, no se acepta.
- **Expresión regular** (`extraer_cantidad`): busca la frase de cantidad y corrige confusiones típicas (`O`→`0`, `I`→`1`).
- **Huella de la foto** (`hash_imagen`, SHA-256): evita sumar dos veces la misma caja (responde 409).

## 4. Dónde cambiar cosas

| Quiero… | Toco… |
|---|---|
| Agregar un celular al catálogo | Panel → *Agregar celular*, o `POST /api/celulares` |
| Cambiar la frase que se lee de la caja | `extraer_cantidad()` en `ocr.py` (los patrones `regex`) |
| Ser más o menos estricto con el modelo | `UMBRAL_MODELO` en `ocr.py` |
| Cambiar el diseño de las cajas | `herramientas/generar_cajas.py` |
| Agregar una tabla | `ESQUEMA` en `db.py` |
| Agregar un endpoint | una función nueva con `@app.get(...)` en `app.py` |

## 5. Cómo probar

```bash
python app.py                                   # servidor en http://localhost:5000
python ocr.py cajas_de_prueba/caja_iPhone_13.png   # solo el OCR, sin servidor
python herramientas/probar_ocr.py               # 27 pruebas con fotos simuladas
python ejemplo_chatbot_cliente.py               # chatbot de ejemplo (usa la API)
```
