# 50K Company Fan-out — Discovery Run & Resume Guide

Goal: enrich `data/companies.json` with ~50,000 NEW genuine companies (and their job
listing endpoints where discoverable). **No recruiters / aggregators / staffing firms.**

## How it works

1. **Plan** — `plan.json` holds the 32 source slots (id, tag, method, source, goal):
   21 Wikidata SPARQL (region + industry), 6 GitHub ATS-URL datasets, 3 startup
   directories, 2 Wikipedia/open-data lists.
2. **Per slot** — a discovery agent fetches a REAL source, writes a raw file
   `data/raw/agentfNN_<tag>.json`, then runs `scripts/_fanout/dedup_new.py` which:
   - dedups vs the existing ~56,520 companies (by normalized name + real website domain),
   - drops middlemen (denylist) + generic ATS slugs + junk URLs,
   - infers `ats_type` from the URL,
   - writes a **resume marker** `data/raw/_fanout/done/agentfNN_<tag>.json.json`
     with `{kept_new, automatable, ats_counts, ...}`.
3. **Consolidate** — `scripts/consolidate.py` ingests every `data/raw/*.json`, merges
   by normalized name (cross-slot dups collapse here), and rewrites `companies.json`.
4. **Index** — `existing_index.json` is the cached set of existing normalized names +
   real domains (ATS-vendor apices like greenhouse.io excluded, so ATS-hosted companies
   are never falsely deduped). Rebuild by deleting it (auto-rebuilt on next helper run).

## Live track log / progress

Per-slot status = the marker files in `data/raw/_fanout/done/`. Quick status:

```bash
cd /mnt/380/Projects/job_auto/repo
python3 - <<'PY'
import json, glob, os
plan = {s['id']: s for s in json.load(open('data/raw/_fanout/plan.json'))}
done = {}
for f in glob.glob('data/raw/_fanout/done/*.json'):
    d = json.load(open(f)); done[d['file']] = d
tot_new = sum(d.get('kept_new',0) for d in done.values())
tot_auto = sum(d.get('automatable',0) for d in done.values())
print(f"slots done: {len(done)}/32   rows kept_new={tot_new}  automatable={tot_auto}")
PY
```

## Resume after interruption

The raw files + markers are the source of truth and survive a session restart.

1. Compute which slots are NOT yet done:
   ```bash
   python3 - <<'PY'
   import json, glob, os
   plan = json.load(open('data/raw/_fanout/plan.json'))
   done = {os.path.basename(f)[:-5] for f in glob.glob('data/raw/_fanout/done/*.json')}
   # marker filename = "<rawfile>.json"; rawfile = "agentfNN_<tag>.json" -> marker = that + ".json"
   remaining = [s for s in plan if f"agentf{int(s['id'][1:]):02d}_{s['tag']}.json.json" not in done]
   json.dump(remaining, open('data/raw/_fanout/_remaining.json','w')); print('remaining:', len(remaining))
   for s in remaining: print(' ', s['id'], s['tag'])
   PY
   ```
2. Re-launch the workflow passing `data/raw/_fanout/_remaining.json` contents as the
   workflow `args` (array of slot objects). The workflow script is
   `scripts/_fanout/fanout_workflow.js`.
3. After all slots are done, run `python3 scripts/consolidate.py` and check the
   `Unique companies` line vs the prior 56,520 baseline for the net-new count.

## Files

- `plan.json` — the 32 slots (source of truth for slot definitions).
- `done/` — per-slot resume markers (one JSON per completed raw file).
- `existing_index.json` — cached existing-company index (names + real domains).
- `../../scripts/_fanout/dedup_new.py` — the dedup/denylist/infer helper.
- `../../scripts/_fanout/fanout_workflow.js` — the orchestration script.
