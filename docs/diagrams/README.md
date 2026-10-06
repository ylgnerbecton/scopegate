# Scopegate architecture diagrams

Mermaid sources are editable architecture contracts. Their SVG exports provide a readable view without a Mermaid-enabled renderer. The implemented local application follows these boundaries; live adapters remain a separate delivery.

| Subject | Source | Rendered view |
| --- | --- | --- |
| System context | [context.mmd](context.mmd) | [context.svg](context.svg) |
| Runtime containers | [container.mmd](container.mmd) | [container.svg](container.svg) |
| Entity relationships | [er.mmd](er.mmd) | [er.svg](er.svg) |
| Invitation acceptance | [invitation-sequence.mmd](invitation-sequence.mmd) | [invitation-sequence.svg](invitation-sequence.svg) |
| Use and revocation | [grant-revocation.mmd](grant-revocation.mmd) | [grant-revocation.svg](grant-revocation.svg) |
| Migration phases | [migration-phases.mmd](migration-phases.mmd) | [migration-phases.svg](migration-phases.svg) |

The source is authoritative. Regenerate exports after changing it; inspect labels, arrows, and sequence branches before publishing. Exports are rendered with Mermaid CLI 12.0.0. Their validation is recorded in [Validation](../VALIDATION.md).
