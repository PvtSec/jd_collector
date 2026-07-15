"""Application settings for the dashboard backend.

Reads sane defaults, overridable by environment variables. An optional ``app:``
block in the engine ``config.yaml`` may also set any field (env wins on conflict).
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

# Repo root = parent of app/  (app/backend/src/settings.py -> ../../..)
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FRONTEND_DIST = REPO_ROOT / "app" / "frontend" / "dist"


class AppSettings(BaseSettings):
    # Engine integration
    engine_config: str = Field(default="config.yaml", description="Path to job_auto config.yaml")
    jobs_db: str = Field(default="data/jobs.db", description="Path to the dashboard jobs/task DB")

    # Persisted plain-file state (survives restarts + DB wipes). Holds applied
    # states and per-scan newly-found jobs.
    state_file: str = Field(default="app/state.json", description="Path to the persisted state file")

    # Scheduler
    tick_minutes: int = Field(default=5, ge=1, description="Minutes between discovery ticks")
    rotate_size: int = Field(default=60, ge=1, description="Companies enumerated per tick")
    link_check_minutes: int = Field(default=720, ge=30, description="Minutes between dead-link prune sweeps")
    # Automatic new-company discovery: re-runs discover_slugs + discover_topstartups
    # + consolidate on this cadence so the company list grows without the manual
    # Rescan button. Default 24h (polite to topstartups.io).
    company_discovery_minutes: int = Field(default=1440, ge=60, description="Minutes between automatic new-company discovery sweeps")
    # Stale-job reaper: consecutive successful enumerations of a company in which a
    # previously-seen job is absent before it is marked closed. Only the fully-
    # paginated ATS are reaped (see discovery.REAPER_ATS). Env: JOBAUTO_STALE_GRACE_MISSES.
    stale_grace_misses: int = Field(default=2, ge=1, description="Consecutive absent enumerations before a job is marked closed")

    # Discovered-jobs seed: the dashboard dumps its discovered jobs to this JSON
    # file (on the volume) and re-imports it on an empty jobs DB so a fresh start
    # isn't empty. On a fresh named volume Docker initializes it from the baked
    # image copy; the export job refreshes the volume copy on this cadence.
    seed_file: str = Field(default="data/jobs_seed.json", description="Discovered-jobs seed file (volume; baked into the image for fresh volumes)")
    seed_export_minutes: int = Field(default=60, ge=5, description="Minutes between seed exports")
    seed_max_rows: int = Field(default=0, ge=0, description="Max jobs kept in the seed (most-recently-seen); 0 = no cap, export every row")

    # Server
    # Render sets the $PORT env var (default 10000 on Render). When running
    # locally without that env var we fall back to 8000 to match the venv dev
    # experience (`uvicorn app.backend.src.main:app --port 8000`).
    host: str = "0.0.0.0"
    port: int = Field(default_factory=lambda: int(os.environ.get("PORT", "8000")))

    # Frontend static assets (served at / in production)
    frontend_dist: str = Field(default=str(DEFAULT_FRONTEND_DIST))

    # Heavy company-discovery scripts (subprocess; consolidate is NOT import-safe).
    # ``{python}`` is replaced with the project venv interpreter if present, else sys.executable.
    rescan_commands: list[str] = Field(
        default_factory=lambda: [
            "{python} scripts/discover_companies.py",
            "{python} scripts/discover_topstartups.py",
            "{python} scripts/discover_yc.py",         # YC Startup Directory (public JSON API + slug probe)
            "{python} scripts/discover_himalayas.py",   # Himalayas public API (role-targeted + full-feed sweep)
            "{python} scripts/discover_builtin.py",     # BuiltIn.com company listing (HTML scrape + slug probe)
            "{python} scripts/discover_chsr.py",        # edoardottt/companies-hiring-security-remote README (cached + slug probe)
            "{python} scripts/consolidate.py",
            "{python} scripts/discover_slugs.py",       # slow (probes unknowns) — last so a timeout doesn't block the merge
        ]
    )
    rescan_step_timeout: int = Field(default=1200, ge=60, description="Per-step subprocess timeout for the rescan chain")

    model_config = {"env_prefix": "JOBAUTO_", "env_file": None, "extra": "ignore"}

    def abs_engine_config(self) -> str:
        p = Path(self.engine_config)
        return str(p if p.is_absolute() else REPO_ROOT / p)

    def abs_jobs_db(self) -> str:
        p = Path(self.jobs_db)
        return str(p if p.is_absolute() else REPO_ROOT / p)

    def abs_frontend_dist(self) -> str:
        p = Path(self.frontend_dist)
        return str(p if p.is_absolute() else REPO_ROOT / p)

    def abs_state_file(self) -> str:
        p = Path(self.state_file)
        return str(p if p.is_absolute() else REPO_ROOT / p)

    def abs_seed_file(self) -> str:
        p = Path(self.seed_file)
        return str(p if p.is_absolute() else REPO_ROOT / p)


def _load_yaml_app_block(engine_config_path: str) -> dict:
    """Return the ``app:`` block of the engine config if present, else {}."""
    try:
        import yaml  # PyYAML is an engine dep
    except Exception:  # pragma: no cover
        return {}
    try:
        with open(engine_config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    block = data.get("app") or {}
    return block if isinstance(block, dict) else {}


def load_settings() -> AppSettings:
    """Build AppSettings: defaults <- env <- engine config ``app:`` block (env wins)."""
    # First read env-only settings so we know the engine_config path to look at.
    base = AppSettings()
    app_block = _load_yaml_app_block(base.abs_engine_config())
    # env already applied via BaseSettings; layer yaml on top only for keys not set in env.
    env_keys = {k.lower() for k in os.environ if k.startswith("JOBAUTO_")}
    overrides = {k: v for k, v in app_block.items() if k.lower() not in env_keys}
    if overrides:
        return base.model_copy(update=overrides)
    return base


settings = load_settings()