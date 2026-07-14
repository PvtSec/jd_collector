"""Load job_auto config (discovery + filtering only — no candidate profile).

This project is a centralized job-search centre: it enumerates boards, filters
jobs by the target roles in config.yaml, and lists them. It does not apply or
submit anything; applying is done by you in the browser.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import yaml


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Safety:
    dry_run: bool = True
    min_delay_seconds: int = 45
    max_delay_seconds: int = 180
    max_applications_per_run: int = 20
    skip_if_captcha: bool = True
    skip_if_tos_anti_automation: bool = True
    respect_robots_txt: bool = True


@dataclass
class Target:
    role_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    location_pref: list[str] = field(default_factory=list)
    work_types: list[str] = field(default_factory=lambda: ["remote", "hybrid"])


@dataclass
class Config:
    raw: dict[str, Any]
    companies_file: str
    ledger_db: str
    target: Target
    safety: Safety
    allow_companies: list[str] | None
    skip_companies: list[str]
    ats_priority: list[str]
    http_timeout: int
    user_agent: str
    http_retries: int

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        d = _load_yaml(path)
        s = d.get("safety", {}) or {}
        t = d.get("target", {}) or {}
        h = d.get("http", {}) or {}
        return cls(
            raw=d,
            companies_file=(d.get("data", {}) or {}).get("companies_file", "data/companies.json"),
            ledger_db=(d.get("data", {}) or {}).get("ledger_db", "data/applied.sqlite"),
            target=Target(
                role_keywords=[k.lower() for k in t.get("role_keywords", [])],
                exclude_keywords=[k.lower() for k in t.get("exclude_keywords", [])],
                location_pref=[l.lower() for l in t.get("location_pref", [])],
                work_types=[w.lower() for w in t.get("work_types", ["remote", "hybrid"])],
            ),
            safety=Safety(
                dry_run=bool(s.get("dry_run", True)),
                min_delay_seconds=int(s.get("min_delay_seconds", 45)),
                max_delay_seconds=int(s.get("max_delay_seconds", 180)),
                max_applications_per_run=int(s.get("max_applications_per_run", 20)),
                skip_if_captcha=bool(s.get("skip_if_captcha", True)),
                skip_if_tos_anti_automation=bool(s.get("skip_if_tos_anti_automation", True)),
                respect_robots_txt=bool(s.get("respect_robots_txt", True)),
            ),
            allow_companies=d.get("allow_companies"),
            skip_companies=[s.lower() for s in (d.get("skip_companies") or [])],
            ats_priority=d.get("ats_priority", ["greenhouse", "lever", "ashby"]),
            http_timeout=int(h.get("timeout_seconds", 20)),
            user_agent=h.get("user_agent", "Mozilla/5.0 (job-auto)"),
            http_retries=int(h.get("retries", 2)),
        )