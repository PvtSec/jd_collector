#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "job_auto/1.0 (company discovery; contact: n/a)"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "uae_osm.json")
BBOX = "22.6,51.5,26.5,56.6"

QUERY = """
[out:json][timeout:180];
(
  nwr["website"](%s);
  nwr["contact:website"](%s);
  nwr["url"](%s);
);
out tags;
""" % (BBOX, BBOX, BBOX)


def _host(url: str) -> str:
    url = url.strip()
    if url and not url.startswith("http"):
        url = "http://" + url
    return urllib.parse.urlparse(url).hostname or ""


def fetch(tries: int = 4) -> list[dict]:
    last = ""
    for i in range(tries):
        try:
            data = urllib.parse.urlencode({"data": QUERY}).encode()
            req = urllib.request.Request(
                OVERPASS, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.load(r)
            return d.get("elements", [])
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(10 * (i + 1))
    print(f"[uae-osm] Overpass failed after {tries} tries: {last}", file=sys.stderr)
    return []


def main() -> int:
    print("[uae-osm] querying Overpass for UAE businesses with websites …")
    elems = fetch()
    print(f"[uae-osm] got {len(elems)} OSM elements")
    out: dict[str, dict] = {}
    skipped = 0
    for e in elems:
        tags = e.get("tags") or {}
        name = (tags.get("name:en") or tags.get("name") or tags.get("brand:en")
                or tags.get("brand") or tags.get("operator") or "").strip()
        website = (tags.get("website") or tags.get("contact:website")
                   or tags.get("url") or "").strip()
        if not name or not website:
            skipped += 1
            continue
        amenity = tags.get("amenity", "")
        shop = tags.get("shop", "")
        if amenity in ("parking", "toilets", "atm", "bench", "fountain",
                       "drinking_water", "post_box", "telephone", "vending_machine"):
            continue
        host = _host(website)
        if not host:
            continue
        key = re.sub(r"[^a-z0-9]", "", name.lower()) or host
        if not key:
            continue
        out[key] = {
            "company_name": name,
            "website": website,
            "career_page_url": "",
            "ats_type": "unknown",
            "source": "uae-osm",
        }
    rows = list(out.values())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"[uae-osm] wrote {len(rows)} UAE candidates "
          f"({skipped} skipped: no name/website) -> {OUT}")
    return len(rows)


if __name__ == "__main__":
    main()