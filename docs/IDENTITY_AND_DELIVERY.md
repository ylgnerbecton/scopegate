# Identity, enrollment and local delivery

The running evaluation uses an independent OIDC process, a PostgreSQL session store and a private local delivery adapter. The local accounts and addresses are synthetic. No external messages are sent. Production configuration rejects the local identity, delivery and recovery adapters until separately reviewed integrations exist.

## Sign in and trust

The browser starts at `/auth/login`. The application requests Authorization Code with PKCE S256, a random state, a nonce and a provider authentication age of at most fifteen minutes. The short-lived flow cookie is encrypted and HttpOnly. Its contents bind the callback to the browser, code verifier and validated same-origin relative destination. The independently running provider exposes discovery and an RSA signing key through JWKS. Its authorization code can be exchanged once, only by the allowlisted client and callback with the matching PKCE verifier.

The application accepts only its configured issuer and endpoint prefix, RS256 and a known signing key. It verifies signature, issuer, audience, authorized party when applicable, nonce, expiration and provider authentication time. A provider failure or unknown proof denies sign in. Two in-process provider slots limit concurrent exchanges; each request has bounded connect/read timeouts and shares the five-second flow deadline. An uncertain code exchange is not repeated with a new intent.

Identity belongs to `(issuer, subject)`. Email remains contact data and a provider claim used for invitation binding. Updating contact email cannot merge two identities. After verification, the application creates a random opaque cookie and stores only its SHA-256 digest. Reauthentication revokes the previous backing session. Browser storage contains neither an identity token nor a refresh token.

Each authenticated browser request locks its session row in a separate statement, reads the authoritative database clock after any wait, and rejects revocation or expiration before extending activity. The idle lifetime is thirty minutes and the absolute lifetime is eight hours. Activity and expiry updates are monotonic within that absolute bound. Controlled two-connection tests prove that a row wait cannot revive an expired or revoked session.

Unsafe browser requests require `X-CSRF-Token` and an exact configured Origin. The CSRF value is bound to the opaque session with a server-secret HMAC. Cookies are HttpOnly for the session and SameSite Lax; production additionally requires Secure cookies. Local evaluation uses HTTP on localhost. API and provider access logging must exclude callback query strings and invitation tokens; ordinary structured request logs record the route path and safe request identifier.

## Invitation lifecycle

An access manager selects explicit project/resource tuples within the organization's current entitlements. Issuance checks the current manager and writer fence, locks resources in UUID order before the exclusive organization lock, and commits the invitation, resource plan, encrypted outbox payload, audit event and receipt together. A pending invitation for the same normalized recipient produces a conflict rather than a second ambiguous intent.

The ordinary invitation response contains its safe status and deadline. The delivery payload holds a random token; the invitation table holds only its digest. Local delivery links use `/invitations/accept#token=...` so that the secret is not sent to HTTP access logs. The browser removes it from the URL and retains it only in the current tab while sign in completes.

Authenticated preview requires a verified matching recipient claim and provider authentication no older than fifteen minutes. It returns only the selected organization, project and resource labels. It creates no membership or grant. Acceptance repeats this proof and checks current state after ordered locks. It creates or reuses one membership, preserves an existing manager role, adds only the selected explicit grants, consumes the token and writes audit and receipt in one transaction. A suspended or expired member requires a manager decision; an invitation cannot silently restore them.

A matching receipt retry returns the earlier result after the current recipient proof is checked. A consumed token with a new key is unavailable. Resend rotates the token while preserving the reviewed plan and deadline. Revoke terminates the pending invitation. Delivery workers reject stale generations; even an earlier link delivered during a race cannot later grant access.

## Worker and private mailbox

The worker claims at most four eligible messages with `FOR UPDATE SKIP LOCKED`. Claiming commits a random lease token, owner, thirty-second expiry, attempt count and replay generation before adapter work starts. Authorization transitions use ordinary ordered locks; they never use `SKIP LOCKED`.

Immediately before delivery, the worker decrypts the payload and verifies the current pending invitation, token digest and deadline. Acknowledgment compares the durable current owner, token, unexpired lease and generation. A crashed or stale worker cannot finalize a newer lease. Delivery has at least once semantics. The local adapter additionally deduplicates its encrypted receipt by the stable delivery key; this does not claim that an external provider has the same guarantee.

Transient failures use bounded exponential full jitter. Eight attempts or the thirty-minute retry horizon make failure visible. Poison ciphertext, invalidated invitations and permanent rejection become terminal failures. A manager can review a failed readable message for replay; replay keeps the same intent and delivery key, increments its generation, retains cumulative attempts and caps the new horizon at invitation expiry. Purged or expired payloads cannot be replayed.

The protected local mailbox reads encrypted files with restricted permissions and returns at most one hundred messages for the selected organization. Viewer and cross-organization requests are denied. Outbox terminal payloads can be purged after one hour in batches of at most one hundred rows. The encrypted local mailbox has a separate twenty-four-hour retention, also purged in bounded batches. Raw links remain out of ordinary audit, receipts and request logs.

Run one worker batch with:

```sh
backend/.venv/bin/python -m scopegate.cli worker --once
```

The normal local composition runs the same worker continuously. Adapter failures never create membership and never turn pending delivery into a fabricated success.

## Synthetic reconciliation and restore

The local migration input format is explicit, versioned and bounded. Each source element has a stable kind/key, organization mapping, source hash and transformation version. Exact verified identity and project/resource mappings can backfill grants before target ownership. Missing identity, unknown effective baseline, conflicting associations, malformed report references and locale conflicts remain reviewed ledger items. Backfill cannot mutate an organization already owned by target writers. Unchanged input replay does not duplicate target or ledger rows.

The fixtures in [fixtures/migration](../fixtures/migration/) contain both allowed and denied decision tuples. Comparison recomputes target policy on the primary database. Reviewer decisions are versioned and organization-scoped, and never switch authority. The restricted operations CLI requires a separate credential, a disabled unscoped writer assertion, a matching monotonic writer epoch, a current fence, drained high-watermarks, no unresolved or divergent decisions and a durable customer manager before cutover. The contract command checks readiness and performs no destructive cleanup.

Restore is a separately fenced operation. An independent filesystem marker survives a database policy snapshot being restored. Scoped tenant read and mutation routes deny access while that marker exists. Account identification through `/api/v1/me` remains available during containment. Reconciliation checks the reviewed journal digest, reapplies supported grant/member restrictions, prevents unknown additions, revokes restored sessions and pending invitations, purges obsolete outbox secrets and preserves target authority with a monotonic epoch. An uncertain restriction needs an explicit reviewed denial before opening. Unsupported permission operations remain fenced.

The controlled restore rehearsal captures the current catalog publication manifest before restoring older policy rows. A catalog version or terminal archive mismatch blocks opening until the Publisher state is independently reconciled. Local filesystem append with flush and fsync proves the controlled demonstration on one host; it does not establish host-loss durability, production RPO, PITR or a live provider recovery guarantee. The review scope is capped at 128 command files, 32 KB per command and 512 KB total. Larger reconciliation requires a separate bounded operational workflow.

Operational marker creation and its final integrity reread are bounded local control-file work inside the maintenance transaction. This is an explicit exception to keeping network adapter work outside domain locks. A timeout fails closed and leaves the independent marker present. Ordinary request paths only check marker presence; they do not scan a recovery journal.

Restricted CLI operations include `profile`, `backfill`, `compare`, `fence`, `cutover`, `unfence`, `contract`, `restore-fence`, `restore-inspect` and `restore-reconcile`. Supply the operations credential through a restricted `--credential-file` or `SCOPEGATE_OPERATIONS_TOKEN`, never through a command-line secret argument. A web reviewer has no authority to execute these operations. When the product runs through Compose, use the opt-in maintenance container, which shares its actual journal and mailbox volumes:

```sh
docker compose --profile maintenance run --rm --build operations --help
```

Append the commands and flags in [the local operations contract](../specs/contracts/local-operations.json). Synthetic input files are available read-only under `/app/fixtures/migration`. This profile receives only the runtime database credential, outbox key and operations authority. It is not started by `make up`. Host virtualenv commands use host filesystem evidence; they must not be used to reconcile a Compose volume with a different journal directory.

## Verification entry points

[Identity tests](../backend/tests/test_identity.py) exercise PKCE, one-time codes, signature/issuer/audience/nonce checks, freshness, CSRF, rotation and the session row-wait schedules. [Invitation tests](../backend/tests/test_invitations.py) exercise verified-recipient binding, races, receipts, manager preservation and atomic rollback. [Delivery tests](../backend/tests/test_delivery.py) exercise crash recovery, lease compare-and-swap, poison payloads, retry exhaustion, replay, purge and protected delivery evidence. [Migration tests](../backend/tests/test_migration.py) exercise source accounting, exact backfill, deny comparisons, reviewer scope, stale epochs, unapplied deltas and current cutover gates. [Operation tests](../backend/tests/test_operations.py) exercise independent fencing and conservative restore reconciliation.

Executed commands and their limits belong in [Validation](VALIDATION.md); test definitions alone are not execution evidence.
