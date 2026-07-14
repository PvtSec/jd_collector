"""SQLite store for discovered jobs + discovery run history.

Mirrors the pattern of ``engine.ledger`` (idempotent schema, sqlite3.Row). The
dashboard's jobs DB is separate from the engine's ``applied.sqlite`` ledger,
which remains the source of truth for applications.

Schema:
  jobs(company, ats, job_id) UNIQUE — one row per discovered posting.
    first_seen  epoch the backend first saw this job ("recently found" signal)
    last_seen   epoch of the last tick that still saw it
    last_check  epoch of the last tick that enumerated its company
    matched     1 if engine.match.matches(j, target) accepted it, else 0
    applied     1 if present in the engine ledger (applied.sqlite)
  task_runs   per-task audit rows (discovery / rescan_companies)
  daily_stats per-day rollup the status bar surfaces
  discovery_cursor  round-robin offset into the automatable company list
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL,
  ats TEXT NOT NULL,
  job_id TEXT NOT NULL,
  title TEXT,
  location TEXT,
  work_type TEXT,
  url TEXT,
  posted_at TEXT,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  last_check REAL NOT NULL,
  matched INTEGER NOT NULL,
  applied INTEGER NOT NULL DEFAULT 0,
  hidden INTEGER NOT NULL DEFAULT 0,
  UNIQUE(company, ats, job_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_matched ON jobs(matched, first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);

CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL,
  status TEXT NOT NULL,
  companies_total INTEGER,
  companies_done INTEGER,
  jobs_seen INTEGER,
  jobs_new INTEGER,
  jobs_matched INTEGER,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON task_runs(started_at);

CREATE TABLE IF NOT EXISTS daily_stats (
  date TEXT PRIMARY KEY,
  runs INTEGER,
  jobs_new INTEGER,
  jobs_matched INTEGER,
  companies_enumerated INTEGER
);

CREATE TABLE IF NOT EXISTS discovery_cursor (
  id INTEGER PRIMARY KEY,
  company_idx INTEGER NOT NULL
);
"""


class DB:
    """Thread-safe wrapper around a single shared sqlite3 connection.

    The discovery job runs in a scheduler thread while FastAPI handlers run on
    the asyncio loop's threads, so every access is guarded by ``self._lock``.
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            # migrate pre-existing DBs: add the hidden column if absent
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            if "hidden" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
            # seed the singleton cursor row
            self._conn.execute(
                "INSERT OR IGNORE INTO discovery_cursor(id, company_idx) VALUES (1, 0)"
            )
            self._conn.commit()

    # ---- jobs ----
    def upsert_job(
        self,
        *,
        company: str,
        ats: str,
        job_id: str,
        title: str,
        location: str,
        work_type: str,
        url: str,
        posted_at: str,
        matched: bool,
        applied: bool = False,
    ) -> bool:
        """Insert if new (returns True) or refresh existing (returns False)."""
        now = time.time()
        matched_i = 1 if matched else 0
        applied_i = 1 if applied else 0
        with self._lock:
            existed = self._conn.execute(
                "SELECT 1 FROM jobs WHERE company=? AND ats=? AND job_id=?",
                (company, ats, job_id),
            ).fetchone()
            if existed:
                self._conn.execute(
                    """UPDATE jobs SET title=?, location=?, work_type=?, url=?, posted_at=?,
                       last_seen=?, last_check=?, matched=?, applied=? WHERE id=(
                         SELECT id FROM jobs WHERE company=? AND ats=? AND job_id=?)""",
                    (title, location, work_type, url, posted_at, now, now,
                     matched_i, applied_i, company, ats, job_id),
                )
            else:
                self._conn.execute(
                    """INSERT INTO jobs(company, ats, job_id, title, location, work_type,
                       url, posted_at, first_seen, last_seen, last_check, matched, applied)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (company, ats, job_id, title, location, work_type, url, posted_at,
                     now, now, now, matched_i, applied_i),
                )
            self._conn.commit()
        return existed is None

    def mark_applied(self, job_db_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET applied=1 WHERE id=?", (job_db_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_applied_by_key(self, *, company: str, ats: str, job_id: str) -> int:
        """Set applied=1 for a job matched by the UNIQUE (company,ats,job_id) key.
        Used by persist.reconcile_applied to restore applied flags into a fresh DB."""
        if not (company and ats and job_id):
            return 0
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET applied=1 WHERE company=? AND ats=? AND job_id=?",
                (company, ats, job_id),
            )
            self._conn.commit()
            return cur.rowcount

    def mark_hidden(self, job_db_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET hidden=1 WHERE id=?", (job_db_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_hidden_by_key(self, *, company: str, ats: str, job_id: str) -> int:
        """Restore hidden flags into a fresh DB from the persisted state file."""
        if not (company and ats and job_id):
            return 0
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET hidden=1 WHERE company=? AND ats=? AND job_id=?",
                (company, ats, job_id),
            )
            self._conn.commit()
            return cur.rowcount

    def get_job(self, job_db_id: int):
        with self._lock:
            r = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_db_id,)).fetchone()
            return dict(r) if r else None

    def purge_non_ats(self, ats_whitelist: list[str]) -> int:
        """Delete jobs whose ``ats`` is not a real ATS (e.g. 'unknown'/'custom'
        third-party-scraped career-page links that 404). The engine enumerators
        only ever emit real ATS rows; the only source of non-ATS rows is the
        topstartups seed. Returns the number of rows deleted."""
        if not ats_whitelist:
            return 0
        placeholders = ",".join("?" for _ in ats_whitelist)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM jobs WHERE ats NOT IN ({placeholders})",
                list(ats_whitelist),
            )
            self._conn.commit()
            return cur.rowcount

    def list_jobs(
        self,
        *,
        q: str | None = None,
        ats: str | None = None,
        matched_only: bool = False,
        applied_only: bool | None = None,
        recent_seconds: float | None = None,
        sort: str = "recent",
        limit: int = 200,
        offset: int = 0,
        include_hidden: bool = False,
    ) -> tuple[list[dict], int]:
        sql = "SELECT * FROM jobs WHERE 1=1"
        args: list = []
        if not include_hidden:
            sql += " AND hidden=0"
        if q:
            sql += " AND (LOWER(company) LIKE ? OR LOWER(title) LIKE ? OR LOWER(location) LIKE ?)"
            p = f"%{q.lower()}%"
            args += [p, p, p]
        if ats:
            sql += " AND ats=?"; args.append(ats)
        if matched_only:
            sql += " AND matched=1"
        if applied_only is True:
            sql += " AND applied=1"
        elif applied_only is False:
            sql += " AND applied=0"
        if recent_seconds is not None:
            sql += " AND first_seen >= ?"; args.append(time.time() - recent_seconds)
        order = {
            "recent": "first_seen DESC",
            "company": "company ASC, first_seen DESC",
            "matched": "matched DESC, first_seen DESC",
        }.get(sort, "first_seen DESC")
        # count first (clone without ORDER/LIMIT)
        count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
        with self._lock:
            total = self._conn.execute(count_sql, args).fetchone()[0]
            rows = self._conn.execute(
                f"{sql} ORDER BY {order} LIMIT ? OFFSET ?",
                args + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def count_jobs(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def stats(self) -> dict:
        now = time.time()
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            matched = self._conn.execute("SELECT COUNT(*) FROM jobs WHERE matched=1").fetchone()[0]
            applied = self._conn.execute("SELECT COUNT(*) FROM jobs WHERE applied=1").fetchone()[0]
            last24 = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE first_seen >= ?", (now - 86400,)
            ).fetchone()[0]
            matched24 = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE matched=1 AND first_seen >= ?", (now - 86400,)
            ).fetchone()[0]
            by_ats = {
                r[0]: r[1]
                for r in self._conn.execute(
                    "SELECT ats, COUNT(*) FROM jobs GROUP BY ats ORDER BY COUNT(*) DESC"
                )
            }
        return {
            "total": total,
            "matched": matched,
            "applied": applied,
            "last_24h": last24,
            "matched_24h": matched24,
            "by_ats": by_ats,
        }

    def distinct_ats(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute(
                "SELECT DISTINCT ats FROM jobs WHERE ats IS NOT NULL ORDER BY ats")]

    # ---- task_runs ----
    def start_run(self, kind: str) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO task_runs(kind, started_at, status, companies_total, "
                "companies_done, jobs_seen, jobs_new, jobs_matched) "
                "VALUES (?,?,'running',0,0,0,0,0)",
                (kind, now),
            )
            self._conn.commit()
            return cur.lastrowid

    def update_run(self, run_id: int, *, companies_total: int, companies_done: int,
                   jobs_seen: int, jobs_new: int, jobs_matched: int):
        with self._lock:
            self._conn.execute(
                "UPDATE task_runs SET companies_total=?, companies_done=?, jobs_seen=?, "
                "jobs_new=?, jobs_matched=? WHERE id=?",
                (companies_total, companies_done, jobs_seen, jobs_new, jobs_matched, run_id),
            )
            self._conn.commit()

    def finish_run(self, run_id: int, status: str, error: str = ""):
        with self._lock:
            self._conn.execute(
                "UPDATE task_runs SET ended_at=?, status=?, error=? WHERE id=?",
                (time.time(), status, error, run_id),
            )
            self._conn.commit()

    def last_run(self):
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM task_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            return dict(r) if r else None

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM task_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def runs_by_day(self, days: int = 14) -> list[dict]:
        cutoff = time.time() - days * 86400
        with self._lock:
            rows = self._conn.execute(
                """SELECT date(started_at,'unixepoch') AS day,
                          COUNT(*) AS runs, COALESCE(SUM(jobs_new),0) AS jobs_new,
                          COALESCE(SUM(jobs_matched),0) AS jobs_matched,
                          COALESCE(SUM(companies_done),0) AS companies_enumerated,
                          MAX(started_at) AS last_ts
                   FROM task_runs WHERE started_at >= ? AND status IN ('success','failed')
                   GROUP BY day ORDER BY day DESC""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def bump_daily(self, *, jobs_new: int, jobs_matched: int, companies_enumerated: int):
        import datetime as _dt
        day = _dt.date.today().isoformat()
        with self._lock:
            self._conn.execute(
                """INSERT INTO daily_stats(date, runs, jobs_new, jobs_matched, companies_enumerated)
                   VALUES (?, 1, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     runs=daily_stats.runs+1,
                     jobs_new=daily_stats.jobs_new+excluded.jobs_new,
                     jobs_matched=daily_stats.jobs_matched+excluded.jobs_matched,
                     companies_enumerated=daily_stats.companies_enumerated+excluded.companies_enumerated""",
                (day, jobs_new, jobs_matched, companies_enumerated),
            )
            self._conn.commit()

    def daily_stats(self, days: int = 14) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- cursor ----
    def get_cursor(self) -> int:
        with self._lock:
            r = self._conn.execute(
                "SELECT company_idx FROM discovery_cursor WHERE id=1"
            ).fetchone()
            return r[0] if r else 0

    def set_cursor(self, idx: int):
        with self._lock:
            self._conn.execute(
                "UPDATE discovery_cursor SET company_idx=? WHERE id=1", (idx,)
            )
            self._conn.commit()


@contextmanager
def raw_connect(path: str):
    """Plain connection for one-off callers (e.g. reading the engine ledger)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()