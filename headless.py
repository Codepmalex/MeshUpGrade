import logging
import os
import sys
import threading
import time
import json
import re
from datetime import datetime

from engine import MeshEngine
from weather import WeatherPlugin
from sms_gateway import AprsIsGateway
from reminders import ReminderManager
from bbs_manager import BbsManager
from sms_contacts import SmsContactsManager
from ai_chat import AiChatManager

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            content = f.read()
            cleaned = re.sub(r'^\s*#.*$', '', content, flags=re.MULTILINE)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing settings.json: {e}")
                return {}
    return {}

def main():
    settings = load_settings()
    if not settings:
        logging.error("No valid settings.json found! Please configure the app on your computer first.")
        sys.exit(1)

    engine = MeshEngine()
    
    sms_gateway = AprsIsGateway()
    sms_quick_cache = {}
    sms_sessions = {}  # {phone: {'node_id': ..., 'last_active': timestamp}}
    sms_pending_confirm = {}  # {phone: {'node_id': ..., 'message': ..., 'short': ...}}
    SMS_SESSION_TTL = 1800  # 30 minutes

    MESH_MENU = (
        "👋 Welcome to the MeshUpGrade Radio Network!\n\n"
        "HOW TO MESSAGE SOMEONE:\n"
        "Just text us the 4-letter name of the radio you want to reach (like 'RACK' or '8b4F').\n\n"
        "HOW TO END A CHAT:\n"
        "When you're done chatting, reply with 'ENDCONVO' to safely disconnect.\n\n"
        "Reply 'MENU' to see this help message anytime."
    )
    
    def _get_node_shortname(node_id):
        """Look up a human-readable shortname for a node ID."""
        if engine.interface and hasattr(engine.interface, 'nodes'):
            node = engine.interface.nodes.get(node_id)
            if node:
                return node.get('user', {}).get('shortName', node_id)
        return node_id

    def _find_node_by_shortname(name):
        """Find a node ID by shortname. Returns (node_id, actual_shortname, exact_match)."""
        exact = None
        fuzzy = None
        fuzzy_short = None
        # Check live nodes first
        if engine.interface and hasattr(engine.interface, 'nodes'):
            for node_id, node_info in engine.interface.nodes.items():
                sn = node_info.get('user', {}).get('shortName', '')
                if sn == name:
                    return node_id, sn, True
                if sn.lower() == name.lower() and not fuzzy:
                    fuzzy = node_id
                    fuzzy_short = sn
        # Fallback to cached nodes
        if not exact and not fuzzy:
            for node_id, info in engine.node_cache.items():
                sn = info.get('shortName', '')
                if sn == name:
                    return node_id, sn, True
                if sn.lower() == name.lower() and not fuzzy:
                    fuzzy = node_id
                    fuzzy_short = sn
        if fuzzy:
            return fuzzy, fuzzy_short, False
        return None, None, False

    def _send_to_node(phone, node_id, message):
        """Send a message to a mesh node on behalf of an SMS user, with delivery/fail notifications."""
        def on_ack(dest):
            logging.info(f"ACK CALLBACK FIRED for {phone} to node {node_id}")
            short = _get_node_shortname(node_id) or node_id
            sms_gateway.send_sms(phone, f"Delivered to {short}!", "SYSTEM", update_route=False)

        def on_fail(dest):
            logging.info(f"FAIL CALLBACK FIRED for {phone} to node {node_id}")
            short = _get_node_shortname(node_id) or node_id
            sms_gateway.send_sms(phone, f"Not delivered yet. We'll text you 'Delivered to {short}!' once they receive it.", "SYSTEM", update_route=False)

        logging.info(f"Sending SMS via mesh to {node_id}: {message}")
        engine.send_dm(node_id, f"SMS from {phone}:\n{message}", ack_callback=on_ack, fail_callback=on_fail)

    def handle_sms_reply(phone, txt, target):
        now = time.time()
        txt_stripped = txt.strip()
        txt_cmd = txt_stripped.upper()

        # ── Check for pending yes/no confirmation ──
        if phone in sms_pending_confirm:
            pending = sms_pending_confirm.pop(phone)
            if txt_cmd in ("YES", "Y"):
                node_id = pending['node_id']
                sms_gateway.routing_table[phone] = node_id
                sms_gateway.save_routes()
                sms_quick_cache[node_id] = {'phone': phone, 'time': now}
                sms_sessions[phone] = {'node_id': node_id, 'last_active': now}
                
                if pending.get('connect_only'):
                    sms_gateway.send_sms(phone, f"Connected to {pending['short']}! Just type your message and it will be sent to them. Reply END when done.", "SYSTEM", update_route=False)
                else:
                    sms_gateway.send_sms(phone, f"Connected to {pending['short']}. Sending your message now.", "SYSTEM", update_route=False)
                    time.sleep(2)
                    _send_to_node(phone, node_id, pending['message'])
            else:
                sms_gateway.send_sms(phone, "Message cancelled. Text a radio name to start a new chat.", "SYSTEM", update_route=False)
            return

        # ── Processing commands & Active route ──
        if txt_cmd == "ENDCONVO":
            sms_gateway.routing_table.pop(phone, None)
            sms_gateway.save_routes()
            sms_sessions.pop(phone, None)
            sms_gateway.send_sms(phone, "Chat ended. Text a radio name anytime to start a new one.", "SYSTEM", update_route=False)
            return
            
        if txt_cmd == "MENU":
            sms_gateway.send_sms(phone, MESH_MENU, "SYSTEM", update_route=False)
            return

        if target:
            # Active route exists, forward the message
            sms_quick_cache[target] = {'phone': phone, 'time': now}
            sms_sessions[phone] = {'node_id': target, 'last_active': now}
            _send_to_node(phone, target, txt_stripped)
            return

        # ── No active route: Look up shortname ──
        if len(txt_stripped) <= 4 and txt_stripped.isalnum():
            found_id, actual_short, exact = _find_node_by_shortname(txt_stripped)
            if found_id and exact:
                sms_gateway.routing_table[phone] = found_id
                sms_gateway.save_routes()
                sms_quick_cache[found_id] = {'phone': phone, 'time': now}
                sms_sessions[phone] = {'node_id': found_id, 'last_active': now}
                sms_gateway.send_sms(phone, f"Connected to {actual_short}! Just type your message and it will be sent to them. Reply ENDCONVO when done.", "SYSTEM", update_route=False)
                return
            elif found_id and not exact:
                # Fuzzy match — ask for confirmation
                sms_pending_confirm[phone] = {
                    'node_id': found_id,
                    'message': None,  # connect only
                    'short': actual_short,
                    'connect_only': True
                }
                sms_gateway.send_sms(phone, f"Did you mean {actual_short}? Reply YES or NO.", "SYSTEM", update_route=False)
                return
            else:
                sms_gateway.send_sms(phone, f"Couldn't find a radio named '{txt_stripped}'. Double check the name and try again.", "SYSTEM", update_route=False)
                return

        # ── Smart guess: Returning user ──
        if phone in sms_sessions:
            last_node = sms_sessions[phone].get('node_id')
            if last_node:
                short = _get_node_shortname(last_node)
                sms_pending_confirm[phone] = {
                    'node_id': last_node,
                    'message': txt_stripped,
                    'short': short
                }
                sms_gateway.send_sms(phone, f"Would you like to send that to {short}? Reply YES or NO.", "SYSTEM", update_route=False)
                return

        # ── Truly new user ──
        sms_gateway.send_sms(phone, MESH_MENU, "SYSTEM", update_route=False)

    sms_gateway.callback_on_sms_reply = handle_sms_reply

    lat_backup = settings.get("lat", "40.7128")
    lon_backup = settings.get("lon", "-74.0060")
    unit = settings.get("unit", "F")
    use_gps = settings.get("use_gps", True)
    sync_ping = settings.get("sync_ping", False)

    def get_location(sender_id):
        if use_gps and engine.interface:
            node = engine.interface.nodes.get(sender_id)
            if node and 'position' in node:
                pos = node['position']
                if 'latitude' in pos and 'longitude' in pos:
                    logging.info(f"Using GPS from node {sender_id}: {pos['latitude']}, {pos['longitude']}")
                    return pos['latitude'], pos['longitude']
        logging.info(f"Using backup location: {lat_backup}, {lon_backup}")
        return float(lat_backup), float(lon_backup)

    def send_reply(sender, text, channel_index=None):
        if channel_index is not None:
            engine.send_broadcast(text, channel_index=channel_index)
        else:
            engine.send_dm(sender, text)

    reminder_mgr = ReminderManager(send_reply)
    bbs_mgr = BbsManager(engine, send_reply, settings)
    sms_contacts_mgr = SmsContactsManager()
    ai_mgr = AiChatManager(settings)

    START_TIME = time.time()
    
    def process_command(msg, sender, packet, channel_index=None):
        msg_original = msg.lstrip("/")
        msg = msg_original.upper()
        
        # Help Menu handling
        if msg == "HELP":
            menu = "--Help Menu--\nWX : Weather\nBBS : Bulletin Board\nRMD : Reminders\nSMS : APRS Texting\nAI : AI Chat\nINBOX : Offline SMS\nSTATUS : Node Health\nUPTIME : Session Time"
            send_reply(sender, menu, channel_index)
            return

        if msg == "INBOX":
            pending = engine.check_inbox(sender)
            if not pending:
                send_reply(sender, "Inbox empty.", channel_index)
            else:
                send_reply(sender, f"Flushing {len(pending)} messages from Offline Inbox...", channel_index)
                for i, txt in enumerate(pending):
                    time.sleep(1) # small delay if multiple
                    send_reply(sender, txt, channel_index)
            return

        if msg == "STATUS":
            send_reply(sender, "Node is healthy.", channel_index)
            return
            
        if msg == "UPTIME":
            elapsed = int(time.time() - START_TIME)
            days, rem = divmod(elapsed, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, _ = divmod(rem, 60)
            if days > 0:
                uptime_str = f"{days}d {hours}h {minutes}m uptime"
            elif hours > 0:
                uptime_str = f"{hours}h {minutes}m uptime"
            else:
                uptime_str = f"{minutes}m uptime"
            send_reply(sender, uptime_str, channel_index)
            return

        if msg == "RMD" or msg == "REMIND":
            resp = reminder_mgr.parse_command("RMD", sender, channel_index)
            send_reply(sender, resp, channel_index)
            return
            
        if msg.startswith("RMD ") or msg.startswith("REMIND "):
            # We pass the original message so casing isn't strictly destroyed when parsing the actual alert text, but we uppercase the command check
            resp = reminder_mgr.parse_command(msg, sender, channel_index)
            send_reply(sender, resp, channel_index)
            return

        if msg.startswith("BBS"):
            # BBS handles its own replies, expirations, and cross-channel routing
            bbs_mgr.parse_command(msg, sender, channel_index)
            return

        if msg == "AI":
            menu = "-AI Menu-\nai <prompt>\nai newchat"
            send_reply(sender, menu, channel_index)
            return

        if msg.startswith("AI "):
            ai_body = msg_original[3:].strip()
            if ai_body.upper() == "NEWCHAT":
                ai_mgr.clear_session(sender)
                send_reply(sender, "AI chat history cleared!", channel_index)
                return
            response = ai_mgr.chat(sender, ai_body)
            if len(response) <= 200:
                send_reply(sender, response, channel_index)
            else:
                send_reply(sender, response[:200], channel_index)
                time.sleep(5)
                send_reply(sender, response[200:400], channel_index)
            return

        # Weather handling
        if msg == "WEATHER" or msg == "WX":
            menu = "-WX Menu-\nReply (eg. WX1)\nWX1-5dayforecast\nWX2-HRLYforecast\nWX3-GenForecast\nWX4-CustomFC\nWX5-HrlyCustom\nWXA-Alerts"
            send_reply(sender, menu, channel_index)
            return
        
        if msg.startswith("WX"):
            try:
                lat, lon = get_location(sender)
                wx = WeatherPlugin(lat, lon, unit=unit)
                response = None
                if msg == "WX1": response = wx.format_wx1()
                elif msg == "WX2": response = wx.format_wx2()
                elif msg == "WX3": response = wx.format_wx3()
                elif msg == "WXA": response = wx.format_wxa()
                elif msg == "WX4" or msg.startswith("WX4"):
                    date_str = msg.replace("WX4", "").strip().replace(" ", "-")
                    if date_str.upper() == "TMW":
                        from datetime import timedelta
                        date_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                    response = wx.format_wx4(date_str)
                    if response is None:
                        response = "No Date, please insert date\n(Format: WX4 YYYY MM DD)\n(for example, WX4 2026 03 09)"
                elif msg == "WX5" or msg.startswith("WX5"):
                    time_str = msg.replace("WX5", "").strip().replace(" ", ":")
                    response = wx.format_wx5(time_str)
                    if response is None:
                        response = "No Time, please insert time\n(Format: WX5 HH MM)\n(for example, WX5 14 00)"
                
                if response:
                    send_reply(sender, response, channel_index)
            except Exception as e:
                logging.error(f"Error processing WX command: {e}")
                send_reply(sender, "Error processing weather request.", channel_index)
            return

        # SMS menu alias (so users can type SMS on a channel without ?)
        if msg == "SMS":
            menu = "-SMS Menu-\n?<number> <msg>\n?<name> <msg>\n?L <msg> : Reply last\n?addcontact <name> <num>\n?delcontact <name>\n?contactlist"
            send_reply(sender, menu, channel_index)
            return

        # SMS command handling
        if msg_original.startswith("?"):
            prefix_cmd = msg_original[1:].strip().split(" ", 1)
            cmd_type = prefix_cmd[0].lower()
            
            if cmd_type == "sms":
                menu = "-SMS Menu-\n?<number> <msg>\n?<name> <msg>\n?L <msg> : Reply last\n?addcontact <name> <num>\n?delcontact <name>\n?contactlist"
                send_reply(sender, menu, channel_index)
                return

            if cmd_type == "contactlist":
                send_reply(sender, sms_contacts_mgr.list_contacts(sender), channel_index)
                return
                
            if cmd_type == "addcontact":
                arg_parts = msg[1:].strip().split(" ")
                if len(arg_parts) >= 3:
                    name = arg_parts[1]
                    num = arg_parts[2]
                    status, reply_msg = sms_contacts_mgr.add_contact(sender, name, num)
                    send_reply(sender, reply_msg, channel_index)
                else:
                    send_reply(sender, "Usage: ?addcontact <name> <number>", channel_index)
                return
                
            if cmd_type == "delcontact":
                arg_parts = msg[1:].strip().split(" ")
                if len(arg_parts) >= 2:
                    name = arg_parts[1]
                    status, reply_msg = sms_contacts_mgr.del_contact(sender, name)
                    send_reply(sender, reply_msg, channel_index)
                else:
                    send_reply(sender, "Usage: ?delcontact <name>", channel_index)
                return

            parts = msg_original[1:].split(" ", 1)
            if len(parts) == 2:
                phone_raw = parts[0]
                body = parts[1]
                clean_phone = ""
                
                if phone_raw.upper() == "L":
                    cached = sms_quick_cache.get(sender)
                    if cached and (time.time() - cached['time']) < 1800:
                        clean_phone = cached['phone']
                    else:
                        send_reply(sender, "No recent SMS saved, or it expired.", channel_index)
                        return
                else:
                    looked_up = sms_contacts_mgr.get_number(sender, phone_raw)
                    if looked_up:
                        clean_phone = looked_up
                    else:
                        clean_phone = re.sub(r'[^\d]', '', phone_raw)
                
                if len(clean_phone) >= 7:
                    sms_quick_cache[sender] = {'phone': clean_phone, 'time': time.time()}
                    if sms_gateway.connected:
                        send_reply(sender, f"Relaying SMS to {clean_phone} via APRS...", channel_index)
                        if not sms_gateway.send_sms(clean_phone, body, sender):
                           send_reply(sender, "Error sending SMS: APRS Gateway Failed.", channel_index) 
                    else:
                        send_reply(sender, "SMS Service Offline. Gateway not configured or disconnected.", channel_index)
                else:
                    send_reply(sender, f"Invalid phone or unknown contact '{phone_raw}'.", channel_index)
            else:
                send_reply(sender, "Format error. Use: ?1234567890 Your text here", channel_index)
            return

        if settings.get("use_signal_test", True):
            snr = packet.get('rxSnr', 'N/A')
            rssi = packet.get('rxRssi', 'N/A')
            resp = f"RXxed!\nSNR is {snr}\nRSSI is {rssi}"
            send_reply(sender, resp, channel_index)
        else:
            send_reply(sender, "Unknown command. DM 'help' for options.", channel_index)

    def on_message_received(packet):
        if 'decoded' in packet and packet['decoded'].get('portnum') == 'TEXT_MESSAGE_APP':
            msg = packet['decoded']['payload'].decode('utf-8').strip()
            sender = packet['fromId']
            if packet.get('toId') != '^all':
                logging.info(f"DM from {sender}: {msg}")
                process_command(msg, sender, packet)
            else:
                # Handle Broadcasts on the Command Channel
                cmd_chan_idx = int(settings.get("cmd_channel", -1))
                if packet.get('channel') == cmd_chan_idx and cmd_chan_idx != -1:
                    logging.info(f"Command Channel broadcast from {sender}: {msg}")
                    process_command(msg, sender, packet, channel_index=cmd_chan_idx)
                else:
                    logging.info(f"Ignored broadcast from {sender}")

    engine.callback_on_message = on_message_received

    # Start monitor
    use_alerts = settings.get("use_alerts", False)
    alert_channel = int(settings.get("alert_channel", 0))
    last_alert_ids = set()

    def check_alerts():
        if not use_alerts or not engine.is_connected:
            threading.Timer(600, check_alerts).start()
            return
            
        logging.info("Checking for weather alerts...")
        wx = WeatherPlugin(float(lat_backup), float(lon_backup), unit=unit)
        alerts = wx.get_alerts()
        
        for alert in alerts:
            aid = alert['id']
            if aid not in last_alert_ids:
                last_alert_ids.add(aid)
                # Meshtastic Alert Bell \a
                msg = f"\a⚠️ WX ALERT: {alert['event']} - {alert['severity']}\n{alert['headline']}"
                logging.info(f"Broadcasting Alert: {alert['event']}")
                engine.send_broadcast(msg, channel_index=alert_channel)
                # 7-second cooldown between multiple alerts to prevent packet loss
                time.sleep(7)
        
        threading.Timer(600, check_alerts).start()

    threading.Timer(10, check_alerts).start()

    def reboot_recovery_task(short_name, was_planned=True):
        engine.last_short_name = short_name
        
        if was_planned:
            try:
                current_name = engine.interface.getShortName()
                if current_name == short_name:
                    logging.info(f"Node already named {short_name}. Skipping reboot.")
                    return
            except:
                pass

            logging.info(f"Interface settle window (1s) before {short_name} command...")
            time.sleep(1)
            
            if not engine.set_short_name(short_name):
                logging.error(f"Failed to set short name to {short_name}")
                return

            logging.info(f"Node rebooting for name change to {short_name}. Waiting 40s...")
            time.sleep(40)
        
        logging.info("Attempting to reconnect...")
        
        if engine.reconnect():
            logging.info("Reconnected successfully. Sending node info broadcast.")
            engine.send_node_info(short_name=short_name)
        else:
            logging.warning(f"Initial reconnect failed. Searching network for '{short_name}'...")
            
            if engine.discover_node(short_name):
                logging.info(f"Node found and reconnected via Discovery! Sending info broadcast.")
                engine.send_node_info(short_name=short_name)
            else:
                logging.error("Discovery failed. Node not found on subnet.")

    def connection_watchdog():
        """Monitors connection and auto-reconnects if peer resets."""
        while True:
            time.sleep(30)
            
            # Send an application-level keepalive to prevent 10-minute NAT/Router drops
            if engine.is_connected and getattr(engine, 'last_conn_type', None) == 'tcp':
                try:
                    engine.interface.sendHeartbeat()
                except BaseException as e:
                    logging.debug(f"Watchdog keepalive failed (expected if node offline): {e}")
                    
            # SMS Gateway Auto-Reconnect
            if getattr(sms_gateway, 'callsign', None) and getattr(sms_gateway, 'passcode', None):
                if not sms_gateway.connected:
                    logging.warning("APRS-IS Connection dropped. Auto-reconnecting in background...")
                    sms_gateway.connect()
                    
            # Only trigger if we WERE connected before (params exist) but aren't now
            if engine.last_conn_params and not engine.is_connected:
                logging.warning("Connection watchdog detected unexpected drop. Triggering recovery...")
                target_name = engine.last_short_name if engine.last_short_name else "ON"
                threading.Thread(target=reboot_recovery_task, args=(target_name, False), daemon=True).start()

    engine.max_retries = int(settings.get("sms_retries", 3))
    engine.retry_cooldown = int(settings.get("sms_cooldown", 15))
    if settings.get("callsign") and settings.get("passcode"):
        sms_gateway.configure(settings["callsign"], settings["passcode"])
        sms_gateway.connect()

    ip_address = settings.get("ip")
    if ip_address:
        logging.info(f"Attempting TCP Connection to {ip_address}...")
        engine.connect_tcp(ip_address)
    elif settings.get("serial_port"):
        logging.info(f"Attempting Serial Connection to {settings.get('serial_port')}...")
        engine.connect_serial(settings.get("serial_port"))
    else:
        logging.warning("No connection targets configured! Please set ip or serial_port in settings.json.")

    threading.Thread(target=connection_watchdog, daemon=True).start()

    logging.info("MeshUpGrade Headless Server is running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down headless server...")
        engine.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
