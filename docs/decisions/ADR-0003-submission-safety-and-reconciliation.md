# ADR-0003 — Treat External Submission as a Non-Idempotent Side Effect

- **Status:** Proposed
- **Date:** 2026-10-27

## Context

An ATS may accept a job application even if the client times out or crashes before receiving confirmation. A naive retry can create duplicates. Some sources provide stable IDs/status lookups; others do not.

## Decision

Before a submission, persist an immutable submission plan and attempt ID. Allow one active submission at a time initially. If the outcome cannot be established, transition to `CONFIRMATION_UNKNOWN` and reconcile using a permitted authoritative signal or explicit user review. Retry only after proving the earlier attempt did not succeed and re-running all gates.

## Consequences

**Positive:** minimizes duplicate applications, preserves auditability, and explicitly handles the distributed-systems uncertainty.  
**Negative:** a few applications may remain paused for manual reconciliation; automatic exactly-once behavior cannot be promised for arbitrary websites.

## Required tests

- Crash before external request.
- Remote acceptance plus local timeout.
- Browser crash after click.
- Confirmation page unavailable or ambiguous.
- Concurrent request/double-click.
- Reconciliation finds prior success.
- Reconciliation proves no prior submission and safely allows a new attempt.
