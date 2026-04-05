import os
import json
import logging
import time
import re
import threading
from datetime import datetime

class BbsManager:
    def __init__(self, engine, send_reply_func, settings):
        self.filename = "bbs_store.json"
        self.engine = engine
        self.send_reply = send_reply_func
        self.settings = settings
        
        self.groups = [g.lower().strip() for g in self.settings.get("bbs_active_groups", ["group1", "group2"])]
        self.default_exp = int(self.settings.get("bbs_default_exp", 12))
        self.max_exp = int(self.settings.get("bbs_max_exp", 48))
        self.bbs_channel = int(self.settings.get("bbs_channel", -1))
        
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
                    
                # Merge loaded data into expected structure
                for g in self.groups:
                    if g in data.get("messages", {}):
                        self.store["messages"][g] = data["messages"][g]
                    if g in data.get("subscriptions", {}):
                        self.store["subscriptions"][g] = data["subscriptions"][g]
                        
            except Exception as e:
                logging.error(f"Failed to load bbs_store.json: {e}")
        self._prune_expired()

    def save_store(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.store, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save bbs_store.json: {e}")

    def _prune_expired(self):
        now = int(time.time())
        changed = False
        for g in self.groups:
            original_len = len(self.store["messages"][g])
            self.store["messages"][g] = [m for m in self.store["messages"][g] if m["expiration"] > now]
            if len(self.store["messages"][g]) != original_len:
                changed = True
        if changed:
            self.save_store()

    def parse_command(self, msg, sender, channel_index):
        self._prune_expired()
        parts = msg.strip().split(" ")
        
        cmd = parts[0].upper()
        
        if cmd == "BBS" and len(parts) == 1:
            glist = ", ".join(self.groups)
            menu = f"-BBS Menu-\nActive: {glist}\nbbsrx <grp> [pX]\nbbstx <grp> [expHrs] <msg>\nbbs sub <grp>\nbbsunsub <grp>\nbbsaddgroup <name>\nbbsdelgroup <name>"
            self.send_reply(sender, menu, channel_index)
            return

        if cmd == "BBS" and len(parts) >= 3 and parts[1].upper() in ["SUB", "SUBSCRIBE"]:
            group = parts[2].lower()
            if group not in self.groups:
                self.send_reply(sender, f"Group '{group}' not found.", channel_index)
                return
            if sender not in self.store["subscriptions"][group]:
                self.store["subscriptions"][group].append(sender)
                self.save_store()
            self.send_reply(sender, f"Subscribed to DM notifications for {group}!", channel_index)
            return

        if cmd == "BBSUNSUB":
            if len(parts) < 2:
                self.send_reply(sender, "Usage: BBSUNSUB <group>", channel_index)
                return
            group = parts[1].lower()
            if group not in self.groups:
                self.send_reply(sender, f"Group '{group}' not found.", channel_index)
                return
            if sender in self.store["subscriptions"][group]:
                self.store["subscriptions"][group].remove(sender)
                self.save_store()
                self.send_reply(sender, f"Unsubscribed from {group}.", channel_index)
            else:
                self.send_reply(sender, f"You are not subscribed to {group}.", channel_index)
            return

        if cmd == "BBSRX":
            if len(parts) < 2:
                self.send_reply(sender, "Usage: BBSRX <group> [pX]", channel_index)
                return
            group = parts[1].lower()
            if group not in self.groups:
                self.send_reply(sender, f"Group '{group}' not found.", channel_index)
                return
            
            page_index = 0
            if len(parts) >= 3:
                p_match = re.match(r'^P(\d+)$', parts[2].upper())
                if p_match:
                    page_index = int(p_match.group(1)) - 1
                
            msgs = self.store["messages"][group]
            if not msgs:
                self.send_reply(sender, f"No active messages in {group}.", channel_index)
                return
            
            # Sort msgs by timestamp descending (newest first)
            msgs_sorted = sorted(msgs, key=lambda x: x['timestamp'], reverse=True)
            
            if page_index < 0 or page_index >= len(msgs_sorted):
                self.send_reply(sender, f"Page P{page_index + 1} not found. (Total msgs: {len(msgs_sorted)})", channel_index)
                return
                
            m = msgs_sorted[page_index]
            
            # Form relative expiration time
            rem_sec = m['expiration'] - int(time.time())
            if rem_sec < 3600:
                rem_str = "<1hr"
            else:
                rem_str = f"{int(rem_sec / 3600)}hr"
                
            self.send_reply(sender, f"--{group.upper()} (P{page_index + 1}/{len(msgs_sorted)})--\n{m['sender']}: {m['message']}\n(Exp {rem_str})", channel_index)
            return

        if cmd == "BBSTX":
            if len(parts) < 3:
                self.send_reply(sender, "Usage: BBSTX <group> [expHrs] <msg>", channel_index)
                return
            
            group = parts[1].lower()
            if group not in self.groups:
                self.send_reply(sender, f"Group '{group}' not found.", channel_index)
                return
            
            # Check for optional exp parameter
            exp_match = re.match(r'^EXP(\d+)$', parts[2].upper())
            if exp_match:
                exp_hrs = int(exp_match.group(1))
                if exp_hrs > self.max_exp:
                    exp_hrs = self.max_exp
                msg_body = " ".join(parts[3:])
            else:
                exp_hrs = self.default_exp
                msg_body = " ".join(parts[2:])
                
            if not msg_body:
                self.send_reply(sender, "Message body cannot be empty.", channel_index)
                return
                
            # Add message
            now = int(time.time())
            exp_ts = now + (exp_hrs * 3600)
            
            # Get shortname for sender if possible
            sender_name = sender
            if hasattr(self.engine, 'interface') and self.engine.interface:
                node = self.engine.interface.nodes.get(sender)
                if node and 'user' in node and 'shortName' in node['user']:
                    sender_name = node['user']['shortName']
            
            self.store["messages"][group].append({
                "sender": sender_name,
                "timestamp": now,
                "expiration": exp_ts,
                "message": msg_body
            })
            self.save_store()
            
            self.send_reply(sender, f"Posted to {group.upper()}! (Expires in {exp_hrs}h)", channel_index)

            # Notify subscribers — run in background thread so we don't block the message handler
            notification_str = f"BBS {group.upper()}: '{msg_body[:80]}' -{sender_name}"
            subscribers = list(self.store["subscriptions"][group])  # snapshot

            def _notify(subs, notif):
                for sub in subs:
                    if sub != sender:
                        time.sleep(5)  # 5s stagger is enough; no need for 15s
                        self.engine.send_dm(sub, notif)

            threading.Thread(target=_notify, args=(subscribers, notification_str), daemon=True).start()

        if cmd == "BBSADDGROUP":
            if len(parts) < 2:
                self.send_reply(sender, "Usage: BBSADDGROUP <name>", channel_index)
                return
            group = parts[1].lower()
            if group in self.groups:
                self.send_reply(sender, f"Group '{group}' already exists.", channel_index)
                return
            self.groups.append(group)
            self.store["messages"][group] = []
            self.store["subscriptions"][group] = []
            self.settings["bbs_active_groups"] = self.groups
            self.save_store()
            self._save_settings()
            self.send_reply(sender, f"Group '{group}' created!", channel_index)
            return

        if cmd == "BBSDELGROUP":
            if len(parts) < 2:
                self.send_reply(sender, "Usage: BBSDELGROUP <name>", channel_index)
                return
            group = parts[1].lower()
            if group not in self.groups:
                self.send_reply(sender, f"Group '{group}' not found.", channel_index)
                return
            self.groups.remove(group)
            self.store["messages"].pop(group, None)
            self.store["subscriptions"].pop(group, None)
            self.settings["bbs_active_groups"] = self.groups
            self.save_store()
            self._save_settings()
            self.send_reply(sender, f"Group '{group}' deleted.", channel_index)
            return

    def _save_settings(self):
        try:
            with open("settings.json", 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save settings.json: {e}")
