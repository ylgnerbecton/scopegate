"""Shared fail-closed primitives for local release evidence and review archives."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from spec_io import load_json as read_json

MANIFEST = "specs/implementation-evidence.json"
MAX_ARTIFACT = 10 * 1024 * 1024
PRIVATE_PARTS = {
    ".git", ".venv", "node_modules", "vendor", "vendors", "var", "private",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "test-results",
    "playwright-report", "dist", "coverage", "tmp", "attachments",
}
SECRET_NAME = re.compile(r"SECRET|PASSWORD|TOKEN|(?:^|_)KEY(?:$|_)|DATABASE_URL", re.IGNORECASE)


class ReleaseFailure(Exception):
    """A release input or executed gate cannot certify the current revision."""


def ensure(condition, message):
    if not condition:
        raise ReleaseFailure(message)


def load_json(path):
    return read_json(Path(path))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def tool_arguments(arguments):
    """Keep real exit codes and unfiltered output when the optional proxy exists."""
    proxy = shutil.which("rtk")
    return [proxy, "proxy", *arguments] if proxy else list(arguments)


def run_tool(root, arguments, timeout=30):
    ensure(shutil.which(arguments[0]) is not None, f"Missing executable: {arguments[0]}")
    return subprocess.run(
        tool_arguments(arguments), cwd=root, capture_output=True, text=True,
        check=False, timeout=timeout,
    )


def clean_revision(root):
    top = run_tool(root, ["git", "rev-parse", "--show-toplevel"])
    ensure(top.returncode == 0 and Path(top.stdout.strip()).resolve() == root.resolve(),
           "Release evidence requires this project to own its Git repository")
    revision = run_tool(root, ["git", "rev-parse", "HEAD"])
    ensure(revision.returncode == 0 and re.fullmatch(r"[a-f0-9]{40,64}", revision.stdout.strip()),
           "Commit the implementation before collecting release evidence")
    dirty = run_tool(root, ["git", "status", "--porcelain=v1", "-z", "--untracked-files=normal"])
    ensure(dirty.returncode == 0, "Cannot inspect repository state")
    changed = [entry[3:] for entry in dirty.stdout.split("\0") if entry]
    ensure(all(path == MANIFEST for path in changed),
           "Uncommitted implementation changes invalidate revision evidence")
    return revision.stdout.strip()


def safe_path(root, relative):
    candidate = Path(relative)
    ensure(not candidate.is_absolute() and ".." not in candidate.parts,
           "Public artifact path must remain inside the repository")
    path = root / candidate
    ensure(path.resolve().is_relative_to(root.resolve()), "Artifact escapes repository")
    current = root
    for part in candidate.parts:
        current = current / part
        ensure(not current.is_symlink(), "Symbolic links are not public release artifacts")
    return path


def public_path(relative):
    parts = Path(relative).parts
    ensure(not (set(parts) & PRIVATE_PARTS), f"Private or dependency path excluded: {relative}")
    ensure(all(not part.startswith(".env") or part == ".env.example" for part in parts),
           f"Credential file excluded: {relative}")
    ensure(Path(relative).suffix.lower() not in {".pyc", ".pyo", ".pdf", ".docx"},
           "Compiled caches and private document attachments are excluded")


def artifact(root, path):
    relative = Path(path).relative_to(root).as_posix() if Path(path).is_absolute() else str(path)
    source = safe_path(root, relative)
    ensure(source.is_file() and 0 < source.stat().st_size <= MAX_ARTIFACT,
           f"Missing, empty or oversized artifact: {relative}")
    return {"path": relative, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


def verify_artifact(root, reference):
    public_path(reference["path"])
    actual = artifact(root, reference["path"])
    ensure(actual == reference, f"Artifact digest mismatch: {reference['path']}")
    return safe_path(root, reference["path"])


def dotenv_secrets(path):
    values = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.removeprefix("export ").partition("=")
        value = value.strip().strip("\"'")
        if separator and SECRET_NAME.search(name) and len(value) >= 4:
            values.add(value)
    return values


def secret_values(root, environment):
    values = {value for name, value in environment.items() if SECRET_NAME.search(name) and len(value) >= 4}
    for path in root.glob(".env*"):
        if path.name == ".env.example" or not path.is_file():
            continue
        values.update(dotenv_secrets(path))
    return sorted(values, key=len, reverse=True)


def sanitize(text, root, secrets):
    for value in secrets:
        text = text.replace(value, "[REDACTED]")
    text = text.replace(str(root.resolve()), "<workspace>")
    text = re.sub(r"(postgres(?:ql)?(?:\+\w+)?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"([?&#](?:token|code|state|access_token|id_token)=)[^\s&#\"<>]+", r"\1[REDACTED]", text)
    return text


def sanitize_file(path, root, secrets):
    ensure(path.stat().st_size <= MAX_ARTIFACT, "Unsanitized output exceeds artifact size limit")
    if path.suffix == ".xml":
        tree = ET.parse(path)
        for element in tree.iter():
            element.attrib.update({name: sanitize(value, root, secrets) for name, value in element.attrib.items()})
            element.text = sanitize(element.text, root, secrets) if element.text else element.text
            element.tail = sanitize(element.tail, root, secrets) if element.tail else element.tail
        tree.write(path, encoding="utf-8", xml_declaration=True)
        return
    contents = path.read_text(encoding="utf-8", errors="replace")
    path.write_text(sanitize(contents, root, secrets), encoding="utf-8")


def topological_gates(gates):
    indexed = {gate["id"]: gate for gate in gates}
    ensure(len(indexed) == len(gates), "Duplicate runtime gate IDs")
    ensure(all(set(gate.get("depends_on", [])) <= set(indexed) for gate in gates),
           "Runtime gate references an unknown dependency")
    pending, result = dict(indexed), []
    while pending:
        ready = [gate for gate in pending.values() if set(gate.get("depends_on", [])) <= {item["id"] for item in result}]
        ensure(ready, "Runtime gate dependency cycle")
        for gate in ready:
            result.append(gate)
            del pending[gate["id"]]
    return result


def public_environment():
    return {
        "scope": "closed local evaluation with synthetic data",
        "python": os.sys.version.split()[0],
        "platform": os.sys.platform,
        "proxy": "rtk proxy" if shutil.which("rtk") else "native subprocess",
    }
