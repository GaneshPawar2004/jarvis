"""Storage for memory and conversation history: SQLite on the laptop, Postgres in the cloud
(when DATABASE_URL is set). Callers write SQL with "?" placeholders for both."""
import sqlite3
import threading
from contextlib import closing

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exchanges (
    id {pk},
    session TEXT NOT NULL,
    ts TEXT NOT NULL,
    "user" TEXT NOT NULL,
    reply TEXT NOT NULL,
    embedding {blob}
);
CREATE TABLE IF NOT EXISTS summaries (
    session TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id {pk},
    fact TEXT NOT NULL,
    saved TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    expires REAL NOT NULL
);
"""

_lock = threading.Lock()
_pg = None  # one shared Postgres connection, reopened if the server dropped it
_ready = False


def is_postgres() -> bool:
    return bool(config.DATABASE_URL)


def _connect_pg():
    global _pg
    import psycopg

    if _pg is None or _pg.closed:
        # prepare_threshold=None: Neon's pooled endpoint (PgBouncer) can't keep prepared statements
        _pg = psycopg.connect(config.DATABASE_URL, autocommit=True, connect_timeout=15, prepare_threshold=None)
    return _pg


def _ensure_schema(run) -> None:
    global _ready
    if not _ready:
        if is_postgres():
            ddl = _SCHEMA.format(pk="BIGSERIAL PRIMARY KEY", blob="BYTEA")
        else:
            ddl = _SCHEMA.format(pk="INTEGER PRIMARY KEY", blob="BLOB")
        for statement in filter(str.strip, ddl.split(";")):
            run(statement, (), fetch=False)
        _ready = True


def _run_sqlite(sql: str, params, fetch: bool, many: bool = False):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(config.HISTORY_DB)) as conn, conn:
        cursor = conn.executemany(sql, params) if many else conn.execute(sql, params)
        return cursor.fetchall() if fetch else None


def _run_pg(sql: str, params, fetch: bool, many: bool = False):
    sql = sql.replace("?", "%s")
    for attempt in range(2):  # Neon closes idle connections; reconnect once
        try:
            with _connect_pg().cursor() as cursor:
                if many:
                    cursor.executemany(sql, params)
                else:
                    cursor.execute(sql, params)
                return cursor.fetchall() if fetch else None
        except Exception as e:
            import psycopg

            if attempt or not isinstance(e, psycopg.OperationalError):
                raise
            global _pg
            _pg = None


def _run(sql: str, params=(), fetch: bool = True, many: bool = False):
    runner = _run_pg if is_postgres() else _run_sqlite
    with _lock:
        _ensure_schema(lambda s, p, fetch: runner(s, p, fetch))
        return runner(sql, params, fetch, many)


def rows(sql: str, params=()) -> list[tuple]:
    return _run(sql, params, fetch=True)


def execute(sql: str, params=()) -> None:
    _run(sql, params, fetch=False)


def execute_many(sql: str, params: list) -> None:
    if params:
        _run(sql, params, fetch=False, many=True)


def upsert_summary_sql() -> str:
    if is_postgres():
        return ("INSERT INTO summaries (session, ts, summary) VALUES (?, ?, ?) "
                "ON CONFLICT (session) DO UPDATE SET ts = EXCLUDED.ts, summary = EXCLUDED.summary")
    return "INSERT OR REPLACE INTO summaries (session, ts, summary) VALUES (?, ?, ?)"
