#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RAW_OUT = os.path.join(DATA, "raw", "agent16_simplify.json")
CACHE = os.path.join(DATA, ".cache_simplify")
UA = "Mozilla/5.0 (job-auto simplify-listing discovery; research)"

# (repo, branch, path, source_platform)
SOURCES = [
    ("SimplifyJobs/New-Grad-Positions", "dev", ".github/scripts/listings.json", "simplify-newgrad"),
    ("SimplifyJobs/Summer2026-Internships", "dev", ".github/scripts/listings.json", "simplify-intern"),
]

# ATS hosts whose board_token consolidate.py can derive cleanly from the URL
# (PATH-token: first path segment; SUBDOMAIN-token: first subdomain). Workday
# excluded (needs careers-root URL, not a job URL).
ATS_HOST_MARKERS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "personio.com", "teamtailor.com", "ats.rippling.com",
    "breezy.hr", "onlyfy.jobs",
]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _is_clean_ats_url(url: str) -> bool:
    return any(m in url.lower() for m in ATS_HOST_MARKERS)


def _cache_get(path: str, max_age: float):
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age:
        try:
            return open(path, encoding="utf-8").read()
        except Exception:
            return None
    return None


def _cache_put(path: str, text: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)
    except Exception:
        pass


def _fetch_listings(repo: str, branch: str, path: str, source_platform: str) -> list[dict]:
    cp = os.path.join(CACHE, repo.replace("/", "__") + ".json")
    txt = _cache_get(cp, 24 * 3600)
    if txt is None:
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": UA, "Accept": "application/json"})
            r.raise_for_status()
            txt = r.text
            _cache_put(cp, txt)
        except Exception as e:
            print(f"[simplify] {repo}: fetch failed: {e}")
            return []
    try:
        data = json.loads(txt)
    except Exception as e:
        print(f"[simplify] {repo}: parse failed: {e}")
        return []
    if not isinstance(data, list):
        print(f"[simplify] {repo}: not a list ({type(data).__name__})")
        return []

    # group active apply-URLs by company (pick the first clean-ATS URL, if any)
    by_company: dict[str, dict] = {}
    n_listings = 0
    for r in data:
        if not isinstance(r, dict) or not r.get("active"):
            continue
        name = (r.get("company_name") or "").strip()
        if not name or len(name) > 100:
            continue
        n_listings += 1
        k = _norm(name)
        if not k:
            continue
        url = (r.get("url") or "").strip()
        rec = by_company.get(k)
        if rec is None:
            rec = {"company_name": name, "source_platform": source_platform}
            by_company[k] = rec
        if "career_page_url" not in rec and url.startswith("http") and _is_clean_ats_url(url):
            rec["career_page_url"] = url
    print(f"[simplify] {repo}: {n_listings} active listings -> {len(by_company)} companies "
          f"({sum(1 for r in by_company.values() if 'career_page_url' in r)} with ATS URL)")
    return list(by_company.values())


def main():
    os.makedirs(CACHE, exist_ok=True)
    records: list[dict] = []
    for repo, branch, path, tag in SOURCES:
        records += _fetch_listings(repo, branch, path, tag)
        time.sleep(0.5)

    # dedupe across sources (prefer a record that already has career_page_url)
    by_name: dict[str, dict] = {}
    for r in records:
        k = _norm(r.get("company_name", ""))
        if not k:
            continue
        if k not in by_name:
            by_name[k] = r
        elif "career_page_url" in r and "career_page_url" not in by_name[k]:
            by_name[k]["career_page_url"] = r["career_page_url"]
    deduped = list(by_name.values())

    existing: list[dict] = []
    if os.path.exists(RAW_OUT):
        try:
            existing = json.load(open(RAW_OUT, encoding="utf-8"))
        except Exception:
            existing = []
    ex_seen = {_norm(r.get("company_name", "")) for r in existing}
    merged = list(existing)
    added = 0
    for r in deduped:
        k = _norm(r.get("company_name", ""))
        if k and k not in ex_seen:
            ex_seen.add(k)
            merged.append(r)
            added += 1
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    with open(RAW_OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    n_ats = sum(1 for r in merged if "career_page_url" in r)
    print(f"[simplify] {added} new + {len(existing)} existing -> {len(merged)} records "
          f"({n_ats} with ATS URL) -> {RAW_OUT}")
    return merged


if __name__ == "__main__":
    main()