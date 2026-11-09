"""Entrena un clasificador de celulares con imagenes.
Autor: Luis Huanel - Aplicaciones de IA (TI2082)
Estructura: dataset/<Modelo>/*.png (recortes de 64x128)"""

# --- 1) IMPORTAR LAS HERRAMIENTAS ------------------------------------
import glob, json                 # glob: buscar archivos; json: guardar
import cv2, joblib, numpy as np   # cv2: leer imagenes; joblib: guardar IA
from skimage.feature import hog   # HOG: describe la FORMA de la imagen
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC       # SVC: el clasificador (SVM)

# --- 2) LOS MODELOS QUE LA IA DEBE RECONOCER -------------------------
# El orden importa: la posicion en la lista es el numero de clase (0, 1, 2)
MODELOS = ["Galaxy A15", "iPhone 13", "Redmi Note 13"]


# --- 3) CONVERTIR UNA IMAGEN EN NUMEROS ------------------------------
def caracteristicas(rgb):
    """Forma (HOG) + color (histograma HSV) de un recorte."""
    # Forma: pasar a gris y medir hacia donde apuntan los bordes
    gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    forma = hog(gris, orientations=9, pixels_per_cell=(8, 8),
                cells_per_block=(2, 2))
    # Color: contar cuantos pixeles hay de cada tono (HSV separa el
    # color de la luz, por eso resiste mejor los cambios de iluminacion)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    color = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4],
                         [0, 180, 0, 256, 0, 256]).flatten()
    color = 4 * color / (color.sum() + 1e-9)   # escalar para comparar
    # Se juntan ambas listas de numeros en una sola "huella" de la imagen
    return np.concatenate([forma, color])


# --- 4) LEER LAS IMAGENES DE ENTRENAMIENTO ---------------------------
def cargar(carpeta="dataset"):
    """Recorre dataset/<Modelo>/*.png y devuelve (X, y)."""
    X, y = [], []                  # X: huellas, y: a que modelo pertenece
    for k, nombre in enumerate(MODELOS):
        patron = f"{carpeta}/{nombre.replace(' ', '_')}/*.png"
        for ruta in sorted(glob.glob(patron)):
            img = cv2.imread(ruta)                       # OpenCV lee BGR
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)   # pasar a RGB
            img = cv2.resize(img, (64, 128))             # mismo tamano
            X.append(caracteristicas(img))
            y.append(k)                                  # etiqueta 0/1/2
    return np.array(X), np.array(y)


# --- 5) DIVIDIR LOS DATOS EN TRES GRUPOS -----------------------------
def separar(y):
    """70% entrenamiento, 15% validacion, 15% prueba."""
    idx = np.arange(len(y))
    # stratify mantiene la misma proporcion de cada modelo en los grupos
    ent, resto = train_test_split(idx, test_size=0.30,
                                  stratify=y, random_state=7)
    val, pru = train_test_split(resto, test_size=0.50,
                                stratify=y[resto], random_state=7)
    return ent, val, pru


# --- 6) ENTRENAR, EVALUAR Y GUARDAR ----------------------------------
if __name__ == "__main__":
    X, y = cargar()
    ent, val, pru = separar(y)
    # El pipeline normaliza los numeros y despues aplica la SVM.
    # probability=True permite obtener la "confianza" de cada prediccion.
    svm = SVC(C=10, probability=True, random_state=7)
    modelo = make_pipeline(StandardScaler(), svm)
    modelo.fit(X[ent], y[ent])     # aprende SOLO con el grupo de entreno
    # Medir la exactitud en los tres grupos (en prueba son imagenes que
    # el modelo nunca vio, asi que es la nota "honesta")
    res = {}
    for nombre, i in [("entrenamiento", ent), ("validacion", val),
                      ("prueba", pru)]:
        acierto = accuracy_score(y[i], modelo.predict(X[i]))
        res[nombre] = {"n": int(len(i)), "exactitud": acierto}
        print(f"{nombre}: {len(i)} imagenes, {acierto:.1%}")
    # La matriz de confusion muestra QUE modelos se confunden entre si
    res["matriz_confusion_prueba"] = confusion_matrix(
        y[pru], modelo.predict(X[pru])).tolist()
    res["por_clase"] = {}
    for k, m in enumerate(MODELOS):
        res["por_clase"][m] = {
            "entrenamiento": int((y[ent] == k).sum()),
            "validacion": int((y[val] == k).sum()),
            "prueba": int((y[pru] == k).sum())}
    res["total_imagenes"] = int(len(y))
    joblib.dump(modelo, "modelo_celulares.joblib")      # guarda la IA
    with open("resultados_entrenamiento.json", "w") as f:
        json.dump(res, f, indent=2)                     # guarda las notas
