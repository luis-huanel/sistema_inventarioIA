# API del inventario de celulares

Base: `http://<IP-del-servidor>:5000/api` · Formato: JSON (UTF-8) · CORS habilitado · Sin autenticación.

Los errores devuelven el código HTTP correspondiente y `{"error": "mensaje"}` (400 datos inválidos, 404 no existe, 409 nombre repetido).

## Objeto `celular`

```json
{
  "id": 2,
  "nombre": "iPhone 13",
  "marca": "Apple",
  "precio": 599990,
  "cantidad": 3,
  "precio_x_cantidad": 1799970,
  "pantalla": "6,1\"",
  "ram": "4 GB",
  "almacenamiento": "128 GB",
  "bateria": "3240 mAh",
  "camara": "12 MP + 12 MP",
  "color": "Rosa",
  "imagen": "/static/imagenes/iPhone_13_frente.png",
  "imagen_url": "http://localhost:5000/static/imagenes/iPhone_13_frente.png",
  "actualizado": "2026-11-09T14:48:52"
}
```

Precios en pesos chilenos (enteros). `precio_x_cantidad` lo calcula la base de datos.

## Lectura

| Método y ruta | Qué hace |
|---|---|
| `GET /api/health` | `{"ok": true}` si el servicio responde. |
| `GET /api/inventario` | `{categoria, items[], total_inventario, total_unidades, modelos, por_revisar, ultima_actualizacion}`. Mismo formato que el JSON del informe. |
| `GET /api/contexto` | `{texto, inventario}`. `texto` es un resumen en español listo para el prompt de un chatbot con IA. |
| `GET /api/celulares` | Lista de celulares. Filtros: `q` (texto en modelo o marca, sin distinguir mayúsculas), `marca`, `con_stock=1`. |
| `GET /api/celulares/{id}` | Un celular. |
| `GET /api/movimientos?limite=50` | Historial de cambios de stock (más recientes primero). |

## Escritura

| Método y ruta | Cuerpo | Qué hace |
|---|---|---|
| `POST /api/celulares` | `{"nombre","marca","precio"}` + opcionales `cantidad, pantalla, ram, almacenamiento, bateria, camara, color` | Crea un celular (201). |
| `PUT /api/celulares/{id}` | Cualquier campo del celular | Actualiza campos. |
| `PATCH /api/celulares/{id}/stock` | `{"cantidad": 10}` o `{"delta": -2}` | Fija o ajusta el stock. No permite quedar bajo 0. |
| `DELETE /api/celulares/{id}` | – | Elimina el celular. |
| `POST /api/celulares/{id}/imagen` | `multipart/form-data`, campo `imagen` (png, jpg, webp, máx. 10 MB) | Cambia la foto del producto. |

Ejemplo (venta de una unidad):

```bash
curl -X PATCH http://localhost:5000/api/celulares/2/stock \
     -H "Content-Type: application/json" -d '{"delta": -1, "detalle": "venta mostrador"}'
```

## Conteo por fotografía

### `POST /api/detectar`

`multipart/form-data`:
- `imagen` (obligatorio): foto del estante.
- `cajas` (opcional): JSON con recuadros `[[x0,y0,x1,y1], ...]` en píxeles. Si no se envía, se usa YOLO (si está instalado) o la foto completa como un solo equipo.

Respuesta:

```json
{
  "metodo": "cajas",
  "detectados": 15,
  "identificados": 14,
  "por_revisar": 1,
  "conteo": {"Galaxy A15": 6, "iPhone 13": 3, "Redmi Note 13": 5},
  "conteo_detalle": [{"id": 1, "nombre": "Galaxy A15", "marca": "Samsung", "cantidad": 6, "en_catalogo": true}],
  "detalle": [{"caja": [80, 60, 300, 420], "modelo": "iPhone 13", "mejor_candidato": "iPhone 13",
               "confianza": 1.0, "estado": "identificado"}],
  "imagen_anotada": "data:image/jpeg;base64,...",
  "id_deteccion": 7
}
```

`estado` es `identificado` (confianza ≥ 0,70) o `por_revisar`. No cambia el stock por sí sola.

### `POST /api/inventario/aplicar`

```json
{"conteo": [{"id": 1, "cantidad": 6}, {"id": 2, "cantidad": 3}], "por_revisar": 1}
```

Fija el stock de cada celular indicado, registra los movimientos y actualiza el contador de equipos por revisar. Devuelve el mismo objeto que `GET /api/inventario`.

## Lectura OCR de la caja

### `POST /api/ocr`

Lee **una o varias cajas** desde **imágenes y/o documentos PDF**. Regla clave: **cada imagen y cada página de un PDF es una caja independiente**; nunca se mezclan (cada una se lee, se calcula e ingresa por separado).

`multipart/form-data`:
- `imagen` (obligatorio, se puede repetir para enviar varios archivos): png, jpg, webp, bmp, tiff o **PDF**. El formato se detecta por el **contenido** del archivo, no por la extensión. Un PDF con texto digital se lee directo; uno escaneado o con fotos se convierte a imagen y se aplica OCR.
- `aplicar` (opcional): `1` para sumar de inmediato la cantidad al stock. Sin este campo es solo **vista previa** y no cambia nada.
- `forzar` (opcional): `1` para permitir ingresar una caja que ya se había ingresado.

Límites: 30 MB por envío, 50 páginas por PDF, 60 cajas por envío.

**Una sola caja** (una imagen): devuelve la lectura, más `lecturas: [esa lectura]`.

```json
{
  "archivo": "caja_iPhone_13.png", "formato": "imagen", "pagina": null,
  "modelo": "iPhone 13", "marca": "Apple", "celular_id": 2,
  "confianza": 1.0,
  "cantidad_leida": 3,
  "precio": 599990,
  "subtotal": 1799970,
  "stock_anterior": 3, "stock_nuevo": 6,
  "aplicado": false, "ya_ingresada": false,
  "estado": "identificado", "motivo": "",
  "miniatura": "data:image/jpeg;base64,...",
  "texto_leido": "CAJA DE PRUEBA - FICTICIA\nAPPLE\niPhone 13\n...CANTIDAD EN CAJA: 3 UNIDADES...",
  "lecturas": ["... la misma lectura ..."]
}
```

**Varias cajas** (varias imágenes o un PDF de varias páginas): devuelve un resumen y una lectura por caja.

```json
{
  "total_cajas": 3, "cajas_identificadas": 3, "subtotal_total": 3379860, "aplicado": false,
  "lecturas": [
    {"archivo": "cajas.pdf (pagina 1)", "formato": "pdf", "pagina": 1, "modelo": "Galaxy A15", "cantidad_leida": 6, "subtotal": 779940, "estado": "identificado"},
    {"archivo": "cajas.pdf (pagina 2)", "formato": "pdf", "pagina": 2, "modelo": "iPhone 13", "cantidad_leida": 3, "subtotal": 1799970, "estado": "identificado"},
    {"archivo": "cajas.pdf (pagina 3)", "formato": "pdf", "pagina": 3, "modelo": "Redmi Note 13", "cantidad_leida": 5, "subtotal": 799950, "estado": "identificado"}
  ]
}
```

- `subtotal = cantidad_leida × precio`. `stock_nuevo = stock_anterior + cantidad_leida`.
- `estado` = `identificado` si se reconoció el modelo (confianza ≥ 0,70) **y** la cantidad; si no, `por_revisar` (o `error` si el archivo no sirve) y `motivo`/`error` dice qué faltó.
- Con `aplicar=1`, **por caja**: se ingresa si está `identificado`; si quedó `por_revisar` trae `error` y no toca el stock (422 si era una sola caja); si ya se ingresó trae `error` (409 si era una sola caja). Un envío con varias cajas responde 200 y cada lectura trae su propio resultado. El movimiento queda en `/api/movimientos` con tipo `ingreso_ocr`.

Ejemplos:

```bash
curl -F imagen=@cajas_de_prueba/caja_iPhone_13.png http://localhost:5000/api/ocr                       # una imagen, vista previa
curl -F imagen=@cajas_de_prueba/cajas_de_prueba.pdf -F aplicar=1 http://localhost:5000/api/ocr          # PDF de 3 paginas: ingresa las 3
curl -F imagen=@a.png -F imagen=@b.jpg http://localhost:5000/api/ocr                                    # varias imagenes
```

La lectura toma unos segundos por caja (se ejecuta el OCR). Las cajas de práctica para imprimir están en `cajas_de_prueba/`.

## Consejos para el chatbot

- Con un modelo de lenguaje: llamar `GET /api/contexto` en cada conversación (o cada pocos minutos) y pegar `texto` en el mensaje de sistema, para que responda con el stock real.
- Con reglas simples: buscar el modelo con `GET /api/celulares?q=<palabra>` y responder con `precio`, `cantidad`, `precio_x_cantidad`; mostrar la foto con `imagen_url`.
- Para ingresar mercadería: enviar la foto de la caja a `POST /api/ocr` con `aplicar=1` (ver `ejemplo_chatbot_cliente.py`, función `leer_caja`).
- Para registrar ventas: `PATCH /api/celulares/{id}/stock` con `{"delta": -1}`.
