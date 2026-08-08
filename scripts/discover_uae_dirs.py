#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "uae_dirs.json")

ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
             "smartrecruiters.com", "teamtailor.com", "personio.", "rippling.com",
             "breezyhr", "myworkdayjobs.com", "onlyfy", "applytojob", "attrax",
             "pinpoint", "bamboohr")


def get(url: str, timeout: int = 25, tries: int = 3) -> str:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(4 * (i + 1))
    return ""


def _host(url: str) -> str:
    url = url.strip()
    if url and not url.startswith("http"):
        url = "http://" + url
    return urllib.parse.urlparse(url).hostname or ""


def _is_ats(url: str) -> str | None:
    u = url.lower()
    for h in ATS_HOSTS:
        if h in u:
            return "greenhouse" if "greenhouse" in u else \
                   "lever" if "lever.co" in u else \
                   "ashby" if "ashbyhq" in u else \
                   "workable" if "workable" in u else \
                   "smartrecruiters" if "smartrecruiters" in u else \
                   "teamtailor" if "teamtailor" in u else \
                   "personio" if "personio" in u else \
                   "rippling" if "rippling" in u else \
                   "breezyhr" if "breezyhr" in u else \
                   "workday" if "myworkdayjobs" in u else "unknown-ats"
    return None


def _walk_json(o, found: list, depth=0):
    if depth > 8:
        return
    if isinstance(o, dict):
        name = o.get("name") or o.get("title") or o.get("legalName") or o.get("companyName")
        web = o.get("website") or o.get("url") or o.get("homepage") or o.get("domain") or ""
        if isinstance(name, str) and name and isinstance(web, str) and web:
            host = _host(web)
            if host and host not in ("www.dxbstart.com", "dxbstart.com",
                                     "hub71.com", "www.hub71.com", "github.com", "www.github.com"):
                found.append((name.strip(), web.strip()))
        for v in o.values():
            _walk_json(v, found, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _walk_json(v, found, depth + 1)


def _extract_json(html: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for b in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            _walk_json(json.loads(b), out)
        except Exception:
            pass
    m = re.search(r'__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            _walk_json(json.loads(m.group(1)), out)
        except Exception:
            pass
    return out


def hub71() -> list[tuple[str, str]]:
    html = get("https://hub71.com/startups")
    if not html:
        return []
    pairs = _extract_json(html)
    seen, out = set(), []
    for n, w in pairs:
        k = re.sub(r"[^a-z0-9]", "", n.lower())
        if k and k not in seen:
            seen.add(k); out.append((n, w))
    print(f"[uae-dirs] hub71: {len(out)} companies")
    return out


def dxbstart() -> list[tuple[str, str]]:
    html = get("https://www.dxbstart.com/company")
    if not html:
        return []
    slugs = sorted(set(re.findall(r'/company/([a-z0-9][a-z0-9-]*[a-z0-9])', html)))
    print(f"[uae-dirs] dxbstart: {len(slugs)} slugs; scraping detail pages (bounded)…")
    out: list[tuple[str, str]] = []
    seen = set()
    for i, s in enumerate(slugs[:220]):
        d = get(f"https://www.dxbstart.com/company/{s}", timeout=15, tries=2)
        if not d:
            continue
        for n, w in _extract_json(d):
            k = re.sub(r"[^a-z0-9]", "", n.lower())
            if k and k not in seen:
                seen.add(k); out.append((n, w))
        if (i + 1) % 40 == 0:
            print(f"  …{i + 1}/{len(slugs)} detail pages, {len(out)} with websites")
            time.sleep(1)
    print(f"[uae-dirs] dxbstart: {len(out)} companies with websites")
    return out


def awesome_lists() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    md = get("https://raw.githubusercontent.com/tvthatsme/dubai-dev-jobs/master/README.md")
    if md:
        for line in md.splitlines():
            m = re.match(r'\s*[-*]\s*\[(.+?)\]\((https?://[^)]+)\)', line)
            if m:
                name, url = m.group(1).strip(), m.group(2).strip()
                host = _host(url)
                if host and "tvthatsme" not in host:
                    out.append((name, url))
    print(f"[uae-dirs] awesome-lists: {len(out)} companies")
    return out


def main() -> int:
    rows: dict[str, dict] = {}

    def add(name: str, website: str):
        name = (name or "").strip()
        website = (website or "").strip()
        if not name or not website:
            return
        key = re.sub(r"[^a-z0-9]", "", name.lower()) or _host(website)
        if not key or key in rows:
            return
        ats = _is_ats(website)
        rows[key] = {
            "company_name": name,
            "website": website if not ats else "",
            "career_page_url": website if ats else "",
            "ats_type": ats or "unknown",
            "source": "uae-dirs",
        }

    for n, w in hub71() + dxbstart() + awesome_lists():
        add(n, w)

    out = list(rows.values())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"[uae-dirs] wrote {len(out)} UAE candidates -> {OUT}")
    return len(out)


if __name__ == "__main__":
    main()