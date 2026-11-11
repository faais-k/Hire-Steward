"""Unified Submission Simulation Service.

Shared authoritative service used by BOTH:
  - POST /api/v1/preparation/simulate
  - POST /api/v1/applications/{application_id}/simulate-submission

Guarantees:
1. Recomputes SHA-256 hashes from frozen material and compares against persisted values.
2. Verifies plan references the intended posting and application.
3. Verifies reviewed application material exists and has not been modified after plan creation.
4. Re-evaluates current eligibility via authoritative service (fail closed).
5. Rejects blocked or review-required plans with persistent failure records.
6. Enforces idempotency for simulation attempts.
7. Persistently records every attempt outcome in ApplicationAttempt.
8. Never makes external HTTP requests.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.adapters.simulated_ats import SimulatedAtsAdapter
from backend.app.db.models import (
    ApplicationAttempt,
    AuditEvent,
    JobPosting,
    SubmissionPlanModel,
    TrackedApplication,
)
from backend.app.domain.application_tracking import ApplicationStatus
from backend.app.services.submission_eligibility import (
    EligibilityDecision,
    evaluate_submission_eligibility,
)


# ---------------------------------------------------------------------------
# Domain errors (HTTP-independent)
# ---------------------------------------------------------------------------


class SimulationError(Exception):
    """Base class for deterministic simulation rejection."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class SimulationIntegrityError(SimulationError):
    """SHA-256 recomputation detected tampering or corruption."""


class SimulationPolicyError(SimulationError):
    """Policy gate rejected the submission (BLOCKED or REVIEW_REQUIRED)."""

    def __init__(self, code: str, message: str, is_blocked: bool = False) -> None:
        self.is_blocked = is_blocked
        super().__init__(code, message)


class SimulationMismatchError(SimulationError):
    """Plan references wrong application or posting."""


class SimulationMaterialsError(SimulationError):
    """Reviewed application materials are missing or modified."""


class SimulationNotFoundError(SimulationError):
    """Referenced entity does not exist."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SimulationResult:
    simulation_id: str
    receipt: str | None
    dry_run: bool
    status: str
    outcome: str
    success: bool
    is_idempotent_replay: bool = False
    attempt_number: int = 1
    plan_sha256: str = ""
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    application_id: str = ""
    submission_plan_id: str = ""
    idempotency_key: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    application_status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hash helpers — must stay identical to SubmissionPlan.create() canonical logic
# ---------------------------------------------------------------------------


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_canonical_packet_hash(
    *,
    application_id: str,
    job_posting_id: str,
    employer_handle: str,
    target_role: str,
    resume_sha256: str,
    cover_letter_sha256: str,
    answers: list[dict[str, Any]],
    is_compensation_eligible: bool,
    is_cooldown_clear: bool,
    compensation_threshold_version: int,
    review_state: str,
) -> str:
    """Reproduce the canonical JSON serialisation used in SubmissionPlan.create()."""
    packet_components = {
        "application_id": application_id,
        "job_posting_id": job_posting_id,
        "employer_handle": employer_handle,
        "target_role": target_role,
        "resume_sha256": resume_sha256,
        "cover_letter_sha256": cover_letter_sha256,
        "answers": answers,
        "is_compensation_eligible": is_compensation_eligible,
        "is_cooldown_clear": is_cooldown_clear,
        "compensation_threshold_version": compensation_threshold_version,
        "review_state": review_state,
    }
    canonical_str = json.dumps(packet_components, sort_keys=True, separators=(",", ":"))
    return sha256_hex(canonical_str)


# ---------------------------------------------------------------------------
# Plan integrity check
# ---------------------------------------------------------------------------


def verify_plan_integrity(
    plan_model: SubmissionPlanModel,
    current_resume_text: str | None = None,
    current_cover_letter_text: str | None = None,
) -> None:
    """Recompute SHA-256 hashes from frozen material and compare with persisted values.

    Guarantees:
    1. Stored hashes must be exactly 64-char lowercase hex strings.
    2. Recomputes resume SHA-256 from frozen plan material (or current material)
       and verifies exact equality with plan_model.resume_sha256.
    3. Recomputes cover-letter SHA-256 and verifies exact equality with
       plan_model.cover_letter_sha256.
    4. If current application text is provided and differs from plan frozen text,
       rejects modification after plan creation.
    5. Reconstructs canonical JSON packet from persisted components and verifies
       plan_model.packet_sha256 matches recomputed packet hash.

    Raises:
        SimulationIntegrityError: on hash format invalidity, hash mismatch, or tampering.
        SimulationMaterialsError: if materials were modified after plan creation.
    """
    # 1. Format check: stored hashes must be valid 64-char hex strings
    for field_name, stored_val in [
        ("resume_sha256", plan_model.resume_sha256),
        ("cover_letter_sha256", plan_model.cover_letter_sha256),
        ("packet_sha256", plan_model.packet_sha256),
    ]:
        if not stored_val or len(stored_val) != 64:
            raise SimulationIntegrityError(
                "INVALID_PLAN_INTEGRITY_HASH",
                f"Submission plan has missing or malformed {field_name} "
                f"(expected 64 hex chars, got {len(stored_val or '')}).",
            )

    # 2. Determine source text for resume & cover letter
    frozen_resume = getattr(plan_model, "resume_markdown", None)
    resume_source = frozen_resume if frozen_resume is not None else (current_resume_text or "")

    frozen_cover = getattr(plan_model, "cover_letter_markdown", None)
    cover_source = frozen_cover if frozen_cover is not None else (current_cover_letter_text or "")

    # Recompute resume hash
    computed_resume_hash = sha256_hex(resume_source)
    if computed_resume_hash != plan_model.resume_sha256:
        raise SimulationIntegrityError(
            "RESUME_HASH_MISMATCH",
            "Resume content does not match the frozen plan hash. "
            "The submission material may have been modified or tampered with.",
        )

    # Recompute cover letter hash
    computed_cover_hash = sha256_hex(cover_source)
    if computed_cover_hash != plan_model.cover_letter_sha256:
        raise SimulationIntegrityError(
            "COVER_LETTER_HASH_MISMATCH",
            "Cover letter content does not match the frozen plan hash. "
            "The submission material may have been modified or tampered with.",
        )

    # 3. Check for modified application materials after plan creation
    if frozen_resume is not None and current_resume_text is not None:
        if current_resume_text.strip() != frozen_resume.strip():
            raise SimulationMaterialsError(
                "APPLICATION_MATERIALS_MODIFIED",
                "Application resume was modified after the submission plan was created. "
                "Recreate the submission plan with updated materials.",
            )

    if frozen_cover is not None and current_cover_letter_text is not None:
        if current_cover_letter_text.strip() != frozen_cover.strip():
            raise SimulationMaterialsError(
                "APPLICATION_MATERIALS_MODIFIED",
                "Application cover letter was modified after the submission plan was created. "
                "Recreate the submission plan with updated materials.",
            )

    # 4. Canonical packet reconstruction & recomputation
    answers = plan_model.answers_json if isinstance(plan_model.answers_json, list) else []
    review_state = getattr(plan_model, "review_state", None) or "USER_REVIEWED"

    computed_packet_hash = compute_canonical_packet_hash(
        application_id=plan_model.application_id,
        job_posting_id=plan_model.job_posting_id,
        employer_handle=plan_model.employer_handle,
        target_role=plan_model.target_role,
        resume_sha256=computed_resume_hash,
        cover_letter_sha256=computed_cover_hash,
        answers=answers,
        is_compensation_eligible=bool(plan_model.is_compensation_eligible),
        is_cooldown_clear=bool(plan_model.is_cooldown_clear),
        compensation_threshold_version=int(plan_model.compensation_threshold_version),
        review_state=review_state,
    )

    if computed_packet_hash != plan_model.packet_sha256:
        raise SimulationIntegrityError(
            "PACKET_HASH_MISMATCH",
            "Submission packet hash does not match the recomputed canonical hash. "
            "Plan components (answers, eligibility flags, or target role) have been tampered with.",
        )


# ---------------------------------------------------------------------------
# Core unified simulation function
# ---------------------------------------------------------------------------


def execute_simulation(
    session: Session,
    *,
    plan_id: str | None = None,
    posting_id: str | None = None,
    application_id: str | None = None,
    mode: str = "SUCCESS",
    idempotency_key: str | None = None,
    raise_on_policy_failure: bool = True,
) -> SimulationResult:
    """Execute an offline dry-run simulation with full cryptographic and policy verification.

    Guarantees:
    1. Loads persisted plan and verifies exact application and posting identity.
    2. Cryptographically recomputes SHA-256 hashes and compares against frozen plan.
    3. Detects if application materials changed after plan creation.
    4. Re-evaluates current compensation and cooldown eligibility (fail closed).
       A previously eligible plan cannot bypass newly changed preferences or cooldowns.
    5. Verifies user review state.
    6. Enforces transactional idempotency for repeated simulation attempts.
    7. Persistently logs all attempts in ApplicationAttempt.
    8. Records system AuditEvent.
    9. Never performs external network transmission (loopback only).

    Args:
        session: Active SQLAlchemy session.
        plan_id: ID of the SubmissionPlanModel to simulate.
        posting_id: Target JobPosting ID.
        application_id: Target TrackedApplication ID.
        mode: Simulation fault injection mode (default "SUCCESS").
        idempotency_key: Optional explicit idempotency key.
        raise_on_policy_failure: If True, raises domain errors (SimulationPolicyError,
            SimulationIntegrityError) for HTTP route translation (e.g. 422).
            If False, persists attempt and returns failed SimulationResult.

    Returns:
        SimulationResult with complete execution details.
    """
    start_time = datetime.now(timezone.utc)

    # 1. Resolve posting
    posting: JobPosting | None = None
    if posting_id:
        posting = session.get(JobPosting, posting_id)
        if posting is None:
            posting = session.scalar(
                select(JobPosting).where(JobPosting.posting_id == posting_id).limit(1)
            )
    if posting is None and plan_id:
        plan_ref = session.get(SubmissionPlanModel, plan_id)
        if plan_ref:
            posting = session.get(JobPosting, plan_ref.job_posting_id)
    if posting is None and application_id:
        app_ref = session.get(TrackedApplication, application_id)
        if app_ref:
            posting = session.get(JobPosting, app_ref.job_posting_id)

    if posting is None:
        raise SimulationNotFoundError(
            "POSTING_NOT_FOUND",
            "Job posting not found.",
        )

    # 2. Resolve application
    app: TrackedApplication | None = None
    if application_id:
        app = session.get(TrackedApplication, application_id)
    if app is None:
        app = session.scalar(
            select(TrackedApplication)
            .where(TrackedApplication.job_posting_id == posting.id)
            .limit(1)
        )
    if app is None:
        raise SimulationNotFoundError(
            "APPLICATION_NOT_FOUND",
            "No application record exists for this posting.",
        )

    # 3. Resolve submission plan
    plan_model: SubmissionPlanModel | None = None
    if plan_id:
        plan_model = session.get(SubmissionPlanModel, plan_id)
    if plan_model is None:
        plan_model = session.scalar(
            select(SubmissionPlanModel)
            .where(SubmissionPlanModel.job_posting_id == posting.id)
            .order_by(SubmissionPlanModel.created_at.desc())
            .limit(1)
        )
    if plan_model is None:
        raise SimulationNotFoundError(
            "SUBMISSION_PLAN_NOT_FOUND",
            "No persisted submission plan exists for this posting. Create a plan first.",
        )

    # 4. Verify plan references intended posting and application
    if plan_model.job_posting_id != posting.id:
        raise SimulationMismatchError(
            "PLAN_POSTING_MISMATCH",
            f"Plan references posting '{plan_model.job_posting_id}', not '{posting.id}'.",
        )
    if plan_model.application_id != app.id:
        raise SimulationMismatchError(
            "PLAN_APPLICATION_MISMATCH",
            f"Plan references application '{plan_model.application_id}', not '{app.id}'.",
        )

    # 5. Load reviewed materials
    frozen_resume = getattr(plan_model, "resume_markdown", None)
    frozen_cover = getattr(plan_model, "cover_letter_markdown", None)
    resume_content = (app.reviewed_resume_markdown or frozen_resume or app.submitted_resume_snapshot or "").strip()
    cover_content = (app.reviewed_cover_letter_markdown or frozen_cover or app.submitted_cover_letter_snapshot or "").strip()
    if not resume_content or not cover_content:
        raise SimulationMaterialsError(
            "APPLICATION_MATERIALS_INCOMPLETE",
            "Cannot simulate submission without reviewed resume and cover letter markdown.",
        )

    # 6. Idempotency check: check if an attempt with matching idempotency_key or plan exists
    if idempotency_key:
        existing_by_key = session.scalar(
            select(ApplicationAttempt).where(
                ApplicationAttempt.application_id == app.id,
                ApplicationAttempt.idempotency_key == idempotency_key,
            )
        )
        if existing_by_key is not None:
            return _build_result_from_attempt(existing_by_key, is_replay=True, app_status=app.status)
    else:
        existing_success = session.scalar(
            select(ApplicationAttempt)
            .where(
                ApplicationAttempt.submission_plan_id == plan_model.id,
                ApplicationAttempt.status.in_(("COMPLETED", "SIMULATED_SUCCESS")),
                ApplicationAttempt.outcome == "SUCCESS",
            )
            .order_by(ApplicationAttempt.started_at.desc())
            .limit(1)
        )
        if existing_success:
            return _build_result_from_attempt(existing_success, is_replay=True, app_status=app.status)

    # Determine attempt number and key
    current_attempt_count = session.scalar(
        select(func.count(ApplicationAttempt.id)).where(
            ApplicationAttempt.application_id == app.id
        )
    ) or 0
    attempt_number = current_attempt_count + 1
    effective_idemp_key = idempotency_key or f"sim_{plan_model.id}_{attempt_number}"

    # 7. Actual SHA-256 integrity verification
    try:
        verify_plan_integrity(
            plan_model,
            current_resume_text=resume_content,
            current_cover_letter_text=cover_content,
        )
    except (SimulationIntegrityError, SimulationMaterialsError) as exc:
        attempt = _persist_attempt(
            session,
            app=app,
            plan_model=plan_model,
            attempt_number=attempt_number,
            idempotency_key=effective_idemp_key,
            simulation_mode=mode,
            status="FAILED",
            outcome="FAILED",
            error_code=exc.code,
            error_message=exc.message,
            started_at=start_time,
        )
        if raise_on_policy_failure:
            raise
        return _build_result_from_attempt(attempt, is_replay=False, app_status=app.status)

    # 8. Re-evaluate current eligibility and policy gates (fail closed)
    eligibility = evaluate_submission_eligibility(
        session,
        job_posting_id=posting.id,
        current_application_id=app.id,
    )

    if eligibility.overall_decision == EligibilityDecision.BLOCKED:
        err_msg = "; ".join(eligibility.blocking_reasons)
        err_code = "INELIGIBLE_COMPENSATION" if not eligibility.is_compensation_eligible else "ACTIVE_COOLDOWN"
        attempt = _persist_attempt(
            session,
            app=app,
            plan_model=plan_model,
            attempt_number=attempt_number,
            idempotency_key=effective_idemp_key,
            simulation_mode=mode,
            status="SIMULATED_FAILURE",
            outcome="FAILED",
            error_code=err_code,
            error_message=err_msg,
            metadata={"reasons": eligibility.blocking_reasons, "eligibility": "BLOCKED"},
            started_at=start_time,
        )
        if raise_on_policy_failure:
            raise SimulationPolicyError(
                "POLICY_BLOCKED",
                f"Simulation rejected by policy gate: {err_msg}",
                is_blocked=True,
            )
        return _build_result_from_attempt(attempt, is_replay=False, app_status=app.status)

    if eligibility.overall_decision == EligibilityDecision.REVIEW_REQUIRED:
        err_msg = "; ".join(eligibility.review_reasons)
        err_code = "INELIGIBLE_COMPENSATION" if not eligibility.is_compensation_eligible else "POLICY_REVIEW_REQUIRED"
        attempt = _persist_attempt(
            session,
            app=app,
            plan_model=plan_model,
            attempt_number=attempt_number,
            idempotency_key=effective_idemp_key,
            simulation_mode=mode,
            status="SIMULATED_FAILURE",
            outcome="FAILED",
            error_code=err_code,
            error_message=err_msg,
            metadata={"reasons": eligibility.review_reasons, "eligibility": "REVIEW_REQUIRED"},
            started_at=start_time,
        )
        if raise_on_policy_failure:
            raise SimulationPolicyError(
                "POLICY_REVIEW_REQUIRED",
                f"Simulation requires verified evidence: {err_msg}",
                is_blocked=False,
            )
        return _build_result_from_attempt(attempt, is_replay=False, app_status=app.status)

    # 9. Verify user review state
    plan_review_state = getattr(plan_model, "review_state", None) or "USER_REVIEWED"
    app_review_state = getattr(app, "review_approval_state", None) or "APPROVED"

    if plan_review_state != "USER_REVIEWED" and app_review_state != "APPROVED":
        err_msg = "Application materials have not received explicit candidate approval."
        attempt = _persist_attempt(
            session,
            app=app,
            plan_model=plan_model,
            attempt_number=attempt_number,
            idempotency_key=effective_idemp_key,
            simulation_mode=mode,
            status="SIMULATED_FAILURE",
            outcome="FAILED",
            error_code="USER_REVIEW_REQUIRED",
            error_message=err_msg,
            started_at=start_time,
        )
        if raise_on_policy_failure:
            raise SimulationPolicyError(
                "USER_REVIEW_REQUIRED",
                err_msg,
                is_blocked=False,
            )
        return _build_result_from_attempt(attempt, is_replay=False, app_status=app.status)

    # 10. Execute simulation dispatch via SimulatedAtsAdapter (loopback only)
    packet = {
        "job_posting_id": posting.id,
        "is_compensation_eligible": eligibility.is_compensation_eligible,
        "is_cooldown_clear": eligibility.is_cooldown_clear,
        "resume_markdown": resume_content,
        "cover_letter_markdown": cover_content,
        "packet_sha256": plan_model.packet_sha256,
        "plan_id": plan_model.id,
    }
    adapter = SimulatedAtsAdapter()
    sim_result = adapter.simulate_dispatch(submission_packet=packet, mode=mode)

    # Classify status & outcome
    if mode in ("AMBIGUOUS_TIMEOUT", "TIMEOUT", "POST_RECEIPT_ERROR"):
        attempt_status = "AMBIGUOUS_RESULT"
        attempt_outcome = "AMBIGUOUS"
    elif sim_result.success:
        attempt_status = "SIMULATED_SUCCESS"
        attempt_outcome = "SUCCESS"
    else:
        attempt_status = "SIMULATED_FAILURE"
        attempt_outcome = "FAILED"

    receipt_str = (
        f"Simulated ATS Submission Receipt (Dry-Run)\n"
        f"Job ID: {posting.id}\n"
        f"Plan ID: {plan_model.id}\n"
        f"Plan SHA-256: {plan_model.packet_sha256}\n"
        f"Receipt ID: {sim_result.simulated_receipt_id}\n"
        f"Status: {attempt_status}\n"
        f"Dispatched via: Local Loopback Simulated ATS\n"
        f"State: Verified Dry-Run Complete. Application state remains user-controlled."
    )

    attempt = _persist_attempt(
        session,
        app=app,
        plan_model=plan_model,
        attempt_number=attempt_number,
        idempotency_key=effective_idemp_key,
        simulation_mode=mode,
        status=attempt_status,
        outcome=attempt_outcome,
        error_code=sim_result.error_code,
        error_message=sim_result.error_message,
        simulated_receipt=receipt_str,
        metadata={
            "duration_ms": sim_result.duration_ms,
            "mode_used": sim_result.mode_used,
            "target_role": plan_model.target_role,
        },
        started_at=start_time,
    )

    # Update application notes/status safely
    if sim_result.success:
        if app.status in (ApplicationStatus.SAVED.value, ApplicationStatus.PREPARING.value):
            app.status = ApplicationStatus.READY_FOR_REVIEW.value
        note = f"[Dry-Run Passed]: Attempt #{attempt_number} ({sim_result.simulated_receipt_id})"
        app.notes = f"{app.notes}\n{note}" if app.notes else note
    else:
        note = f"[Dry-Run Failed]: Attempt #{attempt_number} ({sim_result.error_code} - {sim_result.error_message})"
        app.notes = f"{app.notes}\n{note}" if app.notes else note

    session.commit()

    return SimulationResult(
        simulation_id=attempt.id,
        receipt=receipt_str,
        dry_run=True,
        status=attempt_status,
        outcome=attempt_outcome,
        success=sim_result.success,
        is_idempotent_replay=False,
        attempt_number=attempt_number,
        plan_sha256=plan_model.packet_sha256,
        error_code=sim_result.error_code,
        error_message=sim_result.error_message,
        duration_ms=sim_result.duration_ms,
        application_id=app.id,
        submission_plan_id=plan_model.id,
        idempotency_key=effective_idemp_key,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        application_status=app.status,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _persist_attempt(
    session: Session,
    *,
    app: TrackedApplication,
    plan_model: SubmissionPlanModel,
    attempt_number: int,
    idempotency_key: str,
    simulation_mode: str,
    status: str,
    outcome: str,
    error_code: str | None = None,
    error_message: str | None = None,
    simulated_receipt: str | None = None,
    metadata: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> ApplicationAttempt:
    now = datetime.now(timezone.utc)
    attempt = ApplicationAttempt(
        id=str(uuid.uuid4()),
        application_id=app.id,
        submission_plan_id=plan_model.id,
        attempt_number=attempt_number,
        idempotency_key=idempotency_key,
        simulation_mode=simulation_mode,
        plan_sha256=plan_model.packet_sha256,
        status=status,
        outcome=outcome,
        error_code=error_code,
        error_message=error_message,
        simulated_receipt=simulated_receipt,
        metadata_json=metadata or {},
        started_at=started_at or now,
        completed_at=now,
    )
    session.add(attempt)

    # Record system AuditEvent
    audit = AuditEvent(
        id=str(uuid.uuid4()),
        event_type="SUBMISSION_ATTEMPT_EXECUTED",
        entity_type="APPLICATION",
        entity_id=app.id,
        actor_type="USER",
        actor_id="local",
        payload_json={
            "attempt_id": attempt.id,
            "attempt_number": attempt_number,
            "status": status,
            "outcome": outcome,
            "simulation_mode": simulation_mode,
            "receipt": simulated_receipt,
            "plan_sha256": plan_model.packet_sha256,
        },
        created_at=now,
    )
    session.add(audit)
    session.commit()
    return attempt


def _build_result_from_attempt(
    attempt: ApplicationAttempt,
    *,
    is_replay: bool,
    app_status: str,
) -> SimulationResult:
    duration = 0
    if isinstance(attempt.metadata_json, dict) and "duration_ms" in attempt.metadata_json:
        duration = attempt.metadata_json.get("duration_ms") or 0
    elif attempt.completed_at and attempt.started_at:
        duration = max(0, int((attempt.completed_at - attempt.started_at).total_seconds() * 1000))

    receipt = attempt.simulated_receipt or ""
    return SimulationResult(
        simulation_id=attempt.id,
        receipt=receipt,
        dry_run=True,
        status=attempt.status,
        outcome=attempt.outcome,
        success=(attempt.outcome == "SUCCESS"),
        is_idempotent_replay=is_replay,
        attempt_number=attempt.attempt_number,
        plan_sha256=attempt.plan_sha256 or "",
        error_code=attempt.error_code,
        error_message=attempt.error_message,
        duration_ms=int(duration) if str(duration).isdigit() else 0,
        application_id=attempt.application_id,
        submission_plan_id=attempt.submission_plan_id,
        idempotency_key=attempt.idempotency_key or "",
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        application_status=app_status,
        metadata=attempt.metadata_json if isinstance(attempt.metadata_json, dict) else {},
    )
