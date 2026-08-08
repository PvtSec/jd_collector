#!/usr/bin/env python3
import json, re, os, glob
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW = os.path.join(ROOT, "data", "raw")

def host(u):
    u = (u or "").strip()
    if not u: return ""
    if u.startswith("//"): u = "http:" + u
    if not re.match(r"^https?://", u, re.I): u = "http://" + u
    try: h = (urlparse(u).netloc or "").lower()
    except: return ""
    if h.startswith("www."): h = h[4:]
    return h

comps = json.load(open(os.path.join(ROOT, "data", "companies.json")))
af = json.load(open(os.path.join(RAW, "_fanout", "audit_final.json")))
junk_hosts = set()
for i in af["invalid_indices"]:
    for fld in ("career_page_url", "website"):
        h = host(comps[i].get(fld, ""))
        if h: junk_hosts.add(h)
print(f"junk host set: {len(junk_hosts)} exact hosts")

removed_total = 0
for f in sorted(glob.glob(os.path.join(RAW, "*.json"))):
    try: rows = json.load(open(f))
    except: continue
    if not isinstance(rows, list): continue
    kept = []
    removed = 0
    for r in rows:
        h = host(r.get("career_page_url", "")) or host(r.get("website", ""))
        if h and h in junk_hosts:
            removed += 1
            continue
        kept.append(r)
    if removed:
        json.dump(kept, open(f, "w"), ensure_ascii=False, indent=2)
        removed_total += removed
        print(f"  purged {removed:4}  {os.path.basename(f)}  (kept {len(kept)})")
print(f"\ntotal purged from raw: {removed_total}")
