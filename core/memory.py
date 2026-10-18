"""Long-term memory: simple facts JARVIS keeps about the user, stored in the database."""
import json

import config
from core import db

_migrated = False


def _migrate_json() -> None:
    """One-time move of facts from the old data/memory.json into the database."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    if db.is_postgres() or not config.MEMORY_FILE.exists():
        return
    try:
        old = json.loads(config.MEMORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if old and not db.rows("SELECT id FROM facts LIMIT 1"):
        db.execute_many("INSERT INTO facts (fact, saved) VALUES (?, ?)", [(f["fact"], f["saved"]) for f in old])
    config.MEMORY_FILE.rename(config.MEMORY_FILE.with_suffix(".json.migrated"))


def add_fact(fact: str) -> None:
    _migrate_json()
    db.execute("INSERT INTO facts (fact, saved) VALUES (?, ?)", (fact, config.now().isoformat(timespec="seconds")))


def remove_fact(text: str) -> int:
    _migrate_json()
    matches = db.rows("SELECT id FROM facts WHERE lower(fact) LIKE ?", (f"%{text.lower()}%",))
    db.execute_many("DELETE FROM facts WHERE id = ?", [(m[0],) for m in matches])
    return len(matches)


def all_facts() -> list[str]:
    _migrate_json()
    return [r[0] for r in db.rows("SELECT fact FROM facts ORDER BY id")]
