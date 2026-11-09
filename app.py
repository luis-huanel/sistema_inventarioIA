"""Servidor del sistema de inventario de celulares (API REST + panel web).

MAPA DEL PROYECTO (para entender el codigo)
-------------------------------------------
  app.py            <- ESTE ARCHIVO. Recibe las peticiones HTTP y responde JSON.
  db.py             Crea la base SQLite y guarda/lee datos (tablas, movimientos).
  ocr.py            Lee la CAJA con OCR: foto -> modelo + cantidad -> calculo.
  clasificador.py   Reconoce el modelo mirando la FOTO del equipo (IA con SVM).
  entrenar_celulares.py   Entrena esa IA con las imagenes de dataset/.
  static/           Panel web (HTML + CSS + JavaScript) que usa esta misma API.

COMO FUNCIONA UNA PETICION
--------------------------
  navegador/chatbot --HTTP--> @app.get/@app.post (funcion de abajo)
        --> consulta o modifica SQLite con db.conectar()
        --> devuelve jsonify(...)  (el JSON que ve quien llamo)
  Flask une cada URL con una funcion mediante los decoradores @app.get(...).
  Los errores se lanzan con abort(codigo, "mensaje") y salen como {"error": ...}.

Uso:  python app.py            -> http://localhost:5000
      PUERTO=8000 python app.py
La API (JSON, con CORS habilitado) esta documentada en docs/API.md y en /docs.
"""
import base64
import json
import os
import sqlite3
import uuid

import cv2
import numpy as np
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import clasificador
import db
import ocr

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
UPLOADS = os.path.join(db.BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
EXT_OK = {".png", ".jpg", ".jpeg", ".webp"}


# ------------------------------------------------------------------ utilidades
# CORS: permite que una pagina web de OTRO origen (el chatbot de tu amigo)
# llame a esta API. Sin estas cabeceras el navegador bloquearia la llamada.
@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return resp


@app.route("/api/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return ("", 204)


@app.errorhandler(HTTPException)
def error_http(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": e.description}), e.code
    return e


# Cualquier otro error inesperado: en vez de la pagina generica "internal
# server error", se devuelve un JSON con el motivo real y se imprime el detalle
# en la terminal del servidor para poder corregirlo.
@app.errorhandler(Exception)
def error_inesperado(e):
    import traceback
    traceback.print_exc()
    if not request.path.startswith("/api/"):
        return "Error interno del servidor", 500
    if isinstance(e, ocr.OCRNoDisponible):          # falta instalar el motor OCR
        return jsonify({"error": str(e), "codigo": "ocr_no_disponible"}), 503
    return jsonify({"error": f"Error interno: {type(e).__name__}: {e}"}), 500


def pedir_json():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        abort(400, "Se esperaba un cuerpo JSON (objeto).")
    return datos


def limpiar(datos, parcial=False):
    """Valida y normaliza los campos de un celular.

    parcial=True se usa al ACTUALIZAR (PUT): solo se revisan los campos enviados.
    parcial=False se usa al CREAR (POST): nombre, marca y precio son obligatorios.
    """
    out = {}
    for c in db.CAMPOS:
        if c not in datos:
            if not parcial and c in ("nombre", "marca", "precio"):
                abort(400, f"Falta el campo obligatorio '{c}'.")
            continue
        v = datos[c]
        if c in ("precio", "cantidad"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                abort(400, f"'{c}' debe ser un numero entero.")
            if v < 0:
                abort(400, f"'{c}' no puede ser negativo.")
        else:
            v = ("" if v is None else str(v)).strip()
            if c in ("nombre", "marca") and not v:
                abort(400, f"'{c}' no puede estar vacio.")
        out[c] = v
    return out


def celular_o_404(con, cid):
    fila = con.execute(db.SELECT_CELULAR + " WHERE id = ?", (cid,)).fetchone()
    if fila is None:
        abort(404, f"No existe el celular con id {cid}.")
    return fila


def resumen_inventario(con):
    """Arma el JSON del inventario completo con totales (lo usan varios endpoints)."""
    filas = con.execute(db.SELECT_CELULAR + " ORDER BY id").fetchall()
    base = request.host_url
    items = [db.fila_a_dict(f, base) for f in filas]
    ult = con.execute("SELECT MAX(actualizado) FROM celulares").fetchone()[0]
    return {"categoria": "celulares", "items": items,
            "total_inventario": sum(i["precio_x_cantidad"] for i in items),
            "total_unidades": sum(i["cantidad"] for i in items),
            "modelos": len(items), "por_revisar": db.por_revisar(con),
            "ultima_actualizacion": ult}


# ------------------------------------------------------------------ paginas
@app.get("/")
def inicio():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/docs")
def docs():
    return send_from_directory(app.static_folder, "docs.html")


@app.get("/uploads/<path:nombre>")
def subidas(nombre):
    return send_from_directory(UPLOADS, nombre)


# ------------------------------------------------------------------ API: celulares
@app.get("/api/health")
def health():
    return {"ok": True, "servicio": "inventario-celulares", "ocr": ocr.estado_ocr()}


@app.get("/api/celulares")
def listar():
    """Filtros opcionales: ?q=texto  ?marca=Samsung  ?con_stock=1"""
    q = (request.args.get("q") or "").strip().lower()
    marca = (request.args.get("marca") or "").strip().lower()
    sql, args = db.SELECT_CELULAR + " WHERE 1=1", []
    if q:
        sql += (" AND (LOWER(nombre) LIKE ? OR LOWER(marca) LIKE ?"
                " OR LOWER(nombre || ' ' || marca) LIKE ?"
                " OR LOWER(marca || ' ' || nombre) LIKE ?)")
        args += [f"%{q}%"] * 4
    if marca:
        sql += " AND LOWER(marca) = ?"
        args.append(marca)
    if request.args.get("con_stock") in ("1", "true", "si"):
        sql += " AND cantidad > 0"
    with db.conectar() as con:
        filas = con.execute(sql + " ORDER BY id", args).fetchall()
    return jsonify([db.fila_a_dict(f, request.host_url) for f in filas])


@app.get("/api/celulares/<int:cid>")
def obtener(cid):
    with db.conectar() as con:
        return jsonify(db.fila_a_dict(celular_o_404(con, cid), request.host_url))


@app.post("/api/celulares")
def crear():
    d = limpiar(pedir_json())
    d.setdefault("cantidad", 0)
    d["actualizado"] = db.ahora()
    cols = ", ".join(d)
    try:
        with db.conectar() as con:
            cur = con.execute(f"INSERT INTO celulares ({cols}) VALUES ({','.join('?' * len(d))})",
                              list(d.values()))
            db.registrar_movimiento(con, cur.lastrowid, "alta", None, d["cantidad"], d["nombre"])
            fila = celular_o_404(con, cur.lastrowid)
            return jsonify(db.fila_a_dict(fila, request.host_url)), 201
    except sqlite3.IntegrityError:
        abort(409, f"Ya existe un celular llamado '{d['nombre']}'.")


@app.put("/api/celulares/<int:cid>")
def actualizar(cid):
    d = limpiar(pedir_json(), parcial=True)
    if not d:
        abort(400, "No hay campos para actualizar.")
    try:
        with db.conectar() as con:
            antes = celular_o_404(con, cid)
            d["actualizado"] = db.ahora()
            sets = ", ".join(f"{k} = ?" for k in d)
            con.execute(f"UPDATE celulares SET {sets} WHERE id = ?", list(d.values()) + [cid])
            if "cantidad" in d and d["cantidad"] != antes["cantidad"]:
                db.registrar_movimiento(con, cid, "edicion", antes["cantidad"], d["cantidad"])
            return jsonify(db.fila_a_dict(celular_o_404(con, cid), request.host_url))
    except sqlite3.IntegrityError:
        abort(409, "Ya existe un celular con ese nombre.")


@app.patch("/api/celulares/<int:cid>/stock")
def stock(cid):
    """Cuerpo: {"cantidad": 10}  (fija)  o  {"delta": -2}  (suma/resta)."""
    d = pedir_json()
    with db.conectar() as con:
        antes = celular_o_404(con, cid)
        try:
            nuevo = int(d["cantidad"]) if "cantidad" in d else antes["cantidad"] + int(d["delta"])
        except (KeyError, TypeError, ValueError):
            abort(400, "Envia 'cantidad' o 'delta' como numero entero.")
        if nuevo < 0:
            abort(400, "El stock no puede quedar negativo.")
        con.execute("UPDATE celulares SET cantidad = ?, actualizado = ? WHERE id = ?",
                    (nuevo, db.ahora(), cid))
        db.registrar_movimiento(con, cid, "stock", antes["cantidad"], nuevo, d.get("detalle", ""))
        return jsonify(db.fila_a_dict(celular_o_404(con, cid), request.host_url))


@app.delete("/api/celulares/<int:cid>")
def borrar(cid):
    with db.conectar() as con:
        antes = celular_o_404(con, cid)
        db.registrar_movimiento(con, cid, "baja", antes["cantidad"], None, antes["nombre"])
        con.execute("DELETE FROM celulares WHERE id = ?", (cid,))
    return jsonify({"eliminado": cid})


@app.post("/api/celulares/<int:cid>/imagen")
def subir_imagen(cid):
    f = request.files.get("imagen")
    if f is None or not f.filename:
        abort(400, "Envia el archivo en el campo 'imagen' (multipart/form-data).")
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in EXT_OK:
        abort(400, "Formato no permitido (usa png, jpg, jpeg o webp).")
    nombre = f"{uuid.uuid4().hex[:12]}{ext}"
    f.save(os.path.join(UPLOADS, nombre))
    with db.conectar() as con:
        celular_o_404(con, cid)
        con.execute("UPDATE celulares SET imagen = ?, actualizado = ? WHERE id = ?",
                    (f"/uploads/{nombre}", db.ahora(), cid))
        return jsonify(db.fila_a_dict(celular_o_404(con, cid), request.host_url))


# ------------------------------------------------------------------ API: inventario
@app.get("/api/inventario")
def inventario():
    with db.conectar() as con:
        return jsonify(resumen_inventario(con))


@app.get("/api/contexto")
def contexto():
    """Resumen en texto plano, pensado para pegarlo en el prompt de un chatbot."""
    with db.conectar() as con:
        inv = resumen_inventario(con)
    def clp(n):
        return "$" + f"{n:,}".replace(",", ".")

    lineas = ["Inventario de celulares de Distribuidora Austral del Estrecho SpA "
              f"(actualizado {inv['ultima_actualizacion']}). Precios en pesos chilenos (CLP)."]
    for i in inv["items"]:
        lineas.append(
            f"- {i['marca']} {i['nombre']}: precio {clp(i['precio'])}, stock {i['cantidad']} "
            f"unidades (valor en bodega {clp(i['precio_x_cantidad'])}). Pantalla {i['pantalla']}, "
            f"RAM {i['ram']}, almacenamiento {i['almacenamiento']}, bateria {i['bateria']}, "
            f"camara {i['camara']}, color {i['color']}.")
    lineas.append(f"Total valorizado del inventario: {clp(inv['total_inventario'])}. "
                  f"Unidades totales: {inv['total_unidades']}. "
                  f"Equipos por revisar: {inv['por_revisar']}.")
    return jsonify({"texto": "\n".join(lineas), "inventario": inv})


@app.get("/api/movimientos")
def movimientos():
    limite = min(int(request.args.get("limite", 50)), 500)
    with db.conectar() as con:
        filas = con.execute(
            "SELECT m.*, c.nombre FROM movimientos m LEFT JOIN celulares c ON c.id = m.celular_id"
            " ORDER BY m.id DESC LIMIT ?", (limite,)).fetchall()
    return jsonify([dict(f) for f in filas])


# ------------------------------------------------------------------ API: deteccion por foto
@app.post("/api/detectar")
def detectar():
    """multipart/form-data: 'imagen' (obligatorio) y 'cajas' (opcional, JSON [[x0,y0,x1,y1],...])."""
    f = request.files.get("imagen")
    if f is None:
        abort(400, "Envia la foto en el campo 'imagen' (multipart/form-data).")
    img = cv2.imdecode(np.frombuffer(f.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        abort(400, "No se pudo leer la imagen.")
    cajas = None
    if request.form.get("cajas"):
        try:
            cajas = [[int(v) for v in c] for c in json.loads(request.form["cajas"])]
        except (ValueError, TypeError):
            abort(400, "'cajas' debe ser una lista JSON de [x0, y0, x1, y1].")
    res = clasificador.analizar(img, cajas)
    with db.conectar() as con:
        ids = {r["nombre"]: r for r in con.execute("SELECT id, nombre, marca FROM celulares")}
        res["conteo_detalle"] = [
            {"id": ids[n]["id"] if n in ids else None, "nombre": n,
             "marca": ids[n]["marca"] if n in ids else None, "cantidad": c,
             "en_catalogo": n in ids} for n, c in res["conteo"].items()]
        cur = con.execute(
            "INSERT INTO detecciones (fecha, archivo, metodo, detectados, identificados,"
            " por_revisar, resultado) VALUES (?,?,?,?,?,?,?)",
            (db.ahora(), f.filename, res["metodo"], res["detectados"], res["identificados"],
             res["por_revisar"], json.dumps({k: res[k] for k in ("conteo", "detalle")})))
        res["id_deteccion"] = cur.lastrowid
    return jsonify(res)


@app.post("/api/inventario/aplicar")
def aplicar():
    """Cuerpo: {"conteo": [{"id": 1, "cantidad": 6}, ...], "por_revisar": 1}"""
    d = pedir_json()
    conteo = d.get("conteo")
    if not isinstance(conteo, list) or not conteo:
        abort(400, "Falta 'conteo' (lista de {id, cantidad}).")
    with db.conectar() as con:
        for item in conteo:
            try:
                cid, nuevo = int(item["id"]), int(item["cantidad"])
            except (KeyError, TypeError, ValueError):
                abort(400, "Cada elemento de 'conteo' necesita 'id' y 'cantidad' enteros.")
            if nuevo < 0:
                abort(400, "Las cantidades no pueden ser negativas.")
            antes = celular_o_404(con, cid)
            con.execute("UPDATE celulares SET cantidad = ?, actualizado = ? WHERE id = ?",
                        (nuevo, db.ahora(), cid))
            db.registrar_movimiento(con, cid, "conteo_foto", antes["cantidad"], nuevo,
                                    "Conteo automatico por fotografia")
        con.execute("INSERT OR REPLACE INTO estado VALUES ('por_revisar', ?)",
                    (str(int(d.get("por_revisar", 0))),))
        return jsonify(resumen_inventario(con))


# ------------------------------------------------------------------ API: lectura OCR de la caja
def miniatura(img, ancho=420):
    """Imagen chica (data URL JPEG) de la caja, para mostrarla en el panel.
    Sirve sobre todo con PDF, donde el navegador no tiene la imagen de cada pagina."""
    alto = int(img.shape[0] * ancho / img.shape[1])
    ok, buf = cv2.imencode(".jpg", cv2.resize(img, (ancho, alto), interpolation=cv2.INTER_AREA),
                           [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def procesar_caja(caja, aplicar, forzar):
    """Lee UNA caja (una imagen o una pagina de PDF) y, si se pide, la ingresa.

    'caja' viene de ocr.extraer_cajas(). Devuelve (resultado, codigo_http).
    Cada caja se procesa sola: su propia lectura, su propio calculo y su propio
    ingreso al stock. Nunca se mezclan con otras cajas.
    """
    with db.conectar() as con:
        # el catalogo se lee ahora (no antes) para ver el stock ya actualizado
        # por las cajas anteriores del mismo envio
        catalogo = [dict(r) for r in con.execute("SELECT * FROM celulares")]
        previa = con.execute("SELECT fecha FROM lecturas_ocr WHERE huella = ?",
                             (caja["huella"],)).fetchone()

        # 1) el OCR hace todo el trabajo de lectura y calculo
        res = ocr.leer_caja(caja["img"], catalogo, caja["texto_previo"])
        res["miniatura"] = miniatura(caja["img"])
        res.update(archivo=caja["nombre"], formato=caja["formato"], pagina=caja["pagina"],
                   aplicado=False, ya_ingresada=previa is not None,
                   stock_anterior=None, stock_nuevo=None)

        celular = next((c for c in catalogo if c["id"] == res["celular_id"]), None)
        if celular:
            res["stock_anterior"] = celular["cantidad"]
            res["stock_nuevo"] = celular["cantidad"] + (res["cantidad_leida"] or 0)
            res["imagen_url"] = db.fila_a_dict(celular, request.host_url)["imagen_url"]

        if not aplicar:
            return res, 200                            # solo vista previa

        # 2) validaciones antes de tocar el stock
        if res["estado"] != "identificado":
            return {**res, "error": res["motivo"]}, 422
        if previa is not None and not forzar:
            return {**res, "error": f"Esta caja ya se ingreso el {previa['fecha']}. "
                    "Usa forzar=1 si es otra caja igual."}, 409

        # 3) sumar al stock y dejar rastro (movimiento + lectura)
        con.execute("UPDATE celulares SET cantidad = ?, actualizado = ? WHERE id = ?",
                    (res["stock_nuevo"], db.ahora(), celular["id"]))
        db.registrar_movimiento(con, celular["id"], "ingreso_ocr", res["stock_anterior"],
                                res["stock_nuevo"],
                                f"Caja leida por OCR ({caja['nombre']}): +{res['cantidad_leida']} unidades")
        # con 'forzar' la huella ya existe: se reemplaza el registro anterior
        con.execute("INSERT OR REPLACE INTO lecturas_ocr (fecha, huella, celular_id, cantidad,"
                    " subtotal, confianza, texto) VALUES (?,?,?,?,?,?,?)",
                    (db.ahora(), caja["huella"], celular["id"], res["cantidad_leida"],
                     res["subtotal"], res["confianza"], res["texto_leido"]))
        res["aplicado"] = True
        return res, 200


@app.post("/api/ocr")
def leer_caja_ocr():
    """Lee una o VARIAS cajas desde imagenes y/o documentos PDF.

    multipart/form-data:
        imagen / archivo   uno o varios archivos (se puede repetir el campo).
                           Formatos: png, jpg, webp, bmp, tiff y PDF. El formato
                           se detecta por el contenido, no por la extension.
        aplicar            "1" para ingresar al stock. Sin esto: solo vista previa.
        forzar             "1" para permitir una caja ya ingresada.

    Regla clave: CADA imagen y CADA pagina de PDF es UNA caja independiente.

    Respuesta:
        Una sola caja  -> el objeto de la lectura (modelo, cantidad_leida,
                          subtotal, stock_nuevo...) mas "lecturas": [ese objeto].
        Varias cajas   -> {"total_cajas", "cajas_identificadas", "subtotal_total",
                           "lecturas": [una lectura por caja]}; cada lectura trae
                           su propio estado y, si fallo, su propio "error".
    """
    archivos = [f for lista in request.files.listvalues() for f in lista]
    if not archivos:
        abort(400, "Envia al menos un archivo (imagen o PDF) en el campo 'imagen'.")
    aplicar = request.form.get("aplicar") in ("1", "true", "si")
    forzar = request.form.get("forzar") in ("1", "true", "si")

    cajas = []
    for f in archivos:
        try:
            cajas += ocr.extraer_cajas(f.read(), f.filename or "archivo")
        except ValueError as e:
            if len(archivos) == 1:
                abort(400, str(e))
            cajas.append({"error": str(e), "nombre": f.filename})
    if sum(1 for c in cajas if "img" in c) > 60:
        abort(400, "Maximo 60 cajas por envio.")

    lecturas, codigos = [], []
    for c in cajas:
        if "img" not in c:                                   # archivo invalido
            lecturas.append({"archivo": c["nombre"], "estado": "error", "error": c["error"]})
            codigos.append(400)
        else:
            r, codigo = procesar_caja(c, aplicar, forzar)
            lecturas.append(r)
            codigos.append(codigo)

    if len(lecturas) == 1:                                   # compatibilidad: una sola caja
        return jsonify({**lecturas[0], "lecturas": lecturas}), codigos[0]
    ok = [l for l in lecturas if l.get("estado") == "identificado"]
    return jsonify({
        "total_cajas": len(lecturas), "cajas_identificadas": len(ok),
        "subtotal_total": sum(l["subtotal"] for l in ok),
        "aplicado": aplicar and any(l.get("aplicado") for l in lecturas),
        "lecturas": lecturas})


# Al importar el archivo se crea la base (y los 3 celulares de ejemplo si esta vacia).
db.iniciar()

if __name__ == "__main__":
    puerto = int(os.environ.get("PUERTO", "5000"))
    # host 0.0.0.0 permite que otro computador de la red (el de tu amigo) consuma la API
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=puerto, debug=False)
