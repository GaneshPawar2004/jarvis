"""HUD access control for Wi-Fi mode: PIN login, remembered sessions, lockout, origin checks.
Requests from the laptop itself (loopback) don't need a PIN."""
import json
import os
import secrets
import time
from urllib.parse import urlparse

import config

SECRETS_FILE = config.DATA_DIR / "hud_auth.json"
COOKIE = "jarvis_session"
SESSION_DAYS = 30
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300
LOOPBACK = {"127.0.0.1", "::1", "localhost"}

_failures: dict[str, list[float]] = {}


def _load() -> dict:
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def pin() -> str:
    """The HUD PIN: JARVIS_HUD_PIN from .env, else a random 6-digit PIN created once."""
    if os.getenv("JARVIS_HUD_PIN"):
        return os.getenv("JARVIS_HUD_PIN")
    data = _load()
    if "pin" not in data:
        data["pin"] = f"{secrets.randbelow(10**6):06d}"
        _save(data)
    return data["pin"]


def is_loopback(host: str | None) -> bool:
    return host in LOOPBACK


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    sessions = _load().get("sessions", {})
    expiry = sessions.get(token)
    return bool(expiry and expiry > time.time())


def new_session() -> str:
    data = _load()
    now = time.time()
    sessions = {t: exp for t, exp in data.get("sessions", {}).items() if exp > now}
    token = secrets.token_urlsafe(32)
    sessions[token] = now + SESSION_DAYS * 86400
    data["sessions"] = sessions
    _save(data)
    return token


def locked_out(ip: str) -> int:
    """Seconds left in this IP's lockout, or 0."""
    recent = [t for t in _failures.get(ip, []) if t > time.time() - LOCKOUT_SECONDS]
    _failures[ip] = recent
    if len(recent) >= MAX_FAILURES:
        return int(recent[0] + LOCKOUT_SECONDS - time.time()) + 1
    return 0


def record_failure(ip: str) -> None:
    _failures.setdefault(ip, []).append(time.time())


def check_pin(ip: str, attempt: str) -> bool:
    if secrets.compare_digest(attempt.strip().encode(), pin().encode()):
        _failures.pop(ip, None)
        return True
    record_failure(ip)
    return False


def same_origin(origin: str | None, host: str | None) -> bool:
    """Block other websites from driving JARVIS through the user's browser."""
    if origin is None:  # non-browser clients send no Origin
        return True
    return bool(host) and urlparse(origin).netloc == host
