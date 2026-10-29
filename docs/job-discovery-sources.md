# Hire-steward — Job Discovery Sources and Checkpointing

**Status:** Source-agnostic policy and adapter design. Individual sources stay disabled until their current method, terms and capabilities are verified.

## 1. Source registry

Every source requires a record containing:

- source ID/name and base domain;
- source type (ATS API, public career page, approved aggregator, manual-only);
- official documentation/terms reference and last-reviewed date;
- permitted access method and permitted operations (`read listings`, `read details`, `apply`, `email application`, `manual handoff`);
- authentication requirements and credential handling;
- source-specific request rate, daily cap and backoff behavior;
- pagination/cursor scheme and checkpoint semantics;
- posting date reliability, stable job IDs and canonical URL rules;
- source-specific compensation/sponsorship field limitations;
- schema/adapter version, last successful run and last error;
- known limits and disable conditions.

Use capability states:

`NEEDS_REVIEW`, `VERIFIED_READ_ONLY`, `VERIFIED_READ_AND_SUBMIT`, `MANUAL_ONLY`, `BLOCKED`, `DISABLED_BY_USER`.

Do not treat a public read endpoint as permission to submit. Do not treat a submit endpoint in documentation as permission to use it without the necessary credentials, terms, scope and user authorization.

## 2. First sources and official references

Candidate adapters for investigation—not pre-approved capabilities:

- Greenhouse Job Board API: https://docs.greenhouse.io/job-board (checked 2026-10-28)
- Lever Postings API: https://github.com/lever/postings-api (checked 2026-10-28)
- Ashby Public Job Posting API: https://developers.ashbyhq.com/docs/public-job-posting-api (checked 2026-10-28)
- Ashby Authenticated API (Reference): https://developers.ashbyhq.com/reference/jobpostinglist and https://developers.ashbyhq.com/reference/authentication (checked 2026-10-28)

Official technical documentation and published access documentation were reviewed on 2026-10-28. This review distinguishes:
1. API documentation and technical capability;
2. Terms applicable to authenticated customers or logged-in users;
3. Documented policy applicable to unauthenticated public API access;
4. The unresolved question of recurring third-party, multi-employer aggregation.

When a claim's applicability cannot be established from the reviewed official text, it is marked `NOT ESTABLISHED BY REVIEWED SOURCES`. Missing evidence is not converted into an assumed permission or prohibition. This review is not legal advice and does not grant authorization to access any live production endpoint.

The proposed initial product model across all candidate sources (formalized in [ADR-0012](decisions/ADR-0012-job-discovery-source-access-and-lever-evaluation.md)) is:
- **User-specified employer board identifiers** (user configures the specific company handles or board tokens to monitor; no uncredentialed global crawling);
- **Read-only listing discovery** via documented public endpoints;
- **Manual application handoff** (`MANUAL_ONLY` browser handoff to the canonical job posting URL; automated submission is out of scope);
- **No global scraper, no permission evasion, no credential collection, and no automated application submissions**.

---

### Source 1: Greenhouse (Job Board API)

* **Official Documentation Reference:** [Greenhouse Job Board API](https://docs.greenhouse.io/job-board) (reviewed 2026-10-28).
* **Listing & Detail Endpoints:**
  * Listing: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs`
  * Detail: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{id}`
  * Ancillary: `GET /boards/{board_token}/offices`, `GET /boards/{board_token}/departments`
* **Authentication:**
  * Listing & Detail (GET): **Unauthenticated / public**. No API key, token, or account registration is required to read published boards.
  * Application Submission (POST): `POST /boards/{board_token}/jobs/{id}` requires **HTTP Basic Authentication** using an employer-issued Job Board API Key as username and a blank password (`Authorization: Basic <base64(api_key:)>`).
* **Availability of Descriptions & Identifiers:**
  * Stable identifier: Integer `id` per job.
  * Descriptions: Passing query parameter `?content=true` to the listing endpoint includes the full HTML job description directly in each job object. Alternatively, individual job detail `GET /jobs/{id}` returns the full `content`.
  * Question schema: Passing `?questions=true` returns the job's custom application form questions.
* **Publication Dates & Compensation Fields:**
  * Publication dates: `updated_at` (ISO 8601 timestamp) is documented on job listings. Initial creation date (`created_at`) is not explicitly documented on the public listing payload.
  * Compensation fields: Not documented as a standard structured field in the Job Board API schema.
* **Pagination, Incremental Discovery & Documented Rate Limits:**
  * Pagination: No offset or cursor pagination parameters are documented; the endpoint returns the list of active published jobs for the specified board token.
  * Incremental discovery: Client-side filtering via `updated_at` is possible.
  * Rate limits: `NOT ESTABLISHED BY REVIEWED SOURCES`. The reviewed Job Board API documentation does not state a numeric rate limit or request quota for public GET requests. (The 50 req/10s limit documented elsewhere applies strictly to the internal Harvest API and does not govern the public Job Board API).
* **Explicitly Documented Intended API Use:**
  * "The Job Board API allows you to automate the process of exporting jobs, offices, and departments into a lightweight JSON format and to add applicants to your Greenhouse account from external sources... It is designed for developers who are looking to create custom career sites, job boards, or sync job data."
* **Terms & Policy Distinction:**
  * *Terms applicable to authenticated customers:* Greenhouse Master Subscription Agreement (MSA) governs customer accounts.
  * *Policy applicable to unauthenticated public API access:* `NOT ESTABLISHED BY REVIEWED SOURCES`. The reviewed documentation does not cite or link specific public API terms of use for unauthenticated consumers.
* **Remaining Permission Uncertainties:**
  * Whether recurring third-party aggregation across multiple employer board tokens is permitted is `NOT ESTABLISHED BY REVIEWED SOURCES`. Public endpoint access cannot be treated as affirmative legal permission.
  * Infrastructure-level WAF thresholds and IP rate limits remain unverified.
* **Initial Access Capability State:** `NEEDS_REVIEW`. Application submission is out of scope.

---

### Source 2: Lever (Postings API v0)

* **Official Documentation Reference:** [Lever Postings API GitHub Repository](https://github.com/lever/postings-api) (reviewed 2026-10-28).
* **Listing & Detail Endpoints:**
  * Listing: `GET https://api.lever.co/v0/postings/{company}` (EU instances: `https://api.eu.lever.co/v0/postings/{company}`)
  * Detail: `GET https://api.lever.co/v0/postings/{company}/{posting_id}`
* **Authentication:**
  * Listing & Detail (GET): **Unauthenticated / public / keyless**. No credentials required to query published postings.
  * Application Submission (POST): Documented as `POST /v0/postings/{company}/{posting_id}?key=APIKEY`. The documented endpoint **requires an API key** passed as a query parameter (`?key=APIKEY`) configured for that company's postings integration.
* **Availability of Descriptions & Identifiers:**
  * Stable identifier: Alphanumeric/UUID string `id` per posting.
  * Descriptions: Provides `description` (HTML), `descriptionPlain` (plain text), `lists` (array of structured bullet points), and `additional` (plain text/HTML closing text).
* **Publication Dates & Compensation Fields:**
  * Publication dates: `createdAt` is documented as a Unix epoch timestamp in milliseconds.
  * Compensation fields: Not documented as a standard structured schema field in the public v0 Postings API.
* **Pagination, Incremental Discovery & Documented Rate Limits:**
  * Pagination: Supports `skip` (integer offset) and `limit` (integer count) query parameters.
  * Incremental discovery: Client-side filtering via `createdAt` is possible.
  * Rate limits: `NOT ESTABLISHED BY REVIEWED SOURCES`. The repository does not state a numeric rate limit for the public v0 Postings API. (The 10 req/s steady / 20 req/s burst limit applies exclusively to Lever's separate authenticated v1 Data API and must not be transferred to the public v0 Postings API).
* **Explicitly Documented Intended API Use:**
  * Designed to enable building a custom job site to query published postings and apply to postings.
  * The documentation explicitly notes: *"all job postings in the published state are publicly viewable. These jobs may be scraped by third parties. All other jobs are completely hidden from the jobs API."*
* **Terms & Policy Distinction:**
  * *Terms applicable to authenticated customers:* Lever Master Services Agreement governs customer accounts and authenticated v1 Data API keys.
  * *Policy applicable to unauthenticated public API access:* The official repository expressly states that published jobs are publicly viewable and may be scraped by third parties. However, whether a separate unauthenticated website terms of service imposes external restrictions is `NOT ESTABLISHED BY REVIEWED SOURCES`. That documentation note cannot be converted into blanket legal authorization for every automated aggregation pattern.
* **Remaining Permission Uncertainties:**
  * While Lever documentation is unique among the candidates in explicitly acknowledging that published postings may be scraped by third parties, acceptable polling volume, request frequency, and third-party agent boundaries for multi-employer monitoring remain legally unconfirmed.
  * Application submission requires an integration key (`?key=APIKEY`), confirming that automated submission without employer credentials is unsupported and remains out of scope.
* **Initial Access Capability State:** `NEEDS_REVIEW`. Application submission is out of scope.

---

### Source 3: Ashby (Public Job Posting API vs. Authenticated API)

* **Official Documentation References:**
  * [Ashby Public Job Posting API Guide](https://developers.ashbyhq.com/docs/public-job-posting-api) (reviewed 2026-10-28, re-verified 2026-10-29).
  * [Ashby jobPosting.list RPC Reference](https://developers.ashbyhq.com/reference/jobpostinglist) and [Authentication Reference](https://developers.ashbyhq.com/reference/authentication) (reviewed 2026-10-28, re-verified 2026-10-29).
* **Distinction Between Ashby's Two APIs:**
  1. **Public Job Posting API (Keyless):**
     * Endpoint: `GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}`
     * Authentication: **Unauthenticated / public**. Meant for custom career sites to fetch live published job listings directly without credentials.
  2. **Authenticated Developer API (RPC):**
     * Endpoint: `POST https://api.ashbyhq.com/jobPosting.list`
     * Authentication: **Requires HTTP Basic Authentication** with an employer-issued Ashby API key having `jobsRead` permission.
* **Listing & Detail Endpoints (Public API):**
  * Listing: `GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}`
  * Detail: Returns all published jobs with full detail in the `jobs` array of the response.
* **Authentication:**
  * Public Job Posting API (GET): **Unauthenticated / public**.
  * Authenticated developer endpoints (POST): Require API key credentials.
* **Availability of Descriptions & Identifiers:**
  * Stable identifier: Alphanumeric/UUID string `id` per job.
  * Descriptions: Returns both `descriptionHtml` and `descriptionPlain` directly in the listing payload for every job.
* **Publication Dates & Compensation Fields:**
  * Publication dates: `publishedAt` (ISO 8601 timestamp) is documented on each job object.
  * Compensation fields: Explicitly documented optional parameter `?includeCompensation=true`. When included, the response provides structured compensation tier data and salary ranges if configured for the posting.
* **Pagination, Incremental Discovery & Documented Rate Limits:**
  * Pagination: No pagination parameters are documented for the public Job Board endpoint; it returns currently published jobs for the board.
  * Incremental discovery: Client-side filtering via `publishedAt` timestamp.
  * Rate limits: `NOT ESTABLISHED BY REVIEWED SOURCES`. The Public Job Posting API documentation does not state a numeric rate limit. (The 1,000 req/min limit applies strictly to authenticated developer API keys and must not be transferred to the separate public endpoint).
* **Explicitly Documented Intended API Use:**
  * "The Ashby Job Postings API is a lightweight API meant for building a custom job board for a single organization. It allows you to fetch data for all currently published job postings."
* **Terms & Policy Distinction:**
  * *Terms applicable to authenticated customers:* Ashby Master Services Agreement governs customer accounts and authenticated developer API keys.
  * *Policy applicable to unauthenticated public API access:* `NOT ESTABLISHED BY REVIEWED SOURCES`. The reviewed documentation does not cite or link public API terms of use for unauthenticated consumers.
* **Remaining Permission Uncertainties:**
  * Whether third-party candidate agents may poll this endpoint across multiple organizations without an employer agreement is `NOT ESTABLISHED BY REVIEWED SOURCES`. Public endpoint availability does not establish an affirmative aggregation license.
  * Unadvertised rate limits or WAF thresholds for the public endpoint remain undocumented.
* **Initial Access Capability State:** `NEEDS_REVIEW`. Application submission is out of scope.

---

### Source 4: Direct Employer Career Pages & Syndication Feeds

* **Official Documentation & Technical References:**
  * Workable Master XML Job Feed: `https://www.workable.com/boards/workable.xml` (reviewed 2026-10-29).
  * Workable SPI REST API: `https://{subdomain}.workable.com/spi/v3/jobs` (reviewed 2026-10-29).
  * Schema.org `JobPosting` Structured Data Standard: `https://schema.org/JobPosting` (reviewed 2026-10-29).
  * Standard Enterprise Career Portals (Workday, SAP SuccessFactors, Taleo, iCIMS) Terms of Use (reviewed 2026-10-29).
* **Public Interface Availability:**
  * *Global Multi-Tenant Feeds:* Workable publishes a global XML job feed (`workable.xml`) containing public postings across participating customers. However, there is no native per-company RSS/Atom feed; extracting one employer requires downloading and parsing a monolithic global XML file (>100MB), which violates local storage, bandwidth efficiency, and candidate privacy boundaries.
  * *Direct Employer Feeds (RSS/Atom):* Standard per-employer RSS or Atom syndication feeds are largely legacy or unmaintained across modern ATS providers. Where career sites publish listings, they typically embed JavaScript single-page applications (SPAs) rather than static feeds.
  * *Structured Data (Schema.org / JSON-LD):* Embedded `JobPosting` markup is designed for search engine indexers (e.g., Google for Jobs). Parsing this requires general web scraping of HTML, which violates Hire-Steward's anti-scraping and bounded-interface principles.
  * *Enterprise ATS Portals (Workday, Taleo, SuccessFactors):* Require complex session cookies, anti-bot challenge completion (Cloudflare, Akamai, PerimeterX), and strict terms of use explicitly prohibiting automated or script-based access.
* **Authentication:**
  * Workable REST API (`spi/v3/jobs`): Requires an authenticated Bearer Token with `r_jobs` scope issued by a Super Admin.
  * Global XML: Unauthenticated, but requires unconstrained bulk processing.
  * Enterprise Career Portals: Enforce user account creation or anti-automation barriers.
* **Terms & Policy Distinction:**
  * Enterprise career portals explicitly prohibit automated access, scraping, and bulk extraction in their Terms of Use.
  * Schema.org embedded metadata does not grant a license for autonomous recurring retrieval by third-party agents.
* **Remaining Permission Uncertainties:**
  * Direct employer career pages without documented public developer APIs cannot be accessed programmatically without violating site terms or relying on fragile, anti-evasive scraping.
* **Initial Access Capability State:** `NEEDS_REVIEW` (and `MANUAL_ONLY` for general career portals).

---

### Comparable Four-Source Capability and Permission Matrix (2026-10-29)

All sources remain in `NEEDS_REVIEW`. No adapter, schema, or automated crawler is enabled.

| Evidence Category | Greenhouse (Job Board API) | Lever (Postings API v0) | Ashby (Public Job Posting API) | Direct Employer Feeds / Career Pages |
|---|---|---|---|---|
| **Official Documentation Reference** | https://docs.greenhouse.io/job-board (checked 2026-10-29) | https://github.com/lever/postings-api (checked 2026-10-29) | https://developers.ashbyhq.com/docs/public-job-posting-api (checked 2026-10-29) | Workable XML / Schema.org / Enterprise Portals (checked 2026-10-29) |
| **Documented Listing Endpoint** | `GET /v1/boards/{board_token}/jobs` | `GET /v0/postings/{company}` | `GET /posting-api/job-board/{JOB_BOARD_NAME}` | Monolithic XML (`workable.xml`) or HTML scraping |
| **Listing Authentication** | None (Unauthenticated) | None (Unauthenticated) | None (Unauthenticated) | None for XML; Bearer token for REST API; Session/anti-bot for portals |
| **Job Description Availability** | Full HTML included via `?content=true` or individual `GET /jobs/{id}` | HTML (`description`), text (`descriptionPlain`), and bullet lists (`lists`) included | Both `descriptionHtml` and `descriptionPlain` included directly in listing | Varies; HTML extraction or massive XML |
| **Stable Identifiers** | Integer job `id` | Alphanumeric string posting `id` | Alphanumeric string job `id` | Variable or transient URL slugs |
| **Publication Dates** | `updated_at` (ISO 8601) | `createdAt` (Unix epoch milliseconds) | `publishedAt` (ISO 8601) | Inconsistent or missing |
| **Structured Compensation** | Not documented in public schema | Not documented in public schema | Documented via `?includeCompensation=true` | Unreliable or unparsed text |
| **Pagination Parameters** | None documented | `skip` and `limit` query parameters | None documented | N/A (single bulk file or web pages) |
| **Documented Rate Limits** | NOT ESTABLISHED BY REVIEWED SOURCES | NOT ESTABLISHED BY REVIEWED SOURCES | NOT ESTABLISHED BY REVIEWED SOURCES | Highly restrictive or WAF-blocked |
| **Documented Application Endpoint** | `POST /boards/{board_token}/jobs/{id}` | `POST /v0/postings/{company}/{posting_id}?key=APIKEY` | Out of scope (developer RPC requires API key) | Web form / portal submission |
| **Application Authentication** | HTTP Basic Auth (Employer API Key) | API Key parameter (`?key=APIKEY`) | Employer API Key (RPC) | Candidate login / CAPTCHA |
| **Explicit Documented Intended Use** | Build custom career sites, job boards, or sync job data for a Greenhouse account | Build custom jobs site; notes published jobs are public and may be scraped by third parties | Build a custom job board for a single organization | Syndication to partner boards (XML); human browsing (portals) |
| **Terms Governing Unauthenticated Access** | NOT ESTABLISHED BY REVIEWED SOURCES | Docs state published postings may be scraped by third parties; broader terms NOT ESTABLISHED BY REVIEWED SOURCES | NOT ESTABLISHED BY REVIEWED SOURCES | Terms explicitly prohibit automated access on major enterprise portals |
| **Initial Capability State** | `NEEDS_REVIEW` | `NEEDS_REVIEW` | `NEEDS_REVIEW` | `NEEDS_REVIEW` / `MANUAL_ONLY` |

---

### Detailed Breakdown: Permitted, Prohibited, and Uncertain Actions by Source

#### 1. Lever (Postings API v0)
- **Permitted (Documented Technical Capabilities):**
  - Querying active published postings for a designated company handle via `GET /v0/postings/{company}`.
  - Querying detailed posting metadata and structured text sections via `GET /v0/postings/{company}/{posting_id}`.
  - Paginating through results using `skip` and `limit`.
  - CORS-enabled client-side querying from custom web interfaces.
- **Prohibited:**
  - Automated application submission without a Super Admin API key (`POST /v0/postings/...` requires `?key=APIKEY`).
  - High-frequency polling loops, denial-of-service level request bursts, and stealth / evasion techniques.
  - Harvesting internal, closed, or draft jobs (which require the authenticated v1 Data API).
- **Uncertain / NOT ESTABLISHED BY REVIEWED SOURCES:**
  - Affirmative contractual license for multi-employer recurring aggregation by third-party personal agents. (The documentation note that jobs "may be scraped by third parties" acknowledges reality but does not constitute a bilateral license or warranty).
  - Numeric rate limits, burst thresholds, and CDN/WAF throttling rules for unauthenticated v0 requests.

#### 2. Greenhouse (Job Board API)
- **Permitted (Documented Technical Capabilities):**
  - Exporting published jobs, offices, and departments in lightweight JSON via `GET /v1/boards/{board_token}/jobs`.
  - Fetching full HTML descriptions by appending `?content=true`.
  - Retrieving custom application questions via `?questions=true`.
- **Prohibited:**
  - Submitting job applications programmatically without employer-issued Job Board API keys (HTTP Basic Auth required).
  - Uncredentialed access to internal candidate data or non-public requisitions (requires Harvest API).
- **Uncertain / NOT ESTABLISHED BY REVIEWED SOURCES:**
  - Authorization for third parties to aggregate across arbitrary customer boards without customer instruction or agreement.
  - Public endpoint request quotas, burst limits, and WAF blocking thresholds.

#### 3. Ashby (Public Job Posting API)
- **Permitted (Documented Technical Capabilities):**
  - Fetching all currently published job postings for a single organization via `GET /posting-api/job-board/{JOB_BOARD_NAME}`.
  - Retrieving structured compensation tiers and salary ranges via `?includeCompensation=true`.
  - Reading plain text and HTML descriptions in a single payload.
- **Prohibited:**
  - Automated application submission via the public posting API (no public submit endpoint; application must occur via `jobUrl`/`applyUrl` or authenticated partner RPC).
  - Bypassing authentication for administrative job operations (requires `jobsRead` API key).
- **Uncertain / NOT ESTABLISHED BY REVIEWED SOURCES:**
  - Aggregating job postings across multiple organizations. (The documentation explicitly frames the API as "meant for building a custom job board for a single organization").
  - Rate limits and throttling thresholds for unauthenticated public requests.

#### 4. Direct Employer Career Pages & Syndication Feeds
- **Permitted:**
  - Manual candidate navigation and browser-based job review (`MANUAL_ONLY`).
  - Downloading authorized open syndication feeds where explicitly licensed for candidate tools.
- **Prohibited:**
  - Automated headless browser scraping of employer career pages (violates enterprise portal terms of use and Hire-Steward's anti-scraping policy).
  - Evading CAPTCHAs, Cloudflare/Akamai bot detection, or login requirements.
  - Ingesting massive multi-tenant XML dumps (>100MB) that compromise candidate privacy, storage budgets, or local machine stability.
- **Uncertain / NOT ESTABLISHED BY REVIEWED SOURCES:**
  - Whether any individual employer provides an explicitly permitted, machine-readable personal candidate discovery interface without bespoke agreements.

---

### First Source Recommendation and Smallest Viable Pilot

* **Recommended Initial Candidate**: **Lever (Postings API v0)** is recommended as the candidate source requiring **explicit written clarification / formal owner risk acceptance** before activation.
* **Technical & Governance Rationale**:
  1. *Explicit Public Scrape Acknowledgement:* Lever is the only evaluated ATS whose official technical documentation expressly recognizes third-party automated access (*"all job postings in the published state are publicly viewable. These jobs may be scraped by third parties"*).
  2. *Deterministic Offset Pagination:* Lever supports integer `skip` and `limit`, enabling bounded, incremental batching with loop detection.
  3. *Structured Text Separation:* Lever separates HTML descriptions, plain-text descriptions, and bulleted lists (`lists`), enabling deterministic keyword matching and compensation evaluation without error-prone HTML sanitization.
  4. *Clean Manual Handoff:* Lever returns canonical `hostedUrl` and `applyUrl` links, allowing clean `MANUAL_ONLY` browser handoff without attempting automated submission.
* **Why Lever Cannot Be Activated Automatically**:
  - Lever's third-party scraping statement does not constitute an affirmative bilateral contract, warranty, or blanket legal indemnification.
  - Unauthenticated public rate limits remain undocumented.
  - Consequently, Lever must remain in **`NEEDS_REVIEW`** and disabled until the Phase 0 acceptance gate is formally resolved by the product owner.

#### Smallest Viable Pilot Boundaries

To prove read-only live discovery safely without widening scope or creating operational risk, any future pilot must strictly enforce:

1. **Candidate-Managed Token List Only**:
   - The pilot must NOT crawl the web or discover companies automatically.
   - The candidate must explicitly configure **1 to 3 specific employer handles** (e.g., `company_handle`).
2. **Strictly Bounded Polling Frequency**:
   - Polling frequency is restricted to **at most once every 24 hours** per configured employer handle.
   - Continuous polling loops, daemon watchers, and high-frequency triggers are prohibited.
3. **Rigid Request Budgets & Timeouts**:
   - Maximum 2 HTTP GET requests per employer handle per run (offset limit: 100 postings per page).
   - Maximum request rate: 1 request per second.
   - TCP connect timeout: maximum 5 seconds; HTTP read timeout: maximum 15 seconds.
4. **Honest Attribution**:
   - Transparent `User-Agent` header disclosing identity: `Hire-Steward/1.0 (+https://github.com/faais-k/Hire-Steward)`.
5. **Read-Only Scope**:
   - Strictly HTTP GET requests. Zero POST requests, zero application submission attempts, zero credential harvesting.
6. **Manual-Only Application Handoff**:
   - The candidate is directed to the canonical `hostedUrl` in their personal web browser. Automated submission is strictly out of scope.
7. **Fail-Closed Circuit Breaker**:
   - Three consecutive network or HTTP failures for an employer handle immediately trips the circuit breaker, halts polling for that board, and requires manual candidate inspection or reset.

---

### Phase 0 Exit Gate Status and Concrete Acceptance Criteria

* **Current Status:** **`IN_PROGRESS / NOT PASSED`**.
* **Core Rule:** The Phase 0 roadmap exit gate (*"No unresolved license or source-permission blocker for the first source"*) **CANNOT pass while any material source-permission blocker remains unresolved**.
* **Concrete Acceptance Criteria Required to Close Phase 0**:
  1. **Criterion 1 — Owner Source-Access Decision & Risk Posture Resolution**:
     - The product owner must formally review [ADR-0012](decisions/ADR-0012-job-discovery-source-access-and-lever-evaluation.md) and execute a formal written decision:
       - Either obtaining source-specific clarification or formal legal advice confirming that read-only polling of user-specified Lever boards complies with applicable terms; OR
       - Formally accepting the residual contractual risk of unauthenticated read-only polling under Lever's documented third-party scraping statement, constrained by the Smallest Viable Pilot boundaries.
  2. **Criterion 2 — Approved Single-Request Live Test Protocol**:
     - The owner must approve an isolated, single-request live inspection protocol executed against an agreed employer board to observe real-world HTTP headers, caching behavior (`ETag`, `Last-Modified`), and schema conformity without recurring polling.
  3. **Criterion 3 — Verified Offline Invariant Suite**:
     - Offline adapter tests with recorded fixtures must pass, demonstrating bounded pagination, loop detection, circuit breaking, honest `User-Agent` attribution, and deterministic error handling. *(Satisfied: 88 Lever adapter tests passing in test suite).*

Until Criteria 1 and 2 are explicitly executed and approved, Lever remains **`NEEDS_REVIEW`** and disabled, and Phase 0 remains **`IN_PROGRESS / NOT PASSED`**.

## 3. Initial and recurring discovery

### First activation

- Set the initial publication date range to the previous 14 days if the source provides a reliable date.
- If publication date is absent/unreliable, retain the job with `published_at = unknown` and label it “first observed” rather than inventing a publication date.
- Store an ingestion watermark separately from the listing's posted date.
- Save the run ID and source snapshot for reproducibility.

### Scheduled run

Default local times: 10:00, 17:00 and 22:00 in `Asia/Kolkata`. Persist timezone explicitly and test daylight/timezone handling. Do not rely on host timezone.

For each source:

1. Acquire a source-run lease to prevent overlapping crawl/checkpoint mutation.
2. Load last successful source checkpoint.
3. Query from the checkpoint or safe overlap window if supported. Use a small overlap to handle eventual consistency, then dedupe by stable IDs.
4. Fetch bounded pages; obey published rate limits and `Retry-After` headers where present.
5. Persist observations as pages are successfully processed.
6. Mark the run's completeness and errors.
7. Advance checkpoint only when the source's completion rules are met. Failed or partial runs do not advance a watermark that could lose jobs.
8. Release lease and persist final source health.

One source failure must not halt other independent sources. Do not start a parallel duplicate crawl for the same source while the lease is active.

## 4. Rate limiting and backoff

- Per-source concurrency defaults to 1 until measurement justifies an increase.
- Use token-bucket or leaky-bucket rate control as suitable, but document the actual configured policy.
- Honor public request limits, terms and `Retry-After`.
- Use bounded exponential backoff with jitter on retryable failures.
- Pause the source on repeated 401/403, CAPTCHA, access-policy warning, schema drift or a sudden rate-limit increase; classify the reason and notify the user.
- Never evade limits with account rotation, key rotation, proxy rotation, user-agent/fingerprint spoofing, or stealth behavior.
- No infinite retries. Use a source circuit breaker after repeated failures.

## 5. Normalization

Normalize the following while preserving original values:

- company/legal display name and normalized company key;
- exact source job/requisition ID and source/board ID;
- title and title family;
- location, country, remote/hybrid/on-site and secondary locations;
- employment arrangement (employee, contract, internship, temporary, commission-only);
- posted date, first seen, last seen and date provenance;
- salary amount/range, currency, period, base/variable/stipend, bonus/commission flags;
- visa sponsorship/work authorization text and confidence;
- required/preferred skills and qualifications;
- description content/hash;
- application URL and separate application-channel email where explicitly designated;
- source-level status (active, closed, unknown).

Never erase the raw string when normalizing. Every normalized value should point to source evidence or record that it is inferred.

## 6. Deduplication strategy

### Tier 1: exact

- Same source + stable requisition ID.
- Same canonical URL and stable source identity.
- Source-provided canonical vacancy ID.

### Tier 2: strong composite

- Normalized company + exact normalized title + location + substantially identical description hash + time overlap.
- Cross-source matches can be linked to a common vacancy cluster but should keep each source observation.

### Tier 3: possible duplicate

- Similar company/title/location with near-identical description but weak identity evidence.
- Flag for review; don't merge or auto-block based on title alone.

Store the dedupe rationale, candidate identifiers, confidence and matching algorithm version. User decisions should be auditable and update future duplicate handling without deleting evidence.

## 7. Job identity and lifecycle

A source observation may disappear or change without proof the job is closed. Store lifecycle states such as `ACTIVE`, `POSSIBLY_CLOSED`, `CLOSED_CONFIRMED`, `STALE`, `UNKNOWN`. Only authoritative source evidence or verified application response should mark closure with confidence. Preserve the application snapshot for any job already prepared/submitted.

## 8. Source schema changes

- Validate each source response against a typed schema.
- Treat unexpected required-field absence, type changes or large failure spikes as schema drift.
- Save a sanitized sample/fixture if permitted and safe.
- Disable submission for an adapter that no longer reliably maps fields; read-only discovery may continue if safe.
- Run contract tests before re-enabling.

## 9. Source health metrics

Track last attempt/success, run duration, pages/items, new/updated/duplicate counts, HTTP status distribution, rate limits, parse errors, checkpoint age, backfill gaps, schema version, and disabled reason. “No jobs found” must be distinguishable from “source failed” or “source was skipped because policy could not be verified.”
