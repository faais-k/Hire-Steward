"""Unit tests for the Isolated Evaluation Ledger (Task 8.2 Checkpoint A).

Verifies:
1. SQLite connection factory enforces PRAGMA foreign_keys = ON.
2. Composite foreign keys enforce attempt-to-evaluation and assessment-to-evaluator ownership.
3. Immutability triggers reject UPDATE/DELETE on terminal attempts and assessments.
4. Paired evaluation check constraints enforce provenance admissibility rules.
5. Atomic 5-step assessment commitment transaction.
"""

from __future__ import annotations

import sqlite3
import pytest

from backend.app.evaluation.ledger import (
    EvaluationLedger,
    LedgerConstraintError,
    LedgerIntegrityError,
)


def test_sqlite_foreign_keys_strictly_enforced() -> None:
    """Connection factory must ensure foreign_keys PRAGMA is active and verified."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys;")
        val = cursor.fetchone()[0]
        assert val == 1, "PRAGMA foreign_keys must evaluate to 1"


def test_terminal_attempt_immutability_trigger() -> None:
    """Updating a terminal dispatch attempt must be rejected by SQLite trigger."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        # Create session
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        # Create logical evaluation
        ledger.create_logical_evaluation(
            conn,
            logical_eval_id="eval_a_001",
            session_id="sess_001",
            case_id="rw_calib_001",
            evaluator_role="EVALUATOR_A",
        )
        # Create attempt in STARTED state
        ledger.create_dispatch_attempt(
            conn,
            attempt_id="att_001",
            logical_eval_id="eval_a_001",
            attempt_number=1,
            attempt_type="INITIAL",
            candidate_id="cand_1",
            provider_id="mock_provider",
            model_alias="mock-gpt4",
            resolved_checkpoint_id="mock-gpt4-chk1",
            resolved_family_id="mock-gpt",
            resolved_creator_entity="mock-lab",
            state="STARTED",
            reserved_tokens=2000,
        )

        # Mark attempt as COMPLETED (terminal)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE dispatch_attempts
            SET state = 'COMPLETED', terminal_reason = 'SUCCESS_NORMALIZED'
            WHERE attempt_id = 'att_001';
            """
        )
        conn.commit()

        # Attempting to mutate terminal attempt must fail
        with pytest.raises(sqlite3.IntegrityError, match="Terminal attempt record is immutable"):
            cursor.execute(
                """
                UPDATE dispatch_attempts
                SET reported_input_tokens = 999
                WHERE attempt_id = 'att_001';
                """
            )


def test_assessment_immutability_triggers() -> None:
    """Normalized and committed assessments cannot be modified or deleted."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        ledger.create_logical_evaluation(
            conn,
            logical_eval_id="eval_a_001",
            session_id="sess_001",
            case_id="rw_calib_001",
            evaluator_role="EVALUATOR_A",
        )
        ledger.create_dispatch_attempt(
            conn,
            attempt_id="att_001",
            logical_eval_id="eval_a_001",
            attempt_number=1,
            attempt_type="INITIAL",
            candidate_id="cand_1",
            provider_id="mock_provider",
            model_alias="mock-gpt4",
            resolved_checkpoint_id="mock-gpt4-chk1",
            resolved_family_id="mock-gpt",
            resolved_creator_entity="mock-lab",
            state="STARTED",
            reserved_tokens=2000,
        )

        # Atomically commit assessment
        ledger.commit_assessment(
            conn,
            session_id="sess_001",
            logical_eval_id="eval_a_001",
            attempt_id="att_001",
            assessment_id="asmt_001",
            match_tier="TIER_1",
            match_score=0.92,
            reasoning="Strong alignment",
            raw_payload_hash="hash_raw_123",
        )

        cursor = conn.cursor()
        # Verify UPDATE on normalized_assessments is rejected
        with pytest.raises(sqlite3.IntegrityError, match="Normalized assessments are immutable"):
            cursor.execute("UPDATE normalized_assessments SET match_score = 0.5 WHERE assessment_id = 'asmt_001';")

        # Verify DELETE on normalized_assessments is rejected
        with pytest.raises(sqlite3.IntegrityError, match="Normalized assessments are immutable"):
            cursor.execute("DELETE FROM normalized_assessments WHERE assessment_id = 'asmt_001';")

        # Verify UPDATE on committed_assessments is rejected
        with pytest.raises(sqlite3.IntegrityError, match="Committed assessments are immutable"):
            cursor.execute("UPDATE committed_assessments SET assessment_id = 'asmt_999' WHERE logical_eval_id = 'eval_a_001';")

        # Verify DELETE on committed_assessments is rejected
        with pytest.raises(sqlite3.IntegrityError, match="Committed assessments are immutable"):
            cursor.execute("DELETE FROM committed_assessments WHERE logical_eval_id = 'eval_a_001';")


def test_pair_evaluator_ownership_isolation() -> None:
    """Evaluator A cannot reference Evaluator B's committed assessment."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        # Evaluator A
        ledger.create_logical_evaluation(
            conn, logical_eval_id="eval_a", session_id="sess_001", case_id="case_1", evaluator_role="EVALUATOR_A"
        )
        ledger.create_dispatch_attempt(
            conn, "att_a", "eval_a", 1, "INITIAL", "c1", "p1", "m1", "chk_a", "fam_a", "lab_a", "STARTED", 1000
        )
        ledger.commit_assessment(conn, "sess_001", "eval_a", "att_a", "asmt_a", "TIER_1", 0.9, "good", "hash_a")

        # Evaluator B
        ledger.create_logical_evaluation(
            conn, logical_eval_id="eval_b", session_id="sess_001", case_id="case_1", evaluator_role="EVALUATOR_B"
        )
        ledger.create_dispatch_attempt(
            conn, "att_b", "eval_b", 1, "INITIAL", "c2", "p2", "m2", "chk_b", "fam_b", "lab_b", "STARTED", 1000
        )
        ledger.commit_assessment(conn, "sess_001", "eval_b", "att_b", "asmt_b", "TIER_1", 0.85, "good", "hash_b")

        # Valid pair with correct ownership
        ledger.create_or_update_pair(
            conn,
            pair_id="pair_1",
            session_id="sess_001",
            case_id="case_1",
            evaluator_a_id="eval_a",
            evaluator_b_id="eval_b",
            committed_assessment_a_id="asmt_a",
            committed_assessment_b_id="asmt_b",
            provenance_state="DIFFERENT_KNOWN_FAMILIES",
            same_creator_flag=False,
            pair_status="ADMISSIBLE_PAIR",
        )

        # Cross-ownership attempt: assign asmt_b to evaluator_a
        with pytest.raises(sqlite3.IntegrityError):
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO paired_evaluations (
                    pair_id, session_id, case_id, evaluator_a_id, evaluator_b_id,
                    committed_assessment_a_id, committed_assessment_b_id,
                    provenance_state, same_creator_flag, pair_status, updated_at
                ) VALUES (
                    'pair_invalid', 'sess_001', 'case_2', 'eval_a', 'eval_b',
                    'asmt_b', 'asmt_b',
                    'DIFFERENT_KNOWN_FAMILIES', 0, 'ADMISSIBLE_PAIR', CURRENT_TIMESTAMP
                );
                """
            )


def test_provenance_admissibility_check_constraints() -> None:
    """SAME_CHECKPOINT or UNKNOWN_PROVENANCE can NEVER become ADMISSIBLE_PAIR."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        ledger.create_logical_evaluation(
            conn, "eval_a", "sess_001", "case_1", "EVALUATOR_A"
        )
        ledger.create_dispatch_attempt(
            conn, "att_a", "eval_a", 1, "INITIAL", "c1", "p1", "m1", "chk_a", "fam_a", "lab_a", "STARTED", 1000
        )
        ledger.commit_assessment(conn, "sess_001", "eval_a", "att_a", "asmt_a", "TIER_1", 0.9, "good", "hash_a")

        ledger.create_logical_evaluation(
            conn, "eval_b", "sess_001", "case_1", "EVALUATOR_B"
        )
        ledger.create_dispatch_attempt(
            conn, "att_b", "eval_b", 1, "INITIAL", "c2", "p2", "m2", "chk_b", "fam_b", "lab_b", "STARTED", 1000
        )
        ledger.commit_assessment(conn, "sess_001", "eval_b", "att_b", "asmt_b", "TIER_1", 0.85, "good", "hash_b")

        # SAME_CHECKPOINT with ADMISSIBLE_PAIR must fail check constraint
        with pytest.raises(sqlite3.IntegrityError):
            ledger.create_or_update_pair(
                conn,
                pair_id="pair_same",
                session_id="sess_001",
                case_id="case_1",
                evaluator_a_id="eval_a",
                evaluator_b_id="eval_b",
                committed_assessment_a_id="asmt_a",
                committed_assessment_b_id="asmt_b",
                provenance_state="SAME_CHECKPOINT",
                same_creator_flag=True,
                pair_status="ADMISSIBLE_PAIR",
            )


def test_active_attempt_composite_foreign_key() -> None:
    """active_attempt_id must belong to the exact same logical_eval_id."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        ledger.create_logical_evaluation(
            conn, "eval_1", "sess_001", "case_1", "EVALUATOR_A"
        )
        ledger.create_logical_evaluation(
            conn, "eval_2", "sess_001", "case_2", "EVALUATOR_B"
        )
        # Attempt belongs to eval_2
        ledger.create_dispatch_attempt(
            conn, "att_for_eval_2", "eval_2", 1, "INITIAL", "c1", "p1", "m1", "chk", "fam", "lab", "STARTED", 1000
        )

        cursor = conn.cursor()
        # Trying to set eval_1's active_attempt_id to att_for_eval_2 must fail composite FK at commit
        with pytest.raises(sqlite3.IntegrityError):
            try:
                cursor.execute(
                    "UPDATE logical_evaluations SET active_attempt_id = 'att_for_eval_2' WHERE logical_eval_id = 'eval_1';"
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                raise


def test_completed_logical_eval_and_session_terminal_immutability() -> None:
    """Completed logical evaluation and session cannot be updated."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        cursor = conn.cursor()
        cursor.execute("UPDATE evaluation_sessions SET status = 'COMPLETED' WHERE session_id = 'sess_001';")
        conn.commit()

        # Update on completed session must be rejected by trigger
        with pytest.raises(sqlite3.IntegrityError, match="Terminal evaluation sessions are immutable"):
            cursor.execute("UPDATE evaluation_sessions SET status = 'ACTIVE' WHERE session_id = 'sess_001';")


def test_atomic_commitment_fails_if_attempt_not_started() -> None:
    """commit_assessment must roll back completely if attempt is not in STARTED state."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_001", config_hash="cfg_hash_123")
        ledger.create_logical_evaluation(
            conn, "eval_a", "sess_001", "case_1", "EVALUATOR_A"
        )
        # Create attempt in RESERVED state (not STARTED)
        ledger.create_dispatch_attempt(
            conn, "att_res", "eval_a", 1, "INITIAL", "c1", "p1", "m1", "chk", "fam", "lab", "RESERVED", 1000
        )

        with pytest.raises(LedgerConstraintError, match="not in active STARTED state"):
            ledger.commit_assessment(
                conn, "sess_001", "eval_a", "att_res", "asmt_res", "TIER_1", 0.9, "good", "hash"
            )

        # Verify nothing was inserted into normalized_assessments or committed_assessments
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM normalized_assessments;")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT count(*) FROM committed_assessments;")
        assert cursor.fetchone()[0] == 0

