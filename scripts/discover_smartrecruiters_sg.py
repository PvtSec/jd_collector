#!/usr/bin/env python3
"""Discover Singapore companies with a SmartRecruiters job board.

Source: the public search API behind jobs.smartrecruiters.com.

Notes on the endpoint (probed 2026-08-27):
  GET https://jobs.smartrecruiters.com/sr-jobs/search?limit=100&offset=N&keyword=K[&company=ID][&locationType=remote]
  - The old documented path /api/v1/search is 404. The Angular app ("sr-jobs-client-app")
    calls the relative path "sr-jobs/search" (see PostingService.URL in main.*.js).
  - The backend HONORS: limit (hard-capped to 100), keyword, company, locationType.
    It IGNORES: city / country / region / location / lat+lon filters (totalFound identical
    with and without) AND ALL PAGINATION (offset/from/page/... all echo offset:0 and return
    the same first 100 items). One query = the newest 100 matching postings, nothing more.
  - Workaround used here: keyword="Singapore" acts as a pseudo city filter (the keyword
    index includes the posting's location text; 1294 hits, ~99% located in sg), then a
    wide battery of role / brand / region keywords — each yields a DIFFERENT newest-100 —
    all filtered client-side to location.country == "sg" and unioned per company.
  - Each item carries company.identifier + company.name; the career page is
    https://jobs.smartrecruiters.com/{identifier} (200, redirects to careers. subdomain).

Output: data/raw/agentSG04_smartrecruiters_sg.json (JSON array, one entry per company).
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests

SEARCH_URL = "https://jobs.smartrecruiters.com/sr-jobs/search"
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw",
                        "agentSG04_smartrecruiters_sg.json")

PAGE = 100
SLEEP = 0.3
PAGES_PER_KEYWORD = 1        # server ignores offset: page 2+ always returns page 1

# Location proxies + role keywords (task-suggested set + tech roles) + SG-heavy brand
# guesses + region words. Multi-word keywords are OR'd by the backend, but ranking
# favours postings matching more terms, so "Singapore <role>" skews heavily sg.
KEYWORDS = [
    # pseudo-city sweeps (best yield)
    "Singapore",
    "Science Park Singapore",
    "Jurong",
    "Changi",
    "Singapur",
    "Singapura",
    "新加坡",
    # task-suggested role keywords, bare
    "software engineer",
    "developer",
    "security",
    "QA",
    "data",
    # more tech roles, bare
    "engineer",
    "DevOps",
    "cloud engineer",
    "data analyst",
    "data engineer",
    "cybersecurity",
    "SOC analyst",
    "penetration tester",
    "SDET",
    "platform engineer",
    "site reliability",
    "product manager",
    "internship",
    "graduate programme",
    # "Singapore <role>" combos (OR, but double-match ranks first)
    "Singapore software engineer",
    "Singapore developer",
    "Singapore security",
    "Singapore QA",
    "Singapore data",
    "Singapore engineer",
    "Singapore analyst",
    "Singapore cloud",
    "Singapore DevOps",
    "Singapore internship",
    "Singapore product",
    "Singapore technology",
    # region words that appear in sg-hq postings
    "APAC",
    "ASEAN",
    # SG-heavy employer guesses (client-side country filter keeps only sg postings)
    "DBS",
    "Grab",
    "Shopee",
    "Singtel",
    "OCBC",
    "ST Engineering",
    "NCS",
    "GovTech",
    "Micron",
    "Dyson",
    "Trafigura",
    "Olam",
    "Flex",
    "Seagate",
    "GIC",
    "Temasek",
    "SIA Engineering",
    "SingPost",
    "ComfortDelGro",
    "SATS",
    "Keppel",
    "Sembcorp",
    "Yara",
    "Veson",
    "Zurich Insurance",
    "Prudential",
    "AIA",
    "Manulife",
    "Riotinto",
    # cyber / QA / tech role words (this repo's matcher targets these)
    "backend",
    "frontend",
    "full stack",
    "Java developer",
    "Python developer",
    "test engineer",
    "quality assurance",
    "automation tester",
    "network engineer",
    "systems administrator",
    "Linux administrator",
    "database administrator",
    "solutions architect",
    "IT support",
    "business analyst",
    "scrum master",
    "machine learning",
    "GRC",
    "compliance analyst",
    "risk analyst",
    "incident response",
    "penetration testing",
    "vulnerability",
    "threat intelligence",
    "zero trust",
    "kubernetes",
    "terraform",
    # more Singapore combos
    "Singapore backend",
    "Singapore frontend",
    "Singapore full stack",
    "Singapore Java",
    "Singapore Python",
    "Singapore testing",
    "Singapore network",
    "Singapore Linux",
    "Singapore machine learning",
    "Singapore compliance",
    "Singapore risk",
    "Singapore incident",
    "Singapore identity",
    "Singapore junior",
    "Singapore operations",
    "Singapore finance",
    "Singapore Internship",
]

# Extra sweeps: keyword=Singapore with the one location filter the backend honors.
REMOTE_COMBOS = [
    {"keyword": "Singapore", "locationType": v}
    for v in ("remote", "onsite", "hybrid", "office")
]


def is_sg(item: dict) -> bool:
    loc = item.get("location") or {}
    country = (loc.get("country") or "").lower()
    city = (loc.get("city") or "").lower()
    region = (loc.get("region") or "").lower()
    if country == "sg":
        return True
    return "singapore" in city or "singapore" in region


def fetch(params: dict) -> dict | None:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    for attempt in range(3):
        try:
            r = requests.get(SEARCH_URL, params=params, headers=headers, timeout=40)
        except requests.RequestException as exc:
            print(f"  network error: {exc}", flush=True)
            time.sleep(10)
            continue
        if r.status_code in (403, 429):
            wait = 30 if attempt else 30
            print(f"  HTTP {r.status_code}; sleeping {wait}s "
                  f"(attempt {attempt + 1}/3)", flush=True)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}; giving up on this request", flush=True)
            return None
        try:
            return r.json()
        except ValueError:
            print("  non-JSON response; giving up on this request", flush=True)
            return None
    return None


def sweep() -> None:
    companies: dict[str, dict] = {}
    jobs_scanned = 0
    dirty = 0

    def flush(force: bool = False) -> None:
        nonlocal dirty
        if not dirty:
            return
        entries = sorted(companies.values(), key=lambda e: e["company_name"].lower())
        tmp = OUT_PATH + ".tmp"
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, OUT_PATH)
        dirty = 0
        print(f"  [wrote {len(entries)} companies -> {OUT_PATH}]", flush=True)

    def run(params: dict, label: str) -> None:
        nonlocal jobs_scanned, dirty
        data = fetch(params)
        time.sleep(SLEEP)
        if data is None:
            return
        content = data.get("content") or []
        kept = 0
        for item in content:
            jobs_scanned += 1
            if not is_sg(item):
                continue
            kept += 1
            comp = item.get("company") or {}
            ident = comp.get("identifier")
            name = comp.get("name")
            if not ident or not name:
                continue
            kw = label
            ent = companies.get(ident)
            if ent is None:
                companies[ident] = {
                    "company_name": name,
                    "career_page_url": f"https://jobs.smartrecruiters.com/{ident}",
                    "website": "",
                    "domain_hint": "",
                    "ats_type": "smartrecruiters",
                    "board_token": ident,
                    "source_platform": "sg_smartrecruiters",
                    "location": "Singapore",
                    "sg_jobs_seen": 1,
                    "match_keywords": [kw],
                    "sample_titles": [(item.get("name") or "").strip()][:1],
                }
                dirty += 1
            else:
                ent["sg_jobs_seen"] += 1
                if kw not in ent["match_keywords"]:
                    ent["match_keywords"].append(kw)
                if len(ent["sample_titles"]) < 3:
                    t = (item.get("name") or "").strip()
                    if t and t not in ent["sample_titles"]:
                        ent["sample_titles"].append(t)
        print(f"kw={label!r} total={data.get('totalFound')} got={len(content)} "
              f"sg_kept={kept} companies={len(companies)}", flush=True)

    for kw in KEYWORDS:
        run({"limit": PAGE, "keyword": kw}, kw)
        if dirty >= 100:
            flush()
    for combo in REMOTE_COMBOS:
        params = dict(combo)
        params["limit"] = PAGE
        run(params, f"{combo['keyword']}[{combo.get('locationType')}]")
        if dirty >= 100:
            flush()
    flush(force=True)
    print(f"DONE companies={len(companies)} jobs_scanned={jobs_scanned}", flush=True)


if __name__ == "__main__":
    sys.exit(sweep())
