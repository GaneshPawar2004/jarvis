"""The memory writer: after every few messages (and when a conversation ends) a quick AI
pass reads what was said and adds, updates or removes long-term memories, so JARVIS keeps
learning without the user saying "remember", and old facts get corrected instead of piling up."""
import json
import threading

from google.genai import types

from core import db, llm, memory

EVERY = 6  # messages between automatic memory passes
BATCH = 40  # most messages read in one pass

PROMPT = """You maintain JARVIS's long-term memory about its user.

Existing memories (id | kind | importance | text):
{existing}

New conversation since the last update:
{conversation}

Return ONLY JSON: {{"add": [{{"kind": str, "subject": str, "text": str, "importance": int}}],
"update": [{{"id": int, "text": str, "importance": int}}], "delete": [int]}}

Rules:
- Keep only lasting, useful things about the user: who they are, people in their life,
  projects, preferences, places, goals, routines. Not one-off requests, not what JARVIS did,
  not small talk.
- If something new changes an existing memory (moved city, new job, changed preference),
  UPDATE that memory; never add a contradicting duplicate.
- DELETE memories the user said are wrong or asked to forget.
- Never store passwords, OTPs, PINs, card or ID numbers.
- kind is one of: person, project, preference, place, goal, routine, fact.
- Each text is one short sentence about "the user", e.g. "The user lives in Mumbai."
- importance 1-5: 5 = core identity (name, home city, job, family), 3 = useful, 1 = minor.
- Nothing worth keeping -> {{"add": [], "update": [], "delete": []}}."""

_lock = threading.Lock()


def _cursor() -> int:
    found = db.rows("SELECT value FROM meta WHERE key = 'memory_writer_cursor'")
    return int(found[0][0]) if found else 0


def run() -> dict:
    """Process conversation messages not yet read by the writer. Safe to call any time."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "already running"}
    try:
        rows = db.rows('SELECT id, "user", reply FROM exchanges WHERE id > ? ORDER BY id LIMIT ?', (_cursor(), BATCH))
        if not rows:
            return {"added": 0, "updated": 0, "deleted": 0}
        existing = memory.items()
        prompt = PROMPT.format(
            existing="\n".join(f"{m['id']} | {m['kind']} | {m['importance']} | {m['text']}" for m in existing) or "(none yet)",
            conversation="\n".join(f"User: {u}\nJARVIS: {r}" for _, u, r in rows)[-15000:],
        )
        response, _ = llm.generate(
            [types.Content(role="user", parts=[types.Part(text=prompt)])],
            types.GenerateContentConfig(response_mime_type="application/json"),
            light=True,
        )
        plan = json.loads(response.text or "{}")
        known = {m["id"] for m in existing}
        added = sum(1 for a in plan.get("add", [])
                    if memory.add(a.get("text", ""), a.get("kind", "fact"), a.get("subject", ""),
                                  a.get("importance", 3), source="writer").startswith(("Saved", "Updated")))
        updated = sum(1 for u in plan.get("update", [])
                      if u.get("id") in known and memory.update(u["id"], u.get("text"), u.get("importance")))
        deleted = sum(1 for d in plan.get("delete", []) if d in known and memory.delete(d))
        db.execute(db.upsert_meta_sql(), ("memory_writer_cursor", str(rows[-1][0])))
        return {"added": added, "updated": updated, "deleted": deleted}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}  # retried on the next pass; the cursor didn't move
    finally:
        _lock.release()


def run_in_background() -> None:
    threading.Thread(target=run, daemon=True).start()
