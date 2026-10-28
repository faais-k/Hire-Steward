# ADR-0005 — Keep Targeting Configurable and Hard Safety Gates Deterministic

- **Status:** Accepted for policy direction; implementation pending
- **Date:** 2026-10-27

## Context

The user wants profile and job targeting to be configurable rather than hard-coded for one title. A model-generated score must not override policy conditions such as unsupported answers, duplicate submission, unpaid work, below-preference compensation, unknown mandatory requirements, or legal commitments. The owner has specifically set the compensation preference to default at INR 100,000/year and remain user-configurable; see ADR-0007.

## Decision

Store targeting preferences, including the minimum-compensation preference, as versioned settings. Use deterministic backend policy code for high-impact decisions. Keep the unpaid-role prohibition independent of the configurable threshold. Keep score, confidence, evidence quality, eligibility and final submission authorization distinct. The compensation preference's exact default, validation, conversion and history rules are defined in ADR-0007.

## Consequences

**Positive:** user preferences can evolve; policy remains testable; scores are explainable.  
**Negative:** more explicit states and UI explanations are required; the team must maintain policy tests when settings/logic change.

## Conditions

- User settings cannot override platform access permissions, truthful representation or secret-handling rules.
- User settings cannot override source permissions, truthful representation, the unpaid-role prohibition, secret-handling rules, or other hard safety gates.
- A human can decide to pursue a role despite a mismatch, but cannot submit false answers.
- Score thresholds remain provisional until evaluated on labeled cases.
