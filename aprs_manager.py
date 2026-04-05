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
    import http.client
    try:
        logging.info(f"APRS Ephemeral Inject via HTTP: {packet_str.strip()}")
        login_call = callsign
        if "-" not in login_call:
            login_call += "-13"

        payload = f"user {login_call} pass {passcode} vers MeshUpGrade 0.3.0\r\n{packet_str}"
        body = payload.encode('utf-8')
        headers = {
            'Content-Type': 'application/octet-stream',
            'Content-Length': str(len(body)),
        }

        conn = http.client.HTTPConnection("rotate.aprs2.net", 8080, timeout=10)
        conn.request("POST", "/", body=body, headers=headers)
        resp = conn.getresponse()
        resp_body = resp.read().decode('utf-8', errors='ignore')
        conn.close()

        logging.info(f"APRS HTTP status={resp.status}: {resp_body.strip()}")

        if resp.status in (200, 204):
            return True
        elif resp.status == 403:
            logging.error("APRS HTTP Login rejected: Invalid passcode")
            return False
        else:
            logging.error(f"APRS HTTP Inject failed with status {resp.status}: {resp_body}")
            return False

    except Exception as e:
        logging.error(f"APRS HTTP Inject Exception: {e}")
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
        
    def _save_users(self, bounce=False):
        """Persist users to disk. Set bounce=True to force the RX daemon to reconnect (e.g. after toggling APRS on/off)."""
        try:
            with open(APRS_USERS_FILE, 'w') as f:
                json.dump(self.users, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {APRS_USERS_FILE}: {e}")
        if bounce:
            self.bounce_sock = True

    def start_rx_daemon(self, host_call, host_pass):
        self.host_call = host_call
        self.host_pass = host_pass
        if not self.rx_running:
            self.rx_running = True
            threading.Thread(target=self._rx_loop, daemon=True).start()

    def _rx_loop(self):
        while self.rx_running:
            enabled_users = {}
            for node_id, v in self.users.items():
                if v.get('enabled'):
                    call_with_ssid = f"{v['callsign']}-{v['suffix']}"
                    enabled_users[call_with_ssid.upper()] = node_id

            if not enabled_users:
                time.sleep(10)
                continue

            rx_sock = None
            try:
                rx_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                rx_sock.settimeout(30)
                rx_sock.connect(('rotate.aprs2.net', 14580))

                login_call = self.host_call
                if "-" not in login_call:
                    login_call += "-15"

                # Use message filter 'm/' which specifically delivers messages addressed to our registered callsigns
                # Also add buddy filter 'b/' to additionally receive position updates from those callsigns
                base_calls = list(set(v['callsign'] for v in self.users.values() if v.get('enabled')))
                filter_str = "m/" + "/".join(base_calls)

                login = f"user {login_call} pass {self.host_pass} vers MeshUpGrade 0.2.0 filter {filter_str}\r\n"
                rx_sock.send(login.encode('utf-8'))
                logging.info(f"APRS RX daemon connected. Filter: {filter_str}")

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
                            self._parse_rx(line.strip(), enabled_users)
                    except socket.timeout:
                        if time.time() - last_rx > 120:
                            break
                        try: rx_sock.send(b"#keepalive\r\n")
                        except: break
            except Exception as e:
                logging.error(f"APRS RX Loop Error: {e}")

            if rx_sock:
                try: rx_sock.close()
                except: pass
            time.sleep(5)

    def _parse_rx(self, line, enabled_users):
        """Parse an incoming APRS-IS line. enabled_users is a dict of {CALLSIGN-SSID: node_id}"""
        if line.startswith("#"): return

        # APRS message format: SRC>DEST,PATH::DEST_PADDED:payload{msgid
        if "::" not in line: return
        try:
            head, tail = line.split("::", 1)
            # Dest is 9-char padded field before the colon
            colon_idx = tail.index(":")
            dest_call = tail[:colon_idx].strip().upper()  # strip padding
            payload = tail[colon_idx + 1:]

            target_node_id = enabled_users.get(dest_call)

            if target_node_id:
                src_call = head.split(">")[0]

                if payload.lower().startswith("ack") or payload.lower().startswith("rej"):
                    return

                msg_body = payload
                msg_id = None
                if "{" in payload:
                    msg_body_parts = payload.split("{", 1)
                    msg_body = msg_body_parts[0].strip()
                    if len(msg_body_parts) > 1:
                        msg_id = msg_body_parts[1].strip()

                logging.info(f"APRS RX match for {target_node_id} ({dest_call}): {msg_body}")
                self.send_reply(target_node_id, f"APRS from {src_call}: {msg_body}")

                if msg_id:
                    prof = self.users[target_node_id]
                    full_dest = f"{prof['callsign']}-{prof['suffix']}"
                    ack_pkt = f"{full_dest}>APRS,TCPIP*::{src_call.ljust(9)}:ack{msg_id}\r\n"
                    threading.Thread(
                        target=inject_aprs_packet_and_wait_ack,
                        args=(prof['callsign'], prof['passcode'], ack_pkt),
                        daemon=True
                    ).start()
            else:
                logging.debug(f"APRS RX: ignored line for {tail[:9].strip()} (not in enabled_users)")
        except Exception as e:
            logging.error(f"APRS Parse Error: {e} | line={line!r}")

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
                raw_icon = txt_stripped
                # Sanitize: APRS symbol is always {table_char}{symbol_char}
                # Valid table chars are '/' (primary) and '\' (alternate)
                # If user inputs just one char like '[', assume primary table: '/'
                if len(raw_icon) == 0:
                    raw_icon = '/['  # default: human/jogger
                elif len(raw_icon) == 1:
                    raw_icon = '/' + raw_icon  # prepend primary table
                elif len(raw_icon) >= 2 and raw_icon[0] not in ('/', '\\'):
                    raw_icon = '/' + raw_icon[0]  # treat first char as symbol, primary table
                state['icon'] = raw_icon[:2]  # only keep first 2 chars
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
                "\U0001f310 APRS Gateway Menu:\n\n"
                "APRS SETUP : Link your passcode and icon.\n"
                "APRS ON/OFF : Toggle APRS.\n"
                "APRS <callsign> <msg> : Send a text.\n"
                "APRS LOCATION : Share current location.\n"
                "APRS AUTO LOCATION ON/OFF : Auto-track.\n"
                "APRS FIND <callsign> : Look up anyone on aprs.fi.\n\n"
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
            self._save_users(bounce=True)
            self.send_reply(sender, "APRS is now ON.")
            return True
            
        if cmd == "APRS OFF":
            if sender in self.users:
                self.users[sender]['enabled'] = False
                self._save_users(bounce=True)
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

        # APRS FIND: look up any ham station on aprs.fi
        if len(parts) >= 3 and parts[1].upper() == "FIND":
            target = parts[2].upper()
            self.send_reply(sender, f"Looking up {target} on aprs.fi...")
            def bg_find():
                result = self._aprs_find(target)
                self.send_reply(sender, result)
            threading.Thread(target=bg_find, daemon=True).start()
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
        logging.info(f"APRS _send_location: raw lat={lat!r} lon={lon!r} (types: {type(lat).__name__}, {type(lon).__name__})")
        lat_str, lon_str = convert_to_aprs_coord(lat, lon)
        logging.info(f"APRS coord strings: lat_str={lat_str!r} lon_str={lon_str!r}")
        user_prof = self.users[sender]
        full_source = f"{user_prof['callsign']}-{user_prof['suffix']}"
        icon_class = '/' # Primary Table
        icon_id = '['  # Default Jogger/User
        
        icon_in = user_prof.get('icon', '').strip()
        # icon_in should be 2 chars: table_char + symbol_char (e.g. '/b' = primary table, bicycle)
        # Guard against reversed/bad data from old setups
        if len(icon_in) >= 2 and icon_in[0] in ('/', '\\'):
            icon_class = icon_in[0]
            icon_id = icon_in[1]
        elif len(icon_in) >= 1:
            # single char or bad data: treat as symbol code on primary table
            icon_class = '/'
            icon_id = icon_in[0]
        else:
            icon_class = '/'
            icon_id = '['  # default: human/jogger
            
        t = time.gmtime()
        time_str = f"{t.tm_mday:02d}{t.tm_hour:02d}{t.tm_min:02d}z"
        # Use '@' for Timestamped Position WITH Messaging to force packet uniqueness and beat duplicate filters!
        aprs_pkt = f"{full_source}>APRS,TCPIP*:@" + time_str + f"{lat_str}{icon_class}{lon_str}{icon_id}HAM licensed node. MeshUpGrade (Github!)\r\n"
        logging.info(f"APRS final packet: {aprs_pkt.strip()!r}")
        
        def bg_loc_send():
            success = inject_aprs_packet_and_wait_ack(
                user_prof['callsign'], 
                user_prof['passcode'], 
                aprs_pkt
            )
            if manual:
                if success:
                    self.send_reply(sender, f"APRS Location sent! Packet: {aprs_pkt.strip()}")
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

    def _aprs_find(self, callsign):
        """Query aprs.fi for the last-known position and info of any station. Returns a formatted string."""
        import http.client, urllib.parse
        try:
            # Strip SSID for base lookup — aprs.fi returns all SSIDs of the station
            base_call = callsign.split("-")[0]
            path = f"/api/get?name={urllib.parse.quote(base_call)}&what=loc&apikey=163567.qPHfzJrAp7mMxn&format=json"
            conn = http.client.HTTPConnection("api.aprs.fi", 80, timeout=8)
            conn.request("GET", path, headers={"User-Agent": "MeshUpGrade/0.3"})
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8", errors="ignore")
            conn.close()

            import json as _json
            data = _json.loads(raw)

            if data.get("result") != "ok" or not data.get("entries"):
                return f"No APRS data found for {callsign}. They may not be active."

            e = data["entries"][0]
            name = e.get("name", callsign)
            lat = float(e.get("lat", 0))
            lon = float(e.get("lng", 0))
            course = e.get("course", "")
            speed = e.get("speed", "")
            alt = e.get("altitude", "")
            comment = e.get("comment", "").strip()
            last_time = int(e.get("time", 0))

            # Human-readable time since last seen
            age_s = int(time.time()) - last_time
            if age_s < 60:
                age_str = f"{age_s}s ago"
            elif age_s < 3600:
                age_str = f"{age_s // 60}m ago"
            elif age_s < 86400:
                age_str = f"{age_s // 3600}h ago"
            else:
                age_str = f"{age_s // 86400}d ago"

            lines = [f"📡 {name} ({age_str})"]
            lines.append(f"📍 {lat:.4f}, {lon:.4f}")
            if speed:
                lines.append(f"🚗 {speed} km/h  🧭 {course}°")
            if alt:
                lines.append(f"⬆ {float(alt):.0f} m alt")
            if comment:
                lines.append(f"💬 {comment}")

            return "\n".join(lines)

        except Exception as e:
            logging.error(f"APRS FIND error: {e}")
            return f"Error looking up {callsign}: {e}"

