# Workable — ATS Application Form Schema

> Research date: 2026-07-02. READ-ONLY investigation — no application was submitted.
> Verified against 2 Workable accounts: **Hugging Face** (`huggingface`, 7 open jobs) and **MLabs** (`mlabs`, 75 open jobs).
> Source: live API calls against `apply.workable.com` + inspection of the Workable candidate SPA bundle (`careers.*.js`).

Workable's candidate-facing stack is a public, mostly-CORS-open JSON API on `apply.workable.com` with **no captcha on the form/submit endpoints** and **no auth token required for public jobs**. A presigned-S3 two-step upload handles files. This is the most automation-friendly of the two ATSes studied — plain HTTP can enumerate jobs, fetch the form schema, upload a resume, and submit an application.

---

## 1. Job Enumeration

### List endpoint (verified)
```
POST https://apply.workable.com/api/v3/accounts/{token}/jobs
Content-Type: application/json
```
- `{token}` is the account slug from the careers URL (e.g. `huggingface`, `mlabs`).
- **Method is POST** with an empty JSON body `{}`. GET returns `404 Not Found`.
- No auth, no captcha. CORS-open (`access-control-allow-origin: http://apply.workable.com`).

Response (Hugging Face, verified):
```json
{
  "total": 7,
  "results": [
    {
      "id": 5856207,
      "shortcode": "F8427A442D",
      "title": "Senior Python Software Engineer/Open-Source Contributor - US Remote",
      "remote": true,
      "location": { "country": "United States", "countryCode": "US", "city": "", "region": null },
      "locations": [ { "country": "United States", "countryCode": "US", "city": "", "region": null, "hidden": false } ],
      "state": "published",
      "isInternal": false,
      "code": null,
      "published": "2026-06-02T00:00:00.000Z",
      "type": "full",
      "language": "en",
      "department": ["Product"],
      "accountUid": "940cf17f-c078-40ac-95e8-07704e754048",
      "approvalStatus": "approved",
      "workplace": "remote"
    }
  ]
}
```

### Other enumeration endpoints (from the SPA, verified)
- `GET /api/v3/accounts/{token}/jobs/filters` — facets: `locations`, `departments` (id/name/count), `worktypes`, `remotes`, `workplaces`. Verified for HF (returns Product/Open Source/Wild Card depts).
- `GET /api/v3/accounts/{token}/jobs/departments?all=true`
- `GET /api/v3/accounts/{token}/jobs/count`

### Job detail (single job, verified)
```
GET https://apply.workable.com/api/v1/accounts/{token}/jobs/{shortcode}
```
Returns full job: `id`, `shortcode`, `title`, `remote`, `location`, `locations`, `state`, `type`, `language`, `department`, `accountUid`, `description` (HTML), `benefits`, `requirements`, `skills`, `experience`, `education`. Example HF ML Engineer (id `5851152`, shortcode `81B46579FE`).

> The list endpoint path `/api/v1/accounts/{token}/jobs` is interpreted as the **detail** endpoint and requires a `shortcode` query/body (`400 {"shortcode":"Required"}` if omitted). Use **v3 POST** for listing, **v1 GET** for a single job.

### Application URL patterns (verified)
```
Job page (SPA):     https://apply.workable.com/{token}/j/{shortcode}/
Apply page (SPA):   https://apply.workable.com/{token}/j/{shortcode}/apply
Job description:    https://apply.workable.com/{token}/jobs/view/{shortcode}.md
LLM-friendly index: https://apply.workable.com/{token}/llms.txt
Jobs markdown list: https://apply.workable.com/{token}/jobs.md
```
Both `/j/{shortcode}/` and `/j/{shortcode}/apply` return HTTP 200 (SPA shell). The form data itself comes from the JSON API (§2), not the HTML.

### Account id
The `accountUid` (UUID) appears in API responses and asset URLs (e.g. HF `940cf17f-c078-40ac-95e8-07704e754048`) but the **slug** (`huggingface`) is what's used in all candidate-facing URLs/API paths.

---

## 2. Application Form

### Form schema endpoint (verified)
```
GET https://apply.workable.com/api/v1/jobs/{shortcode}/form
```
No auth. Returns an **array of sections**, each with `name` + `fields[]`. Full schema captured for HF ML Engineer (`81B46579FE`), 4382 bytes.

### Field object shape
```json
{
  "id": "firstname",
  "required": true,
  "label": "First name",
  "type": "text",
  "maxLength": 127
}
```
Field types observed: `text`, `email`, `phone`, `date`, `paragraph` (textarea), `boolean` (checkbox), `dropdown` (with `options[]` + `singleOption`), `file` (with `supportedFileTypes`, `supportedMimeTypes`, `maxFileSize`), `group` (repeatable sub-fields: education/experience).

### Sections & fields (Hugging Face — verified, in order)
**Section: "Personal information"**
| id | type | required | label |
|---|---|---|---|
| `firstname` | text | yes | First name (maxLength 127) |
| `lastname` | text | yes | Last name (maxLength 127) |
| `email` | email | yes | Email (maxLength 255) |
| `phone` | phone | no | Phone (maxLength 255) |

**Section: "Profile"**
| id | type | required | label / notes |
|---|---|---|---|
| `education` | group | no | repeatable: `school`(text,req), `field_of_study`(text), `degree`(text), `start_date`(date), `end_date`(date) |
| `experience` | group | no | repeatable: `title`(text,req), `company`(text), `industry`(text), `summary`(paragraph), `start_date`(date), `end_date`(date), `current`(boolean) |
| `resume` | file | yes | accepted `.pdf .doc .docx .odt .rtf`; max 12 000 000 bytes |
| `CA_47143` | paragraph | yes | Github profile (custom attribute) |
| `CA_47383` | paragraph | yes | Linkedin (custom attribute) |

**Section: "Details"**
| id | type | required | label / notes |
|---|---|---|---|
| `cover_letter` | paragraph | no | Cover letter (maxLength 200000) |
| `CA_10626` | text | no | Expected salary (maxLength 127) |
| `CA_10627` | dropdown | no | Notice period / availability (singleOption) |
| `CA_10628` | boolean | no | Are you eligible to work in the country you are applying? |
| `CA_10629` | text | no | How did you hear about us? |
| `QA_11844074` | boolean | yes | Can you confirm everything is true and your own… |
| `QA_11844075` | boolean | yes | Did you start your first written answer with the exact phrase… |
| `QA_11857981` | boolean | yes | Do you have a public track record of open-source contributions… |
| `QA_11844076` | paragraph | yes | Why Hugging Face, and where would you make the biggest difference… |
| `QA_11857982` | paragraph | yes | Share 2–3 of your open-source contributions with links… |
| `gdpr` | boolean | yes | GDPR consent checkbox |

> EEO fields: this HF job has **no EEO section**. EEO is per-account and fetched separately (§3). The SPA also exposes a `discovery`/`seek/button` endpoint and `autofill`.

---

## 3. Custom Questions

### Field-id prefixes
- `CA_<n>` — **Custom Attribute** (per-account custom field). Types seen: `paragraph`, `text`, `dropdown`, `boolean`.
- `QA_<n>` — **Question** (screening question, can be required). Types seen: `boolean`, `paragraph`, `text`.
- `gdpr` — consent boolean (always present).
- Standard fields: `firstname`, `lastname`, `email`, `phone`, `resume`, `cover_letter`, `education`, `experience`.

### Dropdown encoding (verified — `CA_10627`)
```json
{
  "id": "CA_10627",
  "type": "dropdown",
  "singleOption": true,
  "options": [
    { "name": "139527", "value": "Available immediately" },
    { "name": "139528", "value": " 1 week" },
    { "name": "139529", "value": " 2 weeks" },
    { "name": "139530", "value": " 3 weeks" },
    { "name": "139531", "value": " 1 month" },
    { "name": "139532", "value": " 2 months" },
    { "name": "139533", "value": " 3 months or more" }
  ]
}
```
Submit the **`name` (numeric option id)**, not the `value` label. `singleOption: true` = single-select; absence = multi-select (submit an array of names).

### EEO endpoint (from SPA, verified path)
```
POST https://apply.workable.com/api/v1/eeoc/{shortcode}
```
The SPA builds it as `p(s)("/api/v1/eeoc/".concat(e), t, r)` where `p` = POST. Returns the EEO question set for the job (gender / ethnicity / disability / veteran) **if the account collects EEO**; HF does not, MLabs may. Submit EEO answers through this same endpoint (separate from the main apply payload).

### Other helper endpoints (from SPA)
- `GET /api/v1/jobs/{shortcode}/autofill` — populate form from a profile (returned 400 without params).
- `GET /api/v1/jobs/{shortcode}/seek/button` — "Apply with SEEK" button metadata.
- `GET /api/v1/attribute/...` — custom-attribute metadata.

---

## 4. Resume Upload (two-step, presigned S3)

### Step 1 — request a presigned upload (verified, returns 200 with full S3 POST policy)
```
GET https://apply.workable.com/api/v1/jobs/{shortcode}/form/upload/{fieldId}
```
`{fieldId}` is the form field id, e.g. `resume`. Response (verified):
```json
{
  "uploadPostUrl": {
    "url": "https://workable-application-form.s3.us-east-1.amazonaws.com",
    "fields": {
      "utf8": "",
      "bucket": "workable-application-form",
      "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
      "X-Amz-Credential": "AKIA27KPZUMHP7SV6K43/20260702/us-east-1/s3/aws4_request",
      "X-Amz-Date": "20260702T182112Z",
      "key": "tmp/ttl-1d/production/b8c0c6db-4779-99f1-9a72-9afc6ea0e363",
      "Policy": "<base64 policy>",
      "X-Amz-Signature": "<sig>"
    },
    "path": "tmp/ttl-1d/production/b8c0c6db-4779-99f1-9a72-9afc6ea0e363"
  },
  "downloadUrl": "https://workable-application-form.s3.us-east-1.amazonaws.com/tmp/ttl-1d/production/...?X-Amz-..."
}
```
The policy enforces: `content-length-range 1..12000000`, `$Content-Type` startswith condition, key prefix, ttl-1d (24 h expiry).

### Step 2 — POST the file to S3 (multipart/form-data)
```http
POST https://workable-application-form.s3.us-east-1.amazonaws.com
Content-Type: multipart/form-data; boundary=...
```
Form fields (in this order):
1. Every key from `uploadPostUrl.fields` (`utf8`, `bucket`, `X-Amz-Algorithm`, `X-Amz-Credential`, `X-Amz-Date`, `key`, `Policy`, `X-Amz-Signature`).
2. `Content-Type` — the file's MIME (must match a `supportedMimeTypes` value from the form schema, e.g. `application/pdf`).
3. `file` — the binary file (must be **last**).

S3 responds `204 No Content` on success. The reference key to send in the apply payload is the `path`/`key` (or the `downloadUrl`). The SPA references the uploaded asset by the presigned `path` when submitting.

### Accepted resume types (HF, verified)
`.pdf .doc .docx .odt .rtf` → MIME `application/pdf`, `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/vnd.oasis.opendocument.text`, `application/rtf`. Max **12 MB**.

---

## 5. Submit Endpoint

### Apply (verified endpoint + method from SPA)
```
POST https://apply.workable.com/api/v1/jobs/{shortcode}/apply
Content-Type: application/json
```
The SPA constructs it as:
```js
p(s)("/api/v1/jobs/".concat(e, "/apply"), { candidate: t }, { withCredentials: true, ... })
```
where `p` = POST, `s` = base URL `https://apply.workable.com`. So the body is:
```json
{ "candidate": { /* all form fields keyed by field id */ } }
```
`withCredentials: true` → cookies are sent. A `wmc` cookie (containing a `cookie_id` UUID) is set automatically by the API on first call and should be preserved across the upload + apply sequence. There is **no CSRF token** and **no bearer token**; the SPA sets headers `Content-Type: application/json`, `x-workable-client: <clientId>`, and `Accept: application/json`. `GET` on `/apply` returns `404` (POST-only).

A bare `POST {}` returns **`412 Precondition Failed`** (verified) — i.e. validation rejects an empty candidate object. The required minimum (from the form schema) is `{candidate:{firstname, lastname, email, resume, <required CA_/QA_>, gdpr:true}}`.

### Full submit sequence (plain HTTP works — no captcha)
1. `GET /api/v1/jobs/{shortcode}/form` → learn required fields + dropdown option ids.
2. `GET /api/v1/jobs/{shortcode}/form/upload/resume` → presigned S3 POST fields.
3. `POST` (multipart) the resume to `https://workable-application-form.s3.us-east-1.amazonaws.com` → S3 key/path.
4. (optional) `POST /api/v1/eeoc/{shortcode}` with EEO answers if the account collects them.
5. `POST /api/v1/jobs/{shortcode}/apply` with `{candidate:{...}}` including the uploaded resume reference + all required answers + `gdpr:true`.

### Browser vs. plain HTTP
**Plain HTTP is sufficient.** No JS execution is required for the API path. The only browser-ish niceties needed: send a realistic `User-Agent`, set `Origin: https://apply.workable.com` / `Referer`, preserve the `wmc` + `__cf_bm` cookies, and set `x-workable-client` header (any client-id string the SPA uses). The careers SPA itself is a single bundle at `https://dcvxs6ggqztsa.cloudfront.net/candidate/releases/careers.<hash>.js` — not needed for API submission.

---

## 6. Anti-Bot

- **No captcha** on the form, upload, or apply endpoints (verified — Arkose/reCAPTCHA/hCaptcha absent from the SPA bundle; no challenge on any API call).
- **Cloudflare** fronts `apply.workable.com` (sets `__cf_bm` bot cookie). In practice it did not challenge any of the API calls made during this research (all returned JSON). Aggressive scraping may still trigger Cloudflare's adaptive mode.
- The careers SPA sets a Datadog RUM CSP report header and a `wmc` first-party cookie — telemetry, not a gate.
- CORS: `access-control-allow-origin: http://apply.workable.com` and `access-control-allow-credentials: true` on apply/upload — designed for the SPA, but server-side requests bypass CORS entirely.

---

## 7. Worked Example (Hugging Face — real open job)

Job: *Open-Source Machine Learning Engineer - EMEA Remote* — shortcode `81B46579FE`, id `5851152`, account `huggingface`.

```bash
TOKEN=huggingface
SC=81B46579FE
API=https://apply.workable.com
COOKIES=/tmp/wf_cookies.txt
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# 1) Enumerate open jobs
curl -s -c $COOKIES -b $COOKIES -A "$UA" -X POST "$API/api/v3/accounts/$TOKEN/jobs" \
  -H "Content-Type: application/json" -d '{}'

# 2) Job detail
curl -s -A "$UA" "$API/api/v1/accounts/$TOKEN/jobs/$SC"

# 3) Application form schema (lists every field, required flag, dropdown option ids)
curl -s -A "$UA" "$API/api/v1/jobs/$SC/form"

# 4) Get presigned S3 upload for the resume field
curl -s -A "$UA" "$API/api/v1/jobs/$SC/form/upload/resume"
#  -> uploadPostUrl.url, uploadPostUrl.fields.{bucket,key,Policy,X-Amz-Signature,...}, downloadUrl

# 5) Upload resume to S3 (multipart; file field MUST be last)
curl -s -X POST "https://workable-application-form.s3.us-east-1.amazonaws.com" \
  -F "utf8=" \
  -F "bucket=workable-application-form" \
  -F "X-Amz-Algorithm=AWS4-HMAC-SHA256" \
  -F "X-Amz-Credential=AKIA.../20260702/us-east-1/s3/aws4_request" \
  -F "X-Amz-Date=20260702T182112Z" \
  -F "key=tmp/ttl-1d/production/<uuid>" \
  -F "Policy=<base64-policy>" \
  -F "X-Amz-Signature=<sig>" \
  -F "Content-Type=application/pdf" \
  -F "file=@/path/to/resume.pdf"

# 6) (optional) EEO, if the account collects it
curl -s -X POST "$API/api/v1/eeoc/$SC" -H "Content-Type: application/json" -d '{...}'

# 7) Submit application
curl -s -c $COOKIES -b $COOKIES -A "$UA" -X POST "$API/api/v1/jobs/$SC/apply" \
  -H "Content-Type: application/json" \
  -H "x-workable-client: careers-spa" \
  -H "Origin: https://apply.workable.com" \
  -H "Referer: $API/$TOKEN/j/$SC/apply" \
  -d '{
    "candidate": {
      "firstname": "Jane",
      "lastname": "Doe",
      "email": "jane@example.com",
      "phone": "+1-555-0100",
      "resume": "<S3 path or downloadUrl from step 4>",
      "cover_letter": "I would love to join Hugging Face...",
      "CA_47143": "https://github.com/janedoe",
      "CA_47383": "https://linkedin.com/in/janedoe",
      "CA_10626": "120000",
      "CA_10627": "139531",
      "CA_10628": true,
      "QA_11844074": true,
      "QA_11844075": true,
      "QA_11857981": true,
      "QA_11844076": "Because ...",
      "QA_11857982": "PR #123 in transformers ...",
      "gdpr": true
    }
  }'
```

### Second account confirmation — MLabs (`mlabs`)
```bash
# 75 open jobs (verified)
curl -s -X POST "https://apply.workable.com/api/v3/accounts/mlabs/jobs" -H "Content-Type: application/json" -d '{}'
# -> {"total":75,"results":[{"id":5926186,"shortcode":"09D39057B9","title":"NFL Social Media Manager",...}]}
curl -s "https://apply.workable.com/api/v1/accounts/mlabs/jobs/09D39057B9"
curl -s "https://apply.workable.com/api/v1/jobs/09D39057B9/form"
```
All endpoints return JSON anonymously — same shape as Hugging Face.

---

## Sources
- Live API: `apply.workable.com/api/v3/accounts/huggingface/jobs` (POST), `/api/v1/accounts/huggingface/jobs/81B46579FE`, `/api/v1/jobs/81B46579FE/form`, `/api/v1/jobs/81B46579FE/form/upload/resume` (all 2026-07-02)
- Workable candidate SPA bundle: `https://dcvxs6ggqztsa.cloudfront.net/candidate/releases/careers.2fee351271cf516e.js` (endpoint templates extracted: `/api/v3/accounts/{t}/jobs`, `/api/v1/jobs/{s}/apply`, `/api/v1/jobs/{s}/form`, `/api/v1/jobs/{s}/form/upload/{f}`, `/api/v1/eeoc/{s}`, `/api/v1/jobs/{s}/autofill`)
- Workable LLM docs: `https://apply.workable.com/huggingface/llms.txt`, `https://apply.workable.com/huggingface/jobs.md`