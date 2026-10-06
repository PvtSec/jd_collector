export const meta = {
  name: 'fanout-50k-discovery',
  description: 'Discover genuine companies + job endpoints across source slots (no middlemen)',
  phases: [{ title: 'Discover', detail: 'one agent per source slot — fetch real source, write raw file, dedup' }],
}

const REPO = '/mnt/380/Projects/job_auto/repo'
const HELPER = REPO + '/scripts/_fanout/dedup_new.py'
const ALL_SLOTS = [
  {
    "id": "f01",
    "tag": "wd_na",
    "title": "Wikidata North America (US/CA)",
    "method": "wikidata",
    "source": "SPARQL: business(Q4830453 or Q783793) with P856 website, P17 in {Q30 USA,Q16 Canada}; bias to tech via FILTER on English ?itemDescription/?itemLabel regex 'software|technolog|SaaS|cloud|cyber|AI|data|platform|developer|security|fintech|digital|app|internet'. Endpoint https://query.wikidata.org/sparql?format=json . Paginate OFFSET 0..15000 step 5000, LIMIT 8000/query. USA is huge: also split by P452 industry if too large.",
    "goal": "8000+"
  },
  {
    "id": "f02",
    "tag": "wd_ukie",
    "title": "Wikidata UK & Ireland",
    "method": "wikidata",
    "source": "SPARQL business+P856, P17 in {Q145 UK,Q27 Ireland}. Same tech regex bias. OFFSET paginate.",
    "goal": "4000+"
  },
  {
    "id": "f03",
    "tag": "wd_dach",
    "title": "Wikidata DACH (DE/AT/CH)",
    "method": "wikidata",
    "source": "P17 in {Q183 Germany,Q40 Austria,Q39 Switzerland}. tech regex.",
    "goal": "4000+"
  },
  {
    "id": "f04",
    "tag": "wd_benelux_fr",
    "title": "Wikidata Benelux + France",
    "method": "wikidata",
    "source": "P17 in {Q55 NL,Q31 BE,Q32 LU,Q142 FR}. tech regex.",
    "goal": "4000+"
  },
  {
    "id": "f05",
    "tag": "wd_nordics",
    "title": "Wikidata Nordics",
    "method": "wikidata",
    "source": "P17 in {Q34 SE,Q20 NO,Q79 DK,Q33 FI,Q189 IS}. tech regex.",
    "goal": "3000+"
  },
  {
    "id": "f06",
    "tag": "wd_iberia_it",
    "title": "Wikidata Iberia + Italy + Greece",
    "method": "wikidata",
    "source": "P17 in {Q29 ES,Q45 PT,Q38 IT,Q233 MT,Q41 GR}. tech regex.",
    "goal": "4000+"
  },
  {
    "id": "f07",
    "tag": "wd_cee",
    "title": "Wikidata Central/Eastern Europe",
    "method": "wikidata",
    "source": "P17 in {Q36 PL,Q213 CZ,Q214 SK,Q28 HU,Q218 RO,Q227 BG,Q224 HR,Q404 SI,Q212 UA,Q37 LT,Q211 LV,Q191 EE}. tech regex.",
    "goal": "4000+"
  },
  {
    "id": "f08",
    "tag": "wd_india",
    "title": "Wikidata India",
    "method": "wikidata",
    "source": "P17 Q668 India. tech regex; India is large, paginate up to 12k.",
    "goal": "5000+"
  },
  {
    "id": "f09",
    "tag": "wd_asean",
    "title": "Wikidata ASEAN",
    "method": "wikidata",
    "source": "P17 in {Q334 SG,Q833 MY,Q252 ID,Q881 VN,Q869 TH,Q928 PH,Q424 KH,Q836 MM}. tech regex.",
    "goal": "3000+"
  },
  {
    "id": "f10",
    "tag": "wd_easia",
    "title": "Wikidata Greater China + JP + KR",
    "method": "wikidata",
    "source": "P17 in {Q148 CN,Q865 TW,Q8646 HK,Q17 JP,Q884 KR}. tech regex. Many JP/KR entries have romanized sites.",
    "goal": "4000+"
  },
  {
    "id": "f11",
    "tag": "wd_anz",
    "title": "Wikidata ANZ + Pacific",
    "method": "wikidata",
    "source": "P17 in {Q408 AU,Q664 NZ,Q712 FJ}. tech regex.",
    "goal": "2000+"
  },
  {
    "id": "f12",
    "tag": "wd_latam",
    "title": "Wikidata LATAM",
    "method": "wikidata",
    "source": "P17 in {Q155 BR,Q96 MX,Q414 AR,Q298 CL,Q739 CO,Q77 UY,Q419 PE,Q800 CR}. tech regex.",
    "goal": "3000+"
  },
  {
    "id": "f13",
    "tag": "wd_mena_africa",
    "title": "Wikidata MENA + Africa",
    "method": "wikidata",
    "source": "P17 in {Q878 AE,Q851 SA,Q801 IL,Q43 TR,Q79 EG,Q1028 MA,Q810 JO,Q258 ZA,Q1033 NG,Q114 KE,Q117 GH}. tech regex.",
    "goal": "3000+"
  },
  {
    "id": "f14",
    "tag": "wd_cyber",
    "title": "Wikidata cybersecurity companies (global)",
    "method": "wikidata",
    "source": "SPARQL global: ?item P31/P279* in security classes OR P452 industry ~ 'computer security'/'cybersecurity' OR English desc/label regex 'cyber|security|microsoft defender|threat|SOC|SIEM|pentest|red team|appsec|identity|zero trust'. No country filter. LIMIT 10000.",
    "goal": "2000+"
  },
  {
    "id": "f15",
    "tag": "wd_ai",
    "title": "Wikidata AI/ML companies (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'artificial intelligence|machine learning|AI|deep learning|LLM|generative|computer vision|NLP|MLOps'. global.",
    "goal": "2000+"
  },
  {
    "id": "f16",
    "tag": "wd_fintech",
    "title": "Wikidata fintech / payments / banking-tech (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'fintech|financial technology|payment|neobank|embedded finance|insurtech|crypto|blockchain|trading platform'. global.",
    "goal": "3000+"
  },
  {
    "id": "f17",
    "tag": "wd_saas_cloud",
    "title": "Wikidata SaaS / cloud / infra / hosting (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'SaaS|cloud|infrastructure|hosting|CDN|platform as a service|DevOps|observability|database|data platform'. global.",
    "goal": "3000+"
  },
  {
    "id": "f18",
    "tag": "wd_devtools",
    "title": "Wikidata devtools / OSS companies (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'developer tools|open source|programming|software framework|IDE|version control|API platform|source code'. global.",
    "goal": "2000+"
  },
  {
    "id": "f19",
    "tag": "wd_healthtech",
    "title": "Wikidata healthtech / biotech / medtech / digital health (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'biotech|medtech|health tech|digital health|pharma|genomics|telehealth|healthcare software|life sciences'. global.",
    "goal": "3000+"
  },
  {
    "id": "f20",
    "tag": "wd_gaming_xr",
    "title": "Wikidata gaming / XR / media-tech (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'video game|game developer|game publisher|esports|virtual reality|augmented reality|animation|streaming platform|media technology'. global.",
    "goal": "2000+"
  },
  {
    "id": "f21",
    "tag": "wd_deeptech",
    "title": "Wikidata robotics / aerospace / defense-tech / semis / IoT (global)",
    "method": "wikidata",
    "source": "industry/desc regex 'robotics|aerospace|defense contractor|semiconductor|drone|space technology|IoT|quantum|satellite'. global.",
    "goal": "2000+"
  },
  {
    "id": "f22",
    "tag": "gh_remoteintech",
    "title": "GitHub remoteintech/remote-jobs",
    "method": "github",
    "source": "curl https://raw.githubusercontent.com/remoteintech/remote-jobs/master/README.md (and /company/<slug>/*.md). Each company entry lists its jobs/careers URL — many are boards.greenhouse.io / jobs.lever.co / apply.workable.com. Parse company name + jobs URL. If master 404s try branch 'main'.",
    "goal": "600+"
  },
  {
    "id": "f23",
    "tag": "gh_remote_lists",
    "title": "GitHub remote-job / hiring company lists",
    "method": "github",
    "source": "Discover + curl large 'remote-jobs'/'companies hiring remotely' repos: try ultimatedavs/remote-jobs, duyet/remote-jobs, rossbulat/remote-jobs-database, luke.. /remote-jobs. Use WebFetch on https://github.com/search?q=%22remote%22+jobs+companies&type=repositories to find repos, then curl their raw README/JSON. Extract company + career/jobs URL.",
    "goal": "800+"
  },
  {
    "id": "f24",
    "tag": "gh_greenhouse",
    "title": "GitHub datasets enumerating Greenhouse boards",
    "method": "github",
    "source": "Find GitHub markdown/datasets listing 'boards.greenhouse.io/<slug>' or 'job-boards.greenhouse.io/<slug>'. Use WebFetch github code/repo search for the literal hostname, then curl raw files. Extract slug -> https://boards.greenhouse.io/<slug> and infer company name from repo context/slug.",
    "goal": "1000+"
  },
  {
    "id": "f25",
    "tag": "gh_lever",
    "title": "GitHub datasets enumerating Lever boards",
    "method": "github",
    "source": "Find GitHub markdown/datasets listing 'jobs.lever.co/<slug>'. Search + curl raw. slug -> https://jobs.lever.co/<slug>.",
    "goal": "1000+"
  },
  {
    "id": "f26",
    "tag": "gh_ats_misc",
    "title": "GitHub datasets: Ashby/Workable/SmartRecruiters/Teamtailor boards",
    "method": "github",
    "source": "Search GitHub for 'jobs.ashbyhq.com', 'apply.workable.com', 'jobs.smartrecruiters.com', 'careers.teamtailor.com'. curl raw files; extract board URLs.",
    "goal": "800+"
  },
  {
    "id": "f27",
    "tag": "gh_awesome",
    "title": "GitHub awesome-lists of remote/tech companies",
    "method": "github",
    "source": "Fetch awesome-remote-job style lists + curated tech-company-with-careers repos (e.g. lukasmusch? github topics 'remote-work','hiring','awesome-list'). curl raw, extract company + careers URL.",
    "goal": "800+"
  },
  {
    "id": "f28",
    "tag": "dir_yc",
    "title": "Y Combinator full company directory",
    "method": "directory",
    "source": "WebFetch https://www.ycombinator.com/companies (and ?batch=... / topical pages) to enumerate ALL YC companies across batches/industries beyond what's already known. Extract name + website (+ careers link if present). Many YC cos use greenhouse/lever/ashby — record those when the page exposes them.",
    "goal": "1500+"
  },
  {
    "id": "f29",
    "tag": "dir_eu_apac_mena",
    "title": "EU/APAC/MENA startup directories",
    "method": "directory",
    "source": "WebFetch company lists from Sifted (sifted.eu), EU-Startups (eu-startups.com), e27 (e27.co), Tech in Asia, KrASIA, Wamda (wamda.com), Magnitt. Extract name + website. These are genuine startups, not recruiters.",
    "goal": "1500+"
  },
  {
    "id": "f30",
    "tag": "dir_accelerators",
    "title": "Accelerator/VC portfolio companies",
    "method": "directory",
    "source": "WebFetch Techstars portfolio (techstars.com/companies), 500 Global portfolio, and VC portfolio pages (Sequoia, a16z, Founders Fund, Accel, Index). Extract name + website.",
    "goal": "1500+"
  },
  {
    "id": "f31",
    "tag": "wiki_lists",
    "title": "Wikipedia company/unicorn lists",
    "method": "wikipedia",
    "source": "WebFetch 'List of companies of <country>' for a sweep of countries, 'List of unicorn companies', 'List of public technology companies', 'Forbes Cloud 100', 'Inc. 5000' mirrors. Extract name + official website (from list table or infobox link).",
    "goal": "2000+"
  },
  {
    "id": "f32",
    "tag": "niche_datasets",
    "title": "Open datasets: HN Who-is-Hiring / OpenCorporates / open registers",
    "method": "wikipedia",
    "source": "Find GitHub datasets that parsed Hacker News 'Ask HN: Who is Hiring' months (github 'who-is-hiring' datasets) -> company names + sites. Also OpenCorporates tech-filtered snapshots. curl raw JSON/CSV; extract name + website.",
    "goal": "1500+"
  }
]

const RUN_IDS = (Array.isArray(args) && args.length) ? args.map(String) : null
const SLOTS = RUN_IDS ? ALL_SLOTS.filter(s => RUN_IDS.includes(s.id)) : ALL_SLOTS
log(`fanout: ${SLOTS.length} slot(s) to run` + (RUN_IDS ? '' : ' (all)'))

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['slot', 'tag', 'file', 'status', 'kept_new', 'automatable'],
  properties: {
    slot: { type: 'string' }, tag: { type: 'string' }, file: { type: 'string' },
    status: { type: 'string', enum: ['ok', 'empty', 'failed'] },
    kept_new: { type: 'integer' }, automatable: { type: 'integer' },
    ats_counts: { type: 'object' }, notes: { type: 'string' },
  },
}

const RULES = `ABSOLUTE RULES (violating these wastes the run):
1. REAL DATA ONLY. Emit ONLY companies/URLs you actually fetched from the named source. NEVER invent company names, websites, or ATS slugs/URLs. NEVER "fill in" a plausible boards.greenhouse.io / jobs.lever.co URL you did not observe in the fetched bytes. If you have only a name + website, set career_page_url="" and ats_type="unknown" — that is valid and valuable.
2. WRITE THE FILE YOURSELF with Bash + python3. Do NOT paste hundreds/thousands of rows in chat (it truncates and invites hallucination). Fetch source bytes with curl / WebFetch, parse with python3, and json.dump the list to {FILE}.
3. OUTPUT FILE {FILE} = a JSON array. Each element:
   {"company_name": "...", "career_page_url": "<observed ATS/jobs url or ''>", "website": "<full hostname minus leading www, e.g. acme.com / greateranglia.co.uk — do NOT reduce to last 2 labels>", "ats_type": "<greenhouse|lever|ashby|smartrecruiters|workable|personio|teamtailor|bamboohr|workday|custom|unknown>", "source_platform": "{TAG}", "domain_hint": ""}
4. Skip middlemen — job boards/aggregators (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Wellfound, Otta, etc.) and staffing/recruiters. A later pass filters them too, but do your part.
5. After writing {FILE}, RUN:  python3 {HELPER} "{FILE}"
   It dedups vs the existing ~56,520 companies, drops middlemen + junk + generic ATS slugs, infers ats_type, writes a resume marker, and PRINTS a one-line JSON list like [{"file":...,"kept_new":N,"automatable":M,"ats_counts":{...},...}]. Read kept_new and automatable from the first element.
6. Be resilient: try multiple files/repos/branches/pages/offsets; sleep 1-2s between HTTP requests; on HTTP 429 sleep 12s and retry (up to 3x). If a source truly yields nothing, write [] to {FILE}, still run the helper, return status "empty".
7. Working dir: /mnt/380/Projects/job_auto/repo . Use the absolute paths above.`

const RECIPES = {
  wikidata: `METHOD = wikidata (SPARQL). Endpoint https://query.wikidata.org/sparql . Use curl:
   curl -s -G 'https://query.wikidata.org/sparql' --data-urlencode format=json --data-urlencode query="<URL-encoded SPARQL>" -H 'User-Agent: job_auto/1.0 (research)'
JSON has results.bindings[].<var>.value. Paginate by OFFSET (0, 5000, 10000, 15000), stop when a page returns <5000; concat. If a tech-biased description filter yields <1500, broaden by dropping that filter.
website = the P856 value's HOSTNAME with a leading "www." stripped ONLY (e.g. "https://www.flynorse.com/" -> "flynorse.com", "https://greateranglia.co.uk" -> "greateranglia.co.uk"). Do NOT reduce to the last two labels (that mangles .co.uk/.com.au/.co.jp into "co.uk"); keep the full registrable host. career_page_url="" and ats_type="unknown" (Wikidata rarely has careers pages).`,
  github: `METHOD = github. Prefer downloading the repo tarball in one request (https://github.com/OWNER/REPO/archive/refs/heads/<branch>.tar.gz -> extract), then parse each company file's content, OR curl raw files: https://raw.githubusercontent.com/OWNER/REPO/BRANCH/PATH (try branch 'master' then 'main' on 404). Parse markdown/json/csv with python3 (regex over tables/lists; YAML frontmatter with pyyaml if present). Extract company name + its REAL jobs/careers/ATS URL. Where the jobs-URL host is a known ATS (boards.greenhouse.io / jobs.lever.co / jobs.ashbyhq.com / jobs.smartrecruiters.com / apply.workable.com / jobs.personio.com / careers.teamtailor.com / *.myworkdayjobs.com) set ats_type accordingly; a company-domain /careers|/jobs page -> ats_type "custom"; else "unknown". You may WebFetch https://github.com/search?q=...&type=repositories to DISCOVER candidate repos, then fetch them. Prefer repos whose content literally lists ATS hostnames. Strip obvious aggregator/social URLs (linkedin.com, angel.co, bit.ly, x.com) by clearing career_page_url (keep name+website).`,
  directory: `METHOD = directory. Use WebFetch to enumerate company lists from the named directory sites; extract (name, official website) and any exposed careers/ATS link. For sites with many pages, fetch several pages. If WebFetch returns a redirect, follow by re-calling WebFetch on the new URL. website = full hostname minus leading www. ats_type from any ATS host observed, else "unknown".`,
  wikipedia: `METHOD = wikipedia/open-lists. Use WebFetch on the named Wikipedia/open-data pages; extract (name, official website) from list tables / infobox links. For GitHub open datasets curl the raw file (or tarball) and parse JSON/CSV. website = full hostname minus leading www; career_page_url="" ats_type="unknown" unless a careers URL is explicitly listed.`,
}

function num(id) { return String(parseInt(String(id).replace(/[^0-9]/g, ''), 10)).padStart(2, '0') }

async function runSlot(s) {
  const n = num(s.id)
  const tag = s.tag
  const file = `${REPO}/data/raw/agentf${n}_${tag}.json`
  const recipe = RECIPES[s.method] || RECIPES.wikipedia
  const rules = RULES.replaceAll('{FILE}', file).replaceAll('{HELPER}', HELPER).replaceAll('{TAG}', tag)
  const prompt = [
    `You are discovery agent ${s.id} ("${s.title}") for the job_auto company dataset.`,
    `GOAL: discover genuine companies (+ their job-listing endpoint when available). Target ~${s.goal} rows. More real rows is better; never invent to hit a number.`,
    ``,
    recipe,
    ``,
    `SOURCE (concrete, for THIS slot):
${s.source}`,
    ``,
    rules,
    ``,
    `Return via StructuredOutput: {slot:"${s.id}", tag:"${tag}", file:"${file}", status:"ok|empty|failed", kept_new:N, automatable:M, ats_counts:{...}, notes:"<brief: what you fetched, row count, any fallbacks>"}. N and M MUST come from the helper's printed JSON (first array element).`,
  ].join('\n')
  return agent(prompt, { label: `${s.id}:${tag}`, phase: 'Discover', schema: SCHEMA, agentType: 'general-purpose' })
}

const results = (await parallel(SLOTS.map(s => () => runSlot(s)))).filter(Boolean)
const total_new = results.reduce((a, r) => a + (r.kept_new || 0), 0)
const total_auto = results.reduce((a, r) => a + (r.automatable || 0), 0)
log(`fanout done: ${results.length}/${SLOTS.length} slots returned; ${total_new} new rows (~${total_auto} automatable)`)
return { slots_returned: results.length, total_new, total_auto, results }
