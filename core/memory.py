"""Long-term memory (Memory 2.0): what JARVIS knows about the user, as typed memories
(person, project, preference, place, goal, routine, fact) with an importance from 1 to 5.

Only the memories that matter for the current message go to the AI: the core ones
(importance 4-5) always, plus the ones closest in meaning to the message."""
import json
import re

import numpy as np

import config
from core import db

KINDS = ("person", "project", "preference", "place", "goal", "routine", "fact")
SEND_ALL_BELOW = 30  # with few memories, just send them all (no search needed)
RELEVANT_COUNT = 8
RELEVANT_MIN_SCORE = 0.55
RELEVANT_WINDOW = 0.06  # Gemini similarity scores sit in a narrow band: keep only those near the best match
DUPLICATE_SCORE = 0.88  # a new memory this close to an old one updates it instead

# Never stored as memories: secrets and ID numbers (those belong in the phone's vault).
SECRET = re.compile(
    r"password|passcode|\botp\b|\bpin\b|cvv|card number|\b[A-Z]{5}\d{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b|\b\d{13,19}\b",
    re.IGNORECASE,
)

_migrated = False


def _ts() -> str:
    return config.now().isoformat(timespec="seconds")


def _migrate() -> None:
    """One-time moves: data/memory.json (oldest format) and the old facts table into memories."""
    global _migrated
    if _migrated:
        return
    _migrated = True
    if not db.is_postgres() and config.MEMORY_FILE.exists():
        try:
            old = json.loads(config.MEMORY_FILE.read_text(encoding="utf-8"))
            db.execute_many("INSERT INTO facts (fact, saved) VALUES (?, ?)", [(f["fact"], f["saved"]) for f in old])
            config.MEMORY_FILE.rename(config.MEMORY_FILE.with_suffix(".json.migrated"))
        except (json.JSONDecodeError, OSError):
            pass
    if db.rows("SELECT id FROM memories LIMIT 1"):
        return
    facts = db.rows("SELECT fact, saved FROM facts ORDER BY id")
    db.execute_many(
        "INSERT INTO memories (kind, subject, text, importance, source, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("fact", "", fact, 3, "migrated", saved, saved) for fact, saved in facts],
    )


def is_secret(text: str) -> bool:
    return bool(SECRET.search(text))


# ---------------- reading ----------------

def items() -> list[dict]:
    """Every memory, most important first (for the Memory screen and /memory)."""
    _migrate()
    rows = db.rows("SELECT id, kind, subject, text, importance, source, updated FROM memories ORDER BY importance DESC, id")
    keys = ("id", "kind", "subject", "text", "importance", "source", "updated")
    return [dict(zip(keys, r)) for r in rows]


def all_facts() -> list[str]:
    return [m["text"] for m in items()]


def _vectors() -> tuple[list[dict], np.ndarray]:
    """Memories with their meaning-vectors, computing any that are missing."""
    from core.history import _embed  # same embedding model as conversation search

    missing = db.rows("SELECT id, text FROM memories WHERE embedding IS NULL")
    if missing:
        vectors = _embed([t for _, t in missing], "RETRIEVAL_DOCUMENT")
        db.execute_many("UPDATE memories SET embedding = ? WHERE id = ?",
                        [(v.tobytes(), row[0]) for v, row in zip(vectors, missing)])
    rows = db.rows("SELECT id, kind, text, importance, embedding FROM memories")
    found = [{"id": i, "kind": k, "text": t, "importance": imp} for i, k, t, imp, _ in rows]
    matrix = np.array([np.frombuffer(bytes(e), dtype=np.float32) for *_, e in rows]) if rows else np.zeros((0, 768))
    return found, matrix


def for_prompt(message: str | None) -> list[str]:
    """The memories to give the AI for this message: core ones always, plus the most
    relevant; everything when there are only a few."""
    everything = items()
    if len(everything) <= SEND_ALL_BELOW or not message:
        chosen = everything if len(everything) <= SEND_ALL_BELOW else [m for m in everything if m["importance"] >= 4]
        return [f"({m['kind']}) {m['text']}" for m in chosen]
    from core.history import _embed

    try:
        found, matrix = _vectors()
        scores = matrix @ _embed([message], "RETRIEVAL_QUERY")[0]
    except Exception:  # embedding service unavailable: fall back to the core memories
        return [f"({m['kind']}) {m['text']}" for m in everything if m["importance"] >= 4]
    core = [m for m in found if m["importance"] >= 4]
    ranked = sorted(zip(scores, found), key=lambda pair: -pair[0])
    cutoff = max(RELEVANT_MIN_SCORE, (ranked[0][0] if ranked else 1) - RELEVANT_WINDOW)
    relevant = [m for score, m in ranked if score >= cutoff and m["importance"] < 4][:RELEVANT_COUNT]
    return [f"({m['kind']}) {m['text']}" for m in core + relevant]


# ---------------- writing ----------------

def add(text: str, kind: str = "fact", subject: str = "", importance: int = 3, source: str = "chat") -> str:
    """Save a memory. If an existing one says nearly the same thing, it is updated instead."""
    _migrate()
    text = text.strip()
    if not text:
        return "Nothing to remember."
    if is_secret(text):
        return "Not saved: passwords, OTPs and ID numbers never go into memory (use the phone's vault)."
    kind = kind if kind in KINDS else "fact"
    importance = max(1, min(5, int(importance)))
    try:
        from core.history import _embed

        found, matrix = _vectors()
        if len(found):
            scores = matrix @ _embed([text], "RETRIEVAL_QUERY")[0]
            best = int(np.argmax(scores))
            if scores[best] >= DUPLICATE_SCORE:
                update(found[best]["id"], text=text, importance=max(importance, found[best]["importance"]), kind=kind)
                return "Updated an existing memory."
    except Exception:
        pass  # can't check for duplicates right now; save anyway
    db.execute(
        "INSERT INTO memories (kind, subject, text, importance, source, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, subject.strip()[:80], text, importance, source, _ts(), _ts()),
    )
    return "Saved to memory."


def update(memory_id: int, text: str | None = None, importance: int | None = None, kind: str | None = None) -> bool:
    found = db.rows("SELECT text, importance, kind FROM memories WHERE id = ?", (memory_id,))
    if not found:
        return False
    old_text, old_importance, old_kind = found[0]
    new_text = (text or old_text).strip()
    if is_secret(new_text):
        return False
    db.execute(
        "UPDATE memories SET text = ?, importance = ?, kind = ?, updated = ? WHERE id = ?",
        (new_text, max(1, min(5, int(importance or old_importance))), kind if kind in KINDS else old_kind,
         _ts(), memory_id),
    )
    if new_text != old_text:  # its meaning changed: recompute the vector next time it's needed
        db.execute("UPDATE memories SET embedding = NULL WHERE id = ?", (memory_id,))
    return True


def delete(memory_id: int) -> bool:
    if not db.rows("SELECT id FROM memories WHERE id = ?", (memory_id,)):
        return False
    db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    return True


def forget(text: str) -> int:
    """Delete memories matching the words, or the single closest one in meaning."""
    _migrate()
    matches = [r[0] for r in db.rows("SELECT id FROM memories WHERE lower(text) LIKE ?", (f"%{text.lower()}%",))]
    if not matches:
        try:
            from core.history import _embed

            found, matrix = _vectors()
            if len(found):
                scores = matrix @ _embed([text], "RETRIEVAL_QUERY")[0]
                best = int(np.argmax(scores))
                if scores[best] >= 0.7:
                    matches = [found[best]["id"]]
        except Exception:
            pass
    db.execute_many("DELETE FROM memories WHERE id = ?", [(m,) for m in matches])
    return len(matches)


# old names, still used in a few places
add_fact = add
remove_fact = forget
