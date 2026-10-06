# Scopegate data model

Access is a relationship among an identity, an organization, a project and a resource. The implemented schema normalizes those relationships and uses organization-aware foreign keys to reject cross-account associations. [schema.sql](../specs/contracts/schema.sql) defines **21 domain and supporting tables**; the [Alembic migration](../backend/migrations/versions/0001_target.py) reproduces that contract. Runtime also has Alembic's bookkeeping table, making 22 tables without adding a domain entity.

![All 21 model entities and their primary relationships](diagrams/er.svg)

[Full-size model](diagrams/er.svg) · [Editable source](diagrams/er.mmd)

The diagram includes all 21 entities with selected identifying and lifecycle columns. Composite ownership keys remain explicit; small role/provenance foreign keys and some indexes are explained below rather than drawn as crossing edges. Canonical SQL owns every column, constraint and index.

## Entities and ownership

| Entity | Key and invariants | Owner |
| --- | --- | --- |
| users | UUID; unique `(issuer, subject)`; email is contact data, never authority | Identity integration |
| organizations | UUID; status active or suspended; access mode legacy, shadow, or target | Operations and migration controller |
| projects | UUID; `(organization_id, id)` unique; name not an identity | Organization operations |
| memberships | UUID; unique organization/user; viewer or access_manager; active or suspended; restricted staff reviewer capability | Access operations |
| resources | UUID; unique external_key; monotonic catalog version; published or archived | Catalog publisher |
| resource_localizations | Resource/locale primary key; optional description; no ownership fields | Catalog publisher |
| project_resources | Organization/project/resource primary key; active or disabled entitlement | Contract operations |
| resource_grants | Membership/project/resource primary key with organization; active or revoked | Access manager |
| invitations | UUID; single-use hashed token; intended email/role; bounded expiry | Access operations |
| invitation_resources | Explicit desired grants, constrained to the invitation's organization | Access manager |
| sessions | Hashed opaque token; user, trusted email snapshot, verification/authentication times, expiry, and revocation | Identity integration |
| audit_events | UUID; append-only actor/action/target/safe before and after summary | Command service |
| outbox_messages | UUID; unique delivery key, status, retry count | Notification adapter |
| report_configs | UUID; organization/project reference | Existing consuming product |
| report_resource_refs | Config/resource association through project entitlement | Compatibility adapter |
| migration_runs | Snapshot identity, evidence/policy version, manifest hashes, state, timestamps | Migration controller |
| migration_ledger | Source locator, hashes, transform version, owner and review version; unique run/source | Migration controller |
| migration_controls | Organization writer epoch, fence, high-water marks, and baseline revision | Migration controller |
| migration_decisions | Versioned allow/deny comparison evidence scoped to run and organization | Migration controller |
| command_receipts | Exact actor/organization/operation/key primary key; request fingerprint, committed response and journal binding | Owning command service |
| catalog_receipts | Exact actor/external-key/key primary key; catalog fingerprint and committed response | Catalog publication |

### Relationship groups

| Group | Tables | Purpose and authority |
| --- | --- | --- |
| Identity | `users`, `sessions` | Immutable issuer/subject account; trusted claims and revocable opaque session |
| Organization access | `organizations`, `projects`, `memberships`, `project_resources`, `resource_grants` | Separate tenant ownership, role, availability and consumption grant |
| Global content | `resources`, `resource_localizations`, `catalog_receipts` | Stable catalog identity, locale metadata and versioned publisher retry |
| Enrollment/delivery | `invitations`, `invitation_resources`, `outbox_messages` | Reviewed desired plan, single-use verified acceptance and independent delivery state |
| Protected consumption | `report_configs`, `report_resource_refs` | Scoped durable configuration with exact entitlement references; current access is still rechecked |
| Command evidence | `command_receipts`, `audit_events` | Idempotent response and append-only safe change evidence; neither grants permission |
| Migration/ownership | `migration_runs`, `migration_ledger`, `migration_controls`, `migration_decisions` | Provenance/review, decision parity, organization writer epoch/fence and watermarks |

`migration_controls` is optional per organization until a reviewed ownership flow creates it; it has at most one row for that organization. Its optional `current_run_id` binds the current evidence run. Decision rows belong to one run and organization and include the exact principal/project/resource/action tuple. A ledger row can retain a null organization while its source relationship is unresolved; null is not permission to infer a tenant. Catalog receipts bind `external_key` to the unique resource key, rather than to an organization.

A global resource has a stable content identity. Its availability to a customer comes only from `project_resources`; publication alone grants nothing. A resource may be entitled to several projects without copying content. That assumption requires validation with contract operations before a tenant pilot.

## Policy intersection

```text
allow resource use =
  authenticated identity
  AND organization.status = active
  AND membership belongs to that identity and organization
  AND membership.status = active
  AND membership has not expired
  AND project belongs to that organization and is active
  AND project_resource.status = active
  AND resource.status = published
  AND resource_grant.state = active for that membership/project/resource
```

The role is deliberately absent from the resource-use expression. `access_manager` authorizes defined administration commands; it does not imply content access. Staff memberships follow the same expression and must expire. No wildcard grant is inferred from an internal flag.

## Structural integrity

`resource_grants(organization_id, membership_id)` references the organization's membership, and `(organization_id, project_id, resource_id)` references an entitlement for the same organization. Report references and invitation resources use the same project entitlement key. A grant cannot cross accounts even if a caller bypasses the normal service.

| Association | Physical composite constraint | Rejected mismatch |
| --- | --- | --- |
| Project → organization | `projects.organization_id → organizations.id`; unique `(organization_id, id)` | Unowned project identifier |
| Grant → membership | `(organization_id, membership_id) → memberships(organization_id, id)` | A member from another organization |
| Grant → entitlement | `(organization_id, project_id, resource_id) → project_resources(...)` | Project/resource availability in a different tenant |
| Invitation plan → invitation/entitlement | `(organization_id, invitation_id)` and `(organization_id, project_id, resource_id)` | A resource plan detached from its invitation tenant |
| Report references → configuration/entitlement | `(organization_id, project_id, report_config_id)` and `(organization_id, project_id, resource_id)` | A configuration or resource from a different project/organization |
| Delivery → invitation | `(organization_id, invitation_id) → invitations(organization_id, id)` | Delivery record assigned to another invitation tenant |

Nullable supporting foreign keys retain provenance rather than granting access: `audit_events.organization_id` may be null for global publication, and `migration_ledger.organization_id` may be unresolved. User references on invitations, audit and reports retain the actual actor; review owner/reviewer references retain migration responsibility. These references are present in the SQL even when omitted from the main ER edges for legibility.

Foreign keys enforce structural ownership. They do not enforce current status, elapsed time, manager authority, or token verification. Those require the central policy and transaction protocol. Composite foreign keys are supported by PostgreSQL; referencing columns need appropriate indexes for deletion and join workloads. [PostgreSQL constraints](https://www.postgresql.org/docs/18/ddl-constraints.html).

Use restrictive deletion for identity, organization, membership, resource, entitlement, and audit relationships. Revoke or archive instead of deleting. Expired invitations and sessions may be purged only under an approved retention policy; audit metadata must remain interpretable.

## Membership and identity rules

One identity may have many memberships; one organization may have many identities. There is one membership per pair, reactivated explicitly if suspended. Staff membership requires an expiry and a recorded assignment reason. Migration review additionally requires `can_review_migration`, which is structurally restricted to staff access managers and provisioned only through platform operations. The capability authorizes review in that organization; it never grants resource consumption or permission to cut over without operational gates. Customer viewers may expire. Customer managers cannot expire. Every target organization requires at least one active customer manager without expiry; expiring staff managers never satisfy continuity. This proposed ownership rule needs Product and operations approval before live cutover. Bootstrap and repair enforce it under the exclusive organization lock and audit the assignment.

Use the verified identity provider's issuer and subject as the identity key. Changes to display email cannot move membership. Do not merge two existing accounts solely because normalized email matches. Invitation matching assumes a verified email claim under an approved provider normalization policy: trim surrounding whitespace and compare case-insensitively for the configured provider, preserve the original address, and do not strip dots or plus suffixes. Stop onboarding if the provider cannot safely support that policy.

The server session stores the verified provider email snapshot, `email_verified`, `authenticated_at`, and `claims_verified_at` from validated claims. Invitations never use mutable `users.email` as proof. Acceptance requires a verified matching snapshot and authentication no older than 15 minutes; use OIDC `max_age=900` and validate the returned `auth_time` when reauthentication is needed. A session lasts at most 8 hours, with a 30-minute idle bound. `last_seen_at` advances monotonically using a conditional update only while the session is unrevoked, unexpired and within the idle bound; expired sessions cannot be refreshed. Absolute expiry stays bounded by creation plus 8 hours. Those bounds are implemented locally; the live identity owner must approve their account-disable exposure and provider integration before rollout.

## Grant commands and concurrency

A grant update changes only one organization, membership, and project. The request supplies `If-Match` for the membership's access version, and an explicit `add` and `remove` set. Validate that the sets are disjoint, refer to entitled resources, and remain bounded. Compute a delta; never replace a user's entire cross-account access list.

Acquire referenced resource rows in UUID order with `FOR SHARE`, then the organization's exclusive transaction advisory lock. Recheck current manager authority, acquire the command-key receipt mutex and read a matching receipt before applying a new command. For a new command, lock the scoped membership row and validate its expected access version. Change grants, increment the membership version once for a changed command, append the audit event, and persist the idempotent response in the same transaction. A repeated command with the same key and body returns the stored response. A stale new command returns 412. A no-op diff does not create extra grant transitions.

Critical resource use acquires the resource's `FOR SHARE` lock, then the organization's shared advisory transaction lock, evaluates the policy using the clock after lock acquisition, and creates the consuming record within that transaction. Revocation takes the exclusive organization lock. A use committed before revocation is a completed prior operation; a use starting its policy decision after revocation commits is denied. Existing exported artifacts need a separate retention decision; revocation cannot erase prior downloads.

Publisher archival uses `FOR UPDATE` on the resource row and cannot mutate grants. Membership suspension takes organization lock then membership lock and never acquires resource locks afterward. Configure bounded lock/statement timeouts. Retry deadlocks or serialization failures only through the same idempotency key. Advisory locks are a service protocol, not a database constraint; every writer must participate.

## Invitation lifecycle

`pending -> accepted` and `pending -> revoked` are persisted transitions. `expired` is an effective state when the database clock reaches expiry, even if no cleanup job runs. Resend revokes the old pending invitation and creates a new token in one transaction. Acceptance locks the invitation after the applicable resource, organization, and membership locks, checks verified recipient identity and expiry, and creates or reuses the existing membership without downgrading its role.

An invitation issued by an access manager always grants the viewer role. Creating another access manager or assigning staff access belongs to a privileged platform operations workflow with explicit organizational authorization. It is not exposed as a customer self-service endpoint in the minimum release. Removing, demoting, expiring or suspending the final active customer access manager is rejected while holding the organization lock. Staff expiry cannot strand an organization. Platform repair can assign a new verified durable manager with audit; it cannot bypass resource-use policy.

## Catalog and localization

`external_key` is stable and non-recycled; version increases for semantic updates. Localizations are keyed by an exact supported locale code. Requested locale wins; documented organization default and then English may be used as display fallback. A response reports the selected locale and fallback. Missing translations never change access and never make an organization page fail.

Publisher payloads contain complete resource metadata, all included localizations, and an expected version. Omitted localizations remain intact; explicit deletion is deferred. Null clears nullable metadata; absent fields in operator commands preserve values. An immutable resource UUID and external key keep localized rows, grants, and report references aligned.

## Index and query budget

The DDL indexes organization/user membership lookup, organization/project entitlement, membership/project grant lookup, locale/resource metadata, pending invitations, audit timelines, and report references. Use ordered cursor pagination with a stable UUID tie-breaker. Search starts with parameterized case-insensitive literal matching on external key and localized title; escape wildcard input. Add a trigram index only after measuring a representative query plan.

The capacity plan proposes a larger engineering fixture of 100 organizations, 1,000 projects, 10,000 resources and 100,000 grants. That proposal is not observed production volume. The implemented capacity gate currently seeds 10,000 catalog resources, 40,000 localization rows and 10,000 grants and measures a bounded API process on the internal Docker network. [Measured fixture](../backend/tests/test_performance.py), [performance driver](../scripts/performance_driver.py) and [capacity plan](CAPACITY_PLAN.md) separate this measured fixture from future deployment assumptions.

## Model evolution

The schema contract is a fresh target schema, not a script to run against the legacy database. Production uses expand, controlled backfill, constraint validation, shadow decisions, per-organization cutover, and delayed contraction from [Migration](MIGRATION.md). Preserve the legacy engine version during that sequence and schedule an engine upgrade separately.

## Entitlement lifecycle and delivery durability

Each entitlement has its own monotonic `entitlement_version`. Platform operators fetch the desired transition impact before issuing a versioned command. The SHA-256 impact fingerprint binds organization/project/resource, desired state, entitlement revision, sorted active grant identities, affected membership versions and sorted pending invitation identities/states. Recompute it under the exclusive organization lock; a new grant or invite invalidates the preview even when the entitlement revision did not change. The fingerprint protects review freshness; current machine authority is still required.

Disable atomically marks the entitlement disabled, revokes every active grant for that exact pair, increments each changed membership version once, revokes each complete pending invitation containing the pair, and writes audit and receipt. Initial caps are 200 affected memberships, 500 grants and 200 pending invitations; exceeding any cap returns 409 without mutation. Mixed-plan invitations are revoked as a whole so their reviewed plan cannot silently shrink. Re-enabling never revives grants or tokens. A repeated no-op preserves versions. Lock affected memberships and invitations in UUID order after the resource and organization locks. Terminal resource archival similarly prevents grant resurrection through content publication.

Outbox messages persist encryption-key version, retry deadline, cumulative/generation attempts, replay generation, lease owner/token/expiry, last attempt/error classification and terminal timestamps. Claim with `FOR UPDATE SKIP LOCKED` in a short transaction; send outside that transaction; finalize by compare-and-set against the live lease token and generation. A crashed sender may deliver twice; stable provider delivery keys reduce duplicates, while invitation acceptance remains single-use. Ciphertext may become null only with a purge marker in a terminal state. Retry, replay and purge algorithms and their fault scenarios are specified in [Reliability design](RELIABILITY_DESIGN.md).

## Where each invariant is enforced

| Invariant | Database backstop | Runtime owner and proof boundary |
| --- | --- | --- |
| One immutable provider account and one membership pair | Unique issuer/subject and organization/user keys | [Identity](../backend/src/scopegate/services/identity.py); verified account mapping is not email matching |
| Structural tenant integrity | Composite foreign keys and restrictive deletion | Every service scopes actor and requested organization; disposable SQL checks do not prove actor authority |
| Valid stored lifecycle shape | Enumerated checks, expiry bounds, accepted-recipient evidence and outbox lease/terminal shape | Current database clock and legal transitions; a `CHECK` does not automatically expire a row |
| Durable manager continuity | Customer manager cannot have expiry; staff reviewer capability is structurally constrained | [Invariants](../backend/src/scopegate/services/invariants.py) under exclusive organization lock; cross-row continuity cannot be a row check |
| Revocation and publication order | Resource row locks plus transaction-scoped organization advisory lock protocol | [Access](../backend/src/scopegate/services/access.py), [entitlements](../backend/src/scopegate/services/entitlements.py), [catalog](../backend/src/scopegate/services/catalog.py); every writer must cooperate |
| Command retry does not repeat effects | Exact receipt primary key and committed response | Current actor reauthorization, canonical fingerprint and command-key mutex; receipt replay creates no access |
| Audit survives every committed change | Audit insert is inside the same transaction; runtime role cannot UPDATE/DELETE/TRUNCATE audit | [Common helpers](../backend/src/scopegate/services/common.py), [bootstrap privileges](../backend/src/scopegate/bootstrap.py); append-only application evidence is not protection from a compromised database owner |
| Delivery lease cannot be acknowledged by an old worker | Lease/terminal checks retain a valid record shape | [Delivery](../backend/src/scopegate/services/delivery.py) compares current token, generation and expiry; a valid row shape alone does not prove ownership |
| Restore cannot revive uncertain permission | Database writer epoch/fence plus separate local restore marker | [Recovery](../backend/src/scopegate/services/recovery.py) reconciles independent journal and invalidates restored tokens before reopening |

`make check-schema` runs positive and negative DDL assertions in disposable PostgreSQL. `make test-integration`, `make test-migration` and `make test-operations` separately exercise live policy, races, writer ownership and recovery. [Validation](VALIDATION.md) and [release evidence](../specs/implementation-evidence.json) record executed proof. Diagram/table consistency is a documentation check, not a substitute for those gates.

## Evidence and retention ownership

Audit, receipt, invitation and delivery state have different lifetimes. Audit retains a safe immutable change summary; it stores no invitation secret or sensitive output. Command/catalog receipt responses support the documented 24-hour retry window rather than permanent exactly-once execution. Invitation and session digests retain token lookup without storing raw tokens. Encrypted outbox ciphertext is purged only after a terminal-state retention window, while safe delivery history remains. The local mailbox has its separate 24-hour retention and bounded purge.

Restore markers and command journal files are outside the recovered database. They can retain uncertainty that an old snapshot lacks, but they do not become a permission lookup path. Read current authority from the primary, retain the fence for unresolved intent and require explicit reconciliation. [Reliability](RELIABILITY_DESIGN.md), [delivery system](DELIVERY_SYSTEM.md) and [operations](OPERATIONS.md) own the exact retention and recovery procedures; no generic cascade or background purge may erase their evidence implicitly.
