"""Discover companies from startups.gallery country pages (HTML scrape).

startups.gallery is a curated gallery of ~1,300 early-stage companies, browsable
by country at /categories/locations/countries/<slug>. There is no public API;
company cards are server-rendered as <a href=".../companies/<slug>">…<h3>NAME</h3>…</a>.

For each country page we extract (slug, name) pairs, then probe greenhouse /
lever / ashby for each NEW company (reusing the proven discover_slugs machinery).
A company becomes automatable when its probed ATS board exists. Companies without
a probeable board are still emitted as `ats_type: "unknown"` so consolidate.py
knows about them (discover_slugs.py may resolve them later).

Low-yield per country (a handful of curated startups), but the names are genuine
early-stage APAC/EU companies not present in the Wikipedia lists — widening the
discovery funnel for Singapore / India / Australia / Germany / Japan / etc.

Output: data/raw/agent17_startups_gallery.json — picked up by scripts/consolidate.py.
Re-runnable, polite, idempotent, merges with prior runs. Read-only except raw file.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# import the proven slug machinery from discover_slugs
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from discover_slugs import candidates, PROBES, BOARD_URL  # noqa: E402

DATA = os.environ.get(
    "JOBAUTO_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
RAW_OUT = os.path.join(DATA, "raw", "agent17_startups_gallery.json")
COMPANIES_JSON = os.path.join(DATA, "companies.json")
UA = "Mozilla/5.0 (job-auto startups-gallery-discovery; research)"
ATS_ORDER = ["greenhouse", "lever", "ashby"]

# Country slugs exposed by startups.gallery's locations index. We probe a broad
# set spanning the regions we want to deepen (SG/SE Asia, India, AU/NZ, JP/KR,
# EU/Germany). Missing/404 pages are skipped gracefully (parser returns []).
COUNTRY_SLUGS = [
    # Singapore + SE Asia
    "singapore", "malaysia", "indonesia", "vietnam", "philippines", "thailand",
    "hong-kong", "taiwan",
    # India
    "india",
    # Australia + NZ
    "australia", "new-zealand",
    # Japan + Korea
    "japan", "south-korea",
    # EU / Europe
    "germany", "netherlands", "ireland", "spain", "sweden", "denmark", "finland",
    "norway", "switzerland", "italy", "poland", "czech-republic", "hungary",
    "france", "united-kingdom",
    # other notable hubs
    "israel", "canada", "united-states", "brazil", "argentina", "mexico", "nigeria",
    "armenia",
]

BASE = "https://startups.gallery/categories/locations/countries"


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


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


def parse_country_page(html: str) -> list[tuple[str, str]]:
    """Extract (gallery_slug, company_name) pairs from a country page.

    Each company card is an <a href=".../companies/<slug>">…<h3>NAME</h3>…</a>.
    We capture the slug from the href and the first <h3> text inside the anchor.
    """
    out: list[tuple[str, str]] = []
    # match the anchor that links to a /companies/<slug> page, capture its inner HTML
    for m in re.finditer(
        r'<a [^>]*?href="(?:\.\./)*companies/([a-z0-9-]+)"[^>]*>(.*?)</a>',
        html, re.S,
    ):
        slug = m.group(1)
        inner = m.group(2)
        h3 = re.search(r"<h3[^>]*>([^<]+)</h3>", inner)
        name = (h3.group(1) if h3 else slug.replace("-", " ")).strip()
        name = re.sub(r"\s+", " ", name)
        if name and len(name) <= 60:
            out.append((slug, name))
    # dedup by gallery slug, preserve order
    seen: set[str] = set()
    dedup: list[tuple[str, str]] = []
    for slug, name in out:
        if slug not in seen:
            seen.add(slug)
            dedup.append((slug, name))
    return dedup


def fetch_country(session: requests.Session, slug: str) -> list[tuple[str, str]]:
    url = f"{BASE}/{slug}"
    try:
        r = session.get(url, headers={"User-Agent": UA}, timeout=25)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return parse_country_page(r.text)
    except Exception as e:
        print(f"  [gallery] {slug}: fetch failed: {e}", file=sys.stderr)
        return []


GENERIC_SLUGS = {"company", "inc", "labs", "lab", "ai", "app", "the", "group",
                 "tech", "technologies", "technology", "systems", "global",
                 "digital", "data", "cloud", "software", "solutions", "services",
                 "holdings", "corp", "corporation", "limited", "ltd"}


def probe_one(name: str, gallery_slug: str) -> dict | None:
    """Probe greenhouse/lever/ashby; return a merge record on hit.

    Try name-derived slug candidates first, then the gallery slug itself (it
    occasionally matches the ATS board slug).
    """
    cands = [c for c in candidates(name)[:4] if c not in GENERIC_SLUGS]
    if gallery_slug and gallery_slug not in cands and gallery_slug not in GENERIC_SLUGS:
        cands.append(gallery_slug)
    for ats in ATS_ORDER:
        probe = PROBES[ats]
        for slug in cands:
            try:
                n = probe(slug)
            except Exception:
                n = None
            if n is not None:  # hit (board exists; n = job count)
                return {
                    "company_name": name,
                    "career_page_url": BOARD_URL[ats](slug),
                    "website": "",
                    "domain_hint": "",
                    "ats_type": ats,
                    "board_token": slug,
                    "source_platform": "startups_gallery",
                }
    return None


def main() -> int:
    session = requests.Session()
    print("[gallery] fetching country pages …", flush=True)

    # Collect companies across all country pages, tagged with their country.
    # key=norm(name) -> {name, slug, country}
    all_companies: dict[str, dict] = {}
    for slug in COUNTRY_SLUGS:
        pairs = fetch_country(session, slug)
        added = 0
        for gslug, name in pairs:
            key = _norm(name)
            if not key:
                continue
            if key not in all_companies:
                all_companies[key] = {"name": name, "slug": gslug, "country": slug}
                added += 1
        print(f"  [gallery] country={slug}: {len(pairs)} cards, +{added} new", flush=True)

    print(f"[gallery] {len(all_companies)} unique companies across {len(COUNTRY_SLUGS)} countries", flush=True)

    # Filter to NEW companies (not already in companies.json with a board token,
    # and not already in a prior run of this script).
    have_slugs = existing_slugged_names()
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    seed: list[dict] = []
    if os.path.exists(RAW_OUT):
        try:
            seed = json.load(open(RAW_OUT))
        except Exception:
            seed = []
    by_name = {_norm(s.get("company_name", "")): s for s in seed if s.get("company_name")}
    skip = have_slugs | set(by_name.keys())
    todo = [c for key, c in all_companies.items() if key not in skip and c.get("name")]
    print(f"[gallery] {len(skip)} already known; probing {len(todo)} new …", flush=True)

    def write_seed():
        with open(RAW_OUT, "w", encoding="utf-8") as fh:
            json.dump(list(by_name.values()), fh, indent=2, ensure_ascii=False)

    found = 0
    try:
        if todo:
            with ThreadPoolExecutor(max_workers=16) as pool:
                futs = {pool.submit(probe_one, c["name"], c.get("slug", "")): c for c in todo}
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
                              f"slug={hit['board_token']:<22}", flush=True)
                    if done % 20 == 0:
                        write_seed()
                        print(f"  ...{done}/{len(todo)} probed, {found} boards (checkpointed)", flush=True)
    finally:
        write_seed()

    # Emit unknown-ATS entries for companies with no probeable board, so
    # consolidate.py + discover_slugs.py can resolve them later.
    unknown = 0
    for key, co in all_companies.items():
        if key not in by_name and key not in skip:
            by_name[key] = {
                "company_name": co["name"],
                "career_page_url": f"https://startups.gallery/companies/{co.get('slug', '')}",
                "website": "",
                "domain_hint": "",
                "ats_type": "unknown",
                "source_platform": "startups_gallery",
                "location": co.get("country", ""),
            }
            unknown += 1
    write_seed()

    print(f"\n[gallery] {found} new ATS boards; {unknown} unknown-ATS entries; "
          f"{len(by_name)} total in {RAW_OUT}", flush=True)
    print("[gallery] next: .venv/bin/python scripts/consolidate.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())