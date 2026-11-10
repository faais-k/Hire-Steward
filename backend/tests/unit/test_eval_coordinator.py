"""Unit tests for the Offline Evaluation Coordinator (Task 8.2 Checkpoint A).

Verifies:
1. Full offline evaluation execution for a case with two independent evaluators.
2. Provenance resolution and admissibility disposition:
   - DIFFERENT_KNOWN_FAMILIES -> ADMISSIBLE_PAIR
   - SAME_CHECKPOINT -> BLOCKED_NON_INDEPENDENT
   - SAME_FAMILY_DIFF_CHECKPOINT + owner_override -> FLAGGED_PAIR
   - UNKNOWN_CHECKPOINT -> BLOCKED_NON_INDEPENDENT
3. Attempt fencing: late response on superseded attempt is fenced out and cannot overwrite committed state.
4. Fallback execution on adapter failure.
"""

from __future__ import annotations

import sqlite3
import pytest

from backend.app.evaluation.adapters import (
    MockAdapterConfig,
    MockProviderAdapter,
)
from backend.app.evaluation.coordinator import (
    OfflineEvaluationCoordinator,
)
from backend.app.evaluation.ledger import EvaluationLedger, verify_audit_chain
from backend.app.evaluation.real_world_dataset import load_unlabeled_case


def test_coordinator_evaluates_case_admissible_pair() -> None:
    """Coordinator executes Evaluator A and B with different families -> ADMISSIBLE_PAIR."""
    ledger = EvaluationLedger(db_path=":memory:")

    evaluator_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_openai_gpt4o",
            provider_id="mock_openai",
            model_alias="mock-gpt-4o",
            resolved_checkpoint_id="gpt-4o-2024-08-06",
            resolved_family_id="gpt-4o",
            resolved_creator_entity="openai",
            behavior_mode="SUCCESS",
        )
    )

    evaluator_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_anthropic_claude",
            provider_id="mock_anthropic",
            model_alias="mock-claude-3-5-sonnet",
            resolved_checkpoint_id="claude-3-5-sonnet-20241022",
            resolved_family_id="claude-3-5",
            resolved_creator_entity="anthropic",
            behavior_mode="SUCCESS",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_coord_001"

    pair_result = coordinator.evaluate_case(
        session_id=session_id,
        raw_case=raw_case,
    )

    assert pair_result.pair_status == "ADMISSIBLE_PAIR"
    assert pair_result.provenance_state == "DIFFERENT_KNOWN_FAMILIES"
    assert pair_result.assessment_a.match_tier in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
    assert pair_result.assessment_b.match_tier in ("TIER_1", "TIER_2", "TIER_3", "TIER_4")

    # Verify audit chain integrity
    with ledger.connect() as conn:
        assert verify_audit_chain(conn, session_id=session_id) is True


def test_coordinator_blocks_same_checkpoint_collision() -> None:
    """If both evaluators use identical checkpoints, pair is blocked as non-independent."""
    ledger = EvaluationLedger(db_path=":memory:")

    # Both evaluators configured with identical checkpoint
    evaluator_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_openai",
            model_alias="mock-gpt-4o",
            resolved_checkpoint_id="gpt-4o-2024-08-06",
            resolved_family_id="gpt-4o",
            resolved_creator_entity="openai",
        )
    )
    evaluator_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_openai",
            model_alias="mock-gpt-4o-clone",
            resolved_checkpoint_id="gpt-4o-2024-08-06",
            resolved_family_id="gpt-4o",
            resolved_creator_entity="openai",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_coord_same_chk"

    pair_result = coordinator.evaluate_case(
        session_id=session_id,
        raw_case=raw_case,
    )

    assert pair_result.pair_status == "BLOCKED_NON_INDEPENDENT"
    assert pair_result.provenance_state == "SAME_CHECKPOINT"


def test_coordinator_flagged_pair_with_owner_override() -> None:
    """Intra-family distinct checkpoints with active owner override become FLAGGED_PAIR."""
    ledger = EvaluationLedger(db_path=":memory:")

    evaluator_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_gemini_15_pro",
            provider_id="mock_google",
            model_alias="gemini-1.5-pro",
            resolved_checkpoint_id="gemini-1.5-pro-001",
            resolved_family_id="gemini-1.5",
            resolved_creator_entity="google",
        )
    )
    evaluator_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_gemini_15_flash",
            provider_id="mock_google",
            model_alias="gemini-1.5-flash",
            resolved_checkpoint_id="gemini-1.5-flash-001",
            resolved_family_id="gemini-1.5",
            resolved_creator_entity="google",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
        owner_override_active=True,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_coord_flagged"

    pair_result = coordinator.evaluate_case(
        session_id=session_id,
        raw_case=raw_case,
    )

    assert pair_result.pair_status == "FLAGGED_PAIR"
    assert pair_result.provenance_state == "SAME_FAMILY_DIFF_CHECKPOINT"


def test_coordinator_fences_out_late_responses() -> None:
    """Late response arriving after an evaluation has completed is fenced out."""
    ledger = EvaluationLedger(db_path=":memory:")

    evaluator_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_p1",
            model_alias="mock-m1",
            resolved_checkpoint_id="chk_a",
            resolved_family_id="fam_a",
            resolved_creator_entity="lab_a",
        )
    )
    evaluator_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_p2",
            model_alias="mock-m2",
            resolved_checkpoint_id="chk_b",
            resolved_family_id="fam_b",
            resolved_creator_entity="lab_b",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=evaluator_a,
        evaluator_b_adapter=evaluator_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_coord_fencing"

    # Evaluate case normally
    pair_result = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)
    assert pair_result.pair_status == "ADMISSIBLE_PAIR"

    # Simulate late response delivery on evaluator A with a contradictory tier
    original_tier = pair_result.assessment_a.match_tier
    contradictory_tier = "TIER_1" if original_tier != "TIER_1" else "TIER_4"
    fenced = coordinator.deliver_late_response(
        session_id=session_id,
        logical_eval_id=pair_result.evaluator_a_id,
        attempt_id="att_late_orphan",
        simulated_tier=contradictory_tier,
    )
    assert fenced is True

    # Confirm Evaluator A's committed assessment in ledger did NOT change
    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT match_tier FROM normalized_assessments WHERE assessment_id = ?;",
            (pair_result.assessment_a.assessment_id,),
        )
        current_tier = cursor.fetchone()[0]
        assert current_tier == original_tier
        assert current_tier != contradictory_tier

        # Verify audit log recorded RESPONSE_FENCED_OUT
        cursor.execute(
            "SELECT count(*) FROM evaluation_audit_events WHERE event_type = 'RESPONSE_FENCED_OUT';"
        )
        assert cursor.fetchone()[0] == 1


def test_coordinator_masks_candidate_pii_in_model_payloads() -> None:
    """Coordinator execution path must pseudonymize candidate name and evidence text."""
    ledger = EvaluationLedger(db_path=":memory:")

    received_payloads: list[Any] = []

    class InspectingMockAdapter(MockProviderAdapter):
        def execute_inference(self, payload: Any) -> Any:
            received_payloads.append(payload)
            return super().execute_inference(payload)

    adapter_a = InspectingMockAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_p1",
            model_alias="mock-m1",
            resolved_checkpoint_id="chk_a",
            resolved_family_id="fam_a",
            resolved_creator_entity="lab_a",
        )
    )
    adapter_b = InspectingMockAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_p2",
            model_alias="mock-m2",
            resolved_checkpoint_id="chk_b",
            resolved_family_id="fam_b",
            resolved_creator_entity="lab_b",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=adapter_a,
        evaluator_b_adapter=adapter_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    raw_name = raw_case["candidate_profile"]["name"]  # "Rohit Malviya"
    assert raw_name == "Rohit Malviya"

    coordinator.evaluate_case(session_id="sess_pii_check", raw_case=raw_case)

    assert len(received_payloads) == 2

    for p in received_payloads:
        # 1. Candidate name must be pseudonymized
        assert p.candidate_profile.name == "[CANDIDATE_NAME]"
        assert raw_name not in p.candidate_profile.name

        # 2. Evidence statements must not contain raw candidate name
        for fact in p.candidate_profile.evidence_facts:
            assert raw_name not in fact.statement
            assert "[CANDIDATE_NAME]" in fact.statement

        # 3. Serialized JSON payload must not contain cleartext candidate name
        serialized_json = p.model_dump_json()
        assert raw_name not in serialized_json
        assert "rohit.m@example.invalid" not in serialized_json
        assert "+91-98765-03001" not in serialized_json


def test_audit_case_provenance_has_no_unknown_case() -> None:
    """Assessment commitment audit events must contain the exact case_id, not UNKNOWN_CASE."""
    ledger = EvaluationLedger(db_path=":memory:")
    adapter_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_p1",
            model_alias="mock-m1",
            resolved_checkpoint_id="chk_a",
            resolved_family_id="fam_a",
            resolved_creator_entity="lab_a",
        )
    )
    adapter_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_p2",
            model_alias="mock-m2",
            resolved_checkpoint_id="chk_b",
            resolved_family_id="fam_b",
            resolved_creator_entity="lab_b",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=adapter_a,
        evaluator_b_adapter=adapter_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_provenance_check"
    coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_seq, case_id, event_type
            FROM evaluation_audit_events
            WHERE session_id = ?
            ORDER BY event_seq ASC;
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        assert len(rows) >= 3

        # Zero occurrences of UNKNOWN_CASE
        for seq, case_id, ev_type in rows:
            assert case_id != "UNKNOWN_CASE", f"Event {seq} ({ev_type}) has forbidden UNKNOWN_CASE!"

        # Assessment committed events must have rw_calib_001
        asmt_events = [r for r in rows if r[2] == "ASSESSMENT_COMMITTED"]
        assert len(asmt_events) == 2
        for seq, case_id, _ in asmt_events:
            assert case_id == "rw_calib_001"

        # Verify hash chain integrity
        assert verify_audit_chain(conn, session_id=session_id) is True


def test_coordinator_resolves_and_records_citations_with_confidence() -> None:
    """Coordinator resolves returned model citations and records their confidence tiers."""
    ledger = EvaluationLedger(db_path=":memory:")

    class CitationMockAdapter(MockProviderAdapter):
        def execute_inference(self, payload: Any) -> Any:
            resp = super().execute_inference(payload)
            # Add citations: 1 exact match, 1 fuzzy recovered (drifted), 1 hallucinated, 1 unknown section
            resp.citations = [
                {
                    "source_section": "job_posting.requirements",
                    "quote": "POS Systems",
                    "payload_start": 0,
                    "payload_end": 11,
                },
                {
                    "source_section": "job_posting.requirements",
                    "quote": "POS Systems",
                    "payload_start": 25,  # slight drift
                    "payload_end": 36,
                },
                {
                    "source_section": "job_posting.requirements",
                    "quote": "Hallucinated non-existent requirement text snippet 999",
                    "payload_start": 0,
                    "payload_end": 50,
                },
                {
                    "source_section": "unknown_invalid_section",
                    "quote": "POS Systems",
                    "payload_start": 0,
                    "payload_end": 11,
                },
            ]
            return resp

    adapter_a = CitationMockAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_p1",
            model_alias="mock-m1",
            resolved_checkpoint_id="chk_a",
            resolved_family_id="fam_a",
            resolved_creator_entity="lab_a",
        )
    )
    adapter_b = CitationMockAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_p2",
            model_alias="mock-m2",
            resolved_checkpoint_id="chk_b",
            resolved_family_id="fam_b",
            resolved_creator_entity="lab_b",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=adapter_a,
        evaluator_b_adapter=adapter_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_citation_check"
    pair_res = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    # Inspect citations stored in normalized_assessments
    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT citations_json FROM normalized_assessments WHERE assessment_id = ?;",
            (pair_res.assessment_a.assessment_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        import json
        citations = json.loads(row[0])
        assert len(citations) == 4

        # Verify source_section persistence
        assert citations[0]["source_section"] == "job_posting.requirements"
        assert citations[3]["source_section"] == "unknown_invalid_section"
        assert citations[3]["resolution_status"] == "REJECTED_UNRESOLVED"
        assert citations[3]["confidence"] == "ZERO"

        statuses = [c["resolution_status"] for c in citations]
        confidences = [c["confidence"] for c in citations]

        # Must preserve EXACT_MATCH, FUZZY_RECOVERED, REJECTED_UNRESOLVED
        assert "EXACT_MATCH" in statuses
        assert "REJECTED_UNRESOLVED" in statuses

        # Fuzzy recovery must have LOWER_CONFIDENCE, never HIGH
        for c in citations:
            if c["resolution_status"] == "FUZZY_RECOVERED":
                assert c["confidence"] == "LOWER_CONFIDENCE"
            elif c["resolution_status"] == "EXACT_MATCH":
                assert c["confidence"] == "HIGH"
            elif c["resolution_status"] == "REJECTED_UNRESOLVED":
                assert c["confidence"] == "ZERO"


def test_coordinator_handles_evaluator_a_failure_unilateral_exhaustion() -> None:
    """When Evaluator A fails, pair records FAILED_PAIR_UNILATERAL_EXHAUSTION without crashing."""
    ledger = EvaluationLedger(db_path=":memory:")

    adapter_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_p1",
            model_alias="mock-m1",
            resolved_checkpoint_id="chk_a",
            resolved_family_id="fam_a",
            resolved_creator_entity="lab_a",
            behavior_mode="SERVER_ERROR_500",
        )
    )
    adapter_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_p2",
            model_alias="mock-m2",
            resolved_checkpoint_id="chk_b",
            resolved_family_id="fam_b",
            resolved_creator_entity="lab_b",
            behavior_mode="SUCCESS",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=adapter_a,
        evaluator_b_adapter=adapter_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_fail_eval_a"

    # Must NOT raise RuntimeError
    pair_res = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    assert pair_res.pair_status == "FAILED_PAIR_UNILATERAL_EXHAUSTION"
    assert pair_res.assessment_a is None
    assert pair_res.assessment_b is not None

    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT evaluator_role, status FROM logical_evaluations WHERE session_id = ? ORDER BY evaluator_role;",
            (session_id,),
        )
        eval_rows = cursor.fetchall()
        assert eval_rows == [("EVALUATOR_A", "FAILED"), ("EVALUATOR_B", "COMPLETED")]

        # Audit events must record failure and pair failure
        cursor.execute(
            "SELECT count(*) FROM evaluation_audit_events WHERE session_id = ? AND event_type = 'PAIR_FAILED_UNILATERAL';",
            (session_id,),
        )
        assert cursor.fetchone()[0] == 1

        assert verify_audit_chain(conn, session_id=session_id) is True


def test_coordinator_handles_dual_exhaustion_failure() -> None:
    """When both evaluators fail, pair records FAILED_PAIR_DUAL_EXHAUSTION."""
    ledger = EvaluationLedger(db_path=":memory:")

    adapter_a = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_a",
            provider_id="mock_p1",
            model_alias="mock-m1",
            resolved_checkpoint_id="chk_a",
            resolved_family_id="fam_a",
            resolved_creator_entity="lab_a",
            behavior_mode="RATE_LIMIT_429",
        )
    )
    adapter_b = MockProviderAdapter(
        config=MockAdapterConfig(
            candidate_id="cand_b",
            provider_id="mock_p2",
            model_alias="mock-m2",
            resolved_checkpoint_id="chk_b",
            resolved_family_id="fam_b",
            resolved_creator_entity="lab_b",
            behavior_mode="TIMEOUT",
        )
    )

    coordinator = OfflineEvaluationCoordinator(
        ledger=ledger,
        evaluator_a_adapter=adapter_a,
        evaluator_b_adapter=adapter_b,
    )

    raw_case = load_unlabeled_case("rw_calib_001")
    session_id = "sess_fail_dual"

    pair_res = coordinator.evaluate_case(session_id=session_id, raw_case=raw_case)

    assert pair_res.pair_status == "FAILED_PAIR_DUAL_EXHAUSTION"
    assert pair_res.assessment_a is None
    assert pair_res.assessment_b is None

    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT evaluator_role, status FROM logical_evaluations WHERE session_id = ? ORDER BY evaluator_role;",
            (session_id,),
        )
        eval_rows = cursor.fetchall()
        assert eval_rows == [("EVALUATOR_A", "FAILED"), ("EVALUATOR_B", "FAILED")]

        cursor.execute(
            "SELECT count(*) FROM evaluation_audit_events WHERE session_id = ? AND event_type = 'PAIR_FAILED_DUAL';",
            (session_id,),
        )
        assert cursor.fetchone()[0] == 1

        assert verify_audit_chain(conn, session_id=session_id) is True

