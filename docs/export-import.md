# Hire-steward — Portable Export and Import Specification

**Status:** Planned; implementation belongs to the portability phase.

## 1. Goals

- Move a user's history and selected evidence between Hire-steward installations.
- Preserve provenance, application outcomes, exact submitted artifacts, policy/model versions and timestamps.
- Validate package integrity and schema compatibility before mutating destination state.
- Exclude credentials and secrets by default.
- Make sensitive data inclusion explicit, scoped and understandable.

## 2. Export package layout

Illustrative versioned archive:

```text
hire-steward-export-<date>-<id>.zip
├── manifest.json
├── checksums.sha256
├── data/
│   ├── candidate-profile.json
│   ├── candidate-facts.jsonl
│   ├── documents.jsonl
│   ├── jobs.jsonl
│   ├── job-snapshots.jsonl
│   ├── assessments.jsonl
│   ├── applications.jsonl
│   ├── application-attempts.jsonl
│   ├── application-artifacts.jsonl
│   ├── application-answers.jsonl
│   ├── audit-events.jsonl
│   └── provider-usage-redacted.jsonl
└── evidence/
    └── <content-hash-or-stable-id>/original-file
```

Exact layout may change; `manifest.json` is the compatibility contract. JSONL is suitable for large record collections but must be validated per line with explicit record schema versions.

## 3. Manifest requirements

Fields should include:

- bundle format name and schema version;
- export ID, created timestamp and source app version;
- database schema and relevant policy/scoring/prompt versions;
- selected entity categories and record counts;
- evidence file manifest (stable ID, content hash, size, media type, version/provenance);
- hashes/checksum algorithm;
- whether sensitive personal data was included and the categories included;
- whether encryption was enabled (never export encryption keys/passphrases in the same package);
- excluded categories such as credentials/secrets;
- import compatibility requirements and warnings.

## 4. Never export by default

- API keys, OAuth access/refresh tokens, passwords, private keys, session cookies, browser profiles, OTPs, recovery codes and credential vault contents.
- Raw `.env` files or runtime environment dumps.
- Unredacted logs, browser traces or screenshots that may include secret values.
- Arbitrary provider prompt/response payloads unless explicitly selected under a privacy-aware export option.

Sensitive personal data (for example, national identity numbers, complete address, health/legal/financial facts) should be omitted or redacted unless the user explicitly opts in with a category-specific warning.

## 5. Integrity and encryption

- Generate checksums for every file and validate before import.
- Prefer authenticated encryption for packages containing sensitive data; use a well-reviewed library and documented envelope design rather than bespoke crypto.
- If passphrase-based encryption is offered, use a standard password-based key derivation and authenticated encryption implementation, with parameters/version stored safely in the manifest.
- Never store the decryption key/passphrase in the archive or alongside an unprotected backup.
- A valid checksum is evidence of accidental-corruption detection, not proof that a package is trustworthy or safe.

## 6. Import procedure

1. Upload/open archive into a dedicated staging directory.
2. Enforce compressed and expanded size caps, entry-count caps and file-type rules.
3. Reject absolute paths, path traversal, symbolic links and zip-slip entries.
4. Parse manifest and verify supported format version.
5. Validate every checksum and schema record.
6. Check foreign-key/reference integrity and duplicate IDs.
7. Identify unknown fields and migration needs; do not silently discard critical fields.
8. Produce an import preview with counts, conflicts, sensitive categories and expected changes.
9. Require explicit confirmation before commit.
10. Import in a transaction/batch strategy that can resume or roll back safely.
11. Preserve original source IDs where collision-free and maintain a mapping when IDs conflict.
12. Rebuild derived embeddings/indexes only after base data imports successfully and only when required; store model versions.
13. Disable live submission during import and reconciliation.
14. Verify counts/hashes and produce an import report.

## 7. Conflict handling

- Never silently overwrite a destination's current candidate profile or facts.
- For identical content hashes, deduplicate blobs while preserving source/version provenance.
- For conflicting facts, show both values and source/verification statuses; require user resolution.
- For application history conflicts, preserve both histories and flag duplicate logical applications for review.
- If a submission attempt is in an uncertain state, import it as uncertain and do not retry it automatically.
- Preserve previous policy, score and model versions for historical assessments; don't re-evaluate history silently.

## 8. Portability tests

- Export/import round trip preserves counts, provenance, timestamps, artifact hashes and application outcomes.
- Secrets and sentinel token values never appear in archive or manifest.
- Optional sensitive data is excluded by default and inclusion is accurately disclosed.
- Truncated/corrupt archives fail without modifying live state.
- Path traversal/zip-slip archive is rejected.
- Newer/unknown schema handling is explicit.
- Duplicate import is idempotent or produces a clear conflict report.
- Import into clean instance works and subsequent backup/restore remains valid.
