#!/usr/bin/env python3
"""Package committed public source and verified release proof for offline review."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from release_support import (
    MANIFEST,
    ReleaseFailure,
    clean_revision,
    ensure,
    load_json,
    public_path,
    run_tool,
    safe_path,
    secret_values,
    tool_arguments,
    verify_artifact,
    write_json,
)
from spec_io import unique_object

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_MANIFEST = "REVIEW-MANIFEST.json"


def committed_inventory(root):
    result = run_tool(root, ["git", "ls-files", "--stage", "-z"])
    ensure(result.returncode == 0, "Cannot enumerate committed public source")
    inventory = []
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        metadata, relative = entry.split("\t", 1)
        mode, _, stage = metadata.split()
        ensure(stage == "0" and mode in {"100644", "100755"}, "Unmerged files, submodules or symbolic links cannot be packaged")
        public_path(relative)
        ensure(not relative.startswith("artifacts/"), "Generated proof must be selected by the verified manifest")
        inventory.append(relative)
    ensure(inventory and MANIFEST in inventory, "Committed release manifest is missing from the public inventory")
    return inventory


def artifact_references(value):
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            yield value
        else:
            for child in value.values():
                yield from artifact_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from artifact_references(child)


def verified_references(root, manifest, revision):
    references, pending = {}, list(artifact_references(manifest))
    while pending:
        reference = pending.pop()
        relative = reference["path"]
        if relative in references:
            ensure(references[relative] == reference, "Conflicting artifact hashes in release proof")
            continue
        path = verify_artifact(root, reference)
        references[relative] = reference
        owned_proof = path.name == "result.json" or any(part in {"scenarios", "tasks"} for part in path.parts)
        if path.suffix == ".json" and relative.startswith("artifacts/evidence/") and owned_proof:
            proof = load_json(path)
            ensure(proof.get("revision") == revision, f"Stale nested proof: {relative}")
            pending.extend(artifact_references(proof))
    return references


def package_files(root, inventory, references):
    files = {}
    for relative in sorted(set(inventory) | set(references)):
        path = safe_path(root, relative)
        ensure(path.is_file(), f"Missing public file: {relative}")
        content = path.read_bytes()
        files[relative] = content
    return files


def archive_index(revision, files, references, modes=None):
    return {
        "schema_version": 1, "project": "Scopegate", "revision": revision,
        "scope": "closed local evaluation using synthetic fixtures",
        "live_approvals": [],
        "files": [{"path": relative, "sha256": hashlib.sha256(content).hexdigest(),
                   "bytes": len(content), "mode": (modes or {}).get(relative, "0644"),
                   "kind": "release-manifest" if relative == MANIFEST else
                           ("evidence" if relative in references else "committed-source")}
                  for relative, content in sorted(files.items())],
    }


def write_archive(destination, files, index):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.new")
    contents = {**files, ARCHIVE_MANIFEST: (json.dumps(index, indent=2, sort_keys=True) + "\n").encode()}
    modes = {record["path"]: int(record["mode"], 8) for record in index["files"]}
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, content in sorted(contents.items()):
            information = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            information.compress_type = zipfile.ZIP_DEFLATED
            information.external_attr = (0o100000 | modes.get(relative, 0o644)) << 16
            archive.writestr(information, content)
    temporary.replace(destination)


def verify_archive(path, expected_revision):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        ensure(len(set(names)) == len(names), "Archive contains duplicate entries")
        index = json.loads(archive.read(ARCHIVE_MANIFEST), object_pairs_hook=unique_object)
        ensure(index["revision"] == expected_revision and not index["live_approvals"], "Archive revision or approval scope changed")
        records = {record["path"]: record for record in index["files"]}
        ensure(len(records) == len(index["files"]) and set(names) == {*records, ARCHIVE_MANIFEST}, "Archive inventory does not match its manifest")
        for relative, record in records.items():
            public_path(relative)
            ensure(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "Unsafe archive entry")
            content = archive.read(relative)
            ensure(len(content) == record["bytes"] and hashlib.sha256(content).hexdigest() == record["sha256"],
                   f"Archive file consistency failed: {relative}")
            ensure((archive.getinfo(relative).external_attr >> 16) & 0o777 == int(record["mode"], 8),
                   f"Archive executable mode changed: {relative}")
        ensure(archive.testzip() is None, "Archive CRC verification failed")
    return index


def package(root, destination=None):
    revision = clean_revision(root)
    verifier = subprocess.run(tool_arguments([sys.executable, "scripts/check_evidence.py"]), cwd=root, check=False)
    ensure(verifier.returncode == 0, "Only current passing release evidence can enter the public archive")
    manifest = load_json(root / MANIFEST)
    ensure(manifest["revision"] == revision and not manifest["live_approvals"], "Package requires synthetic local proof without live approvals")
    references = verified_references(root, manifest, revision)
    files = package_files(root, committed_inventory(root), references)
    reject_secrets(root, files)
    modes = {relative: "0755" if safe_path(root, relative).stat().st_mode & 0o111 else "0644" for relative in files}
    index = archive_index(revision, files, references, modes)
    ensure(clean_revision(root) == revision, "Implementation changed during archive collection")
    destination = destination or root / "artifacts/review" / f"scopegate-{revision[:12]}.zip"
    ensure(destination.resolve().is_relative_to((root / "artifacts/review").resolve()), "Review archives belong in artifacts/review")
    write_archive(destination, files, index)
    verify_archive(destination, revision)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    write_json(destination.with_suffix(".manifest.json"), {"schema_version": 1, "revision": revision,
               "archive": destination.relative_to(root).as_posix(), "sha256": digest,
               "file_count": len(files) + 1})
    return destination, digest


def reject_secrets(root, files):
    secrets = [value.encode() for value in secret_values(root, os.environ)]
    for relative, content in files.items():
        ensure(not any(value in content for value in secrets), f"Known local credential found in public archive input: {relative}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, metavar="ARCHIVE", help="Verify archive hashes and inventory without Git or runtime services")
    args = parser.parse_args()
    try:
        if args.verify:
            with zipfile.ZipFile(args.verify) as archive:
                revision = json.loads(archive.read(ARCHIVE_MANIFEST), object_pairs_hook=unique_object)["revision"]
            verify_archive(args.verify, revision)
            print(f"PASS: offline review archive inventory and hashes match revision {revision}.")
            return 0
        destination, digest = package(ROOT)
    except (ReleaseFailure, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print(f"Review packaging failed: {error}", file=sys.stderr)
        return 1
    print(f"PASS: verified public review archive {destination.relative_to(ROOT)} (sha256={digest}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
