import meshtastic
import meshtastic.tcp_interface
import meshtastic.serial_interface
import logging
from pubsub import pub

class MeshEngine:
    def __init__(self, callback_on_message=None):
        self.interface = None
        self.callback_on_message = callback_on_message
        self.is_connected = False

    def connect_tcp(self, hostname):
        try:
            logging.info(f"Connecting to TCP: {hostname}")
            self.interface = meshtastic.tcp_interface.TCPInterface(hostname)
            self._setup_listeners()
            self.is_connected = True
            return True
        except Exception as e:
            logging.error(f"TCP Connection failed: {e}")
            self.is_connected = False
            return False

    def connect_serial(self, dev_path=None):
        try:
            logging.info(f"Connecting to Serial: {dev_path if dev_path else 'Auto'}")
            self.interface = meshtastic.serial_interface.SerialInterface(devPath=dev_path)
            self._setup_listeners()
            self.is_connected = True
            return True
        except Exception as e:
            logging.error(f"Serial Connection failed: {e}")
            self.is_connected = False
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

    def close(self):
        if self.interface:
            try:
                self.interface.close()
            except Exception:
                pass # Suppress noisy shutdown errors
            self.is_connected = False
