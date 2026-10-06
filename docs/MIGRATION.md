# Access model migration

Move each approved organization from legacy access storage to the Scopegate model through expand, backfill, shadow, canary, and contract phases. The safety condition is precise: no principal gains or loses effective access without an explicit reviewed decision. Data parity alone is insufficient because the legacy source does not expose the authorization rule used by resource consumers.

The target model and transaction rules are defined in [DATA_MODEL.md](DATA_MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [SECURITY.md](SECURITY.md). This is an implementation and operational specification. The migration controls, scripts, compatibility adapters, and runtime described here must be implemented and verified before use.

## Nonnegotiable invariants

1. Verify the existing consumption decision before comparing it with the target. Neither the union nor the intersection of legacy resource lists proves effective access.
2. Resolve every affected identity to a verified OIDC issuer and subject. Email is contact information and an invitation delivery attribute; matching email never merges identities.
3. Make organization and project ownership explicit. Similar project labels, locale rows, report references, and operator roles cannot create entitlements.
4. Preserve every grant and revocation recorded after cutover when rolling back application code. Restoring an old snapshot is not an access rollback.
5. Keep one write authority for each organization and epoch. A transaction cannot silently write both an old owner and a new owner.
6. Commit a grant mutation, version change, and audit event together. The existing separately committed delete and insert are unsuitable for migration or compatibility writes.
7. Treat missing metadata as a content issue. Locale coverage and fallback never grant or remove resource access.
8. Preserve report configurations and isolated legacy tables until their consumers, retention rules, and retirement are verified.

## Authority and access baseline

Locate every consumer that generates work or returns protected resource data. Trace the point at which it permits or denies a request, including organization, project, principal, resource, action, and any time-dependent condition. Include jobs, report generation, exports, scheduled tasks, and administrative paths. A gateway that authenticates a request does not establish the resource authorization rule.

For a verified consumer, record the executed resolver version and compare decisions with the target on a consistent data and time snapshot. If the resolver cannot be recovered, require the organization owner and security owner to approve a complete intended-access manifest. Mark its decisions as reviewed policy establishment, rather than claiming legacy parity. An organization stays under legacy authority until one of these baselines is available and its discrepancies are reviewed.

The baseline manifest records a verified principal, organization, project, resource, action, expected allow or deny, reason, evidence, reviewer, approval time, and validity interval. Preserve negative decisions as well as positive decisions. A positive list alone cannot detect newly broadened access. Explicitly cover suspended memberships, expiring staff assignments, disabled entitlements, archived resources, revoked grants, and users who have no membership.

Every difference is classified as one of the following:

| Classification | Handling |
| --- | --- |
| Exact agreement | Record the compared inputs, policy versions, time, and decision digest. |
| Approved policy change | Attach the owner decision, reason, affected principals and resources, activation time, and security review. |
| Unresolved access gain | Block organization cutover and prohibit the target from granting it. |
| Unresolved access loss | Block organization cutover; do not interpret a stricter target decision as automatic approval to remove access. |
| Invalid or unknowable input | Quarantine the relationship for review; do not manufacture an identity, project, resource, or grant. |

Reconciliation is an explicit queue with accountable owners. A quarantine record identifies the affected organization when known, the blocked relationships, the reason, and the evidence required. A retired relationship needs a reviewed retirement decision. The count of blocking unresolved items must be zero for the organization entering canary; hiding an item by skipping it does not satisfy that gate.

## Migration controls

Implement operational staging and reconciliation views over the schema contract's `migration_runs`, `migration_ledger`, and `migration_controls`. Their contracts are requirements, not a claim that the operational database or migration jobs already exist. Store manifests and private evidence in restricted operational storage; public fixtures and documents contain only synthetic examples.

### Organization ownership

Use `organizations.access_mode` as the single `legacy`, `shadow`, or `target` mode. Track the writer epoch, write fence, captured source high-water mark, applied high-water mark, baseline revision, and related approval in `migration_controls`. A mode transition is conditional on the current epoch, so a stale job or application instance cannot resume an old writer. `fenced` below is the operational state when `migration_controls.write_fenced` is true; it is not another value in `organizations.access_mode` or a duplicated owner mode.

| Mode | Read authority | Write authority | Purpose |
| --- | --- | --- | --- |
| `legacy` | Verified legacy consumer rule | Legacy path through the controlled adapter | Establish a baseline and capture every relevant mutation. |
| `shadow` | Verified legacy consumer rule | Same controlled legacy writer | Evaluate target decisions without changing enforcement. |
| `fenced` | The current authority until the final switch; protected operations pause when a consistent decision cannot be made. | No ordinary mutation | Drain writes, reconcile the final sequence, validate, and switch ownership. |
| `target` | Scopegate resolver | Scopegate transaction boundary | Enforce normalized entitlements and explicit grants. |

A per-organization flag alone is insufficient for the legacy replace-resource command: that command has no organization input and deletes assignments for the entire user. Fence it globally before starting an organization canary, or replace it with a compatibility adapter that requires a verified organization and project scope and preserves every other scope. Reject ambiguous calls. If that command cannot be fenced and all direct writers cannot be identified, per-organization cutover is blocked.

Global identity writes have a separate authority boundary. Linking or updating a global user cannot mutate memberships of an organization owned by a different mode. Staff members with several organizations are evaluated through distinct memberships and grants. The same user's organization scopes may be in different modes only after the adapter preserves those boundaries.

The fencing control must cover API workers, background jobs, scheduled commands, manual SQL access, and stale application instances. Enforce it through routing and transaction ownership checks; remove legacy write privileges when an organization changes authority. Where legacy writers cannot check an organization epoch, route their mutation through the adapter or block that mutation path. A flag stored in a table does not fence code that never reads it.

### Replayable ledger

Each transformation records the following fields in a restricted operational ledger:

| Field | Purpose |
| --- | --- |
| Migration run and source snapshot | Identify a consistent input and repeatable scope. |
| Source kind and private source key | Locate the original record and relationship instance, including the field and element locator, without copying it into public examples or logs. |
| Source fingerprint and sequence | Detect changes, duplicate processing, and stale replay. |
| Transformation version | Pin the parser and approved mapping rules. |
| Target kind and identifier | Trace the created or linked target relationship. |
| Proposed operation and result fingerprint | Explain insert, update, preserve, retire, or quarantine. |
| Review reference and outcome | Bind nonmechanical decisions to accountable approval. |
| Apply status and transaction reference | Distinguish planned, applied, failed, and superseded work. |
| Access evidence revision and decision digest | Connect data transformation with its authorization impact through `migration_runs` and the organization's baseline revision. |

Keep private identifiers, contact data, invitation secrets, and source payloads outside the public repository. Restrict ledger access, encrypt stored private inputs where required, and apply the agreed retention policy. Public fixtures and reports use synthetic labels such as Organization Cedar, Project Harbor, and Resource Atlas.

Replay uses the source fingerprint, transformation version, approved mapping revision, and scoped target uniqueness to decide whether work is already applied. A replay cannot resurrect a revoked grant, overwrite a newer membership version, restore an expired staff assignment, or reverse a post-cutover target mutation. Conflicting versions create a reconciliation item rather than a last-writer-wins update.

## Phase 1 Expand

Add the normalized tables, indexes, foreign keys, and scoped constraints without removing old data or changing authorization enforcement. Implement verified identity linkage, explicit organization and project mappings, normalized resource identity and localizations, entitlements, grants, invitations, audit events, and report references. Keep source engine migration separate: an access migration from a PostgreSQL 15 deployment does not also upgrade the server to PostgreSQL 18. Prove transition DDL against the actual legacy engine; schedule an engine upgrade as independent work.

Before any backfill, implement one controlled write path and mutation capture. A durable event or transition record must commit with its authoritative mutation. If old and new representations live in the same database, a temporary compatibility writer may update both within one unit of work. Separate helper calls, two connections, or independently committed writes are not atomic. Across databases, use an outbox and idempotent replay with measured lag; do not describe this as distributed atomicity.

Grant delta commands first lock referenced resource rows in UUID order with `FOR SHARE`, then take an exclusive organization advisory transaction lock and lock the membership row. They require the expected membership access version, validate entitlement and grant scope, and commit the version and audit event with the change. Protected consumption locks its resource row first, then takes the corresponding shared organization lock and performs its current access check and work-record creation in the same transaction. Evaluate expiry against the database clock after lock acquisition. This ordering is required in both the transition adapter and target authority; membership-only mutations take organization then membership locks and do not acquire resource locks afterward. Audit rejection and allow decisions under the retention and privacy policy.

Expand acceptance:

- Old reads remain usable against the expanded schema, including absent metadata and null legacy fields.
- Every old mutation entry point is owned, fenced, or routed through the controlled adapter. No unscoped replace command remains able to erase unrelated access.
- Transaction tests prove that a failed target write cannot leave one representation committed and the other rolled back.
- Source sequence capture covers every relevant committed mutation and can detect gaps.
- DDL lock duration, deployment compatibility, backups, and restoration have been rehearsed using the deployed database version.
- Constraint creation is staged and validated without treating dirty input as valid data.

## Phase 2 Backfill

Take a consistent source snapshot and record its high-water mark. Capture subsequent mutations while processing bounded, restartable batches. Record each source record's disposition; every source relationship must be applied, quarantined, preserved, or explicitly retired. Do not discard malformed or ambiguous records to make totals match.

Apply transformations in dependency order:

1. Map verified identities, organizations, and approved project keys. Keep identities with no verified issuer and subject in staging; do not invent an identity provider subject. Do not activate an affected organization until unresolved identity mappings are reviewed or explicitly retired.
2. Build one global resource per approved opaque external key. Resolve duplicate locale rows and shared-field conflicts. Backfill `resource_localizations` only after choosing canonical values with the catalog owner. Preserve provenance.
3. Create `project_resources` only from the reviewed organization and project entitlement mapping. A resource's localized project label is insufficient evidence.
4. Create memberships from approved identity and organization mappings. Map roles only through the approved role policy. Staff membership is explicitly assigned by platform operations, has an expiry, and provides no resource bypass.
5. Create `resource_grants` from reviewed principal, membership, project, and resource decisions. Managers and staff need grants like viewers. A legacy user list cannot independently create an organization entitlement.
6. Recreate invitations from reviewed enrollment approvals under the safe rules below. Approval does not imply acceptance.
7. Normalize `report_resource_refs` only after organization and project ownership and the referenced entitlement are resolved. Preserve invalid configurations in review rather than activating them.
8. Replay captured changes through the current watermark and verify sequence continuity.

### Parsing and mapping rules

Parse the embedded resource list with a strict, versioned grammar. Preserve null, empty, malformed, unknown, duplicate, and valid as separate states. Trim transport whitespace only under the approved grammar; never rewrite opaque resource keys by case or similarity. JSON report references require valid JSON, the expected array element type, bounded size, and known references. A value that parses successfully can still be semantically invalid.

Create a reviewed alias map for project labels. Similar names do not merge projects automatically; missing labels do not become a default project. The same global resource can appear in several projects through separate entitlements. Conflicting locale metadata remains a catalog review issue and does not affect authorization.

Review email normalization collisions before creating invitations. Keep the verified issuer and subject as identity authority. A preapproval for an existing contact may correspond to a known identity, an unverified account, or a different person. Resolve it through verified identity linkage and owner review; do not insert a second user or attach a membership by email.

### Safe invitation recreation

Preserve the original approval record as evidence and create a new invitation only after confirming the organization, intended recipient, approving access manager, expiry, and explicit desired project and resource grants. An approval boolean alone is insufficient. Customer invitations grant the viewer role; access manager and staff assignment follow the separately authorized platform operations workflow. Desired grants are normalized in `invitation_resources` and must reference entitlements in the invitation's organization. Record a supersession relationship in the restricted ledger, generate a fresh unpredictable secret, store only its hash, and deliver it through the approved channel when the enrollment process is operational.

The recreated invitation starts `pending`. It cannot carry accepted status from an old approval flag. Acceptance requires a verified identity and contact proof under the approved invitation policy, a currently valid pending invitation, an active organization, and an idempotent membership transition. Lock referenced resources, organization, applicable membership, and invitation in the canonical order, then revalidate every desired entitlement and the invitation expiry before creating grants. An invalidated desired entitlement fails the transaction rather than silently dropping an intended grant. Reusing a membership cannot downgrade its role or reactivate a suspended membership without separate authorization. Repeated acceptance with the same authenticated actor, idempotency key, and request fingerprint returns the same result rather than adding a duplicate membership. Revoked, consumed, superseded, or expired invitations cannot be resurrected by replay. Expiry is checked from the timestamp at acceptance even if stored status remains pending.

If an existing active membership already meets the reviewed intent, record a no-op reconciliation outcome and do not issue a new invitation. Pending legacy accounts without organization linkage remain enrollment review items; account existence alone neither proves membership nor authorizes a resource.

### Illustrative validation queries

The following is pseudocode for operational views over private source staging and the target schema. Adapt view names and columns to the implemented ledger; it is not an executable migration script. Every query expected to return zero rows must run against the same organization, snapshot, and mapping revision.

```sql
-- Every staged relationship receives an explicit disposition.
SELECT s.source_kind, s.source_key
FROM source_relationships s
LEFT JOIN migration_ledger_view l
  ON l.source_kind = s.source_kind
 AND l.source_key = s.source_key
 AND l.source_fingerprint = s.fingerprint
 AND l.mapping_revision = :approved_mapping_revision
WHERE s.organization_id = :organization_id
  AND l.disposition IS NULL;

-- A logical resource has at most one record per locale.
SELECT resource_id, locale, count(*)
FROM resource_localizations
GROUP BY resource_id, locale
HAVING count(*) > 1;

-- No grant can escape its membership or entitled project scope.
SELECT g.organization_id, g.membership_id, g.project_id, g.resource_id
FROM resource_grants g
LEFT JOIN memberships m
  ON m.id = g.membership_id
 AND m.organization_id = g.organization_id
LEFT JOIN project_resources pr
  ON pr.organization_id = g.organization_id
 AND pr.project_id = g.project_id
 AND pr.resource_id = g.resource_id
WHERE g.organization_id = :organization_id
  AND (m.id IS NULL OR pr.resource_id IS NULL);

-- Report references require an entitlement in the same project.
SELECT rr.organization_id, rr.project_id, rr.report_config_id, rr.resource_id
FROM report_resource_refs rr
LEFT JOIN project_resources pr
  ON pr.organization_id = rr.organization_id
 AND pr.project_id = rr.project_id
 AND pr.resource_id = rr.resource_id
WHERE rr.organization_id = :organization_id
  AND pr.resource_id IS NULL;

-- Review includes both broadened and lost access.
SELECT coalesce(b.principal_key, t.principal_key) AS principal_key,
       coalesce(b.project_key, t.project_key) AS project_key,
       coalesce(b.resource_key, t.resource_key) AS resource_key,
       coalesce(b.action, t.action) AS action,
       b.decision AS baseline_decision, t.decision AS target_decision
FROM baseline_decisions b
FULL JOIN target_decisions t
  ON t.principal_key = b.principal_key
 AND t.organization_key = b.organization_key
 AND t.project_key = b.project_key
 AND t.resource_key = b.resource_key
 AND t.action = b.action
 AND t.evaluated_at = b.evaluated_at
WHERE coalesce(b.organization_key, t.organization_key) = :organization_key
  AND (b.decision IS NULL OR t.decision IS NULL
       OR b.decision IS DISTINCT FROM t.decision);
```

Missing or null decision rows are unresolved mismatches, including null/null and missing/null. They are never implicit denial or successful parity. The explicit null predicates are necessary because `IS DISTINCT FROM` alone treats two nulls as equal. A grant with a disabled entitlement may remain stored as a revoked or inactive relationship according to the reviewed history; it cannot yield effective access. Compare the resolver outcome rather than counting grant rows as permissions.

Backfill acceptance:

- All source records and relationship instances are accounted for; counts and fingerprints reconcile by organization and data kind.
- No unresolved identity, organization, project, entitlement, grant, or active report reference remains in the cutover cohort.
- Strict parsing and reviewed mappings are deterministic across replay; duplicate runs create no duplicate identities, memberships, locale records, invitations, or grants.
- Constraint validation passes; invalid source inputs remain traceable in staging with owners.
- Mutation capture has no gaps, and replay has reached the agreed source watermark.
- The candidate effective-access manifest has zero unreviewed gains and zero unreviewed losses.

## Phase 3 Shadow

Keep the verified legacy rule authoritative. Evaluate the target on equivalent scoped inputs at the same logical time, recording policy version, ownership epoch, data watermark, target version, and decision reason. Compare both permitted and rejected requests. Shadow evaluation must not create work, accept an invitation, change a grant, or send customer notifications.

Separate semantic disagreement from replication lag. A shadow read on stale target data is an invalid comparison; rerun it once the target has applied the corresponding source sequence. Exercise boundary times around staff expiry and invitation expiry with a shared evaluation clock. Test offline manifest cases even when organic traffic does not cover them.

Shadow acceptance:

- Every known consumer and supported action participates in comparison, including background operations.
- All reviewed manifest scenarios match, except explicitly scheduled and approved policy changes.
- The agreed observation window covers a normal operating cycle; its duration is chosen from measured traffic and job schedules before shadow begins.
- Unreviewed gain count and unreviewed loss count are both zero. Any positive count stops progression immediately.
- Capture lag, lock contention, resolver latency, and error rates stay within the agreed service targets; missing baseline or target comparisons count as failures.
- Security, identity, organization, catalog, and platform owners sign the evidence for the cohort.

## Phase 4 Canary

Choose a small approved organization cohort that exercises ordinary memberships, multiple projects, explicit staff access, report references, and metadata gaps. Do not choose a cohort merely because it has clean data; the exercise must cover the target's important boundaries while keeping the impact bounded.

For each organization, execute the cutover sequence:

1. Compare and increment the writer epoch in `migration_controls` and set its write fence, entering `fenced`. Reject new scoped access mutations and pause protected work whose decision cannot remain consistent during the switch.
2. Drain in-flight legacy mutations and consumer work. Confirm all relevant writer paths observe the fence and no direct legacy writer retains authority.
3. Record the final source sequence, replay through it, and prove sequence continuity. Validate target constraints, the current access manifest, and zero blocking reconciliation items.
4. Under the exclusive organization transaction lock, verify that the mode, epoch, and reconciled source sequence have not changed. Set `organizations.access_mode` to `target`, update the controls, and commit the cutover audit event together while keeping the write fence set.
5. Confirm that reads, mutations, invitation transitions, and protected work route to the target for that epoch. Under the exclusive organization lock, revalidate the epoch and clear the write fence with its audit event. Verify allowed and denied probes with synthetic test principals.
6. Observe the approved operating window and expand only after the evidence remains valid. Repeat the gates independently for each organization.

A request carrying an old epoch must re-resolve ownership or fail with a retryable transition result before writing. It cannot commit under the old authority after the switch. A concurrent revocation and protected work request must follow the shared and exclusive lock order: the permitted ordering is explicit and tested, with no stale check followed by unprotected work creation.

Canary acceptance:

- No old writer can mutate the organization's access after cutover, including an unscoped user-wide replacement.
- No post-cutover grant, revocation, suspension, staff expiry, entitlement disablement, or invitation transition is missing from the target audit stream.
- Cross-organization mutation and resource consumption probes fail; scoped updates preserve memberships and grants in other organizations.
- Concurrency probes prove membership version conflicts, idempotent retries, complete rollback on transaction failure, and correct revocation ordering.
- Resolver availability, latency, audit integrity, and capture or replay health satisfy the approved operating thresholds.
- The rollback rehearsal preserves target changes made after cutover and demonstrates that expired or revoked invitations remain unusable.

## Rollback after cutover

Application rollback and authorization authority rollback are different operations. Prefer deploying the prior compatible application build while keeping target authorization and current target state authoritative. Feature flags may disable a faulty UI or command while the resolver continues to enforce current grants and revocations. Old code is eligible only if it understands the current ownership epoch and target compatibility boundary.

Target authorization remains authoritative after cutover. Re-enable a previous UI or compatible API build only while retaining current target grants, revocations, membership state, and ownership epoch. The legacy representation cannot generally express per-project grants or expiring staff membership, so switching enforcement back to it is outside this rollout. Fence the faulty operation and repair forward if no compatible build is available.

Invitation secrets are not recovered from hashes for rollback. Preserve accepted and revoked states and valid identity links. Reissuing an invitation requires a fresh secret, a fresh reviewed expiry, and explicit supersession; it never restores a consumed or revoked invitation. Rollback must not create a second identity or membership.

Rollback evidence records the incident, authoritative state watermark, compatible application version, current-state decision comparison, approval, ownership epoch, and resulting audit event. Keep access mutations fenced until the selected authority can enforce that state. Database disaster recovery has its own replay and reconciliation procedure; a backup restoration that loses later revocations cannot be advertised as a safe access rollback.

## Phase 5 Contract

Remove old access reads and writes only when every organization has an approved terminal disposition, all consumers use the target authority, and the retention and rollback windows have elapsed. Reject old request formats through a documented retirement response before dropping storage. Remove transition writers and mutation capture only after proving that no remaining consumer depends on them.

Archive ledger evidence and preserved legacy data under the approved retention policy. Do not delete isolated legacy tables or report configurations solely because no route in this application reads them. Verify background jobs, exports, manual operational queries, and downstream consumers with their owners first. Keep aliases or restricted mappings only for the approved support period; keep private provenance out of public fixtures.

Contract acceptance:

- Every consumer has a recorded target owner and observed target usage; no supported operation silently falls back to legacy authorization.
- Zero direct legacy access writes occur during the agreed retirement observation window.
- Stale clients and workers are rejected safely; no compatibility fallback can broaden access.
- Post-cutover audit history, current grants and revocations, invitation state, and report relationships remain queryable under retention rules.
- Rollback eligibility and irreversible removals have explicit platform and security approval.
- The PostgreSQL engine upgrade, if desired, has its own compatibility, backup, and recovery evidence.

## Operational evidence and responsibilities

| Evidence | Accountable owner | Stop condition |
| --- | --- | --- |
| Verified consumer rules and baseline manifest | Security owner and organization owner | Unknown authority or unreviewed access difference. |
| Identity links and invitation recreation | Identity owner | Unverified subject, email collision, unexplained acceptance, or duplicate membership. |
| Project mappings and catalog reconciliation | Organization owner and catalog owner | Ambiguous ownership, unknown resource, or active invalid report reference. |
| Fence coverage and ownership epochs | Service owner and platform owner | Direct writer, stale-epoch commit, source sequence gap, or unscoped replacement. |
| Transaction and concurrency verification | Service owner | Partial commit, missing audit event, lost update, or stale authorization before work creation. |
| Canary service health and restore rehearsal | Platform owner | Agreed availability or latency threshold exceeded, incomplete recovery, or lost revocation. |
| Data retention and final retirement | Data owner and security owner | Unowned dependency or missing approved retention decision. |

Operational dashboards distinguish organizations by mode, last captured and applied sequence, unresolved blocking records, decision comparisons, approved exceptions, lock wait time, mutation conflict rate, and audit completeness. Access gains and losses are separate counters. Dashboards do not include raw invitation secrets or private source payloads.

Each phase produces a versioned evidence record with inputs, checks, failures, approvals, and the next eligible transition. A failed query, unavailable dependency, missing comparison, or interrupted verification is a failed gate. The team advances only when the recorded evidence meets the phase acceptance criteria.
