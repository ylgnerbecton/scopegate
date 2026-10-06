# Scopegate operation and incident recovery

Access operations succeed when failures are visible, contained to their organization, and reversible without changing intended permissions. This runbook defines implementation and pilot requirements; local signals and operating commands are implemented; external alert routing and live hosting remain separately owned integrations.

## Runtime shape

Run one API deployment, one web deployment, and PostgreSQL. The outbox worker is a command of the same backend image, supervised separately. Use Alembic as a controlled release job rather than letting every API replica migrate at startup. Separate application, publisher, operations, and migration credentials. The migration credential owns DDL; normal runtime credentials cannot alter or truncate tables.

The initial deployment stays within the existing hosting environment after discovery. Managed database, TLS termination, OIDC issuer, notification delivery, backup policy, and secret distribution are integration inputs. Docker Compose serves reproducible local development. A local browser demonstration uses isolated synthetic accounts and a restricted local adapter; a hosted demonstration requires a real OIDC provider; customer data and tokens are never exposed through it.

## Health and signals

`/health/live` reports process responsiveness. `/health/ready` checks database reachability and compatible migration version with a bounded timeout. The service refuses readiness if its environment enables a local identity adapter in production or if its schema version is incompatible. Do not include secret configuration in either response.

| Signal | Owner | Proposed trigger and response |
| --- | --- | --- |
| Authorization mismatch during shadow | Backend lead | Any unexplained allow/deny difference stops that organization's cutover |
| Cross-organization result | Lead and incident responder | Any confirmed result triggers immediate isolation of the affected path |
| Access mutation 5xx | Reliability engineer | Sustained error above 1% for 5 minutes triggers investigation; multiwindow burn alerts stop expansion. Fence writes when state correctness is uncertain |
| Pending invitation age | Operations | More than 72 hours surfaces recipient follow-up; expired token remains denied |
| Outbox lag or failed delivery | Reliability engineer | Oldest ready item above 5 minutes or retry cap reached alerts the operator |
| Lock timeout and stale edits | Backend lead | Monitor rates against measured baseline; repeated spikes indicate contention |
| Ledger unresolved records | Operations | Nonzero for a canary organization blocks cutover unless each exception is reviewed |
| Database pool pressure | Reliability engineer | Measure utilization and wait time; bound request queue before raising pool size |

Thresholds are starting proposals. Set the final availability and latency objectives after measuring traffic and aligning business impact. User, email, organization, project, and resource identifiers are not metric labels. Keep sensitive event details in access-controlled logs, with correlation IDs and a documented retention period.

## Incident sequence

1. Identify the failing path, deployment, organization scope, and last command correlation IDs. Preserve evidence before retrying mutations.
2. Fence affected access writers and pause rollout. Preserve the current authority mode and grant state. A global unscoped legacy writer must be disabled globally.
3. Evaluate whether this is content metadata, identity, delivery, policy, storage, or migration. Metadata failures can degrade panels; policy failures deny safely and must not fall back to wider permissions.
4. Compare command receipt, audit, grants, and migration ledger. An uncertain commit is retried with the same idempotency key, never replayed as a new operation.
5. Apply a compatible application rollback or repair. Preserve current target authority, post-cutover approvals, and revocations. Avoid schema downgrade or switching to an unfenced legacy writer.
6. Recheck the actor/resource cases that failed, unrelated organizations, and the revoke-then-rollback scenario. Unfence only after the on-call owner and operations approve the concrete evidence.

Lead owns technical containment and mitigation. Product owns customer impact priorities and any approved change to access policy. Operations confirms intended permissions. Communicate affected behavior, scope, workaround, and next update time; avoid promises of restoration before the state is reconciled.

## Backup and restore

Back up the database before migration and retain a verifiable snapshot reference outside public artifacts. Production recovery needs point-in-time recovery and a tested restore environment. Proposed pilot objectives are RPO at most 5 minutes and RTO at most 60 minutes, subject to the actual hosting service and business approval.

A database restore can discard revocations committed after the recovery point. Before traffic resumes, reconcile the durable access command journal and deny any unresolved grants until revocation status is established. Backup restoration is disaster recovery, not routine access rollback. If no external durable journal exists, recovery cannot claim those RPO/RTO or permission-preservation objectives until a tested reconciliation process is established.

## Release gates

Release the minimum journey only after real identity integration, negative access tests, PostgreSQL constraints, stale edits, token replay, and mutation fault injection pass. Tenant pilot also requires a reviewed access baseline, shadow comparison, writer fence, outbox delivery exercise, and rollback rehearsal. [Quality](QUALITY.md) specifies the evidence; [Migration](MIGRATION.md) specifies the ordered cutover.

## Evidence handling

Public evidence records environment, commands, real exit codes, and synthetic scenario outcomes. Private evidence contains customer manifests, source locators, verified identity mappings, and snapshot links. Retain private evidence in the organization's approved store. Check local/public artifacts for private files and secrets before any publication.

## Detailed operational contracts

[Reliability design](RELIABILITY_DESIGN.md) defines endpoint/dependency failure handling, leases, replays, delivery retention, SLIs, burn alerts, metrics and traces. [Capacity plan](CAPACITY_PLAN.md) defines proposed pool allocations, workload and query budgets. [Delivery system](DELIVERY_SYSTEM.md) defines CI ownership, supply-chain evidence, secrets, host inputs, no-surge replacement, shutdown, canary and journal restore reconciliation. Their JSON contracts contain numeric parameters with owners, allowed ranges and evidence gates. Proposed targets cannot be reported as observed results or contractual guarantees.
