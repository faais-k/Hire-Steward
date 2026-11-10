"""Unit tests for Multi-Session SQLite Evaluation Ledger and Schema Upgrades (Task 8.2 Checkpoint A).

Verifies:
1. Two sessions can initialize in one database.
2. Multiple events can be appended to both sessions independently.
3. Session-specific sequence numbers start at 1 and remain monotonic.
4. Both independent hash chains verify via verify_audit_chain().
5. One session's events cannot corrupt the other session's hash chain.
6. Existing databases created with legacy single-column PK can be upgraded without losing historical audit data.
7. Reopening the database preserves all events and verification results.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import pytest

from backend.app.evaluation.ledger import (
    AuditIntegrityError,
    EvaluationLedger,
    compute_audit_hash,
    verify_audit_chain,
)


def test_two_sessions_can_coexist_in_one_database() -> None:
    """Two sessions initialize and coexist in one database without sequence collision."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "multi_session.db")
        ledger = EvaluationLedger(db_path=db_path)

        conn = ledger.connect()
        try:
            # Session 1
            ledger.create_session(conn, session_id="sess_alpha", config_hash="cfg_alpha_hash")
            # Session 2 in the same database file
            ledger.create_session(conn, session_id="sess_beta", config_hash="cfg_beta_hash")

            cur = conn.cursor()
            cur.execute("SELECT session_id, event_seq, event_type FROM evaluation_audit_events ORDER BY session_id, event_seq;")
            rows = cur.fetchall()

            assert len(rows) == 2
            # Both start at event_seq = 1
            assert rows[0] == ("sess_alpha", 1, "SESSION_INITIALIZED")
            assert rows[1] == ("sess_beta", 1, "SESSION_INITIALIZED")

            assert verify_audit_chain(conn, session_id="sess_alpha") is True
            assert verify_audit_chain(conn, session_id="sess_beta") is True
        finally:
            conn.close()


def test_multiple_events_appended_to_both_sessions() -> None:
    """Interleaved event appending across sessions preserves session-specific sequence numbers and chains."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "interleaved.db")
        ledger = EvaluationLedger(db_path=db_path)

        conn = ledger.connect()
        try:
            ledger.create_session(conn, session_id="s1", config_hash="cfg1")
            ledger.create_session(conn, session_id="s2", config_hash="cfg2")

            # Interleave events
            ledger.append_audit_event(conn, "s1", "case_1", "ATTEMPT_RESERVED", {"attempt": "a1"})
            ledger.append_audit_event(conn, "s2", "case_2", "ATTEMPT_RESERVED", {"attempt": "b1"})
            ledger.append_audit_event(conn, "s1", "case_1", "ATTEMPT_STARTED", {"attempt": "a1"})
            ledger.append_audit_event(conn, "s2", "case_2", "ATTEMPT_STARTED", {"attempt": "b1"})
            ledger.append_audit_event(conn, "s1", "case_1", "ATTEMPT_COMPLETED", {"attempt": "a1"})

            cur = conn.cursor()
            cur.execute("SELECT event_seq, event_type FROM evaluation_audit_events WHERE session_id = 's1' ORDER BY event_seq ASC;")
            s1_events = cur.fetchall()
            assert len(s1_events) == 4
            assert [e[0] for e in s1_events] == [1, 2, 3, 4]

            cur.execute("SELECT event_seq, event_type FROM evaluation_audit_events WHERE session_id = 's2' ORDER BY event_seq ASC;")
            s2_events = cur.fetchall()
            assert len(s2_events) == 3
            assert [e[0] for e in s2_events] == [1, 2, 3]

            assert verify_audit_chain(conn, session_id="s1") is True
            assert verify_audit_chain(conn, session_id="s2") is True
        finally:
            conn.close()


def test_session_chains_are_strictly_isolated() -> None:
    """Corrupting event payload in session 1 does NOT invalidate session 2's hash chain."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "isolation.db")
        ledger = EvaluationLedger(db_path=db_path)

        conn = ledger.connect()
        try:
            ledger.create_session(conn, session_id="s_clean", config_hash="cfg_clean")
            ledger.create_session(conn, session_id="s_target", config_hash="cfg_target")

            ledger.append_audit_event(conn, "s_clean", "case_0", "ATTEMPT_RESERVED", {"ok": True})
            ledger.append_audit_event(conn, "s_target", "case_0", "ATTEMPT_RESERVED", {"ok": True})

            # Temporarily drop trigger to simulate physical bit rot / tampering in s_target only
            cur = conn.cursor()
            cur.execute("DROP TRIGGER trg_audit_no_update;")
            cur.execute("UPDATE evaluation_audit_events SET event_payload_json = '{\"tampered\": true}' WHERE session_id = 's_target' AND event_seq = 2;")
            conn.commit()

            # s_clean must remain 100% valid
            assert verify_audit_chain(conn, session_id="s_clean") is True

            # s_target must detect tampering
            with pytest.raises(AuditIntegrityError, match="Hash mismatch at event 2"):
                verify_audit_chain(conn, session_id="s_target")
        finally:
            conn.close()


def test_legacy_database_migration_preserves_historical_records_and_hash_chains() -> None:
    """Databases created with old single-column PK (event_seq) are safely upgraded without loss."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        legacy_db_path = os.path.join(tmp_dir, "legacy_audit.db")

        # Manually create legacy database schema
        raw_conn = sqlite3.connect(legacy_db_path)
        raw_conn.execute("""
        CREATE TABLE evaluation_sessions (
            session_id TEXT PRIMARY KEY,
            config_hash TEXT NOT NULL,
            start_time TIMESTAMP NOT NULL,
            status TEXT NOT NULL
        );
        """)
        raw_conn.execute("INSERT INTO evaluation_sessions VALUES ('legacy_sess', 'leg_cfg', '2026-10-31T00:00:00Z', 'ACTIVE');")
        raw_conn.execute("""
        CREATE TABLE evaluation_audit_events (
            event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL REFERENCES evaluation_sessions(session_id),
            case_id TEXT NOT NULL,
            logical_eval_id TEXT,
            attempt_id TEXT,
            event_type TEXT NOT NULL,
            event_payload_json TEXT NOT NULL,
            prev_event_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        );
        """)
        h1 = compute_audit_hash("0" * 64, 1, "legacy_sess", "SESSION_ROOT", "SESSION_INITIALIZED", "{}", "2026-10-31T00:00:00Z")
        raw_conn.execute("""
        INSERT INTO evaluation_audit_events VALUES (
            1, 'ev_leg_1', 'legacy_sess', 'SESSION_ROOT', NULL, NULL, 'SESSION_INITIALIZED', '{}', ?, ?, '2026-10-31T00:00:00Z'
        );
        """, ("0" * 64, h1))
        h2 = compute_audit_hash(h1, 2, "legacy_sess", "case_legacy", "ATTEMPT_RESERVED", "{\"att\":1}", "2026-10-31T00:01:00Z")
        raw_conn.execute("""
        INSERT INTO evaluation_audit_events VALUES (
            2, 'ev_leg_2', 'legacy_sess', 'case_legacy', NULL, NULL, 'ATTEMPT_RESERVED', '{\"att\":1}', ?, ?, '2026-10-31T00:01:00Z'
        );
        """, (h1, h2))
        raw_conn.commit()
        raw_conn.close()

        # Instantiate EvaluationLedger on legacy DB, triggering migration
        migrated_ledger = EvaluationLedger(db_path=legacy_db_path)

        conn = migrated_ledger.connect()
        try:
            # 1. Historical data preserved
            cur = conn.cursor()
            cur.execute("SELECT event_seq, event_id, event_hash FROM evaluation_audit_events WHERE session_id = 'legacy_sess' ORDER BY event_seq ASC;")
            rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == 1 and rows[0][1] == "ev_leg_1" and rows[0][2] == h1
            assert rows[1][0] == 2 and rows[1][1] == "ev_leg_2" and rows[1][2] == h2

            # 2. Historical hash chain verifies
            assert verify_audit_chain(conn, session_id="legacy_sess") is True

            # 3. Primary key is now composite (session_id, event_seq)
            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            info = cur.fetchall()
            pks = sorted([row[1] for row in info if row[5] > 0])
            assert pks == ["event_seq", "session_id"]

            # 4. A second session can now be added and coexist!
            migrated_ledger.create_session(conn, session_id="new_session_post_migration", config_hash="new_cfg")
            migrated_ledger.append_audit_event(conn, "new_session_post_migration", "case_new", "ATTEMPT_RESERVED", {"att": 2})

            assert verify_audit_chain(conn, session_id="legacy_sess") is True
            assert verify_audit_chain(conn, session_id="new_session_post_migration") is True
        finally:
            conn.close()


def test_reopening_disk_database_preserves_events_and_verification() -> None:
    """Reopening disk database retains all records and verification succeeds across restarts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "reopen.db")
        ledger1 = EvaluationLedger(db_path=db_path)

        conn1 = ledger1.connect()
        try:
            ledger1.create_session(conn1, "sess_1", "cfg_1")
            ledger1.append_audit_event(conn1, "sess_1", "c1", "ATTEMPT_RESERVED", {"k": 1})
            ledger1.create_session(conn1, "sess_2", "cfg_2")
            ledger1.append_audit_event(conn1, "sess_2", "c2", "ATTEMPT_RESERVED", {"k": 2})
            conn1.commit()
        finally:
            conn1.close()

        # Reopen in new ledger instance
        ledger2 = EvaluationLedger(db_path=db_path)
        conn2 = ledger2.connect()
        try:
            cur = conn2.cursor()
            cur.execute("SELECT count(*) FROM evaluation_audit_events;")
            assert cur.fetchone()[0] == 4

            assert verify_audit_chain(conn2, session_id="sess_1") is True
            assert verify_audit_chain(conn2, session_id="sess_2") is True
        finally:
            conn2.close()
