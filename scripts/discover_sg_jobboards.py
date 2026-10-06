#!/usr/bin/env python3
"""Discover Singapore employers from SG job-board company/employer directories.

Sources (2026-08):
  - sg_jobstreet    sg.jobstreet.com/companies/directory — SSR directory, 74 industry
                    categories, paginated; names via data-testid="company-listing-name-*".
  - sg_wellfound    wellfound.com/location/singapore — SSR pages (5), company blocks
                    (a href=/company/... + h2 text). Individual company pages are
                    DataDome-walled — do not fetch them.
  - sg_cult         cultjobs.com (SG creative/media board) — WP REST /wp-json/wp/v2/job_listing
                    with metas: company-name, company-url, _job_location.
  - sg_startupjobs  back.startupjobs.com/api/companies (public API-Platform JSON-LD; the old
                    startupjobs.sg now redirects here). ~276 companies with offers>0; fetch
                    /api/companies/{id} and keep those with a Singapore location. Mostly
                    Czech/EU — typically only a handful of SG hits.

Blocked/dead (graceful skip, do not retry aggressively):
  - Glints (glints.com) — "Glints - Firewall" 403 on page + API paths even after backoff.
  - FastJobs (fastjobs.sg) — Cloudflare challenge.
  - STJobs (stjobs.sg) — connections refused; domain defunct.
  - TechJobsAsia (techjobsasia.com / techjobs.asia) — unreachable from this network.
  - MyCareersFuture API — 401 (auth required; no-login policy).

Output: data/raw/agentSG08_jobboards.json (company_name / career_page_url / website /
domain_hint / ats_type / source_platform / location). Deduped by normalized name.
"""
from __future__ import annotations

import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PATH = ROOT / "data" / "raw" / "agentSG08_jobboards.json"

UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
SLEEP = 0.4
HTTP_TIMEOUT = 30

BLOCK_AFTER = {403, 429}


def session(extra=None):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-SG,en;q=0.9"})
    if extra:
        s.headers.update(extra)
    return s


def entry(name, career="", website="", platform="sg_misc"):
    return {
        "company_name": name,
        "career_page_url": career,
        "website": website,
        "domain_hint": "",
        "ats_type": "unknown",
        "source_platform": platform,
        "location": "Singapore",
    }


# ---------------------------------------------------------------- wellfound

class _H2AfterCompanyLink(HTMLParser):
    """Collect (href, <h2> text) pairs where an <a href=/company/...> precedes an <h2>."""

    def __init__(self):
        super().__init__()
        self.pend = None
        self.in_h2 = False
        self.buf = ""
        self.out = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href", "").startswith("/company/"):
            self.pend = d["href"]
        elif tag == "h2":
            self.in_h2 = True
            self.buf = ""

    def handle_data(self, data):
        if self.in_h2:
            self.buf += data

    def handle_endtag(self, tag):
        if tag == "h2" and self.in_h2:
            self.in_h2 = False
            if self.pend and self.buf.strip():
                self.out.append((self.pend, " ".join(self.buf.split())))
                self.pend = None


def sweep_wellfound():
    s = session({"Accept": "text/html"})
    results = {}
    page = 1
    while page <= 10:
        u = "https://wellfound.com/location/singapore" + (f"?page={page}" if page > 1 else "")
        r = s.get(u, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            break
        p = _H2AfterCompanyLink()
        p.feed(r.text)
        new = 0
        for h, name in p.out:
            if h not in results:
                results[h] = name
                new += 1
        if new == 0 and page > 1:
            break
        page += 1
        time.sleep(SLEEP)
    return [entry(n, career="https://wellfound.com" + h, platform="sg_wellfound")
            for h, n in results.items()]


# ---------------------------------------------------------------- cultjobs (WP REST)

def sweep_cultjobs(max_pages=30):
    s = session({"Accept": "application/json"})
    results = {}
    for page in range(1, max_pages + 1):
        u = ("https://cultjobs.com/wp-json/wp/v2/job_listing"
             f"?per_page=100&page={page}&_fields=id,slug,metas")
        r = s.get(u, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            break
        d = r.json()
        if not d:
            break
        for j in d:
            m = j.get("metas") or {}
            if "singapore" not in json.dumps(m.get("_job_location") or {}).lower():
                continue
            name = (m.get("company-name") or "").strip()
            if len(name) < 2:
                continue
            web = (m.get("company-url") or "").strip()
            if web and not web.startswith("http"):
                web = "https://" + web
            k = name.lower()
            if k not in results or (web and not results[k]):
                results[k] = (name, web)
        time.sleep(SLEEP)
    return [entry(n, website=w, platform="sg_cult") for n, w in results.values()]


# ---------------------------------------------------------------- startupjobs.com API

def sweep_startupjobs():
    s = session({"Accept": "application/ld+json",
                 "Origin": "https://www.startupjobs.com",
                 "Referer": "https://www.startupjobs.com/companies"})
    base = "https://back.startupjobs.com/api/companies"
    ids = []
    page = 1
    while True:
        r = s.get(base, params={"offers[gt]": 0, "order[offers]": "desc", "page": page},
                  timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            break
        d = r.json()
        mem = d.get("member", [])
        if not mem:
            break
        ids += [(m["id"], m.get("slug"), (m.get("profile") or {}).get("name"))
                for m in mem]
        total_pages = (d.get("totalItems", 0) + 29) // 30
        if page >= total_pages:
            break
        page += 1
        time.sleep(SLEEP)

    def is_sg(locs):
        for l in locs or []:
            for f in ("country", "place", "locality"):
                if "singapore" in ((l.get(f) or {}).get("en") or "").lower():
                    return True
        return False

    out = []
    for cid, slug, name in ids:
        r = s.get(f"{base}/{cid}", timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            time.sleep(SLEEP)
            continue
        prof = (r.json().get("profile") or {})
        if is_sg(prof.get("locations")):
            web = prof.get("web") or ""
            if web and not web.startswith("http"):
                web = "https://" + web
            out.append(entry(prof.get("name") or name or slug, website=web,
                             platform="sg_startupjobs"))
        time.sleep(SLEEP)
    return out


# ---------------------------------------------------------------- jobstreet directory

class _CompanyListingName(HTMLParser):
    """Anchors tagged data-testid='company-listing-name-*' carry exact names."""

    def __init__(self):
        super().__init__()
        self.cur = None
        self.buf = ""
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            tid = dict(attrs).get("data-testid", "")
            if tid.startswith("company-listing-name-"):
                self.cur = dict(attrs).get("href", "")
                self.buf = ""

    def handle_data(self, data):
        if self.cur is not None:
            self.buf += data

    def handle_endtag(self, tag):
        if tag == "a" and self.cur is not None:
            txt = " ".join(self.buf.split())
            if txt:
                self.out.append((self.cur, txt))
            self.cur = None


def sweep_jobstreet(max_pages_per_cat=30):
    s = session({"Accept": "text/html"})
    r = s.get("https://sg.jobstreet.com/companies/directory", timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        return []
    cats = list(dict.fromkeys(re.findall(r'href="(/companies/directory/[^"#?]+)"', r.text)))
    results = {}
    for cat in cats:
        page = 1
        while page <= max_pages_per_cat:
            u = "https://sg.jobstreet.com" + cat + (f"?page={page}" if page > 1 else "")
            try:
                rp = s.get(u, timeout=HTTP_TIMEOUT)
            except requests.RequestException:
                break
            if rp.status_code in BLOCK_AFTER:
                time.sleep(30)
                try:
                    rp = s.get(u, timeout=HTTP_TIMEOUT)
                except requests.RequestException:
                    break
            if rp.status_code != 200:
                break
            p = _CompanyListingName()
            p.feed(rp.text)
            new = 0
            for h, n in p.out:
                if h not in results:
                    results[h] = n
                    new += 1
            if new == 0:
                break
            page += 1
            time.sleep(SLEEP)
        time.sleep(SLEEP)
    return [entry(n, career=h, platform="sg_jobstreet") for h, n in results.items()]


# ---------------------------------------------------------------- main

def norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower()).rstrip("., ")


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sweeps = [
        ("sg_wellfound", sweep_wellfound),
        ("sg_cult", sweep_cultjobs),
        ("sg_startupjobs", sweep_startupjobs),
        ("sg_jobstreet", sweep_jobstreet),
    ]
    seen = set()
    out = []
    for tag, fn in sweeps:
        try:
            rows = fn()
        except Exception as e:  # one blocked board must not sink the rest
            print(f"[sg_jobboards] {tag} failed: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        added = 0
        for e in rows:
            k = norm(e["company_name"])
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(e)
            added += 1
        print(f"[sg_jobboards] {tag}: {len(rows)} raw, {added} added", file=sys.stderr)
        json.dump(out, open(OUT_PATH, "w"), indent=1)  # checkpoint after each source
    json.dump(out, open(OUT_PATH, "w"), indent=1)
    print(f"[sg_jobboards] wrote {len(out)} entries to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
