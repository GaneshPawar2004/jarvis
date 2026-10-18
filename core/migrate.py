"""One-time copy of the laptop's old local memory (data/history.db) into the shared Neon
database, so laptop JARVIS and cloud JARVIS remember the same things."""
import sqlite3
from contextlib import closing

import config
from core import db


def run() -> None:
    if not db.is_postgres():
        print("No Neon database configured (NEON_DB_URL / DATABASE_URL in .env).")
        return
    if not config.HISTORY_DB.exists():
        print("No local memory to copy.")
        return
    with closing(sqlite3.connect(config.HISTORY_DB)) as local:
        tables = {r[0] for r in local.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        facts = local.execute("SELECT fact, saved FROM facts").fetchall() if "facts" in tables else []
        exchanges = local.execute('SELECT session, ts, "user", reply, embedding FROM exchanges').fetchall()
        summaries = local.execute("SELECT session, ts, summary FROM summaries").fetchall()

    known_facts = {r[0] for r in db.rows("SELECT fact FROM facts")}
    new_facts = [f for f in facts if f[0] not in known_facts]
    db.execute_many("INSERT INTO facts (fact, saved) VALUES (?, ?)", new_facts)

    known_sessions = {r[0] for r in db.rows("SELECT DISTINCT session FROM exchanges")}
    new_exchanges = [e for e in exchanges if e[0] not in known_sessions]
    db.execute_many('INSERT INTO exchanges (session, ts, "user", reply, embedding) VALUES (?, ?, ?, ?, ?)', new_exchanges)

    known_summaries = {r[0] for r in db.rows("SELECT session FROM summaries")}
    new_summaries = [s for s in summaries if s[0] not in known_summaries]
    db.execute_many(db.upsert_summary_sql(), new_summaries)

    print(f"Copied {len(new_facts)} facts, {len(new_exchanges)} chat messages and "
          f"{len(new_summaries)} conversation summaries to the shared memory.")
