from __future__ import annotations

import time
import traceback

import engine.ledger as ledger
from engine.boards import CLIENTS, BoardError
from engine.config import Config
from engine.match import matches

from .companies import companies_filtered
from .db import DB
from .settings import AppSettings
from .tasks import TaskManager

# ATS whose enumeration is known to be complete (fully paginated). The stale-job
# reaper only runs for these — capped/scrape enumerators (workable 10/page,
# workday 500/board, breezyhr/onlyfy DOM scrape, mailto href scrape) can return
# partial lists and would false-close jobs that are actually still on the board.
REAPER_ATS = {
    "greenhouse", "lever", "ashby", "smartrecruiters",
    "personio", "rippling", "teamtailor",
}


def _rotate_slice(items: list[dict], cursor: int, size: int) -> list[dict]:
    n = len(items)
    if n == 0:
        return []
    size = min(size, n)
    idx = cursor % n
    if idx + size <= n:
        return items[idx:idx + size]
    return items[idx:] + items[: (idx + size) - n]


def run_tick(settings: AppSettings, task_manager: TaskManager, cfg: Config | None = None
             ) -> dict:
    cfg = cfg or Config.load(settings.abs_engine_config())
    db: DB = task_manager.db

    comps = companies_filtered(cfg, ats=None)
    if not comps:
        task_manager.begin("discovery", companies_total=0)
        task_manager.finish("success", "no automatable companies found")
        return {"jobs_new": 0, "jobs_seen": 0, "jobs_matched": 0,
                "jobs_closed": 0, "companies_done": 0}

    cursor = db.get_cursor()
    slice_ = _rotate_slice(comps, cursor, settings.rotate_size)
    new_cursor = (cursor + len(slice_)) % len(comps)
    db.set_cursor(new_cursor)

    run_id = task_manager.begin("discovery", companies_total=len(slice_))

    jobs_seen = jobs_new = jobs_matched = companies_done = jobs_closed = 0
    new_jobs: list[dict] = []  # newly-discovered job rows, persisted to app/state.json
    # One ledger connection for the whole tick (applied-status lookups).
    try:
        ledger_conn = ledger.connect(cfg.ledger_db).__enter__()
    except Exception:
        ledger_conn = None

    try:
        for i, c in enumerate(slice_):
            ats = c["ats_type"]
            company = c["company_name"]
            token = c["board_token"]
            try:
                jobs = list(CLIENTS[ats](
                    company, token,
                    ua=cfg.user_agent, timeout=cfg.http_timeout, retries=cfg.http_retries,
                ))
            except BoardError as e:
                # one dead board doesn't kill the tick
                continue
            except Exception:
                # unexpected per-company error: log via progress and move on
                continue

            for j in jobs:
                jobs_seen += 1
                ok, _reasons = matches(j, cfg.target)
                if ok:
                    jobs_matched += 1
                applied = False
                if ledger_conn is not None:
                    try:
                        applied = ledger.already_applied(ledger_conn, j.company, j.ats, j.job_id)
                    except Exception:
                        applied = False
                is_new = db.upsert_job(
                    company=j.company, ats=j.ats, job_id=j.job_id,
                    title=j.title, location=j.location, work_type=j.work_type,
                    url=j.url, posted_at=j.posted_at, matched=ok, applied=applied,
                )
                if is_new:
                    jobs_new += 1
                    new_jobs.append({
                        "company": j.company, "ats": j.ats, "job_id": j.job_id,
                        "title": j.title, "location": j.location,
                        "work_type": j.work_type, "url": j.url,
                        "posted_at": j.posted_at, "matched": ok,
                        "first_seen": time.time(),
                    })

            # stale-job reaper: for fully-paginated ATS, mark previously-seen jobs
            # that are absent from this fresh enumeration. Applied jobs are exempt.
            if ats in REAPER_ATS:
                try:
                    reaped = db.reap_company(
                        company=company, ats=ats,
                        fresh_job_ids={j.job_id for j in jobs},
                        grace=settings.stale_grace_misses,
                    )
                    jobs_closed += reaped["closed_now"]
                except Exception:
                    # reaper failure must never kill the tick
                    pass

            companies_done += 1
            if (i + 1) % 5 == 0 or i == len(slice_) - 1:
                task_manager.progress(
                    companies_done=companies_done,
                    companies_total=len(slice_),
                    jobs_seen=jobs_seen,
                    jobs_new=jobs_new,
                    jobs_matched=jobs_matched,
                    jobs_closed=jobs_closed,
                    progress=f"enumerated {companies_done}/{len(slice_)} companies",
                )
                db.update_run(run_id, companies_total=len(slice_),
                              companies_done=companies_done, jobs_seen=jobs_seen,
                              jobs_new=jobs_new, jobs_matched=jobs_matched)

        db.update_run(run_id, companies_total=len(slice_), companies_done=companies_done,
                      jobs_seen=jobs_seen, jobs_new=jobs_new, jobs_matched=jobs_matched)
        db.bump_daily(jobs_new=jobs_new, jobs_matched=jobs_matched,
                      companies_enumerated=companies_done)
        # persist this scan + its newly-found jobs to app/state.json
        try:
            from . import persist
            cur = task_manager.current()
            run_summary = {
                "run_id": cur.get("run_id"),
                "kind": "discovery",
                "started_at": cur.get("started_at"),
                "ended_at": time.time(),
                "status": "success",
                "companies_done": companies_done,
                "companies_total": len(slice_),
                "jobs_seen": jobs_seen,
                "jobs_new": jobs_new,
                "jobs_matched": jobs_matched,
                "jobs_closed": jobs_closed,
            }
            persist.record_scan(settings.abs_state_file(), run_summary, new_jobs)
        except Exception:
            pass
        task_manager.finish("success")
        return {
            "jobs_new": jobs_new, "jobs_seen": jobs_seen,
            "jobs_matched": jobs_matched, "jobs_closed": jobs_closed,
            "companies_done": companies_done, "companies_total": len(slice_),
        }
    except Exception as e:
        task_manager.finish("failed", f"{e}\n{traceback.format_exc()[-400:]}")
        return {"jobs_new": jobs_new, "jobs_seen": jobs_seen,
                "jobs_matched": jobs_matched, "jobs_closed": jobs_closed,
                "companies_done": companies_done, "error": str(e)}
    finally:
        if ledger_conn is not None:
            try:
                ledger_conn.close()
            except Exception:
                pass


def run_rescan(settings: AppSettings, task_manager: TaskManager, cfg: Config | None = None,
               kind: str = "rescan_companies") -> dict:
    import subprocess
    import sys

    task_manager.begin(kind, companies_total=len(settings.rescan_commands))
    py = sys.executable
    done = 0
    err = ""
    try:
        # cwd = repo root (where scripts/ + data/ live)
        cwd = settings.abs_engine_config().rsplit("/", 1)[0] if "/" in settings.engine_config else None
        per_cmd_errors = []
        for i, cmd in enumerate(settings.rescan_commands):
            argv = cmd.replace("{python}", py).split()
            task_manager.progress(companies_done=i, progress=f"running {argv[-1]}")
            # per-script timeout override (e.g. tighter caps on the slow himalayas/slugs
            # steps so the rescan — which blocks the 5-min tick — doesn't stall the
            # dashboard for an hour); falls back to the global rescan_step_timeout.
            import os as _os
            step_timeout = (settings.rescan_step_timeouts or {}).get(
                _os.path.basename(argv[-1]), getattr(settings, "rescan_step_timeout", 1200))
            try:
                subprocess.run(argv, check=False, cwd=cwd,
                               capture_output=True, timeout=step_timeout)
                done += 1
            except subprocess.TimeoutExpired as e:
                per_cmd_errors.append(f"{argv[-1]}: timed out after {e.timeout}s (continuing)")
            except Exception as e:
                per_cmd_errors.append(f"{argv[-1]}: {e} (continuing)")
        err = "; ".join(per_cmd_errors) if per_cmd_errors else ""
        # success if any step completed (new companies may still have been merged
        # even if discover_slugs timed out); per-step errors are surfaced in `err`.
        task_manager.finish("success" if done else "failed", err)
        return {"commands_run": done, "errors": per_cmd_errors}
    except Exception as e:
        task_manager.finish("failed", str(e))
        return {"commands_run": done, "error": str(e)}