import meshtastic
import meshtastic.tcp_interface
import meshtastic.serial_interface
import logging
import time
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from pubsub import pub

class MeshEngine:
    def __init__(self, callback_on_message=None):
        self.interface = None
        self.callback_on_message = callback_on_message
        self.last_short_name = None
        self.last_info_broadcast_time = 0
        self.last_conn_type = None  # 'tcp' or 'serial'
        self.last_conn_params = None

    @property
    def is_connected(self):
        if not self.interface:
            return False
        # The library uses .noProto to indicate the protocol/reader is dead
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
        """Attempts to find the node on the local subnet if IP changed."""
        if self.last_conn_type != 'tcp' or not self.last_conn_params:
            return False
            
        try:
            # Get the current subnet (assuming /24)
            current_ip = self.last_conn_params
            if not all(c in "0123456789." for c in current_ip):
                return False # Might be a hostname already
                
            network = ipaddress.ip_network(f"{current_ip}/24", strict=False)
            logging.info(f"Scanning subnet {network} for node '{target_short_name}'...")
            
            def check_ip(ip):
                ip_str = str(ip)
                if ip_str == current_ip: return None # Already tried
                
                # Fast port check first
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.2)
                    if s.connect_ex((ip_str, 4403)) == 0:
                        return ip_str
                return None

            candidates = []
            with ThreadPoolExecutor(max_workers=50) as executor:
                futures = [executor.submit(check_ip, ip) for ip in network.hosts()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: candidates.append(res)
            
            for ip in candidates:
                logging.debug(f"Testing candidate node at {ip}...")
                try:
                    # Temporary interface to check name
                    temp_iface = meshtastic.tcp_interface.TCPInterface(ip)
                    # Wait a moment for name to be fetched
                    time.sleep(1)
                    if temp_iface.getShortName() == target_short_name:
                        logging.info(f"Found node '{target_short_name}' at new IP: {ip}")
                        temp_iface.close()
                        self.last_conn_params = ip
                        return self.connect_tcp(ip)
                    temp_iface.close()
                except:
                    continue
                    
        except Exception as e:
            logging.error(f"Discovery error: {e}")
            
        return False

    def _setup_listeners(self):
        pub.subscribe(self._on_receive, "meshtastic.receive")

    def _on_receive(self, packet, interface):
        if self.callback_on_message:
            self.callback_on_message(packet)

    def send_dm(self, dest_id, message):
        if not self.interface:
            return False
        
        # RULE #1: ENFORCE 200 CHAR LIMIT
        if len(message) > 200:
            logging.warning("Message too long, truncating to 200 chars.")
            message = message[:197] + "..."
            
        try:
            self.interface.sendText(message, destinationId=dest_id)
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
            sn = short_name if short_name else self.interface.getShortName()
            ln = long_name if long_name else self.interface.getLongName()
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
