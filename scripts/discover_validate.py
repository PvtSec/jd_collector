#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlib  # noqa: E402

RAW_DIR = dlib.ROOT / "data" / "raw"


def _load_raw() -> list[dict]:
    recs: list[dict] = []
    if not RAW_DIR.exists():
        return recs
    for fn in sorted(os.listdir(RAW_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            data = json.loads((RAW_DIR / fn).read_text())
            if isinstance(data, list):
                for r in data:
                    if isinstance(r, dict) and r.get("company_name"):
                        recs.append(r)
        except Exception:
            continue
    return recs


def _validate_one(rec: dict) -> tuple[bool, bool, str, bool]:
    try:
        return dlib.record_company(rec, recheck=False)
    except Exception:
        return False, False, "unknown", False


def run(concurrency: int = 16, limit: int = 0) -> dict:
    dlib.init_db()
    dlib.ensure_log()
    recs = _load_raw()
    if limit:
        recs = recs[:limit]
    new = 0
    new_reliable = 0
    upgraded = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_validate_one, r): r for r in recs}
        for fut in as_completed(futs):
            is_new, is_reliable, hstatus, became = fut.result()
            if is_new:
                new += 1
                if is_reliable:
                    new_reliable += 1
                    dlib.append_log("validate", futs[fut], hstatus)
            elif became:
                upgraded += 1
                dlib.append_log("validate-upgrade", futs[fut], hstatus)
    snap = dlib.snapshot()
    dlib.save_progress({**snap, "phase": "running",
                        "last_validate": {"new": new, "new_reliable": new_reliable,
                                          "upgraded": upgraded, "secs": round(time.time() - t0, 1)}})
    return {"scanned": len(recs), "new": new, "new_reliable": new_reliable,
            "upgraded": upgraded, "reliable_count": snap["reliable_count"],
            "total_unique": snap["total_unique"], "secs": round(time.time() - t0, 1)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Validate raw -> discovery.db + log")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="cap records (debug)")
    a = ap.parse_args()
    print(json.dumps(run(a.concurrency, a.limit), indent=2))