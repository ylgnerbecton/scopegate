"""Explicit local migration and delivery commands with bounded, JSON results."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

from scopegate.config import get_settings
from scopegate.errors import AppError
from scopegate.services import delivery, migration, recovery


def read_json(path: str) -> dict:
    file = Path(path)
    if file.stat().st_size > 2_000_000:
        raise AppError(422, "input_too_large", "The local input exceeds two megabytes.")
    return json.loads(file.read_text())


def authorize_operations(credential_file: str | None) -> None:
    supplied = (
        Path(credential_file).read_text().strip()
        if credential_file
        else os.getenv("SCOPEGATE_OPERATIONS_TOKEN", "")
    )
    if not supplied or not secrets.compare_digest(supplied, get_settings().migration_ops_key):
        raise AppError(
            401, "operations_credential_required", "Provide the separately authorized operations credential."
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Scopegate local operations")
    root.add_argument("--credential-file", help="Restricted file containing the operations credential")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ["profile", "backfill"]:
        command = sub.add_parser(name)
        command.add_argument("--snapshot", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--organization-id", required=True)
    compare.add_argument("--run-id", required=True)
    compare.add_argument("--baseline", required=True)
    fence = sub.add_parser("fence")
    fence.add_argument("--organization-id", required=True)
    fence.add_argument("--run-id", required=True)
    fence.add_argument("--expected-epoch", required=True, type=int)
    fence.add_argument("--baseline-revision", required=True)
    fence.add_argument("--source-high-watermark", required=True, type=int)
    fence.add_argument("--applied-high-watermark", required=True, type=int)
    fence.add_argument("--unscoped-writer-disabled", action="store_true")
    cutover = sub.add_parser("cutover")
    cutover.add_argument("--organization-id", required=True)
    cutover.add_argument("--run-id", required=True)
    cutover.add_argument("--expected-epoch", required=True, type=int)
    cutover.add_argument("--baseline-hash", required=True)
    cutover.add_argument("--target-hash", required=True)
    unfence = sub.add_parser("unfence")
    unfence.add_argument("--organization-id", required=True)
    unfence.add_argument("--expected-epoch", required=True, type=int)
    unfence.add_argument("--reason", required=True)
    contract = sub.add_parser("contract")
    contract.add_argument("--organization-id", required=True)
    contract.add_argument("--run-id", required=True)
    restore_fence = sub.add_parser("restore-fence")
    restore_fence.add_argument("--organization-id", required=True)
    restore_fence.add_argument("--expected-epoch", required=True, type=int)
    restore_inspect = sub.add_parser("restore-inspect")
    restore_inspect.add_argument("--organization-id", required=True)
    restore_reconcile = sub.add_parser("restore-reconcile")
    restore_reconcile.add_argument("--organization-id", required=True)
    restore_reconcile.add_argument("--journal-hash", required=True)
    restore_reconcile.add_argument("--confirmed-denial", action="append", default=[])
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--owner", default=f"worker-{os.getpid()}")
    worker.add_argument("--interval", type=float, default=1)
    return root


def execute(args) -> dict:
    commands = {
        "profile": lambda: migration.profile(read_json(args.snapshot)),
        "backfill": lambda: migration.backfill(read_json(args.snapshot)),
        "compare": lambda: migration.compare(args.run_id, args.organization_id, read_json(args.baseline)),
        "fence": lambda: migration.fence(
            args.organization_id,
            args.run_id,
            args.expected_epoch,
            args.baseline_revision,
            args.source_high_watermark,
            args.applied_high_watermark,
            args.unscoped_writer_disabled,
        ),
        "cutover": lambda: migration.cutover(
            args.organization_id, args.run_id, args.expected_epoch, args.baseline_hash, args.target_hash
        ),
        "unfence": lambda: migration.unfence(args.organization_id, args.expected_epoch, args.reason),
        "contract": lambda: migration.contract_check(args.organization_id, args.run_id),
        "restore-fence": lambda: recovery.begin_restore(args.organization_id, args.expected_epoch),
        "restore-inspect": lambda: recovery.inspect_journal(args.organization_id),
        "restore-reconcile": lambda: recovery.reconcile_restore(
            args.organization_id, args.journal_hash, args.confirmed_denial
        ),
    }
    return commands[args.command]()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "worker":
            if get_settings().environment not in {"local", "test"}:
                raise AppError(503, "local_adapter_restricted")
            if not 0.1 <= args.interval <= 30:
                raise AppError(422, "validation_error", "Worker interval must be between 0.1 and 30 seconds.")
            while True:
                result = delivery.process_batch(args.owner, limit=4)
                if result["claimed"] or args.once:
                    print(json.dumps(result), flush=True)
                if args.once:
                    return 0
                time.sleep(args.interval)
        authorize_operations(args.credential_file)
        print(json.dumps(execute(args), sort_keys=True))
        return 0
    except (AppError, OSError, ValueError) as exc:
        print(
            json.dumps({"error": getattr(exc, "code", "operation_failed"), "message": str(exc)}),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
