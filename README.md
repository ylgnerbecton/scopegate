# Scopegate

**Clear boundaries. Confident access.**

Scopegate is an organization access workspace. Teams manage project resource grants, invite verified recipients, and review every change through an audit trail. Organizations share a catalog while keeping membership, entitlement and resource use separate.

This repository contains a complete local product: a React workspace, FastAPI application, PostgreSQL migrations, an independent local OIDC provider, a durable delivery worker, a synthetic migration workbench, operating rehearsals and review material.

## Run the product

Requirements: Docker with Compose and Python 3.10 or newer for the secret initializer. The build installs its own locked application dependencies.

```sh
make setup
make up
```

Open **http://localhost:5187** and continue to sign in. The independent local provider offers synthetic accounts. Amelia Brooks manages Cedar Studio; Jonah Reed has a limited viewer grant; Rowan Vale has expiring staff assignments in both organizations; Morgan Lane can accept an invitation; Ellis Park manages Birch Labs.

The first build takes longer while images download. `docker compose ps` shows five running services; initialization exits successfully after migration and seeding. API documentation is at **http://localhost:8457/docs**. `make down` stops only this project's services and preserves its named volumes.

Secrets are generated into an ignored `.env` with restrictive permissions. The browser uses opaque session cookies, a verified authorization code flow with PKCE, and same-origin CSRF protection. Invitation links use a fragment removed before authentication. The local mailbox is restricted to access managers; no external message is sent.

## Explore the delivery

- [Guided demonstration in Portuguese](docs/DEMO.pt-BR.md)
- [Executive proposal](docs/PROPOSTA.pt-BR.md) and [review guide](docs/REVIEW_GUIDE.pt-BR.md)
- [Closed delivery scope](docs/LOCAL_PRODUCT.md) and [implementation map](docs/IMPLEMENTATION_MAP.md)
- [Architecture](docs/ARCHITECTURE.md), [domain design](docs/DOMAIN_DESIGN.md) and [data model](docs/DATA_MODEL.md)
- [API contract](specs/contracts/openapi.json), [database contract](specs/contracts/schema.sql) and [policy examples](specs/contracts/policy-cases.json)
- [Security](docs/SECURITY.md), [migration](docs/MIGRATION.md), [operations](docs/OPERATIONS.md) and [engineering decisions](docs/DECISION_MATRIX.md)
- [Learning guide in Portuguese](docs/LEARNING_GUIDE.pt-BR.md) and [acceptance specifications](specs/README.md)

A published resource does not grant customer access; an entitlement does not grant member access; an access manager does not receive an implicit consumption grant. A protected report rechecks current permission when opened. Versions, idempotency receipts, canonical locks and atomic audit changes preserve those rules during concurrent edits and revocation.

## Verify and package

Development and validation require `uv`, Node.js 24, npm, and Chromium. The browser suite uses installed Chrome on macOS; CI can install Chromium with Playwright. The rollback rehearsal requires this release's compatible parent commit in Git; the workflow fetches two revisions and checks matching database and HTTP contracts before using the earlier artifact.

```sh
make deps
make check
make lint typecheck
make test-unit test-integration
make test-browser
make verify
make package
```

Tests use a separate `scopegate_test` database on this project's PostgreSQL instance. They never truncate the displayed workspace. Browser tests exercise the running product with synthetic accounts. Intentional fault injection is named separately from normal journeys.

`make verify` executes runtime gates, captures real exit codes, checks the committed revision and creates hashed evidence. A missing tool, skipped test, unsuccessful command or stale generated contract blocks completion. `make package` creates the review archive under `artifacts/review/`, including public source and referenced proof. It excludes credentials, dependency directories, old failed logs and private inputs.

Verify a downloaded archive without Git or running services with `python3 scripts/package_review.py --verify /path/to/scopegate-<revision>.zip`. This checks the archive inventory, file hashes and executable modes. After extraction, `make setup` and `make up` start the local product. The archive contains no Git history; revision-dependent `make verify` and `make check-evidence` require the original checkout at the recorded commit, including its compatible parent for the rollback rehearsal. An independently initialized copy has a new revision and needs its own compatible baseline and new runtime evidence.

Maintenance commands for the Compose deployment use `docker compose --profile maintenance run --rm --build operations --help`; this opt-in container shares the actual journal and mailbox volumes. See [identity and delivery](docs/IDENTITY_AND_DELIVERY.md) for the command contract and scope.

## Delivery boundary

This release covers a reproducible local product and synthetic operating exercises. A real identity tenant, external notification service, host-loss durability, production traffic migration and sustained availability objectives require separate integration evidence and ownership. Production configuration deliberately refuses startup while those adapters remain outside this release.

Capacity and reliability contracts include proposed live targets. Local measurements describe the tested profile and do not certify a production service level. Migration review never guesses ambiguous access, and the web workbench cannot switch authority. Live pilot and contraction tasks remain outside the local completion stage.
