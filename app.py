import os
from datetime import date, datetime

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

MATERIALS = [
    {"id": 1, "nombre": "Proyector Epson", "categoria": "Audiovisual"},
    {"id": 2, "nombre": "Laptop Dell 14", "categoria": "Informática"},
    {"id": 3, "nombre": "Laptop HP 15", "categoria": "Informática"},
    {"id": 4, "nombre": "Kit de microscopio", "categoria": "Laboratorio"},
    {"id": 5, "nombre": "Balón de fútbol", "categoria": "Deportes"},
    {"id": 6, "nombre": "Balón de básquet", "categoria": "Deportes"},
    {"id": 7, "nombre": "Calculadora científica", "categoria": "Matemáticas"},
    {"id": 8, "nombre": "Set de geometría", "categoria": "Matemáticas"},
    {"id": 9, "nombre": "Tablet Samsung", "categoria": "Informática"},
    {"id": 10, "nombre": "Parlante Bluetooth", "categoria": "Audiovisual"},
    {"id": 11, "nombre": "Cámara fotográfica", "categoria": "Audiovisual"},
    {"id": 12, "nombre": "Kit de química básica", "categoria": "Laboratorio"},
]

# estado: disponible | prestado
inventory = {m["id"]: "disponible" for m in MATERIALS}
loans = []
_seq = 1


def today_iso():
    return date.today().isoformat()


def material_by_id(mid):
    return next((m for m in MATERIALS if m["id"] == mid), None)


def active_loan_for(mid):
    return next((l for l in loans if l["material_id"] == mid and l["estado"] == "activo"), None)


def serialize_loan(l):
    m = material_by_id(l["material_id"])
    overdue = l["estado"] == "activo" and l["fecha_devolucion"] < today_iso()
    return {
        **l,
        "material": m["nombre"] if m else "—",
        "categoria": m["categoria"] if m else "—",
        "vencido": overdue,
    }


def snapshot():
    activos = [serialize_loan(l) for l in loans if l["estado"] == "activo"]
    todos = [serialize_loan(l) for l in reversed(loans)]
    disponibles = []
    prestados = []
    for m in MATERIALS:
        item = {**m, "estado": inventory[m["id"]]}
        if inventory[m["id"]] == "disponible":
            disponibles.append(item)
        else:
            loan = active_loan_for(m["id"])
            item["prestamo"] = serialize_loan(loan) if loan else None
            prestados.append(item)
    vencidos = [a for a in activos if a["vencido"]]
    return {
        "hoy": today_iso(),
        "materiales": MATERIALS,
        "disponibles": disponibles,
        "prestados": prestados,
        "prestamos": todos,
        "activos": activos,
        "vencidos": vencidos,
        "resumen": {
            "total_materiales": len(MATERIALS),
            "disponibles": len(disponibles),
            "prestados": len(prestados),
            "prestamos_activos": len(activos),
            "vencidos": len(vencidos),
            "historico": len(loans),
        },
    }


PAGE = r"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Préstamos de Materiales Escolares</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
  :root {
    --ink: #1c1915;
    --muted: #6b645b;
    --line: #e6dfd4;
    --paper: #f6f1e8;
    --card: #fffdf9;
    --accent: #0f6e56;
    --accent-2: #e8f5ef;
    --warn: #9a3412;
    --warn-bg: #fff1e8;
    --danger: #b42318;
    --shadow: 0 10px 30px rgba(60, 40, 10, .06);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: Outfit, system-ui, sans-serif;
    color: var(--ink);
    background:
      radial-gradient(1200px 500px at 100% -10%, #d7efe6 0%, transparent 55%),
      radial-gradient(900px 400px at -10% 0%, #f3e2c4 0%, transparent 50%),
      var(--paper);
    min-height: 100vh;
  }
  header {
    padding: 28px 20px 8px;
    max-width: 1100px;
    margin: 0 auto;
  }
  header h1 {
    font-family: Fraunces, Georgia, serif;
    font-weight: 700;
    font-size: clamp(1.7rem, 3vw, 2.4rem);
    margin: 0 0 6px;
    letter-spacing: -.02em;
  }
  header p { margin: 0; color: var(--muted); }
  main { max-width: 1100px; margin: 0 auto; padding: 18px 20px 48px; }
  .stats {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin: 18px 0 20px;
  }
  .stat {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 14px 16px;
    box-shadow: var(--shadow);
  }
  .stat b { display: block; font-size: 1.6rem; font-family: Fraunces, serif; }
  .stat span { color: var(--muted); font-size: .85rem; }
  .stat.warn { background: var(--warn-bg); border-color: #f3c7b0; }
  .stat.warn b { color: var(--warn); }
  .grid { display: grid; grid-template-columns: 340px 1fr; gap: 16px; }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 18px;
    box-shadow: var(--shadow);
  }
  h2 { margin: 0 0 12px; font-size: 1.05rem; }
  label { display: block; font-size: .82rem; font-weight: 600; margin: 10px 0 4px; }
  input, select, button {
    font: inherit;
    width: 100%;
    border-radius: 12px;
    border: 1px solid #d9d1c5;
    padding: 10px 12px;
    background: #fff;
    color: var(--ink);
  }
  button {
    cursor: pointer;
    background: var(--accent);
    color: white;
    border: none;
    font-weight: 600;
    margin-top: 14px;
  }
  button:hover { filter: brightness(1.05); }
  button.ghost {
    background: transparent;
    color: var(--accent);
    border: 1px solid #b7d9cc;
    width: auto;
    margin: 0;
    padding: 8px 12px;
  }
  button.danger { background: var(--danger); width: auto; margin: 0; padding: 8px 12px; }
  .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
  .tabs button { width: auto; margin: 0; background: #efe8dc; color: var(--ink); }
  .tabs button.on { background: var(--ink); color: #fff; }
  .search { display: flex; gap: 8px; margin-bottom: 12px; }
  .search input { flex: 1; }
  .search button { width: auto; margin: 0; }
  table { width: 100%; border-collapse: collapse; font-size: .92rem; }
  th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { font-size: .75rem; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
  .pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: .75rem;
    font-weight: 600;
    background: var(--accent-2);
    color: var(--accent);
  }
  .pill.bad { background: #fee4e2; color: var(--danger); }
  .pill.idle { background: #efe8dc; color: #5c5348; }
  .alert {
    background: var(--warn-bg);
    border: 1px solid #f3c7b0;
    border-radius: 14px;
    padding: 12px 14px;
    margin-bottom: 14px;
  }
  .alert h3 { margin: 0 0 8px; color: var(--warn); font-size: .95rem; }
  .empty { color: var(--muted); padding: 12px 0; }
  .toast {
    position: fixed; bottom: 18px; right: 18px;
    background: var(--ink); color: #fff;
    padding: 12px 16px; border-radius: 12px;
    opacity: 0; transform: translateY(8px);
    transition: .25s; pointer-events: none;
  }
  .toast.show { opacity: 1; transform: none; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 860px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .grid, .two { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>Préstamos de materiales</h1>
  <p>Inventario escolar: registra, consulta disponibilidad y controla devoluciones vencidas.</p>
</header>
<main>
  <section class="stats" id="stats"></section>
  <div class="grid">
    <section class="card">
      <h2>Registrar préstamo</h2>
      <form id="form">
        <label>Estudiante</label>
        <input name="estudiante" required placeholder="Nombre y apellido" />
        <label>Grado / sección</label>
        <input name="grado" required placeholder="Ej. 3° B" />
        <label>Material disponible</label>
        <select name="material_id" id="materialSelect" required></select>
        <div class="two">
          <div>
            <label>Fecha de préstamo</label>
            <input type="date" name="fecha_prestamo" id="fPrestamo" required />
          </div>
          <div>
            <label>Devolución prevista</label>
            <input type="date" name="fecha_devolucion" id="fDev" required />
          </div>
        </div>
        <button type="submit">Registrar préstamo</button>
      </form>
    </section>
    <section class="card">
      <div class="tabs" id="tabs">
        <button type="button" data-tab="prestamos" class="on">Préstamos</button>
        <button type="button" data-tab="disponibles">Disponibles</button>
        <button type="button" data-tab="prestados">Prestados</button>
        <button type="button" data-tab="alertas">Alertas</button>
      </div>
      <div id="panel"></div>
    </section>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
const $ = (s, r=document) => r.querySelector(s);
let DATA = null;
let TAB = "prestamos";
let FILTER = "";

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

async function load() {
  const r = await fetch("/api/estado");
  DATA = await r.json();
  render();
}

function renderStats() {
  const s = DATA.resumen;
  const items = [
    ["Materiales", s.total_materiales],
    ["Disponibles", s.disponibles],
    ["Prestados", s.prestados],
    ["Activos", s.prestamos_activos],
    ["Vencidos", s.vencidos, true],
  ];
  $("#stats").innerHTML = items.map(([k,v,w]) =>
    `<div class="stat ${w && v ? "warn" : ""}"><b>${v}</b><span>${k}</span></div>`
  ).join("");
}

function fillSelect() {
  const sel = $("#materialSelect");
  const prev = sel.value;
  sel.innerHTML = DATA.disponibles.map(m =>
    `<option value="${m.id}">${m.nombre} · ${m.categoria}</option>`
  ).join("") || `<option value="">Sin materiales disponibles</option>`;
  if (prev) sel.value = prev;
}

function loansTable(rows, withReturn) {
  if (!rows.length) return `<p class="empty">No hay registros.</p>`;
  return `<table>
    <thead><tr><th>Estudiante</th><th>Grado</th><th>Material</th><th>Préstamo</th><th>Devolución</th><th></th></tr></thead>
    <tbody>${rows.map(l => `<tr>
      <td>${esc(l.estudiante)}</td>
      <td>${esc(l.grado)}</td>
      <td>${esc(l.material)}<br><span class="pill ${l.vencido ? "bad" : l.estado==="activo" ? "" : "idle"}">${l.vencido ? "Vencido" : l.estado}</span></td>
      <td>${l.fecha_prestamo}</td>
      <td>${l.fecha_devolucion}${l.fecha_real ? `<br><small>Real: ${l.fecha_real}</small>` : ""}</td>
      <td>${withReturn && l.estado==="activo" ? `<button class="danger" data-return="${l.id}">Devolver</button>` : ""}</td>
    </tr>`).join("")}</tbody></table>`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}[c]));
}

function renderPanel() {
  const p = $("#panel");
  if (TAB === "prestamos") {
    const q = FILTER.trim().toLowerCase();
    const rows = DATA.prestamos.filter(l => !q || l.estudiante.toLowerCase().includes(q) || l.grado.toLowerCase().includes(q));
    p.innerHTML = `
      <div class="search">
        <input id="q" placeholder="Filtrar por estudiante o grado" value="${esc(FILTER)}" />
        <button type="button" id="clear" class="ghost">Limpiar</button>
      </div>
      ${loansTable(rows, true)}`;
    $("#q").addEventListener("input", e => { FILTER = e.target.value; renderPanel(); $("#q").focus(); });
    $("#clear").onclick = () => { FILTER = ""; renderPanel(); };
  } else if (TAB === "disponibles") {
    p.innerHTML = DATA.disponibles.length
      ? `<table><thead><tr><th>Material</th><th>Categoría</th><th>Estado</th></tr></thead><tbody>
        ${DATA.disponibles.map(m => `<tr><td>${esc(m.nombre)}</td><td>${esc(m.categoria)}</td><td><span class="pill">Disponible</span></td></tr>`).join("")}
        </tbody></table>`
      : `<p class="empty">Todo el inventario está prestado.</p>`;
  } else if (TAB === "prestados") {
    p.innerHTML = DATA.prestados.length
      ? `<table><thead><tr><th>Material</th><th>Estudiante</th><th>Hasta</th><th></th></tr></thead><tbody>
        ${DATA.prestados.map(m => {
          const l = m.prestamo;
          return `<tr><td>${esc(m.nombre)}<br><small>${esc(m.categoria)}</small></td>
            <td>${l ? esc(l.estudiante)+" · "+esc(l.grado) : "—"}</td>
            <td>${l ? l.fecha_devolucion : "—"} ${l && l.vencido ? '<span class="pill bad">Vencido</span>' : ""}</td>
            <td>${l ? `<button class="danger" data-return="${l.id}">Devolver</button>` : ""}</td></tr>`;
        }).join("")}</tbody></table>`
      : `<p class="empty">No hay materiales prestados.</p>`;
  } else {
    const v = DATA.vencidos;
    p.innerHTML = `
      <div class="alert"><h3>PRÉSTAMOS PENDIENTES DE DEVOLUCIÓN</h3>
      <p style="margin:0;color:#7c2d12">${v.length ? v.length + " material(es) con fecha vencida respecto a hoy ("+DATA.hoy+")." : "No hay préstamos vencidos. Todo está al día."}</p></div>
      ${loansTable(v, true)}`;
  }
  p.querySelectorAll("[data-return]").forEach(btn => {
    btn.onclick = () => devolver(btn.dataset.return);
  });
}

function render() {
  renderStats();
  fillSelect();
  const fp = $("#fPrestamo");
  const fd = $("#fDev");
  if (!fp.value) fp.value = DATA.hoy;
  if (!fd.value) {
    const d = new Date(DATA.hoy + "T12:00:00");
    d.setDate(d.getDate() + 7);
    fd.value = d.toISOString().slice(0,10);
  }
  renderPanel();
}

$("#tabs").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  TAB = b.dataset.tab;
  [...$("#tabs").children].forEach(x => x.classList.toggle("on", x === b));
  renderPanel();
});

$("#form").addEventListener("submit", async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = Object.fromEntries(fd.entries());
  const r = await fetch("/api/prestamos", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!r.ok) { toast(j.error || "No se pudo registrar"); return; }
  toast("Préstamo registrado");
  e.target.estudiante.value = "";
  await load();
});

async function devolver(id) {
  const r = await fetch("/api/devoluciones", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ prestamo_id: Number(id) }),
  });
  const j = await r.json();
  if (!r.ok) { toast(j.error || "Error"); return; }
  toast("Material marcado como disponible");
  await load();
}

load();
</script>
</body>
</html>
"""


@app.get("/")
def home():
    return render_template_string(PAGE)


@app.get("/api/estado")
def estado():
    q = (request.args.get("estudiante") or "").strip().lower()
    data = snapshot()
    if q:
        data["prestamos"] = [
            p for p in data["prestamos"]
            if q in p["estudiante"].lower() or q in p["grado"].lower()
        ]
    return jsonify(data)


@app.post("/api/prestamos")
def crear_prestamo():
    global _seq
    body = request.get_json(force=True, silent=True) or {}
    estudiante = (body.get("estudiante") or "").strip()
    grado = (body.get("grado") or "").strip()
    try:
        mid = int(body.get("material_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Material inválido"}), 400
    fp = (body.get("fecha_prestamo") or "").strip()
    fd = (body.get("fecha_devolucion") or "").strip()
    if not estudiante or not grado:
        return jsonify({"error": "Estudiante y grado son obligatorios"}), 400
    if not material_by_id(mid):
        return jsonify({"error": "El material no existe"}), 400
    if inventory[mid] != "disponible":
        return jsonify({"error": "El material no está disponible"}), 400
    for label, value in (("préstamo", fp), ("devolución", fd)):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": f"Fecha de {label} inválida"}), 400
    if fd < fp:
        return jsonify({"error": "La devolución no puede ser anterior al préstamo"}), 400
    loan = {
        "id": _seq,
        "estudiante": estudiante,
        "grado": grado,
        "material_id": mid,
        "fecha_prestamo": fp,
        "fecha_devolucion": fd,
        "fecha_real": None,
        "estado": "activo",
    }
    _seq += 1
    loans.append(loan)
    inventory[mid] = "prestado"
    return jsonify(serialize_loan(loan)), 201


@app.post("/api/devoluciones")
def devolver():
    body = request.get_json(force=True, silent=True) or {}
    try:
        pid = int(body.get("prestamo_id") or body.get("material_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Identificador inválido"}), 400
    loan = next((l for l in loans if l["id"] == pid and l["estado"] == "activo"), None)
    if loan is None and body.get("material_id"):
        try:
            mid = int(body["material_id"])
        except (TypeError, ValueError):
            mid = 0
        loan = active_loan_for(mid)
    if not loan:
        return jsonify({"error": "No hay un préstamo activo para devolver"}), 404
    loan["estado"] = "devuelto"
    loan["fecha_real"] = today_iso()
    inventory[loan["material_id"]] = "disponible"
    return jsonify(serialize_loan(loan))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
