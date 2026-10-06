# Implementation map

| Responsibility | Source |
| --- | --- |
| Composition, safe errors and probes | `backend/src/scopegate/main.py` |
| Configuration, least privilege and migrations | `config.py`, `bootstrap.py`, `backend/migrations/` |
| Transaction and canonical locks | `backend/src/scopegate/db.py` |
| Pure permission predicate | `backend/src/scopegate/domain/policy.py` |
| Organization and membership boundaries | `backend/src/scopegate/services/workspace.py` |
| Grant diffs and protected reports | `backend/src/scopegate/services/access.py` |
| Catalog and tenant search | `backend/src/scopegate/services/catalog.py` |
| Reviewed destructive entitlement changes | `backend/src/scopegate/services/entitlements.py` |
| OIDC verification and session lifecycle | `backend/src/scopegate/services/identity.py`, `identity_provider/` |
| Enrollment and durable delivery | `services/enrollment.py`, `delivery.py`, `worker.py` |
| Synthetic reconciliation and authority protocol | `services/migration.py`, `cli.py` |
| Independent journal and restore fence | `journal.py`, `services/recovery.py` |
| Signals and containment | `observability.py`, `services/operations.py`, `ops/alerts.yaml` |
| Feature-based workspace | `frontend/src/features/`, `frontend/src/lib/` |
| Browser evidence | `frontend/e2e/`, `docs/screenshots/` |
| Contracts and acceptance | `specs/contracts/`, `specs/features/`, `specs/scenario-tests.json` |
| Release proof and public archive | `scripts/record_evidence.py`, `scripts/package_review.py` |

HTTP adapters parse bounded input and delegate. Services own transactions. Shared helpers provide scoped membership checks, version semantics, receipt binding, audit and signed cursors. The database rejects cross-organization associations independently of HTTP authorization.

Generated OpenAPI is checked against independent canonical paths, operation identifiers, required headers and query parameters. Transport tests validate actual JSON against canonical response schemas. Frontend types must reproduce exactly from the same contract.

Browser cache keys include principal, organization and project. Account changes clear server state; an old organization's response cannot render under a new selection. A grant conflict preserves the draft and requires another review before submission.
