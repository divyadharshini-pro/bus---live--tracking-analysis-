from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string
import sqlite3
import hashlib
import secrets
import math
import time
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "smartbus-demo-secret-change-this")
DB_PATH = os.environ.get("BUS_DB_PATH", "smartbus.db")

# Render/production-safe SQLite connection settings
SQLITE_TIMEOUT = 15

STALE_SECONDS = 30
BUNCHING_KM = 0.50


# =========================================================
# DATABASE
# =========================================================
def db():
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        120000
    ).hex()
    return f"{salt}${hashed}"


def check_password(password, stored):
    try:
        salt, old_hash = stored.split("$", 1)
        new_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            120000
        ).hex()
        return secrets.compare_digest(new_hash, old_hash)
    except Exception:
        return False


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS buses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_number TEXT UNIQUE NOT NULL,
            driver_name TEXT NOT NULL DEFAULT '',
            driver_phone TEXT NOT NULL DEFAULT '',
            driver_username TEXT UNIQUE,
            driver_password TEXT,
            lat REAL,
            lon REAL,
            speed REAL DEFAULT 0,
            accuracy REAL,
            updated REAL,
            active INTEGER DEFAULT 1
        )
    """)

    # Migrate an older smartbus.db instead of crashing when Render reuses it.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(buses)").fetchall()}
    required = {
        "driver_name": "TEXT NOT NULL DEFAULT ''",
        "driver_phone": "TEXT NOT NULL DEFAULT ''",
        "driver_username": "TEXT",
        "driver_password": "TEXT",
        "lat": "REAL",
        "lon": "REAL",
        "speed": "REAL DEFAULT 0",
        "accuracy": "REAL",
        "updated": "REAL",
        "active": "INTEGER DEFAULT 1",
    }
    for column, definition in required.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE buses ADD COLUMN {column} {definition}")

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users(username,password,role) VALUES(?,?,?)",
            ("admin", hash_password("admin123"), "admin")
        )

    # Add the demo buses only when the database is completely empty.
    if conn.execute("SELECT COUNT(*) FROM buses").fetchone()[0] == 0:
        demo = [
            ("TN 38 AB 1001", "Demo Driver 1", "9000000001", "driver1001", "bus1001"),
            ("TN 38 AB 1002", "Demo Driver 2", "9000000002", "driver1002", "bus1002"),
            ("TN 38 AB 1003", "Demo Driver 3", "9000000003", "driver1003", "bus1003"),
        ]
        for bus_number, name, phone, username, password in demo:
            conn.execute("""
                INSERT INTO buses
                (bus_number,driver_name,driver_phone,driver_username,driver_password,active)
                VALUES(?,?,?,?,?,1)
            """, (bus_number, name, phone, username, hash_password(password)))

    conn.commit()
    conn.close()

init_db()


# =========================================================
# HELPERS
# =========================================================
def distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fresh(updated):
    return bool(updated) and time.time() - updated <= STALE_SECONDS


def current_user():
    return session.get("username")


def bus_public(row, rows=None):
    # Never expose password hashes or driver login usernames to passengers.
    b = {
        "id": row["id"],
        "bus_number": row["bus_number"],
        "driver_name": row["driver_name"],
        "driver_phone": row["driver_phone"],
        "lat": row["lat"],
        "lon": row["lon"],
        "speed": row["speed"] or 0,
        "accuracy": row["accuracy"],
        "updated": row["updated"],
        "active": row["active"],
    }
    b["fresh"] = fresh(b.get("updated"))
    b["status"] = "LIVE" if b["fresh"] else "WAITING"
    b["age_seconds"] = round(time.time() - b["updated"], 1) if b.get("updated") else None

    nearest = None
    if rows and b.get("lat") is not None and b.get("lon") is not None:
        for other in rows:
            if other["id"] == row["id"]:
                continue
            if other["lat"] is None or other["lon"] is None:
                continue
            d = distance_km(b["lat"], b["lon"], other["lat"], other["lon"])
            if nearest is None or d < nearest[1]:
                nearest = (other, d)

    if nearest:
        other, d = nearest
        b["nearest_bus"] = other["bus_number"]
        b["nearest_distance_km"] = round(d, 2)
        b["bunching"] = (b["fresh"] and fresh(other["updated"]) and d <= BUNCHING_KM)
    else:
        b["nearest_bus"] = None
        b["nearest_distance_km"] = None
        b["bunching"] = False
    return b


def login_required(role=None):
    if not current_user():
        return False
    if role and session.get("role") != role:
        return False
    return True


# =========================================================
# AUTH
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.form
        username = data.get("username", "").strip()
        password = data.get("password", "")

        conn = db()
        user = conn.execute(
            "SELECT * FROM users WHERE lower(username)=lower(?)",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password(password, user["password"]):
            session["username"] = user["username"]
            session["role"] = user["role"]
            if user["role"] == "admin":
                return redirect("/admin")
            return redirect("/driver")

        return render_template_string(LOGIN_HTML, error="Invalid username or password.")

    return render_template_string(LOGIN_HTML, error="")


@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =========================================================
# PAGES
# =========================================================
@app.get("/")
def passenger():
    return render_template_string(PASSENGER_HTML)


@app.get("/admin")
def admin():
    if not login_required("admin"):
        return redirect("/login")
    return render_template_string(ADMIN_HTML, username=current_user())


@app.get("/driver")
def driver():
    if not login_required("driver"):
        return redirect("/login")
    return render_template_string(DRIVER_HTML, username=current_user())


# =========================================================
# API
# =========================================================
@app.get("/api/buses")
def api_buses():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM buses WHERE active=1 ORDER BY bus_number"
    ).fetchall()
    conn.close()
    return jsonify({
        "buses": [bus_public(r, rows) for r in rows],
        "server_time": time.time()
    })


@app.get("/api/bus/<path:bus_number>")
def api_bus(bus_number):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM buses WHERE active=1 ORDER BY bus_number"
    ).fetchall()
    conn.close()

    target = next(
        (r for r in rows if r["bus_number"].lower() == bus_number.strip().lower()),
        None
    )
    if not target:
        return jsonify({"error": "Bus not found"}), 404

    return jsonify(bus_public(target, rows))


@app.post("/api/admin/add-bus")
def api_add_bus():
    if not login_required("admin"):
        return jsonify({"error": "Admin login required"}), 401

    data = request.get_json(silent=True) or {}
    bus_number = str(data.get("bus_number", "")).strip()
    driver_name = str(data.get("driver_name", "")).strip()
    driver_phone = str(data.get("driver_phone", "")).strip()
    driver_username = str(data.get("driver_username", "")).strip()
    driver_password = str(data.get("driver_password", ""))

    if not all([bus_number, driver_name, driver_phone, driver_username, driver_password]):
        return jsonify({"error": "All fields are required."}), 400

    if len(driver_password) < 6:
        return jsonify({"error": "Driver password must be at least 6 characters."}), 400

    conn = db()
    try:
        conn.execute("""
            INSERT INTO buses
            (bus_number,driver_name,driver_phone,driver_username,driver_password,active)
            VALUES(?,?,?,?,?,1)
        """, (
            bus_number,
            driver_name,
            driver_phone,
            driver_username,
            hash_password(driver_password)
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            "error": "Bus number or driver username already exists."
        }), 409

    conn.close()
    return jsonify({"message": "Bus and driver created successfully."}), 201


@app.post("/api/driver/location")
def api_driver_location():
    if not login_required("driver"):
        return jsonify({"error": "Driver login required"}), 401

    data = request.get_json(silent=True) or {}

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        speed_mps = float(data.get("speed", 0) or 0)
        accuracy = float(data.get("accuracy")) if data.get("accuracy") is not None else None
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid GPS data"}), 400

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Invalid coordinates"}), 400

    # A browser GPS speed is normally metres/second.
    speed_kmh = max(0, speed_mps) * 3.6

    conn = db()
    bus = conn.execute(
        "SELECT * FROM buses WHERE driver_username=? AND active=1",
        (current_user(),)
    ).fetchone()

    if not bus:
        conn.close()
        return jsonify({"error": "No bus is assigned to this driver."}), 404

    conn.execute("""
        UPDATE buses
        SET lat=?,lon=?,speed=?,accuracy=?,updated=?
        WHERE id=?
    """, (lat, lon, speed_kmh, accuracy, time.time(), bus["id"]))
    conn.commit()
    conn.close()

    return jsonify({"message": "Live GPS updated", "bus_number": bus["bus_number"]})


@app.post("/api/driver/stop")
def api_driver_stop():
    if not login_required("driver"):
        return jsonify({"error": "Driver login required"}), 401

    conn = db()
    conn.execute("""
        UPDATE buses SET updated=NULL, speed=0
        WHERE driver_username=?
    """, (current_user(),))
    conn.commit()
    conn.close()

    return jsonify({"message": "Trip stopped"})


# =========================================================
# LOGIN UI
# =========================================================
LOGIN_HTML = r"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartBus Login</title>
<style>
body{margin:0;font-family:Arial;background:linear-gradient(135deg,#102b5c,#2563a6);min-height:100vh;display:grid;place-items:center}
.box{width:min(400px,88%);background:white;border-radius:20px;padding:28px;box-shadow:0 20px 50px #0004}
.logo{text-align:center;font-size:42px}
h1{text-align:center;color:#173b7a;margin:8px 0}
p{text-align:center;color:#667085}
input,button{width:100%;padding:14px;margin-top:10px;border-radius:10px;border:1px solid #ccd4e0;font-size:15px;box-sizing:border-box}
button{background:#173b7a;color:white;border:0;font-weight:bold}
.err{background:#fee4e2;color:#b42318;padding:10px;border-radius:9px;margin-top:12px}
.demo{background:#f2f5f9;border-radius:10px;padding:12px;margin-top:16px;font-size:13px}
a{display:block;text-align:center;margin-top:18px;color:#173b7a}
</style>
</head>
<body>
<div class="box">
<div class="logo">🚌</div>
<h1>SmartBus</h1>
<p>Live Bus Tracking System</p>
<form method="post">
<input name="username" placeholder="Username" autocomplete="username" required>
<input name="password" type="password" placeholder="Password" autocomplete="current-password" required>
<button type="submit">🔐 LOGIN</button>
</form>
{% if error %}<div class="err">{{error}}</div>{% endif %}
<div class="demo">
<b>Demo Admin</b><br>
Username: <b>admin</b><br>
Password: <b>admin123</b><br><br>
<b>Demo Drivers</b><br>
driver1001 / bus1001<br>
driver1002 / bus1002<br>
driver1003 / bus1003
</div>
<a href="/">← Passenger Tracking</a>
</div>
</body>
</html>
"""


# =========================================================
# ADMIN UI
# =========================================================
ADMIN_HTML = r"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartBus Admin</title>
<style>
body{margin:0;font-family:Arial;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px}
main{max-width:1000px;margin:auto;padding:16px}
.card{background:white;border-radius:16px;padding:18px;margin-bottom:15px;box-shadow:0 4px 16px #0001}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
input,button{width:100%;box-sizing:border-box;padding:13px;border-radius:10px;border:1px solid #ccd4e0;font-size:15px}
button{background:#173b7a;color:white;border:0;font-weight:bold}
.stat{font-size:26px;font-weight:bold}
.bus{border:1px solid #e1e6ee;border-radius:12px;padding:13px}
.badge{display:inline-block;padding:5px 8px;border-radius:99px;background:#e8f7ed;color:#18753a;font-size:12px}
.wait{background:#fff3d6;color:#9a6500}
a{color:#173b7a}
.success{background:#e8f7ed;color:#18753a;padding:10px;border-radius:9px;margin-top:10px}
.error{background:#fee4e2;color:#b42318;padding:10px;border-radius:9px;margin-top:10px}
</style>
</head>
<body>
<header>
<h2>⚙️ SmartBus Admin Dashboard</h2>
<div>Welcome, {{username}} · <a href="/logout" style="color:white">Logout</a></div>
</header>
<main>
<div class="card">
<h3>➕ Register New Bus & Driver</h3>
<div class="grid">
<input id="bus" placeholder="Bus Number e.g. TN 38 AB 1234">
<input id="name" placeholder="Driver Name">
<input id="phone" placeholder="Driver Mobile">
<input id="du" placeholder="Driver Login Username">
<input id="dp" type="password" placeholder="Driver Login Password">
</div>
<button style="margin-top:12px" onclick="addBus()">ADD BUS + CREATE DRIVER</button>
<div id="msg"></div>
</div>

<div class="card">
<h3>🚌 Registered Buses</h3>
<div id="list" class="grid"></div>
</div>

<div class="card">
<a href="/">🗺️ Passenger View</a> &nbsp; | &nbsp;
<a href="/driver">📱 Driver Login</a>
</div>
</main>

<script>
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function addBus(){
 const payload={
  bus_number:document.getElementById('bus').value.trim(),
  driver_name:document.getElementById('name').value.trim(),
  driver_phone:document.getElementById('phone').value.trim(),
  driver_username:document.getElementById('du').value.trim(),
  driver_password:document.getElementById('dp').value
 };
 const msg=document.getElementById('msg');
 try{
  const r=await fetch('/api/admin/add-bus',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json();
  if(!r.ok){msg.className='error';msg.textContent='❌ '+d.error;return}
  msg.className='success';msg.textContent='✅ Bus and driver created.';
  ['bus','name','phone','du','dp'].forEach(x=>document.getElementById(x).value='');
  load();
 }catch(e){msg.className='error';msg.textContent='❌ Server error'}
}
async function load(){
 const r=await fetch('/api/buses');const d=await r.json();
 document.getElementById('list').innerHTML=(d.buses||[]).map(b=>`
 <div class="bus">
 <b>🚌 ${esc(b.bus_number)}</b><br>
 Driver: ${esc(b.driver_name)}<br>
 Mobile: ${esc(b.driver_phone)}<br>
 <span class="badge ${b.fresh?'':'wait'}">${b.fresh?'LIVE':'WAITING'}</span>
 </div>`).join('');
}
load();setInterval(load,3000);
</script>
</body>
</html>
"""


# =========================================================
# DRIVER UI
# =========================================================
DRIVER_HTML = r"""
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartBus Driver</title>
<style>
body{margin:0;font-family:Arial;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px}
main{max-width:650px;margin:auto;padding:16px}
.card{background:white;border-radius:16px;padding:20px;margin-bottom:15px;box-shadow:0 4px 16px #0001}
button{width:100%;padding:15px;border:0;border-radius:10px;margin-top:10px;background:#173b7a;color:white;font-weight:bold;font-size:16px}
.stop{background:#b42318}
.live{background:#e8f7ed;color:#18753a;padding:12px;border-radius:10px;margin-top:12px}
.wait{background:#fff3d6;color:#9a6500;padding:12px;border-radius:10px;margin-top:12px}
a{color:#173b7a}
</style>
</head>
<body>
<header>
<h2>📱 Driver GPS</h2>
<div>{{username}} · <a href="/logout" style="color:white">Logout</a></div>
</header>
<main>
<div class="card">
<h3>Assigned Bus</h3>
<div id="bus" style="font-size:22px;font-weight:bold">Loading...</div>
<div id="driver"></div>
<button id="start" onclick="startGPS()">🟢 START TRIP & GPS</button>
<button id="stop" class="stop" onclick="stopGPS()" style="display:none">⛔ STOP TRIP</button>
<div id="status" class="wait">GPS is not running.</div>
</div>

<div class="card">
<b>📍 Demo Instructions</b>
<p>Allow location permission when the browser asks. Keep this page open while driving.</p>
<p>Your phone GPS is sent to the server and linked to your assigned bus.</p>
</div>
</main>

<script>
let watch=null;
let assigned=null;

function msg(text,live=false){
 const e=document.getElementById('status');
 e.textContent=text;e.className=live?'live':'wait';
}
async function load(){
 const r=await fetch('/api/buses');const d=await r.json();
 const me=await fetch('/api/driver/me');
 const md=await me.json();
 if(!me.ok || !md.bus){document.getElementById('bus').textContent='No bus assigned';return}
 assigned=md.bus;
 document.getElementById('bus').textContent='🚌 '+assigned.bus_number;
 document.getElementById('driver').textContent='Driver: '+assigned.driver_name;
}
async function send(pos){
 try{
  const r=await fetch('/api/driver/location',{
   method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({
    lat:pos.coords.latitude,
    lon:pos.coords.longitude,
    speed:pos.coords.speed||0,
    accuracy:pos.coords.accuracy
   })
  });
  const d=await r.json();
  if(!r.ok){msg('❌ '+d.error);return}
  msg('🟢 LIVE GPS · Accuracy '+Math.round(pos.coords.accuracy)+' m',true);
 }catch(e){msg('❌ Network error')}
}
function startGPS(){
 if(!navigator.geolocation){msg('❌ GPS is not supported');return}
 msg('📍 Requesting GPS permission...');
 watch=navigator.geolocation.watchPosition(send,e=>msg('❌ GPS: '+e.message),{
  enableHighAccuracy:true,maximumAge:5000,timeout:15000
    
