"""Unit tests for Evaluation Audit Chain Integrity (Task 8.2 Checkpoint A).

Verifies:
1. Monotonic sequence numbers and genesis hash initialization ("0" * 64).
2. Hash-chain linkage across evaluation audit events.
3. Immutability triggers blocking UPDATE and DELETE on audit log.
4. Full-chain verification detecting tampered payloads or broken links.
"""

from __future__ import annotations

import sqlite3
import pytest

from backend.app.evaluation.ledger import (
    AuditIntegrityError,
    EvaluationLedger,
    verify_audit_chain,
)


def test_audit_event_genesis_and_chaining() -> None:
    """Verify genesis event has 64 zeros and subsequent events chain hashes correctly."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_chain_1", config_hash="cfg_hash_test")

        # Session initialization automatically appends event 1 (genesis)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_seq, prev_event_hash, event_hash, event_type
            FROM evaluation_audit_events
            WHERE session_id = 'sess_chain_1'
            ORDER BY event_seq ASC;
            """
        )
        row = cursor.fetchone()
        assert row is not None
        seq, prev_hash, ev_hash, ev_type = row
        assert seq == 1
        assert prev_hash == "0" * 64
        assert len(ev_hash) == 64
        assert ev_type == "SESSION_INITIALIZED"

        # Append another event
        second_hash = ledger.append_audit_event(
            conn,
            session_id="sess_chain_1",
            case_id="case_001",
            event_type="ATTEMPT_RESERVED",
            payload={"attempt_id": "att_01", "tokens": 1500},
        )

        cursor.execute(
            """
            SELECT event_seq, prev_event_hash, event_hash
            FROM evaluation_audit_events
            WHERE session_id = 'sess_chain_1' AND event_seq = 2;
            """
        )
        row2 = cursor.fetchone()
        assert row2 is not None
        assert row2[0] == 2
        assert row2[1] == ev_hash  # Chains to previous event hash!
        assert row2[2] == second_hash

        # Verify full chain passes
        assert verify_audit_chain(conn, session_id="sess_chain_1") is True


def test_audit_log_triggers_reject_update_and_delete() -> None:
    """Audit events cannot be modified or deleted."""
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_chain_2", config_hash="cfg_hash_test")

        cursor = conn.cursor()
        with pytest.raises(sqlite3.IntegrityError, match="Immutable audit log: UPDATE not permitted"):
            cursor.execute("UPDATE evaluation_audit_events SET event_type = 'TAMPERED';")

        with pytest.raises(sqlite3.IntegrityError, match="Immutable audit log: DELETE not permitted"):
            cursor.execute("DELETE FROM evaluation_audit_events WHERE event_seq = 1;")


def test_tamper_detection_in_audit_chain() -> None:
    """If an attacker attempts to tamper with payload (simulated by disabling trigger temporarily or raw check),
    verify_audit_chain detects it and raises AuditIntegrityError.
    """
    ledger = EvaluationLedger(db_path=":memory:")
    with ledger.connect() as conn:
        ledger.create_session(conn, session_id="sess_chain_3", config_hash="cfg_hash_test")
        ledger.append_audit_event(
            conn,
            session_id="sess_chain_3",
            case_id="case_001",
            event_type="ATTEMPT_RESERVED",
            payload={"candidate_id": "c1"},
        )

        # Drop the update trigger just to simulate physical/offline tampering
        cursor = conn.cursor()
        cursor.execute("DROP TRIGGER trg_audit_no_update;")
        cursor.execute(
            """
            UPDATE evaluation_audit_events
            SET event_payload_json = '{\"candidate_id\":\"tampered_hacker\"}'
            WHERE event_seq = 2;
            """
        )
        conn.commit()

        # Chain verification must catch the hash mismatch
        with pytest.raises(AuditIntegrityError, match="Hash mismatch at event 2"):
            verify_audit_chain(conn, session_id="sess_chain_3")
