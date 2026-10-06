#!/usr/bin/env python3
"""Singapore company discovery sweep (agent SG05).

Sub-sources:
  (a) YC directory, region=Singapore, all batches  -> source_platform "sg_yc"
  (b) startups.gallery Singapore country pages     -> source_platform "sg_gallery"
  (c) GitHub awesome-lists / gists (Singapore)     -> source_platform "sg_awesome"

Writes data/raw/agentSG05_dirs.json (JSON array). Never touches companies.json.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("JOBAUTO_DATA_DIR", os.path.join(os.path.dirname(HERE), "data"))
RAW_OUT = os.path.join(DATA, "raw", "agentSG05_dirs.json")
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
YC_API = "https://api.ycombinator.com/v0.1/companies"
TIMEOUT = 30
SLEEP = 0.4


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def load_out() -> dict[str, dict]:
    if os.path.exists(RAW_OUT):
        try:
            arr = json.load(open(RAW_OUT, encoding="utf-8"))
            return {_norm(e.get("company_name", "")): e for e in arr if e.get("company_name")}
        except Exception:
            pass
    return {}


def write_out(by_name: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    tmp = RAW_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(list(by_name.values()), fh, indent=2, ensure_ascii=False)
    os.replace(tmp, RAW_OUT)


def sweep_yc(by_name: dict[str, dict]) -> int:
    """Pull YC companies with region=Singapore across all pages/batches."""
    added = 0
    page = 1
    while page <= 60:
        params = [("per_page", "200")]
        if page > 1:
            params.append(("page", str(page)))
        params.append(("regions", "Singapore"))
        try:
            r = requests.get(YC_API, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
        except Exception as e:
            print(f"  [yc] page {page} error: {e}", file=sys.stderr)
            page += 1
            continue
        if r.status_code != 200:
            print(f"  [yc] page {page} HTTP {r.status_code}", file=sys.stderr)
            if r.status_code in (403, 429):
                time.sleep(30)
            page += 1
            continue
        body = r.json()
        comps = body.get("companies") or []
        n_new = 0
        for c in comps:
            if not isinstance(c, dict):
                continue
            slug = (c.get("slug") or "").strip()
            name = (c.get("name") or "").strip()
            if not slug or not name:
                continue
            regions = c.get("regions") or []
            if "Singapore" not in [x for x in regions if isinstance(x, str)]:
                continue  # hard signal check
            key = _norm(name)
            if not key:
                continue
            if key in by_name and by_name[key].get("source_platform") == "sg_yc":
                continue
            entry = {
                "company_name": name,
                "career_page_url": f"https://www.ycombinator.com/companies/{slug}",
                "website": (c.get("website") or "").strip(),
                "domain_hint": "",
                "ats_type": "yc",
                "source_platform": "sg_yc",
                "location": "Singapore",
            }
            if key not in by_name:
                added += 1
            by_name[key] = entry
            n_new += 1
        print(f"  [yc] page {page}: {len(comps)} companies, +{n_new} SG entries", flush=True)
        time.sleep(SLEEP)
        if not body.get("nextPage"):
            break
        page += 1
    return added


GALLERY_SG = "https://startups.gallery/categories/locations/countries/singapore"


def sweep_gallery(by_name: dict[str, dict]) -> int:
    """startups.gallery Singapore country+city pages (no pagination exists)."""
    import re
    s = requests.Session()
    slugs: list[str] = []
    for url in (GALLERY_SG, "https://startups.gallery/categories/locations/cities/singapore"):
        try:
            r = s.get(url, headers={"User-Agent": UA}, timeout=25)
            if r.status_code != 200:
                continue
            for sl in re.findall(r'href="(?:\.\./)+companies/([a-z0-9-]+)"', r.text):
                if sl not in slugs:
                    slugs.append(sl)
        except Exception as e:
            print(f"  [gallery] {url} failed: {e}", file=sys.stderr)
        time.sleep(SLEEP)
    added = 0
    for sl in slugs:
        name, web = sl.replace("-", " ").title(), ""
        try:
            r = s.get(f"https://startups.gallery/companies/{sl}", headers={"User-Agent": UA}, timeout=25)
            if r.status_code == 200:
                m = re.search(r'<meta property="og:title" content="([^"]*)"', r.text)
                if m:
                    name = m.group(1).replace("| startups.gallery", "").strip() or name
                for w in re.findall(r'href="(https?://[^"]+)"', r.text):
                    host = re.sub(r"^https?://", "", w).split("/")[0].lower()
                    if any(b in host for b in ("google", "framer", "gstatic", "startups.gallery",
                                               "cloudfront", "amazonaws", "youtube", "twitter",
                                               "x.com", "linkedin", "facebook", "instagram")):
                        continue
                    web = w
                    break
        except Exception:
            pass
        key = _norm(name)
        if not key or (key in by_name and by_name[key].get("source_platform") != "sg_awesome"):
            continue
        by_name[key] = {
            "company_name": name,
            "career_page_url": f"https://startups.gallery/companies/{sl}",
            "website": web,
            "domain_hint": "",
            "ats_type": "unknown",
            "source_platform": "sg_gallery",
            "location": "Singapore",
        }
        added += 1
        time.sleep(SLEEP)
    return added


def sweep_awesome(by_name: dict[str, dict]) -> int:
    """GitHub-hosted Singapore startup lists.

    1. M-Sharan-Balaji/startup-map-sg data/startups.json (curated SG startup map).
    2. belligerentbeagle/web-scraper-for-VCs-and-startups outputDescription.csv
       (SG AI-startup scrape; name from snippet when stated, else domain-derived).
    """
    import csv
    import io
    import re
    added = 0
    seen_hosts: set[str] = set()
    for e in by_name.values():
        w = e.get("website") or ""
        if w:
            h = re.sub(r"^https?://", "", w).split("/")[0].lower().removeprefix("www.")
            if h:
                seen_hosts.add(h)

    def add(name: str, website: str) -> bool:
        nonlocal added
        name = (name or "").strip()
        website = (website or "").strip()
        if not name or len(name) > 70:
            return False
        host = re.sub(r"^https?://", "", website).split("/")[0].lower().removeprefix("www.") if website else ""
        if host and host in seen_hosts:
            return False
        key = _norm(name)
        if not key or key in by_name:
            return False
        by_name[key] = {
            "company_name": name,
            "career_page_url": "",
            "website": website,
            "domain_hint": host,
            "ats_type": "unknown",
            "source_platform": "sg_awesome",
            "location": "Singapore",
        }
        if host:
            seen_hosts.add(host)
        added += 1
        return True

    # 1. startup-map-sg dataset
    body = None
    for br in ("main", "master"):
        try:
            r = requests.get(
                f"https://raw.githubusercontent.com/M-Sharan-Balaji/startup-map-sg/{br}/data/startups.json",
                headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 200:
                body = r.json()
                break
        except Exception:
            pass
        time.sleep(SLEEP)
    n_map = 0
    if isinstance(body, dict):
        for st in body.get("startups") or []:
            if not isinstance(st, dict):
                continue
            if add(st.get("name") or "", st.get("website") or ""):
                n_map += 1
    print(f"  [awesome] startup-map-sg: +{n_map}", flush=True)

    # 2. VC-scraper CSV slice
    n_csv = 0
    try:
        r = requests.get(
            "https://raw.githubusercontent.com/belligerentbeagle/web-scraper-for-VCs-and-startups/master/outputDescription.csv",
            headers={"User-Agent": UA}, timeout=30)
        if r.status_code == 200:
            verbs = (" is ", " was ", " are ", " uses ", " works ", " creates ", " builds ",
                     " helps ", " provides ", " specialises ", " specializes ", " integrates ",
                     " makes ", " delivers ", " offers ")
            for row in csv.DictReader(io.StringIO(r.text)):
                dom = (row.get("Website URL") or "").strip().rstrip(".")
                snip = (row.get("Snippet") or "").strip()
                if not dom or "." not in dom or dom == "NIL":
                    continue
                name = ""
                if snip and snip != "NIL":
                    first = snip.split(". ")[0].split(", ")[0]
                    for v in verbs:
                        i = first.find(v)
                        if 0 < i <= 45:
                            cand = first[:i].strip()
                            if cand and cand[:1].isupper() and cand.lower() != "company":
                                name = cand
                            break
                if not name:
                    base = dom.split("/")[0].split(".")[0]
                    name = "-".join(base.split("-")).replace("_", " ").strip().title() or dom
                if add(name, f"https://{dom}"):
                    n_csv += 1
    except Exception as e:
        print(f"  [awesome] csv failed: {e}", file=sys.stderr)
    print(f"  [awesome] vc-scraper csv: +{n_csv}", flush=True)
    return added


def main() -> int:
    by_name = load_out()
    a = sweep_yc(by_name)
    write_out(by_name)
    b = sweep_gallery(by_name)
    write_out(by_name)
    c = sweep_awesome(by_name)
    write_out(by_name)
    print(f"[sg] yc=+{a} gallery=+{b} awesome=+{c}; total {len(by_name)} entries in {RAW_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
