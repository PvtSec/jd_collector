#!/usr/bin/env python3
"""cleanup_discovery_db.py — data-quality cleanup of discovery.db.

Run AFTER scripts/validate_boards.py (which marks dead boards reliable=0).
Three cleanups:
  1. Aggregator/portal URLs (not employer endpoints): himalayas.app, wellfound.com,
     angel.co -> DELETE (they're job-portal profile pages, not careers endpoints).
     ycombinator.com is KEPT (real YC startup job pages).
  2. Junk/test slugs (pure-digit >=6 chars, consonant-only gibberish >=7 chars,
     or repeated-char slugs) -> DELETE.
  3. Duplicates: same (ats_type, board-slug) under multiple names. Keep the
     "best" name (a real name beats a slug-derived placeholder), DELETE the rest.

All deletes are from discovery.db; re-run export_discovery_db.py + consolidate.py
afterward to bake the cleaned set into companies.json. Idempotent.
"""
from __future__ import annotations
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "discovery" / "discovery.db"

AGG_HOSTS = ("himalayas.app", "wellfound.com", "angel.co", "otta.com")


def slug_for(ats: str, url: str) -> str | None:
    u = (url or "").rstrip("/").lower()
    pats = {
        "greenhouse": r"greenhouse\.io/([^/?#]+)",
        "lever": r"jobs\.lever\.co/([^/?#]+)",
        "ashby": r"jobs\.ashbyhq\.com/([^/?#]+)",
        "workable": r"apply\.workable\.com/([^/?#]+)",
        "smartrecruiters": r"(?:jobs|careers)\.smartrecruiters\.com/([^/?#]+)",
        "rippling": r"ats\.rippling\.com/([^/?#]+)",
        "teamtailor": r"https?://([^./]+)\.teamtailor\.com",
        "personio": r"https?://([^./]+)\.jobs\.personio\.com",
        "breezyhr": r"https?://([^./]+)\.breezy\.hr",
        "bamboohr": r"https?://([^./]+)\.bamboohr\.com",
        "pinpoint": r"https?://([^./]+)\.pinpointhq\.com",
        # workday: dedup key is the TENANT (subdomain before .wd<cluster>),
        # NOT the site path — many unrelated employers share site names like
        # /careers or /external, so keying on the path would collapse distinct
        # companies. Tenant subdomain is unique per employer.
        "workday": r"https?://([^./]+)\.wd",
    }
    m = re.search(pats[ats], u) if ats in pats else None
    return m.group(1) if m else None


def is_junk_slug(slug: str) -> bool:
    s = slug.lower()
    if re.fullmatch(r"\d{6,}", s):  # long pure-digit (test boards)
        return True
    if re.fullmatch(r"(.)\1{4,}", s):  # repeated char (yyyyyyyyy)
        return True
    if len(s) >= 7 and not re.search(r"[aeiou]", s) and re.search(r"\d", s):
        # consonant+digit gibberish (f1sch3rh0m3s, sprchrgr, 1456754456yhgbhfg)
        return True
    return False


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def main() -> int:
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    # 1. aggregator URLs
    agg = 0
    for h in AGG_HOSTS:
        n = cur.execute("DELETE FROM companies WHERE career_page_url LIKE ?",
                         (f"%{h}%",)).rowcount
        agg += n
    print(f"1. deleted aggregator-URL rows: {agg}")

    # 2. junk slugs (only for slug-based ATS)
    junk = 0
    for ats in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters",
                "rippling", "teamtailor", "personio", "breezyhr", "bamboohr", "pinpoint"):
        rows = cur.execute(
            "SELECT norm_key, career_page_url FROM companies WHERE ats_type=?",
            (ats,)).fetchall()
        for nkey, url in rows:
            s = slug_for(ats, url)
            if s and is_junk_slug(s):
                cur.execute("DELETE FROM companies WHERE norm_key=?", (nkey,))
                junk += 1
    print(f"2. deleted junk-slug rows: {junk}")

    # 3. duplicates by (ats, slug)
    kept = deleted = 0
    for ats in ("greenhouse", "lever", "ashby", "workable", "smartrecruiters",
                "rippling", "teamtailor", "personio", "breezyhr", "bamboohr",
                "pinpoint", "workday"):
        rows = cur.execute(
            "SELECT norm_key, name, career_page_url FROM companies WHERE ats_type=?",
            (ats,)).fetchall()
        groups: dict[str, list] = {}
        for nkey, name, url in rows:
            s = slug_for(ats, url)
            if not s:
                continue
            groups.setdefault(s, []).append((nkey, name))
        for slug, members in groups.items():
            if len(members) <= 1:
                continue
            # keeper = the name least like the slug (real name beats placeholder)
            def score(m):
                name = m[1] or ""
                # slug-derived placeholder normalizes to the slug; real names differ
                return 0 if norm(name) == norm(slug) else 1
            members.sort(key=score, reverse=True)
            keeper = members[0][0]
            kept += 1
            for nkey, _ in members[1:]:
                cur.execute("DELETE FROM companies WHERE norm_key=?", (nkey,))
                deleted += 1
    print(f"3. dedup: kept {kept} boards, deleted {deleted} duplicate-name rows")

    conn.commit()
    rc = conn.execute("SELECT COUNT(*) FROM companies WHERE reliable=1").fetchone()[0]
    tot = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    conn.close()
    print(f"\nreliable_count now {rc}/50000  (total_unique {tot})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())