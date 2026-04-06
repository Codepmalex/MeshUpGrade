import asyncio
import time
import json
import os
import logging
import re
from datetime import datetime

class ReminderManager:
    def __init__(self, callback_send):
        self.filename = "reminders.json"
        self.callback_send = callback_send
        self.reminders = []
        self.load_reminders()
        asyncio.create_task(self._sweep_loop())

    def load_reminders(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.reminders = json.load(f)
            except Exception as e:
                logging.error(f"Failed to load reminders: {e}")

    async def save_reminders(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.reminders, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save reminders: {e}")

    def add_reminder(self, sender, channel_index, timestamp, message):
        self.reminders.append({
            "sender": sender,
            "channel_index": channel_index,
            "timestamp": timestamp,
            "message": message
        })
        asyncio.create_task(self.save_reminders())

    async def parse_command(self, msg, sender, channel_index):
        parts = msg.split(" ")
        if len(parts) < 3:
            return "-Reminders-\nrmd HH:MM Msg"
            
        time_str = parts[1]
        try:
            parsed_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            return "Invalid time format (HH:MM)."
            
        message_parts = parts[2:]
        target_datetime = datetime.combine(datetime.now().date(), parsed_time)
        
        if target_datetime < datetime.now():
            return "Cannot schedule in the past!"
            
        target_ts = int(target_datetime.timestamp())
        self.add_reminder(sender, channel_index, target_ts, " ".join(message_parts))
        return f"Reminder set for {target_datetime.strftime('%H:%M')}!"

    async def _sweep_loop(self):
        while True:
            try:
                now = int(time.time())
                pending, remaining = [], []
                for r in self.reminders:
                    if r["timestamp"] <= now: pending.append(r)
                    else: remaining.append(r)
                        
                if pending:
                    self.reminders = remaining
                    await self.save_reminders()
                    for task in pending:
                        logging.info(f"Triggering reminder for {task['sender']}")
                        if self.callback_send:
                            await self.callback_send(task['sender'], f"⏰ REMINDER: {task['message']}", task['channel_index'])
            except Exception as e:
                logging.error(f"Reminder sweep error: {e}")
            await asyncio.sleep(60)
