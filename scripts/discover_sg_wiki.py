#!/usr/bin/env python3
"""Discover Singapore companies from Wikipedia (list page + company categories).

Writes/merges entries into data/raw/agentSG07_gov_wiki.json with
source_platform="sg_wiki". Uses the MediaWiki API (cleaner than HTML scraping)
plus Wikidata claims (P856 official website, P576 dissolution date) to enrich
and drop defunct entities.
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import quote

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
API = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
SLEEP = 0.35

# Subcategories of Category:Companies of Singapore worth sweeping for tech talent.
TECH_SUBCAT_KEYWORDS = (
    "software",
    "technology",
    "internet",
    "video game",
    "telecommunication",
    "electronics",
    "semiconductor",
    "e-commerce",
    "cyber",
    "artificial intelligence",
    "fintech",
    "financial technology",
    "computer",
    "data",
    "robotics",
    "defunct",  # collected to EXCLUDE below
)
# Never include pages whose title matches these (gov bodies, schools, lists).
TITLE_BLOCK = (
    "list of",
    "category:",
    "template:",
    "ministry of",
    " authority",
    " government",
    "statutory board",
    " university",
    " polytechnic",
    " institute of technical education",
    " college",
    " banknote",
    " timeline",
    "index of",
    "outline of",
)


def api_get(params, host=API):
    for attempt in range(3):
        try:
            r = requests.get(host, params={**params, "format": "json"}, headers=HEADERS, timeout=25)
            if r.status_code in (403, 429):
                time.sleep(30)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(5 * (attempt + 1))
    return None


def norm_name(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


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
        json.dump(entries, fh, indent=2, sort_keys=False)
    os.replace(tmp, OUT_PATH)


def collect_titles() -> set[str]:
    titles: set[str] = set()

    # 1) links from the curated list page
    j = api_get({"action": "query", "titles": "List of companies of Singapore",
                 "prop": "links", "pllimit": "max", "plnamespace": 0, "redirects": 1})
    if j:
        for p in j.get("query", {}).get("pages", {}).values():
            for l in p.get("links", []):
                titles.add(l["title"])
        for cont in range(5):  # continuation
            if "continue" not in j:
                break
            j = api_get({"action": "query", "titles": "List of companies of Singapore",
                         "prop": "links", "pllimit": "max", "plnamespace": 0, "redirects": 1,
                         **j["continue"]})
            if not j:
                break
            for p in j.get("query", {}).get("pages", {}).values():
                for l in p.get("links", []):
                    titles.add(l["title"])
    print(f"[wiki] list-page links: {len(titles)}", flush=True)

    # 2) tech-ish subcategories of Category:Companies of Singapore (2 levels deep)
    def subcats(cat: str, depth: int, seen: set[str]) -> list[str]:
        out = []
        j = api_get({"action": "query", "list": "categorymembers", "cmtitle": cat,
                     "cmtype": "subcat", "cmlimit": "max"})
        time.sleep(SLEEP)
        if not j:
            return out
        for m in j.get("query", {}).get("categorymembers", []):
            t = m["title"]
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            # only recurse when the parent looks relevant — keeps the sweep bounded
            if depth > 0 and any(k in cat.lower() for k in TECH_SUBCAT_KEYWORDS):
                out.extend(subcats(t, depth - 1, seen))
        return out

    seen: set[str] = set()
    all_subcats = subcats("Category:Companies of Singapore", 2, seen)
    # The direct subcats are containers ("... by industry") plus the fruitful
    # big ones; sweep those explicitly and the industry subcats by keyword.
    tech_cats = [c for c in all_subcats
                 if any(k in c.lower() for k in TECH_SUBCAT_KEYWORDS)
                 and "defunct" not in c.lower()]
    tech_cats += [
        "Category:Companies listed on the Singapore Exchange",
        "Category:Online companies of Singapore",
        "Category:Multinational companies headquartered in Singapore",
        "Category:Companies of Singapore by industry",
    ]
    by_industry = subcats("Category:Companies of Singapore by industry", 1, set())
    tech_cats += [c for c in by_industry
                  if any(k in c.lower() for k in TECH_SUBCAT_KEYWORDS)
                  and "defunct" not in c.lower()]
    tech_cats = sorted(set(tech_cats))
    print(f"[wiki] subcats seen={len(all_subcats)} sweep-matched={len(tech_cats)}", flush=True)

    def members(cat: str) -> list[str]:
        got = []
        kwargs = {"action": "query", "list": "categorymembers", "cmtitle": cat,
                  "cmtype": "page", "cmlimit": "max"}
        while True:
            j = api_get(kwargs)
            if not j:
                break
            got += [m["title"] for m in j.get("query", {}).get("categorymembers", [])
                    if m["ns"] == 0]
            if "continue" not in j:
                break
            kwargs = {**kwargs, **j["continue"]}
            time.sleep(SLEEP)
        return got

    for c in tech_cats:
        if "defunct" in c.lower():
            continue
        ms = members(c)
        titles.update(ms)
        time.sleep(SLEEP)
    print(f"[wiki] titles after categories: {len(titles)}", flush=True)

    # 3) members of the top tech categories themselves (not only subcats)
    for c in ("Category:Technology companies of Singapore",
              "Category:Software companies of Singapore",
              "Category:Financial technology companies of Singapore",
              "Category:Video game companies of Singapore",
              "Category:Telecommunication companies of Singapore",
              "Category:Electronics companies of Singapore"):
        titles.update(members(c))
        time.sleep(SLEEP)

    blocked = {t for t in titles if any(b in t.lower() for b in TITLE_BLOCK)}
    titles -= blocked
    print(f"[wiki] blocked {len(blocked)} titles (gov/school/list), kept {len(titles)}", flush=True)
    return titles


def fetch_websites(titles: list[str]) -> dict[str, str]:
    """Map page title -> official website via wikibase_item + P856."""
    out: dict[str, str] = {}
    title_to_qid: dict[str, str] = {}
    qid_to_title: dict[str, str] = {}

    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    for batch in chunks(titles, 50):
        j = api_get({"action": "query", "titles": "|".join(batch), "prop": "pageprops",
                     "ppprop": "wikibase_item", "redirects": 1})
        if not j:
            continue
        # resolve redirects title->final
        redir = {r["from"]: r["to"] for r in j.get("query", {}).get("redirects", [])}
        for p in j.get("query", {}).get("pages", {}).values():
            qid = (p.get("pageprops") or {}).get("wikibase_item")
            if qid:
                t = p.get("title", "")
                title_to_qid[t] = qid
                qid_to_title[qid] = t
        for orig, final in redir.items():
            if orig in titles and final in title_to_qid:
                title_to_qid[orig] = title_to_qid[final]
        time.sleep(SLEEP)

    qids = sorted(set(title_to_qid.values()))
    print(f"[wiki] qids resolved: {len(qids)}", flush=True)

    for batch in chunks(qids, 50):
        j = api_get({"action": "wbgetentities", "ids": "|".join(batch),
                     "props": "claims"}, host=WIKIDATA)
        if not j:
            continue
        for qid, ent in (j.get("entities") or {}).items():
            claims = ent.get("claims") or {}
            # defunct: dissolution date P576
            if "P576" in claims:
                continue
            for c in claims.get("P856", []):
                try:
                    url = c["mainsnak"]["datavalue"]["value"]
                except Exception:
                    continue
                if isinstance(url, str) and url.startswith("http"):
                    t = qid_to_title.get(qid)
                    if t and t not in out:
                        out[t] = url.split("?")[0]
        time.sleep(SLEEP)
    return out


def main() -> None:
    titles = sorted(collect_titles())
    websites = fetch_websites(titles)
    print(f"[wiki] websites found: {len(websites)}", flush=True)

    entries = []
    for t in titles:
        name = t.strip()
        if not name:
            continue
        web = websites.get(t, "")
        entries.append({
            "company_name": name,
            "career_page_url": "",
            "website": web,
            "domain_hint": web.replace("https://", "").replace("http://", "").split("/")[0] if web else "",
            "ats_type": "unknown",
            "source_platform": "sg_wiki",
            "location": "Singapore",
        })

    # merge into shared output file (only sg_wiki entries are ours to manage here)
    out = [e for e in load_out() if e.get("source_platform") != "sg_wiki"]
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
    print(f"[wiki] wrote {added} sg_wiki entries -> {OUT_PATH} (file total {len(out)})", flush=True)


if __name__ == "__main__":
    main()
