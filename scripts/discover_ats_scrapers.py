#!/usr/bin/env python3
from __future__ import annotations
import csv
import io
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dlib  # noqa: E402

REPO_RAW = "https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/ats-companies"

# engine-supported ATS (must be in dlib ATS_HOST_RULES) -> csv filename
SUPPORTED = {
    "greenhouse":     "greenhouse.csv",
    "lever":          "lever.csv",
    "ashby":          "ashby.csv",
    "bamboohr":       "bamboohr.csv",
    "smartrecruiters": "smartrecruiters.csv",
    "workable":       "workable.csv",
    "personio":       "personio.csv",
    "teamtailor":     "teamtailor.csv",
    "rippling":       "rippling.csv",
    "pinpoint":       "pinpoint.csv",
    "breezy":         "breezy.csv",
    "workday":        "workday.csv",
}

# ATS whose slug column is "<tenant>/<endpoint>" -> name uses tenant only
SLUG_HAS_PATH = {"workday"}


def pretty_name(slug: str) -> str:
    s = slug.replace("-", " ").replace("_", " ").strip()
    return " ".join(w.capitalize() if w.islower() else w for w in s.split()) or slug


def fetch_csv(fname: str) -> str:
    url = f"{REPO_RAW}/{fname}"
    req = urllib.request.Request(url, headers={"User-Agent": "jobauto-discovery/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def run_ats(ats: str) -> dict:
    fname = SUPPORTED[ats]
    print(f"== {ats}: fetching {fname} ==", flush=True)
    try:
        text = fetch_csv(fname)
    except Exception as e:
        print(f"   FETCH FAIL: {e}", flush=True)
        return {"seen": 0, "new": 0, "new_reliable": 0}
    rows = list(csv.DictReader(io.StringIO(text)))
    print(f"   {len(rows)} rows", flush=True)
    stats = {"seen": 0, "new": 0, "new_reliable": 0}
    seen_slug: set[str] = set()
    for row in rows:
        slug = (row.get("slug") or "").strip()
        url = (row.get("url") or "").strip()
        if not slug or not url or slug in seen_slug:
            continue
        seen_slug.add(slug)
        # slug-derived name keeps norm_key consistent across sources (no dupes).
        # workday slug is "<tenant>/<endpoint>" -> name from tenant only so it
        # matches the Feashliaa workday naming (pretty_name(tenant)).
        name_slug = slug.split("/")[0] if ats in SLUG_HAS_PATH else slug
        name = pretty_name(name_slug)
        rec = {"company_name": name, "career_page_url": url, "ats_type": ats}
        is_new, reliable, hstatus, became = dlib.record_company(
            rec, source=f"ats-scrapers-{ats}", force_http=True, recheck=False)
        stats["seen"] += 1
        if is_new:
            stats["new"] += 1
        if reliable and (is_new or became):
            stats["new_reliable"] += 1
            dlib.append_log(f"ats-scrapers-{ats}", rec, hstatus)
        if stats["seen"] % 2000 == 0:
            print(f"  [{ats}] seen={stats['seen']} new={stats['new']} new_reliable={stats['new_reliable']}", flush=True)
    print(f"   done: seen={stats['seen']} new={stats['new']} new_reliable={stats['new_reliable']}", flush=True)
    return stats


def main() -> int:
    targets = [a for a in (sys.argv[1:] or list(SUPPORTED)) if a in SUPPORTED]
    t0 = time.time()
    grand = {"seen": 0, "new": 0, "new_reliable": 0}
    for ats in targets:
        s = run_ats(ats)
        for k in grand:
            grand[k] += s[k]
    print(f"\nTOTAL seen={grand['seen']} new={grand['new']} new_reliable={grand['new_reliable']} "
          f"elapsed={time.time()-t0:.1f}s", flush=True)
    snap = dlib.snapshot()
    print(f"reliable_count={snap['reliable_count']}/{snap['goal']} total_unique={snap['total_unique']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())