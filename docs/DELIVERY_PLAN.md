# Scopegate delivery plan

Deliver a proven access boundary while the existing product continues to operate. P0 contains immediate defects; P1 proves the entire invitation to revocation journey; P2 expands only after access parity and migration rehearsal pass.

The delivery objective is the complete public product across P0 to P2, including migration and operational capabilities. A pilot validates the path but is not the final implementation boundary. Time is allocated to complete the agreed scope rather than fitting it into a fixed short session.

Status: delivery plan and historical estimates under an explicit capacity assumption, not committed deadlines. The local product is implemented within [the closed delivery scope](LOCAL_PRODUCT.md); [Validation](VALIDATION.md) and revision-bound runtime evidence establish its verified behavior. Live pilot and cohort rollout remain separate future work.

## Capacity and planning assumptions

Three engineers remain responsible for the existing product. Assume a combined 1.5 full time equivalents available to Scopegate, approximately 7.5 engineering days per calendar week. The principal lead, backend senior, and fullstack engineer provide that capacity; reliability work is a shared engineering responsibility, supported by Operations.

The estimates assume timely access to a representative data export, the existing application boundary, an OIDC test environment, and the catalog publisher contract. Product and Operations must be available for reconciliation decisions. Availability below 1.5 equivalents, integration discovery, or unresolved business rules increases elapsed time; do not compress verification to preserve a date.

## Delivery options

| Option | Scope | Release condition |
| --- | --- | --- |
| Containment only | Repair current null handling, unavailable resources, search, and atomic edits | Adequate if measured incidents stop and no unresolved structural access risk remains |
| Targeted access rebuild | Replace the access boundary and migrate by cohort | Preferred when explicit grants and repeatable reconciliation are needed |
| Full rewrite | Replace the surrounding product together with access | Reconsider only with evidence that the current product cannot safely host the boundary |
| Pause the build | Keep containment and instrumentation while resolving rules | Required for dependent rollout work if identity, entitlements, or migration approval remain unsettled |

The [product requirements](PRODUCT.md) define the cut line. An additional feature cannot displace authorization correctness, reconciliation, or rollback evidence.

## Phases and estimates

| Phase | Work | Engineering effort | Elapsed estimate at assumed capacity | Exit gate |
| --- | --- | --- | --- | --- |
| P0 Stabilization | Reproduce failures, contain null and not found paths, correct scoped search, make resource diffs atomic, collect baseline events | 3 to 6 engineering days | 1 to 2 weeks | Reproductions pass with persisted access unchanged on failed edits |
| P1 Access slice | Build the bounded domain, actual identity and publisher adapters, API, UI, audit, concurrent access checks, and migration dry run | 18 to 30 engineering days | 3 to 5 weeks | Complete journey and isolation pass against the intended database; integration and dry run evidence reviewed |
| Synthetic rehearsal preparation | Rehearse restore, compare synthetic decisions, exercise fenced synthetic cutover and compatible rollback | 3 to 6 engineering days | 1 to 2 weeks | No unexplained synthetic access difference; no live cutover or customer observation claimed |
| P2 Complete product | Finish management and operational workflows, the migration workbench, report reference reconciliation, all consumer fences, release packaging, and full P0 to P2 evidence | 20 to 30 engineering days | 3 to 5 weeks | Every P0 to P2 capability and quality gate is implemented and verified, including a representative full migration rehearsal |
| First live pilot (T13) | Complete private baseline, actual adapters and writer/consumer gates after local P2; cut over one reviewed organization and observe real use | Estimated after private discovery; additional to public product effort | At least the approved observation window and normal usage cycle; no deadline assigned yet | Every T13 approval, no unexplained access difference, actionable monitoring and tested recovery |
| Additional live cohorts | Repeat reconciliation and cutover for each materially different organization cohort | 8 to 15 engineering days per materially different cohort | 2 to 3 weeks per cohort | Cohort parity and operational gates pass independently |
| P3 Evolution | Address a measured product or operating constraint | Estimated after evidence and scope are defined | No date assigned | A concrete benefit justifies the added capability |

These ranges include design review and verification. They should be revised after P0 discovery and the first migration export. Parallel work may reduce waiting, but a release cannot skip a dependent gate. A live observation window starts only after local P2 is complete and T13 prerequisites pass. It includes enough real usage to exercise invitations, grants, resource use and revocation. Synthetic preparation cannot satisfy that window.

The complete public product is initially estimated at 44 to 72 engineering days across P0, P1, synthetic rehearsal preparation and P2. At 1.5 equivalents, that is roughly 6 to 10 weeks of available engineering capacity; an 8 to 13 week planning range allows for integration sequencing, review and synthetic rehearsal. The first real pilot and further cohort observation are additional work estimated after private discovery. This is an estimate to refine, not a deadline. Additional live cohorts and their unresolved historical exceptions are estimated separately because their number and data quality are not yet established.

The application stack follows the access and migration requirements: FastAPI and PostgreSQL preserve continuity at the existing application boundary, while React and TypeScript provide a typed management interface organized by feature. The real identity provider and publisher interfaces must be confirmed before dependent integration work and before the pilot.

## P0 Stabilization work

The backend senior first captures reproducible examples of missing metadata, unknown resources, incorrect search scope, and resource update behavior. Distinguish a controlled HTTP 400 rejection from any independently verified persistence defect. Record before and after access state for each reproduction.

The fullstack engineer makes optional metadata safe to render, gives unavailable resources a deliberate state, and keeps independent panels usable when a localized description is missing. Backend changes scope every query and update by organization/project, validate the complete resource diff, and commit it once.

Reliability records incident category, impact, request identifier, affected scope, and resolution. P0 ends when each reproduction has a focused regression check, failed mutations leave access unchanged, and the baseline collection path exists. Historical authorization ambiguity remains a migration concern, not an invitation to rewrite records opportunistically.

## P1 Implementation sequence

| Step | Owner | Work and dependency | Required evidence |
| --- | --- | --- | --- |
| 1 Domain contract | Principal lead with Product | Finalize membership, entitlement, grant, publication, and revocation rules before schema work | Approved invariants, unresolved decisions with owners, executable spec review |
| 2 Foundation | Backend senior and reliability | Configuration validation, schema migrations, error contract, scoped persistence, request identifiers, local environment guard | Empty database migration and invalid configuration rejection |
| 3 Identity and catalog seams | Backend senior with Operations and catalog publisher | Implement actual OIDC validation and the publisher contract adapter | Verified email mismatch rejected; local identity unavailable outside local; stable resource and locale fixtures |
| 4 Invitation and membership | Backend senior | Single use invitations with reviewed resource references, atomic acceptance/membership/grants, expiry, active/suspended membership, expiring staff assignments | Acceptance retry, expired token, wrong identity, suspended membership protection, and two organization staff checks |
| 5 Entitlements and grants | Backend senior | Scoped entitlement checks and atomic membership/project/resource diffs | Failed diff changes nothing; manager has no implicit consumption; stale version conflict leaves state unchanged |
| 6 Protected use and revoke | Backend senior with reliability | Serialize authorization admission with concurrent revocation according to the architecture contract | No admission begins after revocation commits; repeated revocation is safe; ordering is auditable |
| 7 User journey | Fullstack engineer | Organization/project navigation, invitation, grant preview, confirmed mutations, resource use, audit, and localized fallbacks | Browser journey, empty/failure states, scope switch behavior, accessibility checks |
| 8 Migration rehearsal | Backend senior with Product and Operations | Import snapshot, classify gaps, create dry run manifest, compare decisions, assign exceptions | Repeatable dry run with no live writes and no automatically approved unresolved record |
| 9 Release verification | Principal lead and reliability | Execute all local and CI gates, inspect evidence, rehearse restore and rollback | Recorded commands, real exit codes, parity review, operational signoff |

Steps 3 and the read only UI foundations can progress in parallel after the domain contract. Protected consumption depends on identity, membership, entitlement, grants, and resource publication. Mutation UI depends on stable API contracts. Pilot cutover depends on every earlier gate.

## Accountability

| Role | Accountable for | Decisions outside the role |
| --- | --- | --- |
| Principal lead | Architectural constraints, cross scope invariants, dependency order, technical release evidence | Commercial entitlement and automatic approval policy |
| Backend senior | Identity integration, data model, transactions, authorization, audit, import and reconciliation tooling | Accepting ambiguous historical grants without Product approval |
| Fullstack engineer | Complete workflow, tenant navigation, explicit resource diffs, accessible states, browser verification | Treating a hidden control as server authorization |
| Reliability responsibility | Incident baseline, concurrent verification, release checks, restore and rollback rehearsal | Waiving missing access parity to meet an estimate |
| Operations | Controlled manager bootstrap, staff assignment and expiry, environment configuration, executing cutover | Changing licensed entitlement rules |
| Product | Automatic approval policy, licensed entitlement interpretation, unresolved migration exceptions, pilot scope | Relaxing isolation or silently approving unresolved records |
| Catalog publisher | Stable resource identity, publication state, translations, and integration contract | Assigning organization or individual access |

Reliability is a named responsibility, not an assumption of a fourth engineer. Product and Operations approval concerns policy and live release decisions; routine implementation proceeds within the agreed scope.

## Pilot and migration gates

Before pilot, run the real OIDC adapter in the pilot environment, disable local demonstration identity, verify the catalog contract, resolve every exception in the cohort, and rehearse restore. A dry run reads a versioned snapshot and produces a manifest; it does not modify current grants.

Compare the proposed access tuples with approved current access. Broadened access, lost approved access, missing identities, ambiguous organizations, and unknown resources are explicit blockers for the affected cohort. Product resolves licensed entitlement and approval questions. Engineering never fills gaps with a broad default grant.

Cut over by bounded organization cohort using the controls in [migration](MIGRATION.md). Preserve a recoverable snapshot and an explicit rollback trigger. After cutover, the target remains the authorization authority. Application rollback may deploy an earlier compatible build while preserving current grants, revocations, and ownership fencing. Returning authorization to the legacy representation is outside this rollout. If no prior build can enforce current target state, fence the faulty operation and repair forward under target authority. Replacing the data store with an old snapshot alone can lose approved changes and revive revoked access.

Stop expansion after an authorization defect, parity drift, failed restore rehearsal, or an unowned migration exception. Continue investigation and independent implementation while the rollout remains contained.

## Complete product acceptance

The full product must implement invitations with explicit resource plans, viewer and manager workflows, controlled platform provisioning, expiring multi organization staff access, catalog publication and translations, protected resource/report admissions, atomic edits, audit, migration workbench, and operational recovery. Every supported legacy consumer must participate in policy comparison and writer fencing before its organization can cut over.

Release packaging includes reproducible dependencies, database migrations, synthetic fixtures, a working local startup path, production configuration checks, CI gates, and a documented demonstration. These outputs exist in the local product; the applicable runtime gates must pass for its recorded revision. P2 evidence covers API, database, browser, OIDC, publisher, replay, ownership epochs, concurrent revoke/use, and application rollback without lost revocations.

Public demonstration uses synthetic data. Live migration requires the authorized data inventory and operational decisions; it is never inferred from the success of the synthetic rehearsal.

## Release evidence

The release bundle must contain the specification version, migration manifest, parity report, open decision register, executed quality checks, browser evidence, concurrent admission/revocation evidence, environment identity configuration, restore rehearsal, and the pilot observation record. Each item names an owner and its result.

The [specification index](../specs/README.md) provides executable dependencies and contracts. The principal lead checks evidence against [architecture](ARCHITECTURE.md), the [data model](DATA_MODEL.md), and [UX](UX.md) before marking a phase complete. A planned test or a drafted runbook is not a passing release gate.

## Public implementation and live rollout gates

The implementation graph separates complete local product delivery from live migration. T00 through T12 use synthetic data, a local OIDC integration provider, explicit contracts, and a full migration/recovery rehearsal. Missing live manifests or private integration configuration do not block foundation, UI, or public packaging. They remain explicit questions and assumptions. T13 requires the real identity provider, every live consumer and writer, reviewed intended-access manifests, shadow parity, and operating approvals before a real organization pilot. T14 rolls out further reviewed cohorts and delays contraction. Synthetic evidence cannot satisfy either live gate.
