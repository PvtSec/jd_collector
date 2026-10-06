#!/usr/bin/env python3
"""SG-prioritized slug probing.

discover_slugs.py walks all of companies.json in sort order; after a big
country sweep that drowns the new entries. This variant probes only
companies tagged with an sg_* source_platform, website-bearing ones first
(a real domain is the strongest predictor of a greenhouse/lever/ashby
board; "Pte Ltd" SME name-only rows rarely have one), and adds
website-domain-derived slug candidates alongside the name-derived ones.

Idempotent: merges into data/discovered_slugs.json (re-run consolidate.py
afterwards to apply). Bounded by JOBAUTO_SG_PROBE_SECONDS (default 2700)
and polite: ≤8 req/s across workers.
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from discover_slugs import PROBES, BOARD_URL, candidates, save_discovered  # noqa: E402

DATA = os.path.join(os.path.dirname(HERE), "data")
SG_TAGS = {
    "sg_himalayas", "sg_e27", "sg_mcf", "sg_smartrecruiters", "sg_yc",
    "sg_gallery", "sg_awesome", "sg_vc", "sg_mas", "sg_wiki", "sg_gov",
    "sg_jobstreet", "sg_cult", "sg_wellfound", "sg_startupjobs", "sg_greenhouse",
}
# probe rougher tags only when they carry a website (see docstring)
TAG_PRIORITY = {"sg_vc": 0, "sg_yc": 1, "sg_gallery": 1, "sg_awesome": 1,
                "sg_e27": 2, "sg_himalayas": 2, "sg_mcf": 3, "sg_wellfound": 3,
                "sg_cult": 3, "sg_mas": 3, "sg_wiki": 3, "sg_gov": 3,
                "sg_jobstreet": 4, "sg_startupjobs": 4}


def domain_candidates(url: str) -> list[str]:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return []
    parts = host.split(".")
    sub = parts[0] if len(parts) >= 3 else ""
    dom = parts[-2] if len(parts) >= 2 else host
    out = []
    for c in (dom, sub):
        c = re.sub(r"[^a-z0-9]", "", c or "")
        if len(c) >= 3:
            out.append(c)
    return list(dict.fromkeys(out))


def main() -> None:
    budget = float(os.environ.get("JOBAUTO_SG_PROBE_SECONDS", "2700"))
    deadline = time.monotonic() + budget
    comps = json.load(open(os.path.join(DATA, "companies.json")))
    seen_slugs = set()  # one slug belongs to one company; skip repeats
    targets = []
    for c in comps:
        if c.get("ats_source") != "guess" or c.get("ats_type") not in ("unknown",):
            continue
        tags = SG_TAGS & set(c.get("source_platforms") or [])
        if not tags:
            continue
        prio = min(TAG_PRIORITY.get(t, 5) for t in tags)
        has_site = bool((c.get("website") or "").strip())
        if not has_site and prio >= 2:
            continue  # name-only for weak tags: skip, scheduler covers later
        targets.append((prio, 0 if has_site else 1, c["company_name"], c.get("website") or ""))
    targets.sort()
    print(f"probing {len(targets)} sg-tagged companies (gh/lv/ashby), budget {budget:.0f}s")

    found = []
    lock_deadline = [deadline]
    out_path = os.path.join(DATA, "discovered_slugs.json")

    def probe_one(item):
        _, _, name, website = item
        if time.monotonic() > lock_deadline[0]:
            return None
        cands = list(dict.fromkeys(candidates(name) + domain_candidates(website)))
        for ats in ("greenhouse", "lever", "ashby"):
            for slug in cands[:6]:
                time.sleep(0.12)
                n = PROBES[ats](slug)
                if n is not None:
                    return {"company_name": name, "ats": ats, "slug": slug,
                            "career_page_url": BOARD_URL[ats](slug), "jobs_found": n}
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(probe_one, targets):
            if time.monotonic() > lock_deadline[0]:
                ex.shutdown(wait=False, cancel_futures=True)
                break
            if res:
                if res["slug"] in seen_slugs:
                    continue
                seen_slugs.add(res["slug"])
                found.append(res)
                print(f"  FOUND  {res['company_name']:<34} -> {res['ats']:<10} "
                      f"slug={res['slug']:<22} jobs={res['jobs_found']}", flush=True)
            if len(found) and len(found) % 100 == 0:
                # checkpoint: merges into discovered_slugs.json so a kill loses
                # at most the last 100 (save_discovered is idempotent by name)
                save_discovered(found, out_path)
                found.clear()  # already persisted; avoid re-merging on next checkpoint
    total = save_discovered(found, out_path)
    print(f"\nsg slugs discovered this run; {total} total in discovered_slugs.json", flush=True)


if __name__ == "__main__":
    main()
