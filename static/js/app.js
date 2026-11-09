"use strict";
const $ = (s, r = document) => r.querySelector(s);
const clp = n => "$" + Number(n).toLocaleString("es-CL");
const API = "/api";
const SIN_IMG = "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="54" height="104"><rect width="54" height="104" fill="#eee"/><text x="27" y="56" font-size="10" text-anchor="middle" fill="#888" font-family="sans-serif">sin foto</text></svg>');
let celulares = [];
let ultimoAnalisis = null;
let editandoId = null;

function toast(msg, mal = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "ver" + (mal ? " mal" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), 3200);
}

async function api(ruta, opciones = {}) {
  const r = await fetch(API + ruta, opciones);
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}
const jsonOpc = (metodo, cuerpo) => ({
  method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
});

function el(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  hijos.flat().forEach(h => e.append(h));
  return e;
}

// ------------------------------------------------------------ inventario
async function cargar() {
  const q = $("#buscar").value.trim();
  const marca = $("#filtro-marca").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (marca) params.set("marca", marca);
  const [lista, inv] = await Promise.all([api("/celulares?" + params), api("/inventario")]);
  celulares = lista;
  $("#k-total").textContent = clp(inv.total_inventario);
  $("#k-unidades").textContent = inv.total_unidades;
  $("#k-modelos").textContent = inv.modelos;
  $("#k-revisar").textContent = inv.por_revisar;
  llenarMarcas(inv.items);
  pintarTabla();
}

function llenarMarcas(items) {
  const sel = $("#filtro-marca");
  const actual = sel.value;
  const marcas = [...new Set(items.map(i => i.marca))].sort();
  sel.replaceChildren(el("option", { value: "", textContent: "Todas las marcas" }),
    ...marcas.map(m => el("option", { value: m, textContent: m })));
  sel.value = marcas.includes(actual) ? actual : "";
}

function pintarTabla() {
  const cuerpo = $("#tabla tbody");
  cuerpo.replaceChildren();
  let total = 0;
  for (const c of celulares) {
    total += c.precio_x_cantidad;
    const img = el("img", { className: "thumb", src: c.imagen_url || SIN_IMG, alt: `${c.marca} ${c.nombre}`, loading: "lazy" });
    img.onerror = () => { img.onerror = null; img.src = SIN_IMG; };
    const menos = el("button", { type: "button", textContent: "−", title: "Restar 1", onclick: () => cambiarStock(c.id, -1) });
    const mas = el("button", { type: "button", textContent: "+", title: "Sumar 1", onclick: () => cambiarStock(c.id, 1) });
    const fila = el("tr", {},
      el("td", {}, img),
      el("td", {}, el("div", { className: "modelo", textContent: c.nombre }),
        el("div", { className: "det", textContent: [c.pantalla, c.ram && c.ram + " RAM", c.almacenamiento, c.color].filter(Boolean).join(" · ") })),
      el("td", { textContent: c.marca }),
      el("td", { className: "num", textContent: clp(c.precio) }),
      el("td", { className: "num" }, el("span", { className: "stock-ctl" }, menos, el("strong", { textContent: c.cantidad }), mas)),
      el("td", { className: "num", textContent: clp(c.precio_x_cantidad) }),
      el("td", {}, el("div", { className: "acc" },
        el("button", { className: "btn btn-claro btn-mini", type: "button", textContent: "Editar", onclick: () => abrirForm(c) }),
        el("button", { className: "btn btn-claro btn-mini", type: "button", textContent: "Eliminar", onclick: () => eliminar(c) }))));
    cuerpo.append(fila);
  }
  $("#pie-total").textContent = clp(total);
  $("#vacio").hidden = celulares.length > 0;
}

async function cambiarStock(id, delta) {
  try { await api(`/celulares/${id}/stock`, jsonOpc("PATCH", { delta })); await cargar(); }
  catch (e) { toast(e.message, true); }
}

async function eliminar(c) {
  if (!confirm(`¿Eliminar ${c.marca} ${c.nombre} del inventario?`)) return;
  try { await api(`/celulares/${c.id}`, { method: "DELETE" }); toast("Celular eliminado"); await cargar(); }
  catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------ formulario
const dlg = $("#dlg"), form = $("#form");
function abrirForm(c = null) {
  editandoId = c ? c.id : null;
  form.reset();
  $("#dlg-error").hidden = true;
  $("#dlg-titulo").textContent = c ? `Editar ${c.nombre}` : "Agregar celular";
  if (c) for (const k of ["nombre", "marca", "precio", "cantidad", "pantalla", "ram", "almacenamiento", "bateria", "camara", "color"])
    form.elements[k].value = c[k] ?? "";
  dlg.showModal();
}
$("#btn-nuevo").onclick = () => abrirForm();
$("#dlg-cancelar").onclick = () => dlg.close();
form.addEventListener("submit", async ev => {
  ev.preventDefault();
  const datos = {};
  for (const k of ["nombre", "marca", "precio", "cantidad", "pantalla", "ram", "almacenamiento", "bateria", "camara", "color"])
    datos[k] = form.elements[k].value;
  try {
    const guardado = editandoId
      ? await api(`/celulares/${editandoId}`, jsonOpc("PUT", datos))
      : await api("/celulares", jsonOpc("POST", datos));
    const archivo = form.elements.archivo.files[0];
    if (archivo) {
      const fd = new FormData(); fd.append("imagen", archivo);
      await api(`/celulares/${guardado.id}/imagen`, { method: "POST", body: fd });
    }
    dlg.close();
    toast("Guardado");
    await cargar();
  } catch (e) { const p = $("#dlg-error"); p.textContent = e.message; p.hidden = false; }
});

// ------------------------------------------------------------ deteccion por foto
async function analizar(archivo, cajas = null) {
  const btns = [$("#btn-analizar"), $("#btn-ejemplo")];
  btns.forEach(b => (b.disabled = true));
  try {
    const fd = new FormData();
    fd.append("imagen", archivo);
    if (cajas) fd.append("cajas", JSON.stringify(cajas));
    ultimoAnalisis = await api("/detectar", { method: "POST", body: fd });
    mostrarAnalisis(ultimoAnalisis);
  } catch (e) { toast(e.message, true); }
  finally { btns.forEach(b => (b.disabled = false)); }
}

function mostrarAnalisis(a) {
  $("#resultado").hidden = false;
  $("#img-anotada").src = a.imagen_anotada;
  $("#chips").replaceChildren(
    el("span", { className: "chip", textContent: `${a.detectados} detectados` }),
    el("span", { className: "chip ok", textContent: `${a.identificados} identificados` }),
    el("span", { className: "chip aviso", textContent: `${a.por_revisar} por revisar` }));
  $("#tabla-conteo tbody").replaceChildren(...a.conteo_detalle.map(c =>
    el("tr", {}, el("td", { textContent: c.nombre + (c.en_catalogo ? "" : " (no está en el catálogo)") }),
      el("td", { className: "num", textContent: c.cantidad }))));
  const nota = {
    cajas: "Recuadros entregados con la foto (foto de ejemplo).",
    yolo: "Equipos encontrados con YOLO.",
    opencv: "Equipos encontrados con el detector incluido (OpenCV, funciona mejor con fondo liso). Para fotos con fondos complicados instala YOLO: pip install ultralytics.",
    imagen_completa: "No se encontraron equipos separados: la foto completa se tomó como un solo equipo. Si es la foto de una CAJA, usa la sección «Leer cajas con OCR». Para estantes complicados instala YOLO (pip install ultralytics).",
  }[a.metodo];
  $("#nota-metodo").textContent = nota || "";
  $("#btn-aplicar").disabled = !a.conteo_detalle.some(c => c.id);
}

$("#btn-analizar").onclick = () => {
  const f = $("#foto").files[0];
  if (!f) return toast("Primero elige una foto", true);
  analizar(f);
};
$("#btn-ejemplo").onclick = async () => {
  const [blob, cajas] = await Promise.all([
    fetch("/static/ejemplos/estante.png").then(r => r.blob()),
    fetch("/static/ejemplos/estante_cajas.json").then(r => r.json()),
  ]);
  analizar(new File([blob], "estante.png", { type: "image/png" }), cajas);
};
$("#btn-aplicar").onclick = async () => {
  if (!ultimoAnalisis) return;
  const conteo = ultimoAnalisis.conteo_detalle.filter(c => c.id).map(c => ({ id: c.id, cantidad: c.cantidad }));
  try {
    await api("/inventario/aplicar", jsonOpc("POST", { conteo, por_revisar: ultimoAnalisis.por_revisar }));
    toast("Inventario actualizado con el conteo de la foto");
    await cargar();
  } catch (e) { toast(e.message, true); }
};

// ------------------------------------------------------------ lectura OCR de cajas
// Se pueden subir VARIOS archivos: imagenes (una caja cada una) y/o PDF (una
// caja por pagina). El servidor detecta el formato por el contenido y devuelve
// "lecturas": una por caja. Aqui se dibuja una tarjeta por cada una.
// Paso 1 (vista previa): POST /api/ocr SIN "aplicar" -> no cambia el stock.
// Paso 2 (confirmar):    POST /api/ocr con aplicar=1 -> suma al stock las cajas
//   bien leidas; las dudosas se saltan y quedan marcadas.
let archivosCaja = [];   // archivos (File) de la ultima lectura

async function enviarCajas(archivos, aplicar = false) {
  const fd = new FormData();
  archivos.forEach(f => fd.append("imagen", f));      // mismo campo repetido = varios archivos
  if (aplicar) fd.append("aplicar", "1");
  const r = await fetch(API + "/ocr", { method: "POST", body: fd });
  const datos = await r.json().catch(() => ({}));
  if (!datos.lecturas && !r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos.lecturas;                              // lista de lecturas, una por caja
}

function tarjetaCaja(d) {
  const bien = d.estado === "identificado";
  const etiqueta = d.aplicado ? "Ingresada" : (d.ya_ingresada ? "Ya ingresada" : (bien ? "Leída correctamente" : "Por revisar"));
  const clase = d.aplicado || bien ? "ok" : "aviso";
  const filas = [
    ["Archivo", (d.formato === "pdf" ? "PDF · " : "Imagen · ") + (d.archivo || "")],
    ["Modelo", d.modelo ? `${d.marca} ${d.modelo}` : "—"],
    ["Cantidad en la caja", d.cantidad_leida ?? "—"],
    ["Cálculo", d.subtotal != null ? `${d.cantidad_leida} × ${clp(d.precio)} = ${clp(d.subtotal)}` : "—"],
    ["Stock actual → nuevo", d.stock_anterior != null ? `${d.stock_anterior} → ${d.stock_nuevo}` : "—"],
  ];
  const marco = el("figure", { className: "marco" });
  if (d.miniatura) marco.append(el("img", { src: d.miniatura, alt: "Caja leída" }));
  return el("article", { className: "caja-card" },
    marco,
    el("div", {},
      el("div", { className: "chips" },
        el("span", { className: "chip " + clase, textContent: etiqueta }),
        el("span", { className: "chip", textContent: `Confianza ${Math.round((d.confianza || 0) * 100)} %` })),
      el("table", { className: "mini tabla-ocr" }, el("tbody", {}, ...filas.map(([k, v]) =>
        el("tr", {}, el("th", { textContent: k }), el("td", { textContent: v }))))),
      d.error && !d.aplicado ? el("p", { className: "ayuda", textContent: d.error }) : "",
      el("details", {}, el("summary", { textContent: "Texto leído por el OCR" }),
        el("pre", { className: "texto-ocr", textContent: d.texto_leido || "" }))));
}

function mostrarCajas(lecturas) {
  $("#res-ocr").hidden = false;
  $("#lista-cajas").replaceChildren(...lecturas.map(tarjetaCaja));
  const ok = lecturas.filter(l => l.estado === "identificado").length;
  const total = lecturas.filter(l => l.subtotal != null).reduce((s, l) => s + l.subtotal, 0);
  $("#resumen-ocr").replaceChildren(
    el("span", { className: "chip", textContent: `${lecturas.length} caja(s)` }),
    el("span", { className: "chip ok", textContent: `${ok} bien leída(s)` }),
    el("span", { className: "chip aviso", textContent: `${lecturas.length - ok} por revisar` }),
    el("span", { className: "chip", textContent: `Subtotal ${clp(total)}` }));
  $("#btn-ingresar-caja").disabled = ok === 0 || lecturas.every(l => l.aplicado);
  $("#nota-ocr").textContent = lecturas.some(l => l.aplicado) ? "Stock actualizado." : "Revisa cada caja y confirma para sumar al stock.";
}

async function procesarCajas(archivos) {
  archivosCaja = archivos;
  const btns = document.querySelectorAll("#seccion-ocr button");
  btns.forEach(b => (b.disabled = true));
  $("#btn-leer-caja").textContent = "Leyendo…";
  try { mostrarCajas(await enviarCajas(archivos)); }
  catch (e) { toast(e.message, true); }
  finally {
    btns.forEach(b => (b.disabled = false));
    $("#btn-leer-caja").textContent = "Leer cajas";
    if (!$("#res-ocr").hidden) $("#btn-ingresar-caja").disabled = false;
  }
}

$("#btn-leer-caja").onclick = () => {
  const fs = [...$("#foto-caja").files];
  if (!fs.length) return toast("Primero elige imágenes o un PDF", true);
  procesarCajas(fs);
};
$("#btn-camara").onclick = () => $("#foto-camara").click();
$("#foto-camara").onchange = () => { if ($("#foto-camara").files.length) procesarCajas([...$("#foto-camara").files]); };
$("#ejemplos-caja").addEventListener("click", async ev => {
  const nombre = ev.target.dataset && ev.target.dataset.caja;
  if (!nombre) return;
  const blob = await fetch(`/static/ejemplos/${nombre}`).then(r => r.blob());
  procesarCajas([new File([blob], nombre, { type: blob.type })]);
});
$("#btn-ingresar-caja").onclick = async () => {
  if (!archivosCaja.length) return;
  const btn = $("#btn-ingresar-caja"); btn.disabled = true; btn.textContent = "Ingresando…";
  try {
    const lecturas = await enviarCajas(archivosCaja, true);
    mostrarCajas(lecturas);
    const n = lecturas.filter(l => l.aplicado).length;
    toast(n ? `${n} caja(s) ingresada(s) al stock` : "No se ingresó ninguna caja", !n);
    await cargar();
  } catch (e) { toast(e.message, true); }
  finally { btn.textContent = "Ingresar cajas al inventario"; }
};

// ------------------------------------------------------------ arranque
let temporizador;
$("#buscar").addEventListener("input", () => { clearTimeout(temporizador); temporizador = setTimeout(() => cargar().catch(e => toast(e.message, true)), 200); });
$("#filtro-marca").addEventListener("change", () => cargar().catch(e => toast(e.message, true)));
cargar().catch(e => toast("No se pudo cargar el inventario: " + e.message, true));


// Revisa al abrir el panel si el servidor tiene motor OCR. Si no hay, muestra
// como instalarlo en vez de dejar que el usuario vea un error al leer una caja.
(async function avisoOcr() {
  try {
    const h = await (await fetch(API + "/health")).json();
    if (h.ocr && !h.ocr.disponible) {
      const a = $("#aviso-ocr");
      a.textContent = "El OCR aun no esta instalado. En la terminal ejecuta:  pip install rapidocr-onnxruntime  y reinicia el servidor. " + (h.ocr.ayuda || "");
      a.hidden = false;
    }
  } catch (e) { /* si falla, el panel sigue funcionando */ }
})();
