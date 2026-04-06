import asyncio
import logging
import json
import os
from meshcore import MeshCore, EventType
from pubsub import pub

class MeshEngine:
    def __init__(self, callback_on_message=None):
        self.client = None
        self.callback_on_message = callback_on_message
        self.is_connected = False
        self.node_id = None
        self.node_info = {}
        
    async def connect_tcp(self, host, port=4403):
        """Connect to a MeshCore node via TCP."""
        try:
            logging.info(f"Connecting to MeshCore node at {host}:{port}...")
            self.client = await MeshCore.create_tcp(host, port)
            
            # Subscribe to the specific events we need
            self.client.subscribe(EventType.CONTACT_MSG_RECV, self._on_event)
            self.client.subscribe(EventType.CHANNEL_MSG_RECV, self._on_event)
            self.client.subscribe(EventType.DEVICE_INFO, self._on_event)
            
            self.is_connected = True
            
            # Fetch basic info
            result = await self.client.commands.req_status()
            if result.type != EventType.ERROR:
                self.node_info = result.payload
                logging.info(f"Connected to MeshCore node: {self.node_info}")
            
            return True
        except Exception as e:
            logging.error(f"MeshCore TCP connection failed: {e}")
            self.is_connected = False
            return False

    async def connect_serial(self, port):
        """Connect to a MeshCore node via Serial."""
        try:
            logging.info(f"Connecting to MeshCore node at {port}...")
            self.client = await MeshCore.create_serial(port)
            self.client.subscribe(EventType.CONTACT_MSG_RECV, self._on_event)
            self.client.subscribe(EventType.CHANNEL_MSG_RECV, self._on_event)
            self.client.subscribe(EventType.DEVICE_INFO, self._on_event)
            self.is_connected = True
            return True
        except Exception as e:
            logging.error(f"MeshCore serial connection failed: {e}")
            self.is_connected = False
            return False

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.is_connected = False

    async def send_dm(self, dest, message):
        """Send a direct message to a destination (hex public key or contact)."""
        if not self.is_connected or not self.client:
            return False
            
        # MeshCore message limit (usually ~200 chars)
        if len(message) > 200:
            message = message[:197] + "..."
            
        try:
            result = await self.client.commands.send_msg(dest, message)
            if result.type == EventType.ERROR:
                logging.error(f"Send failed: {result.payload}")
                return False
            return True
        except Exception as e:
            logging.error(f"Error sending DM: {e}")
            return False

    async def send_broadcast(self, message):
        """Send a broadcast message (to the Public channel)."""
        return await self.send_dm("public", message)

    async def _on_event(self, event):
        """MeshCore event handler (converts MeshCore events to internal pubsub/callbacks)."""
        if event.type in (EventType.CONTACT_MSG_RECV, EventType.CHANNEL_MSG_RECV):
            # event.payload is expected to be a dict with 'sender_pk' and 'text'
            is_public = (event.type == EventType.CHANNEL_MSG_RECV)
            packet = {
                'fromId': event.payload.get('sender_pk', 'unknown'),
                'decoded': {
                    'portnum': 'TEXT_MESSAGE_APP',
                    'payload': event.payload.get('text', '').encode('utf-8')
                },
                'toId': '^all' if is_public else 'me'
            }
            
            if self.callback_on_message:
                asyncio.create_task(self.invoke_callback(packet))
                
        elif event.type == EventType.DEVICE_INFO:
            logging.info(f"Device info received: {event.payload}")
            self.node_info = event.payload

    async def invoke_callback(self, packet):
        if self.callback_on_message:
            if asyncio.iscoroutinefunction(self.callback_on_message):
                await self.callback_on_message(packet)
            else:
                self.callback_on_message(packet)

    def get_short_name(self):
        return self.node_info.get('shortname', 'MeshCore')

    def get_long_name(self):
        return self.node_info.get('longname', 'MeshCore Node')
