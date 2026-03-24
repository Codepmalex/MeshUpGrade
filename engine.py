import sys
import logging
try:
    import serial.tools.list_ports
except ImportError:
    import types
    # Mock the serial package for Android/Termux where it fails to build/import
    sys.modules['serial'] = types.ModuleType('serial')
    
    tools_mod = types.ModuleType('serial.tools')
    sys.modules['serial.tools'] = tools_mod
    sys.modules['serial'].tools = tools_mod
    
    list_ports_mod = types.ModuleType('serial.tools.list_ports')
    list_ports_mod.comports = lambda *args, **kwargs: []
    sys.modules['serial.tools.list_ports'] = list_ports_mod
    sys.modules['serial.tools'].list_ports = list_ports_mod

import meshtastic
import meshtastic.tcp_interface
import logging
try:
    import meshtastic.serial_interface
    SERIAL_AVAILABLE = True
except Exception as e:
    # Android Termux cannot load the underlying pyserial module due to missing /dev/tty
    logging.warning(f"Serial interface disabled (Normal for Android/Termux environments): {e}")
    SERIAL_AVAILABLE = False
import time
import socket
import ipaddress
import threading
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

INBOX_FILE = "sms_inbox.json"
from pubsub import pub

try:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
except ImportError:
    Zeroconf = None

class MeshtasticListener:
    def __init__(self, callback):
        self.callback = callback

    def update_service(self, zc, type_, name):
        pass

    def remove_service(self, zc, type_, name):
        pass

    def add_service(self, zc, type_, name):
        if not hasattr(zc, 'get_service_info'): return
        info = zc.get_service_info(type_, name)
        if info and info.addresses:
            ip = socket.inet_ntoa(info.addresses[0])
            
            # Default to the pure service name
            node_name = name.split('.')[0] 
            
            # Try to extract the real shortname from the TXT record properties
            if info.properties and b'shortname' in info.properties:
                try:
                    node_name = info.properties[b'shortname'].decode('utf-8')
                except Exception:
                    pass
            
            if self.callback:
                self.callback(node_name, ip)


class MeshEngine:
    def __init__(self, callback_on_message=None):
        self.interface = None
        self.callback_on_message = callback_on_message
        self.last_short_name = None
        self.last_info_broadcast_time = 0
        self.last_conn_type = None  # 'tcp' or 'serial'
        self.last_conn_params = None
        
        # SMS Auto-Retry System
        self.ack_tracker = {}
        self.max_retries = 3
        self.retry_cooldown = 15
        
        # SMS Offline Inbox
        self.offline_inbox = self._load_inbox()
        
        self.retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self.retry_thread.start()

    def _load_inbox(self):
        if os.path.exists(INBOX_FILE):
            try:
                with open(INBOX_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading {INBOX_FILE}: {e}")
        return {}
        
    def save_inbox(self):
        try:
            with open(INBOX_FILE, 'w') as f:
                json.dump(self.offline_inbox, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {INBOX_FILE}: {e}")

    def check_inbox(self, dest_id):
        # Returns list of pending messages and clears them
        messages = self.offline_inbox.pop(dest_id, [])
        if messages:
            self.save_inbox()
        return messages

    def _retry_loop(self):
        while True:
            time.sleep(1)
            if not self.is_connected:
                continue
            
            now = time.time()
            for pkt_id, data in list(self.ack_tracker.items()):
                if now - data['last_sent'] >= self.retry_cooldown:
                    if data['retries'] < self.max_retries:
                        logging.warning(f"No ACK for direct message to {data['dest_id']}. Retrying ({data['retries'] + 1}/{self.max_retries})...")
                        try:
                            new_packet = self.interface.sendText(data['message'], destinationId=data['dest_id'])
                            new_id = new_packet.id
                            
                            self.ack_tracker[new_id] = {
                                'dest_id': data['dest_id'],
                                'message': data['message'],
                                'retries': data['retries'] + 1,
                                'last_sent': now,
                                'ack_callback': data.get('ack_callback'),
                                'fail_callback': data.get('fail_callback')
                            }
                            del self.ack_tracker[pkt_id]
                        except BaseException as e:
                            logging.error(f"Retry failed (likely offline): {e}")
                    else:
                        logging.warning(f"Max retries reached for {data['dest_id']}. Spooling to Offline Inbox.")
                        if data['dest_id'] not in self.offline_inbox:
                            self.offline_inbox[data['dest_id']] = []
                        self.offline_inbox[data['dest_id']].append(data['message'])
                        self.save_inbox()
                        # Fire fail callback if registered
                        fail_cb = data.get('fail_callback')
                        if fail_cb:
                            try:
                                fail_cb(data['dest_id'])
                            except Exception as e:
                                logging.error(f"Fail callback error: {e}")
                        del self.ack_tracker[pkt_id]

    @property
    def is_connected(self):
        if not self.interface:
            return False
        # The library uses .noProto to indicate the protocol/reader is dead, 
        # but the isConnected event is cleared immediately upon disconnect.
        if hasattr(self.interface, 'isConnected') and not self.interface.isConnected.is_set():
            return False
        if hasattr(self.interface, 'noProto') and self.interface.noProto:
            return False
        return True

    def connect_tcp(self, hostname):
        try:
            self.last_conn_type = 'tcp'
            self.last_conn_params = hostname
            logging.info(f"Connecting to TCP: {hostname}")
            self.interface = meshtastic.tcp_interface.TCPInterface(hostname)
            self._setup_listeners()
            return True
        except Exception as e:
            logging.error(f"TCP Connection failed: {e}")
            return False

    def connect_serial(self, dev_path=None):
        if not SERIAL_AVAILABLE:
            logging.error("Serial Connection is not supported on this device.")
            return False
            
        try:
            self.last_conn_type = 'serial'
            self.last_conn_params = dev_path
            logging.info(f"Connecting to Serial: {dev_path if dev_path else 'Auto'}")
            self.interface = meshtastic.serial_interface.SerialInterface(devPath=dev_path)
            self._setup_listeners()
            return True
        except Exception as e:
            logging.error(f"Serial Connection failed: {e}")
            return False

    def reconnect(self):
        if self.last_conn_type == 'tcp':
            return self.connect_tcp(self.last_conn_params)
        elif self.last_conn_type == 'serial':
            return self.connect_serial(self.last_conn_params)
        return False

    def discover_node(self, target_short_name):
        """Attempts to find the node on the local subnet using mDNS."""
        if self.last_conn_type != 'tcp':
            return False
            
        found_ip = None
        
        def on_node(name, ip):
            nonlocal found_ip
            if found_ip: return
            
            logging.debug(f"mDNS discovered potential node at {ip}")
            try:
                # Need to verify the short name matches our target
                temp_iface = meshtastic.tcp_interface.TCPInterface(ip)
                time.sleep(1) # Let info sync
                if temp_iface.getShortName() == target_short_name:
                    found_ip = ip
                temp_iface.close()
            except:
                pass

        logging.info(f"Scanning via mDNS for node '{target_short_name}'...")
        if not self.start_mdns_discovery(on_node):
            return False
            
        # Wait up to 15 seconds for mDNS discovery and verification
        for _ in range(15):
            if found_ip:
                break
            time.sleep(1)
            
        self.stop_mdns_discovery()
        
        if found_ip:
            logging.info(f"Found node '{target_short_name}' at new IP: {found_ip}")
            self.last_conn_params = found_ip
            return self.connect_tcp(found_ip)
            
        logging.error(f"Discovery failed. Node '{target_short_name}' not found.")
        return False

    def start_mdns_discovery(self, on_node_found):
        """Starts mDNS zeroconf listener to instantly find nodes."""
        if not Zeroconf:
            logging.error("Zeroconf not installed. Cannot run mDNS discovery.")
            return False
            
        try:
            self.stop_mdns_discovery()
            self.mdns_zeroconf = Zeroconf()
            self.mdns_listener = MeshtasticListener(on_node_found)
            self.mdns_browser = ServiceBrowser(self.mdns_zeroconf, "_meshtastic._tcp.local.", self.mdns_listener)
            logging.info("Started mDNS discovery for _meshtastic._tcp.local.")
            return True
        except Exception as e:
            logging.error(f"mDNS start failed: {e}")
            return False

    def stop_mdns_discovery(self):
        """Stops the active mDNS listener."""
        try:
            if hasattr(self, 'mdns_zeroconf') and self.mdns_zeroconf:
                self.mdns_zeroconf.close()
                self.mdns_zeroconf = None
                logging.info("Stopped mDNS discovery.")
        except Exception as e:
            logging.error(f"mDNS stop failed: {e}")

    def start_hybrid_discovery(self, on_node_found_callback):
        """Starts mDNS and immediately follows it up with a rapid subnet port scan."""
        # 1. Start mDNS
        self.start_mdns_discovery(on_node_found_callback)
        
        # 2. Start rapid port sweep in background
        def sweep_task():
            try:
                # find local ip
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    s.connect(('10.255.255.255', 1))
                    local_ip = s.getsockname()[0]
                except:
                    local_ip = '127.0.0.1'
                finally:
                    s.close()
    
                if local_ip == '127.0.0.1':
                    return
    
                network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
                logging.info(f"Hybrid: Sweeping local subnet {network} for port 4403...")
                
                def check_ip(ip):
                    ip_str = str(ip)
                    if ip_str == local_ip: return None
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.75) # Allow 750ms for slow ESP32 handshakes
                        if s.connect_ex((ip_str, 4403)) == 0:
                            return ip_str
                    return None
    
                import threading
                with ThreadPoolExecutor(max_workers=75) as executor:
                    futures = [executor.submit(check_ip, ip) for ip in network.hosts()]
                    for future in as_completed(futures):
                        res = future.result()
                        if res:
                            # We found an open port 4403! 
                            # Do NOT try to connect with TCPInterface here to get the shortname.
                            # It is a heavy protobuf handshake and will crash the node.
                            # Just return the IP address.
                            node_name = f"Swept Node ({res.split('.')[-1]})"
                                
                            on_node_found_callback(node_name, res)
            except Exception as e:
                logging.debug(f"Hybrid sweep error: {e}")
                
        import threading
        threading.Thread(target=sweep_task, daemon=True).start()

    def _setup_listeners(self):
        pub.subscribe(self._on_receive, "meshtastic.receive")

    def _on_receive(self, packet, interface):
        # Auto-flush Offline Inbox if we see activity from a node
        sender = packet.get('fromId')
        if sender and sender in self.offline_inbox:
            # Check if there are messages waiting
            pending = self.check_inbox(sender)
            if pending:
                logging.info(f"Node {sender} is active! Auto-flushing {len(pending)} offline messages.")
                # We spin up a thread so we don't block the packet reception thread
                def flush_msgs(dest, msgs):
                    for m in msgs:
                        self.send_dm(dest, m)
                        time.sleep(5) # Space out bursting
                threading.Thread(target=flush_msgs, args=(sender, pending), daemon=True).start()

        # ACK Tracking interception
        port = packet.get('decoded', {}).get('portnum')
        if port == 'ROUTING_APP':
            routing = packet.get('decoded', {}).get('routing', {})
            if routing.get('errorReason') == 'NONE':
                req_id = routing.get('requestId') or packet.get('decoded', {}).get('requestId')
                if req_id in self.ack_tracker:
                    acked_dest = self.ack_tracker[req_id]['dest_id']
                    ack_callback = self.ack_tracker[req_id].get('ack_callback')
                    logging.info(f"Received ACK for msg {req_id} to {acked_dest}. Clearing all pending retries for this node.")
                    # Clear ALL pending retries targeting this same destination
                    to_remove = [pid for pid, d in self.ack_tracker.items() if d['dest_id'] == acked_dest]
                    for pid in to_remove:
                        del self.ack_tracker[pid]
                    # Fire the callback if one was registered
                    if ack_callback:
                        try:
                            ack_callback(acked_dest)
                        except Exception as e:
                            logging.error(f"ACK callback error: {e}")

        if self.callback_on_message:
            self.callback_on_message(packet)

    def send_dm(self, dest_id, message, ack_callback=None, fail_callback=None):
        if not self.interface:
            return False
        
        # RULE #1: ENFORCE 200 CHAR LIMIT
        if len(message) > 200:
            logging.warning("Message too long, truncating to 200 chars.")
            message = message[:197] + "..."
            
        try:
            packet = self.interface.sendText(message, destinationId=dest_id, wantAck=True)
            if hasattr(packet, 'id'):
                self.ack_tracker[packet.id] = {
                    'dest_id': dest_id,
                    'message': message,
                    'retries': 0,
                    'last_sent': time.time(),
                    'ack_callback': ack_callback,
                    'fail_callback': fail_callback
                }
            return True
        except Exception as e:
            logging.error(f"Failed to send DM: {e}")
            return False

    def get_channels(self):
        if not self.interface or not self.interface.localNode:
            return []
        channels = []
        # localNode.channels is a list of channel settings
        for i, chan in enumerate(self.interface.localNode.channels):
            # chan is often a dict-like or object with settings
            chan_name = f"Channel {i}"
            if hasattr(chan, 'settings') and chan.settings.name:
                chan_name = chan.settings.name
            elif isinstance(chan, dict) and chan.get('settings', {}).get('name'):
                chan_name = chan['settings']['name']
            channels.append({"index": i, "name": chan_name})
        return channels

    def send_broadcast(self, message, channel_index=0):
        if not self.interface:
            return False
            
        # Broadcast guard: wait 5s after info ping
        time_since_ping = time.time() - self.last_info_broadcast_time
        if time_since_ping < 5:
            wait_time = 5 - time_since_ping
            logging.info(f"Broadcast guard: waiting {wait_time:.1f}s for mesh to clear...")
            time.sleep(wait_time)

        # RULE #1: ENFORCE 200 CHAR LIMIT
        if len(message) > 200:
            logging.warning("Broadcast too long, truncating.")
            message = message[:197] + "..."
            
        try:
            # sendText normally broadcasts if no destinationId is provided
            # channelIndex specifies which channel to use
            self.interface.sendText(message, channelIndex=channel_index)
            return True
        except Exception as e:
            logging.error(f"Failed to send broadcast: {e}")
            return False

    def set_short_name(self, short_name):
        if not self.interface or not self.interface.localNode:
            return False
        try:
            logging.info(f"Setting node short name to: {short_name}")
            self.last_short_name = short_name
            self.interface.localNode.setOwner(short_name=short_name)
            return True
        except Exception as e:
            logging.error(f"Failed to set short name: {e}")
            return False

    def send_node_info(self, short_name=None, long_name=None):
        if not self.interface or not self.interface.localNode or not self.is_connected:
            return False
        try:
            curr_sn = self.interface.getShortName()
            sn = short_name if short_name else curr_sn
            ln = long_name if long_name else self.interface.getLongName()
            
            # Avoid redundant flash writes and reboot loops
            if sn == curr_sn:
                logging.info(f"Node shortname is already '{sn}'. Skipping redundant flash write to prevent crash.")
                self.last_info_broadcast_time = time.time()
                return True
                
            logging.info(f"Re-broadcasting node info to mesh (Short: {sn})...")
            self.interface.localNode.setOwner(long_name=ln, short_name=sn)
            self.last_info_broadcast_time = time.time()
            return True
        except (OSError, Exception) as e:
            if "Broken pipe" in str(e) or "[Errno 32]" in str(e):
                logging.debug(f"Info broadcast skipped: Connection closed ({e})")
            else:
                logging.error(f"Failed to send node info: {e}")
            return False

    def close(self):
        if self.interface:
            try:
                self.interface.close()
            except Exception:
                pass # Suppress noisy shutdown errors
