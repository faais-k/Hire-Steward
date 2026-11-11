# ADR-0019 — Durable Database-Backed Task Worker, Atomic Queue Lease & Local Scheduler

- **Status:** Accepted and fully verified in Milestone 2
- **Date:** 2026-11-10

## Context

Hire-Steward requires asynchronous processing for document ingestion, candidate-job matching, resume tailoring, and scheduled maintenance. Introducing Redis, Celery, RabbitMQ, or external brokers introduces unnecessary operational overhead and failure modes into a local-first single-user application. 

A durable database-backed task engine must:
1. Guarantee exactly-once or at-least-once execution with atomic lease claiming across concurrent workers.
2. Prevent double-claiming race conditions under both PostgreSQL (`SELECT ... FOR UPDATE SKIP LOCKED`) and SQLite (atomic conditional update).
3. Handle concurrent idempotency collisions gracefully via rollback savepoint handling.
4. Provide heartbeat tracking, lease renewal, and zombie worker reaping.
5. Provide a timezone-aware (`Asia/Kolkata`) local scheduler and safe operator lifecycle controls.

## Decision

1. **Alembic Migration `0010_background_tasks.py`**:
   - `background_tasks`: Stores task identity, type, status (`PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`), priority, payload, idempotency key, retry count, max retries, timeout, lease expiration, worker ID, execution timestamps, and error message.
   - `background_workers`: Tracks worker instances, worker status (`ACTIVE`, `PAUSED`, `STOPPED`), heartbeat timestamps, active task ID, and registration metadata.
   - `background_task_runs`: Audit trail tracking run attempts, duration, exit statuses, and error traces.

2. **Dialect-Aware Atomic Lease Claiming**:
   - On PostgreSQL: Uses `SELECT id FROM background_tasks WHERE status = 'PENDING' AND run_at <= :now ORDER BY priority DESC, created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1`.
   - On SQLite: Uses an atomic conditional `UPDATE background_tasks SET status = 'RUNNING', worker_id = :worker_id, locked_until = :lease WHERE id = :candidate_id AND status = 'PENDING'`.

3. **Concurrency & Failure Protection**:
   - `enqueue_task` handles idempotency collisions with transactional savepoint rollback, safely returning the existing task record without aborting the transaction.
   - `reap_zombies` identifies dead workers (heartbeat overdue > 60s), resets their running tasks to `PENDING` (or `FAILED` if retry exhausted), and updates the dead worker's status to `STOPPED`.
   - Worker execution operates within timeout envelopes with cooperative heartbeat extension.

4. **Local Scheduler**:
   - Implements `LocalScheduler` with configured schedule slots (default: 10:00, 17:00, and 22:00 Asia/Kolkata).
   - Manages periodic task dispatching while honoring system pause/resume state.

5. **Operator Lifecycle API**:
   - `POST /api/v1/system/worker/pause` & `POST /api/v1/system/worker/resume`.
   - `GET /api/v1/system/tasks` (with status, type, and pagination filters).
   - `POST /api/v1/system/tasks/{id}/retry` & `POST /api/v1/system/tasks/{id}/cancel`.

## Consequences

- Zero external message broker dependencies (no Redis, Celery, or RabbitMQ).
- Crash-safe durability: all task state resides in the primary database with full transaction isolation.
- Fully verified under multi-threaded SQLite concurrency (50 tasks across 8 threads) and PostgreSQL integration tests.
- System diagnostics route surfaces honest worker states and dead worker detection.
