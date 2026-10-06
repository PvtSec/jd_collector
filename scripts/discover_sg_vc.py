#!/usr/bin/env python3
"""Discover Singapore companies from SG-focused VC fund / incubator portfolio pages.

Sources: Antler (SG-filtered, paginated Webflow CMS), EF (location tiles), and the
portfolio grids / detail pages of ~15 SG funds. Output: data/raw/agentSG06_vc.json.

Politeness: 0.35s min spacing per host, 403/429 -> 30s backoff x2. Public pages only.
Parsing: html.parser / substring checks only (no regex over HTML).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from html.parser import HTMLParser

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RAW_OUT = os.path.join(DATA, "raw", "agentSG06_vc.json")
CACHE = os.path.join(DATA, ".cache_sgvc")
EXTRA_IN = os.path.join(CACHE, "webfetch_extra.json")  # entries gathered via remote fetch
UA = "Mozilla/5.0 (job-auto sg-discovery; research)"

SOCIAL = ("linkedin.com", "twitter.com", "x.com", "facebook.com", "medium.com",
          "instagram.com", "youtube.com", "crunchbase.com", "mailto:", "tel:",
          "wp.com", "website-files.com", "creativecommons.org", "wordpress.org",
          "google.com", "apple.com", "play.google", "apps.apple", "t.me", "wa.me",
          "bloomberg.com", "forbes.com", "cnbc.com", "reuters.com", "techcrunch.com",
          "techinasia.com", "e27.co", "dealstreetasia.com", "intralinks",
          "investorvision.io", "docs.google.com")

_last_host_ts: dict[str, float] = {}
_failed_hosts: set[str] = set()


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def _cache_path(url: str) -> str:
    return os.path.join(CACHE, urllib.parse.quote(url, safe="")[:180])


def fetch(url: str, max_age: float = 3600 * 6, timeout: int = 30) -> str | None:
    """Polite GET with disk cache, per-host spacing, and 403/429 backoff."""
    host = host_of(url)
    if host in _failed_hosts:
        return None
    cp = _cache_path(url)
    if os.path.exists(cp) and (time.time() - os.path.getmtime(cp)) < max_age:
        try:
            return open(cp, encoding="utf-8").read()
        except Exception:
            pass
    for attempt in range(3):
        wait = _last_host_ts.get(host, 0) + 0.35 - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_host_ts[host] = time.time()
        try:
            r = requests.get(url, timeout=timeout, headers={
                "User-Agent": UA, "Accept": "text/html,application/json,*/*"})
            if r.status_code in (403, 429) and attempt < 2:
                time.sleep(30)
                continue
            r.raise_for_status()
            os.makedirs(CACHE, exist_ok=True)
            open(cp, "w", encoding="utf-8").write(r.text)
            return r.text
        except requests.RequestException:
            if attempt < 2:
                time.sleep(2)
                continue
    _failed_hosts.add(host)
    return None


class AnchorScanner(HTMLParser):
    """Collects anchors (text, href, class, aria-label) and img alt attributes in order."""

    def __init__(self):
        super().__init__()
        self.items = []  # list of dicts, in document order
        self._a = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self._a = {"text": [], "href": d.get("href"),
                       "cls": d.get("class") or "", "aria": d.get("aria-label") or ""}
        elif tag == "img":
            alt = d.get("alt") or ""
            if alt.strip():
                self.items.append({"kind": "img", "alt": alt.strip()})

    def handle_data(self, data):
        if self._a is not None:
            self._a["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            self._a["text"] = " ".join("".join(self._a["text"]).split())
            self.items.append({"kind": "a", **self._a})
            self._a = None


class TextScanner(HTMLParser):
    """Collects (tag, attrs, text) triples, flattening nested text into each open tag."""

    def __init__(self, wanted_tags):
        super().__init__()
        self.hits = []
        self._stack = []
        self.wanted = set(wanted_tags)

    def handle_starttag(self, tag, attrs):
        if tag in self.wanted:
            self._stack.append({"tag": tag, "attrs": dict(attrs), "buf": []})

    def handle_endtag(self, tag):
        if tag in self.wanted and self._stack:
            top = self._stack.pop()
            top["text"] = " ".join("".join(top["buf"]).split())
            self.hits.append(top)

    def handle_data(self, data):
        for frame in self._stack:
            frame["buf"].append(data)


def scan(html: str) -> AnchorScanner:
    p = AnchorScanner()
    p.feed(html)
    return p


def is_company_url(url: str, fund_hosts) -> bool:
    if not url or not url.startswith("http"):
        return False
    u = url.lower()
    if any(s in u for s in SOCIAL):
        return False
    if "/login" in u or u.split("//")[-1].startswith("login.") or "portal" in u:
        return False
    h = host_of(u)
    if not h or h in ("localhost",):
        return False
    for fh in fund_hosts:
        if h == fh or h.endswith("." + fh) or fh.endswith("." + h):
            return False
    return True


def name_from_domain(url: str) -> str:
    h = host_of(url) or url
    h = h.removeprefix("www.").removeprefix("blog.").removeprefix("hello.")
    base = h.split(".")[0].split(":")[0]
    return " ".join(w.capitalize() for w in base.replace("-", " ").replace("_", " ").split())


def guess_name(items, idx, url, fund_hosts):
    """Best-effort company name: anchor text, aria-label, nearby img alt, linkedin slug, domain."""
    it = items[idx]
    if it.get("aria"):
        return it["aria"].strip()
    t = (it.get("text") or "").strip()
    if t and " " in t:  # long anchor text is usually a description; short is a name
        if len(t) <= 40 and t.lower() not in ("visit website", "visit", "website", "learn more"):
            return t
    for j in range(idx - 1, max(-1, idx - 6), -1):
        if items[j]["kind"] == "img":
            alt = items[j]["alt"]
            for suffix in (" logo", "-logo", "_logo", " logo png"):
                alt = alt.replace(suffix, "")
            if alt.strip() and len(alt) <= 45:
                return alt.strip()
    low = url.lower()
    if "linkedin.com/company/" in low:
        slug = url.split("/company/")[1].strip("/").split("/")[0].split("?")[0]
        return " ".join(w.capitalize() for w in slug.replace("-", " ").split())
    return name_from_domain(url)


# ---------------------------------------------------------------- entry plumbing

ENTRIES: dict[str, dict] = {}


def norm_key(name: str, website: str) -> str:
    dom = host_of(website).removeprefix("www.") if website else ""
    key = "".join(c for c in (dom or name).lower() if c.isalnum())
    return key or name.lower()


def add(name, website="", careers="", vc="", ats="unknown"):
    name = (name or "").strip()
    if not name or len(name) > 90:
        return
    website = (website or "").strip()
    k = norm_key(name, website)
    if not k:
        return
    if k in ENTRIES:
        e = ENTRIES[k]
        if vc and vc not in e["vc_source"]:
            e["vc_source"] += "+" + vc
        if website and not e["website"]:
            e["website"] = website
            e["domain_hint"] = host_of(website).removeprefix("www.")
        return
    ENTRIES[k] = {
        "company_name": name,
        "career_page_url": careers,
        "website": website,
        "domain_hint": host_of(website).removeprefix("www.") if website else "",
        "ats_type": ats if ats in ("greenhouse", "lever", "ashby", "smartrecruiters",
                                   "workable", "personio", "teamtailor", "bamboohr",
                                   "breezyhr", "recruitee", "pinpoint", "rippling",
                                   "workday") else "unknown",
        "source_platform": "sg_vc",
        "vc_source": vc,
        "location": "Singapore",
    }


def flush():
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    tmp = RAW_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(ENTRIES.values()), f, indent=2, ensure_ascii=False)
    os.replace(tmp, RAW_OUT)


# ---------------------------------------------------------------- fund handlers

def fund_antler():
    """antler.co/portfolio — Webflow CMS, paginated, cards tagged with location."""
    base = "https://www.antler.co/portfolio"
    html = fetch(base)
    if not html:
        return 0
    page_param = None
    i = html.find("_page=2")
    if i > 0:
        j = html.rfind("?", 0, i)
        page_param = html[j + 1:i + len("_page=2") - 2]
    n, page, seen = 0, 1, set()
    while page < 40:
        url = base if page == 1 else f"{base}?{page_param}={page}"
        h = fetch(url) if page > 1 else html
        if not h or "w-dyn-item" not in h:
            break
        p = TextScanner(["p", "div", "a"])
        p.feed(h)
        name = loc = site = None
        got = 0
        for hit in p.hits:
            a, t = hit["attrs"], hit["text"]
            f = a.get("fs-cmsfilter-field")
            if f == "name":
                name = t
            elif f == "location" and a.get("class", "").find("tag_small_text") >= 0 \
                    and loc is None:
                # first tag_small_text is the location; sector/year tags reuse the
                # same field name, so only the first value counts.
                loc = t
            elif hit["tag"] == "a" and "clickable_link" in (a.get("class") or "") \
                    and (a.get("href") or "").startswith("http") and "#" != a.get("href"):
                site = a.get("href")
            if name and loc and site:
                if loc.strip().lower() == "singapore" and site not in seen:
                    seen.add(site)
                    add(name, website=site, vc="Antler")
                    n += 1
                name = loc = site = None
                got += 1
        if got == 0:
            break
        page += 1
    return n


def fund_ef():
    """joinef.com/portfolio — paginated tiles with location tags; no outbound sites."""
    n, page = 0, 1
    while page < 30:
        url = "https://www.joinef.com/portfolio/" + (f"?pagenum={page}" if page > 1 else "")
        h = fetch(url)
        if not h or "data-companyname" not in h:
            break
        p = TextScanner(["div", "a"])
        p.feed(h)
        name = loc = None
        got = 0
        for hit in p.hits:
            a, t = hit["attrs"], hit["text"]
            if hit["tag"] == "div" and "tile__link" in (a.get("class") or ""):
                name = a.get("data-companyname") or t
            elif hit["tag"] == "a" and "locationtag" in (a.get("class") or ""):
                loc = t
            if name and loc:
                if loc.strip().lower() == "singapore":
                    add(name, vc="Entrepreneur First")
                    n += 1
                name = loc = None
                got += 1
        if got == 0:
            break
        page += 1
    return n


def fund_grid(base_url, vc, fund_host, anchor_filter=None):
    """Portfolio grid whose cards link straight to company websites."""
    h = fetch(base_url)
    if not h:
        return 0
    p = scan(h)
    n = 0
    for idx, it in enumerate(p.items):
        if it["kind"] != "a":
            continue
        if anchor_filter and anchor_filter not in (it.get("cls") or ""):
            continue
        url = it["href"]
        if not is_company_url(url, (fund_host,)):
            continue
        name = guess_name(p.items, idx, url, (fund_host,))
        add(name, website=url, vc=vc)
        n += 1
    return n


def fund_detail_pages(list_url, vc, fund_host, path_marker="/portfolio/"):
    """Listing of /portfolio/<slug> detail pages; each detail page has h1 + outbound site."""
    h = fetch(list_url)
    if not h:
        return 0
    p = scan(h)
    slugs = {}
    for idx, it in enumerate(p.items):
        if it["kind"] != "a":
            continue
        href = it.get("href") or ""
        if path_marker not in href:
            continue
        full = urllib.parse.urljoin(list_url, href)
        if host_of(full).removeprefix("www.") != fund_host.removeprefix("www."):
            continue
        slug = full.rstrip("/").split(path_marker)[-1]
        if not slug or slug in slugs:
            continue
        name = guess_name(p.items, idx, full, (fund_host,))
        if name_from_domain(full).lower().replace("/", "") in ("portfolio",):
            continue
        slugs[slug] = (full, name)
    n = 0
    for slug, (full, name) in slugs.items():
        # prefer the slug ("ninja-van" -> "Ninja Van") over a domain-derived
        # fallback, which would name every company after the fund's own site.
        slug_name = " ".join(w.capitalize() for w in slug.replace("-", " ").split())
        d = fetch(full)
        if not d:
            add(slug_name or name, vc=vc)
            continue
        dp = TextScanner(["h1", "h2", "a"])
        dp.feed(d)
        h1 = next((x["text"] for x in dp.hits if x["tag"] in ("h1", "h2")
                   and x["text"] and len(x["text"]) < 70), "")
        best = ""
        for x in dp.hits:
            if x["tag"] != "a":
                continue
            u = x["attrs"].get("href") or ""
            if is_company_url(u, (fund_host,)) and not best:
                best = u
        add(h1 or slug_name or name, website=best, vc=vc)
        n += 1
    return n


def fund_vertex_sea():
    """vertexventures.sg — portfolio section on the homepage."""
    return fund_grid("https://www.vertexventures.sg/", "Vertex Ventures SEA", "vertexventures.sg")


def fund_iterative():
    return fund_grid("https://www.iterative.vc/companies", "Iterative", "iterative.vc")


def fund_block71():
    return fund_grid("https://block71.co/startup/", "BLOCK71", "block71.co")


def fund_wavemaker():
    return fund_grid("https://www.wavemaker.com/portfolio", "Wavemaker Partners", "wavemaker.com")


def merge_webfetch_extras():
    if not os.path.exists(EXTRA_IN):
        return 0
    try:
        extra = json.load(open(EXTRA_IN, encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for e in extra:
        add(e.get("company_name"), website=e.get("website", ""),
            careers=e.get("career_page_url", ""), vc=e.get("vc_source", "unknown"))
        n += 1
    return n


FUNDS = [
    ("Antler", fund_antler),
    ("Entrepreneur First", fund_ef),
    ("Jungle Ventures", lambda: fund_grid("https://www.jungle.vc/portfolio", "Jungle Ventures", "jungle.vc")),
    ("January Capital", lambda: fund_grid("https://www.january.capital/portfolio", "January Capital", "january.capital")),
    ("Quest Ventures", lambda: fund_grid("https://www.questventures.com/businesses/portfolio/", "Quest Ventures", "questventures.com", anchor_filter="w-grid-item-anchor")),
    ("Wavemaker Partners", fund_wavemaker),
    ("Monk's Hill Ventures", lambda: fund_detail_pages("https://monkshill.com/portfolio", "Monk's Hill Ventures", "monkshill.com")),
    ("Golden Gate Ventures", lambda: fund_detail_pages("https://www.goldengate.vc/portfolio", "Golden Gate Ventures", "goldengate.vc")),
    ("Openspace Ventures", lambda: fund_detail_pages("https://www.openspacecapital.com/companies", "Openspace Ventures", "openspacecapital.com")),
    ("KK Fund", lambda: fund_detail_pages("https://kkfund.co/portfolio/", "KK Fund", "kkfund.co")),
    ("Forge Ventures", lambda: fund_detail_pages("https://www.forge.vc/portfolio/", "Forge Ventures", "forge.vc")),
    ("Vertex Ventures SEA", fund_vertex_sea),
    ("Iterative", fund_iterative),
    ("BLOCK71", fund_block71),
]


def load_existing():
    """Merge mode: never lose what a previous run already wrote."""
    if not os.path.exists(RAW_OUT):
        return
    try:
        for e in json.load(open(RAW_OUT, encoding="utf-8")):
            k = norm_key(e.get("company_name", ""), e.get("website", ""))
            if k:
                ENTRIES[k] = e
    except Exception:
        pass


def main():
    os.makedirs(CACHE, exist_ok=True)
    load_existing()
    only = os.environ.get("SGVC_ONLY")
    for name, fn in FUNDS:
        if only and only.lower() not in name.lower():
            continue
        try:
            n = fn()
            print(f"[{name}] +{n}", flush=True)
        except Exception as e:
            print(f"[{name}] ERR {type(e).__name__} {e}", flush=True)
        flush()
    n = merge_webfetch_extras()
    if n:
        print(f"[webfetch-extras] +{n}", flush=True)
    flush()
    with open(RAW_OUT, encoding="utf-8") as f:
        data = json.load(f)
    print(f"TOTAL {len(data)}; with website: {sum(1 for e in data if e['website'])}")


if __name__ == "__main__":
    main()
