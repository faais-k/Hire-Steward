"""Offline Evaluation Coordinator (Task 8.2 Checkpoint A).

Orchestrates:
1. Double-blind case serialization via BlindedEvaluationSerializer.
2. Independent execution across Evaluator A and Evaluator B adapters.
3. Attempt fencing protecting completed assessments from late response overwrites.
4. Relational evaluation ledger persistence and composite foreign-key commitment.
5. Strict provenance evaluation enforcing independence barriers (SAME_CHECKPOINT,
   SAME_FAMILY_DIFF_CHECKPOINT, SAME_CREATOR_DIFF_FAMILY, DIFFERENT_KNOWN_FAMILIES).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel

from backend.app.evaluation.adapters import (
    BaseProviderAdapter,
    ModelInferenceResponse,
)
from backend.app.evaluation.blinded_serializer import (
    BlindedCasePayload,
    BlindedEvaluationSerializer,
)
from backend.app.evaluation.budget import (
    BudgetTracker,
    calculate_actual_cost,
    estimate_call_cost,
)
from backend.app.evaluation.ledger import EvaluationLedger
from backend.app.evaluation.pii_mapper import CitationResolution


class CommittedAssessmentResult(BaseModel):
    """Result of an evaluator's committed assessment."""

    logical_eval_id: str
    attempt_id: str
    assessment_id: str
    match_tier: Literal["TIER_1", "TIER_2", "TIER_3", "TIER_4"]
    match_score: float
    reasoning: str
    resolved_checkpoint_id: str
    resolved_family_id: str
    resolved_creator_entity: str


class CaseEvaluationPairResult(BaseModel):
    """Result of paired evaluation and provenance determination."""

    pair_id: str
    session_id: str
    case_id: str
    evaluator_a_id: str
    evaluator_b_id: str
    assessment_a: CommittedAssessmentResult | None = None
    assessment_b: CommittedAssessmentResult | None = None
    provenance_state: Literal[
        "SAME_CHECKPOINT",
        "SAME_FAMILY_DIFF_CHECKPOINT",
        "SAME_CREATOR_DIFF_FAMILY",
        "DIFFERENT_KNOWN_FAMILIES",
        "UNKNOWN_PROVENANCE",
    ]
    same_creator_flag: bool
    pair_status: Literal[
        "PENDING",
        "IN_PROGRESS",
        "ADMISSIBLE_PAIR",
        "FLAGGED_PAIR",
        "BLOCKED_NON_INDEPENDENT",
        "FAILED_PAIR_UNILATERAL_EXHAUSTION",
        "FAILED_PAIR_DUAL_EXHAUSTION",
    ]


class OfflineEvaluationCoordinator:
    """Coordinates offline multi-model case evaluation and provenance determination."""

    def __init__(
        self,
        ledger: EvaluationLedger,
        evaluator_a_adapter: BaseProviderAdapter,
        evaluator_b_adapter: BaseProviderAdapter,
        owner_override_active: bool = False,
        budget_tracker: BudgetTracker | None = None,
    ) -> None:
        self.ledger = ledger
        self.adapter_a = evaluator_a_adapter
        self.adapter_b = evaluator_b_adapter
        self.owner_override_active = owner_override_active
        self.budget_tracker = budget_tracker
        self.serializer = BlindedEvaluationSerializer()

    def evaluate_case(
        self,
        session_id: str,
        raw_case: dict[str, Any],
    ) -> CaseEvaluationPairResult:
        """Execute blinded evaluation for both evaluators and determine pair admissibility."""
        blinded_payload_a: BlindedCasePayload = self.serializer.serialize(raw_case)
        blinded_payload_b: BlindedCasePayload = self.serializer.serialize(raw_case)
        case_id = blinded_payload_a.case_id

        with self.ledger.connect() as conn:
            # 1. Ensure session exists
            cursor = conn.cursor()
            cursor.execute(
                "SELECT count(*) FROM evaluation_sessions WHERE session_id = ?;",
                (session_id,),
            )
            if cursor.fetchone()[0] == 0:
                self.ledger.create_session(
                    conn=conn,
                    session_id=session_id,
                    config_hash=hashlib.sha256(f"cfg:{session_id}".encode()).hexdigest(),
                )

            # 2. Execute Evaluator A
            eval_a_id = f"eval_a_{case_id}_{uuid.uuid4().hex[:6]}"
            asmt_a = self._execute_evaluator(
                conn=conn,
                session_id=session_id,
                case_id=case_id,
                eval_id=eval_a_id,
                evaluator_role="EVALUATOR_A",
                adapter=self.adapter_a,
                payload=blinded_payload_a,
            )

            # 3. Execute Evaluator B
            eval_b_id = f"eval_b_{case_id}_{uuid.uuid4().hex[:6]}"
            asmt_b = self._execute_evaluator(
                conn=conn,
                session_id=session_id,
                case_id=case_id,
                eval_id=eval_b_id,
                evaluator_role="EVALUATOR_B",
                adapter=self.adapter_b,
                payload=blinded_payload_b,
            )

            # 4. Resolve Provenance Matrix and Status
            if asmt_a is None and asmt_b is None:
                provenance_state: Literal[
                    "SAME_CHECKPOINT",
                    "SAME_FAMILY_DIFF_CHECKPOINT",
                    "SAME_CREATOR_DIFF_FAMILY",
                    "DIFFERENT_KNOWN_FAMILIES",
                    "UNKNOWN_PROVENANCE",
                ] = "UNKNOWN_PROVENANCE"
                same_creator = False
                pair_status: Literal[
                    "PENDING",
                    "IN_PROGRESS",
                    "ADMISSIBLE_PAIR",
                    "FLAGGED_PAIR",
                    "BLOCKED_NON_INDEPENDENT",
                    "FAILED_PAIR_UNILATERAL_EXHAUSTION",
                    "FAILED_PAIR_DUAL_EXHAUSTION",
                ] = "FAILED_PAIR_DUAL_EXHAUSTION"
                ev_type = "PAIR_FAILED_DUAL"
            elif asmt_a is None or asmt_b is None:
                provenance_state = "UNKNOWN_PROVENANCE"
                same_creator = False
                pair_status = "FAILED_PAIR_UNILATERAL_EXHAUSTION"
                ev_type = "PAIR_FAILED_UNILATERAL"
            else:
                provenance_state, same_creator = self._resolve_provenance(asmt_a, asmt_b)
                if provenance_state == "SAME_CHECKPOINT" or provenance_state == "UNKNOWN_PROVENANCE":
                    pair_status = "BLOCKED_NON_INDEPENDENT"
                elif provenance_state == "DIFFERENT_KNOWN_FAMILIES":
                    if same_creator:
                        pair_status = "FLAGGED_PAIR" if self.owner_override_active else "BLOCKED_NON_INDEPENDENT"
                    else:
                        pair_status = "ADMISSIBLE_PAIR"
                elif provenance_state in ("SAME_FAMILY_DIFF_CHECKPOINT", "SAME_CREATOR_DIFF_FAMILY"):
                    pair_status = "FLAGGED_PAIR" if self.owner_override_active else "BLOCKED_NON_INDEPENDENT"
                else:
                    pair_status = "BLOCKED_NON_INDEPENDENT"

                ev_type = (
                    "PAIR_ADMISSIBLE_COMMITTED"
                    if pair_status == "ADMISSIBLE_PAIR"
                    else ("PAIR_FLAGGED_COMMITTED" if pair_status == "FLAGGED_PAIR" else "PAIR_BLOCKED_COLLISION")
                )

            # 5. Persist Pair to Ledger
            pair_id = f"pair_{session_id}_{case_id}"
            committed_a_id = asmt_a.assessment_id if asmt_a else None
            committed_b_id = asmt_b.assessment_id if asmt_b else None
            self.ledger.create_or_update_pair(
                conn=conn,
                pair_id=pair_id,
                session_id=session_id,
                case_id=case_id,
                evaluator_a_id=eval_a_id,
                evaluator_b_id=eval_b_id,
                committed_assessment_a_id=committed_a_id,
                committed_assessment_b_id=committed_b_id,
                provenance_state=provenance_state,
                same_creator_flag=same_creator,
                pair_status=pair_status,
                owner_override_active=self.owner_override_active,
            )

            # 6. Append audit event for pair commitment
            self.ledger.append_audit_event(
                conn=conn,
                session_id=session_id,
                case_id=case_id,
                event_type=ev_type,
                payload={
                    "pair_id": pair_id,
                    "provenance_state": provenance_state,
                    "pair_status": pair_status,
                    "same_creator": same_creator,
                    "override": self.owner_override_active,
                },
                logical_eval_id=eval_a_id,
            )

            return CaseEvaluationPairResult(
                pair_id=pair_id,
                session_id=session_id,
                case_id=case_id,
                evaluator_a_id=eval_a_id,
                evaluator_b_id=eval_b_id,
                assessment_a=asmt_a,
                assessment_b=asmt_b,
                provenance_state=provenance_state,
                same_creator_flag=same_creator,
                pair_status=pair_status,
            )

    def _execute_evaluator(
        self,
        conn: Any,
        session_id: str,
        case_id: str,
        eval_id: str,
        evaluator_role: Literal["EVALUATOR_A", "EVALUATOR_B"],
        adapter: BaseProviderAdapter,
        payload: BlindedCasePayload,
    ) -> CommittedAssessmentResult | None:
        """Register logical evaluation, dispatch attempt, and commit assessment."""
        # 1. Register logical evaluation row
        self.ledger.create_logical_evaluation(
            conn=conn,
            logical_eval_id=eval_id,
            session_id=session_id,
            case_id=case_id,
            evaluator_role=evaluator_role,
        )

        cfg = getattr(adapter, "config", None)
        cand_id = getattr(cfg, "candidate_id", "cand_default")
        prov_id = getattr(cfg, "provider_id", "prov_default")
        alias = getattr(cfg, "model_alias", "alias_default")
        chk = getattr(cfg, "resolved_checkpoint_id", "chk_default")
        fam = getattr(cfg, "resolved_family_id", "fam_default")
        creator = getattr(cfg, "resolved_creator_entity", "creator_default")
        fp = getattr(cfg, "system_fingerprint", None)

        # Pre-dispatch budget reservation
        res_id = f"res_{eval_id}"
        if self.budget_tracker is not None:
            est_cost = estimate_call_cost(alias, pricing_table=self.budget_tracker.pricing_table)
            if not self.budget_tracker.can_reserve(est_cost):
                attempt_id = f"att_{eval_id}_1"
                self.ledger.create_dispatch_attempt(
                    conn=conn,
                    attempt_id=attempt_id,
                    logical_eval_id=eval_id,
                    attempt_number=1,
                    attempt_type="INITIAL",
                    candidate_id=cand_id,
                    provider_id=prov_id,
                    model_alias=alias,
                    resolved_checkpoint_id=chk,
                    resolved_family_id=fam,
                    resolved_creator_entity=creator,
                    state="RESERVED",
                    reserved_tokens=2500,
                    system_fingerprint=fp,
                )
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE dispatch_attempts
                    SET state = 'ABORTED_PRE_SOCKET', terminal_reason = 'CANDIDATE_INELIGIBLE_PRE_SOCKET'
                    WHERE attempt_id = ?;
                    """,
                    (attempt_id,),
                )
                cursor.execute(
                    """
                    UPDATE logical_evaluations
                    SET status = 'FAILED'
                    WHERE logical_eval_id = ?;
                    """,
                    (eval_id,),
                )
                self.ledger.append_audit_event(
                    conn=conn,
                    session_id=session_id,
                    case_id=case_id,
                    event_type="ATTEMPT_FAILED",
                    payload={"eval_id": eval_id, "reason": "BUDGET_CAP_EXCEEDED", "error_type": "CANDIDATE_INELIGIBLE_PRE_SOCKET", "cost": est_cost},
                    logical_eval_id=eval_id,
                    attempt_id=attempt_id,
                )
                conn.commit()
                return None

            self.budget_tracker.reserve(res_id, est_cost)

        max_attempts = 3
        for attempt_number in range(1, max_attempts + 1):
            attempt_id = f"att_{eval_id}_{attempt_number}"
            attempt_type: Literal["INITIAL", "RETRY"] = "INITIAL" if attempt_number == 1 else "RETRY"

            self.ledger.create_dispatch_attempt(
                conn=conn,
                attempt_id=attempt_id,
                logical_eval_id=eval_id,
                attempt_number=attempt_number,
                attempt_type=attempt_type,
                candidate_id=cand_id,
                provider_id=prov_id,
                model_alias=alias,
                resolved_checkpoint_id=chk,
                resolved_family_id=fam,
                resolved_creator_entity=creator,
                state="STARTED",
                reserved_tokens=2500,
                system_fingerprint=fp,
            )

            # 2. Execute adapter inference
            response: ModelInferenceResponse = adapter.execute_inference(payload)

            if response.success:
                if self.budget_tracker is not None:
                    actual_cost = calculate_actual_cost(
                        alias,
                        response.reported_input_tokens,
                        response.reported_output_tokens,
                        pricing_table=self.budget_tracker.pricing_table,
                    )
                    self.budget_tracker.reconcile(res_id, actual_cost)

                # 4. Resolve citations with section-scoped coordinate mapping
                resolved_citations: list[dict[str, Any]] = []
                masking_registry = getattr(payload, "masking_result", None)

                for cit in (response.citations or []):
                    source_section = cit.get("source_section")
                    quote = cit.get("quote", "")
                    p_start = cit.get("payload_start", 0)
                    p_end = cit.get("payload_end", 0)

                    if masking_registry is not None:
                        resolution = masking_registry.resolve_citation(
                            citation_text=quote,
                            payload_start=p_start,
                            payload_end=p_end,
                            source_section=source_section,
                        )
                    else:
                        resolution = CitationResolution(
                            status="REJECTED_UNRESOLVED",
                            resolved_text=None,
                            orig_start=None,
                            orig_end=None,
                            confidence="ZERO",
                            reason="No masking registry available for citation resolution",
                        )

                    resolved_citations.append({
                        "source_section": source_section,
                        "quote": quote,
                        "payload_start": p_start,
                        "payload_end": p_end,
                        "resolution_status": resolution.status,
                        "confidence": resolution.confidence,
                        "resolved_text": resolution.resolved_text,
                        "orig_start": resolution.orig_start,
                        "orig_end": resolution.orig_end,
                        "reason": resolution.reason,
                    })

                citations_json = json.dumps(resolved_citations)

                # 5. Commit assessment
                asmt_id = f"asmt_{eval_id}"
                self.ledger.commit_assessment(
                    conn=conn,
                    session_id=session_id,
                    logical_eval_id=eval_id,
                    attempt_id=attempt_id,
                    assessment_id=asmt_id,
                    match_tier=response.match_tier or "TIER_4",
                    match_score=response.match_score or 0.0,
                    reasoning=response.reasoning or "",
                    raw_payload_hash=hashlib.sha256(response.raw_response_body.encode("utf-8")).hexdigest(),
                    case_id=case_id,
                    citations_json=citations_json,
                )

                return CommittedAssessmentResult(
                    logical_eval_id=eval_id,
                    attempt_id=attempt_id,
                    assessment_id=asmt_id,
                    match_tier=response.match_tier or "TIER_4",
                    match_score=response.match_score or 0.0,
                    reasoning=response.reasoning or "",
                    resolved_checkpoint_id=response.resolved_checkpoint_id,
                    resolved_family_id=response.resolved_family_id,
                    resolved_creator_entity=response.resolved_creator_entity,
                )

            # Failure branch
            cursor = conn.cursor()
            is_timeout = response.error_type == "TIMEOUT_CLIENT"
            is_5xx = response.error_type == "HTTP_5XX_SERVER_ERROR"
            is_429 = response.error_type == "HTTP_429_RATE_LIMIT"
            target_state = "AMBIGUOUS_IN_FLIGHT" if is_timeout else "FAILED"

            cursor.execute(
                """
                UPDATE dispatch_attempts
                SET state = ?, terminal_reason = ?, http_status = ?, latency_ms = ?
                WHERE attempt_id = ?;
                """,
                (target_state, response.error_type, response.http_status, response.latency_ms, attempt_id),
            )
            self.ledger.append_audit_event(
                conn=conn,
                session_id=session_id,
                case_id=case_id,
                event_type="ATTEMPT_FAILED",
                payload={
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "error_type": response.error_type,
                    "http_status": response.http_status,
                    "latency_ms": response.latency_ms,
                    "state": target_state,
                },
                logical_eval_id=eval_id,
                attempt_id=attempt_id,
            )

            # Never auto-retry on timeout or 5xx
            if is_timeout or is_5xx:
                if self.budget_tracker is not None:
                    self.budget_tracker.record_unresolved_liability(res_id)
                cursor.execute(
                    """
                    UPDATE logical_evaluations
                    SET status = 'FAILED'
                    WHERE logical_eval_id = ?;
                    """,
                    (eval_id,),
                )
                conn.commit()
                return None

            # Retry 429 if attempts remain
            if is_429 and attempt_number < max_attempts:
                conn.commit()
                continue

            # Non-retryable error or exhausted 429 retries
            if self.budget_tracker is not None:
                self.budget_tracker.release(res_id)
            cursor.execute(
                """
                UPDATE logical_evaluations
                SET status = 'FAILED'
                WHERE logical_eval_id = ?;
                """,
                (eval_id,),
            )
            conn.commit()
            return None

        return None

    def _resolve_provenance(
        self,
        asmt_a: CommittedAssessmentResult,
        asmt_b: CommittedAssessmentResult,
    ) -> tuple[
        Literal[
            "SAME_CHECKPOINT",
            "SAME_FAMILY_DIFF_CHECKPOINT",
            "SAME_CREATOR_DIFF_FAMILY",
            "DIFFERENT_KNOWN_FAMILIES",
            "UNKNOWN_PROVENANCE",
        ],
        bool,
    ]:
        """Determine canonical provenance classification based on model execution metadata."""
        if (
            "unknown" in asmt_a.resolved_checkpoint_id.lower()
            or "unknown" in asmt_b.resolved_checkpoint_id.lower()
        ):
            return "UNKNOWN_PROVENANCE", False

        if asmt_a.resolved_checkpoint_id == asmt_b.resolved_checkpoint_id:
            return "SAME_CHECKPOINT", True

        same_creator = asmt_a.resolved_creator_entity.lower() == asmt_b.resolved_creator_entity.lower()

        if asmt_a.resolved_family_id == asmt_b.resolved_family_id:
            return "SAME_FAMILY_DIFF_CHECKPOINT", same_creator

        if same_creator:
            return "SAME_CREATOR_DIFF_FAMILY", True

        return "DIFFERENT_KNOWN_FAMILIES", False

    def deliver_late_response(
        self,
        session_id: str,
        logical_eval_id: str,
        attempt_id: str,
        simulated_tier: str,
    ) -> bool:
        """Handle late response arriving after an evaluation has terminated (fencing out)."""
        with self.ledger.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status, active_attempt_id, case_id FROM logical_evaluations WHERE logical_eval_id = ?;",
                (logical_eval_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            status, active_attempt_id, case_id = row
            if status == "COMPLETED":
                # Check if attempt_id exists in dispatch_attempts to satisfy FK constraint
                cursor.execute(
                    "SELECT count(*) FROM dispatch_attempts WHERE attempt_id = ?;",
                    (attempt_id,),
                )
                valid_attempt_fk = attempt_id if cursor.fetchone()[0] > 0 else None

                # Fenced out! Record audit events without updating committed state
                self.ledger.append_audit_event(
                    conn=conn,
                    session_id=session_id,
                    case_id=case_id,
                    event_type="LATE_RESPONSE_RECEIVED",
                    payload={
                        "logical_eval_id": logical_eval_id,
                        "attempt_id": attempt_id,
                        "simulated_tier": simulated_tier,
                    },
                    logical_eval_id=logical_eval_id,
                    attempt_id=valid_attempt_fk,
                )
                self.ledger.append_audit_event(
                    conn=conn,
                    session_id=session_id,
                    case_id=case_id,
                    event_type="RESPONSE_FENCED_OUT",
                    payload={
                        "logical_eval_id": logical_eval_id,
                        "attempt_id": attempt_id,
                        "reason": "Active attempt already completed; late response rejected by fencing barrier",
                    },
                    logical_eval_id=logical_eval_id,
                    attempt_id=valid_attempt_fk,
                )
                conn.commit()
                return True

            return False
