# SmartRecruiters — ATS Application Form Schema

> Research date: 2026-07-02. READ-ONLY investigation — no application was submitted.
> Verified against 3 companies: **Nexthink** (93 open jobs), **Visa** (3), **Uber** (1).
> Source: live API calls + official SmartRecruiters Developer docs (developers.smartrecruiters.com).

There are **two distinct application channels** in SmartRecruiters. An auto-apply engine must choose between them:

| Channel | Endpoint set | Auth | Captcha | Use case |
|---|---|---|---|---|
| **Public Online Job Application (OGA)** | `jobs.smartrecruiters.com/{company}/{id}-{slug}?oga=true` (HTML SPA) + internal `smart-api` | Anonymous (Arkose token) | **Yes — Arkose Labs + Cloudflare** | What a human applicant uses in the browser |
| **Customer / Partner Application API** | `https://api.smartrecruiters.com/v1/postings/{uuid}/candidates` (JSON) | `X-SmartToken` (company API token) or OAuth2 `candidate_applications_manage` | No | Authorized career-site/job-board integrations |

The public OGA flow is anti-bot-gated and not drivable with plain HTTP. The Customer API is clean JSON but requires a token the applicant does not have. Both are documented below.

---

## 1. Job Enumeration

### Endpoint (verified working)
```
GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit={N}&offset={M}
```
- `{company}` is the **company identifier** as used in the career-site URL, **case-sensitive** (e.g. `Nexthink`, `Visa`, `Uber`). Not the numeric company ID.
- Headers: `Accept: application/json` is sufficient (anonymous, read-only).

### Response shape (verified — Nexthink)
```json
{
  "offset": 0,
  "limit": 3,
  "totalFound": 93,
  "content": [
    {
      "id": "744000135484160",
      "uuid": "5a536b6f-d6b0-4d37-a9e2-b4e7c98eebde",
      "jobId": "f58778b5-8f64-423d-a325-64ca8fbf5032",
      "jobAdId": "dbc39402-6fe5-4c26-ba3a-15039f21beb8",
      "name": "Senior Software Engineer C++ (Endpoint Agent, OS internals)",
      "refNumber": "REF3401J",
      "company": { "identifier": "Nexthink", "name": "Nexthink" },
      "releasedDate": "2026-07-02T12:13:14.188Z",
      "location": { "city": "Madrid", "region": "MD", "country": "es",
                     "remote": false, "hybrid": true, "fullLocation": "Madrid, MD, Spain" },
      "industry":    { "id": "computer_software", "label": "Computer Software" },
      "department":  { "id": 3439719, "label": "Data Platform" },
      "function":    { "id": "information_technology", "label": "Information Technology" },
      "typeOfEmployment": { "id": "permanent", "label": "Full-time" },
      "experienceLevel":  { "id": "mid_senior_level", "label": "Mid-Senior Level" },
      "language": { "code": "en", "label": "English" },
      "customField": [
        { "fieldId": "69624c5e9840f3caaa03a84a", "fieldLabel": "Dept",
          "valueId": "Data-Platform-Department", "valueLabel": "Data Platform" },
        { "fieldId": "COUNTRY", "fieldLabel": "Country/Region",
          "valueId": "ch", "valueLabel": "Switzerland" }
      ]
    }
  ]
}
```

### Key IDs per job
- `id` — numeric posting ID (used in the public posting/apply URL slug).
- `uuid` — posting UUID (**used as the `:uuid` path param in the Application API**).
- `jobId` — internal job UUID.
- `jobAdId` — job-ad UUID.

> Note: the list response sometimes omits `postingUrl`/`applyUrl` (e.g. Visa/Uber). Always fetch the **detail** endpoint to get the apply URL.

### Job detail endpoint (verified)
```
GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id-or-uuid}
```
Returns the full posting including `postingUrl`, `applyUrl`, `referralUrl`, `jobAd.sections` (companyDescription, jobDescription, qualifications, additionalInformation), and the full `customField` array.

### Application URL pattern (verified — identical for Nexthink & Visa)
```
postingUrl  = https://jobs.smartrecruiters.com/{company}/{id}-{slug}
applyUrl    = https://jobs.smartrecruiters.com/{company}/{id}-{slug}?oga=true
referralUrl = https://jobs.smartrecruiters.com/external-referrals/company/{company}/publication/{uuid}?dcr_ci={company}
```
`oga=true` = "Online Job Application" — opens the apply form SPA. The `{slug}` is the SEO slug of the job title; the `{id}` is the only part strictly required.

### Other useful endpoints (from the career-site SPA)
- `GET .../postings?limit=N&offset=M&q={keyword}&country={code}&city={city}&function={id}&department={id}&typeOfEmployment={id}` — filtered search.
- Company metadata is embedded in the careers HTML (`companyIdentifier`, `companyID` e.g. Nexthink → `106396183`).

---

## 2. Application Form

### Public OGA form (browser-only)
URL: `https://jobs.smartrecruiters.com/{company}/{id}-{slug}?oga=true`

Fetching this URL with curl (any UA) returns a **1.7–2.2 KB stub** that is purely an **Arkose Labs + Cloudflare challenge** — not the form. Verified:
```
<html><head><title>smartrecruiters.com</title>...
<script data-cfasync="false">var dd={'rt':'c','cid':'...','hsh':'...','t':'bv',
  'host':'geo.captcha-delivery.com','cookie':'...'}</script>
<script src="https://ct.captcha-delivery.com/c.js"></script>
<iframe src="/cdn-cgi/challenge-platform/scripts/jsd/main.js">  // Cloudflare JS challenge
```
The actual form fields are rendered by a JS bundle loaded **only after** the Arkose challenge is solved. The form cannot be scraped via plain HTTP.

### Form fields (from the official Application API schema)
The OGA form maps to the Customer Application API payload. Fields, verified against the developer docs:

| Field | JSON key | Required | Type / encoding |
|---|---|---|---|
| First name | `firstName` | yes | string |
| Last name | `lastName` | yes | string |
| Email | `email` | yes | string |
| Phone | `phoneNumber` | no | string |
| Location | `location` | no | object: `country`, `countryCode`, `regionCode`, `region`, `city`, `lat`, `lng` |
| Web / social | `web` | no | object: `skype`, `linkedIn`, `facebook`, `twitter`, `website` |
| Resume | `resume` | no* | object: `fileName`, `mimeType`, `fileContent` (**Base64**, max 2 MB; PDF/DOC/DOCX/RTF/JPG/PNG) |
| Cover letter | `messageToHiringManager` **or** `attachments[]` | no | string / attachment object (same shape as resume) |
| Attachments | `attachments[]` | no | array of `{fileName, mimeType, fileContent}` (Base64); 2 MB each |
| Avatar | `avatar` | no | `{fileName, mimeType, fileContent}` (Base64 image) |
| Education | `education[]` | no | `institution`, `degree`, `major`, `current`, `location`, `startDate`, `endDate`, `description` |
| Experience | `experience[]` | no | `title`, `company`, `current`, `startDate`, `endDate`, `location`, `description` |
| Tags | `tags` | no | string[] |
| Screening answers | `answers` | yes (if required Qs exist) | see §3 |
| GDPR consent | `consentDecisions` (or legacy `consent: bool`) | depends on config | see §3 |
| Diversity / EEO | part of `answers` (diversity questions) | no | must be displayed below other questions with confidentiality header |
| Source | `sourceDetails` | no | `sourceTypeId`, `sourceSubTypeId`, `sourceId` |
| Internal flag | `internal` | no | boolean (employee applications) |
| AI disclosure | (display) `aiSettings.aiDisclosureLabel` | no | shown in form if AI solutions used |

`*` Resume is effectively required on most postings even though the API marks it optional.

---

## 3. Custom Questions (Screening / Consent / Diversity)

### Configuration endpoint
```
GET https://api.smartrecruiters.com/v1/postings/{uuid}/configuration
```
Returns: screening questions, diversity questions, privacy policies, **consent configuration**, and `aiSettings`. Requires `X-SmartToken`. The response drives which `answers` and `consentDecisions` the form must submit.

> Could not be exercised live (no token) — confirmed via official docs. Use `conditionalsIncluded: true` on the POST to answer conditional questions (one level deep; only `SINGLE_SELECT` can be a parent).

### Answer encoding
`answers` is an array; each entry:
```json
{
  "id": "<questionId>",
  "records": [ { "fields": { "<fieldId>": ["<value>"] } } ]
}
```
Repeatable questions → multiple entries in `records`.

| Question type | Field key | Value format |
|---|---|---|
| `INPUT_TEXT` | `value` | `["free text"]` (UTF-8, ≤ 4 kB) |
| `TEXTAREA` | `value` | `["free text"]` (≤ 4 kB) |
| `CHECKBOX` | `confirm` | `["1"]` if checked; **omit entirely** if unchecked |
| `RADIO` (yes/no) | `value` | `["0"]` or `["1"]` (option IDs) |
| `SINGLE_SELECT` | `value` | `["<optionId>"]` (single option ID in array) |
| `MULTI_SELECT` | `value` | `["<optId1>","<optId2>",...]` |
| `INFORMATION` | — | static text, no answer expected |
| Currency | `amount` | `["10000"]` (numeric string) |

Dropdown options are encoded by **option ID** (not label). The option IDs come from the `/configuration` response.

### Consent encoding
Two models (configured per company):
- **Single consent**: `"consentDecisions": { "SINGLE": true }` (or legacy `"consent": true`)
- **Separated consent**: `"consentDecisions": { "SMART_RECRUIT": true, "SMART_CRM": false, "SMART_MESSAGE_SMS": false, "SMART_MESSAGE_WHATSAPP": false }`

---

## 4. Resume Upload

### Customer API (JSON, base64)
Resume is submitted **inline** in the `POST /postings/{uuid}/candidates` body — no separate upload endpoint:
```json
"resume": {
  "fileName": "resume.pdf",
  "mimeType": "application/pdf",
  "fileContent": "<BASE64-encoded-bytes>"
}
```
Limit 2 MB; accepted: PDF, DOC, DOCX, RTF, JPG, PNG. Cover letter / extra docs go in `attachments[]` (same shape).

### Public OGA flow
After the Arkose challenge, the OGA SPA uploads via an internal `jobs.smartrecruiters.com/smart-api/...` multipart endpoint (presigned). This endpoint is **not documented** and is gated behind the Arkose token; it could not be reached with plain HTTP (every `smart-api` probe returned 404 without the challenge cookie). A real browser session is required to capture the exact multipart field name.

---

## 5. Submit Endpoint

### Customer / Partner Application API (the documented, clean path)
```http
POST https://api.smartrecruiters.com/v1/postings/{uuid}/candidates
Host: api.smartrecruiters.com
X-SmartToken: <company-api-token>          # or Authorization: Bearer <oauth2-token>
Content-Type: application/json
Accept: application/json
```
Body (minimal):
```json
{
  "firstName": "Jane",
  "lastName": "Doe",
  "email": "jane@example.com",
  "phoneNumber": "+1-555-0100",
  "resume": { "fileName": "resume.pdf", "mimeType": "application/pdf", "fileContent": "<BASE64>" },
  "messageToHiringManager": "Cover letter text...",
  "answers": [
    { "id": "q1", "records": [ { "fields": { "value": ["optionId123"] } } ] }
  ],
  "consentDecisions": { "SINGLE": true },
  "sourceDetails": { "sourceTypeId": "..." }
}
```
Response `201`:
```json
{ "id": "candidateId", "applicationId": "appId",
  "createdOn": "2026-07-02T...", "candidatePortalUrl": "...", "smartrJoinUrl": "..." }
```
- **Throttling**: max 8 concurrent requests; adaptive; set timeout ≥ 128 s; HTTP 429 on overflow.
- `smartrJoinUrl` only if `createJoinLink: true`.
- Status check: `GET /postings/{uuid}/candidates/{candidateId}/status`.
- **Plain HTTP works** (no captcha) **but you need a valid `X-SmartToken`** — i.e. this is only usable by the hiring company's own integration, not by a third-party auto-apply bot scraping public jobs.

### Public OGA flow (what a human browser does)
The OGA SPA, after solving Arkose, POSTs the application to an internal `smart-api` endpoint on `jobs.smartrecruiters.com` carrying the Arkose token + Cloudflare cookies. The exact URL/payload is only observable inside a solved browser session and is not officially documented. **Browser automation (Playwright/Selenium with stealth + Arkose solving) is required** — plain `curl` cannot submit.

---

## 6. Anti-Bot

**Confirmed present and active on the public apply flow:**
- **Arkose Labs FunCAPTCHA** — `ct.captcha-delivery.com/c.js`, `geo.captcha-delivery.com`, with `rt:'c'` (challenge) payload. Served for every `?oga=true` request.
- **Cloudflare Bot Management** — `/cdn-cgi/challenge-platform/scripts/jsd/main.js` JS challenge injected via hidden iframe.
- Direct `curl` with a Chrome User-Agent still returns **HTTP 403** + the captcha stub (verified).
- The read-only **job enumeration & detail APIs (`api.smartrecruiters.com/v1/companies/.../postings`) are NOT captcha-protected** — they answer plain JSON anonymously.

The Customer Application API (`X-SmartToken`) is not captcha-protected; its gate is the API token.

---

## 7. Worked Example (Nexthink, real open job)

Job: *Senior Software Engineer C++ (Endpoint Agent, OS internals)* — Madrid.

```bash
# 1) Enumerate
curl -s -H "Accept: application/json" \
  "https://api.smartrecruiters.com/v1/companies/Nexthink/postings?limit=5&offset=0"

# 2) Detail (gives applyUrl + uuid needed for the Application API)
curl -s -H "Accept: application/json" \
  "https://api.smartrecruiters.com/v1/companies/Nexthink/postings/5a536b6f-d6b0-4d37-a9e2-b4e7c98eebde"
# -> uuid=5a536b6f-d6b0-4d37-a9e2-b4e7c98eebde
# -> applyUrl=https://jobs.smartrecruiters.com/Nexthink/744000135484160-senior-software-engineer-c-endpoint-agent-os-internals-?oga=true

# 3) Screening/consent config (needs company token)
curl -s -H "X-SmartToken: <TOKEN>" -H "Accept: application/json" \
  "https://api.smartrecruiters.com/v1/postings/5a536b6f-d6b0-4d37-a9e2-b4e7c98eebde/configuration"

# 4a) Submit via Customer API (needs company token; NO captcha)
curl -s -X POST "https://api.smartrecruiters.com/v1/postings/5a536b6f-d6b0-4d37-a9e2-b4e7c98eebde/candidates" \
  -H "X-SmartToken: <TOKEN>" -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{
    "firstName":"Jane","lastName":"Doe","email":"jane@example.com","phoneNumber":"+1-555-0100",
    "resume":{"fileName":"resume.pdf","mimeType":"application/pdf","fileContent":"<BASE64>"},
    "messageToHiringManager":"I would love to join Nexthink...",
    "answers":[{"id":"<questionId>","records":[{"fields":{"value":["<optionId>"]}}]}],
    "consentDecisions":{"SINGLE":true}
  }'

# 4b) Public apply URL (human / browser-automation only — Arkose-gated)
#    https://jobs.smartrecruiters.com/Nexthink/744000135484160-senior-software-engineer-c-endpoint-agent-os-internals-?oga=true
```

### Cross-company confirmation (all returned 200 from the enumeration API)
| Company | identifier | totalFound | sample applyUrl |
|---|---|---|---|
| Nexthink | `Nexthink` | 93 | `https://jobs.smartrecruiters.com/Nexthink/744000135484160-...?oga=true` |
| Visa | `Visa` | 3 | `https://jobs.smartrecruiters.com/Visa/744000133907678-sr-manager?oga=true` |
| Uber | `Uber` | 1 | (applyUrl in detail endpoint) `…/Uber/3743990000051828-…?oga=true` |

> `Equinix`, `Biogen`, `Mindbody` identifiers returned `totalFound: 0` — they are not currently on the public SmartRecruiters board (or use a different identifier).

---

## Sources
- [SmartRecruiters — Post an Application](https://developers.smartrecruiters.com/docs/post-an-application)
- [SmartRecruiters — Application API](https://developers.smartrecruiters.com/docs/application-api)
- [Get Application Screening Questions and Privacy Policies](https://developers.smartrecruiters.com/docs/partners-get-application-screening-questions-and-privacy-policies)
- [SmartRecruiters — Endpoints](https://developers.smartrecruiters.com/docs/endpoints)
- Live API: `api.smartrecruiters.com/v1/companies/Nexthink/postings` (2026-07-02)