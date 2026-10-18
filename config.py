"""Central configuration for JARVIS."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Tried in order; if one is overloaded or rate-limited, JARVIS falls back to the next.
MODELS = [
    m.strip()
    for m in os.getenv(
        "JARVIS_MODELS", "gemini-3.5-flash,gemini-flash-latest,gemini-flash-lite-latest"
    ).split(",")
    if m.strip()
]

USER_NAME = os.getenv("JARVIS_USER_NAME", "sir")
DATA_DIR = ROOT / "data"
MEMORY_FILE = DATA_DIR / "memory.json"
HISTORY_DB = DATA_DIR / "history.db"
MAX_TOOL_CALLS_PER_TURN = 25  # phone tasks take many small steps

# Cloud servers run on UTC; JARVIS always works in the user's local time.
TIMEZONE = ZoneInfo(os.getenv("JARVIS_TIMEZONE", "Asia/Kolkata"))
# Set on the cloud server (Neon Postgres). Empty = local SQLite in data/history.db.
DATABASE_URL = os.getenv("DATABASE_URL", "")


def now() -> datetime:
    """Current local time for the user (naive, in TIMEZONE)."""
    return datetime.now(TIMEZONE).replace(tzinfo=None)
