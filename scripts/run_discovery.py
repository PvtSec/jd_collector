#!/usr/bin/env python3
"""run_discovery.py — launcher for the 50k-company scaling effort.

Commands:
  status    print reliable_count vs 50000 + total_unique + last validate
  gather    run the durable discover_*.py source-workers concurrently (cohort A)
  validate  run discover_validate.py (raw -> discovery.db + log.md)
  run       gather + validate (one wave); repeat-safe, idempotent
  process   once reliable_count >= 50000: consolidate.py + ./run.sh up

Cohort B (live LLM web-search agents) are launched from the Claude session
via the Agent tool, NOT here — they record finds directly through dlib. This
launcher handles the durable side + the final processing step.

Resumable: all state lives in data/discovery/ (discovery.db, progress.json,
log.md). A fresh session: `python scripts/run_discovery.py status` then
`... run`, and relaunch cohort B agents over remaining partitions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlib  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Cohort A — durable source-workers. Each writes a distinct data/raw/agentN_*.json
# so they are safe to run concurrently. New discoverN_*.py workers are added as
# they are written; missing files are skipped with a warning.
GATHER_SCRIPTS = [
    "discover_simplify.py",
    "discover_remote_boards.py",
    "discover_himalayas.py",
    "discover_companies.py",
    "discover_awesome.py",
    "discover_vc_boards.py",
    "discover_startups_gallery.py",
    "discover_topstartups.py",
    "discover_yc.py",
    "discover_builtin.py",
    "discover_chsr.py",
    "discover_startup_dirs.py",
    "discoverN_greenhouse_dir.py",
    "discoverN_lever_dir.py",
    "discoverN_ashby_dir.py",
    "discoverN_otta.py",
    "discoverN_wellfound.py",
    "discoverN_stocklist.py",
]
PER_STEP_TIMEOUT = 1200  # seconds per gather script (matches rescan cap)


def cmd_status() -> None:
    snap = dlib.snapshot()
    gap = max(0, dlib.GOAL - snap["reliable_count"])
    pct = round(100 * snap["reliable_count"] / dlib.GOAL, 1)
    print(f"reliable_count: {snap['reliable_count']} / {dlib.GOAL}  ({pct}%)  gap={gap}")
    print(f"total_unique:   {snap['total_unique']}")
    print(f"phase:          {snap.get('phase')}")
    print(f"last_updated:   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snap['last_updated']))}")
    lv = snap.get("last_validate")
    if lv:
        print(f"last_validate:  new={lv.get('new')} new_reliable={lv.get('new_reliable')} "
              f"upgraded={lv.get('upgraded')} secs={lv.get('secs')}")
    if snap["reliable_count"] >= dlib.GOAL:
        print("GOAL REACHED — run: python scripts/run_discovery.py process")


def _run_gather_one(script: str) -> dict:
    path = HERE / script
    if not path.exists():
        return {"script": script, "ok": False, "skipped": "not written yet",
                "secs": 0, "out": ""}
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(path)], cwd=str(ROOT),
            capture_output=True, text=True, timeout=PER_STEP_TIMEOUT)
        return {"script": script, "ok": r.returncode == 0,
                "secs": round(time.time() - t0, 1),
                "out": (r.stdout or "")[-2000:], "err": (r.stderr or "")[-1000:]}
    except subprocess.TimeoutExpired:
        return {"script": script, "ok": True, "timeout": True,
                "secs": PER_STEP_TIMEOUT, "out": "timed out (partial ok)"}
    except Exception as e:
        return {"script": script, "ok": False, "secs": round(time.time() - t0, 1),
                "err": str(e)}


def cmd_gather(concurrency: int = 18) -> dict:
    scripts = [s for s in GATHER_SCRIPTS if (HERE / s).exists()]
    missing = [s for s in GATHER_SCRIPTS if not (HERE / s).exists()]
    print(f"gathering {len(scripts)} durable workers (concurrency={concurrency})...")
    if missing:
        print(f"  (skipping not-yet-written: {', '.join(missing)})")
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_run_gather_one, s): s for s in scripts}
        for fut in as_completed(futs):
            res = fut.result()
            results.append(res)
            tag = "OK" if res.get("ok") else "FAIL"
            if res.get("timeout"):
                tag = "TIMEOUT(partial)"
            print(f"  [{tag}] {res['script']}  ({res['secs']}s)")
    dlib.bump_progress({"cohort_a_last_gather": {"secs": round(time.time() - t0, 1),
                                                  "results": results}})
    return {"ran": len(scripts), "missing": missing, "results": results,
            "secs": round(time.time() - t0, 1)}


def cmd_validate(concurrency: int = 16) -> dict:
    import discover_validate
    r = discover_validate.run(concurrency=concurrency)
    print(json.dumps(r, indent=2))
    return r


def cmd_run(gather_conc: int = 18, val_conc: int = 16) -> None:
    snap = dlib.snapshot()
    if snap["reliable_count"] >= dlib.GOAL:
        print("Goal already reached — run `process`.")
        return
    print("=== GATHER ===")
    cmd_gather(gather_conc)
    print("=== VALIDATE ===")
    cmd_validate(val_conc)
    snap = dlib.snapshot()
    print(f"\nreliable_count now {snap['reliable_count']} / {dlib.GOAL}")
    if snap["reliable_count"] >= dlib.GOAL:
        print("GOAL REACHED — run: python scripts/run_discovery.py process")


def cmd_process() -> int:
    snap = dlib.snapshot()
    if snap["reliable_count"] < dlib.GOAL:
        print(f"Goal not reached ({snap['reliable_count']}/{dlib.GOAL}). Refusing to process. "
              "Override with --force.")
        return 1
    print("=== CONSOLIDATE ===")
    r = subprocess.run([sys.executable, str(HERE / "consolidate.py")], cwd=str(ROOT))
    if r.returncode != 0:
        print("consolidate.py failed; aborting.")
        return r.returncode
    n = len(json.loads((ROOT / "data" / "companies.json").read_text()))
    print(f"companies.json now {n} companies")
    print("=== ./run.sh up ===")
    r2 = subprocess.run([str(ROOT / "run.sh"), "up"], cwd=str(ROOT))
    return r2.returncode


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="50k discovery launcher")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    g = sub.add_parser("gather"); g.add_argument("--concurrency", type=int, default=18)
    v = sub.add_parser("validate"); v.add_argument("--concurrency", type=int, default=16)
    rr = sub.add_parser("run")
    rr.add_argument("--gather-concurrency", type=int, default=18)
    rr.add_argument("--validate-concurrency", type=int, default=16)
    p = sub.add_parser("process"); p.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status":
        cmd_status()
    elif a.cmd == "gather":
        cmd_gather(a.concurrency)
    elif a.cmd == "validate":
        cmd_validate(a.concurrency)
    elif a.cmd == "run":
        cmd_run(a.gather_concurrency, a.validate_concurrency)
    elif a.cmd == "process":
        sys.exit(cmd_process() if not a.force else 0)