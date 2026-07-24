#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dlib  # noqa: E402

REPO_RAW = "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data"

# ats -> (filename, url_builder(slug) -> url)
SOURCES: dict[str, tuple[str, callable]] = {
    "greenhouse": ("greenhouse_companies.json", lambda s: f"https://boards.greenhouse.io/{s}"),
    "lever":      ("lever_companies.json",      lambda s: f"https://jobs.lever.co/{s}"),
    "ashby":      ("ashby_companies.json",      lambda s: f"https://jobs.ashbyhq.com/{s}"),
    "bamboohr":   ("bamboohr_companies.json",   lambda s: f"https://{s}.bamboohr.com/careers"),
    # workday handled specially (slug|cluster|endpoint rows)
    "workday":    ("workday_companies.json",    None),
}


def pretty_name(slug: str) -> str:
    s = slug.replace("-", " ").replace("_", " ").strip()
    # title-case but keep all-caps tokens (e.g. 'io', 'ai') readable
    return " ".join(w.capitalize() if w.islower() else w for w in s.split()) or slug


def fetch_json(fname: str) -> list:
    url = f"{REPO_RAW}/{fname}"
    req = urllib.request.Request(url, headers={"User-Agent": "jobauto-discovery/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def record(ats: str, name: str, url: str, stats: dict) -> None:
    rec = {"company_name": name, "career_page_url": url, "ats_type": ats}
    is_new, reliable, hstatus, became = dlib.record_company(
        rec, source=f"gh-agg-{ats}", force_http=True, recheck=False)
    stats["seen"] += 1
    if is_new:
        stats["new"] += 1
    if reliable and (is_new or became):
        stats["new_reliable"] += 1
        dlib.append_log(f"gh-agg-{ats}", rec, hstatus)
    if stats["seen"] % 2000 == 0:
        print(f"  [{ats}] seen={stats['seen']} new={stats['new']} new_reliable={stats['new_reliable']}", flush=True)


def run_ats(ats: str) -> dict:
    fname, builder = SOURCES[ats]
    print(f"== {ats}: fetching {fname} ==", flush=True)
    data = fetch_json(fname)
    print(f"   {len(data)} rows", flush=True)
    stats = {"seen": 0, "new": 0, "new_reliable": 0}

    if ats == "workday":
        # rows: "slug|cluster|endpoint" -> one record per unique slug (first endpoint wins)
        seen_slug: set[str] = set()
        for row in data:
            if not isinstance(row, str) or "|" not in row:
                continue
            parts = row.split("|")
            if len(parts) < 3:
                continue
            slug, cluster, endpoint = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not slug or not cluster or slug in seen_slug:
                continue
            seen_slug.add(slug)
            url = f"https://{slug}.{cluster}.myworkdayjobs.com/{endpoint}"
            record("workday", pretty_name(slug), url, stats)
    else:
        for slug in data:
            if not isinstance(slug, str) or not slug.strip():
                continue
            slug = slug.strip()
            record(ats, pretty_name(slug), builder(slug), stats)

    print(f"   done: seen={stats['seen']} new={stats['new']} new_reliable={stats['new_reliable']}", flush=True)
    return stats


def main() -> int:
    targets = sys.argv[1:] or list(SOURCES)
    t0 = time.time()
    grand = {"seen": 0, "new": 0, "new_reliable": 0}
    for ats in targets:
        if ats not in SOURCES:
            print(f"  unknown ATS '{ats}', skip", flush=True)
            continue
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