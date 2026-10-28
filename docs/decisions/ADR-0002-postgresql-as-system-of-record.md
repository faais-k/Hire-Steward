# ADR-0002 — PostgreSQL as the Initial System of Record

- **Status:** Proposed
- **Date:** 2026-10-27

## Context

The app needs durable transactional state for jobs, source checkpoints, candidate evidence, versioned assessments, application attempts and audit history. It may also benefit from full-text and vector retrieval. Multiple primary databases would add synchronization and backup complexity.

## Decision

Use PostgreSQL as the primary transactional system. Use PostgreSQL full-text search for lexical retrieval. Evaluate pgvector for semantic retrieval. Keep original files in a controlled file store referenced by stable content/version metadata.

## Consequences

**Positive:** transactions, constraints, migrations, one backup boundary for structured state, FTS and optional vector support.  
**Negative:** file store consistency still needs a protocol; vector performance and recall depend on selected model, filters and corpus size.

## Conditions

- Start with ordinary relational queries and full-text search.
- Add pgvector only with model/dimension metadata and an evaluation set.
- Start with exact vector search where corpus size permits; add approximate index only when measured latency/scale requires it.
- No extra vector database unless measured benchmarks or operational needs justify it.

## Revisit when

Measured query plans, corpus size, retrieval quality or remote storage requirements demonstrate PostgreSQL is no longer adequate.
