# ADR-0001 — Start with a Modular Monolith

- **Status:** Proposed
- **Date:** 2026-10-27
- **Decision owner:** Project owner

## Context

Hire-steward initially serves one local user, with a modest schedule, low daily application cap and relatively small evidence set. Its highest risk is correctness of state transitions and external actions, not serving high web request volume. Microservices add deployment, authentication, network, tracing and data-consistency complexity.

## Decision

Use one codebase with explicit domain modules and processes for API and background worker/scheduler. Use one PostgreSQL database. Define adapter/service boundaries so that background workers, provider integrations and file storage can be separated later if evidence supports it.

## Consequences

**Positive:** simpler local deployment, simpler transactions, easier debugging and coherent domain types.  
**Negative:** a large codebase can become coupled unless module boundaries are enforced; worker and API share release cycles initially.

## Revisit when

- Workload creates independent scaling requirements.
- Worker failure isolation requires separate deployment units.
- Multi-user tenancy is approved.
- Team size or deployment requirements justify independent services.

## Alternatives rejected for initial release

- Microservices: too much operational overhead without measured scale need.
- Serverless-only design: unsuitable for always-on local file monitoring and predictable local execution without further design.
