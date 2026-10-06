# Scopegate Domain Design

Scopegate's domain separates identity, organization authority, catalog publication and individual resource use. This design defines the responsibilities and transaction boundaries of the local implementation. The [schema](../specs/contracts/schema.sql), [HTTP contract](../specs/contracts/openapi.json) and [local operations contract](../specs/contracts/local-operations.json) define its persistence and interfaces. The [implementation map](IMPLEMENTATION_MAP.md) identifies the actual source; examples below illustrate responsibilities rather than a literal source layout. The [live CLI blueprint](../specs/contracts/migration-cli.json) retains future private integration requirements.

Status: implemented local boundaries and protocols. The continuity and irreversible revocation assumptions in [ADR 6](adr/0006-manager-continuity-and-entitlement-revocation.md) require Product and Operations validation against the private baseline before a real organization cutover.

## Bounded contexts and dependency rules

| Context | Owns and names | Public dependencies |
| --- | --- | --- |
| Identity | Issuer and subject association, verified session claims, session expiry and logout | Provider adapter and session store; no dependency on organization roles |
| Organization authority | Organization, project, entitlement and durable manager continuity | Verified identity identifiers and stable catalog identifiers |
| Individual access | Membership scope, grant delta, effective resource policy | Organization entitlement and resource lifecycle snapshots |
| Enrollment | Invitation, recipient binding, desired grant plan and delivery intent | Identity claims and individual access use cases |
| Catalog | Stable external key, resource lifecycle and localization | Publisher credential; no membership or entitlement mutation |
| Consumption boundary | Report configuration and normalized resource references | Live access policy; existing computation through an enforcement adapter |
| Migration | Source disposition, reviewed mapping, decision evidence and writer ownership | Explicit ports into the preceding contexts; private evidence repository |
| Audit and delivery | Safe command evidence and postcommit delivery | Caller owned transaction and delivery adapter |

The pure domain predicate imports standard types and immutable access facts. FastAPI transport imports application services; services coordinate domain rules, parameterized SQLAlchemy Core statements and narrow integration functions. `main.py` composes routers, dependencies, operational middleware and safe errors. The implementation keeps fewer modules than a full per-context domain/application/adapter hierarchy: that hierarchy is unnecessary for this closed scope. HTTP handlers delegate to the owning use case rather than issuing cross-context writes. Migration applies reviewed changes through the same mutation invariants, rather than a permissive backfill repository.

Read selectors may join across contexts to produce a bounded authorized projection. They return serialized dictionaries matching the HTTP contract, not ORM objects or lazy relationships. Scoped write helpers preserve the owning service's boundary and never commit independently. The schema provides composite integrity; the policy provides time, status and operation authority. Neither layer substitutes for the other.

## Stable identifiers and naming authority

| Identifier or label | Authority | Permitted change |
| --- | --- | --- |
| User UUID and OIDC issuer and subject | Identity integration | UUID and association are immutable; email cannot rebind them |
| Organization and project UUIDs | Organization authority | Names may change without moving ownership |
| Organization lock key | Database assignment | Stable unique key; never a language runtime hash |
| Resource UUID and external key | Catalog Publisher | Stable and nonrecycled; archive is terminal for that identity |
| Localized title, description and tags | Catalog Publisher | Versioned presentation changes; never an access key |
| Membership UUID | Organization and user tuple | Reuse the unique pair; retain suspension and grant history |
| Grant identity | Organization, membership, project and resource tuple | Change state by scoped delta; never replace all user scopes |
| Invitation secret | Enrollment service | Store its digest; resend creates a new invitation and secret |
| Migration source locator | Private source adapter | Preserve provenance; no name similarity or email based identity inference |

Opaque external keys are compared exactly. Transport decoding happens once at the boundary; a route or importer cannot case fold an external key or strip meaningful characters. The publisher contract must define how all permitted key characters are transported. Names, email domains and translations remain descriptive.

## Aggregates and transaction boundaries

An aggregate is the set whose invariant an operation must change atomically, rather than a requirement to load an entire organization into memory.

| Operation boundary | Atomic records | Concurrency authority |
| --- | --- | --- |
| Grant delta | Changed grant tuples, one membership access version, audit and command receipt | Resource rows, exclusive organization lock and target membership row |
| Membership status | Membership version and status, audit and receipt | Exclusive organization lock; durable manager guard |
| Entitlement disable | Entitlement revision, affected grants, changed membership versions, dependent pending invitations, audit and receipt | One bounded organization operation; deterministic rows and impact review |
| Invitation acceptance | Existing or new membership, selected grants, accepted invitation, audit and receipt | Resource, organization, membership and invitation locks |
| Catalog publication | One resource, included localizations, catalog receipt and safe publication audit | Resource row; uniqueness handles new external keys |
| Report configuration | Configuration, normalized references, audit and receipt | Shared resource and organization locks during the live policy decision |
| Migration transition | Mode, epoch, fence, approved watermarks and audit | Exclusive organization lock and expected epoch |
| Outbox creation | Invitation and encrypted delivery intent | Issuing service's transaction; external delivery occurs later |

Entitlement disable is deliberately a larger boundary because it removes availability for multiple memberships. Its fanout is reviewed and bounded before writing. Each changed membership version increments once, not once per grant. A pending invitation containing the disabled pair is revoked as a whole; removing one selected item would change the recipient's reviewed plan. Reenabling entitlement creates no grant or invitation. An oversized operation fails without partial effects; a future staged workflow needs a separate fence and acceptance design.

The initial disable limits are 200 affected memberships, 500 active grants and 200 pending invitations. These are engineering limits to benchmark, not observed capacity. The privileged preview returns the entitlement revision, counts and an impact fingerprint over the scoped grant keys, affected membership versions and dependent pending invitation identifiers and state. After acquiring the exclusive organization lock, recompute that fingerprint and check `If-Match`. A changed impact returns `412`; exceeding a limit returns `409`, both before any write. A fingerprint is review evidence, never authority.

## Operation permission matrix

Every session row is validated at the request boundary. Domain commands recheck current scoped authority after lock waits. All consumption requires the full [policy intersection](DATA_MODEL.md#policy-intersection).

| Operation | Permitted actor | Required guards and lifecycle effects |
| --- | --- | --- |
| Read current identity and assigned organizations | Valid session | Own identity; active membership discovery only; no global inventory |
| Read organization and projects | Active unexpired membership | Requested organization and project relationships are visible; concealed object errors otherwise |
| Read consumer resources and create or fetch report configuration | Active unexpired membership with explicit grants | Active organization, project and entitlement; published resources; each exact grant verified |
| Read entitled management view, memberships, grants, invitations and audit | Active unexpired access manager in the organization | Bounded authorized projection; historical state is distinct from permission to consume |
| Create project | Organization access manager | Active organization, current management authority, bounded name and atomic audit and receipt |
| Add grant | Organization access manager | Target belongs to organization; published resource and active entitlement; expected membership version |
| Remove grant | Organization access manager | Existing scoped association; removal is permitted for an archived resource or disabled entitlement; no active content requirement |
| Suspend or reactivate membership | Organization access manager | Expected version; preserve independently revoked grants; cannot remove the last durable manager |
| Create, resend or revoke viewer invitation | Organization access manager | Reviewed entitled resource plan; resend supersedes pending token; no promotion or staff assignment |
| Preview or accept invitation | Valid session with recent verified matching recipient claim | Provider authentication at most 15 minutes old; current organization and invitation state; preview grants nothing; acceptance revalidates the whole plan, cannot downgrade a manager or reactivate a suspended membership |
| Provision manager, staff or migration reviewer capability | Scoped platform operations credential | Verified identity mapping, reason, continuity and expiry guards; separate audited workflow |
| Change entitlement | Scoped platform operations credential | Expected entitlement revision and reviewed impact; disable revokes dependent access atomically within its limit |
| Publish or archive catalog resource | Catalog Publisher credential | Allowlisted operation, expected catalog version, no tenant access writes; archive cannot be reversed |
| Read or resolve migration evidence and export manifest | Active unexpired staff access manager with review capability | Exact organization scope, immutable run revision and review version; no live access mutation |
| Backfill, compare, fence, cut over or contract | Scoped operations CLI credential | Explicit private input, expected epoch, reviewed manifest and applicable migration gates |

Customer managers cannot assign roles, membership kind, staff expiry or migration review capability through status or grant payloads. Platform and Publisher credentials cannot be substituted for a browser session to consume resources. Known organization role failures use `403`; invisible objects use `404`. Access diagnostics first apply visibility and cannot disclose an unknown resource's catalog state.

## Legal state transitions

| Entity | Legal transition | Guard |
| --- | --- | --- |
| Membership | `active` to `suspended`, or explicit `suspended` to `active` | Management authority and version; last durable manager remains active; reactivation creates no grants |
| Grant | Absent or `revoked` to `active`; `active` to `revoked` | Explicit manager intent; additions require current entitlement and publication; removals preserve other scopes |
| Entitlement | `active` to `disabled`; `disabled` to `active` | Reviewed bounded disable fanout; enable does not reverse dependent revocations |
| Resource | `published` to `archived`; versioned metadata update within current state | Publisher authority; archived identity cannot return to published |
| Invitation | `pending` to `accepted` or `revoked` | Recipient proof for acceptance; manager authority for revocation; effective expiration is clock derived |
| Delivery | Pending attempts to delivered or failed | Durable lease ownership, bounded retry and stable delivery key; no acceptance implied |
| Migration | Profiled, backfilled, reviewed, shadow and cutover checkpoints, or aborted | Ledger and baseline gates; mode and epoch separate from run progress |

A target organization retains at least one active nonexpiring customer access manager. Staff managers cannot satisfy this continuity rule. Two currently valid staff managers could both expire without a command, so counting currently active managers alone is insufficient. Emergency platform repair is an audited management operation, not a consumption bypass.

## Implemented component layout

![Implemented transport, service, policy and integration boundaries](diagrams/components.svg)

[Editable source](diagrams/components.mmd) · [Deployment and trust boundaries](ARCHITECTURE.md#actual-local-deployment)

| Component | Actual source | Responsibility and dependency limit |
| --- | --- | --- |
| Composition and transport | [main.py](../backend/src/scopegate/main.py), [api/](../backend/src/scopegate/api) | Bind validated input, resolve the actor and delegate; central safe errors and HTTP probes |
| Identity boundary | [dependencies.py](../backend/src/scopegate/dependencies.py), [identity.py](../backend/src/scopegate/services/identity.py) | Verify the configured provider, immutable identity and opaque session; separate browser/platform/Publisher authority |
| Organization authority | [workspace.py](../backend/src/scopegate/services/workspace.py), [invariants.py](../backend/src/scopegate/services/invariants.py), [entitlements.py](../backend/src/scopegate/services/entitlements.py) | Scope projects and memberships, preserve manager continuity and apply reviewed destructive entitlement transitions |
| Individual access and output | [access.py](../backend/src/scopegate/services/access.py), [domain/policy.py](../backend/src/scopegate/domain/policy.py) | Versioned scoped delta and report references; pure access predicate over current facts |
| Catalog projection and publication | [catalog.py](../backend/src/scopegate/services/catalog.py) | Scoped localized search and distinct machine publication; no customer grant assignment |
| Enrollment | [enrollment.py](../backend/src/scopegate/services/enrollment.py) | Single-use recipient-bound acceptance and exact reviewed resource plan |
| Transaction primitives | [db.py](../backend/src/scopegate/db.py) | One READ COMMITTED connection, ordered resource/organization locks and bounded timeouts |
| Shared command semantics | [common.py](../backend/src/scopegate/services/common.py) | Scoped authority, receipts, audit, signed cursors and journal orchestration; caller owns commit |
| Delivery boundary | [delivery.py](../backend/src/scopegate/services/delivery.py), [worker.py](../backend/src/scopegate/worker.py) | Encrypted outbox, durable claims, explicit adapter argument, lease finalization and retention |
| Migration and recovery | [migration.py](../backend/src/scopegate/services/migration.py), [recovery.py](../backend/src/scopegate/services/recovery.py), [journal.py](../backend/src/scopegate/journal.py), [cli.py](../backend/src/scopegate/cli.py) | Explicit mappings and ownership epoch; independent intent and restore fences; web review has no cutover authority |
| Causal diagnostic context | [telemetry.py](../backend/src/scopegate/telemetry.py), [observability.py](../backend/src/scopegate/observability.py) | Fixed operation/dependency spans and safe asynchronous export; encrypted outbox carries validated trace context without authority |
| Web composition | [App.tsx](../frontend/src/App.tsx), [features/](../frontend/src/features) | Session and selected scope, composed feature panels and temporary drafts |
| Web shared boundaries | [api.ts](../frontend/src/lib/api.ts), [queries.ts](../frontend/src/lib/queries.ts), [generated types](../frontend/src/generated/api.d.ts), [ui.tsx](../frontend/src/components/ui.tsx) | One typed transport, principal/organization/project keys and reusable accessible controls |

Services use explicit functions with a transaction context rather than invented repository interfaces or a custom dependency injection container. New provider behavior belongs behind the existing integration boundary; changing authorization semantics still requires a policy/contract decision. The [implementation map](IMPLEMENTATION_MAP.md) owns the full inventory.

### UI component ownership

TanStack Query owns remote state. A feature owns its input draft, selected resource set and review step; reusable controls own semantics, focus and visual state. Feature components receive explicit scope and capability rather than reading an implicit global tenant. Confirmed server responses update the cache; a failed or stale command preserves its draft and requires another review. Query keys include the principal and organization/project dimensions used by the endpoint.

Organization switching cancels old scoped work and clears departed selection and drafts; account change clears server state. A delayed result may populate its old key but cannot render under the new scope. Recipient acceptance uses an authenticated preview without requiring preexisting organization membership. Migration review exposes only scoped evidence and reviewer actions. See [UX](UX.md#navigation-and-scope) for the product interaction contract.

## Implemented transaction and retry flow

The exact grant command is [access.apply_diff](../backend/src/scopegate/services/access.py). Its shared helpers are [db.py](../backend/src/scopegate/db.py) and [common.py](../backend/src/scopegate/services/common.py); the [revocation diagram](diagrams/grant-revocation.svg) shows the ordering against protected use.

1. The HTTP adapter validates UUIDs, bounds, CSRF and headers; the use case rejects duplicated or overlapping addition/removal input. The journal wrapper binds actor, organization, operation, key and canonical payload, then prepares independent intent before domain locks.
2. A separate scoped visibility preflight conceals foreign resource identifiers. It is not reused as an authoritative grant decision.
3. A new bounded transaction locks affected resource rows in UUID order, then the exclusive organization advisory lock. Fresh statements recheck current scoped manager authority after waits.
4. A command-key advisory mutex serializes the exact receipt scope. A matching unexpired receipt returns the recorded result; a mismatched fingerprint fails. Replay cannot reapply an earlier addition after a later revoke.
5. For a new command, enforce the writer/restore fence, resolve the scoped project and entitlement pairs, lock the target membership and validate its expected version. Additions require active membership/project/entitlement and published resources; removals can revoke historical archived or disabled associations.
6. Apply the scoped delta, advance a changed membership's version once, append audit and save the response receipt on the same connection. Exiting `db.transaction()` commits only a successful body and rolls back exceptions; helpers never commit independently.
7. After the transaction connection is released, append the journal outcome. An outcome failure may follow a successful commit and returns uncertainty. Retry the same key/payload under current authority; do not invent a replacement key.

Invitation acceptance locks its existing membership and invitation before receipt matching, so a matching receipt still requires current recent verified recipient binding. Protected report creation uses shared organization authority and reauthorizes resources even when returning its receipt. Catalog publication uses its own external-key mutex and `catalog_receipts`; it never uses a tenant access credential. These are deliberate differences, not candidates for a universal CRUD command wrapper.

## Independent journal around the transaction core

The implemented `journaled` wrapper prepares outside the transaction, passes its server-created reference through context-local state, and records that reference on audit and receipt. The local adapter persists a safe intent and outcome with file locking and fsync outside the recovered database. Client input cannot supply the trusted journal binding. Preparation failure denies the command with no domain effect; postcommit outcome failure is observable uncertainty rather than rollback.

The journal is evidence for recovery, not a permission store. Current authorization remains in the primary database. Restoring that database requires an independent marker and reconciliation before access reopens; unresolved prepared intent stays fenced. The local volume survives a database restore but shares its host, so independently durable live recovery requires a separate adapter and operational proof. [Delivery system](DELIVERY_SYSTEM.md) owns those limits and failure cases.

## Authorized selector example

This SQL pseudocode illustrates a consumer projection. Actual SQLAlchemy statements bind validated parameters, include the chosen locale and search predicate, and fetch at most `limit + 1` rows. It runs on the primary database. Management and migration selectors use their own explicit operation predicates rather than weakening this consumer predicate.

```sql
SELECT r.id, r.external_key, r.catalog_version
FROM memberships AS m
JOIN organizations AS o ON o.id = m.organization_id
JOIN projects AS p ON p.organization_id = o.id
JOIN project_resources AS pr
  ON pr.organization_id = o.id AND pr.project_id = p.id
JOIN resource_grants AS g
  ON g.organization_id = o.id AND g.membership_id = m.id
 AND g.project_id = p.id AND g.resource_id = pr.resource_id
JOIN resources AS r ON r.id = pr.resource_id
WHERE m.user_id = :validated_user_id
  AND o.id = :requested_organization AND p.id = :requested_project
  AND o.status = 'active' AND p.status = 'active'
  AND m.status = 'active'
  AND (m.expires_at IS NULL OR m.expires_at > :decision_time)
  AND pr.status = 'active' AND r.status = 'published'
  AND g.state = 'active'
  AND (:after_id IS NULL OR r.id > :after_id)
ORDER BY r.id
LIMIT :limit_plus_one;
```

## Patterns applied where they reduce a real problem

| Pattern or principle | Application and limit |
| --- | --- |
| SRP and cohesion | Handler parses, service coordinates, policy decides, scoped SQL helpers persist and adapter functions integrate |
| Dependency boundaries and injection | Explicit provider/configuration boundaries and a delivery adapter function argument; no service locator or custom injection framework |
| Narrow integration contracts | Identity, delivery and journal functions preserve their caller's expiry, failure and scope semantics; a live adapter must prove that contract before it replaces the local one |
| Controlled extension | Provider/source variations belong at their integration boundary; changing access semantics requires a reviewed policy and contract change |
| Service layer and transaction context | Validated explicit intent, one `db.transaction()` owner and reproducible receipt/retry scope |
| Scoped SQL helpers and selectors | Named write operations and bounded serialized reads through SQLAlchemy Core; no ORM repository hierarchy or universal CRUD layer |
| Adapter and strategy | Provider, delivery and verified source variations with a real contract; no pluggable authorization strategy that silently changes policy |
| Composition and configuration | Startup validates component credentials and budgets; unimplemented live adapters cause production refusal |
| Specification and state machine | Named policy predicates and explicit legal transitions; no dynamic query language or state machine framework |
| Decorator and facade | Cross cutting request correlation and typed HTTP client; no authorization decorator as the only enforcement |
| Observer, builder and template method | Deferred; the durable outbox covers the actual delivery need, ordinary constructors and explicit functions remain sufficient |
| KISS, DRY, YAGNI and fail fast | Shared business rules, small domain operations, early configuration and input rejection; deeper database guards remain mandatory |

Maintainability checks assess branching, nesting, duplicated policy and cross module imports. Splitting a function solely to improve a metric cannot remove an invariant or hide the transaction owner. The [decision matrix](DECISION_MATRIX.md) records alternative designs and the evidence needed to revisit them.

## Contracts, source and evidence ownership

| Change | Update together | Required evidence |
| --- | --- | --- |
| Permission or state transition | Owning service, pure predicate, independent policy cases and feature acceptance | Domain, real database races and endpoint concealment |
| Persistence relationship | Canonical SQL, Alembic migration, model description and ER source/export | Disposable structural constraints plus actual runtime transitions |
| HTTP request or response | Independent OpenAPI, adapter, generated frontend types and calling feature | Contract drift and actual response validation |
| UI interaction or shared control | Owning feature, shared semantics, UX contract and real capture where visible | Types/build and affected keyboard/browser journeys |
| Delivery, journal or writer authority | Owning service/adapter, local operations contract and operating procedure | Crash/retry/fence/recovery rehearsal against actual adapters |
| Release tooling | Execution graph, named scenario mapping and evidence collector | Current revision, real exit codes, artifact digests and offline archive verification |

The [implementation map](IMPLEMENTATION_MAP.md) identifies source; [execution graph](../specs/execution.json) owns task prerequisites; [scenario mapping](../specs/scenario-tests.json) binds behavior to named tests. There is no second illustrative implementation tree to reconcile. Client types are generated from committed OpenAPI and checked against the application surface. Tests use independent connections, explicit barriers and deterministic synthetic identities rather than timing assumptions or copied expected metadata.

T00–T12 deliver the local product and public package. T13–T14 retain private baseline, provider/host integration, approval and real cohort gates; local proof cannot satisfy those live requirements.
