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
tr.late { background:#fff5f5; }
tr.late td:first-child { box-shadow: inset 3px 0 0 #dc3545; }
.toast-app { position:fixed; bottom:16px; right:16px; z-index:1080; }
"""

HEAD = """
<!DOCTYPE html><html lang="es"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"/>
<style>{css}</style>
</head><body class="bg-light">
"""

ESTUDIANTE = HEAD + """
<nav class="navbar navbar-expand bg-white border-bottom">
  <div class="container">
    <span class="navbar-brand fw-semibold">Materiales escolares</span>
    <a class="btn btn-outline-success btn-sm" href="/admin">Acceso profesor</a>
  </div>
</nav>
<main class="container py-4">
  <h1 class="h3 mb-1">Catálogo de materiales</h1>
  <p class="text-secondary mb-4">Solicita un préstamo. El profesor debe aprobarlo antes de entregarte el material.</p>
  <div class="row g-4">
    <div class="col-lg-4">
      <section class="card shadow-sm">
        <div class="card-body">
          <h2 class="h5 card-title">Solicitud de préstamo</h2>
          <form id="form">
            <label class="form-label">Nombre completo</label>
            <input class="form-control mb-2" name="estudiante" required placeholder="Nombre y apellido"/>
            <label class="form-label">Grado / sección</label>
            <input class="form-control mb-2" name="grado" required placeholder="Ej. 4° A"/>
            <label class="form-label">Material deseado</label>
            <select class="form-select mb-2" name="material_id" id="mats" required></select>
            <label class="form-label">Fecha propuesta de entrega</label>
            <input class="form-control" type="date" name="fecha_devolucion" id="fdev" required/>
            <button class="btn btn-success w-100 mt-3" type="submit">Enviar solicitud</button>
            <p class="text-secondary small mt-2 mb-0">Estado inicial: Pendiente de aprobación por el profesor.</p>
          </form>
        </div>
      </section>
    </div>
    <div class="col-lg-8">
      <section class="card shadow-sm">
        <div class="card-body">
          <h2 class="h5">Disponibles ahora</h2>
          <div id="catalogo" class="table-responsive"></div>
          <h2 class="h5 mt-4">Mis solicitudes recientes</h2>
          <input id="q" class="form-control mb-3" placeholder="Busca por tu nombre"/>
          <div id="mias" class="table-responsive"></div>
        </div>
      </section>
    </div>
  </div>
</main>
<div class="toast-app toast align-items-center text-bg-dark border-0" id="toast" role="alert"><div class="d-flex"><div class="toast-body" id="toastMsg"></div></div></div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}[c]));
function toast(m){ document.getElementById('toastMsg').textContent=m; bootstrap.Toast.getOrCreateInstance(document.getElementById('toast'), {delay:2200}).show(); }
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
    ? `<table class="table table-hover align-middle mb-0"><thead class="table-light"><tr><th>Material</th><th>Estado</th></tr></thead><tbody>${DATA.disponibles.map(m=>`<tr><td>${esc(m.nombre)}</td><td><span class="badge text-bg-success">Disponible</span></td></tr>`).join('')}</tbody></table>`
    : '<p class="text-secondary mb-0">No hay materiales libres en este momento.</p>';
  renderMias();
}
function renderMias(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const rows = DATA.solicitudes.filter(s => !q || s.estudiante.toLowerCase().includes(q));
  document.getElementById('mias').innerHTML = rows.length ? `<table class="table table-hover align-middle mb-0"><thead class="table-light"><tr><th>Estudiante</th><th>Material</th><th>Estado</th><th>Entrega</th></tr></thead><tbody>
    ${rows.slice(0,30).map(s=>`<tr class="${s.dias_tardanza>0?'late':''}"><td>${esc(s.estudiante)}<br><small class="text-secondary">${esc(s.grado)}</small></td><td>${esc(s.material)}</td>
    <td><span class="badge ${s.estado_solicitud==='Pendiente'?'text-bg-warning':s.estado_solicitud==='Aprobado'&&s.dias_tardanza?'text-bg-danger':s.estado_solicitud==='Rechazado'||s.estado_solicitud==='Devuelto'?'text-bg-secondary':'text-bg-success'}">${esc(s.estado_solicitud)}</span>
    ${s.dias_tardanza>0?`<div class="text-danger fw-semibold small mt-1">${s.dias_tardanza} día(s) de atraso</div>`:''}</td>
    <td>${s.fecha_devolucion||'—'}</td></tr>`).join('')}</tbody></table>` : '<p class="text-secondary mb-0">Escribe tu nombre para ver tus solicitudes, o envía una nueva.</p>';
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
<nav class="navbar navbar-expand bg-white border-bottom">
  <div class="container">
    <span class="navbar-brand fw-semibold">Panel del profesor</span>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary btn-sm" href="/">Vista estudiante</a>
      <a class="btn btn-outline-danger btn-sm" href="/admin/salir">Salir</a>
    </div>
  </div>
</nav>
<main class="container py-4">
  <h1 class="h3 mb-1">Panel del profesor</h1>
  <p class="text-secondary">Aprueba solicitudes, registra devoluciones y controla atrasos.</p>
  <section class="row g-3 mb-3" id="stats"></section>
  <section class="card shadow-sm">
    <div class="card-body">
      <div class="btn-group flex-wrap mb-3" id="tabs" role="group">
        <button type="button" class="btn btn-dark" data-tab="pendientes">Solicitudes pendientes</button>
        <button type="button" class="btn btn-outline-dark" data-tab="activos">Devoluciones</button>
        <button type="button" class="btn btn-outline-dark" data-tab="atrasos">Tardanzas</button>
        <button type="button" class="btn btn-outline-dark" data-tab="historial">Historial</button>
      </div>
      <div id="panel" class="table-responsive"></div>
    </div>
  </section>
</main>
<div class="toast-app toast align-items-center text-bg-dark border-0" id="toast" role="alert"><div class="d-flex"><div class="toast-body" id="toastMsg"></div></div></div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const esc = s => String(s??'').replace(/[&<>"']/g, c => ({'&':'&','<':'<','>':'>','"':'"',"'":'&#39;'}[c]));
function toast(m){ document.getElementById('toastMsg').textContent=m; bootstrap.Toast.getOrCreateInstance(document.getElementById('toast'), {delay:2200}).show(); }
let DATA, TAB='pendientes';
async function load(){
  const r = await fetch('/api/admin/estado');
  if (r.status===401) { location.href='/admin'; return; }
  DATA = await r.json();
  const s = DATA.resumen;
  document.getElementById('stats').innerHTML = [
    ['Pendientes', s.pendientes, 'text-bg-warning'],
    ['Activos', s.aprobados, 'text-bg-success'],
    ['Disponibles', s.disponibles, 'text-bg-light'],
    ['Con atraso', s.atrasados, 'text-bg-danger'],
  ].map(([k,v,c])=>`<div class="col-6 col-md-3"><div class="card shadow-sm"><div class="card-body"><div class="fs-3 fw-semibold">${v}</div><div class="text-secondary small">${k}</div></div></div></div>`).join('');
  render();
}
function table(rows, cols){
  if (!rows.length) return '<p class="text-secondary mb-0">Sin registros en esta vista.</p>';
  return `<table class="table table-hover align-middle mb-0"><thead class="table-light"><tr>${cols.map(c=>`<th>${c[0]}</th>`).join('')}</tr></thead><tbody>
    ${rows.map(r=>`<tr class="${r.dias_tardanza>0 && r.estado_solicitud==='Aprobado'?'late':''}">${cols.map(c=>`<td>${c[1](r)}</td>`).join('')}</tr>`).join('')}
  </tbody></table>`;
}
const estudiante = r => `${esc(r.estudiante)}<br><small class="text-secondary">${esc(r.grado)}</small>${r.dias_tardanza>0?`<div class="text-danger fw-semibold">${r.dias_tardanza} día(s) de atraso</div>`:''}`;
function render(){
  const p = document.getElementById('panel');
  if (TAB==='pendientes') {
    p.innerHTML = table(DATA.pendientes, [
      ['Estudiante', estudiante],
      ['Material', r=>esc(r.material)],
      ['Solicitado', r=>esc(r.fecha_solicitud)],
      ['Entrega propuesta', r=>esc(r.fecha_devolucion)],
      ['', r=>`<div class="d-flex gap-1"><button class="btn btn-success btn-sm" data-ok="${r.id}">Aprobar</button><button class="btn btn-outline-danger btn-sm" data-no="${r.id}">Rechazar</button></div>`],
    ]);
  } else if (TAB==='activos') {
    p.innerHTML = table(DATA.activos, [
      ['Estudiante', estudiante],
      ['Material', r=>esc(r.material)],
      ['Desde', r=>esc(r.fecha_prestamo)],
      ['Debe devolver', r=>esc(r.fecha_devolucion)],
      ['', r=>`<button class="btn btn-danger btn-sm" data-dev="${r.id}">Marcar devuelto</button>`],
    ]);
  } else if (TAB==='atrasos') {
    p.innerHTML = `<p class="text-secondary">Hoy es ${DATA.hoy}. En rojo: préstamos aprobados cuya fecha de devolución ya pasó.</p>` +
      table(DATA.atrasados, [
        ['Estudiante', estudiante],
        ['Material', r=>esc(r.material)],
        ['Fecha límite', r=>esc(r.fecha_devolucion)],
        ['Días de tardanza', r=>`<span class="badge text-bg-danger">${r.dias_tardanza}</span>`],
        ['', r=>`<button class="btn btn-danger btn-sm" data-dev="${r.id}">Registrar devolución</button>`],
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
      ['Estado', r=>`<span class="badge ${r.estado_solicitud==='Pendiente'?'text-bg-warning':r.estado_solicitud==='Aprobado'&&r.dias_tardanza?'text-bg-danger':r.estado_solicitud==='Rechazado'||r.estado_solicitud==='Devuelto'?'text-bg-secondary':'text-bg-success'}">${esc(r.estado_solicitud)}</span>`],
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
  [...document.getElementById('tabs').children].forEach(x=>{
    x.classList.toggle('btn-dark', x===b);
    x.classList.toggle('btn-outline-dark', x!==b);
  });
  render();
};
load();
</script></body></html>
"""

LOGIN = HEAD + """
<main class="container py-5" style="max-width:420px">
  <section class="card shadow-sm">
    <div class="card-body">
      <h1 class="h4">Profesor</h1>
      <p class="text-secondary">Ingresa el PIN para abrir el panel.</p>
      <form method="post">
        <label class="form-label">PIN</label>
        <input class="form-control" name="pin" type="password" inputmode="numeric" required autofocus placeholder="••••"/>
        <button class="btn btn-success w-100 mt-3" type="submit">Entrar</button>
      </form>
      {% if error %}<p class="text-danger mt-3 mb-0">{{ error }}</p>{% endif %}
      <p class="mt-3 mb-0"><a href="/">Volver al catálogo</a></p>
    </div>
  </section>
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
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
