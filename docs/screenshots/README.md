# Workspace captures

These fourteen PNGs show the implemented product using synthetic accounts and data. They are direct browser captures with local fonts loaded and animation disabled. The [README gallery](../../README.md#screenshots) provides captions and full-resolution links. No image editing or replacement interface is used.

## Reproduce safely

Install the development dependencies and the browser described in [validation](../VALIDATION.md), then run from the repository root:

```sh
make setup
make deps
make screenshots
```

[capture_workspace.py](../../scripts/capture_workspace.py) builds a uniquely owned temporary Compose project with fresh credentials and fresh volumes. Only the web and independent identity provider publish loopback ports, defaulting to **5189** and **8902**. These must be available. To use another pair:

```sh
python3 scripts/capture_workspace.py --web-port 5190 --identity-port 8903
```

The temporary deployment does not reset the main workspace. Its expanded configuration is private, created with restrictive permissions and removed afterward. Cleanup verifies ownership before removing the exact project's containers, volumes, network and image tags; it checks that none remain. The helper preserves failures instead of reporting an unsuccessful capture or cleanup as success.

Output appears under ignored `artifacts/browser/captures/scopegate-capture-<owner>/`. The manifest records fourteen filenames, dimensions and SHA-256 values plus cleanup confirmation. Review every image at full resolution before copying approved PNGs into this directory. Capture output is not promoted automatically.

## Recorded states

| Files | Visible state |
| --- | --- |
| 01–02 | Sign-in entry and manager overview |
| 03–04 | Explicitly granted resource library and Portuguese metadata |
| 05–06 | Scoped membership list and a proposed grant addition in review |
| 07–08 | Distinct acceptance/delivery states, protected mailbox and a proposed invitation plan |
| 09 | Committed invitation audit event with expanded details |
| 10–12 | Tablet/mobile overview and mobile library |
| 13 | Verified recipient's selected plan before acceptance |
| 14 | Scoped synthetic migration ledger for an authorized staff reviewer |

[capture-workspace.mjs](../../frontend/scripts/capture-workspace.mjs) signs in through the real local OIDC flow. It creates one actual Morgan invitation, waits for the real delivery worker, reloads confirmed summary/activity and uses that delivered invitation for the recipient preview. Other grant/invitation reviews remain drafts; the created invitation is revoked during cleanup. Contexts and the browser are closed even if revocation fails.

Screenshots establish visible layout and synthetic content at capture time. They do not establish authorization, successful acceptance, race correctness, keyboard reachability or accessibility conformance. The [browser tests](../../frontend/e2e/workspace.spec.ts) and revision-bound [release evidence](../COMPLETION_CONTRACT.md) establish their respective behavioral checks.
