#!/usr/bin/env python3
"""e27.co Singapore company discovery (agent SG02).

e27.co sits behind a Cloudflare managed challenge for datacenter IPs, so every
e27.co request here goes through the public r.jina.ai reader proxy
(https://r.jina.ai/<url>), which passes the challenge. Static JS assets are
not challenged and were used to locate the JSON API:

  list:  GET https://e27.co/api/startups/?location=Singapore&page=N&length=M
  view:  GET https://e27.co/api/startups/get/view/?id=<id>   (has `website`)

Notes discovered by probing:
  * `location=` is a relevance-ranked SOFT match: non-SG companies interleave
    (page 1 was ~51% SG), so we crawl every page and keep only items whose
    location[] contains Singapore.
  * the list payload has metas.website but it is always empty; the per-id view
    endpoint carries the real website, so top-ranked entries get enriched
    until the enrichment deadline.
  * totalstartupcount (~38k) is the whole ranked result set, not the SG count.

Output: data/raw/agentSG02_e27.json (JSON array), rewritten incrementally.
Env knobs: JOBAUTO_DATA_DIR, E27_OUT, E27_PAGE_LENGTH (200), E27_RATE_SLEEP
(3.5s ~= 17 req/min, under r.jina.ai's anonymous ~20 RPM), E27_MAX_PAGES,
E27_ENRICH_SECONDS (time budget for website enrichment, rank-ordered).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse

import requests

DATA = os.environ.get(
    "JOBAUTO_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
OUT = os.environ.get("E27_OUT", os.path.join(DATA, "raw", "agentSG02_e27.json"))

JINA = "https://r.jina.ai/"
LIST_URL = "https://e27.co/api/startups/"
VIEW_URL = "https://e27.co/api/startups/get/view/"

PAGE_LENGTH = int(os.environ.get("E27_PAGE_LENGTH", "200"))
RATE_SLEEP = float(os.environ.get("E27_RATE_SLEEP", "3.5"))
MAX_PAGES = int(os.environ.get("E27_MAX_PAGES", "400"))
START_PAGE = int(os.environ.get("E27_START_PAGE", "1"))
ENRICH_SECONDS = float(os.environ.get("E27_ENRICH_SECONDS", "700"))
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"

ATS_SUBSTRINGS = (
    ("greenhouse", "boards.greenhouse.io/"),
    ("lever", "jobs.lever.co/"),
    ("ashby", "jobs.ashbyhq.com/"),
    ("smartrecruiters", "careers.smartrecruiters.com/"),
    ("workable", "apply.workable.com/"),
    ("personio", "jobs.personio.de/"),
    ("personio", "personio.de/careers"),
    ("teamtailor", "teamtailor.com/"),
    ("bamboohr", "bamboohr.com/careers"),
    ("breezyhr", "breezy.hr/"),
    ("recruitee", "recruitee.com/"),
    ("pinpoint", "pinpointhq.com/"),
    ("rippling", "rippling.com/"),
    ("workday", "myworkdayjobs.com/"),
)


def jina_get(url: str, params: dict | None = None, timeout: int = 120) -> str | None:
    """Fetch a URL through r.jina.ai as plain text. Handles 429 with backoff."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            r = requests.get(
                JINA + url,
                headers={"X-Return-Format": "text", "User-Agent": UA},
                timeout=timeout,
            )
            if r.status_code == 429:
                wait = 45 * (attempt + 1)
                print(f"[rate] 429, sleeping {wait}s", flush=True)
                time.sleep(wait)
                continue
            if r.status_code == 200:
                return r.text
            print(f"[warn] jina status {r.status_code} for {url}", flush=True)
        except requests.RequestException as exc:
            print(f"[warn] fetch error {exc}", flush=True)
        time.sleep(8)
    return None


def parse_data(txt: str | None) -> dict | None:
    """Pull the {'data': ...} JSON object out of a (possibly wrapped) body."""
    if not txt:
        return None
    i = txt.find('{"data"')
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(txt, i)
    except json.JSONDecodeError:
        return None
    return obj.get("data") if isinstance(obj, dict) else None


def domain_hint(url: str) -> str:
    if not url:
        return ""
    m = re.match(r"https?://([^/:?#]+)", url.strip(), re.I)
    return m.group(1).lower().removeprefix("www.") if m else ""


def detect_ats(*urls: str) -> str:
    joined = " ".join(u for u in urls if u).lower()
    for ats, needle in ATS_SUBSTRINGS:
        if needle in joined:
            return ats
    return "unknown"


def is_sg(item: dict) -> bool:
    for loc in item.get("location") or []:
        if loc.get("text") == "Singapore" or loc.get("id") == "Singapore":
            return True
    return False


def markets(item: dict) -> list[str]:
    raw = item.get("market") or ""
    try:
        parsed = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[str] = []
    for group in parsed or []:
        if isinstance(group, list):
            out.extend(str(g) for g in group if g and str(g) != "-1")
        elif group and str(group) != "-1":
            out.append(str(group))
    return out


def make_entry(item: dict, rank: int) -> dict:
    metas = item.get("metas") or {}
    website = (metas.get("website") or "").strip()
    return {
        "company_name": (item.get("name") or "").strip(),
        "career_page_url": "",
        "website": website,
        "domain_hint": domain_hint(website),
        "ats_type": "unknown",
        "source_platform": "sg_e27",
        "location": "Singapore",
        "e27_id": str(item.get("id") or ""),
        "e27_slug": item.get("slug") or "",
        "e27_url": item.get("link") or "",
        "rank": rank,
        "stage": item.get("stage") or "",
        "markets": markets(item),
        "short_description": (metas.get("short_description") or "")[:400],
    }


def write(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)


def crawl(entries: list[dict], seen: set[str]) -> None:
    page = START_PAGE
    since_write = 0
    while page <= MAX_PAGES:
        data = parse_data(jina_get(LIST_URL, {"location": "Singapore", "page": page, "length": PAGE_LENGTH}))
        if not data or not data.get("list"):
            print(f"[crawl] page {page}: empty/failed list, stopping", flush=True)
            break
        new = 0
        for item in data["list"]:
            slug = item.get("slug") or ""
            if not is_sg(item) or not slug or slug in seen:
                continue
            seen.add(slug)
            entries.append(make_entry(item, rank=len(entries) + 1))
            new += 1
        total = data.get("totalstartupcount")
        print(
            f"[crawl] page {page}: {len(data['list'])} items, +{new} SG (total SG {len(entries)}; ranked total {total})",
            flush=True,
        )
        since_write += new
        if since_write >= 200:
            write(entries)
            since_write = 0
        if total and page * PAGE_LENGTH >= int(total):
            print("[crawl] reached ranked-total end", flush=True)
            break
        page += 1
        time.sleep(RATE_SLEEP)


def enrich(entries: list[dict], deadline: float) -> None:
    done = 0
    for entry in entries:
        if time.time() > deadline:
            break
        if entry["website"] or not entry["e27_id"]:
            continue
        data = parse_data(jina_get(VIEW_URL, {"id": entry["e27_id"]}))
        if isinstance(data, dict) and data:
            website = (data.get("website") or "").strip()
            careers = ""
            for key in ("careers", "career_page", "career_page_url", "jobs_url"):
                if data.get(key):
                    careers = str(data[key]).strip()
                    break
            if website or careers:
                entry["website"] = website or entry["website"]
                entry["career_page_url"] = careers
                entry["domain_hint"] = domain_hint(entry["website"])
                entry["ats_type"] = detect_ats(careers, entry["website"])
            if data.get("location") and "singapore" not in str(data.get("location", "")).lower():
                # view endpoint disagrees with the list filter: keep, but note it
                entry["location_note"] = str(data.get("location"))
        done += 1
        if done % 25 == 0:
            write(entries)
            print(f"[enrich] {done} lookups, {sum(1 for e in entries if e['website'])} websites", flush=True)
        time.sleep(RATE_SLEEP)
    write(entries)
    print(f"[enrich] finished after {done} lookups", flush=True)


def main() -> int:
    started = time.time()
    entries: list[dict] = []
    seen: set[str] = set()
    if os.environ.get("E27_RESUME") and os.path.exists(OUT):
        try:
            entries = json.load(open(OUT, encoding="utf-8"))
            seen = {e["e27_slug"] for e in entries if e.get("e27_slug")}
            print(f"[resume] loaded {len(entries)} entries from {OUT}", flush=True)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[resume] failed to load {OUT}: {exc}", flush=True)
    crawl(entries, seen)
    write(entries)
    print(f"[main] crawl done: {len(entries)} SG companies in {time.time()-started:.0f}s", flush=True)
    if ENRICH_SECONDS > 0:
        enrich(entries, time.time() + ENRICH_SECONDS)
    n_ws = sum(1 for e in entries if e["website"])
    n_cp = sum(1 for e in entries if e["career_page_url"])
    print(f"[main] final: {len(entries)} entries, {n_ws} websites, {n_cp} career urls", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
