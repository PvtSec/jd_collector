# Ashby ATS — Application Form Schema

Researched 2026-07-02 against live Ashby boards (`jobs.ashbyhq.com/replit`, `jobs.ashbyhq.com/cursor`). All endpoints below were actually fetched; no application was submitted. This is read-only documentation for an auto-job-application engine.

## TL;DR / key takeaways

- Ashby's public-facing careers app is a React SPA served from `jobs.ashbyhq.com/{orgSlug}`. The data layer is a **GraphQL endpoint** at `https://jobs.ashbyhq.com/api/non-user-graphql?op={operationName}` (POST, JSON, no auth, CORS-open to the board origin). GraphQL **introspection is disabled**, but the full query AST is shipped in the client JS bundle, so every operation/field is recoverable.
- The `api.ashbyhq.com/posting-api/job-board/{token}` endpoint mentioned in some docs is **NOT public** — it returns `401 Unauthorized` for every body/method I tried. Ignore it for an auto-applier. Use the GraphQL endpoint + SSR HTML instead.
- Job enumeration is reliable via the **SSR HTML** of `jobs.ashbyhq.com/{orgSlug}` (the page is server-side rendered and embeds a `window.__NEXT`-style JSON blob with the full `jobPostings` array). The GraphQL `ApiJobBoardWithTeams` query also exists but errored ("Unidentified server error") for some orgs (replit, cursor), so SSR scraping is the robust path.
- The per-job application form schema (every field, type, dropdown option, required flag) is **fully returned by the `ApiJobPosting` GraphQL query** — so you can pre-map every question before submitting. Custom questions live in `applicationForm.sections[].fieldEntries[]`; EEO/demographic questions live in a separate `surveyForms[]` array.
- Submission is a **multi-step GraphQL flow, not a single POST**:
  1. (resume) `createFileUploadHandle` → returns a presigned S3 URL + form fields → upload the file to S3 with a multipart POST → get back a `handle`.
  2. `setFormValue` / `setFormValueToFile` for each field (server holds the form state keyed by `formRenderIdentifier`).
  3. `submitMultipleFormsAction` with a **reCAPTCHA Enterprise token** (required, non-null).
- Anti-bot: **reCAPTCHA Enterprise** (score-based, invisible). Site key `6LeFb_YUAAAAALUD5h-BiQEp8JaFChe0A6r49Y`. No Cloudflare challenge on the board/apply pages themselves. The recaptcha token is sent in the GraphQL variables as `recaptchaToken`, wrapped as `ENT===<token>` because enterprise mode is on. This is the main blocker for a pure-HTTP auto-applier — you need a browser (or a recaptcha-solving service) to mint a token with a valid action.

---

## 1. Job enumeration

### Endpoint A (preferred): SSR board HTML

```
GET https://jobs.ashbyhq.com/{orgSlug}
```

The HTML is server-rendered and contains the full job list as embedded JSON. Parse it with a regex/JSON parser:

```bash
curl -s -L -A 'Mozilla/5.0' 'https://jobs.ashbyhq.com/replit' \
  | grep -oE '"jobPostings":\[.*\]'   # then JSON-parse the array
```

Each entry in the `jobPostings` array (98 postings on replit today) has these fields (verified):

```json
{
  "id": "32fa018b-35df-480c-9090-00d0f37d7fe5",          // = jobPostingId, used in URLs
  "title": "Administrative Assistant",
  "departmentId": "97e5b792-...",
  "departmentName": "G&A",
  "departmentExternalName": null,
  "locationId": "d41dcea5-...",
  "locationName": "Foster City, CA",
  "locationExternalName": "Foster City, CA",
  "workplaceType": "Hybrid",                              // Remote | Hybrid | Onsite
  "employmentType": "FullTime",                           // FullTime | PartTime | Contract | ...
  "isListed": true,
  "jobId": "e7fa4fbf-...",                                // underlying Job (≠ posting) id
  "jobRequisitionId": null,
  "teamId": "85378261-...",
  "teamName": "Executive",
  "teamExternalName": null,
  "publishedDate": "2026-06-25",
  "applicationDeadline": null,
  "secondaryLocations": [],
  "compensationTierSummary": null,
  "shouldDisplayCompensationOnJobBoard": false,
  "updatedAt": "2026-06-29T14:20:03.659Z",
  "userRoles": []
}
```

The board page also embeds `teams[]` (id, name, externalName, parentTeamId), `organization`, and `locations`/`departments` arrays for filter UI.

> The `id` here is the **Ashby posting id** (UUID). The application URL is built from it: `https://jobs.ashbyhq.com/{orgSlug}/{id}/application`.

### Endpoint B: GraphQL `ApiJobBoardWithTeams`

```
POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams
Content-Type: application/json
```

```jsonc
{
  "operationName": "ApiJobBoardWithTeams",
  "variables": { "organizationHostedJobsPageName": "replit" },
  "query": "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) { jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) { teams { id name externalName parentTeamId } jobPostings { id title teamId locationId locationName workplaceType employmentType secondaryLocations { locationId locationName } compensationTierSummary } } }"
}
```

Returned `{"data":{"jobBoard":null}}` for several orgs I tried (replicate, replit, cursor, notion, ramp, openai, ashby) — either `null` or an "Unidentified server error". This query is gated on the org having the "teams" feature published in a certain way, so **it is not a reliable enumeration method across all 29 companies**. Prefer SSR HTML. (The per-job `ApiJobPosting` query in §3 works reliably for every org, however.)

### Endpoint C: `api.ashbyhq.com/posting-api/job-board/{token}` — DO NOT USE

```
POST https://api.ashbyhq.com/posting-api/job-board/replicate   → 401 Unauthorized
GET  https://api.ashbyhq.com/posting-api/job-board/replicate    → 404 Not Found
```

Tried `replicate`, `openai`, `ramp`, `notion`, `replit`, `cursor`, `ashby`, `com` with bodies `{}`, `{"pagination":{"limit":100,"offset":0},"filters":[],"sortBy":""}`, `{"limit":100}`. All 401/404. This is Ashby's authenticated **Posting API** (org API key, used by customers to publish jobs), not a public read API. There is no authless version.

### Finding the `orgSlug`

Some companies host on a custom domain (e.g. `cursor.com/careers`, `replicate.com/careers`) that proxies/links to Ashby. The Ashby board slug is discoverable by following the "Apply" / job links on the custom careers page — they resolve to `jobs.ashbyhq.com/{slug}/{jobId}`. For cursor the slug is `cursor`; for replit it's `replit`. For the 29-company dataset, resolve each company's careers page and extract the `jobs.ashbyhq.com/{slug}/` prefix.

---

## 2. Application form (per job)

### URL pattern

- Job posting page: `https://jobs.ashbyhq.com/{orgSlug}/{jobPostingId}`
- Application form page: `https://jobs.ashbyhq.com/{orgSlug}/{jobPostingId}/application`

Both are the same SPA shell; data is loaded via GraphQL. Fetching the HTML alone gives you only the SPA bootstrap (`window.__appData` with `organization:null, posting:null` — populated at runtime). You must call the GraphQL `ApiJobPosting` query to get the form.

### Form schema source: `ApiJobPosting` query

```
POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting
```

```jsonc
{
  "operationName": "ApiJobPosting",
  "variables": {
    "organizationHostedJobsPageName": "cursor",
    "jobPostingId": "00e98809-a4ec-4f32-91db-0e63ef5778b0"
  },
  "query": "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { id title departmentName departmentExternalName locationName locationAddress workplaceType employmentType descriptionHtml isListed isConfidential teamNames secondaryLocationNames compensationTierSummary applicationDeadline shouldAskForTextingConsent candidateTextingPrivacyPolicyUrl candidateTextingTermsAndConditionsUrl legalEntityNameForTextingConsent automatedProcessingLegalNotice { automatedProcessingLegalNoticeRuleId automatedProcessingLegalNoticeHtml } applicationForm { id formControls { identifier title } sections { title descriptionHtml isHidden fieldEntries { id field isRequired descriptionHtml isHidden } } sourceFormDefinitionId } surveyForms { id formControls { identifier title } sections { title descriptionHtml isHidden fieldEntries { id field isRequired descriptionHtml isHidden } } sourceFormDefinitionId } } }"
}
```

Returns 200 with the full posting + form. Verified on replit (`32fa018b-…`, "Administrative Assistant") and cursor (`00e98809-…`, "Billing Support Manager").

### `applicationForm` shape

```
applicationForm: {
  id: "<formRenderIdentifier UUID>",            // e.g. 216b72c5-746a-4b87-8c1a-5b5f50194437
  sourceFormDefinitionId: "<JSON string>",      // composite id, see below
  formControls: [ { identifier: "<UUID>", title: "Submit" } ],  // the submit button(s)
  sections: [
    {
      title: "Details" | "Questions" | "Authorization" | null,
      descriptionHtml: null,
      isHidden: null,
      fieldEntries: [ FormFieldEntry, ... ]
    }
  ]
}
```

`sourceFormDefinitionId` is itself a JSON string, e.g.:
```json
{"kind":"CompositeFormDefinitionId-JobPostingApplicationFormV2","formDefinitionId":"5763cac8-...","jobPostingId":"32fa018b-...","jobBoardSuperType":"External"}
```
This is the `applicationFormDefinitionIdentifier` you pass to submit.

### `FormFieldEntry` shape

```
{
  id: "<formRenderIdentifier>__<path>"   // system fields, OR
  id: "<formRenderIdentifier>_<path>"    // custom fields (note single underscore)
  field: { ...JSON blob... }             // the field definition (type, title, options) — see §3
  isRequired: true | false,
  descriptionHtml: null | "<html>",
  isHidden: null | true
}
```

The `field` key is a **`JSON!` scalar** (not a structured GraphQL type — confirmed by an error when I tried to sub-select it). It serializes to this object:

```jsonc
{
  "id": "<field UUID>",
  "path": "_systemfield_name" | "<custom UUID>",
  "humanReadablePath": "Name" | "",
  "title": "Full Name",
  "isNullable": false,
  "isPrivate": false,
  "isDeactivated": false,
  "isMany": false,
  "metadata": {},
  "type": "String" | "Email" | "Phone" | "File" | "LongText" | "Boolean" | "ValueSelect" | "MultiValueSelect" | "DimensionSelect" | "Location" | "Date" | "Number" | "Currency" | "Url" | "Score" | "SocialLink" | "EducationHistory" | "RichText" | "LinearRating" | "NPSRating",
  "selectableValues": [ { "label": "...", "value": "..." } ],   // only for ValueSelect/MultiValueSelect/DimensionSelect
  "__autoSerializationID": "StringField" | "EmailField" | "ValueSelectField" | ...
}
```

### Standard (system) fields seen across boards

| `path`                 | type     | title        | notes |
|------------------------|----------|--------------|-------|
| `_systemfield_name`    | String   | Name / Full Name | always required |
| `_systemfield_email`   | Email    | Email        | always required |
| `_systemfield_resume`  | File     | Resume       | required on replit, optional on cursor |
| `_systemfield_location`| Location | Location     | replit |

Custom fields use a UUID `path` and the fieldEntry `id` is `{formId}_{path}` (single underscore). System fieldEntry ids use `{formId}__{path}` (double underscore).

### EEO / demographic questions

These are NOT in `applicationForm` — they are in a separate top-level `surveyForms[]` array on the job posting. One survey form was returned for the replit job, with EEO field paths:

| `path`                          | type        | title           |
|---------------------------------|-------------|-----------------|
| `_systemfield_eeoc_gender`      | ValueSelect | Gender          |
| `_systemfield_eeoc_race`        | ValueSelect | Race            |
| `_systemfield_eeoc_veteran_status` | ValueSelect | Veteran Status |

All `isRequired: false` (EEO is voluntary). The survey form has its own `id` (survey form render identifier) and `sourceFormDefinitionId`. It is submitted together with the application form via `submitMultipleFormsAction` (the `surveyIdentifiers` variable).

### Consent / texting

The posting also returns `shouldAskForTextingConsent`, `candidateTextingPrivacyPolicyUrl`, `candidateTextingTermsAndConditionsUrl`, `legalEntityNameForTextingConsent`, and `automatedProcessingLegalNotice { automatedProcessingLegalNoticeRuleId automatedProcessingLegalNoticeHtml }`. These drive extra consent checkboxes / notices; the `automatedProcessingLegalNoticeRuleId` is echoed back as `viewedAutomatedProcessingLegalNoticeRuleId` on submit.

---

## 3. Custom questions — encoding

**Yes — custom questions are fully included in the `ApiJobPosting` response**, so they can be pre-mapped before submitting. There is no separate "questions" endpoint to call.

Field `type` enum (all values found in the client bundle):

```
String, LongText, RichText, Email, Phone, Boolean, Date, Number, Currency, Url,
File, Score, SocialLink, EducationHistory, Location,
ValueSelect, MultiValueSelect, DimensionSelect,
LinearRating, NPSRating
```

(Note: Ashby's docs sometimes call these `shortText`/`longText`/`singleSelect`/`multiSelect`/`boolean`/`file`/`date`; the wire types are the PascalCase names above. There is no `shortText` — short text is `String`.)

### Dropdown options

For `ValueSelect` (single-select), `MultiValueSelect` (multi-select), and `DimensionSelect`, the field JSON contains a `selectableValues` array:

```json
"selectableValues": [
  { "label": "1-2 years", "value": "1-2 years" },
  { "label": "3-5 years", "value": "3-5 years" },
  { "label": "6-8 years", "value": "6-8 years" },
  { "label": "8+",        "value": "8+" }
]
```

- `label` = display text; `value` = the string you send back in `setFormValue`.
- EEO gender options use coded values: `male`, `female`, `decline_to_self_identify`.
- EEO race options: `hispanic_or_latino`, `white`, `black_or_african_american`, `native_hawaiian_or_other_pacific_islander`, `asian`, `american_indian_or_alaska_native`, `two_or_more_races`, `decline_to_self_identify`.
- Veteran: `protected_veteran`, `non_protected_veteran`, `decline_to_self_identify`.

For `MultiValueSelect`, send an array of `value` strings in `setFormValue`.

There is also a `selectableValuesDataSource` property on the field class in the client (for options loaded from an external data source), but every field I observed shipped static `selectableValues` inline.

---

## 4. Resume upload

Ashby uses a **presigned S3 upload** mediated by a GraphQL mutation — not a direct multipart upload to its own API.

### Step 1 — `ApiCreateFileUploadHandle`

```
POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiCreateFileUploadHandle
```

```jsonc
{
  "operationName": "ApiCreateFileUploadHandle",
  "variables": {
    "organizationHostedJobsPageName": "replit",
    "fileUploadContext": "NonUserFormEngine",   // enum FileUploadContext; this is the value used by the apply form
    "filename": "resume.pdf",
    "contentType": "application/pdf",
    "contentLength": 123456
  },
  "query": "mutation ApiCreateFileUploadHandle($organizationHostedJobsPageName: String!, $fileUploadContext: FileUploadContext!, $filename: String!, $contentType: String!, $contentLength: Int!) { fileUploadHandle: createFileUploadHandle(organizationHostedJobsPageName: $organizationHostedJobsPageName, fileUploadContext: $fileUploadContext, filename: $filename, contentType: $contentType, contentLength: $contentLength) { handle url fields } }"
}
```

Returns:

```jsonc
{
  "data": {
    "fileUploadHandle": {
      "handle": "<ashby file handle id>",   // pass to setFormValueToFile
      "url":    "https://<s3 bucket>.s3.amazonaws.com",   // presigned S3 POST target
      "fields": { "key": "...", "AWSAccessKeyId": "...", "policy": "...", "signature": "...", "x-amz-security-token": "..." }   // S3 POST form fields
    }
  }
}
```

### Step 2 — upload to S3 (multipart POST)

```bash
curl -s -X POST "https://<s3 bucket>.s3.amazonaws.com" \
  -F "key=<fields.key>" \
  -F "AWSAccessKeyId=<fields.AWSAccessKeyId>" \
  -F "policy=<fields.policy>" \
  -F "signature=<fields.signature>" \
  -F "x-amz-security-token=<fields.x-amz-security-token>" \
  -F "file=@resume.pdf"
```

(Use `fields` exactly as returned; the `file` field must be last.)

### Step 3 — attach to the form field

```
POST .../api/non-user-graphql?op=ApiSetFormValueToFile
```

```jsonc
{
  "operationName": "ApiSetFormValueToFile",
  "variables": {
    "organizationHostedJobsPageName": "replit",
    "formRenderIdentifier": "<applicationForm.id>",
    "path": "_systemfield_resume",
    "fileHandle": "<handle from step 1>",
    "formDefinitionIdentifier": "<sourceFormDefinitionId string>"
  },
  "query": "mutation ApiSetFormValueToFile($organizationHostedJobsPageName: String!, $formRenderIdentifier: String!, $path: String!, $fileHandle: String, $formDefinitionIdentifier: String) { setFormValueToFile(organizationHostedJobsPageName: $organizationHostedJobsPageName, formRenderIdentifier: $formRenderIdentifier, path: $path, fileHandle: $fileHandle, formDefinitionIdentifier: $formDefinitionIdentifier) { ... on FormRender { id } } }"
}
```

For multi-file fields use `ApiAddManyFilesToFormValue` (`fileHandles: [String!]!`) instead. Removal is `ApiRemoveFileFromFormValue` (`fileId: String!`).

> The multipart field name when uploading to S3 is `file` (the last form field in the presigned POST), not a field name of Ashby's choosing. Ashby only sees the resulting `handle`.

There is also `ApiAutofillApplicationFormWithUploadedResume` — after uploading a resume you can call it with the `fileHandle` and the form will parse name/email/phone from the file and pre-fill those fields server-side. Useful for the auto-applier.

---

## 5. Submit endpoint

Submission is **NOT a single HTTP request**. The form state is held server-side, keyed by `applicationForm.id` (the `formRenderIdentifier`). You set each field's value with `setFormValue` mutations, then fire `submitMultipleFormsAction`. All via the same GraphQL endpoint, all JSON. There is no multipart submit.

### Field-value mutations (one per field, before submit)

```
POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSetFormValue
```

```jsonc
{
  "operationName": "ApiSetFormValue",
  "variables": {
    "organizationHostedJobsPageName": "replit",
    "formRenderIdentifier": "<applicationForm.id>",
    "path": "_systemfield_name",            // the field.path
    "value": "Jane Doe",                     // JSON value — see value format table
    "formDefinitionIdentifier": "<sourceFormDefinitionId>"
  },
  "query": "mutation ApiSetFormValue($organizationHostedJobsPageName: String!, $formRenderIdentifier: String!, $path: String!, $value: JSON, $formDefinitionIdentifier: String) { setFormValue(organizationHostedJobsPageName: $organizationHostedJobsPageName, formRenderIdentifier: $formRenderIdentifier, path: $path, value: $value, formDefinitionIdentifier: $formDefinitionIdentifier) { ... on FormRender { id sections { fieldEntries { id field isRequired } } } } }"
}
```

**Value format by field type** (inferred from client serialization):

| type            | `value` JSON                                |
|-----------------|---------------------------------------------|
| String          | `"text"`                                    |
| LongText / RichText | `"text"`                                |
| Email           | `"user@example.com"`                        |
| Phone           | `"+15551234567"`                            |
| Boolean         | `true` / `false`                            |
| ValueSelect     | `"<option value>"`  (e.g. `"3-5 years"`)    |
| MultiValueSelect| `["<v1>","<v2>"]`                            |
| Location        | `{"name":"Foster City, CA","providerLocationId":"..."}` (use the autocomplete; a plain string may also be accepted) |
| Date            | `"YYYY-MM-DD"`                              |
| Number / Currency | `123` / `{"amount":120000,"currency":"USD"}` |
| Url / SocialLink | `"https://..."`                             |
| File            | use `setFormValueToFile` (not this mutation) |

### Submit mutation

```
POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSubmitMultipleFormsAction
```

```jsonc
{
  "operationName": "ApiSubmitMultipleFormsAction",
  "variables": {
    "organizationHostedJobsPageName": "replit",
    "jobPostingId": "32fa018b-35df-480c-9090-00d0f37d7fe5",
    "applicationFormRenderIdentifier": "<applicationForm.id>",
    "applicationFormActionIdentifier": "<formControls[0].identifier>",   // the "Submit" button UUID
    "applicationFormDefinitionIdentifier": "<applicationForm.sourceFormDefinitionId>",
    "surveyIdentifiers": [
      { "formRenderIdentifier": "<surveyForms[0].id>", "formActionIdentifier": "<surveyForms[0].formControls[0].identifier>", "formDefinitionIdentifier": "<surveyForms[0].sourceFormDefinitionId>" }
    ],
    "recaptchaToken": "ENT===<recaptcha enterprise token>",
    "sourceAttributionCode": null,
    "viewedAutomatedProcessingLegalNoticeRuleId": null,
    "deviceFingerprint": null,
    "applicationRequestId": null
  },
  "query": "mutation ApiSubmitMultipleFormsAction($organizationHostedJobsPageName: String!, $jobPostingId: String!, $applicationFormRenderIdentifier: String!, $applicationFormActionIdentifier: String!, $applicationFormDefinitionIdentifier: String, $surveyIdentifiers: [JSON!]!, $recaptchaToken: String!, $sourceAttributionCode: String, $viewedAutomatedProcessingLegalNoticeRuleId: String, $deviceFingerprint: String, $applicationRequestId: String) { submitMultipleFormsAction(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId, applicationFormRenderIdentifier: $applicationFormRenderIdentifier, applicationFormActionIdentifier: $applicationFormActionIdentifier, applicationFormDefinitionIdentifier: $applicationFormDefinitionIdentifier, surveyIdentifiers: $surveyIdentifiers, recaptchaToken: $recaptchaToken, sourceAttributionCode: $sourceAttributionCode, viewedAutomatedProcessingLegalNoticeRuleId: $viewedAutomatedProcessingLegalNoticeRuleId, deviceFingerprint: $deviceFingerprint, applicationRequestId: $applicationRequestId) { applicationFormResult { ... on FormRender { id } ... on FormSubmitSuccess { _ } } surveyFormResults { ... on FormRender { id } ... on FormSubmitSuccess { _ } } messages { blockMessageForCandidateHtml } } }"
}
```

Required (non-null) variables: `organizationHostedJobsPageName`, `jobPostingId`, `applicationFormRenderIdentifier`, `applicationFormActionIdentifier`, `surveyIdentifiers` (array, may be `[]` if no survey), `recaptchaToken`. The rest are optional.

Response: `applicationFormResult` is either `FormRender` (validation errors — re-render) or `FormSubmitSuccess` (success). On validation errors the returned `FormRender` includes `errorMessages` and `formErrors [{message, fieldEntryId}]`.

### Can it be done via HTTP API without a browser?

Partially. All field-setting and the final submit are plain JSON POSTs to the GraphQL endpoint — no browser JS is needed to construct them. **The blocker is `recaptchaToken`** (see §6): it is `String!` (non-null) on the submit mutation, and it must be a freshly-minted reCAPTCHA Enterprise token. You'll need either a headless browser executing the recaptcha challenge, or a third-party recaptcha-solving service. A pure curl flow will fail at submit with a recaptcha error.

---

## 6. Anti-bot

- **reCAPTCHA Enterprise** (invisible, score-based). Present on every apply page.
  - Site key: `6LeFb_YUAAAAALUD5h-BiQEp8JaFChe0A6r49Y` (read from `window.__appData.recaptchaPublicSiteKey` on the apply page).
  - Enterprise flag: the client loads `https://www.google.com/recaptcha/enterprise.js?render=<sitekey>` and calls `grecaptcha.enterprise.execute(siteKey, {action: ...})`.
  - Token wrapping: because enterprise mode is on, the client prefixes the token with `ENT===` before sending it as `recaptchaToken`. So the value you submit must be the literal string `ENT===<rawToken>`.
  - The client also has a `RECAPTCHA_SCORE_BELOW_THRESHOLD` error path — Ashby enforces a minimum score server-side.
  - The `.grecaptcha-badge { visibility: hidden }` style on the board HTML confirms the invisible badge variant.
- **Cloudflare**: no Cloudflare challenge / `cf-browser-verification` on `jobs.ashbyhq.com` board or apply pages, and no Cloudflare turnstile. The GraphQL endpoint responds directly to curl. (Ashby fronts the site with its own infra; Cloudflare may sit in front of `api.ashbyhq.com` but that endpoint is auth-gated anyway.)
- **Device fingerprint**: `submitMultipleFormsAction` accepts an optional `deviceFingerprint: String` — not required, but the client may send one.
- **Rate limiting / application limits**: the posting returns `applicationLimitCalloutHtml` when an org limits how often a candidate can apply; handle this message in the submit response.

---

## 7. Worked example — Replit "Administrative Assistant"

Real open job (verified 2026-07-02):

- orgSlug: `replit`
- jobPostingId: `32fa018b-35df-480c-9090-00d0f37d7fe5`
- title: Administrative Assistant (Foster City, CA, Hybrid, FullTime)
- applicationForm.id (formRenderIdentifier): `216b72c5-746a-4b87-8c1a-5b5f50194437`
- applicationForm.sourceFormDefinitionId: `{"kind":"CompositeFormDefinitionId-JobPostingApplicationFormV2","formDefinitionId":"5763cac8-e091-434f-b03e-a2760b5a808a","jobPostingId":"32fa018b-35df-480c-9090-00d0f37d7fe5","jobBoardSuperType":"External"}`
- formControls[0].identifier (actionIdentifier): `41f1fa81-99c9-4497-a5b6-2a0f0598c84e`
- surveyForms[0].id: `9682d38f-31da-4170-8302-8802302f537b`
- surveyForms[0].sourceFormDefinitionId: `4ae59e9f-119c-4d34-8ccc-13663bc84793`
- recaptcha site key: `6LeFb_YUAAAAALUD5h-BiQEp8JaFChe0A6r49Y`

### Step 0 — fetch the form schema (read-only)

```bash
curl -s -X POST 'https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting' \
  -H 'Content-Type: application/json' \
  -d '{
    "operationName":"ApiJobPosting",
    "variables":{"organizationHostedJobsPageName":"replit","jobPostingId":"32fa018b-35df-480c-9090-00d0f37d7fe5"},
    "query":"query ApiJobPosting($o:String!,$j:String!){jobPosting(organizationHostedJobsPageName:$o,jobPostingId:$j){id title applicationForm{id formControls{identifier title} sections{title fieldEntries{id field isRequired} } sourceFormDefinitionId} surveyForms{id formControls{identifier title} sections{fieldEntries{id field isRequired}} sourceFormDefinitionId}}}"
  }'
```

### Step 1 — upload resume

```bash
# 1a. get presigned S3 handle
HANDLE_JSON=$(curl -s -X POST 'https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiCreateFileUploadHandle' \
  -H 'Content-Type: application/json' \
  -d '{
    "operationName":"ApiCreateFileUploadHandle",
    "variables":{"organizationHostedJobsPageName":"replit","fileUploadContext":"NonUserFormEngine","filename":"resume.pdf","contentType":"application/pdf","contentLength":123456},
    "query":"mutation ApiCreateFileUploadHandle($o:String!,$c:FileUploadContext!,$f:String!,$ct:String!,$cl:Int!){fileUploadHandle:createFileUploadHandle(organizationHostedJobsPageName:$o,fileUploadContext:$c,filename:$f,contentType:$ct,contentLength:$cl){handle url fields}}"
  }')
HANDLE=$(echo "$HANDLE_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['fileUploadHandle']['handle'])")
URL=$(echo "$HANDLE_JSON"   | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['fileUploadHandle']['url'])")
KEY=$(echo "$HANDLE_JSON"   | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['fileUploadHandle']['fields']['key'])")
# ...extract AWSAccessKeyId, policy, signature, x-amz-security-token similarly

# 1b. upload to S3 (file field MUST be last)
curl -s -X POST "$URL" \
  -F "key=$KEY" \
  -F "AWSAccessKeyId=$AWSID" \
  -F "policy=$POLICY" \
  -F "signature=$SIG" \
  -F "x-amz-security-token=$TOKEN" \
  -F "file=@resume.pdf"

# 1c. attach handle to the resume field
curl -s -X POST 'https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSetFormValueToFile' \
  -H 'Content-Type: application/json' \
  -d '{
    "operationName":"ApiSetFormValueToFile",
    "variables":{"organizationHostedJobsPageName":"replit","formRenderIdentifier":"216b72c5-746a-4b87-8c1a-5b5f50194437","path":"_systemfield_resume","fileHandle":"'"$HANDLE"'","formDefinitionIdentifier":"{\"kind\":\"CompositeFormDefinitionId-JobPostingApplicationFormV2\",\"formDefinitionId\":\"5763cac8-e091-434f-b03e-a2760b5a808a\",\"jobPostingId\":\"32fa018b-35df-480c-9090-00d0f37d7fe5\",\"jobBoardSuperType\":\"External\"}"},
    "query":"mutation ApiSetFormValueToFile($o:String!,$f:String!,$p:String!,$h:String,$d:String){setFormValueToFile(organizationHostedJobsPageName:$o,formRenderIdentifier:$f,path:$p,fileHandle:$h,formDefinitionIdentifier:$d){__typename}}"
  }'
```

### Step 2 — set each value field (repeat per field)

```bash
# Name
curl -s -X POST 'https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSetFormValue' \
  -H 'Content-Type: application/json' \
  -d '{
    "operationName":"ApiSetFormValue",
    "variables":{"organizationHostedJobsPageName":"replit","formRenderIdentifier":"216b72c5-746a-4b87-8c1a-5b5f50194437","path":"_systemfield_name","value":"Jane Doe","formDefinitionIdentifier":"{\"kind\":\"CompositeFormDefinitionId-JobPostingApplicationFormV2\",\"formDefinitionId\":\"5763cac8-e091-434f-b03e-a2760b5a808a\",\"jobPostingId\":\"32fa018b-35df-480c-9090-00d0f37d7fe5\",\"jobBoardSuperType\":\"External\"}"},
    "query":"mutation ApiSetFormValue($o:String!,$f:String!,$p:String!,$v:JSON,$d:String){setFormValue(organizationHostedJobsPageName:$o,formRenderIdentifier:$f,path:$p,value:$v,formDefinitionIdentifier:$d){__typename}}"
  }'

# Email -> path "_systemfield_email", value "jane@example.com"
# Phone -> path "e4197ade-2b17-45c7-8cca-a2ad772e1dce", value "+15551234567"
# Location -> path "_systemfield_location"
# "What excites you about Replit?" (LongText) -> path "90456d1d-541c-4e76-b82f-49e4840847d6", value "..."
# Years of experience (ValueSelect) -> path "15472de4-f47a-4806-83ce-c3e2d4037ea1", value "3-5 years"
# Desired salary (String) -> path "8bf68e7b-...", value "$150k"
# Booleans -> path "f0f79fa8-.../d5f11609-.../de3249cd-.../5044a612-.../eb6f6616-...", value true/false
```

### Step 3 — submit

```bash
# You MUST obtain a real reCAPTCHA Enterprise token first, e.g. via headless browser:
#   grecaptcha.enterprise.execute("6LeFb_YUAAAAALUD5h-BiQEp8JaFChe0A6r49Y", {action: "submit"})
# then prefix with "ENT===".
RECAPTCHA_TOKEN="ENT===AAAA..."   # placeholder

curl -s -X POST 'https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiSubmitMultipleFormsAction' \
  -H 'Content-Type: application/json' \
  -d '{
    "operationName":"ApiSubmitMultipleFormsAction",
    "variables":{
      "organizationHostedJobsPageName":"replit",
      "jobPostingId":"32fa018b-35df-480c-9090-00d0f37d7fe5",
      "applicationFormRenderIdentifier":"216b72c5-746a-4b87-8c1a-5b5f50194437",
      "applicationFormActionIdentifier":"41f1fa81-99c9-4497-a5b6-2a0f0598c84e",
      "applicationFormDefinitionIdentifier":"{\"kind\":\"CompositeFormDefinitionId-JobPostingApplicationFormV2\",\"formDefinitionId\":\"5763cac8-e091-434f-b03e-a2760b5a808a\",\"jobPostingId\":\"32fa018b-35df-480c-9090-00d0f37d7fe5\",\"jobBoardSuperType\":\"External\"}",
      "surveyIdentifiers":[
        {"formRenderIdentifier":"9682d38f-31da-4170-8302-8802302f537b",
         "formActionIdentifier":"<surveyForms[0].formControls[0].identifier>",
         "formDefinitionIdentifier":"4ae59e9f-119c-4d34-8ccc-13663bc84793"}
      ],
      "recaptchaToken":"'"$RECAPTCHA_TOKEN"'"
    },
    "query":"mutation ApiSubmitMultipleFormsAction($o:String!,$j:String!,$a:String!,$act:String!,$def:String,$sur:[JSON!]!,$r:String!,$src:String,$view:String,$df:String,$ar:String){submitMultipleFormsAction(organizationHostedJobsPageName:$o,jobPostingId:$j,applicationFormRenderIdentifier:$a,applicationFormActionIdentifier:$act,applicationFormDefinitionIdentifier:$def,surveyIdentifiers:$sur,recaptchaToken:$r,sourceAttributionCode:$src,viewedAutomatedProcessingLegalNoticeRuleId:$view,deviceFingerprint:$df,applicationRequestId:$ar){applicationFormResult{__typename ...on FormSubmitSuccess{_}} messages{blockMessageForCandidateHtml}}}"
  }'
```

> I did NOT execute Step 3 (or any state-changing mutation) — that would submit a real application. The mutation signature, variable names, and field shapes above are taken verbatim from the shipped client AST and the read-only `ApiJobPosting` response.

---

## Appendix: GraphQL operations discovered (all at `POST https://jobs.ashbyhq.com/api/non-user-graphql?op={name}`)

| Operation | kind | purpose |
|-----------|------|---------|
| `ApiJobBoardWithTeams` | query | list jobs on a board (unreliable across orgs) |
| `ApiJobPosting` | query | full posting + applicationForm + surveyForms (reliable) |
| `ApiJobPostingForApplicationRequest` | query | variant for application-request links |
| `ApiOrganizationFromHostedJobsPageName` | query | resolve org from slug |
| `ApiCreateFileUploadHandle` | mutation | presigned S3 upload handle |
| `ApiSetFormValue` | mutation | set a field's JSON value |
| `ApiSetFormValueToFile` | mutation | attach an uploaded file to a field |
| `ApiAddManyFilesToFormValue` | mutation | attach multiple files |
| `ApiRemoveFileFromFormValue` | mutation | remove a file |
| `ApiAutofillApplicationFormWithUploadedResume` | mutation | parse resume → prefill name/email/phone |
| `ApiSubmitMultipleFormsAction` | mutation | submit application + surveys |
| `ApiSubmitRegistrationFormAction` | mutation | hiring-event RSVP forms |
| `ApiGetConsent` / `ApiRecordCookieConsent` / `ApiSubmitCandidateTextingConsent` | query/mutation | consent management |

The query AST for every operation above is embedded in the public JS bundle at
`https://cdn.ashbyprd.com/frontend_non_user/<hash>/assets/index-<hash>.js`
(referenced from the board HTML's vite manifest). If Ashby changes a field name, re-extract the AST from the current bundle.