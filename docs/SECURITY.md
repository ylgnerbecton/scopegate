# Scopegate Security

Scopegate treats organization isolation and resource authorization as product invariants. A valid identity does not imply membership, a membership does not imply resource access, and an access management role does not imply consumption. Implementation must pass the security gates in [Quality](QUALITY.md) before a tenant pilot.

## Assets and trust boundaries

Protected assets are organization data, membership state, resource grants, report configuration and output, invitation tokens, sessions, delivery payloads and audit events. The browser is untrusted. Path identifiers, request bodies, cookies, locale values and client permission hints require server validation. The identity provider establishes identity; the database establishes current organization access. Catalog Publisher credentials and platform operations credentials form separate privileged boundaries with narrowly defined operations.

| Threat | Enforcement |
| --- | --- |
| Guessed cross organization identifiers | Scoped policy queries, composite tenant foreign keys and concealed object responses |
| Privilege escalation through access editing | Manager scope checks, immutable operation allowlist, version checks and last manager protection |
| Revoked access used by an in flight report | Shared organization lock for critical use and exclusive lock for authorization mutation |
| Forwarded or replayed invitation | Token digest, verified email binding, expiration and one atomic acceptance transition |
| Stale browser data after organization switching | Tenant and principal query keys, request cancellation and cache reset |
| Sensitive state in logs or delivery | Redaction, encrypted sensitive outbox payload, minimal retention and restricted adapter access |
| Unauthorized global catalog mutation | Separate machine credential, allowlisted writes and Publisher audit |
| Audit removal by the application | Append only application privileges and same transaction durability |

## Authentication and sessions

The production adapter uses OIDC Authorization Code with PKCE and an allowlisted issuer and callback URL. It validates state, nonce, token signature, issuer, audience, expiration and authorized party when applicable. Discovery and key refresh must not accept arbitrary URLs supplied by the browser. Provider failure denies authentication. A real provider and callback integration is a pilot prerequisite; fake identity headers are prohibited.

User identity is the immutable unique issuer and subject pair. An email change updates contact information after provider verification and never rebinds identity or merges accounts. OIDC defines the subject within its issuer and separately defines `email_verified`; Scopegate's invitation binding uses those distinct claims. See [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html).

The same origin web session uses an opaque identifier backed by the `sessions` table. Production cookies are `Secure`, `HttpOnly` and appropriately `SameSite`; mutation requests require CSRF protection and origin validation. Session rotation follows authentication and any sensitive session transition. Server side expiration and revocation remain authoritative. Browser storage does not hold provider refresh tokens or invitation tokens. CORS uses an explicit origin allowlist.

The session stores validated `verified_email` and `email_verified` claims, the provider authentication time in `authenticated_at`, and the server validation time in `claims_verified_at`. `users.email` remains contact data and cannot prove invitation ownership. Invitation preview and acceptance require a verified matching session claim and provider authentication no older than 15 minutes. Request OIDC `max_age=900` when reauthentication is needed and validate the returned `auth_time`; a callback timestamp cannot replace provider authentication time. Missing required claims or a provider unable to satisfy this freshness policy denies the sensitive action. Recheck freshness after lock waits, and retry with the same idempotency key after successful reauthentication.

The local adapter is permitted only in named development and test environments with synthetic users. The production configuration validator rejects it, regardless of route or environment defaults. Tests must demonstrate this failure mode.

## Authorization contract

The central policy denies unless all required relationships are present and active. Every HTTP operation, list, count, search, report execution and export uses that policy. This follows OWASP's guidance to deny by default and validate permissions on every request; the particular Scopegate relationship model is our design. See [OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

Consumption requires an active organization and project, active unexpired organization membership, active project entitlement, published resource and explicit active grant for the exact project resource. Staff has the same requirement and a mandatory expiration. Managers can grant or revoke only within active organization entitlements, cannot promote or create managers, and cannot remove the last active non-expiring customer manager. Staff managers do not count toward continuity. Staff and manager provisioning belong to controlled platform operations with audit and a reason, rather than customer API parameters.

An inaccessible object receives `404`. `403` is used only when an organization is already visible to the actor and the required role is missing. Neither response identifies hidden objects. Inputs cannot override organization ownership, membership kind, role or creator fields through mass assignment. DTOs allowlist editable fields.

Migration review is a separate tenant capability. A reviewer must have an active unexpired `staff` membership, the `access_manager` role and a platform assigned `can_review_migration` flag for that organization. Ordinary customer managers and unflagged staff cannot read private source references, resolve exceptions or export manifests. Customer commands cannot assign the flag. Web review scopes summaries, records, decisions and exports to that membership; fence, reconciliation and cutover commands use the separately authorized operations CLI with explicit organization and manifest inputs. Review authority never grants resource consumption or bypasses the cutover gates.

## Tokens and delivery

Invitation tokens are cryptographically random, bounded in lifetime and stored as digests in invitation records. Authenticated preview verifies the recent session email claim before disclosing the organization and selected resource plan, and creates no membership or grants. Acceptance repeats that binding and follows the ordered locks. After current session and recipient checks, a matching actor scoped receipt may return the original result without repeating acceptance. A new request still requires a pending unexpired invitation; invalid, revoked, consumed and expired tokens fail without exposing the target's private data. Rate limits protect token verification and invitation issuance. Tokens never enter logs, analytics, query caches or audit payloads.

The durable outbox contains only the delivery data the adapter needs. A payload containing a raw invitation link is encrypted at rest with a key outside the database dump, access restricted, and purged under a bounded retention policy after delivery or expiration while retaining safe delivery status. The development adapter writes synthetic delivery evidence and cannot send external messages. The delivery integration must redact links, use transport encryption and preserve bounded retry behavior. It must not create membership before acceptance or report success before the creation transaction commits.

## Transactions and audit

Resource rows, organization advisory locks and membership row locks follow the order in [Architecture](ARCHITECTURE.md). Policy is recomputed after waits using an authoritative clock. Mutation checks a membership version and computes a grant difference. A concurrency conflict or timeout rolls back the entire operation; a retry never bypasses policy.

Access changes, invitation acceptance and critical report output include audit evidence in the same transaction. Events record operation, actor, organization, target identifiers, safe before and after state, reason, request identifier and occurrence time. They exclude tokens, secrets, contact message content and complete resource payloads. Application database credentials can insert and read authorized audit records but cannot update or delete them. Database owners still have broader powers; stronger production tamper resistance requires separate immutable export and operational access controls.

## Database isolation and privileges

Composite organization foreign keys protect relational integrity independently of HTTP validation. The application database role is distinct from the migration owner and has no superuser or DDL permission. Publisher writes are restricted to catalog operations at the service boundary; its database capability cannot change grants. No customer endpoint accepts raw SQL or arbitrary query expressions.

The initial implementation uses central policy enforcement. Before a second independent database consumer is admitted, add and verify row security as defense in depth. PostgreSQL owners normally bypass row security, and superuser or `BYPASSRLS` roles bypass it; a production application role must have neither privilege nor table ownership. Future tenant context uses transaction scoped `SET LOCAL`, fails closed when unset, and is tested under connection reuse. See [PostgreSQL row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html). This rollout ordering is a Scopegate decision, not a guarantee supplied by PostgreSQL.

## Input and output controls

Use parameterized SQLAlchemy statements, bounded pagination and constrained sort and filter fields. Validate identifiers and payload sizes before allocating large work. Escape localized labels and user supplied text. Structured report references carry organization and project relationships; opaque JSON cannot hide unvalidated resource references. Every export reauthorizes each referenced resource at creation and delivery boundaries. Sensitive responses use appropriate cache controls.

Dependency and container scanning, secret scanning and locked dependency installation must run in the application CI once the foundation milestone exists. The specification workflow checks package integrity; runtime gates execute locked dependency audits, privilege tests and threat scenarios. Selected live hosting and final image security require their own measured evidence. Critical or high findings block release unless a documented, time bounded exception identifies owner, exposure, compensating control and expiration. No secrets or private production exports belong in repository fixtures.

## Reporting a vulnerability

Use the repository owner's private contact channel or the hosting platform's private vulnerability reporting capability when enabled. Include affected version, minimal synthetic reproduction and impact. Do not publish tokens, personal information or another organization's data in a public issue. Triage assigns an owner, preserves evidence, contains exposure, fixes the shared rule and adds a regression scenario before closing the report.
