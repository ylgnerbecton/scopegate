# Solution review

Use this map to review the closed local delivery from problem through operating evidence. The [coverage registry](../specs/coverage.json) contains 27 written clauses, the [feature specifications](../specs/README.md) contain developer-ready acceptance, and the [scenario map](../specs/scenario-tests.json) binds acceptance to named tests or documentary checks. These registries describe scope; only the revision-bound [completion evidence](COMPLETION_CONTRACT.md) certifies executed checks.

## Five required outcomes

| Outcome and clauses | Review material | Concrete validation |
| --- | --- | --- |
| Diagnosis: causes, hypotheses, signals and decision owners — A01–A03 | [Diagnosis](DIAGNOSIS.md) | Compatibility diagnosis tests cover missing and absent organizations without metadata mutation; source profiling distinguishes broken references from authority decisions |
| Product direction: objective, metrics, included scope, smallest valuable slice and alternatives — B01–B05 | [Product](PRODUCT.md), [proposal](PROPOSTA.pt-BR.md) | One finite invite → verified acceptance → explicit grant → protected use → revoke journey; business improvement targets retain an unmeasured baseline |
| Solution: entities, ownership, granular access, staff scope, onboarding, catalog separation and alternatives — C01–C07 | [Architecture](ARCHITECTURE.md), [data model](DATA_MODEL.md), [domain](DOMAIN_DESIGN.md), [decisions](DECISION_MATRIX.md) | Independent SQL and HTTP contracts; pure policy cases; real PostgreSQL constraints/races; signed OIDC flow; all 21 tables in the ER view |
| Delivery: phased acceptance, safe migration, risks and dependencies — D01–D04 | [Delivery plan](DELIVERY_PLAN.md), [migration](MIGRATION.md), [risks](RISK_REGISTER.md) | Synthetic replay/parity, write fencing, current target authority, compatible rollback, worker/proxy replacement and restore reconciliation |
| Alignment: priority, tradeoffs, independent technical decisions and commercial escalations — E01–E04 | [Alignment message](PRODUCT_ALIGNMENT.pt-BR.md) | A concise ready-to-paste draft plus decision owners; no external message is sent by the release workflow |

Cross-cutting clauses M01–M04 cover predictable delivery, business value/estimates, preserved intended access and continued delivery through a useful minimum slice. They resolve to the product, delivery and migration documents above. The [requirements](REQUIREMENTS.md) connect the 20 requirements to feature ownership; the [engineering standards](ENGINEERING_STANDARDS.md) record adoption and justified deferral.

## Architecture checks that matter

1. **Four independent relationships:** identity, membership, entitlement and grant have distinct keys and lifecycles. A role or translation never substitutes for an individual grant. Read the [ER view](diagrams/er.svg) alongside [canonical SQL](../specs/contracts/schema.sql).
2. **One current authorization authority:** services use SQLAlchemy Core transactions and shared ordered-lock helpers. Pure policy accepts values; HTTP handlers delegate. The [component view](diagrams/components.svg) names actual modules, without implying separate domain deployments.
3. **Observable concurrency:** resource locks precede organization and membership locks; protected use and revocation re-read state after waiting. Versions protect reviewed edits, while actor/body-bound receipts protect retries. [Correctness](DISTRIBUTED_CORRECTNESS.md) defines the race proofs.
4. **Postcommit effects:** invitation creation commits its plan, receipt, audit and encrypted outbox before delivery. Lease ownership, attempt/deadline limits and adapter retries cannot broaden recipient acceptance. [Reliability](RELIABILITY_DESIGN.md) owns bounded failure behavior.
5. **Concrete deployment:** five running services plus initialization and opt-in maintenance. Two API processes share one container and database; they are not independent replicas. The journal has a separate volume on the same host. [Deployment](diagrams/deployment.svg) shows ports, credentials and storage boundaries.
6. **Reversible authority transition:** ambiguous source records require evidence and an owner. Cutover fences legacy writers; application rollback retains target authority and current revocations. Source engine upgrade and real adapter integration require their own environment proofs.
7. **Usable reviewed commands:** native controls, visible selected state, bounded pagination, scoped query identity and preserved conflict drafts. [Component design](COMPONENT_DESIGN.md) gives source ownership, interactions and verification limits.

## Gaps addressed by the refinement

| Review finding | Resulting correction | Evidence to inspect |
| --- | --- | --- |
| Logical architecture was easy to confuse with implementation/deployment | Actual module map, separate deployment view and explicitly local integration boundaries | Architecture/component/deployment sources and Compose topology |
| ER omitted supporting entities | All 21 SQL entities, selected actual columns and explicit omitted provenance edges | ER source and complete SQL contract |
| Shared controls did not communicate selected state and recovery consistently | Pressed choice groups, clear-search focus, unique dialog IDs and reachable previous-page controls | Component/cursor/resource panel tests and real browser journeys |
| Full-page accessibility coverage omitted library/overview/audit content | Corrected contrast and expanded visible-page scans | Revision-bound browser attachments and interaction evidence |
| Static quality relied too heavily on guidance | AST import boundaries, complete inventory and callable complexity limit of 10 | G-LINT output and negative architecture fixtures |
| Diagnostic context stopped at HTTP | Bounded command/transaction/provider/worker spans with encrypted validated trace context and safe async export | Tracing privacy, context and failure tests; operations gate |
| Compatibility acceptance covered null but not an absent identifier | Separate absent-organization regression, deliberate 404 and unchanged existing metadata | Diagnosis tests and F01-AC-01 bindings |
| Preparation time could be read as a live observation period | Synthetic preparation separated from additional unestimated private pilot observation | Delivery plan and alignment message |

The gaps table identifies implemented changes and where to verify them; it does not replace fresh release results. Architecture diagrams and screenshots are review aids, not runtime proof.

## Review and completion boundary

Start with the [README](../README.md), run the product, follow the [demonstration](DEMO.pt-BR.md), then inspect [validation](VALIDATION.md) and the collected evidence. `make verify` records all 12 gates against a stable revision; missing tools, failures, stale source, skipped browser journeys or broken evidence closure block packaging. `make check-evidence package` validates the report graph and creates the review archive.

The local scope covers T00–T12 with synthetic organizations, identities, delivery and migration fixtures. Real source discovery, business baselines, production identity/delivery/journal adapters, independent-host availability and monitored live rollout remain explicitly gated in T13–T14. The historic staffing estimate expresses planning assumptions, not measured construction time or a live delivery commitment. A same-host bounded performance rehearsal and successful local restore do not establish production capacity or disaster recovery certification.
