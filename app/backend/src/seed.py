from __future__ import annotations

import json
import os
import tempfile
import time

SEED_VERSION = 1

# columns persisted per job row (everything except the autoincrement id)
_COLS = (
    "company", "ats", "job_id", "title", "location", "work_type", "url",
    "posted_at", "first_seen", "last_seen", "last_check", "matched", "applied",
    "hidden", "closed", "closed_at", "miss_count",
)
_INT_COLS = {"matched", "applied", "hidden", "closed", "miss_count"}


def export_seed(db, path: str, max_rows: int) -> dict:
    cols_csv = ",".join(_COLS)
    with db._lock:
        if max_rows and int(max_rows) > 0:
            rows = db._conn.execute(
                f"SELECT {cols_csv} FROM jobs ORDER BY last_seen DESC LIMIT ?",
                (int(max_rows),),
            ).fetchall()
        else:
            # no cap — export every row (most-recently-seen first)
            rows = db._conn.execute(
                f"SELECT {cols_csv} FROM jobs ORDER BY last_seen DESC"
            ).fetchall()
    jobs = []
    for r in rows:
        d = {}
        for c in _COLS:
            v = r[c]
            if c in _INT_COLS and v is not None:
                v = int(v)
            d[c] = v
        jobs.append(d)
    payload = {
        "version": SEED_VERSION,
        "exported_at": time.time(),
        "count": len(jobs),
        "jobs": jobs,
    }
    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"exported": len(jobs), "path": path}


def import_seed(db, path: str) -> int:
    # Uses INSERT OR IGNORE so it is safe even if the DB is not fully empty.
    if not path or not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    jobs = payload.get("jobs") if isinstance(payload, dict) else payload
    if not jobs:
        return 0
    cols_csv = ",".join(_COLS)
    placeholders = ",".join("?" for _ in _COLS)
    rows = [tuple(j.get(c) for c in _COLS) for j in jobs]
    with db._lock:
        before = db._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        db._conn.executemany(
            f"INSERT OR IGNORE INTO jobs ({cols_csv}) VALUES ({placeholders})",
            rows,
        )
        db._conn.commit()
        after = db._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return after - before