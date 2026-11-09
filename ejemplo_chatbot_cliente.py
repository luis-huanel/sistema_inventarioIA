"""Ejemplo de como un chatbot CONSUME la API del inventario.

Solo usa la biblioteca estandar. Tu amigo puede copiar las funciones
consultar() y contexto() en su propio chatbot.

Uso:
    python ejemplo_chatbot_cliente.py                       (servidor local)
    python ejemplo_chatbot_cliente.py http://192.168.1.20:5000   (otro equipo)
"""
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000").rstrip("/") + "/api"


def get(ruta, **params):
    url = BASE + ruta + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def leer_caja(ruta_foto, aplicar=False):
    """Envia una IMAGEN o un PDF de cajas a POST /api/ocr y devuelve el JSON.

    Cada imagen / pagina de PDF es una caja; el JSON trae "lecturas" (una por caja).

    aplicar=False  -> solo vista previa (no cambia el stock).
    aplicar=True   -> suma la cantidad leida al stock automaticamente.
    Como Python estandar no trae 'multipart', armamos el cuerpo a mano.
    """
    limite = "----caja" + str(abs(hash(ruta_foto)))
    with open(ruta_foto, "rb") as f:
        foto = f.read()
    cuerpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"imagen\"; "
              f"filename=\"{os.path.basename(ruta_foto)}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + foto
    if aplicar:
        cuerpo += (f"\r\n--{limite}\r\nContent-Disposition: form-data; "
                   f"name=\"aplicar\"\r\n\r\n1").encode()
    cuerpo += f"\r\n--{limite}--\r\n".encode()
    peticion = urllib.request.Request(BASE + "/ocr", data=cuerpo, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={limite}"})
    try:
        with urllib.request.urlopen(peticion, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:          # 409/422 traen un JSON con el motivo
        return json.load(e)


def contexto():
    """Texto con todo el inventario: ideal para el prompt de un chatbot con IA."""
    return get("/contexto")["texto"]


def consultar(texto):
    """Busca un celular por nombre/marca dentro del texto de la pregunta."""
    for palabra in sorted(texto.replace("?", "").split(), key=len, reverse=True):
        if len(palabra) >= 3:
            r = get("/celulares", q=palabra)
            if r:
                return r[0]
    return None


def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))


def responder(pregunta):
    t = sin_tildes(pregunta)
    inv = get("/inventario")
    if "total" in t or "valor" in t and "inventario" in t:
        return f"El inventario vale ${inv['total_inventario']:,} ({inv['total_unidades']} unidades).".replace(",", ".")
    c = consultar(pregunta)
    if not c:
        modelos = ", ".join(i["nombre"] for i in inv["items"])
        return f"No encontre ese modelo. Tengo: {modelos}."
    if "precio" in t or "cuesta" in t or "vale" in t:
        return f"El {c['marca']} {c['nombre']} cuesta ${c['precio']:,}.".replace(",", ".")
    return (f"{c['marca']} {c['nombre']}: quedan {c['cantidad']} unidades "
            f"(${c['precio_x_cantidad']:,} en bodega). Foto: {c['imagen_url']}").replace(",", ".")


if __name__ == "__main__":
    print("Chatbot de ejemplo conectado a", BASE)
    print("--- contexto que podrias enviarle a un modelo de lenguaje ---")
    print(contexto())
    print("--- escribe una pregunta ('salir' para terminar) ---")
    print("    Tambien: 'caja <foto.png>' lee una caja | 'ingresar <foto.png>' la suma al stock")
    while True:
        q = input("Tu: ").strip()
        if q.lower() in ("salir", "exit", ""):
            break
        if q.lower().startswith(("caja ", "ingresar ")):
            orden, ruta = q.split(" ", 1)
            r = leer_caja(ruta.strip(), aplicar=orden.lower() == "ingresar")
            # r["lecturas"] trae UNA lectura por caja (imagen o pagina de PDF)
            for l in r.get("lecturas", []):
                if l.get("modelo") and l.get("cantidad_leida"):
                    print(f"Bot: {l['archivo']}: {l['marca']} {l['modelo']} x {l['cantidad_leida']} = ${l['subtotal']:,}".replace(",", "."),
                          "-> stock", l["stock_anterior"], "->", l["stock_nuevo"],
                          "(ingresado)" if l["aplicado"] else "(solo lectura)")
                else:
                    print("Bot:", l.get("archivo"), "no se pudo leer:", l.get("error") or l.get("motivo"))
            if "lecturas" not in r:
                print("Bot: error:", r.get("error"))
            continue
        print("Bot:", responder(q))
