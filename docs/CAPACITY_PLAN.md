# Scopegate capacity and query plan

Scopegate starts with bounded requests, one primary database, and measured scaling decisions. This plan supplies explicit synthetic workloads and proposed local and pilot budgets so implementation can be tested before an organization pilot. The numbers are engineering hypotheses, not observations of a live installation. [capacity.json](../specs/contracts/capacity.json) owns the machine-readable values; [Reliability](RELIABILITY_DESIGN.md) owns deadlines and safe degradation.

## Workload assumptions and evidence

The proposed workload serves 100 organizations, 1,000 projects, 10,000 catalog resources, and 100,000 grants, preserving the fixture basis in [Data model](DATA_MODEL.md). Add 20,000 identities, 30,000 memberships, up to 40,000 localized resource rows, 50,000 invitations, one million audit events, and 5,000 due outbox items. One organization holds half the grants, and one membership has 10,000 grants across projects. This skew deliberately exercises pagination and contention; a uniform fixture would conceal important failure paths.

Keep separate fixture variants for missing translations, suspended memberships, expired staff, archived resources, disabled entitlements, revoked grants, invitation replay, and migration discrepancies. They are not random noise mixed into a success-only benchmark. Define expected permitted and denied outcomes before generating load. Use deterministic seeds and record fixture revision, cardinalities, distribution, database statistics, engine version, hardware allocation, and application revision in every report.

| Assumption | Proposed value | Evidence required before live adoption |
| --- | --- | --- |
| Ordinary arrival rate | 10 requests/s | Edge request distribution by bounded operation class and active period. |
| Sustained peak | 40 requests/s | Busy-hour measurements and tenant workflow traces. |
| Burst | 160 requests/s for 60 seconds | Release and batch activity measurements, including denial traffic. |
| Mean service residence time | 250 ms | Mean edge-to-response time, including queueing; do not substitute a percentile. |
| Mean held database time | 80 ms/request | Checkout-to-return measurements across the workload mix. |
| Read and search share | 65% and 15% | Actual endpoint mix; search remains a scoped tenant query. |
| Mutation and protected-use share | 10% and 5% | Version conflicts, delta size, report reference distribution. |
| Identity and operational share | 5% | Callback frequency and bounded operational reads. |
| HTTP pilot allocation | Two replicas, two workers each; 2 vCPU and 1 GiB per replica | Profiled CPU, event-loop delay, memory, and host adapter limits. |
| Database pilot allocation | 2 vCPU, 4 GiB; 20 GiB initial storage | Query plans, resident working set, WAL and growth measurements. |

The resource allocation is a test profile to provision through the selected hosting adapter, not an assumed existing environment. Local testing must report when the actual host differs. The local benchmark records actual fixture sizes, host profile, throughput, latency, connection demand and pressure behavior in artifacts/performance/report.json. The larger live profile remains unverified.

## Concurrency calculation

Little's law relates average in-flight work to arrival rate and mean residence time in a stable observation interval: `L = λ × W`. The proposed numbers give ordinary `10 × 0.25 = 2.5`, peak `40 × 0.25 = 10`, and burst `160 × 0.25 = 40` concurrent requests. Fractional results are averages, not worker counts. A p95 latency is useful for user experience but cannot replace the mean in this equation.

The proposed four HTTP workers allow 16 active requests each, for 64 total active requests, with at most eight waiting admissions per worker and a 50 ms admission wait. This covers the 40-request illustrative burst concurrency with some headroom, provided the residence-time hypothesis holds. If a dependency increases mean residence to two seconds, `40 × 2 = 80` concurrent requests exceeds that limit; bounded rejection protects the application rather than allowing indefinite queues.

Mean concurrent database occupancy is a different calculation. With 80 ms of checkout occupancy per request, peak `40 × 0.08 = 3.2` and burst `160 × 0.08 = 12.8` connections are illustrative averages. The HTTP pool maximum is 20. Lock contention, long transactions, uneven balancing, and slow SQL can exhaust one worker's pool before an average across replicas predicts trouble. Measure per-process waits and tenant skew rather than increasing all pools from this arithmetic alone.

## Connection budget and rollout overlap

For one database, enforce:

```text
HTTP_replicas × workers_per_replica × (pool_size + max_overflow)
+ outbox_total_connections
+ operations_and_migration_connections
+ database_and_host_reserve
<= max_connections
```

| Consumer | Proposed bound | Maximum connections |
| --- | --- | --- |
| HTTP | 2 replicas × 2 workers × (pool 4 + overflow 1) | 20 |
| Outbox | 2 worker processes × pool 2, zero overflow | 4 |
| Operations and migration | Shared allocation, including at most 2 backfill connections | 8 |
| Database, host, monitoring, and recovery reserve | Reserved independently of application pools | 20 |
| Planned application and operational use | 20 + 4 + 8 | 32 |
| Application and operational allocation | Maximum 60 less reserve 20 | 40 |
| Planned use plus protected reserve | 32 + 20 | 52 |
| PostgreSQL configured maximum | Proposed subject to host memory verification | 60 |
| Unused headroom within allocation | 40 − 32 | 8 |

SQLAlchemy's per-engine maximum checkout count is pool size plus overflow; each worker owns its pool. The selected synchronous or asynchronous engine must use the corresponding supported pool, and overflow must remain finite. If role separation creates multiple engines in a worker, their combined maximum remains inside that worker's allocation; the pool size is not copied independently for every credential. [SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html).

A third HTTP replica adds ten connections: application and operational use becomes 42, exceeding its allocation of 40, and the total including reserve becomes 62, exceeding 60. Initial rollout therefore uses maximum surge zero and minimum ready replicas one. Drain and dispose the retiring replica's pools before replacement admission. Include old workers, new workers, release jobs, and operator sessions in the same budget; a deployment controller cannot omit draining processes from its calculation. Preserve current target authority while replicas change.

Autoscaling beyond two replicas, or enabling a surge replica, requires a newly approved connection and database-memory budget, load evidence, and a reviewed deployment plan. A pooler can be evaluated after measured churn or connection overhead justifies it; it is not introduced preemptively. Transaction pooling must be checked against session features, advisory transaction locks, prepared statements, and connection context before adoption.

## Endpoint budgets

All values below are proposed p95 server-edge latency targets under the sustained 40 requests/s profile. Collect p50, mean, p95, p99, worst successful latency, bad-request ratio, and saturation measures; do not report only successful fast responses. The absolute request deadlines in reliability apply independently.

| Operation class | Proposed p95 | Maximum application SQL statements | Work bound |
| --- | --- | --- | --- |
| Organization and project lists | 250 ms | 5 | Default 25, maximum 100 rows. |
| Members and grant pages | 300 ms | 6 | Maximum 100 rows; grant cursor binds access version. |
| Scoped resource search and localization | 350 ms | 6 | Maximum 100 rows; authorization precedes pagination. |
| Invitation creation or resend | 500 ms | 12 | Bounded explicit resource plan; outbox commit only. |
| Grant delta and membership change | 500 ms | 12 | At most 100 additions and 100 removals; changed delta at most 200. |
| Entitlement disable after impact preview | 750 ms | 16 | At most 200 memberships, 500 grants, and 200 pending invitations; larger impact returns conflict with no writes. |
| Invitation preview and acceptance | 500 ms | 12 | Recent verified session; no provider call while locks are held. |
| Protected report admission | 500 ms | 10 | Bounded resource set and atomic durable admission; report computation is separate. |
| Identity callback | 2,500 ms | 8 plus bounded provider calls | Absolute callback deadline 5,000 ms. |
| Audit and migration review page | 350 ms | 6 | Maximum 100 rows; restricted reviewer scope. |

Statement counts include session, policy, receipt, and audit work where applicable; connection initialization and transaction control are separately recorded. A trace assertion fails if page size changes from 1 to 100 and the query count grows with rows. A constant extra batch lookup can be reviewed; one query per localized record or grant is prohibited. Count round trips as well as statements so batched SQL does not hide excessive database work.

The current API contract remains authoritative for operation-specific body and reference bounds. The proposed transport envelope is 64 KiB for ordinary commands and 256 KiB for a publisher resource with localizations, rejected before materialization. A body cap does not replace per-field limits or the entitlement-impact caps. Impact preview uses the same scope and a deterministic fingerprint; mutation verifies its revision and fingerprint under canonical locks. A stale preview cannot justify an oversized or changed write.

## Pagination and query plans

Use keyset pagination with stable ordering and a UUID tie-breaker. Cursor binds principal, organization, project, query, locale, sort, view, and relevant access version. A grant cursor from an older membership version yields a refresh conflict rather than combining inconsistent pages. Counts and cursor boundaries are formed after policy filtering. Offset pagination is excluded from large operational lists.

For an audit timeline, the intended predicate is `organization_id = :organization AND (created_at, id) < (:last_time, :last_id)` with descending timestamp and identifier ordering and a bounded limit. `audit_events_org_time` already supports that shape. For a grant page, use its scoped composite key and access version; validate whether resource identifier ordering is sufficient for the selected view rather than adding an index for every displayed column.

Capture `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on synthetic representative data for each high-volume query. PostgreSQL explains actual execution and buffer use; the command executes the statement, so mutation-plan experiments require a disposable database or explicit transaction rollback. [PostgreSQL query plans](https://www.postgresql.org/docs/18/using-explain.html).

| Query | Existing candidate index | Review signal |
| --- | --- | --- |
| Principal membership and tenant scope | `memberships_user_org` and scoped uniqueness | No scan of unrelated memberships to authorize one request. |
| Entitled resources within a project | `project_resources` primary key | Bounded range access and policy joins. |
| Membership grant page | `resource_grants` scoped primary key | Constant query count; bounded rows and consistent cursor. |
| Locale batch | `localizations_locale_resource` and resource/locale primary key | Batch joins avoid one query per resource. |
| Audit cursor | `audit_events_org_time` | No full-history sort or offset walk. |
| Pending invitation lookup | `pending_invitations_org_recipient` | Measured selectivity and expiry handling; no email-based identity merge. |
| Outbox claim | `outbox_pending` plus the reviewed lease predicate | Claim work remains bounded with many leased or future rows. |
| Migration ledger and manifest | Scoped run/organization keys and outcome index | Batch export and review do not scan all private records per page. |

Plan acceptance checks actual versus estimated rows, loops, rows removed by filters, shared hits and reads, temporary spill, execution time, and lock waits. Flag estimate errors above tenfold and disk sorts in bounded tenant list paths for investigation, not automatic rejection when a small deliberate scan is cheaper. `ANALYZE` statistics and distribution accompany the plan. Initial hypothesis: hot policy lookups p95 at most 25 ms, bounded list SQL p95 at most 75 ms, no unexplained temporary disk spill at the page bounds. Final thresholds follow measured hardware evidence.

Search begins with escaped case-insensitive literal matching on the approved fields. A leading-substring query may require measured trigram indexing at catalog scale; a plain B-tree does not solve every matching shape. Add `pg_trgm` only after its plans, storage, write cost, supported deployment, and tenant filter behavior are reviewed. Keep global catalog metadata hidden from customer searches even if the index could find it.

## Cache and replica rules

Use immutable versioned static assets with a CDN when the selected host supports it. Cache catalog presentation metadata by resource version and locale for at most five minutes; invalidate on publication or archival and serve it only after the current policy has admitted the requested record. Missing or old catalog metadata can degrade presentation. It cannot keep an archived resource usable.

Do not cache sessions, memberships, entitlements, grants, migration authority modes, staff expiry decisions, or successful authorization decisions for protected use. Frontend query state remains presentation state and is cleared on account switching and logout. Every consumption and access mutation reads the current primary under the canonical lock protocol.

A future replica may serve explicitly nonauthorizing analytics or catalog metadata after its lag and data-exposure policy are verified. It must not decide access or supply a state check whose staleness could permit use after a primary revocation. Replica lag is measured, and every candidate query gets an owner, consistency classification, and fallback. The initial plan has zero replicas.

## Storage and retention sensitivity

At the proposed peak, the 10% mutation share produces four commands per second. Eight peak hours per day gives `4 × 8 × 3,600 = 115,200` mutation events per day, assuming one event per command. Ninety days gives 10,368,000 events. An illustrative 500-byte stored event would occupy about 5.18 GB before indexes, row overhead, retained versions, WAL, backups, or extra events. At 250 to 1,000 bytes, that raw estimate spans 2.59 to 10.37 GB. These are sensitivity calculations; the audit retention period and actual stored bytes require data-owner and measured database evidence.

Measure relation and index size, daily WAL, transaction churn, purge progress, bloat, vacuum duration, and retained journal volume. The initial 20 GiB database allocation cannot be declared sufficient from the fixture count alone. Alert for review at 70% storage use and project remaining days from observed growth. Expansion or archival must preserve current grant state and required recovery evidence; dropping audit partitions is not a shortcut around retention approval.

## Test scenarios and acceptance

| Scenario | Proposed schedule | Required result |
| --- | --- | --- |
| Warmup and steady peak | 15-minute warmup, 30 minutes at 40 requests/s | Endpoint p95 budgets, bad fraction at most 0.1%, no unsafe allow, bounded query counts and pools. |
| Burst and recovery | 60 seconds at 160 requests/s, then ten minutes at 40 | No connection-budget violation; bounded rejection and recovery within two minutes. |
| Hot organization | Half the grant workload targets the large organization | Version conflicts are explicit; unrelated organizations remain responsive. |
| Concurrent edit and use | Shared-use and exclusive-revoke interleavings under load | Canonical ordering, no protected admission after revocation wins, complete audit. |
| Entitlement impact boundary | Exactly at caps and one over each cap | Within-cap atomic mutation; above-cap 409 with no access or invitation writes. |
| Stress to first saturation | Increase load in 20 requests/s steps, at most five minutes each | Record the first limiting resource; rejection protects memory, pools, and state. |
| Soak | Two hours at 40 requests/s with invitation and outbox work | No growing memory, connection leakage, outbox drift, or purge backlog. |
| Dependency degradation | Slow provider, unavailable delivery, exhausted pool | Bounded safe behavior from reliability; no retry multiplication. |

The workload runner uses a fixed-arrival model for peak and burst tests so slow responses do not silently reduce offered load. Report offered, admitted, completed, denied, overloaded, timed-out, and cancelled work separately, including separate allowed and denied latency distributions. The test must account for coordinated omission and edge timeouts. Run cold and warm metadata variants, with and without permitted cache reuse; permission behavior must remain identical.

The local benchmark and `G-PERFORMANCE` entrypoint, `make test-performance`, are implemented; [Validation](VALIDATION.md) records the measured profile and actual evidence. They do not establish the full proposed workload, long-running schedules above, every capacity/resilience parameter or a live availability objective. Those remain separately owned adoption requirements outside the closed local release. Store histograms, query plans, connection maxima, resource graphs, failure classification and pass criteria at the tested revision. An insufficient environment or a generator unable to sustain its declared offered load is inconclusive and cannot become passing performance evidence.

## Scaling decisions and trigger evidence

| Candidate change | Trigger to investigate | Evidence before approval |
| --- | --- | --- |
| More HTTP replicas or workers | CPU above 70% and p95 target missed for three measured peak windows, with low database contention | Profiling proves application bottleneck; new connection and memory budget includes rollout overlap. |
| Database vertical growth | Working set, CPU, or I/O constrains proven efficient queries | Query and lock tuning complete; cost, backup, and restore behavior reverified. |
| More outbox workers | Due age exceeds five minutes with healthy provider and sustained claim capacity shortage | Provider quota, DB allocation, lease safety, and duplicate delivery behavior verified. |
| Read replica | Nonauthorizing analytics measurably harms primary workload | Explicit read classification, lag visibility, no authorization decision moved. |
| Audit time partitioning | Audit retention or vacuum/maintenance threatens a measured operating window, initially review at ten million events | Partition-aware constraints, query pruning, retention ownership, and restore rehearsal. |
| External broker | Database outbox cannot meet measured delivery throughput after bounded tuning, or independent consumers become necessary | Delivery semantics, inbox/deduplication, operational ownership, and migration cost justified. |
| Tenant shard | Single-primary write capacity or contractual isolation is exhausted after simpler measures | Tenant placement, global identity/catalog strategy, cross-shard workflow, fencing, and recovery RFC. |

Thresholds initiate investigation; they do not automatically install infrastructure. Start with the modular monolith, primary database, explicit pools, and bounded outbox. Partitioning, sharding, a broker, replicas, and an orchestrator require separate reviewed decisions based on the problem now present.

## Pilot inputs and ownership

Platform owner confirms host limits, connection reserve, storage growth, backup transport, and provider quotas. Backend owner supplies query plans, pool metrics, payload bounds, and contention results. Product and operations confirm actual workflows and peak periods. Security owner confirms that caching and replica classification preserve the current access rule. The release owner approves targets and evidence windows before T13; unknown production traffic, storage, provider limits, or host allocation remains a live input gate while synthetic implementation continues.
