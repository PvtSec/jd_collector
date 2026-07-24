#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RAW_OUT = os.path.join(DATA, "raw", "agent13_awesome.json")
CACHE = os.path.join(DATA, ".cache_awesome")
UA = "Mozilla/5.0 (job-auto awesome-list discovery; research)"

# (owner/repo, branch-fallbacks, source_platform tag)
AWESOME_SOURCES = [
    ("Nic-Sevic/remote-jobs", ["master", "main"], "remoteintech"),
    ("fireball787b/awesome-remote-companies", ["main", "master"], "awesome-remote-companies"),
    ("adherb/remote-tech-companies", ["main", "master"], "remote-tech-companies"),
    # security-tool / vendor lists (company names embedded in tool listings)
    ("sbilly/awesome-security", ["master", "main"], "awesome-security"),
    ("enaqx/awesome-pentest", ["master", "main"], "awesome-pentest"),
    ("paragonie/awesome-appsec", ["master", "main"], "awesome-appsec"),
]

# Host substrings that mark an ATS-hosted board URL -> career_page_url (direct).
ATS_HOST_MARKERS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "personio.com", "teamtailor.com", "rippling.com",
    "breezy.hr", "onlyfy.jobs", "myworkdayjobs.com", "pinpointhq.com",
    "trinethire.com", "applytojob.com", "bamboohr.com", "comeet.com",
    "jobvite.com", "recruitee.com", "catsone.com", "hireology.com",
    "niceboard.com", "freshteam.com",
]
CAREERS_PATH_MARKERS = ["/careers", "/jobs", "/career", "/job-openings", "/openings"]

# Link text we should NOT treat as a company name (meta / navigation).
META_TEXT = {
    "contributing", "contribute", "license", "readme", "table of contents",
    "contents", "back to top", "edit", "pull request", "issue", "wiki",
    "home", "website", "blog", "twitter", "linkedin", "github", "gitlab",
    "glassdoor", "discord", "slack", "youtube", "facebook", "instagram",
    "rss", "feed", "about", "contact", "here", "this list", "the list",
    "start", "top", "bottom", "search", "apply", "remote", "remote jobs",
    "remote work", "job board", "job boards", "resources", "tools",
    "companies", "company", "values", "culture", "salary", "description",
    "yes", "no", "unknown", "n/a", "na",
}

# URL substrings that mean the link is NOT a company site (skip it).
SKIP_URL_MARKERS = [
    "github.com", "gitlab.com", "twitter.com", "x.com", "linkedin.com",
    "glassdoor.", "wikipedia.org", "youtube.com", "reddit.com", "discord.",
    "slack.", "facebook.com", "instagram.com", "crunchbase.com",
    "angel.co", "wellfound.com", "otta.com", "g2.com", "capterra.com",
    "mailto:", "t.me/", "hackerone.com", "bugcrowd.com", # bounty platforms, not employers here
]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _fetch_text(url: str) -> str:
    r = requests.get(url, timeout=25, headers={"User-Agent": UA})
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    return r.text


def _fetch_readme(owner_repo: str, branches: list[str]) -> str:
    base = f"https://raw.githubusercontent.com/{owner_repo}"
    os.makedirs(CACHE, exist_ok=True)
    cache_key = owner_repo.replace("/", "__")
    for br in branches:
        url = f"{base}/{br}/README.md"
        try:
            txt = _fetch_text(url)
            if txt:
                # cache for polite re-runs within the cadence
                try:
                    open(os.path.join(CACHE, cache_key + ".md"), "w", encoding="utf-8").write(txt)
                except Exception:
                    pass
                return txt
        except Exception:
            continue
    # fall back to cache if live fetch failed
    cp = os.path.join(CACHE, cache_key + ".md")
    if os.path.exists(cp):
        return open(cp, encoding="utf-8").read()
    return ""


def _looks_like_careers(url: str) -> bool:
    u = url.lower()
    return any(m in u for m in ATS_HOST_MARKERS) or any(m in u for m in CAREERS_PATH_MARKERS)


def _extract(readme: str, source_platform: str) -> list[dict]:
    out = []
    seen = set()
    # match [Text](url)  — Text may contain one space/word; url http(s) or www
    for m in re.finditer(r"\[([^\]]{1,60})\]\((https?://[^\s)]+|www\.[^\s)]+)\)", readme):
        text = re.sub(r"`", "", m.group(1)).strip()
        url = m.group(2).strip()
        if not text:
            continue
        # skip images / nested links / markdown artifacts
        if text.startswith("!") or "[" in text or "]" in text or ">" in text:
            continue
        # strip leading list/table markers
        text = re.sub(r"^(#+|\||\*|-|>|\s|[0-9]+\.?\s)+", "", text).strip()
        # strip trailing punctuation
        text = text.strip(" \t\r\n|-*_:.,")
        if not text or len(text) > 60:
            continue
        low = text.lower().strip()
        # skip if the "name" is actually a URL
        if low.startswith(("http", "www.", "ftp")) or "://" in low:
            continue
        # skip meta / section-y text
        if low in META_TEXT or low.startswith("category:") or low.startswith("list of"):
            continue
        if any(s in url.lower() for s in SKIP_URL_MARKERS):
            continue
        if text.lower() in META_TEXT:
            continue
        # heuristic: a real company name has a letter and >=2 chars after norm
        if not re.search(r"[A-Za-z]", text):
            continue
        k = _norm(text)
        if not k or len(k) < 2 or k in seen:
            continue
        seen.add(k)
        url = url if url.startswith("http") else "https://" + url
        rec = {"company_name": text, "source_platform": source_platform}
        if _looks_like_careers(url):
            rec["career_page_url"] = url
        else:
            rec["website"] = url
        out.append(rec)
    return out


def main():
    records: list[dict] = []
    for owner_repo, branches, tag in AWESOME_SOURCES:
        readme = _fetch_readme(owner_repo, branches)
        if not readme:
            print(f"[awesome] {owner_repo}: README not fetched (skipping)")
            continue
        recs = _extract(readme, tag)
        records.extend(recs)
        print(f"[awesome] {owner_repo}: {len(recs)} company candidates")
        time.sleep(0.5)  # polite between lists

    # dedupe within this run by normalized name (keep first, prefer career_page_url)
    seen = set()
    deduped = []
    for r in records:
        k = _norm(r.get("company_name", ""))
        if k and k not in seen:
            seen.add(k)
            deduped.append(r)

    # merge with existing raw file (idempotent by name)
    existing: list[dict] = []
    if os.path.exists(RAW_OUT):
        try:
            existing = json.load(open(RAW_OUT, encoding="utf-8"))
        except Exception:
            existing = []
    ex_seen = {_norm(r.get("company_name", "")) for r in existing}
    merged = list(existing)
    added = 0
    for r in deduped:
        k = _norm(r.get("company_name", ""))
        if k and k not in ex_seen:
            ex_seen.add(k)
            merged.append(r)
            added += 1
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    with open(RAW_OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"[awesome] {added} new + {len(existing)} existing -> {len(merged)} records -> {RAW_OUT}")
    return merged


if __name__ == "__main__":
    main()