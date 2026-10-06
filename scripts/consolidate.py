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

# Multi-part public suffixes where the registrable domain is the last THREE labels
# (e.g. foo.blogspot.co.uk -> blogspot.co.uk; acme.com.sg -> acme.com.sg). Without this,
# bare_domain() collapses every .com.sg / .co.uk site to the public suffix itself.
MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "net.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.au", "net.au", "org.au", "edu.au", "co.nz", "net.nz", "org.nz", "ac.nz",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "co.kr", "or.kr", "go.kr",
    "com.sg", "com.my", "co.id", "or.id", "co.th", "com.ph", "com.vn", "com.tw",
    "com.hk", "com.cn", "com.br", "com.mx", "com.ar", "com.co", "com.pe", "com.cl",
    "co.in", "org.in", "net.in", "com.tr", "com.pk", "com.bd",
    "co.za", "co.ke", "com.eg", "com.sa", "co.il",
}
# Hosts that host many unrelated employers' pages — a matching domain here is NOT evidence
# of same-company, so domain-based merge rails must skip them.
SHARED_HOSTS = {
    "linkedin.com", "linkedin.cn", "facebook.com", "twitter.com", "x.com",
    "github.com", "github.io", "gist.github.com", "gitlab.com", "bitbucket.org",
    "blogspot.com", "wordpress.com", "wp.com", "wixsite.com", "weebly.com",
    "myshopify.com", "shopify.com", "squarespace.com", "webflow.io", "notion.site",
    "carrd.co", "linktr.ee", "medium.com", "substack.com", "behance.net", "dribbble.com",
    "angel.co", "wellfound.com", "crunchbase.com", "glassdoor.com", "indeed.com",
    "youtube.com", "google.com", "googleusercontent.com", "t.co", "bit.ly",
}
SHARED_HOST_LABELS = {"blogspot", "wordpress", "github", "wixsite", "shopify",
                      "squarespace", "webflow", "notion", "medium", "substack",
                      "linktr", "tumblr", "typepad", "weebly", "godaddy"}

def _with_scheme(url):
    """urlparse needs a scheme to populate netloc; many career/website values are bare
    (e.g. 'alugha.com'). Prepend https:// when no scheme is present."""
    u = (url or "").strip()
    if u and "://" not in u and not u.startswith("//") and not u.lower().startswith("mailto:"):
        u = "https://" + u
    return u

def host(url):
    try:
        return (urlparse(_with_scheme(url)).netloc or "").lower().removeprefix("www.")
    except Exception:
        return ""

def registrable_domain(url):
    h = host(url)
    if not h:
        return ""
    parts = h.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return h

def bare_domain(url):
    return registrable_domain(url)

def is_shared_host(url):
    d = registrable_domain(url)
    if not d:
        return False
    if d in SHARED_HOSTS:
        return True
    return d.split(".")[0] in SHARED_HOST_LABELS

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
    """Scheme-agnostic, host-normalized (www stripped), path-only key. Drops the query
    so www. vs bare and trailing-slash variants of the same careers page collide."""
    p = urlparse(_with_scheme(url or ""))
    h = (p.netloc or "").lower().removeprefix("www.")
    path = (p.path or "").rstrip("/")
    return (h + path) if (h or path) else ""

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

# pass B: identical non-ATS careers URL (scheme/host normalized), merged across name
# aliases OR when the shared careers URL's registrable domain matches a member's website
# domain. Shared-host careers URLs (linkedin/facebook/blogspot/...) are excluded — a
# matching portal page is not evidence of same-company. The old startswith("http")
# guard is dropped so bare-scheme URLs like 'alugha.com' enter the group too.
_url_groups = defaultdict(list)
for _i, _c in enumerate(merged):
    _u = _c.get("career_page_url") or ""
    if _u and alias_ats_key(_c) is None and not is_shared_host(_u):
        _k = board_url_key(_u)
        if _k:
            _url_groups[_k].append(_i)
_alias_drop = set()
for _k, _idxs in _url_groups.items():
    if len(_idxs) < 2:
        continue
    _career_dom = registrable_domain(merged[_idxs[0]].get("career_page_url") or "")
    _knorms = [norm_name(merged[i]["company_name"]) for i in _idxs]
    _keep_i = min(_idxs, key=lambda i: (-_knorms.count(_knorms[_idxs.index(i)]),
                                        len(merged[i]["company_name"]), i))
    _kn = norm_name(merged[_keep_i]["company_name"])
    _grp = []
    for _i2, _n in zip(_idxs, _knorms):
        if _i2 == _keep_i:
            _grp.append(_i2)
            continue
        if name_aliases(_kn, _n):
            _grp.append(_i2)
            continue
        _wd = registrable_domain(merged[_i2].get("website") or "")
        if (_career_dom and _wd and _career_dom == _wd
                and not is_shared_host(merged[_i2].get("website") or "")):
            _grp.append(_i2)
    if len(_grp) < 2:
        continue
    _keep_i = _merge_alias_group(_grp)
    _alias_drop.update(i for i in _grp if i != _keep_i)
    _alias_stats["url_alias_merged"] += len(_grp) - 1
merged = [c for i, c in enumerate(merged) if i not in _alias_drop]

# --- Pass C: global canonical-name merge -------------------------------------
# Passes A/B only dedup within a shared board/URL. There is no global name-alias
# merge, so rows like "Asana" (greenhouse) + "Asana, Inc." (unknown), "Boomi, LP"
# (greenhouse) + "Boomi" (ashby), or "Agoda" + "AGODA COMPANY PTE. LTD." survive as
# separate rows -> duplicate job listings (jobs dedup key is (company, ats, job_id)).
# This pass merges same-company rows across spelling/abbreviation/short-form
# variants, using STRICT aliasing (legal suffixes only — NOT tld words like 'ai',
# which would wrongly merge "Clarity AI" with "Clarity") plus corroborating rails
# so distinct companies sharing a name and real numeric names ("Figure 1", "Sage
# 50") stay separate. Every merge is logged to data/dedup_merge_log.json.

ABBREV_WORDS = {
    "labs": "laboratories", "intl": "international", "sys": "systems",
    "grp": "group", "tech": "technologies", "svcs": "services",
    "mgmt": "management", "soln": "solutions", "hldgs": "holdings",
    "mfg": "manufacturing", "comm": "communications",
}
AUTO_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable",
            "personio", "workday", "bamboohr", "trinethire", "onlyfy", "keka",
            "pinpoint", "breezyhr", "teamtailor", "rippling", "recruitee",
            "attrax", "applytojob"}
PAGE_RANK = {"greenhouse": 0, "lever": 0, "ashby": 0, "workable": 0, "rippling": 0,
             "smartrecruiters": 1, "personio": 2, "workday": 2, "bamboohr": 2,
             "trinethire": 2, "onlyfy": 2, "keka": 2, "pinpoint": 2, "breezyhr": 2,
             "teamtailor": 2, "recruitee": 2, "attrax": 2, "applytojob": 2,
             "yc": 3, "custom": 4, "unknown": 5, "mailto": 5}
_C_SRC_PREC = {"verified": 3, "discovered": 2, "url": 1, "guess": 0}
_PASS_C_CAP = 256  # skip exhaustive pairwise rails inside canon groups larger than this

def _abbrev_norm(n):
    """Name normalized for same-company aliasing: parentheticals dropped, & -> and,
    ABBREV_WORDS expanded (labs -> laboratories, tech -> technologies), trailing LEGAL
    suffixes stripped, and a trailing DOTTED tld word stripped (domain-as-name: e.g.
    'Doutore.com' -> 'doutore', 'Ritual.co' -> 'ritual'). Non-dotted tld words
    ('Clarity AI', 'Specter One') and trailing digits are KEPT — stripping them would
    merge distinct companies whose names differ only by such a word/number."""
    s = re.sub(r"\s*\(.*?\)\s*", " ", (n or "").lower()).replace("&", "and")
    changed = True
    while changed:
        changed = False
        m = re.search(r"\.([a-z]{2,6})$", s)
        if m and m.group(1) in TLD_WORDS:
            s = s[:m.start()]; changed = True
    toks = re.findall(r"[a-z0-9]+", s)
    toks = [ABBREV_WORDS.get(t, t) for t in toks]
    changed = True
    while changed and toks:
        changed = False
        if toks[-1] in LEGAL_SUFFIXES and len("".join(toks[:-1])) >= 3:
            toks.pop(); changed = True
    return "".join(toks)

def _abbrev_alias(n1, n2):
    a, b = _abbrev_norm(n1), _abbrev_norm(n2)
    return bool(a) and a == b

def _trailing_digit(name):
    return bool(re.search(r"\s\d+$", (name or "").lower()))

def _canon_tokens(name):
    n = re.sub(r"\s*\(.*?\)\s*", " ", (name or "").lower()).replace("&", " and ")
    return re.findall(r"[a-z0-9]+", n)

def canon_key(name):
    """(base, digit_flag). base excludes a trailing numeric scraper suffix (so
    'Envato 2' -> ('envato', True), grouping separately from 'Envato' -> ('envato',
    False)); digit variants are reconciled by the digit rail, not by canon grouping.
    Trailing legal AND tld words are stripped (loose grouping); the merge decision
    itself uses strict_alias so the loose grouping never causes a wrong merge."""
    toks = _canon_tokens(name)
    digit = bool(toks and toks[-1].isdigit())
    core = toks[:-1] if digit else toks
    core = [ABBREV_WORDS.get(t, t) for t in core]
    changed = True
    while changed and core:
        changed = False
        if core[-1] in (LEGAL_SUFFIXES | TLD_WORDS) and len("".join(core[:-1])) >= 4:
            core.pop(); changed = True
    return ("".join(core), digit)

def _slug_norm(c):
    s = (c.get("board_token") or "").lower()
    if not s:
        u = _with_scheme(c.get("career_page_url") or "")
        m = re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", u)
        if m:
            s = m.group(1).lower()
        else:
            h = host(c.get("career_page_url") or "")
            if h:
                s = h.split(".")[0]
    return re.sub(r"[^a-z0-9]", "", s or "")

def _auto(c):
    return c["ats_type"] in AUTO_ATS and bool(c.get("board_token"))

def _shell(c):
    return not (c.get("website") or "").strip() and c["ats_type"] not in AUTO_ATS

def _dom(c):
    u = c.get("website") or ""
    return registrable_domain(u) if (u and not is_shared_host(u)) else ""

# union-find over current merged positions
_N = len(merged)
_uf = list(range(_N))
def _find(a):
    while _uf[a] != a:
        _uf[a] = _uf[_uf[a]]; a = _uf[a]
    return a
def _union(a, b):
    ra, rb = _find(a), _find(b)
    if ra != rb:
        _uf[ra] = rb; return True
    return False

_edge_reason = {}  # frozenset({i,j}) -> reason, for component labeling
def _edge(i, j, reason):
    if _union(i, j):
        _edge_reason[frozenset((i, j))] = reason

# group by canon key
_cgroups = defaultdict(list)
for _i, _c in enumerate(merged):
    _ck = canon_key(_c["company_name"])
    if _ck[0]:
        _cgroups[_ck].append(_i)

# rail A: within a canon group
for _ck, _idxs in _cgroups.items():
    if len(_idxs) < 2:
        continue
    if len(_idxs) <= _PASS_C_CAP:
        _pairs = ((a, b) for ai, a in enumerate(_idxs) for b in _idxs[ai+1:])
    else:
        # large canon group: skip pairwise rails (too expensive; rare). Same-company
        # variants in such a group are caught by the digit rail / pass A-B instead.
        _pairs = ()
    for _a, _b in _pairs:
        ca, cb = merged[_a], merged[_b]
        sa, sb = _auto(ca), _auto(cb)
        da, db = _dom(ca), _dom(cb)
        _domcon = bool(da and db and da != db)
        if _domcon:
            continue
        if sa and sb:
            # rail A2 (board2): both enumerated, abbrev-alias or equal slug
            if (_abbrev_alias(ca["company_name"], cb["company_name"])
                    or _slug_norm(ca) == _slug_norm(cb)):
                _edge(_a, _b, "board2")
            continue
        # at least one not enumerated: merge on abbreviation/short-form alias equality.
        # (No canon-equality shell collapse — that merged distinct companies whose names
        # differ by a tld word or digit, e.g. Figure 1 vs Figure 53, Specter-AI vs
        # Specter One. _abbrev_alias keeps those separate while still merging
        # Doutore LLC + Doutore.com, Silicon Labs + Silicon Laboratories.)
        if _abbrev_alias(ca["company_name"], cb["company_name"]):
            _edge(_a, _b, "alias")

# rail B1 (same-website-domain) is intentionally NOT used: a shared registrable domain
# is strong evidence in principle, but in this dataset many rows carry a `website` that
# points to a platform/catalog page (docker.com, ycombinator.com, fresha.com, a jobs
# portal) rather than the company's own domain, so union-by-domain merges unrelated
# employers. Every strict_alias pair already lands in the same canon group (legal-suffix
# stripping is a subset of canon stripping), so rail A1 subsumes the safe same-company
# cases. Rebrands that differ by a tld-word suffix (BILL vs Bill.com) and regional
# subsidiaries with a qualifier word (Thales DIS, Coinbase Singapore) are deliberately
# left separate rather than risk prefix-based false merges (Oscar vs Oscar Yankee).

# indices by canon base (digit=False) for the digit rail; count automatable per base
_base_groups = defaultdict(list)
_base_auto = defaultdict(list)
for _i, _c in enumerate(merged):
    _ck = canon_key(_c["company_name"])
    if _ck[0] and not _ck[1]:
        _base_groups[_ck[0]].append(_i)
        if _auto(_c):
            _base_auto[_ck[0]].append(_i)

# rail B4: a trailing-digit variant reconciles with its base canon group. Two cases:
#  (a) base has NO enumerated row — the digit row is the real board, base rows are
#      name-only shells (Envato 2 + Envato(custom); Gravity Payments 1 + Gravity
#      Payments(custom)). Slug must corroborate: slug == base+digits.
#  (b) base HAS an enumerated row — both are boards of (presumably) the same company.
#      Only merge on a SINGLE-digit suffix (1-9 = board-suffix pattern like 'netradyne'
#      vs 'netradyne-1') where the two boards' slugs differ by exactly that digit.
#      Multi-digit names (Studio 397, Alchemy 43, Hawkeye 360, Sage 50, Newton 21) are
#      treated as real brand names and left separate — slug==base+digits is not enough
#      there, since 'studio397' vs the base 'Studio' slug 'studio555' don't tie anyway.
for _i, _c in enumerate(merged):
    _ck = canon_key(_c["company_name"])
    if not _ck[0] or not _ck[1]:
        continue
    _base = _ck[0]
    _toks = _canon_tokens(_c["company_name"])
    _dstr = _toks[-1] if _toks and _toks[-1].isdigit() else ""
    _si = _slug_norm(_c)
    _cand = _base_groups.get(_base, [])
    if not _cand or not _dstr:
        continue
    _autos = _base_auto.get(_base, [])
    if _autos:
        # case (b): both enumerated — single-digit slug tie with a base board slug
        if len(_dstr) == 1 and _auto(_c):
            for _j in _autos:
                if _si == _slug_norm(merged[_j]) + _dstr:
                    _edge(_i, _j, "digit"); break
        continue
    # case (a): digit row is the sole enumerated board; base is shells/custom
    if _auto(_c) and _si and _si == _base + _dstr:
        _edge(_i, _cand[0], "digit")
        continue
    _di = _dom(_c)
    if _di:
        for _j in _cand:
            if _dom(merged[_j]) == _di:
                _edge(_i, _j, "digit"); break

# build components
_comps = defaultdict(list)
for _i in range(_N):
    _comps[_find(_i)].append(_i)
_comps = [v for v in _comps.values() if len(v) > 1]

_REASON_PRIORITY = ["board2", "domain", "digit", "alias", "shell-prefix", "shell-collapse"]
def _comp_reason(idxs):
    seen = {_edge_reason.get(frozenset((a, b))) for a in idxs for b in idxs if a != b}
    for r in _REASON_PRIORITY:
        if r in seen:
            return r
    return "merge"

_merge_log = []
_pass_c_stats = Counter()
_pass_c_drop = set()

def _merge_pass_c(idxs):
    counts = Counter(merged[i]["company_name"] for i in idxs)
    keep_i = max(idxs, key=lambda i: (_C_SRC_PREC.get(merged[i].get("ats_source", "guess"), 0),
                                      -PAGE_RANK.get(merged[i].get("ats_type", "unknown"), 9),
                                      1 if not _trailing_digit(merged[i]["company_name"]) else 0,
                                      -len(merged[i]["company_name"]), -i))
    keep = merged[keep_i]
    name = sorted(counts.items(),
                  key=lambda kv: (-kv[1], 0 if not _trailing_digit(kv[0]) else 1,
                                  len(kv[0]), kv[0]))[0][0]
    keep["company_name"] = name
    all_urls = []
    for i in idxs:
        for u in [merged[i].get("career_page_url", "")] + merged[i].get("alternate_career_urls", []):
            if u and u not in all_urls:
                all_urls.append(u)
    primary = keep.get("career_page_url", "")
    seen = {board_url_key(primary)}
    alts, demoted = [], []
    for u in all_urls:
        ku = board_url_key(u)
        if not ku or ku in seen:
            continue
        seen.add(ku)
        if u == primary:
            continue
        alts.append(u)
        a = infer_ats_from_url(u)
        if a in AUTO_ATS:
            demoted.append({"ats": a, "url": u})
    keep["alternate_career_urls"] = alts
    webs = [merged[i].get("website", "").strip() for i in idxs if merged[i].get("website", "").strip()]
    if webs:
        wc = Counter(webs)
        keep["website"] = sorted(wc.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
    keep["agent_ats_labels"] = sorted({l for i in idxs for l in merged[i].get("agent_ats_labels", [])})
    keep["source_platforms"] = sorted({s for i in idxs for s in merged[i].get("source_platforms", [])})
    for i in idxs:
        if merged[i].get("domain_hint") and not keep.get("domain_hint"):
            keep["domain_hint"] = merged[i]["domain_hint"]; break
    keep["ats_conflict"] = any(merged[i].get("ats_conflict") for i in idxs)
    keep["is_mnc_flagged"] = norm_name(name) in _mnc_norms
    reason = _comp_reason(idxs)
    _pass_c_stats[reason] += 1
    removed = [{"name": merged[i]["company_name"],
                "ats": merged[i].get("ats_type", ""),
                "url": merged[i].get("career_page_url", "")}
               for i in idxs if i != keep_i]
    _merge_log.append({
        "kept": name,
        "kept_board": {"ats": keep.get("ats_type", ""), "source": keep.get("ats_source", ""),
                       "url": primary},
        "removed": removed,
        "demoted_boards": demoted,
        "reason": reason,
    })
    return keep_i

_keep_idx = set()
for _idxs in _comps:
    _keep_idx.add(_merge_pass_c(_idxs))
_keep_roots = {_find(k) for k in _keep_idx}
for _i in range(_N):
    if _find(_i) in _keep_roots and _i not in _keep_idx:
        _pass_c_drop.add(_i)
merged = [c for i, c in enumerate(merged) if i not in _pass_c_drop]

with open(os.path.join(OUT_DIR, "dedup_merge_log.json"), "w") as _f:
    json.dump(_merge_log, _f, indent=2, ensure_ascii=False)

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
print(f"Pass C canonical-name dedup: removed {len(_pass_c_drop)} row(s) across "
      f"{sum(_pass_c_stats.values())} merge group(s) "
      f"({dict(_pass_c_stats)}); log -> data/dedup_merge_log.json")
print(f"ATS conflicts     : {len(conflicts)} -> {conflicts}")
print("By ATS:")
for ats, n in sorted(summary.items(), key=lambda kv: -kv[1]):
    print(f"  {ats:<16} {n}")