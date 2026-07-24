#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from discover_slugs import candidates, PROBES, BOARD_URL  # noqa: E402

DATA = os.environ.get("JOBAUTO_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
RAW_OUT = os.path.join(DATA, "raw", "agent11_builtin.json")
COMPANIES_JSON = os.path.join(DATA, "companies.json")

BUILTIN_BASE = "https://builtin.com"
CACHE_DIR = os.path.join(DATA, ".cache_builtin")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_WORKERS = 8  # lower concurrency — we hit builtin.com per company
PROBE_DELAY = 0.15
PAGE_DELAY = 0.5
COMPANY_DELAY = 0.3

# Location hubs to sweep (these give different companies per region)
LOCATION_HUBS = [
    "",  # default (all/global)
    "?country=IND",   # India
    "?country=GBR",   # UK
    "?country=DEU",   # Germany
    "?country=SGP",   # Singapore
    "?country=CAN",   # Canada
    "?country=NLD",   # Netherlands
    "?country=IRL",   # Ireland
]


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def existing_slugged_names() -> set[str]:
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


def fetch_cached(url: str, cache_key: str | None = None) -> str:
    if cache_key:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, re.sub(r"[^a-z0-9]", "_", cache_key) + ".html")
        if os.path.exists(path):
            return open(path, encoding="utf-8").read()

    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200:
                text = r.text
                if cache_key:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                return text
            elif r.status_code in (403, 429):
                time.sleep(5)
                continue
            else:
                return ""
        except requests.RequestException:
            time.sleep(2)
    return ""


def extract_slugs_from_listing(html: str) -> list[str]:
    # BuiltIn listing pages have href="/company/{slug}" links
    slugs = re.findall(r'href="/company/([a-z0-9-]+)"', html)
    seen = set()
    result = []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def extract_company_from_profile(html: str, slug: str) -> dict | None:
    if not html:
        return None

    # Company name: look for <title>Built In | CompanyName</title> or og:title
    name = ""
    m = re.search(r"<title>(?:Built In\s*\|\s*)?([^|<]+?)(?:\s*\|\s*Built In)?</title>", html, re.I)
    if m:
        name = m.group(1).strip()
    if not name:
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html, re.I)
        if m:
            raw = m.group(1).strip()
            name = re.sub(r"\s*\|\s*Built In\s*$", "", raw, flags=re.I).strip()

    if not name:
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m:
            name = m.group(1).strip()

    name = re.sub(r"\s*-\s*(Jobs|Careers|Company Profile|Overview)\s*$", "", name, flags=re.I).strip()

    # Website URL: look for external links that aren't builtin.com or social media
    website = ""
    for m in re.finditer(r'href="(https?://([^"]+))"', html):
        url = m.group(1)
        host = m.group(2).lower()
        # Skip builtin.com, social media, CDN, and common non-website URLs
        if any(skip in host for skip in [
            "builtin.com", "facebook.com", "twitter.com", "linkedin.com",
            "instagram.com", "youtube.com", "github.com", "cdn.",
            "google.com", "apple.com", "fonts.",
        ]):
            continue
        # Skip utm/tracking params in URL
        if "utm_" in url or "ref=" in url:
            continue
        website = url
        break

    if not name:
        name = slug.replace("-", " ").title()

    return {
        "name": name,
        "slug": slug,
        "website": website,
    }


def collect_all_slugs() -> list[str]:
    all_slugs: list[str] = []
    seen_slugs: set[str] = set()

    for hub in LOCATION_HUBS:
        page = 1
        stale = 0
        while stale < 2 and page <= 500:
            if hub:
                url = f"{BUILTIN_BASE}/companies{hub}&page={page}"
            else:
                url = f"{BUILTIN_BASE}/companies?page={page}"

            cache_key = f"listing_{hub}_{page}" if hub else f"listing_default_{page}"
            html = fetch_cached(url, cache_key)
            if not html:
                break

            slugs = extract_slugs_from_listing(html)
            new = 0
            for s in slugs:
                if s not in seen_slugs:
                    seen_slugs.add(s)
                    all_slugs.append(s)
                    new += 1

            if new == 0:
                stale += 1
            else:
                stale = 0

            if page % 20 == 0 or new > 0:
                print(f"  [builtin] hub={hub or 'default'} page {page}: {new} new slugs, "
                      f"total unique={len(seen_slugs)}", flush=True)

            page += 1
            time.sleep(PAGE_DELAY)

    print(f"[builtin] collected {len(seen_slugs)} unique slugs across all hubs", flush=True)
    return all_slugs


def fetch_company_details(slug: str) -> dict | None:
    url = f"{BUILTIN_BASE}/company/{slug}"
    html = fetch_cached(url, f"company_{slug}")
    if not html:
        return None
    result = extract_company_from_profile(html, slug)
    return result


def probe_one(co: dict) -> dict | None:
    name = co["name"]
    cands = [c for c in candidates(name)[:5] if c]
    if not cands:
        return None
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
        time.sleep(PROBE_DELAY)
    if not hit:
        return None
    ats, slug, n = hit
    return {
        "company_name": name,
        "career_page_url": BOARD_URL[ats](slug),
        "website": co.get("website", ""),
        "domain_hint": "",
        "ats_type": ats,
        "board_token": slug,
        "slug": slug,
        "jobs_found": n,
        "source_platform": "builtin",
    }


def main() -> int:
    print("[builtin] Phase 1: collecting company slugs from BuiltIn.com …", flush=True)
    all_slugs = collect_all_slugs()

    if not all_slugs:
        print("[builtin] no slugs found; aborting", file=sys.stderr)
        return 1

    print(f"\n[builtin] Phase 2: fetching details for {len(all_slugs)} companies …", flush=True)
    companies: dict[str, dict] = {}  # norm_name -> {name, slug, website}

    # Batch detail fetching with rate limiting
    for i, slug in enumerate(all_slugs):
        details = fetch_company_details(slug)
        if details and details.get("name"):
            key = _norm(details["name"])
            if key not in companies:
                companies[key] = details
        if (i + 1) % 50 == 0:
            print(f"  ...{i+1}/{len(all_slugs)} details fetched, {len(companies)} unique", flush=True)
        time.sleep(COMPANY_DELAY)

    print(f"[builtin] fetched details for {len(companies)} unique companies", flush=True)

    have_slugs = existing_slugged_names()
    have_seed = existing_seed_names(RAW_OUT)
    skip = have_slugs | have_seed
    todo = [c for key, c in companies.items() if key not in skip and c.get("name")]
    print(f"[builtin] {len(skip)} already have boards; probing {len(todo)} new …", flush=True)

    # Phase 3: Probe for ATS boards
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

    # Also write companies without ATS boards as unknown entries
    unknown_count = 0
    for key, co in companies.items():
        if key not in by_name and key not in skip and co.get("slug"):
            by_name[key] = {
                "company_name": co["name"],
                "career_page_url": f"https://builtin.com/company/{co['slug']}",
                "website": co.get("website", ""),
                "domain_hint": "",
                "ats_type": "unknown",
                "source_platform": "builtin",
            }
            unknown_count += 1

    write_seed()

    print(f"\n[builtin] {found} new ATS boards; {unknown_count} unknown-ATS entries; "
          f"{len(by_name)} total in {RAW_OUT}", flush=True)
    print("[builtin] next: .venv/bin/python scripts/consolidate.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())