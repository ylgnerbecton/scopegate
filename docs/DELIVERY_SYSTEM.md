# Scopegate delivery and recovery system

Scopegate's delivery system turns the approved contracts into reproducible releases while keeping authorization authority and current revocations intact. Local development and CI use the same gate commands. A real organization rollout adds reviewed identity, host, consumer, data, and recovery inputs; synthetic evidence cannot complete those live gates.

The repository provides specification/schema checks, runtime entrypoints, locked images, durable leases, local traces/metrics and a Compose deployment. The sequence below also defines future live delivery requirements; LOCAL_PRODUCT.md distinguishes their scope from the executable local release. [execution.json](../specs/execution.json) owns task dependencies, and [Quality](QUALITY.md) owns behavioral acceptance.

## Reproducible foundation

Use Python 3.12 as the accepted backend baseline, PostgreSQL 18 for fresh local environments, and proposed Node.js 24 LTS for frontend tooling. Pin the exact supported patch, package manager version, dependency lockfiles, and image digests in the foundation manifest. Reconfirm support at foundation rather than committing a floating latest tag. Node's primary release page identifies its supported LTS branches; the selected Vite version's documented runtime range must also pass. [Node releases](https://nodejs.org/en/about/previous-releases), [Vite requirements](https://vite.dev/guide/).

Backend dependency installation is locked and hash-verified where the selected package manager supports it. Frontend uses a committed package lock and a frozen install such as `npm ci`. CI fails on lockfile drift. Base images and third-party workflow actions use immutable digests or full commit SHAs. A scheduled dependency update is a normal small pull request with affected tests, scans, compatibility notes, and owner review; it does not silently change release artifacts.

One Compose definition supplies database, HTTP process, web development interface, local integration identity provider, and protected synthetic delivery adapter. The application image also starts the supervised outbox worker. Local ports and resources are explicit; startup never stops unrelated developer services. Environment validation rejects unknown mode, missing issuer, incompatible schema, inadequate pool allocation, absent required delivery key material, or production use of the local identity adapter.

`make setup`, `make deps`, `make up`, `make bootstrap`, `make dev` and `make down` are implemented. Setup generates restricted local secrets; deps performs frozen installation; up migrates and seeds the owned deployment. Missing tools are failures. Seed requires a named synthetic environment and cannot overwrite production. Down removes only this project's owned resources; it does not prune global Docker state. Preserve deterministic fixture IDs and versions for contract and browser scenarios.

## Trunk development and review

Use trunk-based development with short-lived branches and small cohesive pull requests. Each change names its acceptance scenarios, dependencies, public and private inputs, and excluded work. Prefer one reviewable behavior per pull request; do not split a transaction invariant across unrelated branches merely to reduce the diff. Incomplete user-visible behavior stays behind a reviewed flag with an owner and expiry.

The author runs the applicable gates locally and records the exact revision and result. A reviewer checks behavior, security boundaries, transaction ownership, coupling, duplication, failure handling, and reversibility against the mandatory standards. Cross-module policy or schema decisions need an ADR or RFC before implementation. Interfaces and patterns are introduced at demonstrated boundaries, rather than adding a framework to satisfy a pattern inventory.

Main must remain releasable. Required statuses cannot be bypassed by a successful aggregate job that skipped failing children. A missing binary, insufficient test environment, unavailable provider fixture, timeout, or empty suite is a failed or blocked gate. Draft design and synthetic implementation progress continue while private live inputs are unavailable; live release eligibility remains blocked.

## Local and CI gate map

The following IDs use the execution registry. All twelve local gate entrypoints are implemented. Runtime CI fails when a required tool, command or proof is absent; live deployment and approval steps remain external.

| Gate | Intended command | Trigger and blocking condition | Evidence and owner |
| --- | --- | --- | --- |
| Planning consistency | `make check` | Every change; malformed contracts, missing scenario references, or contradictory planning blocks merge. | Contract validation at revision; principal lead. |
| Planning graph | `make plan` | Dependency or task changes; cycles and unknown inputs block implementation selection. | Ordered task graph and input gates; principal lead. |
| Fresh structural schema | `make check-schema` | SQL changes and release baseline; DDL or structural negative failure blocks merge. | Engine, check counts, exit status, own-container cleanup; backend owner. |
| G-LINT | `make lint typecheck` | Code changes; mandatory standards, Python or TypeScript typing, or formatting failures block merge. | Tool versions, complexity report and diagnostics; module owner. |
| G-DOMAIN | `make test-unit` | Policy, transitions, clock, or adapter changes; missing negative scenario or failed policy branch blocks merge. | Independent allow/deny and transition cases; backend owner. |
| G-DATABASE | `make test-integration` | Persistence or transactional changes; partial writes, bad scoped relationship, lost update, or incorrect lock ordering blocks merge. | Real PostgreSQL multi-connection evidence; backend owner. |
| G-CONTRACT | `make check-contracts` | API, schema, client, or compatibility changes; incompatible generated contract blocks merge. | OpenAPI and generated client diff plus response cases; API owner. |
| G-IDENTITY | `make test-identity` | Identity and invitation binding changes; failed signature, issuer, audience, callback, freshness, or logout case blocks release. | Local provider integration; production provider record separately at T13; identity owner. |
| G-BROWSER | `make test-browser` | UI behavior or critical API changes; account switch leak, inaccessible critical flow, or replay behavior blocks release. | Browser journeys and accessibility artifacts; fullstack owner. |
| G-MIGRATION | `make test-migration` | Mapping, ledger, fencing, authority, or compatibility changes; unexplained access change or revocation loss blocks release. | Synthetic source replay and target-only rollback; migration owner. |
| G-PERFORMANCE | `make test-performance` | Query, pool, bounds, concurrency, or release changes; missing workload, budget violation, leak, or unbounded query blocks release. | Capacity report and plans from [Capacity](CAPACITY_PLAN.md); backend and platform owners. |
| G-SECURITY | `make test-security` | Every release and security-sensitive change; exposed secret, unsafe configuration, exploitable high finding, or policy bypass blocks release. | SAST, dependency, image, secret, DAST and negative endpoint evidence; security owner. |
| G-OPERATIONS | `make test-operations` | Delivery, readiness, shutdown, timeout, telemetry, recovery, or release changes; unbounded failure or unsafe restore blocks release. | Fault matrix, SLO signals, lease crash and journal restore; platform owner. |
| G-BUILD | `make build smoke` | Release candidate; image, static build, migration compatibility, startup, or scoped smoke failure blocks promotion. | Artifact digests, SBOM and migration checks; release owner. |
| G-RELEASE | `make check-runtime` | Release candidate; any applicable gate missing or failed, or a live prerequisite unresolved, blocks promotion. | Signed release evidence manifest and input approvals; principal lead and release owner. |

Run unit and contract checks broadly on each code pull request. Integration, security, and affected browser tests run on their relevant changes; every release candidate runs all gates at the exact artifact revision. Capacity and operations scenarios may use a controlled scheduled environment between changes, but promotion requires a passing result for the candidate or an explicitly proven unchanged artifact and environment. A passing old report cannot certify changed query, timeout, or pool settings.

## Supply chain and secrets

Build once and promote the same image and web artifact digests through test, pilot, and rollout. Generate an SBOM, record dependency and base image digests, scan both source dependencies and final artifacts, and attach signed provenance when the selected registry supports verified signing. Reject unsigned or unverified promotion when the configured release policy requires it. A scan of source alone does not prove the built image is clean.

CI uses read-only repository permissions by default, elevated job permissions only where necessary, and isolated credentials for publication and deployment. Untrusted pull requests receive no deployment or production secrets. Pin workflow actions to full SHAs and review what they execute; GitHub's primary guidance treats immutability and minimum permissions as supply-chain controls. [GitHub workflow security](https://docs.github.com/en/actions/reference/security/secure-use).

Use separate external secrets for application, catalog publisher, operations, migration, delivery, journal, and backup roles. Workload identity or short-lived credentials are preferred when the selected host supports them. DDL credentials are restricted to the migration release job and unavailable to ordinary HTTP or worker processes. A database runtime role owns no application table, has no superuser or bypass permission, and cannot update or delete audit evidence.

Secret scanning covers files, histories introduced by the change, build contexts, logs, and release artifacts. Redaction is not a substitute for avoiding secret output. If exposed, rotate the credential and investigate access; deleting the current file does not erase history. High and critical exposures block release unless the security owner approves a specific bounded exception with expiration and compensating controls. Policy defects and confirmed cross-organization access have no error-budget waiver.

## Host adapter and infrastructure ownership

Use the existing hosting environment through a small explicit adapter. Discover the runtime supervisor, ingress and TLS termination, secret distribution, database service and backup mechanism, registry, delivery provider, identity issuer, and telemetry destination before choosing infrastructure code. Do not invent a cloud account, Kubernetes installation, or managed-service SLA.

Infrastructure definitions must reproduce the selected host's resources and policy: environment isolation, least-privilege roles, network paths, resource limits, protected secret references, backup and journal destinations, health checks, deployment concurrency, and alert ownership. Use the host's existing supported infrastructure tool. A provider change or orchestration platform adoption requires an RFC with necessity, cost, operating owner, and restore implications; Compose remains the local interface regardless.

Separate developer test credentials, local integration provider credentials, and production identities. A hosted demonstration needs a real configured provider and synthetic data; it does not receive private manifests. Public evidence contains hashes, versions, synthetic outcomes, and commands. Private evidence stays in the approved operational store.

## Database release sequence

Alembic runs once as a controlled release job with the migration owner role. HTTP workers never race to migrate at startup. Check compatibility with the currently serving and rollback-eligible application versions. Fresh PostgreSQL 18 schema validation is separate from an existing PostgreSQL 15 expand and backfill rehearsal; changing the engine and access model together is excluded.

1. Validate the expand migration in a disposable copy, including lock duration, constrained writes, rollback eligibility, and resource budget.
2. Apply additive compatible DDL through the release job while the current authority remains in place. Use bounded lock and statement settings; a busy lock aborts the migration rather than blocking customer work indefinitely.
3. Deploy the compatible application artifact and controlled adapters. Backfill and constraint validation run in bounded maintenance allocation, with ledger and fence checks.
4. Perform shadow and reviewed organization cutover under [Migration](MIGRATION.md). A schema deployed successfully is not permission to move access authority.
5. Delay contraction until every consumer, observation window, backup retention, and target-compatible rollback condition is satisfied. An irreversible column or legacy writer removal needs explicit review.

Migration failure leaves the old compatible application serving where safe, with no partially approved cutover. Destructive schema downgrade is not the routine rollback. Role privilege tests run using actual runtime credentials; a successful superuser structural test cannot prove least privilege.

## Feature flags and canary cohorts

Each flag has a named owner, purpose, supported environments, default, expiry, dependency, and removal task. Record flag values in the release evidence. Evaluate authorization-related ownership in the primary transaction; a distributed feature flag cache cannot override `organizations.access_mode`, `migration_controls.write_fenced`, or writer epoch. Use flags for UI or compatible implementation selection, not to skip entitlement or grant checks.

Proposed live application observation stages are 5%, 25%, and 100% of eligible approved organizations, with minimum one organization in the first stage. Percentages select whole organizations from a recorded manifest, rounded up and limited to the eligible count; every request for an organization uses its selected artifact and authority. Random per-request traffic splitting cannot send one organization's grant writes to incompatible owners. Already cutover organizations remain under target authority throughout.

| Stage | Proposed minimum observation | Advancement evidence |
| --- | --- | --- |
| 5% of eligible organizations | 24 hours and one normal operating cycle | Zero invariant failure, complete audit and lease behavior, latency budgets, successful allowed and denied synthetic probes. |
| 25% of eligible organizations | 48 hours and the relevant job cycle | Stable request SLO, pool and lock budget, no hidden hot-tenant regression, reviewed incident and parity record. |
| 100% of eligible organizations | 72 hours before retiring the previous artifact | Current target state and rollback eligibility preserved; recovery and ownership inventory complete. |

The windows are proposals to align with actual usage. Organizations without approved identity mapping, current manifest, drained source deltas, or required integration evidence are ineligible, irrespective of the desired percentage. A low-traffic canary needs explicit probes and functional scenario coverage; elapsed quiet time alone is insufficient.

Stop expansion and fence the affected operation immediately on a confirmed unsafe allow, cross-organization disclosure, missing mutation audit, lost revocation, stale writer commit, or unexplained access difference. Sustained mutation unavailable ratio above 1% for five minutes, burn-rate alert, endpoint p95 over budget for two five-minute windows, or outbox due age over five minutes triggers investigation and rollback eligibility review. Error rates include accepted user timeouts and overload. Metadata-only defects may disable the affected panel while authorization remains enforced.

## Startup readiness and graceful stop

`/health/live` reports process responsiveness. Readiness confirms valid environment, compatible migration version, usable primary connection within a bounded one-second probe, required key and adapter configuration, and admission state. It rejects production local identity configuration and startup with insufficient connection allocation. An unavailable external delivery provider does not make an otherwise safe HTTP process unready; its queue and breaker expose separate dependency health. An identity outage affects new authentication, not proof that current database sessions are valid.

For organization-specific migration fencing, readiness remains a process capability check. Requests to a fenced operation return its explicit transition response; hiding a single blocked organization by marking the whole deployment healthy does not authorize it. A fresh process reads current modes and epochs before accepting writes.

On HTTP shutdown, mark readiness false, stop admissions, allow up to 30 seconds for already admitted bounded requests, and roll back overdue transactions before disposing pools. The host supervisor gets a proposed 40-second termination grace to preserve the ten-second cleanup margin. Do not return success for a transaction cancelled at shutdown. Replacements are admitted only when the previous pools no longer consume the connection allocation.

An outbox worker first stops claiming. It may finish a current four-second provider attempt and persist an outcome if it still holds the lease token; it never extends a lease indefinitely to avoid shutdown. Unknown external outcome remains reclaimable after lease expiry. A worker that cannot safely record its result exits without manufacturing delivery success. Backfill stops between bounded chunks and records its committed watermark. Process kill, rollback, and crash cases are required `G-OPERATIONS` evidence.

## Restore and authorization intent journal

Routine application rollback deploys only a previously verified target-compatible artifact. Current target schema, ownership, grants, revocations, sessions, invitations, receipts, and audit remain authoritative. If no previous artifact can enforce them, fence the faulty operation and repair forward. Restoring an old database snapshot or changing authority back to legacy is not an application rollback.

Disaster recovery needs a private, externally durable intent journal beyond the recovered database. The host adapter must define acknowledgment durability, ordering and retention before a live claim of permission-preserving recovery. Proposed intent flow is:

1. Validate the authenticated command's shape and record a minimal prepared intent with actor and scope, expected version, operation, request digest, bounded access delta, and unique journal key. Obtain external durability acknowledgment before starting the access transaction. A journal-required live access mutation returns unavailable if preparation fails, without changing access.
2. Execute the normal primary transaction, rechecking current identity, authority, locks, versions, and policy. Its audit event and command receipt carry the same `journal_reference`; this linkage is mandatory for journal-required live access mutations, while nonaccess and catalog evidence may omit it. The journal acknowledgment alone grants nothing.
3. After the database commit and connection release, append the outcome referencing the committed audit and response digest. A failure to append outcome is observable and requires reconciliation; the prepared intent still identifies the potentially committed change.

The synthetic local adapter appends a restricted minimal record to a file outside the disposable database, flushes and `fsync`s it before acknowledgment, and synchronizes creation metadata. Its ordered append and concurrent-writer behavior are tested. A file on the same developer host demonstrates database-restore reconciliation; it does not prove recovery from host loss or production durability. T13 selects an independently durable host store with documented acknowledgment semantics, ordering, retention, encryption, and access controls. A durable audit outbox in the same database cannot replace this external intent journal.

This protocol is deliberately not described as a distributed atomic commit. Prepared intent can outlive a rejected transaction, and a commit can precede the external outcome record. During restore, uncertain revocation intent blocks use of affected relationships until reconciled; uncertain addition intent does not grant access. Recovery compares journal, receipts, audit, ledger, current identity state, and reviewed manifests. Retrying an unresolved command uses its original scope and key. Journal unavailability blocks journal-required access mutations, while current approved primary consumption continues unless an unresolved restore or revocation requires fencing. This is an explicit durability versus mutation-availability tradeoff.

Keep the restored environment fenced while verifying target authority and epochs, constraints, session revocation, invitation acceptance and supersession, outbox outcomes and secrets, receipt validity, audit continuity, and every affected access decision. Rotate or invalidate sessions if the recovered session revocation history cannot be established. An expired or purged invitation payload cannot be regenerated as an old valid token. Preserve external provider outcomes to avoid uncontrolled delivery replay.

The proposed RPO at most five minutes and RTO at most 60 minutes are objectives pending host capability, journal durability, privacy, retention, and rehearsal approval. RTO includes access reconciliation and safe readiness, not merely database startup. Measure backup age, restore duration, journal catch-up, unknown decision count, and explicit no-revived-revocation probes. Unknown journal gaps block affected reopening even if an infrastructure restore meets its time target.

## Evidence and live prerequisites

The release manifest records revision, image and web digests, locks and SBOM, schema and adapter versions, gate commands and actual exit codes, measured budgets, flags and expiry, selected organization cohort, authority epochs, baseline revision, backup and journal references, rollback artifact, owner approvals, and observation outcome. Store private identities, payloads, snapshots, and access manifests separately; public records use synthetic examples.

T00 through T12 can implement and prove the complete local product with a local provider, synthetic manifests, delivery fault injection, and an isolated restore environment. T13 additionally needs the actual issuer and callback configuration, verified identity mappings, complete live consumer and writer inventory, approved intended-access manifest, host resources and pool reserve, provider quotas and deduplication, external key and journal stores, backup and retention approvals, and operational signoff. T14 advances only reviewed whole-organization cohorts and delays contraction.

The principal lead owns gate coherence. Platform owns release, secrets, capacity, and recovery mechanics. Identity and delivery owners validate their external adapters. Product and organization owners approve access intent and live impact. Every unanswered integration question has an owner and remains a visible live gate; it does not prevent independent synthetic implementation.
