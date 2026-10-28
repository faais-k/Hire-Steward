# ADR-0011: Candidate evidence uses bounded local storage and unreviewed provenance

**Status:** Accepted for Foundation 3 implementation  
**Date:** 2026-10-28

## Context

Hire-steward needs candidate-document versions and fact provenance without
turning uploaded text, extracted data, or a model assertion into verified
candidate truth. Filesystem and database commits cannot be atomic. Unbounded
upload bodies and orphaned files create local denial-of-service and recovery
risks.

## Decision

Foundation 3 accepts only non-empty strict UTF-8 `text/plain` bodies. The
server streams and hashes bytes, limits each version to 10 MiB, stores content
by SHA-256 beneath a configured absolute root outside the checkout, and never
uses caller filenames/paths as storage identity.

The service admits at most two in-process upload streams and reserves the full
10 MiB in PostgreSQL before writing. A singleton committed/reserved meter has a
100 MiB service-managed budget. Reservations persist through staging and a
database failure after placement, so potential orphan files remain accounted
until operator-only stale reconciliation. Reconciliation never deletes a file
referenced by a committed blob; unexpected files are reported, not deleted.

Documents/versions, blobs, usage, reservations, facts, and fact evidence use
revision `0003_candidate_evidence`. New public facts are always `UNREVIEWED`.
Provenance validates a document-version byte span and derives its hash on the
server; it proves byte integrity only, not semantic support or truth.

## Consequences

- This bounds service-created staged/orphan/committed bytes in supported
  single-process deployment. It is not OS disk quota and does not coordinate
  independent processes or manual writers.
- No PDF/DOCX/OCR/parser/LLM extraction, raw download, or verification route is
  introduced.
- `0003` downgrade drops Foundation 3 evidence metadata. It is only safe for
  disposable synthetic data or after deliberate export/removal; it does not
  preserve populated evidence.
- Future semantic evidence support, user verification, multi-process storage,
  backup/restore, and automated reclamation need separate decisions.
