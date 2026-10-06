#!/usr/bin/env python3
"""Capture real screens in an owned, disposable deployment without resetting the workspace."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OWNER_LABEL = "scopegate.capture.owner"
EXPECTED_CAPTURES = (
    "01-sign-in", "02-overview", "03-resource-library", "04-localized-library",
    "05-members", "06-grant-change-review", "07-invitation-history", "08-invitation-plan-review",
    "09-audit-activity", "10-overview-tablet", "11-overview-mobile", "12-library-mobile",
    "13-recipient-plan", "14-migration-review",
)


def redact(value: str, private_values: set[str]) -> str:
    for private in sorted(private_values, key=len, reverse=True):
        if private:
            value = value.replace(private, "[redacted]")
    value = value.replace(str(ROOT), "<workspace>")
    value = re.sub(r"((?:token|code|state|nonce)=)[^&#\s\"']+", r"\1[redacted]", value)
    return re.sub(r"(?im)(\b(?:cookie|set-cookie|authorization|x-csrf-token)\s*[:=]\s*)[^\r\n]+",
                  r"\1[redacted]", value)


def private_environment(config: dict) -> set[str]:
    return {
        str(value)
        for service in config.get("services", {}).values()
        for key, value in service.get("environment", {}).items()
        if any(word in key for word in ("PASSWORD", "SECRET", "KEY", "TOKEN", "DATABASE_URL"))
        and value
    }


def run(command: list[str], *, private_values: set[str], timeout: int = 120,
        environment: dict[str, str] | None = None, required: bool = True) -> subprocess.CompletedProcess:
    wrapped = ["rtk", "proxy", *command] if shutil.which("rtk") else command
    result = subprocess.run(wrapped, cwd=ROOT, env=environment, text=True,
                            capture_output=True, timeout=timeout, check=False)
    if required and result.returncode:
        diagnostic = redact((result.stdout + result.stderr)[-6000:], private_values)
        raise RuntimeError(f"{command[0]} exited {result.returncode}: {diagnostic}")
    return result


def capture_configuration(config: dict, owner: str, web_port: int, identity_port: int) -> dict:
    """Copy the resolved topology; replace external endpoints, credentials and resource ownership."""
    if not re.fullmatch(r"[0-9a-f]{12}", owner):
        raise ValueError("Capture owner must be a fresh hexadecimal identifier")
    if web_port == identity_port or not all(1024 <= port <= 65535 for port in (web_port, identity_port)):
        raise ValueError("Capture ports must be distinct unprivileged ports")
    project = f"scopegate-capture-{owner}"
    result = copy.deepcopy(config)
    result["name"] = project
    required_services = {"database", "initialize", "identity", "api", "worker", "web"}
    if not required_services.issubset(result.get("services", {})):
        raise ValueError("The canonical deployment is missing a capture dependency")
    for kind in ("volumes", "networks"):
        for name, resource in result.get(kind, {}).items():
            if resource.get("external"):
                raise ValueError("A capture cannot attach an externally owned resource")
            resource["name"] = f"{project}_{name}"
            resource.setdefault("labels", {})[OWNER_LABEL] = owner
    passwords = {"admin": secrets.token_urlsafe(32), "runtime": secrets.token_urlsafe(32)}
    keys = {
        "SCOPEGATE_OUTBOX_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        **{f"SCOPEGATE_{key}": secrets.token_urlsafe(36)
           for key in ("SESSION_SECRET", "CURSOR_SECRET", "PLATFORM_KEY", "CATALOG_KEY", "MIGRATION_OPS_KEY")},
    }
    origin, issuer = f"http://localhost:{web_port}", f"http://localhost:{identity_port}"
    for name, service in result["services"].items():
        service.setdefault("labels", {})[OWNER_LABEL] = owner
        environment = service.setdefault("environment", {})
        for key in list(environment):
            if key in keys:
                environment[key] = keys[key]
        if environment.get("SCOPEGATE_OPERATIONS_TOKEN"):
            environment["SCOPEGATE_OPERATIONS_TOKEN"] = keys["SCOPEGATE_MIGRATION_OPS_KEY"]
        if name == "database":
            environment["POSTGRES_PASSWORD"] = passwords["admin"]
        if environment.get("SCOPEGATE_DATABASE_URL"):
            environment["SCOPEGATE_DATABASE_URL"] = (
                f"postgresql+psycopg://scopegate_app:{passwords['runtime']}@database:5432/scopegate"
            )
        if environment.get("SCOPEGATE_MIGRATION_DATABASE_URL"):
            environment["SCOPEGATE_MIGRATION_DATABASE_URL"] = (
                f"postgresql+psycopg://postgres:{passwords['admin']}@database:5432/scopegate"
            )
        if "SCOPEGATE_PUBLIC_ORIGIN" in environment:
            environment["SCOPEGATE_PUBLIC_ORIGIN"] = origin
        if "SCOPEGATE_OIDC_ISSUER" in environment:
            environment["SCOPEGATE_OIDC_ISSUER"] = issuer
        if "SCOPEGATE_OIDC_REDIRECT_URI" in environment:
            environment["SCOPEGATE_OIDC_REDIRECT_URI"] = f"{origin}/auth/callback"
        service.pop("ports", None)
        if "build" in service:
            service["image"] = f"{project}-{'web' if name == 'web' else 'backend'}:local"
            service["build"].setdefault("labels", {})[OWNER_LABEL] = owner
    result["services"]["web"]["ports"] = [{"target": 8080, "published": str(web_port),
        "host_ip": "127.0.0.1", "protocol": "tcp"}]
    result["services"]["identity"]["ports"] = [{"target": 8901, "published": str(identity_port),
        "host_ip": "127.0.0.1", "protocol": "tcp"}]
    return result


def assert_owned(resources: list[dict], project: str, owner: str, kind: str) -> None:
    for resource in resources:
        labels = resource.get("Config", {}).get("Labels", {}) if kind == "container" else resource.get("Labels", {})
        if labels.get("com.docker.compose.project") != project or labels.get(OWNER_LABEL) != owner:
            raise RuntimeError(f"Refusing to remove a {kind} without matching capture ownership")


def inspect_owned(project: str, owner: str, private_values: set[str]) -> None:
    for kind, template in (("container", "{{.ID}}"), ("volume", "{{.Name}}"), ("network", "{{.ID}}")):
        command = ["docker", "ps", "-a"] if kind == "container" else ["docker", kind, "ls"]
        listed = run([*command, "--filter", f"label=com.docker.compose.project={project}", "--format", template],
                     private_values=private_values)
        identifiers = listed.stdout.split()
        if identifiers:
            inspected = run(["docker", kind, "inspect", *identifiers], private_values=private_values)
            assert_owned(json.loads(inspected.stdout), project, owner, kind)


def cleanup(compose: list[str], project: str, owner: str, private_values: set[str]) -> None:
    inspect_owned(project, owner, private_values)
    run([*compose, "down", "--volumes", "--remove-orphans", "--timeout", "15"],
        private_values=private_values, timeout=90)
    for suffix in ("backend", "web"):
        image = f"{project}-{suffix}:local"
        inspected = run(["docker", "image", "inspect", image], private_values=private_values, required=False)
        if inspected.returncode == 0:
            labels = json.loads(inspected.stdout)[0].get("Config", {}).get("Labels", {})
            if labels.get(OWNER_LABEL) != owner:
                raise RuntimeError("Refusing to remove an image without matching capture ownership")
            run(["docker", "image", "rm", image], private_values=private_values)
        elif "No such image" not in inspected.stderr:
            raise RuntimeError("Docker could not verify the owned capture image cleanup")
    # A nonzero Docker read is a failed cleanup check, not evidence of no remaining resources.
    for command, template in ((["docker", "ps", "-a"], "{{.ID}}"),
                              (["docker", "volume", "ls"], "{{.Name}}"),
                              (["docker", "network", "ls"], "{{.ID}}")):
        result = run([*command, "--filter", f"label=com.docker.compose.project={project}", "--format", template],
                     private_values=private_values)
        if result.stdout.strip():
            raise RuntimeError("Capture cleanup left an owned resource behind")


def verify_captures(output: Path) -> list[dict]:
    expected = {f"{name}.png" for name in EXPECTED_CAPTURES}
    if {path.name for path in output.glob("*.png")} != expected:
        raise RuntimeError("Capture inventory must contain all fourteen expected screens")
    inventory = []
    for name in sorted(expected):
        data = (output / name).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise RuntimeError(f"Capture {name} is not a PNG")
        width, height = struct.unpack(">II", data[16:24])
        if width < 300 or height < 300:
            raise RuntimeError(f"Capture {name} has an unexpected viewport")
        inventory.append({"file": name, "width": width, "height": height,
                          "sha256": hashlib.sha256(data).hexdigest()})
    return inventory


def wait_ready(origin: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{origin}/health/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError("The isolated workspace did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-port", type=int, default=5189)
    parser.add_argument("--identity-port", type=int, default=8902)
    args = parser.parse_args()
    for port in (args.web_port, args.identity_port):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", port))
    owner = secrets.token_hex(6)
    project = f"scopegate-capture-{owner}"
    output = ROOT / "artifacts/browser/captures" / project
    output.mkdir(parents=True, exist_ok=False)
    private_values: set[str] = set()
    resolved = run(["docker", "compose", "--project-name", project, "config", "--format", "json"],
                   private_values=private_values, required=False)
    if resolved.returncode:
        raise RuntimeError("Canonical Compose resolution failed; private configuration output is withheld")
    canonical = json.loads(resolved.stdout)
    private_values.update(private_environment(canonical))
    config = capture_configuration(canonical, owner, args.web_port, args.identity_port)
    private_values.update(private_environment(config))
    with tempfile.TemporaryDirectory(prefix=f"{project}-") as directory:
        path = Path(directory) / "compose.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(config, stream)
        compose = ["docker", "compose", "--project-name", project, "-f", str(path)]
        try:
            print("Building two owned capture images", flush=True)
            run([*compose, "build", "api", "web"], private_values=private_values, timeout=600)
            print("Starting the isolated workspace and independent identity provider", flush=True)
            run([*compose, "up", "--no-build", "-d"], private_values=private_values)
            origin = f"http://localhost:{args.web_port}"
            wait_ready(origin)
            environment = {**os.environ, "SCOPEGATE_WEB_URL": origin,
                           "SCOPEGATE_SCREENSHOT_DIRECTORY": str(output)}
            captured = run(["node", "frontend/scripts/capture-workspace.mjs"],
                           private_values=private_values, environment=environment, timeout=300)
            print(redact(captured.stdout, private_values), end="", flush=True)
            inventory = verify_captures(output)
        finally:
            print("Removing only the owned capture project, volumes and image tags", flush=True)
            cleanup(compose, project, owner, private_values)
    manifest = {"project": project, "origin": origin, "screenshots": inventory,
                "cleanup": "verified; no owned containers, networks or volumes remain"}
    (output / "capture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified fourteen real captures in {output.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
