# Scopegate Transaction and Delivery Correctness

Scopegate's first runtime has one application boundary and one database, but concurrent requests, workers, provider calls and uncertain network outcomes still create distributed failure modes. This design makes admission, revocation, delivery and retry guarantees explicit. Runtime tests exercise the local lock, version, revocation and lease protocol. Structural checks remain distinct from those application proofs; live host/provider guarantees require separate evidence.

## Isolation and time contract

Authorization transactions explicitly use `READ COMMITTED` on the primary database. PostgreSQL 15 remains the legacy compatibility baseline; PostgreSQL 18 is the new target environment. The migration adapter uses the same access lock protocol without coupling model migration to an engine upgrade.

At PostgreSQL Read Committed, each statement obtains a new snapshot; a statement that began before a lock wait is not a fresh policy read after that wait. See [PostgreSQL 15 transaction isolation](https://www.postgresql.org/docs/15/transaction-iso.html). Scopegate therefore separates lock acquisition from the subsequent policy statement. An advisory lock function embedded in a large policy SELECT is insufficient. The SQLAlchemy session must refresh or replace prelock objects instead of treating its identity map as current authorization state.

The executed [transaction probe](../scripts/transaction_probe.py) used two independent connections and controlled lock barriers on PostgreSQL 18.6. Its combined lock and policy statement returned the earlier active state after revocation committed; its separate lock statement followed by a policy statement returned revoked. Those two schedules establish why this protocol needs a fresh statement. They do not exercise HTTP handlers, SQLAlchemy identity maps, all writers, invitation acceptance or the PostgreSQL 15 adapter. Package execution evidence belongs in [Validation](VALIDATION.md).

After acquiring locks, capture the database clock and run the complete operation predicate in a new statement. Use that time for membership and invitation expiration and recent authentication checks. Do not use a transaction start timestamp to prove freshness after waiting. A bounded operation admitted before natural expiry may finish within its transaction deadline; no operation is newly admitted after expiry. Time checks cannot freeze the clock or promise that commit occurs at the exact decision instant.

## Lock order and ownership

PostgreSQL row locks and transaction scoped advisory locks have different responsibilities. Row locks protect resource publication and specific mutations; the organization lock orders critical use against tenant access mutations. Advisory locks are a cooperating application protocol, not a constraint that protects arbitrary SQL writers. See [PostgreSQL explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html).

| Operation | Ordered locks before policy reread |
| --- | --- |
| Grant delta | Existing referenced resource rows in UUID order `FOR SHARE`; exclusive organization lock; target membership row |
| Entitlement disable | Disabled resource row `FOR SHARE`; exclusive organization lock; affected memberships in UUID order; dependent pending invitations in UUID order |
| Invitation acceptance | Plan resource rows in UUID order `FOR SHARE`; exclusive organization lock; applicable membership row; invitation row |
| Critical report creation or bounded consumption | Resource rows in UUID order `FOR SHARE`; shared organization lock; fresh membership and grant read |
| Membership status, role or expiry change | Exclusive organization lock; membership rows in UUID order; no resource lock acquired afterwards |
| Catalog update or terminal archive | Resource row `FOR UPDATE`; no organization lock or grant mutation |
| Writer ownership change | Exclusive organization lock; current control row and expected epoch |

Missing input does not bypass scope validation. Removals may lock an extant archived resource and revoke its historical scoped grant. Hard resource deletion is forbidden. Multi resource commands sort before acquiring any row lock; input order is not lock order. Commands affecting several organizations are decomposed into separate reviewed operations, not a user wide mutation acquiring organization locks opportunistically.

An initial read-only visibility check verifies actor membership, project ownership and exact scoped entitlement pairs before global resource locks are requested. Protected output additionally verifies current consumer discoverability. Otherwise, a known global foreign resource and an unknown resource could produce different results before tenant authorization. The preflight is concealment only: every authoritative check repeats in a fresh statement after the ordered locks, and its earlier result is never reused as permission.

The application takes a command-key advisory mutex after resource and organization locks and before looking up a receipt. Namespace `17291` binds the complete actor/organization/operation/key tuple through a hash for coordination, while the receipt's primary key keeps those fields exact. This is necessary for report creation: two shared organization locks would otherwise allow both requests to miss the same receipt and create different reports. The mutex is bounded by the transaction lock timeout, and a fresh receipt query after the wait observes a previous commit. Hash collisions cause conservative contention rather than shared authority.

Set bounded lock, statement and transaction timeouts. A timeout rolls back the whole use case; a deadlock or serialization failure restarts it with the same receipt key and new authoritative reads. Never retry only the last SQL statement. Do not use `SKIP LOCKED` for authorization, grant removal or impact counting: skipped rows would make a mutation's meaning depend on contention.

## Race schedules and exact outcomes

| Schedule | Required result and future test |
| --- | --- |
| A locks resource and waits for shared organization lock; B revokes and commits; A receives lock | A runs a new policy statement and denies. `fresh_policy_after_advisory_wait` must fail an implementation that reuses A's earlier snapshot. |
| A obtains shared organization lock, authorizes and writes; B requests exclusive lock | A commits first; B then revokes and commits. Any later admission denies. `critical_use_then_revoke` asserts commit ordering and durable rows. |
| Two editors hold the same expected membership version | Exclusive organization serialization lets one change the version; a new stale command returns `412`. A matching receipt retry returns its original result without another transition. |
| A grants to user X while B disables the same entitlement | If A commits first, B's recomputed impact includes that grant or rejects its stale preview; if B commits first, A cannot add. No silent unreviewed fanout. |
| Entitlement is disabled and later enabled | Scoped grants remain revoked and dependent invitations remain revoked. No prior access returns until a fresh explicit grant or invitation is approved. |
| Two managers try to suspend the remaining durable managers | Organization lock serializes the count and change; the second command cannot remove the last active nonexpiring customer manager. |
| Staff manager is valid now but expires later | Staff never satisfies durable continuity. Suspending the only durable customer manager fails even while staff is currently active. |
| Grant edits for the same global user run in organizations A and B | Each changes its own membership aggregate and versions; neither writes the global user's access list or the other membership. |
| Two report requests reference resources in reversed order | Sorted locks remove that inversion; bounded timeout still handles contention from unrelated database activity. |
| Publisher archives while a critical use holds resource share lock | Archive commits after the earlier use. A later use sees archived status and denies; a newer publication cannot reverse terminal archive. |
| Session or invitation freshness expires while waiting | Clock and trusted claims are checked after waiting; deny or require reauthentication, without partial membership or grant changes. |

Entitlement preview is advisory and can become stale. Under the exclusive organization lock, verify its entitlement revision and recompute the impact fingerprint over grants, membership versions and pending invitations. A mismatch returns `412` without effects. The initial limits are 200 changed memberships, 500 active grants and 200 pending invitations; exceeding any limit returns `409` before writes. Bounded disable revokes all affected tuples, advances each changed membership once, revokes each dependent pending invitation as a whole and appends audit and receipt atomically. Enabling entitlement restores availability only.

The durable manager rule is an explicit product assumption that must be approved before private cutover. Platform emergency provisioning can repair a failed continuity baseline through a separately audited credential. It cannot make an expired staff membership an implicit consumer or evade current resource grants.

## Publisher creation and receipt races

An existing catalog resource is locked before expected version validation. A new external key has no row to lock: selecting absence is not exclusivity. The implementation therefore acquires a bounded external-key advisory mutex in namespace `17292`, then issues a fresh resource lookup and `FOR UPDATE` lock when the row exists. The unique external key constraint remains a backstop. An alternative conflict-aware insert requires fresh winner and receipt reads; catching a uniqueness exception and continuing in an aborted transaction is invalid. The catalog namespace is distinct from command-key coordination and never acquires a tenant lock.

Two identical requests with the same actor, key and fingerprint produce one resource and one committed catalog receipt. Two different requests both expecting version zero cannot both create the key: one succeeds, the other receives a defined conflict. Resource metadata, localizations, receipt and safe publication audit share one transaction. There is no permission assignment through catalog publication.

Grant and entitlement retries reauthorize their actor and check matching committed receipts before reevaluating the old expected version or reviewed impact. Returning a historical successful response does not reapply its delta. A grant-add receipt retried after a later revoke cannot reactivate the grant. A previously active entitlement receipt retried after catalog archive returns its recorded outcome without reopening the resource or reconstructing any dependent access.

## Commit uncertainty and receipt retention

A response timeout after `COMMIT` is an unknown outcome, not proof of rollback. The client retries the exact actor scoped command with the same key, body, route target and expected version. Current authentication and authority are checked first; matching receipt lookup precedes new transition and expected version checks. Invitation retry additionally verifies current recent recipient binding before returning a stored acceptance. A consumed token with a different key is rejected.

Successful receipts remain available for at least 24 hours. Automatic client retry must fit within that guaranteed window and use bounded exponential backoff with jitter. Persist the original key in the pending client command rather than generating a new key on reload. After the supported retry window, stop automatic mutation retries and reconcile through current state, audit and the operator path. Purging a receipt ends the response replay guarantee; this design does not claim permanent deduplication or exactly once network execution.

| Failure point | Durable state and response |
| --- | --- |
| Before transaction commit | No grant, version, receipt or audit transition persists; retry entire command |
| Audit or receipt insertion fails | Entire mutation rolls back; never return success |
| Commit succeeds but connection drops before response | Effect and receipt remain; matching retry returns the recorded result |
| Key reused with different fingerprint | `409`; no mutation and no other command's result |
| Actor loses authority before retry | Deny according to current scope; receipt is not permission to read hidden state |
| Supported receipt retry window passes | Reconcile instead of resubmitting uncertain work as a new command |

## Durable outbox and delivery leases

Creation of a delivery intent is transactional with the invitation. Sending is not part of the database transaction. Workers claim a bounded batch using `FOR UPDATE SKIP LOCKED`, assign a durable lease token and expiry, and commit the claim before calling the external adapter. PostgreSQL describes `SKIP LOCKED` as suitable for queue like consumers rather than general consistent reads. See [PostgreSQL SELECT](https://www.postgresql.org/docs/18/sql-select.html). Scopegate's lease and retry protocol is an application design.

The outbox adapter needs durable lease ownership, lease expiry, cumulative and generation attempt counts, retry deadline, next attempt time and stable delivery key. A claim uses a new token; acknowledgment is conditional on that token, its unexpired lease and current pending state. A stale worker cannot acknowledge or reschedule a row claimed by another worker. The adapter timeout stays below the lease duration with a safety margin. Lease expiration and worker restart make abandoned work eligible again only inside the retry budget.

The proposed generation budget is eight claims within 30 minutes and before invitation expiry. Each claim increments cumulative `attempts` and `generation_attempts`, including a crash with an unknown provider outcome. Failed items remain visible. A reviewed requeue requires a still pending unexpired invitation and readable ciphertext; it increments `replay_generation`, resets only the generation count, retains the stable delivery key and cumulative history, and sets the deadline to the earlier of now plus 30 minutes and invitation expiry. The [reliability contract](RELIABILITY_DESIGN.md) owns exact budgets and retention.

```sql
-- Illustrative claim shape; concrete column names follow the schema contract.
WITH candidates AS (
  SELECT message.id FROM outbox_messages AS message
  JOIN invitations AS invitation
    ON invitation.organization_id = message.organization_id
   AND invitation.id = message.invitation_id
  WHERE message.state = 'pending'
    AND message.available_at <= clock_timestamp()
    AND message.generation_attempts < 8
    AND message.retry_deadline_at > clock_timestamp()
    AND invitation.state = 'pending'
    AND invitation.expires_at > clock_timestamp()
    AND message.encrypted_payload IS NOT NULL
    AND (message.lease_expires_at IS NULL
         OR message.lease_expires_at <= clock_timestamp())
  ORDER BY message.available_at, message.id
  FOR UPDATE OF message SKIP LOCKED
  LIMIT :batch_size
)
UPDATE outbox_messages AS message
SET lease_owner = :worker_id,
    lease_token = gen_random_uuid(),
    lease_expires_at = clock_timestamp() + :lease_duration,
    attempts = attempts + 1,
    generation_attempts = generation_attempts + 1,
    last_attempt_at = clock_timestamp()
FROM candidates
WHERE message.id = candidates.id
RETURNING message.id, message.lease_token, message.delivery_key,
          message.encrypted_payload;
-- Commit here. Send outside the transaction, then conditionally acknowledge.
```

Before the external call, verify current invitation validity again without retaining a database transaction over the call. A revocation can still race the external provider after that read; the message may arrive but acceptance remains denied. A bounded finalizer marks exhausted, expired or invalid unleased work `failed` and clears lease fields with safe evidence. Merely excluding such rows from future claims would strand invisible pending work. Finalization and outcome updates must use claim ownership or expired lease predicates so they cannot overwrite a current owner.

| Crash window | Expected recovery |
| --- | --- |
| Before claim commit | No durable claim; another worker can select the item |
| After claim commit but before send | Lease expires and the item is retried |
| After provider accepts send but before acknowledgment | Delivery may repeat; stable provider idempotency key prevents duplicates only if that provider contract supports it |
| Old worker returns after a newer claim | Old lease token acknowledgment changes zero rows; newer claim retains ownership |
| Retry budget exhausted or payload is invalid | Persist visible failed state and safe failure code; do not consume the invitation |
| Invitation is revoked or expires before delayed delivery | Acceptance remains denied; delivery status cannot resurrect enrollment |

The project guarantees one database acceptance transition, not exactly once email delivery. The local adapter provides deterministic synthetic evidence. A real delivery integration must document whether its provider deduplicates the stable key; otherwise duplicate messages are an explicit supported failure outcome. Failed items act as a database dead letter state and are not automatically replayed as fresh invitations. Sensitive ciphertext is cleared after bounded retention while safe state remains.

## Identity, keys and invalidation budget

The server session carries validated issuer and subject identity, verified email claim, provider authentication time and claim validation time. Contact email cannot replace those claims. Invitation actions require authentication no older than 15 minutes and validated provider `auth_time` after `max_age=900`. Request claims freshness is rechecked after lock waits.

JWT validation uses an issuer specific algorithm and audience allowlist. Keys come from configured discovery and JWKS endpoints, not token supplied `jku` or arbitrary URLs. Unknown key IDs cause one bounded, coalesced issuer refresh and then rejection; attacker controlled IDs cannot generate unbounded outbound fetches. See [JWT Best Current Practices](https://www.rfc-editor.org/rfc/rfc8725). Key cache TTL and refresh behavior are configuration inputs to test against the actual provider.

Local logout revokes a primary database session and prevents subsequent request validations. An already admitted bounded operation may finish; logout is not advertised as the same commit ordered barrier as grant revocation. Provider account disable does not automatically revoke an opaque application session. Without a tested provider logout integration, the configured session lifetime is the worst case bound for continued active use; the implemented maximum is eight hours with a 30 minute idle bound. Product and the identity owner must approve that exposure or require a shorter bound before pilot.

If the provider supports validated back channel logout, integrate and test its logout token and session binding rather than assuming support. The standard defines such an interaction, but it does not prove that the configured provider offers it. See [OIDC Back Channel Logout](https://openid.net/specs/openid-connect-backchannel-1_0.html). Key retirement, provider disable, local logout, staff expiry and resource grant revocation have different invalidation mechanisms and must not be presented as one guarantee.

Session `last_seen_at` is monotonic. Sliding idle expiry cannot exceed the absolute created time plus eight hours, and delayed concurrent activity cannot revive a revoked session. Complete session touch transactions before acquiring domain resource and organization locks; do not hold a global session update lock across several tenant transactions. Cookie mutations require a session bound CSRF token and origin validation. Login state and nonce are cryptographically bound to the initiating browser and consumed once; trusted proxy headers require an explicit deployment allowlist.

## Reads, replicas and background use

Authorization state and command receipts are read from the primary. An asynchronous replica can return an earlier active grant after primary revocation; adding a replica to the policy path would violate the intended guarantee. Browser cache, static asset CDN and catalog display caches are presentation aids only. A database query always reauthorizes protected metadata before it is returned. No privilege decision cache is part of the first release.

Grant cursor pages bind actor, tenant, project, filters and aggregate access version; a changed version requires refresh. Migration manifest pages bind immutable evidence revision. Ordinary resource pages promise bounded authorized rows at each statement snapshot, not a cross request snapshot while the catalog and grants change. A read that began before revocation committed can finish from that earlier valid snapshot within its deadline. A newly started primary read sees the committed revocation, and every protected action performs its own current locked policy decision even if a card was fetched earlier. The stronger commit ordering guarantee applies to bounded protected output, rather than a long lived client view.

A queued request is not a permanent authorization ticket. Existing background consumers must recheck current membership, publication, entitlement and grant before each bounded durable output and before delivery. Preserve the original actor and scope through a verified enforcement adapter; do not substitute a broadly privileged service credential. Long computation does not hold an organization lock throughout external I/O. It works in bounded steps whose output transaction takes the required locks and current policy. Defining a new delegated job principal or asynchronous computation engine is outside the initial product and requires its own contract before introduction.

## Evidence required before relying on these guarantees

Use independent real PostgreSQL connections, deterministic barriers, controlled clocks and failpoints around commit, claim, send and acknowledgment. Record durable rows and order, not only HTTP results. Test the PostgreSQL 15 transition adapter separately from the PostgreSQL 18 target. Include new external key contention, stale preview impact, whole invitation revocation, delayed receipt retry, expired leases, late acknowledgments, primary versus simulated replica lag and background output after revocation. The [quality gates](QUALITY.md), [migration plan](MIGRATION.md) and [ADR 7](adr/0007-ordered-authorization-transactions.md) define where this evidence blocks release.
