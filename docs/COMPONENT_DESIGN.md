# Workspace component design

This is the implemented React workspace contract. Shared presentation and interaction primitives reduce repeated mechanics; feature modules retain their own business drafts and server commands. The server independently decides permission, version conflicts and committed results. [UX](UX.md) defines user journeys; [architecture](ARCHITECTURE.md) defines application ownership.

## Ownership and composition

| Boundary | Source | Responsibility |
| --- | --- | --- |
| Session and workspace shell | [App.tsx](../frontend/src/App.tsx) | Resolve the authenticated principal, select organization/project, mount the current scoped feature and clear session data on logout |
| Scoped query identity | [workspace.ts](../frontend/src/lib/workspace.ts), [queries.ts](../frontend/src/lib/queries.ts) | Include principal, organization, project, endpoint, filters and cursor in query identity; reset cursor history synchronously when identity changes |
| Transport and command retry | [api.ts](../frontend/src/lib/api.ts) | Generated contract types, cancellation signal, safe typed errors, CSRF headers and command keys bound to endpoint/body |
| Interaction primitives | [ui.tsx](../frontend/src/components/ui.tsx) | Native buttons/dialogs, controlled search, selected choices, status/error panels and headings |
| Bounded pagination | [Pagination.tsx](../frontend/src/components/Pagination.tsx) | Named navigation, disabled pending actions, current-page announcement and previous-page recovery |
| Resource identity artwork | [ResourceVisual.tsx](../frontend/src/components/ResourceVisual.tsx) | Derive decorative SVG variation from the stable resource key; use the same visual in the overview and library |
| Feature decisions | [features](../frontend/src/features/) | Render bounded reads, own draft/review/confirmation state, issue commands and refresh affected queries |

The shared layer accepts values and callbacks; it does not import tenant authorization or issue a grant. A feature's organization/project props determine its endpoint and scoped key. Rendering a management choice does not authorize consumption. The application remounts scoped feature state on workspace changes, while cancellation and separate query identities prevent a departed response from becoming current data.

## Interaction contracts

| Component | Contract | Important edge |
| --- | --- | --- |
| `ChoiceGroup<T>` | A labeled group of native buttons with `aria-pressed`, controlled `value`, options and `onChange` | A scope choice and layout choice are separate groups; selecting the management collection displays an explicit access explanation |
| `SearchBox` | Controlled input with a unique associated label; an explicit clear button restores input focus | Clear uses `type="button"`, disappears for an empty value and cannot submit an enclosing form |
| `Dialog` | Native modal, unique title/description IDs, Escape dismissal and trigger focus restoration | Selection, review and conflict belong to the feature; a modal is not a second permission system |
| `Button` | Native action with explicit pending/disabled behavior | Pending commands cannot be accidentally submitted again through the visible control |
| `Pagination` | Named navigation with live page text; no invented total; at most 25 results per request | Keep it mounted on empty/error later pages so Previous remains reachable after fetching stops |
| `Loading`, `Empty`, `ErrorPanel`, `Notice` | Separate loading, absence, recoverable failure and status semantics | A panel failure does not replace independent successful panels or silently resemble an empty collection |
| `ResourceVisual` | Decorative, stable-key artwork without authorization meaning | Reordering or filtering cards keeps the same resource visual; labels and stable keys convey identity as text |

Typography, text contrast, visible focus and touch spacing are defined in [styles.css](../frontend/src/styles.css). Presentation uses the existing visual vocabulary and font assets. Resource descriptions are rendered only when returned by the API; absent content is not replaced with invented catalog text. Overview counts describe a bounded loaded sample when a next page exists, rather than claiming an exact global count.

## Server state and cursor protocol

`usePagedQuery` stores a cursor stack for one hashed query identity. Equal filter objects preserve the page regardless of property order. A changed endpoint, principal/scope key or filter returns to page one before an old cursor can be sent. Query functions pass the cancellation signal to the real HTTP reader. Previous never removes the first cursor; Next ignores a pending read, missing/repeated cursor or an already advanced captured page. The server also validates cursor scope and aggregate versions.

Grid/list switches change presentation, so they do not reset a valid data page. Search, locale and granted/entitled changes affect the server collection, so they reset pagination. An empty later page explains that the collection may have changed and retains Previous. A failed later page retains both its retry and previous-page controls once pending work ends. No component manufactures a total from a cursor page.

## Feature state transitions

| Feature | State path | Authority and recovery |
| --- | --- | --- |
| Overview | Independently loading panels → data, empty or failure | Retry only the failed panel; bounded summaries identify their sample boundary |
| Resources | Scoped list → selected resource → pending protected admission → confirmed/error | Protected report creation and read recheck current server permission; denial refreshes the collection |
| Membership grants | Current version → draft → reviewed diff → pending → confirmed | Removals need confirmation; 412 preserves intended selection and requires another review against the competing version |
| Invitations | Recipient/plan draft → review → committed pending invitation → delivery updates | Acceptance and delivery state remain separate; a successful email adapter cannot accept a token |
| Recipient | Verified preview → accept command → accepted result | Recipient-bound recent verified claims and single-use state are checked by the server |
| Migration | Read ledger → evidence draft → reviewed decision → committed version | Conflict preserves evidence; an explicit replacement acknowledgment is required; the browser cannot cut over authority |
| Audit | Bounded events → optional details/filter → next/previous page | Historical evidence remains readable; action filtering does not imply an implemented target or time-range filter |

See [Members](../frontend/src/features/Members.tsx), [Invitations](../frontend/src/features/Invitations.tsx), [Resources](../frontend/src/features/Resources.tsx), [Migration](../frontend/src/features/Migration.tsx), [Overview](../frontend/src/features/Overview.tsx) and [Activity](../frontend/src/features/Activity.tsx). These modules share interaction primitives and command helpers while retaining distinct lifecycle rules.

## Verification and limits

[Control tests](../frontend/src/components/ui.test.tsx) check controlled search/focus, pressed choices, pending pagination and unique dialog associations. [Cursor tests](../frontend/src/lib/queries.test.tsx) cover repeated activation, identity/filter resets, late departed responses, empty-page recovery and repeated cursors. [Resource panel tests](../frontend/src/features/Resources.test.tsx) exercise real feature composition with empty/failed later pages, collection-specific copy and search reset.

[Browser journeys](../frontend/e2e/workspace.spec.ts) exercise the real deployed services, competing commands, panel fault injection, tenant switching and keyboard-only operations at 375, 768 and 1440 pixels. Unrestricted tagged accessibility scans cover visible page and dialog states. [Validation](VALIDATION.md) defines how to check their actual results at the current revision. Unit fixtures isolate interaction mechanics; they do not certify server authorization. Automated scans do not replace a recorded human screen-reader walkthrough. Screenshots provide visual evidence, separately from the executed behavior.
