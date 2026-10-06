# Staged Migration with a Canonical Writer

Status: Accepted for implementation

## Context

The existing baseline uses PostgreSQL 15 and an earlier data model. A new explicit relationship model must preserve legitimate decisions and historical revocations while the product remains available. Combining model migration with a database engine upgrade would obscure failure causes and recovery boundaries.

## Decision

Separate data model migration from the PostgreSQL engine upgrade. Build and rehearse the model migration against the PostgreSQL 15 source baseline. PostgreSQL 18 is the new product environment; upgrading an existing database has an independent backup, restore and compatibility gate.

Use Alembic for expand and contract changes. A migration ledger tracks deterministic backfill batches, mapping versions, source progress and verification. Backfill is resumable and idempotent, never overwriting a newer target authorization decision. Invalid or ambiguous source relationships are quarantined for review instead of inferred into grants.

Roll out by organization: expand, backfill, compare decisions, shadow read, fence legacy writes, apply final delta, verify, switch to the canonical target and observe. Shadow reads never serve target decisions before the organization is cut over. After cutover, target authorization is authoritative and legacy writers remain fenced.

Rollback after cutover can restore only an application version compatible with the target schema and lock protocol. Do not downgrade the authorization schema, replay older grant state or reenable a legacy writer. Contract occurs only after the rollback window and every required organization transition are verified.

## Alternatives considered

A single cutover increases the impact of an unknown mapping error. Unfenced dual writing permits race conditions and divergent revocation state. Reverting an old application and schema together can resurrect access that was intentionally revoked after migration.

## Consequences

The migration has explicit checkpoints and requires decision equivalence evidence, not only row counts. Per organization fencing and mapping make the rollout more deliberate but reduce blast radius. Once an organization crosses the canonical writer boundary, recovery follows the target model.

## Acceptance evidence

G5 demonstrates resumable backfill, reviewed mismatches, final delta, legacy write rejection and target compatible application rollback. Engine upgrade rehearsal is a separate operational artifact. See [Migration phases](../diagrams/migration-phases.mmd).
