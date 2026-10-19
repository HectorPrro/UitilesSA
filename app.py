import hashlib
import os
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage
from datetime import date, datetime
from functools import wraps

from flask import Flask, jsonify, redirect, render_template_string, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "prestamos-escolares-dev")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prestamos.db"))
ADMIN_PIN = os.environ.get("ADMIN_PIN", "2010")



DOMINIO = "@sanagustin.edu.pe"



def enviar_codigo(destino, codigo, nombre):
    host = (os.environ.get("MAIL_SERVER") or "").strip()
    user = (os.environ.get("MAIL_USERNAME") or "").strip()
    password = (os.environ.get("MAIL_PASSWORD") or "").replace(" ", "").strip()
    port = int((os.environ.get("MAIL_PORT") or "587").strip() or "587")
    if not host or not user or not password:
        return False
    msg = EmailMessage()
    msg["Subject"] = "Código de verificación — Materiales San Agustín"
    msg["From"] = (os.environ.get("MAIL_FROM") or user).strip()
    msg["To"] = destino
    msg.set_content(
        f"Hola {nombre},\n\nTu código de verificación es {codigo}.\n"
        "Ingrésalo en la página de verificación para activar tu cuenta.\n"
    )
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg)
    return True


def hash_clave(clave, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", clave.encode(), salt.encode(), 120_000).hex()
    return salt, digest


def usuario_actual(conn):
    uid = session.get("usuario_id")
    if not uid:
        return None
    user = conn.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if not user or not user["is_verified"]:
        return None
    return user


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
            usuario_id INTEGER,
            FOREIGN KEY (material_id) REFERENCES materiales(id)
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_completo TEXT NOT NULL,
            grado_seccion TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'estudiante',
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_code TEXT
        );
        """
    )

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(usuarios)")]
    if cols and "email" not in cols:
        conn.execute("ALTER TABLE usuarios RENAME TO usuarios_old")
        conn.execute("""
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_completo TEXT NOT NULL,
                grado_seccion TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'estudiante',
                is_verified INTEGER NOT NULL DEFAULT 0,
                verification_code TEXT
            )
        """)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(solicitudes_prestamos)")]
    if "usuario_id" not in cols:
        conn.execute("ALTER TABLE solicitudes_prestamos ADD COLUMN usuario_id INTEGER")
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
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary btn-sm" href="/salir">Salir</a>
      <a class="btn btn-outline-success btn-sm" href="/admin">Acceso profesor</a>
    </div>
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
          <p class="small text-secondary mb-2">Perfil: <strong>{{ nombre }}</strong><br>{{ grado }} · {{ correo }}</p>
          <form id="form">
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
          <h2 class="h5 mt-4">Préstamos activos</h2><div id="activos" class="table-responsive mb-3"></div><h2 class="h5">Historial</h2>
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
function tabla(rows, vacio){
  if (!rows.length) return '<p class="text-secondary mb-0">'+vacio+'</p>';
  return `<table class="table table-hover align-middle mb-0"><thead class="table-light"><tr><th>Material</th><th>Estado</th><th>Entrega</th></tr></thead><tbody>
    ${rows.slice(0,40).map(s=>`<tr class="${s.dias_tardanza>0?'late':''}"><td>${esc(s.material)}</td>
    <td><span class="badge ${s.estado_solicitud==='Pendiente'?'text-bg-warning':s.estado_solicitud==='Aprobado'&&s.dias_tardanza?'text-bg-danger':s.estado_solicitud==='Rechazado'||s.estado_solicitud==='Devuelto'?'text-bg-secondary':'text-bg-success'}">${esc(s.estado_solicitud)}</span>
    ${s.dias_tardanza>0?`<div class="text-danger fw-semibold small mt-1">${s.dias_tardanza} día(s) de atraso</div>`:''}</td>
    <td>${s.fecha_devolucion||'—'}</td></tr>`).join('')}</tbody></table>`;
}
function renderMias(){
  const act = DATA.solicitudes.filter(s => s.estado_solicitud==='Pendiente' || s.estado_solicitud==='Aprobado');
  const hist = DATA.solicitudes.filter(s => s.estado_solicitud==='Devuelto' || s.estado_solicitud==='Rechazado');
  document.getElementById('activos').innerHTML = tabla(act, 'No tienes préstamos activos.');
  document.getElementById('mias').innerHTML = tabla(hist, 'Aún no hay historial.');
}
document.getElementById('form').addEventListener('submit', async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  const r = await fetch('/api/solicitudes', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j = await r.json();
  if (!r.ok) return toast(j.error||'Error');
  toast('Solicitud enviada. Queda pendiente de aprobación.');
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


CUENTA = HEAD + """
<nav class="navbar navbar-expand bg-white border-bottom">
  <div class="container">
    <span class="navbar-brand fw-semibold">Materiales escolares</span>
    <a class="btn btn-outline-success btn-sm" href="/admin">Acceso profesor</a>
  </div>
</nav>
<main class="container py-4" style="max-width:520px">
  <h1 class="h3">{{ titulo }}</h1>
  <p class="text-secondary">{{ subtitulo }}</p>
  <section class="card shadow-sm"><div class="card-body">
    <form method="post">
      {% if modo == 'registro' %}
      <label class="form-label">Nombre completo</label>
      <input class="form-control mb-2" name="nombre" required placeholder="Nombres y apellidos"/>
      <div class="row g-2">
        <div class="col-7">
          <label class="form-label">Grado</label>
          <select class="form-select" name="grado" required>
            <option value="">Elige</option>
            <option>6.º</option><option>7.º</option><option>8.º</option>
            <option>9.º</option><option>10.º</option><option>11.º</option>
          </select>
        </div>
        <div class="col-5">
          <label class="form-label">Sección</label>
          <select class="form-select" name="seccion" required>
            <option value="">Elige</option>
            <option>A</option><option>B</option><option>C</option><option>D</option><option>E</option>
          </select>
        </div>
      </div>
      <label class="form-label mt-2">Correo institucional</label>
      <input class="form-control mb-2" name="correo" type="email" required placeholder="nombre@sanagustin.edu.pe"/>
      {% elif modo == 'verificar' %}
      <label class="form-label">Código de 6 dígitos</label>
      <input class="form-control" name="codigo" required inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="000000"/>
      {% else %}
      <label class="form-label">Correo institucional</label>
      <input class="form-control mb-2" name="correo" type="email" required placeholder="usuario@sanagustin.edu.pe"/>
      {% endif %}
      {% if modo != 'verificar' %}
      <label class="form-label">Clave</label>
      <input class="form-control" name="clave" type="password" required minlength="4"/>
      {% endif %}
      <button class="btn btn-success w-100 mt-3" type="submit">{{ boton }}</button>
    </form>
    {% if aviso %}<p class="alert alert-warning mt-3 mb-0">{{ aviso }}</p>{% endif %}
    {% if error %}<p class="text-danger mt-3 mb-0">{{ error }}</p>{% endif %}
    <p class="mt-3 mb-0">
      {% if modo == 'registro' %}
      <a href="/login">Ya tengo cuenta</a>
      {% elif modo == 'verificar' %}
      <a href="/login">Volver al inicio de sesión</a>
      {% else %}
      <a href="/registro">Crear cuenta</a>
      {% endif %}
    </p>
  </div></section>
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""


def _render_cuenta(modo, error=None, aviso=None):
    meta = {
        "registro": ("Crear cuenta", "Registrarme", "Nombre, grado, sección y correo @sanagustin.edu.pe. Te enviaremos un código de 6 dígitos."),
        "login": ("Entrar", "Entrar", "Correo institucional y clave. La cuenta debe estar verificada."),
        "verificar": ("Verificar correo", "Confirmar código", "Escribe el código de 6 dígitos que enviamos a tu correo."),
    }
    titulo, boton, subtitulo = meta[modo]
    return render_template_string(
        CUENTA, title=titulo, css=BASE_CSS, modo=modo,
        titulo=titulo, boton=boton, error=error, aviso=aviso, subtitulo=subtitulo,
    )


GRADOS = {"6.º", "7.º", "8.º", "9.º", "10.º", "11.º"}
SECCIONES = {"A", "B", "C", "D", "E"}


def _codigo():
    return f"{secrets.randbelow(1_000_000):06d}"


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("usuario_id") and request.method == "GET":
        return redirect("/")
    if request.method == "GET":
        return _render_cuenta("login")
    correo = (request.form.get("correo") or "").strip().lower()
    clave = request.form.get("clave") or ""
    if not correo.endswith(DOMINIO):
        return _render_cuenta("login", "El correo debe ser " + DOMINIO)
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (correo,)).fetchone()
    conn.close()
    if not user or hash_clave(clave, user["salt"])[1] != user["password_hash"]:
        return _render_cuenta("login", "Correo o clave incorrectos")
    if not user["is_verified"]:
        session["pendiente_id"] = user["id"]
        return redirect("/verificar")
    session["usuario_id"] = user["id"]
    session.pop("pendiente_id", None)
    return redirect("/")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return _render_cuenta("registro")
    nombre = (request.form.get("nombre") or "").strip()
    grado = (request.form.get("grado") or "").strip()
    seccion = (request.form.get("seccion") or "").strip().upper()
    correo = (request.form.get("correo") or "").strip().lower()
    clave = request.form.get("clave") or ""
    if len(nombre) < 5:
        return _render_cuenta("registro", "Escribe tu nombre completo")
    if grado not in GRADOS or seccion not in SECCIONES:
        return _render_cuenta("registro", "Elige grado y sección de la lista")
    if not correo.endswith(DOMINIO) or correo.count("@") != 1 or len(correo.split("@")[0]) < 2:
        return _render_cuenta("registro", "Usa un correo institucional " + DOMINIO)
    if len(clave) < 4:
        return _render_cuenta("registro", "La clave debe tener al menos 4 caracteres")
    conn = get_db()
    if conn.execute("SELECT id FROM usuarios WHERE email = ?", (correo,)).fetchone():
        conn.close()
        return _render_cuenta("registro", "Ese correo ya está registrado")
    salt, digest = hash_clave(clave)
    codigo = _codigo()
    grado_seccion = f"{grado} {seccion}"
    cur = conn.execute(
        """INSERT INTO usuarios
           (nombre_completo, grado_seccion, email, password_hash, salt, rol, is_verified, verification_code)
           VALUES (?, ?, ?, ?, ?, 'estudiante', 0, ?)""",
        (nombre, grado_seccion, correo, digest, salt, codigo),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    session["pendiente_id"] = uid
    session.pop("usuario_id", None)
    try:
        enviado = enviar_codigo(correo, codigo, nombre)
    except Exception:
        enviado = False
    if not enviado:
        session["codigo_local"] = codigo
    return redirect("/verificar")


@app.route("/verificar", methods=["GET", "POST"])
def verificar():
    uid = session.get("pendiente_id")
    if not uid:
        return redirect("/login")
    aviso = None
    mostrar_codigo = bool(session.pop("codigo_local", None))
    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    if not user:
        conn.close()
        return redirect("/registro")
    if request.method == "GET":
        if mostrar_codigo and user["verification_code"]:
            aviso = "No se pudo enviar el correo. Copia este código y confírmalo abajo: " + user["verification_code"]
        conn.close()
        return _render_cuenta("verificar", aviso=aviso)
    codigo = (request.form.get("codigo") or "").strip()
    if codigo != (user["verification_code"] or "") or len(codigo) != 6:
        conn.close()
        return _render_cuenta("verificar", "El código no coincide")
    conn.execute("UPDATE usuarios SET is_verified = 1, verification_code = NULL WHERE id = ?", (uid,))
    conn.commit()
    conn.close()
    session["usuario_id"] = uid
    session.pop("pendiente_id", None)
    return redirect("/")


@app.route("/", methods=["GET"])
def inicio():
    conn = get_db()
    user = usuario_actual(conn)
    conn.close()
    if not user or not user["is_verified"]:
        return redirect("/login")
    return render_template_string(
        ESTUDIANTE, title="Materiales escolares", css=BASE_CSS,
        nombre=user["nombre_completo"], grado=user["grado_seccion"], correo=user["email"],
    )


@app.get("/estudiante")
def estudiante():
    return redirect("/")




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


@app.get("/salir")
def salir_estudiante():
    session.pop("usuario_id", None)
    session.pop("pendiente_id", None)
    return redirect("/login")


@app.get("/admin/salir")
def salir():
    session.clear()
    return redirect("/admin")


@app.get("/api/publico")
def publico():
    conn = get_db()
    user = usuario_actual(conn)
    if not user:
        conn.close()
        return jsonify({"error": "Inicia sesión"}), 401
    sync_tardanzas(conn)
    conn.commit()
    nombres = material_map(conn)
    disponibles = [dict(r) for r in conn.execute("SELECT id, nombre, estado FROM materiales WHERE estado = 'Disponible' ORDER BY nombre")]
    sols = [fila(r, nombres) for r in conn.execute(
        "SELECT * FROM solicitudes_prestamos WHERE usuario_id = ? ORDER BY id DESC LIMIT 80",
        (user["id"],),
    )]
    conn.close()
    return jsonify({"hoy": today().isoformat(), "disponibles": disponibles, "solicitudes": sols})


@app.post("/api/solicitudes")
def crear_solicitud():
    body = request.get_json(force=True, silent=True) or {}
    fecha = (body.get("fecha_devolucion") or "").strip()
    try:
        mid = int(body.get("material_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Elige un material"}), 400
    conn = get_db()
    user = usuario_actual(conn)
    if not user:
        conn.close()
        return jsonify({"error": "Inicia sesión"}), 401
    estudiante = user["nombre_completo"]
    grado = user["grado_seccion"]
    try:
        if parse_date(fecha) < today():
            return jsonify({"error": "La fecha de entrega no puede ser anterior a hoy"}), 400
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400
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
           (estudiante, grado, material_id, fecha_solicitud, fecha_devolucion, estado_solicitud, dias_tardanza, usuario_id)
           VALUES (?, ?, ?, ?, ?, 'Pendiente', 0, ?)""",
        (estudiante, grado, mid, today().isoformat(), fecha, user["id"]),
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
