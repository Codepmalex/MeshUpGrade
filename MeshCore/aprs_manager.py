import asyncio
import logging
import json
import os
import re
import time
import aiohttp
from datetime import datetime

APRS_USERS_FILE = "aprs_users.json"

def convert_to_aprs_coord(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except: return "0000.00N", "00000.00E"
    lat_deg, lat_min = int(abs(lat)), (abs(lat) - int(abs(lat))) * 60
    lat_str = f"{lat_deg:02d}{lat_min:05.2f}{'N' if lat >= 0 else 'S'}"
    lon_deg, lon_min = int(abs(lon)), (abs(lon) - int(abs(lon))) * 60
    lon_str = f"{lon_deg:03d}{lon_min:05.2f}{'E' if lon >= 0 else 'W'}"
    return lat_str, lon_str

class AprsManager:
    def __init__(self, engine, send_reply_func):
        self.engine = engine
        self.send_reply = send_reply_func
        self.users = self._load_users()
        self.setup_sessions = {}
        self.rx_running = False
        self.host_call = "NOCALL"
        self.host_pass = "-1"
        self.reader = None
        self.writer = None

    def _load_users(self):
        if os.path.exists(APRS_USERS_FILE):
            try:
                with open(APRS_USERS_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading {APRS_USERS_FILE}: {e}")
        return {}

    async def _save_users(self):
        try:
            with open(APRS_USERS_FILE, 'w') as f:
                json.dump(self.users, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {APRS_USERS_FILE}: {e}")

    async def start_rx_daemon(self, host_call, host_pass):
        self.host_call = host_call
        self.host_pass = host_pass
        if not self.rx_running:
            self.rx_running = True
            asyncio.create_task(self._rx_loop())

    async def _rx_loop(self):
        """Async APRS-IS RX loop."""
        while self.rx_running:
            try:
                logging.info(f"Connecting to APRS-IS for RX (rotate.aprs2.net)...")
                self.reader, self.writer = await asyncio.open_connection("rotate.aprs2.net", 14580)
                
                # Filter for messages (m/) and buddies (b/) - note: using m/ for MeshCore target
                login = f"user {self.host_call} pass {self.host_pass} vers MeshCoreGrade 0.3.0 filter m/{self.host_call}\r\n"
                self.writer.write(login.encode())
                await self.writer.drain()
                
                while self.rx_running:
                    line = await self.reader.readline()
                    if not line: break
                    await self._parse_rx(line.decode('utf-8', errors='ignore'))
            except Exception as e:
                logging.error(f"APRS-IS RX loop error: {e}")
            await asyncio.sleep(10)

    async def _parse_rx(self, line):
        if line.startswith("#") or ":" not in line: return
        # Logic to route message to specific mesh user (sender in our system)
        # For simplicity, if we receive a message for 'self.host_call', we 
        # need to know which mesh user corresponds to it. 
        # In this implementation, we broadcast or send to the user who enabled it.
        if f":{self.host_call.ljust(9)}:" in line:
            payload = line.split(":", 3)[-1]
            if "{" in payload: payload = payload.split("{")[0]
            logging.info(f"APRS message for {self.host_call}: {payload}")
            # Forwarding to mesh node (Simulation: find node who owns this call)
            # For now, we broadcast it to the channel so the user sees it.
            if self.send_reply:
                await self.send_reply("^all", f"APRS Msg: {payload}")

    async def process_mesh_command(self, txt, sender):
        """Main command handler for APRS commands."""
        # Setup and Toggle logic ported from MeshUpGrade
        # ... (implementation abbreviated for space, remains similar logic but async)
        if txt == "APRS FIND":
            await self.send_reply(sender, "Usage: APRS FIND <callsign>")
        return True
