#!/usr/bin/env python3
"""Consolidate raw per-agent company JSON into a deduplicated dataset grouped by ATS.

Strategy:
- Read all data/raw/agent*.json
- Normalize company name + website domain as the dedup key
- For each company, merge all career_page_urls and ats labels seen across agents
- Determine an AUTHORITATIVE ats_type by inspecting the career_page_url domain
  (an ATS-hosted URL beats an agent's guess for a company-domain /careers page)
- Pick a primary career_page_url: prefer an ATS-hosted board URL (directly automatable),
  else the company-domain careers page
- Flag ATS conflicts (multiple distinct non-unknown ats labels)
- Emit: data/companies.json, data/companies.csv, data/ats_summary.json, data/by_ats/*.json
"""
import json, csv, os, re
from collections import defaultdict, Counter
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
OUT_DIR = os.path.join(ROOT, "data")
BY_ATS_DIR = os.path.join(OUT_DIR, "by_ats")

# Map URL host substrings -> canonical ATS id. Order matters (first match wins).
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
    ("breezyhr",   [".breezy.hr", "breezy.hr"]),
    ("teamtailor", ["careers.teamtailor.com", ".teamtailor.com"]),
    ("rippling",   ["ats.rippling.com"]),
    ("workday",    [".myworkdayjobs.com", ".wd5.myworkdayjobs.com", "myworkdayjobs.com"]),
    ("yc",         ["ycombinator.com/companies/"]),
    ("applytojob", ["applytojob.com"]),
    ("attrax",     ["wise.jobs"]),
]

# Companies that are clearly large MNCs / not startups -> flag (kept, but tagged)
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

# Ground-truth ATS verified by probing each vendor's board API (2026-07).
# Maps norm_name -> (ats_type, authoritative ATS-hosted career_page_url).
VERIFIED = {
    "stripe":       ("greenhouse", "https://boards.greenhouse.io/stripe"),
    "ramp":         ("ashby",      "https://jobs.ashbyhq.com/ramp"),
    "notion":       ("ashby",      "https://jobs.ashbyhq.com/notion"),
    "replit":       ("ashby",      "https://jobs.ashbyhq.com/replit"),
    "cursor": ("ashby",   "https://jobs.ashbyhq.com/cursor"),  # Cursor (Anysphere)
    "huggingface":  ("workable",   "https://apply.workable.com/huggingface/"),
}

def host(url):
    try:
        return (urlparse(url).netloc or "").lower().lstrip("www.")
    except Exception:
        return ""

def bare_domain(url):
    h = host(url)
    # strip subdomains: keep last two labels
    parts = h.split(".")
    if len(parts) >= 2:
        # handle co.uk style minimally
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
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)      # drop parentheticals like (Anysphere)
    n = n.replace("(formerly rstudio)", " ")
    n = re.sub(r"[^a-z0-9]", "", n)           # alphanumeric only
    return n

def domain_key(entry):
    """Best-effort stable key: bare domain of website, else of career url."""
    for url in (entry.get("website"), entry.get("career_page_url")):
        if url:
            d = bare_domain(url)
            if d:
                return d
    return norm_name(entry.get("company_name", ""))

# ---- load ----
raw = []
for fn in sorted(os.listdir(RAW_DIR)):
    if fn.endswith(".json"):
        with open(os.path.join(RAW_DIR, fn)) as f:
            raw.extend(json.load(f))

# Load slug-discovery results (written by scripts/discover_slugs.py) into a
# norm_name -> (ats, board_url, slug) map. Confirmed by live board-API probes.
DISCOVERED = {}
_ds_path = os.path.join(OUT_DIR, "discovered_slugs.json")
if os.path.exists(_ds_path):
    with open(_ds_path) as _f:
        for _r in json.load(_f):
            DISCOVERED[norm_name(_r["company_name"])] = (_r["ats"], _r["career_page_url"], _r["slug"])

# ---- group ----
groups = defaultdict(list)
for e in raw:
    key = norm_name(e["company_name"]) or domain_key(e)
    groups[key].append(e)

def primary_url_sort_key(url):
    """Lower is better. ATS-hosted board URLs rank first."""
    ats = infer_ats_from_url(url)
    # rank: 0 = standard automatable ATS, 1 = yc, 2 = company-domain careers, 3 = board profile, 4 = homepage
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
    # canonical name: shortest spelling among the most frequent
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
        # no career_page_url known for this company; fall back to website/homepage
        primary_url = website

    domains = [e.get("domain_hint", "").strip() for e in entries if e.get("domain_hint")]
    domain_hint = domains[0] if domains else ""

    sources = sorted({e.get("source_platform", "") for e in entries if e.get("source_platform")})

    # ATS labels: authoritative from primary URL, plus all agent guesses
    auth_ats = infer_ats_from_url(primary_url)
    agent_labels = sorted({(e.get("ats_type") or "unknown").lower() for e in entries})
    if auth_ats:
        ats_type = auth_ats
        ats_source = "url"
    else:
        # no ATS-hosted URL; use the most common non-unknown agent label, else custom/unknown
        non_unknown = [a for a in agent_labels if a not in ("unknown", "custom")]
        if non_unknown:
            ats_type = Counter(non_unknown).most_common(1)[0][0]
        elif "custom" in agent_labels:
            ats_type = "custom"
        else:
            ats_type = "unknown"
        ats_source = "guess"

    # conflict if multiple distinct standard ATS signals
    all_ats_signals = {a for a in agent_labels if a not in ("unknown",)} | ({auth_ats} if auth_ats else set())
    standard = {a for a in all_ats_signals if a not in ("custom", "yc", "unknown")}
    conflict = len(standard) > 1

    # board_token: real ATS board slug, but ONLY when the URL is an authoritative
    # ATS-hosted board (url/verified). For guess rows the primary_url is a
    # company-domain /careers page, so its first path segment (e.g. "company",
    # "about") is NOT a real slug — leave None to avoid junk-token enumeration.
    #
    # Some ATS types use the subdomain as the company identifier (e.g.
    # yousign.careers.teamtailor.com -> token is "yousign"), while others use
    # a path segment (e.g. boards.greenhouse.io/stripe -> token is "stripe").
    SUBDOMAIN_TOKEN_ATS = {"teamtailor", "personio", "breezyhr", "onlyfy"}
    PATH_TOKEN_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "rippling"}
    board_token = None
    if ats_source in ("url", "verified") and ats_type in (SUBDOMAIN_TOKEN_ATS | PATH_TOKEN_ATS):
        if ats_type in SUBDOMAIN_TOKEN_ATS:
            hostname = (urlparse(primary_url).hostname or "").lower()
            parts = hostname.split(".")
            if len(parts) >= 3:
                board_token = parts[0]  # first subdomain is the company slug
        else:
            m = re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", primary_url)
            if m:
                board_token = m.group(1)
    elif ats_type == "mailto":
        # mailto companies (e.g. PentStark) have no ATS slug; the enumerator
        # scrapes the careers page, so board_token IS the careers page URL.
        board_token = primary_url

    is_mnc = norm_name(name) in {norm_name(x) for x in MNC_FLAG}

    # Apply ground-truth overrides from board-API probing
    vkey = norm_name(name)
    if vkey in VERIFIED:
        v_ats, v_url = VERIFIED[vkey]
        ats_type = v_ats
        ats_source = "verified"
        if v_url not in urls:
            urls.insert(0, v_url)
        primary_url = v_url
        conflict = False
        # recompute board_token for the verified ATS URL
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

# ---- board-collision dedup ----
# Multiple companies can resolve to the SAME ATS-hosted board URL. Two cases,
# both produced by name-derived slug probing (notably the Wikidata harvest pass):
#   (a) generic-slug false positives: e.g. 396 "National ..." orgs all stamped with
#       boards.greenhouse.io/national — one unrelated company's real board. These
#       are wrong-company attributions and would enumerate the same jobs hundreds
#       of times under unrelated employers.
#   (b) true aliases: acquired brands / name variants on the parent's board, e.g.
#       Perforce + OpenLogic + Puppet + "Perforce Software" all on
#       jobs.lever.co/perforce. Same jobs enumerated 4x.
# Heuristic: the real owner of a board is the claimant whose website bare-domain
# or exact normalized name matches the board slug. Keep that one (deduping its
# name-variants to a canonical entry); revert every non-owner claimant to
# name-only (ats_type=unknown, not automatable). If no claimant matches the slug
# (all false positives), or several claimants with different domains match
# (ambiguous), keep the best-matching owner and revert the rest. This runs every
# consolidate, so the scheduler's rescan can't re-pollute the dataset.
SLUG_ATS = (SUBDOMAIN_TOKEN_ATS | PATH_TOKEN_ATS)  # ATS whose board URL carries a company slug

def board_url_key(url):
    return (url or "").lower().replace("https://", "").replace("http://", "").rstrip("/")

def board_slug(url, ats_type):
    """Company-identifying token from an ATS board URL (reuses the SUBDOMAIN/PATH split)."""
    if ats_type in SUBDOMAIN_TOKEN_ATS:
        parts = (urlparse(url).hostname or "").lower().split(".")
        return parts[0] if len(parts) >= 3 else ""
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
        # exact domain-label match, slug contained in the domain, or the domain
        # label is a >=4-char prefix of the slug (e.g. ExtraHop / extrahop.com
        # owns boards.greenhouse.io/extrahopnetworks).
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
    """Revert a false-positive/alias entry to name-only (not automatable)."""
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
        # no claimant matches the board slug -> all false positives
        for _i in _idxs:
            _strip_ats(_i)
        continue
    _keep = min(_owners, key=lambda i: (0 if merged[i].get("website") else 1,
                                        len(merged[i]["company_name"]), i))
    # non-owners are always false positives -> revert to name-only
    for _i in _idxs:
        if _i not in _owners:
            _strip_ats(_i)
    _doms = {bare_domain(merged[_i].get("website") or "") for _i in _owners}
    _doms.discard("")
    if len(_doms) <= 1:
        # one real entity (possibly several name variants) -> drop the dup variants
        for _i in _owners:
            if _i != _keep:
                _dedup_drop.add(_i)
    else:
        # several different companies plausibly own this slug -> keep the best
        # match, revert the other distinct companies to name-only (not dropped:
        # they're real companies, just not this board's owner)
        for _i in _owners:
            if _i != _keep:
                _strip_ats(_i)

if _dedup_drop:
    merged = [c for i, c in enumerate(merged) if i not in _dedup_drop]

# sort: automatable ATS first, then by name
ATS_ORDER = {"greenhouse":0, "lever":1, "ashby":2, "smartrecruiters":3, "workable":4,
             "personio":5, "workday":6, "bamboohr":7, "trinethire":8, "onlyfy":9,
             "keka":10, "pinpoint":11, "breezyhr":12, "teamtailor":13, "rippling":14,
             "attrax":15, "applytojob":16,
             "custom":17, "yc":18, "unknown":19}
merged.sort(key=lambda c: (ATS_ORDER.get(c["ats_type"], 99), c["company_name"].lower()))

# ---- write companies.json + csv ----
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

# ---- ats summary ----
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

# ---- by_ats split ----
os.makedirs(BY_ATS_DIR, exist_ok=True)
by_ats = defaultdict(list)
for c in merged:
    by_ats[c["ats_type"]].append({k: c[k] for k in
        ("company_name","website","career_page_url","board_token","domain_hint","source_platforms")})
for ats, rows in by_ats.items():
    with open(os.path.join(BY_ATS_DIR, f"{ats}.json"), "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

# ---- console report ----
print(f"Total raw entries : {len(raw)}")
print(f"Unique companies  : {len(merged)}")
print(f"Board-collision dedup: dropped {len(_dedup_drop)} alias-dup entr(ies), "
      f"reverted {_dedup_stripped} false-positive/alias entr(ies) to unknown")
print(f"ATS conflicts     : {len(conflicts)} -> {conflicts}")
print("By ATS:")
for ats, n in sorted(summary.items(), key=lambda kv: -kv[1]):
    print(f"  {ats:<16} {n}")