# ADR-0006 — Historical Decision: Non-Overridable Compensation Floor

- **Status:** Superseded on 2026-10-28 by [ADR-0007](ADR-0007-configurable-compensation-preference.md)
- **Decision date:** 2026-10-28
- **Decision source:** Earlier 2026-10-28 owner instruction

## Context at the time

The earlier PRD described INR 100,000 as a default floor whose value could be changed. The then-current owner instruction was interpreted to mean that known annualized compensation below INR 100,000 must block application, and that a user could only raise the value.

## Superseded decision

At that time, the decision was:

- INR 100,000 annualized was treated as a hard minimum safety floor.
- The user could set a higher floor, but no UI, API, import, model output, or configuration could lower it.
- Unpaid work was always blocked.
- Unknown compensation and ranges crossing the floor required review.
- Annualization had to preserve source amount, currency, period and assumptions; unknown hours/duration could not be invented.

This is retained as decision history only. It is not the current policy and must not be used as an active implementation requirement. The owner's later decision makes INR 100,000/year the configurable default; see ADR-0007. The independent prohibition on applying to unpaid roles remains active.

## Historical consequences

The original proposed tests covered attempts to lower the floor, unpaid roles, confirmed below-floor amounts, unknown values and crossing ranges. Those test ideas are superseded by the more complete configurable-setting acceptance criteria in ADR-0007 and `testing-evaluation.md`. No implementation or tests were completed under this ADR.
