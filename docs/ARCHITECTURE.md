# Scopegate Architecture

Scopegate gives organizations explicit control over who can use each resource in a project. The first implementation uses one modular application and one PostgreSQL database so that access changes, invitation acceptance, and audit records share a transaction boundary. The architecture is accepted for implementation; runtime behavior must satisfy the release gates in [Quality](QUALITY.md).

## Product boundaries

An organization is the tenant boundary. A project belongs to exactly one organization. Resources form a global catalog maintained by a Catalog Publisher; a resource becomes available to an organization only through an active project entitlement. An active membership and an explicit active resource grant are both necessary to consume that resource. Access managers manage access within existing project entitlements; their role does not grant consumption rights.

Customer and staff memberships use the same authorization rules. Staff access has a required expiration and is assigned through a controlled platform operations workflow. There is no global administrator bypass. Customer endpoints cannot enumerate or modify the global catalog. The Publisher uses a scoped machine credential with allowlisted operations, rather than a customer session.

## Runtime and deployment

| Component | Decision | Responsibility |
| --- | --- | --- |
| Web interface | React, TypeScript, Vite, TanStack Query | Organization selection, scoped resource discovery, invitations and access management |
| Application | Python 3.12, FastAPI | HTTP contract, session handling, use cases, policy enforcement and background delivery |
| Persistence | SQLAlchemy 2, psycopg 3, Alembic | Typed persistence, transaction ownership and ordered schema changes |
| Database | PostgreSQL 18 for the new product | Tenant relationships, constraints, authorization state, audit and outbox |
| Identity provider | OpenID Connect provider | Authentication and verified identity claims |
| Delivery adapter | Database outbox and replaceable delivery port | Postcommit invitation delivery with bounded retries |

The same application image can run the HTTP process and an outbox worker process. They share the database and versioned application modules. Redis, a message broker, an external policy service and a cluster orchestrator are outside the initial scope. PostgreSQL 15 is the existing migration baseline; migrating its data model and upgrading its database engine are separate changes with separate rehearsals.

Local development uses PostgreSQL 18 and synthetic fixtures. A local authentication adapter can support deterministic development and integration tests only when the environment explicitly permits it. Production startup must reject that adapter. A real provider integration, including negative token and callback tests, is required before a tenant pilot.

See [System context](diagrams/context.mmd) and [Containers](diagrams/container.mmd).

## Modules and dependency direction

| Module | Owns | Dependencies |
| --- | --- | --- |
| Identity | OIDC callback, immutable issuer and subject association, sessions | Provider port, session repository |
| Organizations | Organizations, projects and project entitlements | Identity principal, catalog identifiers |
| Access | Memberships, resource grants and central policy | Organization context and catalog state |
| Invitations | Invitation lifecycle and acceptance | Identity, Access, outbox |
| Catalog | Global resources and localization | Publisher credential validation |
| Reports | Configuration, scoped references and critical use | Access policy and resource versions |
| Audit | Append events in a caller owned transaction | Actor and operation metadata |
| Migration | Backfill, equivalence checks and cutover ledger | Explicit source adapter and target repositories |

HTTP handlers validate request shapes and call application services. Services enforce invariants and own one unit of work. Repositories express scoped queries and persist changes; they never commit independently. Domain policy remains independent of FastAPI and SQLAlchemy. Ports isolate the identity provider, delivery system and existing source adapter. Frontend features call one typed HTTP client and reuse the query key factory.

This division applies DRY to shared rules: one policy predicate, one transaction owner, one tenant context resolver and one error mapping. It does not introduce a generic repository framework or a custom migration framework. Explicit domain operations remain easier to inspect than a universal CRUD abstraction.

## Data model and constraints

| Record | Identity and invariant |
| --- | --- |
| `users` | Immutable `(issuer, subject)` is unique. Verified email is contact and invitation evidence, never a primary identity key. |
| `organizations` and `projects` | Every project carries its organization identifier. Active organization and project status are necessary for use. |
| `memberships` | Unique `(organization_id, user_id)`; role `viewer` or `access_manager`; status `active` or `suspended`; kind `customer` or `staff`; aggregate `access_version`. Staff requires `expires_at` and an assignment reason. |
| `resources` | Global unique `external_key`, `catalog_version` and `published` or `archived` status. Publisher owns catalog changes. |
| `resource_localizations` | Unique resource and locale pair; localization never carries authorization. |
| `project_resources` | Composite organization, project and resource identity; status `active` or `disabled`. |
| `resource_grants` | Scoped membership, project and resource tuple; state `active` or `revoked`; edits use the membership's aggregate access version. |
| `invitations` and `invitation_resources` | Invitation belongs to one organization; references use the same project entitlement relationship as grants. Token digest is stored separately from delivery payload. |
| `report_configs` and `report_resource_refs` | Organization scoped configuration with normalized references to entitled project resources. |
| `audit_events`, `sessions`, migration ledger and outbox | Transactional evidence, opaque session state, migration progress and durable delivery respectively. |

Tenant children use composite foreign keys containing `organization_id`, including grants, invitation references and report references. This rejects a project from one organization paired with a membership from another, even when individual identifiers exist. Cross row role rules and lock ordering belong in application services; a row `CHECK` cannot prove them. PostgreSQL supports composite foreign keys and requires their referenced columns to be unique. See [PostgreSQL constraints](https://www.postgresql.org/docs/18/ddl-constraints.html). Scopegate's use of those constraints for tenant integrity is a design decision.

Resources are archived rather than hard deleted; foreign key deletion is restrictive. Revoked grants remain addressable. A changed command increments the membership's aggregate access version once. Mutation computes additions, reactivations and revocations as a difference between current and requested sets, preserving unchanged records. Wholesale deletion and reinsertion would lose history and enlarge the race window.

See [Entity relationships](diagrams/er.mmd) and the authoritative [schema contract](../specs/contracts/schema.sql).

## Authorization and query shape

The application derives the actor from a validated session and resolves an active organization membership from the database. A tenant identifier in a path is a requested scope, not authority. Detail reads, lists, counts, searches, writes, exports and report execution apply the same policy in their database query or service boundary before materializing results.

Consumption requires all of the following at the decision instant: a valid session, an active organization, an active unexpired membership in that organization, an active project in that organization, an active project entitlement, a published resource and an active grant for that membership and project resource. Access management additionally requires `access_manager` and remains constrained by the organization's existing entitlements. Managers cannot create or promote another manager or remove the last active non-expiring customer manager; platform operations handle manager provisioning through a separate controlled path.

An inaccessible object yields `404`, including guessed identifiers. A known organization in which the actor has an active membership but insufficient role yields `403`. Response bodies and logs do not reveal hidden organization names, project existence or resource metadata. List filtering happens before pagination and counting. Report references are checked individually; a mixed allowed and denied set fails atomically.

## Transaction and concurrency protocol

Authorization is a live database decision. Cached frontend permissions are presentation hints. Services use a bounded transaction and acquire locks in this order:

1. Lock existing affected resource rows in deterministic identifier order. Critical use and access mutations use `FOR SHARE`; Publisher archival takes `FOR UPDATE`. Missing or archived input does not skip policy validation. Hard deletion is forbidden.
2. Acquire a transaction scoped advisory lock for the organization. Critical consumption uses the shared variant; access mutations use the exclusive variant.
3. Lock a membership row where mutation requires it, then check its expected access version. Issue lock acquisition separately from a new policy statement under READ COMMITTED, refresh ORM snapshots, and recompute policy using the authoritative clock after waits. Invitation transitions lock their invitation row after the applicable resource, organization and membership locks.

Membership suspension and expiration changes take the organization lock and membership lock without acquiring resource locks later. Publisher changes never acquire organization locks and never alter grants. These restrictions prevent an inverted lock dependency. Advisory locks use the organization's stored unique `lock_key`; they must not use a process randomized hash. The lock protocol is an application obligation and is verified against real database connections.

Critical report use holds shared resource and organization locks while checking policy, validating normalized report references and creating the durable result inside the same transaction. Revocation waits for earlier critical use to commit, then changes the grant and audit event under the exclusive organization lock. Any critical use that obtains the lock after revocation commits sees the revoked state. Revocation cannot erase an artifact already committed while access was valid. Large or external work must be decomposed into bounded steps that reauthorize before each durable output; an unbounded transaction is not acceptable.

Expiration is checked after waiting for locks using `clock_timestamp()` or an immediately captured authoritative wall clock. A transaction start timestamp is insufficient when a lock wait spans expiration. Lock and statement timeouts abort rather than extend access indefinitely; retryable failures restart the entire use case with the same actor scoped idempotency key. Durable authorization changes and their audit event commit together. Delivery occurs only after commit.

See [Revocation sequence](diagrams/grant-revocation.mmd). The precise timeout budget must be established by the concurrency and load gates before a pilot.

## Invitation acceptance

Issuing an invitation validates every requested project resource against active organization entitlements and the sender's manager role. Creation stores a bounded single use token digest, invitation resource references, audit event and outbox item in one transaction. The delivery adapter handles the sensitive link outside that transaction.

Acceptance requires an authenticated OIDC identity whose provider asserts a verified email matching the invitation's canonical email. It locks the invitation and affected authorization state, evaluates expiration after any wait, and revalidates entitlements. The service reuses the existing identity and organization membership rather than creating a duplicate. A suspended membership is not silently reactivated, and an existing manager is not downgraded by a viewer invitation. Membership changes, explicit grants, accepted state and audit event commit atomically. A consumed, revoked or expired token cannot create new access. Retry semantics must preserve this single transition without exposing the token or producing duplicate grants.

Stored lifecycle states are `pending`, `accepted` and `revoked`. An effective `expired` state is derived from the current clock while pending; the correctness of expiration never depends on a sweeper. See [Invitation sequence](diagrams/invitation-sequence.mmd).

## Interface state and localization

The interface distinguishes loading, empty, forbidden, stale and failed states. A manager can select only entitled project resources returned by a scoped endpoint. A viewer sees only explicitly granted resources. No global catalog browser is exposed to tenant sessions.

Every tenant query key includes organization, principal and resource scope where applicable. Organization switching cancels old requests, resets tenant state and invalidates scoped cache entries; logout clears the entire session cache. Late responses from the previous organization cannot render in the current view. Authorization failures trigger refresh and safe redirection rather than retaining a usable stale action.

Resource labels use requested locale with a documented fallback. Locale never changes grant identity. Translation content is escaped and cannot inject executable markup.

## Evolution and operating model

Migration follows expand, backfill, compare, shadow read, fenced pilot cutover and contract. The target becomes canonical for each cutover organization. Legacy writers remain fenced and cannot resurrect revoked grants. A rollback after cutover may restore only a target compatible application version; reverting the schema or reenabling an older authorization writer is not a safe rollback. See [Migration phases](diagrams/migration-phases.mmd) and [ADR 4](adr/0004-staged-migration.md).

The initial deployment has one database consumer boundary through the application. A central policy plus composite constraints and negative tests is the first enforcement layer. Row security is a planned defense before multiple independent database consumers are introduced, rather than an untested duplicate policy in the first increment. See [ADR 5](adr/0005-central-policy-before-rls.md).

Operational signals cover authorization denials, grant conflicts, invitation transitions, outbox age, database errors, lock waits and migration mismatches. They include request identifiers and safe actor and tenant references, not tokens or sensitive resource payloads. Availability and latency objectives are measured during the load gate; this architecture makes no throughput claim.

## Decisions and further reading

- [ADR 1 Modular monolith](adr/0001-modular-monolith.md)
- [ADR 2 Explicit resource grants](adr/0002-explicit-resource-grants.md)
- [ADR 3 Invitation onboarding](adr/0003-invitation-onboarding.md)
- [ADR 4 Staged migration](adr/0004-staged-migration.md)
- [ADR 5 Central policy before row security](adr/0005-central-policy-before-rls.md)
- [Security](SECURITY.md), [Quality](QUALITY.md) and [Risk register](RISK_REGISTER.md)

## Implementation depth and recovery ports

[Domain design](DOMAIN_DESIGN.md) defines context dependencies, atomic operation boundaries, state guards, permissions, ports and planned developer paths. [Transaction correctness](DISTRIBUTED_CORRECTNESS.md) makes isolation, lock ordering, receipt races, provider invalidation and lease outcomes precise. [Decision matrix](DECISION_MATRIX.md) records when alternatives become justified. ADRs 6–8 close continuity, destructive entitlement disable, terminal resource archive and primary-only authorization.

[Capacity](CAPACITY_PLAN.md) and [resilience](RELIABILITY_DESIGN.md) propose bounded pool, deadline, admission and delivery configurations. Two initial HTTP replicas share one primary database; their processes and outbox worker have a summed connection budget, including the reserve and deployment replacement strategy. These are hypotheses to measure, not throughput guarantees.

Disaster recovery has a separate externally durable journal port for live access intent and outcome. A prepared intent is acknowledged before a journal-required mutation; audit and receipt bind its reference. Failure rejects that mutation without effects. It introduces no second authorization store and no distributed atomic-commit claim. The local rehearsal uses an isolated durable synthetic adapter outside the recovered database. The production host must supply and prove an independently durable adapter before permission-preserving recovery is claimed. [Delivery system](DELIVERY_SYSTEM.md) specifies uncertainty fencing and reconciliation. Ordinary application rollback continues to use current target state.
