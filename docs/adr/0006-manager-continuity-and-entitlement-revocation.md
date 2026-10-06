# Durable Manager Continuity and Explicit Revocation

Status: Accepted for implementation

## Context

Counting currently valid managers cannot prove future management continuity when every remaining manager may expire. Separately, changing an entitlement from disabled back to active would restore any earlier grant still stored as active and could make an earlier pending invitation usable again.

## Decision

A target organization retains at least one active customer access manager without expiration. Staff managers and expiring customer managers do not satisfy this durable continuity rule. Customer status changes and platform role or expiry changes enforce the guard under the exclusive organization transaction lock. Bootstrap creates the first durable manager atomically. An audited platform emergency repair has management scope and gives no resource consumption bypass.

Entitlement disable is a revocation operation. Within one bounded transaction, disable the exact organization and project resource, revoke its active grants, increment each changed membership access version once, and revoke every pending invitation containing that pair as a whole. Append audit and receipt atomically. Reenable creates no grants and revives no invitation. New access requires explicit fresh authorization.

The privileged preview provides revision, counts and an impact fingerprint. After locking, recompute the scoped fingerprint and expected revision. Changed impact returns `412`; more than 200 affected memberships, 500 active grants or 200 pending invitations returns `409` before effects. Initial limits require workload validation before pilot. Larger staged disable is outside the first increment.

Resource archive is terminal for its UUID and external key. Catalog publication cannot republish that archived identity or alter tenant grants. Replacement content uses a new stable key and a reviewed entitlement and grant plan.

## Alternatives and consequences

Availability pause preserving old grants is rejected because reenable would restore access without renewed intent. An entitlement generation bound to grants can make very large invalidation efficient, but adds policy, invitation and migration semantics; revisit only after measured fanout requires it. Retaining an expiring manager is insufficient continuity.

The durable owner and irreversible lifecycle semantics are proposed product assumptions. Product and Operations must validate them against intended access before private cutover. The synthetic baseline uses these semantics. Migration cannot silently apply them to incompatible existing organizations.

## Acceptance evidence

Prove two simultaneous manager suspensions, staff expiry after the last durable owner is targeted, stale impact preview, over limit rejection, atomic multi membership disable, whole mixed plan invitation revocation and reenable without restored access. Verify independent organization memberships are unchanged. These are future runtime gates.
