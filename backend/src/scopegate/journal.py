"""Independent synthetic append journal used for the local restore rehearsal."""

import fcntl
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from prometheus_client import Counter

from scopegate.config import get_settings
from scopegate.errors import AppError

FAILURES = Counter("scopegate_journal_failures_total", "Independent command journal I/O failures", ["phase"])
logger = logging.getLogger("scopegate.journal")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        pending = memoryview(canonical(record) + b"\n")
        while pending:
            written = os.write(descriptor, pending)
            if written == 0:
                raise OSError("The independent journal write made no progress.")
            pending = pending[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(actor_key: str, organization_id: str, operation: str, key: str, payload: dict,
            safe_delta: dict | None = None) -> str:
    binding = {"actor": actor_key, "organization": organization_id, "operation": operation, "key": key}
    reference = hashlib.sha256(canonical(binding)).hexdigest()
    record = {**binding, "reference": reference, "request_hash": hashlib.sha256(canonical(payload)).hexdigest(),
              "phase": "prepared", "at": datetime.now(UTC).isoformat(),
              "delta": safe_delta if safe_delta is not None else {"input_hash": hashlib.sha256(canonical(payload)).hexdigest()}}
    try:
        directory = get_settings().journal_directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f"{reference}.jsonl"
        with path.open("a+", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            first = stream.readline()
            if first:
                prior = json.loads(first)
                if prior["request_hash"] != record["request_hash"]:
                    raise AppError(409, "idempotency_conflict", "The command key was used for different input.")
            else:
                stream.write(canonical(record).decode() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                _sync_directory(directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        FAILURES.labels("prepared").inc()
        logger.error("journal_prepare_unavailable", extra={"journal_reference": reference})
        raise AppError(503, "journal_unavailable", "The independent command journal is unavailable.") from error
    return reference


def outcome(reference: str, status: str, response: dict) -> None:
    try:
        append(get_settings().journal_directory / f"{reference}.jsonl", {
            "reference": reference, "phase": status, "at": datetime.now(UTC).isoformat(),
            "response_hash": hashlib.sha256(canonical(response)).hexdigest(),
        })
    except OSError as error:
        FAILURES.labels(status).inc()
        logger.error("journal_outcome_uncertain", extra={"journal_reference": reference, "phase": status})
        raise AppError(
            503,
            "journal_outcome_uncertain",
            "The command outcome could not be confirmed. Retry with the same command key.",
        ) from error
