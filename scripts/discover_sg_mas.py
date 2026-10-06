#!/usr/bin/env python3
"""Discover Singapore fintech companies from the MAS Financial Institutions
Directory (eservices.mas.gov.sg/fid) — public licence-category listings plus
per-institution detail pages (which carry the entity's own website).

Writes/merges into data/raw/agentSG07_gov_wiki.json with source_platform="sg_mas".
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import sys
import time
from urllib.parse import quote

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = os.environ.get(
    "JOBAUTO_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
OUT_PATH = os.path.join(DATA, "raw", "agentSG07_gov_wiki.json")

BASE = "https://eservices.mas.gov.sg"
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
HEADERS = {"User-Agent": UA}
SLEEP = 0.35

# Fintech/software-relevant licence categories (payments + capital markets +
# local banks). Insurance/insurer categories deliberately skipped (volume,
# little tech signal per entity).
CATEGORIES = [
    "Major Payment Institution",
    "Standard Payment Institution",
    "Finance Company",
    "Merchant Bank",
    "Local Bank",
    "Recognised Market Operator",
    "Capital Markets Services Licensee",  # largest + least fintech — last so a
    # detail-page budget cutoff trims this tail first
]

SKIP_HOSTS = ("mas.gov.sg", "gov.sg", "wogaa.sg", "eservices.mas.gov.sg")

NAME_H3 = re.compile(r'<h3 class="header-inner-2">([^<]+)</h3>')
DETAIL = re.compile(r'href="(/fid/institution/detail/[^"]+)"')
DATA_HIT = re.compile(r'data-hit="(\d+)"')
TITLE_RE = re.compile(r"<title>([^<]*)</title>")


def norm_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def get(url: str) -> str | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code in (403, 429):
                time.sleep(30)
                continue
            r.raise_for_status()
            return r.text
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def load_out() -> list[dict]:
    if os.path.exists(OUT_PATH):
        try:
            return json.load(open(OUT_PATH))
        except Exception:
            pass
    return []


def save_out(entries: list[dict]) -> None:
    tmp = OUT_PATH + ".tmp"
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(tmp, "w") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp, OUT_PATH)


def parse_listing(text: str) -> list[tuple[str, str]]:
    """Return [(display_name, detail_path)] pairs from a category listing page."""
    names = [htmllib.unescape(n).strip() for n in NAME_H3.findall(text)]
    paths = DETAIL.findall(text)
    # the h3 anchors wrap the same rows as the detail links; pair by order
    pairs = []
    if len(names) == len(paths):
        pairs = list(zip(names, paths))
    else:
        for p in paths:
            slug = p.rsplit("/", 1)[-1]
            # strip leading id digits -> readable name
            nm = re.sub(r"^\d+-", "", slug).replace("-", " ")
            pairs.append((nm, p))
    seen: set[str] = set()
    out = []
    for n, p in pairs:
        if p not in seen:
            seen.add(p)
            out.append((n, p))
    return out


def detail_website(path: str) -> str:
    text = get(BASE + path)
    if not text:
        return ""
    for url in re.findall(r'href="(https?://[^"]+)"', text):
        host = url.split("//", 1)[-1].split("/")[0].lower()
        if any(s in host for s in SKIP_HOSTS):
            continue
        return url.rstrip("/")
    return ""


def main() -> None:
    found: dict[str, dict] = {}
    for cat in CATEGORIES:
        page = 1
        total = None
        cat_entries: dict[str, str] = {}
        while True:
            url = f"{BASE}/fid/institution?category={quote(cat)}&page={page}"
            text = get(url)
            if not text:
                break
            if total is None:
                m = DATA_HIT.search(text)
                total = int(m.group(1)) if m else 0
            pairs = parse_listing(text)
            if not pairs:
                break
            for name, path in pairs:
                cat_entries.setdefault(path, name)
            if page * 10 >= (total or 0) or page > 120:
                break
            page += 1
            time.sleep(SLEEP)
        print(f"[mas] {cat}: {len(cat_entries)} entities (hit={total})", flush=True)
        for path, name in cat_entries.items():
            key = norm_name(name)
            if not key or key in found:
                # still keep the licence category breadth by name only
                continue
            found[key] = {"company_name": name, "detail": path}
        time.sleep(SLEEP)

    print(f"[mas] unique institutions: {len(found)}", flush=True)

    # fetch websites from detail pages — prioritised by category (payments and
    # banks first; capital-markets licensees last so a budget cutoff trims the
    # least tech-relevant tail first). Progress is merged into the output file
    # every FLUSH_EVERY lookups so any interruption keeps a valid JSON file.
    FLUSH_EVERY = 150
    DETAIL_BUDGET_S = float(os.environ.get("SG_MAS_DETAIL_BUDGET_S", "600"))
    started = time.time()
    got = 0
    flushed = 0

    def flush(force: bool = False) -> None:
        nonlocal flushed
        entries = []
        for rec in found.values():
            web = rec.get("website", "")
            if not rec.get("tried") and not force:
                continue  # not looked up yet — leave for a later incremental run
            entries.append({
                "company_name": rec["company_name"],
                "career_page_url": "",
                "website": web,
                "domain_hint": web.split("//")[-1].split("/")[0] if web else "",
                "ats_type": "unknown",
                "source_platform": "sg_mas",
                "location": "Singapore",
            })
        out = [e for e in load_out() if e.get("source_platform") != "sg_mas"]
        seen = {norm_name(e["company_name"]) for e in out}
        added = 0
        for e in entries:
            k = norm_name(e["company_name"])
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(e)
            added += 1
        save_out(out)
        flushed = added
        print(f"[mas] flushed {added} sg_mas entries (file total {len(out)})", flush=True)

    for i, (key, rec) in enumerate(found.items(), 1):
        if time.time() - started > DETAIL_BUDGET_S:
            print(f"[mas] detail budget hit at {i-1}/{len(found)}", flush=True)
            break
        rec["tried"] = True
        web = detail_website(rec["detail"])
        if web:
            rec["website"] = web
            got += 1
        if i % FLUSH_EVERY == 0:
            print(f"[mas] detail pages {i}/{len(found)} websites={got}", flush=True)
            flush()
        time.sleep(SLEEP)
    print(f"[mas] websites: {got}/{len(found)}", flush=True)
    flush(force=True)


if __name__ == "__main__":
    main()
