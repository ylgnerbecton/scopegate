# Scopegate workspace

The browser workspace uses React, TypeScript, Vite, and TanStack Query. It connects to the real HTTP service through one origin; a separate local OpenID Connect provider establishes verified sessions.

Use the repository's root `Makefile` and setup instructions to start PostgreSQL, the service, the identity provider, and the delivery worker. Then run:

```sh
npm ci
npm run dev
```

Open `http://localhost:5187`. Keep the hostname consistent with the configured callback and allowed origin. The development proxy sends `/api`, `/auth`, and `/health` to port 8457. The static Docker image uses an unprivileged nginx server on port 8080.

## Workflows

The interface includes scoped overview and library views, versioned membership and grant changes, explicit invitation plans and verified acceptance, audit inspection, and migration ledger review. Managers can view project entitlements without receiving consumption permission. Every resource opening creates and rechecks a protected report reference.

Organization and project IDs are visible and persisted in the URL. Every scoped server-state key also includes the current principal. Changing organization or project cancels requests and removes departed scope caches. Commands show confirmed responses, use stable idempotency keys after uncertain failures, and require another review after a version conflict. Draft rebasing preserves unrelated competing changes.

The local delivery inbox is a protected, manager-only adapter surface. Invitation secrets move from the URL fragment into tab-scoped storage before sign-in and are removed after acceptance. Provider tokens never enter browser storage. The migration workspace records decisions and exports bounded, versioned decision manifests; cutover belongs to the restricted CLI.

## Verification

```sh
npm run types:check
npm run typecheck
npm run lint
npm run format:check
npm run test
npm run build
npm audit
npm run test:e2e
```

`types:generate` updates HTTP types from the canonical OpenAPI document. `types:check` generates into a temporary directory and fails if tracked types differ. The Vite override keeps the application and test runner on the same audited version.

Unit checks exercise command transport, cancellation, scoped cache identities, and preservation of explicit grant intent. Browser checks require the complete running local stack, including the synthetic expired and failed delivery fixtures created by the root demo setup. macOS uses installed Chrome; Linux uses installed Playwright Chromium. Set `SCOPEGATE_BROWSER_CHANNEL` or `SCOPEGATE_WEB_URL` only when the configured environment matches. Happy paths use actual services. The separately named audit panel failure test injects one HTTP response to verify independent panel recovery. JSON results are written to `../artifacts/browser/results.json` for the evidence collector.

Fonts are bundled for an offline, self-contained UI. Their redistribution licenses ship in `public/licenses/`. Original SVG patterns are implemented in the resource and overview components.

`npm run screenshots` captures actual workspace views into the ignored `../artifacts/browser/screenshots/` directory. It reviews grant and invitation drafts without committing them. For the recipient preview it creates one synthetic invitation through the service and revokes that exact invitation during cleanup. Review the images before copying stable presentation assets into `docs/screenshots/`; browser test gates never overwrite those tracked assets.
