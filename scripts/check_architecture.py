"""Preserve the implemented Python import boundaries and callable complexity."""

from __future__ import annotations

import argparse
import ast
import os
import sys
from importlib.metadata import version
from pathlib import Path

from radon.complexity import cc_visit
from radon.visitors import Class

ROOT = Path(__file__).resolve().parents[1]
MAX_COMPLEXITY = 10
SOURCE_ROOTS = (Path("backend/src"), Path("identity_provider"))
REQUIRED_TREES = (*SOURCE_ROOTS, Path("backend/src/scopegate/domain"), Path("backend/src/scopegate/api"))
DOMAIN_VALUES = {
    "__future__", "builtins", "collections", "dataclasses", "datetime", "decimal",
    "enum", "fractions", "functools", "itertools", "math", "operator", "re", "typing", "uuid",
}
API_INFRASTRUCTURE = {
    "sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pg8000", "sqlite3", "alembic",
    "redis", "pymongo", "kafka", "celery", "httpx", "requests", "socket", "smtplib",
    "cryptography", "jwt", "opentelemetry", "prometheus_client", "importlib", "identity_provider",
    "http", "urllib", "xmlrpc", "subprocess",
}
API_BOUNDARIES = {"api", "services", "dependencies", "errors", "config", "domain"}
EFFECT_EXPORTS = {"db", "transaction", "get_engine", "journal", "audit", "receipt", "lock_org", "lock_resources"}


class ArchitectureFailure(Exception):
    """The complete source inventory could not be checked."""


def inventory(root: Path) -> list[Path]:
    for relative in REQUIRED_TREES:
        directory = root / relative
        if directory.is_symlink() or not directory.is_dir():
            raise ArchitectureFailure(f"{relative.as_posix()}: required source directory is missing or linked")
    files: list[Path] = []
    for relative in SOURCE_ROOTS:
        for directory, folders, names in os.walk(root / relative, onerror=raise_inventory_error):
            for name in sorted(folders + names):
                path = Path(directory) / name
                if path.is_symlink():
                    raise ArchitectureFailure(f"{path.relative_to(root).as_posix()}: linked source is not accepted")
                if name.endswith(".py") and name in names:
                    files.append(path)
    for relative in REQUIRED_TREES:
        if not any(path.is_relative_to(root / relative) for path in files):
            raise ArchitectureFailure(f"{relative.as_posix()}: source inventory is empty")
    return sorted(files)


def raise_inventory_error(error: OSError) -> None:
    raise ArchitectureFailure(f"Source inventory failed: {type(error).__name__}") from error


def module_name(root: Path, path: Path) -> tuple[str, str]:
    base = root / "backend/src" if path.is_relative_to(root / "backend/src") else root
    parts = list(path.relative_to(base).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    module = ".".join(parts)
    package = module if is_package else ".".join(parts[:-1])
    return module, package


def imported_targets(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    parts = package.split(".") if package else []
    if node.level:
        if node.level > len(parts):
            raise ArchitectureFailure("Relative import escapes the source package")
        parts = parts[:len(parts) - node.level + 1]
    else:
        parts = []
    prefix = ".".join([*parts, *([node.module] if node.module else [])])
    return [f"{prefix}.{alias.name}" if prefix else alias.name for alias in node.names]


def within(module: str, boundary: str) -> bool:
    return module == boundary or module.startswith(f"{boundary}.")


def forbidden_dependency(module: str, target: str) -> str | None:
    parts = target.split(".")
    dependency = parts[0]
    bounded = within(module, "scopegate.domain") or within(module, "scopegate.api")
    if bounded and target == "builtins.__import__":
        return "Dynamic imports are not accepted in domain or HTTP adapters"
    if within(module, "scopegate.domain"):
        if target == "scopegate.domain" or target.startswith("scopegate.domain."):
            return None
        if dependency not in DOMAIN_VALUES:
            return "domain imports must remain within the pure domain and standard value types"
    if within(module, "scopegate.api"):
        if dependency in API_INFRASTRUCTURE:
            return "HTTP adapters must delegate persistence and external effects to services"
        if dependency == "scopegate" and (len(parts) < 2 or parts[1] not in API_BOUNDARIES):
            return "HTTP adapters may import only services and HTTP/domain boundary helpers"
        if target.startswith("scopegate.services.common") and target != "scopegate.services.common.expected_version":
            return "HTTP adapters may use only expected_version from the shared transaction helpers"
        if target.startswith("scopegate.services.") and parts[-1] in EFFECT_EXPORTS:
            return "HTTP adapters cannot import transaction effects reexported by services"
    return None


def import_errors(tree: ast.AST, module: str, package: str) -> list[tuple[int, str]]:
    errors: list[tuple[int, str]] = []
    bounded = within(module, "scopegate.domain") or within(module, "scopegate.api")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                targets = imported_targets(node, package)
            except ArchitectureFailure as error:
                errors.append((node.lineno, str(error)))
                continue
            for target in targets:
                reason = forbidden_dependency(module, target)
                if reason:
                    errors.append((node.lineno, f"{target}: {reason}"))
        dynamic_call = isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == "__import__"
            or isinstance(node.func, ast.Attribute) and node.func.attr == "__import__"
        )
        if bounded and dynamic_call:
            errors.append((node.lineno, "Dynamic imports are not accepted in domain or HTTP adapters"))
    return errors


def callable_blocks(source: str):
    pending = list(cc_visit(source))
    seen: set[tuple[str, int, int]] = set()
    while pending:
        block = pending.pop()
        if isinstance(block, Class):
            pending.extend(block.methods)
            pending.extend(block.inner_classes)
            continue
        identity = (block.name, block.lineno, block.col_offset)
        if identity not in seen:
            seen.add(identity)
            yield block
            pending.extend(block.closures)


def check(root: Path) -> dict:
    files = inventory(root)
    errors: list[str] = []
    count = 0
    maximum = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
            module, package = module_name(root, path)
            errors.extend(f"{relative}:{line}: {message}" for line, message in import_errors(tree, module, package))
            for block in callable_blocks(source):
                count += 1
                maximum = max(maximum, block.complexity)
                if block.complexity > MAX_COMPLEXITY:
                    errors.append(f"{relative}:{block.lineno}: {block.name} has CC {block.complexity}; maximum is {MAX_COMPLEXITY}")
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append(f"{relative}: source could not be checked ({type(error).__name__})")
    return {"files": len(files), "callables": count, "maximum_complexity": maximum, "radon_version": version("radon"), "errors": sorted(errors)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Source checkout to inspect")
    args = parser.parse_args()
    try:
        report = check(args.root.resolve())
    except ArchitectureFailure as error:
        print(f"Architecture check failed: {error}", file=sys.stderr)
        return 1
    if report["errors"]:
        print("Architecture check failed:", file=sys.stderr)
        for error in report["errors"][:50]:
            print(error, file=sys.stderr)
        if len(report["errors"]) > 50:
            print(f"{len(report['errors']) - 50} additional violations", file=sys.stderr)
        return 1
    print(f"Architecture check passed: {report['files']} Python files, {report['callables']} callable blocks, "
          f"maximum CC {report['maximum_complexity']}/{MAX_COMPLEXITY}, Radon {report['radon_version']}; "
          "domain and HTTP import boundaries preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
