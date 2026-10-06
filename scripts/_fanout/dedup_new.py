#!/usr/bin/env python3
import json, os, re, sys
from urllib.parse import urlparse
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
FAN = os.path.join(RAW, "_fanout")
DONE = os.path.join(FAN, "done")
IDX = os.path.join(FAN, "existing_index.json")

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

def norm_name(name):
    n = (name or "").lower()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n)
    n = n.replace("(formerly rstudio)", " ")
    n = re.sub(r"[^a-z0-9]", "", n)
    return n

def infer_ats(url):
    u = (url or "").lower()
    for ats_id, subs in ATS_HOST_RULES:
        for s in subs:
            if s in u:
                return ats_id
    return None

ATS_VENDOR_APEX = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "personio.com",
    "personio.de", "smartrecruiters.com", "bamboohr.com", "teamtailor.com",
    "trinethire.com", "onlyfy.jobs", "keka.com", "pinpointhq.com", "breezy.hr",
    "rippling.com", "myworkdayjobs.com", "workday.com", "applytojob.com",
    "wise.jobs", "ycombinator.com", "recruitee.com", "jobsoid.com", "jobvite.com",
    "icims.com", "taleo.com", "taleo.net", "ultipro.com", "ukg.com",
    "successfactors.com",
}

def real_domain(url):
    d = registrable_domain(url)
    return "" if d in ATS_VENDOR_APEX else d


MULTI_TLD = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "ltd.uk", "plc.uk",
    "sch.uk", "com.au", "net.au", "org.au", "edu.au", "co.nz", "net.nz", "org.nz",
    "co.jp", "co.kr", "or.kr", "ne.jp", "co.in", "net.in", "org.in", "firm.in",
    "com.sg", "com.hk", "com.mx", "com.br", "org.br", "net.br", "co.za", "web.za",
    "com.tr", "com.ar", "com.co", "co.id", "com.my", "com.ph", "com.vn", "com.cn",
    "com.tw",
}


def registrable_domain(url):
    h = host(url)
    if not h:
        return ""
    parts = h.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_TLD:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return h


AGG_APEX = {
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "monster.com", "flexjobs.com", "talent.com", "jooble.org", "simplyhired.com",
    "careerbuilder.com", "snagajob.com", "dice.com", "theladders.com",
    "wellfound.com", "angel.co", "otta.com", "weworkremotely.com",
    "remoteok.com", "remotive.com", "workingnomads.com", "himalayas.com",
    "builtin.com", "builtinnyc.com", "startup.jobs", "producthunt.com",
    "crunchbase.com", "owler.com", "craft.co",
    "roberthalf.com", "randstad.com", "adecco.com", "manpower.com",
    "kornferry.com", "heidrick.com", "teksystems.com", "insightglobal.com",
    "cybercoders.com", "modis.com", "apexsystems.com", "aerotek.com",
    "allegisgroup.com", "spherion.com", "kellyservices.com", "expresspros.com",
    "michaelpage.com", "hays.com", "pagepersonnel.com", "mastechdigital.com",
    "mlaglobal.com", "deeptech.jobs", "spencerstuart.com", "russellreynolds.com",
    "egonzehnder.com", "stantonchase.com", "boyden.com", "normanbroadbent.com",
    "ward-secure.com", "intersearch.org", "alto-partners.com",
}

DENY_NAMES = {norm_name(x) for x in [
    "Lever", "Greenhouse", "Ashby", "Workable", "Personio", "SmartRecruiters",
    "BambooHR", "TeamTailor", "Trinet Hire", "Trinethire", "Onlyfy", "Keka",
    "Pinpoint", "Breezy HR", "Rippling", "Workday", "Recruitee", "Jobsoid",
    "Jobvite", "iCIMS", "Taleo", "UltiPro", "UKG", "SuccessFactors",
    "Applytojob", "Wise (Attrax)",
    "Glassdoor", "Indeed", "LinkedIn", "ZipRecruiter", "Monster", "FlexJobs",
    "We Work Remotely", "RemoteOK", "Remotive", "Himalayas", "Built In",
    "Otta", "Wellfound", "AngelList", "Product Hunt", "Crunchbase",
    "Robert Half", "Randstad", "Adecco", "Manpower", "ManpowerGroup",
    "Kelly Services", "Korn Ferry", "Heidrick & Struggles", "TEKsystems",
    "Insight Global", "CyberCoders", "Modis", "Apex Systems", "Aerotek",
    "Allegis Group", "Spherion", "Express Employment Professionals",
    "Michael Page", "Hays", "PageGroup", "Mastech Digital",
    "Major Lindsey & Africa", "Major Lindsey", "Spencer Stuart",
    "Russell Reynolds", "Egon Zehnder", "Stanton Chase", "Boyden",
    "Norman Broadbent", "Per Ardua", "Wise Employment", "Allegis",
    "Morgan Philips", "Michael Bailey", "Frazer Jones",
]}

DENY_NAME_CONTAINS = [
    "recruitment", "recruitingagency", "staffing", "employmentagency",
    "executivesearch", "searchfirm", "talentagency", "rposervices",
    "manpowerservices", "jobboard", "jobportal", "careersportal",
    "staffingsolutions", "recruitsolutions", "talentsolutions",
    "employment services", "staffing solutions", "executive search",
    "search partners", "talent solutions", "headhunters",
]

GENERIC_ATS_SLUGS = {
    "careers", "career", "jobs", "job", "jobboard", "company", "companies",
    "national", "default", "apply", "app", "main", "home", "index", "new",
    "test", "demo", "sample", "board", "boards", "greenhouse", "lever",
    "ashby", "workable", "general", "login", "portal", "site", "null", "none",
    "yourcompany", "example", "acme", "foo", "bar", "xxx", "yyy",
}

JUNK_URL_HINTS = ("example.com", "example.org", "yourcompany", "your-domain",
                  "domain.com", "acme.com", "changeme", "localhost", "127.0.0.1",
                  " FIXME", "TODO", "INSERT")


def ats_slug(url):
    m = re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", url or "")
    return (m.group(1) or "").lower() if m else ""

NON_COMPANY_HOSTS = [
    "bnf.fr", "inria.fr", "go.jp", "cfl.lu", "bm-lyon.fr", "ajmanded.ae",
    "brill.com", "brill.nl", "brillonline.com", "ingentaconnect.com",
    "archive.org", "archive-it.org", "opendata.arcgis.com", "data.gouv.fr",
    "data.amsterdam.nl", "rotterdamopendata.nl", "wikipedia.org", "wikimedia.org",
    "wikidata.org", "sciencedirect.com", "springer.com", "hathitrust.org",
    "persee.fr", "hal.science", "europeana.eu", "idref.fr", "academia.edu",
    "doi.org", "jstor.org", "adeli.biz", "ndl.go.jp", "jstage.jst.go.jp",
]


def _host_of(url):
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "http:" + u
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    try:
        h = (urlparse(u).netloc or "").lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def is_non_company(url, website):
    h = _host_of(url) or _host_of(website)
    if not h:
        return False
    return any(h == s or h.endswith("." + s) for s in NON_COMPANY_HOSTS)


def is_denied(name, name_dom, url):
    nm = norm_name(name)
    if nm in DENY_NAMES:
        return True
    for s in DENY_NAME_CONTAINS:
        if s in nm:
            return True
    url_apex = bare_domain(url)
    if url_apex and url_apex in AGG_APEX:
        return True
    if name_dom and name_dom in AGG_APEX:
        return True
    return False


def build_index():
    if os.path.exists(IDX):
        with open(IDX) as f:
            return json.load(f)
    names = set()
    domains = set()
    src = os.path.join(DATA, "companies.json")
    if os.path.exists(src):
        with open(src) as f:
            for c in json.load(f):
                nm = norm_name(c.get("company_name"))
                if nm:
                    names.add(nm)
                d = real_domain(c.get("career_page_url")) or real_domain(c.get("website"))
                if d:
                    domains.add(d)
    obj = {"names": sorted(names), "domains": sorted(domains)}
    os.makedirs(FAN, exist_ok=True)
    with open(IDX, "w") as f:
        json.dump(obj, f)
    return obj


def process(path, names, domains):
    if not os.path.exists(path):
        return {"file": path, "error": "missing"}
    with open(path) as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        return {"file": path, "error": "not_a_list", "got": type(rows).__name__}
    kept = []
    dropped_existing = 0
    dropped_deny = 0
    dropped_empty = 0
    dropped_generic = 0
    dropped_junk = 0
    seen = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = (r.get("company_name") or "").strip()
        if len(name) < 2:
            dropped_empty += 1
            continue
        url = (r.get("career_page_url") or "").strip()
        web = (r.get("website") or "").strip()
        if any(j in (url + web).lower() for j in JUNK_URL_HINTS):
            dropped_junk += 1
            continue
        if is_non_company(url, web):
            dropped_junk += 1
            continue
        name_dom = real_domain(web) or real_domain(url)
        nm = norm_name(name)
        if is_denied(name, name_dom, url):
            dropped_deny += 1
            continue
        ats = infer_ats(url)
        if ats and ats_slug(url) in GENERIC_ATS_SLUGS:
            dropped_generic += 1
            continue
        if (nm and nm in names) or (name_dom and name_dom in domains):
            dropped_existing += 1
            continue
        key = nm or name_dom
        if not key or key in seen:
            continue
        seen.add(key)
        r.setdefault("website", web)
        r["domain_hint"] = r.get("domain_hint") or name_dom
        r["ats_type"] = ats if ats else r.get("ats_type", "unknown")
        r.setdefault("source_platform", "fanout")
        kept.append(r)
    with open(path, "w") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    ats_counts = dict(Counter(r.get("ats_type", "unknown") for r in kept))
    automatable = sum(v for k, v in ats_counts.items()
                      if k in {"greenhouse","lever","ashby","smartrecruiters",
                               "workable","personio","workday","bamboohr",
                               "trinethire","onlyfy","keka","pinpoint","breezyhr",
                               "teamtailor","rippling","attrax","applytojob"})
    summary = {
        "file": os.path.basename(path),
        "input": len(rows),
        "kept_new": len(kept),
        "dropped_existing": dropped_existing,
        "dropped_denylist": dropped_deny,
        "dropped_generic_slug": dropped_generic,
        "dropped_junk_url": dropped_junk,
        "dropped_empty_or_dup": dropped_empty,
        "ats_counts": ats_counts,
        "automatable": automatable,
    }
    os.makedirs(DONE, exist_ok=True)
    with open(os.path.join(DONE, os.path.basename(path) + ".json"), "w") as f:
        json.dump(summary, f, indent=2)
    return summary


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        print("usage: dedup_new.py <rawfile> [<rawfile> ...]", file=sys.stderr)
        sys.exit(2)
    idx = build_index()
    names, domains = set(idx["names"]), set(idx["domains"])
    out = [process(p, names, domains) for p in paths]
    print(json.dumps(out, ensure_ascii=False))
