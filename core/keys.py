"""The user's own AI provider keys: stored encrypted in the database with a server-only
secret, shown back only as their last 4 characters, never logged or given to the AI."""
import base64
import hashlib
import os
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config
from core import db

# id -> what it is. "kinds" = what JARVIS can use it for.
PROVIDERS = {
    "gemini": {"name": "Google Gemini", "kinds": ["chat"], "signup": "https://aistudio.google.com/apikey",
               "note": "Free tier; JARVIS's default brain"},
    "anthropic": {"name": "Anthropic Claude", "kinds": ["chat"], "signup": "https://console.anthropic.com/settings/keys",
                  "note": "Paid; strongest at long phone and laptop tasks"},
    "openai": {"name": "OpenAI", "kinds": ["chat", "images"], "signup": "https://platform.openai.com/api-keys",
               "note": "Paid; chat and GPT Image pictures"},
    "groq": {"name": "Groq", "kinds": ["chat"], "signup": "https://console.groq.com/keys",
             "note": "Free tier; very fast replies"},
    "openrouter": {"name": "OpenRouter", "kinds": ["chat"], "signup": "https://openrouter.ai/keys",
                   "note": "One key for many models, some free"},
    "cloudflare": {"name": "Cloudflare Workers AI", "kinds": ["images"], "signup": "https://dash.cloudflare.com/profile/api-tokens",
                   "note": "Free daily images (FLUX); needs your account ID too", "needs_extra": "Account ID"},
    "pollinations": {"name": "Pollinations", "kinds": ["images"], "signup": "https://pollinations.ai",
                     "note": "Free images with no key (small watermark)", "no_key": True},
}


def _cipher() -> AESGCM:
    """A key derived from a server-only secret (JARVIS_KEY_SECRET, or else the JARVIS password)."""
    secret = os.getenv("JARVIS_KEY_SECRET") or os.getenv("JARVIS_PASSWORD", "")
    if not secret:
        raise RuntimeError("No server secret available to protect API keys.")
    return AESGCM(hashlib.scrypt(secret.encode(), salt=b"jarvis-api-keys-v1", n=2**14, r=8, p=1, dklen=32))


def _seal(value: str) -> str:
    nonce = secrets.token_bytes(12)
    return base64.b64encode(nonce + _cipher().encrypt(nonce, value.encode(), None)).decode()


def _open(sealed: str) -> str:
    raw = base64.b64decode(sealed)
    return _cipher().decrypt(raw[:12], raw[12:], None).decode()


def save(provider: str, key: str, extra: str = "") -> None:
    key = key.strip()
    db.execute("DELETE FROM api_keys WHERE provider = ?", (provider,))
    db.execute("INSERT INTO api_keys (provider, secret, extra, last4, added) VALUES (?, ?, ?, ?, ?)",
               (provider, _seal(key), extra.strip(), key[-4:], config.now().isoformat(timespec="seconds")))


def remove(provider: str) -> None:
    db.execute("DELETE FROM api_keys WHERE provider = ?", (provider,))


def get(provider: str) -> tuple[str, str] | None:
    """(key, extra) for a provider the user added; Gemini falls back to the server's own key."""
    found = db.rows("SELECT secret, extra FROM api_keys WHERE provider = ?", (provider,))
    if found:
        try:
            return _open(found[0][0]), found[0][1]
        except Exception:
            return None  # the server secret changed: the key must be added again
    if provider == "gemini" and config.GEMINI_API_KEY:
        return config.GEMINI_API_KEY, ""
    return None


def stored() -> dict[str, dict]:
    """What's saved, without the keys themselves."""
    return {p: {"last4": l4, "added": added} for p, l4, added in db.rows("SELECT provider, last4, added FROM api_keys")}


_settings: dict[str, tuple[float, str | None]] = {}


def setting(name: str, default: str = "") -> str:
    """A saved choice (e.g. which provider runs chat), cached for 30 s to keep replies fast."""
    hit = _settings.get(name)
    if hit is None or time.time() - hit[0] > 30:
        found = db.rows("SELECT value FROM meta WHERE key = ?", (f"setting:{name}",))
        hit = (time.time(), found[0][0] if found else None)
        _settings[name] = hit
    return hit[1] if hit[1] is not None else default


def set_setting(name: str, value: str) -> None:
    db.execute(db.upsert_meta_sql(), (f"setting:{name}", value))
    _settings.pop(name, None)
