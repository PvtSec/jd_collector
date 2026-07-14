# Greenhouse ATS — Application Form Schema

READ-ONLY research. No application was submitted. All findings below were
verified by fetching live public endpoints on 2026-07-02.

Board used for inspection: **Stripe** (`https://boards-api.greenhouse.io/v1/boards/stripe`).
Because Stripe's career site is a heavily customised JS-rendered SPA, the
standard application-form schema was additionally verified against two other
live Greenhouse boards (**Mercury** and **Cloudflare**) that expose the
identical Greenhouse backend form. The schema is the same Greenhouse
application backend for all 71 companies; only the marketing wrapper differs.

---

## 1. Job Enumeration

### Public board API (no auth)

```
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
```

Optional query params:

- `content=true` — include the full HTML job description in each `content`
  field (otherwise omitted).
- `?order=posting_date` / `?order=title` — sort.

Pagination: **none.** The endpoint returns every open job in one response.
The only pagination-related value is `meta.total` (a count). Stripe returns
490 jobs in a single 3.6 MB JSON document. (Greenhouse caps a board at ~500
active posts; if a board exceeds this you must filter by department via the
`/departments` endpoint, which also embeds jobs.)

### Related endpoints

```
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/departments
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/offices
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}   # single job detail
```

### JSON response shape (`/jobs?content=true`)

```json
{
  "jobs": [
    {
      "id": 7954688,                         // <- job post id (gh_jid)
      "internal_job_id": 3453698,            // internal, not used for apply
      "title": "Account Executive, AI Sales (Grower)",
      "requisition_id": "See Opening ID",
      "absolute_url": "https://stripe.com/jobs/search?gh_jid=7954688",
      "location": { "name": "San Francisco, CA" },
      "departments": [ { "id": 295360, "name": "...", "parent_id": 297997, "child_ids": [] } ],
      "offices":      [ { "id": 65234, "name": "US", "location": null, "parent_id": 673, "child_ids": [...] } ],
      "metadata": null,
      "updated_at": "2026-06-26T17:05:44-04:00",
      "first_published": "2026-06-02T08:58:57-04:00",
      "application_deadline": null,
      "language": "en",
      "company_name": "Stripe",
      "content": "&lt;h2&gt;Who we are&lt;/h2&gt;...",   // HTML, entity-escaped
      "data_compliance": [
        { "type": "gdpr", "requires_consent": false,
          "requires_processing_consent": false,
          "requires_retention_consent": false,
          "retention_period": null,
          "demographic_data_consent_applies": false }
      ],
      "ai_disclaimer": null,
      "include_ai_disclaimer": false,
      "ai_opt_out_request_url": "http://app.greenhouse.io/ai_opt_out_request/job_post/7954688/ai_opt_out"
    }
  ],
  "meta": { "total": 490 }
}
```

How to extract the fields the engine needs:

| Engine field    | Path                                   |
|-----------------|----------------------------------------|
| job ID          | `jobs[].id`  (this is the `gh_jid`)    |
| title           | `jobs[].title`                         |
| department      | `jobs[].departments[].name`            |
| location        | `jobs[].location.name`                 |
| office          | `jobs[].offices[].name`                |
| application URL | `https://boards.greenhouse.io/{board_token}/jobs/{id}?gh_jid={id}` |
| description     | `jobs[].content` (HTML, entity-escaped) |

> Note on `absolute_url`: many boards set this to a *company-branded* URL
> (Stripe → `stripe.com/jobs/search?gh_jid=...`) rather than the Greenhouse
> host. The Greenhouse-hosted application form is always reachable at
> `https://job-boards.greenhouse.io/{board_token}/jobs/{id}?gh_jid={id}`
> (the bare `boards.greenhouse.io/...` form 301-redirects to that).

---

## 2. Application Form

### Per-job application URL pattern

```
https://job-boards.greenhouse.io/{board_token}/jobs/{job_post_id}?gh_jid={job_post_id}
```

(`https://boards.greenhouse.io/{board}/jobs/{id}` 301-redirects to the above.
The `gh_jid` query param is the job post id and is required for tracking.)

The page is a **Remix SSR app**. The full form definition is serialised into
inline JS as `window.__remixContext.state.loaderData["routes/$url_token_.jobs_.$job_post_id"].jobPost`.
You do not need a browser to read the schema — fetch the HTML and parse that
JSON blob (regex `window\.__remixContext\s*=\s*(\{.*?\});\s*</script>`).

### `jobPost` object (loader data) — keys

```
post_type, language, title, hiring_plan_id, content, introduction, conclusion,
enable_eeoc, job_post_location, public_url, company_name, confirmation_message,
pay_ranges, published_at, employment, fingerprint, redirect_to, is_featured,
ai_disclaimer, include_ai_disclaimer, apply_with_seek, show_quick_apply_cta,
ai_opt_out_request_url, application_deadline, education_config,
questions, eeoc_sections
```

The same route also exposes, alongside `jobPost`:

```
submitPath:        "https://boards.greenhouse.io/{board}/jobs/{job_post_id}"   # POST target
confirmationPath:  "/{board}/jobs/{job_post_id}/confirmation"
quickApply:        { active, magicActive, url: "https://my.greenhouse.io", metadata: { jobPostId } }
```

### Standard form fields (universal across boards)

The `jobPost.questions` array always begins with these core fields (order is
stable; some boards add `preferred_name` between last name and email):

| Field name (`fields[].name`) | Type            | Required | Label          |
|------------------------------|-----------------|----------|----------------|
| `first_name`                 | `input_text`    | yes      | First Name     |
| `last_name`                  | `input_text`    | yes      | Last Name      |
| (`preferred_name` *)         | `input_text`    | no       | Preferred First Name |
| `email`                      | `input_text`    | yes      | Email          |
| `phone`                      | `input_text`    | yes      | Phone          |
| `resume`                     | `input_file`    | yes      | Resume/CV (also exposes `resume_text` textarea) |
| `cover_letter`               | `input_file`    | no       | Cover Letter (also exposes `cover_letter_text` textarea) |

Profile-link custom questions are extremely common (LinkedIn / GitHub /
Website / Portfolio) — see section 3.

### Location / country field

Most boards render a country react-select combobox (`id="country"`,
`aria-labelledby="country-label"`) and a free-text location. These map to the
JSON submit fields `location`, `latitude`, `longitude`, `country_short_name`
(see the `qs` allowlist in section 5). Not a normal `question_*` field.

### EEO / demographic questions

Present only when `jobPost.enable_eeoc === true`. They live in
`jobPost.eeoc_sections` (a list), not in `questions`. Each section has
`description` (HTML) and `questions[]` with the same field shape as custom
questions. Standard EEO field names (verified on Cloudflare):

| Field name           | Type                       | Options                                                                                  |
|----------------------|----------------------------|------------------------------------------------------------------------------------------|
| `gender`             | `multi_value_single_select`| 1 Male, 2 Female, 3 Decline To Self Identify                                             |
| `race`               | `multi_value_single_select`| 1 American Indian/Alaskan Native, 2 Asian, 3 Black, 4 Hispanic/Latino, 5 White, 6 Native Hawaiian/Pacific Islander, 7 Two or More, 8 Decline |
| `veteran_status`     | `multi_value_single_select`| 1 not a protected veteran, 2 identify as one or more, 3 don't wish to answer             |
| `disability_status`  | `multi_value_single_select`| 1 Yes, 2 No, 3 I do not want to answer                                                   |

All EEO questions are `required: false` (voluntary). There is typically a 4th
section with `questions: []` containing only the public-burden statement text.

### Consent / acknowledgement checkboxes

Boards add custom yes/no or checkbox questions for privacy policy
acknowledgement, etc. These are normal `question_*` entries (see section 3),
typically `multi_value_multi_select` with `multi_select_style: "checkbox"`.

---

## 3. Custom Questions

Custom questions are appended after the core fields in `jobPost.questions`.
Each question has this shape:

```json
{
  "required": false,
  "label": "LinkedIn Profile",
  "description": null,
  "multi_select_style": "checkbox",      // only meaningful for select types
  "fields": [
    {
      "name": "question_15187728004",     // field name sent on submit
      "type": "input_text",               // see types below
      "allowed_filetypes": ["pdf","doc","docx","txt","rtf"],  // file types only
      "values": [ ... ]                   // select types only
    }
  ]
}
```

### Field-name convention

`question_{question_id}`. For multi-select questions the name is
`question_{question_id}[]` (trailing `[]`) — submitted as repeated form values
/ an array.

### Question types (verified)

| `type`                          | UI rendering            | Answer encoding in submit payload                          |
|---------------------------------|-------------------------|------------------------------------------------------------|
| `input_text`                    | short text input        | `text_value`                                               |
| `textarea`                      | long text textarea      | `text_value`                                               |
| `input_file`                    | file upload             | S3 upload → `{name}_url`, `{name}_url_filename`            |
| `multi_value_single_select`     | dropdown / radio        | `boolean_value` (if options are 0/1) **or** `answer_selected_options_attributes` (list of `question_option_id`) |
| `multi_value_multi_select`      | checkboxes             | `answer_selected_options_attributes` list of `question_option_id` |

### How dropdown options are encoded

In the loader JSON, options live in `fields[].values[]`:

```json
{
  "name": "question_15187732004",
  "type": "multi_value_single_select",
  "values": [
    { "value": 1, "label": "Yes" },
    { "value": 0, "label": "No"  }
  ]
}
```

- For **Yes/No** questions (values are literally `1` / `0`), the submit
  payload uses `boolean_value: <0|1>` (no option ids).
- For other single-selects, the submit payload uses
  `answer_selected_options_attributes: { 0: { question_option_id: <value> } }`.
- For multi-select (`name` ends in `[]`), each selected `value` becomes an
  entry in `answer_selected_options_attributes` keyed by index.

The `value` in the loader JSON **is** the `question_option_id` used on submit
(cast to int). Example consent checkbox (Cloudflare):

```json
{
  "name": "question_67192156[]",
  "type": "multi_value_multi_select",
  "values": [ { "value": 724414123, "label": "Acknowledge/Confirm" } ]
}
```

### Profile-link questions

Very common, always `input_text`, `required: false`, with labels like
"LinkedIn Profile", "GitHub", "Website", "Portfolio", "Personal Website/Blog".
The engine should map its stored profile URLs into these by matching label
substring.

---

## 4. Resume Upload

There is **no direct multipart upload to the submit endpoint**. Resumes (and
cover letters, and any `input_file` custom questions) are uploaded to
**S3 via presigned POST** *before* the application is submitted, then the
resulting S3 URL is referenced in the JSON application payload.

### Step A — fetch presigned S3 fields (read-only, verified)

```
GET https://boards.greenhouse.io/uncacheable_attributes/presigned_fields?fields[]=resume&fields[]=cover_letter
```

(Other field names: any `input_file` field name, e.g. `fields[]=question_15187731004`.)

200 response (verified live):

```json
{
  "url": "https://grnhse-prod-jben-us-west-2.s3.us-west-2.amazonaws.com",
  "resume": {
    "fields": {
      "x-amz-server-side-encryption": "AES256",
      "success_action_status": "201",
      "policy": "<base64 policy>",
      "x-amz-credential": "AKIAVQGOLGY32BHIJKML/20260702/us-west-2/s3/aws4_request",
      "x-amz-algorithm": "AWS4-HMAC-SHA256",
      "x-amz-date": "20260702T181656Z",
      "x-amz-signature": "<sig>"
    },
    "key": "stash/applications/resumes/{timestamp}-{unique_id}-<hash>"
  },
  "cover_letter": { "fields": { ... }, "key": "stash/applications/cover_letters/{timestamp}-{unique_id}-<hash>" }
}
```

- S3 bucket: `grnhse-prod-jben-us-west-2` (region `us-west-2`).
- Key prefix per field: `stash/applications/resumes/...`,
  `stash/applications/cover_letters/...`, etc.
- The client replaces `{timestamp}` with `Date.now()` and `{unique_id}` with a
  random 14-char base36 string before upload.
- S3 policy `content-length-range` is **1 to 104,857,600 bytes (100 MiB)**.

### Step B — POST the file to S3 (multipart/form-data)

```
POST https://grnhse-prod-jben-us-west-2.s3.us-west-2.amazonaws.com
Content-Type: multipart/form-data

utf8: ✓
<x-amz-... fields from presigned response>
key: stash/applications/resumes/<timestamp>-<unique_id>-<hash>
authenticity_token: 1234
Content-Type: application/octet-stream
file: <binary>
```

Field name on the multipart is `file`. On `201` success, S3 returns XML
containing the object's `Location` (the canonical S3 URL). The client uses
that URL as `resume_url` and the original filename as `resume_url_filename`
in the final JSON submit.

### Accepted file types

Form `accept` attribute (verified): `.pdf, .doc, .docx, .txt, .rtf`.
The loader JSON `allowed_filetypes` is `["pdf","doc","docx","txt","rtf"]`.
S3 layer allows up to 100 MiB; Greenhouse UI typically warns over ~1 MB but
does not hard-block until the S3 policy limit.

### Alternative: paste resume text

Every `input_file` field is paired with a `*_text` textarea
(`resume_text`, `cover_letter_text`) for plain-text entry. If used, it is sent
as a top-level field on the JSON submit (no S3 upload needed).

### Cloud upload integrations

The form also offers "Dropbox", "Google Drive", and "Enter manually" buttons
(Dropbox chooser key `mh9jyh4mfwjnfhj`, Google Picker app id
`594601915089`). These ultimately produce a `{name, url}` file object fed into
the same `resume_url`/`resume_url_filename` submit fields.

---

## 5. Submit Endpoint

### Request

```
POST {submitPath}
Content-Type: application/json

{submitPath} = https://boards.greenhouse.io/{board_token}/jobs/{job_post_id}
```

> Verified by reading the bundle
> `https://job-boards.cdn.greenhouse.io/assets/entry.client-smbYsTst.js`
> (function `Ua`). The modern job-board renderer submits **JSON**, not
> multipart. (The legacy `boards.greenhouse.io` iframe form used
> `multipart/form-data`; that path now 301-redirects to the JSON renderer.)

### Payload shape

```jsonc
{
  "job_application": {
    "first_name": "Jane",
    "last_name":  "Doe",
    "email":      "jane@example.com",
    "phone":      "+14155550100",
    // location allowlist (only sent if present):
    "location":             "San Francisco, CA",
    "latitude":             37.7749,
    "longitude":            -122.4194,
    "country_short_name":   "US",
    "from_job_board_renderer": true,           // always true from this UI
    "resume_url":            "https://grnhse-prod-jben-us-west-2.s3.us-west-2.amazonaws.com/stash/applications/resumes/<key>",
    "resume_url_filename":   "Jane_Doe_Resume.pdf",
    "cover_letter_url":      "...",            // optional
    "cover_letter_url_filename": "Jane_Doe_Cover.pdf",
    "answers_attributes": {                    // custom questions keyed by question_id
      "15187728004": { "question_id": "15187728004", "priority": 0, "text_value": "https://linkedin.com/in/jane" },
      "15187732004": { "question_id": "15187732004", "priority": 1, "boolean_value": 0 },
      "67192156":    { "question_id": "67192156",    "priority": 2,
                       "answer_selected_options_attributes": { "0": { "question_option_id": 724414123 } } }
    },
    "demographic_answers": [ ... ],            // EEO answers (see below)
    "data_compliance":     { ... },            // GDPR consent answers
    "attachments":         { ... },            // custom input_file question S3 URLs
    "employments":         [ ... ]             // employment history (education_config driven)
  },
  "fingerprint": "a93dbd47545b8c1c5be787f1e728408195bb6997",   // from jobPost.fingerprint
  "g-recaptcha-enterprise-token": "<token from grecaptcha.enterprise.execute>",  // see section 6
  // if a CSRF token was present in the page:
  "<csrf_key>": "<csrf_value>"
  // if email verification security code flow is active:
  // "security_code": "123456"
}
```

### Field-name allowlist for the `job_application` object

The client only copies these top-level string fields from the form into
`job_application` (the `qs` set in the bundle):

```
first_name, last_name, preferred_name, email, phone,
resume_text, cover_letter_text,
location, latitude, longitude, country_short_name
```

Everything else is routed into `answers_attributes`, `attachments`,
`demographic_answers`, `data_compliance`, or `employments`.

### `answers_attributes` construction (per custom question)

For a custom question with field name `question_{id}` (or `question_{id}[]`):

- `input_text` / `textarea` →
  `{ question_id: "{id}", priority: <n>, text_value: "<value>" }`
- `multi_value_single_select` with 0/1 options →
  `{ question_id: "{id}", priority: <n>, boolean_value: <0|1> }`
- `multi_value_single_select` / `multi_value_multi_select` (other) →
  `{ question_id: "{id}", priority: <n>,
     answer_selected_options_attributes: { "0": { question_option_id: <v> }, "1": {...}, ... } }`
- `input_file` → handled as `attachments` (see below), not in `answers_attributes`.

`priority` is a 0-indexed counter incremented across all custom answers in
form order.

### `attachments` (custom file questions)

For an `input_file` custom question named `question_{id}`, after S3 upload:

```json
"attachments": { "{id}_url": "<s3 url>", "{id}_url_filename": "<filename>" }
```

(`resume` and `cover_letter` are **not** put in `attachments` — they go in
`resume_url` / `cover_letter_url` at the top level.)

### `demographic_answers` (EEO)

Built from `jobPost.eeoc_sections[].questions`:

```json
[
  { "question_id": <eeoc_question_id>,
    "answer_options": [ { "answer_option_id": <value> } ]
  }
]
```

(EEO question ids and answer-option ids come from the `eeoc_sections` loader
data, not from `questions`.)

### `data_compliance` (GDPR consent)

Only when `jobPost.data_compliance[*].requires_*_consent` is true. The page
builds a `data_compliance` object from the compliance questions rendered in
the demographic section. For Stripe/US boards this is typically empty
(`requires_consent: false`).

### Hidden tokens

- **`fingerprint`** — `jobPost.fingerprint` (a 40-char hex string baked into
  the loader data, per job post). Sent as a top-level field. This is the
  integrity token that ties the submission to a specific job-post version.
- **CSRF token** — if the page rendered a CSRF meta tag, the client sends it
  as `{<csrf_key>: <csrf_value>}` at the top level. On the boards inspected
  (Mercury, Cloudflare) no CSRF token was present in the loader.
- **`g-recaptcha-enterprise-token`** — invisible reCAPTCHA Enterprise token,
  see section 6.
- **`request_token`** — optional, present only if a `jobApplicationRequestToken`
  was passed (e.g. from "Quick Apply" / MyGreenhouse flow).

### Can submission happen via plain HTTP?

**No.** The submit requires a live **`g-recaptcha-enterprise-token`** produced
by `window.grecaptcha.enterprise.execute(invisibleKey, {action:"apply_to_job"})`.
That call only works inside a real browser context that has first loaded
`https://www.recaptcha.net/recaptcha/enterprise.js?render=<sitekey>`.
A plain `curl` with no token will be rejected. Practically, the engine must
drive a browser (Playwright/Puppeteer) to:

1. load the application page (so recaptcha enterprise JS initialises),
2. populate the form,
3. perform the S3 presign + upload,
4. call `grecaptcha.enterprise.execute(...)` to mint a token,
5. POST the JSON to `submitPath` (the bundle does this via `fetch`).

A headless browser that executes the page's own React submit handler is the
simplest path; reimplementing the JSON POST by hand still requires the
browser-minted recaptcha token.

---

## 6. Anti-Bot

### reCAPTCHA Enterprise (invisible)

Verified from `window.ENV` on both Mercury and Cloudflare boards:

```
GOOGLE_RECAPTCHA_INVISIBLE_KEY: "6LfmcbcpAAAAAChNTbhUShzUOAMj_wY9LQIvLFX0"
GOOGLE_RECAPTCHA_ENDPOINT:      "https://www.recaptcha.net/recaptcha/enterprise.js"
```

- Type: **invisible** reCAPTCHA Enterprise, action `apply_to_job`.
- Trigger: **always** — the token is minted on every submit via
  `grecaptcha.enterprise.execute(...)`. There is no "only on suspicious
  traffic" mode here; the token is a required field in the JSON payload.
- On failure the client retries once with `captcha_retried: true`.
- Google serves recaptcha from `www.recaptcha.net` (not `google.com`).

### Email verification (security code)

Some boards additionally enable an 8-digit email verification code flow
(component `Xa`, 8 single-digit inputs). When active, instead of the
recaptcha token the submit sends `security_code: "<8 digits>"` after the
candidate enters the code emailed to them. This is board-config driven, not
universal.

### Cloudflare

The HTML marketing pages (`boards.greenhouse.io/<board>`, `job-boards.greenhouse.io/<board>`)
are fronted by Cloudfront (headers: `via: 1.1 ...cloudfront.net`,
`x-amz-cf-pop`, `x-cache`). No Cloudflare challenge page was observed on the
board pages or the JSON API — plain `curl` with a normal UA returns 200. The
board page at `boards.greenhouse.io/stripe` returns an empty body to a bare
curl (it 301-redirects to `job-boards.greenhouse.io/stripe`); following the
redirect with a browser UA works. The JSON API
(`boards-api.greenhouse.io`) has no challenge at all.

No hCaptcha or Cloudflare Turnstile was observed on any inspected board.

---

## 7. Worked Example — Stripe job 7954688

Job: **Account Executive, AI Sales (Grower)** — `id=7954688`,
board token `stripe`. Status: open as of 2026-07-02
(`https://boards-api.greenhouse.io/v1/boards/stripe/jobs`).

> ⚠️ The curl below would submit a **real** application if run with valid
> values. It is for schema reference only. The `g-recaptcha-enterprise-token`
> cannot be generated without a browser, which is the hard gate.

Stripe's career site is a custom SPA (`stripe.com/jobs/listing/.../apply`,
component `DetailApplyCard`) but its backend is the standard Greenhouse
application API, so the submit target and payload schema are identical to
every other Greenhouse board:

`submitPath = https://boards.greenhouse.io/stripe/jobs/7954688`

### Step 1 — enumerate (read-only)

```bash
curl -s 'https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true' \
  | jq '.jobs[] | {id, title, location: .location.name,
                   department: .departments[0].name,
                   url: ("https://job-boards.greenhouse.io/stripe/jobs/" + (.id|tostring))}'
```

### Step 2 — read the form schema for this job (read-only)

```bash
curl -sL -A 'Mozilla/5.0' \
  'https://job-boards.greenhouse.io/stripe/jobs/7954688?gh_jid=7954688' \
  | grep -oE 'window\.__remixContext\s*=\s*\{.*\};\s*</script>' \
  | python3 -c 'import sys,json,re;
m=re.search(r"window\.__remixContext\s*=\s*(\{.*?\});\s*</script>", sys.stdin.read());
jp=json.loads(m.group(1))["state"]["loaderData"]["routes/$url_token_.jobs_.\$job_post_id"]["jobPost"];
print(json.dumps(jp["questions"], indent=2))'
```

### Step 3 — presign resume upload (read-only GET; no file sent)

```bash
curl -s 'https://boards.greenhouse.io/uncacheable_attributes/presigned_fields?fields[]=resume' \
  > /tmp/presign.json
S3_URL=$(jq -r .url /tmp/presign.json)
RES_KEY=$(jq -r .resume.key /tmp/presign.json)
# replace {timestamp} and {unique_id}
RES_KEY=${RES_KEY/\{timestamp\}/$(date +%s000)}
RES_KEY=${RES_KEY/\{unique_id\}/$(openssl rand -hex 7)}
```

### Step 4 — upload the resume to S3 (writes to S3 — DO NOT RUN for real)

```bash
# Build the multipart form from presigned fields + file, POST to $S3_URL
# Field name for the file is "file". Returns 201 XML with <Location>.
```

### Step 5 — submit the application (DO NOT RUN for real)

```bash
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ...' \
  -H 'Referer: https://job-boards.greenhouse.io/stripe/jobs/7954688?gh_jid=7954688' \
  -H 'Origin: https://job-boards.greenhouse.io' \
  --data '{
    "job_application": {
      "first_name": "Jane",
      "last_name": "Doe",
      "email": "jane@example.com",
      "phone": "+14155550100",
      "location": "San Francisco, CA",
      "country_short_name": "US",
      "from_job_board_renderer": true,
      "resume_url": "https://grnhse-prod-jben-us-west-2.s3.us-west-2.amazonaws.com/stash/applications/resumes/'"$RES_KEY"'",
      "resume_url_filename": "Jane_Doe_Resume.pdf",
      "answers_attributes": {
        "<linkedin_question_id>": { "question_id": "<linkedin_question_id>", "priority": 0, "text_value": "https://linkedin.com/in/jane" },
        "<visa_question_id>":     { "question_id": "<visa_question_id>",     "priority": 1, "boolean_value": 0 }
      },
      "demographic_answers": [],
      "data_compliance": {},
      "attachments": {}
    },
    "fingerprint": "<jobPost.fingerprint for this job>",
    "g-recaptcha-enterprise-token": "<token from grecaptcha.enterprise.execute(...,{action:\"apply_to_job\"})>"
  }' \
  'https://boards.greenhouse.io/stripe/jobs/7954688'
```

All `<..._question_id>` placeholders must be filled from the actual
`jobPost.questions` array (Step 2), since question ids are per-board/per-job.
A successful submit returns 200 and the client redirects to
`/{board}/jobs/{id}/confirmation`.

### Practical automation path

Because of the invisible reCAPTCHA Enterprise token, a pure-curl pipeline
cannot submit. The viable engine design for Greenhouse is:

1. Use the public JSON API to enumerate jobs (no browser needed).
2. For each target job, fetch `job-boards.greenhouse.io/{board}/jobs/{id}?gh_jid={id}`,
   parse `window.__remixContext` to get `questions`, `eeoc_sections`,
   `fingerprint`, and `submitPath`.
3. Drive a **Playwright** (headful or headless with stealth) browser to:
   - load the page (initialises reCAPTCHA Enterprise),
   - fill `first_name`/`last_name`/`email`/`phone`/custom answers,
   - upload resume via the page's own UI (which does presign + S3 POST), or
     inject `resume_text`,
   - click **Apply** so the page's own `fetch(submitPath, {method:POST, JSON})`
     runs — this mints the recaptcha token and sends the correct payload
     automatically.
4. Assert the confirmation page URL
   (`/{board}/jobs/{id}/confirmation`) as success.

Reimplementing the JSON POST by hand is possible *only if* you also mint the
recaptcha token from a browser context first — so letting the page submit
itself is simpler and more robust.

---

## Appendix — verified endpoints & key constants

| Item | Value |
|------|-------|
| Jobs API | `https://boards-api.greenhouse.io/v1/boards/{board}/jobs[?content=true]` |
| Departments API | `https://boards-api.greenhouse.io/v1/boards/{board}/departments` |
| Single job API | `https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}` |
| Application page | `https://job-boards.greenhouse.io/{board}/jobs/{id}?gh_jid={id}` |
| Submit endpoint | `POST https://boards.greenhouse.io/{board}/jobs/{id}` (JSON body) |
| S3 presign | `GET https://boards.greenhouse.io/uncacheable_attributes/presigned_fields?fields[]=resume&fields[]=cover_letter` |
| S3 bucket | `grnhse-prod-jben-us-west-2` (us-west-2) |
| S3 object prefix | `stash/applications/resumes/{timestamp}-{unique_id}-<hash>` (cover_letters similar) |
| S3 max size | 104,857,600 bytes (~100 MiB, policy `content-length-range`) |
| Resume file types | `pdf, doc, docx, txt, rtf` |
| reCAPTCHA site key | `6LfmcbcpAAAAAChNTbhUShzUOAMj_wY9LQIvLFX0` (invisible Enterprise) |
| reCAPTCHA endpoint | `https://www.recaptcha.net/recaptcha/enterprise.js` |
| reCAPTCHA action | `apply_to_job` |
| Form schema source | `window.__remixContext.state.loaderData["routes/$url_token_.jobs_.$job_post_id"]` |
| CDN bundle | `https://job-boards.cdn.greenhouse.io/assets/entry.client-smbYsTst.js` |

### Verified live job IDs (2026-07-02)

| Board | Job post id | Title | EEO enabled |
|-------|-------------|-------|-------------|
| stripe | 7954688 | Account Executive, AI Sales (Grower) | (custom SPA) |
| cloudflare | 7958059 | (open) | yes |
| mercury | 5775685004 | Chief Audit Officer | no |
| figma | 5364702004 | (open) | — |
| datadog | 7194969 | (open) | — |