from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
from urllib.parse import urlparse

import requests

# import the proven slug machinery from discover_slugs
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from discover_slugs import candidates, PROBES, BOARD_URL  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
RAW_OUT = os.path.join(DATA, "raw", "agent8_seedprobe.json")
SEED_FILE = os.path.join(DATA, "seed_companies.txt")
UA = "Mozilla/5.0 (job-auto company-discovery; research)"
ATS_ORDER = ["greenhouse", "lever", "ashby"]  # probe order per name

# A small curated seed of notable tech companies NOT guaranteed to be unicorns
# (security / devops / infra / AI / European startups etc.), to widen coverage
# beyond the Wikipedia unicorn list.
CURATED = [
    "GitLab", "Cloudflare", "Datadog", "Snyk", "Wiz", "Aqua Security", "Orca Security",
    "Lacework", "CrowdStrike", "SentinelOne", "Tenable", "Rapid7", "Graylog", "Grafana Labs",
    "HashiCorp", "Pulumi", "Spacelift", "Snyk", "Sysdig", "Aqua", "Upbound", "Civo",
    "Fly.io", "Render", "Railway", "Plural", "Northflank", "Koyeb", " shuttle",
    "Modal", "Anyscale", "Replicate", "Hugging Face", "Cohere", "Anthropic", "OpenAI",
    "Mistral AI", "H", "Poolside", "Magic.dev", "Cursor", "Anysphere", "Devin",
    "PostHog", "Plausible", "Fathom", "Sentry", "Rollbar", "Loggly", "Papertrail",
    "Vercel", "Netlify", "Val Town", "Deno", "Cloudflare", "Bun", "Astro",
    "Supabase", "Appwrite", "Nhost", "Xata", "Convex", "PlanetScale", "Neon",
    "Tigris", "Turso", "Upstash", "Momento", "Aiven", "Astra DB", "ScyllaDB",
    "SingleStore", "ClickHouse", "Tinybird", "Materialize", "RisingWave", "Decodable",
    "Meilisearch", "Typesense", "Qdrant", "Weaviate", "Pinecone", "Chroma",
    "Tailscale", "Twingate", "Cloudflare", "Ngrok", "Ockam", "Teleport",
    "Fly Machines", "Zitadel", "Ory", "Clerk", "Stytch", "WorkOS", "Auth0",
    "Okta", "Frontegg", "BoxyHQ", "Permify", "Oso", "Cerbos", "Authzen",
    "Snyk", "Spearbit", "OpenZeppelin", "Trail of Bits", "CertiK", "Quantstamp",
    "Paradigm", "Flashbots", "CyberConnect", "Dune", "Nansen", "Arkham",
    "BastionZero", "Akeyless", "Teleport", "Infisical", "Doppler", "EnvKey",
    "1Password", "Bitwarden", "ProtonMail", "Tutanota", "Threema", "Wire",
    "ProtonVPN", "Mullvad", "IVPN", "DefGuard", "Firezone",
    "Resend", "Loops", "Nylas", "Postmark", "Mailgun", "SendGrid", "Plunk",
    "Cal.com", "Calendly", "SavvyCal", "Vimcal", "Morgen", "Reclaim",
    "Plane", "Linear", "Height", "Shortcut", "GitHub", "Atlassian",
    "Sprinto", "Drata", "Vanta", "Secureframe", "Anecdotes", "Apideck",
    "Baseten", "Bento", "Hex", "Count", "Briefer", "Evidence", "Pivot",
    "ElevenLabs", "Resemble", "PlayHT", "WellSaid", "Descript", "AssemblyAI",
    "Deepgram", "Whisper", "Cartesia", "Sun", "Suno",
    # --- cybersecurity-focused companies (modern security startups/scale-ups +
    #     established vendors) added to widen security-board discovery. Probing
    #     only hits greenhouse/lever/ashby, so big vendors on Workday/custom
    #     sites simply won't match — harmless (deduped, skipped if listed). ---
    "Cado Security", "Vectra AI", "ExtraHop", "Fidelis Cybersecurity",
    "Recorded Future", "SecurityScorecard", "BitSight", "Mandiant",
    "Arctic Wolf", "Huntress", "ReliaQuest", "Expel", "Blumira", "SpearTip",
    "Blackpanda", "Kroll", "GuidePoint Security", "Pondurance", "BlueVoyant",
    "Deepwatch", "Optiv", "Presidio", "Secureworks", "Trustwave", "NCC Group",
    "Coalfire", "Schellman", "A-LIGN", "Bishop Fox", "Synack", "Cobalt",
    "Pentera", "Imperva", "Radware", "Fastly", "Sumo Logic", "LogRhythm",
    "Exabeam", "Securonix", "Qualys", "Ivanti", "SonicWall", "Delinea",
    "Semperis", "CyberArk", "BeyondTrust", "Varonis", "Mimecast", "Proofpoint",
    "Zscaler", "Splunk", "Elastic", "Darktrace", "Aikido Security", "Cycode",
    "Socket", "Pixee", "DryRun Security", "Corgea", "Apiiro", "Legit Security",
    "Kontext", "Sweet Security", "Escape", "Sygnia", "Oligo Security",
    "Apono", "Astrix Security", "Spera Security", "DoControl", "Sentnl",
    "HackerOne", "Bugcrowd", "Intigriti", "YesWeHack", "Synopsys",
    "Trellix", "Fortinet", "Palo Alto Networks", "Check Point",
]


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def existing_names(path: str) -> set[str]:
    try:
        comps = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return {_norm(c.get("company_name", "")) for c in comps}


def _names_from_wikitables(html: str, name_headers=("company", "name", "service", "product", "organization", "firm")) -> list[str]:
    out = []
    META = ("list of", "startup company", "unicorn", "category:", "wikipedia:", "template:")
    for tbl in re.findall(r'<table[^>]*class="[^"]*wikitable[^"]*"[^>]*>(.*?)</table>', html, re.S):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S)
        idx = None
        for row in rows:
            ths = re.findall(r"<th[^>]*>(.*?)</th>", row, re.S)
            if not ths:
                continue
            for i, th in enumerate(ths):
                t = re.sub(r"<[^>]+>", "", th).lower()
                if any(h in t for h in name_headers):
                    idx = i; break
            if idx is not None:
                break
        if idx is None:
            continue
        for row in rows:
            cells = re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", row, re.S)
            if len(cells) <= idx:
                continue
            cell = cells[idx]
            m = re.search(r'<a [^>]*?title="([^"]+)"', cell)
            name = (m.group(1) if m else re.sub(r"<[^>]+>", "", cell)).strip()
            name = re.sub(r"\s+", " ", name or "").strip()
            name = re.sub(r"\s*\([^)]*\)", "", name).strip()
            low = name.lower()
            if (not name or len(name) > 60 or name[0].isdigit()
                    or low in ("company", "name", "firm")
                    or any(x in low for x in META)):
                continue
            out.append(name)
    return out


def _names_from_bullets(html: str) -> list[str]:
    out = []
    META = ("list of", "category:", "wikipedia:", "template:", "company", "startup")
    for li in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S):
        m = re.search(r'<a [^>]*?title="([^"]+)"', li)
        if not m:
            continue
        name = m.group(1).strip()
        name = re.sub(r"\s*\([^)]*\)", "", name).strip()
        low = name.lower()
        if (not name or len(name) > 60 or name[0].isdigit()
                or any(x in low for x in META)):
            continue
        out.append(name)
    return out


def fetch_wikipedia_page_names(page: str) -> list[str]:
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "parse", "page": page, "format": "json",
                    "prop": "text", "redirects": 1},
            headers={"User-Agent": UA}, timeout=25,
        )
        html = (r.json().get("parse", {}) or {}).get("text", {}).get("*", "") or ""
    except Exception as e:
        print(f"[wiki] {page}: fetch failed: {e}")
        return []
    names = _names_from_wikitables(html) + _names_from_bullets(html)
    seen, dedup = set(), []
    for n in names:
        k = _norm(n)
        if k and k not in seen:
            seen.add(k); dedup.append(n)
    return dedup


def fetch_wikipedia_category(category: str, limit: int = 500) -> list[str]:
    out: list[str] = []
    cont = {}
    while len(out) < limit:
        try:
            r = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "list": "categorymembers",
                        "cmtitle": category, "cmlimit": min(500, limit - len(out)),
                        "cmtype": "page", "format": "json", **cont},
                headers={"User-Agent": UA}, timeout=25,
            )
            d = r.json()
        except Exception as e:
            print(f"[wiki-cat] {category}: fetch failed: {e}")
            break
        members = d.get("query", {}).get("categorymembers", []) or []
        for m in members:
            t = m.get("title", "")
            if not t or t.startswith("List of") or t.startswith("Category:"):
                continue
            # strip Wikipedia disambiguation parentheticals: "Clio (software company)" -> "Clio"
            t = re.sub(r"\s*\([^)]*\)", "", t).strip()
            low = t.lower()
            if t and low not in ("company", "name", "firm", "organization"):
                out.append(t)
        if "continue" not in d:
            break
        cont = d["continue"]; cont.update(d.get("query-continue", {}).get("categorymembers", {}))
    return out


# Wikipedia list pages that yield company names (verified to return data).
WIKI_LISTS = [
    "List of unicorn startup companies",
    "List of artificial intelligence companies",
    "List of social networking services",
    "List of video game companies",
    "List of computer security companies",   # direct cybersecurity relevance
    # --- country "List of companies" pages (broaden APAC + EU coverage) ---
    "List of companies of Singapore",
    "List of companies of India",
    "List of companies of Japan",
    "List of companies of Germany",
    "List of companies of South Korea",
    "List of companies of Israel",
    "List of largest Australian companies",   # AU has no "List of companies of Australia"
    "List of Indian IT companies",
    "List of public listed software companies of India",
]

# Wikipedia categories — high-yield article-title pulls. Cybersecurity is
# directly relevant to the candidate's pentest target.
WIKI_CATEGORIES = [
    "Category:Software companies of the United States",
    "Category:Software companies of the United Kingdom",
    "Category:Software companies of India",
    "Category:Artificial intelligence companies",
    "Category:Cloud computing providers",
    "Category:Cybersecurity companies",
    "Category:Information security companies",
    "Category:Network security companies",
    "Category:Firewall companies",
    "Category:Antivirus software companies",
    # --- country-specific software / tech / cybersecurity categories ---
    "Category:Software companies of Singapore",
    "Category:Technology companies of Singapore",
    "Category:Software companies of Australia",
    "Category:Technology companies of Australia",
    "Category:Software companies of Germany",
    "Category:Software companies of Japan",
    "Category:Software companies of South Korea",
    "Category:Software companies of the Netherlands",
    "Category:Software companies of Ireland",
    "Category:Cybersecurity companies of Singapore",
    "Category:Cybersecurity companies of Israel",
]


def fetch_wikipedia_companies() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for page in WIKI_LISTS:
        names = fetch_wikipedia_page_names(page)
        for n in names:
            out.append((n, ""))
        print(f"[wiki-list] {page}: {len(names)} names")
    for cat in WIKI_CATEGORIES:
        names = fetch_wikipedia_category(cat)
        for n in names:
            out.append((n, ""))
        print(f"[wiki-cat] {cat}: {len(names)} names")
    seen = set()
    deduped = []
    for n, w in out:
        k = _norm(n)
        if k and k not in seen:
            seen.add(k); deduped.append((n, w))
    print(f"[wiki] {len(deduped)} unique company names")
    return deduped


def load_seed_file() -> list[tuple[str, str]]:
    if not os.path.exists(SEED_FILE):
        return []
    out = []
    for line in open(SEED_FILE, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append((line, ""))
    print(f"[seedfile] {len(out)} names from {SEED_FILE}")
    return out


def domain_from(url: str) -> str:
    try:
        h = urlparse(url).hostname or ""
        return h.replace("www.", "")
    except Exception:
        return ""


GENERIC_SLUGS = {"company", "inc", "labs", "lab", "ai", "app", "the", "group",
                 "tech", "technologies", "technology", "systems", "global",
                 "digital", "data", "cloud", "software", "solutions", "services",
                 "holdings", "corp", "corporation", "limited", "ltd"}


def probe_one(name: str, website: str) -> dict | None:
    cands = [c for c in candidates(name)[:4] if c not in GENERIC_SLUGS]
    for ats in ATS_ORDER:
        probe = PROBES[ats]
        for slug in cands:
            n = probe(slug)
            if n is not None:  # hit (board exists; n = job count)
                return {
                    "company_name": name,
                    "career_page_url": BOARD_URL[ats](slug),
                    "website": website or "",
                    "domain_hint": domain_from(website) if website else "",
                    "ats_type": ats,
                    "source_platform": "seedprobe",
                }
    return None


def main():
    print("[seedprobe] gathering seed company names...")
    seeds = fetch_wikipedia_companies()
    seeds += [(n, "") for n in CURATED]
    seeds += load_seed_file()

    skip = existing_names(os.path.join(DATA, "companies.json"))
    # dedupe seeds by normalized name, drop ones already in companies.json
    seen = set(skip)
    targets: list[tuple[str, str]] = []
    for name, web in seeds:
        k = _norm(name)
        if k and k not in seen:
            seen.add(k); targets.append((name, web))
    print(f"[seedprobe] {len(targets)} NEW names to probe (skipped {len(skip)} already listed)")

    records: list[dict] = []
    hits = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futs = {pool.submit(probe_one, n, w): n for (n, w) in targets}
        for fut in concurrent.futures.as_completed(futs):
            try:
                rec = fut.result()
            except Exception:
                rec = None
            if rec:
                hits += 1
                records.append(rec)
                print(f"  HIT: {rec['company_name']} -> {rec['ats_type']} {rec['career_page_url']}")
    print(f"[seedprobe] {hits} ATS boards found across {len(targets)} probes")

    # MERGE with existing agent8 records (don't overwrite — prior runs' hits
    # must survive so consolidate keeps them; re-runnable/idempotent by name).
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
            seen.add(k); merged.append(rec); added += 1
    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    with open(RAW_OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"[seedprobe] merged {added} new + {len(existing)} existing -> {len(merged)} records -> {RAW_OUT}")
    print("[seedprobe] next: run scripts/consolidate.py to merge into companies.json")
    return merged


if __name__ == "__main__":
    main()