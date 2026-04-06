import aiohttp
import logging
import json
import math
import time
import asyncio
from datetime import datetime

WHICHSAT_HOST = "api.wheretheiss.at"

async def _http_get_json(url, timeout=8):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                return await response.json()
    except Exception as e:
        logging.error(f"Satellite API error ({url}): {e}")
        return None

async def get_iss_position():
    """Return a formatted string with the ISS's current position and speed."""
    url = f"https://{WHICHSAT_HOST}/v1/satellites/25544"
    data = await _http_get_json(url)
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

async def get_next_pass(lat, lon, n=2):
    """Estimate the next ISS passes using orbital-model-based pass prediction."""
    url = f"https://{WHICHSAT_HOST}/v1/satellites/25544"
    data = await _http_get_json(url)
    if not data:
        return "Couldn't reach satellite API. Try again shortly."

    try:
        iss_lat = float(data["latitude"])
        iss_lon = float(data["longitude"])
    except (KeyError, ValueError, TypeError) as e:
        return f"Couldn't parse ISS position: {e}"

    ISS_INCL         = 51.6
    ORBIT_PERIOD_S   = 92.68 * 60
    EARTH_ROT_DEG_PER_ORBIT = 360.0 * ORBIT_PERIOD_S / 86400.0

    if abs(lat) > ISS_INCL + 5:
        return f"Your latitude ({lat:.1f}°) is outside ISS orbital range (±{ISS_INCL}°)."

    def haversine_deg(lat1, lon1, lat2, lon2):
        r1, r2 = math.radians(lat1), math.radians(lat2)
        dr = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dr/2)**2 + math.cos(r1) * math.cos(r2) * math.sin(dl/2)**2
        return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))

    THRESHOLD_DEG = 23.0
    step_s = 20
    scan_window_s = int(ORBIT_PERIOD_S * 10)
    now = int(time.time())

    clamped = max(-1.0, min(1.0, iss_lat / ISS_INCL))
    phase0 = math.asin(clamped)

    passes_found = []
    in_pass = False
    pass_start = None

    t = 0
    while t < scan_window_s and len(passes_found) < n:
        orbit_num = t / ORBIT_PERIOD_S
        phase = phase0 + (2 * math.pi * t / ORBIT_PERIOD_S)
        pred_lat = ISS_INCL * math.sin(phase)
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

    lines = ["🛰️ ISS Pass Estimate (±10 min)"]
    for (rise_ts, set_ts) in passes_found:
        wait_s   = max(0, rise_ts - now)
        dur_m    = max(1, (set_ts - rise_ts) // 60)
        wait_str = f"{wait_s // 3600}h {(wait_s % 3600) // 60}m" if wait_s >= 3600 else f"{wait_s // 60}m"
        rise_utc = time.strftime("%H:%Mz", time.gmtime(rise_ts))
        lines.append(f"⏰ In ~{wait_str} @ ~{rise_utc}")
        lines.append(f"⏱ ~{dur_m}m window")

    lines.append("(Orbital model estimate)")
    return "\n".join(lines)

async def handle_sat_command(msg_upper, send_reply_fn, sender, channel_index, home_lat, home_lon):
    """Entry point from headless.py. Adapts to async send functions."""
    parts = msg_upper.split()
    if parts[0] != "SAT": return
    
    sub = parts[1].upper() if len(parts) > 1 else "HELP"
    
    if sub == "HELP":
        menu = "🛰️ Sat Tracker\nSAT ISS: Position\nSAT PASS: Passes\n"
        await send_reply_fn(sender, menu, channel_index)
    elif sub == "ISS":
        await send_reply_fn(sender, "Fetching ISS pos...", channel_index)
        res = await get_iss_position()
        await send_reply_fn(sender, res, channel_index)
    elif sub == "PASS":
        await send_reply_fn(sender, "Calculating pass...", channel_index)
        res = await get_next_pass(home_lat, home_lon)
        await send_reply_fn(sender, res, channel_index)
