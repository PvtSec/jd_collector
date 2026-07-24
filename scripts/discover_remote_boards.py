#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RAW_OUT = os.path.join(DATA, "raw", "agent14_remote.json")
CACHE = os.path.join(DATA, ".cache_remote")
UA = "Mozilla/5.0 (job-auto remote-board discovery; research)"

REMOTEOK_API = "https://remoteok.com/api"
WWR_RSS = "https://weworkremotely.com/remote-jobs.rss"
REMOTIVE_API = "https://remotive.com/api/remote-jobs?limit=1000"

ATS_HOST_MARKERS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "personio.com", "teamtailor.com", "rippling.com",
    "breezy.hr", "onlyfy.jobs", "myworkdayjobs.com", "pinpointhq.com",
    "trinethire.com", "applytojob.com", "bamboohr.com", "comeet.com",
    "jobvite.com", "recruitee.com", "catsone.com", "hireology.com",
    "niceboard.com", "freshteam.com",
]

# title separators used by WWR ("Company: Role") and others
_TITLE_SEP = re.compile(r"\s*[:—–\-|]\s*")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _is_ats_url(url: str) -> bool:
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


def _get(url: str, timeout: int = 25) -> str:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept": "application/json, application/rss+xml, */*"})
    r.raise_for_status()
    return r.text


def _company_from_title(title: str) -> str:
    if not title:
        return ""
    # split on the FIRST strong separator
    for sep in [":", "—", "–", " | "]:
        if sep in title:
            head = title.split(sep, 1)[0].strip()
            if 2 <= len(head) <= 60:
                return head
    # fall back to first ' - ' only if it yields a short head
    m = _TITLE_SEP.split(title, 1)
    if len(m) > 1 and 2 <= len(m[0].strip()) <= 60:
        return m[0].strip()
    return ""


def from_remoteok() -> list[dict]:
    out = []
    cp = os.path.join(CACHE, "remoteok.json")
    txt = _cache_get(cp, 6 * 3600)
    if txt is None:
        try:
            txt = _get(REMOTEOK_API)
            _cache_put(cp, txt)
            time.sleep(0.5)
        except Exception as e:
            print(f"[remote] remoteok fetch failed: {e}")
            return out
    try:
        data = json.loads(txt)
    except Exception:
        return out
    if isinstance(data, list):
        for j in data:
            if not isinstance(j, dict) or "company" not in j:
                continue  # skip the leading legal-notice object
            name = (j.get("company") or "").strip()
            if not name:
                continue
            rec = {"company_name": name, "source_platform": "remoteok"}
            url = (j.get("url") or "").strip()
            if url and url.startswith("http") and _is_ats_url(url):
                rec["career_page_url"] = url
            out.append(rec)
    print(f"[remote] remoteok: {len(out)} companies")
    return out


def from_wwr() -> list[dict]:
    out = []
    cp = os.path.join(CACHE, "wwr.xml")
    txt = _cache_get(cp, 6 * 3600)
    if txt is None:
        try:
            txt = _get(WWR_RSS)
            _cache_put(cp, txt)
            time.sleep(0.5)
        except Exception as e:
            print(f"[remote] wwr fetch failed: {e}")
            return out
    try:
        root = ET.fromstring(txt)
    except Exception as e:
        print(f"[remote] wwr parse failed: {e}")
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        name = _company_from_title(title)
        if not name:
            continue
        rec = {"company_name": name, "source_platform": "weworkremotely"}
        link = (item.findtext("link") or "").strip()
        # WWR links are internal (not ATS), so we only keep an ATS link if present
        if link and _is_ats_url(link):
            rec["career_page_url"] = link
        out.append(rec)
    print(f"[remote] wwr: {len(out)} companies")
    return out


def from_remotive() -> list[dict]:
    # Remotive is rate-limited; cache 24h and tolerate failure.
    out = []
    cp = os.path.join(CACHE, "remotive.json")
    txt = _cache_get(cp, 24 * 3600)
    if txt is None:
        try:
            txt = _get(REMOTIVE_API)
            _cache_put(cp, txt)
        except Exception as e:
            print(f"[remote] remotive fetch failed (rate-limited?): {e}")
            return out
    try:
        data = json.loads(txt)
    except Exception:
        return out
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        name = (j.get("company_name") or "").strip()
        if not name:
            continue
        rec = {"company_name": name, "source_platform": "remotive"}
        url = (j.get("url") or "").strip()
        if url and _is_ats_url(url):
            rec["career_page_url"] = url
        out.append(rec)
    print(f"[remote] remotive: {len(out)} companies")
    return out


def main():
    records = []
    records += from_remoteok()
    records += from_wwr()
    records += from_remotive()

    # dedupe within run (keep a career_page_url if any source had one)
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
    print(f"[remote] {added} new + {len(existing)} existing -> {len(merged)} records -> {RAW_OUT}")
    return merged


if __name__ == "__main__":
    main()