#!/usr/bin/env python3
"""Discover companies from the Himalayas public jobs API (https://himalayas.app).

The Himalayas API exposes two endpoints:
  - /jobs/api          — full unfiltered jobs feed (paginated, max 20/page)
  - /jobs/api/search   — filtered search by query, country, seniority, etc.

Strategy:
  1. Search for target-role jobs (pentest, SDET, QA, security) across multiple
     role queries to surface companies that are actively hiring for our roles.
  2. Also sweep the full jobs feed (offset-based pagination) to collect ALL
     companies with remote jobs — even if they're not currently hiring for
     target roles, their ATS board slug may match what we need.
  3. For each NEW company (not already in companies.json with a board token),
     derive slug candidates and probe greenhouse/lever/ashby.

The job listings also include locationRestrictions (country array), so we can
tag India/EU/APAC/worldwide-friendly companies right in the seed data.

Output: data/raw/agent10_himalayas.json — picked up by scripts/consolidate.py.
Re-runnable, concurrent, skips names already in companies.json or in prior seed.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import requests

# allow `import discover_slugs` when run as a script (scripts/ is on sys.path[0])
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from discover_slugs import candidates, PROBES, BOARD_URL  # noqa: E402

DATA = os.environ.get("JOBAUTO_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
RAW_OUT = os.path.join(DATA, "raw", "agent10_himalayas.json")
COMPANIES_JSON = os.path.join(DATA, "companies.json")

HIMALAYAS_API = "https://himalayas.app/jobs/api/search"
HIMALAYAS_FEED = "https://himalayas.app/jobs/api"
UA = "Mozilla/5.0 (job-auto himalayas-discovery; research)"
MAX_WORKERS = 16
PROBE_DELAY = 0.1

# Target role queries: core roles first, then adjacent
ROLE_QUERIES = [
    # tier, query
    ("core", "penetration tester"),
    ("core", "SDET"),
    ("core", "QA automation"),
    ("core", "QA engineer"),
    ("core", "test automation"),
    ("adjacent", "security engineer"),
    ("adjacent", "application security"),
    ("adjacent", "devsecops"),
    ("adjacent", "offensive security"),
]

# Titles that are clearly NOT IC target roles even if keyword matches
EXCLUDE_RE = re.compile(
    r"\b(manager|director|head of|vp|intern|principal|chief|internship)\b", re.I
)

# Country-targeted sweeps (ISO alpha-2 codes work in the Himalayas `country`
# param). These surface companies HQ'd/hiring in regions underrepresented in
# the global role sweep — Singapore first, then SE Asia / India / AU / EU / JP.
# Each country runs the full ROLE_QUERIES list so we only collect companies
# actively hiring for our target roles IN that country.
COUNTRY_QUERIES = [
    "SG",   # Singapore
    "IN",   # India
    "AU",   # Australia
    "NZ",   # New Zealand
    "DE",   # Germany
    "NL",   # Netherlands
    "IE",   # Ireland
    "JP",   # Japan
    "KR",   # South Korea
    "MY",   # Malaysia
    "ID",   # Indonesia
    "VN",   # Vietnam
    "PH",   # Philippines
    "TH",   # Thailand
    "HK",   # Hong Kong
    "TW",   # Taiwan
    "IL",   # Israel
    "ES",   # Spain
    "PL",   # Poland
    "CZ",   # Czechia
]


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def existing_slugged_names() -> set[str]:
    """Names already in companies.json WITH a confirmed board token — skip these."""
    names: set[str] = set()
    if not os.path.exists(COMPANIES_JSON):
        return names
    try:
        for c in json.load(open(COMPANIES_JSON)):
            if c.get("board_token") and c.get("ats_type") in PROBES:
                names.add(_norm(c.get("company_name", "")))
    except Exception:
        pass
    return names


def existing_seed_names(seed_path: str) -> set[str]:
    if not os.path.exists(seed_path):
        return set()
    try:
        return {_norm(s.get("company_name", "")) for s in json.load(open(seed_path)) if s.get("ats_type")}
    except Exception:
        return set()


def fetch_jobs(session: requests.Session, query: str, page: int = 1, limit: int = 20,
               country: str | None = None) -> tuple[list[dict], int]:
    """Fetch jobs from the Himalayas search API. Returns (jobs, total_count).

    `country` (ISO alpha-2, full name, or slug) restricts results to a country —
    used by sweep_countries to surface SG/APAC/EU companies specifically.
    """
    try:
        params: dict = {"q": query, "page": page, "limit": limit}
        if country:
            params["country"] = country
        r = session.get(
            HIMALAYAS_API,
            params=params,
            headers={"User-Agent": UA},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("jobs", []), data.get("totalCount", 0)
    except Exception as e:
        ctry = f", country={country!r}" if country else ""
        print(f"  [himalayas] search API error (q={query!r}{ctry}, page={page}): {e}", file=sys.stderr)
        return [], 0


def fetch_feed_page(session: requests.Session, offset: int = 0, limit: int = 20) -> tuple[list[dict], int]:
    """Fetch a page from the full jobs feed. Returns (jobs, total_count)."""
    try:
        r = session.get(
            HIMALAYAS_FEED,
            params={"offset": offset, "limit": limit},
            headers={"User-Agent": UA},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("jobs", []), data.get("totalCount", 0)
    except Exception as e:
        print(f"  [himalayas] feed API error (offset={offset}): {e}", file=sys.stderr)
        return [], 0


def sweep_target_roles(session: requests.Session) -> dict[str, dict]:
    """Search for target-role jobs and collect unique companies with location info."""
    companies: dict[str, dict] = {}  # norm_name -> {name, slug, locations, tier, roles}

    for tier, role in ROLE_QUERIES:
        page = 1
        total_seen = 0
        while True:
            jobs, total = fetch_jobs(session, role, page=page)
            if not jobs:
                break
            for j in jobs:
                title = (j.get("title") or "").strip()
                company = (j.get("companyName") or "").strip()
                if not company:
                    continue
                # Relevance gate: title should contain the search keyword
                low = title.lower()
                q = role.lower().replace(" ", "")
                if role.lower() not in low and q not in low.replace(" ", ""):
                    continue
                if EXCLUDE_RE.search(low):
                    continue

                key = _norm(company)
                locs = j.get("locationRestrictions") or []
                if key not in companies:
                    companies[key] = {
                        "name": company,
                        "slug": j.get("companySlug", ""),
                        "locations": set(locs),
                        "tier": tier,
                        "roles": {role},
                    }
                else:
                    companies[key]["locations"].update(locs)
                    companies[key]["roles"].add(role)
                    # core wins over adjacent
                    if tier == "core" and companies[key]["tier"] != "core":
                        companies[key]["tier"] = "core"

            total_seen = total
            if page * 20 >= total or not jobs:
                break
            page += 1
            time.sleep(0.3)

        print(f"  [himalayas] role={role!r}: {total_seen} total jobs", flush=True)

    # Convert sets to lists for JSON serialization
    for v in companies.values():
        v["locations"] = sorted(v["locations"])
        v["roles"] = sorted(v["roles"])
    return companies


def sweep_countries(session: requests.Session) -> dict[str, dict]:
    """Country-targeted role searches: for each country in COUNTRY_QUERIES, run
    the ROLE_QUERIES list filtered to that country. Collects companies actively
    hiring for target roles in SG/APAC/EU — regions under-collected by the
    global role sweep. Returns its own fresh dict (merged by the caller).
    """
    companies: dict[str, dict] = {}
    for country in COUNTRY_QUERIES:
        country_hits = 0
        for tier, role in ROLE_QUERIES:
            page = 1
            while True:
                jobs, total = fetch_jobs(session, role, page=page, country=country)
                if not jobs:
                    break
                for j in jobs:
                    title = (j.get("title") or "").strip()
                    company = (j.get("companyName") or "").strip()
                    if not company:
                        continue
                    low = title.lower()
                    q = role.lower().replace(" ", "")
                    if role.lower() not in low and q not in low.replace(" ", ""):
                        continue
                    if EXCLUDE_RE.search(low):
                        continue
                    key = _norm(company)
                    locs = j.get("locationRestrictions") or []
                    if key not in companies:
                        companies[key] = {
                            "name": company,
                            "slug": j.get("companySlug", ""),
                            "locations": set(locs),
                            "tier": tier,
                            "roles": {role},
                        }
                        country_hits += 1
                    else:
                        companies[key]["locations"].update(locs)
                        companies[key]["roles"].add(role)
                        if tier == "core" and companies[key]["tier"] != "core":
                            companies[key]["tier"] = "core"
                if page * 20 >= total or not jobs:
                    break
                page += 1
                time.sleep(0.3)
        print(f"  [himalayas] country={country}: +{country_hits} new companies", flush=True)
    # Convert sets to lists for JSON serialization (role sweep does this too)
    for v in companies.values():
        v["locations"] = sorted(v["locations"])
        v["roles"] = sorted(v["roles"])
    return companies


def sweep_full_feed(session: requests.Session, max_pages: int = 500) -> dict[str, dict]:
    """Sweep the full jobs feed to collect ALL companies with remote jobs.

    This is a breadth-first sweep — we don't filter by role, we just collect
    every unique company name and slug. This discovers companies even if they
    don't currently have target-role openings (their ATS board may still be
    useful for future runs).
    """
    companies: dict[str, dict] = {}
    offset = 0
    limit = 20
    total = None
    pages = 0
    seen_slugs: set[str] = set()

    while pages < max_pages:
        jobs, total_count = fetch_feed_page(session, offset=offset, limit=limit)
        if not jobs:
            break
        if total is None:
            total = total_count
            print(f"  [himalayas] feed: {total} total jobs", flush=True)

        new = 0
        for j in jobs:
            company = (j.get("companyName") or "").strip()
            slug = (j.get("companySlug") or "").strip()
            if not company:
                continue
            key = _norm(company)
            if key not in companies:
                companies[key] = {
                    "name": company,
                    "slug": slug,
                    "locations": [],
                    "tier": "feed",
                    "roles": [],
                }
                new += 1
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)

        if new == 0 and pages > 10:
            # If we're not finding new companies, stop early
            break

        offset += limit
        pages += 1
        if offset >= total:
            break
        if pages % 50 == 0:
            print(f"  [himalayas] feed page {pages}: {len(companies)} unique companies, {offset}/{total} jobs", flush=True)
        time.sleep(0.2)

    print(f"  [himalayas] feed sweep: {len(companies)} companies from {pages} pages ({total} total jobs)", flush=True)
    return companies


def probe_one(co: dict) -> dict | None:
    """Probe greenhouse/lever/ashby for this company; return merge record on hit."""
    name = co["name"]
    cands = [c for c in candidates(name)[:5] if c]
    if not cands:
        return None
    import time as _t
    hit = None
    for ats in ("greenhouse", "lever", "ashby"):
        for slug in cands:
            try:
                n = PROBES[ats](slug)
            except Exception:
                n = None
            if n is not None:
                hit = (ats, slug, n)
                break
        if hit:
            break
        _t.sleep(PROBE_DELAY)
    if not hit:
        return None
    ats, slug, n = hit
    return {
        "company_name": name,
        "career_page_url": BOARD_URL[ats](slug),
        "website": "",
        "domain_hint": "",
        "ats_type": ats,
        "board_token": slug,
        "slug": slug,
        "jobs_found": n,
        "location": ", ".join(co.get("locations", [])[:5]) if co.get("locations") else "",
        "source_platform": "himalayas",
        "himalayas_tier": co.get("tier", ""),
        "himalayas_roles": co.get("roles", []),
    }


def main() -> int:
    session = requests.Session()

    # Phase 1: Country-targeted role sweep — SG/APAC/EU companies that are
    # under-collected by the global sweeps below. Run FIRST so it always
    # completes within the rescan step's 1200s budget (the full-feed sweep
    # that follows is the time sink and can time out without losing this).
    print("[himalayas] Phase 1: sweeping target roles by country (SG/APAC/EU) …", flush=True)
    country_companies = sweep_countries(session)
    print(f"[himalayas] country sweep found {len(country_companies)} unique companies", flush=True)

    # Phase 2: Collect companies from target-role searches (global)
    print("[himalayas] Phase 2: sweeping target-role searches …", flush=True)
    role_companies = sweep_target_roles(session)
    print(f"[himalayas] role search found {len(role_companies)} unique companies", flush=True)

    # Phase 3: Sweep the full feed for breadth (capped — 500 pages alone blows
    # the 1200s step budget and starves everything else; 80 pages still gives
    # ~1600 breadth companies while leaving time to probe + persist).
    print("[himalayas] Phase 3: sweeping full jobs feed (capped) …", flush=True)
    feed_companies = sweep_full_feed(session, max_pages=80)

    # Merge: role + country companies take priority over feed (they have tier/role/loc info)
    all_companies: dict[str, dict] = {}
    all_companies.update(feed_companies)
    all_companies.update(country_companies)  # country data overwrites feed data
    all_companies.update(role_companies)     # role data overwrites both

    print(f"[himalayas] total unique companies: {len(all_companies)}", flush=True)

    # Filter to NEW companies (not already in companies.json or seed file)
    have_slugs = existing_slugged_names()
    have_seed = existing_seed_names(RAW_OUT)
    skip = have_slugs | have_seed
    todo = [c for key, c in all_companies.items() if key not in skip and c.get("name")]
    print(f"[himalayas] {len(skip)} already have boards; probing {len(todo)} new …", flush=True)

    # Probe for ATS boards
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    seed: list[dict] = []
    if os.path.exists(RAW_OUT):
        try:
            seed = json.load(open(RAW_OUT))
        except Exception:
            seed = []
    by_name = {_norm(s.get("company_name", "")): s for s in seed if s.get("ats_type")}

    def write_seed():
        with open(RAW_OUT, "w") as fh:
            json.dump(list(by_name.values()), fh, indent=2, ensure_ascii=False)

    # Persist all newly-collected companies as unknown-ATS entries BEFORE the
    # (slow) probe phase, so a rescan-step timeout during probing cannot lose
    # them — discover_slugs resolves unknowns into real boards next cycle, and
    # probing below upgrades any it finds a board for. This guarantees the
    # country-sweep companies land even if the step is later killed.
    persisted = 0
    for key, co in all_companies.items():
        if key not in by_name and key not in skip and co.get("name"):
            by_name[key] = {
                "company_name": co["name"],
                "career_page_url": f"https://himalayas.app/companies/{co['slug']}" if co.get("slug") else "",
                "website": "",
                "domain_hint": "",
                "ats_type": "unknown",
                "source_platform": "himalayas",
                "himalayas_slug": co.get("slug", ""),
                "himalayas_tier": co.get("tier", ""),
                "location": ", ".join(co.get("locations", [])[:5]) if co.get("locations") else "",
            }
            persisted += 1
    write_seed()
    print(f"[himalayas] persisted {persisted} new companies as unknown-ATS (pre-probe safety write)", flush=True)

    found = 0
    try:
        if todo:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futs = {pool.submit(probe_one, c): c for c in todo}
                done = 0
                for fut in as_completed(futs):
                    done += 1
                    try:
                        hit = fut.result()
                    except Exception:
                        hit = None
                    if hit:
                        found += 1
                        by_name[_norm(hit["company_name"])] = hit
                        print(f"  FOUND  {hit['company_name']:<26} -> {hit['ats_type']:<10} "
                              f"slug={hit['board_token']:<22} jobs={hit['jobs_found']}", flush=True)
                    if done % 25 == 0:
                        write_seed()
                        print(f"  ...{done}/{len(todo)} probed, {found} new boards (checkpointed)", flush=True)
    finally:
        write_seed()

    # Also write companies without ATS boards (but with himalayas data) as unknown-ATS entries
    # so consolidate.py knows about them
    unknown_count = 0
    for key, co in all_companies.items():
        if key not in by_name and key not in skip and co.get("slug"):
            by_name[key] = {
                "company_name": co["name"],
                "career_page_url": f"https://himalayas.app/companies/{co['slug']}",
                "website": "",
                "domain_hint": "",
                "ats_type": "unknown",
                "source_platform": "himalayas",
                "himalayas_slug": co.get("slug", ""),
                "himalayas_tier": co.get("tier", ""),
            }
            unknown_count += 1

    write_seed()

    print(f"\n[himalayas] {found} new ATS boards; {unknown_count} unknown-ATS entries; "
          f"{len(by_name)} total in {RAW_OUT}", flush=True)
    print("[himalayas] next: .venv/bin/python scripts/consolidate.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())