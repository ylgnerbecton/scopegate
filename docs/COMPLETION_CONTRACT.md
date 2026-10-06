# Scopegate completion contract

The written design and a working product have separate completion criteria. `make check` validates the specification package. `make check-evidence` verifies recorded implementation proof and fails whenever proof is absent, stale or unsuccessful. `make verify` produces proof only from actual commands for the current committed revision.

[coverage.json](../specs/coverage.json) maps 27 written-delivery clauses to documents and requirements. [standards.json](../specs/standards.json) maps engineering concepts to decisions, owners, gates and revisit conditions. [execution.json](../specs/execution.json) orders developer tasks and names the runtime gates. [evidence.schema.json](../specs/evidence.schema.json) defines the output required from the release gate runner.

## Recording proof

Commit the implementation revision before running the release gates. The release gate runner executes the canonical commands, preserves actual exit codes, captures tool versions and environment, records UTC start/finish times, and writes sanitized artifacts with SHA-256 digests. It then writes `specs/implementation-evidence.json`. Keep generated artifacts in ignored `artifacts/` during local work; publish reviewed sanitized artifacts as immutable CI attachments for a real release. A CI attestation and protected release job must bind those artifacts to the commit; a hand-written manifest alone does not establish trusted provenance.

Each acceptance scenario references a passing gate and a specific artifact showing the asserted behavior. Each completed task references its required scenarios and a review artifact covering the non-scenario outputs and input gates. A passing lint command cannot certify a grant race or a migration rehearsal. Owners must review the relevance of proof as well as its presence.

The verifier rejects missing, failed, blocked, skipped, stale, empty or digest-mismatched proof. It requires the current committed revision and rejects uncommitted implementation changes. The generated manifest itself may change after the commit. It never executes arbitrary command strings from the manifest. CI runs the canonical command allowlist from the execution contract.

## Stages

| Stage | Required proof | Boundary |
| --- | --- | --- |
| Written design | 27 clauses, 15 standard groups, diagrams, valid contracts, scenario/task coverage | Current package checks; no runtime claims |
| Local product | T00–T12, every scenario, all runtime gates, integrated local identity provider and synthetic migration | `make check-evidence`; complete synthetic product |
| Live pilot | Local proof plus T13, actual identity integration, writer/consumer coverage, private intended baseline, parity and approved recovery | `python3 scripts/check_evidence.py --stage pilot` |
| Controlled live completion | Pilot proof plus T14, cohort observation and delayed legacy contraction | `python3 scripts/check_evidence.py --stage complete` |

Live approvals identify accountable owners and reviewed revision. Public artifacts contain a sanitized approval summary and digest, never raw identities, customer manifests or provider credentials. The private approved manifest remains in the authorized operations store. Public synthetic demonstrations cannot satisfy those approvals.

## Review questions

For each change: does it solve an observed problem with the smallest maintainable mechanism; do tenant boundaries, state transitions and failure behavior stay explicit; is it observable, secure and testable; can it be reversed without restoring revoked access; are dependencies and coupling justified; and do evidence and ownership match the claimed completion stage? Record unresolved answers with an owner and a blocking gate.

## Validator and aggregate gate behavior

The evidence verifier enforces every keyword used by the committed evidence schema through a bounded dependency-free validator. Unsupported schema keywords fail closed. Independent JSON Schema validation checks the schema itself. An invalid schema version, boolean exit code, unknown field, invalid scope or malformed environment cannot become passing proof. Task records match the selected completion stage exactly.

G-RELEASE aggregates the other eleven gates and the applicable input approvals, then emits its own result. It does not invoke itself recursively. After the aggregate completes, the runner writes the final manifest and invokes check-evidence. The completion verifier checks recorded evidence; trusted CI provenance and accountable review establish whether those records came from the required execution.
