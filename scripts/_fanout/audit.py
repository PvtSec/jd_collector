#!/usr/bin/env python3
import json, re, os
from collections import Counter, defaultdict
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
comps = json.load(open(os.path.join(ROOT, "data", "companies.json")))
N = len(comps)

AUTOMATABLE={"greenhouse","lever","ashby","smartrecruiters","workable","personio",
 "workday","bamboohr","trinethire","onlyfy","keka","pinpoint","breezyhr","teamtailor","rippling","attrax","applytojob"}
SUBDOMAIN_TOKEN_ATS={"teamtailor","personio","breezyhr","onlyfy","bamboohr"}
PATH_TOKEN_ATS={"greenhouse","lever","ashby","smartrecruiters","workable","rippling"}
ATS_APEX={"greenhouse.io","lever.co","ashbyhq.com","workable.com","personio.com","personio.de",
 "smartrecruiters.com","bamboohr.com","teamtailor.com","trinethire.com","onlyfy.jobs","keka.com",
 "pinpointhq.com","breezy.hr","rippling.com","myworkdayjobs.com","workday.com","applytojob.com",
 "wise.jobs","recruitee.com","jobsoid.com","jobvite.com","icims.com","taleo.com","taleo.net",
 "ultipro.com","ukg.com","successfactors.com"}

def host(u):
    try: return (urlparse(u).netloc or "").lower().lstrip("www.")
    except: return ""
def norm_name(n):
    n=(n or "").lower(); n=re.sub(r"\s*\(.*?\)\s*"," ",n); return re.sub(r"[^a-z0-9]","",n)
def board_key(u):
    return (u or "").lower().strip().rstrip("/").replace("https://","").replace("http://","")
def path_slug(u):
    m=re.search(r"https?://[^/]+/([A-Za-z0-9_\-]+)", (u or "").lower()); return m.group(1) if m else ""

NONJOB_HOST_SUFFIX=[
 "web.archive.org","archive.org","archive-it.org","web.archive",
 "gallica.bnf.fr","expositions.bnf.fr","gallicaintramuros.bnf.fr","catalogue.bnf.fr",".bnf.fr",
 "inria.fr","team.inria.fr",".inria.fr","hal.science","hal.inria","persee.fr",
 "brill.com","brill.nl","brillonline.com","booksandjournals.brillonline.com",
 "data.gouv.fr","data.amsterdam.nl","data.cityofchicago.org","data.gov","opendata",
 "cfl.lu","mobiliteco.lu",
 "bm-lyon.fr","bm.nancy.fr","bm-grenoble.fr",
 "mod.go.jp",".go.jp","mtbldb.mlit.go.jp",
 "europeana.eu","jstor.org","doi.org","sciencedirect.com","link.springer.com","springer.com",
 "academia.edu","researchgate.net","wikimedia.org",".wikipedia.org","wikidata.org",
 "patents.google.com","google.com/patent","legacy.lib","library.osu.edu","babel.hathitrust.org",
 "catalogue.idref.fr","idref.fr","viaf.org","catalog.loc.gov","worldcat.org",
 "amsterdam.nl","rotterdam.nl",
]
def is_nonjob(h):
    if not h: return False
    if h in ("web.archive.org","archive.org"): return True
    for s in NONJOB_HOST_SUFFIX:
        if h==s or h.endswith("."+s) or h.endswith(s): return True
    return False

invalid_nonjob=[]
invalid_shared_nonats=[]
fixable_scheme=[]
bare_domain=[]
auto_no_token=0
ats_alias_groups=0; ats_alias_rows=0

by_url=defaultdict(list)
for i,c in enumerate(comps):
    u=(c.get("career_page_url") or "").strip()
    if u: by_url[board_key(u)].append(i)

for i,c in enumerate(comps):
    raw=(c.get("career_page_url") or "").strip()
    ats=c.get("ats_type"); h=host(raw); lu=(raw or "").lower()
    if is_nonjob(h):
        invalid_nonjob.append(i); continue
    if raw:
        grp=by_url[board_key(raw)]
        if len(grp)>=3 and h not in ATS_APEX and not any(h.endswith("."+a) for a in ATS_APEX):
            invalid_shared_nonats.append(i); continue
    if raw and (lu.startswith("http://") or lu.startswith("https://")):
        pass
    elif raw.startswith("//"):
        fixable_scheme.append(i)
    elif re.match(r"^https?://", raw, re.I) and not lu.startswith(("http://","https://")):
        fixable_scheme.append(i)
    elif raw and not lu.startswith(("http://","https://")) and ("/" not in raw):
        if "." in raw: bare_domain.append(i)
    if ats in AUTOMATABLE and not c.get("board_token"):
        auto_no_token+=1

by_tok=defaultdict(list)
for i,c in enumerate(comps):
    t=c.get("board_token")
    if t and c.get("ats_type") in AUTOMATABLE: by_tok[(c["ats_type"],str(t).lower())].append(i)
alias_groups={k:v for k,v in by_tok.items() if len(v)>1}
ats_alias_groups=len(alias_groups); ats_alias_rows=sum(len(v) for v in alias_groups.values())

by_name=defaultdict(list)
for i,c in enumerate(comps):
    nm=norm_name(c.get("company_name"))
    if nm: by_name[nm].append(i)
name_collisions=sum(1 for v in by_name.values() if len(v)>1)

inv=set(invalid_nonjob)|set(invalid_shared_nonats)
print(f"loaded {N:,} companies\n")
print("=== GENUINELY INVALID / FALSE JOB PAGES (purgable) ===")
print(f"  non-job host (catalog/archive/gov-data/journal/wayback) : {len(invalid_nonjob):,}")
print(f"  shared >=3 cos on non-ATS host (catalog/aggregator)     : {len(invalid_shared_nonats):,}")
print(f"  TOTAL purgable invalid                                   : {len(inv):,}")
print()
print("=== NOT invalid (do NOT purge) ===")
print(f"  ATS same-board alias groups / rows (legit subsidiaries)  : {ats_alias_groups} / {ats_alias_rows}")
print(f"  normalized-name collisions (should be 0)                 : {name_collisions}")
print(f"  fixable scheme (capital/protocol-relative, valid)        : {len(fixable_scheme):,}")
print(f"  bare-domain homepage (weak, name+site seed)              : {len(bare_domain):,}")
print(f"  automatable ats but no board_token (not enumerable)      : {auto_no_token:,}")

print("\n-- purge breakdown: top non-job hosts --")
c=Counter(host(comps[i].get("career_page_url","")) for i in invalid_nonjob)
for h,n in c.most_common(20): print(f"   {n:5}  {h}")
print("\n-- purge breakdown: top shared non-ATS hosts --")
c2=Counter(host(comps[i].get("career_page_url","")) for i in invalid_shared_nonats)
for h,n in c2.most_common(20): print(f"   {n:5}  {h}")
print("\n-- sample purge rows --")
for i in list(invalid_nonjob)[:8]+list(invalid_shared_nonats)[:8]:
    cc=comps[i]; print(f"   {cc['company_name'][:34]:34} {cc.get('career_page_url','')[:50]}")

purge_names=sorted({comps[i]["company_name"] for i in inv})
json.dump({"count":len(inv),"names":purge_names},
          open(os.path.join(ROOT,"data","raw","_fanout","purge_invalid.json"),"w"),ensure_ascii=False)
json.dump({"count":len(fixable_scheme),"indices":fixable_scheme},
          open(os.path.join(ROOT,"data","raw","_fanout","fixable_scheme.json"),"w"))
print(f"\nwrote purge_invalid.json ({len(purge_names)} names) + fixable_scheme.json ({len(fixable_scheme)})")
