"""Run two owned application artifacts against one isolated, compatible test database."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url

CONTRACTS = ("specs/contracts/schema.sql", "specs/contracts/openapi.json")


def command(root, arguments, *, timeout=60):
    proxy = shutil.which("rtk")
    invocation = [proxy, "proxy", *arguments] if proxy else arguments
    result = subprocess.run(invocation, cwd=root, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Rollback rehearsal {arguments[0]} command failed with exit code {result.returncode}")
    return result.stdout.strip()


def revision(root, reference):
    value = command(root, ["git", "rev-parse", "--verify", reference + "^{commit}"])
    if not re.fullmatch(r"[a-f0-9]{40,64}", value):
        raise RuntimeError("Rollback application requires an actual Git revision")
    return value


def compatibility(root, previous):
    hashes = {}
    for relative in CONTRACTS:
        current = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        old = hashlib.sha256((previous / relative).read_bytes()).hexdigest()
        if current != old:
            raise RuntimeError(f"Rollback compatibility rejected changed canonical contract: {relative}")
        hashes[relative] = current
    return hashes


def runtime_database(settings):
    database = make_url(settings.database_url)
    if database.database != "scopegate_test" or database.username != "scopegate_app":
        raise RuntimeError("Rollback containers require the isolated runtime scopegate_test credential")
    if database.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Rollback database must be the explicitly owned local test instance")
    return database


def owned_database_network(root, settings):
    database = runtime_database(settings)
    container = command(root, ["docker", "compose", "ps", "--quiet", "database"])
    if not container or "\n" in container:
        raise RuntimeError("Rollback requires exactly one owned Compose database")
    details = json.loads(command(root, ["docker", "inspect", container]))[0]
    labels = details["Config"]["Labels"]
    if (labels.get("com.docker.compose.project"), labels.get("com.docker.compose.service")) != (
        "scopegate", "database"
    ):
        raise RuntimeError("Rollback database must be the Scopegate Compose database service")
    published = details["NetworkSettings"]["Ports"].get("5432/tcp") or []
    if not any(binding["HostIp"] == "127.0.0.1" and binding["HostPort"] == str(database.port)
               for binding in published):
        raise RuntimeError("Owned Compose database does not match the test fixture database port")
    networks = details["NetworkSettings"]["Networks"]
    if len(networks) != 1:
        raise RuntimeError("Rollback requires one unambiguous owned database network")
    network, state = next(iter(networks.items()))
    if "database" not in state["Aliases"]:
        raise RuntimeError("Owned database network must resolve the Compose database alias")
    return network


def environment_file(settings, directory):
    database = runtime_database(settings)
    runtime = database.set(host="database", port=5432).render_as_string(hide_password=False)
    values = {
        "SCOPEGATE_COMPONENT": "api",
        "SCOPEGATE_ENVIRONMENT": "test",
        "SCOPEGATE_DATABASE_URL": runtime,
        "SCOPEGATE_PUBLIC_ORIGIN": settings.public_origin,
        "SCOPEGATE_OIDC_ISSUER": settings.oidc_issuer,
        "SCOPEGATE_SESSION_SECRET": settings.session_secret,
        "SCOPEGATE_CURSOR_SECRET": settings.cursor_secret,
        "SCOPEGATE_PLATFORM_KEY": settings.platform_key,
        "SCOPEGATE_CATALOG_KEY": settings.catalog_key,
        "SCOPEGATE_OUTBOX_KEY": settings.outbox_key,
        "SCOPEGATE_JOURNAL_DIRECTORY": "/app/var/journal",
        "SCOPEGATE_OTEL_EXPORT_ENABLED": "false",
        "SCOPEGATE_POOL_SIZE": "2",
        "SCOPEGATE_MAX_OVERFLOW": "0",
    }
    if any("\n" in str(value) or "\r" in str(value) for value in values.values()):
        raise RuntimeError("Container environment must contain single-line values")
    path = directory / "api.env"
    with path.open("x", encoding="utf-8") as handle:
        path.chmod(0o600)
        handle.write("".join(f"{key}={value}\n" for key, value in values.items()))
    return path


class ApplicationRollback:
    def __init__(self, root, directory, settings):
        self.root, self.directory = root, directory
        self.current_revision = revision(root, "HEAD")
        override = os.environ.get("SCOPEGATE_ROLLBACK_BASELINE_REVISION")
        if override and not re.fullmatch(r"[a-f0-9]{40,64}", override):
            raise RuntimeError("Intermediate rollback override must be a complete Git commit hash")
        self.baseline_revision = revision(root, override or "HEAD^")
        self.override = override is not None
        self.reference = uuid4().hex
        self.network = owned_database_network(root, settings)
        self.env_file = environment_file(settings, directory)
        self.images, self.containers, self.image_ids = {}, [], {}
        self.base_url = "http://127.0.0.1:8459"
        self.journal = directory / "journal"
        self.journal.mkdir(mode=0o777)
        self.journal.chmod(0o777)

    def build(self):
        archive, previous = self.directory / "previous.tar", self.directory / "previous"
        command(self.root, ["git", "archive", "--format=tar", "--output=" + str(archive), self.baseline_revision])
        previous.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(previous, filter="data")
        self.contract_hashes = compatibility(self.root, previous)
        self._build_image("current", self.root, self.current_revision)
        self._build_image("previous", previous, self.baseline_revision)

    def _build_image(self, phase, context, source_revision):
        tag = f"scopegate-rollback-{self.reference}:{phase}"
        self.images[phase] = tag
        command(self.root, ["docker", "build", "--quiet", "--file", str(context / "backend/Dockerfile"),
                            "--label", "org.opencontainers.image.revision=" + source_revision,
                            "--label", "scopegate.rehearsal=" + self.reference,
                            "--tag", tag, str(context)], timeout=240)
        image = json.loads(command(self.root, ["docker", "image", "inspect", tag]))[0]
        labels = image["Config"]["Labels"]
        if labels.get("org.opencontainers.image.revision") != source_revision:
            raise RuntimeError("Built rollback artifact does not identify the expected source revision")
        self.image_ids[phase] = image["Id"]

    def start(self, phase):
        name = f"scopegate-rollback-{self.reference}-{phase}"
        self.containers.append(name)
        container = command(self.root, ["docker", "run", "--detach", "--name", name,
                                       "--label", "scopegate.rehearsal=" + self.reference,
                                       "--network", self.network,
                                       "--env-file", str(self.env_file),
                                       "--publish", "127.0.0.1:8459:8457",
                                       "--volume", f"{self.journal}:/app/var/journal",
                                       self.images[phase]])
        details = json.loads(command(self.root, ["docker", "inspect", container]))[0]
        if details["Image"] != self.image_ids[phase]:
            raise RuntimeError("Rollback container does not run its verified application artifact")
        inputs = {value.partition("=")[0] for value in details["Config"]["Env"]}
        if "SCOPEGATE_MIGRATION_DATABASE_URL" in inputs or "SCOPEGATE_MIGRATION_OPS_KEY" in inputs:
            raise RuntimeError("Rollback application container must not receive maintenance credentials")
        deadline, last_status = time.monotonic() + 30, 0
        with httpx.Client(base_url=self.base_url, timeout=2, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get("/health/ready")
                    last_status = response.status_code
                    if response.status_code == 200 and response.json().get("status") == "ready":
                        return
                except (httpx.HTTPError, ValueError):
                    last_status = 0
                time.sleep(0.2)
        raise RuntimeError(f"Owned {phase} rollback API did not become ready; last HTTP status {last_status}")

    def previous(self):
        command(self.root, ["docker", "rm", "--force", self.containers[-1]])
        self.containers.pop()
        self.start("previous")

    def cleanup(self):
        failures = []
        for name in self.containers:
            try:
                owned = command(self.root, ["docker", "container", "ls", "--all", "--quiet",
                                           "--filter", "name=^/" + name + "$",
                                           "--filter", "label=scopegate.rehearsal=" + self.reference])
                if owned:
                    command(self.root, ["docker", "rm", "--force", owned])
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                failures.append("Owned rollback container cleanup failed")
        for image in self.images.values():
            try:
                owned = command(self.root, ["docker", "image", "ls", "--quiet",
                                           "--filter", "reference=" + image,
                                           "--filter", "label=scopegate.rehearsal=" + self.reference])
                if owned:
                    command(self.root, ["docker", "image", "rm", image])
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                failures.append("Owned rollback image tag cleanup failed")
        return failures

    def metadata(self):
        return {
            "scope": ("Actual application artifact swap against an explicit intermediate baseline"
                      if self.override else "Actual current-to-parent application swap")
                     + "; isolated local scopegate_test database",
            "current_revision": self.current_revision,
            "baseline_revision": self.baseline_revision,
            "intermediate_baseline_override": self.override,
            "canonical_contract_sha256": self.contract_hashes,
            "built_image_ids": self.image_ids,
            "runtime_database": "scopegate_test",
            "admin_credentials_supplied": False,
        }


@contextmanager
def applications(root: Path, settings):
    ignored = root / "var"
    ignored.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rollback-", dir=ignored) as temporary:
        rehearsal = ApplicationRollback(root, Path(temporary), settings)
        try:
            rehearsal.build()
            rehearsal.start("current")
            yield rehearsal
        finally:
            original = sys.exception()
            failures = rehearsal.cleanup()
            if failures:
                message = "; ".join(failures)
                if original is not None:
                    original.add_note(message)
                else:
                    raise RuntimeError(message)
