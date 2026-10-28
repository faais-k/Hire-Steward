# ADR-0008: Focused storage for compensation preference and assessments

**Status:** Accepted for the first backend slice  
**Date:** 2026-10-28

## Context

The project has no existing application schema or migration history. The owner authorized a narrow backend slice that must persist the configurable annual minimum, audit intentional changes transactionally, and preserve the threshold used for each assessment. A generic settings framework or premature full candidate/job schema would add scope without supporting this slice.

## Decision

- Use one root Python project and one `uv.lock` for the modular monolith. Keep Python code under `backend/`; migrations are owned by `backend/migrations/`.
- Constrain transitive Starlette below 1.0 while the test client integration uses `httpx`; the resolved Starlette 1.x release deprecates that pairing. Revisit the constraint when migrating tests to the supported successor client.
- Store the single local user's minimum in a focused `compensation_preferences` row with exact `NUMERIC(18,2)` amount, explicit `INR` and `YEAR`, version, and update timestamp. Seed INR 100,000/year in the migration. Constrain the singleton identity, currency, period, version, and non-negative amount in the database.
- Store changes in an append-only `compensation_preference_audits` table. The setting update and its audit row share one transaction. Actor metadata is assigned by the server (`local_api` / `local`) because this slice has no user authentication; clients cannot select it and the field does not claim a verified human identity.
- Persist each deterministic evaluation in an append-only `compensation_assessments` table with its threshold snapshot, source evidence fields, normalized annual range if available, conversion basis, outcome, reason code, and timestamp. This initial slice uses a caller-provided opaque job reference because the canonical job table does not exist; a later job-schema migration may add a foreign key without rewriting assessment history.
- Use exact decimal strings at the JSON boundary. Support direct INR/year amounts and explicitly recurring INR/month amounts annualized by 12. Other currencies and unsupported periods require review; do not infer exchange rates, hours, days, or contract duration.
- Use Psycopg 3 as SQLAlchemy's synchronous PostgreSQL driver for the synchronous API. The resolved `psycopg` and `psycopg-binary` distributions report `LGPL-3.0-only`; explicit license review remains required before redistributing/bundling the application. No legal conclusion is made here.
- Require same-origin `Origin` and loopback `Host` values on state-changing local API requests. Do not enable permissive CORS or remote access in this slice. This is a narrow local browser request guard, not authentication or a remote-deployment security boundary.

## Alternatives considered

- **Store settings in a generic JSON profile:** this follows the conceptual future profile model but provides weaker database constraints for the only current setting and requires profile infrastructure that does not yet exist.
- **Create the full candidate profile, job, application, and audit schemas now:** rejected because it exceeds the requested slice and would force unvalidated choices about unrelated entities.
- **Use floating-point values or JSON numeric values:** rejected because exact threshold comparisons and persisted money values must remain decimal-safe.
- **Normalize all pay periods immediately:** rejected because reliable annualization requires source-specific facts (hours, workdays, term, exchange rate) not present in the current model.

## Consequences

- The schema is intentionally single-user and focused. A future multi-profile design will need an explicit migration and actor identity model.
- Assessment history can be explained after a preference change. No application-submission tables or routes are introduced here; submitted application records remain outside this slice.
- PostgreSQL is the production database target. SQLite is used only for local migration/API integration tests; PostgreSQL-specific verification requires a running PostgreSQL service.
- The same-origin guard limits accidental cross-origin browser writes but does not replace authentication, OS account isolation, or a security review before remote exposure.

## Revisit when

- A canonical candidate profile/job schema is introduced.
- Multi-user or remote access is approved.
- Evidence supports additional currency or compensation-period normalization.
- PostgreSQL integration tests can run against the supported local deployment.

## Historical clarification — compensation evidence trust

The original Foundation 1 assessment endpoint accepted caller-reported status, amounts and an opaque reference and let the evaluator treat those fields as verified evidence. That trust interpretation was incorrect and is superseded by [ADR-0009](ADR-0009-compensation-evidence-trust-boundary.md). The storage choices in this ADR remain in effect, while caller-originated assessment data is now explicitly reported/unverified. Migration `0002_compensation_evidence_trust_state` marks existing assessments unverified; no public endpoint can create a trusted state. The project still has no complete source-ingestion/verifier path.
