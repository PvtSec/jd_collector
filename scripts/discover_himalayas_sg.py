#!/usr/bin/env python3
"""Singapore full-country sweep of the himalayas.app jobs API.

Unlike discover_himalayas.py (security-role queries only), this captures EVERY
company that has >=1 job whose locationRestrictions contains "Singapore",
across all roles/industries.

Method
------
1. Keyword slices: GET https://himalayas.app/jobs/api/search?q=<kw>&country=SG&page=N
   (20 jobs/page server cap), paginated per keyword, client-side filtered for
   "Singapore" in locationRestrictions. `country=SG` alone means "eligible from
   Singapore" (includes worldwide-remote), so the locationRestrictions check is
   the real Singapore signal.
2. Feed filler: GET https://himalayas.app/jobs/api?cursor=... (newest-first),
   same client-side filter, to catch companies whose titles/descriptions match
   none of the keyword slices.

Output: data/raw/agentSG01_himalayas_sg.json (JSON array, incremental rewrites).

Public API only; polite UA + sleep; on 403/429 sleep 30s, retry twice, move on.
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get(
    "JOBAUTO_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
RAW_OUT = os.path.join(DATA, "raw", "agentSG01_himalayas_sg.json")

HIMALAYAS_API = "https://himalayas.app/jobs/api/search"
HIMALAYAS_FEED = "https://himalayas.app/jobs/api"
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
PAGE_SIZE = 20  # server hard cap regardless of ?limit
SLEEP = 0.35
MAX_PAGES_PER_KEYWORD = 45
CHECKPOINT_EVERY = 10  # keywords

# Broad role/industry/common-title word slices (q is full-text: title+company+description).
KEYWORDS = [
    # engineering / software
    "engineer", "developer", "software", "programmer", "frontend", "backend",
    "full stack", "mobile", "android", "ios", "web", "devops", "sre",
    "site reliability", "platform", "infrastructure", "cloud", "architect",
    "security", "cybersecurity", "devsecops", "network", "systems",
    "qa", "test", "automation", "sdet",
    # data / ai
    "data", "analyst", "analytics", "scientist", "machine learning", "ai",
    "artificial intelligence", "llm", "research", "statistic", "bi",
    # product / design
    "product", "project", "program", "designer", "design", "ux", "ui",
    "researcher", "scrum", "agile", "owner",
    # business / gtM
    "marketing", "growth", "sales", "business", "development", "account",
    "customer", "support", "success", "solutions", "consultant", "partnership",
    "operations", "ops", "finance", "fintech", "financial", "accounting",
    "risk", "compliance", "legal", "hr", "people", "talent", "recruiter",
    "recruiting", "talent acquisition",
    # seniority / employment-type catch-alls
    "senior", "junior", "lead", "manager", "head", "director", "specialist",
    "executive", "associate", "assistant", "coordinator", "intern",
    "internship", "graduate", "entry", "remote", "hybrid", "contract",
    "full-time", "part-time", "freelance",
    # stacks (extra description-level hooks)
    "python", "java", "javascript", "typescript", "react", "node", "golang",
    "rust", "ruby", "php", "laravel", "dotnet", "kubernetes", "aws", "saas",
    "startup", "fintech", "ecommerce", "logistics", "blockchain", "crypto",
    "web3", "gaming", "healthtech", "edtech", "insurtech", "travel",
]

ATS_SUBSTRINGS = [
    ("greenhouse", "boards.greenhouse.io"),
    ("greenhouse", "job-boards.greenhouse.io"),
    ("lever", "jobs.lever.co"),
    ("ashby", "jobs.ashbyhq.com"),
    ("ashby", "app.ashbyhq.com"),
    ("smartrecruiters", "careers.smartrecruiters.com"),
    ("smartrecruiters", "jobs.smartrecruiters.com"),
    ("workable", "apply.workable.com"),
    ("personio", "jobs.personio.de"),
    ("personio", "talent.personio.com"),
    ("rippling", "rippling.com/ats/"),
    ("rippling", "ats.rippling.com"),
    ("teamtailor", "apply.teamtailor.com"),
    ("teamtailor", "jobs.teamtailor.com"),
    ("bamboohr", "bamboohr.com"),
    ("breezyhr", "breezy.hr"),
    ("recruitee", "recruitee.com"),
    ("pinpoint", "pinpoint.hr"),
    ("workday", "myworkdayjobs.com"),
    ("workday", "wd1.myworkdayjobs.com"),
    ("workday", "wd3.myworkdayjobs.com"),
    ("workday", "wd5.myworkdayjobs.com"),
    ("icims", "icims.com"),
    ("successfactors", "successfactors.com"),
    ("taleo", "taleo.net"),
    ("greenhouse", "grnh.se"),
    ("lever", "lever.co"),
]


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _is_sg(job: dict) -> bool:
    for loc in job.get("locationRestrictions") or []:
        if "singapore" in (loc or "").lower():
            return True
    return False


def _ats_from_url(url: str) -> tuple[str, str] | None:
    """Return (ats_type, canonical-ish careers url) if url is a known ATS board."""
    low = (url or "").lower()
    for ats, needle in ATS_SUBSTRINGS:
        if needle in low:
            return ats, url
    return None


class Sweeper:
    def __init__(self, deadline_ts: float):
        self.sess = requests.Session()
        self.sess.headers.update({"User-Agent": UA})
        self.deadline = deadline_ts
        self.companies: dict[str, dict] = {}
        self.load_existing()
        self.requests = 0
        self.sg_jobs = 0

    # -- persistence ---------------------------------------------------
    def load_existing(self) -> None:
        if os.path.exists(RAW_OUT):
            try:
                for e in json.load(open(RAW_OUT)):
                    k = _norm(e.get("company_name", ""))
                    if k:
                        self.companies[k] = e
            except Exception:
                pass

    def write(self) -> None:
        os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
        tmp = RAW_OUT + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(list(self.companies.values()), fh, indent=1, ensure_ascii=False)
        os.replace(tmp, RAW_OUT)

    # -- http ----------------------------------------------------------
    def get_json(self, url: str, params: dict) -> dict | None:
        for attempt in range(3):
            try:
                r = self.sess.get(url, params=params, timeout=25)
                if r.status_code in (403, 429):
                    wait = 30 if attempt < 2 else 0
                    print(f"  [sg] {r.status_code} on {url} params={params} "
                          f"(attempt {attempt + 1}); sleeping {wait}s", file=sys.stderr, flush=True)
                    if wait:
                        time.sleep(wait)
                        continue
                    return None
                r.raise_for_status()
                self.requests += 1
                return r.json()
            except Exception as e:
                if attempt == 2:
                    print(f"  [sg] GET {url} {params} failed: {e}", file=sys.stderr, flush=True)
                    return None
                time.sleep(5)
        return None

    # -- merging -------------------------------------------------------
    def add_job(self, job: dict) -> bool:
        if not _is_sg(job):
            return False
        name = (job.get("companyName") or "").strip()
        if not name:
            return False
        self.sg_jobs += 1
        key = _norm(name)
        slug = (job.get("companySlug") or "").strip()
        title = (job.get("title") or "").strip()
        link = (job.get("applicationLink") or "").strip()
        locs = job.get("locationRestrictions") or []

        entry = self.companies.get(key)
        if entry is None:
            entry = {
                "company_name": name,
                "career_page_url": f"https://himalayas.app/companies/{slug}" if slug else "",
                "website": "",
                "domain_hint": "",
                "ats_type": "unknown",
                "source_platform": "sg_himalayas",
                "location": "Singapore",
                "himalayas_slug": slug,
                "sg_job_count": 0,
                "example_titles": [],
                "locations": [],
                "sg_locations": [],
            }
            self.companies[key] = entry
        # fill missing pieces
        if not entry.get("himalayas_slug") and slug:
            entry["himalayas_slug"] = slug
        if not entry.get("career_page_url") and slug:
            entry["career_page_url"] = f"https://himalayas.app/companies/{slug}"
        entry["sg_job_count"] = entry.get("sg_job_count", 0) + 1
        if title and len(entry.get("example_titles", [])) < 6 and title not in entry.get("example_titles", []):
            entry.setdefault("example_titles", []).append(title)
        for loc in locs:
            if loc and loc not in entry.get("locations", []) and len(entry.get("locations", [])) < 12:
                entry.setdefault("locations", []).append(loc)
            if loc and "singapore" in loc.lower() and loc not in entry.get("sg_locations", []):
                entry.setdefault("sg_locations", []).append(loc)
        # external ATS apply links beat the himalayas placeholder
        if link and "himalayas.app" not in link:
            hit = _ats_from_url(link)
            if hit:
                ats, _ = hit
                if entry.get("ats_type") in ("", "unknown"):
                    entry["ats_type"] = ats
                if not entry.get("career_page_url") or "himalayas.app/companies/" in entry.get("career_page_url", ""):
                    p = urlparse(link)
                    entry["career_page_url"] = f"{p.scheme}://{p.netloc}"
            else:
                if not entry.get("website"):
                    p = urlparse(link)
                    if p.scheme and p.netloc and "himalayas" not in p.netloc:
                        entry["website"] = f"{p.scheme}://{p.netloc}"
        return True

    # -- phases --------------------------------------------------------
    def sweep_keywords(self) -> None:
        since_write = 0
        start = int(os.environ.get("SG_START_INDEX", "0"))
        for kw in KEYWORDS[start:]:
            if time.time() > self.deadline:
                print("[sg] deadline hit during keyword sweep", flush=True)
                return
            page = 1
            total = 0
            got_sg = 0
            while page <= MAX_PAGES_PER_KEYWORD:
                if time.time() > self.deadline:
                    return
                data = self.get_json(HIMALAYAS_API, {
                    "q": kw, "country": "SG", "page": page, "limit": PAGE_SIZE,
                })
                if not data:
                    break
                jobs = data.get("jobs") or []
                total = data.get("totalCount") or 0
                if not jobs:
                    break
                for j in jobs:
                    if self.add_job(j):
                        got_sg += 1
                if page * PAGE_SIZE >= total:
                    break
                page += 1
                time.sleep(SLEEP)
            since_write += 1
            print(f"  [sg] kw={kw!r}: total={total} pages={page - 1} sg_companies={len(self.companies)} "
                  f"(+{got_sg} sg jobs this kw)", flush=True)
            if since_write >= CHECKPOINT_EVERY:
                self.write()
                since_write = 0
        self.write()

    def sweep_feed(self) -> None:
        data = self.get_json(HIMALAYAS_FEED, {"limit": PAGE_SIZE})
        pages = 0
        while data and time.time() < self.deadline:
            cursor = data.get("nextCursor")
            for j in data.get("jobs") or []:
                self.add_job(j)
            pages += 1
            if pages % 100 == 0:
                self.write()
                print(f"  [sg] feed page {pages}: {len(self.companies)} companies, "
                      f"{self.sg_jobs} sg jobs", flush=True)
            if not cursor:
                break
            data = self.get_json(HIMALAYAS_FEED, {"limit": PAGE_SIZE, "cursor": cursor})
            time.sleep(0.3)
        self.write()
        print(f"[sg] feed filler stopped after {pages} pages", flush=True)


def main() -> int:
    budget = int(os.environ.get("SG_SWEEP_SECONDS", "1500"))
    deadline = time.time() + budget
    sw = Sweeper(deadline)
    print(f"[sg] keyword sweep over {len(KEYWORDS)} slices (budget {budget}s) …", flush=True)
    sw.sweep_keywords()
    print(f"[sg] after keywords: {len(sw.companies)} companies, {sw.sg_jobs} sg jobs, "
          f"{sw.requests} requests", flush=True)
    remaining = deadline - time.time()
    if remaining > 120:
        print(f"[sg] feed filler sweep with {remaining:.0f}s left …", flush=True)
        sw.sweep_feed()
    sw.write()
    n_career = sum(1 for e in sw.companies.values() if e.get("career_page_url"))
    print(f"[sg] DONE: {len(sw.companies)} companies -> {RAW_OUT} "
          f"({n_career} with career_page_url, {sw.requests} requests)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
