#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SPARQL = "https://query.wikidata.org/sparql"
UA = "job_auto/1.0 (company discovery; contact: n/a)"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "uae_wikidata.json")

Q_UAE = "Q878"
ORG_TYPES = ["Q43229", "Q4830453", "Q785020", "Q6881511", "Q167037"]

Q_BY_COUNTRY = """
SELECT DISTINCT ?c ?cLabel ?website WHERE {
  ?c wdt:P17 wd:%s.
  ?c wdt:P856 ?website.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % Q_UAE

Q_AE_DOMAIN = """
SELECT DISTINCT ?c ?cLabel ?website WHERE {
  ?c wdt:P856 ?website.
  FILTER(REGEX(STR(?website), "\\\\.ae(/|$|:)"))
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def run_sparql(query: str, tries: int = 4) -> list[dict]:
    last = ""
    for i in range(tries):
        try:
            data = urllib.parse.urlencode({"query": query}).encode()
            req = urllib.request.Request(
                SPARQL, data=data,
                headers={"Accept": "application/sparql-results+json",
                         "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
            return d.get("results", {}).get("bindings", [])
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(8 * (i + 1))
    print(f"[uae-wikidata] SPARQL failed after {tries} tries: {last}", file=sys.stderr)
    return []


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or ""


def main() -> int:
    out: dict[str, dict] = {}

    def add(name: str, website: str):
        name = (name or "").strip()
        website = (website or "").strip()
        if not name or not website:
            return
        key = re.sub(r"[^a-z0-9]", "", name.lower()) or _host(website)
        if not key:
            return
        out[key] = {
            "company_name": name,
            "website": website,
            "career_page_url": "",
            "ats_type": "unknown",
            "source": "uae-wikidata",
        }

    print("[uae-wikidata] query 1: P17=UAE companies with website …")
    for b in run_sparql(Q_BY_COUNTRY):
        add(b.get("cLabel", {}).get("value", ""), b.get("website", {}).get("value", ""))
    print(f"  -> {len(out)} so far")

    print("[uae-wikidata] query 2: .ae-domain websites …")
    n0 = len(out)
    for b in run_sparql(Q_AE_DOMAIN):
        add(b.get("cLabel", {}).get("value", ""), b.get("website", {}).get("value", ""))
    print(f"  -> +{len(out) - n0} from .ae-domain, total {len(out)}")

    rows = list(out.values())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"[uae-wikidata] wrote {len(rows)} UAE candidates -> {OUT}")
    return len(rows)


if __name__ == "__main__":
    main()