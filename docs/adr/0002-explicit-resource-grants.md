# Explicit Grants within Project Entitlements

Status: Accepted for implementation

## Context

An organization can have several projects and a resource can appear in more than one project. Organization membership and access management authority must not silently permit consumption of every entitled resource.

## Decision

Represent catalog availability with `project_resources` and individual consumption authority with `resource_grants`. The complete decision requires an active organization, active unexpired membership, active project in the same organization, active project entitlement, published resource and explicit active grant for the exact membership and project resource.

Use `viewer` and `access_manager` roles to govern management operations. An access manager remains subject to explicit consumption grants. Staff uses the same relationship model with a mandatory membership expiration. Staff and manager provisioning belong to a controlled platform operations path without a global consumption bypass.

Composite organization foreign keys protect tenant relationships. Central policy scopes every operation, including counts and exports. Inaccessible objects yield `404`; visible organizations with insufficient role yield `403`. Managers cannot promote or create managers or remove the last active manager.

Grant edits compute a difference instead of replacing all records. Version checks, membership row locks and organization advisory transaction locks prevent lost updates. Critical use shares the organization lock; revocation takes it exclusively. Resource row locks serialize Publisher archival with use. The lock order and clock recomputation are defined in [Architecture](../ARCHITECTURE.md).

## Alternatives considered

An organization wide role alone is simple but cannot express per project consumption. A resource list embedded in a membership JSON field weakens relational integrity, audit differences and reference validation. Duplicating authorization predicates in each route makes omissions likely.

## Consequences

Authorization queries join several relationships and need appropriate indexes. Access management and consumption remain independent and explainable. Shared resource identifiers do not erase project boundaries. An already committed report remains valid historical output; revocation blocks future critical use according to commit ordering.

These relationship and locking choices are Scopegate design decisions. They apply OWASP's deny by default and per request verification guidance without treating roles as a substitute for resource relationships. See [OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

## Acceptance evidence

G2 covers tenant leakage and every predicate. G3 proves concurrent updates, revocation ordering, expiration after waits and last manager protection with PostgreSQL connections.
