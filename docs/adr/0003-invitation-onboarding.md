# Authenticated Invitation Acceptance

Status: Accepted for implementation

## Context

An invitation may reach a new user, an existing user or an existing organization member. Delivery is asynchronous and a link may be forwarded or retried. Creating membership at issuance would grant access before identity is established.

## Decision

Issuance validates the sender's manager authority and every requested project entitlement. One transaction creates a pending invitation with a bounded token digest, normalized resource references, audit event and delivery outbox item. A delivery adapter sends the sensitive link after commit; the application does not implement an SMTP service.

Acceptance requires an authenticated OIDC principal with a provider verified email matching the invitation's canonical email. Identity remains the immutable unique issuer and subject pair. Email binding verifies the intended invitation recipient; it never merges identities.

The service locks affected resources, authorization state and the invitation, recomputes expiration after waiting, and revalidates entitlements. It reuses the existing user and unique organization membership. A suspended membership is not automatically reactivated, and an existing manager is not downgraded. Membership changes, explicit grants, accepted state and audit commit atomically. A replay cannot grant access again.

Stored states are pending, accepted and revoked. Expired is an effective state derived from the authoritative clock while pending. Cleanup is an operational concern rather than an authorization dependency. Retry handling returns no other actor's result and cannot repeat the state transition.

## Alternatives considered

Token possession alone would make a forwarded link sufficient authority. Provisioning at issuance would grant before acceptance. Linking users by email would conflate contact data with durable identity. A synchronous delivery call in the transaction would couple database consistency to an external service.

## Consequences

A real OIDC provider integration is required before a tenant pilot. The invitation flow has an additional authentication step, while identity reuse and explicit grants preserve a consistent access model. Sensitive outbox payloads require encryption, restricted access and short retention. A failed delivery can be retried without undoing the committed invitation.

## Acceptance evidence

G3 covers simultaneous acceptance, replay, expiry, atomic rollback and delivery retries. G4 proves the real provider flow and production rejection of the local adapter. See [Invitation sequence](../diagrams/invitation-sequence.mmd).
