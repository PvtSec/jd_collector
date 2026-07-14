"""Read-side helpers over the dashboard DB + the engine ledger.

The dashboard DB (``data/jobs.db``) is the discovery store; the engine ledger
(``data/applied.sqlite``) is the source of truth for applications. This module
bridges the two: ``mark_applied`` writes through ``engine.ledger.record`` and
flips the local ``applied`` flag, so the ledger stays honest even when the user
applies outside the bot and just marks the row here.
"""
from __future__ import annotations

import time

import engine.ledger as ledger

from .db import DB, raw_connect
from . import persist


def mark_applied(db: DB, cfg, settings, job_db_id: int) -> dict:
    """Mark a discovered job as applied: write to the engine ledger + flip local
    flag + record in the persisted state file."""
    job = db.get_job(job_db_id)
    if not job:
        return {"ok": False, "error": "job not found"}
    with ledger.connect(cfg.ledger_db) as conn:
        inserted = ledger.record(
            conn,
            company=job["company"],
            ats=job["ats"],
            job_id=job["job_id"],
            title=job["title"] or "",
            url=job["url"] or "",
            status="manual",
            mode="manual",
            note="marked applied via dashboard",
        )
    db.mark_applied(job_db_id)
    try:
        persist.record_applied(settings.abs_state_file(), job)
    except Exception:
        pass
    return {"ok": True, "inserted": inserted, "job": job}


def applied_summary(cfg) -> dict:
    """Aggregate counts from the engine ledger (mode:status -> count)."""
    try:
        with ledger.connect(cfg.ledger_db) as conn:
            return ledger.stats(conn)
    except Exception:
        # ledger may not exist yet on a fresh install
        return {}


def applied_rows(cfg, limit: int = 200) -> list[dict]:
    try:
        with raw_connect(cfg.ledger_db) as conn:
            rows = conn.execute(
                "SELECT company, ats, job_id, title, url, status, mode, note, "
                "applied_at FROM applications ORDER BY applied_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []