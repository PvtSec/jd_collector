#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RAW_OUT = os.path.join(DATA, "raw", "agent15_startupdirs.json")
CACHE = os.path.join(DATA, ".cache_startupdirs")
UA = "Mozilla/5.0 (job-auto startup-directory discovery; research)"

NEURONFEED = "https://neuronfeed.com/api/v1/startups"
MAX_PAGES = 5
PAGE_SIZE = 100


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


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


def _first(*vals):
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _iter_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("startups", "data", "items", "results", "companies"):
            v = data.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = v.get("startups") or v.get("data") or v.get("items") or v.get("results")
                if isinstance(inner, list):
                    return inner
    return []


def _name_of(obj: dict) -> str:
    return _first(obj.get("name"), obj.get("company_name"), obj.get("startup_name"),
                  obj.get("company"), obj.get("title"))


def _website_of(obj: dict) -> str:
    w = _first(obj.get("website"), obj.get("url"), obj.get("homepage"),
               obj.get("company_url"), obj.get("site"), obj.get("external_url"))
    if w and not w.startswith("http"):
        w = "https://" + w
    return w


def _fetch_paginated(base_url: str, source_platform: str, cache_file: str,
                     extra_params: dict | None = None) -> list[dict]:
    out: list[dict] = []
    cp = os.path.join(CACHE, cache_file)
    cached = _cache_get(cp, 6 * 3600)
    if cached is not None:
        try:
            return [r for r in json.loads(cached) if isinstance(r, dict)]
        except Exception:
            cached = None

    params = dict(extra_params or {})
    for page in range(1, MAX_PAGES + 1):
        params.update({"page": page, "limit": PAGE_SIZE})
        try:
            r = requests.get(base_url, params=params, timeout=25,
                             headers={"User-Agent": UA, "Accept": "application/json"})
            if r.status_code in (429, 401, 403):
                print(f"[startupdirs] {source_platform}: HTTP {r.status_code} on page {page} (stopping)")
                break
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[startupdirs] {source_platform}: page {page} failed: {e}")
            break
        items = _iter_items(data)
        if not items:
            break
        added_here = 0
        for obj in items:
            if not isinstance(obj, dict):
                continue
            name = _name_of(obj)
            if not name or len(name) > 80:
                continue
            rec = {"company_name": name, "source_platform": source_platform}
            web = _website_of(obj)
            if web:
                rec["website"] = web
            out.append(rec)
            added_here += 1
        # stop if last page (heuristic: fewer than a full page returned) OR
        # the page returned no new rows (pagination param ignored -> repeats)
        if len(items) < PAGE_SIZE or added_here == 0:
            break
        time.sleep(1.0)  # polite
    _cache_put(cp, json.dumps(out))
    print(f"[startupdirs] {source_platform}: {len(out)} companies")
    return out


def main():
    os.makedirs(CACHE, exist_ok=True)
    records: list[dict] = []
    records += _fetch_paginated(NEURONFEED, "neuronfeed", "neuronfeed.json")

    # dedupe within run
    seen, deduped = set(), []
    for r in records:
        k = _norm(r.get("company_name", ""))
        if k and k not in seen:
            seen.add(k)
            deduped.append(r)

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
    print(f"[startupdirs] {added} new + {len(existing)} existing -> {len(merged)} records -> {RAW_OUT}")
    return merged


if __name__ == "__main__":
    main()