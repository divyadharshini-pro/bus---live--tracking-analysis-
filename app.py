from flask import Flask, request, jsonify, render_template_string
from time import time
import math

app = Flask(__name__)

BUNCHING_KM = 0.50
STALE_SECONDS = 20

BUSES = {
    "BUS-01": {"number": "TN 38 AB 1234", "lat": 11.0168, "lng": 76.9558, "speed": 0.0, "updated": None, "accuracy": None},
    "BUS-02": {"number": "TN 38 CD 5678", "lat": 11.0200, "lng": 76.9620, "speed": 0.0, "updated": None, "accuracy": None},
    "BUS-03": {"number": "TN 38 EF 9012", "lat": 11.0250, "lng": 76.9700, "speed": 0.0, "updated": None, "accuracy": None},
}

def distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
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
.bus-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
.bus-name{font-size:18px;font-weight:bold}
.badge{padding:5px 9px;border-radius:20px;font-size:12px;background:#e8f7ed;color:#19733b}
.warning{background:#fff2d5;color:#8a5b00}
.info{font-size:13px;margin-top:7px;color:#596579}
select,button,input{width:100%;padding:11px;border-radius:9px}
select,input{border:1px solid #ccd4df;margin:7px 0 10px}
button{border:0;background:#173b7a;color:white;font-weight:bold;cursor:pointer}
.search-row{display:grid;grid-template-columns:1fr 110px;gap:8px}
.search-result{padding:10px;background:#f4f7fb;border-radius:10px;margin-top:4px}
.search-result strong{color:#173b7a}
@media(max-width:500px){.search-row{grid-template-columns:1fr}}
.stop{background:#9b2c2c;margin-top:8px}
.status-live{color:#19733b;font-weight:bold}
.status-demo{color:#8a5b00;font-weight:bold}
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
<h3>🔎 Where is my Bus?</h3>
<div class="search-row">
<input id="busSearch" type="text" placeholder="Enter bus number e.g. TN 38 AB 1234">
<button onclick="searchBus()">Track Bus</button>
</div>
<div id="searchResult" class="search-result info">Enter a registered bus number to find its live location.</div>
</div>

<div class="card" style="margin-top:15px">
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
<button id="stopButton" class="stop" onclick="stopGPS()" style="display:none">Stop Live GPS</button>
<p id="gpsStatus">GPS not started.</p>
<div class="info" style="font-size:12px">
Only the selected bus will receive this phone's GPS location.
</div>
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
    try {
        const response = await fetch("/api/buses");
        const buses = await response.json();
        const ids = Object.keys(buses);
        const now = Date.now() / 1000;

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
            const isFresh = bus.updated !== null &&
                (now - bus.updated) <= 20;

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

            const bunching = isFresh && nearest < 0.5;
            const arrival = isFresh ? eta(nearest, bus.speed) : null;

            let status;
            if (!isFresh) {
                status = "📍 Demo / Waiting";
            } else if (bunching) {
                status = "⚠️ Bunching";
            } else if (bus.speed < 2) {
                status = "🟡 Stopped";
            } else {
                status = "🟢 Moving";
            }

            html += `
            <div class="bus-card">
                <div class="bus-head">
                    <div class="bus-name">🚌 ${bus.number || id}</div>
                    <div class="info" style="margin-top:2px">${id}</div>
                    <div class="badge ${bunching ? "warning" : ""}">${status}</div>
                </div>
                <div class="info">🚀 Speed: <b>${Number(bus.speed).toFixed(1)} km/h</b></div>
                <div class="info">🚍 Nearest Bus: <b>${nearestBus}</b></div>
                <div class="info">📏 Distance: <b>${nearest.toFixed(2)} km</b></div>
                <div class="info">⏱️ Estimated Time: <b>${arrival ? arrival + " min" : "Waiting for movement"}</b></div>
                <div class="info ${isFresh ? "status-live" : "status-demo"}">
                    ${isFresh ? "📡 GPS updated recently" : "📍 Starting/demo position"}
                </div>
                ${isFresh && bunching ? `
                    <div class="info" style="color:#8a5b00">
                        ⚠️ Traffic bunching detected. Buses are within 500 meters.
                    </div>` : ""}
            </div>`;
        });

        document.getElementById("busCards").innerHTML = html;
    } catch (error) {
        document.getElementById("busCards").innerHTML =
            "<div class='info'>Unable to load bus data.</div>";
    }
}

function normalizeBusNumber(value) {
    return value.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

async function searchBus() {
    const input = document.getElementById("busSearch").value.trim();
    const result = document.getElementById("searchResult");

    if (!input) {
        result.innerHTML = "⚠️ Please enter a bus number.";
        return;
    }

    try {
        const response = await fetch("/api/buses");
        const buses = await response.json();
        const wanted = normalizeBusNumber(input);
        let foundId = null;

        for (const id of Object.keys(buses)) {
            const busNumber = normalizeBusNumber(buses[id].number || id);
            if (busNumber === wanted || normalizeBusNumber(id) === wanted) {
                foundId = id;
                break;
            }
        }

        if (!foundId) {
            result.innerHTML = "❌ Bus not found. Try one of the registered bus numbers shown below.";
            return;
        }

        const bus = buses[foundId];
        const isFresh = bus.updated !== null && (Date.now() / 1000 - bus.updated) <= 20;
        const status = !isFresh ? "📍 Demo / Waiting" : (bus.speed < 2 ? "🟡 Stopped" : "🟢 Moving");

        map.setView([bus.lat, bus.lng], 16);
        if (markers[foundId]) {
            markers[foundId].openTooltip();
        }

        result.innerHTML = `
            <strong>🚌 ${bus.number || foundId}</strong><br>
            📍 Location: ${bus.lat.toFixed(5)}, ${bus.lng.toFixed(5)}<br>
            🚀 Speed: ${Number(bus.speed).toFixed(1)} km/h<br>
            ${status}<br>
            ${isFresh ? "📡 Live GPS updated recently" : "📍 Starting/demo position"}
        `;
    } catch (error) {
        result.innerHTML = "Unable to search bus right now.";
    }
}

document.getElementById("busSearch").addEventListener("keydown", event => {
    if (event.key === "Enter") searchBus();
});

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
    document.getElementById("stopButton").style.display = "block";

    watchId = navigator.geolocation.watchPosition(
        async position => {
            const speedMs = position.coords.speed;
            const speedKmh = speedMs === null ? 0 : Math.max(0, speedMs * 3.6);

            const data = {
                bus: bus,
                lat: position.coords.latitude,
                lng: position.coords.longitude,
                speed: speedKmh,
                accuracy: position.coords.accuracy
            };

            try {
                await fetch("/api/location", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(data)
                });
                updateBuses();
            } catch (error) {
                document.getElementById("gpsStatus").textContent =
                    "GPS update failed.";
            }
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

function stopGPS() {
    if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
    }
    document.getElementById("gpsStatus").textContent = "GPS stopped.";
    document.getElementById("stopButton").style.display = "none";
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
        accuracy = float(data.get("accuracy", 0))
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid GPS data"}), 400

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"error": "Invalid coordinates"}), 400

    BUSES[bus].update({
        "lat": lat,
        "lng": lng,
        "speed": speed,
        "updated": time(),
        "accuracy": accuracy
    })

    return jsonify({"success": True, "bus": bus})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
