# Modular Monolith with One Database

Status: Accepted for implementation

## Context

Memberships, resource grants, invitation acceptance and audit evidence must change atomically. The first product increment needs clear ownership and demonstrable tenant isolation without distributed transaction or delivery infrastructure.

## Decision

Use a modular monolith built with Python 3.12 and FastAPI, SQLAlchemy 2, psycopg 3 and Alembic. Use PostgreSQL 18 for new local and product environments. React, TypeScript, Vite and TanStack Query provide the web interface. One database stores domain state, sessions, audit events, delivery outbox and migration ledger.

Modules expose application use cases and narrow ports. A service owns the unit of work; repositories never commit. The HTTP process and delivery worker can use the same versioned application image. The first implementation has no Redis, event broker, cluster orchestrator or external policy engine. Alembic remains the schema migration mechanism.

## Alternatives considered

| Alternative | Reason for deferral |
| --- | --- |
| Separate access, invitation and audit services | Adds partial failure and consistency work before an independent scaling or ownership need exists |
| External policy engine | Requires another operational boundary and synchronized relationship data |
| Generic framework for all domain operations | Hides invariants behind abstractions that do not yet serve multiple distinct needs |

## Consequences

The database transaction provides a practical consistency boundary. Deployment and local reproduction remain small. Modules still require dependency discipline and independent tests; a single deployable does not justify shared mutable state or route level business logic.

The application and database initially scale together. The outbox separates delivery timing without separating domain ownership. Extract a module only when measured load, an independent lifecycle or a real ownership boundary justifies the additional operational cost. Preserve the public use case contract and transactional invariants during any extraction.

## Acceptance evidence

G1 checks module and contract consistency. G3 proves atomic mutations and delivery behavior. G6 establishes workload and recovery budgets. No scale claim is accepted without measurements.
