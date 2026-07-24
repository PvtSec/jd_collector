#!/usr/bin/env python3
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "discovery" / "discovery.db"
OUT = ROOT / "data" / "raw" / "agent_discoverydb.json"


def main() -> int:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute(
        "SELECT name, website, career_page_url, ats_type "
        "FROM companies WHERE reliable=1 "
        "AND career_page_url != '' ORDER BY name"
    ).fetchall()
    conn.close()
    entries = [
        {
            "company_name": name or "",
            "career_page_url": url or "",
            "ats_type": ats or "unknown",
            "website": website or "",
        }
        for (name, website, url, ats) in rows
        if url  # need a career_page_url to be useful
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, ensure_ascii=False))
    print(f"exported {len(entries)} reliable companies -> {OUT.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())