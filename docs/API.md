# Scopegate API and publisher contract

The HTTP contract exposes access administration through organization and project boundaries. [openapi.json](../specs/contracts/openapi.json) defines the canonical HTTP surface implemented by the local product. [Implementation map](IMPLEMENTATION_MAP.md) identifies its source; executed checks and their limits belong in [Validation](VALIDATION.md). Live adapters remain outside this release.

## Authentication and authority

Browser requests use an opaque, server-side session created through OpenID Connect authorization code flow with PKCE. The API validates the provider issuer, audience, signature, state, nonce, and token time bounds before identifying the user. Unsafe cookie requests also require an origin check and a session-bound CSRF token. Provider tokens are not stored in browser local storage. [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html).

The provider and existing consuming application integration must be confirmed and tested before the pilot. The local test adapter is available only in an explicitly local environment; deployment refuses to start with that adapter outside local development.

Three authorities remain distinct:

| Authority | Surface | Boundary |
| --- | --- | --- |
| Authenticated user | Membership-scoped organization workspace | Management role does not confer resource use |
| Catalog publisher | `PUT /api/v1/catalog/resources/{external_key}` | Catalog content only; no customer membership or entitlement mutation |
| Platform operations | Organization bootstrap and project entitlement commands | Explicit administrative provisioning; no implicit consumer access |

The local application uses separate generated opaque bearer credentials for platform and catalog authorities, compared in constant time and restricted to their respective HTTP surfaces. They are never accepted as a customer session. Issuer, audience, subject and scope validation for live machine credentials requires the separately reviewed production integration. Organization bootstrap creates the organization and its first access manager atomically from an already verified user ID. Staff assignments and manager promotion require a separate privileged operations workflow with a reason and an audit record; ordinary managers cannot invoke it.

## HTTP behavior

- Lists use an opaque cursor and `limit` from 1 to 100, default 25. Cursor binds organization, project, view, locale, search, and sort; mismatched or malformed cursors return 422. Stable ordering has a UUID tie-breaker.
- Objects outside the actor's account return 404 without revealing existence. An actor with known membership and insufficient management authority receives 403.
- `If-Match: "v7"` supplies a membership access version for grant diffs and membership status changes, or the ledger review version for a migration resolution. Missing required headers fail validation; a stale version returns 412 and prompts a refresh.
- State-changing commands require `Idempotency-Key` of 8 to 128 characters. Receipts bind actor, organization, operation, route target, request body, and expected version. Reusing a key with different input returns 409. Matching input returns the recorded result after current authentication and authority are checked. Successful receipts are retained at least 24 hours; the client must not retry with a new key after an uncertain commit.
- Logout is idempotent through session revocation and does not require a tenant command receipt. Publisher upserts use external key plus expected catalog version and request fingerprint. Bootstrap receipts are scoped to the UUID supplied in the privileged creation request. These commands do not misuse tenant grant receipt storage.
- Validation uses 422; state conflict and token replay use 409; a token known to be expired or revoked uses 410 only after recipient verification, so anonymous requests cannot enumerate invitation state. Unexpected internal failures return 500; unavailable dependencies, exhausted pools and bounded lock waits return 503. Both carry a correlation ID without SQL or a stack trace. Rate limits return 429 with `Retry-After`; temporary overload may return 503 with the same retry hint. Unsafe retries preserve the original idempotency key.

The contract's broad error responses define allowable classes, not permission to reveal data. Specific service tests must prove the concealment rule.

```json
{
  "error": {
    "code": "access_version_conflict",
    "message": "Access changed while you were editing. Refresh and review the current grants.",
    "correlation_id": "00000000-0000-4000-8000-000000000001",
    "fields": {}
  }
}
```

Stable codes include `organization_not_found`, `membership_not_found`, `permission_denied`, `access_version_conflict`, `entitlement_inactive`, `grant_not_entitled`, `invitation_unavailable`, `invitation_expired`, `invitation_already_used`, `idempotency_conflict`, `catalog_version_conflict`, `last_manager_required`, `validation_error`, and `temporarily_unavailable`. Tests assert codes and semantics, not translated message text.

## Access commands

`PATCH /organizations/{organization_id}/memberships/{membership_id}/projects/{project_id}/grants` accepts an explicit delta:

```json
{
  "add": ["00000000-0000-4000-8000-000000000101"],
  "remove": ["00000000-0000-4000-8000-000000000102"],
  "reason": "Align access with the approved project assignment"
}
```

The service checks disjoint lists, batch bounds, actor authority, organization ownership, project entitlement, and membership version after acquiring locks. Grant reads are cursor-paginated with at most 100 items and a cursor bound to the access version; a changed version returns 412. Mutation returns only `changed_grants`, at most 200 entries, plus the new access version. It does not return an unbounded grant inventory. It changes only this membership/project, increments the access version on a changed command, and writes grants, audit, and receipt in one transaction. A duplicate or no-op cannot create another access transition. Account switching and parallel edits cannot affect another membership.

Membership suspension uses the same organization lock and version. Suspending the last active customer access manager without expiry fails with 409; staff managers do not count toward this invariant. Re-enabling a member does not create grants or resurrect independently revoked grants.

`POST /organizations/{organization_id}/access-decisions` evaluates only the current actor. Before returning a reason, the service applies visibility: the actor must already be permitted to discover that resource through a consumer grant or a management entitlement view. Unknown, foreign, and invisible ungranted IDs share 404. The result helps explain a denied journey for already visible objects; consumers must recheck at the actual use boundary. It is not a reusable authorization token.

## Invitations and delivery

Creating an invitation captures viewer role, recipient address, selected project/resource pairs, and expiry. The server generates at least 256 bits of randomness, stores only its hash in the invitation, and writes an encrypted delivery payload to the same database outbox. Clear tokens never appear in logs, audit, API responses, or ordinary list pages. The local delivery adapter exposes messages only in the protected local environment.

Acceptance requires a valid server session with a trusted verified email snapshot matching the recipient and authentication within 15 minutes. Store verified email, `email_verified`, and authentication/claim verification times in the server session after validating provider claims; mutable user contact email is not verification. Request OIDC `max_age=900` and validate `auth_time` on reauthentication. It atomically consumes the invitation, reuses the issuer/subject identity and existing membership, applies the reviewed grant plan, and writes audit. Do not downgrade an existing manager or reactivate a suspended member implicitly; that state conflict needs a manager's explicit action. A disabled entitlement or archived resource since issuance stops acceptance with a visible reviewable conflict; no partial membership/grant commit occurs.

An authenticated `POST /invitations/preview` verifies the token, recipient snapshot, freshness, organization state, and pending/expiry status before returning the organization and intended project/resource labels. This permits the invited recipient to review only targeted non-content metadata before membership exists. It consumes no token, creates no grant, and reveals no unrelated resources.

Resend revokes the old token and creates a new invitation/outbox message atomically. Delivery is at least once: the sender uses a stable delivery key, records attempt/outcome, retries bounded failures, and does not mark the invitation accepted based on delivery. A delayed delivery may contain an expired token, which acceptance rejects. The delivery adapter retrieves secrets from an environment key store and deletes ciphertext after its approved retention period.

## Search and partial reads

`GET /organizations/{organization_id}/projects/{project_id}/resources` searches a tenant-owned entitlement relation. Its default `view=granted` returns only resources the current actor may consume. `view=entitled` is restricted to access managers and is used to assign permissions. Neither view exposes the global catalog. `q` matches literal external key or localized title case-insensitively, with `%` and `_` escaped. `locale` is validated, with fallback metadata explicit in the response.

Organization metadata, members, resources, and audit load through separate bounded endpoints. A metadata or translation failure produces a recoverable panel error rather than making the whole organization inaccessible. Authorization failure never becomes a permissive fallback.

## Catalog publication

The publisher sends a stable external key, expected current version, strictly greater new version, lifecycle status, and keyed localizations. Unknown keys require expected version 0. Existing keys require the current version and reject stale updates with 409. A repeated identical publication returns its original result; a new version with changed data is a new publication. A reused external key can never be rebound to a different resource identity. Archival is terminal: an archived key cannot return to published. A replacement needs a new stable key and fresh reviewed entitlements and grants.

Publication owns content only. It may update several languages atomically but cannot write project entitlement, membership, grant, or customer report state. Omitted localizations remain; nullable metadata can be cleared explicitly. Publisher archival uses the resource lock described in [Data model](DATA_MODEL.md), so resource use cannot commit against an archival transition it should observe.

## Report references

Creating a report configuration validates every referenced resource through the current actor's full policy, holds the shared organization lock, and persists configuration and normalized references together. Fetching a configuration checks current membership and every contained resource grant; a saved reference is never authorization. Existing report rendering remains outside this redesign, but its server must use the same authority or a compatible enforcement adapter before cutover.

## Contract evolution

Generate client types from the OpenAPI contract at foundation. API implementation must produce a compatible generated contract, with changes reviewed alongside acceptance scenarios. Additive nullable fields may evolve within v1; changes to meaning, authority, or required inputs require a decision record and compatibility plan. Keep examples synthetic.

## Migration review and operational commands

The web workbench uses bounded organization-scoped migration run, ledger item, and manifest endpoints. A reviewer must have an active, unexpired staff membership with `access_manager` role and explicit `can_review_migration` capability provisioned by platform operations. Customer managers and ordinary staff cannot see source locators, manifests, or review commands. Every response and export is scoped to that organization.

A ledger resolution requires its review version, idempotency key, decision reason, and an assigned reviewer where applicable. The service verifies target mappings, ownership, and required Product/contract-owner approvals. Recording a review does not mutate live grants or switch authority. Recompute candidates and parity after a decision; do not copy a reviewer-provided target ID into active access without validated transformation.

Manifest export is paginated against an immutable run/revision and authorizes every page. The cursor binds that revision; changed evidence invalidates the cursor. Null baseline/target decisions are unresolved mismatches, not implicit denial. No raw tokens or catalog content are exported.

Profile, backfill, comparison, fencing, cutover, unfencing and non-destructive contraction readiness are implemented local CLI operations in [local-operations.json](../specs/contracts/local-operations.json). [Identity and delivery](IDENTITY_AND_DELIVERY.md#synthetic-reconciliation-and-restore) documents their entrypoint and maintenance container. The web interface records decisions and displays their results; comparison and authority changes use the separately authorized CLI and cannot bypass cutover gates. [migration-cli.json](../specs/contracts/migration-cli.json) remains the future live integration blueprint with private input and approval requirements; it does not describe the installed local argument format or certify a live migration.

## Reviewed entitlement transitions

Platform operators use `GET /organizations/{organization_id}/projects/{project_id}/entitlements/{resource_id}/impact?desired_status=disabled` before changing contract availability. A missing entitlement has revision zero. `PUT` requires the returned impact token, a reason, `If-Match` for that entitlement revision and an idempotency key. Revision or fingerprint mismatch returns 412. Initial fanout caps are 200 memberships, 500 active grants and 200 pending invitations; a larger transition returns 409 `entitlement_impact_too_large` without writes and needs an approved bounded redesign.

The disabled transition revokes exact-pair grants and whole affected pending invitations atomically, advances each changed membership once, and audits the counts. Re-enabling creates no grants or invitations. Matching committed receipts are returned after current platform authority, before evaluating a stale preview; conflicting fingerprints return 409. This ordering allows a successful command to be retried after its own version change.
