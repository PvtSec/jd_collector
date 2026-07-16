"""Persisted plain-file state for the dashboard.

A single human-readable JSON file (default ``app/state.json``) that survives
restarts and even a SQLite wipe. It holds two things the user asked to persist:

  1. ``applied`` — jobs marked applied via the dashboard (deduped by
     company/ats/job_id). This is a mirror of the engine ledger's
     dashboard-marked rows, kept here so the applied state can be restored into
     a fresh ``jobs.db``.
  2. ``scans`` — a rolling log of recent discovery scans, each with its newly-
     found jobs (capped: last ``MAX_SCANS`` scans, ``MAX_NEW_PER_SCAN`` jobs each).

The engine ledger (``data/applied.sqlite``) and the dashboard DB
(``data/jobs.db``) remain the live stores; this file is an inspectable,
portable, restart-proof companion written on every mark-applied and every
completed scan tick.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MAX_SCANS = 30          # keep the last N scan summaries in the file
MAX_NEW_PER_SCAN = 200  # cap new-job entries recorded per scan

_lock = threading.Lock()


def _read(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {"updated_at": 0.0, "applied": [], "scans": []}


def _write(path: str, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _applied_key(rec: dict) -> tuple:
    return (rec.get("company", ""), rec.get("ats", ""), rec.get("job_id", ""))


def record_applied(state_path: str, job: dict) -> None:
    """Append/refresh a dashboard-marked-applied job in the persisted file."""
    with _lock:
        state = _read(state_path)
        applied = state.get("applied", [])
        key = _applied_key(job)
        # dedupe: replace if present, else append
        applied = [a for a in applied if _applied_key(a) != key]
        rec = {
            "company": job.get("company", ""),
            "ats": job.get("ats", ""),
            "job_id": job.get("job_id", ""),
            "title": job.get("title", ""),
            "url": job.get("url", ""),
            "applied_at": time.time(),
            "source": "dashboard",
        }
        applied.append(rec)
        state["applied"] = applied
        state["updated_at"] = time.time()
        _write(state_path, state)


def record_hidden(state_path: str, job: dict) -> None:
    """Record a user-hidden (dead) job so it stays hidden across restarts / DB wipes."""
    with _lock:
        state = _read(state_path)
        hidden = state.get("hidden", [])
        key = _applied_key(job)
        if not any(_applied_key(h) == key for h in hidden):
            hidden.append({
                "company": job.get("company", ""),
                "ats": job.get("ats", ""),
                "job_id": job.get("job_id", ""),
                "url": job.get("url", ""),
                "hidden_at": time.time(),
            })
            state["hidden"] = hidden
            state["updated_at"] = time.time()
            _write(state_path, state)


def reconcile_hidden(state_path: str, db) -> int:
    """Restore hidden flags into a (possibly fresh) jobs DB from the persisted file."""
    state = _read(state_path)
    n = 0
    for rec in state.get("hidden", []):
        n += db.mark_hidden_by_key(
            company=rec.get("company", ""),
            ats=rec.get("ats", ""),
            job_id=rec.get("job_id", ""),
        )
    return n


def record_scan(state_path: str, run_summary: dict, new_jobs: list[dict]) -> None:
    """Record a completed discovery scan + its newly-found jobs (capped)."""
    with _lock:
        state = _read(state_path)
        scans = state.get("scans", [])
        capped = new_jobs[:MAX_NEW_PER_SCAN]
        entry = {
            "run_id": run_summary.get("run_id"),
            "kind": run_summary.get("kind", "discovery"),
            "started_at": run_summary.get("started_at"),
            "ended_at": run_summary.get("ended_at", time.time()),
            "status": run_summary.get("status", "success"),
            "companies_done": run_summary.get("companies_done", 0),
            "companies_total": run_summary.get("companies_total", 0),
            "jobs_seen": run_summary.get("jobs_seen", 0),
            "jobs_new": run_summary.get("jobs_new", 0),
            "jobs_matched": run_summary.get("jobs_matched", 0),
            "jobs_closed": run_summary.get("jobs_closed", 0),
            "new_jobs": capped,
            "new_jobs_total": len(new_jobs),  # true count (capped list may be shorter)
        }
        scans.append(entry)
        scans = scans[-MAX_SCANS:]
        state["scans"] = scans
        state["updated_at"] = time.time()
        _write(state_path, state)


def reconcile_applied(state_path: str, db) -> int:
    """On startup, restore applied flags into a (possibly fresh) jobs DB.

    Returns the number of rows flipped to applied=1.
    """
    state = _read(state_path)
    applied = state.get("applied", [])
    n = 0
    for rec in applied:
        n += db.mark_applied_by_key(
            company=rec.get("company", ""),
            ats=rec.get("ats", ""),
            job_id=rec.get("job_id", ""),
        )
    return n


def reconcile_applied_from_ledger(ledger_db: str, db) -> int:
    """On startup, restore applied flags from the authoritative ledger
    (applied.sqlite) into the jobs DB.

    The jobs DB ``applied`` column is a denormalised cache that is refreshed on
    each enumeration via ``ledger.already_applied``. If a tick's ledger lookup
    ever misses (transient open failure / name drift), the cache flag can flip
    back to 0 even though the application is still recorded in the ledger. The
    ledger is the source of truth, so on every startup we re-stamp applied=1
    for every job present in it. Only flips 0->1; never clears an applied flag.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(ledger_db)
    except Exception:
        return 0
    n = 0
    try:
        for company, ats, job_id in conn.execute(
            "SELECT company, ats, job_id FROM applications"
        ).fetchall():
            n += db.mark_applied_by_key(company=company, ats=ats, job_id=str(job_id))
    finally:
        conn.close()
    return n


def load(state_path: str) -> dict:
    """Read-only access to the persisted state (for /api/state)."""
    return _read(state_path)