from flask import Flask, request, jsonify, render_template_string
from time import time
import math

app = Flask(__name__)

BUNCHING_KM = 0.50
STALE_SECONDS = 20

BUSES = {
    "BUS-01": {
        "number": "TN 38 AB 1234",
        "lat": 11.0168, "lng": 76.9558,
        "speed": 0.0, "updated": None, "accuracy": None,
        "driver_name": "", "driver_phone": "", "trip_active": False
    },
    "BUS-02": {
        "number": "TN 38 CD 5678",
        "lat": 11.0200, "lng": 76.9620,
        "speed": 0.0, "updated": None, "accuracy": None,
        "driver_name": "", "driver_phone": "", "trip_active": False
    },
    "BUS-03": {
        "number": "TN 38 EF 9012",
        "lat": 11.0250, "lng": 76.9700,
        "speed": 0.0, "updated": None, "accuracy": None,
        "driver_name": "", "driver_phone": "", "trip_active": False
    },
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
<title>BusLive - Where is my Bus?</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}
body{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:white;padding:18px}
header h1{margin:0;font-size:24px}
header p{margin:6px 0 0;font-size:13px}
nav{background:#fff;padding:10px 15px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
nav a{display:inline-block;text-decoration:none;color:#173b7a;font-weight:bold;margin-right:16px;padding:7px 10px;border-radius:8px}
nav a:hover{background:#eef3ff}
.container{max-width:1200px;margin:auto;padding:15px}
.layout{display:grid;grid-template-columns:1.6fr 1fr;gap:15px}
.card{background:white;border-radius:16px;padding:15px;box-shadow:0 4px 18px rgba(0,0,0,.08)}
#map{height:520px;border-radius:12px}
.bus-card{border:1px solid #e3e7ef;border-radius:12px;padding:12px;margin-bottom:10px}
.bus-head{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.bus-name{font-size:18px;font-weight:bold}
.badge{padding:5px 9px;border-radius:20px;font-size:12px;background:#e8f7ed;color:#19733b}
.warning{background:#fff2d5;color:#8a5b00}
.info{font-size:13px;margin-top:7px;color:#596579}
select,button,input{width:100%;padding:11px;border-radius:9px}
select,input{border:1px solid #ccd4df;margin:7px 0 10px}
button{border:0;background:#173b7a;color:white;font-weight:bold;cursor:pointer}
button.secondary{background:#52627a}
button.stop{background:#9b2c2c}
.search-row{display:grid;grid-template-columns:1fr 110px;gap:8px}
.search-result{padding:10px;background:#f4f7fb;border-radius:10px;margin-top:4px}
.search-result strong{color:#173b7a}
.status-live{color:#19733b;font-weight:bold}
.status-demo{color:#8a5b00;font-weight:bold}
.driver-status{padding:10px;border-radius:10px;background:#f4f7fb;margin-top:8px}
.small{font-size:12px;color:#667085}
.notice{background:#eef5ff;border-left:4px solid #173b7a;padding:10px;border-radius:8px;margin-bottom:12px;font-size:13px}
@media(max-width:800px){.layout{grid-template-columns:1fr}#map{height:400px}}
@media(max-width:500px){.search-row{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
<h1>🚌 BusLive</h1>
<p>Where is my Bus? • Live GPS • Passenger ETA • Driver Mode • Bunching Analysis</p>
</header>
<nav>
<a href="/">🧑‍💼 Passenger View</a>
<a href="/driver">📱 Driver Mode</a>
</nav>

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

function distance(a,b){
    const R=6371, p1=a.lat*Math.PI/180, p2=b.lat*Math.PI/180;
    const dp=(b.lat-a.lat)*Math.PI/180, dl=(b.lng-a.lng)*Math.PI/180;
    const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
    return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
}
function eta(d,s){
    if(s<2)return null;
    return Math.max(1,Math.round((d/s)*60));
}
function normalizeBusNumber(v){return v.toUpperCase().replace(/[^A-Z0-9]/g,"");}

async function updateBuses(){
    try{
        const response=await fetch("/api/buses");
        const buses=await response.json();
        const ids=Object.keys(buses);
        const now=Date.now()/1000;

        ids.forEach((id,index)=>{
            const bus=buses[id];
            if(!markers[id]){
                markers[id]=L.circleMarker([bus.lat,bus.lng],{
                    radius:9,color:colors[index%colors.length],
                    fillColor:colors[index%colors.length],fillOpacity:.9
                }).addTo(map).bindTooltip(bus.number || id,{permanent:true,direction:"top"});
            }else{
                markers[id].setLatLng([bus.lat,bus.lng]);
                markers[id].setTooltipContent(bus.number || id);
            }
        });

        let html="";
        ids.forEach(id=>{
            const bus=buses[id];
            const fresh=bus.updated!==null && (now-bus.updated)<=20;
            let nearest=Infinity, nearestBus="";
            ids.forEach(other=>{
                if(other===id)return;
                const d=distance(bus,buses[other]);
                if(d<nearest){nearest=d;nearestBus=other;}
            });
            const bunching=fresh && nearest<0.5;
            const arrival=fresh?eta(nearest,bus.speed):null;
            let status;
            if(!fresh)status="📍 Demo / Waiting";
            else if(bunching)status="⚠️ Bunching";
            else if(bus.speed<2)status="🟡 Stopped";
            else status="🟢 Moving";

            html+=`
            <div class="bus-card">
              <div class="bus-head">
                <div class="bus-name">🚌 ${bus.number||id}</div>
                <div class="info">${id}</div>
                <div class="badge ${bunching?"warning":""}">${status}</div>
              </div>
              <div class="info">🚀 Speed: <b>${Number(bus.speed).toFixed(1)} km/h</b></div>
              <div class="info">🚍 Nearest Bus: <b>${nearestBus||"—"}</b></div>
              <div class="info">📏 Distance: <b>${nearest.toFixed(2)} km</b></div>
              <div class="info">⏱️ Estimated Time: <b>${arrival?arrival+" min":"Waiting for movement"}</b></div>
              <div class="info">👨‍✈️ Driver: <b>${bus.driver_name||"Not assigned"}</b></div>
              <div class="info ${fresh?"status-live":"status-demo"}">
                ${fresh?"📡 Live GPS updated recently":"📍 Starting/demo position"}
              </div>
              ${fresh&&bunching?`<div class="info" style="color:#8a5b00">⚠️ Traffic bunching detected. Buses are within 500 meters.</div>`:""}
            </div>`;
        });
        document.getElementById("busCards").innerHTML=html;
    }catch(e){
        document.getElementById("busCards").innerHTML="<div class='info'>Unable to load bus data.</div>";
    }
}

async function searchBus(){
    const input=document.getElementById("busSearch").value.trim();
    const result=document.getElementById("searchResult");
    if(!input){result.innerHTML="⚠️ Please enter a bus number.";return;}
    try{
        const buses=await (await fetch("/api/buses")).json();
        const wanted=normalizeBusNumber(input);
        let found=null;
        for(const id of Object.keys(buses)){
            if(normalizeBusNumber(buses[id].number||id)===wanted || normalizeBusNumber(id)===wanted){
                found=id;break;
            }
        }
        if(!found){result.innerHTML="❌ Bus not found. Try a registered bus number.";return;}
        const bus=buses[found];
        const fresh=bus.updated!==null && (Date.now()/1000-bus.updated)<=20;
        const status=!fresh?"📍 Demo / Waiting":(bus.speed<2?"🟡 Stopped":"🟢 Moving");
        map.setView([bus.lat,bus.lng],16);
        if(markers[found])markers[found].openTooltip();
        result.innerHTML=`
          <strong>🚌 ${bus.number||found}</strong><br>
          👨‍✈️ Driver: ${bus.driver_name||"Not assigned"}<br>
          📍 Location: ${bus.lat.toFixed(5)}, ${bus.lng.toFixed(5)}<br>
          🚀 Speed: ${Number(bus.speed).toFixed(1)} km/h<br>
          ${status}<br>
          ${fresh?"📡 Live GPS updated recently":"📍 Starting/demo position"}
        `;
    }catch(e){result.innerHTML="Unable to search bus right now.";}
}
document.getElementById("busSearch").addEventListener("keydown",e=>{if(e.key==="Enter")searchBus();});
updateBuses();
setInterval(updateBuses,3000);
</script>
</body>
</html>
"""

DRIVER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BusLive Driver Mode</title>
<style>
body{margin:0;font-family:Arial,sans-serif;background:#f4f7fb;color:#172033}
header{background:#173b7a;color:#fff;padding:18px}
header h1{margin:0;font-size:23px}
header p{margin:6px 0 0;font-size:13px}
nav{background:#fff;padding:10px 15px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
nav a{text-decoration:none;color:#173b7a;font-weight:bold;margin-right:15px}
.container{max-width:650px;margin:auto;padding:15px}
.card{background:#fff;border-radius:16px;padding:18px;box-shadow:0 4px 18px rgba(0,0,0,.08);margin-bottom:15px}
label{font-size:13px;font-weight:bold}
input,select,button{width:100%;padding:12px;border-radius:9px;box-sizing:border-box}
input,select{border:1px solid #ccd4df;margin:7px 0 12px}
button{border:0;background:#173b7a;color:#fff;font-weight:bold;margin-top:5px}
.stop{background:#9b2c2c}
.status{padding:14px;border-radius:10px;background:#f4f7fb;margin-top:12px}
.live{color:#19733b;font-weight:bold}
.small{font-size:12px;color:#667085;line-height:1.5}
</style>
</head>
<body>
<header>
<h1>📱 Driver Mode</h1>
<p>Use this phone as the bus GPS tracker</p>
</header>
<nav>
<a href="/">🧑‍💼 Passenger View</a>
</nav>
<div class="container">
<div class="card">
<h3>🚌 Driver Trip Setup</h3>
<p class="small">Enter the driver's details and assign this phone to a bus. The phone GPS will then send the live location to the server.</p>

<label>Driver Name</label>
<input id="driverName" type="text" placeholder="e.g. Kumar">

<label>Driver Mobile Number</label>
<input id="driverPhone" type="tel" inputmode="numeric" placeholder="e.g. 9876543210">

<label>Bus Number</label>
<select id="busSelect">
<option value="BUS-01">TN 38 AB 1234 — BUS-01</option>
<option value="BUS-02">TN 38 CD 5678 — BUS-02</option>
<option value="BUS-03">TN 38 EF 9012 — BUS-03</option>
</select>

<button onclick="startTrip()">🟢 START TRIP & GPS</button>
<button class="stop" onclick="stopTrip()">⛔ STOP TRIP</button>

<div id="status" class="status">Trip not started.</div>
</div>

<div class="card">
<h3>🔐 Demo Note</h3>
<p class="small">For the project demo, the mobile number is stored only with the selected bus in the running server memory. For a real production system, driver authentication and a secure database should be added.</p>
</div>
</div>

<script>
let watchId=null;
let currentBus=null;

async function startTrip(){
    const name=document.getElementById("driverName").value.trim();
    const phone=document.getElementById("driverPhone").value.trim();
    const bus=document.getElementById("busSelect").value;
    const status=document.getElementById("status");

    if(!name || !phone){
        status.innerHTML="⚠️ Enter Driver Name and Mobile Number first.";
        return;
    }
    if(!navigator.geolocation){
        status.innerHTML="❌ GPS is not supported on this phone.";
        return;
    }

    currentBus=bus;
    try{
        await fetch("/api/trip/start",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({bus:bus,driver_name:name,driver_phone:phone})
        });
    }catch(e){
        status.innerHTML="❌ Could not start trip.";
        return;
    }

    if(watchId!==null)navigator.geolocation.clearWatch(watchId);

    status.innerHTML="📡 <span class='live'>Requesting GPS permission...</span>";

    watchId=navigator.geolocation.watchPosition(async position=>{
        const speedMs=position.coords.speed;
        const speedKmh=speedMs===null?0:Math.max(0,speedMs*3.6);

        const data={
            bus:currentBus,
            lat:position.coords.latitude,
            lng:position.coords.longitude,
            speed:speedKmh,
            accuracy:position.coords.accuracy
        };

        try{
            const res=await fetch("/api/location",{
                method:"POST",
                headers:{"Content-Type":"application/json"},
                body:JSON.stringify(data)
            });
            if(res.ok){
                status.innerHTML=
                  "🟢 <span class='live'>TRIP ACTIVE</span><br>"+
                  "🚌 Bus: "+currentBus+"<br>"+
                  "📍 GPS: "+position.coords.latitude.toFixed(5)+", "+position.coords.longitude.toFixed(5)+"<br>"+
                  "🚀 Speed: "+speedKmh.toFixed(1)+" km/h<br>"+
                  "🎯 Accuracy: ±"+Math.round(position.coords.accuracy)+" m";
            }else{
                status.innerHTML="⚠️ GPS received, but server rejected the update.";
            }
        }catch(e){
            status.innerHTML="⚠️ Internet/server connection problem.";
        }
    },error=>{
        status.innerHTML="❌ GPS Error: "+error.message+"<br><span class='small'>Allow location permission and keep GPS/Internet ON.</span>";
    },{
        enableHighAccuracy:true,
        maximumAge:3000,
        timeout:15000
    });
}

async function stopTrip(){
    if(watchId!==null){
        navigator.geolocation.clearWatch(watchId);
        watchId=null;
    }
    if(currentBus){
        try{
            await fetch("/api/trip/stop",{
                method:"POST",
                headers:{"Content-Type":"application/json"},
                body:JSON.stringify({bus:currentBus})
            });
        }catch(e){}
    }
    document.getElementById("status").innerHTML="⛔ Trip stopped. GPS sharing has stopped.";
    currentBus=null;
}
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/driver")
def driver():
    return render_template_string(DRIVER_HTML)

@app.route("/api/buses")
def get_buses():
    return jsonify(BUSES)

@app.route("/api/trip/start", methods=["POST"])
def start_trip():
    data=request.get_json(silent=True) or {}
    bus=data.get("bus")
    name=str(data.get("driver_name","")).strip()
    phone=str(data.get("driver_phone","")).strip()

    if bus not in BUSES:
        return jsonify({"error":"Unknown bus"}),400
    if not name or not phone:
        return jsonify({"error":"Driver name and phone are required"}),400

    BUSES[bus].update({
        "driver_name":name,
        "driver_phone":phone,
        "trip_active":True,
        "updated":time()
    })
    return jsonify({"success":True,"bus":bus})

@app.route("/api/trip/stop", methods=["POST"])
def stop_trip():
    data=request.get_json(silent=True) or {}
    bus=data.get("bus")
    if bus not in BUSES:
        return jsonify({"error":"Unknown bus"}),400

    BUSES[bus].update({
        "trip_active":False,
        "speed":0.0,
        "updated":None
    })
    return jsonify({"success":True,"bus":bus})

@app.route("/api/location", methods=["POST"])
def update_location():
    data=request.get_json(silent=True) or {}
    bus=data.get("bus")
    if bus not in BUSES:
        return jsonify({"error":"Unknown bus"}),400

    try:
        lat=float(data["lat"])
        lng=float(data["lng"])
        speed=max(0.0,float(data.get("speed",0)))
        accuracy=max(0.0,float(data.get("accuracy",0)))
    except (KeyError,TypeError,ValueError):
        return jsonify({"error":"Invalid GPS data"}),400

    if not(-90<=lat<=90 and -180<=lng<=180):
        return jsonify({"error":"Invalid coordinates"}),400

    BUSES[bus].update({
        "lat":lat,
        "lng":lng,
        "speed":speed,
        "updated":time(),
        "accuracy":accuracy,
        "trip_active":True
    })
    return jsonify({"success":True,"bus":bus})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=10000)

