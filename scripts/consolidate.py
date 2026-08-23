#!/usr/bin/env python3
import json, csv, os, re
from collections import defaultdict, Counter
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
OUT_DIR = os.path.join(ROOT, "data")
BY_ATS_DIR = os.path.join(OUT_DIR, "by_ats")

ATS_HOST_RULES = [
    ("greenhouse", ["boards.greenhouse.io", "job-boards.greenhouse.io"]),
    ("lever",      ["jobs.lever.co"]),
    ("ashby",      ["jobs.ashbyhq.com", "app.ashbyhq.com"]),
    ("smartrecruiters", ["jobs.smartrecruiters.com", "careers.smartrecruiters.com"]),
    ("workable",   ["apply.workable.com"]),
    ("personio",   ["jobs.personio.com", ".jobs.personio.com"]),
    ("bamboohr",   [".bamboohr.com", "bamboohr.com/careers"]),
    ("trinethire", ["app.trinethire.com"]),
    ("onlyfy",     [".onlyfy.jobs", "onlyfy.jobs"]),
    ("keka",       [".keka.com"]),
    ("pinpoint",   ["pinpointhq.com"]),
    ("recruitee",  [".recruitee.com"]),
    ("breezyhr",   [".breezy.hr", "breezy.hr"]),
    ("teamtailor", ["careers.teamtailor.com", ".teamtailor.com"]),
    ("rippling",   ["ats.rippling.com"]),
    ("workday",    [".myworkdayjobs.com", ".wd5.myworkdayjobs.com", "myworkdayjobs.com"]),
    ("yc",         ["ycombinator.com/companies/"]),
    ("applytojob", ["applytojob.com"]),
    ("attrax",     ["wise.jobs"]),
]

# Subdomain-token ATS use wildcard DNS — non-tenant subdomains still resolve and
# look live; they must never become board tokens.
RESERVED_SUBDOMAINS = {
    "www", "www2", "api", "app", "apps", "admin", "login", "auth", "sso",
    "help", "support", "docs", "documentation", "resources", "developer", "developers",
    "assets", "static", "cdn", "img", "images", "media", "files", "download", "downloads",
    "blog", "news", "status", "mail", "email", "smtp", "ftp", "ns1", "ns2",
    "test", "testing", "staging", "stage", "dev", "demo", "sandbox", "preview",
    "jobs", "job", "careers", "career", "apply", "recruiting", "hire", "hiring",
    "my", "portal", "account", "accounts", "secure", "shop", "store", "info",
}

MNC_FLAG = {
    "stripe", "cloudflare", "figma", "mongodb", "elastic", "gitlab", "lyft",
    "doordash", "epic games", "opentable", "zillow", "poshmark", "udemy",
    "taboola", "adyen", "toast", "lyft", "canonical", "fastly", "airtable",
    "rubrik", "nasuni", "logicmonitor", "fourkites", "wikimedia foundation",
    "duolingo", "ramp", "rippling", "anduril industries", "scale ai",
    "anthropic", "openai", "hugging face", "notion", "vercel", "replit",
    "ret tool", "retool", "cohere", "coreweave", "nebius", "rippling",
    "grafana labs", "kraken", "ripple", "phantom", "brex", "mercury",
    "posthog", "linear", "coder", "supabase", "perplexity", "mistr al ai",
    "elevenlabs", "zapier", "duckduckgo", "buffer", "close",
}

VERIFIED = {
    "stripe":       ("greenhouse", "https://boards.greenhouse.io/stripe"),
    "ramp":         ("ashby",      "https://jobs.ashbyhq.com/ramp"),
    "notion":       ("ashby",      "https://jobs.ashbyhq.com/notion"),
    "replit":       ("ashby",      "https://jobs.ashbyhq.com/replit"),
    "cursor": ("ashby",   "https://jobs.ashbyhq.com/cursor"),
    "huggingface":  ("workable",   "https://apply.workable.com/huggingface/"),
}

def host(url):
    try:
        return (urlparse(url).netloc or "").lower().lstrip("www.")
    except Exception:
        return ""

def bare_domain(url):
    h = host(url)
    parts = h.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return h

def infer_ats_from_url(url):
    u = (url or "").lower()
    for ats_id, subs in ATS_HOST_RULES:
        for s in subs:
            if s in u:
                return ats_id
    return None

def norm_name(name):
    n = name.lower()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = n.replace("(formerly rstudio)", " ")
    n = re.sub(r"[^a-z0-9]", "", n)
    return n

def domain_key(entry):
    for url in (entry.get("website"), entry.get("career_page_url")):
        if url:
            d = bare_domain(url)
            if d:
                return d
    return norm_name(entry.get("company_name", ""))

raw = []
for fn in sorted(os.listdir(RAW_DIR)):
    if fn.endswith(".json"):
        with open(os.path.join(RAW_DIR, fn)) as f:
            raw.extend(json.load(f))

DISCOVERED = {}
_ds_path = os.path.join(OUT_DIR, "discovered_slugs.json")
if os.path.exists(_ds_path):
    with open(_ds_path) as _f:
        for _r in json.load(_f):
            DISCOVERED[norm_name(_r["company_name"])] = (_r["ats"], _r["career_page_url"], _r["slug"])

groups = defaultdict(list)
for e in raw:
    key = norm_name(e["company_name"]) or domain_key(e)
    groups[key].append(e)

def primary_url_sort_key(url):
    ats = infer_ats_from_url(url)
    if ats in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable",
               "personio", "bamboohr", "trinethire", "workday", "onlyfy", "keka",
               "pinpoint", "breezyhr", "teamtailor", "rippling", "applytojob", "attrax"):
        return (0, url)
    if ats == "yc":
        return (1, url)
    path = urlparse(url).path.lower()
    if any(seg in path for seg in ["career", "jobs", "join", "hiring", "vacanc"]):
        return (2, url)
    if "wellfound.com" in url or "startup.jobs" in url or "rubyonremote" in url:
        return (3, url)
    return (4, url)

merged = []
for key, entries in groups.items():
    name_counts = Counter(e["company_name"] for e in entries)
    name = sorted(name_counts.items(), key=lambda kv: (-kv[1], len(kv[0])))[0][0]

    urls = []
    for e in entries:
        u = e.get("career_page_url", "").strip()
        if u and u not in urls:
            urls.append(u)
    websites = [e.get("website", "").strip() for e in entries if e.get("website")]
    website = websites[0] if websites else ""

    urls.sort(key=primary_url_sort_key)
    if urls:
        primary_url = urls[0]
    else:
        primary_url = website

    domains = [e.get("domain_hint", "").strip() for e in entries if e.get("domain_hint")]
    domain_hint = domains[0] if domains else ""

    sources = sorted({e.get("source_platform", "") for e in entries if e.get("source_platform")})

    auth_ats = infer_ats_from_url(primary_url)
    agent_labels = sorted({(e.get("ats_type") or "unknown").lower() for e in entries})
    if auth_ats:
        ats_type = auth_ats
        ats_source = "url"
    else:
        non_unknown = [a for a in agent_labels if a not in ("unknown", "custom")]
        if non_unknown:
            ats_type = Counter(non_unknown).most_common(1)[0][0]
        elif "custom" in agent_labels:
            ats_type = "custom"
        else:
            ats_type = "unknown"
        ats_source = "guess"

    all_ats_signals = {a for a in agent_labels if a not in ("unknown",)} | ({auth_ats} if auth_ats else set())
    standard = {a for a in all_ats_signals if a not in ("custom", "yc", "unknown")}
    conflict = len(standard) > 1

    SUBDOMAIN_TOKEN_ATS = {"teamtailor", "personio", "breezyhr", "onlyfy",
                           "bamboohr", "pinpoint", "recruitee"}
    PATH_TOKEN_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "rippling"}
    board_token = None
    if ats_source in ("url", "verified") and ats_type in (SUBDOMAIN_TOKEN_ATS | PATH_TOKEN_ATS):
        if ats_type in SUBDOMAIN_TOKEN_ATS:
            hostname = (urlparse(primary_url).hostname or "").lower()
            parts = hostname.split(".")
            if len(parts) >= 3:
                sub = parts[0]
                # 'images7' -> 'images': numbered variants are still reserved
                if re.sub(r"\d+$", "", sub) not in RESERVED_SUBDOMAINS:
                    board_token = sub
        else:
            m = re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", primary_url)
            if m:
                board_token = m.group(1)
    elif ats_type == "mailto":
        board_token = primary_url
    elif ats_type == "workday" and ats_source in ("url", "verified"):
        board_token = primary_url

    is_mnc = norm_name(name) in {norm_name(x) for x in MNC_FLAG}

    vkey = norm_name(name)
    if vkey in VERIFIED:
        v_ats, v_url = VERIFIED[vkey]
        ats_type = v_ats
        ats_source = "verified"
        if v_url not in urls:
            urls.insert(0, v_url)
        primary_url = v_url
        conflict = False
        m = re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", v_url)
        board_token = m.group(1) if m else None
    elif vkey in DISCOVERED:
        v_ats, v_url, v_slug = DISCOVERED[vkey]
        ats_type = v_ats
        ats_source = "discovered"
        if v_url not in urls:
            urls.insert(0, v_url)
        primary_url = v_url
        conflict = False
        board_token = v_slug

    merged.append({
        "company_name": name,
        "website": website,
        "career_page_url": primary_url,
        "alternate_career_urls": urls[1:] if len(urls) > 1 else [],
        "ats_type": ats_type,
        "ats_source": ats_source,
        "ats_conflict": conflict,
        "agent_ats_labels": agent_labels,
        "board_token": board_token,
        "domain_hint": domain_hint,
        "source_platforms": sources,
        "is_mnc_flagged": is_mnc,
    })

SLUG_ATS = (SUBDOMAIN_TOKEN_ATS | PATH_TOKEN_ATS)

def board_url_key(url):
    return (url or "").lower().replace("https://", "").replace("http://", "").rstrip("/")

def board_slug(url, ats_type):
    if ats_type in SUBDOMAIN_TOKEN_ATS:
        parts = (urlparse(url).hostname or "").lower().split(".")
        if len(parts) < 3:
            return ""
        sub = parts[0]
        # keep in step with the token derivation above: reserved subdomains aren't boards
        return "" if re.sub(r"\d+$", "", sub) in RESERVED_SUBDOMAINS else sub
    m = re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", url or "")
    return m.group(1) if m else ""

def owns_board(c, slug):
    t = norm_name(slug)
    if not t:
        return False
    if norm_name(c.get("company_name", "")) == t:
        return True
    bd = c.get("website") and bare_domain(c["website"])
    if bd:
        first = norm_name(bd.split(".")[0])
        if t == first or t in bd or (len(first) >= 4 and t.startswith(first)):
            return True
    return False

_board_groups = defaultdict(list)
for _i, _c in enumerate(merged):
    if (_c.get("ats_type") in SLUG_ATS and _c.get("career_page_url")
            and _c.get("ats_source") in ("url", "verified", "discovered")):
        _k = board_url_key(_c["career_page_url"])
        if _k:
            _board_groups[_k].append(_i)

_dedup_drop = set()
_dedup_stripped = 0

def _strip_ats(idx):
    global _dedup_stripped
    c = merged[idx]
    c["career_page_url"] = c.get("website") or ""
    c["alternate_career_urls"] = []
    c["ats_type"] = "unknown"
    c["ats_source"] = "guess"
    c["ats_conflict"] = False
    c["board_token"] = None
    _dedup_stripped += 1

for _k, _idxs in _board_groups.items():
    if len(_idxs) < 2:
        continue
    _slug = board_slug(merged[_idxs[0]]["career_page_url"], merged[_idxs[0]]["ats_type"])
    _owners = [_i for _i in _idxs if owns_board(merged[_i], _slug)]
    if not _owners:
        for _i in _idxs:
            _strip_ats(_i)
        continue
    _keep = min(_owners, key=lambda i: (0 if merged[i].get("website") else 1,
                                        len(merged[i]["company_name"]), i))
    for _i in _idxs:
        if _i not in _owners:
            _strip_ats(_i)
    _doms = {bare_domain(merged[_i].get("website") or "") for _i in _owners}
    _doms.discard("")
    if len(_doms) <= 1:
        for _i in _owners:
            if _i != _keep:
                _dedup_drop.add(_i)
    else:
        for _i in _owners:
            if _i != _keep:
                _strip_ats(_i)

if _dedup_drop:
    merged = [c for i, c in enumerate(merged) if i not in _dedup_drop]

# --- Alias merge ------------------------------------------------------------
# One board = one employer = one row: name variants ("Aiven"/"Aiven.io") and host
# variants (boards. vs job-boards.greenhouse.io) merge. Plain careers URLs merge
# only on mutual name aliases, so portals shared by distinct subsidiaries stay separate.

LEGAL_SUFFIXES = {"inc", "llc", "ltd", "limited", "gmbh", "ag", "bv", "nv", "plc",
                  "sa", "srl", "spa", "oy", "ab", "as", "aps", "kk", "pte",
                  "sdnbhd", "corp", "corporation", "company", "co", "pvt",
                  "pvtltd", "private", "llp", "lp", "holdings"}
TLD_WORDS = {"com", "io", "net", "org", "co", "ai", "app", "dev", "xyz", "info",
             "tech", "so", "one"}
HOST_KEY_ATS = {"workday", "applytojob", "trinethire", "keka", "attrax"}

def _strip_words(n, words):
    for w in words:
        if n.endswith(w) and len(n) - len(w) >= 4:
            return n[: -len(w)]
    return n

def name_aliases(n1, n2):
    if not n1 or not n2 or n1 == n2:
        return n1 == n2 and bool(n1)
    a = _strip_words(_strip_words(n1, TLD_WORDS), LEGAL_SUFFIXES)
    b = _strip_words(_strip_words(n2, TLD_WORDS), LEGAL_SUFFIXES)
    if a == b:
        return True
    short, long_ = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
    return len(short) >= 5 and long_.startswith(short)

def alias_ats_key(c):
    u = c.get("career_page_url") or ""
    if not u:
        return None
    a = infer_ats_from_url(u)
    if a in SLUG_ATS:
        s = board_slug(u, a)
        return (a, s.lower()) if s else None
    if a in HOST_KEY_ATS:
        h = (urlparse(u).hostname or "").lower()
        return (a, h) if h else None
    return None

_alias_stats = Counter()

def _merge_alias_group(idxs):
    """Merge merged[idxs] into one row; returns the kept index."""
    counts = Counter(merged[i]["company_name"] for i in idxs)
    keeper = min(idxs, key=lambda i: (-counts[merged[i]["company_name"]],
                                      len(merged[i]["company_name"]), i))
    keep = merged[keeper]
    urls = []
    for i in idxs:
        for u in [merged[i].get("career_page_url", "")] + merged[i].get("alternate_career_urls", []):
            if u and u not in urls:
                urls.append(u)
    seen = {board_url_key(keep.get("career_page_url"))}
    alts = []
    for u in urls:
        ku = board_url_key(u)
        if ku and ku not in seen:
            seen.add(ku)
            alts.append(u)
    keep["alternate_career_urls"] = alts
    websites = [merged[i].get("website", "").strip() for i in sorted(idxs)
                if merged[i].get("website", "").strip()]
    if websites:
        wc = Counter(websites)
        keep["website"] = sorted(wc.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
    keep["agent_ats_labels"] = sorted({l for i in idxs for l in merged[i].get("agent_ats_labels", [])})
    keep["source_platforms"] = sorted({s for i in idxs for s in merged[i].get("source_platforms", [])})
    if not keep.get("domain_hint"):
        for i in idxs:
            if merged[i].get("domain_hint"):
                keep["domain_hint"] = merged[i]["domain_hint"]
                break
    _prec = {"verified": 3, "discovered": 2, "url": 1, "guess": 0}
    for i in idxs:
        if _prec.get(merged[i].get("ats_source"), 0) > _prec.get(keep.get("ats_source"), 0):
            keep["ats_type"], keep["ats_source"] = merged[i]["ats_type"], merged[i]["ats_source"]
    keep["ats_conflict"] = any(merged[i].get("ats_conflict") for i in idxs)
    keep["is_mnc_flagged"] = norm_name(keep["company_name"]) in _mnc_norms
    return keeper

_mnc_norms = {norm_name(x) for x in MNC_FLAG}

# pass A: same ATS board (slug or tenant host) under different names
_ats_groups = defaultdict(list)
for _i, _c in enumerate(merged):
    _k = alias_ats_key(_c)
    if _k:
        _ats_groups[_k].append(_i)
_alias_drop = set()
for _k, _idxs in _ats_groups.items():
    if len(_idxs) < 2:
        continue
    _keep_i = _merge_alias_group(_idxs)
    _alias_drop.update(i for i in _idxs if i != _keep_i)
    _alias_stats["ats_board_merged"] += len(_idxs) - 1
merged = [c for i, c in enumerate(merged) if i not in _alias_drop]

# pass B: identical non-ATS careers URL, but only across name aliases
_url_groups = defaultdict(list)
for _i, _c in enumerate(merged):
    _u = _c.get("career_page_url") or ""
    if _u and alias_ats_key(_c) is None and _u.lower().startswith(("http://", "https://")):
        _k = board_url_key(_u)
        if _k:
            _url_groups[_k].append(_i)
_alias_drop = set()
for _k, _idxs in _url_groups.items():
    if len(_idxs) < 2:
        continue
    _knorms = [norm_name(merged[i]["company_name"]) for i in _idxs]
    _keep_i = min(_idxs, key=lambda i: (-_knorms.count(_knorms[_idxs.index(i)]),
                                        len(merged[i]["company_name"]), i))
    _kn = norm_name(merged[_keep_i]["company_name"])
    _grp = [i for i, n in zip(_idxs, _knorms) if i == _keep_i or name_aliases(_kn, n)]
    if len(_grp) < 2:
        continue
    _keep_i = _merge_alias_group(_grp)
    _alias_drop.update(i for i in _grp if i != _keep_i)
    _alias_stats["url_alias_merged"] += len(_grp) - 1
merged = [c for i, c in enumerate(merged) if i not in _alias_drop]

# alternate-careers hygiene: drop alternates duplicating the primary or each other
_alt_dupes = 0
for _c in merged:
    _pk = board_url_key(_c.get("career_page_url"))
    _seen = {_pk} if _pk else set()
    _alts = []
    for _u in _c.get("alternate_career_urls", []):
        _ku = board_url_key(_u)
        if _ku and _ku not in _seen:
            _seen.add(_ku)
            _alts.append(_u)
        else:
            _alt_dupes += 1
    _c["alternate_career_urls"] = _alts

ATS_ORDER = {"greenhouse":0, "lever":1, "ashby":2, "smartrecruiters":3, "workable":4,
             "personio":5, "workday":6, "bamboohr":7, "trinethire":8, "onlyfy":9,
             "keka":10, "pinpoint":11, "breezyhr":12, "teamtailor":13, "rippling":14,
             "recruitee":15, "attrax":16, "applytojob":17,
             "custom":18, "yc":19, "unknown":20}
merged.sort(key=lambda c: (ATS_ORDER.get(c["ats_type"], 99), c["company_name"].lower()))

with open(os.path.join(OUT_DIR, "companies.json"), "w") as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)

with open(os.path.join(OUT_DIR, "companies.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["company_name","website","career_page_url","ats_type","ats_source",
                "ats_conflict","board_token","domain_hint","source_platforms","is_mnc_flagged"])
    for c in merged:
        w.writerow([c["company_name"], c["website"], c["career_page_url"], c["ats_type"],
                    c["ats_source"], c["ats_conflict"], c["board_token"] or "",
                    c["domain_hint"], "|".join(c["source_platforms"]), c["is_mnc_flagged"]])

summary = Counter(c["ats_type"] for c in merged)
conflicts = [c["company_name"] for c in merged if c["ats_conflict"]]
with open(os.path.join(OUT_DIR, "ats_summary.json"), "w") as f:
    json.dump({
        "total_companies": len(merged),
        "by_ats": dict(sorted(summary.items(), key=lambda kv: -kv[1])),
        "ats_conflicts": conflicts,
        "automatable_count": sum(1 for c in merged if c["ats_type"] in
                                 ("greenhouse","lever","ashby","smartrecruiters","workable",
                                  "personio","workday","bamboohr","trinethire","onlyfy",
                                  "keka","pinpoint","breezyhr","teamtailor","rippling",
                                  "attrax","applytojob")),
    }, f, indent=2)

os.makedirs(BY_ATS_DIR, exist_ok=True)
by_ats = defaultdict(list)
for c in merged:
    by_ats[c["ats_type"]].append({k: c[k] for k in
        ("company_name","website","career_page_url","board_token","domain_hint","source_platforms")})
for ats, rows in by_ats.items():
    with open(os.path.join(BY_ATS_DIR, f"{ats}.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

print(f"Total raw entries : {len(raw)}")
print(f"Unique companies  : {len(merged)}")
print(f"Board-collision dedup: dropped {len(_dedup_drop)} alias-dup entr(ies), "
      f"reverted {_dedup_stripped} false-positive/alias entr(ies) to unknown")
print(f"Alias merge: merged {dict(_alias_stats)} duplicate endpoint row(s), "
      f"dropped {_alt_dupes} duplicate alternate URL(s)")
print(f"ATS conflicts     : {len(conflicts)} -> {conflicts}")
print("By ATS:")
for ats, n in sorted(summary.items(), key=lambda kv: -kv[1]):
    print(f"  {ats:<16} {n}")