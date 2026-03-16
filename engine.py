import meshtastic
import meshtastic.tcp_interface
import meshtastic.serial_interface
import logging
import time
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
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
            clean_name = name.split('.')[0]
            if self.callback:
                self.callback(clean_name, ip)


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
