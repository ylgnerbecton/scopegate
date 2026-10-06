# Durable Delivery with Primary Authorization

Status: Accepted for implementation

## Context

An external provider can accept a message while its caller loses the acknowledgment. A worker can crash after claiming or sending. A database replica or cached permission can also remain stale after a primary revocation. These failures require distinct guarantees rather than an exactly once claim.

## Decision

Invitation creation and encrypted outbox intent share a database transaction. Workers claim bounded batches with row locks and a durable expiring lease, commit, and then call the adapter outside the transaction. A new lease token identifies each claim; conditional acknowledgment and retry updates cannot be performed by a stale claimant. Cumulative and generation attempts, availability time, retry deadline and visible failed state bound recovery. A generation permits at most eight claims within 30 minutes and before invitation expiry. Reviewed requeue preserves the delivery key and cumulative history. Clear sensitive payload under retention while preserving safe delivery evidence.

The database guarantees one acceptance transition and a committed receipt. External delivery is at least once; stable provider idempotency prevents repeated sends only when the actual provider supports it. A local adapter supplies synthetic evidence rather than proof about a production delivery service. No broker or generic inbox is required for the current boundary.

Read sessions, current access state and command receipts from the primary. Frontend and metadata caches never authorize protected actions. Future replica reads are restricted to an explicitly stale tolerant projection. Background consumers reauthorize each bounded output and delivery; queue admission is not an enduring permission.

Keep matching response replay for at least 24 hours and constrain automatic retry to that window. Current identity and authority are checked before receipt replay; a reused key and changed fingerprint conflicts. After the guaranteed window, reconcile unknown outcomes rather than retrying under a fresh key.

## Alternatives and consequences

Synchronous delivery inside the issuing transaction cannot make external effects rollback with PostgreSQL and prolongs lock holding. Process memory callbacks cannot survive crashes. A broker can be added when measured delivery throughput or independent consumers justify its operating cost, while the transactional outbox remains the source of intent.

The design permits duplicate notifications after send and acknowledgment failure unless the provider contract deduplicates. Primary policy reads incur database work but preserve revocation semantics. Session, provider and key invalidation remain distinct and have explicit exposure budgets in [Distributed correctness](../DISTRIBUTED_CORRECTNESS.md#identity-keys-and-invalidation-budget).

## Acceptance evidence

Prove abandoned claim recovery, send before acknowledgment crash, stale lease acknowledgment, retry exhaustion, payload retention, matching commit retry and changed fingerprint conflict. Simulate replica lag and cached grants to show neither can authorize output after primary revocation. Verify current policy at each supported background boundary.
