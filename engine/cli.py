from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from .config import Config
from .boards import CLIENTS, Job, BoardError, parse_posted
from .match import matches
from . import ledger


def _load_companies(cfg: Config) -> list[dict]:
    with open(cfg.companies_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _companies_filtered(cfg: Config, ats: str | None) -> list[dict]:
    comps = _load_companies(cfg)
    if ats:
        comps = [c for c in comps if c["ats_type"] == ats]
    if cfg.allow_companies:
        allow = {a.lower() for a in cfg.allow_companies}
        comps = [c for c in comps if c["company_name"].lower() in allow]
    if cfg.skip_companies:
        skip = {s.lower() for s in cfg.skip_companies}
        comps = [c for c in comps if c["company_name"].lower() not in skip]
    out = []
    for c in comps:
        if c["ats_type"] not in CLIENTS:
            continue
        token = c.get("board_token")
        if c["ats_type"] == "smartrecruiters":
            # SR board slugs are the lowercased company name; guess rows carry a
            # junk path-segment token (e.g. "company"/"about"), so always derive.
            token = "".join(ch for ch in c["company_name"].lower() if ch.isalnum())
        if token:
            c = dict(c, board_token=token)
            out.append(c)
    return out


def cmd_list_companies(cfg: Config, args):
    comps = _load_companies(cfg)
    if args.ats:
        comps = [c for c in comps if c["ats_type"] == args.ats]
    print(f"{'COMPANY':<28} {'ATS':<16} {'TOKEN':<22} {'SRC':<9} DOMAIN")
    print("-" * 90)
    for c in comps:
        print(f"{c['company_name']:<28} {c['ats_type']:<16} {str(c.get('board_token') or ''):<22} "
              f"{c['ats_source']:<9} {c.get('domain_hint','')}")
    print(f"\n{len(comps)} companies" + (f" on {args.ats}" if args.ats else ""))


def cmd_jobs(cfg: Config, args):
    comps = _companies_filtered(cfg, args.ats)
    if args.company:
        name = args.company.lower()
        comps = [c for c in comps if c["company_name"].lower() == name]
    if not comps:
        print("No enumerable companies matched. Check --ats / --company / allow_companies.")
        return

    sort = getattr(args, "sort", "board") or "board"
    days = getattr(args, "days", None)
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    total_seen = 0
    total_matched = 0
    per_ats: dict[str, int] = {}
    rows: list[tuple[Job, dict]] = []  # (job, company_dict)
    for c in comps:
        ats = c["ats_type"]
        token = c["board_token"]
        client = CLIENTS[ats]
        try:
            jobs = list(client(c["company_name"], token,
                               ua=cfg.user_agent, timeout=cfg.http_timeout, retries=cfg.http_retries))
        except BoardError as e:
            print(f"[skip] {c['company_name']:<24} {ats:<10} {e}")
            continue
        per_ats[ats] = per_ats.get(ats, 0) + len(jobs)
        total_seen += len(jobs)
        for j in jobs:
            ok, _ = matches(j, cfg.target)
            if not ok:
                continue
            if cutoff:
                pd = parse_posted(j.posted_at)
                if pd is None or pd < cutoff:
                    continue
            rows.append((j, c))
            total_matched += 1
            if args.limit and total_matched >= args.limit:
                break
        if args.limit and total_matched >= args.limit:
            break

    def _posted_key(j: Job) -> float:
        pd = parse_posted(j.posted_at)
        if pd is None:
            return float("-inf")
        if pd.tzinfo is None:
            pd = pd.replace(tzinfo=timezone.utc)
        return pd.timestamp()

    def _line(j: Job, c: dict) -> str:
        pd = parse_posted(j.posted_at)
        pdstr = pd.strftime("%Y-%m-%d") if pd else "—"
        return (f"  - {j.title}  (posted {pdstr})  "
                f"[{j.location or '—'} / {j.work_type or '—'}]")

    if sort == "recent":
        rows.sort(key=lambda r: _posted_key(r[0]), reverse=True)
        for j, c in rows:
            print(f"[{c['company_name']}] {_line(j, c)}")
            print(f"    {j.url}")
    else:
        # group by company, preserving first-seen order
        by_company: dict[str, list[Job]] = {}
        order: list[str] = []
        c_ref: dict[str, dict] = {}
        for j, c in rows:
            nm = c["company_name"]
            if nm not in by_company:
                by_company[nm] = []
                order.append(nm)
                c_ref[nm] = c
            by_company[nm].append(j)
        for nm in order:
            jobs = by_company[nm]
            print(f"\n# {nm} ({c_ref[nm]['ats_type']}, {len(jobs)} matched)")
            for j in jobs:
                print(_line(j, c_ref[nm]))
                print(f"    {j.url}")

    print(f"\n--- {total_seen} jobs seen across {len(comps)} companies; {total_matched} matched"
          + (f" (last {days} days)" if days else "")
          + (f" sorted by recent" if sort == "recent" else "") + " ---")
    for a, n in sorted(per_ats.items(), key=lambda kv: -kv[1]):
        print(f"  {a:<16} {n} open")


def cmd_stats(cfg: Config, args):
    comps = _load_companies(cfg)
    from collections import Counter
    by = Counter(c["ats_type"] for c in comps)
    automatable = sum(1 for c in comps if c.get("board_token"))
    print(f"Companies in dataset : {len(comps)}")
    print(f"Automatable (token)  : {automatable}")
    print("By ATS:")
    for a, n in sorted(by.items(), key=lambda kv: -kv[1]):
        print(f"  {a:<16} {n}")
    if os.path.exists(cfg.ledger_db):
        with ledger.connect(cfg.ledger_db) as conn:
            st = ledger.stats(conn)
        if st:
            print("\nLedger:")
            for k, v in st.items():
                print(f"  {k:<24} {v}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="job-auto", description="centralized job-search centre")
    p.add_argument("-c", "--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    lc = sub.add_parser("list-companies", help="list companies in dataset")
    lc.add_argument("--ats"); lc.set_defaults(func=cmd_list_companies)

    j = sub.add_parser("jobs", help="enumerate + filter open jobs (read-only)")
    j.add_argument("--ats"); j.add_argument("--company")
    j.add_argument("--limit", type=int, default=50)
    j.add_argument("--sort", choices=["board", "recent"], default="board",
                   help="board=group by company (default); recent=newest posted_at first")
    j.add_argument("--days", type=int, default=None,
                   help="only jobs posted within the last N days (requires posted_at)")
    j.set_defaults(func=cmd_jobs)

    s = sub.add_parser("stats", help="dataset + ledger stats")
    s.set_defaults(func=cmd_stats)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg_path = args.config
    if not os.path.exists(cfg_path):
        # fall back to example config so CLI is runnable before user edits
        cfg_path = "config.example.yaml"
    cfg = Config.load(cfg_path)
    args.func(cfg, args)


if __name__ == "__main__":
    main()