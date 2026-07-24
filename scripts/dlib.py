#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_DISCOVERY_DIR = ROOT / "data" / "discovery"
DISCOVERY_DIR = Path(os.environ.get("JOBAUTO_DISCOVERY_DIR", DEFAULT_DISCOVERY_DIR))
DB_PATH = DISCOVERY_DIR / "discovery.db"
LOG_PATH = DISCOVERY_DIR / "log.md"
PROGRESS_PATH = DISCOVERY_DIR / "progress.json"
COMPANIES_JSON = ROOT / "data" / "companies.json"

GOAL = 50000

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA}
HTTP_TIMEOUT = 8

# Dedup helpers — MUST mirror scripts/consolidate.py (norm_name, domain_key,
# bare_domain, infer_ats_from_url, ATS_HOST_RULES). Kept in sync manually.
ATS_HOST_RULES = [
    ("greenhouse", ["boards.greenhouse.io", "job-boards.greenhouse.io"]),
    ("lever",      ["jobs.lever.co"]),
    ("ashby",      ["jobs.ashbyhq.com", "app.ashbyhq.com"]),
    ("smartrecruiters", ["jobs.smartrecruiters.com", "careers.smartrecruiters.com"]),
    ("workable",   ["apply.workable.com"]),
    ("personio",   ["jobs.personio.com", ".jobs.personio.com"]),
    ("bamboohr",   [".bamboohr.com", "bamboohr.com/careers"]),
    ("trinethire", ["app.trinethire.com"]),
    ("onlyfy",     [".onlyfy.jobs", "onlyfy.jobs"]),
    ("keka",       [".keka.com"]),
    ("pinpoint",   ["pinpointhq.com"]),
    ("breezyhr",   [".breezy.hr", "breezy.hr"]),
    ("teamtailor", ["careers.teamtailor.com", ".teamtailor.com"]),
    ("rippling",   ["ats.rippling.com"]),
    ("workday",    [".myworkdayjobs.com", ".wd5.myworkdayjobs.com", "myworkdayjobs.com"]),
    ("yc",         ["ycombinator.com/companies/"]),
    ("applytojob", ["applytojob.com"]),
    ("attrax",     ["wise.jobs"]),
]

# ATS-host ids that mean "automatable / reliable by construction".
ATS_HOST_IDS = {ats for ats, _ in ATS_HOST_RULES if ats != "yc"}

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
BODY_NOT_FOUND = re.compile(
    r"(page not found|404\s*[-–—]?\s*(not found|error)|"
    r"we couldn'?t find|could not find (that |the )?page|"
    r"this page (doesn'?t|does not) exist|page (doesn'?t|does not) exist|"
    r"no longer available|has been removed|"
    r"the page you (were )?looking for)", re.I)
TITLE_NOT_FOUND = re.compile(r"(not found|404|doesn'?t exist|does not exist|no longer)", re.I)


def norm_name(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = n.replace("(formerly rstudio)", " ")
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def bare_domain(url: str) -> str:
    try:
        h = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    if not h:
        return ""
    parts = h.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return h


def domain_key(entry: dict) -> str:
    for url in (entry.get("website"), entry.get("career_page_url")):
        if url:
            d = bare_domain(url)
            if d:
                return d
    return norm_name(entry.get("company_name", ""))


def norm_key(entry: dict) -> str:
    return norm_name(entry.get("company_name", "")) or domain_key(entry)


def infer_ats_from_url(url: str) -> str | None:
    u = (url or "").lower()
    for ats_id, subs in ATS_HOST_RULES:
        for s in subs:
            if s in u:
                return ats_id
    return None


# HTTP liveness — mirror app/backend/src/liveness.py check_url
def http_check(url: str, timeout: int = HTTP_TIMEOUT) -> str:
    if not url or not url.startswith("http"):
        return "dead"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        code = r.status_code
        html = r.text if code < 400 else ""
    except requests.RequestException:
        return "unknown"
    if code in (404, 410):
        return "dead"
    if 200 <= code < 400:
        if _looks_dead_200(html):
            return "dead"
        return "live"
    if 500 <= code < 600:
        return "unknown"
    return "unknown"


def _looks_dead_200(html: str) -> bool:
    if not html:
        return False
    m = TITLE_RE.search(html)
    title = m.group(1).strip() if m else ""
    if title and TITLE_NOT_FOUND.search(title):
        return True
    snippet = html[:32768]
    return bool(BODY_NOT_FOUND.search(snippet))


def is_ats_host_url(url: str) -> bool:
    return infer_ats_from_url(url) in ATS_HOST_IDS


def is_reliable(rec: dict) -> tuple[bool, str]:
    url = (rec.get("career_page_url") or "").strip()
    if not url:
        return False, "none"
    if is_ats_host_url(url):
        return True, "ats-host"
    v = http_check(url)
    return (v == "live"), v


def _connect() -> sqlite3.Connection:
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            norm_key TEXT PRIMARY KEY,
            name TEXT,
            website TEXT,
            career_page_url TEXT,
            ats_type TEXT,
            source TEXT,
            http_status TEXT,
            reliable INTEGER NOT NULL DEFAULT 0,
            first_seen REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reliable ON companies(reliable)")
    conn.commit()
    conn.close()


def record_company(rec: dict, *, source: str | None = None,
                   force_http: bool = True, recheck: bool = True
                   ) -> tuple[bool, bool, str, bool]:
    init_db()
    key = norm_key(rec)
    if not key:
        return False, False, "none", False
    name = (rec.get("company_name") or "").strip()
    website = (rec.get("website") or "").strip()
    url = (rec.get("career_page_url") or "").strip()
    ats = rec.get("ats_type") or infer_ats_from_url(url) or "unknown"
    src = source or rec.get("source_platform") or rec.get("source") or "unknown"

    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT reliable, http_status FROM companies WHERE norm_key=?", (key,)).fetchone()
        if existing is not None and existing[0] == 1 and not recheck:
            # already reliable; just refresh harmless metadata, skip HTTP
            conn.execute(
                "UPDATE companies SET name=COALESCE(NULLIF(?, ''),name), "
                "website=COALESCE(NULLIF(?, ''),website), "
                "ats_type=CASE WHEN ?!='unknown' THEN ? ELSE ats_type END WHERE norm_key=?",
                (name, website, ats, ats, key))
            conn.commit()
            return False, True, existing[1] or "ats-host", False

        prior_reliable = bool(existing[0]) if existing else False
        # Reliability: ATS-host trusted; else HTTP-check (skip if force_http False).
        if url and is_ats_host_url(url):
            reliable, hstatus = True, "ats-host"
        elif url and force_http:
            reliable, hstatus = is_reliable(rec)
        else:
            reliable, hstatus = False, "unknown"

        is_new = existing is None
        conn.execute(
            "INSERT INTO companies (norm_key,name,website,career_page_url,ats_type,source,http_status,reliable,first_seen) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(norm_key) DO UPDATE SET "
            "name=excluded.name, website=COALESCE(NULLIF(excluded.website,''),companies.website), "
            "career_page_url=COALESCE(NULLIF(excluded.career_page_url,''),companies.career_page_url), "
            "ats_type=CASE WHEN excluded.ats_type!='unknown' THEN excluded.ats_type ELSE companies.ats_type END, "
            "http_status=excluded.http_status, reliable=MAX(excluded.reliable,companies.reliable)",
            (key, name, website, url, ats, src, hstatus, 1 if reliable else 0, time.time()))
        row = conn.execute("SELECT reliable FROM companies WHERE norm_key=?", (key,)).fetchone()
        final_reliable = bool(row[0]) if row else reliable
        conn.commit()
        return is_new, final_reliable, hstatus, (final_reliable and not prior_reliable)
    finally:
        conn.close()


# log.md (atomic append) + progress.json
def format_log_line(worker: str, rec: dict, hstatus: str) -> str:
    name = (rec.get("company_name") or "").replace("|", "/").strip()
    url = (rec.get("career_page_url") or "").replace("|", "/").strip()
    ats = rec.get("ats_type") or infer_ats_from_url(url) or "custom"
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    return f"{ts} | {worker} | NEW | {name} | {ats} | {url} | {hstatus}"


def append_log(worker: str, rec: dict, hstatus: str) -> None:
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    line = format_log_line(worker, rec, hstatus)
    # Cap at 1000 chars to stay well under PIPE_BUF.
    if len(line) > 1000:
        line = line[:1000]
    with open(LOG_PATH, "ab") as f:
        f.write((line + "\n").encode("utf-8", "replace"))


def _read_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text())
        except Exception:
            pass
    return {"goal": GOAL, "reliable_count": 0, "total_unique": 0,
            "phase": "init", "workers": {}, "last_updated": time.time()}


def snapshot() -> dict:
    init_db()
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        reliable = conn.execute("SELECT COUNT(*) FROM companies WHERE reliable=1").fetchone()[0]
    finally:
        conn.close()
    prog = _read_progress()
    prog["total_unique"] = total
    prog["reliable_count"] = reliable
    prog["last_updated"] = time.time()
    prog["goal"] = GOAL
    return prog


def save_progress(prog: dict) -> None:
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    prog["last_updated"] = time.time()
    PROGRESS_PATH.write_text(json.dumps(prog, indent=2, ensure_ascii=False))


def bump_progress(worker_state: dict | None = None) -> dict:
    prog = snapshot()
    if worker_state:
        prog.setdefault("workers", {}).update(worker_state)
    prog["phase"] = "running"
    save_progress(prog)
    return prog


def log_header() -> str:
    return """# Discovery Log — target 50,000 reliable companies (resolvable careers/job-board URL)

RESUME IN A NEW SESSION:
  1. cd /mnt/380/Projects/job_auto/repo
  2. python scripts/run_discovery.py status      # reliable_count vs 50000 + worker state
  3. python scripts/run_discovery.py run          # relaunch 32-way workers over unfinished partitions
  4. Repeat step 3 in fresh sessions until reliable_count >= 50000
  5. When done: python scripts/consolidate.py && ./run.sh up   # bake into the app

FORMAT: each line = <iso8601> | <worker> | NEW | <company> | <ats|custom> | <url> | <http-status>
A company counts toward 50k only if it has a resolvable careers URL
(ATS-host board URL, trusted — or a /careers page returning HTTP 200, validated).
Name-only companies are kept but do NOT count toward the 50k goal.
--- discoveries below ---
"""


def ensure_log() -> None:
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
        LOG_PATH.write_text(log_header())


# Seed existing companies.json so dedup starts from the current 13,637.
# ATS-host rows count as reliable; others are recorded (seen) but not reliable.
def seed_from_companies_json() -> int:
    if not COMPANIES_JSON.exists():
        return 0
    init_db()
    ensure_log()
    data = json.loads(COMPANIES_JSON.read_text())
    conn = _connect()
    inserted = 0
    now = time.time()
    rows = []
    for e in data:
        key = norm_key(e)
        if not key:
            continue
        url = (e.get("career_page_url") or "").strip()
        ats = e.get("ats_type") or infer_ats_from_url(url) or "unknown"
        reliable = 1 if is_ats_host_url(url) else 0
        hstatus = "ats-host" if reliable else "none"
        rows.append((key, (e.get("company_name") or "").strip(),
                           (e.get("website") or "").strip(), url, ats,
                           "seed-companies-json", hstatus, reliable, now))
    conn.executemany(
        "INSERT OR IGNORE INTO companies "
        "(norm_key,name,website,career_page_url,ats_type,source,http_status,reliable,first_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?)", rows)
    inserted = conn.total_changes
    conn.commit()
    conn.close()
    return inserted


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="dlib — discovery library CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="init db + log + seed from companies.json")
    sub.add_parser("status", help="print snapshot")
    sub.add_parser("seed", help="seed db from companies.json only")
    sub.add_parser("reliable", help="print reliable_count / goal")
    ac = sub.add_parser("add", help="record one company (name+url); logs if new & reliable")
    ac.add_argument("--name", required=True)
    ac.add_argument("--url", required=True, help="career_page_url")
    ac.add_argument("--website", default="")
    ac.add_argument("--source", default="llm-agent")
    a = ap.parse_args()
    if a.cmd == "init":
        init_db(); ensure_log()
        n = seed_from_companies_json()
        print(f"seeded {n} companies from companies.json")
        print(json.dumps(snapshot(), indent=2))
    elif a.cmd == "status":
        print(json.dumps(snapshot(), indent=2))
    elif a.cmd == "reliable":
        s = snapshot()
        print(f"{s['reliable_count']}/{GOAL} reliable  total_unique={s['total_unique']}")
    elif a.cmd == "seed":
        print(f"seeded {seed_from_companies_json()} companies")
    elif a.cmd == "add":
        init_db(); ensure_log()
        rec = {"company_name": a.name, "career_page_url": a.url, "website": a.website}
        is_new, is_reliable, hstatus, became = record_company(rec, source=a.source)
        if is_new and is_reliable:
            append_log(a.source, rec, hstatus)
        elif became:
            append_log(a.source + "-upgrade", rec, hstatus)
        print(json.dumps({"is_new": is_new, "is_reliable": is_reliable,
                          "http_status": hstatus, "became_reliable": became}))