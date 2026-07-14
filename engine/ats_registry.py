"""Shared ATS host-pattern registry.

Single source of truth for "which ATS does this URL/host belong to?" Used by:
  - app/backend /api/detect (host-pattern fallback when the company isn't in
    companies.json)
  - scripts/discover_companies.py (infer ATS from a career-page URL)
  - anything else that needs to label a URL by ATS

Keep in sync with the extension's HOST_PATTERNS (extension/content.js) — the
patterns here are the app-side mirror.
"""
from __future__ import annotations

import re

# (ats_id, regex tested against the URL hostname)
ATS_HOST_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:^|\.)(?:boards|job-boards)\.greenhouse\.io$")),
    ("lever", re.compile(r"(?:^|\.)jobs\.lever\.co$")),
    ("ashby", re.compile(r"(?:^|\.)?(?:jobs|app)\.ashbyhq\.com$")),
    ("workable", re.compile(r"(?:^|\.)apply\.workable\.com$")),
    ("smartrecruiters", re.compile(r"(?:^|\.)?(?:careers|jobs)\.smartrecruiters\.com$")),
    ("personio", re.compile(r"\.jobs\.personio\.com$")),
    ("rippling", re.compile(r"(?:^|\.)ats\.rippling\.com$")),
    ("teamtailor", re.compile(r"\.careers\.teamtailor\.com$")),
    ("breezyhr", re.compile(r"\.breezy\.hr$")),
    ("onlyfy", re.compile(r"\.onlyfy\.jobs$")),
    ("mailto", re.compile(r"\.(?:mailto|mail-to)\.jobs$")),  # rare; mostly a logical ATS
    ("workday", re.compile(r"\.myworkdayjobs\.com$")),
    ("bamboohr", re.compile(r"(?:^|\.)bamboohr\.com$")),
    ("careerspage", re.compile(r"(?:^|\.)careers-page\.com$")),
    # new batch — public apply forms, autofillable via the extension's generic
    # heuristic filler; enumerators TBD per-ATS (Workday is enumerated).
    ("recruitee", re.compile(r"(?:^|\.)(?:recruitee|careers\.recruitee)\.com$")),
    ("comeet", re.compile(r"(?:^|\.)comeet\.(com|co)$")),
    ("jobvite", re.compile(r"(?:^|\.)jobvite\.com$")),
    ("jazzhr", re.compile(r"(?:^|\.)(?:resumator|jazz)\.(com|co)$")),
    ("pinpoint", re.compile(r"(?:^|\.)pinpointhq\.com$")),
    ("trinethire", re.compile(r"(?:^|\.)trinethire\.com$")),
    ("keka", re.compile(r"\.keka\.com$")),
    ("applytojob", re.compile(r"(?:^|\.)applytojob\.com$")),
    ("cats", re.compile(r"(?:^|\.)catsone\.com$")),
    ("hireology", re.compile(r"(?:^|\.)hireology\.com$")),
    ("niceboard", re.compile(r"(?:^|\.)niceboard\.(com|co)$")),
    ("freshteam", re.compile(r"(?:^|\.)freshteam\.com$")),
    ("attrax", re.compile(r"\.jobs$")),  # wise.jobs etc. — weak, last-resort
]


def detect_ats_by_host(url: str) -> str | None:
    """Return the ATS id for a URL by hostname, or None."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    for ats, re_ in ATS_HOST_PATTERNS:
        if re_.search(host):
            return ats
    return None