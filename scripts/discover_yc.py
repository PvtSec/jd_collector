#!/usr/bin/env python3
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# allow `import discover_slugs` when run as a script (scripts/ is on sys.path[0])
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from discover_slugs import candidates, PROBES, BOARD_URL  # noqa: E402

DATA = os.environ.get("JOBAUTO_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
RAW_OUT = os.path.join(DATA, "raw", "agent9_yc.json")
COMPANIES_JSON = os.path.join(DATA, "companies.json")
YC_API = "https://api.ycombinator.com/v0.1/companies"
YC_API_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " \
            "(KHTML, like Gecko) Chrome/120 Safari/537.36"
YC_API_PER_PAGE = 200  # server caps responses around 200; keeps requests cheap
HTTP_TIMEOUT = 30

# Probing politeness
MAX_WORKERS = 16
PROBE_DELAY = 0.1  # seconds between probe attempts within a company

# Cap pages so a stuck API can't loop forever. YC currently has ~5000
# companies, so 50 pages × 200/page is well above the real total.
MAX_PAGES = 80
STALE_STOP = 8  # consecutive pages with no new companies => stop (one YC page
                # can re-emit companies we've already seen across filters)


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


# YC industry filter queries — each loads a filtered view that may surface
# companies not reached by the unfiltered scroll. We hit the same JSON API
# with a different `industries` query param; the API returns the same shape.
YC_INDUSTRY_FILTERS = [
    "Security",
    "Developer Tools",
    "SaaS",
    "Artificial Intelligence",
    "Cloud Computing",
    "DevOps",
    "FinTech",
    "Healthcare",
    "Enterprise Software",
    "Infrastructure",
]


def _fetch_page(page: int, industries: str | None = None) -> dict | None:
    params: list[tuple[str, str]] = [("per_page", str(YC_API_PER_PAGE))]
    if page > 1:
        params.append(("page", str(page)))
    if industries:
        params.append(("industries", industries))
    try:
        r = requests.get(YC_API, params=params, headers={"User-Agent": YC_API_UA},
                         timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print(f"  [yc] API error page={page} industries={industries!r}: {e}", file=sys.stderr)
        return None


def _ingest(body: dict, companies: dict[str, dict]) -> int:
    if not body or not isinstance(body.get("companies"), list):
        return 0
    before = len(companies)
    for c in body["companies"]:
        if not isinstance(c, dict):
            continue
        slug = (c.get("slug") or "").strip()
        if not slug or slug in companies:
            continue
        name = (c.get("name") or "").strip() or slug
        # YC API exposes regions (list[str]) — collapse to a comma-joined
        # location string the way the old Playwright scraper did.
        loc = ""
        regions = c.get("regions") or []
        if isinstance(regions, list):
            loc = ", ".join(r for r in regions if isinstance(r, str))
        companies[slug] = {"name": name, "location": loc, "yc_slug": slug}
    return len(companies) - before


def scrape_yc_companies() -> list[dict]:
    companies: dict[str, dict] = {}

    # Pass 1: unfiltered paged pull
    print(f"[yc] Pass 1: unfiltered API pull (per_page={YC_API_PER_PAGE}) …", flush=True)
    page = 1
    stale = 0
    while page <= MAX_PAGES:
        body = _fetch_page(page)
        if body is None:
            stale += 1
            if stale >= STALE_STOP:
                print(f"  [yc] API returned {stale} consecutive errors at page={page}; stopping", file=sys.stderr)
                break
            page += 1
            continue
        n_new = _ingest(body, companies)
        print(f"  page {page:3d}  +{n_new:4d}  total {len(companies)}", flush=True)
        if n_new == 0:
            stale += 1
        else:
            stale = 0
        # API reports `nextPage` (full URL or null) and `totalPages` (int).
        # Bound by MAX_PAGES regardless of what the server reports.
        next_page = body.get("nextPage")
        total_pages = body.get("totalPages") or 0
        if not next_page or page >= min(total_pages or page + 1, MAX_PAGES):
            break
        # Parse the page number from the nextPage URL (the server returns
        # something like
        #   https://api.ycombinator.com/v0.1/companies?industries=...&page=N
        # ); fall back to incrementing if the URL doesn't carry a page param.
        next_num = page + 1
        if isinstance(next_page, str):
            from urllib.parse import urlparse, parse_qs
            try:
                qs = parse_qs(urlparse(next_page).query)
                p_val = (qs.get("page") or [None])[0]
                if p_val and p_val.isdigit():
                    next_num = int(p_val)
            except Exception:
                pass
        page = next_num
        if stale >= STALE_STOP:
            break
    print(f"[yc] Pass 1 done: {len(companies)} unique companies "
          f"(scanned pages 1..{page})", flush=True)

    # Pass 2: industry-filtered pulls (only first 3 pages of each — these
    # are the high-value, top-of-list companies for the filter).
    for industry in YC_INDUSTRY_FILTERS:
        print(f"[yc] Pass 2: industry={industry!r} …", flush=True)
        for p in range(1, 4):
            body = _fetch_page(p, industries=industry)
            if body is None:
                break
            n_new = _ingest(body, companies)
            print(f"  page {p} +{n_new} (total: {len(companies)})", flush=True)
            if not body.get("nextPage"):
                break

    out = list(companies.values())
    print(f"[yc] pulled {len(out)} unique YC companies total", flush=True)
    return out


def probe_one(co: dict) -> dict | None:
    name = co["name"]
    cands = [c for c in candidates(name)[:5] if c]
    if not cands:
        return None
    import time
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
        "website": "",
        "domain_hint": "",
        "ats_type": ats,
        "board_token": slug,
        "slug": slug,
        "jobs_found": n,
        "location": co.get("location", ""),
        "source_platform": "yc-directory",
    }


def main() -> int:
    print("[yc] loading YC directory via public API …", flush=True)
    scraped = scrape_yc_companies()
    if not scraped:
        print("[yc] no companies scraped; aborting", file=sys.stderr)
        return 1

    have_slugs = existing_slugged_names()
    have_seed = existing_seed_names(RAW_OUT)
    skip = have_slugs | have_seed
    todo = [c for c in scraped if _norm(c["name"]) not in skip and c["name"]]
    print(f"[yc] {len(scraped)} scraped; {len(skip)} already have boards; probing {len(todo)} new …", flush=True)

    # seed map persisted to disk so an interrupt never loses everything
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    seed = []
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
                        write_seed()  # checkpoint so a kill can't lose the run
                        print(f"  ...{done}/{len(todo)} probed, {found} new boards (checkpointed)", flush=True)
    finally:
        write_seed()

    print(f"\n[yc] {found} new boards this run; {len(by_name)} total in {RAW_OUT}", flush=True)
    print("[yc] next: .venv/bin/python scripts/consolidate.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())