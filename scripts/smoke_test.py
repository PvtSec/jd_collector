"""End-to-end smoke test for the running dashboard. Run inside the container:

    docker compose exec job-auto python scripts/smoke_test.py

Uses a sentinel company namespace (zzsmoketestzz); cleans up all three stores (jobs DB,
applied ledger, state.json) in a finally block and hard-fails on any residue.
Exit 0 = all checks passed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.backend.src import persist
from app.backend.src.settings import settings
from engine.config import Config

BASE = "http://127.0.0.1:8000"
# no '_' or '%' in these — the API's q filter is a raw LIKE, where _ and % are wildcards
COMPANY = "zzsmoketestzz"
TAG = f"zz{int(time.time() * 1000)}zz"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def http(method: str, path: str) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def cfg_ledger_path() -> str:
    cfg = Config.load(settings.abs_engine_config())
    p = cfg.ledger_db
    if not os.path.isabs(p):
        p = os.path.join(os.path.dirname(settings.abs_engine_config()), p)
    return p


def jobs_conn() -> sqlite3.Connection:
    c = sqlite3.connect(settings.abs_jobs_db(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def ledger_conn() -> sqlite3.Connection:
    c = sqlite3.connect(cfg_ledger_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def clean_state() -> None:
    # one retry if record_scan interleaves (detected via updated_at change)
    for _ in range(2):
        state = persist._read(settings.abs_state_file())
        before = state.get("updated_at")
        state["applied"] = [a for a in state.get("applied", []) if a.get("company") != COMPANY]
        state["hidden"] = [h for h in state.get("hidden", []) if h.get("company") != COMPANY]
        if state.get("updated_at") == before:
            persist._write(settings.abs_state_file(), state)
            return
    persist._write(settings.abs_state_file(), state)


def clean_stores() -> None:
    with jobs_conn() as c:
        c.execute("DELETE FROM jobs WHERE company=?", (COMPANY,))
    with ledger_conn() as c:
        c.execute("DELETE FROM applications WHERE company=?", (COMPANY,))
    clean_state()


def main() -> int:
    clean_stores()
    jid = None
    try:
        code, health = http("GET", "/api/health")
        check("health 200+ok", code == 200 and isinstance(health, dict) and health.get("ok") is True)
        check("health jobs>=1", isinstance(health, dict) and int(health.get("jobs", 0)) >= 1,
              f"jobs={health if isinstance(health, dict) else health}")

        code, s = http("GET", "/api/stats")
        ok = code == 200 and isinstance(s, dict)
        check("stats 200", ok)
        if ok:
            check("stats ranges",
                  isinstance(s.get("total"), int) and s["total"] >= 1
                  and isinstance(s.get("matched"), int) and 0 <= s["matched"] <= s["total"]
                  and isinstance(s.get("applied"), int) and s["applied"] >= 0
                  and isinstance(s.get("closed"), int) and s["closed"] >= 0
                  and isinstance(s.get("by_ats"), dict) and len(s["by_ats"]) >= 1
                  and "last_run" in s and "sweep" in s,
                  json.dumps({k: s.get(k) for k in ("total", "matched", "applied", "closed")}))
            print(f"       stats: total={s.get('total')} matched={s.get('matched')} "
                  f"applied={s.get('applied')} closed={s.get('closed')}")

        code, r = http("GET", "/api/jobs?limit=5")
        check("jobs default page", code == 200 and isinstance(r, dict)
              and r.get("count") == len(r.get("items", [])) <= 5 and r.get("total", 0) >= r["count"])

        code, r = http("GET", "/api/jobs?matched=true&limit=3")
        items = r.get("items", []) if isinstance(r, dict) else []
        check("matched view contract", code == 200
              and all(i["matched"] == 1 and i["closed"] == 0 and i["hidden"] == 0 for i in items))

        code, r = http("GET", "/api/jobs?applied=true&limit=3")
        items = r.get("items", []) if isinstance(r, dict) else []
        check("applied filter", code == 200 and all(i["applied"] == 1 for i in items))

        code, r = http("GET", "/api/jobs?closed=only&limit=3")
        items = r.get("items", []) if isinstance(r, dict) else []
        check("closed=only filter", code == 200 and all(i["closed"] == 1 for i in items))

        p0 = http("GET", "/api/jobs?matched=true&limit=3&offset=0")
        p1 = http("GET", "/api/jobs?matched=true&limit=3&offset=1")
        ok = p0[0] == 200 and p1[0] == 200 and p0[1]["total"] == p1[1]["total"]
        if ok and p0[1]["total"] > 1 and p0[1]["items"] and p1[1]["items"]:
            ok = p0[1]["items"][0]["id"] != p1[1]["items"][0]["id"]
        check("paging offset consistency", ok)

        code, r = http("GET", "/api/demand?limit=50")
        rows = r.get("rows", []) if isinstance(r, dict) else []
        counts = [x["count"] for x in rows]
        check("demand shape+sorted", code == 200 and isinstance(r.get("analyzed"), int)
              and counts == sorted(counts, reverse=True)
              and all(set(x) >= {"skill", "category", "count"} for x in rows))
        print(f"       demand: analyzed={r.get('analyzed')} rows={len(rows)}")

        now = time.time()
        with jobs_conn() as c:
            cur = c.execute(
                "INSERT INTO jobs(company, ats, job_id, title, location, work_type, url, "
                "posted_at, first_seen, last_seen, last_check, matched) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                (COMPANY, "smoke", TAG, "smoke test job", "remote", "remote",
                 f"https://example.com/{TAG}", "", now, now, now),
            )
            jid = cur.lastrowid

        code, j = http("GET", f"/api/jobs/{jid}")
        check("detail before applied", code == 200 and j.get("company") == COMPANY
              and j.get("applied") == 0)

        code, res = http("POST", f"/api/jobs/{jid}/mark-applied")
        check("mark-applied ok", code == 200 and isinstance(res, dict) and res.get("ok") is True)

        with jobs_conn() as c:
            applied = c.execute("SELECT applied FROM jobs WHERE id=?", (jid,)).fetchone()[0]
        check("applied in jobs DB", applied == 1)

        with ledger_conn() as c:
            lrows = c.execute("SELECT job_id FROM applications WHERE company=?", (COMPANY,)).fetchall()
        check("applied in ledger", len(lrows) == 1 and lrows[0][0] == TAG,
              f"ledger rows={[dict(x) for x in lrows]}")

        st = persist._read(settings.abs_state_file())
        srecs = [a for a in st.get("applied", []) if a.get("company") == COMPANY]
        check("applied in state.json", len(srecs) == 1 and srecs[0].get("job_id") == TAG)

        code, r = http("GET", f"/api/jobs?applied=true&q={COMPANY}")
        check("applied visible via API", code == 200 and r.get("total") == 1
              and r["items"] and r["items"][0]["id"] == jid and r["items"][0]["applied"] == 1)

        code, res = http("POST", f"/api/jobs/{jid}/hide")
        check("hide ok", code == 200 and isinstance(res, dict) and res.get("ok") is True)

        with jobs_conn() as c:
            hidden = c.execute("SELECT hidden FROM jobs WHERE id=?", (jid,)).fetchone()[0]
        check("hidden in jobs DB", hidden == 1)

        st = persist._read(settings.abs_state_file())
        hrecs = [h for h in st.get("hidden", []) if h.get("company") == COMPANY]
        check("hidden in state.json", len(hrecs) == 1 and hrecs[0].get("job_id") == TAG)

        code, r = http("GET", f"/api/jobs?q={COMPANY}")
        check("hidden excluded from view", code == 200 and r.get("total") == 0)
    finally:
        clean_stores()

    with jobs_conn() as c:
        n_jobs = c.execute("SELECT COUNT(*) FROM jobs WHERE company=?", (COMPANY,)).fetchone()[0]
    with ledger_conn() as c:
        n_ledger = c.execute("SELECT COUNT(*) FROM applications WHERE company=?", (COMPANY,)).fetchone()[0]
    st = persist._read(settings.abs_state_file())
    residue = (len([a for a in st.get("applied", []) if a.get("company") == COMPANY])
               + len([h for h in st.get("hidden", []) if h.get("company") == COMPANY]))
    code, r = http("GET", f"/api/jobs?q={COMPANY}")
    check("zero residue", n_jobs == 0 and n_ledger == 0 and residue == 0
          and code == 200 and r.get("total") == 0)

    print(f"\n{'ALL PASS' if not failures else 'FAILURES: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
