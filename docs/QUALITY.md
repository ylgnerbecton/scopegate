# Scopegate Quality

Scopegate is ready to release only when tenant isolation, explicit resource grants, invitation acceptance and migration correctness have reproducible evidence. The gates below define implementation acceptance. They describe required checks, not completed runtime results.

## Quality ownership

The engineering owner is accountable for the shared policy and transaction protocol. Module owners maintain focused unit and integration coverage. A reviewer independently checks security boundaries and migration evidence. A release owner records the exact revision, dependency lockfiles, environment, commands, exit codes and artifacts for each gate. An empty result, unavailable dependency or infrastructure failure never counts as a passing check.

Use small policy functions and explicit use cases rather than repeating conditions in route handlers. Prefer readable identifiers, typed request and response contracts, clear module boundaries and restrained abstractions. Shared rules belong in one implementation; fixture assertions must express behavior independently of those rules.

## Test layers

| Layer | Purpose | Required evidence |
| --- | --- | --- |
| Static checks | Catch malformed contracts, types and dependencies | Python lint and typing; TypeScript typing and lint; dependency and secret scans |
| Policy unit tests | Prove the decision matrix and time boundaries | Allowed and denied examples for each predicate, role and membership kind |
| PostgreSQL integration | Prove SQL constraints, transaction boundaries and actual locks | PostgreSQL 18 connections with realistic transaction interleavings |
| HTTP contract tests | Prove validation, authentication, error mapping and scope | Requests using real repositories and synthetic actors across two organizations |
| Browser tests | Prove usable access management and tenant state handling | Viewer, manager, invitation, organization switching and stale response scenarios |
| Migration rehearsal | Prove old and new decision equivalence and safe cutover | PostgreSQL 15 source snapshot, target checks, ledger and revocation preservation |
| Operational rehearsal | Prove recovery and bounded degradation | Restore, worker retry, provider outage and transaction timeout evidence |

SQLite or mocks cannot substitute for PostgreSQL lock or composite foreign key tests. Tests using the development identity adapter cannot substitute for the real OIDC provider integration.

## Authorization matrix

Build fixtures with two organizations, two projects per organization, one resource shared by multiple projects, several catalog resources and independent memberships. For each operation exercise absent membership, suspended membership, expired staff membership, viewer, manager without a consumption grant, granted viewer and revoked grant. Assert response, persisted state, audit effects and absence of forbidden identifiers.

Negative scenarios must cover:

- Detail access with a valid identifier from another organization, including nested path mismatches.
- List, count, search and pagination that omit hidden rows before counting or cursor construction.
- Create, update, delete, export and consume using foreign project, membership or resource references.
- A report containing an allowed resource and a denied resource, which fails atomically.
- A manager attempting to grant a resource outside project entitlements, promote a viewer, create a manager or remove the last active non-expiring customer manager.
- A manager or staff member without a consumption grant receiving no implicit resource access.
- Published, archived and disabled entitlement transitions, including localization fallback that does not change access.
- Attempts to inject tenant, role, membership kind or ownership through unknown payload fields.
- Access decision requests with unknown, foreign and ungranted resource identifiers, proving that diagnostics do not reveal hidden catalog status or existence.
- Migration summaries, source records, decisions and exports requested by a viewer, customer manager, unflagged staff, expired reviewer or reviewer from another organization. Only the scoped staff manager with the platform assigned review capability succeeds.

Direct database tests must reject cross organization grant, invitation and report relationships. These constraint tests complement policy tests; neither replaces the other.

## Invitation and identity gates

Test issuance against active entitlements, empty or duplicate references, expiration limits and manager authority. Test acceptance with new identity, existing identity, existing membership, existing manager and suspended membership. A viewer invitation cannot silently lower an existing manager's role or reactivate a suspension.

Reject wrong issuer, invalid signature, wrong audience, stale nonce or state, expired identity token, unverified email, mismatched email, expired invitation, revoked invitation and consumed invitation. Verify email changes never merge immutable identities. Concurrent acceptance yields one accepted transition, one membership and one grant set, with consistent audit evidence. Fault injection before commit leaves no partial membership or grant; an outbox failure after commit does not erase accepted access.

Preview verifies the recipient's recent session claims before returning the organization and bounded grant plan, without consuming the token or granting access. An unverified contact email in `users` cannot substitute for the session claim. Cover absent or stale provider `auth_time`, authentication older than 15 minutes and freshness expiring during a lock wait. After reauthentication, a retry with the same actor, key and body returns the stored result before reapplying pending state checks; a new key for a consumed token is rejected. A different identity or mismatched fingerprint cannot obtain that receipt.

Test the real provider authorization flow, callback and key refresh before the pilot. Verify production configuration rejects the local adapter and fabricated identity headers. Confirm cookie attributes, CSRF checks, logout invalidation and session expiration through HTTP tests.

## Concurrency and retry gates

Use independent database connections with deterministic barriers rather than sleeps as the only scheduling mechanism. Each scenario must assert both outcomes and durable rows:

| Interleaving | Required outcome |
| --- | --- |
| Two grant edits read the same membership version | One commits; the stale edit conflicts or safely retries the whole use case |
| Critical report obtains shared tenant lock before revocation | Report commits while access is valid; revocation commits afterwards |
| Revocation commits before critical report obtains its lock | Report cannot create an authorized output |
| Publisher archival overlaps critical use | Sorted resource row locks order the archive and use; no output commits against an already archived decision |
| Staff expiration passes during lock wait | Recomputed clock check denies use after the wait |
| Simultaneous manager suspension or removal | The last active non-expiring customer manager invariant holds |
| Grant mutation and invitation acceptance overlap | No lost grant changes, duplicate membership or partial acceptance |
| Timeout, deadlock or connection loss interrupts a mutation | Whole transaction rolls back; retry with the same key produces no duplicate effect |

Every path follows sorted resource locks, organization lock and membership lock. Membership only mutations do not acquire resource locks later. Mutation updates grants by difference; unchanged grants retain identity, and the membership access version increments once for a changed command. Idempotency tests bind a key to actor, organization, operation and request fingerprint, reject conflicting reuse, and never return another actor's cached result.

## Browser and accessibility gates

Verify the full flow with keyboard operation, visible focus, meaningful labels, readable errors and status announcements. Cover narrow and wide viewports and the supported locales. A manager's selection UI displays only entitled project resources, prevents duplicate selection and explains conflicts without exposing hidden data.

Switch organizations while a request is in flight. The previous response cannot populate the new view or enable a stale action. Query keys contain principal and tenant scope; logout removes all session data. Test loading, empty, forbidden, network error, concurrent edit and retry states. Revocation refreshes affected views and safely removes an invalid action. Browser hiding is never the only authorization check.

## Migration gates

Use a sanitized source fixture that includes shared resources, missing legacy references, duplicate contacts, multiple memberships, historical revocations and saved report references. Mapping rules classify invalid records instead of silently granting access. Backfill is resumable with a ledger and cannot overwrite a newer target decision.

Compare record counts, relationship integrity, resource reference mapping and the full policy decision matrix per organization. Semantic equivalence concerns which actor can perform which operation, not merely matching row counts. Every mismatch is resolved or explicitly classified as a reviewed restriction before cutover.

Rehearse per organization write fencing, final delta transfer, canonical writer switch and application rollback. Assert that fenced legacy code cannot write access state or resurrect revoked grants. Keep the target schema and canonical target state after cutover. Perform the PostgreSQL engine upgrade rehearsal separately from data model migration.

## Performance and operational gates

Select a documented representative dataset and a workload that includes tenant lists, invitation creation, grant edits and report use. Capture query plans, latency distributions, error rates, lock waits and database utilization. Establish an acceptable latency and transaction timeout budget from these measurements before a pilot; there is no unmeasured throughput target.

Check indexes for tenant policy joins and referencing foreign keys. Verify pagination bounds, bounded report work and backfill batch sizes. A large tenant must not force unbounded response materialization. Test an identity provider outage, exhausted database pool, outbox retry, duplicate delivery, poison delivery payload and worker restart. Restore a database backup and verify constraints, ledger state and audit continuity.

Grant reads use bounded cursor pages carrying the membership access version. A cursor cannot silently combine pages from different aggregate versions; the client must refresh after a conflict. Grant mutation responses contain the bounded `changed_grants` delta, at most 200 entries for the allowed addition and removal limits, rather than materializing the complete assignment set. Verify an edit preserves unselected and off page grants and that the interface reconciles the confirmed delta with its current paginated view. Migration record lists and manifest exports also use bounded query batches; export creation and retrieval recheck reviewer scope.

## Release gates

| Canonical gate | Planned command | Required result |
| --- | --- | --- |
| G-LINT | `make lint typecheck` | Backend/frontend lint and strict types |
| G-DOMAIN | `make test-unit` | Policy, transitions, and identity adapter unit tests |
| G-DATABASE | `make test-integration` | Real PostgreSQL constraints, transactions, and concurrency |
| G-CONTRACT | `make check-contracts` | Generated API and client compatibility |
| G-BROWSER | `make test-browser` | Complete scoped journey and accessibility |
| G-MIGRATION | `make test-migration` | Replay, parity, fence, and post-revoke rollback |
| G-IDENTITY | `make test-identity` | Real OIDC provider positive/negative integration |
| G-BUILD | `make build smoke` | Images, web build, migrations, and smoke |
| G-RELEASE | `make check-runtime` | Require all runtime gates and reviewed pilot prerequisites |
| G-PERFORMANCE | `make test-performance` | Measured steady/burst/stress query, connection and latency budgets |
| G-SECURITY | `make test-security` | Threat, dependency, supply-chain and startup configuration gates |
| G-OPERATIONS | `make test-operations` | Delivery crash, alert, recovery, purge and incident drills |

Every local release candidate requires all runtime gates. G-MIGRATION includes the synthetic compatibility exercise even for a fresh local product; a real migrated organization additionally requires its reviewed private parity and writer evidence. G-IDENTITY uses the local integration provider for the synthetic product and the actual provider before a live pilot. These commands execute the local runtime tooling. Real provider and rollout proofs remain stage-specific. Each gate records actual commands, exit codes, revision, environment and artifacts through [Completion contract](COMPLETION_CONTRACT.md). A material change reruns affected gates; earlier reports cannot certify changed behavior.

## Completion standard

A completed increment includes implementation, behavioral checks, documentation, migrations, operational instructions and reviewed evidence for its applicable gates. Documentation changes can be checked for links, contract consistency and rendering without claiming runtime correctness. Release notes identify supported behavior, remaining limitations and recovery conditions at the exact revision.

## Lifecycle and resilience regressions

Prove durable customer-manager continuity even while staff managers are valid. Prove disable/re-enable never resurrects grants or pending invitation plans, impact previews invalidate on new grants or invitations, and cap-plus-one rejects atomically. Prove terminal archival rejects republishing the same key. Exercise session default timestamps, monotonic activity, absolute/idle expiry and logout races.

Outbox tests use token/generation CAS, attempt and deadline exhaustion, lease expiry, crash before and after provider acceptance, stale acknowledgments, manual replay preconditions and irreversible ciphertext purge. Capacity tests retain failed, overloaded and timed-out samples. Security and operations gates exercise startup guards, bounded dependency failure, telemetry redaction, alert ownership and restore reconciliation. [Standards](ENGINEERING_STANDARDS.md), [Reliability](RELIABILITY_DESIGN.md) and [Delivery](DELIVERY_SYSTEM.md) own the detailed thresholds and acceptance.
