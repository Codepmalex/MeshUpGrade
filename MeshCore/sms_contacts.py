import os
import json
import logging

class SmsContactsManager:
    def __init__(self):
        self.filename = "sms_contacts.json"
        self.contacts = {}
        self.load_contacts()

    def load_contacts(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.contacts = json.load(f)
            except Exception as e:
                logging.error(f"Failed to load SMS contacts: {e}")

    async def save_contacts(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.contacts, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save SMS contacts: {e}")

    async def add_contact(self, sender, name, number):
        name = name.lower().strip()
        stripped_num = ''.join(filter(str.isdigit, number))
        if len(stripped_num) < 10:
            return False, "Error: Invalid number."
            
        if sender not in self.contacts: self.contacts[sender] = {}
        self.contacts[sender][name] = stripped_num
        await self.save_contacts()
        return True, f"Contact '{name}' saved."

    def get_number(self, sender, name):
        name = name.lower().strip()
        return self.contacts.get(sender, {}).get(name)

    def list_contacts(self, sender):
        if sender not in self.contacts: return "No contacts."
        lines = [f"{n}: {num}" for n, num in self.contacts[sender].items()]
        return "\n".join(lines)
