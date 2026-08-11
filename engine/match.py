from __future__ import annotations
from .config import Target
from .boards import Job


def _norm(s: str) -> str:
    return (s or "").lower()


def matches(job: Job, target: Target) -> tuple[bool, list[str]]:
    title = _norm(job.title)
    loc = _norm(job.location)
    wt = _norm(job.work_type)
    reasons: list[str] = []

    role_hit = (not target.role_keywords) or any(k in title for k in target.role_keywords)
    if target.role_keywords and not role_hit:
        reasons.append("title not in target roles")
    SENIORITY_PREFIXES = {"senior", "sr", "sr."}
    for k in target.exclude_keywords:
        if k in title:
            if role_hit and k in SENIORITY_PREFIXES:
                continue
            reasons.append("title matched exclude keyword")
            break

    US_ONLY = ("united states", " us ", " us-", "us -", "- us", " usa ", "usa)",
               "u.s.", "u.s. ", "america", "new york", "san francisco", "boston",
               "seattle", "chicago", "austin", "denver", "washington dc",
               "los angeles", "toronto", "canada", "bay area", "west coast")
    US_CA_BARE = {"us", "usa", "u.s.", "u.s.a.", "united states of america",
                  "america", "canada", "ca", "united states", "north america"}
    pref = target.location_pref or []
    GEO = [p for p in pref if p not in ("remote", "worldwide", "global")]
    if wt == "remote":
        loc_token = loc.strip().rstrip(".")
        is_us_ca = (any(u in loc for u in US_ONLY)
                    or loc_token in US_CA_BARE
                    or any(loc.endswith(" " + t) or loc.startswith(t + " ") for t in US_CA_BARE))
        if is_us_ca and not any(g in loc for g in GEO):
            reasons.append("remote but US/CA-only")
    elif wt in ("hybrid", "onsite", ""):
        if not loc:
            # Some ATS (teamtailor, workday, personio) under-report both
            # work_type and location even for valid remote/global postings.
            # Only reject when we *know* it's non-remote (hybrid/onsite); when
            # work_type is also unknown, surface the title-matched role for
            # manual review instead of dropping it on missing metadata.
            if wt:
                reasons.append("no location info for non-remote role")
        elif not any(p in loc for p in pref):
            reasons.append(f"location '{job.location}' not in preferred list")
    return (not reasons, reasons)