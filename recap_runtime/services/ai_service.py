"""Gemini client used by the planner (translation only).

Proxy: GEMINI_PROXY in the .env file wins (e.g. http://127.0.0.1:10808, or "none" for direct).
Without it a local v2rayN proxy on 127.0.0.1:10808 is used when it is running, else direct.
"""
import os
import socket

from google import genai
from google.genai import types  # noqa: F401  (the planner reads ai_service.types)

_LOCAL_PROXY = "http://127.0.0.1:10808"
_PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")


def gemini_proxy() -> str:
    configured = str(os.getenv("GEMINI_PROXY") or "").strip()
    if configured:
        return "" if configured.lower() in {"none", "off", "direct", "0"} else configured
    try:
        with socket.create_connection(("127.0.0.1", 10808), timeout=0.2):
            return _LOCAL_PROXY
    except OSError:
        return ""


class AIService:
    def __init__(self, *, api_key: str | None = None, text_model: str | None = None):
        self.api_key = str(api_key or os.getenv("GEMINI_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("⚠️ GEMINI_API_KEY မတွေ့ပါ! .env ဖိုင်ကို စစ်ဆေးပါ။")
        self.proxy = gemini_proxy()
        self._proxy_snapshot: dict[str, tuple[bool, str | None]] = {}
        self._enable_proxy()
        try:
            self.client = genai.Client(api_key=self.api_key)
        finally:
            self._disable_proxy()
        self.text_model = str(text_model or os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash")).strip()

    def _enable_proxy(self):
        if self.proxy:
            if not self._proxy_snapshot:
                self._proxy_snapshot = {
                    name: (name in os.environ, os.environ.get(name)) for name in _PROXY_ENV_NAMES
                }
            for name in _PROXY_ENV_NAMES:
                os.environ[name] = self.proxy

    def _disable_proxy(self):
        if self.proxy:
            for name, (was_present, previous) in self._proxy_snapshot.items():
                if was_present:
                    os.environ[name] = str(previous or "")
                else:
                    os.environ.pop(name, None)
            self._proxy_snapshot.clear()
