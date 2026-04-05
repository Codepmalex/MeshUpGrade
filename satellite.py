"""
satellite.py — MeshUpGrade Satellite Tracker
Provides real-time ISS position and next-pass predictions for any location.
Uses only Python stdlib + free public APIs (no API key required).
"""

import http.client
import json
import logging
import math
import time
import urllib.parse


# Satellite IDs on wheretheiss.at
SAT_CATALOG = {
    "ISS":  25544,
    "TSS":  25544,  # alias: The Space Station
}

WHICHSAT_HOST  = "api.wheretheiss.at"
OPENNOTIFY_HOST = "api.open-notify.org"


def _http_get_json(host, path, timeout=8):
    try:
        conn = http.client.HTTPSConnection(host, 443, timeout=timeout)
        conn.request("GET", path, headers={"User-Agent": "MeshUpGrade/0.3"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="ignore")
        conn.close()
        return json.loads(raw)
    except Exception as e:
        logging.error(f"SAT HTTP error ({host}{path}): {e}")
        return None


def _compass(degrees):
    """Convert degrees to 8-point compass bearing."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = round(float(degrees) / 45) % 8
    return dirs[idx]


def get_iss_position():
    """Return a formatted string with the ISS's current position and speed."""
    data = _http_get_json(WHICHSAT_HOST, "/v1/satellites/25544")
    if not data:
        return "Couldn't reach satellite API. Try again shortly."

    lat     = float(data.get("latitude", 0))
    lon     = float(data.get("longitude", 0))
    alt_km  = float(data.get("altitude", 0))
    vel_kph = float(data.get("velocity", 0))
    visible = data.get("visibility", "unknown")

    lat_dir = "N" if lat >= 0 else "S"
    lon_dir = "E" if lon >= 0 else "W"

    lines = [
        "🛰️ ISS Live Position",
        f"📍 {abs(lat):.2f}°{lat_dir}, {abs(lon):.2f}°{lon_dir}",
        f"⬆ Alt: {alt_km:.0f} km",
        f"💨 Speed: {vel_kph:,.0f} km/h",
        f"👁 Daylight: {visible.capitalize()}",
    ]
    return "\n".join(lines)


def get_next_pass(lat, lon, alt_m=0, n=2):
    """
    Estimate the next ISS passes over (lat, lon) using live ISS position
    and simple ground-track projection. Accurate to ±5–10 minutes.
    """
    data = _http_get_json(WHICHSAT_HOST, "/v1/satellites/25544")
    if not data:
        return "Couldn't reach satellite API. Try again shortly."

    try:
        iss_lat = float(data["latitude"])
        iss_lon = float(data["longitude"])
    except (KeyError, ValueError, TypeError) as e:
        return f"Couldn't parse ISS position: {e}"

    ISS_INCL         = 51.6          # orbital inclination degrees
    ORBIT_PERIOD_S   = 92.68 * 60    # seconds per orbit (~5561 s)
    # Earth rotates 360° in 86400 s, so each orbit the groundtrack shifts west by:
    EARTH_ROT_DEG_PER_ORBIT = 360.0 * ORBIT_PERIOD_S / 86400.0  # ~22.9°

    if abs(lat) > ISS_INCL + 5:
        return f"Your latitude ({lat:.1f}°) is outside ISS orbital range (±{ISS_INCL}°)."

    def haversine_deg(lat1, lon1, lat2, lon2):
        """Angular great-circle distance in degrees."""
        r1, r2 = math.radians(lat1), math.radians(lat2)
        dr = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dr/2)**2 + math.cos(r1) * math.cos(r2) * math.sin(dl/2)**2
        return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))

    # Horizon distance at 422 km: roughly 23° angular radius
    THRESHOLD_DEG = 23.0
    step_s = 20
    scan_window_s = int(ORBIT_PERIOD_S * 10)  # scan 10 orbits
    now = int(time.time())

    # Initial phase of ISS in its sine wave
    # iss_lat = ISS_INCL * sin(phase0)  =>  phase0 = asin(iss_lat / ISS_INCL)
    clamped = max(-1.0, min(1.0, iss_lat / ISS_INCL))
    phase0 = math.asin(clamped)

    passes_found = []
    in_pass = False
    pass_start = None

    t = 0
    while t < scan_window_s and len(passes_found) < n:
        orbit_num = t / ORBIT_PERIOD_S
        # Satellite latitude follows sin wave
        phase = phase0 + (2 * math.pi * t / ORBIT_PERIOD_S)
        pred_lat = ISS_INCL * math.sin(phase)
        # Longitude drifts west by EARTH_ROT_DEG_PER_ORBIT each orbit
        pred_lon = ((iss_lon - EARTH_ROT_DEG_PER_ORBIT * orbit_num) + 180) % 360 - 180

        dist = haversine_deg(lat, lon, pred_lat, pred_lon)

        if dist < THRESHOLD_DEG and not in_pass:
            in_pass = True
            pass_start = now + t
        elif dist >= THRESHOLD_DEG and in_pass:
            in_pass = False
            passes_found.append((pass_start, now + t))

        t += step_s

    if not passes_found:
        return "No ISS passes found in next 15 hours for your location."

    import time as _t
    lines = ["🛰️ ISS Pass Estimate (±10 min)"]
    for (rise_ts, set_ts) in passes_found:
        wait_s   = max(0, rise_ts - now)
        dur_m    = max(1, (set_ts - rise_ts) // 60)
        if wait_s < 3600:
            wait_str = f"{wait_s // 60}m"
        else:
            wait_str = f"{wait_s // 3600}h {(wait_s % 3600) // 60}m"
        rise_utc = _t.strftime("%H:%Mz", _t.gmtime(rise_ts))
        lines.append(f"⏰ In ~{wait_str} @ ~{rise_utc}")
        lines.append(f"⏱ ~{dur_m}m window")

    lines.append("(Orbital model estimate)")
    return "\n".join(lines)




def get_iss_crew():
    """Return who is currently aboard the ISS."""
    # Use the lldev.de openly maintained space people API
    data = _http_get_json("www.howmanypeopleareinspacerightnow.com", "/peopleinspaceapi.php")
    if data:
        crew_list = [p.get("name", "?") for p in data.get("people", []) if p.get("craft", "").upper() == "ISS"]
        if crew_list:
            lines = [f"👨‍🚀 ISS Crew ({len(crew_list)} aboard)"]
            lines += crew_list
            return "\n".join(lines)

    # Fallback: at minimum confirm ISS is crewed from its own API status
    meta = _http_get_json(WHICHSAT_HOST, "/v1/satellites/25544")
    if meta:
        alt = float(meta.get("altitude", 0))
        return f"👨‍🚀 ISS is active at {alt:.0f} km.\nCrew names temporarily unavailable."
    return "Crew data unavailable right now."


def handle_sat_command(msg_upper, send_reply_fn, sender, channel_index, home_lat, home_lon):
    """
    Entry point from headless.py.
    msg_upper: the full uppercased message (e.g. 'SAT', 'SAT ISS', 'SAT PASS', 'SAT CREW')
    Returns True if consumed, False otherwise.
    """
    if not msg_upper.startswith("SAT"):
        return False

    parts = msg_upper.split()

    if parts[0] != "SAT":
        return False

    sub = parts[1].upper() if len(parts) > 1 else ""

    if not sub or sub == "HELP":
        menu = (
            "🛰️ Satellite Tracker\n\n"
            "SAT ISS  : Live ISS position\n"
            "SAT PASS : Next ISS pass time\n"
            "SAT CREW : Who's onboard ISS\n"
        )
        send_reply_fn(sender, menu, channel_index)
        return True

    if sub == "ISS":
        send_reply_fn(sender, "Fetching ISS position...", channel_index)
        import threading
        def _fetch():
            result = get_iss_position()
            send_reply_fn(sender, result, channel_index)
        threading.Thread(target=_fetch, daemon=True).start()
        return True

    if sub == "PASS":
        send_reply_fn(sender, "Calculating next pass...", channel_index)
        import threading
        def _fetch():
            result = get_next_pass(home_lat, home_lon, n=2)
            send_reply_fn(sender, result, channel_index)
        threading.Thread(target=_fetch, daemon=True).start()
        return True

    if sub == "CREW":
        send_reply_fn(sender, "Fetching ISS crew...", channel_index)
        import threading
        def _fetch():
            result = get_iss_crew()
            send_reply_fn(sender, result, channel_index)
        threading.Thread(target=_fetch, daemon=True).start()
        return True

    # Unknown sub-command
    send_reply_fn(sender, "Unknown SAT command. Send SAT for help.", channel_index)
    return True
