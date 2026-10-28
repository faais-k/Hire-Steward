# Hire-steward — Security, Privacy and Threat Model

**Status:** Security baseline. Revisit before any remote deployment, new provider integration, or live submission feature.

## 1. Data assets

- Candidate identity/profile, contact details and work authorization declarations.
- Resumes, certificates, employment/work reports, project documents and extracted facts.
- Job/application history, exact application answers, submitted documents and confirmation evidence.
- API keys, OAuth tokens, refresh tokens, browser cookies/session state, passwords and OTPs.
- Provider prompts/responses, model telemetry, logs, screenshots and backups.
- Source credentials, rate limits and capability records.

## 2. Threat actors and failure modes

- Malicious or compromised job page containing prompt injection or malicious HTML.
- Malicious document, hidden text, hostile PDF content, filenames or archive paths.
- Provider compromise, misconfiguration, quota/fallback behavior or unexpected data retention.
- Local malware or another user/process accessing local files or ports.
- Accidentally exposed dashboard/DB/backup on a public interface.
- Credential leakage through `.env`, stack traces, screenshots, browser profiles or exports.
- ATS schema changes causing wrong field mapping or duplicate submissions.
- Concurrency race bypassing daily limits or duplicate checks.
- Import bundle with zip-slip, path traversal or malicious oversized content.
- Model hallucination, cross-task context leakage or retrieved instruction abuse.

## 3. Core controls

### Local access

- Bind API to loopback by default.
- Do not bind `0.0.0.0` without explicit deployment configuration, authentication, TLS and firewall/network review.
- Current state-changing compensation routes require a loopback `Host` and matching `Origin`; Starlette's trusted-host middleware rejects non-loopback host names. This is a local browser request guard, not user authentication, and must not be treated as safe remote access. No permissive CORS policy is enabled.
- Provide separate liveness and readiness endpoints; health output must not include environment variables or secrets.
- Use restrictive filesystem permissions for data/credential directories and run containers as non-root where feasible.

### Secret management

- API keys and OAuth tokens are not application facts and must not be sent to the LLM.
- Use OS credential manager or an encrypted local vault for durable personal use. Environment variables may be used to inject secrets into containers at runtime but should not be treated as a durable secure vault.
- `.env.example` contains variable names and placeholders only; real `.env` is ignored by Git.
- Compose binds the development PostgreSQL port to loopback. The sample password is a local placeholder, not a production credential. GitHub Actions uses a disposable test-only password; it does not contain user or service credentials.
- PostgreSQL tests require the explicit `JOBPILOT_TEST_DATABASE_URL` variable and exact `jobpilot_test` database name. They use unique temporary schemas and remove only those schemas; do not point the test variable at a developer's normal database.
- For remote hosting, use platform secrets or a dedicated secret manager and least-privilege service accounts.
- Do not store long-lived tokens in browser local storage.
- Never export credentials, cookies, tokens, OTPs or browser profiles by default.

### Candidate data minimization

- Collect only data required for a configured task.
- Each field/category has an allowlist specifying whether it may be sent to a particular target/source/provider.
- A restricted executor fills only approved form fields on trusted domains. The LLM proposes content but cannot read vault secrets or arbitrary hidden fields.
- Redact phone/address/identity numbers where not needed for a particular task.
- For external AI, apply privacy classification before context construction and honor user provider-sharing settings.

### Prompt injection and content safety

- Treat all web pages, resumes, emails, office files, PDFs and OCR output as untrusted data.
- Do not permit retrieved text to modify system policy, tool permissions, destination allowlists, secrets or consent.
- Use strict schemas and backend validation, but do not rely on schema validity alone to establish factual accuracy.
- Render HTML descriptions in a safe sanitized mode or plain text.
- Scan imported archives for path traversal, unexpected file types and excessive expansion.

### Compensation evidence integrity

- Treat API-supplied or model-extracted compensation status, amount/range, currency, period and reference as unverified observations. The caller cannot set `VERIFIED`; strict request validation rejects verification/outcome fields and returns a generic safe `422` without echoing submitted values.
- A URL or opaque reference is metadata, not proof of source authenticity, retrieval, permitted access, or support for the claimed amount. A model's assertion that a source was checked is not proof.
- Only a future controlled source-ingestion/verifier component may establish trusted compensation evidence. It must record permitted source/method, retrieved source/version hash or immutable snapshot, supporting text/span, verified fields, verifier version/method and timestamp. This path is not implemented; therefore public compensation assessments remain unverified and review-required.
- Assessment results and submission eligibility are separate. An unverified assessment cannot be marked eligible to submit. Trusted unpaid evidence must be deterministically blocked regardless of the user-configured threshold; unverified reported unpaid is not labeled a verified fact but remains held for review.

### Browser executor

- Explicit per-source/domain allowlist.
- No stealth behavior, CAPTCHA bypass, access-control evasion, proxy/account rotation, or arbitrary navigation.
- No model-generated JavaScript, shell commands or arbitrary HTTP requests.
- Use dedicated browser context, minimal session lifetime, restricted persistence and explicit user handoff.
- Remove sensitive values from screenshots/traces where possible; disable or tightly restrict traces that may include personally identifiable data.

## 4. Source and provider data policy

For each source/provider, store terms/docs URL, last review date, permitted operations, data categories allowed, retention expectations, quota and user consent. The source adapter must fail closed if the requested operation is not verified.

Official service terms/pricing/data handling may differ across free and paid tiers and can change. Do not infer privacy from “free” or “API.” Recheck and disclose actual provider behavior when activating a provider.

### Gemini

Official Gemini API pricing documentation currently distinguishes free and paid tiers and indicates a difference in whether submitted content may be used to improve products. Verify the exact current policy for the selected model/tier at configuration time: https://ai.google.dev/gemini-api/docs/pricing.

### Groq

Current rate-limit documentation exposes model-dependent request/token limits and 429 behavior. Use returned rate-limit headers and configured limits; do not assume a fixed universal limit: https://console.groq.com/docs/rate-limits.

### Gmail

OAuth scopes and app verification requirements need review. Prefer the narrowest practical permission. The official scope list identifies `gmail.send` as sensitive: https://developers.google.com/workspace/gmail/api/auth/scopes.

## 5. Sensitive values and restricted executor

The model must never handle passwords, OTPs, session cookies, API keys, refresh tokens or secrets from the credential vault. Candidate identity fields (for example, national identity numbers, complete home address, health/legal/financial details) require a separate sensitivity classification and an explicit purpose/target allowlist.

The executor should receive only opaque secret references for pre-approved fields; secret material is resolved immediately before filling by a trusted local boundary, not included in model prompts, telemetry or generated text. If that design cannot be implemented safely in the first release, do not automate such fields; require manual entry.

## 6. Logging and audit safety

Allowed to log: run/task IDs, source ID, model ID, duration, status, counts, safe error code, hashes and non-sensitive gate outcomes.

Do not log by default: complete resume text, raw sensitive answers, tokens, cookies, OTPs, private prompt payloads, unredacted screenshots, authorization headers or full provider errors that may echo request bodies.

Audit events should record consequential state changes with actor, timestamp, subject, decision version and references. Audit immutability is a design property; restrict database write access and consider hash chaining if tamper evidence is needed. Avoid calling it “tamper-proof” without a separate security design.

## 7. Retention and deletion

- Document active retention settings and delete/export controls.
- Distinguish active facts, historical submitted artifacts, logs, provider telemetry and backups.
- A removed watch-folder file should not silently delete historical records used for an application.
- Deletion should explain immediate removals and backup expiry behavior.
- Exports should be encrypted where they include sensitive personal data, with the user responsible for protecting the export passphrase/key.
- Never include an encrypted backup key inside the same unprotected package as the encrypted payload.

## 8. Remote-hosting hardening checklist

Before remote use:

- Authentication and authorization implemented and tested.
- TLS at the ingress and restrictive firewall rules.
- No public database/browser-debug port.
- Non-root containers, read-only root filesystem where practical, resource limits, minimal images and dependency scans.
- Secrets manager and rotation/revocation procedure.
- Rate limiting on API, login and export endpoints.
- CSRF/CORS/session security reviewed according to authentication method.
- Backup encryption, access controls, restore drill and retention policy.
- Logs/metrics contain no sensitive payloads.
- Threat model and penetration test updated.

## 9. Incident response

Document how to: globally stop submissions; disable a source adapter/provider; revoke OAuth/API credentials; quarantine imports; preserve sanitized audit evidence; restore from a known backup; identify impacted applications; and notify the user of any potentially duplicated or uncertain external action. Do not automatically delete the only evidence needed to reconcile a submission.

## 10. Security acceptance tests

- Prompt injection from job pages cannot invoke tools or override policies.
- `.env`, API keys, cookies, OTPs and identity secrets are absent from exports/logs/test snapshots.
- SSRF attempts to localhost/private IPs are blocked by source-fetch layer.
- Filename/path traversal and zip-slip inputs are rejected.
- Unauthenticated non-loopback access is blocked in default deployment.
- Concurrent submit requests cannot exceed cap or create duplicate attempts.
- Database/file access permissions and backup encryption behave as documented.
- Compose configuration and readiness fail safely when PostgreSQL is unavailable; PostgreSQL-specific migration, transaction and concurrency assertions require a run against a real PostgreSQL server.
