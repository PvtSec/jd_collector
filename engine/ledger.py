"""Applied-jobs ledger — SQLite store of every application (and dry-run match).

Prevents duplicate submissions and gives a history. Read/written by the engine;
safe to inspect manually with `sqlite3 data/applied.sqlite`.
"""
from __future__ import annotations
import os
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    ats TEXT NOT NULL,
    job_id TEXT NOT NULL,
    title TEXT,
    url TEXT,
    status TEXT NOT NULL,          -- matched | submitted | skipped | failed
    mode TEXT NOT NULL,            -- dry_run | live
    note TEXT,
    applied_at REAL NOT NULL,
    UNIQUE(company, ats, job_id)
);
CREATE INDEX IF NOT EXISTS idx_status ON applications(status);
"""


@contextmanager
def connect(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def already_applied(conn: sqlite3.Connection, company: str, ats: str, job_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM applications WHERE company=? AND ats=? AND job_id=?",
        (company, ats, job_id),
    ).fetchone()
    return row is not None


def record(
    conn: sqlite3.Connection,
    *,
    company: str,
    ats: str,
    job_id: str,
    title: str = "",
    url: str = "",
    status: str = "matched",
    mode: str = "dry_run",
    note: str = "",
) -> bool:
    """Insert a row. Returns True if inserted, False if it was a duplicate."""
    try:
        conn.execute(
            "INSERT INTO applications(company,ats,job_id,title,url,status,mode,note,applied_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (company, ats, job_id, title, url, status, mode, note, time.time()),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, mode, COUNT(*) c FROM applications GROUP BY status, mode"
    ).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        out[f"{r['mode']}:{r['status']}"] = r["c"]
    return out