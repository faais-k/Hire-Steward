# ADR-0009 — Compensation Evidence Trust Boundary

**Status:** Accepted; public trust boundary implemented, trusted evidence ingestion pending  
**Date:** 2026-10-28  
**Related:** ADR-0007, ADR-0008

## Context

Foundation 1 accepted caller-supplied compensation status, amounts and an arbitrary opaque evidence reference. The service passed those values to the domain evaluator as if they were verified, so a public caller could obtain a `MEETS_THRESHOLD` result without proof that a source existed, had been retrieved, or supported the amount. The model-facing specification also allowed extraction but did not define a production provenance verifier. A reference string and a model assertion do not establish authenticity or evidential support.

## Decision

- Represent compensation classification and evidence verification separately: `reported_status` describes what was asserted, while `evidence_verification_state` describes whether controlled provenance checks support that assertion.
- Every public request is an unverified observation. The public schema has no trust-state or decision field and rejects unknown fields. The service sets `UNVERIFIED` itself; client metadata and model output cannot change this.
- Every unverified observation returns deterministic `REVIEW_REQUIRED` with stable reason `EVIDENCE_UNVERIFIED`, and `eligible_to_submit` is always false. Responses label values as reported and do not present unverified unpaid reports as confirmed facts.
- An opaque evidence reference or URL is metadata only. Model-generated assertions, status, amounts, confidence and decisions cannot establish verification.
- The pure domain evaluator remains deterministic and may evaluate an internally trusted `CompensationEvidence` object. No production service currently creates one. Do not add a test-only or hard-coded trust bypass to the public API.
- A future controlled source-ingestion/verifier must establish permitted source/method, retrieval and source/version provenance, retain an immutable source snapshot/hash and exact supporting text/span, validate paid status and amount/currency/period, and record verifier method/version/time before it marks evidence trusted. Source-specific permission and authenticity rules remain outstanding.
- A trusted, confirmed unpaid classification remains blocked independently of the configurable INR/year minimum. An unverified report of unpaid remains review-required and cannot proceed.
- Migration `0002_compensation_evidence_trust_state` adds a constrained state with `UNVERIFIED` server default/backfill. Existing assessment facts and threshold snapshots remain intact; the effective API view treats legacy assessments as unverified and suppresses old normalized values/conversion assumptions. Stored legacy outcomes remain historical database data and are not exposed as authoritative API results.

## Rationale and alternatives

Failing closed is necessary because no current component can prove compensation source provenance. It preserves the configurable threshold policy, independently preserves the unpaid gate for trusted classifications, and prevents an arbitrary public assertion from manufacturing eligibility.

Rejected alternatives:

- Trust the caller-provided status, URL or reference: none proves the source was retrieved or supports the amount.
- Trust model-generated status/decision: model output is untrusted and cannot validate its own provenance.
- Add a hard-coded trusted source or fake verifier: it would create false assurance without retrieval, permission, content validation or durable evidence.
- Remove the pure evaluator: it remains useful for deterministic policy tests and future internal, provenance-backed inputs.

## Consequences and migration implications

- The current public compensation API can store observations but cannot produce a verified threshold pass. Review is required for every public assessment until a real verifier exists.
- Public request-validation failures use a generic stable error without echoing salary/reference values.
- Legacy assessments acquire `UNVERIFIED` by migration default. Their facts, threshold snapshots and stored outcomes are retained; the effective API decision is review-required, not the prior outcome.
- Future ingestion must use a controlled internal boundary and source-specific policy review. Adding a trusted-state enum is not itself evidence verification.
- No job application submission route exists, and live submissions remain disabled.

## Revisit when

Revisit when a permitted source-ingestion path is designed and tested against source-authenticity, retrieval, evidence-span, update/version, retention, concurrency and failure cases. Any implementation must preserve the public no-trust-claims rule and deterministic policy gates.
