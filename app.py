from flask import Flask, jsonify, request, render_template_string
import sqlite3
import math
import time
import os

app = Flask(__name__)

DB_PATH = os.environ.get("BUS_DB_PATH", "buses.db")
STALE_SECONDS = 30
BUNCHING_KM = 0.50


# -----------------------------
# Database
# -----------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS buses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bus_number TEXT UNIQUE NOT NULL,
            driver_name TEXT NOT NULL,
            driver_phone TEXT NOT NULL,
            lat REAL,
            lon REAL,
            speed REAL DEFAULT 0,
            accuracy REAL,
            updated REAL,
            active INTEGER DEFAULT 1
        )
    """)

    # Demo buses are inserted only if the database is empty.
    count = conn.execute("SELECT COUNT(*) AS c FROM buses").fetchone()["c"]
    if count == 0:
        demo = [
            ("TN 38 AB 1001", "Demo Driver 1", "9000000001", 11.0168, 76.9558),
            ("TN 38 AB 1002", "Demo Driver 2", "9000000002", 11.0200, 76.9620),
            ("TN 38 AB 1003", "Demo Driver 3", "9000000003", 11.0250, 76.9700),
        ]
        conn.executemany("""
            INSERT INTO buses
            (bus_number, driver_name, driver_phone, lat, lon, speed, updated, active)
            VALUES (?, ?, ?, ?, ?, 0, ?, 1)
        """, [(*row, time.time()) for row in demo])

    conn.commit()
    conn.close()


init_db()


# -----------------------------
# Helpers
# -----------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_fresh(updated):
    return bool(updated) and (time.time() - updated <= STALE_SECONDS)


def bus_dict(row, all_rows=None):
    bus = dict(row)
    bus["fresh"] = is_fresh(bus.get("updated"))
    bus["status"] = "LIVE" if bus["fresh"] else "WAITING"

    if bus["fresh"]:
        bus["age_seconds"] = round(max(0, time.time() - bus["updated"]), 1)
    else:
        bus["age_seconds"] = None

    # Find nearest other bus.
    nearest = None
    if all_rows:
        for other in all_rows:
            if other["id"] == row["id"]:
                continue
            if row["lat"] is None or row["lon"] is None:
                continue
            if other["lat"] is None or other["lon"] is None:
                continue

            d = haversine(row["lat"], row["lon"], other["lat"], other["lon"])
            if nearest is None or d < nearest["distance_km"]:
                nearest = {
                    "bus_number": other["bus_number"],
                    "distance_km": d
                }

    if nearest:
        bus["nearest_bus"] = nearest["bus_number"]
        bus["nearest_distance_km"] = round(nearest["distance_km"], 2)
        bus["bunching"] = (
            bus["fresh"]
            and is_fresh(row["updated"])
            and is_fresh(
                next(
                    (x["updated"] for x in all_rows if x["bus_number"] == nearest["bus_number"]),
                    0
                )
            )
            and nearest["distance_km"] <= BUNCHING_KM
        )
    else:
        bus["nearest_bus"] = None
        bus["nearest_distance_km"] = None
        bus["bunching"] = False

    return bus


# -----------------------------
# Pages
# -----------------------------
@app.route("/")
def home():
    return render_template_string(PASSENGER_HTML)


@app.route("/driver")
def driver():
    return render_template_string(DRIVER_HTML)


@app.route("/admin")
def admin():
    return render_template_string(ADMIN_HTML)


# -----------------------------
# APIs
# -----------------------------
@app.get("/api/buses")
def api_buses():
    conn = get_db()
    rows = conn.execute("SELECT * FROM buses WHERE active = 1 ORDER BY bus_number").fetchall()
    conn.close()

    data = [bus_dict(row, rows) for row in rows]
    return jsonify({"buses": data, "server_time": time.time()})


@app.get("/api/bus/<path:bus_number>")
def api_bus(bus_number):
    conn = get_db()
    rows = conn.execute("SELECT * FROM buses WHERE active = 1 ORDER BY bus_number").fetchall()
    conn.close()

    target = next(
        (row for row in rows if row["bus_number"].lower() == bus_number.strip().lower()),
        None
    )

    if target is None:
        return jsonify({"error": "Bus not found"}), 404

    return jsonify(bus_dict(target, rows))


@app.post("/api/buses")
def api_add_bus():
    data = request.get_json(silent=True) or {}

    bus_number = str(data.get("bus_number", "")).strip()
    driver_name = str(data.get("driver_name", "")).strip()
    driver_phone = str(data.get("driver_phone", "")).strip()

    if not bus_number or not driver_name or not driver_phone:
        return jsonify({
            "error": "Bus number, driver name and driver mobile are required."
        }), 400

    conn = get_db()
    try:
        cur = conn.execute("""
            INSERT INTO buses
            (bus_number, driver_name, driver_phone, active)
            VALUES (?, ?, ?, 1)
        """, (bus_number, driver_name, driver_phone))
        conn.commit()
        bus_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "This bus number already exists."}), 409

    row = conn.execute("SELECT * FROM buses WHERE id = ?", (bus_id,)).fetchone()
    conn.close()

    return jsonify({
        "message": "Bus registered successfully",
        "bus": dict(row)
    }), 201


@app.post("/api/location")
def api_location():
    data = request.get_json(silent=True) or {}

    bus_number = str(data.get("bus_number", "")).strip()
    lat = data.get("lat")
    lon = data.get("lon")
    speed = data.get("speed", 0)
    accuracy = data.get("accuracy")

    if not bus_number:
        return jsonify({"error": "Bus number is required"}), 400

    try:
        lat = float(lat)
        lon = float(lon)
        speed = float(speed or 0)
        accuracy = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid GPS values"}), 400

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Invalid coordinates"}), 400

    if speed < 0:
        speed = 0

    conn = get_db()
    cur = conn.execute("""
        UPDATE buses
        SET lat = ?, lon = ?, speed = ?, accuracy = ?, updated = ?, active = 1
        WHERE lower(bus_number) = lower(?)
    """, (lat, lon, speed * 3.6 if speed <= 60 else speed, accuracy, time.time(), bus_number))

    if cur.rowcount == 0:
        conn.close()
        return jsonify({"error": "Bus not registered"}), 404

    conn.commit()
    row = conn.execute(
        "SELECT * FROM buses WHERE lower(bus_number) = lower(?)",
        (bus_number,)
    ).fetchone()
    conn.close()

    return jsonify({
        "message": "GPS updated",
        "bus": dict(row)
    })


@app.post("/api/stop")
def api_stop():
    data = request.get_json(silent=True) or {}
    bus_number = str(data.get("bus_number", "")).strip()

    if not bus_number:
        return jsonify({"error": "Bus number is required"}), 400

    conn = get_db()
    cur = conn.execute("""
        UPDATE buses
        SET updated = NULL, speed = 0
        WHERE lower(bus_number) = lower(?)
    """, (bus_number,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return jsonify({"error": "Bus not found"}), 404

    return jsonify({"message": "Trip stopped"})


# -----------------------------
# Passenger UI
# -----------------------------
PASSENGER_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Where is my Bus?</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px 16px}
header h1{margin:0;font-size:24px}
header p{margin:6px 0 0;opacity:.9}
.container{max-width:1100px;margin:auto;padding:16px}
.search{display:flex;gap:8px;margin-bottom:14px}
input,select,button{font:inherit}
input,select{width:100%;padding:13px;border:1px solid #ccd4e0;border-radius:10px;background:white}
button{padding:13px 17px;border:0;border-radius:10px;background:#173b7a;color:white;font-weight:bold}
button.secondary{background:#5c677d}
#map{height:430px;border-radius:14px;overflow:hidden;box-shadow:0 4px 18px #0001}
.card{background:white;border-radius:14px;padding:15px;margin-top:14px;box-shadow:0 3px 14px #0001}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.badge{display:inline-block;padding:5px 9px;border-radius:999px;background:#e8f7ed;color:#18753a;font-size:12px;font-weight:bold}
.badge.wait{background:#fff3d6;color:#9a6500}
.metric{font-size:13px;color:#657086;margin-top:6px}
.big{font-size:21px;font-weight:bold;margin-top:5px}
a{color:white}
.small{font-size:12px;color:#667085}
</style>
</head>
<body>
<header>
  <h1>🚌 Where is my Bus?</h1>
  <p>Search a registered bus and see its live driver-phone GPS.</p>
</header>

<div class="container">
  <div class="search">
    <input id="search" placeholder="Enter bus number e.g. TN 38 AB 1234">
    <button onclick="searchBus()">Track</button>
  </div>

  <div id="result" class="card">
    <b>Live Bus Tracking</b>
    <div class="small">Search a bus number or select a bus below.</div>
  </div>

  <div id="map"></div>

  <div class="card">
    <h3>All Registered Buses</h3>
    <div id="busList" class="grid"></div>
  </div>

  <div class="card">
    <a href="/driver">📱 Driver Mode</a>
    &nbsp; | &nbsp;
    <a href="/admin">⚙️ Add Bus</a>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map('map').setView([11.0168,76.9558], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
  attribution:'© OpenStreetMap contributors'
}).addTo(map);

const markers = {};
let selectedBus = null;

function esc(s){
  return String(s ?? '').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
}

function markerIcon(){
  return L.divIcon({
    className:'',
    html:'<div style="font-size:30px">🚌</div>',
    iconSize:[34,34],
    iconAnchor:[17,17]
  });
}

async function loadBuses(){
  try{
    const r = await fetch('/api/buses');
    const data = await r.json();
    const buses = data.buses || [];
    renderList(buses);
    buses.forEach(updateMarker);
    if(selectedBus){
      const b = buses.find(x=>x.bus_number.toLowerCase()===selectedBus.toLowerCase());
      if(b) showBus(b,false);
    }
  }catch(e){
    document.getElementById('result').innerHTML='<b>Server connection error.</b>';
  }
}

function updateMarker(b){
  if(b.lat == null || b.lon == null) return;
  const popup = `
    <b>${esc(b.bus_number)}</b><br>
    ${b.fresh ? '🟢 LIVE' : '🟡 WAITING'}<br>
    Speed: ${Number(b.speed||0).toFixed(1)} km/h
  `;
  if(!markers[b.bus_number]){
    markers[b.bus_number] = L.marker([b.lat,b.lon],{icon:markerIcon()}).addTo(map);
  }else{
    markers[b.bus_number].setLatLng([b.lat,b.lon]);
  }
  markers[b.bus_number].bindPopup(popup);
}

function renderList(buses){
  document.getElementById('busList').innerHTML = buses.map(b=>`
    <div class="card" style="margin:0;cursor:pointer" onclick="track('${encodeURIComponent(b.bus_number)}')">
      <b>${esc(b.bus_number)}</b>
      <div class="metric">${esc(b.driver_name)}</div>
      <div style="margin-top:8px">
        <span class="badge ${b.fresh?'':'wait'}">${b.fresh?'🟢 LIVE':'🟡 WAITING'}</span>
      </div>
      <div class="metric">Speed: ${Number(b.speed||0).toFixed(1)} km/h</div>
    </div>
  `).join('');
}

function track(encoded){
  document.getElementById('search').value=decodeURIComponent(encoded);
  searchBus();
}

async function searchBus(){
  const q=document.getElementById('search').value.trim();
  if(!q){
    document.getElementById('result').innerHTML='<b>Enter a bus number.</b>';
    return;
  }
  try{
    const r=await fetch('/api/bus/'+encodeURIComponent(q));
    const b=await r.json();
    if(!r.ok){document.getElementById('result').innerHTML='<b>❌ Bus not found.</b>';return;}
    showBus(b,true);
  }catch(e){
    document.getElementById('result').innerHTML='<b>Connection error.</b>';
  }
}

function showBus(b,zoom){
  selectedBus=b.bus_number;
  const live=b.fresh;
  document.getElementById('result').innerHTML=`
    <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap">
      <div>
        <div class="big">🚌 ${esc(b.bus_number)}</div>
        <div class="metric">Driver: ${esc(b.driver_name)}</div>
      </div>
      <span class="badge ${live?'':'wait'}">${live?'🟢 LIVE':'🟡 WAITING'}</span>
    </div>
    <div class="grid" style="margin-top:12px">
      <div><div class="metric">Speed</div><b>${Number(b.speed||0).toFixed(1)} km/h</b></div>
      <div><div class="metric">GPS Accuracy</div><b>${b.accuracy!=null?Number(b.accuracy).toFixed(0)+' m':'-'}</b></div>
      <div><div class="metric">Last Update</div><b>${live?(Number(b.age_seconds).toFixed(0)+' sec ago'):'Waiting for GPS'}</b></div>
      <div><div class="metric">Nearest Bus</div><b>${b.nearest_bus?esc(b.nearest_bus)+' ('+Number(b.nearest_distance_km).toFixed(2)+' km)':'-'}</b></div>
    </div>
    ${b.bunching?'<div style="margin-top:12px;color:#b42318;font-weight:bold">⚠️ Bunching detected</div>':''}
  `;

  if(b.lat!=null && b.lon!=null){
    updateMarker(b);
    if(zoom) map.setView([b.lat,b.lon],16);
  }
}

document.getElementById('search').addEventListener('keydown',e=>{
  if(e.key==='Enter') searchBus();
});

loadBuses();
setInterval(loadBuses,3000);
</script>
</body>
</html>
"""


# -----------------------------
# Driver UI
# -----------------------------
DRIVER_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Driver GPS</title>
<style>
body{margin:0;font-family:Arial;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px}
main{max-width:650px;margin:auto;padding:16px}
.card{background:white;padding:18px;border-radius:14px;box-shadow:0 3px 15px #0001;margin-bottom:14px}
input,select,button{width:100%;padding:13px;margin-top:8px;border-radius:10px;border:1px solid #ccd4e0;font:inherit}
button{background:#173b7a;color:white;border:0;font-weight:bold}
button.stop{background:#b42318}
.status{padding:12px;border-radius:10px;margin-top:12px;background:#fff3d6}
.live{background:#e8f7ed;color:#18753a}
</style>
</head>
<body>
<header>
<h2>📱 Driver Mode</h2>
<div>Use this phone as the bus GPS.</div>
</header>

<main>
<div class="card">
<label>Bus Number</label>
<select id="bus"></select>

<label>Driver Name</label>
<input id="driverName" placeholder="Driver name">

<label>Driver Mobile</label>
<input id="driverPhone" placeholder="Mobile number">

<button id="start" onclick="startTrip()">🟢 START TRIP & GPS</button>
<button id="stop" class="stop" onclick="stopTrip()" style="display:none">⛔ STOP TRIP</button>

<div id="status" class="status">Waiting to start GPS.</div>
</div>

<div class="card">
<b>How it works</b>
<p>Keep this page open while driving. Your phone GPS sends the selected bus location to the server.</p>
<p>Passengers can search the same bus number from the main page.</p>
</div>
</main>

<script>
let watchId=null;

async function loadBuses(){
  const r=await fetch('/api/buses');
  const data=await r.json();
  const sel=document.getElementById('bus');
  sel.innerHTML=(data.buses||[]).map(b=>`<option value="${b.bus_number}">${b.bus_number}</option>`).join('');
}

function status(msg,live=false){
  const el=document.getElementById('status');
  el.className='status '+(live?'live':'');
  el.textContent=msg;
}

async function sendLocation(pos){
  const bus=document.getElementById('bus').value;
  const lat=pos.coords.latitude;
  const lon=pos.coords.longitude;
  const accuracy=pos.coords.accuracy;
  const speedMps=pos.coords.speed;
  const speed=Number.isFinite(speedMps) && speedMps>=0 ? speedMps : 0;

  try{
    const r=await fetch('/api/location',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        bus_number:bus,
        lat:lat,
        lon:lon,
        speed:speed,
        accuracy:accuracy
      })
    });
    const data=await r.json();
    if(!r.ok){status('❌ '+(data.error||'GPS update failed'));return;}
    status('🟢 LIVE — GPS updated | Accuracy: '+Math.round(accuracy)+' m',true);
  }catch(e){
    status('❌ Internet/server connection problem');
  }
}

function gpsError(err){
  status('❌ GPS error: '+err.message);
}

function startTrip(){
  if(!navigator.geolocation){
    status('❌ This phone does not support GPS.');
    return;
  }

  const bus=document.getElementById('bus').value;
  if(!bus){status('❌ Select a bus first.');return;}

  document.getElementById('start').style.display='none';
  document.getElementById('stop').style.display='block';
  status('📍 Requesting GPS permission...');

  watchId=navigator.geolocation.watchPosition(
    sendLocation,
    gpsError,
    {enableHighAccuracy:true, maximumAge:5000, timeout:15000}
  );
}

async function stopTrip(){
  if(watchId!==null){
    navigator.geolocation.clearWatch(watchId);
    watchId=null;
  }

  const bus=document.getElementById('bus').value;
  try{
    await fetch('/api/stop',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({bus_number:bus})
    });
  }catch(e){}

  document.getElementById('start').style.display='block';
  document.getElementById('stop').style.display='none';
  status('⛔ Trip stopped.');
}

loadBuses();
</script>
</body>
</html>
"""


# -----------------------------
# Admin / Bus Registration UI
# -----------------------------
ADMIN_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Add Bus</title>
<style>
body{margin:0;font-family:Arial;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px}
main{max-width:650px;margin:auto;padding:16px}
.card{background:white;padding:18px;border-radius:14px;box-shadow:0 3px 15px #0001;margin-bottom:14px}
input,button{width:100%;padding:13px;margin-top:9px;border-radius:10px;border:1px solid #ccd4e0;font:inherit}
button{background:#173b7a;color:white;border:0;font-weight:bold}
.success{background:#e8f7ed;color:#18753a;padding:12px;border-radius:10px;margin-top:12px}
.error{background:#fdecec;color:#b42318;padding:12px;border-radius:10px;margin-top:12px}
</style>
</head>
<body>
<header>
<h2>⚙️ Register New Bus</h2>
<div>Add as many buses as required.</div>
</header>

<main>
<div class="card">
<label>Bus Number</label>
<input id="bus" placeholder="e.g. TN 38 AB 1234">

<label>Driver Name</label>
<input id="name" placeholder="Driver name">

<label>Driver Mobile</label>
<input id="phone" placeholder="Driver mobile number">

<button onclick="addBus()">➕ ADD BUS</button>
<div id="msg"></div>
</div>

<div class="card">
<a href="/">← Passenger View</a><br><br>
<a href="/driver">📱 Driver Mode</a>
</div>

<script>
async function addBus(){
  const payload={
    bus_number:document.getElementById('bus').value.trim(),
    driver_name:document.getElementById('name').value.trim(),
    driver_phone:document.getElementById('phone').value.trim()
  };

  const msg=document.getElementById('msg');
  try{
    const r=await fetch('/api/buses',
