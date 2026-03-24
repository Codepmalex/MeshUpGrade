import flet as ft
import logging
import os
import sys
import threading
import time
from datetime import datetime
from engine import MeshEngine

START_TIME = time.time()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GuiLogHandler(logging.Handler):
    def __init__(self, log_list, page):
        super().__init__()
        self.log_list = log_list
        self.page = page

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_list.controls.append(ft.Text(msg, font_family="monospace", size=12))
            if len(self.log_list.controls) > 100:
                self.log_list.controls.pop(0)
            self.page.update()
        except Exception:
            # Page likely closed/destroyed
            pass

import json
import re

SETTINGS_FILE = "settings.json"

def save_settings(settings):
    json_str = json.dumps(settings, indent=4)
    header = """## MeshUpGrade Settings Configuration
## This file can be edited manually. Lines starting with ## are ignored.
## Values Guide:
## lat, lon        - Your coordinates (e.g., "40.7128", "-74.0060")
## unit            - "F" for Fahrenheit, "C" for Celsius
## use_alerts      - true or false
## alert_channel   - Channel index for severe weather broadcasts (e.g. "0")
## cmd_channel     - Channel index for command broadcasts ("-1" for DM only)
## use_signal_test - true or false (auto-reply for ping testing)
## sync_ping       - true or false (broadcasts name change to mesh)

"""
    with open(SETTINGS_FILE, "w") as f:
        f.write(header + json_str)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            content = f.read()
            # Strip commented lines so standard JSON parser doesn't crash
            cleaned = re.sub(r'^\s*#.*$', '', content, flags=re.MULTILINE)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing settings.json: {e}")
                return {}
    return {}

from weather import WeatherPlugin
from sms_gateway import AprsIsGateway
from reminders import ReminderManager
from bbs_manager import BbsManager
from sms_contacts import SmsContactsManager
from ai_chat import AiChatManager

def main(page: ft.Page):
    page.title = "MeshUpGrade"
    page.padding = 20
    
    settings = load_settings()
    engine = MeshEngine()
    
    sms_gateway = AprsIsGateway()
    sms_quick_cache = {}
    sms_sessions = {}
    sms_pending_confirm = {}
    SMS_SESSION_TTL = 1800

    MESH_MENU = (
        "Welcome to MeshUpGrade!\n"
        "To chat with someone, text their 4-letter radio name.\n"
        "Reply ENDCONVO to stop chatting.\n"
        "Reply MENU to see this again."
    )

    def _get_node_shortname(node_id):
        if engine.interface and hasattr(engine.interface, 'nodes'):
            node = engine.interface.nodes.get(node_id)
            if node:
                return node.get('user', {}).get('shortName', node_id)
        return node_id

    def _find_node_by_shortname(name):
        exact = None
        fuzzy = None
        fuzzy_short = None
        if engine.interface and hasattr(engine.interface, 'nodes'):
            for node_id, node_info in engine.interface.nodes.items():
                sn = node_info.get('user', {}).get('shortName', '')
                if sn == name:
                    return node_id, sn, True
                if sn.lower() == name.lower() and not fuzzy:
                    fuzzy = node_id
                    fuzzy_short = sn
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
    
    # Weather Settings
    lat_field = ft.TextField(label="Backup Latitude", value=settings.get("lat", "40.7128"), width=150)
    lon_field = ft.TextField(label="Backup Longitude", value=settings.get("lon", "-74.0060"), width=150)
    unit_picker = ft.Dropdown(
        label="Temperature Units",
        value=settings.get("unit", "F"),
        options=[ft.dropdown.Option("F", "Fahrenheit"), ft.dropdown.Option("C", "Celsius")],
        width=200
    )
    use_node_gps = ft.Switch(label="Use Sender's Node GPS (if available)", value=settings.get("use_gps", True))
    sync_ping = ft.Switch(label="Broadcast Node Info after Status Change", value=settings.get("sync_ping", False))

    def get_location(sender_id):
        if use_node_gps.value and engine.interface:
            node = engine.interface.nodes.get(sender_id)
            if node and 'position' in node:
                pos = node['position']
                if 'latitude' in pos and 'longitude' in pos:
                    logging.info(f"Using GPS from node {sender_id}: {pos['latitude']}, {pos['longitude']}")
                    return pos['latitude'], pos['longitude']
        logging.info(f"Using backup location: {lat_field.value}, {lon_field.value}")
        return float(lat_field.value), float(lon_field.value)

    # Log Terminal Component
    log_terminal = ft.Column(scroll=ft.ScrollMode.ALWAYS, height=400, expand=True)
    gui_handler = GuiLogHandler(log_terminal, page)
    gui_handler.setFormatter(logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S'))
    logging.getLogger().addHandler(gui_handler)

    def send_reply(sender, text, channel_index=None):
        if channel_index is not None:
            engine.send_broadcast(text, channel_index=channel_index)
        else:
            engine.send_dm(sender, text)

    reminder_mgr = ReminderManager(send_reply)
    bbs_mgr = BbsManager(engine, send_reply, settings)
    sms_contacts_mgr = SmsContactsManager()
    ai_mgr = AiChatManager(settings)

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
                wx = WeatherPlugin(lat, lon, unit=unit_picker.value)
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
                
                # Verify numeric
                if len(clean_phone) >= 7: # Basic check for valid phone number length
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

        if use_signal_test.value:
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

    # Weather Alert Settings
    use_alerts = ft.Switch(label="Enable Weather Alerts (NWS)", value=settings.get("use_alerts", False))
    alert_channel = ft.Dropdown(
        label="Alert Channel",
        value=str(settings.get("alert_channel", "0")),
        options=[ft.dropdown.Option("0", "Primary (Index 0)")],
        width=250
    )
    alert_warning = ft.Text("⚠️ WARNING: Broadcasting on Channel 0 (LongFast) is highly discouraged and may result in a ban from some meshes.", color="red", visible=False)
    
    test_alert_field = ft.TextField(label="Test Alert Message", value="Test Weather Alert!", width=250)
    
    last_alert_ids = set()

    def update_channels_list():
        if engine.interface:
            chans = engine.get_channels()
            options = [ft.dropdown.Option(str(c['index']), f"Idx {c['index']}: {c['name']}") for c in chans]
            alert_channel.options = options
            cmd_channel.options = [ft.dropdown.Option("-1", "None (DM Only)")] + options
            page.update()

    def check_alerts():
        if not use_alerts.value or not engine.is_connected:
            threading.Timer(600, check_alerts).start()
            return
            
        logging.info("Checking for weather alerts...")
        lat, lon = float(lat_field.value), float(lon_field.value)
        wx = WeatherPlugin(lat, lon, unit=unit_picker.value)
        alerts = wx.get_alerts()
        
        for alert in alerts:
            aid = alert['id']
            if aid not in last_alert_ids:
                last_alert_ids.add(aid)
                # Meshtastic Alert Bell \a
                msg = f"\a⚠️ WX ALERT: {alert['event']} - {alert['severity']}\n{alert['headline']}"
                logging.info(f"Broadcasting Alert: {alert['event']}")
                engine.send_broadcast(msg, channel_index=int(alert_channel.value))
                # 7-second cooldown between multiple alerts to prevent packet loss
                time.sleep(7)
        
        threading.Timer(600, check_alerts).start()

    # Start monitor
    threading.Timer(10, check_alerts).start()

    def send_test_alert_click(e):
        msg = f"\a⚠️ WX TEST: {test_alert_field.value}"
        logging.info(f"Sending test broadcast on channel {alert_channel.value}")
        engine.send_broadcast(msg, channel_index=int(alert_channel.value))

    def alert_channel_change(e):
        alert_warning.visible = (alert_channel.value == "0")
        page.update()

    alert_channel.on_change = alert_channel_change

    # Command Routing Settings
    cmd_channel = ft.Dropdown(
        label="Command Channel (Broadcasts)",
        value=str(settings.get("cmd_channel", "-1")),
        options=[ft.dropdown.Option("-1", "None (DM Only)")],
        width=250
    )
    cmd_warning = ft.Text("⚠️ WARNING: Command channel cannot be the same as the Alert channel.", color="red", visible=False)

    def cmd_channel_change(e):
        if cmd_channel.value != "-1" and cmd_channel.value == alert_channel.value:
            cmd_warning.visible = True
        else:
            cmd_warning.visible = False
        page.update()

    cmd_channel.on_change = cmd_channel_change

    # UI Components
    status_text = ft.Text("Status: Disconnected")
    ip_address = ft.TextField(label="IP Address", value=settings.get("ip", "192.168.1.50"), width=200)
    serial_port = ft.TextField(label="Serial Port (Auto or /dev/...) ", value=settings.get("serial_port", ""), width=200)
    
    def reboot_recovery_task(short_name, was_planned=True):
        engine.last_short_name = short_name
        
        if was_planned:
            # Check if name already matches
            try:
                current_name = engine.interface.getShortName()
                if current_name == short_name:
                    logging.info(f"Node already named {short_name}. Skipping reboot.")
                    status_text.value = f"Status: Connected ({engine.last_conn_type.upper()}) - Already Optimized"
                    page.update()
                    return
            except:
                pass

            # 1-second settle time as requested
            logging.info(f"Interface settle window (1s) before {short_name} command...")
            time.sleep(1)
            
            if not engine.set_short_name(short_name):
                logging.error(f"Failed to set short name to {short_name}")
                return

            logging.info(f"Node rebooting for name change to {short_name}. Waiting 40s...")
            status_text.value = f"Status: Rebooting to {short_name} (40s)..."
            page.update()
            
            time.sleep(40)
        
        logging.info("Attempting to reconnect...")
        status_text.value = "Status: Reconnecting..."
        page.update()
        
        if engine.reconnect():
            logging.info("Reconnected successfully. Sending node info broadcast.")
            engine.send_node_info(short_name=short_name)
            status_text.value = f"Status: Connected ({engine.last_conn_type.upper()}) - Sync OK"
        else:
            logging.warning(f"Initial reconnect failed. Searching network for '{short_name}'...")
            status_text.value = f"Status: Searching network for {short_name}..."
            page.update()
            
            if engine.discover_node(short_name):
                logging.info(f"Node found and reconnected via Discovery! Sending info broadcast.")
                engine.send_node_info(short_name=short_name)
                status_text.value = f"Status: Connected (ADAPTIVE) - Sync OK"
            else:
                logging.error("Discovery failed. Node not found on subnet.")
                status_text.value = "Status: Reconnect Failed (Not Found)"
        page.update()

    def connect_tcp_click(e):
        success = engine.connect_tcp(ip_address.value)
        status_text.value = f"Status: {'Connected (TCP)' if success else 'Failed'}"
        if success:
            settings["ip"] = ip_address.value
            save_settings(settings)
            update_channels_list()
        page.update()

    def connect_serial_click(e):
        port = serial_port.value.strip() if serial_port.value.strip() else None
        success = engine.connect_serial(port)
        status_text.value = f"Status: {'Connected (Serial)' if success else 'Failed'}"
        if success:
            settings["serial_port"] = serial_port.value
            save_settings(settings)
            update_channels_list()
        page.update()

    callsign_field = ft.TextField(label="HAM Callsign", value=settings.get("callsign", ""), width=150)
    passcode_field = ft.TextField(label="APRS Passcode", value=settings.get("passcode", ""), password=True, can_reveal_password=True, width=150)
    retries_field = ft.TextField(label="Max Retries", value=str(settings.get("sms_retries", 3)), width=100)
    cooldown_field = ft.TextField(label="Retry Cooldown (s)", value=str(settings.get("sms_cooldown", 15)), width=130)

    bbs_active_groups_field = ft.TextField(label="Active Groups (comma-separated)", value=", ".join(settings.get("bbs_active_groups", ["group1", "group2"])), width=300)
    bbs_default_exp_field = ft.TextField(label="Default Expiration (Hours)", value=str(settings.get("bbs_default_exp", 12)), width=150)
    bbs_max_exp_field = ft.TextField(label="Max Allowed Expiration (Hours)", value=str(settings.get("bbs_max_exp", 48)), width=150)
    bbs_channel = ft.Dropdown(
        label="BBS Broadcast Channel",
        options=[ft.dropdown.Option("-1", "DM Only")] + [ft.dropdown.Option(str(i), f"Channel {i}") for i in range(8)],
        value=str(settings.get("bbs_channel", "-1")),
    )

    def update_settings_click(e):
        settings.update({
            "lat": lat_field.value,
            "lon": lon_field.value,
            "unit": unit_picker.value,
            "use_gps": use_node_gps.value,
            "sync_ping": sync_ping.value,
            "ip": ip_address.value,
            "serial_port": serial_port.value,
            "use_alerts": use_alerts.value,
            "alert_channel": int(alert_channel.value),
            "use_signal_test": use_signal_test.value,
            "cmd_channel": int(cmd_channel.value),
            "callsign": callsign_field.value,
            "passcode": passcode_field.value,
            "sms_retries": int(retries_field.value if retries_field.value.isdigit() else 3),
            "sms_cooldown": int(cooldown_field.value if cooldown_field.value.isdigit() else 15),
            "bbs_active_groups": [g.strip() for g in bbs_active_groups_field.value.split(",") if g.strip()],
            "bbs_default_exp": int(bbs_default_exp_field.value if bbs_default_exp_field.value.isdigit() else 12),
            "bbs_max_exp": int(bbs_max_exp_field.value if bbs_max_exp_field.value.isdigit() else 48),
            "bbs_channel": int(bbs_channel.value)
        })
        save_settings(settings)
        logging.info("Settings saved.")
        
        # Apply SMS settings
        engine.max_retries = settings["sms_retries"]
        engine.retry_cooldown = settings["sms_cooldown"]
        if settings["callsign"] and settings["passcode"]:
            sms_gateway.configure(settings["callsign"], settings["passcode"])
            if not sms_gateway.connected:
                sms_gateway.connect()
                
        # Apply BBS Settings
        bbs_mgr.groups = [g.lower() for g in settings["bbs_active_groups"]]
        bbs_mgr.default_exp = settings["bbs_default_exp"]
        bbs_mgr.max_exp = settings["bbs_max_exp"]
        bbs_mgr.bbs_channel = settings["bbs_channel"]
                
        page.update()
        
    # Apply initial SMS settings
    engine.max_retries = int(settings.get("sms_retries", 3))
    engine.retry_cooldown = int(settings.get("sms_cooldown", 15))
    if settings.get("callsign") and settings.get("passcode"):
        sms_gateway.configure(settings["callsign"], settings["passcode"])
        sms_gateway.connect()

    # Signal Test Toggle
    use_signal_test = ft.Switch(label="Signal Test (Auto-reply SNR/RSSI)", value=settings.get("use_signal_test", True))

    # View Switcher
    content_area = ft.Column(expand=True, scroll=ft.ScrollMode.ADAPTIVE)

    def auto_find_click(e):
        node_list = ft.Column(scroll=ft.ScrollMode.ADAPTIVE, height=200)
        seen_ips = set()

        def close_dialog(e=None):
            engine.stop_mdns_discovery()
            dialog.open = False
            page.update()

        def select_node(ip_addr):
            ip_address.value = ip_addr
            status_text.value = f"Status: Selected node at {ip_addr}."
            close_dialog()

        def on_node_found(name, ip):
            if ip in seen_ips:
                return
            seen_ips.add(ip)
            
            # Append a new tile for the discovered node
            node_list.controls.append(
                ft.ListTile(
                    title=ft.Text(f"📡 {name}", weight="bold"),
                    subtitle=ft.Text(f"IP: {ip}"),
                    on_click=lambda e, ip_addr=ip: select_node(ip_addr)
                )
            )
            try:
                page.update()
            except Exception:
                pass

        dialog = ft.AlertDialog(
            title=ft.Text("Scanning for Meshtastic Nodes..."),
            content=node_list,
            actions=[ft.TextButton("Cancel", on_click=close_dialog)],
            on_dismiss=lambda e: engine.stop_mdns_discovery()
        )

        page.dialog = dialog
        dialog.open = True
        page.update()
        
        # Start the background sweep
        engine.start_hybrid_discovery(on_node_found)

    def show_connection(e):
        content_area.controls = [
            ft.Text("Connection", size=20),
            ft.Text("WiFi / TCP:", size=16, weight="bold"),
            ft.Text("Tip: Use 'node-name.local' to survive IP changes.", size=12, italic=True),
            ft.Row([ip_address, ft.ElevatedButton("Auto Find", on_click=auto_find_click), ft.ElevatedButton("Connect TCP", on_click=connect_tcp_click)]),
            ft.Divider(),
            ft.Text("USB / Serial:", size=16, weight="bold"),
            ft.Row([serial_port, ft.ElevatedButton("Connect Serial", on_click=connect_serial_click)]),
            ft.Divider(),
            status_text,
            ft.Divider(),
            ft.Text("Command Routing", size=18),
            cmd_channel,
            cmd_warning,
            ft.Divider(),
            ft.Text("Features", size=18),
            use_signal_test,
            sync_ping,
            ft.Divider(),
            ft.Row([
                ft.ElevatedButton("Save Settings", on_click=update_settings_click),
                ft.ElevatedButton("End Program & Logout", on_click=lambda _: shutdown_app(), color="red"),
            ]),
        ]
        page.update()


    def show_weather(e):
        content_area.controls = [
            ft.Text("Weather Configuration", size=20),
            use_node_gps,
            ft.Text("Backup Location (if GPS unavailable):"),
            ft.Row([lat_field, lon_field]),
            unit_picker,
            ft.Divider(),
            ft.Text("Weather Alerts (Broadcasts)", size=18),
            use_alerts,
            alert_channel,
            alert_warning,
            ft.Row([test_alert_field, ft.ElevatedButton("Test Broadcast", on_click=send_test_alert_click)]),
            ft.ElevatedButton("Save Settings", on_click=update_settings_click),
        ]
        page.update()

    def show_sms(e):
        sms_status = ft.Text(f"Gateway Status: {'Connected to APRS-IS' if sms_gateway.connected else 'Disconnected'}", color="green" if sms_gateway.connected else "red")
        content_area.controls = [
            ft.Text("SMS & APRS Gateway", size=20),
            sms_status,
            ft.Text("To use the SMS Gateway, you must provide a valid Amateur Radio Callsign and an APRS-IS Passcode.\nReplies from cell phones will be routed back to the original radio sender automatically via DMs.", size=12, italic=True),
            ft.Divider(),
            ft.Text("APRS-IS Authentication:", size=16, weight="bold"),
            ft.Row([callsign_field, passcode_field]),
            ft.Divider(),
            ft.Text("Mesh Retry Logic (No-ACK Auto-resend):", size=16, weight="bold"),
            ft.Row([retries_field, cooldown_field]),
            ft.Divider(),
            ft.ElevatedButton("Save Settings & Connect", on_click=update_settings_click)
        ]
        page.update()

    def show_terminal(e):
        content_area.controls = [
            ft.Text("Terminal", size=20),
            ft.Container(content=log_terminal, border=ft.border.all(1, "grey400"), padding=10, border_radius=5),
        ]
        page.update()

    def show_bbs(e):
        content_area.controls = [
            ft.Text("Bulletin Board System (BBS)", size=20),
            ft.Text("Configure the local BBS groups and message expiration limits.", size=12, italic=True),
            ft.Divider(),
            bbs_active_groups_field,
            ft.Row([bbs_default_exp_field, bbs_max_exp_field]),
            bbs_channel,
            ft.Divider(),
            ft.ElevatedButton("Save Settings", on_click=update_settings_click)
        ]
        page.update()

    ai_vendor_dropdown = ft.Dropdown(
        label="AI Vendor",
        options=[ft.dropdown.Option("anthropic", "Anthropic"), ft.dropdown.Option("openai", "OpenAI")],
        value=settings.get("ai_vendor", "anthropic"),
        width=180,
    )
    ai_model_dropdown = ft.Dropdown(
        label="AI Model",
        options=[
            ft.dropdown.Option("claude-3-haiku-20240307", "Claude 3.5 Haiku"),
            ft.dropdown.Option("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
            ft.dropdown.Option("claude-3-opus-20240229", "Claude 3 Opus"),
            ft.dropdown.Option("gpt-4o-mini", "GPT-4o Mini"),
            ft.dropdown.Option("gpt-4o", "GPT-4o"),
            ft.dropdown.Option("gpt-4-turbo", "GPT-4 Turbo"),
        ],
        value=settings.get("ai_model", "claude-3-haiku-20240307"),
        width=250,
    )
    ai_api_key_field = ft.TextField(label="API Key", value=settings.get("ai_api_key", ""), password=True, can_reveal_password=True, width=400)

    def save_ai_settings(e):
        settings["ai_vendor"] = ai_vendor_dropdown.value
        settings["ai_model"] = ai_model_dropdown.value
        settings["ai_api_key"] = ai_api_key_field.value
        save_settings(settings)
        ai_mgr.vendor = settings["ai_vendor"]
        ai_mgr.model = settings["ai_model"]
        ai_mgr.api_key = settings["ai_api_key"]
        logging.info("AI settings saved.")
        page.update()

    def show_ai(e):
        content_area.controls = [
            ft.Text("AI Chat Configuration", size=20),
            ft.Text("Configure the AI vendor, model, and API key for mesh AI chat.", size=12, italic=True),
            ft.Divider(),
            ft.Row([ai_vendor_dropdown, ai_model_dropdown]),
            ai_api_key_field,
            ft.Divider(),
            ft.ElevatedButton("Save AI Settings", on_click=save_ai_settings),
        ]
        page.update()

    nav_row = ft.Row([
        ft.ElevatedButton("Connection", on_click=show_connection),
        ft.ElevatedButton("Weather", on_click=show_weather),
        ft.ElevatedButton("SMS", on_click=show_sms),
        ft.ElevatedButton("BBS", on_click=show_bbs),
        ft.ElevatedButton("AI", on_click=show_ai),
        ft.ElevatedButton("Terminal", on_click=show_terminal),
    ])

    def shutdown_app():
        logging.info("Shutting down MeshUpGrade...")
        
        # Show a non-closable dialog to prevent further interaction
        shutdown_dialog = ft.AlertDialog(
            title=ft.Text("Shutting Down"),
            content=ft.Text("Performing final mesh sync (OFF status)...\nThis may take up to 45 seconds."),
            modal=True
        )
        page.dialog = shutdown_dialog
        shutdown_dialog.open = True
        page.update()

        def perform_shutdown_sync():
            try:
                engine.close()
            except Exception as e:
                logging.debug(f"Shutdown sync error (suppressed): {e}")
            finally:
                os._exit(0)

        # Start shutdown sync in a background daemon thread
        threading.Thread(target=perform_shutdown_sync, daemon=True).start()

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
                # Avoid triggering if we are already in the middle of a recovery
                if status_text.value and "Rebooting" in status_text.value:
                    continue
                    
                # Suspend watchdog if the user is actively manually scanning for nodes
                if getattr(page, 'dialog', None) and page.dialog.open:
                    continue
                    
                logging.warning("Connection watchdog detected unexpected drop. Triggering recovery...")
                target_name = engine.last_short_name if engine.last_short_name else "ON"
                
                # For watchdog drops, skip the initial name-change wait (was_planned=False)
                threading.Thread(target=reboot_recovery_task, args=(target_name, False), daemon=True).start()

    # Start the watchdog
    threading.Thread(target=connection_watchdog, daemon=True).start()

    show_connection(None)
    page.add(nav_row, ft.Divider(), content_area)
    page.on_close = shutdown_app

if __name__ == "__main__":
    if not os.path.exists("assets"):
        os.makedirs("assets")
    logging.info("Starting MeshUpGrade GUI...")
    ft.app(target=main)
