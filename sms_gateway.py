import socket
import logging
import threading
import time
import re
import json
import os

ROUTES_FILE = "sms_routes.json"

class AprsIsGateway:
    def __init__(self, callback_on_sms_reply=None):
        self.server = "rotate.aprs2.net"
        self.port = 14580
        self.callsign = ""
        self.passcode = ""
        self.sock = None
        self.connected = False
        self.listen_thread = None
        self.should_run = False
        
        self.callback_on_sms_reply = callback_on_sms_reply
        self.last_sms_time = 0  # Rate limit tracker
        # Map phone number to original sender Node ID to route replies
        self.routing_table = self._load_routes()

    def _load_routes(self):
        if os.path.exists(ROUTES_FILE):
            try:
                with open(ROUTES_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading {ROUTES_FILE}: {e}")
        return {}
        
    def save_routes(self):
        try:
            with open(ROUTES_FILE, 'w') as f:
                json.dump(self.routing_table, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {ROUTES_FILE}: {e}")

    def configure(self, callsign, passcode):
        self.callsign = callsign.upper().strip()
        self.passcode = passcode.strip()

    def connect(self):
        if not self.callsign or not self.passcode:
            logging.warning("APRS-IS not configured. Cannot connect SMS Gateway.")
            self.connected = False
            return False
            
        try:
            logging.info(f"Connecting to APRS-IS ({self.server}:{self.port}) as {self.callsign}...")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((self.server, self.port))
            
            # Login string. Filter m/{callsign} ensures we get all messages explicitly addressed to us, preventing firehose throttling.
            login_str = f"user {self.callsign} pass {self.passcode} vers MeshUpGrade 0.4.0 filter m/{self.callsign}\r\n"
            self.sock.send(login_str.encode("utf-8"))
            
            self.connected = True
            self.should_run = True
            self.last_rx_time = time.time()
            self.sock.settimeout(0.5) # Non-blocking for loop
            
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
            logging.info("APRS-IS SMS Gateway connected and listening.")
            return True
        except Exception as e:
            logging.error(f"APRS-IS Connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        self.should_run = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = None
        logging.info("APRS-IS SMS Gateway disconnected.")

    def send_sms(self, phone_number, message, original_sender_id, update_route=True):
        if not self.connected:
            logging.error("APRS SMS Gateway not connected. Cannot send.")
            return False
            
        # Rate limit: wait at least 10 seconds between sends to avoid APRS spam blocking
        # (Bypass or reduce for systemic notifications if needed, but safe to keep for all)
        now = time.time()
        elapsed = now - self.last_sms_time
        if elapsed < 10:
            wait = 10 - elapsed
            logging.info(f"SMS rate limit: waiting {wait:.1f}s before sending...")
            time.sleep(wait)
        
        # Clean phone number (strip everything but digits and '+')
        clean_phone = re.sub(r'[^\d]', '', phone_number)
        
        # Save mapping for replies ONLY if this is a real user message (not a "Delivered!" notification)
        if update_route and original_sender_id != "SYSTEM":
            self.routing_table[clean_phone] = original_sender_id
            self.save_routes()
        
        dest_padded = "SMS".ljust(9)
        
        # APRS network deduplicates identical messages. By appending an {ID, we force it to route.
        # We can use a random 3-digit ID or just the last 3 digits of time.
        msg_id = str(int(time.time() * 10))[-3:]
        
        aprs_packet = f"{self.callsign}>APRS,TCPIP*::{dest_padded}:@{clean_phone} {message}" + "{" + msg_id + "\r\n"
        
        try:
            self.sock.send(aprs_packet.encode("utf-8"))
            self.last_sms_time = time.time()
            logging.info(f"Sent SMS via APRS to {clean_phone} (msg_id={msg_id})")
            return True
        except Exception as e:
            logging.error(f"Failed to send APRS SMS: {e}")
            self.connected = False
            return False

    def _listen_loop(self):
        buf = ""
        while self.should_run:
            try:
                data = self.sock.recv(4096).decode("utf-8", errors="ignore")
                if not data:
                    logging.error("APRS-IS connection closed by server.")
                    break
                    
                self.last_rx_time = time.time()
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    self._parse_line(line.strip())
            except socket.timeout:
                now = time.time()
                # Send keepalive every 60s to keep connection alive
                if hasattr(self, '_last_keepalive') and now - self._last_keepalive > 60:
                    try:
                        self.sock.send(b"#keepalive\n")
                        self._last_keepalive = now
                    except:
                        pass
                else:
                    if not hasattr(self, '_last_keepalive'):
                        self._last_keepalive = now
                if getattr(self, 'last_rx_time', 0) and now - self.last_rx_time > 120:
                    logging.error("APRS-IS connection timed out (no keepalives for 120s). Dropping.")
                    break
            except Exception as e:
                logging.error(f"APRS-IS listening error: {e}")
                break
                
        self.connected = False

    def _parse_line(self, line):
        # Ignore server comments starting with #
        if line.startswith("#"):
            return
        
        # Log ALL incoming APRS traffic for debugging
        logging.debug(f"APRS-IS RX: {line}")
            
        # Look for messages TO us: anything containing ::OURCALL  :
        callsign_field = f":{self.callsign.ljust(9)}:"
        if callsign_field not in line:
            return
        
        try:
            # Extract the payload after the addressee
            payload = line.split(callsign_field, 1)[1]
            
            # Payload format from SMSGTE is usually @1234567890 Message body{ID or #alias Message body{ID
            if payload.startswith("@") or payload.startswith("#"):
                # Split at first space to separate number/alias and message
                parts = payload[1:].split(" ", 1)
                if len(parts) == 2:
                    reply_phone = parts[0]
                    reply_msg = parts[1]
                    
                    # Strip trailing ack request if present e.g. "Message body{123"
                    if "{" in reply_msg:
                        reply_msg = reply_msg.split("{")[0]
                        
                    logging.info(f"Received SMS reply from {reply_phone}: {reply_msg}")
                    
                    # Send ACK back to APRS-IS if it had an ID
                    if "{" in payload:
                        msg_id = payload.split("{")[1]
                        ack_packet = f"{self.callsign}>APRS,TCPIP*::{'SMS'.ljust(9)}:ack{msg_id}\r\n"
                        try:
                            self.sock.send(ack_packet.encode('utf-8'))
                        except:
                            pass
                    
                    if self.callback_on_sms_reply:
                        target_mesh_node = self.routing_table.get(reply_phone)
                        self.callback_on_sms_reply(reply_phone, reply_msg, target_mesh_node)
        except Exception as e:
            logging.error(f"Error parsing APRS SMS packet: {e} | Line: {line}")
