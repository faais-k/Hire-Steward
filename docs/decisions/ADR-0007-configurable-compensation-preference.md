# ADR-0007 — Configurable Annual Compensation Preference

- **Status:** Accepted owner policy; preference backend implemented; trusted evidence provenance and broader workflow integration pending
- **Date:** 2026-10-28
- **Supersedes:** ADR-0006
- **Decision source:** Current owner instruction in the JobPilot documentation correction request

## Context

The prior decision treated INR 100,000/year as a non-overridable minimum. The owner has now decided that INR 100,000/year is the default preference, not an immutable floor. The user must be able to set a different minimum through application settings, including zero. The independent rule against applying to unpaid roles must remain effective at every setting. Compensation evidence is often absent, ranged, expressed in different units/currencies, or ambiguous, so incorrect normalization could create false eligibility.

## Decision

- Persist a versioned `minimum_compensation` setting in user/application settings. The default is INR 100,000 per year, shown as **Minimum annual compensation (INR per year)**.
- Accept any finite, non-negative monetary amount, including zero. Reject malformed, negative, NaN, infinite and otherwise invalid values. Use exact decimal or integer-minor-unit arithmetic for decisions, never binary floating point.
- Keep the prohibition on applying to unpaid work as an independent, unconditional policy gate. A zero preference does not make unpaid work eligible.
- Evidence verification is governed separately by ADR-0009. Caller- or model-reported compensation remains unverified until a controlled source-ingestion/verifier establishes provenance; no such production path currently exists.
- Evaluate compensation deterministically in the backend using the persisted setting. Reliably established annual compensation below the setting fails the compensation gate; an amount at or above it passes this gate only. A score or model output cannot change the setting or override the result.
- Unknown or contradictory compensation, unsupported normalization, or a range that crosses the setting requires investigation/review unless reliable additional evidence resolves the uncertainty. A range wholly below fails this gate; a range whose lower bound meets/exceeds the setting passes this gate only.
- Normalize monthly, annual, hourly, daily, weekly, stipend, commission and contract compensation only with a defensible, recorded basis. An explicit recurring monthly rate may be annualized as amount × 12, with that assumption and original source evidence retained. Do not invent hours, work days, contract duration or exchange rates. Non-INR compensation requires a reliable exchange rate plus source, timestamp and basis; otherwise review.
- Apply one deterministic evaluator consistently during matching/eligibility, dashboard explanations, scheduled reassessment, application preparation and the final submission gate. Frontend validation is informative only. AI may extract and explain evidence, but cannot alter the setting or authoritative eligibility result.
- Audit intentional setting changes with previous/new amount, currency, period, timestamp, actor and settings version. Do not include unrelated sensitive information.
- Snapshot the threshold amount, currency, annualized unit and applicable conversion assumptions for every assessment and policy evaluation. New settings affect future/recomputed decisions. Do not silently rewrite previous assessments or the recorded facts, answers or outcomes of submitted applications.

## Rationale and alternatives

The configurable preference follows the owner's current choice while retaining a separate hard prohibition for unpaid work and deterministic, evidence-based safeguards. Keeping the preference in persisted settings makes the visible choice authoritative for backend workflows and allows historical assessments to remain explainable.

Alternatives considered:

- Retain a non-overridable INR 100,000 minimum: rejected because the owner explicitly changed that policy.
- Read a fixed threshold only from an environment variable: rejected because the user must be able to change it through application settings and past assessments need versioned values.
- Store a threshold in arbitrary currencies: rejected for the initial contract. The user preference is INR/year; foreign compensation may be compared only with a documented, reliable exchange rate.
- Let AI infer annual pay or decide eligibility: rejected because missing hours, duration, exchange rates and policy results require deterministic validation and explicit uncertainty.

## Migration and implementation implications

- Add the versioned setting with INR 100,000/year as the default for new profiles.
- Preserve a valid existing user-configured value when migrating; do not silently clamp it. If legacy input is invalid, surface a validation/review state instead of inventing a replacement.
- Add an audit event for preference changes and immutable threshold/conversion snapshots to job assessments and policy evaluations. Submission attempts must retain the linked policy evaluation.
- Historical assessments without a recorded threshold cannot be retroactively assigned one; preserve them with provenance marked incomplete. Reassess against the current setting before any future consequential action.
- A setting update does not rewrite already-submitted application facts, answers or outcomes.
- Add and pass the compensation acceptance cases in `testing-evaluation.md` before the corresponding policy phase is considered complete or any submission path is enabled.

## Revisit when

Revisit only if the owner changes the policy, evidence from implementation identifies a conversion/validation gap, or evaluation demonstrates inconsistent deterministic decisions. Any change must retain the unpaid-role prohibition unless the owner explicitly changes that separate policy.
