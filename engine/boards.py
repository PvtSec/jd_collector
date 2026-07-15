"""Per-ATS job-board clients (read-only enumeration).

Each client yields normalized `Job` objects from a company's public board.

Status:
- greenhouse: VERIFIED against live API (boards-api.greenhouse.io).
- lever:      VERIFIED against live API (api.lever.co).
- ashby:      STUB — public POST endpoint returns 401; awaiting schema research
              for the correct enumeration path (likely board-page scraping).
- workable:   STUB — v3 endpoint 404s; awaiting schema research.
- smartrecruiters: STUB — awaiting schema research.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html import unescape
from typing import Iterator
import requests

GH_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{token}?mode=json"


@dataclass
class Job:
    ats: str
    company: str
    job_id: str
    title: str
    location: str
    url: str                 # the application/hosted URL
    department: str = ""
    work_type: str = ""      # remote | hybrid | onsite | ""
    posted_at: str = ""      # ISO 8601 publish date ("" if unknown)
    raw: dict = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


class BoardError(Exception):
    pass


def _ms_to_iso(ms) -> str:
    """Epoch milliseconds (Lever createdAt) -> ISO 8601 UTC string, '' if unparseable."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def parse_posted(s: str):
    """Parse a posted_at string to a timezone-aware datetime, or None.

    Handles ISO 8601 with offset (replacing a trailing 'Z' for Py3.10),
    date-only 'YYYY-MM-DD', and empty input.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(s[:10])
        except ValueError:
            return None


def _get(url: str, *, timeout: int = 20, ua: str, retries: int = 2) -> requests.Response:
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": ua, "Accept": "application/json"})
            if r.status_code == 404:
                raise BoardError(f"404 board not found: {url}")
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.0)
    raise BoardError(f"request failed: {url} -> {last}")


# ---------------- Greenhouse ----------------

def list_greenhouse(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    r = _get(GH_API.format(token=token), timeout=timeout, ua=ua, retries=retries)
    data = r.json()
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") if isinstance(j.get("location"), dict) else ""
        depts = [d.get("name", "") for d in j.get("departments", []) if isinstance(d, dict)]
        yield Job(
            ats="greenhouse",
            company=company,
            job_id=str(j.get("id")),
            title=j.get("title", ""),
            location=loc,
            url=j.get("absolute_url", ""),
            department=" / ".join(depts),
            work_type=_infer_worktype(j.get("metadata")),
            posted_at=j.get("first_published", "") or "",
            raw=j,
        )


def _infer_worktype(metadata) -> str:
    """Greenhouse sometimes encodes Remote/Hybrid in metadata fields."""
    if not isinstance(metadata, list):
        return ""
    for m in metadata:
        if isinstance(m, dict):
            name = (m.get("name") or "").lower()
            val = (m.get("value") or "").lower() if isinstance(m.get("value"), str) else ""
            if "remote" in name or "remote" in val:
                return "remote"
            if "hybrid" in name or "hybrid" in val:
                return "hybrid"
    return ""


# ---------------- Lever ----------------

def list_lever(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    r = _get(LEVER_API.format(token=token), timeout=timeout, ua=ua, retries=retries)
    data = r.json()
    if not isinstance(data, list):
        raise BoardError(f"unexpected lever response for {token}: {type(data)}")
    for p in data:
        cats = p.get("categories", {}) or {}
        yield Job(
            ats="lever",
            company=company,
            job_id=p.get("id", ""),
            title=p.get("text", ""),
            location=cats.get("location", "") if isinstance(cats, dict) else "",
            url=p.get("applyUrl") or p.get("hostedUrl", ""),
            department=cats.get("team", "") if isinstance(cats, dict) else "",
            work_type=(p.get("workplaceType") or "").lower(),
            posted_at=_ms_to_iso(p.get("createdAt")),
            raw=p,
        )


# ---------------- Ashby ----------------
# Ashby's posting-api is authed (401). The public path is the SSR board page at
# jobs.ashbyhq.com/{slug}, whose HTML embeds `window.__appData` JSON containing
# jobBoard.jobPostings. Verified live (replit = 98 postings). See
# research/ats_schemas/ashby.md for the (browser-required) submit flow.

ASHBY_BOARD = "https://jobs.ashbyhq.com/{slug}"


def _extract_json_assignment(html: str, var: str) -> dict:
    """Balance-parse a `window.<var> = {...}` JS assignment from HTML."""
    import json as _json
    marker = f"window.{var} = "
    start = html.find(marker)
    if start == -1:
        raise BoardError(f"{var} not found in board HTML")
    i = html.index("{", start)
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(html)):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return _json.loads(html[i:j + 1])
    raise BoardError(f"unterminated {var} JSON")


def _find_key(o, key):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


def list_ashby(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    slug = token
    url = ASHBY_BOARD.format(slug=slug)
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": ua, "Accept": "text/html"})
            if r.status_code == 404:
                raise BoardError(f"404 ashby board not found: {url}")
            r.raise_for_status()
            data = _extract_json_assignment(r.text, "__appData")
            break
        except BoardError:
            raise
        except requests.RequestException as e:
            last = e
            time.sleep(1.0)
    else:
        raise BoardError(f"ashby request failed: {url} -> {last}")

    postings = _find_key(data, "jobPostings") or []
    if not postings and data.get("organization") is None:
        raise BoardError(
            f"ashby board '{slug}' returned no organization and 0 postings — "
            "slug may be wrong or the board is inactive/custom"
        )
    for p in postings:
        if not p.get("isListed", True):
            continue
        pid = p.get("id", "")
        yield Job(
            ats="ashby",
            company=company,
            job_id=pid,
            title=p.get("title", ""),
            location=p.get("locationName", "") or p.get("locationExternalName", ""),
            url=f"https://jobs.ashbyhq.com/{slug}/{pid}",
            department=p.get("departmentName", "") or p.get("departmentExternalName", ""),
            work_type=(p.get("workplaceType") or "").lower(),
            posted_at=p.get("publishedDate", "") or "",
            raw=p,
        )


# ---------------- Workable ----------------
# Workable is the one ATS with NO captcha — full HTTP auto-apply is possible.
# Enumeration: POST /api/v3/accounts/{token}/jobs with body {} (GET 404s).
# See research/ats_schemas/workable.md for the form + submit flow.

WORKABLE_JOBS = "https://apply.workable.com/api/v3/accounts/{token}/jobs"


def _post_json(url: str, body: dict, *, timeout: int = 20, ua: str, retries: int = 2) -> requests.Response:
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.post(url, json=body, timeout=timeout,
                              headers={"User-Agent": ua, "Content-Type": "application/json",
                                       "x-workable-client": "job-auto/0.1"})
            if r.status_code == 404:
                raise BoardError(f"404 workable account not found: {url}")
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.0)
    raise BoardError(f"workable request failed: {url} -> {last}")


def list_workable(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    r = _post_json(WORKABLE_JOBS.format(token=token), {}, timeout=timeout, ua=ua, retries=retries)
    data = r.json()
    for j in data.get("results", []) or data.get("jobs", []):
        loc = j.get("location") or {}
        loc_str = ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
        dept = j.get("department") or []
        yield Job(
            ats="workable",
            company=company,
            job_id=j.get("shortcode") or str(j.get("id", "")),
            title=j.get("title", ""),
            location=loc_str,
            url=f"https://apply.workable.com/{token}/j/{j.get('shortcode','')}",
            department=" / ".join(dept) if isinstance(dept, list) else str(dept),
            work_type=(j.get("workplace") or ("remote" if j.get("remote") else "")).lower(),
            posted_at=j.get("published", "") or "",
            raw=j,
        )


# ---------------- SmartRecruiters ----------------
# Enumeration is open: GET /v1/companies/{slug}/postings. Public apply is
# Arkose FunCAPTCHA + Cloudflare gated (needs browser + solver); the captcha-free
# Customer API needs a per-company X-SmartToken the applicant won't have.
# See research/ats_schemas/smartrecruiters.md.

SR_POSTINGS = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"


def list_smartrecruiters(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    slug = token
    r = _get(SR_POSTINGS.format(slug=slug) + "?limit=500", timeout=timeout, ua=ua, retries=retries)
    data = r.json()
    for p in data.get("content", []) or []:
        loc = p.get("location") or {}
        loc_str = loc.get("fullLocation") or ", ".join(
            x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
        wt = "remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else "onsite")
        pid = p.get("id", "")
        yield Job(
            ats="smartrecruiters",
            company=company,
            job_id=pid,
            title=p.get("name", ""),
            location=loc_str,
            url=f"https://jobs.smartrecruiters.com/{slug}/{pid}",
            department=(p.get("department") or {}).get("label", "") if isinstance(p.get("department"), dict) else "",
            work_type=wt,
            posted_at=p.get("releasedDate", "") or "",
            raw=p,
        )


# ---------------- Personio ----------------
# Public XML feed at {company}.jobs.personio.de/xml — no auth required.
# See research/ats_schemas/personio.md for the (browser-required) submit flow.

PERSONIO_XML = "https://{company}.jobs.personio.de/xml?language=en"


def list_personio(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    import xml.etree.ElementTree as ET
    url = PERSONIO_XML.format(company=token)
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": ua, "Accept": "application/xml"})
            if r.status_code == 404:
                raise BoardError(f"404 personio board not found: {url}")
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last = e
            time.sleep(1.0)
    else:
        raise BoardError(f"personio request failed: {url} -> {last}")

    root = ET.fromstring(r.text)
    for pos in root.findall("position"):
        pid = (pos.findtext("id") or "").strip()
        title = (pos.findtext("name") or "").strip()
        office = (pos.findtext("office") or "").strip()
        dept = (pos.findtext("department") or "").strip()
        created = (pos.findtext("createdAt") or "").strip()
        yield Job(
            ats="personio",
            company=company,
            job_id=pid,
            title=title,
            location=office,
            url=f"https://{token}.jobs.personio.com/job/{pid}?language=en",
            department=dept,
            work_type="",
            posted_at=created,
            raw={"id": pid, "office": office, "department": dept, "createdAt": created},
        )


# ---------------- Rippling ----------------
# Public REST API at api.rippling.com/platform/api/ats/v1/board/{slug}/jobs — no auth.
# See research/ats_schemas/rippling.md for the (browser-required) submit flow.

RIPPLING_API = "https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs"


def list_rippling(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    url = RIPPLING_API.format(slug=token)
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": ua, "Accept": "application/json"})
            if r.status_code == 404:
                raise BoardError(f"404 rippling board not found: {url}")
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last = e
            time.sleep(1.0)
    else:
        raise BoardError(f"rippling request failed: {url} -> {last}")

    data = r.json()
    if not isinstance(data, list):
        raise BoardError(f"unexpected rippling response for {token}: {type(data)}")
    for j in data:
        jid = j.get("uuid") or j.get("id", "")
        loc = j.get("workLocation") or {}
        loc_str = loc.get("label", "") if isinstance(loc, dict) else str(loc)
        dept = j.get("department") or {}
        dept_str = dept.get("label", "") if isinstance(dept, dict) else str(dept)
        yield Job(
            ats="rippling",
            company=company,
            job_id=jid,
            title=j.get("name", ""),
            location=loc_str,
            url=j.get("url") or f"https://ats.rippling.com/{token}/jobs/{jid}/apply?step=application",
            department=dept_str,
            work_type="",
            posted_at="",
            raw=j,
        )


# ---------------- Teamtailor ----------------
# No public API without auth. Scrape the careers page HTML for embedded JSON
# (similar to Ashby's window.__appData pattern).
# See research/ats_schemas/teamtailor.md for the (browser-required) submit flow.

TEAMTAILOR_RSS = "https://{company}.teamtailor.com/jobs.rss"


def list_teamtailor(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    """Enumerate Teamtailor jobs via the public RSS feed.

    Teamtailor career pages are SPAs with no embedded JSON in the initial HTML.
    The RSS feed at {company}.teamtailor.com/jobs.rss is public and contains
    all published jobs with title, description, location, and link.
    """
    import xml.etree.ElementTree as ET
    url = TEAMTAILOR_RSS.format(company=token)
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": ua, "Accept": "application/rss+xml, application/xml"})
            if r.status_code == 404:
                raise BoardError(f"404 teamtailor board not found: {url}")
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last = e
            time.sleep(1.0)
    else:
        raise BoardError(f"teamtailor request failed: {url} -> {last}")

    root = ET.fromstring(r.text)
    ns = {"tt": "https://teamtailor.com/locations"}
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        # Extract job ID from link: https://yousign.teamtailor.com/jobs/123456-slug
        jid = ""
        if "/jobs/" in link:
            jid = link.rsplit("/jobs/", 1)[-1].split("?")[0]
        # Try to extract location from description HTML
        loc_str = ""
        import re as _re
        loc_m = _re.search(r'<span[^>]*class="[^"]*location[^"]*"[^>]*>(.*?)</span>', desc, _re.IGNORECASE)
        if loc_m:
            loc_str = _re.sub(r'<[^>]+>', '', loc_m.group(1)).strip()
        # Extract department if present
        dept_str = ""
        dept_m = _re.search(r'<span[^>]*class="[^"]*department[^"]*"[^>]*>(.*?)</span>', desc, _re.IGNORECASE)
        if dept_m:
            dept_str = _re.sub(r'<[^>]+>', '', dept_m.group(1)).strip()
        yield Job(
            ats="teamtailor",
            company=company,
            job_id=jid,
            title=title,
            location=loc_str,
            url=link,
            department=dept_str,
            work_type="",
            posted_at="",
            raw={"id": jid, "title": title, "link": link, "location": loc_str, "department": dept_str},
        )


# ---------------- HTML-scraping helpers (BreezyHR / Onlyfy) ----------------
# Both boards are SPAs but server-render their full job list into the initial
# HTML (for SEO), so a plain ``_get`` + regex is enough — no headless browser.
# A headless browser is in fact *less* reliable here: BreezyHR serves
# bot-challenge blanks to Chromium on repeated hits (see list_mailto note), and
# Onlyfy's classless Tailwind markup defeated the old DOM selectors' location
# lookup (it always came back empty). requests sidesteps both problems.

def _clean(s: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _breezy_worktype(raw: str) -> str:
    """Normalize a BreezyHR position-type label to a clean lowercase string.

    BreezyHR ships untranslated polyglot placeholders in the SSR HTML, e.g.
    ``%LABEL_POSITION_TYPE_FULL_TIME%`` (a client-side lib translates them).
    Reduce the placeholder to ``full time``; pass through any non-placeholder
    label (localized strings) lowercased; ``""`` for empty.
    """
    if not raw:
        return ""
    m = re.match(r"%LABEL_POSITION_TYPE_([A-Z_]+)%", raw.strip())
    if m:
        return m.group(1).replace("_", " ").lower()
    return raw.strip().lower()


# BreezyHR polyglot placeholders that surface in the location span (the
# client-side translator never runs on the SSR HTML, so they leak through).
_BREEZY_LOCATION_LABELS = {
    "%LABEL_MULTIPLE_LOCATIONS%": "Multiple locations",
}


def _breezy_location(raw: str) -> str:
    """Clean a BreezyHR location: map known polyglot placeholders to text,
    pass through real (possibly localized) location strings unchanged."""
    if not raw:
        return ""
    return _BREEZY_LOCATION_LABELS.get(raw.strip(), raw.strip())


def _onlyfy_posted(raw: str) -> str:
    """Onlyfy (DACH product) renders dates as ``dd.mm.yyyy``; normalize to
    ISO ``yyyy-mm-dd`` so parse_posted/ sorts work. Other formats pass through."""
    if not raw:
        return ""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})$", raw.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return raw


# ---------------- BreezyHR ----------------
# No public API without auth, but the careers page server-renders the full job
# list into the initial HTML. See research/ats_schemas/breezyhr.md for the
# (browser-required) submit flow.

BREEZYHR_CAREERS = "https://{company}.breezy.hr/"


def list_breezyhr(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    """Enumerate BreezyHR jobs from the server-rendered careers HTML.

    Each position renders as ``<a href="/p/{hex}-{slug}"><h2>{title}</h2>
    <ul class="meta"><li class="location">…<span>{loc}</span></li>
    <li class="type">…<span>{type}</span></li></ul>…</a>``. Two anchors share the
    same href per card (details + actions); only the details one has the ``<h2>``,
    so we dedup on the stable hex id and skip the actions anchor.
    """
    url = BREEZYHR_CAREERS.format(company=token)
    html_text = _get(url, timeout=timeout, ua=ua, retries=retries).text
    if "/p/" not in html_text:
        raise BoardError(f"breezyhr board '{token}': no job links in HTML")
    seen: set[str] = set()
    for m in re.finditer(
        r'<a\s+href="(/p/(?P<pid>[A-Za-z0-9_-]+))"[^>]*>(?P<body>.*?)</a>',
        html_text, re.S,
    ):
        body = m.group("body")
        if "<h2" not in body:
            continue  # the per-card "actions" anchor (Apply button only)
        slug_id = m.group("pid")
        # stable job id = the hex prefix before the first '-'
        hexm = re.match(r"[0-9a-f]+", slug_id)
        job_id = hexm.group(0) if hexm else slug_id
        if job_id in seen:
            continue
        seen.add(job_id)
        href = m.group(1)
        tm = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
        title = _clean(tm.group(1)) if tm else ""
        lm = re.search(r'class="location"[^>]*>.*?<span[^>]*>(.*?)</span>', body, re.S)
        location = _breezy_location(_clean(lm.group(1))) if lm else ""
        wm = re.search(r'class="type"[^>]*>.*?<span[^>]*>(.*?)</span>', body, re.S)
        work_type = _breezy_worktype(_clean(wm.group(1))) if wm else ""
        yield Job(
            ats="breezyhr",
            company=company,
            job_id=job_id,
            title=title,
            location=location,
            url=f"https://{token}.breezy.hr{href}",
            department="",
            work_type=work_type,
            posted_at="",
            raw={"href": href, "slug_id": slug_id},
        )


# ---------------- Onlyfy (formerly Prescreen) ----------------
# No public API without auth, but the careers page server-renders the full job
# list into the initial HTML. See research/ats_schemas/onlyfy.md for the
# (browser-required) submit flow.

ONLYFY_JOBS = "https://{company}.onlyfy.jobs/en"


def list_onlyfy(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    """Enumerate Onlyfy jobs from the server-rendered careers HTML.

    Each card is ``<a data-testid="job-card" aria-label="{title}"
    href="/{locale}/job/{id}">`` containing ``<h3 data-testid="job-title">`` and
    a ``<div data-testid="job-more-info">`` with a pipe-separated string
    ``{location} | {work_type} | {posted_at} | {department}``.
    """
    url = ONLYFY_JOBS.format(company=token)
    html_text = _get(url, timeout=timeout, ua=ua, retries=retries).text
    if "/job/" not in html_text:
        raise BoardError(f"onlyfy board '{token}': no job links in HTML")
    seen: set[str] = set()
    for m in re.finditer(
        r'<a\b(?P<attrs>[^>]*data-testid="job-card"[^>]*)>(?P<body>.*?)</a>',
        html_text, re.S,
    ):
        attrs = m.group("attrs")
        body = m.group("body")
        hm = re.search(r'href="(?P<href>/[a-z]{2}/job/(?P<pid>[A-Za-z0-9]+))"', attrs)
        if not hm:
            continue
        pid = hm.group("pid")
        if pid in seen:
            continue
        seen.add(pid)
        href = hm.group("href")
        tm = re.search(r'data-testid="job-title"[^>]*>(.*?)</h3>', body, re.S)
        title = _clean(tm.group(1)) if tm else ""
        if not title:
            am = re.search(r'aria-label="([^"]*)"', attrs)
            title = unescape(am.group(1)) if am else ""
        location = work_type = posted_at = department = ""
        info = re.search(r'data-testid="job-more-info"[^>]*>(.*?)</div>', body, re.S)
        if info:
            parts = [_clean(p) for p in unescape(info.group(1)).split("|")]
            location = parts[0] if len(parts) > 0 else ""
            work_type = parts[1] if len(parts) > 1 else ""
            posted_at = _onlyfy_posted(parts[2]) if len(parts) > 2 else ""
            department = parts[3] if len(parts) > 3 else ""
        yield Job(
            ats="onlyfy",
            company=company,
            job_id=pid,
            title=title,
            location=location,
            url=f"https://{token}.onlyfy.jobs{href}",
            department=department,
            work_type=work_type,
            posted_at=posted_at,
            raw={"href": href, "more_info": info.group(1) if info else ""},
        )


# ---------------- Mailto (email-apply) ----------------
# Some companies (ZynoSec, PentStark) list roles as `mailto:careers@…?subject=…`
# links on a custom careers page — no form, no ATS. We scrape those links and
# synthesize Jobs whose `url` is the mailto href; the mailto submitter drafts the
# email body. `token` here is the careers page URL (set as board_token by
# consolidate.py for ats_type == "mailto"). location/work_type default to the
# candidate's tier info (remote India) since the pages don't state it.

def list_mailto(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    """Scrape `mailto:` role links from a careers page (token = careers URL).

    The mailto role links are in the static HTML on known mailto sites
    (ZynoSec, PentStark), so a plain requests fetch is preferred — it avoids
    headless-browser bot-challenges that blank the page on repeated hits.
    Playwright is the fallback for sites that render the links client-side.
    """
    import urllib.parse as _urlparse
    import re as _re
    career_url = token

    hrefs = _mailto_hrefs_from_html(career_url, ua, timeout, retries)
    if not hrefs:
        # fallback: render in a real browser for client-side mailto lists
        hrefs = _mailto_hrefs_from_browser(career_url, ua)

    seen = set()
    for href in hrefs:
        parsed = _urlparse.urlparse(href)
        to = parsed.path  # the email address (mailto:careers@…)
        qs = _urlparse.parse_qs(parsed.query)
        subject = (qs.get("subject", [""])[0])
        if not subject:
            continue
        # role title = subject with "Application — " / "Application - " prefix stripped
        title = _re.sub(r'^\s*application\s*[—\-]\s*', '', subject, flags=_re.I).strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        body = (qs.get("body", [""])[0])
        yield Job(
            ats="mailto",
            company=company,
            job_id=_re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or title,
            title=title,
            location="Remote, India",
            url=href,
            department="",
            work_type="remote",
            posted_at="",
            raw={"email": to, "subject": subject, "body": body},
        )


def _mailto_hrefs_from_html(url: str, ua: str, timeout: int, retries: int) -> list[str]:
    import re as _re
    last = None
    for _ in range(retries + 1):
        try:
            r = _get(url, timeout=timeout, ua=ua, retries=0)
            if r.status_code == 200 and r.text:
                return list(set(_re.findall(r'href="(mailto:[^"]+)"', r.text)))
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)
        time.sleep(1.0)
    return []


def _mailto_hrefs_from_browser(url: str, ua: str) -> list[str]:
    # Optional Playwright fallback for sites that render mailto links
    # client-side. Playwright is not a required dependency; if it is absent the
    # import below raises ImportError, caught here, and we return [] — the
    # primary requests path (_mailto_hrefs_from_html) handles the known mailto
    # companies from static HTML.
    hrefs: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=ua, viewport={"width": 1280, "height": 900})
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector('a[href^="mailto:"]', timeout=12000)
                except Exception:
                    page.wait_for_timeout(4000)
                hrefs = page.evaluate("""() => Array.from(
                    document.querySelectorAll('a[href^="mailto:"]')
                  ).map(a => a.getAttribute('href') || '')""")
            finally:
                browser.close()
    except Exception:
        pass
    return hrefs


def list_workday(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    """Workday public careers — POST to the cxs jobs endpoint.

    ``token`` is the full careers URL, e.g.
    ``https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers``. Workday
    exposes a public JSON endpoint at ``/wday/cxs/{tenant}/{site}/jobs`` (POST)
    used by the careers SPA. Paginated via offset; capped at 500 jobs/board.
    """
    try:
        from urllib.parse import urlparse
        p = urlparse(token)
        host = p.hostname or ""
        parts = [x for x in (p.path or "").split("/") if x]
        if not host or not parts:
            return
        tenant = host.split(".")[0]
        site = parts[0]
        base = f"{p.scheme}://{host}"
    except Exception:
        return
    headers = {"User-Agent": ua, "Content-Type": "application/json",
               "Accept": "application/json"}
    limit = 20
    offset = 0
    yielded = 0
    cap = 500
    while offset < cap:
        try:
            r = requests.post(
                f"{base}/wday/cxs/{tenant}/{site}/jobs",
                headers=headers, timeout=timeout,
                json={"limit": limit, "offset": offset, "searchText": "", "facets": []},
            )
            if r.status_code == 404:
                return
            r.raise_for_status()
            data = r.json().get("jobPostings", []) or []
        except Exception:
            return
        if not data:
            return
        for j in data:
            ext = j.get("externalPath", "") or ""
            jid = (j.get("bulletFields") or [""])[0] or ext
            loc = j.get("locationsText", "") or ""
            wt = "remote" if "remote" in loc.lower() else ("hybrid" if "hybrid" in loc.lower() else "")
            yield Job(
                ats="workday", company=company, job_id=jid,
                title=j.get("title", "") or "",
                location=loc, url=(base + ext) if ext else token,
                work_type=wt, posted_at="", raw=j,
            )
            yielded += 1
        if len(data) < limit:
            return
        offset += limit
        time.sleep(0.2)


CLIENTS = {
    "greenhouse": list_greenhouse,
    "lever": list_lever,
    "ashby": list_ashby,
    "workable": list_workable,
    "smartrecruiters": list_smartrecruiters,
    "personio": list_personio,
    "rippling": list_rippling,
    "teamtailor": list_teamtailor,
    "breezyhr": list_breezyhr,
    "onlyfy": list_onlyfy,
    "mailto": list_mailto,
    "workday": list_workday,
}