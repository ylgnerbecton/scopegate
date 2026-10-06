#!/usr/bin/env python3
"""Probe real local transports and the owned Compose deployment."""

import json
import os
import subprocess
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def verify_gate_state():
    encoded = os.environ.get("SCOPEGATE_RELEASE_GATES")
    if encoded is None:
        return
    records = json.loads(encoded)
    expected = {
        "G-LINT", "G-DOMAIN", "G-DATABASE", "G-CONTRACT", "G-BROWSER",
        "G-MIGRATION", "G-IDENTITY", "G-BUILD", "G-PERFORMANCE", "G-SECURITY", "G-OPERATIONS",
    }
    if isinstance(records, dict):
        records = list(records.values())
    if {item["id"] for item in records} != expected:
        raise RuntimeError("The release requires all eleven preceding gate records")
    if any(item.get("status") != "passed" or item.get("exit_code") != 0 for item in records):
        raise RuntimeError("A preceding release gate failed or was skipped")


def main():
    verify_gate_state()
    with httpx.Client(timeout=5, follow_redirects=False) as client:
        for path, status in [("/health/live", "ok"), ("/health/ready", "ready")]:
            response = client.get("http://localhost:5187" + path)
            response.raise_for_status()
            if response.json()["status"] != status:
                raise RuntimeError(f"Unexpected probe result: {path}")
        frontend = client.get("http://localhost:5187/")
        frontend.raise_for_status()
        if "Scopegate" not in frontend.text or "<script" not in frontend.text:
            raise RuntimeError("The workspace bundle is not available")
        provider = client.get("http://localhost:8901/.well-known/openid-configuration")
        provider.raise_for_status()
        if provider.json()["issuer"] != "http://localhost:8901":
            raise RuntimeError(
                "Independent identity discovery does not match the local issuer"
            )
        api = client.get("http://localhost:8457/openapi.json")
        api.raise_for_status()
    expected = json.loads((ROOT / "specs/contracts/openapi.json").read_text())
    actual = api.json()
    if set(actual["paths"]) != set(expected["paths"]):
        raise RuntimeError("Running API paths differ from the canonical contract")
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    services = {}
    for line in result.stdout.splitlines():
        record = json.loads(line)
        services[record["Service"]] = record["State"]
    required = {"database", "identity", "api", "worker", "web"}
    if any(services.get(service) != "running" for service in required):
        raise RuntimeError("All five owned deployment services must be running")
    print(
        "PASS: real workspace, API, independent issuer, worker and PostgreSQL deployment are ready."
    )


if __name__ == "__main__":
    main()
