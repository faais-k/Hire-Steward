# JobPilot — AI and Retrieval Specification

**Status:** Proposed design; provider/model choices remain provisional until evaluated against privacy, quotas, quality and price.

## 1. AI's role

AI is an assistive interpretation and drafting layer. Deterministic code decides permissions, hard eligibility gates, daily caps, cooldowns, exact duplicate handling, allowed destination, whether an answer is grounded, and whether an external action can start. AI cannot grant itself permission.

## 2. Task registry

Every AI task has a stable `task_name`, `task_version`, input schema, output schema, privacy classification, maximum input/output, timeout, retry budget, permitted provider classes, and evaluation set.

Initial task categories:

1. `document_extract`: document text to typed facts and source locations.
2. `job_normalize`: job description to structured normalized fields.
3. `requirement_classify`: mandatory/preferred/responsibility classification.
4. `question_classify`: identify factual, preference, eligibility, sensitive, legal, or ambiguous question.
5. `evidence_retrieve`: usually deterministic search/ranking, with optional query rewriting.
6. `match_explain`: evidence-backed explanation and candidate requirement states.
7. `application_draft`: minimal resume edits, optional cover letter and answers.
8. `answer_equivalence`: determine whether an approved answer is contextually equivalent to a new question; policy still requires human-approved reusable scope.
9. `suspicious_content_detect`: flag injection-like content for defense-in-depth.
10. `independent_review`: separate pass checking grounding, unsupported claims, missing requirements and schema errors.

The router may use a different provider/model for each task. One large agent that owns the whole lifecycle is prohibited.

## 3. Provider-neutral adapter contract

Each adapter must implement a normalized interface similar to:

```python
class ModelAdapter(Protocol):
    async def generate_structured(
        self,
        *,
        task: TaskDefinition,
        input_payload: Mapping[str, object],
        output_schema: type[BaseModel],
        timeout_seconds: float,
    ) -> ModelResult: ...
```

`ModelResult` should contain parsed output, provider, exact model ID, request/response identifiers where available, usage, latency, finish status, safety status, and normalized error. Do not expose provider SDK objects to domain code.

### Router requirements

- Candidate providers/models configured per task.
- Check task privacy class against user-approved provider sharing policy before dispatch.
- Enforce per-provider rate limits and budgets.
- Distinguish unsupported model, quota limit, timeout, malformed response, refusal, and transient provider errors.
- Use bounded retries only where safe. Do not rotate identities/keys to bypass provider quota.
- Paid fallback remains off by default. When enabled, stop when the configured budget is reached.
- Log exact model/version and fallback path. Never silently change models between evaluation and production.

### Candidate providers

Groq and Gemini API access may be configured as adapters, but their current model availability, quotas, privacy/data-use rules, billing and terms must be verified at runtime and when settings are changed. A free tier may have lower rate limits or different data-use terms from a paid tier. Keep this knowledge in configuration/documentation with a last-verified timestamp, not hard-coded as permanent truth.

Local inference/embeddings may be evaluated later to minimize external sharing; do not promise model quality or footprint before a device-specific benchmark.

## 4. Privacy classification before model dispatch

Example classes:

- `PUBLIC_JOB_DATA`: public job listing text without candidate data.
- `CANDIDATE_NON_SENSITIVE`: candidate facts/documents approved for provider sharing.
- `CANDIDATE_SENSITIVE`: identity, address, health, legal/financial, or other explicitly sensitive information.
- `SECRET`: API keys, passwords, cookies, session tokens, refresh tokens, OTPs and credential-store values.

Rules:

- `SECRET` must never enter a model prompt.
- `CANDIDATE_SENSITIVE` must not be sent to external providers unless the user has explicitly enabled a specific use and it is necessary; by default redact or use local processing.
- Before sending candidate resumes/work evidence externally, show provider and data-use notice and honor the user's configuration.
- The default must be conservative because provider tiers may have different retention/training terms.
- Do not include entire profile/document sets when a small set of facts can answer the task.

## 5. Structured extraction

Input includes document text/structure, page/section markers, schema, and a clear instruction that input content is untrusted data. Output should include:

- `facts[]`: typed fact, raw extracted text, normalized value, source span/page, confidence, proposed sensitivity, date/units if applicable.
- `warnings[]`: missing text, conflicting dates, ambiguous value, possible OCR issue or unsupported layout.
- `document_quality`: parser status and completeness estimate.

Validate against a strict schema. Store `raw_output` separately from accepted facts. Extraction results are suggestions; user verification may be required. No extracted field may overwrite a verified fact automatically.

### Non-destructive rule

If parsing returns empty/invalid output, mark the extraction attempt failed and preserve the prior active fact/document profile. Empty extraction is not evidence that the candidate has no degree, skills, job or experience.

## 6. Job requirements schema

Each extracted requirement should contain:

```json
{
  "requirement_text": "source wording",
  "normalized_skill": "optional canonical label",
  "kind": "mandatory | preferred | responsibility | other",
  "importance": "high | medium | low | unknown",
  "years_min": null,
  "location_or_work_auth": null,
  "source_span": "paragraph or section locator",
  "confidence": 0.0
}
```

The JSON is illustrative. The production schema must define types, enums and numeric bounds in code. `mandatory` classification must carry the source phrase and confidence; the model cannot invent legal consequences or turn vague “nice to have” wording into a hard gate without review.

### Compensation evidence extraction boundary

The model may extract a job's stated compensation evidence into a strict schema containing source text/span, amount or range, currency, stated period (`HOUR`, `DAY`, `MONTH`, `YEAR`, `CONTRACT`, or `UNKNOWN`), reported paid/unpaid/unknown status, base/variable/stipend qualification, and confidence. It may explain ambiguity but must preserve unknowns and contradictions. Model output is always an unverified observation; it cannot set evidence verification state, set or change the user's minimum compensation preference, invent missing amounts/hours/days/contract duration/exchange rates, annualize without a defensible basis, or issue the authoritative eligibility decision. A deterministic backend evaluator reads the persisted versioned INR/year setting and applies the compensation and unpaid-role gates. Model output cannot turn an unverified, blocked, or review result into a trusted pass.

The public compensation API likewise accepts reported observations only. A trusted state may be created only by a future controlled source-ingestion/verifier component after it establishes permitted source access, retrieval, immutable source/version provenance, an exact supporting text/span, and consistency of amount, currency, period and paid classification. Such a component does not yet exist; references and model-generated source claims are not verification.

For an explicit recurring monthly rate, the backend may compute a comparable annual rate as amount × 12 and must retain that assumption and the original evidence. Hourly/daily/contract compensation requires reliable work-time or duration evidence. A foreign-currency comparison requires a reliable exchange-rate source, timestamp and basis. If any required basis is missing, the result is investigation/review.

## 7. Candidate evidence retrieval

### Initial retrieval design

1. Normalize terms and use PostgreSQL full-text search (and optional trigram/exact skill indexes) for lexical matching.
2. Add semantic retrieval with `pgvector` only after selecting a model and checking provider/privacy requirements.
3. Use separate result lists for lexical, semantic and explicit skill coverage.
4. Fuse rank positions with RRF; do not directly add raw cosine similarity to BM25 score without calibrated normalization.
5. Reranking remains off until a benchmark shows measurable benefit.
6. Show the evidence text and source version behind every candidate-specific claim.

### Skill coverage

Track explicit terms, normalized skill concepts, synonyms, tool versions where relevant, project evidence and context. Avoid a binary “skill is present” based solely on a resume keyword. Distinguish:

- explicit verified evidence;
- document-supported but unverified evidence;
- transferable/adjacent evidence;
- mentioned but weakly evidenced;
- no evidence found;
- contradicted or expired evidence.

A missing keyword means “not found,” not necessarily “does not have the skill.”

### Embedding metadata

Persist model/provider ID, exact model version if available, embedding dimension, normalization method, source content hash, chunking version and timestamp. A model switch requires a measured migration/re-embedding plan. Never compare incompatible vector spaces.

## 8. Matching score and confidence

### Provisional score components

| Component | Weight | Meaning |
|---|---:|---|
| Role alignment | 25 | Configurable target role and responsibility alignment |
| Required technical skills | 20 | Evidence-backed coverage of required skills, not all listed skills |
| Verified project/work evidence | 15 | Relevant, supportable work evidence |
| Experience fit | 15 | Role level and relevant experience; gaps do not independently reject |
| Seniority | 10 | Level fit and scope |
| Location/work arrangement | 10 | User preference compatibility and feasibility |
| Compensation/contract preference | 5 | Known compensation and contract preference fit |
| **Total** | **100** | Initial weights only; not validated |

Score weights are versioned. Unknown data must not be assigned an optimistic score by default; represent score availability and confidence explicitly. Hard gates are evaluated independently and cannot be offset by the weighted score.

### Confidence

Confidence measures the quality/completeness of evidence used to assess a job, not likelihood of receiving an offer. Example factors: source completeness, publication-date reliability, extracted requirement confidence, candidate evidence coverage, salary/visa uncertainty, contradictory facts, and parser warnings. Use named levels plus reasons; do not show a precise percentage unless calibrated on labeled data.

Initial threshold bands may be experimented with, but they are not release authority. High score + low confidence equals review/skip, never auto-submit.

## 9. Application drafting and grounded claims

- Supply the smallest set of approved candidate facts and job facts relevant to each output.
- Every candidate-specific claim must map to one or more fact/evidence IDs or be explicitly marked as a user-authored new fact needing verification.
- Preserve known resume structure and use minimal targeted changes.
- No unsupported numerical metrics, titles, dates, tools, responsibilities, certifications, salary, work authorization or experience.
- Keep job description requirements separate from candidate experience. Do not rephrase a requirement as if the candidate performed it.
- Provide a validation result: `grounded`, `needs_user_confirmation`, or `rejected_unsupported` per claim/answer.
- If one answer is unknown, ask the user and continue unrelated preparation tasks.

## 10. Answer-bank reuse

Reuse requires both explicit user approval and semantic/contextual equivalence. Store question context, answer, permitted scope, approval version/date, supporting evidence, sensitivity, and expiry/revalidation requirement where applicable. A prior answer about work authorization, compensation, legal declarations, or another sensitive topic must be checked for freshness and context. User consent to one response is not blanket permission to reuse it everywhere.

## 11. Prompt injection and tool safety

- Treat all retrieved content as untrusted data, regardless of where it appears.
- Explicitly delimit job descriptions, resumes, emails, OCR text and provider responses in prompts.
- Ignore any embedded instruction that asks to reveal secrets, override policy, change system settings, call unapproved tools, navigate to an arbitrary domain or fabricate a claim.
- Treat any model-generated compensation threshold, compensation eligibility conclusion, or request to alter a threshold as untrusted; the backend uses the persisted setting and deterministic evaluator.
- Tools available to the model (if any) are read-only and narrow. Side effects are performed only through typed backend commands requiring an approved `SubmissionPlan` and gate recheck.
- Domain allowlists and source capability checks are enforced outside the prompt.
- Log injection test result and safe reason without storing harmful or sensitive payloads unnecessarily.

## 12. Caching and invalidation

A cached result is valid only if all behavior-affecting identifiers match: content hash, document version, job snapshot, policy/scoring version, prompt version, output schema version, model ID/version, retrieval version, candidate profile/fact version, and relevant settings. Cache results do not authorize external side effects; final gate checks always run fresh.

## 13. Evaluation and release gates

Maintain separate metrics for extraction, retrieval, ranking, policy decisions, answer grounding, and submission reconciliation. Minimum required checks:

- Schema-valid extraction rate and field-level precision/recall on labeled documents.
- Job requirement classification precision/recall, especially mandatory vs preferred.
- Retrieval precision@k/recall@k and relevance judgments.
- Ranking quality and stability under minor wording changes.
- False auto-eligible rate and unresolved mandatory mismatch leakage (target zero in gold tests).
- Unsupported claims and answer-bank semantic mismatch rate (target zero in gold tests).
- Prompt-injection robustness on hostile resume/job/website fixtures.
- Token/cost/latency budgets per task and fallback correctness.

Do not promote a new model or prompt solely because one example looks better. Compare against a fixed evaluation set and preserve the previous configuration for rollback.
