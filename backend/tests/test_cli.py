"""The documented local command surface matches the real argument parser."""

import json
from pathlib import Path

import pytest

from scopegate.cli import authorize_operations, parser
from scopegate.errors import AppError


def test_command_contract_matches_parser():
    contract = json.loads(
        (Path(__file__).resolve().parents[2] / "specs/contracts/local-operations.json").read_text()
    )
    root = parser()
    commands = next(action for action in root._actions if action.dest == "command").choices
    assert set(commands) == {command["name"] for command in contract["commands"]}
    for command in contract["commands"]:
        required = {
            action.option_strings[0].removeprefix("--")
            for action in commands[command["name"]]._actions
            if action.required
        }
        flags = {
            action.option_strings[0].removeprefix("--")
            for action in commands[command["name"]]._actions
            if action.option_strings
        }
        documented = set(command["required_arguments"])
        assert documented <= flags
        assert required == documented - {"unscoped-writer-disabled"}


def test_operations_require_separate_secret(monkeypatch, tmp_path, settings):
    monkeypatch.delenv("SCOPEGATE_OPERATIONS_TOKEN", raising=False)
    with pytest.raises(AppError) as error:
        authorize_operations(None)
    assert error.value.status == 401
    file = tmp_path / "operations.key"
    file.write_text(settings.migration_ops_key)
    file.chmod(0o600)
    authorize_operations(str(file))
    monkeypatch.setenv("SCOPEGATE_OPERATIONS_TOKEN", "incorrect")
    with pytest.raises(AppError):
        authorize_operations(None)
