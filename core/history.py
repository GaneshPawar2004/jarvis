"""Conversation memory: every exchange is logged, sessions get short summaries, and past
conversations can be searched by meaning (Gemini embeddings)."""
import json
from datetime import datetime

import numpy as np
from google.genai import types

import config
from core import db, llm

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIMS = 768
EMBED_BATCH = 100


def new_session_id() -> str:
    return config.now().strftime("%Y%m%d-%H%M%S")


def _ts() -> str:
    return config.now().isoformat(timespec="seconds")


def log_exchange(session: str, user: str, reply: str) -> None:
    db.execute(
        'INSERT INTO exchanges (session, ts, "user", reply) VALUES (?, ?, ?, ?)',
        (session, _ts(), user, reply),
    )


def session_transcript(session: str) -> str:
    rows = db.rows('SELECT "user", reply FROM exchanges WHERE session = ? ORDER BY id', (session,))
    return "\n".join(f"User: {u}\nJARVIS: {r}" for u, r in rows)


def unsummarized_sessions(exclude: str, limit: int = 3) -> list[str]:
    rows = db.rows(
        """SELECT DISTINCT session FROM exchanges
           WHERE session != ? AND session NOT IN (SELECT session FROM summaries)
           ORDER BY session DESC LIMIT ?""",
        (exclude, limit),
    )
    return [r[0] for r in rows]


def save_summary(session: str, summary: str) -> None:
    """Store a session summary; an empty string marks a session as not worth summarising."""
    db.execute(db.upsert_summary_sql(), (session, _ts(), summary))


def recent_summaries(limit: int = 5) -> list[tuple[str, str]]:
    """(date, summary) pairs for the latest non-empty session summaries, oldest first."""
    rows = db.rows(
        "SELECT session, summary FROM summaries WHERE summary != '' ORDER BY session DESC LIMIT ?",
        (limit,),
    )
    return [(_session_date(s), text) for s, text in reversed(rows)]


def _session_date(session: str) -> str:
    return datetime.strptime(session, "%Y%m%d-%H%M%S").strftime("%d %b %Y, %I:%M %p")


def _embed(texts: list[str], task: str) -> np.ndarray:
    response = llm.client().models.embed_content(
        model=EMBED_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(task_type=task, output_dimensionality=EMBED_DIMS),
    )
    vectors = np.array([e.values for e in response.embeddings], dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _embed_missing() -> None:
    """Embed logged exchanges lazily, so normal chatting never waits on the embedding API."""
    rows = db.rows('SELECT id, "user", reply FROM exchanges WHERE embedding IS NULL')
    for start in range(0, len(rows), EMBED_BATCH):
        batch = rows[start : start + EMBED_BATCH]
        vectors = _embed([f"User: {u}\nJARVIS: {r}" for _, u, r in batch], "RETRIEVAL_DOCUMENT")
        db.execute_many(
            "UPDATE exchanges SET embedding = ? WHERE id = ?",
            [(v.tobytes(), row[0]) for v, row in zip(vectors, batch)],
        )


def search(query: str, limit: int = 5) -> list[dict]:
    """Find past exchanges most related to the query, by meaning; falls back to keywords."""
    try:
        _embed_missing()
        q = _embed([query], "RETRIEVAL_QUERY")[0]
        rows = db.rows('SELECT session, "user", reply, embedding FROM exchanges WHERE embedding IS NOT NULL')
        scored = sorted(
            ((float(np.frombuffer(bytes(e), dtype=np.float32) @ q), s, u, r) for s, u, r, e in rows),
            reverse=True,
        )[:limit]
        matches = [(s, u, r) for score, s, u, r in scored if score > 0.55]
    except Exception:
        words = [w for w in query.lower().split() if len(w) > 2] or [query.lower()]
        clause = " OR ".join('(lower("user") LIKE ? OR lower(reply) LIKE ?)' for _ in words)
        params = [p for w in words for p in (f"%{w}%", f"%{w}%")]
        matches = db.rows(
            f'SELECT session, "user", reply FROM exchanges WHERE {clause} ORDER BY id DESC LIMIT ?',
            (*params, limit),
        )
    return [{"when": _session_date(s), "user": u, "jarvis": r} for s, u, r in matches]


def save_thread(thread: str, contents: list[types.Content]) -> None:
    """Keep the live conversation in the database, so a server restart doesn't wipe it."""
    data = json.dumps([c.model_dump(mode="json", exclude_none=True) for c in contents])
    db.execute(db.upsert_thread_sql(), (thread, _ts(), data))


def load_thread(thread: str) -> list[types.Content]:
    rows = db.rows("SELECT contents FROM threads WHERE id = ?", (thread,))
    if not rows:
        return []
    try:
        return [types.Content.model_validate(c) for c in json.loads(rows[0][0])]
    except Exception:
        return []  # an unreadable thread starts fresh rather than breaking the brain
