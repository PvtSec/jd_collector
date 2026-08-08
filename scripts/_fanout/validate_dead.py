#!/usr/bin/env python3
import json, sys, os, time, threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "/app")
import engine.boards as boards

COMPANIES = "/app/data/companies.json"
OUTDIR = "/app/data/raw/_fanout"
OUT = OUTDIR + "/dead_boards.json"
OUT_JSONL = OUTDIR + "/dead_boards.jsonl"
os.makedirs(OUTDIR, exist_ok=True)
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PROBE_ATS = {"greenhouse", "lever", "ashby", "personio", "rippling", "teamtailor"}

def token_for(c):
    ats = c.get("ats_type"); name = c.get("company_name", "")
    if ats == "smartrecruiters":
        return "".join(ch for ch in name.lower() if ch.isalnum()) or None
    if ats == "workday":
        return c.get("career_page_url") or c.get("board_token") or None
    return c.get("board_token") or None

def verdict(ats, name, token):
    try:
        gen = boards.CLIENTS[ats](name, token, ua=UA, timeout=8, retries=0)
        next(gen); return "live"
    except StopIteration:
        return "live"
    except boards.BoardError as e:
        m = str(e).lower()
        return "dead" if ("404" in m or "not found" in m) else "unknown"
    except Exception:
        return "unknown"

def main():
    comps = json.load(open(COMPANIES))
    targets = [(i, c.get("ats_type"), c.get("company_name", ""), tok)
               for i, c in enumerate(comps)
               if c.get("ats_type") in PROBE_ATS and (tok := token_for(c))]
    print(f"probing {len(targets)} boards across {sorted(PROBE_ATS)} (48 workers)", flush=True)

    dead = []
    counts = Counter(); dead_by_ats = Counter()
    lock = threading.Lock()
    jlf = open(OUT_JSONL, "w")
    t0 = time.time(); done = 0
    with ThreadPoolExecutor(max_workers=48) as ex:
        futs = {ex.submit(verdict, ats, name, tok): (i, ats) for (i, ats, name, tok) in targets}
        for fut in as_completed(futs):
            i, ats = futs[fut]
            try: v = fut.result()
            except Exception: v = "unknown"
            counts[(ats, v)] += 1
            if v == "dead":
                with lock:
                    dead.append(i); dead_by_ats[ats] += 1
                    jlf.write(json.dumps({"i": i, "ats": ats,
                                          "name": comps[i]["company_name"],
                                          "url": comps[i].get("career_page_url", "")}) + "\n")
                    jlf.flush()
            done += 1
            if done % 1000 == 0:
                el = time.time() - t0; rate = done / el
                eta = (len(targets) - done) / rate if rate else 0
                print(f"  ...{done}/{len(targets)}  dead={sum(dead_by_ats.values())}  "
                      f"({rate:.0f}/s, eta~{eta:.0f}s)", flush=True)
    jlf.close()

    print("\n=== RESULTS ===", flush=True)
    for ats in sorted(PROBE_ATS):
        print(f"  {ats:14s} live={counts[(ats,'live')]:5d} dead={counts[(ats,'dead')]:5d} "
              f"unknown={counts[(ats,'unknown')]:5d}", flush=True)
    print(f"  TOTAL dead = {len(dead)}", flush=True)

    dead_names = sorted({comps[i]["company_name"] for i in dead})
    json.dump({"dead_count": len(dead), "dead_by_ats": dict(dead_by_ats),
               "names": dead_names, "indices": dead},
              open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"\nwrote {OUT} ({len(dead_names)} dead companies) + {OUT_JSONL}", flush=True)

if __name__ == "__main__":
    main()
