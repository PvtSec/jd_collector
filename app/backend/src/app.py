"""FastAPI app — dashboard API, SSE event stream, and frontend static serving.

Routes:
  GET  /api/health
  GET  /api/jobs?recent=&sort=&ats=&q=&matched=&applied=&limit=&offset=  filtered job list
  GET  /api/jobs/{id}                                                single job (JD link = url)
  GET  /api/stats                                                    count tiles + by-ats
  GET  /api/daily?days=14                                            per-day rollup for status bar
  GET  /api/tasks/current                                            current-run snapshot
  GET  /api/tasks/history                                            recent task_runs
  POST /api/tasks/force-reload                                       kick discovery now (409 if running)
  POST /api/tasks/rescan-companies                                   kick heavy rescan (409 if running)
  POST /api/jobs/{id}/mark-applied                                   write to engine ledger + flip flag
  GET  /api/applied                                                  recent engine-ledger rows
  GET  /api/events                                                   SSE stream (task_started/progress/completed/failed)
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from engine.config import Config
from engine.boards import CLIENTS as ATS_CLIENTS

from . import discovery, scheduler, persist, liveness
from .db import DB
from .settings import settings
from .tasks import TaskManager, set_manager
from . import repository

# ---- singletons ----
db = DB(settings.abs_jobs_db())
tm = TaskManager(db)
set_manager(tm)

# Cache the engine Config; reloaded by rescan via /api/tasks/rescan-companies.
_cfg: Config | None = None


def _get_cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config.load(settings.abs_engine_config())
    return _cfg


def _reload_cfg() -> Config:
    global _cfg
    _cfg = Config.load(settings.abs_engine_config())
    return _cfg


def _seed_from_flat(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        rows = json.load(f)
    n = 0
    for j in rows:
        url = j.get("url") or ""
        if not url:
            continue
        # the flat file uses url as the key; map to (company, ats, job_id)
        # heuristically so upsert_job gets a stable UNIQUE key.
        company = j.get("company") or "unknown"
        ats = j.get("ats") or "unknown"
        job_id = url
        db.upsert_job(
            company=company, ats=ats, job_id=job_id,
            title=j.get("title", ""), location=j.get("location", ""),
            work_type="", url=url, posted_at="",
            matched=(j.get("loc_class") == "accept"),
            applied=False,
        )
        n += 1
    return n


# Seed the dashboard DB from a snapshot on first boot so the UI isn't empty
# before the first tick lands jobs. Prefer the discovered-jobs seed (real
# (company,ats,job_id) keys + full state incl closed); fall back to the static
# topstartups flat snapshot, then an explicit SEED_JSON env override.
if db.count_jobs() == 0:
    here = os.path.dirname(__file__)
    try:
        from . import seed as _seed
        n = _seed.import_seed(db, settings.abs_seed_file())
        if n:
            print(f"[seed] imported {n} jobs from {settings.abs_seed_file()}")
    except Exception as e:  # pragma: no cover
        print(f"[seed] import failed: {e}")
        n = 0
    if db.count_jobs() == 0:
        candidates = [
            os.path.abspath(os.path.join(here, "..", "..", "..", "data",
                                         "topstartups_jobs_flat.json")),
            os.environ.get("SEED_JSON", ""),
        ]
        for p in candidates:
            if p and os.path.exists(p):
                try:
                    m = _seed_from_flat(p)
                    print(f"[seed] loaded {m} jobs from {p}")
                except Exception as e:  # pragma: no cover
                    print(f"[seed] failed {p}: {e}")
                break


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bind the asyncio loop so the worker thread can publish SSE events.
    tm.bind_loop(asyncio.get_running_loop())
    # Restore applied flags from the persisted state file into the (possibly
    # fresh) jobs DB, so applied state survives a DB wipe.
    try:
        n = persist.reconcile_applied(settings.abs_state_file(), db)
        if n:
            print(f"[persist] restored {n} applied flag(s) from {settings.abs_state_file()}")
    except Exception as e:
        print(f"[persist] reconcile failed: {e}")
    try:
        n = persist.reconcile_hidden(settings.abs_state_file(), db)
        if n:
            print(f"[persist] restored {n} hidden flag(s) from {settings.abs_state_file()}")
    except Exception as e:
        print(f"[persist] reconcile-hidden failed: {e}")
    scheduler.start(settings)
    print(f"[scheduler] started, tick every {settings.tick_minutes} min, "
          f"rotate {settings.rotate_size}/tick, db={settings.abs_jobs_db()}, "
          f"state={settings.abs_state_file()}")
    # One-time background migration: restore valid unknown-ATS listings that
    # were blanket-purged in a prior version, then prune only the genuinely
    # dead (404/410) links. Gated by a marker file so it runs once.
    threading.Thread(target=_migrate_links, daemon=True).start()
    try:
        yield
    finally:
        scheduler.stop()


def _migrate_links() -> None:
    marker = os.path.join(os.path.dirname(settings.abs_state_file()), ".links_v2_done")
    if os.path.exists(marker):
        return
    flat = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                        "data", "topstartups_jobs_flat.json"))
    try:
        if os.path.exists(flat):
            n = _seed_from_flat(flat)
            print(f"[migrate] re-seeded {n} jobs from flat file (restoring valid unknown-ATS listings)")
    except Exception as e:
        print(f"[migrate] re-seed failed: {e}")
    try:
        res = liveness.prune_dead_unknown(db, ats_whitelist=list(ATS_CLIENTS.keys()))
        print(f"[migrate] link validate: checked={res['checked']} dead={res['dead']} "
              f"deleted={res['deleted']} live={res['live']} unknown={res['unknown']}")
    except Exception as e:
        print(f"[migrate] prune failed: {e}")
    try:
        open(marker, "w").close()
    except Exception:
        pass


app = FastAPI(title="job_auto dashboard", lifespan=lifespan)


# ---------- API ----------
@app.get("/api/health")
def health():
    return {"ok": True, "jobs": db.count_jobs()}


@app.get("/api/jobs")
def jobs(q: str = "", ats: str = "", matched: bool = False,
         applied: str = "", recent: str = "", sort: str = "recent",
         closed: str = "exclude",
         limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    recent_seconds = _parse_recent(recent)
    applied_only = _parse_tri(applied)
    closed_mode = (closed or "exclude").strip().lower()
    if closed_mode not in ("exclude", "only", "any"):
        closed_mode = "exclude"
    rows, total = db.list_jobs(
        q=q or None, ats=ats or None, matched_only=matched,
        applied_only=applied_only, recent_seconds=recent_seconds,
        sort=sort, limit=limit, offset=offset, closed=closed_mode,
    )
    return {"items": rows, "total": total, "count": len(rows), "limit": limit, "offset": offset}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int):
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@app.post("/api/jobs/{job_id}/mark-applied")
def mark_applied(job_id: int):
    res = repository.mark_applied(db, _get_cfg(), settings, job_id)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error", "job not found"))
    return res


@app.post("/api/jobs/{job_id}/hide")
def hide_job(job_id: int):
    """Hide a dead/stale link from the dashboard. Persisted in app/state.json so
    it stays hidden across restarts and is re-hidden after a DB wipe."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    db.mark_hidden(job_id)
    try:
        persist.record_hidden(settings.abs_state_file(), job)
    except Exception:
        pass
    return {"ok": True, "hidden": True, "job": job}


@app.get("/api/state")
def state():
    """Return the persisted state file (applied states + recent scans)."""
    return persist.load(settings.abs_state_file())


# ---- company/ATS detection for embedded-ATS pages ---------------------------
from urllib.parse import urlparse as _urlparse  # noqa: E402

_companies_cache: list[dict] | None = None
_companies_cache_mtime: float = 0.0


def _companies_for_detect() -> list[dict]:
    """mtime-aware cache — re-reads companies.json after consolidate.py rewrites it
    (manual rescan or the 24h discover_companies job), so /api/stats + /api/detect
    see the new companies without a restart."""
    global _companies_cache, _companies_cache_mtime
    try:
        mtime = os.path.getmtime(_get_cfg().companies_file)
    except Exception:
        return _companies_cache or []
    if _companies_cache is None or mtime != _companies_cache_mtime:
        try:
            with open(_get_cfg().companies_file, "r", encoding="utf-8") as f:
                _companies_cache = json.load(f)
            _companies_cache_mtime = mtime
        except Exception:
            return _companies_cache or []
    return _companies_cache


def _host_of(u: str) -> str:
    try:
        return (_urlparse(u).hostname or "").lower()
    except Exception:
        return ""


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "" for ch in (name or "").lower())


@app.get("/api/detect")
def detect(url: str = Query(..., description="page URL to identify")):
    """Identify which ATS a company page uses (handles vanity/embedded pages).

    Matches the URL against companies.json: career_page_url, alternate_career_urls,
    website host, domain_hint, and company-name slug. Returns the ATS + company
    + board_token so the extension can run the right filler even when the form
    is embedded inline/iframe on the company's own domain.
    """
    try:
        target_host = (_urlparse(url).hostname or "").lower()
        target_path = (_urlparse(url).path or "").lower()
    except Exception:
        return {"matched": False}
    if not target_host:
        return {"matched": False}

    best = None
    best_score = 0
    best_type = ""
    for c in _companies_for_detect():
        score = 0
        mtype = ""
        cpu = c.get("career_page_url", "") or ""
        alts = c.get("alternate_career_urls", []) or []
        website = c.get("website", "") or ""
        domain = (c.get("domain_hint", "") or "").lower()
        name = c.get("company_name", "") or ""

        # exact URL hit (ignore scheme)
        for u in [cpu] + list(alts):
            if u and _host_of(u) == target_host and _urlparse(u).path.rstrip("/").lower() == target_path.rstrip("/"):
                score = 100; mtype = "url"; break
        if not score:
            # host match against career_page_url / website
            for u in [cpu, website]:
                h = _host_of(u)
                if h and (h == target_host or target_host.endswith("." + h) or h.endswith("." + target_host)):
                    score = 60; mtype = "host"
            # domain_hint substring in the target host
            if domain and domain in target_host:
                score = max(score, 45); mtype = "domain"
            # company-name slug in the target host
            s = _slug(name)
            if s and len(s) >= 4 and s in target_host:
                score = max(score, 35); mtype = "name"
        if score > best_score:
            best_score = score
            best = c
            best_type = mtype

    if best and best_score >= 35:
        return {
            "matched": True,
            "ats": best.get("ats_type"),
            "company": best.get("company_name"),
            "board_token": best.get("board_token"),
            "career_page_url": best.get("career_page_url"),
            "match_type": best_type,
            "score": best_score,
        }
    # Fallback: recognize the ATS by URL host pattern even if the company isn't
    # in companies.json (e.g. a Recruitee/Jobvite/Workday page for a new company).
    from engine.ats_registry import detect_ats_by_host
    host_ats = detect_ats_by_host(url)
    if host_ats:
        return {"matched": True, "ats": host_ats, "company": None,
                "board_token": None, "career_page_url": None,
                "match_type": "host_pattern", "score": 10}
    return {"matched": False}


@app.post("/api/links/validate")
def validate_links():
    """Liveness-check non-ATS job URLs and delete the genuinely dead (404/410)
    ones. Real-ATS URLs are trusted (live by construction). Returns counts."""
    return liveness.prune_dead_unknown(db, ats_whitelist=list(ATS_CLIENTS.keys()))


@app.get("/api/stats")
def stats():
    s = db.stats()
    s["last_run"] = db.last_run()
    s["applied_ledger"] = repository.applied_summary(_get_cfg())
    # company-list growth: total known + automatable (so the UI shows new
    # companies being discovered by the automatic discover_companies job)
    try:
        comps = _companies_for_detect()
        automatable = sum(1 for c in comps if c.get("board_token"))
        s["companies_total"] = len(comps)
        s["companies_automatable"] = automatable
    except Exception:
        pass
    return s


@app.get("/api/daily")
def daily(days: int = Query(14, ge=1, le=120)):
    return db.daily_stats(days)


@app.get("/api/ats")
def ats():
    return db.distinct_ats()


@app.get("/api/tasks/current")
def tasks_current():
    return tm.current()


@app.get("/api/tasks/history")
def tasks_history(limit: int = Query(20, ge=1, le=200)):
    return tm.history(limit)


@app.post("/api/tasks/force-reload")
def tasks_force_reload():
    if not scheduler.force_reload(tm):
        raise HTTPException(409, "a task is already running")
    return {"accepted": True, "started_at": time.time()}


@app.post("/api/tasks/rescan-companies")
def tasks_rescan():
    if not scheduler.rescan(tm):
        raise HTTPException(409, "a task is already running")
    # The rescan job reloads companies.json; invalidate the cached Config so the
    # next tick picks up new board tokens.
    _reload_cfg()
    return {"accepted": True, "started_at": time.time(),
            "note": "heavy rescan: re-runs discover_slugs + discover_topstartups + consolidate"}


@app.get("/api/applied")
def applied(limit: int = Query(200, ge=1, le=1000)):
    return {"items": repository.applied_rows(_get_cfg(), limit)}


# ---------- SSE ----------
@app.get("/api/events")
async def events():
    q = tm.subscribe()

    async def gen():
        try:
            # initial hello so the client knows it's connected
            yield f"data: {json.dumps({'type': 'hello', 'running': tm.is_running})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            tm.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------- helpers ----------
def _parse_recent(s: str) -> float | None:
    s = (s or "").strip().lower()
    if not s or s == "all":
        return None
    units = {"h": 3600, "d": 86400, "m": 60}
    if s[-1] in units:
        try:
            return float(s[:-1]) * units[s[-1]]
        except ValueError:
            return None
    try:
        return float(s) * 86400  # bare number → days
    except ValueError:
        return None


def _parse_tri(s: str) -> bool | None:
    s = (s or "").strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


# ---------- frontend static serving ----------
FRONTEND_DIST = settings.abs_frontend_dist()
if os.path.isdir(FRONTEND_DIST):
    assets = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

    @app.get("/{path:path}")
    def spa(path: str):
        full = os.path.join(FRONTEND_DIST, path)
        if path and os.path.isfile(full):
            return FileResponse(full)
        # SPA fallback
        idx = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(idx):
            return FileResponse(idx)
        return JSONResponse({"message": "frontend not built", "api": ["/api/health"]})
else:
    @app.get("/")
    def index():
        return JSONResponse({
            "message": "frontend not built. Run `npm run build` in app/frontend/ "
                       "(or run `npm run dev` for the Vite dev server).",
            "api": ["/api/health", "/api/jobs", "/api/stats", "/api/tasks/current",
                    "/api/tasks/force-reload", "/api/events"],
        })