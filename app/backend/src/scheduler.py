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
        return
    discovery.run_tick(settings, tm)


def _force_tick_job():
    settings = _settings
    tm = get_manager()
    discovery.run_tick(settings, tm)


def _rescan_job():
    settings = _settings
    tm = get_manager()
    discovery.run_rescan(settings, tm)


def _prune_links_job():
    from . import liveness
    from .app import db, ATS_CLIENTS
    try:
        liveness.prune_dead_unknown(db, ats_whitelist=list(ATS_CLIENTS.keys()))
    except Exception as e:
        print(f"[prune] periodic link check failed: {e}")


def _prune_jobs_job():
    settings = _settings
    if settings is None:
        return
    from . import liveness
    from .app import db, ATS_CLIENTS
    try:
        res = liveness.prune_dead_jobs(
            db, ats_whitelist=list(ATS_CLIENTS.keys()),
            limit=settings.job_liveness_batch,
        )
        print(f"[liveness] job-url sweep: checked={res['checked']} "
              f"closed={res['closed']} dead={res['dead']} "
              f"live={res['live']} unknown={res['unknown']}")
    except Exception as e:
        print(f"[liveness] job-url sweep failed: {e}")


def _discover_companies_job():
    settings = _settings
    tm = get_manager()
    if tm.is_running:
        return
    discovery.run_rescan(settings, tm, kind="discover_companies")


def _export_seed_job():
    settings = _settings
    if settings is None:
        return
    try:
        from . import seed
        from .app import db
        path = settings.abs_seed_file()
        sig = db.export_signature()
        if sig == seed.read_sig(path):
            return  # nothing changed since the last export
        res = seed.export_seed(db, path, settings.seed_max_rows)
        seed.write_sig(path, sig)
        print(f"[seed] exported {res['exported']} jobs -> {res['path']}")
    except Exception as e:
        print(f"[seed] export failed: {e}")


def start(settings: AppSettings):
    global _scheduler, _settings
    _settings = settings
    _scheduler = BackgroundScheduler(
        executors={"default": APThreadPool(1), "prune": APThreadPool(1),
                   "heavy": APThreadPool(1), "liveness": APThreadPool(1)},
        timezone="UTC",
    )
    _scheduler.add_job(
        _tick_job, "interval", minutes=settings.tick_minutes,
        id="discovery", coalesce=True, max_instances=1,
        next_run_time=datetime.utcnow(),
    )
    _scheduler.add_job(
        _prune_links_job, "interval", minutes=settings.link_check_minutes,
        id="prune_links", coalesce=True, max_instances=1, executor="prune",
    )
    _scheduler.add_job(
        _prune_jobs_job, "interval", minutes=settings.job_liveness_minutes,
        id="prune_jobs", coalesce=True, max_instances=1, executor="liveness",
        misfire_grace_time=600,
        next_run_time=datetime.utcnow() + timedelta(seconds=150),
    )
    _scheduler.add_job(
        _discover_companies_job, "interval", minutes=settings.company_discovery_minutes,
        id="discover_companies", coalesce=True, max_instances=1, executor="heavy",
        next_run_time=datetime.utcnow() + timedelta(seconds=90),
    )
    _scheduler.add_job(
        _export_seed_job, "interval", minutes=settings.seed_export_minutes,
        id="export_seed", coalesce=True, max_instances=1, executor="prune",
        next_run_time=datetime.utcnow() + timedelta(seconds=120),
    )
    _scheduler.start()


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def force_reload(tm: TaskManager) -> bool:
    if tm.is_running:
        return False
    _scheduler.add_job(_force_tick_job, "date", id="force",
                       replace_existing=True)
    return True


def rescan(tm: TaskManager) -> bool:
    if tm.is_running:
        return False
    _scheduler.add_job(_rescan_job, "date", id="rescan",
                       replace_existing=True)
    return True