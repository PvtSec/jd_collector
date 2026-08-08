from __future__ import annotations

import html as _html
import logging
import os
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

import requests

from engine.ats_registry import detect_ats_by_host
from engine.boards import _extract_json_assignment, _find_key

from .skills_vocab import SKILLS

log = logging.getLogger("resume")

UA = "job-auto-resume-builder/1.0 (+dashboard)"
JD_MAX_CHARS = 20000
SKILL_LIMIT = 40

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_HERE, "resume_template.tex")


class ResumeError(Exception):
    pass


class ResumeCompileError(ResumeError):
    pass



def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)</(p|div|li|tr|br|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _get(url: str, *, accept: str = "text/html,application/json", timeout: int = 20) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept": accept})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.debug("JD fetch failed %s: %s", url, e)
        return None


def _get_json(url: str, *, timeout: int = 20):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept": "application/json"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.debug("JD json fetch failed %s: %s", url, e)
        return None


def _path_segs(url: str) -> list[str]:
    return [s for s in (urlparse(url).path or "").split("/") if s]


def _resolve_token(ats: str, company_name: str, companies: list[dict] | None) -> str | None:
    if not companies or not company_name:
        return None
    cl = company_name.lower()
    for c in companies:
        if (c.get("company_name") or "").lower() == cl and c.get("ats_type") == ats:
            return c.get("board_token") or None
    return None


def _token_from_url(ats: str, segs: list[str]) -> str | None:
    if ats == "greenhouse":
        if "jobs" in segs:
            i = segs.index("jobs")
            if i >= 1:
                return segs[i - 1]
    elif ats == "lever":
        if len(segs) >= 2:
            return segs[0]
    elif ats == "workable":
        if "j" in segs:
            i = segs.index("j")
            if i >= 1:
                return segs[i - 1]
    elif ats == "smartrecruiters":
        if len(segs) >= 1:
            return segs[0]
    elif ats == "personio":
        host_seg = None
        return None
    elif ats == "ashby":
        if len(segs) >= 1:
            return segs[0]
    return None


def fetch_jd(job_row: dict, companies: list[dict] | None = None) -> str | None:
    url = (job_row or {}).get("url") or ""
    if not url or not url.startswith("http"):
        return None
    ats = detect_ats_by_host(url) or (job_row.get("ats") or "").lower()
    company = job_row.get("company") or ""
    jid = job_row.get("job_id") or ""
    segs = _path_segs(url)

    def token() -> str | None:
        return _token_from_url(ats, segs) or _resolve_token(ats, company, companies)

    try:
        if ats == "greenhouse" and token() and jid:
            data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token()}/jobs/{jid}")
            if data and data.get("content"):
                return _strip_html(data["content"])[:JD_MAX_CHARS]

        elif ats == "lever" and token() and jid:
            data = _get_json(f"https://api.lever.co/v0/postings/{token()}/{jid}?mode=json")
            if data and (data.get("descriptionPlain") or data.get("description")):
                return _strip_html(data.get("descriptionPlain") or data.get("description"))[:JD_MAX_CHARS]

        elif ats == "workable" and token() and jid:
            data = _get_json(f"https://apply.workable.com/api/v3/accounts/{token()}/jobs/{jid}")
            if data and data.get("description"):
                return _strip_html(data["description"])[:JD_MAX_CHARS]

        elif ats == "smartrecruiters" and token() and jid:
            data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{token()}/postings/{jid}")
            if data:
                txt = data.get("jobDescription")
                if not txt:
                    job_ad = data.get("jobAd") or {}
                    sections = job_ad.get("sections") or {}
                    jd = sections.get("jobDescription") or {}
                    txt = jd.get("text") if isinstance(jd, dict) else None
                if not txt:
                    txt = _find_key(data, "description") or _find_key(data, "jobDescription")
                if txt:
                    return _strip_html(str(txt))[:JD_MAX_CHARS]

        elif ats == "ashby" and jid:
            page = _get(url, accept="text/html")
            if page:
                try:
                    data = _extract_json_assignment(page, "__appData")
                except Exception:
                    data = None
                if data:
                    desc = _find_key(data, "descriptionHtml") or _find_key(data, "description")
                    if desc:
                        return _strip_html(str(desc))[:JD_MAX_CHARS]

        elif ats == "personio" and jid:
            t = (urlparse(url).hostname or "").split(".")[0]
            if not t or t in ("", "www"):
                t = _resolve_token("personio", company, companies)
            if t:
                page = _get(f"https://{t}.jobs.personio.com/job/{jid}?language=en",
                            accept="text/html")
                if page:
                    return _strip_html(page)[:JD_MAX_CHARS]
    except Exception as e:
        log.debug("JD per-ATS fetch error (%s): %s", ats, e)

    page = _get(url, accept="text/html,application/json")
    if page:
        text = _strip_html(page)
        if len(text) >= 120:
            return text[:JD_MAX_CHARS]
    return None



_MATCHERS: list[tuple[re.Pattern, str, str]] = []
for _cat, _skills in SKILLS.items():
    for _sk in sorted(_skills, key=len, reverse=True):
        _pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(_sk) + r"(?![A-Za-z0-9])", re.IGNORECASE)
        _MATCHERS.append((_pat, _sk, _cat))


def extract_skills(jd_text: str | None, title: str | None = None) -> list[dict]:
    text = f"{jd_text or ''}\n{title or ''}"
    if not text.strip():
        return []
    hits: dict[str, tuple[int, str, str]] = {}
    for pat, name, cat in _MATCHERS:
        m = pat.search(text)
        if not m:
            continue
        norm = name.lower()
        prev = hits.get(norm)
        if prev is None or m.start() < prev[0]:
            hits[norm] = (m.start(), name, cat)
    ordered = sorted(hits.values(), key=lambda t: t[0])
    return [{"name": name, "category": cat} for _, name, cat in ordered[:SKILL_LIMIT]]



def _esc(s) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)
    s = s.replace("\\", r"\textbackslash{}")
    for a, b in (("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                ("_", r"\_"), ("{", r"\{"), ("}", r"\}")):
        s = s.replace(a, b)
    s = s.replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}")
    return s


def _dates(start, end) -> str:
    s = _esc(start).strip()
    e = _esc(end).strip()
    if s and e:
        return f"{s} – {e}"
    return s or e or ""


def _href(url, label) -> str:
    url = (url or "").strip()
    label = (label or "").strip()
    if not url:
        return _esc(label) if label else ""
    if not label:
        label = url
    return "\\mbox{\\hrefWithoutArrow{" + _esc(url) + "}{" + _esc(label) + "}}"


def _build_header(f: dict) -> str:
    name = _esc(f.get("name"))
    items: list[str] = []
    email = (f.get("email") or "").strip()
    if email:
        items.append(_href(f"mailto:{email}", email))
    loc = (f.get("location") or "").strip()
    if loc:
        items.append(f"\\mbox{{{_esc(loc)}}}")
    phone = (f.get("phone") or "").strip()
    if phone:
        tel = phone if phone.startswith("+") else f"+{phone}"
        items.append(_href(f"tel:{tel}", phone))
    li = (f.get("linkedIn") or "").strip()
    if li:
        items.append(_href(li, _shorten_url(li, "linkedin.com/in/...")))
    gh = (f.get("github") or "").strip()
    if gh:
        items.append(_href(gh, _shorten_url(gh, "github.com/...")))
    web = (f.get("website") or "").strip()
    if web:
        items.append(_href(web, _shorten_url(web, web)))
    sep = "\\kern 5.0 pt\\AND\\kern 5.0 pt"
    contact = sep.join(items)
    return (
        "\\begin{header}\n"
        f"\\fontsize{{25 pt}}{{25 pt}}\\selectfont {name}\n\\vspace{{5 pt}}\n\\normalsize\n"
        f"{contact}\n"
        "\\end{header}\n\\vspace{15 pt - 0.3 cm}\n"
    )


def _shorten_url(url: str, fallback_label: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    host = (p.hostname or "").replace("www.", "")
    path = (p.path or "").strip("/")
    if "linkedin.com" in host:
        return f"linkedin.com/{path}" if path else "LinkedIn"
    if "github.com" in host:
        return f"github.com/{path}" if path else "GitHub"
    if host:
        return f"{host}/{path}".rstrip("/") if path else host
    return fallback_label


def _highlights(items: list[str]) -> str:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return ""
    out = "\\begin{onecolentry}\n\\begin{highlights}\n"
    for it in items:
        out += f"\\item {_esc(it)}\n"
    out += "\\end{highlights}\n\\end{onecolentry}\n"
    return out


def _section(title: str, body: str) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    return f"\\vspace{{0.1 cm}}\n\\section{{{title}}}\n{body}\n"


def _build_summary(f: dict) -> str:
    return _highlights(f.get("summary") or [])


def _build_skills(f: dict) -> str:
    skills = [s for s in (f.get("skills") or []) if s.get("keep") and (s.get("name") or "").strip()]
    if not skills:
        return ""
    by_cat: dict[str, list[str]] = {}
    for s in skills:
        by_cat.setdefault(s.get("category") or "Skills", []).append(s["name"])
    out = ""
    for cat, names in by_cat.items():
        out += "\\begin{onecolentry}\n"
        out += f"\\textbf{{{_esc(cat)}:}} {_esc(', '.join(names))}\n"
        out += "\\end{onecolentry}\n\\vspace{0.1 cm}\n"
    return out


def _build_experience(f: dict) -> str:
    out = ""
    for blk in f.get("experience") or []:
        title = _esc(blk.get("title"))
        comp = _esc(blk.get("company"))
        loc = _esc(blk.get("location"))
        dates = _dates(blk.get("start"), blk.get("end"))
        title_line = f"\\textbf{{\\fontsize{{11}}{{16}}\\selectfont {title}"
        if comp:
            loc_part = f" -- {loc}" if loc else ""
            title_line += f" \\\\{comp}{loc_part}"
        title_line += "}"
        out += "\\begin{twocolentry}\n"
        out += f"{{ {_dates(blk.get('start'), blk.get('end'))} }} {title_line}\n"
        out += "\\end{twocolentry}\n"
        desc = (blk.get("desc") or "").strip()
        if desc:
            out += f"\\begin{{onecolentry}}\n\\textit{{{_esc(desc)}}}\n\\end{{onecolentry}}\n"
        out += "\\vspace{0.10 cm}\n"
        hl = _highlights(blk.get("highlights") or [])
        if hl:
            out += hl
        out += "\\vspace{0.2 cm}\n"
    return out.rstrip() + "\n" if out.strip() else ""


def _build_education_certs(f: dict) -> str:
    out = ""
    for blk in f.get("education") or []:
        inst = _esc(blk.get("institution"))
        degree = _esc(blk.get("degree"))
        dates = _dates(blk.get("start"), blk.get("end"))
        out += "\\begin{twocolentry}\n"
        out += f"{{ {_dates(blk.get('start'), blk.get('end'))} }} \\textbf{{{_esc(blk.get('institution'))}}}\n"
        out += "\\begin{onecolentry}\n"
        out += f"\\textit{{{_esc(blk.get('degree'))}}}\n"
        out += "\\end{onecolentry}\n\\end{twocolentry}\n\\vspace{0.3 cm}\n"
    for blk in f.get("certifications") or []:
        name = _esc(blk.get("name"))
        date = _esc(blk.get("date"))
        url = (blk.get("url") or "").strip()
        third = _esc(url) if url else ""
        out += "\\begin{threecolentry}\n"
        out += f"{{{_esc(blk.get('name'))}}} {{{_esc(blk.get('date'))}}} {{{third}}}\n"
        out += "\\end{threecolentry}\n"
        hl = _highlights(blk.get("highlights") or [])
        if hl:
            out += hl
    return out


def _build_projects(f: dict) -> str:
    out = ""
    for blk in f.get("projects") or []:
        name = _esc(blk.get("name"))
        tags = _esc(blk.get("tags"))
        url = (blk.get("url") or "").strip()
        url_part = f"\\hspace{{0.5cm}} {_esc(url)}" if url else ""
        out += "\\begin{twocolentry}\n"
        out += f"{{ {_esc(blk.get('tags'))} }}{{\\textbf{{{_esc(blk.get('name'))}}}{url_part}}}\n"
        out += "\\end{twocolentry}\n\\vspace{0.1 cm}\n"
        hl = _highlights(blk.get("highlights") or [])
        if hl:
            out += hl
        out += "\\vspace{0.3 cm}\n"
    return out


def _build_achievements(f: dict) -> str:
    out = ""
    for blk in f.get("achievements") or []:
        url = (blk.get("url") or "").strip()
        third = _esc(url) if url else ""
        out += "\\begin{threecolentry}\n"
        out += f"{{{_esc(blk.get('name'))}}} {{{_esc(blk.get('date'))}}} {{{third}}}\n"
        out += "\\end{threecolentry}\n"
        hl = _highlights(blk.get("highlights") or [])
        if hl:
            out += hl
    return out


def render_tex(f: dict) -> str:
    with open(_TEMPLATE_PATH, "r", encoding="utf-8") as fh:
        template = fh.read()

    body = _build_header(f)
    body += _section("PROFILE SUMMARY", _build_summary(f))
    body += _section("SKILLS", _build_skills(f))
    body += _section("WORK EXPERIENCE", _build_experience(f))
    edu_body = _build_education_certs(f)
    body += _section("EDUCATION \\& CERTIFICATIONS", edu_body)
    body += _section("PROJECTS", _build_projects(f))
    body += _section("ACHIEVEMENTS", _build_achievements(f))

    pdf_title = _esc(f.get("name") or "Resume")
    out = template.replace("@@PDF_TITLE@@", pdf_title)
    out = out.replace("@@BODY@@", body)
    return out



def _log_excerpt(log_text: str) -> str:
    if not log_text:
        return "unknown LaTeX error"
    lines = log_text.splitlines()
    keep: list[str] = []
    for ln in lines:
        if ln.startswith("! ") or ln.startswith("l.") or ln.startswith("Missing") \
                or ln.startswith("Undefined") or ln.startswith("Emergency stop"):
            keep.append(ln)
    excerpt = "\n".join(keep[:12]).strip()
    return excerpt or log_text[-1200:]


def compile_pdf(tex: str) -> bytes:
    if not shutil.which("pdflatex"):
        raise ResumeCompileError(
            "pdflatex is not installed in this environment. "
            "Rebuild the image with the TeX Live layer (see Dockerfile).")
    tmp = tempfile.mkdtemp(prefix="resume_", dir="/tmp")
    try:
        tex_path = os.path.join(tmp, "resume.tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(tex)
        env = dict(os.environ, max_print_line="1000", error_line="254")
        for _ in range(2):
            proc = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "-file-line-error", "-output-directory", tmp, "resume.tex"],
                cwd=tmp, capture_output=True, text=True, timeout=90, env=env,
            )
            if proc.returncode != 0:
                log_text = ""
                try:
                    with open(os.path.join(tmp, "resume.log"), encoding="utf-8",
                              errors="replace") as fh:
                        log_text = fh.read()
                except Exception:
                    log_text = proc.stdout or ""
                raise ResumeCompileError(_log_excerpt(log_text))
        pdf_path = os.path.join(tmp, "resume.pdf")
        if not os.path.exists(pdf_path):
            raise ResumeCompileError("pdflatex produced no PDF output")
        with open(pdf_path, "rb") as fh:
            return fh.read()
    except ResumeCompileError:
        raise
    except subprocess.TimeoutExpired:
        raise ResumeCompileError("pdflatex timed out (>90s)")
    except Exception as e:
        raise ResumeCompileError(f"compile error: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



def get_job_context(job_row: dict, companies: list[dict] | None = None) -> dict:
    jd = None
    err = None
    try:
        jd = fetch_jd(job_row, companies=companies)
    except Exception as e:
        err = str(e)
    skills = extract_skills(jd, title=job_row.get("title"))
    return {
        "title": job_row.get("title") or "",
        "company": job_row.get("company") or "",
        "jd_text": jd or "",
        "skills": skills,
        "jd_error": err,
    }