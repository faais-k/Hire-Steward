# JobPilot — Visual Design System

**Status:** Proposed design baseline for a productivity-focused, trustworthy, desktop-first web app.

## 1. Design intent

JobPilot should feel like a calm professional workbench, not a flashy AI demo or a sales dashboard. The interface should put the user's evidence, decisions, and next actions first. It should be information-dense without being cramped, visually quiet, and explicit about the difference between successful, uncertain, blocked, and pending work.

### Experience principles

1. **Explain before acting:** scores and gates have readable reasons.
2. **Status is never color-only:** label, icon and text accompany color.
3. **Uncertainty is visible:** use “Unknown” or “Needs review,” never a green pass for missing information.
4. **Dangerous actions are visually and behaviorally distinct:** review, approve, submit and delete cannot be confused.
5. **Evidence is close to claims:** users can inspect the source excerpt/fact behind a generated answer.
6. **Progressive disclosure:** the default screen shows key facts; diagnostics and raw provider details are available without overwhelming every view.
7. **Accessible at normal zoom and keyboard-only:** avoid tiny grey text, low-contrast borders, and hover-only controls.

## 2. Color system

Use semantic tokens rather than scattered color values. Proposed hex values are initial design decisions and must be contrast-tested across actual components. Dark theme can be implemented after the light theme's information hierarchy is stable.

### Light theme

| Token | Value | Use |
|---|---|---|
| `--jp-bg` | `#F6F8FB` | App canvas |
| `--jp-surface` | `#FFFFFF` | Main panels and cards |
| `--jp-surface-muted` | `#EEF2F7` | Subtle secondary surfaces |
| `--jp-text` | `#172033` | Primary text |
| `--jp-text-muted` | `#566176` | Secondary text; check contrast |
| `--jp-border` | `#D8DFE9` | Dividers and control borders |
| `--jp-primary` | `#2357D9` | Primary navigation/action accent |
| `--jp-primary-hover` | `#1947B8` | Hover/focus treatment |
| `--jp-primary-soft` | `#E8EEFF` | Selected states and quiet highlights |
| `--jp-success` | `#177245` | Confirmed success only |
| `--jp-success-soft` | `#E8F6EE` | Success background |
| `--jp-warning` | `#8A5200` | Needs attention / review |
| `--jp-warning-soft` | `#FFF4D6` | Warning background |
| `--jp-danger` | `#B42332` | Blocking error / destructive action |
| `--jp-danger-soft` | `#FDECEE` | Error background |
| `--jp-info` | `#245EA8` | Informational state |
| `--jp-info-soft` | `#EAF3FF` | Informational background |
| `--jp-focus` | `#111827` | Strong focus outline or dedicated high-contrast focus token |

Do not apply green to high matching scores that still have unresolved policy gates. “Match,” “eligibility,” “confidence,” and “submission status” are separate semantics and need separate labels.

### Dark theme

Add only after the light theme is accepted. Define a complete alternate semantic palette; do not invert colors mechanically. Test code/description readability, form focus, charts, warning/danger states and text contrast. Respect `prefers-color-scheme` but provide a user override.

## 3. Typography

### Font family

Preferred system stack for reliable local performance and no remote font dependency:

```css
font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
  "Segoe UI", sans-serif;
```

If Inter is included in the application, verify its license and ship only the required weights. A system stack is acceptable for the MVP. Use a monospace stack only for IDs, timestamps in diagnostic views, structured JSON and code.

### Type scale

| Token | Size / line height | Intended use |
|---|---|---|
| `--jp-type-xs` | 12px / 16px | Compact metadata; not essential instructions |
| `--jp-type-sm` | 14px / 20px | Secondary text and dense table cells |
| `--jp-type-md` | 16px / 24px | Default body and form text |
| `--jp-type-lg` | 18px / 28px | Subsection lead, card title |
| `--jp-type-xl` | 22px / 30px | Page section heading |
| `--jp-type-2xl` | 28px / 36px | Page title |
| `--jp-type-3xl` | 34px / 42px | Sparse dashboard headline only |

Use semibold weight for headings, regular for body, and medium/semibold for labels. Avoid large text on dense data tables. Do not use font size alone to communicate status.

## 4. Spacing, radius, layout

Use a 4px base spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64px. Prefer consistent spacing tokens over per-component arbitrary values.

- Page horizontal padding: 24px desktop; 16px tablet; 12px compact mobile.
- Page max width: approximately 1440px for dense workspace views; allow tables to use full available width.
- Card padding: 16–24px depending on content density.
- Border radius: 6px for controls, 8px for cards, 12px for major panels; avoid excessive pill shapes.
- Border width: 1px default; thicker outlines reserved for focus/selection.
- Sidebar: 232–256px expanded; collapsible; compact navigation labels must remain available to assistive technologies.
- Top header: 56–64px; show current run state and user-configured environment clearly.
- Use sticky headers only when they help table navigation; avoid nested scroll traps.

## 5. Information architecture and screen layout

### Primary navigation

1. **Overview** — run status, new matches, waiting-on-user queue, source health, recent outcomes.
2. **Jobs** — discovered jobs, filters, score/confidence, policy status and source metadata.
3. **Evidence** — candidate documents, verified facts, contradictory/uncertain facts and version history.
4. **Applications** — workflow state, planned/submitted documents, exact answers, confirmation and timeline.
5. **Answer bank** — approved reusable answers and their scope/consent status.
6. **Runs & sources** — schedules, source checkpoints, last success, error state and rate limits.
7. **AI usage** — provider/model, task, tokens, latency, error/fallback and estimated/actual costs.
8. **Settings** — targeting, policy thresholds, schedules, integrations, privacy, export/import and retention.

### Overview page

Top row: current system state, last scheduled run, next run time, and a safe stop/pause control. Main content: new relevant jobs, waiting for user, applications with uncertain outcomes, source failures and recent activity. Keep system health distinct from job-match quality.

### Job list

Each row/card must show role, company, location/work arrangement, published date or clearly labeled observed date, salary if known and its period, match score, confidence, gate state and a short reason. Include sort/filter by score, recency, status, source, confidence, sponsorship and compensation. Do not hide hard-block explanations behind a tooltip.

When compensation affects a gate, show the source amount/range, currency and stated period, the minimum used (labeled INR/year), the gate result, and any conversion assumption or unresolved evidence. Keep `unknown`, `review`, and `blocked` visibly distinct. An assessment made under an earlier setting must display its historical threshold and assessment time; current settings must not be presented as if they were used for that earlier decision.

### Job detail

Three clear sections:

- **Opportunity:** normalized job facts and the raw source link.
- **Match analysis:** matched, missing, unknown and conflicting requirements with linked evidence.
- **Application preview:** resume, cover letter, exact answers, missing fields, consent, legal declarations and submit readiness.

### Application timeline

Use an event timeline for discovered, evaluated, prepared, approved, submit attempted, confirmation, reconciliation, follow-up. Every event includes timestamp, actor (`system`, `user`, or approved integration), transition reason and references. Do not expose unredacted internal prompts by default.

## 6. Component conventions

The Settings page exposes **Minimum annual compensation (INR per year)** with a default of INR 100,000/year. Explain that the user may configure a finite non-negative amount, including zero, while unpaid jobs remain ineligible regardless of the value. Validation errors must identify the invalid field. Explain conversion assumptions wherever a non-annual or non-INR salary is compared. The backend's deterministic result is authoritative; AI explanations are supporting text only.

- Buttons: primary for one main action per view; secondary for alternatives; destructive style only for delete/stop/irreversible action.
- “Submit application” action should display the target company/role, destination/source, exact attached documents and any irreversible consequence before execution.
- Use icon + text for statuses; avoid icons without accessible names.
- Badge palette should be neutral by default. Reserve saturated green/red/orange for meaningful outcome states.
- Tooltips are supplemental, not the only place a rule is explained.
- Empty states should describe the next useful step and whether no results means no matches, a source failure, or a filter issue.
- Error panels should give a safe explanation, correlation ID and retry/manual next step where appropriate.
- Confirm dialogs should summarize impact and offer a cancel path; no generic “Are you sure?” without context.

## 7. Status vocabulary

| Status | Meaning | Recommended treatment |
|---|---|---|
| `DISCOVERED` | Job imported but not fully assessed | Neutral |
| `REVIEW_REQUIRED` | User decision or missing fact needed | Amber + explicit text |
| `ELIGIBLE` | Deterministic gates passed; does not imply submission approved | Blue/neutral |
| `PREPARING` | Application material is being prepared | Neutral progress |
| `READY_TO_SUBMIT` | All pre-submit checks passed; explicit mode/consent still applies | Strong neutral/blue |
| `SUBMITTING` | External action is in progress | Progress indicator; prevent duplicate click |
| `CONFIRMATION_UNKNOWN` | External outcome could not be established | Amber; clear instruction to reconcile |
| `APPLIED` | External confirmation evidence captured | Green + evidence link/reference |
| `BLOCKED` | A policy gate failed | Red or neutral warning according to severity; reason shown |
| `FAILED_RETRYABLE` | A safe transient failure occurred | Amber/info with bounded retry action |
| `MANUAL_ACTION_REQUIRED` | Site, CAPTCHA, or user decision requires handoff | Blue/amber; preserve context |
| `SKIPPED` | User or policy chose not to pursue | Neutral; retain reason |

Avoid labeling a job “rejected” when it was only not discovered, not assessed, or failed a technical import.

## 8. Accessibility and responsive behavior

- Aim for WCAG 2.2 AA contrast and keyboard operation; validate actual color pairs with automated and manual checks.
- Every form control has a visible label, instructions where needed, and inline errors connected semantically.
- Keyboard focus is visible and not obscured by sticky headers/sidebars.
- Tables have accessible headings and are usable at 200% zoom; provide responsive card/table alternatives where appropriate.
- Do not use motion to communicate status alone; respect reduced-motion preferences.
- On narrow screens, prioritize viewing/reviewing and manual actions. Complex comparison tables may scroll horizontally with a clear affordance.

## 9. Charts and metrics

Use charts only when they clarify a trend: discovered jobs by day, source success rate, applications by state, model usage/cost over time. Every chart needs a title, date range, units, accessible text alternative and empty/error state. Never graph the match score as if it were a probability of receiving an offer unless a calibrated statistical model supports that interpretation.

## 10. Content style

Use short descriptive labels: “Needs sponsorship check,” “Missing required evidence,” “Submission outcome unknown,” “Salary not disclosed.” Avoid hype terms such as “perfect match,” “guaranteed fit,” or “AI-approved.” Explain what the app knows, what it inferred, and what still needs confirmation.
