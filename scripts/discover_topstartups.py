#!/usr/bin/env python3
"""Discover companies + matching jobs from https://topstartups.io (read-only).

Sweeps:
  1. Startup list (https://topstartups.io/?page=N)  -> every company card:
     name, website, "View Jobs" URL (often an ATS board URL), industry tags.
  2. Jobs board per target-role query (?role=...) -> ALL jobs whose title matches
     the candidate's target roles, walked page-by-page until stale.
     Core targets: Penetration Tester / QA Automation / SDET.
     Adjacent (pentest background): Security Engineer / AppSec / DevSecOps.

End detection: server returns page-1 content past the last page, so we stop when
a page adds nothing new. Pages are cached under data/.cache_topstartups/ so
re-runs are cheap.

Outputs:
  data/raw/agent6_topstartups.json   merge-ready company records (consolidate.py ingests)
  data/topstartups_matches.json      companies with open target-role jobs (actionable),
                                     each job tagged tier: core | adjacent

Re-run: .venv/bin/python scripts/discover_topstartups.py
"""
import json, os, re, time, sys
from urllib.parse import urlparse, urlunparse, quote_plus
import requests

BASE = "https://topstartups.io"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
H = {"User-Agent": UA}
DELAY = 0.4
CACHE = os.path.join("data", ".cache_topstartups")

ATS_HOSTS = [
    ("greenhouse",      ["boards.greenhouse.io", "job-boards.greenhouse.io"]),
    ("lever",           ["jobs.lever.co"]),
    ("ashby",           ["jobs.ashbyhq.com", "app.ashbyhq.com"]),
    ("smartrecruiters", ["jobs.smartrecruiters.com", "careers.smartrecruiters.com"]),
    ("workable",        ["apply.workable.com"]),
    ("personio",        [".jobs.personio.com", "jobs.personio.com"]),
    ("bamboohr",        [".bamboohr.com", "bamboohr.com/careers"]),
    ("trinethire",      ["app.trinethire.com"]),
    ("onlyfy",          [".onlyfy.jobs", "onlyfy.jobs"]),
    ("keka",            [".keka.com"]),
    ("pinpoint",        ["pinpointhq.com"]),
    ("breezyhr",        [".breezy.hr", "breezy.hr"]),
    ("teamtailor",      ["careers.teamtailor.com", ".teamtailor.com"]),
    ("rippling",        ["ats.rippling.com"]),
    ("workday",         [".myworkdayjobs.com", "myworkdayjobs.com"]),
]

def infer_ats(url):
    u = (url or "").lower()
    for ats_id, subs in ATS_HOSTS:
        for s in subs:
            if s in u:
                return ats_id
    return None

def norm_name(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())

def strip_tags(s):
    s = re.sub(r"<span[^>]*>.*?</span>", "", s, flags=re.S)   # drop badge spans (New/tags.new)
    s = re.sub(r"<[^>]+>", "", s)
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()

def clean_url(u):
    if not u:
        return ""
    u = u.strip().rstrip("/")
    p = urlparse(u)
    if p.query:
        u = urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    return u

def anchor_hrefs(card, id_val):
    """All href values from <a> tags carrying id=id_val (order-independent,
    quoted or unquoted href)."""
    out = []
    for m in re.finditer(r'<a\b([^>]*)>', card):
        tag = m.group(1)
        if f'id="{id_val}"' in tag:
            am = re.search(r'href\s*=\s*"([^"]*)"', tag)
            if not am:
                am = re.search(r'href\s*=\s*(\S+)', tag)
            if am:
                out.append(am.group(1).strip())
    return out

def board_root(url, ats):
    u = clean_url(url)
    if not u:
        return "", None
    p = urlparse(u)
    parts = [x for x in p.path.split("/") if x]
    token = parts[0] if parts else ""
    if ats == "ashby":
        return f"https://jobs.ashbyhq.com/{token}", token
    if ats == "greenhouse":
        return f"https://boards.greenhouse.io/{token}", token
    if ats == "lever":
        return f"https://jobs.lever.co/{token}", token
    if ats == "workable":
        return f"https://apply.workable.com/{token}", token
    if ats == "smartrecruiters":
        return f"https://jobs.smartrecruiters.com/{token}", token
    if ats == "personio":
        return f"https://{p.netloc}", p.netloc.split(".jobs.personio.com")[0]
    if ats == "teamtailor":
        return f"https://{p.netloc}", p.netloc.split(".teamtailor.com")[0].replace("careers.", "")
    if ats == "breezyhr":
        return f"https://{p.netloc}", p.netloc.split(".breezy.hr")[0]
    if ats == "onlyfy":
        return f"https://{p.netloc}", p.netloc.split(".onlyfy.jobs")[0]
    if ats == "rippling":
        return f"https://ats.rippling.com/{token}/jobs", token
    if ats == "workday":
        return u, None
    return u, token or None

os.makedirs(CACHE, exist_ok=True)

def fetch(url):
    key = re.sub(r'[^a-z0-9]', '_', url.lower())
    path = os.path.join(CACHE, key + ".html")
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    for attempt in range(3):
        try:
            r = requests.get(url, headers=H, timeout=30)
            if r.status_code == 200:
                open(path, "w", encoding="utf-8").write(r.text)
                return r.text
            print(f"  [{r.status_code}] {url}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  retry {attempt}: {e}", file=sys.stderr)
        time.sleep(1.5)
    return ""

# ---- startup list parsing ----
def parse_startup_page(html):
    out = []
    for c in re.split(r'infinite-item', html)[1:]:
        mname = re.search(r'<h3[^>]*>(.*?)</a></h3>', c, re.S)
        name = strip_tags(mname.group(1)) if mname else ""
        if not name:
            continue
        site = clean_url((anchor_hrefs(c, "startup-website-link") or [""])[0])
        jobs = clean_url((anchor_hrefs(c, "view-jobs") or [""])[0])
        inds = [strip_tags(x) for x in re.findall(r'id="industry-tags"[^>]*>(.*?)</span>', c, re.S)]
        out.append({"name": name, "website": site, "view_jobs": jobs,
                    "industries": [i for i in inds if i]})
    return out

# ---- jobs board parsing ----
def parse_jobs_page(html):
    out = []
    for c in re.split(r'infinite-item', html)[1:]:
        mco = re.search(r'<h7[^>]*>(.*?)</h7>', c, re.S)
        company = strip_tags(mco.group(1)) if mco else ""
        if not company:
            continue
        mtitle = re.search(r'<h5[^>]*>(.*?)</h5>', c, re.S)
        title = strip_tags(mtitle.group(1)) if mtitle else ""
        links = anchor_hrefs(c, "startup-website-link")
        website = clean_url(links[0]) if links else ""
        apply_url = clean_url(links[1]) if len(links) > 1 else ""
        mloc = re.search(r'fa-map-marker-alt"></i>\s*(.*?)</h7>', c, re.S)
        location = strip_tags(mloc.group(1)) if mloc else ""
        out.append({"company": company, "website": website, "apply_url": apply_url,
                    "title": title, "location": location})
    return out

# ---------------- main ----------------
def main():
    companies = {}

    def upsert(name, website, careers_url, industries):
        key = norm_name(name)
        if not key:
            return None
        rec = companies.get(key)
        if rec is None:
            rec = {"company_name": name, "career_page_url": "", "website": website or "",
                   "domain_hint": "", "ats_type": "unknown", "source_platform": "topstartups.io",
                   "industries": industries or []}
            companies[key] = rec
        if website and not rec["website"]:
            rec["website"] = website
        if industries:
            for i in industries:
                if i not in rec["industries"]:
                    rec["industries"].append(i)
        ats = infer_ats(careers_url)
        if ats:
            root, token = board_root(careers_url, ats)
            if root:
                rec["career_page_url"] = root
                rec["ats_type"] = ats
                rec["board_token"] = token or ""
        elif not rec["career_page_url"] and careers_url:
            rec["career_page_url"] = careers_url
        return rec

    # ---- sweep 1: startup list ----
    print("== startup list ==")
    seen = set()
    stale = 0
    page = 1
    while page <= 80 and stale < 2:
        html = fetch(f"{BASE}/?page={page}")
        if not html:
            break
        cards = parse_startup_page(html)
        if not cards:
            break
        new = 0
        for c in cards:
            upsert(c["name"], c["website"], c["view_jobs"], c["industries"])
            k = norm_name(c["name"])
            if k not in seen:
                seen.add(k); new += 1
        print(f"  page {page}: {len(cards)} cards, {new} new, total {len(companies)}")
        stale = stale + 1 if new == 0 else 0
        page += 1
        time.sleep(DELAY)

    # ---- sweep 2: matching jobs by target role ----
    # (keyword, tier)  -- core = active targets, adjacent = pentest-background relevant
    ROLE_QUERIES = [
        ("core",     "Penetration Tester"),
        ("core",     "Pentest"),
        ("core",     "Red Team"),
        ("core",     "Offensive Security"),
        ("core",     "SDET"),
        ("core",     "QA Automation"),
        ("core",     "QA Engineer"),
        ("core",     "Test Automation"),
        ("core",     "Software Engineer in Test"),
        ("adjacent", "Security Engineer"),
        ("adjacent", "Application Security"),
        ("adjacent", "AppSec"),
        ("adjacent", "Product Security"),
        ("adjacent", "DevSecOps"),
    ]
    # titles that are clearly NOT IC target roles even if keyword matches
    EXCLUDE_RE = re.compile(r"\b(manager|director|head of|vp|intern|lead\s+engineer|principal|chief|internship)\b", re.I)

    print("== matching jobs ==")
    # job dedup key = apply_url (falls back to company+title)
    jobs_by_url = {}
    company_matches = {}  # norm_name -> {company, ats, board_url, tier, jobs:[...]}

    for tier, role in ROLE_QUERIES:
        stale = 0
        page = 1
        role_new = 0
        while page <= 60 and stale < 4:
            html = fetch(f"{BASE}/jobs/?role={quote_plus(role)}&page={page}")
            if not html:
                break
            cards = parse_jobs_page(html)
            if not cards:
                break
            page_new = 0
            for c in cards:
                if not c["title"]:
                    continue
                url = c["apply_url"] or f"{c['company']}|{c['title']}"
                if url in jobs_by_url:
                    continue
                # relevance gate: title should actually contain the role keyword,
                # and not be an excluded seniority/role type
                low = c["title"].lower()
                if role.lower() not in low and role.replace(" ", "") not in low.replace(" ", ""):
                    continue
                if EXCLUDE_RE.search(low) and not re.search(r"\b(sd|software development engineer)", low):
                    # keep SDET even though it has no exclude words; drop managers etc.
                    if not low.startswith(("sdet",)):
                        continue
                jobs_by_url[url] = True
                page_new += 1
                role_new += 1
                rec = upsert(c["company"], c["website"], c["apply_url"], [])
                k = norm_name(c["company"])
                cm = company_matches.get(k)
                if cm is None:
                    cm = {"company": c["company"], "ats": rec["ats_type"] if rec else "unknown",
                          "board_url": rec["career_page_url"] if rec else "",
                          "tier": tier, "jobs": []}
                    company_matches[k] = cm
                else:
                    # core wins over adjacent
                    if tier == "core" and cm["tier"] != "core":
                        cm["tier"] = "core"
                entry = {"title": c["title"], "location": c["location"],
                         "url": c["apply_url"], "tier": tier}
                if entry not in cm["jobs"]:
                    cm["jobs"].append(entry)
            stale = stale + 1 if page_new == 0 else 0
            print(f"  role={role!r:28} page {page}: {len(cards)} cards, {page_new} new, role-total {role_new}")
            page += 1
            time.sleep(DELAY)

    # ---- finalize raw file ----
    raw = []
    for rec in companies.values():
        inds = rec.get("industries") or []
        rec["domain_hint"] = " / ".join(inds[:4]) if inds else ""
        raw.append({
            "company_name": rec["company_name"],
            "career_page_url": rec["career_page_url"],
            "website": rec["website"],
            "domain_hint": rec["domain_hint"],
            "ats_type": rec["ats_type"],
            "source_platform": "topstartups.io",
        })
    with open("data/raw/agent6_topstartups.json", "w") as f:
        json.dump(raw, f, indent=2)
    print(f"\nwrote data/raw/agent6_topstartups.json  ({len(raw)} companies)")

    # ---- matches report: core first ----
    match_list = sorted(company_matches.values(),
                        key=lambda m: (0 if m["tier"] == "core" else 1, m["company"].lower()))
    with open("data/topstartups_matches.json", "w") as f:
        json.dump(match_list, f, indent=2)
    n_core = sum(1 for m in match_list if m["tier"] == "core")
    n_jobs = sum(len(m["jobs"]) for m in match_list)
    print(f"wrote data/topstartups_matches.json  ({len(match_list)} companies, "
          f"{n_core} core, {n_jobs} matching jobs)")

    from collections import Counter
    brk = Counter(r["ats_type"] for r in raw)
    print("ATS breakdown:", dict(brk))

if __name__ == "__main__":
    main()