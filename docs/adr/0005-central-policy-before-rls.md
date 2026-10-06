# Central Policy before Row Security

Status: Accepted for implementation

## Context

The first deployment has one application boundary responsible for database access. Domain authorization includes membership expiration, project entitlements, explicit grants, management authority and critical use locking. Implementing those rules simultaneously in unverified application and database policies would create two decision sources to maintain.

## Decision

Start with one central application policy, composite tenant foreign keys, scoped repositories and mandatory negative tests. The runtime database role is distinct from the schema owner, with limited DML privileges and no superuser capability. No independent service or analytics client may query tenant tables directly during this stage.

Introduce PostgreSQL row security as defense in depth before allowing multiple independent database consumers. Keep the domain policy authoritative for operation semantics and compare database tenant filtering against it. Add policies through Alembic, measure their query impact and test both `USING` and `WITH CHECK` behavior.

The application role does not own the tables or have `BYPASSRLS`; PostgreSQL owners normally bypass policies, and superusers or `BYPASSRLS` roles bypass them. Future tenant context uses transaction scoped `SET LOCAL`, denies when absent and is tested across pooled connection reuse. See [PostgreSQL row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html). The staged enforcement plan is Scopegate's design decision.

## Alternatives considered

RLS from the first increment would add an independent policy surface before domain semantics and transaction behavior are proven. Application filtering indefinitely would become insufficient when a new consumer can bypass the application. The selected order gives each layer a measurable acceptance gate.

## Consequences

Initial correctness depends on central policy and scoped queries, so G2 is a release blocker. Database constraints prevent invalid relationships but cannot replace read authorization. RLS remains mandatory at the consumer expansion boundary; it is not a claim that the current implementation has database row filtering.

## Acceptance evidence

G2 proves initial isolation. Before a new database consumer is admitted, demonstrate absent context denial, cross tenant denial, write checks, owner privilege separation, connection reuse safety, query plans and backup behavior under the real production role.
