#!/usr/bin/env python3
"""Discover distinct employers from MyCareersFuture (Singapore national job board).

Public API (no auth):
    GET https://api.mycareersfuture.gov.sg/v2/jobs?search=&page=N&limit=100
Notes:
  * `limit` is server-capped at 100 (120/150/200/500 -> HTTP 400).
  * POST /v2/search ignores its `page`/`pageSize` body fields (always page 0, 20 rows).
  * Each result carries `postedCompany` with `name`, `uen`, `ssicCode`,
    `employeeCount`, and sometimes `companyUrl`.

Output: data/raw/agentSG03_mcf.json — JSON array, one entry per distinct employer
(dedup by company name, case-insensitive; richest website/uen wins).
State (resumable): /tmp/mcf_sg03_state.json

Politeness: custom research UA, 0.3s sleep between calls; 403/429/5xx -> 30s
backoff, 2 retries, then abort that endpoint.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time

import requests

API = "https://api.mycareersfuture.gov.sg/v2/jobs"
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "raw", "agentSG03_mcf.json")
STATE = "/tmp/mcf_sg03_state.json"
LIMIT = 100
SLEEP = 0.3
RETRY_SLEEP = 30
RETRIES = 2


def page_order(total_pages: int) -> list[int]:
    """Strided sweep: even pages first (breadth across the whole board), then odd."""
    evens = list(range(0, total_pages, 2))
    odds = list(range(1, total_pages, 2))
    return evens + odds


def domain_of(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if "//" in u:
        u = u.split("//", 1)[1]
    host = u.split("/", 1)[0].split(":", 1)[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def load_state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> int:
    budget_s = float(sys.argv[1]) if len(sys.argv) > 1 else 1140.0
    t0 = time.time()
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept": "application/json"})

    st = load_state()
    companies: dict[str, dict] = {c["company_name"].strip().casefold(): c
                                  for c in st.get("companies", [])}
    order: list[int] = st.get("order", [])
    idx: int = st.get("next_idx", 0)
    pages_done: set[int] = set(st.get("pages_done", []))
    blocked: list[str] = []

    def save() -> None:
        entries = sorted(companies.values(), key=lambda c: c["company_name"])
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            json.dump(entries, f, ensure_ascii=False, indent=1)
        os.replace(tmp, OUT)
        with open(STATE + ".tmp", "w") as f:
            json.dump({"companies": entries, "order": order, "next_idx": idx,
                       "pages_done": sorted(pages_done)}, f)
        os.replace(STATE + ".tmp", STATE)

    def fetch(page: int) -> dict | None:
        """Fetch one page. Uses curl -m for a TRUE wall-clock cap: requests'
        read timeout only fires between bytes, so a trickling/half-open
        connection could otherwise hang a page forever."""
        for attempt in range(1, RETRIES + 2):
            try:
                r = sess.get(API, params={"search": "", "page": page, "limit": LIMIT},
                             timeout=(10, 20))
                if r.status_code == 200:
                    return r.json()
                print(f"page {page}: HTTP {r.status_code} (attempt {attempt})", flush=True)
                if attempt > RETRIES:
                    # fall back to curl hard-cap before giving up
                    pass
            except Exception as e:  # noqa: BLE001
                print(f"page {page}: {type(e).__name__} (attempt {attempt})", flush=True)
            try:
                cp = subprocess.run(
                    ["curl", "-s", "--compressed", "-m", "25",
                     "-A", UA, "-H", "Accept: application/json",
                     f"{API}?search=&page={page}&limit={LIMIT}"],
                    capture_output=True, text=True, timeout=35)
                if cp.returncode == 0 and cp.stdout.strip():
                    return json.loads(cp.stdout)
                print(f"page {page}: curl rc={cp.returncode} (attempt {attempt})", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"page {page}: curl {type(e).__name__} (attempt {attempt})", flush=True)
            if attempt <= RETRIES:
                time.sleep(RETRY_SLEEP)
        return None

    # Discover total on first run.
    total = st.get("total")
    if not order:
        first = fetch(0)
        if first is None:
            print("FATAL: endpoint blocked on initial fetch", flush=True)
            return 2
        total = first.get("total") or 0
        order = page_order(math.ceil(total / LIMIT))
        # We already hold page 0's data; fall through to normal processing of idx 0.
        st_pages = {p: first for p in [0]}
    else:
        st_pages = {}

    since_save_entries = 0
    since_save_pages = 0
    while idx < len(order):
        if time.time() - t0 > budget_s:
            print(f"time budget {budget_s:.0f}s reached at idx {idx}/{len(order)}", flush=True)
            break
        page = order[idx]
        data = st_pages.pop(page, None)
        if data is None:
            data = fetch(page)
            time.sleep(SLEEP)
        if data is None:
            blocked.append(f"page {page}")
            if len(blocked) >= 3:
                print(f"endpoint failing repeatedly; stopping (blocked={blocked})", flush=True)
                break
            continue
        blocked.clear()
        pages_done.add(page)
        since_save_pages += 1
        for res in data.get("results") or []:
            pc = res.get("postedCompany") or {}
            name = (pc.get("name") or "").strip()
            if not name:
                continue
            key = name.casefold()
            url = (pc.get("companyUrl") or "").strip()
            e = companies.get(key)
            if e is None:
                e = {"company_name": name, "career_page_url": "", "website": "",
                     "domain_hint": "", "ats_type": "unknown",
                     "source_platform": "sg_mcf", "location": "Singapore",
                     "uen": pc.get("uen") or "", "job_count": 0}
                companies[key] = e
                since_save_entries += 1
            if url and not e.get("website"):
                e["website"] = url
                e["domain_hint"] = domain_of(url)
            if url and not e.get("career_page_url") and "/career" in url.lower():
                e["career_page_url"] = url
            if pc.get("uen") and not e.get("uen"):
                e["uen"] = pc["uen"]
            if pc.get("employeeCount") and not e.get("employee_count"):
                e["employee_count"] = pc["employeeCount"]
            if pc.get("ssicCode") and not e.get("ssic_code"):
                e["ssic_code"] = str(pc["ssicCode"])
            e["job_count"] += 1
        idx += 1
        if idx % 25 == 0:
            print(f"idx {idx}/{len(order)} pages_done={len(pages_done)} "
                  f"companies={len(companies)} elapsed={time.time()-t0:.0f}s", flush=True)
        if since_save_entries >= 200 or since_save_pages >= 60:
            save()
            since_save_entries = 0
            since_save_pages = 0
    save()
    print(f"DONE companies={len(companies)} pages_done={len(pages_done)} "
          f"of {len(order)} idx={idx} elapsed={time.time()-t0:.0f}s "
          f"with_website={sum(1 for c in companies.values() if c.get('website'))} "
          f"blocked={blocked}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
