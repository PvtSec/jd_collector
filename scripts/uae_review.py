#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import dlib  # noqa: E402

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
COMPANIES = os.path.join(os.path.dirname(__file__), "..", "data", "companies.json")
OUT = os.path.join(RAW, "uae_candidates.json")
UAE_FILES = ["uae_wikidata.json", "uae_osm.json", "uae_dirs.json"]


def load_existing_keys() -> set[str]:
    if not os.path.exists(COMPANIES):
        return set()
    with open(COMPANIES, encoding="utf-8") as f:
        comps = json.load(f)
    return {dlib.norm_key(c) for c in comps if c.get("company_name")}


def _qatar(r: dict) -> bool:
    web = (r.get("website") or r.get("career_page_url") or "").lower()
    name = (r.get("company_name") or "").lower()
    if web.endswith(".qa") or ".qa/" in web or "//www." in web and web.rstrip("/").endswith(".qa"):
        return True
    for t in ("qatar", "doha", "lusail", "the pearl-qatar", "al bidda"):
        if t in name:
            return True
    return False


NON_EMPLOYER = ("hotel", " resort", " mall", "mosque", " park", "stadium", " beach",
                "autodrome", " museum", " cinema", "aquarium", "theme park",
                "ferrari world", " golf", " zoo", "waterfall", "heritage village",
                " fort", " palace", "tower of", "observatory", "roller", "ski dubai")


def _non_employer(r: dict) -> bool:
    name = " " + (r.get("company_name") or "").lower() + " "
    return any(k in name for k in NON_EMPLOYER)


def main() -> int:
    existing = load_existing_keys()
    print(f"[uae-review] existing companies.json keys: {len(existing)}")

    by_src: dict[str, int] = {}
    uniq: dict[str, dict] = {}
    total = 0
    for fn in UAE_FILES:
        p = os.path.join(RAW, fn)
        if not os.path.exists(p):
            print(f"  (missing {fn})")
            continue
        with open(p, encoding="utf-8") as f:
            rows = json.load(f)
        n_file = 0
        for r in rows:
            total += 1
            name = r.get("company_name") or ""
            if not name or _qatar(r):
                continue
            key = dlib.norm_key(r)
            if not key or key in uniq:
                continue
            uniq[key] = r
            by_src[r.get("source", "?")] = by_src.get(r.get("source", "?"), 0) + 1
            n_file += 1
        print(f"  {fn}: {len(rows)} rows -> {n_file} unique-added (Qatar dropped)")

    new_rows = [r for k, r in uniq.items() if k not in existing]

    automatable = sum(1 for r in new_rows if dlib.is_ats_host_url(r.get("career_page_url", "")))
    name_only = len(new_rows) - automatable
    noise = sum(1 for r in new_rows if _non_employer(r))
    clean_rows = [r for r in new_rows if not _non_employer(r)]

    print("\n=== UAE candidate report ===")
    print(f"total UAE rows read:          {total}")
    print(f"unique after UAE dedup:       {len(uniq)}")
    print(f"NEW (not in companies.json):   {len(new_rows)}")
    print(f"  - ATS-automatable:           {automatable}")
    print(f"  - name-only (website):       {name_only}")
    print(f"  - likely non-employer POIs:  {noise}  (hotels/malls/mosques/landmarks)")
    print(f"  - clean (employer-ish):      {len(clean_rows)}")
    print("by source:")
    for s, n in sorted(by_src.items(), key=lambda x: -x[1]):
        print(f"  {s:20} {n}")

    print("\n--- sample of 30 NEW UAE candidates (clean subset) ---")
    for r in clean_rows[:30]:
        ats = dlib.infer_ats_from_url(r.get("career_page_url", "")) or "-"
        print(f"  [{ats:14}] {r.get('company_name', '')[:38]:38} | {(r.get('website') or r.get('career_page_url',''))[:50]}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(new_rows, f, ensure_ascii=False)
    with open(OUT.replace("uae_candidates", "uae_candidates_clean"), "w", encoding="utf-8") as f:
        json.dump(clean_rows, f, ensure_ascii=False)
    print(f"\n[uae-review] wrote {len(new_rows)} NEW (full) -> {OUT}")
    print(f"[uae-review] wrote {len(clean_rows)} NEW (clean) -> {OUT.replace('uae_candidates','uae_candidates_clean')}")
    print("[uae-review] NOT merging — review and approve before running consolidate.py")
    return len(new_rows)


if __name__ == "__main__":
    main()