from __future__ import annotations
import concurrent.futures
import json
import os
import re
import sys
from urllib.parse import urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RAW_OUT = os.path.join(DATA, "raw", "agent12_chsr.json")
CACHE_DIR = os.path.join(DATA, ".cache_chsr")
README_URL = "https://raw.githubusercontent.com/edoardottt/companies-hiring-security-remote/main/README.md"

# Mirror of consolidate.py ATS_HOST_RULES — only the ATS we can detect from a
# careers-URL host. (jobvite/recruitee/comeet/etc. have no dashboard enumerator,
# so they stay "unknown" here, consistent with the rest of the project.)
ATS_HOST_RULES = [
    ("greenhouse", ["boards.greenhouse.io", "job-boards.greenhouse.io"]),
    ("lever", ["jobs.lever.co"]),
    ("ashby", ["jobs.ashbyhq.com", "app.ashbyhq.com"]),
    ("smartrecruiters", ["jobs.smartrecruiters.com", "careers.smartrecruiters.com"]),
    ("workable", ["apply.workable.com"]),
    ("personio", ["jobs.personio.com", ".jobs.personio.com"]),
    ("bamboohr", [".bamboohr.com", "bamboohr.com/careers"]),
    ("onlyfy", [".onlyfy.jobs", "onlyfy.jobs"]),
    ("keka", [".keka.com"]),
    ("pinpoint", ["pinpointhq.com"]),
    ("breezyhr", [".breezy.hr", "breezy.hr"]),
    ("teamtailor", ["careers.teamtailor.com", ".teamtailor.com"]),
    ("rippling", ["ats.rippling.com"]),
    ("workday", [".myworkdayjobs.com", "myworkdayjobs.com"]),
]

# Probe order for the slug-probing fallback (company-domain careers pages).
ATS_ORDER = ["greenhouse", "lever", "ashby"]
GENERIC_SLUGS = {"company", "inc", "labs", "lab", "ai", "app", "the", "group",
                 "tech", "technologies", "technology", "systems", "global",
                 "digital", "data", "cloud", "software", "solutions", "services",
                 "holdings", "corp", "corporation", "limited", "ltd", "security",
                 "networks", "network", "cyber", "defense"}


def _norm(name: str) -> str:
    n = re.sub(r"\s*\(.*?\)\s*", " ", (name or "").lower())
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def domain_from(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").replace("www.", "")
    except Exception:
        return ""


def infer_ats_from_url(url: str) -> str | None:
    h = (urlparse(url).hostname or "").lower()
    if not h:
        return None
    for ats, subs in ATS_HOST_RULES:
        for s in subs:
            core = s[1:] if s.startswith(".") else s
            if h == core or h.endswith("." + core):
                return ats
    # personio country TLDs not in the static list (e.g. *.jobs.personio.de)
    if re.search(r"jobs\.personio\.[a-z.]+$", h):
        return "personio"
    # workable subdomain boards: <slug>.workable.com (consolidate only knows apply.workable.com)
    if h.endswith(".workable.com") and h != "apply.workable.com":
        return "workable"
    return None


def workable_slug(url: str) -> str | None:
    h = (urlparse(url).hostname or "").lower()
    if h.endswith(".workable.com") and h not in ("apply.workable.com", "workable.com"):
        return h.split(".")[0]
    return None


def fetch_readme() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "README.md")
    use_cache = os.path.exists(cache)
    if use_cache:
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            use_cache = False
    r = requests.get(README_URL, timeout=30,
                     headers={"User-Agent": "Mozilla/5.0 (job-auto chsr-discovery)"})
    r.raise_for_status()
    text = r.text
    with open(cache, "w", encoding="utf-8") as f:
        f.write(text)
    return text


# | Company | ... | [Link](url) | ... |
ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|[^|]*\|[^|]*\|\s*\[Link\]\(([^)]+)\)\s*\|[^|]*\|\s*$"
)


def parse_table(md: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen = set()
    for line in md.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        url = m.group(2).strip()
        if not name or not url or name.lower() in ("company", "---", "company name"):
            continue
        # drop any trailing Markdown bold/asterisks + rating noise like "4.5"
        name = re.sub(r"[*`]", "", name).strip()
        k = _norm(name)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append((name, url))
    return out


def existing_names(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    try:
        comps = json.load(open(path, encoding="utf-8"))
    except Exception:
        return set()
    return {_norm(c.get("company_name", "")) for c in comps}


def probe_one(name: str, careers_url: str) -> dict:
    ats = infer_ats_from_url(careers_url)
    if ats == "workable":
        # <slug>.workable.com -> rewrite to apply.workable.com/{slug} so
        # consolidate.py derives a board_token (PATH token) and it's automatable.
        slug = workable_slug(careers_url)
        if slug:
            return {
                "company_name": name,
                "career_page_url": f"https://apply.workable.com/{slug}",
                "website": "",
                "domain_hint": domain_from(careers_url),
                "ats_type": "workable",
                "board_token": slug,
                "slug": slug,
                "source_platform": "chsr",
                "chsr_url": careers_url,
            }
    if ats:
        return {
            "company_name": name,
            "career_page_url": careers_url,
            "website": "",
            "domain_hint": domain_from(careers_url),
            "ats_type": ats,
            "source_platform": "chsr",
            "chsr_url": careers_url,
        }
    # company-domain careers page -> probe greenhouse/lever/ashby for a real board
    from discover_slugs import candidates, PROBES, BOARD_URL  # noqa: E402
    cands = [c for c in candidates(name)[:4] if c not in GENERIC_SLUGS]
    for ats_id in ATS_ORDER:
        probe = PROBES[ats_id]
        for slug in cands:
            try:
                n = probe(slug)
            except Exception:
                n = None
            if n is not None:  # board exists
                return {
                    "company_name": name,
                    "career_page_url": BOARD_URL[ats_id](slug),
                    "website": "",
                    "domain_hint": domain_from(careers_url),
                    "ats_type": ats_id,
                    "board_token": slug,
                    "slug": slug,
                    "jobs_found": n,
                    "source_platform": "chsr",
                    "chsr_url": careers_url,
                }
    # no ATS board found -> track as unknown with the careers page
    return {
        "company_name": name,
        "career_page_url": careers_url,
        "website": "",
        "domain_hint": domain_from(careers_url),
        "ats_type": "unknown",
        "source_platform": "chsr",
        "chsr_url": careers_url,
    }


def main():
    print("[chsr] fetching companies-hiring-security-remote README...")
    md = fetch_readme()
    rows = parse_table(md)
    print(f"[chsr] parsed {len(rows)} companies from the list")

    skip = existing_names(os.path.join(DATA, "companies.json"))
    targets = [(n, u) for (n, u) in rows if _norm(n) not in skip]
    print(f"[chsr] {len(targets)} NEW to probe (skipped {len(rows) - len(targets)} already listed)")

    records: list[dict] = []
    by_ats: dict[str, int] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futs = {pool.submit(probe_one, n, u): n for (n, u) in targets}
        for fut in concurrent.futures.as_completed(futs):
            try:
                rec = fut.result()
            except Exception as e:
                print(f"  [err] {futs[fut]}: {e}")
                continue
            records.append(rec)
            a = rec.get("ats_type", "unknown")
            by_ats[a] = by_ats.get(a, 0) + 1
    for a, n in sorted(by_ats.items(), key=lambda kv: -kv[1]):
        print(f"  {a:<16} {n}")

    # merge idempotently with any prior agent12_chsr records
    existing: list[dict] = []
    if os.path.exists(RAW_OUT):
        try:
            existing = json.load(open(RAW_OUT, encoding="utf-8"))
        except Exception:
            existing = []
    seen = {_norm(r.get("company_name", "")) for r in existing}
    merged = list(existing)
    added = 0
    for rec in records:
        k = _norm(rec.get("company_name", ""))
        if k and k not in seen:
            seen.add(k)
            merged.append(rec)
            added += 1
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    with open(RAW_OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"[chsr] merged {added} new + {len(existing)} existing -> {len(merged)} records -> {RAW_OUT}")
    print("[chsr] next: run scripts/consolidate.py to merge into companies.json")
    return merged


if __name__ == "__main__":
    sys.exit(0 if main() is not None else 1)