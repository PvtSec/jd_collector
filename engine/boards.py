from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
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
    url: str
    department: str = ""
    work_type: str = ""
    posted_at: str = ""
    raw: dict = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw", None)
        return d


class BoardError(Exception):
    pass


def _ms_to_iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def parse_posted(s: str):
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



ASHBY_BOARD = "https://jobs.ashbyhq.com/{slug}"


def _extract_json_assignment(html: str, var: str) -> dict:
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



TEAMTAILOR_RSS = "https://{company}.teamtailor.com/jobs.rss"


def list_teamtailor(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
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
    from email.utils import parsedate_to_datetime
    ns = {"tt": "https://teamtailor.com/locations"}
    _RS = {"remote": "remote", "hybrid": "hybrid", "office": "onsite"}
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        jid = link.rsplit("/jobs/", 1)[-1].split("?")[0] if "/jobs/" in link else ""
        names = []
        locs = item.find("tt:locations", ns)
        if locs is not None:
            for loc in locs.findall("tt:location", ns):
                nm = (loc.findtext("tt:name", "", ns) or "").strip()
                if nm:
                    names.append(nm)
        loc_str = ", ".join(dict.fromkeys(names))
        if not loc_str:
            loc_m = re.search(r'<span[^>]*class="[^"]*location[^"]*"[^>]*>(.*?)</span>', desc, re.I)
            if loc_m:
                loc_str = re.sub(r"<[^>]+>", "", loc_m.group(1)).strip()
        dept_str = (item.findtext("department") or "").strip()
        if not dept_str:
            dept_m = re.search(r'<span[^>]*class="[^"]*department[^"]*"[^>]*>(.*?)</span>', desc, re.I)
            if dept_m:
                dept_str = re.sub(r"<[^>]+>", "", dept_m.group(1)).strip()
        work_type = _RS.get((item.findtext("remoteStatus") or "").strip().lower(), "")
        posted = ""
        pd = item.findtext("pubDate")
        if pd:
            try:
                posted = parsedate_to_datetime(pd).isoformat()
            except Exception:
                posted = ""
        yield Job(
            ats="teamtailor",
            company=company,
            job_id=jid,
            title=title,
            location=loc_str,
            url=link,
            department=dept_str,
            work_type=work_type,
            posted_at=posted,
            raw={"id": jid, "title": title, "link": link, "location": loc_str, "department": dept_str},
        )



def _clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _breezy_worktype(raw: str) -> str:
    if not raw:
        return ""
    m = re.match(r"%LABEL_POSITION_TYPE_([A-Z_]+)%", raw.strip())
    if m:
        return m.group(1).replace("_", " ").lower()
    return raw.strip().lower()


_BREEZY_LOCATION_LABELS = {
    "%LABEL_MULTIPLE_LOCATIONS%": "Multiple locations",
}


def _breezy_location(raw: str) -> str:
    if not raw:
        return ""
    return _BREEZY_LOCATION_LABELS.get(raw.strip(), raw.strip())


def _onlyfy_posted(raw: str) -> str:
    if not raw:
        return ""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})$", raw.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return raw



BREEZYHR_CAREERS = "https://{company}.breezy.hr/"


def list_breezyhr(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
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
            continue
        slug_id = m.group("pid")
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



ONLYFY_JOBS = "https://{company}.onlyfy.jobs/en"


def list_onlyfy(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
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



def list_mailto(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2) -> Iterator[Job]:
    import urllib.parse as _urlparse
    import re as _re
    career_url = token

    hrefs = _mailto_hrefs_from_html(career_url, ua, timeout, retries)
    if not hrefs:
        hrefs = _mailto_hrefs_from_browser(career_url, ua)

    seen = set()
    for href in hrefs:
        parsed = _urlparse.urlparse(href)
        to = parsed.path
        qs = _urlparse.parse_qs(parsed.query)
        subject = (qs.get("subject", [""])[0])
        if not subject:
            continue
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
                location=loc, url=(base + "/" + site + ext) if ext else token,
                work_type=wt, posted_at="", raw=j,
            )
            yielded += 1
        if len(data) < limit:
            return
        offset += limit
        time.sleep(0.2)


BAMBOOHR_LIST = "https://{sub}.bamboohr.com/careers/list"
BAMBOOHR_DETAIL = "https://{sub}.bamboohr.com/careers/{jid}/detail"
BAMBOOHR_JOB_URL = "https://{sub}.bamboohr.com/careers/{jid}"

# *.bamboohr.com resolves for ANY subdomain (wildcard DNS), so non-tenant hosts must be
# rejected by name rather than by whether they answer.
BAMBOOHR_RESERVED = {
    "www", "api", "app", "help", "blog", "docs", "documentation", "resources",
    "staticfe", "static", "assets", "images", "get", "login", "support",
    "status", "partners", "marketplace", "developer", "cdn",
}

# bamboohr "locationType": 0 = on-site, 1 = remote, 2 = hybrid. The sibling isRemote
# field is always null and must not be used.
_BHR_LOCTYPE = {"0": "onsite", "1": "remote", "2": "hybrid", 0: "onsite", 1: "remote", 2: "hybrid"}


def _bamboohr_sub(token: str) -> str:
    """Accept a bare subdomain ('acme') or any *.bamboohr.com URL, return the subdomain."""
    t = (token or "").strip()
    if "://" in t or "/" in t or "." in t:
        from urllib.parse import urlparse
        h = (urlparse(t if "://" in t else "https://" + t).hostname or "").lower()
        parts = h.split(".")
        t = parts[0] if len(parts) >= 2 else h
    t = t.lower()
    if not t or re.sub(r"\d+$", "", t) in BAMBOOHR_RESERVED:
        raise BoardError(f"bamboohr: '{token}' is not a tenant subdomain")
    return t


def _bamboohr_get(url: str, *, ua: str, timeout: int, retries: int) -> dict:
    """GET a bamboohr careers JSON endpoint, treating any redirect as a dead board.

    Tenants that never existed 30x to www.bamboohr.com; boards switched off 30x to
    /login.php. Following redirects would make both look like a live empty board.
    """
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, timeout=timeout, allow_redirects=False,
                             headers={"User-Agent": ua, "Accept": "application/json"})
            if r.status_code in (301, 302, 303, 307, 308):
                dest = r.headers.get("Location", "")
                if "login" in dest:
                    raise BoardError(f"bamboohr board not public: {url}")
                raise BoardError(f"bamboohr tenant does not exist: {url} -> {dest}")
            if r.status_code in (401, 403):
                raise BoardError(f"bamboohr board not public ({r.status_code}): {url}")
            if r.status_code == 404:
                raise BoardError(f"404 bamboohr resource not found: {url}")
            r.raise_for_status()
            if "json" not in (r.headers.get("content-type") or ""):
                raise BoardError(f"bamboohr: non-JSON response for {url}")
            return r.json()
        except BoardError:
            raise
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(1.0)
    raise BoardError(f"bamboohr request failed: {url} -> {last}")


def _bamboohr_location(loc: dict | None, ats_loc: dict | None, loc_type) -> str:
    loc = loc or {}
    ats_loc = ats_loc or {}
    if _BHR_LOCTYPE.get(loc_type) == "remote":
        parts = [ats_loc.get("city"), ats_loc.get("province") or ats_loc.get("state"),
                 ats_loc.get("country")]
        return ", ".join(dict.fromkeys(p for p in parts if p)) or "Remote"
    parts = [loc.get("city"), loc.get("state"), loc.get("addressCountry"), ats_loc.get("country")]
    return ", ".join(dict.fromkeys(p for p in parts if p))


BAMBOOHR_DETAIL_WORKERS = 4


def list_bamboohr(company: str, token: str, *, ua: str, timeout: int = 20, retries: int = 2,
                  detail: bool = True, detail_max: int = 80) -> Iterator[Job]:
    """Enumerate a bamboohr careers board.

    /careers/list returns every open posting in one unpaginated response
    (meta.totalCount == len(result)), so it is safe for closed-job detection. The list
    payload has no country and no date -- only /careers/{id}/detail supplies those, which
    location_pref matching needs, so detail defaults on (costs 1 request per posting).

    Those detail calls dominate the runtime (a 34-job board takes ~34s serially vs ~0.7s
    without them), so they are fetched with a small worker pool. The pool size is the only
    thing pacing them, so keep it low -- the scheduler already runs several bamboohr boards
    at once via ats_concurrency.
    """
    sub = _bamboohr_sub(token)
    data = _bamboohr_get(BAMBOOHR_LIST.format(sub=sub), ua=ua, timeout=timeout, retries=retries)
    rows = data.get("result") or []
    if not isinstance(rows, list):
        raise BoardError(f"unexpected bamboohr response for {sub}: {type(rows)}")

    details: dict[str, dict] = {}
    if detail:
        wanted = [str(j.get("id")) for j in rows[:detail_max] if j.get("id")]

        def _one(jid: str):
            try:
                d = _bamboohr_get(BAMBOOHR_DETAIL.format(sub=sub, jid=jid),
                                  ua=ua, timeout=timeout, retries=1)
                return jid, ((d.get("result") or {}).get("jobOpening") or {})
            except BoardError:
                return jid, {}

        if wanted:
            with ThreadPoolExecutor(max_workers=BAMBOOHR_DETAIL_WORKERS) as ex:
                for jid, jo in ex.map(_one, wanted):
                    if jo:
                        details[jid] = jo

    for j in rows:
        jid = str(j.get("id") or "")
        if not jid:
            continue
        raw = dict(j)
        loc_type = j.get("locationType")
        loc, ats_loc = j.get("location"), j.get("atsLocation")
        posted = ""
        jo = details.get(jid)
        if jo:
            posted = jo.get("datePosted") or ""
            loc = jo.get("location") or loc
            ats_loc = jo.get("atsLocation") or ats_loc
            loc_type = jo.get("locationType", loc_type)
            raw.update({"datePosted": posted, "location": loc, "atsLocation": ats_loc})
        yield Job(
            ats="bamboohr", company=company, job_id=jid,
            title=(j.get("jobOpeningName") or "").strip(),
            location=_bamboohr_location(loc, ats_loc, loc_type),
            url=BAMBOOHR_JOB_URL.format(sub=sub, jid=jid),
            department=(j.get("departmentLabel") or "").strip(),
            work_type=_BHR_LOCTYPE.get(loc_type, ""),
            posted_at=posted, raw=raw,
        )


PINPOINT_POSTINGS = "https://{sub}.pinpointhq.com/postings.json"


def list_pinpoint(company: str, token: str, *, ua: str, timeout: int = 20,
                  retries: int = 2) -> Iterator[Job]:
    """Enumerate a pinpoint board. Complete in one response; carries no posted date."""
    r = _get(PINPOINT_POSTINGS.format(sub=token), timeout=timeout, ua=ua, retries=retries)
    data = r.json()
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise BoardError(f"unexpected pinpoint response for {token}: {type(data)}")
    for p in rows:
        loc = p.get("location") or {}
        loc_str = ", ".join(dict.fromkeys(
            x for x in (loc.get("city"), loc.get("province"), loc.get("country")) if x
        )) or (loc.get("name") or "")
        # workplace_type is the real signal; the sibling `remote` field is always null
        wt = (p.get("workplace_type") or "").lower()
        if not wt and "remote" in (loc.get("name") or "").lower():
            wt = "remote"
        yield Job(
            ats="pinpoint", company=company, job_id=str(p.get("id", "")),
            title=(p.get("title") or "").strip(),
            location=loc_str,
            url=p.get("url") or f"https://{token}.pinpointhq.com{p.get('path','')}",
            department=(p.get("department") or {}).get("name", "") if isinstance(p.get("department"), dict) else "",
            work_type=wt, posted_at="",
            raw={k: p.get(k) for k in ("id", "employment_type", "workplace_type", "path")},
        )


RECRUITEE_OFFERS = "https://{sub}.recruitee.com/api/offers/"


def list_recruitee(company: str, token: str, *, ua: str, timeout: int = 20,
                   retries: int = 2) -> Iterator[Job]:
    """Enumerate a recruitee board. Complete in one response; has published_at."""
    r = _get(RECRUITEE_OFFERS.format(sub=token), timeout=timeout, ua=ua, retries=retries)
    data = r.json()
    offers = data.get("offers") if isinstance(data, dict) else None
    if offers is None:
        raise BoardError(f"unexpected recruitee response for {token}: {type(data)}")
    for o in offers:
        if (o.get("status") or "published") != "published":
            continue
        if o.get("remote"):
            wt = "remote"
        elif o.get("hybrid"):
            wt = "hybrid"
        elif o.get("on_site"):
            wt = "onsite"
        else:
            wt = ""
        loc_str = o.get("location") or ", ".join(
            x for x in (o.get("city"), o.get("state_name"), o.get("country")) if x
        )
        posted = (o.get("published_at") or o.get("created_at") or "")
        posted = posted.replace(" UTC", "Z").replace(" ", "T")
        yield Job(
            ats="recruitee", company=company, job_id=str(o.get("id", "")),
            title=o.get("title", ""), location=loc_str,
            url=o.get("careers_url") or f"https://{token}.recruitee.com/o/{o.get('slug','')}",
            department=o.get("department") or "", work_type=wt, posted_at=posted,
            raw={k: o.get(k) for k in ("id", "slug", "status", "employment_type_code", "country_code")},
        )


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
    "bamboohr": list_bamboohr,
    "pinpoint": list_pinpoint,
    "recruitee": list_recruitee,
}