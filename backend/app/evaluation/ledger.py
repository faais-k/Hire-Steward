"""Isolated Evaluation Ledger implementation (Task 8.2 Checkpoint A).

Enforces:
1. SQLite WAL mode with mandatory PRAGMA foreign_keys = ON verification.
2. Complete relational schema and composite foreign keys enforcing evaluator ownership.
3. Immutability triggers protecting terminal attempts, assessments, commitments, and audit logs.
4. Five-step atomic assessment commitment transaction.
5. Append-only SHA-256 hash chaining with RFC 8785 canonical JSON formatting.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


class LedgerError(Exception):
    """Base exception for evaluation ledger operations."""


class LedgerIntegrityError(LedgerError):
    """Raised when ledger integrity, foreign keys, or audit verification fails."""


class LedgerConstraintError(LedgerError):
    """Raised when an illegal transition or constraint is violated."""


class AuditIntegrityError(LedgerIntegrityError):
    """Raised when an audit chain gap, broken hash linkage, or payload tamper is detected."""


LEDGER_DDL = """
PRAGMA foreign_keys = ON;

-- 1. Evaluation Sessions
CREATE TABLE IF NOT EXISTS evaluation_sessions (
    session_id TEXT PRIMARY KEY,
    config_hash TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('INITIALIZING', 'ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED'))
);

CREATE TRIGGER IF NOT EXISTS trg_session_terminal_immutable
BEFORE UPDATE ON evaluation_sessions
FOR EACH ROW
WHEN OLD.status IN ('COMPLETED', 'FAILED')
BEGIN
    SELECT RAISE(ABORT, 'Terminal evaluation sessions are immutable: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_session_no_delete
BEFORE DELETE ON evaluation_sessions
BEGIN
    SELECT RAISE(ABORT, 'Evaluation sessions are immutable: DELETE not permitted');
END;

-- 2. Logical Evaluations
CREATE TABLE IF NOT EXISTS logical_evaluations (
    logical_eval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES evaluation_sessions(session_id),
    case_id TEXT NOT NULL,
    evaluator_role TEXT NOT NULL CHECK(evaluator_role IN ('EVALUATOR_A', 'EVALUATOR_B')),
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'IN_FLIGHT', 'COMPLETED', 'FAILED', 'BLOCKED')),
    active_attempt_id TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_logical_eval_case UNIQUE(session_id, case_id, evaluator_role),
    CONSTRAINT uq_logical_eval_composite UNIQUE(logical_eval_id, session_id, case_id, evaluator_role),
    CONSTRAINT fk_logical_eval_active_attempt FOREIGN KEY (active_attempt_id, logical_eval_id)
        REFERENCES dispatch_attempts(attempt_id, logical_eval_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TRIGGER IF NOT EXISTS trg_logical_eval_terminal_immutable
BEFORE UPDATE ON logical_evaluations
FOR EACH ROW
WHEN OLD.status IN ('COMPLETED', 'FAILED', 'BLOCKED')
BEGIN
    SELECT RAISE(ABORT, 'Terminal logical evaluations are immutable: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_logical_eval_no_delete
BEFORE DELETE ON logical_evaluations
BEGIN
    SELECT RAISE(ABORT, 'Logical evaluations are immutable: DELETE not permitted');
END;

-- 3. Dispatch Attempts
CREATE TABLE IF NOT EXISTS dispatch_attempts (
    attempt_id TEXT PRIMARY KEY,
    logical_eval_id TEXT NOT NULL REFERENCES logical_evaluations(logical_eval_id),
    attempt_number INTEGER NOT NULL,
    attempt_type TEXT NOT NULL CHECK(attempt_type IN ('INITIAL', 'RETRY', 'FALLBACK')),
    candidate_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_alias TEXT NOT NULL,
    resolved_checkpoint_id TEXT NOT NULL,
    resolved_family_id TEXT NOT NULL,
    resolved_creator_entity TEXT NOT NULL,
    system_fingerprint TEXT,
    state TEXT NOT NULL CHECK(state IN (
        'RESERVED',
        'STARTED',
        'COMPLETED',
        'FAILED',
        'SUPERSEDED',
        'ABORTED_PRE_SOCKET',
        'AMBIGUOUS_IN_FLIGHT'
    )),
    terminal_reason TEXT CHECK(terminal_reason IN (
        'SUCCESS_NORMALIZED',
        'TIMEOUT_CLIENT',
        'HTTP_429_RATE_LIMIT',
        'HTTP_401_AUTH_REVOKED',
        'HTTP_403_ACCESS_RESTRICTED',
        'HTTP_5XX_SERVER_ERROR',
        'SCHEMA_VALIDATION_FAILURE',
        'CANDIDATE_INELIGIBLE_PRE_SOCKET',
        'CRASH_RECOVERY_ABORT',
        'CRASH_RECOVERY_AMBIGUOUS'
    )),
    reserved_tokens INTEGER NOT NULL,
    reported_input_tokens INTEGER,
    reported_output_tokens INTEGER,
    http_status INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    CONSTRAINT uq_attempt_step UNIQUE(logical_eval_id, attempt_number),
    CONSTRAINT uq_attempt_composite UNIQUE(attempt_id, logical_eval_id)
);

CREATE TRIGGER IF NOT EXISTS trg_attempt_no_reassign
BEFORE UPDATE OF logical_eval_id ON dispatch_attempts
BEGIN
    SELECT RAISE(ABORT, 'Attempt ownership cannot be reassigned to a different logical evaluation');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempt_terminal_immutable
BEFORE UPDATE ON dispatch_attempts
FOR EACH ROW
WHEN OLD.state IN ('COMPLETED', 'FAILED', 'SUPERSEDED', 'ABORTED_PRE_SOCKET', 'AMBIGUOUS_IN_FLIGHT')
BEGIN
    SELECT RAISE(ABORT, 'Terminal attempt record is immutable: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempt_no_delete
BEFORE DELETE ON dispatch_attempts
BEGIN
    SELECT RAISE(ABORT, 'Attempts are immutable: DELETE not permitted');
END;

-- 4. Normalized Assessments
CREATE TABLE IF NOT EXISTS normalized_assessments (
    assessment_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    logical_eval_id TEXT NOT NULL,
    match_tier TEXT NOT NULL CHECK(match_tier IN ('TIER_1', 'TIER_2', 'TIER_3', 'TIER_4')),
    match_score REAL NOT NULL CHECK(match_score >= 0.0 AND match_score <= 1.0),
    reasoning TEXT NOT NULL,
    raw_payload_hash TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL,
    CONSTRAINT fk_assessment_attempt FOREIGN KEY (attempt_id, logical_eval_id)
        REFERENCES dispatch_attempts(attempt_id, logical_eval_id),
    CONSTRAINT uq_assessment_composite UNIQUE(assessment_id, attempt_id, logical_eval_id)
);

CREATE TRIGGER IF NOT EXISTS trg_assessment_no_update
BEFORE UPDATE ON normalized_assessments
BEGIN
    SELECT RAISE(ABORT, 'Normalized assessments are immutable: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_assessment_no_delete
BEFORE DELETE ON normalized_assessments
BEGIN
    SELECT RAISE(ABORT, 'Normalized assessments are immutable: DELETE not permitted');
END;

-- 5. Committed Assessments
CREATE TABLE IF NOT EXISTS committed_assessments (
    logical_eval_id TEXT PRIMARY KEY REFERENCES logical_evaluations(logical_eval_id),
    assessment_id TEXT NOT NULL UNIQUE,
    attempt_id TEXT NOT NULL UNIQUE,
    committed_at TIMESTAMP NOT NULL,
    CONSTRAINT fk_commit_composite FOREIGN KEY (assessment_id, attempt_id, logical_eval_id)
        REFERENCES normalized_assessments(assessment_id, attempt_id, logical_eval_id),
    CONSTRAINT uq_commit_eval_assessment UNIQUE(logical_eval_id, assessment_id)
);

CREATE TRIGGER IF NOT EXISTS trg_committed_assessment_no_update
BEFORE UPDATE ON committed_assessments
BEGIN
    SELECT RAISE(ABORT, 'Committed assessments are immutable: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_committed_assessment_no_delete
BEFORE DELETE ON committed_assessments
BEGIN
    SELECT RAISE(ABORT, 'Committed assessments are immutable: DELETE not permitted');
END;

-- 6. Paired Evaluations
CREATE TABLE IF NOT EXISTS paired_evaluations (
    pair_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES evaluation_sessions(session_id),
    case_id TEXT NOT NULL,
    evaluator_a_id TEXT NOT NULL,
    evaluator_b_id TEXT NOT NULL,
    evaluator_a_role TEXT NOT NULL DEFAULT 'EVALUATOR_A' CHECK(evaluator_a_role = 'EVALUATOR_A'),
    evaluator_b_role TEXT NOT NULL DEFAULT 'EVALUATOR_B' CHECK(evaluator_b_role = 'EVALUATOR_B'),
    committed_assessment_a_id TEXT,
    committed_assessment_b_id TEXT,
    provenance_state TEXT NOT NULL CHECK(provenance_state IN (
        'SAME_CHECKPOINT',
        'SAME_FAMILY_DIFF_CHECKPOINT',
        'SAME_CREATOR_DIFF_FAMILY',
        'DIFFERENT_KNOWN_FAMILIES',
        'UNKNOWN_PROVENANCE'
    )),
    same_creator_flag BOOLEAN NOT NULL DEFAULT 0,
    owner_override_active BOOLEAN NOT NULL DEFAULT 0,
    pair_status TEXT NOT NULL CHECK(pair_status IN (
        'PENDING',
        'IN_PROGRESS',
        'ADMISSIBLE_PAIR',
        'FLAGGED_PAIR',
        'BLOCKED_NON_INDEPENDENT',
        'FAILED_PAIR_UNILATERAL_EXHAUSTION',
        'FAILED_PAIR_DUAL_EXHAUSTION'
    )),
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_paired_case UNIQUE(session_id, case_id),
    CONSTRAINT chk_pair_distinct_evaluators CHECK(evaluator_a_id != evaluator_b_id),
    CONSTRAINT fk_pair_eval_a FOREIGN KEY (evaluator_a_id, session_id, case_id, evaluator_a_role)
        REFERENCES logical_evaluations(logical_eval_id, session_id, case_id, evaluator_role),
    CONSTRAINT fk_pair_eval_b FOREIGN KEY (evaluator_b_id, session_id, case_id, evaluator_b_role)
        REFERENCES logical_evaluations(logical_eval_id, session_id, case_id, evaluator_role),
    CONSTRAINT fk_pair_commit_a FOREIGN KEY (evaluator_a_id, committed_assessment_a_id)
        REFERENCES committed_assessments(logical_eval_id, assessment_id),
    CONSTRAINT fk_pair_commit_b FOREIGN KEY (evaluator_b_id, committed_assessment_b_id)
        REFERENCES committed_assessments(logical_eval_id, assessment_id),
    CONSTRAINT chk_pair_commitments_present CHECK (
        (pair_status NOT IN ('ADMISSIBLE_PAIR', 'FLAGGED_PAIR')) OR
        (committed_assessment_a_id IS NOT NULL AND committed_assessment_b_id IS NOT NULL)
    ),
    CONSTRAINT chk_pair_admissibility_integrity CHECK (
        (pair_status != 'ADMISSIBLE_PAIR') OR
        (provenance_state = 'DIFFERENT_KNOWN_FAMILIES' AND same_creator_flag = 0)
    ),
    CONSTRAINT chk_pair_flagged_integrity CHECK (
        (pair_status != 'FLAGGED_PAIR') OR
        (owner_override_active = 1 AND provenance_state IN ('SAME_FAMILY_DIFF_CHECKPOINT', 'SAME_CREATOR_DIFF_FAMILY'))
    ),
    CONSTRAINT chk_pair_blocked_provenance CHECK (
        NOT (provenance_state IN ('SAME_CHECKPOINT', 'UNKNOWN_PROVENANCE') AND pair_status IN ('ADMISSIBLE_PAIR', 'FLAGGED_PAIR'))
    )
);

CREATE TRIGGER IF NOT EXISTS trg_pair_terminal_immutable
BEFORE UPDATE ON paired_evaluations
FOR EACH ROW
WHEN OLD.pair_status IN (
    'ADMISSIBLE_PAIR',
    'FLAGGED_PAIR',
    'BLOCKED_NON_INDEPENDENT',
    'FAILED_PAIR_UNILATERAL_EXHAUSTION',
    'FAILED_PAIR_DUAL_EXHAUSTION'
)
BEGIN
    SELECT RAISE(ABORT, 'Terminal paired evaluations are immutable: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_pair_no_delete
BEFORE DELETE ON paired_evaluations
BEGIN
    SELECT RAISE(ABORT, 'Paired evaluations are immutable: DELETE not permitted');
END;

-- 7. Append-Only Evaluation Audit Events
CREATE TABLE IF NOT EXISTS evaluation_audit_events (
    event_seq INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES evaluation_sessions(session_id),
    case_id TEXT NOT NULL,
    logical_eval_id TEXT REFERENCES logical_evaluations(logical_eval_id),
    attempt_id TEXT REFERENCES dispatch_attempts(attempt_id),
    event_type TEXT NOT NULL CHECK(event_type IN (
        'SESSION_INITIALIZED',
        'ATTEMPT_RESERVED',
        'ATTEMPT_STARTED',
        'ATTEMPT_COMPLETED',
        'ATTEMPT_FAILED',
        'ATTEMPT_SUPERSEDED',
        'LATE_RESPONSE_RECEIVED',
        'RESPONSE_FENCED_OUT',
        'ASSESSMENT_COMMITTED',
        'PAIR_PROVENANCE_EVALUATED',
        'PAIR_ADMISSIBLE_COMMITTED',
        'PAIR_FLAGGED_COMMITTED',
        'PAIR_BLOCKED_COLLISION',
        'PAIR_FAILED_UNILATERAL',
        'PAIR_FAILED_DUAL',
        'SESSION_COMPLETED',
        'SESSION_FAILED'
    )),
    event_payload_json TEXT NOT NULL,
    prev_event_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (session_id, event_seq)
);

CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
BEFORE UPDATE ON evaluation_audit_events
BEGIN
    SELECT RAISE(ABORT, 'Immutable audit log: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON evaluation_audit_events
BEGIN
    SELECT RAISE(ABORT, 'Immutable audit log: DELETE not permitted');
END;
"""


def compute_audit_hash(
    prev_event_hash: str,
    event_seq: int,
    session_id: str,
    case_id: str,
    event_type: str,
    canonical_payload_json: str,
    created_at_iso: str,
) -> str:
    """Compute SHA-256 hash for an evaluation audit event."""
    hash_input = (
        f"{prev_event_hash}|{event_seq}|{session_id}|{case_id}|{event_type}|{canonical_payload_json}|{created_at_iso}".encode(
            "utf-8"
        )
    )
    return hashlib.sha256(hash_input).hexdigest()


def verify_audit_chain(conn: sqlite3.Connection, session_id: str) -> bool:
    """Verify monotonic sequencing, hash linkage, and payload SHA-256 digests."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT event_seq, event_id, case_id, event_type, event_payload_json,
               prev_event_hash, event_hash, created_at
        FROM evaluation_audit_events
        WHERE session_id = ?
        ORDER BY event_seq ASC;
        """,
        (session_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return True

    expected_prev_hash = "0" * 64
    expected_seq = rows[0][0]

    for row in rows:
        event_seq, event_id, case_id, event_type, payload_json, prev_hash, current_hash, created_at = row

        # 1. Monotonic sequence verification
        if event_seq != expected_seq:
            raise AuditIntegrityError(f"Sequence gap detected: expected {expected_seq}, found {event_seq}")

        # 2. Hash-chain linkage verification
        if prev_hash != expected_prev_hash:
            raise AuditIntegrityError(f"Hash linkage broken at event {event_seq}")

        # 3. Canonical payload serialization (RFC 8785)
        parsed_payload = json.loads(payload_json)
        canonical_payload = json.dumps(parsed_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        # 4. Hash recomputation
        computed_hash = compute_audit_hash(
            prev_event_hash=prev_hash,
            event_seq=event_seq,
            session_id=session_id,
            case_id=case_id,
            event_type=event_type,
            canonical_payload_json=canonical_payload,
            created_at_iso=created_at,
        )

        if computed_hash != current_hash:
            raise AuditIntegrityError(
                f"Hash mismatch at event {event_seq}: computed {computed_hash}, stored {current_hash}"
            )

        expected_prev_hash = current_hash
        expected_seq += 1

    return True


class EvaluationLedger:
    """Manages an isolated SQLite evaluation database."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path == ":memory:":
            self._mem_conn: sqlite3.Connection | None = sqlite3.connect(":memory:")
            self._configure_conn(self._mem_conn)
            self.init_schema(self._mem_conn)
        else:
            self._mem_conn = None
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = self.connect()
            try:
                self.init_schema(conn)
            finally:
                conn.close()

    def _configure_conn(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA foreign_keys;")
        val = cursor.fetchone()[0]
        if val != 1:
            raise LedgerIntegrityError("Failed to enable SQLite foreign_keys constraint")

        if self.db_path != ":memory:":
            cursor.execute("PRAGMA journal_mode = WAL;")

    def connect(self) -> sqlite3.Connection:
        """Create a connection with PRAGMA foreign_keys = ON verified."""
        if self.db_path == ":memory:" and self._mem_conn is not None:
            return self._mem_conn

        conn = sqlite3.connect(self.db_path)
        self._configure_conn(conn)
        return conn

    def init_schema(self, conn: sqlite3.Connection) -> None:
        """Execute canonical SQLite DDL for all evaluation tables and triggers with safe migration."""
        if conn.in_transaction:
            raise LedgerIntegrityError(
                "Cannot initialize schema while a transaction is active on connection. "
                "Commit or roll back active transactions before initializing schema."
            )
        self._migrate_schema_if_needed(conn)
        conn.executescript(LEDGER_DDL)
        conn.commit()

    def _migrate_schema_if_needed(self, conn: sqlite3.Connection) -> None:
        """Check for and safely upgrade legacy single-column PK audit tables to composite PK."""
        # 1. Verify connection has no active transaction before changing foreign-key enforcement
        if conn.in_transaction:
            raise LedgerIntegrityError(
                "Cannot migrate schema while a transaction is active on the connection. "
                "Commit or roll back active transactions before migrating."
            )

        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='evaluation_audit_events';")
        if cursor.fetchone()[0] == 0:
            return

        cursor.execute("PRAGMA table_info(evaluation_audit_events);")
        info = cursor.fetchall()
        pks = [row[1] for row in info if row[5] > 0]
        # Only migrate if legacy schema where event_seq is sole primary key
        if pks != ["event_seq"]:
            return

        # 2. Execute PRAGMA foreign_keys = OFF outside transaction
        cursor.execute("PRAGMA foreign_keys = OFF;")
        # 3. Read the pragma back and verify it returns 0
        cursor.execute("PRAGMA foreign_keys;")
        fk_val = cursor.fetchone()[0]
        if fk_val != 0:
            raise LedgerIntegrityError(
                f"Failed to disable foreign_keys for schema migration: expected 0, got {fk_val}"
            )

        try:
            # 4. Begin explicit migration transaction
            cursor.execute("BEGIN IMMEDIATE;")

            # Drop triggers on old table so they do not fire or block during rebuild
            cursor.execute("DROP TRIGGER IF EXISTS trg_audit_no_update;")
            cursor.execute("DROP TRIGGER IF EXISTS trg_audit_no_delete;")

            # 5. Perform table-rebuild migration using individual cursor.execute calls
            cursor.execute(
                """
                CREATE TABLE evaluation_audit_events_migrating (
                    event_seq INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL REFERENCES evaluation_sessions(session_id),
                    case_id TEXT NOT NULL,
                    logical_eval_id TEXT REFERENCES logical_evaluations(logical_eval_id),
                    attempt_id TEXT REFERENCES dispatch_attempts(attempt_id),
                    event_type TEXT NOT NULL,
                    event_payload_json TEXT NOT NULL,
                    prev_event_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (session_id, event_seq)
                );
                """
            )
            cursor.execute(
                """
                INSERT INTO evaluation_audit_events_migrating (
                    event_seq, event_id, session_id, case_id, logical_eval_id,
                    attempt_id, event_type, event_payload_json, prev_event_hash,
                    event_hash, created_at
                ) SELECT event_seq, event_id, session_id, case_id, logical_eval_id,
                         attempt_id, event_type, event_payload_json, prev_event_hash,
                         event_hash, created_at
                FROM evaluation_audit_events;
                """
            )
            cursor.execute("DROP TABLE evaluation_audit_events;")
            cursor.execute("ALTER TABLE evaluation_audit_events_migrating RENAME TO evaluation_audit_events;")

            # Recreate indexes and triggers within the atomic transaction
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_session ON evaluation_audit_events(session_id, event_seq);"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_case ON evaluation_audit_events(case_id);")
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
                BEFORE UPDATE ON evaluation_audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'Immutable audit log: UPDATE not permitted');
                END;
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
                BEFORE DELETE ON evaluation_audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'Immutable audit log: DELETE not permitted');
                END;
                """
            )

            # 6. Execute PRAGMA foreign_key_check
            cursor.execute("PRAGMA foreign_key_check;")
            # 7. Fetch all returned violations
            violations = cursor.fetchall()
            # 8. If violations exist, abort migration and roll back
            if violations:
                raise LedgerIntegrityError(
                    f"Foreign key violations detected during schema migration: {violations}"
                )

            # 9. Update PRAGMA user_version within the migration transaction
            cursor.execute("PRAGMA user_version = 2;")

            # 10. Commit the transaction
            conn.commit()

        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            # If transaction is somehow still active (e.g. failed commit), ensure rollback
            if conn.in_transaction:
                conn.rollback()

            # 11. Verify conn.in_transaction is false
            if conn.in_transaction:
                raise LedgerIntegrityError(
                    "Connection unexpectedly remains in transaction after migration completion/rollback"
                )

            # 12. Execute PRAGMA foreign_keys = ON outside the transaction
            cursor.execute("PRAGMA foreign_keys = ON;")
            # 13. Read it back and verify it returns 1
            cursor.execute("PRAGMA foreign_keys;")
            fk_restored = cursor.fetchone()[0]
            if fk_restored != 1:
                raise LedgerIntegrityError(
                    f"Failed to restore foreign_keys to ON after schema migration: expected 1, got {fk_restored}"
                )

    def create_session(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        config_hash: str,
    ) -> None:
        """Initialize an evaluation session and append the genesis audit event."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO evaluation_sessions (session_id, config_hash, start_time, status)
            VALUES (?, ?, ?, 'ACTIVE');
            """,
            (session_id, config_hash, now_iso),
        )

        # Append genesis audit event
        self.append_audit_event(
            conn=conn,
            session_id=session_id,
            case_id="SESSION_ROOT",
            event_type="SESSION_INITIALIZED",
            payload={"config_hash": config_hash, "start_time": now_iso},
        )
        conn.commit()

    def create_logical_evaluation(
        self,
        conn: sqlite3.Connection,
        logical_eval_id: str,
        session_id: str,
        case_id: str,
        evaluator_role: Literal["EVALUATOR_A", "EVALUATOR_B"],
    ) -> None:
        """Register a logical evaluation row for an evaluator role."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO logical_evaluations (
                logical_eval_id, session_id, case_id, evaluator_role,
                status, active_attempt_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'IN_FLIGHT', NULL, ?, ?);
            """,
            (logical_eval_id, session_id, case_id, evaluator_role, now_iso, now_iso),
        )
        conn.commit()

    def create_dispatch_attempt(
        self,
        conn: sqlite3.Connection,
        attempt_id: str,
        logical_eval_id: str,
        attempt_number: int,
        attempt_type: Literal["INITIAL", "RETRY", "FALLBACK"],
        candidate_id: str,
        provider_id: str,
        model_alias: str,
        resolved_checkpoint_id: str,
        resolved_family_id: str,
        resolved_creator_entity: str,
        state: Literal["RESERVED", "STARTED", "COMPLETED", "FAILED", "SUPERSEDED", "ABORTED_PRE_SOCKET", "AMBIGUOUS_IN_FLIGHT"],
        reserved_tokens: int,
        system_fingerprint: str | None = None,
    ) -> None:
        """Create a dispatch attempt record."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO dispatch_attempts (
                attempt_id, logical_eval_id, attempt_number, attempt_type,
                candidate_id, provider_id, model_alias, resolved_checkpoint_id,
                resolved_family_id, resolved_creator_entity, system_fingerprint,
                state, terminal_reason, reserved_tokens, created_at, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?);
            """,
            (
                attempt_id,
                logical_eval_id,
                attempt_number,
                attempt_type,
                candidate_id,
                provider_id,
                model_alias,
                resolved_checkpoint_id,
                resolved_family_id,
                resolved_creator_entity,
                system_fingerprint,
                state,
                reserved_tokens,
                now_iso,
                now_iso if state == "STARTED" else None,
            ),
        )
        conn.commit()

    def commit_assessment(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        logical_eval_id: str,
        attempt_id: str,
        assessment_id: str,
        match_tier: Literal["TIER_1", "TIER_2", "TIER_3", "TIER_4"],
        match_score: float,
        reasoning: str,
        raw_payload_hash: str,
        case_id: str | None = None,
        citations_json: str = "[]",
    ) -> None:
        """Atomically commit an assessment with 5-step transaction and audit chaining."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.cursor()

        # Step 0: Resolve actual case_id from logical_evaluations
        cursor.execute(
            "SELECT case_id FROM logical_evaluations WHERE logical_eval_id = ?;",
            (logical_eval_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise LedgerConstraintError(f"Logical evaluation {logical_eval_id} not found")
        resolved_case_id = row[0]
        if case_id is not None and case_id != resolved_case_id:
            raise LedgerConstraintError(f"Case ID mismatch: expected {resolved_case_id}, got {case_id}")

        # Step 1: Update attempt state to COMPLETED
        cursor.execute(
            """
            UPDATE dispatch_attempts
            SET state = 'COMPLETED', terminal_reason = 'SUCCESS_NORMALIZED', completed_at = ?
            WHERE attempt_id = ? AND logical_eval_id = ? AND state = 'STARTED';
            """,
            (now_iso, attempt_id, logical_eval_id),
        )
        if cursor.rowcount != 1:
            raise LedgerConstraintError(
                f"Failed to complete attempt {attempt_id}: attempt is not in active STARTED state"
            )

        # Step 2: Insert into normalized_assessments
        cursor.execute(
            """
            INSERT INTO normalized_assessments (
                assessment_id, attempt_id, logical_eval_id,
                match_tier, match_score, reasoning, raw_payload_hash, citations_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                assessment_id,
                attempt_id,
                logical_eval_id,
                match_tier,
                match_score,
                reasoning,
                raw_payload_hash,
                citations_json,
                now_iso,
            ),
        )
        if cursor.rowcount != 1:
            raise LedgerConstraintError(f"Failed to insert normalized assessment {assessment_id}")

        # Step 3: Insert into committed_assessments
        cursor.execute(
            """
            INSERT INTO committed_assessments (
                logical_eval_id, assessment_id, attempt_id, committed_at
            ) VALUES (?, ?, ?, ?);
            """,
            (logical_eval_id, assessment_id, attempt_id, now_iso),
        )
        if cursor.rowcount != 1:
            raise LedgerConstraintError(f"Failed to insert committed assessment for {logical_eval_id}")

        # Step 4: Update logical_evaluations
        cursor.execute(
            """
            UPDATE logical_evaluations
            SET active_attempt_id = ?, status = 'COMPLETED', updated_at = ?
            WHERE logical_eval_id = ? AND status = 'IN_FLIGHT';
            """,
            (attempt_id, now_iso, logical_eval_id),
        )
        if cursor.rowcount != 1:
            raise LedgerConstraintError(f"Failed to transition logical evaluation {logical_eval_id} to COMPLETED")

        # Step 5: Append audit event inside same transaction with real case_id
        self.append_audit_event(
            conn=conn,
            session_id=session_id,
            case_id=resolved_case_id,
            event_type="ASSESSMENT_COMMITTED",
            payload={
                "logical_eval_id": logical_eval_id,
                "attempt_id": attempt_id,
                "assessment_id": assessment_id,
                "match_tier": match_tier,
                "match_score": match_score,
            },
            logical_eval_id=logical_eval_id,
            attempt_id=attempt_id,
        )

        conn.commit()

    def create_or_update_pair(
        self,
        conn: sqlite3.Connection,
        pair_id: str,
        session_id: str,
        case_id: str,
        evaluator_a_id: str,
        evaluator_b_id: str,
        committed_assessment_a_id: str | None,
        committed_assessment_b_id: str | None,
        provenance_state: Literal[
            "SAME_CHECKPOINT",
            "SAME_FAMILY_DIFF_CHECKPOINT",
            "SAME_CREATOR_DIFF_FAMILY",
            "DIFFERENT_KNOWN_FAMILIES",
            "UNKNOWN_PROVENANCE",
        ],
        same_creator_flag: bool,
        pair_status: Literal[
            "PENDING",
            "IN_PROGRESS",
            "ADMISSIBLE_PAIR",
            "FLAGGED_PAIR",
            "BLOCKED_NON_INDEPENDENT",
            "FAILED_PAIR_UNILATERAL_EXHAUSTION",
            "FAILED_PAIR_DUAL_EXHAUSTION",
        ],
        owner_override_active: bool = False,
    ) -> None:
        """Insert or update a paired evaluation row."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO paired_evaluations (
                pair_id, session_id, case_id, evaluator_a_id, evaluator_b_id,
                evaluator_a_role, evaluator_b_role,
                committed_assessment_a_id, committed_assessment_b_id,
                provenance_state, same_creator_flag, owner_override_active,
                pair_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'EVALUATOR_A', 'EVALUATOR_B', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, case_id) DO UPDATE SET
                committed_assessment_a_id = excluded.committed_assessment_a_id,
                committed_assessment_b_id = excluded.committed_assessment_b_id,
                provenance_state = excluded.provenance_state,
                same_creator_flag = excluded.same_creator_flag,
                owner_override_active = excluded.owner_override_active,
                pair_status = excluded.pair_status,
                updated_at = excluded.updated_at;
            """,
            (
                pair_id,
                session_id,
                case_id,
                evaluator_a_id,
                evaluator_b_id,
                committed_assessment_a_id,
                committed_assessment_b_id,
                provenance_state,
                1 if same_creator_flag else 0,
                1 if owner_override_active else 0,
                pair_status,
                now_iso,
            ),
        )
        conn.commit()

    def append_audit_event(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        case_id: str,
        event_type: str,
        payload: dict[str, Any],
        logical_eval_id: str | None = None,
        attempt_id: str | None = None,
    ) -> str:
        """Append a canonical SHA-256 hash-chained audit event."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_seq, event_hash
            FROM evaluation_audit_events
            WHERE session_id = ?
            ORDER BY event_seq DESC
            LIMIT 1;
            """,
            (session_id,),
        )
        last_row = cursor.fetchone()
        if last_row:
            next_seq = last_row[0] + 1
            prev_hash = last_row[1]
        else:
            next_seq = 1
            prev_hash = "0" * 64

        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        event_hash = compute_audit_hash(
            prev_event_hash=prev_hash,
            event_seq=next_seq,
            session_id=session_id,
            case_id=case_id,
            event_type=event_type,
            canonical_payload_json=canonical_payload,
            created_at_iso=now_iso,
        )
        event_id = f"ev_{uuid.uuid4().hex[:16]}"

        cursor.execute(
            """
            INSERT INTO evaluation_audit_events (
                event_seq, event_id, session_id, case_id, logical_eval_id,
                attempt_id, event_type, event_payload_json, prev_event_hash,
                event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                next_seq,
                event_id,
                session_id,
                case_id,
                logical_eval_id,
                attempt_id,
                event_type,
                canonical_payload,
                prev_hash,
                event_hash,
                now_iso,
            ),
        )
        return event_hash
