#!/usr/bin/env python3
"""Discover Singapore-hiring companies on Greenhouse public job boards.

Source of board tokens (all public):
  1. greenhouse.com sitemap customer-stories slugs -> company-name token guesses
     (the customer directory itself is /customer-stories; /customers 404s and the
     board roots just serve the marketing site).
  2. A seed list of tokens harvested from public Singapore/APAC job lists on
     GitHub (sushinoya/singapore-tech-internships, didtheyghostme/Singapore-Summer2026,
     kxrt/Singapore-Summer2024, speedyapply 2027 INTL lists, northwesternfintech,
     Lamiiine visa-sponsored, Zackhardtoname/internships) via GitHub code search.

Each candidate token is verified against the public board API
https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=false and kept
only if a location/office field contains "singapore" (plain substring).
Tokens already present in data/by_ats/greenhouse.json are skipped.

Output: data/raw/agentSG09_greenhouse_sg.json (JSON array). Never touches
data/companies.json — consolidate.py owns that.

Usage: python3 scripts/discover_greenhouse_sg.py [-c config.yaml] [--workers 12]
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
BOARD_API = "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=false"
BOARD_META = "https://boards-api.greenhouse.io/v1/boards/{}"
OUT_PATH = os.path.join(ROOT, "data", "raw", "agentSG09_greenhouse_sg.json")
EXISTING_PATH = os.path.join(ROOT, "data", "by_ats", "greenhouse.json")

# Tokens verified live (Aug 2026) via the public board API — harvested from
# web search for SG-hosted greenhouse boards plus SG/APAC GitHub job lists.
# Most big names are already in data/by_ats/greenhouse.json (auto-skipped);
# new ones get verified for Singapore before being written.
SEED_TOKENS = {
    "figma": "Figma",
    "govtech": "GovTech",
    "guardsquare": "Guardsquare",
    "pinterest": "Pinterest",
    "remotecom": "Remote",
    "coinbase": "Coinbase",
    "okx": "OKX",
    "abnormalsecurity": "Abnormal",
    "wehrtyou": "Hudson River Trading",
    "vulncheck": "VulnCheck",
    "intrinsicrobotics": "Intrinsic",
    "optiverprivate": "Optiver",
    "monzo": "Monzo",
    "spothero": "SpotHero",
    "stitchfix": "Stitch Fix",
    "vaynerx": "VaynerX",
    "wise": "Wise",
    "wrike": "Wrike",
}

_rate_lock = threading.Lock()
_last_req = [0.0]
_consec_429 = [0]


def spaced_get(sess, url, timeout=25):
    """GET with global inter-request spacing (politeness ~<=8 req/s)."""
    for attempt in range(3):
        with _rate_lock:
            wait = 0.15 - (time.time() - _last_req[0])
            if wait > 0:
                time.sleep(wait)
            _last_req[0] = time.time()
        try:
            r = sess.get(url, timeout=timeout)
        except requests.RequestException:
            return None
        if r.status_code in (403, 429):
            _consec_429[0] += 1
            if _consec_429[0] >= 3:
                print("[rate] backing off 30s", file=sys.stderr)
                time.sleep(30)
                _consec_429[0] = 0
            continue
        _consec_429[0] = 0
        return r
    return None


def slugify(name):
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if ord(c) < 128).lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def story_token_guesses():
    """greenhouse.com sitemap customer-story slugs -> simple token guesses."""
    guesses = {}
    try:
        r = requests.get("https://www.greenhouse.com/sitemap.xml",
                         headers={"User-Agent": UA}, timeout=90)
        locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
        r.close()
        for u in locs:
            if not u.startswith("https://www.greenhouse.com/customer-stories/"):
                continue
            slug = u.rsplit("/", 1)[1]
            if slug.startswith("case-study-"):
                guesses.setdefault(slug[len("case-study-"):], slug)
    except requests.RequestException:
        pass
    return guesses


def find_singapore(payload):
    """Return the matched office/location string, or None. Plain substring only."""
    def scan_offices(offices):
        for o in offices or []:
            for s in (o.get("name", ""), (o.get("location") or {}).get("name", "")):
                if "singapore" in s.lower():
                    return s
        return None

    hit = scan_offices(payload.get("offices"))
    if hit:
        return hit
    for job in payload.get("jobs", []):
        hit = scan_offices(job.get("offices"))
        if hit:
            return hit
        loc = (job.get("location") or {}).get("name", "")
        if "singapore" in loc.lower():
            return loc
    return None


def load_existing_tokens():
    try:
        with open(EXISTING_PATH) as f:
            return {e.get("board_token", "").lower() for e in json.load(f) if e.get("board_token")}
    except (OSError, ValueError):
        return set()


def write_results(entries):
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUT_PATH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default=None, help="unused; CLI parity with other scripts")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    existing = load_existing_tokens()
    candidates = dict(SEED_TOKENS)
    for tok, slug in story_token_guesses().items():
        candidates.setdefault(tok, slug)
    todo = {t: n for t, n in candidates.items() if t.lower() not in existing}
    print(f"existing={len(existing)} candidates={len(candidates)} to_probe={len(todo)}")

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    entries = []
    done = [0]
    lock = threading.Lock()

    def probe(item):
        tok, srcname = item
        r = spaced_get(sess, BOARD_API.format(tok))
        done_i = None
        with lock:
            done[0] += 1
            done_i = done[0]
        if r is None or r.status_code == 404:
            return None
        if r.status_code != 200:
            return None
        try:
            payload = json.loads(r.text)
        except ValueError:
            return None
        evidence = find_singapore(payload)
        if not evidence:
            return None
        company = srcname
        meta_r = spaced_get(sess, BOARD_META.format(tok))
        if meta_r is not None and meta_r.status_code == 200:
            try:
                company = json.loads(meta_r.text).get("name") or company
            except ValueError:
                pass
        entry = {
            "company_name": company or tok,
            "career_page_url": f"https://job-boards.greenhouse.io/{tok}",
            "website": "",
            "domain_hint": "",
            "ats_type": "greenhouse",
            "board_token": tok,
            "source_platform": "sg_greenhouse",
            "location": "Singapore",
            "sg_evidence": evidence,
        }
        with lock:
            entries.append(entry)
            write_results(entries)
        print(f"[{done_i}/{len(todo)}] SG+ {tok} ({evidence[:60]})")
        return entry

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(probe, sorted(todo.items())))
    write_results(entries)
    print(f"done: probed={len(todo)} sg_positive={len(entries)} -> {OUT_PATH}")


if __name__ == "__main__":
    main()
