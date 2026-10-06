# Ordered Locks and Fresh Authorization Statements

Status: Accepted for implementation

## Context

Critical use must not create durable output from a policy decision that became stale while waiting for revocation. Concurrent grant edits, invitation acceptance, entitlement changes and publication also need one consistent lock order. A stronger isolation label by itself does not define the desired use and revocation ordering.

## Decision

Use explicit `READ COMMITTED` transactions on the primary. Lock extant affected resources in UUID order, then acquire the organization's transaction scoped advisory lock, then membership rows in UUID order, then invitation rows in UUID order when needed. Critical consumption uses shared resource and organization locks. Access mutations use shared resource and exclusive organization locks. Publisher updates use an exclusive resource row lock and never acquire an organization lock.

Membership only mutations acquire organization and membership locks without acquiring resources afterwards. Advisory keys use the organization's stable database assigned key. Separate lock acquisition from the next policy SELECT, recompute database time after waiting, and refresh prelock ORM state. Every authoritative writer and compatibility adapter participates.

Before taking global resource locks, perform a read-only scoped visibility check for the actor, organization, project and referenced entitlement or consumer grant. This conceals both known foreign IDs and unknown IDs consistently. The preliminary read never authorizes a mutation or durable output. After canonical locks are obtained, reread all authority and state predicates; revocation or expiry during the interval must still deny the operation. Successful historical receipts are checked after current actor authority and before new version or lifecycle transitions.

Serialize a command receipt binding after resource and organization locks, before subsequent target row mutations. The implementation uses the two-integer advisory namespace `17291` with a hash of actor, organization, operation and key. This also orders duplicate report creation commands, whose domain transaction holds a shared organization lock. Matching receipt lookup uses a fresh statement after waiting. A hash collision only serializes unrelated commands; it never shares their receipts, which retain the complete composite key and request hash.

Catalog creation uses a separate two-integer namespace `17292` and a hash of the stable external key before looking up and locking its resource row. This handles the absence of a row on first publication. The unique external-key constraint remains the integrity backstop. Catalog transactions acquire no organization lock, and repeated publication receipts are checked before expected-version or lifecycle validation. Terminal archive cannot be reversed by a new publication or a replay.

Use bounded deadlines. A timeout aborts the whole operation; retryable database failures restart the complete use case with the original actor scoped idempotency key. No external delivery or long computation runs inside this transaction.

## Alternatives and consequences

Optimistic versions remain necessary for editors but cannot protect a check followed by output creation. Repeatable Read or Serializable would need a different, tested postwait snapshot protocol and retry behavior; they are not a drop in substitution. An advisory lock obtained within the same long SELECT cannot make that statement's earlier snapshot fresh.

The organization lock deliberately serializes access changes, trading some tenant write concurrency for an understandable invariant. Measure lock waits before introducing finer locks. The protocol does not protect arbitrary SQL outside the application; database privileges and migration fencing restrict those writers.

Unique constraints alone could arbitrate creation, but handling an insert loser requires a savepoint or a conflict-aware insert followed by fresh row and receipt reads. The external-key mutex makes that lifecycle explicit with the same bounded lock timeout. It is local database coordination, not a distributed lock service. Permission and catalog namespaces use the two-integer key space; organization keys use PostgreSQL's distinct one-bigint key space.

## Acceptance evidence

The executed [snapshot probe](../../scripts/transaction_probe.py) demonstrated stale same statement policy and fresh subsequent statement policy after a controlled advisory wait on PostgreSQL 18.6. It establishes the database primitive. The local application's separate transaction schedules and recorded outcomes are linked through [Validation](../VALIDATION.md) and the [implementation map](../IMPLEMENTATION_MAP.md); the probe alone does not prove the complete application protocol or a PostgreSQL 15 live transition.

Execute [transaction schedules](../DISTRIBUTED_CORRECTNESS.md#race-schedules-and-exact-outcomes) on real PostgreSQL 15 transition and PostgreSQL 18 target connections. Prove fresh policy after wait, opposite resource input order, grant versus disable, publisher archive, staff expiry, complete rollback and membership version conflict.
