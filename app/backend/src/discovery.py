from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import engine.ledger as ledger
from engine.boards import CLIENTS, BoardError
from engine.config import Config
from engine.match import matches

from .companies import companies_filtered
from .db import DB
from .settings import AppSettings
from .skills_vocab import extract_skills, job_text
from .tasks import TaskManager

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

    n = len(comps)
    cursor = db.get_cursor()
    slice_ = _rotate_slice(comps, cursor, settings.rotate_size)
    new_cursor = (cursor + len(slice_)) % n
    wrapped = (cursor + len(slice_)) > n

    dead = db.dead_keys(threshold=settings.dead_skip_threshold,
                        cooldown_seconds=settings.dead_skip_minutes * 60)
    work: list[tuple[dict, str]] = []
    skipped_dead = 0
    for c in slice_:
        key = f"{c['ats_type']}|{c['board_token']}"
        if key in dead:
            skipped_dead += 1
        else:
            work.append((c, key))

    run_id = task_manager.begin("discovery", companies_total=len(work))

    jobs_seen = jobs_new = jobs_matched = companies_done = jobs_closed = 0
    boards_failed = 0
    new_jobs: list[dict] = []
    alive_keys: list[str] = []
    dead_pairs: list[tuple[str, str]] = []
    try:
        ledger_conn = ledger.connect(cfg.ledger_db).__enter__()
    except Exception:
        ledger_conn = None

    try:
        ats_sem = {a: threading.Semaphore(settings.ats_concurrency)
                   for a in {c["ats_type"] for c, _ in work}}

        def _enumerate(c: dict):
            with ats_sem[c["ats_type"]]:
                try:
                    return ("ok", list(CLIENTS[c["ats_type"]](
                        c["company_name"], c["board_token"],
                        ua=cfg.user_agent, timeout=cfg.http_timeout, retries=cfg.http_retries,
                    )))
                except BoardError:
                    return ("dead", None)
                except Exception:
                    return ("error", None)

        with ThreadPoolExecutor(max_workers=settings.tick_concurrency) as ex:
            futures = {ex.submit(_enumerate, c): i for i, (c, _k) in enumerate(work)}
            for fut in as_completed(futures):
                i = futures[fut]
                c, key = work[i]
                ats = c["ats_type"]
                company = c["company_name"]
                status, jobs = fut.result()
                if status != "ok":
                    dead_pairs.append((key, ats))
                    continue

                alive_keys.append(key)

                # match + ledger lookup + skill extraction stay outside the DB
                # write lock; the whole board then lands in one transaction
                board_rows = []
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
                    try:
                        skills = extract_skills(job_text(j))
                    except Exception:
                        skills = None
                    board_rows.append({
                        "company": j.company, "ats": j.ats, "job_id": j.job_id,
                        "title": j.title, "location": j.location,
                        "work_type": j.work_type, "url": j.url,
                        "posted_at": j.posted_at, "matched": ok,
                        "applied": applied, "skills": skills,
                    })
                try:
                    res = db.ingest_board(
                        company=company, ats=ats, rows=board_rows,
                        reap=ats in REAPER_ATS, grace=settings.stale_grace_misses,
                    )
                except Exception:
                    boards_failed += 1
                    print(f"[tick] ingest failed for {company} ({ats}); board skipped")
                    res = {"jobs_new": 0, "new_rows": [], "closed_now": 0}
                jobs_new += res["jobs_new"]
                jobs_closed += res["closed_now"]
                new_jobs.extend(res["new_rows"])

                companies_done += 1
                if companies_done % 5 == 0 or i == len(work) - 1:
                    task_manager.progress(
                        companies_done=companies_done,
                        companies_total=len(work),
                        jobs_seen=jobs_seen,
                        jobs_new=jobs_new,
                        jobs_matched=jobs_matched,
                        jobs_closed=jobs_closed,
                        progress=f"enumerated {companies_done}/{len(work)} companies"
                                 + (f" (skipped {skipped_dead} dead)" if skipped_dead else ""),
                    )
                    db.update_run(run_id, companies_total=len(work),
                                  companies_done=companies_done, jobs_seen=jobs_seen,
                                  jobs_new=jobs_new, jobs_matched=jobs_matched)

        try:
            db.update_dead(alive_keys=alive_keys, dead_pairs=dead_pairs)
        except Exception:
            pass

        try:
            sweep_evt = db.advance_sweep(new_cursor=new_cursor, wrapped=wrapped,
                                         total=n, jobs_new=jobs_new,
                                         jobs_matched=jobs_matched)
            if sweep_evt.get("completed"):
                task_manager.publish({
                    "type": "sweep_completed",
                    "sweep_id": sweep_evt["sweep_id"],
                    "jobs_new": sweep_evt["jobs_new"],
                    "jobs_matched": sweep_evt["jobs_matched"],
                    "new_sweep_id": sweep_evt["sweep_id"] + 1,
                })
        except Exception:
            pass

        task_manager.progress(
            companies_done=companies_done, companies_total=len(work),
            jobs_seen=jobs_seen, jobs_new=jobs_new, jobs_matched=jobs_matched,
            jobs_closed=jobs_closed,
            progress=f"enumerated {companies_done}/{len(work)} companies"
                     + (f" (skipped {skipped_dead} dead)" if skipped_dead else ""),
        )

        db.update_run(run_id, companies_total=len(work), companies_done=companies_done,
                      jobs_seen=jobs_seen, jobs_new=jobs_new, jobs_matched=jobs_matched)
        db.bump_daily(jobs_new=jobs_new, jobs_matched=jobs_matched,
                      companies_enumerated=companies_done)
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
                "companies_total": len(work),
                "jobs_seen": jobs_seen,
                "jobs_new": jobs_new,
                "jobs_matched": jobs_matched,
                "jobs_closed": jobs_closed,
            }
            persist.record_scan(settings.abs_state_file(), run_summary, new_jobs)
        except Exception:
            pass
        task_manager.finish(
            "success",
            f"{boards_failed} board ingest(s) failed" if boards_failed else "")
        return {
            "jobs_new": jobs_new, "jobs_seen": jobs_seen,
            "jobs_matched": jobs_matched, "jobs_closed": jobs_closed,
            "companies_done": companies_done, "companies_total": len(slice_),
            "boards_failed": boards_failed,
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
        cwd = settings.abs_engine_config().rsplit("/", 1)[0] if "/" in settings.engine_config else None
        per_cmd_errors = []
        for i, cmd in enumerate(settings.rescan_commands):
            argv = cmd.replace("{python}", py).split()
            task_manager.progress(companies_done=i, progress=f"running {argv[-1]}")
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
        task_manager.finish("success" if done else "failed", err)
        return {"commands_run": done, "errors": per_cmd_errors}
    except Exception as e:
        task_manager.finish("failed", str(e))
        return {"commands_run": done, "error": str(e)}