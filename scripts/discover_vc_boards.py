#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RAW_OUT = os.path.join(DATA, "raw", "agent18_vc_boards.json")
CACHE = os.path.join(DATA, ".cache_vc")
UA = "Mozilla/5.0 (job-auto vc-board discovery; research)"

# ATS host substrings — emit a career_page_url only when a board apply URL lands on one of these
# (these boards almost always link to LinkedIn, so this rarely fires).
ATS_HOST_MARKERS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "personio.com", "teamtailor.com", "rippling.com",
    "breezy.hr", "onlyfy.jobs", "myworkdayjobs.com", "pinpointhq.com",
    "trinethire.com", "applytojob.com", "bamboohr.com", "comeet.com",
    "jobvite.com", "recruitee.com", "catsone.com", "hireology.com",
    "niceboard.com", "freshteam.com",
]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _is_ats_url(url: str) -> bool:
    return any(m in url.lower() for m in ATS_HOST_MARKERS)


def _cache_get(path: str, max_age: float):
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age:
        try:
            return open(path, encoding="utf-8").read()
        except Exception:
            return None
    return None


def _cache_put(path: str, text: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)
    except Exception:
        pass


def _get(url: str, timeout: int = 30, headers=None) -> str:
    h = {"User-Agent": UA, "Accept": "text/html,application/json,application/xml,*/*"}
    if headers:
        h.update(headers)
    r = requests.get(url, timeout=timeout, headers=h)
    r.raise_for_status()
    return r.text


def _humanize_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    s = re.sub(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "", s)  # trailing uuid
    s = re.sub(r"-\d+$", "", s)          # trailing disambiguator -2
    s = re.sub(r"[-_]+", " ", s).strip()
    if not s:
        return ""
    # Title-case words but keep tokens that mix letters+digits (e.g. 'm3ter') intact-cased only on first letter
    words = []
    for w in s.split():
        words.append(w[:1].upper() + w[1:])
    return " ".join(words)


GETRO_SITEMAP = "https://jobs.insightpartners.com/sitemap_companies.xml"
GETRO_JOBS_SITEMAPS = [
    "https://jobs.insightpartners.com/sitemap_jobs1.xml",
    "https://jobs.insightpartners.com/sitemap_jobs2.xml",
]
GETRO_BACKFILL_STATE = os.path.join(CACHE, "getro_backfill.json")
GETRO_BACKFILL_BATCH = 30  # job pages fetched per run; ~534 slugs -> fully resolved in ~18 runs


def _getro_company_slugs() -> list[str]:
    cp = os.path.join(CACHE, "getro_companies.xml")
    txt = _cache_get(cp, 24 * 3600)
    if txt is None:
        txt = _get(GETRO_SITEMAP)
        _cache_put(cp, txt)
    root = ET.fromstring(txt)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    slugs = []
    for url in root.iter(ns + "url"):
        m = re.search(r"/companies/([^/?#]+)$", (url.findtext(ns + "loc") or "").strip())
        if m:
            slugs.append(m.group(1))
    return slugs


def _getro_job_url_by_slug() -> dict:
    by_slug: dict[str, str] = {}
    for sitemap in GETRO_JOBS_SITEMAPS:
        cp = os.path.join(CACHE, os.path.basename(sitemap))
        try:
            txt = _cache_get(cp, 24 * 3600)
            if txt is None:
                txt = _get(sitemap)
                _cache_put(cp, txt)
            for loc in re.findall(r"<loc>([^<]+)</loc>", txt):
                m = re.search(r"/companies/([^/]+)/jobs/", loc)
                if m and m.group(1) not in by_slug:
                    by_slug[m.group(1)] = loc
        except Exception as e:
            print(f"[vc] getro jobs sitemap {sitemap} failed: {e}")
    return by_slug


def _getro_backfill(job_url_by_slug: dict) -> dict:
    try:
        state = json.load(open(GETRO_BACKFILL_STATE, encoding="utf-8"))
    except Exception:
        state = {"resolved": {}, "tried": {}}
    resolved: dict = state.get("resolved", {})
    tried: dict = state.get("tried", {})

    # unresolved = slug with a job url, not yet resolved, and whose job url is new (or unseen)
    unresolved = [(s, u) for s, u in job_url_by_slug.items()
                  if s not in resolved and tried.get(s) != u]
    batch = unresolved[:GETRO_BACKFILL_BATCH]

    for slug, job_url in batch:
        try:
            html = _get(job_url, timeout=25)
        except Exception as e:
            print(f"[vc] getro backfill {slug} fetch failed (will retry): {e}")
            continue  # transient: leave un-tried so it retries next run
        name = None
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            try:
                d = json.loads(m.group(1))
                cj = d.get("props", {}).get("pageProps", {}).get("initialState", {}).get("jobs", {}).get("currentJob")
                if isinstance(cj, dict):
                    name = (cj.get("organization") or {}).get("name")
            except Exception:
                pass
        if name:
            resolved[slug] = name.strip()
        else:
            tried[slug] = job_url  # this url gave no name; a rotated url will retry

    try:
        os.makedirs(os.path.dirname(GETRO_BACKFILL_STATE), exist_ok=True)
        json.dump({"resolved": resolved, "tried": tried}, open(GETRO_BACKFILL_STATE, "w", encoding="utf-8"), indent=2)
    except Exception as e:
        print(f"[vc] getro backfill state save failed: {e}")
    print(f"[vc] getro backfill: {len(resolved)} resolved, {len(tried)} tried-no-name, "
          f"{len(batch)} fetched this run")
    return resolved


def from_getro() -> list[dict]:
    out: list[dict] = []
    try:
        slugs = _getro_company_slugs()
    except Exception as e:
        print(f"[vc] getro sitemap fetch/parse failed: {e}")
        return out

    # Best-effort accurate names via a bounded batch of SSR job pages (slug -> currentJob.org.name).
    resolved: dict = {}
    try:
        job_url_by_slug = _getro_job_url_by_slug()
        if job_url_by_slug:
            resolved = _getro_backfill(job_url_by_slug)
    except Exception as e:
        print(f"[vc] getro backfill skipped: {e}")

    resolved_count = 0
    for slug in slugs:
        name = resolved.get(slug) or _humanize_slug(slug)
        if not name:
            continue
        if slug in resolved:
            resolved_count += 1
        out.append({"company_name": name, "source_platform": "insight_partners"})
    print(f"[vc] getro (insight_partners): {len(out)} companies "
          f"({resolved_count} with accurate job-page names, rest slug-humanized)")
    return out


def _consider_initial(board_url: str) -> tuple[str, str]:
    txt = _get(board_url.rstrip("/") + "/jobs")
    m = re.search(r"window\.serverInitialData\s*=\s*(\{)", txt)
    if not m:
        raise RuntimeError("serverInitialData not found")
    seg = txt[m.end() - 1:]
    depth = end = 0
    for k, ch in enumerate(seg):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    d = json.loads(seg[:end])
    csrf = d.get("csrfToken") or ""
    board_id = (d.get("board") or {}).get("id") or ""
    if not csrf or not board_id:
        raise RuntimeError("csrf/board id missing")
    return csrf, board_id


def from_consider(board_url: str, board_id_hint: str, label: str, source_platform: str) -> list[dict]:
    out: list[dict] = []
    cp = os.path.join(CACHE, f"consider_{board_id_hint}.html")
    txt = _cache_get(cp, 24 * 3600)
    if txt is None:
        try:
            txt = _get(board_url.rstrip("/") + "/jobs")
            _cache_put(cp, txt)
        except Exception as e:
            print(f"[vc] consider {label} page fetch failed: {e}")
            return out
    try:
        m = re.search(r"window\.serverInitialData\s*=\s*(\{)", txt)
        seg = txt[m.end() - 1:]
        depth = end = 0
        for k, ch in enumerate(seg):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
        d = json.loads(seg[:end])
        csrf = d.get("csrfToken") or ""
        board_id = (d.get("board") or {}).get("id") or board_id_hint
        if not csrf:
            print(f"[vc] consider {label}: no csrf token")
            return out
    except Exception as e:
        print(f"[vc] consider {label} parse failed: {e}")
        return out

    # One shot — size large enough to fetch the whole portfolio (verified: size>=total returns all).
    size = 1000
    try:
        r = requests.post(
            board_url.rstrip("/") + "/api-boards/search-companies",
            timeout=40,
            headers={"User-Agent": UA, "Accept": "application/json",
                     "Content-Type": "application/json", "X-CSRF-Token": csrf,
                     "Origin": board_url, "Referer": board_url.rstrip("/") + "/companies"},
            data=json.dumps({"board": {"id": board_id, "isParent": True},
                             "query": {}, "meta": {"size": size}}),
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[vc] consider {label} search-companies failed: {e}")
        return out
    if data.get("errors"):
        print(f"[vc] consider {label} errors: {data['errors'][:1]}")
        return out
    for c in data.get("companies") or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        rec: dict = {"company_name": name, "source_platform": source_platform}
        web = (c.get("website") or {})
        if isinstance(web, dict):
            url = (web.get("url") or "").strip()
            if url:
                rec["website"] = url
        dom = (c.get("domain") or "").strip()
        # Consider's "domain" is inconsistent: sometimes a real domain ("anduril.com"),
        # sometimes an industry label ("AI/ML", "fintech/payments"). Only emit it as
        # domain_hint when it actually looks like a domain, so we don't mislabel.
        if dom and re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", dom.lower()):
            rec["domain_hint"] = dom
        out.append(rec)
    print(f"[vc] consider {label} ({source_platform}): {len(out)} companies (total {data.get('total')})")
    return out


INDEX_PAGE = "https://www.indexventures.com/startup-jobs"
ES_INDEX = "wagtail__startup_jobs_jobmodel"


def from_index_ventures() -> list[dict]:
    out: list[dict] = []
    cp = os.path.join(CACHE, "index_page.html")
    txt = _cache_get(cp, 24 * 3600)
    if txt is None:
        try:
            txt = _get(INDEX_PAGE)
            _cache_put(cp, txt)
        except Exception as e:
            print(f"[vc] index ventures page fetch failed: {e}")
            return out
    # ES_GLOBALS.url = "https://<user>:<pass>@<host>.es.amazonaws.com"  (public search-only role)
    m = re.search(r'ES_GLOBALS\s*=\s*\{[^}]*?url\s*:\s*"(https://[^"]+\.es\.amazonaws\.com)"', txt, re.S)
    if not m:
        print("[vc] index ventures: ES_GLOBALS endpoint not found")
        return out
    es_url = m.group(1)
    parsed = urllib.parse.urlparse(es_url)
    host = parsed.hostname
    userpass = f"{parsed.username}:{parsed.password}" if parsed.username else ""
    if not host or not userpass:
        print("[vc] index ventures: ES endpoint missing host/creds")
        return out
    search_url = f"https://{host}/{ES_INDEX}/_search"
    body = json.dumps({
        "size": 0,
        "query": {"term": {"_django_content_type": "startup_jobs.JobModel"}},
        "aggs": {"companies": {"terms": {"field": "job_company_title_filter", "size": 1000}}},
    })
    try:
        r = requests.post(
            search_url, data=body, timeout=40,
            headers={"User-Agent": UA, "Content-Type": "application/json",
                     "Authorization": "Basic " + base64.b64encode(userpass.encode()).decode()},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[vc] index ventures ES query failed: {e}")
        return out
    buckets = (((data.get("aggregations") or {}).get("companies") or {}).get("buckets")) or []
    for b in buckets:
        name = (b.get("key") or "").strip()
        if name and b.get("doc_count", 0) > 0:
            out.append({"company_name": name, "source_platform": "index_ventures"})
    print(f"[vc] index ventures: {len(out)} companies")
    return out


WIZ_BOARD = "https://www.wiz.io/cloud-security-job-board"
WIZ_INDEX = "cloud-job-board"
# Public search-only Algolia key shipped in the board's client JS (fallback if runtime extraction fails).
WIZ_ALGOLIA_FALLBACK = ("HDR4182JVE", "2023c7fbf68076909d1a85ec42cea550")
_APPKEY_RE = re.compile(r'([A-Z0-9]{6,12})","([0-9a-f]{32})"')


def _wiz_algolia_keys(page_html: str) -> tuple[str, str]:
    srcs = list(dict.fromkeys(re.findall(r'<script[^>]*src="([^"]+)"', page_html)))
    srcs = [s for s in srcs if "/vc-ap-" in s]
    # the chunk URLs carry a ?dpl= query; fetch and scan for the appid/key pair
    for s in srcs:
        url = s if s.startswith("http") else "https://www.wiz.io" + s
        cp = os.path.join(CACHE, "wiz_chunk_" + re.sub(r"[^a-z0-9]", "_", s[-40:].lower()) + ".js")
        txt = _cache_get(cp, 24 * 3600)
        if txt is None:
            try:
                txt = _get(url, timeout=25)
                _cache_put(cp, txt)
            except Exception:
                continue
        m = _APPKEY_RE.search(txt)
        if m:
            return m.group(1), m.group(2)
    return WIZ_ALGOLIA_FALLBACK


def from_cloudsecurity_jobs() -> list[dict]:
    out: list[dict] = []
    cp = os.path.join(CACHE, "wiz_board.html")
    txt = _cache_get(cp, 24 * 3600)
    if txt is None:
        try:
            txt = _get(WIZ_BOARD)
            _cache_put(cp, txt)
        except Exception as e:
            print(f"[vc] cloudsecurity.jobs (wiz) page fetch failed: {e}")
            return out
    app_id, api_key = _wiz_algolia_keys(txt)
    url = f"https://{app_id}-dsn.algolia.net/1/indexes/{WIZ_INDEX}/query"
    body = json.dumps({"params": "hitsPerPage=1000&query="})
    try:
        r = requests.post(url, data=body, timeout=40,
                          headers={"User-Agent": UA, "Content-Type": "application/json",
                                   "X-Algolia-Application-Id": app_id,
                                   "X-Algolia-API-Key": api_key})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[vc] cloudsecurity.jobs (wiz) algolia query failed: {e}")
        return out
    seen: set[str] = set()
    for h in data.get("hits") or []:
        name = (h.get("company_name") or "").strip()
        if not name:
            continue
        k = _norm(name)
        if k and k not in seen:
            seen.add(k)
            out.append({"company_name": name, "source_platform": "cloudsecurity_jobs"})
    print(f"[vc] cloudsecurity_jobs (wiz): {len(out)} companies (nbHits {data.get('nbHits')})")
    return out


def main():
    records: list[dict] = []
    records += from_getro()
    records += from_consider("https://jobs.sequoiacap.com", "sequoia-capital", "sequoia", "sequoia")
    records += from_consider("https://jobs.lsvp.com", "lightspeed", "lightspeed", "lightspeed")
    records += from_index_ventures()
    records += from_cloudsecurity_jobs()

    # dedupe within run (keep website/career_page_url if any source had one)
    by_name: dict[str, dict] = {}
    for r in records:
        k = _norm(r.get("company_name", ""))
        if not k:
            continue
        if k not in by_name:
            by_name[k] = r
        else:
            for f in ("career_page_url", "website", "domain_hint"):
                if f in r and f not in by_name[k]:
                    by_name[k][f] = r[f]
    deduped = list(by_name.values())

    existing: list[dict] = []
    if os.path.exists(RAW_OUT):
        try:
            existing = json.load(open(RAW_OUT, encoding="utf-8"))
        except Exception:
            existing = []
    # Insight Partners names start slug-humanized and are upgraded to accurate job-page names
    # gradually by the backfill, so drop stale insight_partners rows and re-emit the fresh set
    # each run (safe at the consolidate level — grouping is by normalized name). Other boards
    # emit accurate names directly and stay merge-append (idempotent).
    existing = [r for r in existing if r.get("source_platform") != "insight_partners"]
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
    print(f"[vc] {added} new + {len(existing)} existing -> {len(merged)} records -> {RAW_OUT}")
    return merged


if __name__ == "__main__":
    main()