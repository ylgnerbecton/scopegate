# Scopegate Domain Design

Scopegate's domain separates identity, organization authority, catalog publication and individual resource use. This design defines the responsibilities and transaction boundaries of the local implementation. The [schema](../specs/contracts/schema.sql), [HTTP contract](../specs/contracts/openapi.json) and [local operations contract](../specs/contracts/local-operations.json) define its persistence and interfaces. The [implementation map](IMPLEMENTATION_MAP.md) identifies the actual source; examples below illustrate responsibilities rather than a literal source layout. The [live CLI blueprint](../specs/contracts/migration-cli.json) retains future private integration requirements.

Status: local implementation design with illustrative examples. The continuity and irreversible revocation assumptions in [ADR 6](adr/0006-manager-continuity-and-entitlement-revocation.md) require Product and Operations validation against the private baseline before a real organization cutover.

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

Domain code imports standard types and domain value objects. Application services import domain rules and narrow ports. SQLAlchemy, FastAPI and provider SDKs belong to adapters. A composition root constructs concrete adapters and injects them explicitly. HTTP handlers cannot import another module's table and bypass its use case. Migration applies reviewed changes through the same mutation invariants, rather than a permissive backfill repository.

Read selectors may join across contexts to produce a bounded authorized projection. They expose DTOs, not ORM objects or lazy relationships. Write repositories are named for their domain purpose and preserve the ownership boundary. The schema provides composite integrity; the policy provides time, status and operation authority. Neither layer substitutes for the other.

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

## Proposed component layout

```text
backend/src/scopegate/
  bootstrap.py                         explicit application composition
  identity/{domain,application,adapters}/
  organizations/{domain,application,adapters}/
  access/domain/{commands,policy,state}.py
  access/application/{grant_service,ports,selectors}.py
  access/adapters/{postgres,http}.py
  invitations/{domain,application,adapters}/
  catalog/{domain,application,adapters}/
  reports/{domain,application,adapters}/
  migration/{application,adapters}/
  audit/{application,adapters}/
  delivery/{application,adapters}/
frontend/src/
  app/{router,SessionBoundary,WorkspaceShell}.tsx
  features/resources/{ResourceLibrary,ResourceCard,ReportConfigPanel}.tsx
  features/members/{MemberList,MemberDetail,GrantEditor,GrantDiffReview}.tsx
  features/invitations/{InvitationList,InvitationForm,InvitationAcceptance}.tsx
  features/audit/AuditFeed.tsx
  features/migration/{MigrationWorkbench,LedgerTable,DecisionForm}.tsx
  shared/api/{client.ts,generated/}
  shared/{queryKeys.ts,ui/}
```

This is an illustrative dependency layout, not generated source. A small context can use fewer files until responsibilities need separation. Module import checks must prevent domain to adapter imports and cross context write access.

| Component or port | Responsibility and contract |
| --- | --- |
| `AccessPolicy` | Pure operation predicates over immutable facts and an explicit decision time; shared by commands and protected consuming adapters |
| `AuthorizationSelector` | Primary database projection of scoped facts; query predicate and policy parity tested against the same truth table |
| `AuthorizationLocks` | Ordered resource, organization, membership and invitation locks; it does not decide permission |
| `MembershipRepository`, `GrantRepository` | Scoped domain state reads and writes; no generic entity repository and no implicit commit |
| `CommandReceiptRepository`, `CatalogReceiptRepository` | Canonical fingerprint matching and minimal response replay within the supported window |
| `IdentityProvider` | Code exchange and validated claims from the configured issuer; environment permitted adapters must preserve the same trust contract |
| `SourceAdapter` | Private baseline facts with provenance and explicit unresolved records; no inferred identity assignment |
| `DeliveryAdapter` | One bounded provider attempt with a stable delivery key; reports accepted, rejected or unknown outcome |
| `EnforcementAdapter` | Existing computation boundary that carries the authenticated actor and scope, then checks current access for protected output |
| `WorkspaceShell` and feature routes | Organization and project scope, authorized navigation and query lifecycle; they cannot grant authority |

The frontend route tree composes `SessionBoundary` → `WorkspaceShell` → one feature page. `MemberDetail` opens `GrantEditor`, whose reviewed draft passes through `GrantDiffReview` before mutation. `InvitationAcceptance` has a recipient session boundary and authenticated preview before the acceptance command; it does not require preexisting organization membership. `MigrationWorkbench` composes paged ledger and decision panels only for the scoped reviewer capability. Shared UI contains accessible controls and loading/error presentation; feature rules remain in their feature and server contract. TanStack Query owns remote state, while each page owns its temporary draft. Query keys contain principal, organization and project where applicable; switching scope cancels old requests, resets drafts and invalidates departed data under the [workflow contract](UX.md#navigation-and-scope).

## Explicit service and unit of work example

The following Python illustrates control flow. Domain types and repository interfaces are intentionally named for access operations; implementation must provide their concrete methods and tests. `database_time` comes from the database after lock acquisition, and `snapshot` runs as a new statement. No provider or delivery call occurs inside this transaction.

```python
from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

class AccessUnitOfWork(Protocol):
    locks: AuthorizationLocks
    memberships: MembershipRepository
    grants: GrantRepository
    entitlements: EntitlementRepository
    sessions: SessionRepository
    authorization: AuthorizationSelector
    receipts: CommandReceiptRepository
    audit: AuditRepository

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 traceback: TracebackType | None) -> None: ...
    def database_time(self) -> DecisionTime: ...
    def commit(self) -> None: ...

class GrantService:
    def __init__(
        self,
        unit_of_work: Callable[[], AccessUnitOfWork],
        policy: AccessPolicy,
    ) -> None:
        self.unit_of_work = unit_of_work
        self.policy = policy

    def apply(self, actor: SessionPrincipal, command: GrantDiff,
              prepared: PreparedIntent | None) -> GrantDelta:
        command.validate_shape()  # Disjoint sets and at most 100 in each.
        command.require_journal_binding(prepared)  # Mandatory for live journal-required commands.
        journal_reference = prepared.reference if prepared is not None else None
        with self.unit_of_work() as work:
            work.locks.resources_shared(sorted(command.resource_ids))
            work.locks.organization_exclusive(command.organization_id)
            member = work.memberships.lock_scoped(command.target)
            at = work.database_time()
            principal = work.sessions.require_current(actor, at)
            snapshot = work.authorization.snapshot(principal, command.scope, at)
            self.policy.require_manage(snapshot)

            prior = work.receipts.match(command.receipt_scope(principal),
                                        command.fingerprint)
            if prior is not None:
                return prior.result  # No new state transition or commit.

            member.require_version(command.expected_version)
            additions = work.entitlements.snapshot_scoped(command.scope, command.add)
            removals = work.grants.snapshot_scoped(command.scope, command.remove)
            self.policy.require_grant_additions(snapshot, additions, at)
            self.policy.require_grant_removals(snapshot, removals)
            changes = work.grants.apply_delta(command.target,
                                              command.add, command.remove)
            if changes:
                member.advance_access_version()
                work.memberships.save(member)
                work.audit.append_grant_change(principal, command, changes, at,
                                              journal_reference=journal_reference)
            result = GrantDelta(member.access_version, changes)
            work.receipts.record(command.receipt_scope(principal),
                                 command.fingerprint, result,
                                 journal_reference=journal_reference)
            work.commit()
            return result
```

The unit of work defaults to rollback on exit unless explicitly committed. Repositories do not commit or perform external work. They return scoped facts for the pure policy rather than defining independent allow rules. The membership save explicitly persists its domain version. Session validation here is a read; idle touches finish in the request boundary transaction before domain locks. Receipt matching rejects a reused key with a different fingerprint; expected version is checked only for a new command. Current authority is checked before returning a prior result. The service returns the changed delta, never a full grant inventory.

## Live journal wrapper around the transaction core

The illustrated GrantService is the locked transaction core. Its application orchestrator validates current request identity and shape, calls the durable journal prepare port outside any database transaction, and passes a server-created PreparedIntent bound to actor, scope, operation, idempotency key and request fingerprint. Client input cannot supply that proof. Live configuration requires this prepared reference; the local synthetic adapter follows the same flow independently of the recovered database.

After the core returns and its connection is released, the orchestrator appends the outcome with the receipt and committed audit references. Audit and receipt persist the same journal_reference. Preparation failure rejects the mutation with 503 and no effect. Outcome failure after commit is observable uncertainty; it cannot be presented as rollback or trigger a new-key retry. The durable prepared record supports reconciliation. No journal or provider I/O occurs while resource or organization locks are held. The prepare port deduplicates the bound command key; conflicting fingerprints fail, and repeated matching outcomes remain harmless. Delivery system defines the recovery and live approval requirements.

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
| SRP and cohesion | Handler parses, service coordinates, policy decides, repository persists and adapter integrates |
| Dependency inversion and injection | Constructor injected provider, persistence and delivery ports; no service locator or custom injection framework |
| Interface segregation and substitution | Narrow ports reflect a caller's actual needs; adapters preserve expiry, failure and scope semantics instead of broadening permission for convenience |
| Open/closed principle | A real provider or source variation is added behind its port; changing access semantics requires a reviewed policy and contract change |
| Service layer, command and unit of work | Immutable intent, one transaction owner and reproducible retry scope |
| Domain repository and selector | Domain write operations; bounded DTO reads; no universal CRUD repository |
| Adapter and strategy | Provider, delivery and verified source variations with a real contract; no pluggable authorization strategy that silently changes policy |
| Factory | Composition root selects an environment permitted adapter; production validation precedes construction |
| Specification and state machine | Named policy predicates and explicit legal transitions; no dynamic query language or state machine framework |
| Decorator and facade | Cross cutting request correlation and typed HTTP client; no authorization decorator as the only enforcement |
| Observer, builder and template method | Deferred; the durable outbox covers the actual delivery need, ordinary constructors and explicit functions remain sufficient |
| KISS, DRY, YAGNI and fail fast | Shared business rules, small domain operations, early configuration and input rejection; deeper database guards remain mandatory |

Maintainability checks assess branching, nesting, duplicated policy and cross module imports. Splitting a function solely to improve a metric cannot remove an invariant or hide the transaction owner. The [decision matrix](DECISION_MATRIX.md) records alternative designs and the evidence needed to revisit them.

## Implementation artifacts by task

This table preserves the original task blueprint and conceptual paths. The implemented source layout is in [Implementation map](IMPLEMENTATION_MAP.md); the paths below are illustrative and are not a second inventory of delivered files. The [execution graph](../specs/execution.json) owns prerequisites and completion evidence. The local product uses committed uv and npm lockfiles for reproducible installation.

| Task | Code and artifact paths | Boundary to prove |
| --- | --- | --- |
| T01 Foundation | `backend/pyproject.toml`, backend dependency lockfile, `backend/src/scopegate/bootstrap.py`, `frontend/package.json`, frontend dependency lockfile, `compose.yaml`, runtime Make targets and CI workflow | Environment validation, thin API startup, generated client pipeline and reproducible builds |
| T02 Persistence | `backend/alembic/versions/`, context `adapters/postgres.py`, `backend/tests/integration/test_tenant_constraints.py`, `backend/tests/fixtures/target/` | Canonical DDL equivalence, domain scoped repositories and direct structural rejection |
| T03 Identity and provisioning | `identity/application/login_service.py`, `identity/adapters/oidc.py`, `identity/adapters/session_store.py`, `organizations/application/provisioning_service.py` | Verified issuer and subject, trusted session claims, logout and durable first manager |
| T04 Catalog and entitlement | `catalog/application/publish_service.py`, `catalog/adapters/http.py`, `organizations/application/entitlement_service.py` | Publisher receipt and version, terminal archive, reviewed bounded disable and no revival |
| T05 Access | `access/domain/policy.py`, `access/domain/commands.py`, `access/application/grant_service.py`, `access/application/ports.py`, `access/adapters/postgres.py` | One pure policy, constructor injection, access version, scoped delta and ordered transaction |
| T06 Enrollment and delivery | `invitations/application/enrollment_service.py`, `invitations/adapters/http.py`, `delivery/application/worker.py`, `delivery/adapters/` | Recipient proof, receipt before pending check, one acceptance and durable delivery lease |
| T07 Resource and report reads | `access/application/resource_selector.py`, `reports/application/report_service.py`, `reports/adapters/enforcement.py` | Bounded authorized projections and current authorization at each consuming boundary |
| T08 Migration | `migration/application/{profile,backfill,compare,ownership}.py`, `migration/adapters/cli.py`, `migration/adapters/http.py`, `backend/tests/fixtures/legacy/` | Private source port, reviewed mappings, replay ledger, epoch fence and scoped review |
| T09 Web workspace | `frontend/src/features/`, `frontend/src/shared/api/generated/`, `frontend/src/shared/queryKeys.ts`, `frontend/src/app/session.ts` | Generated OpenAPI types, tenant state reset, confirmed mutations and accessible workflows |
| T10 Integrated gates | `backend/tests/{unit,integration,contracts,security}/`, `frontend/tests/`, browser suite and runtime gate workflow | Real database schedules, fault injection, endpoint concealment and provider integration evidence |
| T11 Local demonstration | Synthetic seed command, complete local journey script, synthetic restore and rollback evidence | Several organizations, no implicit grants, deterministic delivery and truthful adapter labeling |
| T12 Public packaging | Setup commands, screenshots from synthetic data, accurate README and `docs/VALIDATION.md` evidence | Complete local product evidence without claiming private integrations or live cutover |

Client types are generated from the committed OpenAPI contract and checked against the application's generated OpenAPI. Handwritten API DTO duplicates cannot drift from that generation. Fixtures have deterministic identities and clocks, intentionally conflicting relationships and explicit expected outcomes. Use fixed barriers for concurrency scenarios instead of brittle timing sleeps. T13 and T14 retain their additional private integration, baseline, approval and real rollout gates; local packaging cannot satisfy them.
