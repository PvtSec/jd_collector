#!/usr/bin/env python3
from __future__ import annotations
import argparse
import concurrent.futures
import re
import sqlite3
import sys
import urllib.request
import urllib.error
import ssl
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # so `import engine.boards` works
import engine.boards as boards  # noqa: E402

DB = HERE.parent / "data" / "discovery" / "discovery.db"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ATS validated via engine enumerator (token = slug)
ENUM_ATS = {"greenhouse", "lever", "ashby", "workable",
            "smartrecruiters", "rippling", "teamtailor"}
# ATS validated via direct HTTP
DIRECT_ATS = {"personio", "breezyhr"}

DEAD_MARK = "dead-404"


def slug_for(ats: str, url: str) -> str | None:
    u = (url or "").rstrip("/").lower()
    try:
        if ats == "greenhouse":
            m = re.search(r"greenhouse\.io/([^/?#]+)", u)
        elif ats == "lever":
            m = re.search(r"jobs\.lever\.co/([^/?#]+)", u)
        elif ats == "ashby":
            m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", u)
        elif ats == "workable":
            m = re.search(r"apply\.workable\.com/([^/?#]+)", u)
        elif ats == "smartrecruiters":
            m = re.search(r"(?:jobs|careers)\.smartrecruiters\.com/([^/?#]+)", u)
        elif ats == "rippling":
            m = re.search(r"ats\.rippling\.com/([^/?#]+)", u)
        elif ats == "teamtailor":
            m = re.search(r"https?://([^./]+)\.teamtailor\.com", u)
        elif ats == "personio":
            m = re.search(r"https?://([^./]+)\.jobs\.personio\.com", u)
        elif ats == "breezyhr":
            m = re.search(r"https?://([^./]+)\.breezy\.hr", u)
        else:
            return None
        return m.group(1) if m else None
    except Exception:
        return None


def verdict_enum(ats: str, company: str, slug: str) -> str:
    fn = boards.CLIENTS[ats]
    try:
        gen = fn(company, slug, ua=UA, timeout=8, retries=0)
        next(gen)  # triggers first request; got >=1 job -> live
        return "live"
    except StopIteration:
        return "live"  # board exists, 0 open jobs
    except boards.BoardError as e:
        msg = str(e).lower()
        if "404" in msg or "not found" in msg:
            return "dead"
        return "unknown"  # request failed / unexpected -> don't drop
    except Exception:
        return "unknown"


def verdict_direct(ats: str, slug: str) -> str:
    if ats == "personio":
        url = f"https://{slug}.jobs.personio.com/xml?language=en"
    else:  # breezyhr
        url = f"https://{slug}.breezy.hr/"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as r:
            return "live"
    except urllib.error.HTTPError as e:
        return "dead" if e.code in (404, 410) else "unknown"
    except Exception:
        return "unknown"


def validate(row, conn_lock):
    nkey, name, ats, url = row
    slug = slug_for(ats, url)
    if not slug:
        return (ats, "no-slug")
    if ats in ENUM_ATS:
        v = verdict_enum(ats, name, slug)
    else:
        v = verdict_direct(ats, slug)
    if v == "dead":
        with conn_lock:
            conn = sqlite3.connect(str(DB))
            conn.execute(
                "UPDATE companies SET reliable=0, http_status=? WHERE norm_key=?",
                (DEAD_MARK, nkey))
            conn.commit()
            conn.close()
    return (ats, v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="N per ATS (0=all)")
    ap.add_argument("--workers", type=int, default=40)
    a = ap.parse_args()

    conn = sqlite3.connect(str(DB))
    targets = sorted(ENUM_ATS | DIRECT_ATS)
    rows_by_ats = {}
    for ats in targets:
        rs = conn.execute(
            "SELECT norm_key,name,ats_type,career_page_url FROM companies "
            "WHERE reliable=1 AND ats_type=? AND http_status NOT LIKE 'dead%' "
            "AND career_page_url!=''", (ats,)).fetchall()
        if a.sample:
            import random
            random.seed(hash(ats) & 0xffff)
            rs = random.sample(rs, min(a.sample, len(rs)))
        rows_by_ats[ats] = rs
    conn.close()

    total = sum(len(v) for v in rows_by_ats.values())
    print(f"validating {total} boards across {len(targets)} ATS "
          f"(workers={a.workers})", flush=True)

    from collections import Counter
    counts = Counter()
    dead_by_ats = Counter()
    import threading
    lock = threading.Lock()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futmap = {}
        for ats, rs in rows_by_ats.items():
            for r in rs:
                futmap[ex.submit(validate, r, lock)] = ats
        for fut in concurrent.futures.as_completed(futmap):
            ats = futmap[fut]
            try:
                _, v = fut.result()
            except Exception:
                v = "unknown"
            counts[(ats, v)] += 1
            if v == "dead":
                dead_by_ats[ats] += 1
            done += 1
            if done % 500 == 0:
                print(f"  ...{done}/{total}  dead so far={sum(dead_by_ats.values())}", flush=True)

    print("\n=== RESULTS ===")
    for ats in targets:
        live = counts[(ats, "live")]
        dead = counts[(ats, "dead")]
        unk = counts[(ats, "unknown")]
        nos = counts[(ats, "no-slug")]
        print(f"  {ats:16s} live={live:5d} dead={dead:5d} unknown={unk:5d} no-slug={nos}")
    print(f"  TOTAL dead marked unreliable: {sum(dead_by_ats.values())}")
    conn = sqlite3.connect(str(DB))
    rc = conn.execute("SELECT COUNT(*) FROM companies WHERE reliable=1").fetchone()[0]
    print(f"  reliable_count now {rc}/50000")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())