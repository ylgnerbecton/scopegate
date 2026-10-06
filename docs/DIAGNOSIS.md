# Access management diagnosis

Scopegate separates an organization entitlement from an individual grant and makes both decisions explicit within a project. The legacy design cannot reliably express that boundary: it stores resource references in several unrelated text fields, places organization membership on a user record, and replaces user access without an organization or project scope. Repair requires a reviewed access baseline, transactional commands, and a normalized model before any organization changes its authorization authority.

This diagnosis describes a static source and data review. Target behavior is specified in [DATA_MODEL.md](DATA_MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [MIGRATION.md](MIGRATION.md); these documents do not certify that the target runtime has been implemented or deployed. All examples below use synthetic labels.

## Evidence and confidence

| Classification | Meaning | Appropriate conclusion |
| --- | --- | --- |
| Observed | Directly present in the schema, executable source, or supplied sample data. | State what the code or data does and the condition that triggers it. |
| Reported | An operational symptom described alongside the source. | Preserve the symptom, but verify its causal path before assigning a cause. |
| Hypothesis | A plausible explanation that needs logs, runtime traces, production data, or an owner decision. | Record the missing signal and provisional operating rule. |

The source contains no resource consumption endpoint and no demonstrated authorization resolver. It therefore cannot establish how report generation, questionnaire creation, or an external consumer currently decides effective access. The organization resource list and the user resource list are candidate inputs, not evidence that either is authoritative. Their union, intersection, or precedence cannot become a migration rule by assumption.

## Complete route inventory

There are seven explicitly declared business routes and one explicitly declared root liveness route. Framework documentation routes are excluded from this count. The four-route legacy endpoint note covers only part of the business API.

| Semantic operation | Method | Observed behavior | Required target boundary |
| --- | --- | --- | --- |
| Legacy organization aggregate read | GET | Reads an organization, manually parses its embedded resource list, selects one hard-coded locale, then reads its users. | Read an organization and project context with independently handled metadata and membership queries. |
| Legacy organization user read | GET | Lists users through the nullable organization field on the user. | List memberships within an authorized organization scope. |
| Legacy user creation transition | POST | Rejects any exact email match in the approval list, otherwise inserts an active user with an optional organization. | Link verified identity and membership through explicit enrollment rules. |
| Legacy signup transition | POST | Inserts a pending user without an organization, ignoring the supplied organization value. | Accept a valid invitation or remain in an explicit, recoverable enrollment state. |
| Legacy replace resource command | PUT | Deletes every resource assignment for a user, then inserts one text list without organization or project scope. | Apply a scoped grant delta atomically with concurrency control. |
| Legacy resource search | GET | Filters by locale and sorts by external key; accepts a search parameter that never participates in the SQL predicate. | Search authorized catalog metadata with a defined query and locale policy. |
| Legacy localized metadata edit | PUT | Updates matching resource key and locale rows; null inputs preserve old values; always reports success. | Update one versioned localized record, distinguish omission from clearing, and report missing or conflicting records. |
| Root liveness read | GET | Returns a static success object. | Keep liveness separate from database readiness and dependency health. |

No authentication or authorization dependency is visible on these routes. This observation applies to the reviewed application boundary; it does not prove that an external gateway or deployment layer is absent. The target must enforce its permissions at the API and transaction boundary regardless of any gateway.

## Data inventory

The schema has eight tables. Six participate in the described identity, access, catalog, or report data model. Two isolated legacy tables have no demonstrated reads or writes in the application source and remain preserved until dependency ownership is verified.

| Legacy aggregate | Observed representation | Integrity gap | Target concept |
| --- | --- | --- | --- |
| Organization | One project name and a text resource list. | A single field cannot represent multiple projects; null and malformed lists lack defined meaning. | `organizations`, `projects`, `project_resources`. |
| User | Unique case-sensitive email, nullable organization, free-form role and status. | Identity and membership are conflated; an internal operator cannot hold explicit memberships in multiple organizations. | Verified `users` plus `memberships`. |
| Localized resource row | One row per external key and locale, including a repeated project name. | No unique key for resource and locale; project and shared metadata can disagree between translations. | `resources`, `resource_localizations`; project ownership belongs in entitlements. |
| User resource assignment | One text list for the whole user. | No scope, no referential checks, no durable grant history, no safe concurrent update contract. | `resource_grants` for a membership, project, and entitled resource. |
| Email preapproval | Email, optional organization, and boolean approval. | Approval and account creation are separate; no expiry, acceptance, or verified identity link. | `invitations` with explicit state and expiry. |
| Report configuration | Resource keys inside JSON stored as text. | Hidden dependency outside the documented access locations; no referential or project checks. | `report_resource_refs` within an organization and project. |

The sample contains three organization records, four user records, eight localized resource rows representing four distinct resource keys, two user assignment rows, two preapproval rows, and two report configurations. These counts are sample evidence, not production sizing inputs.

One sample user assignment references a resource key absent from the catalog. Another crosses organization boundaries for an internal operator. One organization resource list is null. A resource has four locale rows with divergent project values, including a missing project. Other resources have fewer locales and one description is absent. These conditions require explicit reconciliation; deduplicating rows or supplying a default project would change meaning.

## Findings and consequences

### Aggregate reads fail on invalid structure

**Observed:** The aggregate read selects the first organization result without checking whether it exists, then calls a string operation on the embedded resource field. A missing organization can raise an index error. A null embedded list can raise an attribute error before any user list is returned. Each database call opens a separate connection, so the organization, resources, and users are not read from one consistent transaction snapshot.

**Reported:** An organization page fails with null fields, while the separate user path can still be used for access work.

**Conclusion:** The null list is a concrete failure path consistent with the symptom. The complete page behavior still depends on the consumer UI, which is outside this application source. In the target, invalid access data creates a reconciliation item; a missing metadata translation does not break membership administration or change a grant.

### Replacing access can erase unrelated assignments

**Observed:** The replace command deletes all assignments for a user, even when its input describes resources for one organization. The delete and insert use separate database helper calls, separate connections, and separate committed transactions. An insert failure after a successful delete leaves no assignment row. Concurrent commands can overwrite each other or produce multiple assignment rows because there is no uniqueness constraint on the user assignment relationship.

**Conclusion:** The command loses historical state and can erase access outside the intended scope. The sample demonstrates an internal user with resources associated with multiple organizations; it does not demonstrate how the consumer previously enforced them. A target mutation must name organization, membership, and project, preserve all other scopes, compare the membership access version, and commit the delta with its audit event in one transaction.

### Enrollment transitions do not converge

**Observed:** User creation rejects any matching preapproval row, without inspecting its approval boolean. Signup creates a pending record without an organization and exposes no transition to approval. The preapproved sample includes both an email with no user record and an email already present as a user. Duplicate user email insertion relies on a database uniqueness error that is not mapped to a domain response.

**Reported:** A user remains waiting for approval, and a failed user creation is followed by an organization page failure.

**Conclusion:** Preapproval and enrollment can contradict each other. The rejection in the creation transition happens before its insert and has no demonstrated organization mutation. The reported association between that 400 response and an organization page failure remains a hypothesis; request correlation and transaction evidence are needed before treating them as one causal chain.

The target invitation transition must distinguish invitation validity, verified identity, existing membership, and account linkage. An approved legacy flag cannot become an active membership automatically. A pending legacy account cannot be joined to an existing identity by matching email alone.

### Email and reference comparisons lack a shared policy

**Observed:** Email lookup uses exact SQL equality, and the ordinary unique text email constraint is case-sensitive. No trimming or normalization is visible. Resource list parsing splits on commas but does not validate syntax, whitespace, duplicate keys, unknown keys, or project ownership. References are strings without foreign keys.

**Conclusion:** Case variants can produce inconsistent preapproval matches and distinct stored email values. No case variant collision is demonstrated in the sample; the risk follows from the schema and comparisons. Target identity is the immutable verified OIDC issuer and subject. Canonical email is a delivery and lookup attribute under a documented policy, never the authority for merging identities. Resource keys remain opaque and case-sensitive unless the catalog owner approves a different rule.

### Search and edits misstate their results

**Observed:** Resource search ignores the query parameter. The aggregate resource read hard-codes a primary locale while the search accepts a locale. Localized updates can match zero or several rows, and their response does not distinguish either condition. Null fields are passed through `COALESCE`, which prevents intentionally clearing an existing value. Each locale must be edited separately.

**Conclusion:** Search behavior is a code defect. Translation editing needs a shared resource identity, a unique locale key, patch semantics, and versions. Bulk operations must be transactional or report deliberate per-item results. Locale fallback belongs to metadata presentation; it must never manufacture or remove resource access.

### Project ownership cannot be recovered from labels alone

**Observed:** Project names appear on both organizations and localized resource rows. The sample has conflicting spellings and null values among locale rows for the same resource. An organization holds only one project label while its embedded list contains resources carrying different project labels.

**Conclusion:** Project labels are incomplete and inconsistent evidence. Similar text does not prove project equivalence. Project and entitlement backfill requires an owner-approved mapping, including explicit decisions on shared resources. A catalog resource may be reused through separate `project_resources`; localized metadata carries no tenant authority.

### Status and membership integrity depend on application conventions

**Observed:** Status and role columns use free text with defaults and no check constraint. The nullable organization reference, user assignments, preapprovals, and report references have no declared foreign keys. The localized resource key has no uniqueness constraint. Several status and timestamp fields are nullable despite their defaults. Defaults apply only when omitted and do not prevent explicit nulls.

**Conclusion:** The database accepts states that the application may not understand, dangling relationships, and duplicate logical localized records. The target must validate domain states and enforce scoped uniqueness and composite relationships. Customer and staff memberships have explicit roles and status; staff membership additionally expires. Access managers and staff still require individual resource grants.

### Reports contain a hidden resource dependency

**Observed:** Report configuration stores JSON resource references in text, beyond the visible organization list, user assignment list, localized resource rows, and preapproval relationship. The reviewed routes do not read report configurations.

**Conclusion:** Report configurations must participate in impact analysis and reconciliation even though the report generation consumer is absent. A valid report reference points to an entitlement in the same organization and project. It neither grants access nor proves a user's prior access. Invalid or unresolved references block the affected report configuration from activation.

## Questions that govern the target and migration

The owner column names an accountable role, not an assumed answer. P0 decisions block access cutover. P1 decisions block the affected command or data cohort. P2 decisions may follow once they cannot change authorization meaning.

| Question | Owner | Priority | Required signal | Provisional rule |
| --- | --- | --- | --- | --- |
| Which service makes the final consumption decision, and which legacy rule does it execute? | Security owner with consumer service owner | P0 | Resolver code, traced decisions, denied and allowed requests, and policy signoff. | Keep legacy authority; do not infer access from a union or intersection of lists. |
| How does each legacy user map to a verified issuer and subject? | Identity owner | P0 | Identity provider verification and reviewed mapping with collision handling. | No email merge, invented subject, or automatic activation. |
| Which organization and project own each resource relationship? | Organization owner with catalog owner | P0 | Approved mapping of project keys, entitlement records, and exceptions. | Hold ambiguous relationships in reconciliation staging. |
| What is the intended scope of the internal operator role? | Security owner with platform operations | P0 | Reviewed organization assignments, reason, approver, and expiry. | Use explicitly assigned, expiring staff memberships and ordinary grants; no global bypass. |
| Is a null embedded list empty, unknown, or a broken import? | Organization owner | P0 | Import history and explicit resource access manifest. | Treat as unknown and block inferred entitlements. |
| Does preapproval authorize invitation only, or has identity verification already occurred? | Identity owner with organization access manager | P0 | Historical approval evidence and current verification records. | Recreate bounded invitations after review; never mark them accepted. |
| Why does the failed creation request coincide with an aggregate read failure? | Service owner with operations | P1 | Correlated request logs, stored state before and after, transaction traces. | Track them as separate incidents until a causal path is demonstrated. |
| What should happen to users without a membership? | Product owner with identity owner | P1 | Supported onboarding flow and consumer requirements. | Permit identity enrollment; deny tenant operations until active membership and grant exist. |
| Which locales are required, and which fallback is acceptable? | Catalog owner with product owner | P1 | Locale coverage requirements and approved fallback sequence. | Show an explicit metadata fallback or unavailable translation; leave access unchanged. |
| Can a localized value be cleared, and what constitutes a bulk edit? | Catalog owner | P1 | Patch contract and acceptable partial failure policy. | Omitted fields stay unchanged; explicit null is validated separately. |
| Which email canonicalization policy is acceptable for delivery and invitations? | Identity owner | P1 | Provider behavior, delivery policy, and collision review. | Normalize only under the approved contact policy and retain provenance. |
| Which consumers use the isolated legacy tables or report configuration? | Service owner with data owner | P1 | Query inventory, runtime telemetry, job and export inventory. | Preserve the tables and configurations; avoid deletion or speculative migration. |
| What volumes, retention periods, and availability targets apply? | Platform owner with product owner | P2 | Production measurements and contractual requirements. | Use conservative bounded batches; treat sizing numbers as hypotheses until measured. |

## Remediation order

1. Establish the consumption authority, verified identity mappings, and access manifest. Resolve organization, project, resource, and staff scope before deriving effective access.
2. Fence the unscoped replace command and route changes through one scoped transaction boundary. Include audit events, versions, and idempotency handling.
3. Expand the normalized model and backfill through a replayable ledger. Surface unknown references and ambiguous relationships for review.
4. Implement convergent invitation acceptance, explicit membership assignment, reliable search, and versioned localized editing against the target contracts.
5. Compare authorized consumption decisions in shadow mode, canary approved organizations, and retire legacy reads only after parity and rollback rehearsal.

## Acceptance evidence

Diagnosis is ready for implementation when the complete operation inventory has an owner, every P0 question has a recorded answer or an explicit blocked cohort, and the access manifest can express a verified principal, organization, project, resource, action, and expected decision. Evidence must include the following scenarios.

| Scenario | Required outcome |
| --- | --- |
| Missing organization and null embedded resource list | Explain the observed failure condition, distinguish missing data from empty data, and link it to a reconciliation decision. |
| User assignment with an absent resource key | No invented catalog row or inferred permission; the relationship remains blocked until reviewed. |
| Multi-organization staff member | A change in one organization preserves all other organizations and requires a valid explicit staff assignment. |
| Preapproved email without a verified user | A reviewed invitation may be created; active membership and grants require verified acceptance. |
| Existing identity and canonical email collision | No duplicate or merged identity by email; ambiguous delivery is reviewed. |
| Search, missing locale, and field clearing | Query semantics are explicit; metadata behavior is independent of authorization; omission and null differ. |
| Report references and isolated legacy tables | Dependency ownership is recorded, all affected references are reconciled, and unused status is not assumed. |
| Failed creation followed by aggregate failure | The two observed paths remain separate unless runtime evidence proves causation. |
| Migration comparison | No unreviewed access gain or loss, including deny decisions, expiry, disabled entitlements, suspended memberships, and revoked grants. |

Implementation verification is specified in [QUALITY.md](QUALITY.md). Cutover evidence and rollback requirements are specified in [MIGRATION.md](MIGRATION.md).
