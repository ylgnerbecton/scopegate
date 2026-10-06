# Scopegate project charter

Scopegate makes access operations safe enough to change and clear enough to explain. A user can belong to several organizations, each organization can own several projects, and individual access is constrained by the project's licensed resource set.

## Product identity

The name combines scope, the boundary of a permission, with gate, the place where that permission is checked. The repository slug is `scopegate`. The name is a working product identity; commercial trademark and domain clearance are outside the technical design.

Alternative names considered were Permitlane and Scopeport. Scopegate directly communicates controlled access while remaining independent of any source context.

## Required outcomes

The deliverable includes a diagnosis that separates evidence from hypotheses, a compact product proposal, concrete data and system design, a delivery and migration plan, and a product alignment message. The implementation extension adds versioned API and publishing contracts, SQL constraints, acceptance scenarios, a dependency graph, and checks for package consistency. The depth extension adds 27 atomic coverage clauses, 230 engineering decisions, a developer blueprint, transaction schedules, endpoint/connection budgets, lease-based delivery, service objectives, release/recovery protocols and an evidence completion contract.

## Product vocabulary

| Term | Meaning |
| --- | --- |
| Organization | Customer account and access isolation boundary |
| Project | Organization-owned workspace and contracted scope |
| Resource | Stable published catalog object that may have localized metadata |
| Project entitlement | Resource licensed and enabled for one project |
| Membership | Relationship between an identity and one organization |
| Resource grant | Individual permission for one entitled resource in one project |
| Access manager | Scoped operator of memberships and grants |
| Catalog publisher | Service boundary that publishes resource content |

## Implementation status

The local product is implemented with executable migrations, independent OIDC verification, a durable delivery worker, browser journeys and synthetic migration/recovery exercises. Runtime proof is recorded separately from written coverage. See docs/LOCAL_PRODUCT.md for the closed scope; real provider integration and production rollout remain outside this release.
