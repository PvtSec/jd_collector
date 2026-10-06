#!/usr/bin/env python3
"""Discover Singapore companies from Singapore-government-linked public lists.

Covered (2026-08):
  * SGInnovate portfolio (sginnovate.com/our-portfolio) — gov-backed deep-tech
    investor; portfolio cards carry company name + website.
  * AI Singapore "AI companies" spotlight category (aisingapore.org) —
    national AI programme; articles profile local AI startups.

Attempted and blocked (kept here so nobody re-burns time):
  * SGTech member directory (sgtech.org.sg/memberDirectory) — Next.js SPA
    whose backend (sgtech-prod-api.sgtech.org.sg) requires per-request
    X-Timestamp/X-Nonce/X-Signature HMAC headers; every endpoint returns
    403 Access Denied without them.
  * IMDA / SG Digital programme pages (imda.gov.sg) — bot challenge (HTTP
    202 + JS challenge) for datacenter IPs; empty page even via proxies.
  * web.archive.org fallback — unreachable from this host (TLS reset).

Writes/merges into data/raw/agentSG07_gov_wiki.json with source_platform="sg_gov".
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = os.environ.get(
    "JOBAUTO_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
OUT_PATH = os.path.join(DATA, "raw", "agentSG07_gov_wiki.json")

UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
HEADERS = {"User-Agent": UA}
SLEEP = 0.4

SKIP_HOST_TOKENS = (
    "aisingapore", "aiap.sg", "sginnovate", "linkedin", "facebook", "twitter", "x.com",
    "youtube", "instagram", "wp.com", "wordpress", "google", "apple", "microsoft",
    "github.com/aisingapore", "reddit", "gravatar", "w.org", "gmpg", "gnu.org",
    "schema.org", "ioai-official", "gov.sg", "imda.gov.sg", "mas.gov.sg", "sgtech.org.sg",
)

CARD = re.compile(
    r'<figure[^>]*><img src="[^"]+" alt="([^"]+)"\s*/?>.*?'
    r'<a href="(https?://[^"]+)" target="_blank" class="mt-3">',
    re.S,
)


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


def sginnovate() -> list[dict]:
    out: list[dict] = []
    text = get("https://www.sginnovate.com/our-portfolio")
    if not text:
        return out
    for name, url in CARD.findall(text):
        name = name.strip()
        if not name or name.lower() in ("home", "logo", "footer logo", "portfolio banner"):
            continue
        out.append({
            "company_name": name,
            "career_page_url": "",
            "website": url.rstrip("/"),
            "domain_hint": urlparse(url).netloc,
            "ats_type": "unknown",
            "source_platform": "sg_gov",
            "location": "Singapore",
        })
    return out


def slug_tokens(title: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", title.lower()) if len(tok) > 3}


def aisingapore() -> list[dict]:
    out: list[dict] = []
    text = get("https://aisingapore.org/category/ai-companies/")
    if not text:
        return out
    arts = re.findall(
        r'<h2[^>]*class="[^"]*entry-title[^"]*"[^>]*>\s*<a href="([^"]+)"[^>]*>([^<]+)</a>',
        text,
    )
    if not arts:
        arts = re.findall(
            r'<a href="(https://aisingapore.org/[a-z0-9-]{8,}/)"[^>]*>([^<]{8,90})</a>', text)
        seen = set()
        dedup = []
        for u, t in arts:
            if u not in seen and "/category/" not in u:
                seen.add(u)
                dedup.append((u, t))
        arts = dedup
    for url, _t in arts:
        time.sleep(SLEEP)
        art = get(url)
        if not art:
            continue
        m = re.search(r'property="og:title" content="([^"]*)"', art)
        if not m:
            m = re.search(r"<title>([^<]*)</title>", art)
        title = (m.group(1) if m else _t).strip()
        title = re.sub(r"\s*-\s*AI Singapore\s*$", "", title).strip()
        links = re.findall(r'href="(https?://([^"/]+)/?[^"]*)"', art)
        best = ""
        best_score = 0
        seen_hosts: set[str] = set()
        toks = slug_tokens(url.rsplit("/", 2)[-2] if url.endswith("/") else url.rsplit("/", 1)[-1])
        for full, host in links:
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            if any(tok in host for tok in SKIP_HOST_TOKENS):
                continue
            score = len(slug_tokens(host.replace("www.", "")) & toks)
            if score > best_score:
                best_score, best = score, full.rstrip("/")
        if title and len(title) > 2:
            out.append({
                "company_name": title,
                "career_page_url": "",
                "website": best if best_score > 0 else "",
                "domain_hint": urlparse(best).netloc if best and best_score > 0 else "",
                "ats_type": "unknown",
                "source_platform": "sg_gov",
                "location": "Singapore",
            })
    return out


def main() -> None:
    entries = sginnovate()
    print(f"[gov] sginnovate: {len(entries)}", flush=True)
    entries += aisingapore()
    print(f"[gov] +aisingapore: total {len(entries)}", flush=True)

    out = [e for e in load_out() if e.get("source_platform") != "sg_gov"]
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
    print(f"[gov] wrote {added} sg_gov entries -> {OUT_PATH} (file total {len(out)})", flush=True)


if __name__ == "__main__":
    main()
