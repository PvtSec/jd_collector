# Lever ATS Application Form Schema

READ-ONLY research. No application was submitted. All data verified by fetching
live endpoints on 2026-07-02 using boards `whoop`, `mistral`, and `qonto`.

Reference boards used:
- `https://jobs.lever.co/whoop` (159 postings) — primary example
- `https://jobs.lever.co/mistral` — survey / EEO variant
- `https://jobs.lever.co/qonto` — dropdown + multiple-select + consent variant

---

## 1. Job Enumeration

### Endpoint

```
GET https://api.lever.co/v0/postings/{token}?mode=json
```

- `{token}` is the company board slug (e.g. `whoop`, `mistral`, `qonto`). This is
  the same slug used in `jobs.lever.co/{token}`.
- **No auth required.** Public, unauthenticated, CORS-friendly.
- `?mode=json` forces a JSON content-type. In practice the default (no param)
  also returns JSON for this endpoint, but `mode=json` is the documented/safe
  form for programmatic use. Without `mode=json` some Lever endpoints return HTML.
- Pagination via query params `skip` and `limit`:
  `?mode=json&skip=0&limit=100`. Verified: `skip=5&limit=2` returns 2 postings
  offset by 5.

### Single posting

```
GET https://api.lever.co/v0/postings/{token}/{postingId}?mode=json
```

Returns the same shape as one element of the list.

### JSON response shape (one element)

```json
{
  "additionalPlain": "",
  "additional": "<div>...HTML extra info / compensation / EEO statement...</div>",
  "categories": {
    "location": "Boston, MA",
    "team": "Operations",
    "commitment": "Full-time",        // may be absent (whoop omits it; mistral/qonto include it)
    "department": "Corporate & Middle Office",  // optional, qonto only
    "allLocations": ["Boston, MA"]
  },
  "createdAt": 1779984555484,          // ms epoch
  "descriptionPlain": "",
  "description": "<div>...HTML job description...</div>",
  "id": "38493926-11d7-4dbc-8620-243ec9c93f9a",   // posting ID — UUID
  "lists": [
    { "text": "RESPONSIBILITIES:", "content": "<div>...</div>" },
    { "text": "QUALIFICATIONS:",  "content": "<div>...</div>" }
  ],
  "text": "Allocation Analyst, Wholesale Planning",  // TITLE
  "country": "US",
  "workplaceType": "onsite",           // onsite | remote | hybrid
  "opening": "",
  "openingPlain": "",
  "descriptionBody": "<div>...</div>",
  "descriptionBodyPlain": "",
  "hostedUrl": "https://jobs.lever.co/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a",
  "applyUrl":   "https://jobs.lever.co/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a/apply"
}
```

Top-level keys observed: `additionalPlain, additional, categories, createdAt,
descriptionPlain, description, id, lists, text, country, workplaceType, opening,
openingPlain, descriptionBody, descriptionBodyPlain, hostedUrl, applyUrl`.

### Field extraction map

| Desired field    | JSON path                  |
|------------------|----------------------------|
| posting ID       | `id`                       |
| title            | `text`                     |
| team             | `categories.team`          |
| location         | `categories.location`      |
| all locations    | `categories.allLocations`  |
| commitment/level | `categories.commitment`    |
| department       | `categories.department`    |
| country          | `country`                  |
| workplace type   | `workplaceType`            |
| job description  | `description` (HTML)       |
| bullet lists     | `lists[]` (text + content) |
| created date     | `createdAt` (ms epoch)     |
| job page URL     | `hostedUrl`                |
| application URL  | `applyUrl`                 |

The per-job **application URL** is always `hostedUrl + "/apply"` and equals
`applyUrl`. Pattern: `https://jobs.lever.co/{token}/{postingId}/apply`.

### Board page (HTML)

`https://jobs.lever.co/{token}` is an HTML page listing postings; not needed for
enumeration — use the JSON API instead.

---

## 2. Application Form

### URL pattern

```
https://jobs.lever.co/{token}/{postingId}/apply
```

### Form tag

```html
<form id="application-form" enctype="multipart/form-data" method="POST">
```

**No `action` attribute** → the form POSTs to the current URL
(`https://jobs.lever.co/{token}/{postingId}/apply`).

### Standard fields (present on every posting tested)

| Field            | HTML                                                                 | Required |
|------------------|----------------------------------------------------------------------|----------|
| Name             | `<input type="text" name="name" data-qa="name-input" required>`     | yes      |
| Email            | `<input type="email" name="email" data-qa="email-input" required>`  | yes      |
| Phone            | `<input type="text" name="phone" data-qa="phone-input" required>`   | yes (whoop) / optional elsewhere |
| Location         | `<input type="text" name="location" data-qa="location-input" maxlength="100" required>` + hidden `<input type="hidden" name="selectedLocation">` (JSON string of geocoded location) | yes |
| Current org/title| `<input type="text" name="org" data-qa="org-input">`                 | optional |
| Resume upload    | `<input type="file" name="resume" data-qa="input-resume" class="application-file-input invisible-resume-upload">` | optional (UI prompts for it) |

### Links section (per-company configurable labels)

Field name pattern: `urls[{Label}]`. Labels seen across boards:
`LinkedIn`, `Twitter`, `GitHub`, `Portfolio`, `Other`, `Quora`, `Design Portfolio`,
`Dribbble`, `Google Scholar`.

```html
<input type="text" name="urls[LinkedIn]">
<input type="text" name="urls[GitHub]">
<input type="text" name="urls[Portfolio]">
<input type="text" name="urls[Other]">
```

### Cover letter

Not a default field. Cover-letter-style questions are typically added by the
company as a custom `textarea` card (e.g. Qonto's "What leads you to apply?").
There is no reserved `coverLetter` field name on the standard form.

### Pronouns (some boards, e.g. Qonto)

```html
<input ... name="pronouns" ...>
```
Plus a checkbox group `#candidatePronounsCheckboxes` with standard / use-name-only
/ custom-pronouns options (handled by `application.js`).

### EEO questions (US boards, e.g. Whoop)

Rendered as `<select>` elements:

```html
<select name="eeo[gender]">
<select name="eeo[race]">
<select name="eeo[veteran]">
```

Options observed:
- `eeo[gender]`: `Male`, `Female`, `Decline to self-identify`
- `eeo[race]`: `Hispanic or Latino`, `White (Not Hispanic or Latino)`,
  `Black or African American (Not Hispanic or Latino)`,
  `Native Hawaiian or Other Pacific Islander (Not Hispanic or Latino)`,
  `Asian (Not Hispanic or Latino)`, `American Indian or Alaska Native (Not Hispanic or Latino)`,
  `Two or More Races (Not Hispanic or Latino)`, `Decline to self-identify`
- `eeo[veteran]`: `I am a veteran`, `I am not a veteran`, `Decline to self-identify`

Each begins with a placeholder `Select ...` option (empty value).
Some boards also surface a disability select (`#disabilitySelectElement`) with a
signature section; non-US boards (Mistral, Qonto) replace US EEO with a
self-service **survey** card (see below).

### Consent (some boards, e.g. Qonto)

```html
<input type="checkbox" name="consent[marketing]" value="0">
```

### Hidden / metadata fields (always present)

```html
<input type="hidden" name="accountId" value="{companyAccountIdUuid}">
<input type="hidden" name="linkedInData">
<input type="hidden" name="origin">
<input type="hidden" name="referer">
<input type="hidden" name="timezone" id="applicant-timezone" value="">
<input type="hidden" name="socialReferralKey">
<input type="hidden" name="socialSource">
<input type="hidden" name="resumeStorageId" value="">
<input type="hidden" name="source">
<input id="hcaptchaResponseInput" type="hidden" name="h-captcha-response" value="">
```

`accountId` is a per-company UUID (whoop = `340bc750-7cdd-4d26-acd6-9ecde06d53bb`,
mistral = `bd25b6fb-9adc-4ff5-8305-860f94209570`). It is embedded in the page and
must be sent back. `resumeStorageId` is populated by the resume-parse flow
(see §4) when a resume is uploaded and parsed before submit.

---

## 3. Custom Questions

There are **two encodings** for custom questions, both following the same
`baseTemplate` + `fieldN` pattern.

### A. Posting cards — `cards[{cardId}][...]`

```html
<input type="hidden"
       name="cards[{cardId}][baseTemplate]"
       value="{escaped JSON definition}">
<input type="radio" name="cards[{cardId}][field0]" value="Yes">
<input type="radio" name="cards[{cardId}][field0]" value="No">
```

The `baseTemplate` hidden input carries the full question definition as an
HTML-escaped JSON string. Unescaped shape:

```json
{
  "createdAt": 1581623851461,
  "updatedAt": 1581623851461,
  "text": "Location - Boston",          // card/group title
  "instructions": "",
  "type": "posting",
  "accountId": "340bc750-7cdd-4d26-acd6-9ecde06d53bb",
  "fields": [
    {
      "type": "multiple-choice",        // rendered as radio buttons
      "text": "Do you currently reside in the Greater Boston Area?",
      "description": "",
      "required": true,
      "id": "2445d3af-993d-47c5-80bd-c3ec06cfa07d",   // field ID — stable UUID
      "options": [
        { "text": "Yes", "optionId": "6e0c30af-b7a3-496a-9cef-8039209a7d22" },
        { "text": "No",  "optionId": "d16718ee-fbaf-407f-a3e5-95fe3d9ab7ec" }
      ]
    }
  ],
  "id": "6517f195-8fe3-462e-98aa-5f92fdd6f82a"        // card ID — stable UUID
}
```

Field types observed (all on live postings):

| `type`            | HTML rendering                                | Submitted value                 |
|-------------------|-----------------------------------------------|---------------------------------|
| `multiple-choice` | `<input type="radio" ...>` per option          | option **text** (e.g. `Yes`)    |
| `multiple-select` | `<input type="checkbox" ...>` per option       | option **text**                 |
| `dropdown`        | `<select>` with `<option value="text">`        | option **text** (or `""`)       |
| `textarea`        | `<textarea name="cards[{cardId}][field0]">`    | free text                       |
| `input-text`      | `<input type="text">`                          | free text                       |

**Important:** the submitted `value` is the option **text**, not the
`optionId`. The `optionId` is metadata in the baseTemplate only; the form posts
the text. (Verified on Qonto dropdown: `<option value="Yes, I can come to the
office at least 3 days per week.">…</option>`.)

A card with multiple questions uses `field0`, `field1`, … (e.g. Whoop "Work
Authorization" has two `multiple-choice` fields → `cards[…][field0]` and
`cards[…][field1]`).

### B. Survey cards — `surveysResponses[{surveyId}][...]`

Used for self-identified demographic surveys (Mistral, Qonto). Same structure,
different field prefix:

```html
<input type="hidden" name="surveysResponses[{surveyId}][baseTemplate]" value="{escaped JSON}">
<input type="hidden" name="surveysResponses[{surveyId}][surveyId]" value="{surveyId}">
<input type="radio" name="surveysResponses[{surveyId}][responses][field0]" value="Female">
<input type="hidden" name="surveysResponses[{surveyId}][candidateSelectedLocation]">
```

Survey baseTemplate `"type"` is `"survey"` (vs `"posting"` for cards). Fields
otherwise identical: `multiple-choice`, `textarea`, etc. Surveys are typically
optional (`required: false`).

### Stability of IDs

- `cardId` / `surveyId` / field `id` / `optionId` are all **UUIDs stable per
  question definition**. They persist across postings on the same board (the
  "Work Authorization" card has the same IDs on every Whoop posting that uses
  it). A board-level template can be cached, but always re-fetch the apply page
  per posting because a company can edit the template (updatedAt changes) and
  individual postings can have posting-specific cards.
- `postingId` is stable for the lifetime of the posting.
- `accountId` is stable per company/board.

### Recommended approach for an engine

1. GET the apply page HTML per posting.
2. Parse every `cards[…][baseTemplate]` and `surveysResponses[…][baseTemplate]`
   hidden input (unescape HTML entities → JSON).
3. Build a `{cardId/surveyId → {fieldIndex → {type, text, options, required}}}`
   map.
4. Render/answer using the **option text** as the submitted value, posting to
   `cards[{id}][field{N}]` or `surveysResponses[{id}][responses][field{N}]`.
5. Forward the `baseTemplate` hidden input verbatim (Lever expects it back).

---

## 4. Resume Upload

### Two-stage mechanism

Lever uses a **parse-then-submit** flow, controlled by `/js/parseResume.js`.

**Stage 1 — parse (XHR, immediate on file select):**

```
POST https://jobs.lever.co/parseResume
Content-Type: multipart/form-data

resume      = <file>           (field name: "resume")
accountId   = {accountId}      (from hidden input)
```

- Max file size: `100 * 1000 * 1000` bytes (100 MB) — `MAX_FILE_SIZE` in
  `parseResume.js`. Oversize → HTTP 400 `PayloadTooLargeError`.
- Response: JSON profile used to **autofill** form fields:
  ```json
  {
    "name": "...",
    "email": "...",
    "phone": "...",
    "position": "...",          // → org field
    "location": { "name": "..." },
    "links": [ { "domain": "linkedin.com", "url": "..." }, ... ]
  }
  ```
- Autofill targets (only if the user hasn't manually touched the field):
  `name`, `email`, `phone`, `org` (← position), `location`, `selectedLocation`
  (← JSON of location), and `urls[LinkedIn|Twitter|Quora|GitHub|Other]`
  (matched by link domain).
- `parseResume.js` does NOT set `resumeStorageId` itself; the storage ID is
  populated by `application.js` / page logic after parse so the final submit
  can reference the already-uploaded resume. The hidden field
  `<input type="hidden" name="resumeStorageId" value="">` is sent on final
  submit.

**Stage 2 — final submit:** the same `resume` file is re-sent as
`multipart/form-data` field `resume` in the application POST (see §5). The form
`enctype="multipart/form-data"` carries both the file and all text fields.

So the engine must either (a) re-attach the resume file on the final POST, or
(b) perform the `/parseResume` POST first, capture `resumeStorageId`, and send
that on the final POST. Sending the file directly on the apply POST is the
simplest and works.

---

## 5. Submit Endpoint

### Request

```
POST https://jobs.lever.co/{token}/{postingId}/apply
Content-Type: multipart/form-data  (form enctype)
```

- URL = the apply page URL (form has no `action`).
- Method = `POST`.
- Body = `multipart/form-data` containing **all** standard fields, hidden
  metadata, every `cards[…][baseTemplate]` + answered `cards[…][fieldN]`,
  every `surveysResponses[…]`, EEO selects (`eeo[gender|race|veteran]`),
  `urls[…]`, `consent[…]`, `pronouns`, and the `resume` file part.
- The `cards[…][baseTemplate]` hidden inputs **must** be echoed back verbatim
  (they contain the question definition Lever uses to validate answers).
- `h-captcha-response` must be populated (see §6).

### Plain HTTP vs browser

A plain HTTP POST **can** work if you supply a valid `h-captcha-response` token
(obtained out-of-band) and all required fields. There is no CSRF token, no
session cookie requirement, and no JS-only signing on the form itself — the
hidden-field values are all present in the static HTML. The only blocker is
hCaptcha (§6), which requires either a browser executing JS or a captcha-solving
step. Without a valid `h-captcha-response`, the server rejects the submission.

---

## 6. Anti-Bot

### hCaptcha (invisible / passive)

Every apply page loads:

```html
<script src="https://js.hcaptcha.com/1/secure-api.js?host=jobs.lever.co&onload=Onload"></script>
<div id="h-captcha" data-sitekey="e33f87f8-88ec-4e1a-9a13-df9bbb1d8120"></div>
<input id="hcaptchaResponseInput" type="hidden" name="h-captcha-response" value="">
```

- **Provider:** hCaptcha (not reCAPTCHA).
- **Sitekey:** `e33f87f8-88ec-4e1a-9a13-df9bbb1d8120` (shared across
  `jobs.lever.co` boards — verified identical on whoop, mistral, qonto).
- **Mode:** passive/invisible — `hcaptcha.execute(captchaId)` is called on form
  submit; the token is written into `h-captcha-response` and submitted with the
  form. The user normally does not solve a challenge; hCaptcha scores the
  browser fingerprint. A visual challenge may be triggered by hCaptcha when the
  score is low (suspicious UA, no JS, repeated submissions, datacenter IP).
- **Cloudflare:** not observed on `jobs.lever.co` apply pages in testing
  (no Cloudflare challenge page, no `cf-` cookies required). The API and apply
  pages are served directly. Datacenter IPs may still get challenged by hCaptcha
  itself.

### Trigger conditions (observed/expected)

- Missing/empty `h-captcha-response` → server-side rejection.
- Programmatic POSTs from datacenter IPs with no prior JS execution → high
  chance of hCaptcha raising a visual challenge or returning no token.
- Rapid repeat submissions from the same IP → likely escalation.

### Mitigation for an engine

Run the apply flow in a real browser (Playwright/headless Chromium) so hCaptcha
can execute passively and produce a token. A pure-curl flow requires an
h-captcha-response token harvested separately (not recommended; fragile and
against hCaptcha ToS).

---

## 7. Worked Example

Pick a currently-open Whoop posting:

- postingId: `38493926-11d7-4dbc-8620-243ec9c93f9a`
- title: "Allocation Analyst, Wholesale Planning"
- apply URL: `https://jobs.lever.co/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a/apply`
- accountId: `340bc750-7cdd-4d26-acd6-9ecde06d53bb`

This posting's custom cards (extracted from its apply page):

| cardId | field | type | question | options |
|--------|-------|------|----------|---------|
| `6517f195-8fe3-462e-98aa-5f92fdd6f82a` | field0 | multiple-choice | "Do you currently reside in the Greater Boston Area?" | Yes / No |
| `219fbe07-a192-4bc0-94e1-eeab70c81107` | field0 | multiple-choice | "This is a hybrid role…4 days per week. Does this setup align…?" | Yes / No |
| `7b840a00-bccd-4752-a3dd-2c887a15ffe2` | field0 | multiple-choice | "Are you legally authorized to work in the United States?" | Yes / No |
| `7b840a00-bccd-4752-a3dd-2c887a15ffe2` | field1 | multiple-choice | "Will you now or in the future require visa sponsorship…?" | Yes / No |
| `2690853c-4731-41b0-a871-687f8f7b351d` | field0 | textarea | "Why are you interested in working at WHOOP?" | free text |

### Placeholder curl command

> This is for schema illustration only. Replace `{HCAPTCHA_TOKEN}` with a real
> hCaptcha token obtained in a browser. Do not run without a valid token and
> genuine candidate data.

```bash
curl -X POST \
  'https://jobs.lever.co/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a/apply' \
  -H 'Referer: https://jobs.lever.co/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a/apply' \
  -H 'User-Agent: Mozilla/5.0 (...)' \
  -F 'name=Jane Doe' \
  -F 'email=jane.doe@example.com' \
  -F 'phone=+1-555-555-5555' \
  -F 'location=Boston, MA' \
  -F 'selectedLocation={"name":"Boston, MA"}' \
  -F 'org=Senior Analyst at Acme Corp' \
  -F 'urls[LinkedIn]=https://www.linkedin.com/in/janedoe' \
  -F 'urls[GitHub]=https://github.com/janedoe' \
  -F 'urls[Portfolio]=https://janedoe.com' \
  -F 'urls[Other]=' \
  -F 'resume=@/path/to/Jane_Doe_Resume.pdf' \
  -F 'resumeStorageId=' \
  -F 'accountId=340bc750-7cdd-4d26-acd6-9ecde06d53bb' \
  -F 'origin=' \
  -F 'referer=' \
  -F 'timezone=America/New_York' \
  -F 'socialReferralKey=' \
  -F 'socialSource=' \
  -F 'source=' \
  -F 'linkedInData=' \
  -F 'eeo[gender]=Female' \
  -F 'eeo[race]=White (Not Hispanic or Latino)' \
  -F 'eeo[veteran]=I am not a veteran' \
  -F 'h-captcha-response={HCAPTCHA_TOKEN}' \
  -F 'cards[6517f195-8fe3-462e-98aa-5f92fdd6f82a][baseTemplate]={"createdAt":1581623851461,...VERBATIM_FROM_PAGE...}' \
  -F 'cards[6517f195-8fe3-462e-98aa-5f92fdd6f82a][field0]=Yes' \
  -F 'cards[219fbe07-a192-4bc0-94e1-eeab70c81107][baseTemplate]={...VERBATIM_FROM_PAGE...}' \
  -F 'cards[219fbe07-a192-4bc0-94e1-eeab70c81107][field0]=Yes' \
  -F 'cards[7b840a00-bccd-4752-a3dd-2c887a15ffe2][baseTemplate]={...VERBATIM_FROM_PAGE...}' \
  -F 'cards[7b840a00-bccd-4752-a3dd-2c887a15ffe2][field0]=Yes' \
  -F 'cards[7b840a00-bccd-4752-a3dd-2c887a15ffe2][field1]=No' \
  -F 'cards[2690853c-4731-41b0-a871-687f8f7b351d][baseTemplate]={...VERBATIM_FROM_PAGE...}' \
  -F 'cards[2690853c-4731-41b0-a871-687f8f7b351d][field0]=I am excited by WHOOPs mission to unlock human performance...'
```

Notes on the curl:
- Each `cards[…][baseTemplate]` value must be the **exact** HTML-unescaped JSON
  string from the corresponding hidden input on the apply page (re-fetch per
  posting; do not hard-code — `updatedAt` and `optionId`s can change when the
  company edits the template).
- `selectedLocation` is a JSON string; the page normally fills it from the
  `/retrieveLocations` geocoder. A plain string like `{"name":"Boston, MA"}`
  works for a free-text location.
- `eeo[…]` values must exactly match an `<option>` text (or be empty/`Decline to self-identify`).
- A real submission should be driven from a browser session so `h-captcha-response`
  is populated by hCaptcha's passive execution; plain curl with a harvested
  token is fragile.

---

## Appendix: Per-board variance checklist

| Feature              | whoop | mistral | qonto |
|----------------------|-------|---------|-------|
| `categories.commitment` | absent | present | present |
| `categories.department` | absent | absent | present |
| EEO selects (`eeo[…]`)   | yes (US) | no | no |
| Survey (`surveysResponses[…]`) | no | yes (demographic) | no |
| Pronouns field           | no | no | yes |
| Consent (`consent[marketing]`) | no | no | yes |
| `urls[…]` labels         | LinkedIn/GitHub/Portfolio/Twitter/Other | LinkedIn/Twitter/GitHub/Google Scholar/Design Portfolio | LinkedIn/GitHub/Dribbble/Other |
| Dropdown custom question | no | no | yes |
| multiple-select custom   | no | no | yes |

Always fetch the specific posting's apply page and parse its fields dynamically —
do not assume a fixed schema across all 23 companies.

---

## Source endpoints (verified 2026-07-02)

- `https://api.lever.co/v0/postings/whoop?mode=json` (159 postings)
- `https://api.lever.co/v0/postings/mistral?mode=json`
- `https://api.lever.co/v0/postings/qonto?mode=json`
- `https://api.lever.co/v0/postings/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a?mode=json`
- `https://jobs.lever.co/whoop/38493926-11d7-4dbc-8620-243ec9c93f9a/apply` (HTML form)
- `https://jobs.lever.co/mistral/7894fd8a-ffc9-4c89-87f0-f8a7b695cf01/apply` (HTML form)
- `https://jobs.lever.co/qonto/4f0ad125-61c3-4dbd-b266-9228503d4de8/apply` (HTML form)
- `https://jobs.lever.co/js/parseResume.js`
- `https://jobs.lever.co/js/application.js`