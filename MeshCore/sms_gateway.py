import asyncio
import logging
import json
import os
import re
import time
from datetime import datetime

ROUTES_FILE = "sms_routes.json"

class AprsIsGateway:
    def __init__(self, callback_on_sms_reply=None):
        self.server = "rotate.aprs2.net"
        self.port = 14580
        self.callsign = ""
        self.passcode = ""
        self.reader = None
        self.writer = None
        self.connected = False
        self.routing_table = self._load_routes()
        self.callback_on_sms_reply = callback_on_sms_reply

    def _load_routes(self):
        if os.path.exists(ROUTES_FILE):
            try:
                with open(ROUTES_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading {ROUTES_FILE}: {e}")
        return {}

    async def _save_routes(self):
        try:
            with open(ROUTES_FILE, 'w') as f:
                json.dump(self.routing_table, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {ROUTES_FILE}: {e}")

    def configure(self, callsign, passcode):
        self.callsign = callsign.upper().strip()
        self.passcode = passcode.strip()

    async def connect(self):
        if not self.callsign or not self.passcode:
            logging.warning("APRS-IS not configured. Cannot connect SMS Gateway.")
            return False
            
        try:
            logging.info(f"Connecting to APRS-IS SMS ({self.server}:{self.port}) as {self.callsign}...")
            self.reader, self.writer = await asyncio.open_connection(self.server, self.port)
            
            login = f"user {self.callsign} pass {self.passcode} vers MeshCoreGrade 0.3.0 filter p/SMS\r\n"
            self.writer.write(login.encode())
            await self.writer.drain()
            
            self.connected = True
            asyncio.create_task(self._listen_loop())
            return True
        except Exception as e:
            logging.error(f"SMS APRS-IS connection failed: {e}")
            self.connected = False
            return False

    async def _listen_loop(self):
        while self.connected:
            try:
                line = await self.reader.readline()
                if not line: break
                await self._parse_line(line.decode('utf-8', errors='ignore'))
            except Exception as e:
                logging.error(f"SMS Gateway RX error: {e}")
                break
        self.connected = False

    async def _parse_line(self, line):
        if line.startswith("#") or f":{self.callsign.ljust(9)}:@" not in line: return
        try:
            payload = line.split(f":{self.callsign.ljust(9)}:", 1)[1]
            if payload.startswith("@"):
                parts = payload[1:].split(" ", 1)
                if len(parts) == 2:
                    reply_phone, reply_msg = parts[0], parts[1]
                    if "{" in reply_msg: reply_msg = reply_msg.split("{")[0]
                    logging.info(f"SMS from {reply_phone}: {reply_msg}")
                    
                    if self.callback_on_sms_reply:
                        target_mesh_node = self.routing_table.get(reply_phone)
                        # Callback should be async
                        await self.callback_on_sms_reply(reply_phone, reply_msg, target_mesh_node)
        except Exception as e:
            logging.error(f"Error parsing APRS SMS: {e}")

    async def send_sms(self, phone, message, sender_id):
        if not self.connected: 
            # Try to reconnect
            if not await self.connect(): return False
            
        clean_phone = re.sub(r'[^\d]', '', phone)
        self.routing_table[clean_phone] = sender_id
        await self._save_routes()
        
        # APRS format: CALL>APRS,TCPIP*::SMS      :@1234567890 Message{123
        msg_id = str(int(time.time() * 10))[-3:]
        dest_padded = "SMS".ljust(9)
        packet = f"{self.callsign}>APRS,TCPIP*::{dest_padded}:@{clean_phone} {message}" + "{" + msg_id + "\r\n"
        
        try:
            self.writer.write(packet.encode())
            await self.writer.drain()
            return True
        except Exception as e:
            logging.error(f"Failed to send SMS packet: {e}")
            self.connected = False
            return False
