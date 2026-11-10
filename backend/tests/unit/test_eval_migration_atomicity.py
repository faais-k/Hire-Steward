"""Unit tests for atomic SQLite evaluation schema migration, pragma ordering, and rollback safety.

Verifies:
1. Successful migration restores PRAGMA foreign_keys = ON on the migration connection itself.
2. PRAGMA foreign_key_check returns zero violations on successful migration.
3. Composite primary key (session_id, event_seq) is verified.
4. Historical audit records and hash chains remain intact.
5. Injected failures at every stage (after temp table creation, after data copy, after drop old table, before final commit)
   trigger complete atomic rollback, preserving legacy schema, triggers, and data.
6. Foreign key enforcement is restored to 1 even after failed migration / rollback.
7. Active caller transactions are detected and rejected before changing pragma, preventing accidental commit.
8. executescript() is not called during schema migration.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import pytest

from backend.app.evaluation.ledger import (
    EvaluationLedger,
    LedgerIntegrityError,
    compute_audit_hash,
    verify_audit_chain,
)


def _create_legacy_database(db_path: str) -> tuple[str, str]:
    """Create a legacy database with single-column PK event_seq and 2 audit events."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute(
            """
            CREATE TABLE evaluation_sessions (
                session_id TEXT PRIMARY KEY,
                config_hash TEXT NOT NULL,
                start_time TIMESTAMP NOT NULL,
                status TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE logical_evaluations (
                logical_eval_id TEXT PRIMARY KEY
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE dispatch_attempts (
                attempt_id TEXT PRIMARY KEY
            );
            """
        )
        cur.execute(
            "INSERT INTO evaluation_sessions VALUES ('legacy_sess', 'leg_cfg_hash', '2026-10-31T00:00:00Z', 'ACTIVE');"
        )
        cur.execute(
            """
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
            """
        )
        cur.execute(
            """
            CREATE TRIGGER trg_audit_no_update
            BEFORE UPDATE ON evaluation_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Immutable audit log: UPDATE not permitted');
            END;
            """
        )
        cur.execute(
            """
            CREATE TRIGGER trg_audit_no_delete
            BEFORE DELETE ON evaluation_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Immutable audit log: DELETE not permitted');
            END;
            """
        )

        h1 = compute_audit_hash(
            "0" * 64, 1, "legacy_sess", "SESSION_ROOT", "SESSION_INITIALIZED", "{}", "2026-10-31T00:00:00Z"
        )
        cur.execute(
            """
            INSERT INTO evaluation_audit_events VALUES (
                1, 'ev_leg_1', 'legacy_sess', 'SESSION_ROOT', NULL, NULL, 'SESSION_INITIALIZED', '{}', ?, ?, '2026-10-31T00:00:00Z'
            );
            """,
            ("0" * 64, h1),
        )
        h2 = compute_audit_hash(
            h1, 2, "legacy_sess", "case_legacy", "ATTEMPT_RESERVED", '{"att":1}', "2026-10-31T00:01:00Z"
        )
        cur.execute(
            """
            INSERT INTO evaluation_audit_events VALUES (
                2, 'ev_leg_2', 'legacy_sess', 'case_legacy', NULL, NULL, 'ATTEMPT_RESERVED', '{"att":1}', ?, ?, '2026-10-31T00:01:00Z'
            );
            """,
            (h1, h2),
        )
        conn.commit()
    finally:
        conn.close()
    return h1, h2


def _make_uninitialized_ledger(db_path: str) -> EvaluationLedger:
    """Create an EvaluationLedger instance without running __init__ schema initialization."""
    ledger = EvaluationLedger.__new__(EvaluationLedger)
    ledger.db_path = db_path
    ledger._mem_conn = None
    return ledger


class HookedCursor(sqlite3.Cursor):
    """Cursor that intercepts execute calls to inject test failures."""

    def execute(self, sql: str, *args):
        hook = getattr(self.connection, "fail_on_sql_substr", None)
        if hook and hook in sql:
            raise RuntimeError(f"Simulated failure on SQL statement containing: '{hook}'")
        return super().execute(sql, *args)


class HookedConnection(sqlite3.Connection):
    """Connection that allows injecting failures at commit or cursor execution."""

    fail_on_sql_substr: str | None = None
    fail_on_commit: bool = False

    def cursor(self) -> HookedCursor:
        return super().cursor(factory=HookedCursor)

    def commit(self) -> None:
        if getattr(self, "fail_on_commit", False):
            raise RuntimeError("Simulated failure before final commit")
        return super().commit()


class NoExecutescriptConnection(sqlite3.Connection):
    """Connection that raises if executescript() is called."""

    def executescript(self, *args, **kwargs):
        raise AssertionError("executescript() was called inside schema migration path!")


# =========================================================================
# 1. SUCCESSFUL MIGRATION TESTS
# =========================================================================


def test_successful_migration_verifies_pragmas_on_migration_connection() -> None:
    """Verify that the exact migration connection has foreign_keys=1, no violations, and valid chain."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "mig_success.db")
        h1, h2 = _create_legacy_database(db_path)

        migration_conn = sqlite3.connect(db_path)
        try:
            cur = migration_conn.cursor()
            cur.execute("PRAGMA foreign_keys = ON;")

            ledger = _make_uninitialized_ledger(db_path=db_path)
            ledger._migrate_schema_if_needed(migration_conn)

            # 1. Migration connection transaction state
            assert migration_conn.in_transaction is False

            # 2. PRAGMA foreign_keys is verified enabled on the migration connection itself
            cur.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # 3. PRAGMA foreign_key_check returns zero violations
            cur.execute("PRAGMA foreign_key_check;")
            violations = cur.fetchall()
            assert len(violations) == 0

            # 4. User version updated
            cur.execute("PRAGMA user_version;")
            assert cur.fetchone()[0] == 2

            # 5. Composite primary key verified
            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            info = cur.fetchall()
            pks = sorted([row[1] for row in info if row[5] > 0])
            assert pks == ["event_seq", "session_id"]

            # 6. Historical records and hash chain intact
            cur.execute("SELECT event_seq, event_id, event_hash FROM evaluation_audit_events ORDER BY event_seq ASC;")
            rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0] == (1, "ev_leg_1", h1)
            assert rows[1] == (2, "ev_leg_2", h2)
            assert verify_audit_chain(migration_conn, "legacy_sess") is True

            # 7. Immutability triggers active on rebuilt table
            with pytest.raises(sqlite3.IntegrityError, match="Immutable audit log: UPDATE not permitted"):
                cur.execute("UPDATE evaluation_audit_events SET event_payload_json = '{}' WHERE event_seq = 1;")

            with pytest.raises(sqlite3.IntegrityError, match="Immutable audit log: DELETE not permitted"):
                cur.execute("DELETE FROM evaluation_audit_events WHERE event_seq = 1;")
        finally:
            migration_conn.close()

        # 8. Subsequent connections via EvaluationLedger.connect() have foreign keys verified
        full_ledger = EvaluationLedger(db_path=db_path)
        new_conn = full_ledger.connect()
        try:
            cur_new = new_conn.cursor()
            cur_new.execute("PRAGMA foreign_keys;")
            assert cur_new.fetchone()[0] == 1

            # Second session can be added and verify
            full_ledger.create_session(new_conn, session_id="sess_2", config_hash="cfg_2")
            full_ledger.append_audit_event(new_conn, "sess_2", "c2", "ATTEMPT_RESERVED", {"ok": True})
            assert verify_audit_chain(new_conn, "legacy_sess") is True
            assert verify_audit_chain(new_conn, "sess_2") is True
        finally:
            new_conn.close()


# =========================================================================
# 2. FAILURE INJECTION AND ROLLBACK TESTS
# =========================================================================


def test_failure_injection_after_temp_table_creation_rolls_back() -> None:
    """Failure during INSERT INTO migrating rolls back and preserves legacy table & triggers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "fail_temp_table.db")
        h1, h2 = _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path, factory=HookedConnection)
        try:
            conn.fail_on_sql_substr = "INSERT INTO evaluation_audit_events_migrating"

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(RuntimeError, match="Simulated failure on SQL statement containing"):
                ledger._migrate_schema_if_needed(conn)

            # Connection transaction state and foreign keys restored
            assert conn.in_transaction is False
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # Migrating table was rolled back and dropped
            cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='evaluation_audit_events_migrating';")
            assert cur.fetchone()[0] == 0

            # Legacy table preserved with single-column PK
            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            pks = [row[1] for row in cur.fetchall() if row[5] > 0]
            assert pks == ["event_seq"]

            # Data preserved
            cur.execute("SELECT count(*) FROM evaluation_audit_events;")
            assert cur.fetchone()[0] == 2

            # Immutability triggers restored
            with pytest.raises(sqlite3.IntegrityError, match="Immutable audit log: UPDATE not permitted"):
                cur.execute("UPDATE evaluation_audit_events SET event_payload_json = '{}' WHERE event_seq = 1;")
        finally:
            conn.close()


def test_failure_injection_after_data_copying_rolls_back() -> None:
    """Failure during DROP TABLE old table rolls back and preserves legacy table & triggers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "fail_drop_old.db")
        h1, h2 = _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path, factory=HookedConnection)
        try:
            conn.fail_on_sql_substr = "DROP TABLE evaluation_audit_events;"

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(RuntimeError, match="Simulated failure on SQL statement containing"):
                ledger._migrate_schema_if_needed(conn)

            assert conn.in_transaction is False
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # Migrating table is rolled back
            cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='evaluation_audit_events_migrating';")
            assert cur.fetchone()[0] == 0

            # Legacy table preserved
            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            pks = [row[1] for row in cur.fetchall() if row[5] > 0]
            assert pks == ["event_seq"]

            # Hash chain verified
            assert verify_audit_chain(conn, "legacy_sess") is True

            # Triggers active
            with pytest.raises(sqlite3.IntegrityError, match="Immutable audit log: UPDATE not permitted"):
                cur.execute("UPDATE evaluation_audit_events SET event_payload_json = '{}' WHERE event_seq = 1;")
        finally:
            conn.close()


def test_failure_injection_after_old_table_dropped_rolls_back() -> None:
    """Failure during RENAME TO old table rolls back and restores legacy table from transaction log."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "fail_rename.db")
        h1, h2 = _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path, factory=HookedConnection)
        try:
            conn.fail_on_sql_substr = "ALTER TABLE evaluation_audit_events_migrating RENAME TO"

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(RuntimeError, match="Simulated failure on SQL statement containing"):
                ledger._migrate_schema_if_needed(conn)

            assert conn.in_transaction is False
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # Old table restored by rollback
            cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='evaluation_audit_events';")
            assert cur.fetchone()[0] == 1

            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            pks = [row[1] for row in cur.fetchall() if row[5] > 0]
            assert pks == ["event_seq"]

            assert verify_audit_chain(conn, "legacy_sess") is True
        finally:
            conn.close()


def test_failure_injection_before_final_commit_rolls_back() -> None:
    """Failure during commit rolls back all changes and preserves legacy table & triggers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "fail_commit.db")
        h1, h2 = _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path, factory=HookedConnection)
        try:
            conn.fail_on_commit = True

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(RuntimeError, match="Simulated failure before final commit"):
                ledger._migrate_schema_if_needed(conn)

            assert conn.in_transaction is False
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # Schema version remains 0 (unmigrated)
            cur.execute("PRAGMA user_version;")
            assert cur.fetchone()[0] == 0

            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            pks = [row[1] for row in cur.fetchall() if row[5] > 0]
            assert pks == ["event_seq"]

            assert verify_audit_chain(conn, "legacy_sess") is True
        finally:
            conn.close()


def test_foreign_key_violations_abort_migration_and_rollback() -> None:
    """If data violates foreign key constraints during table rebuild, migration aborts and rolls back."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "fk_violation.db")
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE evaluation_sessions (
                    session_id TEXT PRIMARY KEY,
                    config_hash TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    status TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
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
                """
            )
            # Insert event referencing non-existent session_id 'ghost_session'
            cur.execute(
                """
                INSERT INTO evaluation_audit_events VALUES (
                    1, 'ev_bad', 'ghost_session', 'CASE_1', NULL, NULL, 'SESSION_INITIALIZED', '{}', '000', '111', '2026-10-31T00:00:00Z'
                );
                """
            )
            conn.commit()

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(LedgerIntegrityError, match="Foreign key violations detected during schema migration"):
                ledger._migrate_schema_if_needed(conn)

            # Rollback was clean and foreign keys restored
            assert conn.in_transaction is False
            cur.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # Table remained legacy
            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            pks = [row[1] for row in cur.fetchall() if row[5] > 0]
            assert pks == ["event_seq"]
        finally:
            conn.close()


# =========================================================================
# 3. TRANSACTION SAFETY AND CALLER ISOLATION TESTS
# =========================================================================


def test_active_transaction_on_connection_blocks_migration_without_committing() -> None:
    """An active caller transaction on connection causes migration to reject without committing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "caller_tx.db")
        _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            # Caller opens an uncommitted transaction
            cur.execute("INSERT INTO evaluation_sessions VALUES ('uncommitted_sess', 'cfg', '2026-11-01', 'ACTIVE');")
            assert conn.in_transaction is True

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(LedgerIntegrityError, match="Cannot migrate schema while a transaction is active"):
                ledger._migrate_schema_if_needed(conn)

            # The caller's transaction was NOT committed
            assert conn.in_transaction is True
            conn.rollback()

            # The uncommitted record was properly rolled back and discarded
            cur.execute("SELECT count(*) FROM evaluation_sessions WHERE session_id = 'uncommitted_sess';")
            assert cur.fetchone()[0] == 0
        finally:
            conn.close()


def test_active_transaction_blocks_init_schema_without_committing() -> None:
    """init_schema rejects active caller transaction without executing executescript()."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "caller_init_tx.db")
        _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO evaluation_sessions VALUES ('caller_sess', 'cfg', '2026-11-01', 'ACTIVE');")
            assert conn.in_transaction is True

            ledger = _make_uninitialized_ledger(db_path=db_path)
            with pytest.raises(LedgerIntegrityError, match="Cannot initialize schema while a transaction is active"):
                ledger.init_schema(conn)

            # Caller transaction was not committed by executescript
            assert conn.in_transaction is True
            conn.rollback()

            cur.execute("SELECT count(*) FROM evaluation_sessions WHERE session_id = 'caller_sess';")
            assert cur.fetchone()[0] == 0
        finally:
            conn.close()


def test_migration_never_calls_executescript() -> None:
    """Schema migration path uses only cursor.execute() and never calls conn.executescript()."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "no_executescript.db")
        _create_legacy_database(db_path)

        conn = sqlite3.connect(db_path, factory=NoExecutescriptConnection)
        try:
            ledger = _make_uninitialized_ledger(db_path=db_path)
            # Must execute without calling executescript
            ledger._migrate_schema_if_needed(conn)

            cur = conn.cursor()
            cur.execute("PRAGMA table_info(evaluation_audit_events);")
            pks = sorted([row[1] for row in cur.fetchall() if row[5] > 0])
            assert pks == ["event_seq", "session_id"]
            assert conn.in_transaction is False
            assert cur.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
        finally:
            conn.close()
