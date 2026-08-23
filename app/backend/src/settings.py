from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FRONTEND_DIST = REPO_ROOT / "app" / "frontend" / "dist"


class AppSettings(BaseSettings):
    engine_config: str = Field(default="config.yaml", description="Path to job_auto config.yaml")
    jobs_db: str = Field(default="data/jobs.db", description="Path to the dashboard jobs/task DB")

    state_file: str = Field(default="app/state.json", description="Path to the persisted state file")

    tick_minutes: int = Field(default=5, ge=1, description="Minutes between discovery ticks")
    rotate_size: int = Field(default=60, ge=1, description="Companies enumerated per tick")
    tick_concurrency: int = Field(default=24, ge=1, description="Max boards enumerated concurrently per tick (global)")
    ats_concurrency: int = Field(default=4, ge=1, description="Max concurrent enumerations per ATS host (rate-limit safety)")
    dead_skip_threshold: int = Field(default=4, ge=1, description="Consecutive failures before a board is skipped as dead")
    dead_skip_minutes: int = Field(default=360, ge=10, description="Cooldown before a dead board is re-probed (minutes)")
    link_check_minutes: int = Field(default=720, ge=30, description="Minutes between dead-link prune sweeps")
    company_discovery_minutes: int = Field(default=1440, ge=60, description="Minutes between automatic new-company discovery sweeps")
    stale_grace_misses: int = Field(default=2, ge=1, description="Consecutive absent enumerations before a job is marked closed")
    job_liveness_minutes: int = Field(default=120, ge=15, description="Minutes between per-job URL existence sweeps (closes dead listed jobs the board-reaper can't reach, e.g. orphaned by company/job_id drift)")
    job_liveness_batch: int = Field(default=500, ge=10, description="Matched+open jobs whose endpoint is URL-checked per liveness sweep")

    seed_file: str = Field(default="data/jobs_seed.json", description="Discovered-jobs seed file (volume; baked into the image for fresh volumes)")
    seed_export_minutes: int = Field(default=360, ge=5, description="Minutes between seed exports")
    seed_max_rows: int = Field(default=0, ge=0, description="Max jobs kept in the seed (most-recently-seen); 0 = no cap, export every row")

    host: str = "0.0.0.0"
    port: int = Field(default_factory=lambda: int(os.environ.get("PORT", "8000")))

    frontend_dist: str = Field(default=str(DEFAULT_FRONTEND_DIST))

    rescan_commands: list[str] = Field(
        default_factory=lambda: [
            "{python} scripts/discover_companies.py",
            "{python} scripts/discover_topstartups.py",
            "{python} scripts/discover_yc.py",
            "{python} scripts/discover_himalayas.py",
            "{python} scripts/discover_builtin.py",
            "{python} scripts/discover_chsr.py",
            "{python} scripts/discover_awesome.py",
            "{python} scripts/discover_remote_boards.py",
            "{python} scripts/discover_startup_dirs.py",
            "{python} scripts/discover_simplify.py",
            "{python} scripts/discover_startups_gallery.py",
            "{python} scripts/discover_vc_boards.py",
            "{python} scripts/consolidate.py",
            "{python} scripts/discover_slugs.py",
        ]
    )
    rescan_step_timeout: int = Field(default=1200, ge=60, description="Per-step subprocess timeout for the rescan chain")
    rescan_step_timeouts: dict = Field(
        default_factory=lambda: {"discover_himalayas.py": 600, "discover_slugs.py": 900}
    )

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
    try:
        import yaml
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
    base = AppSettings()
    app_block = _load_yaml_app_block(base.abs_engine_config())
    env_keys = {k.lower() for k in os.environ if k.startswith("JOBAUTO_")}
    overrides = {k: v for k, v in app_block.items() if k.lower() not in env_keys}
    if overrides:
        return base.model_copy(update=overrides)
    return base


settings = load_settings()