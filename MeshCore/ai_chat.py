import aiohttp
import logging
import time
import json as json_lib

class AiChatManager:
    SYSTEM_PROMPT = (
        "You are a concise AI assistant in a MeshCore mesh network. "
        "Every response MUST be UNDER 200 characters total. No exceptions. "
        "Be extremely brief. No greetings."
    )

    def __init__(self, settings):
        self.settings = settings
        self.vendor = settings.get("ai_vendor", "anthropic").lower()
        self.model = settings.get("ai_model", "claude-3-haiku-20240307")
        self.api_key = settings.get("ai_api_key", "")
        self.sessions = {}
        self.session_ttl = 1800

    def clear_session(self, sender):
        if sender in self.sessions:
            del self.sessions[sender]

    async def chat(self, sender, user_message):
        if not self.api_key:
            return "AI not configured. Set API key in settings."

        if sender not in self.sessions:
            self.sessions[sender] = {"messages": [], "last_active": time.time()}

        session = self.sessions[sender]
        session["last_active"] = time.time()
        session["messages"].append({"role": "user", "content": user_message})

        try:
            if self.vendor == "anthropic":
                response = await self._call_anthropic(session["messages"])
            elif self.vendor == "openai":
                response = await self._call_openai(session["messages"])
            else:
                return f"Unknown AI vendor '{self.vendor}'."
        except Exception as e:
            logging.error(f"AI API error: {e}")
            session["messages"].pop()
            return f"AI Error: {str(e)[:150]}"

        session["messages"].append({"role": "assistant", "content": response})
        return response

    async def _call_anthropic(self, messages):
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "max_tokens": 150,
            "system": self.SYSTEM_PROMPT,
            "messages": messages
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise Exception(f"{resp.status}: {err_text[:100]}")
                    data = await resp.json()
                    return data["content"][0]["text"]
        except Exception as e:
            raise e

    async def _call_openai(self, messages):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        oai_messages = [{"role": "system", "content": self.SYSTEM_PROMPT}] + messages
        payload = {
            "model": self.model,
            "max_tokens": 150,
            "messages": oai_messages
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise Exception(f"{resp.status}: {err_text[:100]}")
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise e
