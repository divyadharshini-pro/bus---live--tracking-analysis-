from flask import Flask, request, jsonify, render_template_string
from time import time
import math

app = Flask(__name__)

BUSES = {
    "BUS-01": {"lat": 11.0168, "lng": 76.9558, "speed": 0, "updated": None},
    "BUS-02": {"lat": 11.0200, "lng": 76.9620, "speed": 0, "updated": None},
    "BUS-03": {"lat": 11.0250, "lng": 76.9700, "speed": 0, "updated": None},
}

def distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BusLive - Live Bus Tracking</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px}
header h1{margin:0;font-size:24px}
header p{margin:6px 0 0;font-size:13px}
.container{max-width:1200px;margin:auto;padding:15px}
.layout{display:grid;grid-template-columns:1.6fr 1fr;gap:15px}
.card{background:white;border-radius:16px;padding:15px;box-shadow:0 4px 18px rgba(0,0,0,.08)}
#map{height:520px;border-radius:12px}
.bus-card{border:1px solid #e3e7ef;border-radius:12px;padding:12px;margin-bottom:10px}
.bus-head{display:flex;justify-content:space-between;align-items:center}
.bus-name{font-size:18px;font-weight:bold}
.badge{padding:5px 9px;border-radius:20px;font-size:12px;background:#e8f7ed;color:#19733b}
.warning{background:#fff2d5;color:#8a5b00}
.info{font-size:13px;margin-top:7px;color:#596579}
select,button{width:100%;padding:11px;border-radius:9px}
select{border:1px solid #ccd4df;margin:7px 0 10px}
button{border:0;background:#173b7a;color:white;font-weight:bold}
@media(max-width:800px){.layout{grid-template-columns:1fr}#map{height:400px}}
</style>
</head>
<body>
<header>
<h1>🚌 BusLive</h1>
<p>Real-time 3 Bus Tracking • Distance • ETA • Bunching Analysis</p>
</header>

<div class="container">
<div class="layout">
<div class="card">
<h3>🗺️ Live Bus Map</h3>
<div id="map"></div>
</div>

<div>
<div class="card">
<h3>🚍 Passenger View</h3>
<div id="busCards">Loading buses...</div>
</div>

<div class="card" style="margin-top:15px">
<h3>📍 Driver GPS</h3>
<label>Select Bus</label>
<select id="busSelect">
<option value="BUS-01">BUS-01</option>
<option value="BUS-02">BUS-02</option>
<option value="BUS-03">BUS-03</option>
</select>
<button onclick="startGPS()">Start Live GPS</button>
<p id="gpsStatus">GPS not started.</p>
</div>
</div>
</div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const map = L.map("map").setView([11.020, 76.962], 14);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap contributors"
}).addTo(map);

const markers = {};
const colors = ["#173b7a", "#e35b2d", "#198754"];

function distance(a, b) {
    const R = 6371;
    const p1 = a.lat * Math.PI / 180;
    const p2 = b.lat * Math.PI / 180;
    const dp = (b.lat - a.lat) * Math.PI / 180;
    const dl = (b.lng - a.lng) * Math.PI / 180;
    const x = Math.sin(dp / 2) ** 2 +
        Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

function eta(distanceKm, speed) {
    if (speed < 2) return null;
    return Math.max(1, Math.round((distanceKm / speed) * 60));
}

async function updateBuses() {
    const response = await fetch("/api/buses");
    const buses = await response.json();
    const ids = Object.keys(buses);

    ids.forEach((id, index) => {
        const bus = buses[id];
        if (!markers[id]) {
            markers[id] = L.circleMarker([bus.lat, bus.lng], {
                radius: 9,
                color: colors[index],
                fillColor: colors[index],
                fillOpacity: 0.9
            }).addTo(map).bindTooltip(id, {
                permanent: true,
                direction: "top"
            });
        } else {
            markers[id].setLatLng([bus.lat, bus.lng]);
        }
    });

    let html = "";

    ids.forEach(id => {
        const bus = buses[id];
        let nearest = Infinity;
        let nearestBus = "";

        ids.forEach(other => {
            if (other === id) return;
            const d = distance(bus, buses[other]);
            if (d < nearest) {
                nearest = d;
                nearestBus = other;
            }
        });

        const bunching = nearest < 0.5;
        const arrival = eta(nearest, bus.speed);
        const status = bunching ? "⚠️ Bunching" :
            (bus.speed < 2 ? "🟡 Stopped" : "🟢 Moving");

        html += `
        <div class="bus-card">
            <div class="bus-head">
                <div class="bus-name">🚌 ${id}</div>
                <div class="badge ${bunching ? "warning" : ""}">${status}</div>
            </div>
            <div class="info">🚀 Speed: <b>${bus.speed.toFixed(1)} km/h</b></div>
            <div class="info">🚍 Nearest Bus: <b>${nearestBus}</b></div>
            <div class="info">📏 Distance: <b>${nearest.toFixed(2)} km</b></div>
            <div class="info">⏱️ Estimated Time: <b>${arrival ? arrival + " min" : "Waiting for movement"}</b></div>
            ${bunching ? `<div class="info" style="color:#8a5b00">
                ⚠️ Traffic bunching detected. Buses are within 500 meters.
            </div>` : ""}
        </div>`;
    });

    document.getElementById("busCards").innerHTML = html;
}

let watchId = null;

function startGPS() {
    if (!navigator.geolocation) {
        alert("GPS is not supported on this device.");
        return;
    }

    const bus = document.getElementById("busSelect").value;

    if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId);
    }

    document.getElementById("gpsStatus").textContent =
        "📍 Live GPS started for " + bus;

    watchId = navigator.geolocation.watchPosition(
        async position => {
            const data = {
                bus: bus,
                lat: position.coords.latitude,
                lng: position.coords.longitude,
                speed: (position.coords.speed || 0) * 3.6
            };

            await fetch("/api/location", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(data)
            });

            updateBuses();
        },
        error => {
            document.getElementById("gpsStatus").textContent =
                "GPS Error: " + error.message;
        },
        {
            enableHighAccuracy: true,
            maximumAge: 3000,
            timeout: 10000
        }
    );
}

updateBuses();
setInterval(updateBuses, 3000);
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/driver")
def driver():
    return render_template_string(HTML)

@app.route("/api/buses")
def get_buses():
    return jsonify(BUSES)

@app.route("/api/location", methods=["POST"])
def update_location():
    data = request.get_json(silent=True) or {}
    bus = data.get("bus")

    if bus not in BUSES:
        return jsonify({"error": "Unknown bus"}), 400

    try:
        lat = float(data["lat"])
        lng = float(data["lng"])
        speed = max(0.0, float(data.get("speed", 0)))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid GPS data"}), 400

    BUSES[bus].update({
        "lat": lat,
        "lng": lng,
        "speed": speed,
        "updated": time()
    })

    return jsonify({"success": True, "bus": bus})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
