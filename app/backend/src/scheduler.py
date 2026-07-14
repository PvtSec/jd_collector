"""Background scheduler — APScheduler interval job + manual force/rescan.

A single-worker ``ThreadPoolExecutor`` guarantees ticks never overlap (sync
enumerators incl. Playwright can't run concurrently here). ``force_reload``
and ``rescan`` are one-shot jobs added on demand.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor as APThreadPool

from .settings import AppSettings
from .tasks import TaskManager, TaskRunning, get_manager
from . import discovery

_scheduler: BackgroundScheduler | None = None
_settings: AppSettings | None = None


def _tick_job():
    settings = _settings
    tm = get_manager()
    if tm.is_running:
        return  # single-flight: skip if a manual run is in progress
    discovery.run_tick(settings, tm)


def _force_tick_job():
    """One-shot job added by force_reload — just calls run_tick."""
    settings = _settings
    tm = get_manager()
    discovery.run_tick(settings, tm)


def _rescan_job():
    settings = _settings
    tm = get_manager()
    discovery.run_rescan(settings, tm)


def _prune_links_job():
    """Periodic dead-link prune: drop non-ATS URLs that 404/410. Real-ATS URLs
    are trusted. Runs on a separate executor so it never blocks discovery."""
    from . import liveness
    from .app import db, ATS_CLIENTS
    try:
        liveness.prune_dead_unknown(db, ats_whitelist=list(ATS_CLIENTS.keys()))
    except Exception as e:
        print(f"[prune] periodic link check failed: {e}")


def _discover_companies_job():
    """Automatic new-company discovery: re-runs the heavy discovery scripts
    (discover_slugs + discover_topstartups + consolidate) so the company list
    grows without the manual Rescan button. On its own executor so the 5-min
    job-rotation tick keeps running."""
    settings = _settings
    tm = get_manager()
    if tm.is_running:
        return  # don't start a long company-discovery while a task is running
    discovery.run_rescan(settings, tm, kind="discover_companies")


def start(settings: AppSettings):
    global _scheduler, _settings
    _settings = settings
    _scheduler = BackgroundScheduler(
        executors={"default": APThreadPool(1), "prune": APThreadPool(1), "heavy": APThreadPool(1)},
        timezone="UTC",
    )
    _scheduler.add_job(
        _tick_job, "interval", minutes=settings.tick_minutes,
        id="discovery", coalesce=True, max_instances=1,
        next_run_time=datetime.utcnow(),  # fire once on startup
    )
    # periodic dead-link prune (default every 12h) on its own executor
    _scheduler.add_job(
        _prune_links_job, "interval", minutes=settings.link_check_minutes,
        id="prune_links", coalesce=True, max_instances=1, executor="prune",
    )
    # automatic new-company discovery (default every 24h) — fires once shortly
    # after startup so new companies appear quickly, then on the cadence.
    _scheduler.add_job(
        _discover_companies_job, "interval", minutes=settings.company_discovery_minutes,
        id="discover_companies", coalesce=True, max_instances=1, executor="heavy",
        next_run_time=datetime.utcnow() + timedelta(seconds=90),
    )
    _scheduler.start()


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def force_reload(tm: TaskManager) -> bool:
    """If idle, kick a discovery tick immediately. Returns True if accepted."""
    if tm.is_running:
        return False
    # one-shot, run now
    _scheduler.add_job(_force_tick_job, "date", id="force",
                       replace_existing=True)
    return True


def rescan(tm: TaskManager) -> bool:
    """If idle, kick the heavy rescan job immediately."""
    if tm.is_running:
        return False
    _scheduler.add_job(_rescan_job, "date", id="rescan",
                       replace_existing=True)
    return True