import json
import logging
import os
import re
import socket
import threading
import time

APRS_USERS_FILE = "aprs_users.json"

def convert_to_aprs_coord(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except:
        return "0000.00N", "00000.00E"
    """Convert decimal degrees to APRS DDMM.mmN/DDDMM.mmE format."""
    lat_deg = int(abs(lat))
    lat_min = (abs(lat) - lat_deg) * 60
    lat_dir = 'N' if lat >= 0 else 'S'
    lat_str = f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}"
    
    lon_deg = int(abs(lon))
    lon_min = (abs(lon) - lon_deg) * 60
    lon_dir = 'E' if lon >= 0 else 'W'
    lon_str = f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"
    
    return lat_str, lon_str

def inject_aprs_packet_and_wait_ack(callsign, passcode, packet_str, wait_ack_id=None, timeout=30):
    import struct
    try:
        logging.info(f"APRS Ephemeral Inject: {packet_str.strip()}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 5))
        sock.settimeout(5)
        sock.connect(('rotate.aprs2.net', 14580))
        login_call = callsign
        if "-" not in login_call:
            login_call += "-13"
        sock.send(f"user {login_call} pass {passcode} vers MeshUpGrade 0.2.0\r\n".encode('utf-8'))
        
        # Give the server a moment and read the authentication response
        login_resp = ""
        try:
            start_l = time.time()
            while time.time() - start_l < 3:
                login_resp += sock.recv(512).decode('utf-8', errors='ignore')
                if "logresp" in login_resp.lower() or "not allowed" in login_resp.lower():
                    break
        except socket.timeout:
            pass
            
        if "unverified" in login_resp.lower() or "not allowed" in login_resp.lower():
            logging.error(f"APRS Login rejected: {login_resp.strip()}")
            sock.close()
            return False

        sock.send(packet_str.encode('utf-8'))
        
        if not wait_ack_id:
            time.sleep(3.0)
            sock.close()
            return True
            
        # Wait for ACK
        sock.settimeout(1.0)
        end_time = time.time() + timeout
        buf = ""
        while time.time() < end_time:
            try:
                data = sock.recv(1024).decode('utf-8', errors='ignore')
                if not data: break
                buf += data
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    if f"ack{wait_ack_id}" in line.lower():
                        sock.close()
                        return True
                    if f"rej{wait_ack_id}" in line.lower():
                        sock.close()
                        return False
            except socket.timeout:
                continue
        sock.close()
        return False
    except Exception as e:
        logging.error(f"APRS Inject failed: {e}")
        return False

class AprsManager:
    def __init__(self, engine, send_reply_func):
        self.engine = engine
        self.send_reply = send_reply_func
        self.users = self._load_users()
        self.setup_sessions = {}
        self.rx_running = False
        self.bounce_sock = False
        self.host_call = "NOCALL"
        self.host_pass = "-1"
        
    def _load_users(self):
        if os.path.exists(APRS_USERS_FILE):
            try:
                with open(APRS_USERS_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading {APRS_USERS_FILE}: {e}")
        return {}
        
    def _save_users(self):
        with open(APRS_USERS_FILE, 'w') as f:
            json.dump(self.users, f, indent=4)
        self.bounce_sock = True

    def start_rx_daemon(self, host_call, host_pass):
        self.host_call = host_call
        self.host_pass = host_pass
        if not self.rx_running:
            self.rx_running = True
            threading.Thread(target=self._rx_loop, daemon=True).start()

    def _rx_loop(self):
        while self.rx_running:
            enabled_users = [f"{v['callsign']}-{v['suffix']}" for v in self.users.values() if v.get('enabled')]
            if not enabled_users:
                time.sleep(10)
                continue
                
            rx_sock = None
            try:
                rx_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                rx_sock.settimeout(30)
                rx_sock.connect(('rotate.aprs2.net', 14580))
                b_filters = " ".join([f"b/{c}" for c in enabled_users])
                
                login_call = self.host_call
                if "-" not in login_call:
                    login_call += "-15"
                    
                login = f"user {login_call} pass {self.host_pass} vers MeshUpGrade 0.2.0 filter {b_filters}\n"
                rx_sock.send(login.encode('utf-8'))
                
                last_rx = time.time()
                buf = ""
                
                self.bounce_sock = False
                while self.rx_running and not self.bounce_sock:
                    try:
                        data = rx_sock.recv(1024).decode('utf-8', errors='ignore')
                        if not data: break
                        last_rx = time.time()
                        buf += data
                        while '\n' in buf:
                            line, buf = buf.split('\n', 1)
                            self._parse_rx(line.strip())
                    except socket.timeout:
                        if time.time() - last_rx > 120:
                            break
                        try: rx_sock.send(b"#keepalive\n")
                        except: break
            except Exception as e:
                logging.error(f"APRS RX Loop Error: {e}")
                
            if rx_sock:
                try: rx_sock.close()
                except: pass
            time.sleep(5)

    def _parse_rx(self, line):
        if line.startswith("#"): return
        
        # Format: N0CALL-1>APRS,TCPIP*::KD9XYZ-9 :Hello world!{123
        if "::" not in line: return
        try:
            head, tail = line.split("::", 1)
            # Find destination call (9 chars padded)
            dest_call = tail[:9].strip()
            payload = tail[10:]
            
            target_node_id = None
            for node_id, prof in self.users.items():
                if prof.get('enabled') and f"{prof['callsign']}-{prof['suffix']}" == dest_call:
                    target_node_id = node_id
                    break
                    
            if target_node_id:
                src_call = head.split(">")[0]
                
                if payload.lower().startswith("ack") or payload.lower().startswith("rej"):
                    return
                    
                msg_body = payload
                msg_id = None
                if "{" in payload:
                    msg_body_parts = payload.split("{", 1)
                    msg_body = msg_body_parts[0]
                    if len(msg_body_parts) > 1:
                        msg_id = msg_body_parts[1]
                    
                logging.info(f"APRS RX match for {target_node_id}: {msg_body}")
                self.send_reply(target_node_id, f"APRS from {src_call}: {msg_body}")
                
                if msg_id:
                    ack_pkt = f"{dest_call}>APRS,TCPIP*::{src_call.ljust(9)}:ack{msg_id}\n"
                    prof = self.users[target_node_id]
                    threading.Thread(
                        target=inject_aprs_packet_and_wait_ack, 
                        args=(prof['callsign'], prof['passcode'], ack_pkt),
                        daemon=True
                    ).start()
        except Exception as e:
            logging.error(f"APRS Parse Error: {e}")

    def _get_callsign_from_longname(self, sender):
        """Extract a ham callsign from a node's longName if present."""
        if not self.engine.interface or not hasattr(self.engine.interface, 'nodes'):
            return None
            
        node = self.engine.interface.nodes.get(sender)
        if not node: return None
        
        ln = node.get('user', {}).get('longName', '')
        # Simple Ham callsign pattern (e.g., K1ABC, KD9XYZ, M0ABC, 2E0XYZ)
        match = re.search(r'\b[a-zA-Z0-9]{1,2}\d[a-zA-Z]{1,3}\b', ln)
        if match:
            return match.group(0).upper()
        return None

    def handle_command(self, sender, text):
        txt_stripped = text.strip()
        cmd = txt_stripped.upper()
        
        # 1. Handle Setup State Machine
        if sender in self.setup_sessions:
            state = self.setup_sessions[sender]
            
            if cmd == "APRS SETUP":
                # Restart
                self.setup_sessions[sender] = {'step': 1}
                self.send_reply(sender, "What is your aprs passcode?")
                return True
                
            step = state['step']
            
            if step == 1:
                if not txt_stripped.isdigit():
                    self.send_reply(sender, "Passcode must be numeric. What is your aprs passcode? (Or send END to cancel)")
                    return True
                state['passcode'] = txt_stripped
                state['step'] = 2
                self.send_reply(sender, "What is your suffix? (Eg. 7, 8, 2, 10)")
                return True
                
            if step == 2:
                state['suffix'] = txt_stripped.replace('-', '') # Strip dash if they added it
                state['step'] = 3
                self.send_reply(sender, "Enter your icon (e.g. /b or - )")
                return True
                
            if step == 3:
                state['icon'] = txt_stripped
                state['step'] = 4
                callsign = self._get_callsign_from_longname(sender) or "UNKNOWN"
                fs_call = f"{callsign}-{state['suffix']}"
                self.send_reply(sender, f"Your configuration will be shown on aprs.fi as {fs_call}, with icon {state['icon']}, using your passcode {state['passcode']}. Is this correct? Y/N")
                return True
                
            if step == 4:
                if cmd in ('Y', 'YES'):
                    callsign = self._get_callsign_from_longname(sender)
                    if not callsign:
                        self.send_reply(sender, "ERROR: No valid ham callsign found in your node's LongName! Configuration aborted. Please update your LongName.")
                        del self.setup_sessions[sender]
                        return True
                        
                    self.users[sender] = {
                        "callsign": callsign,
                        "passcode": state['passcode'],
                        "suffix": state['suffix'],
                        "icon": state['icon'],
                        "enabled": True,
                        "auto_location": False
                    }
                    self._save_users()
                    del self.setup_sessions[sender]
                    self.send_reply(sender, "APRS profile saved! You can now send APRS messages.")
                else:
                    del self.setup_sessions[sender]
                    self.send_reply(sender, "Setup aborted. Send APRS SETUP to start setup again.")
                return True

        if not cmd.startswith("APRS"):
            return False
            
        parts = txt_stripped.split()
        
        if cmd == "APRS":
            msg = (
                "🌐 APRS Gateway Menu:\n\n"
                "APRS SETUP : Link your passcode and icon.\n"
                "APRS ON/OFF : Toggle APRS.\n"
                "APRS <callsign> <msg> : Send a text.\n"
                "APRS LOCATION : Share current location.\n"
                "APRS AUTO LOCATION ON/OFF : Auto-track.\n\n"
                "Note: A valid Ham Callsign must be in your node's LongName!"
            )
            self.send_reply(sender, msg)
            return True
            
        if cmd in ("APRS SETUP"):
            self.setup_sessions[sender] = {'step': 1}
            self.send_reply(sender, "What is your aprs passcode?")
            return True

        if cmd == "APRS ON":
            callsign = self._get_callsign_from_longname(sender)
            if not callsign:
                self.send_reply(sender, "You must have a valid ham callsign in your mesh node's LongName to use APRS!")
                return True
            if sender not in self.users:
                self.send_reply(sender, "You must complete APRS SETUP first!")
                return True
            self.users[sender]['enabled'] = True
            self._save_users()
            self.send_reply(sender, "APRS is now ON.")
            return True
            
        if cmd == "APRS OFF":
            if sender in self.users:
                self.users[sender]['enabled'] = False
                self._save_users()
            self.send_reply(sender, "APRS is now OFF.")
            return True
            
        if cmd == "APRS AUTO LOCATION ON":
            if sender not in self.users or not self.users[sender].get('enabled'):
                self.send_reply(sender, "You must setup and enable APRS first (APRS ON).")
                return True
            self.users[sender]['auto_location'] = True
            self._save_users()
            self.send_reply(sender, "APRS Auto Location is now ON. Your GPS beacons will be mirrored to aprs.fi.")
            return True
            
        if cmd == "APRS AUTO LOCATION OFF":
            if sender in self.users:
                self.users[sender]['auto_location'] = False
                self._save_users()
            self.send_reply(sender, "APRS Auto Location is now OFF.")
            return True
            
        if cmd == "APRS LOCATION":
            self._send_location(sender, manual=True)
            return True

        # Handle APRS Message Send
        # Format: APRS KD9XYZ-9 Hello World! OR APRS KD9XYZ 9 Hello World!
        if len(parts) >= 3:
            if sender not in self.users or not self.users[sender].get('enabled'):
                self.send_reply(sender, "Cannot send. APRS is not ON or not set up. Reply APRS SETUP.")
                return True
                
            target_call = parts[1].upper()
            msg_start_idx = 2
            
            # Format correction for spaces instead of dashes (e.g. APRS KE2BPN 7 Hello)
            if parts[2].isdigit():
                target_call = f"{target_call}-{parts[2]}"
                msg_start_idx = 3
                if len(parts) <= 3:
                    self.send_reply(sender, "Please provide a message to send.")
                    return True
            elif "-" not in target_call and not target_call.isdigit():
                # If they didn't provide a digit, assume SSID 0, or let standard APRS routing handle the raw callsign
                pass
                
            text_to_send = " ".join(parts[msg_start_idx:])
            user_prof = self.users[sender]
            full_source = f"{user_prof['callsign']}-{user_prof['suffix']}"
            
            # Message formatting
            target_padded = target_call.ljust(9)
            msg_id = str(int(time.time() * 10))[-3:]
            aprs_pkt = f"{full_source}>APRS,TCPIP*::{target_padded}:{text_to_send}" + "{" + msg_id + "\r\n"
            
            self.send_reply(sender, f"Sending APRS message to {target_call}...")
            
            def bg_send():
                success = inject_aprs_packet_and_wait_ack(
                    user_prof['callsign'], 
                    user_prof['passcode'], 
                    aprs_pkt, 
                    wait_ack_id=msg_id, 
                    timeout=30
                )
                if success:
                    self.send_reply(sender, f"APRS: Delivered to {target_call}!")
                else:
                    self.send_reply(sender, f"APRS: Failed to receive ACK from {target_call}. They may be offline.")
                    
            threading.Thread(target=bg_send, daemon=True).start()
            return True

        return False

    def _send_location(self, sender, manual=False):
        if sender not in self.users or not self.users[sender].get('enabled'):
            if manual:
                self.send_reply(sender, "Cannot send location. APRS is not ON or not set up.")
            return

        # Fetch location from engine cache
        node = self.engine.interface.nodes.get(sender) if self.engine.interface and hasattr(self.engine.interface, 'nodes') else None
        if not node or 'position' not in node:
            if manual:
                self.send_reply(sender, "No GPS position found for your node on the mesh. Ensure your GPS is active and ambiguity allows sharing.")
            return
            
        pos = node['position']
        lat = pos.get('latitude')
        lon = pos.get('longitude')
        
        if lat is None or lon is None:
            if manual:
                self.send_reply(sender, "Your node's position lacks valid coordinates.")
            return
            
        # Compile packet
        lat_str, lon_str = convert_to_aprs_coord(lat, lon)
        user_prof = self.users[sender]
        full_source = f"{user_prof['callsign']}-{user_prof['suffix']}"
        icon_class = '/' # Primary Table
        icon_id = '['  # Default Jogger/User
        
        icon_in = user_prof.get('icon', '').strip()
        if len(icon_in) == 1:
            icon_class = '/'
            icon_id = icon_in[0]
        elif len(icon_in) >= 2:
            icon_class = icon_in[0]
            icon_id = icon_in[1]
            
        t = time.gmtime()
        time_str = f"{t.tm_mday:02d}{t.tm_hour:02d}{t.tm_min:02d}z"
        # Use '@' for Timestamped Position WITH Messaging to force packet uniqueness and beat duplicate filters!
        aprs_pkt = f"{full_source}>APRS,TCPIP*:@" + time_str + f"{lat_str}{icon_class}{lon_str}{icon_id}HAM licensed node. MeshUpGrade (Github!)\r\n"
        
        def bg_loc_send():
            success = inject_aprs_packet_and_wait_ack(
                user_prof['callsign'], 
                user_prof['passcode'], 
                aprs_pkt
            )
            if manual:
                if success:
                    self.send_reply(sender, "APRS Location sent successfully to aprs.fi!")
                else:
                    self.send_reply(sender, "APRS Location failed to send.")
                    
        threading.Thread(target=bg_loc_send, daemon=True).start()

    def process_mesh_position(self, sender, lat, lon):
        """Hook for engine.py to feed live GPS data to AUTO locators."""
        if sender in self.users and self.users[sender].get('enabled') and self.users[sender].get('auto_location'):
            # Since meshtastic emits position relatively infrequently based on their own settings,
            # we respect the user's "mirror every single packet" request exactly.
            logging.info(f"Auto-mirroring position for {sender} to APRS-IS.")
            self._send_location(sender, manual=False)
