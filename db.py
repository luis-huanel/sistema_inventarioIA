"""Base de datos SQLite del inventario de celulares.

SQLite guarda TODO en un solo archivo (inventario.db); no necesita instalar un
servidor de base de datos. Python lo trae incluido (modulo sqlite3).

TABLAS
------
  celulares     el catalogo: nombre, marca, precio, cantidad (stock), specs.
                'precio_x_cantidad' no se guarda: se calcula en cada consulta
                (ver SELECT_CELULAR) para que nunca quede desactualizado.
  movimientos   historial: cada cambio de stock (venta, conteo por foto,
                ingreso por OCR...) con valor anterior y nuevo.
  detecciones   cada foto de estante analizada por la IA.
  lecturas_ocr  cada caja leida por OCR (la 'huella' evita ingresarla 2 veces).
  estado        pares clave/valor sueltos (ej.: cuantos equipos 'por_revisar').
"""
import os
import sqlite3
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("INVENTARIO_DB", os.path.join(BASE, "inventario.db"))

CAMPOS = ["nombre", "marca", "precio", "cantidad", "pantalla", "ram",
          "almacenamiento", "bateria", "camara", "color", "imagen"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS celulares (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT NOT NULL UNIQUE,
    marca          TEXT NOT NULL,
    precio         INTEGER NOT NULL CHECK (precio >= 0),
    cantidad       INTEGER NOT NULL DEFAULT 0 CHECK (cantidad >= 0),
    pantalla       TEXT, ram TEXT, almacenamiento TEXT,
    bateria        TEXT, camara TEXT, color TEXT,
    imagen         TEXT,
    actualizado    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS movimientos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha       TEXT NOT NULL,
    celular_id  INTEGER REFERENCES celulares(id) ON DELETE SET NULL,
    tipo        TEXT NOT NULL,
    anterior    INTEGER,
    nuevo       INTEGER,
    detalle     TEXT
);
CREATE TABLE IF NOT EXISTS detecciones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,
    archivo       TEXT,
    metodo        TEXT,
    detectados    INTEGER,
    identificados INTEGER,
    por_revisar   INTEGER,
    resultado     TEXT
);
-- Cada caja leida por OCR. 'huella' (SHA-256 de la foto) es UNICA: asi la misma
-- foto no se puede ingresar dos veces al stock.
CREATE TABLE IF NOT EXISTS lecturas_ocr (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,
    huella        TEXT NOT NULL UNIQUE,
    celular_id    INTEGER REFERENCES celulares(id) ON DELETE SET NULL,
    cantidad      INTEGER,
    subtotal      INTEGER,
    confianza     REAL,
    texto         TEXT
);
CREATE TABLE IF NOT EXISTS estado (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""

# Datos de ejemplo (precios del informe; especificaciones referenciales).
SEMILLA = [
    ("Galaxy A15", "Samsung", 129990, 6, '6,5"', "4 GB", "128 GB", "5000 mAh",
     "50 MP + 5 MP + 2 MP", "Negro", "/static/imagenes/Galaxy_A15_frente.png"),
    ("iPhone 13", "Apple", 599990, 3, '6,1"', "4 GB", "128 GB", "3240 mAh",
     "12 MP + 12 MP", "Rosa", "/static/imagenes/iPhone_13_frente.png"),
    ("Redmi Note 13", "Xiaomi", 159990, 5, '6,67"', "6 GB", "128 GB", "5000 mAh",
     "108 MP + 8 MP + 2 MP", "Verde azulado",
     "/static/imagenes/Redmi_Note_13_frente.png"),
]


def ahora():
    return datetime.now().isoformat(timespec="seconds")


def conectar():
    """Abre la base. Uso:  with db.conectar() as con:  (guarda los cambios al salir)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def iniciar():
    """Crea las tablas y, si la base esta vacia, carga los 3 celulares."""
    with conectar() as con:
        con.executescript(ESQUEMA)
        if con.execute("SELECT COUNT(*) FROM celulares").fetchone()[0] == 0:
            for fila in SEMILLA:
                con.execute(
                    "INSERT INTO celulares (nombre, marca, precio, cantidad, pantalla,"
                    " ram, almacenamiento, bateria, camara, color, imagen, actualizado)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", fila + (ahora(),))
            con.execute("INSERT OR REPLACE INTO estado VALUES ('por_revisar', '1')")


SELECT_CELULAR = ("SELECT *, precio * cantidad AS precio_x_cantidad "
                  "FROM celulares")


def fila_a_dict(fila, base_url=""):
    d = dict(fila)
    img = d.get("imagen") or ""
    d["imagen_url"] = (base_url.rstrip("/") + img) if img.startswith("/") else img
    return d


def registrar_movimiento(con, celular_id, tipo, anterior, nuevo, detalle=""):
    """Deja constancia de un cambio de stock. 'tipo' dice el origen: stock,
    conteo_foto, ingreso_ocr..."""
    con.execute("INSERT INTO movimientos (fecha, celular_id, tipo, anterior, nuevo,"
                " detalle) VALUES (?,?,?,?,?,?)",
                (ahora(), celular_id, tipo, anterior, nuevo, detalle))


def por_revisar(con):
    fila = con.execute("SELECT valor FROM estado WHERE clave='por_revisar'").fetchone()
    return int(fila["valor"]) if fila else 0


if __name__ == "__main__":
    iniciar()
    print("Base lista en", DB_PATH)
