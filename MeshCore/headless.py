import asyncio
import logging
import json
import os
import sys
import time
from datetime import datetime

# MeshCore Engine
from engine import MeshEngine

# Logic components (Ported from MeshUpGrade)
from weather import WeatherPlugin
from ai_chat import AiChatManager
from bbs_manager import BbsManager
from satellite import handle_sat_command
from aprs_manager import AprsManager
from sms_gateway import AprsIsGateway
from sms_contacts import SmsContactsManager
from reminders import ReminderManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load settings
with open('settings.json', 'r') as f:
    settings = json.load(f)

# Global instances
engine = MeshEngine()
ai_mgr = AiChatManager(settings)
sms_contacts = SmsContactsManager()
sms_gateway = AprsIsGateway()
aprs_mgr = AprsManager(engine, None) # will set callback later
rmd_mgr = None # init later
bbs_mgr = None # init later

async def send_reply(dest, text, channel_idx=0):
    """Helper to send a direct message reply or broadcast."""
    if dest == '^all':
        await engine.send_broadcast(text)
    else:
        await engine.send_dm(dest, text)

async def process_command(msg_original, sender, packet, channel_index=0):
    """Main command dispatcher (async)."""
    msg = msg_original.upper().strip()
    
    # 1. HELP
    if msg == "HELP":
        help_msg = (
            "MeshCoreGrade Bot\n"
            "WX   : Weather\n"
            "AI   : Chat with Claude\n"
            "APRS : APRS Gateway\n"
            "SAT  : Satellite Tracker\n"
            "BBS  : Bulletin Board\n"
            "SMS  : SMS Gateway"
        )
        await send_reply(sender, help_msg, channel_index)
        return

    # 2. WEATHER
    if msg.startswith("WX"):
        lat = settings.get("lat", "43.0")
        lon = settings.get("lon", "-78.4")
        unit = settings.get("unit", "F")
        wx = WeatherPlugin(lat, lon, unit)
        
        if msg == "WX":
            # Current conditions
            resp = wx.format_wx3()
            await send_reply(sender, resp, channel_index)
        elif "ALERT" in msg:
            resp = wx.format_wxa()
            await send_reply(sender, resp, channel_index)
        return

    # 3. AI CHAT
    if msg.startswith("AI "):
        query = msg_original[3:].strip()
        # AI might take time, so we wrap it in a thread or just await if it's already async
        # For now, simulate async via run_in_executor if blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, ai_mgr.chat, sender, query)
        
        # MeshCore message limit handling (chunking)
        chunk1 = response[:190]
        await send_reply(sender, chunk1, channel_index)
        if len(response) > 190:
            await asyncio.sleep(2)
            chunk2 = response[190:380]
            await send_reply(sender, chunk2, channel_index)
        return

    # 4. SATELLITE (handle_sat_command needs to be async-aware)
    # Note: We pass send_reply directly
    if msg.startswith("SAT"):
        lat = settings.get("lat", "43.0")
        lon = settings.get("lon", "-78.4")
        # Adapt synchronous handler to async send
        def _sync_reply(s, m, c):
            asyncio.create_task(send_reply(s, m, c))
        handle_sat_command(msg, _sync_reply, sender, channel_index, float(lat), float(lon))
        return

    # 5. BBS / SMS / APRS (these need more porting depth, showing skeletons)
    if msg.startswith("BBS"):
        # bbs_mgr.parse_command(msg_original, sender, channel_index)
        await send_reply(sender, "BBS module port in progress...", channel_index)
        return

    # Fallback
    if sender != 'me':
        await send_reply(sender, "Unknown command. Send 'HELP' for options.", channel_index)

async def on_message_handler(packet):
    """Callback for incoming MeshCore messages."""
    sender = packet['fromId']
    msg = packet['decoded']['payload'].decode('utf-8')
    logging.info(f"Received message from {sender}: {msg}")
    
    # Process the command
    await process_command(msg, sender, packet)

async def main():
    engine.callback_on_message = on_message_handler
    
    # 1. Connect (using settings)
    target_ip = settings.get("ip")
    if target_ip:
        if not await engine.connect_tcp(target_ip):
            logging.error("Failed to connect to MeshCore node. Exiting.")
            return
    else:
        logging.error("No IP address configured in settings.json")
        return

    logging.info("MeshCoreGrade Server is running. Press Ctrl+C to stop.")
    
    # Keep the program running
    while True:
        await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Stopping...")
