"""Owned isolated API artifacts for compatibility and capacity rehearsals."""

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


def command(root, arguments, *, timeout=60, include_stderr=False, input_text=None):
    proxy = shutil.which("rtk")
    invocation = [proxy, "proxy", *arguments] if proxy else arguments
    result = subprocess.run(invocation, cwd=root, capture_output=True, text=True, timeout=timeout,
                            input=input_text, check=False)
    if result.returncode:
        raise RuntimeError(f"Rollback rehearsal {arguments[0]} command failed with exit code {result.returncode}")
    return (result.stdout + (result.stderr if include_stderr else "")).strip()


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


def environment_file(settings, directory, *, pool_size=2, max_overflow=0):
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
        "SCOPEGATE_POOL_SIZE": str(pool_size),
        "SCOPEGATE_MAX_OVERFLOW": str(max_overflow),
    }
    if any("\n" in str(value) or "\r" in str(value) for value in values.values()):
        raise RuntimeError("Container environment must contain single-line values")
    path = directory / "api.env"
    with path.open("x", encoding="utf-8") as handle:
        path.chmod(0o600)
        handle.write("".join(f"{key}={value}\n" for key, value in values.items()))
    return path


class OwnedApi:
    def __init__(self, root, directory, settings, *, port=8459, pool_size=2, max_overflow=0,
                 cpu=None, memory_bytes=None):
        self.root, self.directory = root, directory
        self.current_revision = revision(root, "HEAD")
        self.reference = uuid4().hex
        self.network = owned_database_network(root, settings)
        self.env_file = environment_file(settings, directory, pool_size=pool_size, max_overflow=max_overflow)
        self.images, self.containers, self.drivers, self.image_ids = {}, [], [], {}
        self.container_ids = {}
        self.driver_metadata = []
        self.port, self.cpu, self.memory_bytes = port, cpu, memory_bytes
        self.base_url = f"http://127.0.0.1:{port}"
        self.cleaned = False
        self.journal = directory / "journal"
        self.journal.mkdir(mode=0o777)
        self.journal.chmod(0o777)

    def build(self):
        self._build_image("current", self.root, self.current_revision)

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

    def start(self, phase="current"):
        name = f"scopegate-rollback-{self.reference}-{phase}"
        self.containers.append(name)
        limits = []
        if self.cpu is not None:
            limits += ["--cpus", str(self.cpu)]
        if self.memory_bytes is not None:
            limits += ["--memory", str(self.memory_bytes)]
        container = command(self.root, ["docker", "run", "--detach", "--name", name,
                                       "--label", "scopegate.rehearsal=" + self.reference,
                                       "--network", self.network,
                                       "--env-file", str(self.env_file),
                                       "--publish", f"127.0.0.1:{self.port}:8457",
                                       "--volume", f"{self.journal}:/app/var/journal",
                                       *limits, self.images[phase]])
        details = json.loads(command(self.root, ["docker", "inspect", container]))[0]
        self.container_ids[phase] = details["Id"]
        if details["Image"] != self.image_ids[phase]:
            raise RuntimeError("Rollback container does not run its verified application artifact")
        inputs = {value.partition("=")[0] for value in details["Config"]["Env"]}
        if "SCOPEGATE_MIGRATION_DATABASE_URL" in inputs or "SCOPEGATE_MIGRATION_OPS_KEY" in inputs:
            raise RuntimeError("Rollback application container must not receive maintenance credentials")
        self.limits = {"cpu": details["HostConfig"]["NanoCpus"] / 1_000_000_000,
                       "memory_bytes": details["HostConfig"]["Memory"]}
        self.await_ready(phase)

    def await_ready(self, phase):
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

    def save_logs(self, path):
        output = command(self.root, ["docker", "logs", self.containers[-1]], include_stderr=True)
        path.write_text(output + "\n", encoding="utf-8")

    def statistics(self):
        script = ("import json;from pathlib import Path;"
                  "p=Path('/sys/fs/cgroup/cpu.stat');"
                  "cpu=dict(line.split() for line in p.read_text().splitlines());"
                  "memory=int(Path('/sys/fs/cgroup/memory.current').read_text());"
                  "print(json.dumps({'cpu':{k:int(v) for k,v in cpu.items()},'memory_bytes':memory}))")
        return json.loads(command(self.root, ["docker", "exec", self.containers[-1], "python", "-c", script]))

    def run_driver(self, configuration):
        name = f"scopegate-driver-{self.reference}-{uuid4().hex[:12]}"
        self.drivers.append(name)
        payload = {**configuration, "base_url": f"http://{self.containers[-1]}:8457"}
        output = command(self.root, ["docker", "run", "--interactive", "--name", name,
                                    "--label", "scopegate.rehearsal=" + self.reference,
                                    "--network", self.network, "--cpus", "2", "--memory", str(256 * 1024 * 1024),
                                    "--volume", f"{self.root / 'scripts/performance_driver.py'}:/app/driver.py:ro",
                                    "--entrypoint", "python", self.images["current"], "/app/driver.py"],
                         input_text=json.dumps(payload), timeout=45)
        details = json.loads(command(self.root, ["docker", "inspect", name]))[0]
        if details["Image"] != self.image_ids["current"]:
            raise RuntimeError("Owned load generator must run the verified current dependency artifact")
        limits = {"cpu": details["HostConfig"]["NanoCpus"] / 1_000_000_000,
                  "memory_bytes": details["HostConfig"]["Memory"]}
        if limits != {"cpu": 2, "memory_bytes": 256 * 1024 * 1024}:
            raise RuntimeError("Owned load generator did not receive its declared bounded resources")
        self.driver_metadata.append({"operation": configuration["operation"], "image_id": details["Image"],
                                     "container_id": details["Id"],
                                     "resource_limits": limits, "session_input": "Private stdin; no environment credentials",
                                     "exit_code": details["State"]["ExitCode"]})
        return json.loads(output)

    def cleanup(self):
        failures = []
        for name in [*self.containers, *self.drivers]:
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
        self.cleaned = not failures
        return failures

    def metadata(self):
        return {"source_revision": self.current_revision, "image_ids": self.image_ids,
                "container_ids": self.container_ids,
                "runtime_database": "scopegate_test", "resource_limits": self.limits,
                "admin_credentials_supplied": False,
                "transport_topology": "Owned API container to Compose database:5432",
                "readiness_transport": "Host readiness probe to published API port"}


class ApplicationRollback(OwnedApi):
    def __init__(self, root, directory, settings):
        super().__init__(root, directory, settings)
        override = os.environ.get("SCOPEGATE_ROLLBACK_BASELINE_REVISION")
        if override and not re.fullmatch(r"[a-f0-9]{40,64}", override):
            raise RuntimeError("Intermediate rollback override must be a complete Git commit hash")
        self.baseline_revision = revision(root, override or "HEAD^")
        self.override = override is not None

    def build(self):
        archive, previous = self.directory / "previous.tar", self.directory / "previous"
        command(self.root, ["git", "archive", "--format=tar", "--output=" + str(archive), self.baseline_revision])
        previous.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(previous, filter="data")
        self.contract_hashes = compatibility(self.root, previous)
        super().build()
        self._build_image("previous", previous, self.baseline_revision)

    def previous(self):
        command(self.root, ["docker", "rm", "--force", self.containers[-1]])
        self.containers.pop()
        self.start("previous")

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
def runtime(root: Path, settings, factory=OwnedApi, *, logs=None, **options):
    ignored = root / "var"
    ignored.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rollback-", dir=ignored) as temporary:
        rehearsal = factory(root, Path(temporary), settings, **options)
        try:
            rehearsal.build()
            rehearsal.start("current")
            yield rehearsal
        finally:
            original = sys.exception()
            if logs is not None and rehearsal.containers:
                try:
                    rehearsal.save_logs(logs)
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as failure:
                    if original is not None:
                        original.add_note("Owned API logs could not be saved")
                    else:
                        original = failure
            failures = rehearsal.cleanup()
            if failures:
                message = "; ".join(failures)
                if original is not None:
                    original.add_note(message)
                else:
                    raise RuntimeError(message)
            if original is not None and sys.exception() is None:
                raise original


def applications(root: Path, settings):
    return runtime(root, settings, ApplicationRollback)


def current_application(root: Path, settings, **options):
    return runtime(root, settings, **options)
