from __future__ import annotations

import json

from engine.boards import CLIENTS
from engine.config import Config


def load_companies(cfg: Config) -> list[dict]:
    with open(cfg.companies_file, "r", encoding="utf-8") as f:
        return json.load(f)


def companies_filtered(cfg: Config, ats: str | None = None) -> list[dict]:
    comps = load_companies(cfg)
    if ats:
        comps = [c for c in comps if c["ats_type"] == ats]
    if cfg.allow_companies:
        allow = {a.lower() for a in cfg.allow_companies}
        comps = [c for c in comps if c["company_name"].lower() in allow]
    if cfg.skip_companies:
        skip = {s.lower() for s in cfg.skip_companies}
        comps = [c for c in comps if c["company_name"].lower() not in skip]
    out: list[dict] = []
    for c in comps:
        if c["ats_type"] not in CLIENTS:
            continue
        token = c.get("board_token")
        if c["ats_type"] == "smartrecruiters":
            token = "".join(ch for ch in c["company_name"].lower() if ch.isalnum())
        if c["ats_type"] == "workday":
            # workday enumerator needs the full careers URL (tenant + site + host)
            token = c.get("career_page_url") or token
        if token:
            out.append(dict(c, board_token=token))
    out.sort(key=lambda c: (c["ats_type"], c["company_name"].lower()))
    return out