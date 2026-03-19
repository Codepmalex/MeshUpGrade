import threading
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
        
        # Start the background sweep thread
        self.thread = threading.Thread(target=self._sweep_loop, daemon=True)
        self.thread.start()

    def load_reminders(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.reminders = json.load(f)
            except Exception as e:
                logging.error(f"Failed to load reminders.json: {e}")
                self.reminders = []

    def save_reminders(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.reminders, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save reminders.json: {e}")

    def add_reminder(self, sender, channel_index, timestamp, message):
        self.reminders.append({
            "sender": sender,
            "channel_index": channel_index,
            "timestamp": timestamp,
            "message": message
        })
        self.save_reminders()

    def parse_command(self, msg, sender, channel_index):
        # Expected: RMD HH:MM [YYYY-MM-DD] Message
        # or RMD HH MM [YYYY MM DD] Message
        parts = msg.split(" ")
        
        if len(parts) < 3:
            return "-Reminders Menu-\nFormat:\nrmd HH:MM [Optional Date] Msg\nEx: rmd 14:00 2026-03-25 Fix Antenna\nEx: rmd 14 00 walk dog (defaults to today)"
            
        # Try to parse time
        time_str = parts[1]
        if ":" not in time_str and len(parts) >= 4 and parts[2].isdigit():
            # Support 'HH MM' format
            time_str = f"{parts[1]}:{parts[2]}"
            remaining_parts = parts[3:]
        else:
            time_str = time_str.replace("-", ":") # fallback
            remaining_parts = parts[2:]
            
        try:
            parsed_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            return "Invalid time format. Use HH:MM or HH MM (24-hour time)."
            
        # Try to parse optional date
        date_obj = datetime.now().date()
        message_parts = remaining_parts
        
        if len(remaining_parts) >= 1:
            potential_date = remaining_parts[0]
            # Format YYYY-MM-DD
            if re.match(r'^\d{4}-\d{2}-\d{2}$', potential_date):
                try:
                    date_obj = datetime.strptime(potential_date, "%Y-%m-%d").date()
                    message_parts = remaining_parts[1:]
                except ValueError:
                    pass
            elif len(remaining_parts) >= 3 and remaining_parts[0].isdigit() and len(remaining_parts[0]) == 4:
                # Format YYYY MM DD
                try:
                    date_obj = datetime.strptime(f"{remaining_parts[0]}-{remaining_parts[1]}-{remaining_parts[2]}", "%Y-%m-%d").date()
                    message_parts = remaining_parts[3:]
                except ValueError:
                    pass
                    
        if not message_parts:
            return "You must include a message to remind you about!"
            
        target_datetime = datetime.combine(date_obj, parsed_time)
        now = datetime.now()
        
        if target_datetime < now:
            return f"Error: Cannot schedule reminders in the past! ({target_datetime.strftime('%Y-%m-%d %H:%M')})"
            
        message_body = " ".join(message_parts)
        target_ts = int(target_datetime.timestamp())
        
        self.add_reminder(sender, channel_index, target_ts, message_body)
        
        return f"Reminder set successfully for {target_datetime.strftime('%Y-%m-%d at %H:%M')}!"

    def _sweep_loop(self):
        while True:
            try:
                now = int(time.time())
                pending = []
                remaining = []
                
                for r in self.reminders:
                    if r["timestamp"] <= now:
                        pending.append(r)
                    else:
                        remaining.append(r)
                        
                if pending:
                    self.reminders = remaining
                    self.save_reminders()
                    
                    for task in pending:
                        formatted_msg = f"⏰ REMINDER:\n{task['message']}"
                        logging.info(f"Triggering reminder for {task['sender']}")
                        try:
                            self.callback_send(task['sender'], formatted_msg, task['channel_index'])
                        except Exception as e:
                            logging.error(f"Failed to trigger reminder callback: {e}")
                            
            except Exception as e:
                logging.error(f"Reminder sweep encountered an error: {e}")
                
            time.sleep(60) # Sweep every minute
