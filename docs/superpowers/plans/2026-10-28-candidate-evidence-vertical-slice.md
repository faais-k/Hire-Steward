# Candidate Evidence and Provenance Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small, local-only foundation for candidate-document metadata, immutable text document versions, unreviewed candidate facts, and document-version provenance. Storage, provenance, extraction, and caller input must never be treated as proof that a candidate fact is true.

**Architecture:** Extend the existing FastAPI/SQLAlchemy modular monolith with a candidate-evidence domain, a confined content-addressed file adapter, one additive Alembic revision, and narrowly protected routes. PostgreSQL is authoritative for metadata and quota accounting. Raw text bytes live only under a configured owner-controlled data root outside tracked source files. No dependency is needed: FastAPI/Starlette already exposes `Request.stream()` for a bounded raw-body endpoint.

**Tech stack:** Python 3.12, FastAPI/Pydantic, SQLAlchemy 2.x, Alembic, PostgreSQL, pytest, existing SQLite migration fixtures, and the existing isolated `jobpilot_test` PostgreSQL pattern.

## Status and fixed scope

This is a plan revision only. The current implementation has compensation settings/assessments, not candidate profiles, documents, facts, storage, parsing, extraction, or upload routes. Existing public compensation evidence remains unverified and no part of this work changes that boundary.

The following Foundation 3 defaults are proposed for owner confirmation before implementation.

| Decision | Proposed Foundation 3 default |
|---|---|
| Initial file policy | Accept only non-empty UTF-8 `text/plain`, at most **10 MiB** per document version. Validate bytes while streaming; filename extension and declared media type alone are not evidence. |
| Storage limit | Default **100 MiB physical-service storage budget** for committed blobs, staged uploads, and service-managed orphans. Each upload persistently reserves the full 10 MiB before bytes are written; the committed/reserved meter is transactionally maintained. At most two in-process uploads may stream concurrently. |
| Fact taxonomy | Closed, validated types: `SKILL`, `EDUCATION`, `EMPLOYMENT`, `PROJECT`, and `CERTIFICATION`. Each accepts only its strict, bounded object shape below. |
| Verification boundary | New facts are always `UNREVIEWED`. No public route can set `USER_VERIFIED`, `REJECTED`, `SUPERSEDED`, `CONFLICTED`, confidence, an extraction result, an evidence hash, or a trusted state. Attaching provenance leaves the fact `UNREVIEWED`. |

PDF/DOCX parsing, OCR, malware-scanning integrations, LLM extraction, embeddings, a vector database, background tasks, job discovery, matching, a frontend, authentication implementation, multi-user tenancy, file downloads, application preparation, and submission are out of scope. Text-only ingestion supplies storage/version/provenance groundwork; it is not resume parsing.

## Existing conventions that this plan follows

- The app factory in `backend/app/main.py` includes routers directly and installs a global request-validation handler returning `422 {"detail":"INVALID_REQUEST"}`. Add an optional typed evidence-settings argument for test injection rather than a generic settings framework.
- Existing state-changing compensation routes use `Depends(require_local_same_origin)`. New writes use exactly that dependency. It is a local request guard, not authentication.
- Services use `with session.begin()`; preference updates use `SELECT ... FOR UPDATE`. Document-version allocation and quota updates follow that convention.
- Existing migration IDs are `0001_compensation_preference` and `0002_comp_evidence_trust`; the metadata guard requires unique IDs of at most 32 characters.
- `GET /ready` derives required tables/columns from `models.Base.metadata`, requires the Alembic head, and fails closed. New models automatically extend readiness expectations after migration.
- The conceptual API uses `/api/v1/documents` and `/api/v1/facts`. This plan adopts those paths and replaces only the conceptual multipart/task wording for the implemented text-only slice.
- PostgreSQL isolation is currently module-local in `backend/tests/integration/test_postgres_integration.py`, not shared in `conftest.py`. Move that exact fixture/helper pattern to `backend/tests/integration/conftest.py` before a second PostgreSQL module reuses it.

## Exact API contract

All state-changing operations require the existing matching local `Host` and `Origin` protection. JSON request models inherit `StrictRequest` (`extra="forbid"`). No endpoint returns raw bytes, absolute paths, temporary paths, database exception messages, or stored excerpts.

| Operation | Route and body | Result | Safe failures |
|---|---|---|---|
| Create logical document | `POST /api/v1/documents`; JSON `{ "display_name": string }` | `201` active document metadata with server UUID | `422 INVALID_REQUEST` |
| Create document version | `POST /api/v1/documents/{document_id}/versions`; streamed raw body; `Content-Type: text/plain` or `text/plain; charset=utf-8`; required `X-Original-Filename` | `201` version/blob metadata; `200` existing version for same bytes on same document | `403 LOCAL_SAME_ORIGIN_REQUIRED`, `404 DOCUMENT_NOT_FOUND`, `409 DOCUMENT_RETIRED`, `413 DOCUMENT_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`, `422 INVALID_DOCUMENT_CONTENT`, `503 EVIDENCE_STORAGE_UNAVAILABLE` |
| Read/retire documents | `GET /api/v1/documents`, `GET /api/v1/documents/{document_id}`, `GET /api/v1/documents/{document_id}/versions`, `POST /api/v1/documents/{document_id}/retire` | metadata only; retirement is idempotent and deletes nothing | `403` for write, `404 DOCUMENT_NOT_FOUND` |
| Create fact | `POST /api/v1/facts`; strict discriminated JSON union below | `201` with server-set `UNREVIEWED` | `422 INVALID_REQUEST` |
| Attach provenance | `POST /api/v1/facts/{fact_id}/provenance`; JSON `{ "document_version_id": UUID, "byte_start": integer, "byte_end": integer, "excerpt": optional string }` | `201` span/hash metadata; fact remains `UNREVIEWED` | `403`, `404 FACT_OR_DOCUMENT_VERSION_NOT_FOUND`, `409 DUPLICATE_PROVENANCE`, `422 INVALID_PROVENANCE`, `503 EVIDENCE_STORAGE_INTEGRITY_ERROR` |
| Read facts/provenance | `GET /api/v1/facts`, `GET /api/v1/facts/{fact_id}`, `GET /api/v1/facts/{fact_id}/provenance` | metadata only | `404 FACT_NOT_FOUND` |

For raw upload, reject declared `Content-Length` above 10 MiB before reading, but never trust it. Consume `Request.stream()` incrementally, count actual bytes, and stop with `413` once actual input exceeds 10 MiB. Do not call `await request.body()` or construct an unbounded in-memory byte string. Missing or dishonest `Content-Length` is therefore safe. Accept only `text/plain` with no charset or UTF-8 charset. Strict incremental UTF-8 decoding validates actual bytes; empty text, invalid UTF-8, or NUL bytes are `422 INVALID_DOCUMENT_CONTENT`.

Normalize `X-Original-Filename` with Unicode NFC, then accept only 1–128 characters matching `[A-Za-z0-9][A-Za-z0-9._ -]{0,127}`. Reject `/`, `\\`, `.`, `..`, and control characters. It is display metadata, never a storage path. Optional HTTP headers cannot all be rejected without breaking HTTP, but `X-Content-Hash`, `X-Storage-Key`, `X-Verification-State`, and similar headers are never read or authoritative; the server computes the values it needs.

## Candidate fact contract

Use a Pydantic discriminated union on `fact_type`; every outer/nested model has `extra="forbid"`. Strings are Unicode-normalized, non-empty after trim, and bounded. Store the server-generated canonical JSON form and SHA-256 `value_hash`; clients cannot send the hash.

| `fact_type` | Required `value` object | Optional bounded fields |
|---|---|---|
| `SKILL` | `{ "name": string <= 120 }` | none |
| `EDUCATION` | `{ "institution": string <= 160, "credential": string <= 120 }` | `field_of_study` <= 120; `graduation_year` 1900–2100 |
| `EMPLOYMENT` | `{ "employer": string <= 160, "title": string <= 160 }` | ISO `YYYY-MM-DD` `start_date`/`end_date`; end cannot precede start |
| `PROJECT` | `{ "name": string <= 160 }` | `description` <= 1,000 |
| `CERTIFICATION` | `{ "name": string <= 160 }` | `issuer` <= 160; `credential_id` <= 128 |

The database reserves `UNREVIEWED`, `DOCUMENT_SUPPORTED`, `USER_VERIFIED`, `CONFLICTED`, `REJECTED`, and `SUPERSEDED`, but the only state produced by this slice is `UNREVIEWED`. A link proves only a database reference and byte-span integrity; it does not prove semantic support, currency, or truth. No automatic `DOCUMENT_SUPPORTED` transition is designed or performed.

## Provenance versus verification

`candidate_fact_evidence` is provenance, not a verifier. On attach, the service validates the IDs, loads the version's blob hash, re-hashes the immutable text file, and rejects on a mismatch. It validates byte offsets, derives `evidence_hash = SHA256(blob[byte_start:byte_end])` server-side, and stores offsets plus the derived hash. Optional `excerpt` must exactly equal the strict UTF-8 decoding of that span and is discarded after validation; raw excerpts are neither stored nor returned. The span is limited to 4 KiB.

This proves a recorded span exists in a retained immutable version. It does not prove the span semantically supports the fact. There is no parser, extractor, source verifier, LLM, confidence assignment, or truth promotion. Missing/tampered blob data produces no provenance record and a safe `503`.

## Consistent schema and migration design

Use seven tables, not the earlier inconsistent five-table proposal: a singleton usage table plus durable upload reservations are necessary to bound service-managed physical storage under concurrent PostgreSQL uploads and crashes.

| Table | Fields and constraints |
|---|---|
| `candidate_document_blobs` | `content_hash` `String(64)` PK; unique server-generated `storage_key` `String(96)`; `media_type = text/plain`; positive `byte_size` `BigInteger`; `created_at`. Server validates lowercase SHA-256 hex; portable DB checks enforce length/size/media type. |
| `candidate_evidence_storage_usage` | Singleton `id = 1`, non-negative `committed_bytes` and `reserved_bytes`, positive `version`, `updated_at`; seed zero. Lock it with `FOR UPDATE` before every reservation, finalization, or reconciliation. Enforce `committed_bytes + reserved_bytes <= configured_total_bytes`. |
| `candidate_evidence_storage_reservations` | UUID `id`; fixed `reserved_bytes` equal to the configured per-version cap at reservation time; server-owned temporary key; state `STAGING`, `READY_TO_PLACE`, or `PLACED`; nullable computed content hash/final key/actual size; creation/update timestamps. The reservation is committed before its temporary file is created and persists until finalization or safe reconciliation. |
| `candidate_documents` | UUID `id` `String(36)`, safe `display_name` `String(120)`, state `ACTIVE`/`RETIRED`, `created_at`, `retired_at`. Retirement is metadata-only. |
| `candidate_document_versions` | UUID `id`; `document_id` FK `RESTRICT`; positive `version_number`; `blob_hash` `String(64)` FK to blob `content_hash` `RESTRICT`; sanitized filename; ingestion timestamp; `extraction_status = NOT_REQUESTED`; nullable safe extraction error/version. Unique `(document_id, version_number)` and `(document_id, blob_hash)`. Immutable. |
| `candidate_facts` | UUID `id`; closed `fact_type`; JSON value; server-generated `value_hash`; reserved state constraint/default `UNREVIEWED`; optional `supersedes_fact_id` self-FK `RESTRICT`; created timestamp. No confidence column in this slice. |
| `candidate_fact_evidence` | UUID `id`; fact/version FKs `RESTRICT`; non-negative start and positive end offsets; derived hash; server-set method `LOCAL_API_REPORTED`; timestamp. Unique `(fact_id, document_version_id, byte_start, byte_end)` and indexes for fact/version. |

Name all foreign keys, checks, primary keys, uniques, and indexes. Index documents by `(state, created_at)` and versions by `(document_id, ingested_at)`. Services independently verify cross-record IDs before insert.

Create additive revision `0003_candidate_evidence` (24 characters), with `down_revision = "0002_comp_evidence_trust"`. Create blobs, usage, reservations, documents, versions, facts, provenance; seed only usage. Downgrade provenance, facts, versions, documents, reservations, usage, blobs. **Downgrade drops every Foundation 3 table and all candidate-evidence metadata; it is safe only for disposable/synthetic data or after an explicit export-and-removal decision. It does not preserve a populated installation's candidate evidence.** Do not alter compensation tables/logic. The existing migration-metadata guard enforces the revision length.

## Storage and crash-recovery protocol

1. Acquire a two-slot in-process semaphore. In a short committed transaction, lock the usage singleton and require `committed_bytes + reserved_bytes + 10 MiB <= 100 MiB`. Create a durable `STAGING` reservation for the full 10 MiB, increase `reserved_bytes` by 10 MiB, and generate its unique temporary key. This is intentionally conservative: an upload of one byte and a future deduplicated upload reserve 10 MiB while staging so missing/dishonest headers cannot bypass the physical budget.
2. Only after that reservation commits, stream into the reservation's temporary file *inside* the configured root. Incrementally hash/decode UTF-8 and cap actual input at 10 MiB. Delete only that request-owned temporary file on ordinary pre-placement failure, then in a separate transaction release its reservation. A hard crash leaves both the file, if any, and the durable reservation for reconciliation.
3. Require an absolute configured root outside the repository, resolve it before use, and owner-restrict it (`0700` dirs/`0600` files where POSIX permissions apply). Reject repository-relative roots, non-positive values, per-version limit above total quota, and malformed configuration. Document placeholders only in `.env.example` after implementation.
4. Derive the only final key as `sha256/<first-two-hex>/<full-64-hex-hash>`, resolve it, and confirm it stays under the root. The filename never contributes to the key. In a short committed `READY_TO_PLACE` transition, record the server-calculated hash, actual size, and intended final key while retaining the reservation. This makes a final orphan identifiable if a crash follows placement.
5. For an existing committed blob, verify its on-disk full hash/size, discard the request temporary file, create only the document version, and release the full reservation. For a new hash, atomically place staged content, then in finalization lock the usage row, reservation, and target document. Add blob/version metadata; replace the 10 MiB reservation with the actual blob size by increasing `committed_bytes` by actual size, decreasing `reserved_bytes` by 10 MiB, and deleting the reservation in the same transaction. Locks serialize quota accounting and `max(version_number) + 1` allocation.
6. If final placement fails, retain/reconcile the reservation safely; ordinary handling may remove only its temporary file. If the database transaction fails after placement, the prior `READY_TO_PLACE` reservation and its 10 MiB accounting remain committed while new metadata rolls back. The resulting final file is a potential orphan and cannot be reused, overwritten, or silently deleted by later uploads.
7. Implement a local operator-only reconciliation command as part of this slice, not an HTTP route. Under the usage-row lock and after a configurable grace period, it processes stale reservations. It probes a reservation's temporary and intended final keys; it may delete one only after rechecking that no `candidate_document_blobs` row references the matching hash/key, then releases the reservation. If a blob row exists, it never deletes the file and reports an integrity error. Unexpected files not matching a reservation or blob record are reported but never auto-deleted. A later upload encountering a reservation-owned orphan must fail safe with `EVIDENCE_STORAGE_PENDING_RECONCILIATION` rather than claim/reuse it.

For files created exclusively by this single API process under the owner-restricted root, `committed_bytes + reserved_bytes <= 100 MiB` is a strict **service-managed physical-storage budget**: each staged or orphaned file is covered by a full 10 MiB reservation until it is committed or reconciled. Repeated database failures consume reservations and eventually reject new uploads; they cannot increase service-managed file bytes beyond the budget. This is intentionally an availability trade-off. It is not a filesystem-wide disk quota: a user, another process, manual file copy, filesystem block overhead, or a second uncoordinated API process can still consume disk outside this guarantee. OS quotas and multi-process admission are future hardening.

## Files to change when implementation is separately approved

| File | Responsibility |
|---|---|
| `backend/app/evidence_config.py` | Typed validated storage settings and test injection. |
| `backend/app/adapters/storage.py` | Stream/temp/hash/UTF-8 validation, confinement, atomic placement, existing-blob verification, range read. |
| `backend/app/domain/candidate_evidence.py` | Enums, filename/fact schemas, canonical JSON/hash helpers, typed errors. |
| `backend/app/services/candidate_evidence.py` | Transactional document version/quota/fact/provenance operations. |
| `backend/app/db/models.py` | Seven ORM tables with named constraints/indexes, including usage and durable reservations. |
| `backend/migrations/versions/0003_candidate_evidence.py` | Additive migration and dependency-order downgrade. |
| `backend/app/api/schemas.py`, `backend/app/api/routes/candidate_evidence.py`, `backend/app/main.py` | Strict contract above, router registration, optional settings injection. |
| `backend/tests/integration/conftest.py`, `backend/tests/integration/test_postgres_integration.py` | Move current safe PostgreSQL fixture/helpers without weakening its dedicated database/schema protections. |
| `backend/tests/unit/test_candidate_evidence.py`, `backend/tests/integration/test_candidate_evidence_api.py`, `backend/tests/integration/test_postgres_candidate_evidence.py` | Unit/storage, SQLite/API, and real PostgreSQL coverage. |
| `.env.example`, `.gitignore`, `README.md`, `docs/api-spec.md`, `docs/data-model.md`, `docs/security-privacy.md`, `docs/testing-evaluation.md`, `docs/requirements-traceability.md`, `docs/risk-register.md`, `docs/memory.md` | Update only after implementation, from actual behavior/results. |

## Test-first implementation tasks

### Task 1: finalize scope and failing contracts

- [ ] Record owner confirmation of text-only 10 MiB/100 MiB policy, the five fact schemas, and `UNREVIEWED`-only creation. Add an ADR only if it becomes durable cross-product policy.
- [ ] Add failing domain/schema/API tests for the exact routes and JSON/raw contracts above.
- [ ] Acceptance: no code/path implies parsing, semantic verification, `DOCUMENT_SUPPORTED`, `USER_VERIFIED`, or submission eligibility.

### Task 2: failing adversarial tests

- [ ] Cover unsafe filenames/root escape, media spoofing, empty/invalid UTF-8/NUL bytes, exact/over 10 MiB stream, absent/false `Content-Length`, quota admission, existing blob mismatch, and no response leakage of text/path/SQL details.
- [ ] Cover all type-specific fact values/unknown nested fields and caller/model attempts to set state/confidence/hash/storage/extraction/verifier/decision fields.
- [ ] Cover absent/mismatched fact/version, invalid range/excerpt, blob tampering, duplicate provenance, and `UNREVIEWED` after valid link.
- [ ] Cover two concurrent 10 MiB reservation attempts, a deduplicated upload releasing its reservation without a second committed-byte increment, database failure after placement retaining a reservation, stale temporary/final reservation reconciliation, unexpected-root-file reporting without deletion, quota exhaustion after repeated failed finalizations, and the refusal to delete a blob referenced by a committed row.
- [ ] Acceptance: failures reflect absent behavior, not a shared-fixture or unsafe database setup error.

### Task 3: models/migration/readiness

- [ ] Add seven models and revision `0003_candidate_evidence`; test clean head, `0002 -> 0003` compensation preservation, invalid FK/state/size/usage/reservation inserts, and dependency-order downgrade against synthetic evidence only. Document in the migration test that downgrade drops all Foundation 3 candidate-evidence metadata and is not a populated-installation preservation path.
- [ ] Test `/ready` fails closed for missing Foundation 3 table/column/stale head while `/health` remains DB independent.

### Task 4: storage/services/routes

- [ ] Implement bounded streaming storage then document/fact/provenance services under existing `with session.begin()` patterns and protected routes.
- [ ] Test database failure after placement: metadata/version/provenance/committed usage roll back, but the durable reservation remains and physically accounts for the potential orphan until reconciliation.
- [ ] Acceptance: successful fact is always `UNREVIEWED`; provenance validates version/span integrity only.

### Task 5: SQLite/PostgreSQL/docs/verification

- [ ] Move the module-local PostgreSQL fixture to integration `conftest.py`; retain its exact `postgresql+psycopg`, `jobpilot_test`, random schema, and cleanup safeguards.
- [ ] PostgreSQL-only tests: FK/check constraints, 0002 upgrade, destructive downgrade against synthetic data, rollback/orphan reservation retention, concurrent identical uploads/version allocation, quota/reservation locks, readiness schema drift, plus existing compensation isolation regressions.
- [ ] Run `uv run --locked pytest -m "not postgres" -q`, `uv lock --check`, compilation, PostgreSQL tests only with dedicated `JOBPILOT_TEST_DATABASE_URL`, and `git diff --check`. Update docs/memory only for actual behavior/results; commit/push only with separate authorization.

## Acceptance criteria for the implemented slice

- Only non-empty valid UTF-8 `text/plain` up to 10 MiB is accepted, with actual-byte streaming enforcement independent of `Content-Length`.
- Roots/keys cannot escape the configured external root; unsafe names, types, bytes, sizes, hashes, and storage-key assertions fail safely.
- Each committed version references an immutable blob through `blob_hash`; duplicate content, version numbers, committed/reserved accounting, and `RESTRICT` FKs are deterministic under PostgreSQL concurrency.
- In the supported single-process, owner-restricted-root environment, full-capacity durable reservations bound all service-managed staged/orphan/committed file bytes to 100 MiB. Quota exhaustion safely rejects more uploads. This is not an OS/filesystem-wide limit.
- Crash handling leaves at most a reported, reservation-accounted potential orphan, never a committed missing-file reference. Reconciliation never deletes a blob referenced by a committed row.
- Closed fact schemas reject arbitrary JSON. Client/model input cannot set trust, confidence, state, hashes, extraction results, or storage keys.
- Provenance derives byte-span hashes server-side but never establishes semantic support or promotes an `UNREVIEWED` fact.
- `/ready` fails closed for stale/missing Foundation 3 schema; `/health` remains independent. Compensation and live-submission safety guarantees are unchanged.

## Remaining limitations and revisit triggers

- Span integrity is not semantic verification. `DOCUMENT_SUPPORTED`, `USER_VERIFIED`, confidence, conflicts, and supersession require separate reviewed workflows.
- The semaphore is a single-process local control. Multi-process/remote/multi-user scope needs stronger admission/authentication/authorization design first.
- PDF/DOCX/OCR, malicious-file scanning, parser/extractor output, raw-file download, backup/restore, and automated (rather than operator-approved) reclamation require separate security/resource/license/operational work.
