# Scopegate implementation instructions

Implement the behavior specified by this repository. Read README.md, specs/README.md, specs/execution.json, and the documents referenced by the selected task before making changes.

## Sources of truth

- docs/PRODUCT.md owns scope and proposed outcomes.
- docs/DATA_MODEL.md and specs/contracts/schema.sql own relationships and database invariants.
- specs/contracts/openapi.json owns the HTTP surface. Generated application OpenAPI must be checked against this independent contract.
- docs/SECURITY.md owns authorization rules and trust boundaries.
- specs/features/ owns acceptance scenarios. specs/execution.json owns dependencies and required evidence.
- docs/MIGRATION.md owns cutover and rollback. A successful backfill is not permission to switch production traffic.

Resolve disagreements before implementation by changing the canonical contract and every affected reference together. Keep a decision record for changes to architecture, access policy, or migration ownership.

## Work protocol

1. Select a task whose dependencies and input gates are complete. Keep the implementation state separate from the existing design state.
2. Identify its required behavior, failure cases, contracts, and excluded work.
3. Implement the smallest complete change. Parallelize only tasks with independent write ownership and satisfied dependencies.
4. Run the validation commands applicable to the change. Record the command, exit code, environment, and evidence. A missing executable, skipped gate, or infrastructure failure is not a passing check.
5. Update the contract and documentation only when actual behavior warrants it. Do not label planned functionality as implemented.

## Engineering constraints

HTTP handlers validate and delegate. Services own transactions. Selectors own bounded reads. Shared policy evaluates every customer data path, including lists, reports, exports, and background work. A URL organization ID is untrusted input. Deny by default.

Use composite organization foreign keys, normalized associations, explicit state transitions, scoped grant diffs, and optimistic versions. Never infer customer access from email domains, manager roles, staff status, project names, or catalog publication. Never delete all grants for a user to edit one organization.

Follow the documented lock order and ownership fence. Use one database transaction for membership/grant/audit changes. Preserve revocations across rollback. Do not resolve ambiguous migration rows by taking the union or intersection of legacy fields.

Use DRY for repeated business rules, not merely similar syntax. Prefer small cohesive modules and explicit dependencies. Apply SOLID where it clarifies responsibilities; introduce interfaces at genuine external boundaries. Avoid a generic repository, dependency injection framework, microservices, queues, or policy engine without a recorded requirement.

Frontend code is organized by feature. Server state belongs to TanStack Query; tenant and project IDs are part of every scoped query key. Clear tenant data on switching accounts. Mutations reflect confirmed responses, preserve form input after failure, and support keyboard operation.

## Public content

Use Scopegate's independent product vocabulary and synthetic examples. Keep private source material, copied source code, external organizations, personal contact details, credentials, and unpublished customer data outside this repository. The public artifact must be understandable without private files.

## Completion

A task is complete only when its acceptance scenarios and required evidence exist. The specification validator proves package consistency; runtime, PostgreSQL, browser, migration, and identity-provider checks must be executed independently at their milestones. Report limitations plainly.

## Design depth and measured completion

Read docs/DOMAIN_DESIGN.md for module boundaries, docs/IMPLEMENTATION_MAP.md for the implemented artifacts, docs/DISTRIBUTED_CORRECTNESS.md for ordered transactions, and docs/ENGINEERING_STANDARDS.md plus specs/standards.json for the fifteen-category decision registry. Do not implement a deferred pattern because its name appears in the registry. Adopted rules are normative requirements; their runtime verification depends on current measured release evidence.

READ COMMITTED lock acquisition and policy evaluation are separate SQL statements. Refresh ORM state after waiting. Customer managers have no expiry and at least one active customer manager must remain; staff never counts for continuity. Entitlement disable requires revision and recomputed impact fingerprint, revokes exact-pair grants and whole dependent invitations atomically within caps, and reenable grants nothing. Resource archive is terminal. Session activity is monotonic and cannot revive expiry or revocation. Worker acknowledgments use the durable current lease token and generation.

Use specs/contracts/capacity.json, resilience.json and slo.json as proposed configuration inputs. Confirm budgets through their owning runtime gates before live use. No replica or cache may make an authoritative access decision. A slow or failed dependency cannot broaden permission.

Use docs/COMPLETION_CONTRACT.md and specs/evidence.schema.json for completed task proof. make check-evidence verifies recorded commands, current revision and artifact digests; missing or stale proof blocks completion. Keep local synthetic evidence separate from live approvals. Follow docs/DELIVERY_SYSTEM.md for build provenance, target-compatible rollback and externally durable restore reconciliation. Read docs/LEARNING_GUIDE.pt-BR.md to practice explaining the decisions and their limits.
