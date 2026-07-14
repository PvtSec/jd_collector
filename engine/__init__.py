"""job_auto engine — automated job application framework.

Read-only job enumeration + matching is implemented here. Actual application
submission lives in `engine/submit/` (per-ATS) and is gated behind
`config.safety.dry_run` — it is NOT enabled by default.
"""
__version__ = "0.1.0"