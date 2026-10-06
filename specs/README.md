# Scopegate executable specifications

The specifications turn architectural decisions into bounded implementation tasks and acceptance evidence. They describe the implemented local product and separately owned live stages. The specification validator checks consistency; runtime gates prove executed behavior.

## Read and execute

1. Read [Requirements](../docs/REQUIREMENTS.md) and the selected feature JSON. Each feature declares scope, invariants, dependencies, failure cases, and acceptance scenarios.
2. Use [execution.json](execution.json) to select a task whose dependencies are complete. Complete the input gates before its runtime work.
3. Implement against [OpenAPI](contracts/openapi.json), [target SQL](contracts/schema.sql), and [policy cases](contracts/policy-cases.json). Record the acceptance evidence referenced by the task.
4. Run `make check` after changing the planning package. Run the additional runtime gates listed for the task after implementation; the declared Make targets execute the implemented tooling.
5. Mark a local implementation task complete only when its actual evidence exists. Documentation completion does not imply implementation completion.

## Feature map

| ID | Feature | Primary risk |
| --- | --- | --- |
| F01 | [Containment and baseline](features/F01-containment.json) | Treating symptoms as proof or corrupting a legacy write |
| F02 | [Identity and organization model](features/F02-identity.json) | Implicit identity or cross-account ownership |
| F03 | [Scoped access lifecycle](features/F03-access.json) | Privilege expansion, lost grants, or stale revocation |
| F04 | [Invitation onboarding](features/F04-invitations.json) | Approval limbo or replayed token |
| F05 | [Catalog and search](features/F05-catalog.json) | Global catalog leakage or localized identity drift |
| F06 | [Migration and cutover](features/F06-migration.json) | Access loss, unauthorized access, or unsafe rollback |
| F07 | [Operator workflow](features/F07-workspace.json) | Stale tenant data, hidden failure, or inaccessible controls |
| F08 | [Quality and operation](features/F08-quality.json) | False confidence or incomplete release evidence |

## Contract ownership

The SQL contract owns structural constraints, the API contract owns HTTP shapes, and [Security](../docs/SECURITY.md) owns policy. State, clock, role, and concurrency rules require runtime services and tests; SQL alone does not prove them. `policy-cases.json` supplies decision examples and negative cases, and does not substitute for endpoint enforcement.

The task graph permits independent backend foundation and identity discovery, then catalog and migration tooling after the model settles. Grant policy must precede invitations and consumption. Browser work can proceed against generated contract mocks but its end-to-end gate waits for real services. Migration cutover waits for the identity and consumer integrations, access parity, and a rollback rehearsal.

## Validation evidence

Each task lists a concrete result, not an arbitrary coverage percentage. Application tooling exposes the declared gate IDs through the same local and CI entry points. No missing runtime gate may be silently skipped. A stage with private input unavailable may complete synthetic tests but cannot complete the production gate.

The schema contract may be loaded in a disposable PostgreSQL database to validate DDL and structural negative cases. It must never be applied directly to an existing legacy database.

## Depth, configuration and completion contracts

[coverage.json](coverage.json) maps every atomic written-delivery item. [standards.json](standards.json) maps 230 concepts across fifteen engineering groups. [Capacity](contracts/capacity.json), [resilience](contracts/resilience.json) and [objectives](contracts/slo.json) define proposed numeric defaults, allowed ranges, ownership and verification gates. [Completion](../docs/COMPLETION_CONTRACT.md) separates written design, synthetic product, live pilot and completed live cohorts.

The existing `make check-evidence` validates recorded implementation proof against [evidence.schema.json](evidence.schema.json), current revision and artifact hashes. The [implementation-evidence.json](implementation-evidence.json) is generated from executed gates by `make verify`. The runner also verifies the named per-scenario tests and documentary evidence. Never manufacture passing metadata or substitute one gate's result for another behavior.
