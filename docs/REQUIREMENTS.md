# Scopegate requirements and evidence map

The minimum release restores a complete access journey while preserving organization boundaries and existing intended permissions. Requirement IDs link the written proposal to behavior specifications and implementation evidence. Runtime evidence below is linked through the executed local gate manifest; real pilot evidence remains a separate stage.

| ID | Required outcome | Canonical document | Feature | Required evidence |
| --- | --- | --- | --- | --- |
| REQ-01 | Explain root causes, signals, and open questions | [Diagnosis](DIAGNOSIS.md) | F01 | Reviewed symptom and hypothesis register |
| REQ-02 | Align scope, outcomes, and minimum valuable slice | [Product](PRODUCT.md) | F01 | Baseline and explicit scope decision |
| REQ-03 | Support several projects per organization | [Data model](DATA_MODEL.md) | F02 | Composite foreign key and project ownership tests |
| REQ-04 | Support one user in several organizations | [Data model](DATA_MODEL.md) | F02 | Account A edit preserves account B grants |
| REQ-05 | Enforce individual resource access within project entitlement | [Security](SECURITY.md) | F03 | Policy allow and deny matrix on real database |
| REQ-06 | Scope and expire internal staff access | [Security](SECURITY.md) | F03 | Expiry and multi-account negative tests |
| REQ-07 | Replace approval lists with a finite onboarding flow | [API](API.md) | F04 | Invite accept, resend, revoke, expire, replay tests |
| REQ-08 | Separate catalog publication from access administration | [Architecture](ARCHITECTURE.md) | F05 | Publisher authentication and authority tests |
| REQ-09 | Maintain one resource identity across locales | [Data model](DATA_MODEL.md) | F05 | Localization uniqueness and missing-locale tests |
| REQ-10 | Make search, filtering, pagination, and partial views reliable | [UX](UX.md) | F05 | Tenant-scoped search and panel failure scenarios |
| REQ-11 | Make access changes atomic, scoped, and auditable | [Data model](DATA_MODEL.md) | F03 | Fault injection, stale edit, concurrency, audit tests |
| REQ-12 | Migrate every access reference including report configuration | [Migration](MIGRATION.md) | F06 | Ledger reconciliation and effective-access comparison |
| REQ-13 | Preserve intended access and prevent new unauthorized access | [Migration](MIGRATION.md) | F06 | Zero unresolved allow/deny divergence for pilot |
| REQ-14 | Fence writers and preserve revocations during rollback | [Migration](MIGRATION.md) | F06 | Post-cutover revoke plus application rollback rehearsal |
| REQ-15 | Sequence delivery with owners, gates, and risk triggers | [Delivery plan](DELIVERY_PLAN.md) | F08 | Milestone review with actual capacity and risks |
| REQ-16 | Communicate technical decisions and escalations clearly | [Product alignment](PRODUCT_ALIGNMENT.pt-BR.md) | F08 | Product decision log and concise walkthrough |
| REQ-17 | Provide an accessible operator workflow | [UX](UX.md) | F07 | Browser checks at defined widths and keyboard journey |
| REQ-18 | Enforce authentication and authorization on every data path | [Security](SECURITY.md) | F03 | OIDC integration and cross-organization tests |
| REQ-19 | Automate implementation ordering and quality gates | [Specifications](../specs/README.md) | F08 | DAG validation and actual runtime gate results |
| REQ-20 | Define operation, observability, and incident recovery | [Operations](OPERATIONS.md) | F08 | Alerts, restore drill, and rollback evidence |

## Coverage boundaries

Templates and other isolated legacy tables remain untouched until a real consumer is established. Resource computation, report rendering internals, and identity-provider replacement are outside the access redesign. Existing report references and the authorization boundary around report creation remain in scope.

No production traffic switches while intended access is ambiguous. Questions are recorded with owners and temporary rules, rather than resolved through undocumented assumptions.
