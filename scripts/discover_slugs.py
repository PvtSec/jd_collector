#!/usr/bin/env python3
"""Discover real ATS board slugs for companies whose ATS is known but slug unknown.

For each `ats_source:guess` row with ats in {greenhouse, lever, ashby} (and unknown
rows), generate candidate slugs from the company name and probe the public board API.
On a hit (board exists / jobs > 0), record (ats, slug, board_url) to
data/discovered_slugs.json, which consolidate.py then merges into companies.json.

Read-only: only GETs board APIs, never submits anything. Be polite: small delay,
descriptive UA, bounded candidates.
"""
import json, re, time, os
import requests

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
UA = "Mozilla/5.0 (job-auto slug-discovery; contact: <your-email>))"
GH = "https://boards-api.greenhouse.io/v1/boards/{}/jobs?per_page=1"
LV = "https://api.lever.co/v0/postings/{}?mode=json&limit=1"
ASH = "https://jobs.ashbyhq.com/{}"

SUFFIXES = ["inc", "labs", "ai", "technologies", "technology", "systems", "group",
            "corp", "corporation", "llc", "co", "gmbh", "industries", "app",
            "software", "ventures", "health", "science", "sciences"]


def candidates(name: str) -> list[str]:
    n = re.sub(r"\s*\(.*?\)\s*", " ", name).strip().lower()
    base = re.sub(r"[^a-z0-9]", "", n)
    if not base:
        return []
    cands = [base]
    # also try tokens from inside parentheticals, e.g. "Posit (formerly RStudio)" -> rstudio
    for inside in re.findall(r"\(([^)]+)\)", name):
        for w in re.sub(r"[^a-z0-9 ]", " ", inside.lower()).split():
            if w not in ("formerly", "inc", "corp", "the", "an", "a"):
                cands.append(w)
    for suf in SUFFIXES:
        if base.endswith(suf) and len(base) > len(suf) + 2:
            cands.append(base[: -len(suf)])
    # drop trailing digits variant (e.g. unit410 -> unit)
    cands.append(re.sub(r"\d+$", "", base))
    return list(dict.fromkeys([c for c in cands if c]))


def _norm_name(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def save_discovered(found: list[dict], out: str) -> int:
    """Merge `found` into discovered_slugs.json keyed by normalized company name.

    Idempotent: re-running never erases prior discoveries (fixes the old 'w' overwrite
    that would have wiped the 35 existing entries on a standalone re-run).
    """
    existing = {}
    if os.path.exists(out):
        for r in json.load(open(out)):
            existing[_norm_name(r["company_name"])] = r
    for r in found:
        existing[_norm_name(r["company_name"])] = r
    merged = list(existing.values())
    with open(out, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    return len(merged)


def probe_greenhouse(slug: str):
    try:
        r = requests.get(GH.format(slug), timeout=15, headers={"User-Agent": UA})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
        return len(jobs)
    except Exception:
        return None


def probe_lever(slug: str):
    try:
        r = requests.get(LV.format(slug), timeout=15, headers={"User-Agent": UA})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return len(data) if isinstance(data, list) else None
    except Exception:
        return None


def probe_ashby(slug: str):
    try:
        r = requests.get(ASH.format(slug), timeout=20,
                         headers={"User-Agent": UA, "Accept": "text/html"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        # quick check without full balance-parse: organization must be present
        if '"organization":null' in r.text or '"organization": null' in r.text:
            return None
        if '"jobPostings":[' in r.text:
            n = r.text.count('"id":"')  # rough posting count
            return max(1, n)
        return None
    except Exception:
        return None


PROBES = {"greenhouse": probe_greenhouse, "lever": probe_lever, "ashby": probe_ashby}
BOARD_URL = {
    "greenhouse": lambda s: f"https://boards.greenhouse.io/{s}",
    "lever": lambda s: f"https://jobs.lever.co/{s}",
    "ashby": lambda s: f"https://jobs.ashbyhq.com/{s}",
}


def discover():
    comps = json.load(open(os.path.join(DATA, "companies.json")))
    # target: guess rows with known standard ATS, plus unknown rows (probe all 3)
    targets = []
    for c in comps:
        if c["ats_source"] != "guess":
            continue
        if c["ats_type"] in ("greenhouse", "lever", "ashby"):
            targets.append((c, [c["ats_type"]]))
        elif c["ats_type"] == "unknown":
            targets.append((c, ["greenhouse", "lever", "ashby"]))
    print(f"probing {len(targets)} companies across greenhouse/lever/ashby...")

    found = []
    for c, ats_list in targets:
        cands = candidates(c["company_name"])
        if not cands:
            continue
        hit = None
        for ats in ats_list:
            for slug in cands:
                n = PROBES[ats](slug)
                if n is not None:
                    hit = (ats, slug, n)
                    break
            if hit:
                break
            time.sleep(0.15)
        if hit:
            ats, slug, n = hit
            found.append({
                "company_name": c["company_name"],
                "ats": ats,
                "slug": slug,
                "career_page_url": BOARD_URL[ats](slug),
                "jobs_found": n,
            })
            print(f"  FOUND  {c['company_name']:<26} -> {ats:<10} slug={slug:<22} jobs={n}")
        else:
            print(f"  miss   {c['company_name']:<26} (was {c['ats_type']})")
        time.sleep(0.2)

    out = os.path.join(DATA, "discovered_slugs.json")
    total = save_discovered(found, out)
    print(f"\n{len(found)} slugs discovered this run; {total} total in {out}")
    return found


if __name__ == "__main__":
    discover()