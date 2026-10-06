#!/usr/bin/env python3
"""Exercise upstream address replacement without restarting the owned web server."""

import json
import time
import uuid
from pathlib import Path

import httpx
from release_support import ReleaseFailure, ensure, run_tool, write_json

ROOT = Path(__file__).resolve().parents[1]


def run(arguments):
    result = run_tool(ROOT, arguments, timeout=30)
    ensure(result.returncode == 0, "Owned proxy lifecycle command failed")
    return result.stdout.strip()


def api_details():
    container = run(["docker", "compose", "ps", "-q", "api"])
    ensure(container and "\n" not in container, "Exactly one owned API is required")
    details = json.loads(run(["docker", "inspect", container]))[0]
    ensure(details["Config"]["Labels"].get("com.docker.compose.project") == "scopegate",
           "API must belong to this project")
    networks = details["NetworkSettings"]["Networks"]
    ensure(len(networks) == 1, "The local rehearsal requires one owned Compose network")
    network, state = next(iter(networks.items()))
    return network, state["IPAddress"], details["Config"]["Image"]


def await_ready(client):
    deadline, statuses = time.monotonic() + 45, []
    while time.monotonic() < deadline:
        try:
            response = client.get("http://localhost:5187/health/ready")
            statuses.append(response.status_code)
            if response.status_code == 200 and response.json().get("status") == "ready":
                return statuses
        except (httpx.HTTPError, ValueError):
            statuses.append(0)
        time.sleep(0.25)
    raise ReleaseFailure("Web proxy did not recover within its readiness deadline")


def main():
    web = run(["docker", "compose", "ps", "-q", "web"])
    ensure(web and "\n" not in web, "Exactly one running owned web server is required")
    hold = "scopegate-proxy-probe-" + uuid.uuid4().hex[:12]
    with httpx.Client(timeout=2) as client:
        await_ready(client)
        network, old_address, image = api_details()
        started = time.monotonic()
        try:
            run(["docker", "compose", "rm", "--stop", "--force", "api"])
            run(["docker", "run", "--detach", "--name", hold, "--network", network,
                 "--ip", old_address, "--entrypoint", "python", image,
                 "-c", "import time; time.sleep(120)"])
            run(["docker", "compose", "up", "--detach", "--no-deps", "api"])
            ensure(api_details()[1] != old_address, "Rehearsal did not replace the upstream address")
            statuses = await_ready(client)
            ensure(run(["docker", "compose", "ps", "-q", "web"]) == web,
                   "Web server must recover without being recreated")
        finally:
            run_tool(ROOT, ["docker", "rm", "--force", hold])
            run(["docker", "compose", "up", "--detach", "--no-deps", "api"])
    elapsed = round(time.monotonic() - started, 3)
    write_json(ROOT / "artifacts/operations/proxy-recovery.json", {
        "scope": "Actual owned Compose API replaced at a different address; same web container",
        "recovery_deadline_seconds": 45, "elapsed_seconds": elapsed,
        "upstream_address_changed": True, "web_recreated": False,
        "observed_http_statuses": statuses, "passed": True,
    })
    print(f"PASS: unchanged web server recovered after API address replacement ({elapsed}s).")


if __name__ == "__main__":
    try:
        main()
    except (ReleaseFailure, OSError, ValueError) as error:
        raise SystemExit(f"Proxy recovery rehearsal failed: {error}") from error
