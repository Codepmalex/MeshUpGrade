import logging
import time
import threading

class AiChatManager:
    SYSTEM_PROMPT = (
        "You are a concise AI assistant embedded in a Meshtastic mesh radio network. "
        "CRITICAL RULE: Every response MUST be UNDER 200 characters total. No exceptions. "
        "Be extremely brief. Use abbreviations. No greetings or filler. Just answer directly."
    )

    VENDORS = {
        "anthropic": {
            "models": ["claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229"],
            "default": "claude-3-5-haiku-20241022"
        },
        "openai": {
            "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
            "default": "gpt-4o-mini"
        }
    }

    def __init__(self, settings):
        self.settings = settings
        self.vendor = settings.get("ai_vendor", "anthropic").lower()
        self.model = settings.get("ai_model", self.VENDORS.get(self.vendor, {}).get("default", ""))
        self.api_key = settings.get("ai_api_key", "")
        # Per-user conversation histories: {sender: {"messages": [...], "last_active": timestamp}}
        self.sessions = {}
        self.session_ttl = 1800  # 30 minutes

    def _prune_sessions(self):
        now = time.time()
        expired = [s for s, data in self.sessions.items() if now - data["last_active"] > self.session_ttl]
        for s in expired:
            del self.sessions[s]

    def clear_session(self, sender):
        if sender in self.sessions:
            del self.sessions[sender]

    def chat(self, sender, user_message):
        if not self.api_key:
            return "AI not configured. Set API key in settings."

        self._prune_sessions()

        if sender not in self.sessions:
            self.sessions[sender] = {"messages": [], "last_active": time.time()}

        session = self.sessions[sender]
        session["last_active"] = time.time()
        session["messages"].append({"role": "user", "content": user_message})

        try:
            if self.vendor == "anthropic":
                response = self._call_anthropic(session["messages"])
            elif self.vendor == "openai":
                response = self._call_openai(session["messages"])
            else:
                return f"Unknown AI vendor '{self.vendor}'."
        except Exception as e:
            logging.error(f"AI API error: {e}")
            return f"AI Error: {str(e)[:150]}"

        session["messages"].append({"role": "assistant", "content": response})
        return response

    def _call_anthropic(self, messages):
        import requests
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": self.model,
            "max_tokens": 100,
            "system": self.SYSTEM_PROMPT,
            "messages": messages
        }
        resp = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]

    def _call_openai(self, messages):
        import requests
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        oai_messages = [{"role": "system", "content": self.SYSTEM_PROMPT}] + messages
        payload = {
            "model": self.model,
            "max_tokens": 100,
            "messages": oai_messages
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
