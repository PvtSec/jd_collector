from __future__ import annotations

import concurrent.futures
import time
from typing import Literal

import re
import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA}
TIMEOUT = 8

Verdict = Literal["live", "dead", "unknown"]

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
    if not html:
        return False
    m = TITLE_RE.search(html)
    title = m.group(1).strip() if m else ""
    if title and TITLE_NOT_FOUND.search(title):
        return True
    snippet = _body_snippet(html)
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
        if _looks_dead_200(html):
            return "dead"
        return "live"
    if 500 <= code < 600:
        return "unknown"
    return "unknown"


def prune_dead_unknown(db, *, ats_whitelist: list[str] | None = None,
                       concurrency: int = 8, limit: int = 500) -> dict:
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


def prune_dead_jobs(db, *, ats_whitelist: list[str] | None = None,
                    concurrency: int = 8, limit: int = 300,
                    matched_only: bool = True) -> dict:
    """Close open jobs whose own URL no longer exists (HTTP 404/410 or soft
    not-found). Catch-all for rows the board-reaper can't see — orphaned by
    company/job_id drift. Default: matched+open only, oldest last_check first;
    matched_only=False also sweeps the non-matched tail. Never touches applied."""
    now = time.time()
    where = "closed=0 AND applied=0 AND url LIKE 'http%'"
    if matched_only:
        where += " AND matched=1"
    if ats_whitelist:
        ph = ",".join("?" * len(ats_whitelist))
        sql = (f"SELECT id, url FROM jobs WHERE {where} "
               f"AND ats IN ({ph}) ORDER BY last_check ASC LIMIT ?")
        params = (*ats_whitelist, limit)
    else:
        sql = (f"SELECT id, url FROM jobs WHERE {where} "
               f"ORDER BY last_check ASC LIMIT ?")
        params = (limit,)
    with db._lock:
        rows = [dict(r) for r in db._conn.execute(sql, params).fetchall()]
    if not rows:
        return {"checked": 0, "dead": 0, "closed": 0, "live": 0, "unknown": 0}

    dead_ids: list[int] = []
    keep_ids: list[int] = []
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
            else:
                if verdict == "live":
                    live += 1
                else:
                    unknown += 1
                keep_ids.append(r["id"])

    closed = 0
    with db._lock:
        if dead_ids:
            cur = db._conn.execute(
                f"UPDATE jobs SET closed=1, closed_at=?, miss_count=miss_count+1 "
                f"WHERE id IN ({','.join('?' * len(dead_ids))}) AND applied=0",
                (now, *dead_ids),
            )
            closed = cur.rowcount
        if keep_ids:
            db._conn.execute(
                f"UPDATE jobs SET last_check=? "
                f"WHERE id IN ({','.join('?' * len(keep_ids))})",
                (now, *keep_ids),
            )
        db._conn.commit()
    return {"checked": len(rows), "dead": len(dead_ids), "closed": closed,
            "live": live, "unknown": unknown}