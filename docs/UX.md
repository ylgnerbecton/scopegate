# Scopegate access workflows

Scopegate makes the organization, project, and affected resources visible before an access change. The interface helps users act within an authorized scope and understand the result; the server remains the authority for every decision.

Status: interaction specification. Screens and checks below define the intended implementation.

## Navigation and scope

The shell shows the active organization and project in the header and page title. Organization and project identifiers live in the URL so reloads and shared links preserve context. A route that names an unauthorized scope shows a controlled unavailable state rather than silently selecting a different organization.

Every scoped query key includes the principal and selected organization, plus the project identifier where applicable. Switching organization cancels pending scope requests, closes detail panels, clears selection and unsaved grant drafts after an explicit discard prompt, resets project selection, and invalidates the departed scope's cache. Responses from an old scope cannot populate the new scope's panels. Switching project applies the same rules to project bound state. Logout and account switching clear the session cache.

Only explicitly assigned organizations appear in the switcher. An internal staff identity sees its separate memberships and expiry for each organization. No interface offers a global access switch.

## Primary screens

| Screen | Audience | Purpose |
| --- | --- | --- |
| Resource library | A consumer with an active membership | Show resources the selected membership may consume in the selected project |
| Member list and detail | Access manager | Inspect active/suspended viewers, invitation status, expiry, and explicit grants |
| Invitation acceptance | Verified invited identity | Confirm the organization and accept a valid invitation |
| Resource access editor | Access manager | Compare current grants with a proposed scoped diff before committing |
| Audit activity | Authorized manager or operations reviewer | Inspect actor, scope, change, outcome, and correlation |
| Migration workbench | Authorized operations reviewer with Product decisions | Review dry run summaries, parity differences, unresolved records, and decision ownership |

A manager's resource access editor can show entitled catalog metadata for management. The consumer library shows only resources the manager has a separate explicit grant to consume. Management visibility must not be confused with permission to open resource content.

## Invitation and first access

An access manager invites a viewer by email within the selected organization and selects an explicit resource grant plan from the entitled project resources. The confirmation shows the email, organization, projects, named resources, and invitation expiry. Acceptance grants only that reviewed plan after server revalidation; membership or a role alone grants no content. The member console cannot issue manager promotions.

The recipient signs in through the configured identity provider. Acceptance requires a verified matching email and a token that is valid, unexpired, and unused. Expired or already consumed invitations show a useful outcome and a path to request a replacement. A different signed in identity can change account without losing the invitation route.

After acceptance, the viewer sees the selected organization's library with only the explicit accepted grants. An active membership without grants has a dedicated empty state explaining that a manager must assign access. Membership, grants, invitation state, and audit commit atomically. Repeating acceptance cannot create another membership or broaden access; acceptance cannot silently reactivate a suspended membership or downgrade an existing manager.

## Resource access editor

The editor is titled with the member, organization, and project. It lists published resources entitled to that exact project, with current grant state and localized metadata. Archived or removed entitlements remain visible in historical context but cannot be newly granted.

Search filters this scoped list and handles missing optional metadata. Stable resource identifiers remain available in the detail view when titles are similar. Selection survives search changes within the same scope and is cleared when the scope changes.

The preview divides the proposed diff into additions, removals, and unchanged grants. It shows counts, named resources, and the target member/project/organization. A destructive change requires explicit confirmation of the removals. The server commits the complete validated diff atomically; it must not interpret an incomplete page of results as a request to replace all grants.

| Outcome | Visible behavior |
| --- | --- |
| Successful change | Show the confirmed resulting grants, update audit, and announce the result |
| Invalid selection | Keep the draft and show resource specific validation without claiming a saved result |
| Concurrent change | Explain that access changed since the editor loaded; reload current access and require review of the recomputed diff |
| Lost authority or suspended membership | Disable further submission, retain a readable explanation, and refresh the scoped membership |
| Network failure | Preserve the draft, offer retry, and reconcile with current server state before declaring success |

Mutations use confirmed server results and an explicit pending state. Disable duplicate submission while pending. Optimistic presentation is limited to read interactions such as local filters and panel selection; grants, revocation, membership state, and migration decisions never appear committed before confirmation.

## Resource use and revocation

Opening a resource sends a new protected admission request. A cached card or an earlier authorization response is not permission to use it later. The server evaluates active membership, staff expiry, published resource state, project entitlement, and the explicit grant at the use boundary. A report action checks every normalized resource reference before creating durable output; mixed permitted and denied references produce one atomic rejection.

If access is revoked or membership expires, the next attempted admission produces a controlled unavailable state and refreshes the library. Revocation confirmation explains that future admissions are blocked once the change commits. An admission already completed before that commit may finish; the interface does not promise to erase content already delivered.

Managers confirm revocation against a visible target and scope. Removing the last active manager is rejected. Suspending a viewer shows the affected resource count and makes the consequence clear before confirmation.

## Localized resource metadata

Resolve labels through requested locale, organization default locale, then English. If no translation is available, use a neutral resource label with the stable identifier. A missing translation shows the fallback with an available language hint and never crashes the screen. Description is optional; a missing description is omitted rather than fabricated.

Translation changes update presentation only. Identity, grants, entitlement, and publication state depend on stable keys, not localized titles. The catalog publisher owns translated metadata; the access editor cannot modify it as part of a grant change.

## Partial failure and empty states

The member summary, resource list, audit feed, and migration summary are independent panels. If one fails, the rest remain usable when their authorization is still valid. A panel includes a scoped retry action and an accessible failure message. Protected content stays closed if its authorization cannot be established.

| State | Message and action |
| --- | --- |
| No active memberships | Explain that no organization is assigned and direct the user to the invitation or operations path |
| Active membership without grants | Explain that membership is active and a manager must assign resource access |
| No entitled resources in a project | Explain that there is nothing available to grant; do not offer a broad catalog bypass |
| No search results | Keep the scoped filters visible and offer a reset |
| Missing localized metadata | Use the defined fallback and keep the resource stable |
| Unknown or archived resource | Show unavailable content with a link back to the selected project |
| Scope changes during a request | Ignore the stale response and load only the newly selected scope |
| Invalid edit | Keep current access unchanged and preserve the editable draft |

## Audit activity

Audit rows show timestamp, actor, organization, project where applicable, action, target, outcome, and correlation identifier. Resource diffs can be expanded into additions and removals. Sensitive invitation tokens and identity credentials never appear.

Filters include action, target, and time range. An access manager sees only the authorized organization. Operations review across organizations uses an explicitly authorized operational path; staff membership alone does not expose a global audit feed.

## Migration workbench

The workbench is clearly labelled as a dry run until a separately authorized cutover begins. Its header identifies snapshot and manifest versions, the bounded cohort, effective access counts, parity differences, and unresolved record counts.

Each exception shows the source record reference, reason, potential access effect, owner, and decision history. Product decisions on licensed entitlements, approval policy, and unresolved historical access are explicit. No bulk control approves unresolved records or substitutes a default organization. A blocking exception keeps its organization out of cutover, even if other records within that organization reconcile.

The web actions are inspect, assign owner, record a justified resolution, and export the versioned manifest. An authorized operator reruns comparison through the migration CLI; the web workbench refreshes its results. Cutover is a restricted CLI operation, without a web action. A stale snapshot or unresolved blocker disables cutover readiness. The interface never treats a green count of imported records as proof of access parity.

## Accessibility and responsive behavior

Verify the workflow at 375, 768, and 1440 CSS pixels. At narrow widths, scope selectors and filters stack, tables become readable lists or controlled scrolling regions, and the diff preview keeps scope and removal counts visible. Primary actions remain reachable without horizontal page overflow.

Use semantic landmarks, one main heading per route, labelled inputs, native controls, visible keyboard focus, and status text independent of color. Associate field errors with their controls and announce async outcomes through an appropriate live region. Dialogs trap focus and restore it to their trigger; destructive confirmation must remain usable with a keyboard.

Verify a complete keyboard journey and a screen reader walkthrough for invitation acceptance, grant preview, resource use, and revocation. Reduced motion preferences apply to transitions. Touch targets use at least 44 by 44 CSS pixels where practical.

## Verification scenarios

The browser journey must prove invitation acceptance with an explicit grant plan, its confirmed grants, successful resource use, an atomic grant edit, a confirmed revoke, and subsequent denial. Exercise a separate membership without grants to prove the empty state. Repeat the protected journey with an internal staff identity assigned to two organizations and confirm that organization switching cannot reuse grants, stale responses, or cached panels.

Additional checks cover missing translations, archived resources, scoped search, failed and stale diffs, expired invitations, staff expiry, last manager protection, partial panel failure, and unresolved migration exceptions. Verify visible behavior against server state; a screenshot alone cannot prove authorization correctness.

Behavior depends on the [product requirements](PRODUCT.md), [architecture](ARCHITECTURE.md), [API contract](API.md), and [migration controls](MIGRATION.md).
