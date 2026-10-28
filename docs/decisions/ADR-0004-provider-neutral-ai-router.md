# ADR-0004 — Use a Provider-Neutral AI Router with Privacy and Budget Gates

- **Status:** Proposed
- **Date:** 2026-10-27

## Context

The product may use multiple provider APIs and optionally local models. Model availability, rate limits, free-tier quotas, pricing and data-use terms vary and change. Domain logic should not be tied to a single SDK or silently switch to a more expensive/private-data-incompatible provider.

## Decision

Define typed task contracts and provider adapters behind a router. Select a model based on task quality, output schema support, privacy classification, quota state, latency and budget. Paid fallbacks remain disabled until explicitly authorized. Log exact model/task/version and fallback reason.

## Consequences

**Positive:** provider changes and evaluations are easier to manage; privacy/cost checks are centralized.  
**Negative:** adapter and evaluation maintenance add code; a router must not become an unbounded agent framework.

## Required controls

- Per-task model candidates and output schemas.
- Per-provider rate limits/quota-aware handling.
- Explicit user data-sharing preference.
- No secrets in model context.
- No account/key rotation to evade limits.
- Pinned evaluation config and rollback path.
