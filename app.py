import os
import sqlite3
from datetime import date, datetime
from functools import wraps

from flask import Flask, jsonify, redirect, render_template_string, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "prestamos-escolares-dev")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prestamos.db"))
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS materiales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            estado TEXT NOT NULL DEFAULT 'Disponible'
        );
        CREATE TABLE IF NOT EXISTS solicitudes_prestamos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estudiante TEXT NOT NULL,
            grado TEXT NOT NULL,
            material_id INTEGER NOT NULL,
            fecha_solicitud TEXT NOT NULL,
            fecha_prestamo TEXT,
            fecha_devolucion TEXT,
            fecha_real TEXT,
            estado_solicitud TEXT NOT NULL,
            dias_tardanza INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (material_id) REFERENCES materiales(id)
        );
        """
    )
    count = conn.execute("SELECT COUNT(*) AS c FROM materiales").fetchone()["c"]
    if count == 0:
        seed = [
            "Proyector Epson",
            "Laptop Dell 14",
            "Laptop HP 15",
            "Kit de microscopio",
            "Balón de fútbol",
            "Balón de básquet",
            "Calculadora científica",
            "Set de geometría",
            "Tablet Samsung",
            "Parlante Bluetooth",
            "Cámara fotográfica",
            "Kit de química básica",
        ]
        conn.executemany("INSERT INTO materiales (nombre, estado) VALUES (?, 'Disponible')", [(n,) for n in seed])
    conn.commit()
    conn.close()


def today():
    return date.today()


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def tardanza_de(row):
    if row["estado_solicitud"] != "Aprobado" or not row["fecha_devolucion"]:
        return 0
    limite = parse_date(row["fecha_devolucion"])
    delta = (today() - limite).days
    return delta if delta > 0 else 0


def sync_tardanzas(conn):
    rows = conn.execute(
        "SELECT id, fecha_devolucion, estado_solicitud FROM solicitudes_prestamos WHERE estado_solicitud = 'Aprobado'"
    ).fetchall()
    for row in rows:
        dias = tardanza_de(row)
        conn.execute("UPDATE solicitudes_prestamos SET dias_tardanza = ? WHERE id = ?", (dias, row["id"]))


def material_map(conn):
    return {r["id"]: r["nombre"] for r in conn.execute("SELECT id, nombre FROM materiales")}


def fila(row, nombres):
    d = dict(row)
    d["material"] = nombres.get(d["material_id"], "—")
    d["dias_tardanza"] = tardanza_de(row) if d["estado_solicitud"] == "Aprobado" else d.get("dias_tardanza") or 0
    return d


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"error": "No autorizado"}), 401
        return fn(*args, **kwargs)

    return wrapper


BASE_CSS = """
:root {
  --ink:#1c1915; --muted:#6b645b; --line:#e6dfd4; --paper:#f6f1e8; --card:#fffdf9;
  --accent:#0f6e56; --accent-2:#e8f5ef; --warn:#9a3412; --warn-bg:#fff1e8; --danger:#b42318;
}
* { box-sizing:border-box; }
body {
  margin:0; font-family:Outfit,system-ui,sans-serif; color:var(--ink);
  background:
    radial-gradient(1100px 420px at 100% -10%, #d7efe6 0%, transparent 55%),
    radial-gradient(800px 360px at -10% 0%, #f3e2c4 0%, transparent 50%),
    var(--paper);
  min-height:100vh;
}
a { color:var(--accent); }
header, main { max-width:1100px; margin:0 auto; padding:22px 18px; }
header { padding-bottom:0; display:flex; justify-content:space-between; gap:12px; align-items:flex-end; flex-wrap:wrap; }
h1 { font-family:Fraunces,Georgia,serif; font-size:clamp(1.6rem,3vw,2.3rem); margin:0 0 4px; letter-spacing:-.02em; }
header p, .muted { color:var(--muted); margin:0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:18px; padding:16px; box-shadow:0 10px 30px rgba(60,40,10,.06); }
.grid { display:grid; grid-template-columns:340px 1fr; gap:16px; }
.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 14px; }
.stat b { display:block; font-family:Fraunces,serif; font-size:1.5rem; }
.stat.warn { background:var(--warn-bg); border-color:#f3c7b0; }
.stat.warn b { color:var(--warn); }
label { display:block; font-size:.82rem; font-weight:600; margin:10px 0 4px; }
input, select, button { font:inherit; width:100%; border-radius:12px; border:1px solid #d9d1c5; padding:10px 12px; background:#fff; color:var(--ink); }
button { cursor:pointer; background:var(--accent); color:#fff; border:none; font-weight:600; }
button.ghost { background:transparent; color:var(--accent); border:1px solid #b7d9cc; width:auto; }
button.danger { background:var(--danger); width:auto; }
button.ok { background:#0f6e56; width:auto; }
button.no { background:#9a3412; width:auto; }
.row-actions { display:flex; gap:6px; flex-wrap:wrap; }
table { width:100%; border-collapse:collapse; font-size:.92rem; }
th, td { text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:.72rem; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); }
.pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:.75rem; font-weight:700; background:var(--accent-2); color:var(--accent); }
.pill.bad { background:#fee4e2; color:var(--danger); }
.pill.wait { background:#fff4d6; color:#92400e; }
.pill.off { background:#efe8dc; color:#5c5348; }
tr.late { background:#fff5f3; }
tr.late td:first-child { box-shadow:inset 3px 0 0 var(--danger); }
.tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.tabs button { width:auto; background:#efe8dc; color:var(--ink); }
.tabs button.on { background:var(--ink); color:#fff; }
.toast { position:fixed; bottom:16px; right:16px; background:var(--ink); color:#fff; padding:12px 14px; border-radius:12px; opacity:0; transform:translateY(8px); transition:.25s; }
.toast.show { opacity:1; transform:none; }
.nav a { margin-left:12px; font-weight:600; text-decoration:none; }
.empty { color:var(--muted); }
@media (max-width:860px) { .grid, .stats { grid-template-columns:1fr 1fr; } .grid { grid-template-columns:1fr; } }
"""

HEAD = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>{css}</style></head><body>
"""

ESTUDIANTE = HEAD + """
<header>
  <div>
    <h1>Catálogo de materiales</h1>
    <p>Solicita un préstamo. El profesor debe aprobarlo antes de entregarte el material.</p>
  </div>
  <nav class="nav"><a href="/admin">Acceso profesor</a></nav>
</header>
<main>
  <div class="grid">
    <section class="card">
      <h2>Solicitud de préstamo</h2>
      <form id="form">
        <label>Nombre completo</label>
        <input name="estudiante" required placeholder="Nombre y apellido"/>
        <label>Grado / sección</label>
        <input name="grado" required placeholder="Ej. 4° A"/>
        <label>Material deseado</label>
        <select name="material_id" id="mats" required></select>
        <label>Fecha propuesta de entrega</label>
        <input type="date" name="fecha_devolucion" id="fdev" required/>
        <button type="submit" style="margin-top:14px">Enviar solicitud</button>
        <p class="muted" style="margin-top:10px;font-size:.85rem">Estado inicial: Pendiente de aprobación por el profesor.</p>
      </form>
    </section>
    <section class="card">
      <h2>Disponibles ahora</h2>
      <div id="catalogo"></div>
      <h2 style="margin-top:18px">Mis solicitudes recientes</h2>
      <div class="search" style="display:flex;gap:8px;margin-bottom:8px">
        <input id="q" placeholder="Busca por tu nombre"/>
      </div>
      <div id="mias"></div>
    </section>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}[c]));
function toast(m){ const t=document.getElementById('toast'); t.textContent=m; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2200); }
let DATA;
async function load(){
  const r = await fetch('/api/publico');
  DATA = await r.json();
  const sel = document.getElementById('mats');
  sel.innerHTML = DATA.disponibles.map(m => `<option value="${m.id}">${esc(m.nombre)}</option>`).join('') || '<option value="">Nada disponible</option>';
  if (!document.getElementById('fdev').value) {
    const d = new Date(DATA.hoy+'T12:00:00'); d.setDate(d.getDate()+7);
    document.getElementById('fdev').value = d.toISOString().slice(0,10);
  }
  document.getElementById('catalogo').innerHTML = DATA.disponibles.length
    ? `<table><thead><tr><th>Material</th><th>Estado</th></tr></thead><tbody>${DATA.disponibles.map(m=>`<tr><td>${esc(m.nombre)}</td><td><span class="pill">Disponible</span></td></tr>`).join('')}</tbody></table>`
    : '<p class="empty">No hay materiales libres en este momento.</p>';
  renderMias();
}
function renderMias(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const rows = DATA.solicitudes.filter(s => !q || s.estudiante.toLowerCase().includes(q));
  const pill = e => e==='Pendiente'?'wait':e==='Rechazado'?'off':e==='Devuelto'?'off':(s=>s)?'':'';
  document.getElementById('mias').innerHTML = rows.length ? `<table><thead><tr><th>Estudiante</th><th>Material</th><th>Estado</th><th>Entrega</th></tr></thead><tbody>
    ${rows.slice(0,30).map(s=>`<tr class="${s.dias_tardanza>0?'late':''}"><td>${esc(s.estudiante)}<br><small>${esc(s.grado)}</small></td><td>${esc(s.material)}</td>
    <td><span class="pill ${s.estado_solicitud==='Pendiente'?'wait':s.estado_solicitud==='Aprobado'&&s.dias_tardanza?'bad':s.estado_solicitud==='Rechazado'||s.estado_solicitud==='Devuelto'?'off':''}">${esc(s.estado_solicitud)}</span>
    ${s.dias_tardanza>0?`<div style="color:#b42318;font-weight:700;margin-top:4px">${s.dias_tardanza} día(s) de atraso</div>`:''}</td>
    <td>${s.fecha_devolucion||'—'}</td></tr>`).join('')}</tbody></table>` : '<p class="empty">Escribe tu nombre para ver tus solicitudes, o envía una nueva.</p>';
}
document.getElementById('q').addEventListener('input', renderMias);
document.getElementById('form').addEventListener('submit', async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  const r = await fetch('/api/solicitudes', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j = await r.json();
  if (!r.ok) return toast(j.error||'Error');
  toast('Solicitud enviada. Queda pendiente de aprobación.');
  e.target.estudiante.value='';
  load();
});
load();
</script></body></html>
"""

ADMIN = HEAD + """
<header>
  <div>
    <h1>Panel del profesor</h1>
    <p>Aprueba solicitudes, registra devoluciones y controla atrasos.</p>
  </div>
  <nav class="nav"><a href="/">Vista estudiante</a> <a href="/admin/salir">Salir</a></nav>
</header>
<main>
  <section class="stats" id="stats"></section>
  <section class="card">
    <div class="tabs" id="tabs">
      <button type="button" data-tab="pendientes" class="on">Solicitudes pendientes</button>
      <button type="button" data-tab="activos">Devoluciones</button>
      <button type="button" data-tab="atrasos">Tardanzas</button>
      <button type="button" data-tab="historial">Historial</button>
    </div>
    <div id="panel"></div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
const esc = s => String(s??'').replace(/[&<>"']/g, c => ({'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}[c]));
function toast(m){ const t=document.getElementById('toast'); t.textContent=m; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2200); }
let DATA, TAB='pendientes';
async function load(){
  const r = await fetch('/api/admin/estado');
  if (r.status===401) { location.href='/admin'; return; }
  DATA = await r.json();
  const s = DATA.resumen;
  document.getElementById('stats').innerHTML = [
    ['Pendientes', s.pendientes],
    ['Activos', s.aprobados],
    ['Disponibles', s.disponibles],
    ['Con atraso', s.atrasados, true],
  ].map(([k,v,w])=>`<div class="stat ${w&&v?'warn':''}"><b>${v}</b><span>${k}</span></div>`).join('');
  render();
}
function table(rows, cols){
  if (!rows.length) return '<p class="empty">Sin registros en esta vista.</p>';
  return `<div style="overflow:auto"><table><thead><tr>${cols.map(c=>`<th>${c[0]}</th>`).join('')}</tr></thead><tbody>
    ${rows.map(r=>`<tr class="${r.dias_tardanza>0 && r.estado_solicitud==='Aprobado'?'late':''}">${cols.map(c=>`<td>${c[1](r)}</td>`).join('')}</tr>`).join('')}
  </tbody></table></div>`;
}
const estudiante = r => `${esc(r.estudiante)}<br><small>${esc(r.grado)}</small>${r.dias_tardanza>0?`<div style="color:#b42318;font-weight:700">${r.dias_tardanza} día(s) de atraso</div>`:''}`;
function render(){
  const p = document.getElementById('panel');
  if (TAB==='pendientes') {
    p.innerHTML = table(DATA.pendientes, [
      ['Estudiante', estudiante],
      ['Material', r=>esc(r.material)],
      ['Solicitado', r=>esc(r.fecha_solicitud)],
      ['Entrega propuesta', r=>esc(r.fecha_devolucion)],
      ['', r=>`<div class="row-actions"><button class="ok" data-ok="${r.id}">Aprobar</button><button class="no" data-no="${r.id}">Rechazar</button></div>`],
    ]);
  } else if (TAB==='activos') {
    p.innerHTML = table(DATA.activos, [
      ['Estudiante', estudiante],
      ['Material', r=>esc(r.material)],
      ['Desde', r=>esc(r.fecha_prestamo)],
      ['Debe devolver', r=>esc(r.fecha_devolucion)],
      ['', r=>`<button class="danger" data-dev="${r.id}">Marcar devuelto</button>`],
    ]);
  } else if (TAB==='atrasos') {
    p.innerHTML = `<p class="muted" style="margin-top:0">Hoy es ${DATA.hoy}. En rojo: préstamos aprobados cuya fecha de devolución ya pasó.</p>` +
      table(DATA.atrasados, [
        ['Estudiante', estudiante],
        ['Material', r=>esc(r.material)],
        ['Fecha límite', r=>esc(r.fecha_devolucion)],
        ['Días de tardanza', r=>`<b style="color:#b42318">${r.dias_tardanza}</b>`],
        ['', r=>`<button class="danger" data-dev="${r.id}">Registrar devolución</button>`],
      ]);
  } else {
    p.innerHTML = table(DATA.historial, [
      ['ID', r=>r.id],
      ['Estudiante', estudiante],
      ['Material', r=>esc(r.material)],
      ['Solicitud', r=>esc(r.fecha_solicitud)],
      ['Préstamo', r=>esc(r.fecha_prestamo||'—')],
      ['Devolución prevista', r=>esc(r.fecha_devolucion||'—')],
      ['Real', r=>esc(r.fecha_real||'—')],
      ['Estado', r=>`<span class="pill ${r.estado_solicitud==='Pendiente'?'wait':r.estado_solicitud==='Aprobado'&&r.dias_tardanza?'bad':r.estado_solicitud==='Rechazado'||r.estado_solicitud==='Devuelto'?'off':''}">${esc(r.estado_solicitud)}</span>`],
      ['Tardanza', r=> r.estado_solicitud==='Aprobado' && r.dias_tardanza ? r.dias_tardanza+' días' : '0'],
    ]);
  }
  p.querySelectorAll('[data-ok]').forEach(b=>b.onclick=()=>accion('/api/admin/aprobar', b.dataset.ok));
  p.querySelectorAll('[data-no]').forEach(b=>b.onclick=()=>accion('/api/admin/rechazar', b.dataset.no));
  p.querySelectorAll('[data-dev]').forEach(b=>b.onclick=()=>accion('/api/admin/devolver', b.dataset.dev));
}
async function accion(url, id){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:Number(id)})});
  const j = await r.json();
  if (!r.ok) return toast(j.error||'Error');
  toast('Actualizado');
  load();
}
document.getElementById('tabs').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  TAB = b.dataset.tab;
  [...document.getElementById('tabs').children].forEach(x=>x.classList.toggle('on', x===b));
  render();
};
load();
</script></body></html>
"""

LOGIN = HEAD + """
<main style="max-width:420px">
  <section class="card">
    <h1>Profesor</h1>
    <p class="muted">Ingresa el PIN para abrir el panel.</p>
    <form method="post">
      <label>PIN</label>
      <input name="pin" type="password" inputmode="numeric" required autofocus placeholder="••••"/>
      <button type="submit" style="margin-top:14px">Entrar</button>
    </form>
    {% if error %}<p style="color:#b42318">{{ error }}</p>{% endif %}
    <p><a href="/">Volver al catálogo</a></p>
  </section>
</main></body></html>
"""


@app.get("/")
@app.get("/estudiante")
def estudiante():
    return render_template_string(ESTUDIANTE, title="Materiales escolares", css=BASE_CSS)


@app.route("/admin", methods=["GET", "POST"])
@app.route("/profesor", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        pin = (request.form.get("pin") or "").strip()
        if pin == ADMIN_PIN:
            session["admin"] = True
            return redirect("/admin/panel")
        return render_template_string(LOGIN, title="Acceso profesor", css=BASE_CSS, error="PIN incorrecto")
    if session.get("admin"):
        return redirect("/admin/panel")
    return render_template_string(LOGIN, title="Acceso profesor", css=BASE_CSS, error=None)


@app.get("/admin/panel")
def admin_panel():
    if not session.get("admin"):
        return redirect("/admin")
    return render_template_string(ADMIN, title="Panel del profesor", css=BASE_CSS)


@app.get("/admin/salir")
def salir():
    session.clear()
    return redirect("/admin")


@app.get("/api/publico")
def publico():
    conn = get_db()
    sync_tardanzas(conn)
    conn.commit()
    nombres = material_map(conn)
    disponibles = [dict(r) for r in conn.execute("SELECT id, nombre, estado FROM materiales WHERE estado = 'Disponible' ORDER BY nombre")]
    sols = [fila(r, nombres) for r in conn.execute("SELECT * FROM solicitudes_prestamos ORDER BY id DESC LIMIT 80")]
    conn.close()
    return jsonify({"hoy": today().isoformat(), "disponibles": disponibles, "solicitudes": sols})


@app.post("/api/solicitudes")
def crear_solicitud():
    body = request.get_json(force=True, silent=True) or {}
    estudiante = (body.get("estudiante") or "").strip()
    grado = (body.get("grado") or "").strip()
    fecha = (body.get("fecha_devolucion") or "").strip()
    try:
        mid = int(body.get("material_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Elige un material"}), 400
    if len(estudiante) < 3 or not grado:
        return jsonify({"error": "Nombre y grado son obligatorios"}), 400
    try:
        if parse_date(fecha) < today():
            return jsonify({"error": "La fecha de entrega no puede ser anterior a hoy"}), 400
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400
    conn = get_db()
    mat = conn.execute("SELECT id, estado FROM materiales WHERE id = ?", (mid,)).fetchone()
    if not mat or mat["estado"] != "Disponible":
        conn.close()
        return jsonify({"error": "Ese material ya no está disponible"}), 400
    pendiente = conn.execute(
        "SELECT id FROM solicitudes_prestamos WHERE material_id = ? AND estado_solicitud = 'Pendiente'",
        (mid,),
    ).fetchone()
    if pendiente:
        conn.close()
        return jsonify({"error": "Ya hay una solicitud pendiente para ese material"}), 400
    conn.execute(
        """INSERT INTO solicitudes_prestamos
           (estudiante, grado, material_id, fecha_solicitud, fecha_devolucion, estado_solicitud, dias_tardanza)
           VALUES (?, ?, ?, ?, ?, 'Pendiente', 0)""",
        (estudiante, grado, mid, today().isoformat(), fecha),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 201


@app.get("/api/admin/estado")
@admin_required
def admin_estado():
    conn = get_db()
    sync_tardanzas(conn)
    conn.commit()
    nombres = material_map(conn)
    rows = [fila(r, nombres) for r in conn.execute("SELECT * FROM solicitudes_prestamos ORDER BY id DESC")]
    disponibles = conn.execute("SELECT COUNT(*) AS c FROM materiales WHERE estado = 'Disponible'").fetchone()["c"]
    conn.close()
    pendientes = [r for r in rows if r["estado_solicitud"] == "Pendiente"]
    activos = [r for r in rows if r["estado_solicitud"] == "Aprobado"]
    atrasados = [r for r in activos if r["dias_tardanza"] > 0]
    return jsonify({
        "hoy": today().isoformat(),
        "pendientes": pendientes,
        "activos": activos,
        "atrasados": atrasados,
        "historial": rows,
        "resumen": {
            "pendientes": len(pendientes),
            "aprobados": len(activos),
            "disponibles": disponibles,
            "atrasados": len(atrasados),
        },
    })


def _solicitud_activa(conn, sid, estado):
    return conn.execute(
        "SELECT * FROM solicitudes_prestamos WHERE id = ? AND estado_solicitud = ?",
        (sid, estado),
    ).fetchone()


@app.post("/api/admin/aprobar")
@admin_required
def aprobar():
    body = request.get_json(force=True, silent=True) or {}
    try:
        sid = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Solicitud inválida"}), 400
    conn = get_db()
    sol = _solicitud_activa(conn, sid, "Pendiente")
    if not sol:
        conn.close()
        return jsonify({"error": "La solicitud ya no está pendiente"}), 404
    mat = conn.execute("SELECT estado FROM materiales WHERE id = ?", (sol["material_id"],)).fetchone()
    if not mat or mat["estado"] != "Disponible":
        conn.close()
        return jsonify({"error": "El material ya está prestado"}), 409
    conn.execute("UPDATE materiales SET estado = 'Prestado' WHERE id = ?", (sol["material_id"],))
    conn.execute(
        "UPDATE solicitudes_prestamos SET estado_solicitud = 'Rechazado' WHERE material_id = ? AND estado_solicitud = 'Pendiente' AND id != ?",
        (sol["material_id"], sid),
    )
    conn.execute(
        "UPDATE solicitudes_prestamos SET estado_solicitud = 'Aprobado', fecha_prestamo = ?, dias_tardanza = 0 WHERE id = ?",
        (today().isoformat(), sid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/admin/rechazar")
@admin_required
def rechazar():
    body = request.get_json(force=True, silent=True) or {}
    try:
        sid = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Solicitud inválida"}), 400
    conn = get_db()
    sol = _solicitud_activa(conn, sid, "Pendiente")
    if not sol:
        conn.close()
        return jsonify({"error": "La solicitud ya no está pendiente"}), 404
    conn.execute("UPDATE solicitudes_prestamos SET estado_solicitud = 'Rechazado' WHERE id = ?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/admin/devolver")
@admin_required
def devolver():
    body = request.get_json(force=True, silent=True) or {}
    try:
        sid = int(body.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Préstamo inválido"}), 400
    conn = get_db()
    sol = _solicitud_activa(conn, sid, "Aprobado")
    if not sol:
        conn.close()
        return jsonify({"error": "No hay un préstamo activo con ese id"}), 404
    dias = tardanza_de(sol)
    conn.execute(
        "UPDATE solicitudes_prestamos SET estado_solicitud = 'Devuelto', fecha_real = ?, dias_tardanza = ? WHERE id = ?",
        (today().isoformat(), dias, sid),
    )
    conn.execute("UPDATE materiales SET estado = 'Disponible' WHERE id = ?", (sol["material_id"],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "dias_tardanza": dias})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
