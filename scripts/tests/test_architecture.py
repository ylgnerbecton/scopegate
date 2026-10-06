"""Negative source fixtures keep the static boundary gate fail closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_architecture import ArchitectureFailure, check, inventory, main


@pytest.fixture
def source_tree(tmp_path):
    for name in ["backend/src/scopegate/domain/policy.py", "backend/src/scopegate/api/access.py", "identity_provider/app.py"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def valid():\n    return True\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("source", [
    "import sqlalchemy as store\n",
    "from fastapi import HTTPException as Error\n",
    "from scopegate import db as store\n",
    "import scopegate as application\n",
    "from .. import config as settings\n",
    "def evaluate():\n    from ..services.access import apply_diff as mutate\n",
    "import identity_provider.app as provider\n",
    "from urllib.request import urlopen\n",
    "import os\n",
    "from pathlib import Path\n",
    "from subprocess import run\n",
    "import tempfile\n",
    "from importlib import import_module as load\n",
    "def evaluate():\n    return __import__('scopegate.db')\n",
    "from builtins import __import__ as load\n",
    "import builtins as library\ndef evaluate():\n    return library.__import__('scopegate.db')\n",
])
def test_domain_rejects_adapter_dependencies_including_aliases_and_nested_imports(source_tree, source):
    (source_tree / "backend/src/scopegate/domain/policy.py").write_text(source, encoding="utf-8")
    errors = check(source_tree)["errors"]
    assert errors and all("domain/policy.py" in error for error in errors)


@pytest.mark.parametrize("source", [
    "import sqlalchemy as store\n",
    "from scopegate import db as store\n",
    "from ..journal import prepare as prepare_command\n",
    "def route():\n    from .. import seed\n",
    "from ..bootstrap import bootstrap\n",
    "from scopegate.services.common import audit as record\n",
    "from scopegate.services.access import transaction as atomic\n",
    "from scopegate.cli import main\n",
    "from psycopg import connect\n",
    "import httpx as client\n",
    "from urllib.request import urlopen\n",
    "import http.client as client\n",
    "from subprocess import run\n",
    "from importlib import import_module as load\n",
    "import identity_provider.app as provider\n",
])
def test_http_adapters_reject_direct_or_reexported_infrastructure(source_tree, source):
    (source_tree / "backend/src/scopegate/api/access.py").write_text(source, encoding="utf-8")
    errors = check(source_tree)["errors"]
    assert errors and all("api/access.py" in error for error in errors)


def test_standard_value_types_domain_relative_imports_and_service_delegation_are_allowed(source_tree):
    (source_tree / "backend/src/scopegate/domain/policy.py").write_text(
        "from dataclasses import dataclass\nfrom datetime import datetime\nfrom . import values\n",
        encoding="utf-8",
    )
    (source_tree / "backend/src/scopegate/api/access.py").write_text(
        "from fastapi import APIRouter\nfrom pydantic import BaseModel\n"
        "from ..services import access\nfrom scopegate.services.common import expected_version as parse\n"
        "from scopegate.config import get_settings\nfrom ..dependencies import actor\n",
        encoding="utf-8",
    )
    assert check(source_tree)["errors"] == []


@pytest.mark.parametrize("relative", ["backend/src/scopegate/services/future.py", "identity_provider/future.py"])
def test_complexity_cap_covers_services_and_provider(source_tree, relative):
    path = source_tree / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def branch(value):\n" + "".join(f"    if value == {i}:\n        return {i}\n" for i in range(10)), encoding="utf-8")
    assert any("CC 11" in error and relative in error for error in check(source_tree)["errors"])


def test_nested_callable_cannot_hide_its_complexity_inside_a_simple_outer_function(source_tree):
    path = source_tree / "identity_provider/app.py"
    path.write_text("def outer():\n    def branch(value):\n" + "".join(f"        if value == {i}:\n            return {i}\n" for i in range(10)) + "    return branch\n", encoding="utf-8")
    assert any("branch has CC 11" in error for error in check(source_tree)["errors"])


@pytest.mark.parametrize("source", ["def invalid(:\n", "from ...db import transaction\n"])
def test_invalid_syntax_or_escaping_relative_import_cannot_pass(source_tree, source):
    (source_tree / "backend/src/scopegate/api/access.py").write_text(source, encoding="utf-8")
    assert check(source_tree)["errors"]


def test_missing_source_tree_cannot_be_a_vacuous_pass(tmp_path):
    with pytest.raises(ArchitectureFailure, match="required source directory"):
        check(tmp_path)


def test_empty_boundary_tree_cannot_hide_a_removed_component(source_tree):
    (source_tree / "backend/src/scopegate/domain/policy.py").unlink()
    with pytest.raises(ArchitectureFailure, match="source inventory is empty"):
        check(source_tree)


def test_directory_inventory_errors_are_failures(source_tree, monkeypatch):
    def walk(path, onerror):
        onerror(PermissionError("directory is unavailable"))

    monkeypatch.setattr("check_architecture.os.walk", walk)
    with pytest.raises(ArchitectureFailure, match="Source inventory failed: PermissionError"):
        inventory(source_tree)


def test_invalid_encoding_is_a_failed_check(source_tree):
    (source_tree / "backend/src/scopegate/domain/policy.py").write_bytes(b"\xff")
    assert any("UnicodeDecodeError" in error for error in check(source_tree)["errors"])


def test_command_returns_nonzero_for_a_boundary_violation(source_tree, monkeypatch, capsys):
    (source_tree / "backend/src/scopegate/api/access.py").write_text("import sqlalchemy\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_architecture.py", "--root", str(source_tree)])
    assert main() == 1
    assert "HTTP adapters must delegate" in capsys.readouterr().err


def test_linked_source_cannot_escape_the_inventory(source_tree, tmp_path_factory):
    external = tmp_path_factory.mktemp("external") / "hidden.py"
    external.write_text("import sqlalchemy\n", encoding="utf-8")
    (source_tree / "backend/src/scopegate/domain/hidden.py").symlink_to(external)
    with pytest.raises(ArchitectureFailure, match="linked source"):
        check(source_tree)


def test_unreadable_source_is_a_failed_check(source_tree, monkeypatch):
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path.name == "policy.py":
            raise PermissionError("source is unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert any("PermissionError" in error for error in check(source_tree)["errors"])


def test_current_source_satisfies_the_architecture_constraints():
    report = check(Path(__file__).resolve().parents[2])
    assert report["errors"] == [], "\n".join(report["errors"])
    assert report["files"] >= 37 and report["callables"] > 0
    assert report["maximum_complexity"] <= 10
