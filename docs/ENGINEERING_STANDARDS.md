# Scopegate engineering standards

Scopegate's engineering standards protect explicit access, atomic changes, bounded operation and recoverable migration. Every principle, pattern, metric and technique in the fifteen categories has a normative decision in [standards.json](../specs/standards.json), with a component, accountable owner, enforcement gate, required evidence and revisit trigger.

The registry contains 230 concepts. Adoption defines an engineering requirement, not a claim that 230 patterns have been implemented or that every live objective has been measured. The local product's source is identified in [Implementation map](IMPLEMENTATION_MAP.md); verified behavior is established by revision-bound runtime evidence. Context dependent choices require the stated need; deferred choices remain outside current scope; choices marked not applicable have an explicit alternative. An ID must not be reused for a different meaning.

## Standards that drive implementation

One shared policy determines whether a principal may consume a resource in an organization and project. It requires valid identity, active organization/project, active unexpired membership, published resource, active entitlement, and explicit individual grant. A manager role is management authority, not content access. Staff follows the same predicate with required expiry.

Services own transaction boundaries. Scoped repositories read and persist without independently committing. A changed grant command updates grants, the membership access version, receipt, and audit in one transaction. Ordered locks coordinate protected use with revocation; a browser decision or replica snapshot cannot replace current authority.

DRY applies to those repeated rules and boundaries. It does not require combining similar syntax from unrelated responsibilities. KISS favors one policy, specific commands, native transactions, and a small composition root. YAGNI excludes machinery without an accepted consumer. SOLID gives each module a purpose and puts interfaces at actual identity, delivery, source, and consumption seams. It does not require a class for every function.

Fail fast applies to invalid configuration and impossible state before side effects. Defensive validation applies again after waiting for locks and at external boundaries. Explicit actor, scope, version, clock, and transaction inputs prevent ambient authority. Comments may explain a nonobvious invariant or tradeoff; they must not substitute for clear names or preserve obsolete behavior.

The [domain design](DOMAIN_DESIGN.md) owns responsibilities and dependency direction. [Distributed correctness](DISTRIBUTED_CORRECTNESS.md) owns concurrency assumptions. This standard does not create a second policy implementation.

## Quality measurements and exceptions

Measure changed production functions with one pinned tool and rule configuration. Store tool/version, revision, unit, result, and review disposition so results can be compared. Cyclomatic complexity counts decision paths; it is a warning about review and verification effort, not proof of a defect.

| Function complexity | Required action |
| --- | --- |
| 10 or below | Normal review; correctness and cohesion still matter |
| Above 10 through 15 | Review the paths, nesting, and focused tests before merging |
| Above 15 through 20 | Refactor before merging, or record a principal approved bounded exception |
| Above 20 | Fail the quality gate unless the explicit exception process applies |

An exception names the exact function and revision, current measured value, reason extraction would be harmful, owner, compensating tests, debt item, and removal condition. It expires before the next release and needs a new reviewed decision to continue. The principal lead owns the exception; a contributor cannot suppress the rule locally. An exception cannot waive tenant isolation, transaction atomicity, or release evidence. Exclusions for generated code must be documented and must not hide handwritten policy.

Track cognitive complexity, duplication, size, coupling, cohesion, Maintainability Index, smells, and estimated debt effort. Establish a reproducible baseline before setting numeric limits for these signals. Review nesting and unrelated responsibility even when a numeric score is low. Function/class/module length is a signal to inspect, not an arbitrary universal line cap.

The import graph is a hard boundary: domain policy must not depend on HTTP, ORM, or provider SDKs; modules may not acquire undocumented cross module write ownership. Maintainability Index and debt ratios remain contextual estimates, with tool and uncertainty recorded. No baseline, objective threshold, or improvement result is invented. A debt item has impact, owner, effort range, mitigation, and review/expiry condition.

Coverage reports support a scenario map. Every critical predicate needs independent allowed, denied, and boundary examples. A high repository percentage cannot compensate for an untested revocation race or hidden tenant count. Duplication review distinguishes copied business rules from incidental text; extraction must preserve ownership and readability.

## Pattern decisions

The registry contains the precise owner, evidence, gate, and trigger for every pattern. The implementation choices below explain where the pattern earns its place.

| Pattern | Scopegate application |
| --- | --- |
| Factory | A small composition root selects configured adapters and rejects an unsafe identity adapter in production |
| Strategy | Context dependent callable variation for a real locale/retry algorithm; one authorization predicate remains canonical |
| Adapter | OIDC, delivery, catalog input, legacy source, and consuming application boundaries |
| Repository | Specific scoped queries; no generic CRUD repository framework |
| Unit of Work | Native SQLAlchemy transaction with one application owner |
| Dependency Injection | Explicit constructors and native HTTP dependencies; no additional container |
| Command | Typed bounded mutations with actor, scope, expected version, and receipt identity |
| Observer | Deferred for critical effects; durable outbox owns postcommit delivery |
| Decorator | Context dependent instrumentation that preserves port failures and exposes transaction ownership |
| Facade | Bounded access services for routes and consumers, with protected use inside the service boundary |
| Builder | Context dependent fixture construction; no production fluent hierarchy without need |
| Specification | One explicit domain access predicate, rather than a general rule language |
| State Machine | Guarded invitation, membership, grant, and migration transitions |
| Template Method | Deferred; explicit functions and ports avoid an inherited transaction skeleton |
| Service Layer | Policy orchestration, ordered locks, transaction, and response mapping belong in named application operations |

Layered, Clean, and Hexagonal architecture describe complementary constraints on the chosen modular monolith. Domain Driven Design supplies vocabulary, boundaries, and invariants. Separate command/read functions are useful without a second CQRS store. Migration uses a replayable pipeline; event driven behavior is limited to durable postcommit handoff where it is needed.

Onion layering adds no separate mechanism to the chosen dependency rules. Microservices, event sourcing, actors, serverless deployment, and Temporal/Airflow/Celery orchestration are deferred. They require a concrete independent deployment/team boundary, isolation need, measured workload, or recovery problem. Audit is not event sourcing, and a database outbox does not imply an external broker. Each alternative has its own trigger in the registry.

## Verification by product risk

Use many focused domain tests, strong PostgreSQL integration and contract tests, and a few complete browser journeys. Unit tests independently express policy and state rules. Integration tests prove constraints, snapshots, ordered locks, versions, receipts, and atomicity using real independent connections. Contract tests verify typed HTTP and adapter boundaries. E2E tests cover the complete invitation/grant/use/revoke journey and scope switching.

Regression tests preserve confirmed defect triggers. Smoke proves cold startup, migrations, readiness, and allowed/denied probes. Load and stress tests use a documented workload and dataset to establish capacity and bounded overload. Controlled fault drills exercise provider failure, database waiting, worker restart, poison delivery, and restore. Security probes and scans test an isolated running environment. Small snapshots are appropriate only when their stable output benefits semantic review; large DOM snapshots do not prove access.

Mutation testing targets pure critical policy guards. A proposed ten minute job budget is an execution bound to validate at foundation, not a claimed runtime or quality percentage. Seeded mutations that remove grant, scope, state, or expiry checks must be detected. Surviving mutations receive a disposition; budget exhaustion is incomplete evidence, never success. Equivalent mutations require a reviewed explanation. Broader mutation coverage is added only when it improves risk evidence within the agreed cost.

## Operating requirements

The full product includes structured logs, safe request/correlation identifiers, metrics, traces across the actual boundaries, dashboards, actionable alerts, health probes, business measurements, and recovery drills. These are requirements to implement; the planning validator cannot certify them.

Diagnostics identify safe actor/scope references, action, time, dependency, duration, and outcome. Do not log complete request payloads, invitation secrets, provider tokens, or raw source records. Metrics use bounded labels; individual identities and organization IDs are not labels. A synthetic failed journey must be traceable without exposing those secrets.

Define SLIs before SLO targets and record the denominator, exclusions, and observation window. Product and Operations approve any commercial SLA separately; no contractual commitment follows from an engineering proposal. Error budget policy ties observed reliability to rollout pauses and discretionary work. [Reliability design](RELIABILITY_DESIGN.md) and [capacity planning](CAPACITY_PLAN.md) own those definitions and operating budgets.

Horizontal replicas, load balancing, metadata caching, vertical scaling, and infrastructure tools are selected only under their stated deployment and measurement conditions. Indexing, bounded pools, admission control, worker limits, timeouts, idempotency, and safe retries are current requirements. Read replicas may not serve authoritative access from stale state. Partitioning, sharding, and autoscaling wait for measured triggers.

CI and local gates execute the same commands. Build once and promote the tested artifact with lockfiles and provenance. Small reviewed trunk based changes are preferred over GitFlow. Cohort canary uses parity and writer fences; feature flags cannot restore an old authorization writer. Blue green deployment needs overlapping connection headroom and compatible code. Docker is selected; Kubernetes and Helm are deferred. Infrastructure as Code and Terraform depend on the actual hosting target rather than a speculative stack.

## Fifteen category index

| Registry group | Canonical application |
| --- | --- |
| STD-01 Code quality | [Domain design](DOMAIN_DESIGN.md) |
| STD-02 Quality metrics | This standard and [quality](QUALITY.md) |
| STD-03 Design patterns | [Domain design](DOMAIN_DESIGN.md) |
| STD-04 Architecture | [Domain design](DOMAIN_DESIGN.md) and [architecture](ARCHITECTURE.md) |
| STD-05 Scalability | [Capacity plan](CAPACITY_PLAN.md) |
| STD-06 Database | [Distributed correctness](DISTRIBUTED_CORRECTNESS.md) and [data model](DATA_MODEL.md) |
| STD-07 APIs | [API](API.md) |
| STD-08 Security | [Security](SECURITY.md) |
| STD-09 Tests | [Quality](QUALITY.md) |
| STD-10 Observability | [Reliability design](RELIABILITY_DESIGN.md) |
| STD-11 Performance | [Capacity plan](CAPACITY_PLAN.md) |
| STD-12 DevOps | [Delivery system](DELIVERY_SYSTEM.md) |
| STD-13 Technical review | This standard |
| STD-14 Decision practices | This standard and [decision records](adr/0001-modular-monolith.md) |
| STD-15 Release completeness | [Delivery system](DELIVERY_SYSTEM.md) |

## Enforcement and decision ownership

`standards.json` maps each concept to one primary gate in [execution.json](../specs/execution.json). G-LINT covers static boundaries and complexity; G-DOMAIN, G-DATABASE, and G-CONTRACT cover rules and atomic effects; G-IDENTITY and G-SECURITY cover authentication and threats; G-BROWSER covers usable workflows; G-MIGRATION covers access parity and fencing; G-PERFORMANCE and G-OPERATIONS cover measured load and recovery; G-BUILD covers reproducible artifacts; G-RELEASE assembles the applicable evidence. These local gate entrypoints are implemented. A gate name or an adopted registry entry is not passing proof; only recorded execution at the delivery revision establishes its tested scope. Live workload, provider, host and sustained service objectives remain separate gates.

Before a material change, explain the problem and why it matters now. Record a concise ADR for accepted architecture changes. Use an RFC when the impact spans owners or reversibility is difficult. A spike or proof of concept answers one uncertain question within a bound and ends with an explicit adopt/discard decision. Risk review names the stop condition and recovery owner. A significant incident receives a blameless postmortem with contributing conditions and verifiable corrective actions.

The principal lead owns design constraints and exceptions; module owners own implementation evidence; reliability is a responsibility within the three engineer capacity, not an assumed extra position. Product owns commercial entitlements and unresolved approval rules. No standards review silently approves ambiguous access or substitutes synthetic evidence for a live gate.
