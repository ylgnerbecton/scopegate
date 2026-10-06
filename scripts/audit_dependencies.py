#!/usr/bin/env python3
"""Audit exact locked dependencies and export a reproducible software inventory."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "artifacts/security"
    directory.mkdir(parents=True, exist_ok=True)
    exported = subprocess.run(
        [
            "uv",
            "export",
            "--project",
            "backend",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    requirements = directory / "requirements.lock.txt"
    requirements.write_text(exported.stdout)
    command = [
        str(ROOT / "backend/.venv/bin/pip-audit"),
        "-r",
        str(requirements),
        "--no-deps",
        "--disable-pip",
        "--format",
        "cyclonedx-json",
        "--output",
        str(directory / "backend-sbom.json"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    audit = subprocess.run(
        ["npm", "audit", "--json"],
        cwd=ROOT / "frontend",
        capture_output=True,
        text=True,
        check=False,
    )
    (directory / "frontend-audit.json").write_text(audit.stdout)
    if audit.returncode:
        raise RuntimeError(
            "The locked frontend dependency audit failed; inspect artifacts/security/frontend-audit.json"
        )
    inventory = subprocess.run(
        ["npm", "sbom", "--sbom-format", "cyclonedx"],
        cwd=ROOT / "frontend",
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(inventory.stdout)
    # Preserve dependency identity, versions, hashes and licenses. Optional
    # maintainer/project links are omitted from the shareable inventory.
    for component in report.get("components", []):
        component.pop("externalReferences", None)
    (directory / "frontend-sbom.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        "PASS: locked dependency audits and both CycloneDX inventories were generated."
    )


if __name__ == "__main__":
    main()
