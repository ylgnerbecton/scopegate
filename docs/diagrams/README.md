# Scopegate architecture diagrams

Eight source-backed views describe the same product at different levels. Mermaid sources are editable; SVG exports provide a readable review without requiring a Mermaid renderer. Sources and exports must change together. [Architecture](../ARCHITECTURE.md) defines scope and operating guarantees; [canonical SQL](../../specs/contracts/schema.sql) defines the complete model.

| View | What to read | Source | Rendered view |
| --- | --- | --- | --- |
| System context | People, machine actors and separate identity/delivery/recovery authority | [context.mmd](context.mmd) | [context.svg](context.svg) |
| Logical application boundaries | Application, primary authority and implemented local integration boundaries | [container.mmd](container.mmd) | [container.svg](container.svg) |
| Implemented components | Actual transport, cohesive services, pure policy and shared transaction helpers | [components.mmd](components.mmd) | [components.svg](components.svg) |
| Local deployment | Five running services, two API processes, lifecycle jobs, credential scopes and volumes | [deployment.mmd](deployment.mmd) | [deployment.svg](deployment.svg) |
| Entity relationships | All 21 domain/supporting entities with selected keys and lifecycle columns | [er.mmd](er.mmd) | [er.svg](er.svg) |
| Invitation acceptance | Committed outbox delivery and verified single-use acceptance | [invitation-sequence.mmd](invitation-sequence.mmd) | [invitation-sequence.svg](invitation-sequence.svg) |
| Use and revocation | Commit-ordered protected admission, exclusive revocation and fresh reads | [grant-revocation.mmd](grant-revocation.mmd) | [grant-revocation.svg](grant-revocation.svg) |
| Migration phases | Reviewed mapping, fencing, target authority and compatible rollback | [migration-phases.mmd](migration-phases.mmd) | [migration-phases.svg](migration-phases.svg) |

## Reading boundaries

- Context and logical boxes describe responsibilities, not independently deployed domain services. The deployment view alone shows the concrete Compose topology.
- Solid arrows in flowcharts show calls, data movement or storage attachment as labeled; dashed arrows show lifecycle ordering, diagnostic context or a reserved mount as labeled. The diagrams do not imply distributed atomic commit.
- Local OIDC, mailbox and journal adapters are implemented. Real provider/host integration and monitored cohorts need separate delivery. Journal storage is outside the recovered database volume but shares the Docker host.
- The ER covers every table with selected columns. Composite foreign keys contain organization/project scope; some actor/reviewer provenance edges are omitted to preserve legibility. The SQL contract contains the complete physical detail.
- Sequence branches describe observable outcomes and the required transaction order. A rendered diagram is documentation; actual race, provider, browser and recovery gates establish behavior.

## Reproduce the exports

Exports use Mermaid CLI **12.0.0** with the committed [render configuration](mermaid-config.json). Node.js and a browser supported by Puppeteer are prerequisites. From the repository root:

```sh
npx --yes --package @mermaid-js/mermaid-cli@12.0.0 mmdc \
  --input docs/diagrams/deployment.mmd \
  --output docs/diagrams/deployment.svg \
  --configFile docs/diagrams/mermaid-config.json \
  --backgroundColor white --size 1600
```

Repeat for a changed source, keeping its SVG basename. A host with an already installed browser can pass `--puppeteerConfigFile` containing its Puppeteer launch options; host-specific paths do not belong in the public package. Render every changed source, open its export at full resolution and inspect node labels, edge labels, relationship endpoints and branch text. Check that no text overlaps or leaves the SVG viewBox. The complete ER is intended for its full-size view rather than as a thumbnail.

Maintain source links when names change. Deployment claims must agree with `compose.yaml`; component names must resolve to the actual source; entity names and displayed columns must match canonical SQL. [Validation](../VALIDATION.md) owns release proof, separately from this visual review.
