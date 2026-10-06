# Scopegate product requirements

Scopegate lets organizations control who can use each published resource within a project. It separates identity, organization membership, project entitlements, and individual grants so an access change has a visible and bounded effect.

Status: local product implemented. The behavior below defines acceptance; proposed live objectives remain hypotheses until separately validated. Local delivery scope and exclusions are in LOCAL_PRODUCT.md.

## Product decision

Stabilize the existing access workflow first, then replace its access boundary through a narrow vertical slice. Keep the surrounding product running while the new boundary proves equivalent for approved access. A full rewrite would enlarge the migration surface before the underlying access rules are settled.

| Option | Benefit | Limitation | Decision |
| --- | --- | --- | --- |
| Contain defects in the existing workflow | Reduces immediate impact with a small change surface | Leaves ambiguous ownership and historical access rules in place | P0, followed by explicit reconciliation |
| Rebuild the access boundary | Makes tenant scope, entitlements, and grants independently testable | Requires adapters, parity checks, and a controlled migration | P1 and P2 |
| Rewrite the entire product | Allows broad redesign | Couples unrelated behavior, data, and operational changes to access correctness | Defer unless measurements establish a wider constraint |
| Make no new build | Preserves engineering capacity | Repeated access failures and unclear rules remain | Reconsider if containment removes the structural risk and measured costs stay acceptable |

The [diagnosis](DIAGNOSIS.md) describes the failure mechanisms and evidence needed to confirm them. Product owns uncertain business rules; engineering must not turn an unknown rule into an automatic approval.

## Users and responsibilities

| User | Goal | Boundary |
| --- | --- | --- |
| Organization viewer | Find and use resources granted for a selected project | Active membership, a current project entitlement, and an explicit individual grant are all required |
| Organization access manager | Invite viewers and change their resource grants | Authority is limited to the assigned organization; the role does not grant resource consumption |
| Internal staff member | Work across explicitly assigned organizations | Each organization has its own active membership, expiry, and grants; no global bypass exists |
| Catalog publisher | Maintain stable resource identities, publication state, and localized metadata | Publishing a resource does not assign it to an organization or a person |
| Platform operations | Provision controlled management access and time limited staff memberships | Changes require an authorized operation and an audit record |
| Product owner | Decide access policy and approve unresolved commercial or migration decisions | Determines automatic approval policy, licensed entitlements, and unresolved historical exceptions |

Roles in the product are `viewer` and `access_manager`. A membership can be `active` or `suspended`. Internal staff membership is an explicit platform operations assignment and must expire. A manager cannot promote someone to `access_manager` through the member console or remove the organization's last active manager.

Platform operations creates organizations, assigns the initial verified access manager, and changes project entitlements through a separate scoped platform credential. The catalog publisher has a distinct credential and cannot perform those access operations. Neither credential grants a person implicit resource consumption.

## Access model

Resources have global stable identities. A title or translation is descriptive metadata and never an authorization key. A resource has a publication lifecycle of `published` or `archived`, with translations keyed by locale.

`project_resources` defines which resource an organization may make available in a project. `resource_grants` grants consumption to a specific organization membership, project, and resource. Being a manager, belonging to an organization, or seeing a resource in the catalog is insufficient to consume it.

For example, Maya has an active viewer membership in Cedar and an expiring staff membership in Harbor. Cedar's Launch project is entitled to resources Atlas and Beacon; Harbor's Review project is entitled only to Atlas. Granting Maya Cedar/Launch/Atlas permits that one tuple. It grants neither Cedar/Launch/Beacon nor Harbor/Review/Atlas. Harbor needs its own explicit grant. Changing Atlas's Portuguese title changes neither permission.

## Release scope

### P0 Stabilize the existing workflow

| Requirement | Acceptance condition |
| --- | --- |
| Contain legacy null values | Missing optional metadata renders a safe fallback. Required identity or scope gaps produce a controlled unavailable state and a reconciliation item |
| Handle unavailable resources | Unknown or archived resources produce a deliberate not found response and a recoverable UI; they do not crash the surrounding screen |
| Correct scoped search | Search uses the selected organization and project, tolerates missing translations, and cannot reveal another organization's restricted data |
| Make resource edits atomic | The server validates the complete requested diff before writing. One transaction changes only the selected membership, project, and organization |
| Reject invalid edits safely | Validation failures, including HTTP 400 responses, leave persisted access unchanged. A response status alone is not evidence that organization data was corrupted |
| Restore operational visibility | Reproductions, request identifiers, structured failure records, and an incident ledger distinguish symptoms from confirmed causes |

P0 does not reinterpret historical access or bulk delete memberships to remove invalid records. The containment boundary preserves evidence for reconciliation.

### P1 Prove one complete access journey

The first slice covers one pilot organization and project while also exercising an internal staff identity assigned to two organizations. The second organization is required to prove isolation; it is not a second production rollout cohort.

| Capability | Acceptance condition |
| --- | --- |
| Verified invitation | A single use, expiring invitation names the organization and an explicit resource grant plan. Only an authenticated identity whose verified IdP email matches may accept; repeated acceptance cannot create duplicates |
| Membership | Acceptance creates or reuses the organization membership and applies the invitation's explicit grants atomically. It does not silently reactivate a suspended membership, downgrade a manager, or infer access from the role |
| Resource entitlement | A published resource is available to grant only while the organization/project entitlement is current |
| Resource grant | A manager previews and confirms a scoped diff. The server revalidates authority, entitlement, publication, and concurrency before one atomic commit |
| Protected resource use | Every admission checks active membership, staff expiry, publication, project entitlement, and the explicit grant at the protected use boundary. Report creation checks each normalized resource reference; a mixed permitted and denied set fails atomically |
| Revocation | Once revocation commits, later admissions fail. An admission completed earlier may finish; that ordering is visible in audit records |
| Identity integration | The actual OIDC adapter validates the identity contract before the pilot. Local demonstration identity is disabled outside the local environment |
| Audit | Invitation, membership, grant, revoke, suspension, staff expiry, and protected admission events identify actor, organization, target, outcome, and correlation |
| Usable interface | Invite, membership list, resource selection, access preview, resource use, revocation, and audit views handle loading, empty, failure, and pending states |
| Migration rehearsal | A dry run classifies records, compares effective access, and produces a reviewable manifest without changing live access |

Managers can grant only resources already entitled to the selected project. Commercial entitlement changes are separate from user access management. Automatic approval is disabled until Product defines which requests may qualify and the rule is explicitly reviewed.

### P2 Expand after parity

Complete the public product with the full management workflow, integration checks, migration workbench, report reference reconciliation, writer fencing, operational controls, release packaging, and evidence for every P0 to P2 criterion. A passing vertical slice alone does not finish the product.

Roll out by bounded organization cohort only after dry run, explicit exception resolution, decision parity, rehearsal, and pilot evidence meet the migration gates. Projects remain explicit within each cohort. An unresolved blocking record prevents its organization from cutting over. The migration workbench must make the reason and next owner visible.

### P3 Grow when justified

Consider bulk delegation, advanced catalog workflows, broader locale management, stronger analytics, or additional integration adapters when adoption and measured bottlenecks justify them. Infrastructure complexity requires a demonstrated operating need.

## Explicit cuts

The initial delivery excludes a full product rewrite, organization self provisioning, a new identity provider, manager role promotion through the member console, automatic approval of unresolved access, broad catalog authoring, and unrestricted bulk grant operations. It also excludes microservices, Redis, a separate policy engine, and Kubernetes.

The catalog publisher integration remains a contract with a focused adapter. Resource lifecycle and localized metadata are included; building a new publishing platform is not.

Existing report resource references and authorization before durable report creation are in scope. Replacing report computation or rendering internals, and modifying isolated legacy tables without an established consumer, are outside the access redesign.

## Success measures

Baseline incident rates and onboarding times are not yet measured. These are proposed acceptance targets, to be confirmed by Product and Operations after baseline collection. They are not achieved results or contractual service commitments.

| Measure | Baseline to collect | Proposed target | Evidence |
| --- | --- | --- | --- |
| Broadened access in the pilot | Compare approved legacy tuples with proposed effective access | Zero unapproved broadened tuples | Dry run manifest and decision comparison |
| Lost approved access in the pilot | Enumerate approved access before cutover | Zero lost approved tuples | Parity report with every exception resolved |
| Access incidents | Count confirmed failures by category and impact over a representative operating window | Zero critical authorization defects during the pilot observation window | Incident ledger and protected access checks |
| Viewer onboarding time | Median and p90 from verified invitation acceptance to first successful authorized admission, including approval wait separately | At least 30 percent improvement in median processing time after a stable baseline | Timestamped workflow events and cohort comparison |
| Revocation correctness | Record admission and revocation ordering | No new admission after revocation commits | Concurrent integration checks and audit sequence |
| Operational readiness | Rehearse setup, migration, restore, and failure recovery | Every release gate has executable evidence and an assigned operator | Release checklist and rehearsal record |

Approval delay and system processing time must be measured separately so an improvement in one cannot disguise a regression in the other. Small pilot samples support operational learning, not statistical claims about all future cohorts.

## Decisions required before pilot

Product must settle automatic approval policy, the source of licensed entitlements, and ownership of unresolved migration exceptions. Operations must confirm staff assignment and expiry procedures. The catalog publisher must confirm identity stability, locale fallback, and archive semantics. The principal lead owns the authorization invariants, migration boundaries, and evidence required to release.

The pilot stays blocked if identity verification, entitlement ownership, rollback, or any access exception in its cohort remains unresolved. Work on independent implementation tasks can continue while these decisions are collected.

## Related specifications

Implementation boundaries are in [architecture](ARCHITECTURE.md) and the [data model](DATA_MODEL.md). [UX](UX.md) defines visible behavior, the [delivery plan](DELIVERY_PLAN.md) defines sequencing and release gates, and [migration](MIGRATION.md) defines reconciliation and cutover. The [specification index](../specs/README.md) links executable contracts and verification tasks.
