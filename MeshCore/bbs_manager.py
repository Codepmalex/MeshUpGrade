import os
import json
import logging
import asyncio
import time
import re
from datetime import datetime

class BbsManager:
    def __init__(self, engine, send_reply_func, settings):
        self.filename = "bbs_store.json"
        self.engine = engine
        self.send_reply = send_reply_func
        self.settings = settings
        self.groups = [g.lower().strip() for g in self.settings.get("bbs_active_groups", ["group1", "group2"])]
        self.store = {"messages": {}, "subscriptions": {}}
        for g in self.groups:
            self.store["messages"][g] = []
            self.store["subscriptions"][g] = []
        self.load_store()

    def load_store(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    data = json.load(f)
                    for g in self.groups:
                        if g in data.get("messages", {}): self.store["messages"][g] = data["messages"][g]
                        if g in data.get("subscriptions", {}): self.store["subscriptions"][g] = data["subscriptions"][g]
            except Exception as e:
                logging.error(f"Failed to load BBS store: {e}")

    async def save_store(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.store, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save BBS store: {e}")

    async def parse_command(self, msg, sender, channel_index):
        parts = msg.strip().split(" ")
        cmd = parts[0].upper()
        
        if cmd == "BBS" and len(parts) == 1:
            glist = ", ".join(self.groups)
            menu = f"-BBS-\nGroups: {glist}\nbbs rx <grp>\nbbs tx <grp> <msg>\nbbs sub <grp>"
            await self.send_reply(sender, menu, channel_index)
            return

        if cmd == "BBS" and len(parts) >= 3 and parts[1].upper() == "SUB":
            group = parts[2].lower()
            if group not in self.groups:
                await self.send_reply(sender, f"Group '{group}' not found.", channel_index)
                return
            if sender not in self.store["subscriptions"][group]:
                self.store["subscriptions"][group].append(sender)
                await self.save_store()
            await self.send_reply(sender, f"Subscribed to {group}!", channel_index)
            return

        if cmd == "BBSTX" or (cmd == "BBS" and len(parts) >= 3 and parts[1].upper() == "TX"):
            # Simplified logic for example
            group = parts[2].lower() if cmd == "BBS" else parts[1].lower()
            if group not in self.groups: return
            msg_body = " ".join(parts[3:] if cmd == "BBS" else parts[2:])
            
            # Add message
            now = int(time.time())
            self.store["messages"][group].append({
                "sender": sender[:10],
                "timestamp": now,
                "message": msg_body
            })
            await self.save_store()
            await self.send_reply(sender, f"Posted to {group.upper()}!", channel_index)
            
            # Notify subscribers
            notification = f"BBS {group.upper()}: '{msg_body[:80]}'"
            for sub in self.store["subscriptions"][group]:
                if sub != sender:
                    asyncio.create_task(self._notify_user(sub, notification))
            return

    async def _notify_user(self, sub, text):
        await asyncio.sleep(5)
        # Assuming our engine has an async send_dm
        await self.engine.send_dm(sub, text)
