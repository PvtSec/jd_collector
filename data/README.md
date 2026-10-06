# Career-page dataset

Consolidated, deduplicated list of IT/software companies (startups + mid-size tech,
**not** traditional MNCs) with their career pages and the Applicant Tracking System
(ATS) that powers each application form.

## Files

| File | What it is |
|---|---|
| `companies.json` | Master list — one object per company (see schema below) |
| `companies.csv` | Same data, flat, for spreadsheets / quick scanning |
| `ats_summary.json` | Counts by ATS + automatable total |
| `by_ats/<ats>.json` | Companies split per ATS (greenhouse.json, ashby.json, …) |
| `raw/agent*.json` | Original per-research-agent output (5 sources), pre-dedup |

## Company object schema (`companies.json`)

```jsonc
{
  "company_name": "Linear",
  "website": "https://linear.app",
  "career_page_url": "https://linear.app/careers",   // primary, best automatable URL
  "alternate_career_urls": [],                         // other URLs agents found
  "ats_type": "ashby",                                 // greenhouse|lever|ashby|smartrecruiters|workable|personio|bamboohr|workday|trinethire|onlyfy|keka|pinpoint|breezyhr|attrax|applytojob|yc|custom|unknown
  "ats_source": "url",                                 // url|verified|guess
  "ats_conflict": false,                               // agents disagreed on ATS (now resolved)
  "board_token": "linear",                             // ATS board slug, when known — enables direct API access
  "domain_hint": "devtools/SaaS",
  "source_platforms": ["yc","builtin"],
  "is_mnc_flagged": false                              // large/mid-cap, kept but not a pure startup
}
```

### `ats_source` meaning
- **url** — ATS inferred from an ATS-hosted career URL (authoritative, has `board_token`).
- **verified** — confirmed by probing the vendor's board API (Stripe, Ramp, Notion, Replit, Cursor, Hugging Face).
- **guess** — only a company-domain `/careers` page is known; the ATS slug is unknown and must be discovered before automating.

## Coverage (201 unique companies, from 227 raw entries)

| ATS | Count | Enumerable now (board slug known) | Board API / method |
|---|---:|---:|---|
| greenhouse | 72 | 59 | `boards-api.greenhouse.io/v1/boards/{token}/jobs` (public, no auth) |
| ashby | 33 | 32 | SSR `jobs.ashbyhq.com/{token}` → parse `window.__appData` (posting-api is authed) |
| lever | 23 | 20 | `api.lever.co/v0/postings/{token}?mode=json` (public) |
| smartrecruiters | 3 | 3 | `api.smartrecruiters.com/v1/companies/{slug}/postings` (slug = lowercased name) |
| workable | 2 | 2 | `POST apply.workable.com/api/v3/accounts/{token}/jobs` (no captcha — full HTTP apply possible) |
| custom | 39 | 0 | per-site scraping needed |
| unknown | 8 | 0 | needs discovery |
| yc | 9 | 0 | `ycombinator.com/companies/{name}/jobs` (shared YC platform) |
| workday / breezyhr / personio / bamboohr / trinethire / onlyfy / keka / pinpoint / attrax / applytojob | 1–2 each | 0 | varies |

**116 companies are enumerable now** (113 with a confirmed board slug + 3 SmartRecruiters
via derived slug). Slug discovery recovered 35 companies and corrected several wrong
ATS guesses (e.g. Linear/Supabase/Posh were greenhouse-guessed but are actually Ashby).

### `ats_source` values
- **url** (90) — ATS inferred from an ATS-hosted career URL (authoritative).
- **discovered** (35) — slug + ATS confirmed by `scripts/discover_slugs.py` probing the public board APIs.
- **verified** (6) — confirmed by manual board-API probe (Stripe, Ramp, Notion, Replit, Cursor, Hugging Face).
- **guess** (70) — only a company-domain `/careers` page is known; slug/ATS still unconfirmed.

## Files added by discovery
- `discovered_slugs.json` — output of `scripts/discover_slugs.py` (company → confirmed ATS + slug + job count).
- `research/ats_schemas/{greenhouse,lever,ashby,smartrecruiters,workable}.md` — per-ATS application-form schemas (fields, custom questions, resume upload, submit endpoint, captcha, worked curl). Key result: Greenhouse/Lever/Ashby require a real browser for submission (reCAPTCHA Enterprise / hCaptcha); Workable is captcha-free and fully HTTP-automatable; SmartRecruiters public apply is Arkose-gated.

## How it was built
`scripts/consolidate.py` reads `raw/agent*.json` + `discovered_slugs.json`, dedups by
normalized company name + website domain, infers the authoritative ATS from the
career-URL host, prefers ATS-hosted board URLs over company `/careers` pages, resolves
ATS conflicts via the `VERIFIED` dict, and merges discovered slugs. Writes all output
files. Re-run anytime: `python3 scripts/consolidate.py`. Re-discover slugs:
`python3 scripts/discover_slugs.py`.

## Caveats
- `guess`-sourced rows may have the wrong ATS — verify before bulk-apply.
- A few `website`/`domain_hint` values are best-effort inferences from the source agents.
- `is_mnc_flagged` is a coarse heuristic; refine as needed.
- Career URLs drift (companies switch ATS). The board-API probe pattern in
  `consolidate.py` (`VERIFIED` dict) is the way to re-verify.