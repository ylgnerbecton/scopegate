# Validation and proof boundaries

Scopegate is an implemented local product. Release acceptance requires twelve real gates against the committed revision, all 67 mapped acceptance scenarios and T00–T12 task proofs. The collector records commands, timestamps, exit codes, test results and artifact hashes in [implementation-evidence.json](../specs/implementation-evidence.json). It rejects missing tools, nonzero exits, skipped tests and mismatched proof. The manifest is authoritative for the current release.

## Reproduce

```sh
make deps
make up
make verify
make check-evidence
make package
```

The host requires Docker Compose, Python 3.12 through uv, Node.js 24 and a Playwright browser. Linux installation is `npm --prefix frontend exec -- playwright install --with-deps chromium`; macOS uses installed Chrome. `make down` stops the owned deployment and preserves volumes. The dependency audit requires network access; unavailable advisory feeds are failures.

The commands are defined in [execution.json](../specs/execution.json). Python results use JUnit; frontend unit and browser results use JSON. [scenario-tests.json](../specs/scenario-tests.json) binds each scenario to named passing tests or an explicitly documentary review. Discovery ownership, scope and standards decisions use documentary proof, which cannot certify an unexecuted integration. Public packaging includes Git inventory and verified artifacts, excluding local configuration, token files and database content.

## Behavior checks

Tests execute real PostgreSQL transactions in the separate `scopegate_test` database. Controlled races observe actual database waits. They cover post-lock expiry, use/revoke ordering, duplicate receipts, stale edits, audit atomicity, scoped staff grants, durable manager continuity, terminal catalog archival and entitlement caps. HTTP responses are validated against the independent OpenAPI contract. Customer role escalation, foreign ownership, CSRF and machine credentials have negative cases.

An independent local OIDC issuer performs signed code exchange with S256 PKCE. Tests reject wrong issuer, audience, nonce, freshness, signature and keys. Sessions recheck revocation and expiration after row waits. Invitations enforce verified recipient binding, single use, current entitlements and suspended-member protection. Outbox tests exercise lease ownership, crash recovery, exhausted retries, reviewed replay and one-hour ciphertext retention.

Browser journeys use the running issuer, API, worker and database. They cover invitation acceptance through use/revocation, a real organization-A response held until organization B is visible, localization, narrow layouts, keyboard controls, an isolated resource-panel fault, competing grant edits, distinct invitation/delivery states and competing migration evidence. Invitation and reviewed grant changes run exclusively through keyboard events at 375, 768 and 1440 pixels. Axe checks the journey states against WCAG A/AA rules without exclusions, and exported interaction and delayed-response reports are included in the verified proof. These scans and screenshots do not claim universal assistive-technology certification.

Migration tests account for malformed and ambiguous source elements without inventing access, retain unknown identity/baseline decisions, replay idempotently, compare allow and deny decisions and fence incomplete cutover. Recovery restores an older policy state and reconciles later revocations before reopening traffic. Unknown operations or changed catalog evidence keep the restore fenced. Alert drills expose actionable ownership and contain the affected organization; remote notification delivery remains external. The operations gate also stops the actual owned Compose worker with SIGTERM, verifies exit 0 without forced termination, and restarts it before release. A second rehearsal replaces the API at a different container address and verifies recovery through the same web container within 45 seconds. Both reports are included in the verified proof.

The web proxy uses Docker's internal DNS resolver with a five-second cache and a variable upstream, following the [NGINX proxy contract](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass). API replacement can produce transient failures during restart or cache expiry; the rehearsal checks recovery rather than claiming uninterrupted service.

Application rollback builds the current and parent Git revisions as separate local container artifacts, requiring identical canonical database and HTTP contracts. Against the isolated test database, an existing report must return 200 before revocation, then remain present while the previous artifact denies it by policy after the swap. Target authority and the revoked grant must remain unchanged. The earlier artifact is a local compatible baseline, not certification for arbitrary older binaries or live deployments. CI fetches both revisions; the intermediate manual baseline override is not used for final release evidence.

## Local workload

The capacity test seeds approximately 10,000 resources, 40,000 localized rows and 10,000 grants. It measures one API process in an owned container limited to one CPU and 512 MiB, with a maximum of five database connections, verified sessions, open-loop traffic and controlled row-lock pressure. The API connects directly to the isolated test database through the same Compose network used by the product; a separate owned load-generator container reaches that API through the internal network. The report identifies both containers and their resource limits. Browser and published-port transport are outside this capacity measurement and are exercised by the browser and proxy gates. A separate authenticated preflight warms startup and connections before measured arrivals. Every measured response includes arrival-to-completion latency, dispatch lag and HTTP duration; generator connection capacity covers all scheduled arrivals, preventing a hidden client-pool queue from substituting for server admission. The report records the source revision, container image ID, enforced limits, CPU and memory counters, connection peak and removal of the owned benchmark resources. Current measurements are stored in `artifacts/performance/report.json` and referenced by verified proof.

Release acceptance requires 20/20 successful responses at 10 RPS, bounded responses under higher load and locks, twenty foreign-scope denials and at most five API database connections. Page depths 1, 25 and 100 must use a constant number of SQL statements. The generator retains scheduled arrival-to-completion latency, so dispatch delays cannot be subtracted to obtain approval. Earlier host-side rehearsals exposed substantial published-port overhead and failed to dispatch the highest rate on schedule; their timings do not describe this release profile. Each release reruns the internal-network experiment, and current verified results take precedence over historical measurements.

This two-second-per-rate profile establishes behavior only at the tested size. Larger production datasets, sustained throughput, availability targets, distributed journal durability, host-loss recovery and real-provider integration remain unvalidated. The report marks production capacity unvalidated.

## Additional and external proof

Specification checks cover 20 requirements, eight features, 67 scenarios, fifteen tasks, 35 API operations, 27 written clauses and 230 engineering concepts. The negative fixture harness verifies 61 malformed or stale metadata cases. The independent DDL runner previously executed eleven positive and 69 negative PostgreSQL structural cases plus controlled snapshot/lock schedules. Eight architecture diagrams have rendered exports, including actual components and local deployment; the ER includes all 21 tables with selected columns. Runtime lint, types, build, dependency audits and generated contract drift are required gates. SBOMs preserve actual package identities, versions, hashes and licenses; optional maintainer links are omitted from the shareable frontend inventory; no operating-system image vulnerability scan is claimed.

The GitHub workflow uses Node.js 24 and the official [setup-node action](https://github.com/actions/setup-node), with uv installed through its [official integration guidance](https://docs.astral.sh/uv/guides/integration/github/). Remote workflow execution is unverified until publication. All release evidence is local; there are no live approval records.

T13 and T14 are outside the closed delivery: actual identity/notification adapters, complete live writer/consumer inventory, reviewed intended-access baseline, tenant pilot, observed cohorts and eventual legacy contraction. Synthetic evidence cannot substitute for their owners and approvals. Production configuration deliberately refuses startup until those integrations are implemented and reviewed.
