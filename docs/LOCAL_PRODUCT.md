# Local product delivery boundary

The deliverable is one complete, reproducible local release. Its scope is closed around organization access management and evidence-backed synthetic operating exercises. A modular monolith uses one primary PostgreSQL authority, a separate local identity provider, a durable delivery worker and a browser workspace.

| Included capability | Concrete implementation |
| --- | --- |
| Verified identity | Code flow, S256 PKCE, state, nonce, RS256/JWKS, issuer/audience and recent authentication; opaque revocable sessions |
| Organization access | Explicit memberships, expiring staff assignments, manager continuity and composite organization foreign keys |
| Project resource access | Publisher catalog, localizations, entitlements, explicit grant diffs and protected report admission |
| Concurrent changes | Canonical locks, post-lock reads and clock, optimistic versions, deterministic receipts and atomic audit |
| Onboarding | Recipient-bound preview, single-use acceptance, selected grants, encrypted durable outbox and protected local mailbox |
| Migration | Synthetic snapshot, element ledger, unknown baseline, reviewed mappings, allow/deny comparison and fenced CLI cutover |
| Workspace | Organization/project switching, localized search, access and invitation dialogs, activity, reconciliation and narrow layouts |
| Operations | Aggregate metrics, redacted traces, alert injection, scoped containment, independent restore markers and revocation reconciliation |
| Delivery | Locked dependencies, reproducible images, runtime/browser gates, public contracts, source archive and review narrative |

No customer endpoint promotes an access manager or provisions a staff assignment. Those assignments belong to trusted administrative integration. Publisher and platform credentials have separate HTTP surfaces; neither produces an implicit consumer grant.

Tasks T00 through T12 define the local delivery. T13 and T14 describe a separately owned live pilot and later legacy contraction. They do not extend the local release into an unbounded production program.

| Outside this release | Required future evidence |
| --- | --- |
| Real identity and notification providers | Actual issuer, revocation integration, recipient policies, quotas and delivery retention |
| Live source transformation | Private snapshots, intended-access baseline and every writer/consumer owner; synthetic fixtures demonstrate the protocol |
| Host-loss recovery | External journal adapter, acknowledgment durability, backup/PITR and a measured host recovery drill |
| Interpretation of conflicting access | A human owner must establish intent; union or intersection can create unintended permission |
| Full production capacity and availability | Approved host resources, larger deployment profile, provider limits and long observation windows |
| Destructive legacy cleanup | The local CLI reports contraction readiness without deleting source tables |

Restore opening is conservative. Supported grant and membership restrictions are reapplied from validated independent evidence. An uncertain addition is never guessed. Unsupported committed operations, a changed catalog manifest or an unresolved outcome retain the fence. The local rehearsal does not claim distributed atomicity or host-loss durability.

The five written outcomes are in [the executive proposal](PROPOSTA.pt-BR.md): diagnosis, architecture, onboarding/access journey, migration, and product alignment. [Coverage](../specs/coverage.json) links their 27 atomic clauses to requirements and documents. Runtime evidence is separate from written coverage.
