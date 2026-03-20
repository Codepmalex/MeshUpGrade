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
                logging.error(f"Failed to load sms_contacts.json: {e}")

    def save_contacts(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.contacts, f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save sms_contacts.json: {e}")

    def add_contact(self, sender, name, number):
        name = name.lower().strip()
        
        stripped_num = ''.join(filter(str.isdigit, number))
        if len(stripped_num) < 10:
            return False, "Error: Invalid number. Must be at least 10 digits."
            
        if sender not in self.contacts:
            self.contacts[sender] = {}
        
        self.contacts[sender][name] = stripped_num
        self.save_contacts()
        return True, f"Contact '{name}' successfully saved as {stripped_num}."

    def del_contact(self, sender, name):
        name = name.lower().strip()
        if sender in self.contacts and name in self.contacts[sender]:
            del self.contacts[sender][name]
            self.save_contacts()
            return True, f"Contact '{name}' deleted."
        return False, f"Error: Contact '{name}' not found in your directory."

    def get_number(self, sender, name):
        name = name.lower().strip()
        if sender in self.contacts and name in self.contacts[sender]:
            return self.contacts[sender][name]
        return None
