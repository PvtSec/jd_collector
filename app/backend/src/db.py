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
  closed INTEGER NOT NULL DEFAULT 0,
  closed_at REAL,
  miss_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(company, ats, job_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_matched ON jobs(matched, first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_company_ats ON jobs(company, ats);
-- Covering indexes for /api/jobs list + count. The default view is
-- matched=1 AND closed=0 AND hidden=0 ORDER BY first_seen DESC — these make the
-- COUNT(*) (the expensive part, ~0.3-2.5s on 900k rows without them) index-only,
-- and the matched+open text search (q LIKE) an index-only scan over the ~5k
-- matched partition instead of a 900k-row table scan.
-- Covering indexes for /api/jobs list + count.
-- idx_jobs_open (closed, hidden, matched): covers the COUNTs (equality on
-- closed/hidden/matched) index-only. first_seen is intentionally NOT included
-- so this index can't serve ORDER BY first_seen — that routes the all-open
-- SELECT to idx_jobs_open_first (no 800k-row sort).
DROP INDEX IF EXISTS idx_jobs_open;
DROP INDEX IF EXISTS idx_jobs_open_fs;
CREATE INDEX IF NOT EXISTS idx_jobs_open
  ON jobs(closed, hidden, matched);
-- idx_jobs_open_first (closed, hidden, first_seen): the "all open jobs" view
-- (matched OFF) — the planner walks it in first_seen order for
-- ORDER BY first_seen DESC LIMIT n (no sort, early stop).
CREATE INDEX IF NOT EXISTS idx_jobs_open_first
  ON jobs(closed, hidden, first_seen);
-- partial covering index for the default matched+open view: covers the q LIKE
-- search AND the ats_exclude (NOT IN) filter as an index-only scan over the
-- ~5k matched partition. DROP+recreate on each init is cheap (5k rows) and lets
-- us evolve the column set without a separate migration.
DROP INDEX IF EXISTS idx_jobs_matched_search;
CREATE INDEX IF NOT EXISTS idx_jobs_matched_search
  ON jobs(ats, company, title, location, first_seen)
  WHERE matched=1 AND closed=0 AND hidden=0;

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
  company_idx INTEGER NOT NULL,
  sweep_id INTEGER NOT NULL DEFAULT 1,
  sweep_started_at REAL NOT NULL DEFAULT 0,
  sweep_total INTEGER NOT NULL DEFAULT 0,
  sweep_jobs_new INTEGER NOT NULL DEFAULT 0,
  sweep_jobs_matched INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dead_boards (
  company_key TEXT PRIMARY KEY,
  ats TEXT NOT NULL,
  consecutive_failures INTEGER NOT NULL DEFAULT 1,
  first_dead_at REAL NOT NULL,
  last_checked_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dead_last ON dead_boards(last_checked_at);

CREATE TABLE IF NOT EXISTS skill_demand (
  skill TEXT PRIMARY KEY,
  category TEXT,
  count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_skills (
  job_id INTEGER NOT NULL,
  skill TEXT NOT NULL,
  PRIMARY KEY(job_id, skill)
);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill ON job_skills(skill);
"""


class DB:

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        self._read_lock = threading.Lock()
        self._read_conn = sqlite3.connect(path, check_same_thread=False)
        self._read_conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            if "hidden" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
            if "closed" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN closed INTEGER NOT NULL DEFAULT 0")
            if "closed_at" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN closed_at REAL")
            if "miss_count" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN miss_count INTEGER NOT NULL DEFAULT 0")
            if "skills_counted" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN skills_counted INTEGER NOT NULL DEFAULT 0")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_closed ON jobs(closed)"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO discovery_cursor(id, company_idx) VALUES (1, 0)"
            )
            dcols = {r[1] for r in self._conn.execute("PRAGMA table_info(discovery_cursor)")}
            for col, decl in [
                ("sweep_id", "INTEGER NOT NULL DEFAULT 1"),
                ("sweep_started_at", "REAL NOT NULL DEFAULT 0"),
                ("sweep_total", "INTEGER NOT NULL DEFAULT 0"),
                ("sweep_jobs_new", "INTEGER NOT NULL DEFAULT 0"),
                ("sweep_jobs_matched", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                if col not in dcols:
                    self._conn.execute(
                        f"ALTER TABLE discovery_cursor ADD COLUMN {col} {decl}"
                    )
            self._conn.execute(
                "UPDATE discovery_cursor SET sweep_started_at=? "
                "WHERE id=1 AND sweep_started_at=0",
                (time.time(),),
            )
            self._conn.execute(
                "UPDATE task_runs SET status='failed', ended_at=?, "
                "error=COALESCE(error,'') || ' [process restarted]' "
                "WHERE status='running'",
                (time.time(),),
            )
            self._conn.commit()
            _analyzed_marker = os.path.join(
                os.path.dirname(os.path.abspath(self.path)) or ".", ".db_analyzed_v6")
            if not os.path.exists(_analyzed_marker):
                try:
                    self._conn.execute("ANALYZE")
                    self._conn.commit()
                    open(_analyzed_marker, "w").close()
                except Exception:
                    pass

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
                       last_seen=?, last_check=?, matched=?, applied=MAX(applied, ?),
                       miss_count=0, closed=0, closed_at=NULL WHERE id=(
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

    def count_skills_once(self, *, company: str, ats: str, job_id: str, skills) -> None:
        if not skills:
            return
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM jobs WHERE company=? AND ats=? AND job_id=? AND skills_counted=0",
                (company, ats, job_id),
            ).fetchone()
            if not row:
                return
            jid = row[0]
            self._conn.execute("UPDATE jobs SET skills_counted=1 WHERE id=?", (jid,))
            for display, category in skills:
                self._conn.execute(
                    "INSERT INTO skill_demand(skill, category, count) VALUES(?,?,1) "
                    "ON CONFLICT(skill) DO UPDATE SET count=count+1",
                    (display, category),
                )
                self._conn.execute(
                    "INSERT OR IGNORE INTO job_skills(job_id, skill) VALUES(?,?)",
                    (jid, display),
                )
            self._conn.commit()

    def skill_demand(self, limit: int = 200) -> dict:
        with self._read_lock:
            analyzed = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE skills_counted=1"
            ).fetchone()[0]
            rows = self._read_conn.execute(
                "SELECT skill, category, count FROM skill_demand "
                "ORDER BY count DESC, skill ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return {
            "analyzed": analyzed,
            "rows": [{"skill": r[0], "category": r[1], "count": r[2]} for r in rows],
        }

    def mark_applied(self, job_db_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET applied=1 WHERE id=?", (job_db_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_applied_by_key(self, *, company: str, ats: str, job_id: str) -> int:
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
        with self._read_lock:
            r = self._read_conn.execute("SELECT * FROM jobs WHERE id=?", (job_db_id,)).fetchone()
            return dict(r) if r else None

    def purge_non_ats(self, ats_whitelist: list[str]) -> int:
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

    def reap_company(self, *, company: str, ats: str,
                     fresh_job_ids: set[str], grace: int) -> dict:
        if not fresh_job_ids:
            return {"absent": 0, "closed_now": 0}
        now = time.time()
        placeholders = ",".join("?" for _ in fresh_job_ids)
        fresh = list(fresh_job_ids)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE jobs SET miss_count = miss_count + 1 "
                f"WHERE company=? AND ats=? AND applied=0 "
                f"AND job_id NOT IN ({placeholders})",
                [company, ats, *fresh],
            )
            absent = cur.rowcount
            cur = self._conn.execute(
                "UPDATE jobs SET closed=1, closed_at=? "
                "WHERE company=? AND ats=? AND applied=0 AND closed=0 "
                "AND miss_count >= ?",
                (now, company, ats, grace),
            )
            closed_now = cur.rowcount
            self._conn.commit()
        return {"absent": absent, "closed_now": closed_now}

    def list_jobs(
        self,
        *,
        q: str | None = None,
        ats: str | list[str] | None = None,
        matched_only: bool = False,
        applied_only: bool | None = None,
        recent_seconds: float | None = None,
        sort: str = "recent",
        limit: int = 200,
        offset: int = 0,
        include_hidden: bool = False,
        closed: str = "exclude",
        skill: str | None = None,
    ) -> tuple[list[dict], int]:
        sql = "SELECT * FROM jobs WHERE 1=1"
        args: list = []
        if not include_hidden:
            sql += " AND hidden=0"
        if closed == "only":
            sql += " AND closed=1"
        elif closed != "any":
            sql += " AND closed=0"
        if q:
            sql += " AND (LOWER(company) LIKE ? OR LOWER(title) LIKE ? OR LOWER(location) LIKE ?)"
            p = f"%{q.lower()}%"
            args += [p, p, p]
        if ats:
            ats_list = [ats] if isinstance(ats, str) else [a for a in ats if a]
            if ats_list:
                placeholders = ",".join("?" for _ in ats_list)
                sql += f" AND ats NOT IN ({placeholders})"
                args += ats_list
        if matched_only:
            sql += " AND matched=1"
        if applied_only is True:
            sql += " AND applied=1"
        elif applied_only is False:
            sql += " AND applied=0"
        if recent_seconds is not None:
            sql += " AND first_seen >= ?"; args.append(time.time() - recent_seconds)
        if skill:
            sql += " AND id IN (SELECT job_id FROM job_skills WHERE skill=?)"
            args.append(skill)
        order = {
            "recent": "first_seen DESC",
            "company": "company ASC, first_seen DESC",
            "matched": "matched DESC, first_seen DESC",
        }.get(sort, "first_seen DESC")
        count_sql = sql.replace("SELECT *", "SELECT COUNT(*)", 1)
        with self._read_lock:
            total = self._read_conn.execute(count_sql, args).fetchone()[0]
            rows = self._read_conn.execute(
                f"{sql} ORDER BY {order} LIMIT ? OFFSET ?",
                args + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], total

    def count_jobs(self) -> int:
        with self._read_lock:
            return self._read_conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def stats(self) -> dict:
        now = time.time()
        with self._read_lock:
            total = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE closed=0").fetchone()[0]
            matched = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE matched=1 AND closed=0").fetchone()[0]
            applied = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE applied=1 AND closed=0").fetchone()[0]
            closed = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE closed=1").fetchone()[0]
            last24 = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE first_seen >= ? AND closed=0", (now - 86400,)
            ).fetchone()[0]
            matched24 = self._read_conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE matched=1 AND first_seen >= ? AND closed=0",
                (now - 86400,)
            ).fetchone()[0]
            by_ats = {
                r[0]: r[1]
                for r in self._read_conn.execute(
                    "SELECT ats, COUNT(*) FROM jobs WHERE closed=0 GROUP BY ats ORDER BY COUNT(*) DESC"
                )
            }
        return {
            "total": total,
            "matched": matched,
            "applied": applied,
            "closed": closed,
            "last_24h": last24,
            "matched_24h": matched24,
            "by_ats": by_ats,
        }

    def distinct_ats(self) -> list[str]:
        with self._read_lock:
            return [r[0] for r in self._read_conn.execute(
                "SELECT DISTINCT ats FROM jobs WHERE ats IS NOT NULL ORDER BY ats")]

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
        with self._read_lock:
            r = self._read_conn.execute(
                "SELECT * FROM task_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            return dict(r) if r else None

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._read_lock:
            rows = self._read_conn.execute(
                "SELECT * FROM task_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def runs_by_day(self, days: int = 14) -> list[dict]:
        cutoff = time.time() - days * 86400
        with self._read_lock:
            rows = self._read_conn.execute(
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
        with self._read_lock:
            rows = self._read_conn.execute(
                "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_cursor(self) -> int:
        with self._read_lock:
            r = self._read_conn.execute(
                "SELECT company_idx FROM discovery_cursor WHERE id=1"
            ).fetchone()
            return r[0] if r else 0

    def set_cursor(self, idx: int):
        with self._lock:
            self._conn.execute(
                "UPDATE discovery_cursor SET company_idx=? WHERE id=1", (idx,)
            )
            self._conn.commit()

    def get_sweep(self) -> dict:
        with self._read_lock:
            r = self._read_conn.execute(
                "SELECT company_idx, sweep_id, sweep_started_at, sweep_total, "
                "sweep_jobs_new, sweep_jobs_matched FROM discovery_cursor WHERE id=1"
            ).fetchone()
        if not r:
            return {"cursor": 0, "sweep_id": 1, "sweep_started_at": 0,
                    "sweep_total": 0, "sweep_covered": 0,
                    "sweep_jobs_new": 0, "sweep_jobs_matched": 0}
        cursor, sid, started, total, jn, jm = r
        return {
            "cursor": cursor,
            "sweep_id": sid,
            "sweep_started_at": started,
            "sweep_total": total,
            "sweep_covered": cursor,
            "sweep_jobs_new": jn,
            "sweep_jobs_matched": jm,
        }

    def advance_sweep(self, *, new_cursor: int, wrapped: bool, total: int,
                      jobs_new: int, jobs_matched: int) -> dict:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT sweep_id, sweep_jobs_new, sweep_jobs_matched "
                "FROM discovery_cursor WHERE id=1"
            ).fetchone()
            old_id, old_jn, old_jm = (row[0], row[1], row[2]) if row else (1, 0, 0)
            if wrapped:
                completed = {"completed": True, "sweep_id": old_id,
                              "jobs_new": old_jn + jobs_new,
                              "jobs_matched": old_jm + jobs_matched}
                self._conn.execute(
                    "UPDATE discovery_cursor SET company_idx=?, sweep_id=sweep_id+1, "
                    "sweep_started_at=?, sweep_total=?, sweep_jobs_new=?, "
                    "sweep_jobs_matched=? WHERE id=1",
                    (new_cursor, now, total, jobs_new, jobs_matched),
                )
                self._conn.commit()
                return completed
            self._conn.execute(
                "UPDATE discovery_cursor SET company_idx=?, sweep_total=?, "
                "sweep_jobs_new=sweep_jobs_new+?, sweep_jobs_matched=sweep_jobs_matched+? "
                "WHERE id=1",
                (new_cursor, total, jobs_new, jobs_matched),
            )
            self._conn.execute(
                "UPDATE discovery_cursor SET sweep_started_at=? "
                "WHERE id=1 AND sweep_started_at=0",
                (now,),
            )
            self._conn.commit()
            return {"completed": False}

    def dead_keys(self, *, threshold: int, cooldown_seconds: float) -> set[str]:
        cutoff = time.time() - cooldown_seconds
        with self._read_lock:
            rows = self._read_conn.execute(
                "SELECT company_key FROM dead_boards "
                "WHERE consecutive_failures >= ? AND last_checked_at > ?",
                (threshold, cutoff),
            ).fetchall()
        return {r[0] for r in rows}

    def update_dead(self, *, alive_keys: list[str], dead_pairs: list[tuple[str, str]]):
        now = time.time()
        with self._lock:
            if alive_keys:
                self._conn.executemany(
                    "DELETE FROM dead_boards WHERE company_key=?",
                    [(k,) for k in alive_keys],
                )
            if dead_pairs:
                self._conn.executemany(
                    "INSERT INTO dead_boards(company_key, ats, consecutive_failures, "
                    "first_dead_at, last_checked_at) "
                    "VALUES(?, ?, 1, ?, ?) "
                    "ON CONFLICT(company_key) DO UPDATE SET "
                    "consecutive_failures = consecutive_failures + 1, "
                    "last_checked_at = excluded.last_checked_at",
                    [(k, a, now, now) for k, a in dead_pairs],
                )
            self._conn.commit()

    def dead_board_count(self) -> int:
        with self._read_lock:
            return self._read_conn.execute("SELECT COUNT(*) FROM dead_boards").fetchone()[0]


@contextmanager
def raw_connect(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()