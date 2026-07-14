"""URL liveness checks — drop genuinely dead links, keep valid ones.

The dashboard's real-ATS rows come from the boards' own APIs and are live by
construction, so we never validate those. The only rows that can 404 are the
non-ATS (``unknown``/``custom``) third-party-scraped career-page links carried
by the topstartups seed. This module checks those and deletes only the ones
that return a definitive 404/410 — transient errors (5xx, timeouts, HEAD-405)
are treated as "unknown" and left alone, so flaky-but-valid pages aren't dropped.
"""
from __future__ import annotations

import concurrent.futures
from typing import Literal

import re
import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA}
TIMEOUT = 8

Verdict = Literal["live", "dead", "unknown"]

# SPA career sites (e.g. HashiCorp) return HTTP 200 with a client-rendered
# "Page Not Found" body. Detect those via title/body markers so we still drop
# them. Checked against the <title> and the first ~32 KB of the body.
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
BODY_NOT_FOUND = re.compile(
    r"(page not found|404\s*[-–—]?\s*(not found|error)|"
    r"we couldn'?t find|could not find (that |the )?page|"
    r"this page (doesn'?t|does not) exist|page (doesn'?t|does not) exist|"
    r"no longer available|has been removed|"
    r"the page you (were )?looking for)",
    re.I,
)
TITLE_NOT_FOUND = re.compile(r"(not found|404|doesn'?t exist|does not exist|no longer)", re.I)


def _body_snippet(text: str, limit: int = 32768) -> str:
    return text[:limit] if text else ""


def _looks_dead_200(html: str) -> bool:
    """A 200 response whose body indicates a not-found page (SPA 404)."""
    if not html:
        return False
    m = TITLE_RE.search(html)
    title = m.group(1).strip() if m else ""
    if title and TITLE_NOT_FOUND.search(title):
        return True
    snippet = _body_snippet(html)
    # require a strong phrase in the body (title already handled above)
    return bool(BODY_NOT_FOUND.search(snippet))


def check_url(url: str, timeout: int = TIMEOUT) -> Verdict:
    if not url or not url.startswith("http"):
        return "dead"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        code = r.status_code
        html = r.text if code < 400 else ""
    except requests.RequestException:
        return "unknown"
    if code in (404, 410):
        return "dead"
    if 200 <= code < 400:
        # SPA career sites may 200 with a "Page Not Found" body — detect it.
        if _looks_dead_200(html):
            return "dead"
        return "live"
    if 500 <= code < 600:
        return "unknown"
    # 4xx other than 404/410 (403 bot-block, 401 auth, 405 method) — ambiguous
    return "unknown"


def prune_dead_unknown(db, *, ats_whitelist: list[str] | None = None,
                       concurrency: int = 8, limit: int = 500) -> dict:
    """Liveness-check non-ATS rows and delete the definitively dead ones.

    ``ats_whitelist`` is the set of real ATS whose URLs are trusted (never
    checked). Rows whose ``ats`` is not in it are checked. Returns counts.
    """
    with db._lock:
        rows = db._conn.execute(
            "SELECT id, url FROM jobs WHERE ats NOT IN "
            f"({','.join('?' * len(ats_whitelist))}) LIMIT ?"
            if ats_whitelist else
            "SELECT id, url FROM jobs LIMIT ?",
            (*(ats_whitelist or []), limit),
        ).fetchall()
    rows = [dict(r) for r in rows]
    if not rows:
        return {"checked": 0, "dead": 0, "deleted": 0, "live": 0, "unknown": 0}

    dead_ids: list[int] = []
    live = unknown = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(check_url, r["url"]): r for r in rows}
        for fut in concurrent.futures.as_completed(futures):
            r = futures[fut]
            try:
                verdict = fut.result()
            except Exception:
                verdict = "unknown"
            if verdict == "dead":
                dead_ids.append(r["id"])
            elif verdict == "live":
                live += 1
            else:
                unknown += 1

    deleted = 0
    if dead_ids:
        with db._lock:
            cur = db._conn.execute(
                f"DELETE FROM jobs WHERE id IN ({','.join('?' * len(dead_ids))})",
                dead_ids,
            )
            db._conn.commit()
            deleted = cur.rowcount
    return {"checked": len(rows), "dead": len(dead_ids), "deleted": deleted,
            "live": live, "unknown": unknown}