# Scopegate Architecture Decision Matrix

The architecture must protect scoped access while remaining understandable, testable and small enough to operate. This matrix compares viable choices against those goals and records when a deferred choice would become justified. Ratings are qualitative engineering judgments for the current scope, not measured performance scores or a mathematical proof.

Status: decisions governing the implemented local product and explicitly deferred evolution. The [ADRs](adr/0001-modular-monolith.md) record the selected boundaries; [Implementation map](IMPLEMENTATION_MAP.md) identifies delivered source. A selected decision is not proof that every technique or live operating target has been verified. Product assumptions still require validation against the private access baseline before live rollout.

## Evaluation criteria

Use five criteria: authority correctness, transaction clarity, verification cost, operational burden and ability to evolve independently. Authority correctness is a gate: an alternative that broadens access or loses revocations is rejected regardless of its other advantages. Measured workload and real ownership needs can change the other judgments. `Fit` means a direct match; `Tradeoff` means feasible with a meaningful cost; `Defer` means the present benefit does not justify that cost; `Reject` means it conflicts with an invariant.

## Deployment and dependency architecture

| Alternative | Authority and transaction clarity | Verification and operations | Evolution | Decision and revisit signal |
| --- | --- | --- | --- | --- |
| Modular monolith with inward dependency rules and explicit ports | Fit: one use case transaction across access, enrollment and audit | Fit: one deployment family and database; real adapter tests remain necessary | Fit: modules expose seams for later extraction | Selected; revisit after measured independent scaling or team lifecycle needs |
| Layered application with no context ownership | Tradeoff: transactions are possible, but cross module writes are easy | Tradeoff: low initial setup with increasing coupling risk | Tradeoff: unclear extraction seams | Use layers inside modules; reject unrestricted table access between modules |
| Microservices for access, enrollment and audit | Tradeoff: relationship data and audit must cross transactional boundaries | Defer: delivery, replay, schema compatibility and partial failure become mandatory | Fit only with real independent ownership or deployment need | Defer until such a need outweighs synchronization cost and its failure evidence exists |
| Serverless HTTP functions over managed PostgreSQL | Tradeoff: bounded transactions are feasible with careful pooling | Tradeoff: platform limits, connection bursts and worker lifecycle must be measured | Conditional fit for hosting constraints | Defer deployment choice until actual hosting discovery; preserve domain and adapter boundaries |

Clean, hexagonal and onion architecture express related inward dependency rules rather than requiring three frameworks. Scopegate applies that rule through pure domain logic, explicit use cases and adapters. Domain driven design supplies the context vocabulary and invariant boundaries. It does not require an aggregate framework, service per entity or event sourcing.

## Access model and policy

| Alternative | Correctness | Maintenance and evidence | Decision |
| --- | --- | --- | --- |
| Normalized memberships, project entitlements and explicit grants | Fit: tenant keys and per project individual authority are expressible | Fit: joins and indexes are visible; shared predicate and negative tests | Selected |
| Resource identifiers embedded in user text or JSON | Reject: weak relationship integrity and user wide replacement semantics | Tradeoff: easy initial storage but hard scoped diff, audit and reconciliation | Reject for target authority; parse only through the reviewed source adapter |
| Organization role alone | Reject: cannot express an ungranted manager or different resources per project | Simple queries cannot recover the missing business distinction | Reject |
| Relationship based external policy engine | Potential fit if multiple independent products need shared decisions | Defer: synchronized state, consistency semantics and another service to operate | Revisit when policy federation or measured decision complexity requires it |
| Application policy with composite database constraints | Fit at the single application consumer boundary | Fit only with mandatory negative endpoint and SQL tests | Initial enforcement layer |
| Application policy plus PostgreSQL row security | Fit as defense in depth, with nonowner roles and pooled context tests | Tradeoff: a second tenant filtering surface to verify | Required before independent database consumers; stage under ADR 5 |

RBAC selects management operations. Relationships and attributes such as expiration, status and scope decide consumption. A generic ABAC rules language would obscure this small known policy. Prefer named pure predicates with a complete decision matrix.

## Concurrency and destructive lifecycle

| Alternative | Benefit | Cost or rejected implication | Decision |
| --- | --- | --- | --- |
| Read Committed with ordered resource and organization locks and fresh statement | Visible admission and revocation ordering; simple retry scope | Every cooperating writer must follow the protocol | Selected under [ADR 7](adr/0007-ordered-authorization-transactions.md) |
| Serializable as a replacement for the protocol | Detects broader database serialization conflicts | Serial equivalence alone does not specify the desired postwait policy decision or external delivery ordering | Defer; a new predicate intensive invariant can justify a tested design change |
| Version checks alone | Detects a stale editor | Cannot protect a report's check and durable creation against concurrent revocation | Retain versions alongside locks |
| Entitlement disable as availability pause | Preserves old grants for later resumption | Reenable can silently restore access and accept earlier invitation plans | Reject for the selected product semantics |
| Bounded disable revokes scoped grants and dependent invitations | Explicit irreversible access removal with one reviewed transaction | Larger fanout needs impact preview, version checks and firm caps | Selected under [ADR 6](adr/0006-manager-continuity-and-entitlement-revocation.md) |
| Entitlement generation with grants bound to an epoch | Constant size invalidation can support very large fanout | Adds effective grant state, invitation revision and migration semantics | Defer until bounded disable is insufficient; new ADR and parity evidence required |
| Retain one currently valid manager of any kind | Easy current count | Staff expiry can later leave the organization unmanaged | Reject as continuity proof |
| Retain one active nonexpiring customer manager | Explicit durable management continuity | Requires a reviewed ownership assumption and emergency repair workflow | Selected; private Product and Operations approval required |

## Delivery, read models and processing styles

| Style | Applied or deferred reason |
| --- | --- |
| Event driven delivery | Apply transactional outbox for the actual invitation delivery boundary; retain grant authority in the transaction |
| CQRS | Apply separate command services and bounded read selectors within one application; defer independent read stores and consistency lag |
| Event sourcing | Defer: append only audit is evidence, not the source from which all current state is rebuilt |
| Pipeline processing | Apply bounded migration stages with a ledger, explicit input revision and reconciliation gates |
| Workflow engine such as Temporal, Airflow or Celery | Defer: current enrollment and migration controls are expressible with domain state and a database worker; revisit durable long workflows with external compensation |
| Actor model | Defer: PostgreSQL transactions already serialize the required scope; no independent actor runtime need |
| In process observer callbacks for critical audit or delivery | Reject as durability mechanism: process death can lose an effect after the domain commit |
| External broker and inbox store | Defer infrastructure; command and catalog receipts deduplicate present inbound commands. Add an inbox only for a real external event boundary requiring event identifier and atomic consumer state |
| Builder or template method framework | Defer until repeated construction or algorithm skeletons create a real maintenance problem |

## Scaling choices and revisit evidence

| Mechanism | First implementation | Evidence needed for expansion |
| --- | --- | --- |
| Stateless HTTP replicas and load balancing | Permitted after integration tests; opaque sessions and authority remain in the database | Pool sum, tenant contention and measured burst behavior |
| Vertical database sizing and indexes | Apply representative query plans, bounded pagination and selected indexes | CPU, I/O, lock wait and query workload; no sizing claim from fixture volume alone |
| Async worker pool and backpressure | Apply bounded database outbox batches, leases, provider timeout, retry budget and visible failed state | Delivery age, duplicate outcomes, backlog growth and separate API/worker connection budgets |
| Rate limiting and bulkheads | Bound expensive routes and external adapter concurrency; separate worker capacity from HTTP capacity | Actual gateway and hosting capabilities, saturation test and safe denial behavior |
| Circuit breaker and exponential retry | Bounded adapter failure handling with jitter; never wrap database authorization in permissive fallback | Provider outage and recovery traces; avoid a custom resilience framework |
| Caching and CDN | Static assets and scoped browser presentation; no server privilege cache | Measured metadata cost; current primary authorization must still filter every response |
| Read replicas | Defer for access decisions and receipts | Use only a separately classified stale tolerant read need; no policy path can rely on replica freshness |
| Partitioning | Defer until audit or ledger volume produces measured retention, vacuum or query pressure | Query plans, retention ownership and rehearsed partition maintenance |
| Sharding | Defer: global catalog and tenant integrity currently benefit from one relational boundary | A demonstrated capacity limit and a complete cross shard identity, migration and policy design |
| Autoscaling and cluster orchestration | Defer infrastructure-specific implementation | Hosting budget, rollout needs and proven saturation controls; replica count cannot exceed database capacity |

## Standards coverage and deliberate limits

| Standard category | Application to this architecture | Deferred or separate evidence |
| --- | --- | --- |
| Code quality | KISS, DRY, explicit constructor injection, pure policy, fail fast configuration and defensive state checks | No universal repository or injection framework |
| Quality metrics | Review complexity, nesting, duplicate predicates, module size, coupling and cohesion | Coverage and maintainability scores support review; they do not prove authorization or substitute for behavioral gates |
| Design patterns | Service, command, adapter, domain repository, unit of work and factory at composition | Strategy only for real provider or source variation; other patterns require a concrete repeated problem |
| Software architecture | Modular monolith, inward dependencies, bounded contexts and narrow ports | Microservices, independent read models and workflow runtimes require new measured needs |
| Scalability | Bounded work, pool budget, indexes, worker backpressure, rate limits and retry | Replica, partition and shard choices follow measurements |
| Database | Normalized relationships, composite constraints, transaction locks, access versions and safe Alembic changes | Dynamic authorization remains a shared service rule; hard deletion is restricted |
| API | REST operations, OpenAPI, generated client, stable errors, cursor binding and receipt scope | gRPC is deferred until a real service boundary requires a second transport |
| Security | OIDC, verified session claims, relationship policy, least privilege, CSRF, encoding and safe secret handling | Real provider, delivery, supply chain, SAST and DAST gates cannot be replaced by document review |
| Tests | Strong domain and PostgreSQL integration, contract and limited end to end journeys | Targeted stress and fault injection; mutation tests for critical pure policy after meaningful scenarios exist; snapshots for stable manifests only |
| Observability | Structured safe logs, request correlation, traces through adapters, business outcomes and readiness | SLIs, SLOs and error budgets need a measured baseline; an SLA needs an actual service agreement |
| Performance | Query plans, profiling, batching, no N+1 DTO reads and bounded async I/O | Compression, precomputation and extra caches require measured benefit |
| Delivery | Reproducible lockfiles and images, trunk based small changes, local/CI parity, per organization rollout fences | Blue green infrastructure must retain target authority; Kubernetes, Helm and Terraform depend on hosting requirements |
| Technical review | Simplicity, scope, safety, testability, reversibility and dependency direction reviewed together | A favorable benchmark cannot waive an access mismatch |
| Decisions | ADRs, tradeoffs, focused spikes and risk register | A spike answers one named uncertainty; no open ended framework comparison |
| Completion | Domain behavior, timeouts, retry, audit, monitoring, rollback and ownership have concrete gates | Planning completion remains distinct from executed runtime and private rollout evidence |

## Revisit procedure

Name the measured problem and affected invariant, record alternatives and failure outcomes, and run a bounded proof against representative data. Update the ADR, canonical contracts and affected tests together. A platform change cannot silently relax tenant scope, receipt semantics, manager continuity or revocation ordering. Review incidents without assigning blame; turn the failing boundary into an explicit regression scenario and an owned corrective action.
