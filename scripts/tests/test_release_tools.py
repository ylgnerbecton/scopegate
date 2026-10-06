"""Exercise release boundaries using real tiny commands and isolated Git fixtures."""

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_evidence import EvidenceFailure, gate_check
from package_review import (
    ARCHIVE_MANIFEST,
    archive_index,
    committed_inventory,
    package_files,
    verified_references,
    verify_archive,
    write_archive,
)
from record_evidence import (
    browser_results,
    execute_gate,
    gate_environment,
    junit_results,
    scenario_proof,
    standalone_reports,
    vitest_results,
)
from record_evidence import (
    test_gate as named_test_gate,
)
from release_support import (
    MANIFEST,
    ReleaseFailure,
    artifact,
    clean_revision,
    run_tool,
    sanitize,
    sanitize_file,
    secret_values,
    topological_gates,
    write_json,
)


def tiny_gate(root, target, body):
    (root / "Makefile").write_text(target + ":\n\t" + body + "\n")
    return {"id": "G-LINT", "planned_entrypoint": "make " + target, "depends_on": []}


def execute_fixture(root, gate):
    return execute_gate(root, gate, "f" * 40, root / "artifacts/gate", [], os.environ.copy(), [], 10)


def commit_fixture(root):
    (root / "specs").mkdir(exist_ok=True)
    write_json(root / MANIFEST, {"fixture": "runner boundary"})
    (root / ".gitignore").write_text("artifacts/\n.env\n")
    (root / "README.md").write_text("Synthetic runner fixture.\n")
    commands = [
        ["git", "init", "--quiet"], ["git", "add", "."],
        ["git", "-c", "user.name=Release fixture", "-c", "user.email=fixture@example.test",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
         "commit", "--quiet", "-m", "Synthetic runner fixture"],
    ]
    for arguments in commands:
        result = run_tool(root, arguments)
        assert result.returncode == 0, result.stderr
    return clean_revision(root)


def test_runner_rejects_missing_executable(tmp_path):
    gate = tiny_gate(tmp_path, "lint", "true")
    with patch("record_evidence.shutil.which", return_value=None):
        record, tests = execute_fixture(tmp_path, gate)
    assert record["status"] == "failed" and record["exit_code"] is None
    assert tests == []
    assert "Missing executable: make" in (tmp_path / "artifacts/gate/command.log").read_text()


def test_runner_preserves_real_nonzero_command_exit(tmp_path):
    record, tests = execute_fixture(tmp_path, tiny_gate(tmp_path, "lint", "exit 7"))
    assert record["status"] == "failed" and record["exit_code"] == 2
    assert tests == []
    actual = json.loads((tmp_path / "artifacts/gate/result.json").read_text())
    assert actual["exit_code"] == record["exit_code"]
    assert "Error 7" in (tmp_path / "artifacts/gate/command.log").read_text()


def test_runner_pass_records_real_command_and_hashed_artifacts(tmp_path):
    record, tests = execute_fixture(tmp_path, tiny_gate(tmp_path, "lint", "echo fixture-check-ran"))
    assert record["status"] == "passed" and record["exit_code"] == 0 and tests == []
    assert "fixture-check-ran" in (tmp_path / "artifacts/gate/command.log").read_text()
    assert record["started_at"] <= record["finished_at"]
    for reference in record["artifacts"]:
        assert hashlib.sha256((tmp_path / reference["path"]).read_bytes()).hexdigest() == reference["sha256"]


def test_runner_requires_committed_clean_revision(tmp_path):
    revision = commit_fixture(tmp_path)
    write_json(tmp_path / MANIFEST, {"generated": True})
    assert clean_revision(tmp_path) == revision
    (tmp_path / "README.md").write_text("Uncommitted behavior change.\n")
    with pytest.raises(ReleaseFailure, match="Uncommitted implementation"):
        clean_revision(tmp_path)


@pytest.mark.parametrize("child", ["skipped", "failure", "error"])
def test_runner_rejects_skipped_or_error_junit(tmp_path, child):
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuites><testsuite tests="1"><testcase file="test_example.py" name="test_example"><{child}/></testcase></testsuite></testsuites>')
    with pytest.raises(ReleaseFailure, match="skipped, failed or error"):
        junit_results(path)


def test_runner_requires_fresh_reports_and_named_test(tmp_path):
    with pytest.raises(ReleaseFailure, match="fresh JUnit"):
        junit_results(tmp_path / "missing.xml")
    results = {"G-IDENTITY": [{"file": "tests/test_identity.py", "name": "test_nonce[valid]", "result": "passed"}]}
    assert named_test_gate("backend/tests/test_identity.py::test_nonce", ["G-IDENTITY"], results) == "G-IDENTITY"
    with pytest.raises(ReleaseFailure, match="did not pass"):
        named_test_gate("backend/tests/test_identity.py::test_nonce", ["G-DATABASE"], results)


def test_release_gate_receives_all_predecessor_results(tmp_path):
    gates = [{"id": "G-RELEASE", "depends_on": ["G-LINT"]}, {"id": "G-LINT", "depends_on": []}]
    assert [item["id"] for item in topological_gates(gates)] == ["G-LINT", "G-RELEASE"]
    previous = [{"id": "G-LINT", "status": "passed", "exit_code": 0}]
    result = gate_environment(tmp_path, previous, {}, release=True)
    assert json.loads(result["SCOPEGATE_RELEASE_GATES"]) == previous
    ordinary = gate_environment(tmp_path, previous, {"SCOPEGATE_RELEASE_GATES": "stale-parent-state"})
    assert "SCOPEGATE_RELEASE_GATES" not in ordinary
    with pytest.raises(ReleaseFailure, match="cycle"):
        topological_gates([{"id": "G-LINT", "depends_on": ["G-LINT"]}])


def test_runner_blocks_release_after_failed_predecessor(tmp_path):
    gate = tiny_gate(tmp_path, "release", "touch executed")
    gate.update({"id": "G-RELEASE", "depends_on": ["G-LINT"]})
    previous = [{"id": "G-LINT", "status": "failed", "exit_code": 2}]
    record, _ = execute_gate(tmp_path, gate, "f" * 40, tmp_path / "artifacts/gate", previous, {}, [], 10)
    assert record["status"] == "blocked" and record["exit_code"] is None
    assert not (tmp_path / "executed").exists()


def test_runner_rejects_skipped_frontend_and_browser_results(tmp_path):
    frontend = tmp_path / "frontend.json"
    write_json(frontend, {"success": True, "numTotalTests": 1, "numPendingTests": 1})
    with pytest.raises(ReleaseFailure, match="failed, skipped or todo"):
        vitest_results(frontend)
    browser = tmp_path / "browser.json"
    write_json(browser, {"stats": {"skipped": 1}, "suites": []})
    with pytest.raises(ReleaseFailure, match="skipped tests"):
        browser_results(browser)


def browser_report_fixture(root):
    payloads = {
        "artifacts/browser/results.json": {"suites": [{"title": "Workspace"}], "stats": {"expected": 6}},
        "artifacts/browser/interaction-evidence.json": {
            "keyboard_traversals": [{"viewport": 375, "actions": ["Tab", "Enter"]}],
            "axe_scans": [{"violations": []}],
        },
        "artifacts/browser/tenant-delay-evidence.json": {
            "held_source": "cedar", "visible_destination": "birch", "old_response_released": True,
        },
    }
    for relative, payload in payloads.items():
        write_json(root / relative, payload)
    output = root / "artifacts/evidence/G-BROWSER"
    output.mkdir(parents=True)
    return output, payloads


def test_browser_reports_preserve_distinct_producer_contents(tmp_path):
    output, payloads = browser_report_fixture(tmp_path)
    reports = standalone_reports(tmp_path, "G-BROWSER", output)
    expected_names = ["browser-results.json", "interaction-evidence.json", "tenant-delay-evidence.json"]
    assert [path.name for path in reports] == expected_names
    assert len(set(reports)) == 3 and set(output.iterdir()) == set(reports)
    for source, destination in zip(payloads, reports, strict=True):
        assert destination.read_bytes() == (tmp_path / source).read_bytes()
        assert json.loads(destination.read_text()) == payloads[source]


def test_browser_report_destination_collision_fails_before_copy(tmp_path):
    output, payloads = browser_report_fixture(tmp_path)
    colliding = "artifacts/another/browser-results.json"
    write_json(tmp_path / colliding, {"different_producer": True})
    with (
        patch("record_evidence.OUTPUTS", {"G-BROWSER": [*payloads, colliding]}),
        pytest.raises(ReleaseFailure, match="Duplicate standalone report destinations"),
    ):
        standalone_reports(tmp_path, "G-BROWSER", output)
    assert list(output.iterdir()) == []
    assert json.loads((tmp_path / colliding).read_text()) == {"different_producer": True}


def test_browser_report_collection_preserves_existing_destination(tmp_path):
    output, _ = browser_report_fixture(tmp_path)
    previous = output / "browser-results.json"
    previous.write_bytes(b"Existing producer evidence must remain intact.\n")
    with pytest.raises(ReleaseFailure, match="destination already exists"):
        standalone_reports(tmp_path, "G-BROWSER", output)
    assert previous.read_bytes() == b"Existing producer evidence must remain intact.\n"
    assert list(output.iterdir()) == [previous]


def test_gate_verifier_rejects_duplicate_artifacts_with_valid_hashes(tmp_path):
    gate = tiny_gate(tmp_path, "lint", "echo verified-artifact-fixture")
    record, _ = execute_fixture(tmp_path, gate)
    with patch("check_evidence.ROOT", tmp_path):
        gate_check(record, gate, "f" * 40)
        record["artifacts"].append(record["artifacts"][0].copy())
        with patch("check_evidence.artifact_check") as artifact_verifier:
            with pytest.raises(EvidenceFailure, match="duplicate artifact paths"):
                gate_check(record, gate, "f" * 40)
            artifact_verifier.assert_not_called()


def test_sanitized_logs_remove_dotenv_and_failure_repr_secrets(tmp_path):
    secret = "fixture-session-value-947abc"
    (tmp_path / ".env").write_text(f'SCOPEGATE_SESSION_SECRET="{secret}"\nDATABASE_URL=postgresql://name:private-password@localhost/db\n')
    captured = f"Settings(session_secret='{secret}', database_url='postgresql://name:private-password@localhost/db') at {tmp_path}/backend; /auth/callback?code=private-code&state=private-state"
    cleaned = sanitize(captured, tmp_path, secret_values(tmp_path, {}))
    assert secret not in cleaned and "private-password" not in cleaned
    assert "private-code" not in cleaned and "private-state" not in cleaned
    assert str(tmp_path) not in cleaned and "<workspace>" in cleaned


def test_junit_sanitization_preserves_parseable_pass_results(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuites><testsuite tests="1"><testcase file="test_example.py" name="test_example"><system-out>root={tmp_path}; secret=fixture-sensitive-value</system-out></testcase></testsuite></testsuites>')
    sanitize_file(path, tmp_path, ["fixture-sensitive-value"])
    assert junit_results(path)[0]["name"] == "test_example"
    assert str(tmp_path) not in path.read_text() and "fixture-sensitive-value" not in path.read_text()


def test_junit_suite_error_counter_cannot_disagree_with_case_nodes(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuites><testsuite tests="1" errors="1"><testcase file="test_example.py" name="test_example"/></testsuite></testsuites>')
    with pytest.raises(ReleaseFailure, match="suite counts"):
        junit_results(path)


def test_documentary_proof_is_explicit_and_hashed(tmp_path):
    document = tmp_path / "README.md"
    document.write_text("Scope and limitations.\n")
    declaration = {"id": "F08-AC-02", "gate_ids": ["G-LINT"], "tests": [],
                   "documents": ["README.md"], "note": "Design exists"}
    with pytest.raises(ReleaseFailure, match="explicitly declared"):
        scenario_proof(tmp_path, declaration, {"G-LINT": {}}, {}, "f" * 40, tmp_path / "artifacts/evidence")
    declaration["note"] = "Documentary: scope and limitations are reviewed with runtime gate evidence."
    result = scenario_proof(tmp_path, declaration, {"G-LINT": {}}, {}, "f" * 40, tmp_path / "artifacts/evidence")
    proof = json.loads((tmp_path / result["artifact"]["path"]).read_text())
    assert proof["documentary_only"] is True
    assert proof["documents"][0]["sha256"] == hashlib.sha256(document.read_bytes()).hexdigest()


def test_packager_rejects_stale_nested_proof(tmp_path):
    path = tmp_path / "artifacts/evidence/run/scenarios/F08-AC-02.json"
    write_json(path, {"revision": "0" * 40, "documents": []})
    manifest = {"scenarios": [{"artifact": artifact(tmp_path, path)}]}
    with pytest.raises(ReleaseFailure, match="Stale nested proof"):
        verified_references(tmp_path, manifest, "f" * 40)


def test_public_package_excludes_credentials_and_unreferenced_failed_logs(tmp_path):
    (tmp_path / ".env").write_text("PRIVATE_PASSWORD=fixture-private\n")
    (tmp_path / ".env.example").write_text("PRIVATE_PASSWORD=replace-locally\n")
    commit_fixture(tmp_path)
    passed = tmp_path / "artifacts/evidence/run/G-LINT/command.log"
    passed.parent.mkdir(parents=True)
    passed.write_text("Command passed.\n")
    (passed.parent / "old-failed.log").write_text("Unreferenced failure.\n")
    inventory = committed_inventory(tmp_path)
    assert ".env" not in inventory and ".env.example" in inventory
    reference = artifact(tmp_path, passed)
    references = {reference["path"]: reference}
    files = package_files(tmp_path, inventory, references)
    assert reference["path"] in files
    assert not any(name.endswith("old-failed.log") or name == ".env" for name in files)


def test_packager_rejects_tracked_credential_input(tmp_path):
    (tmp_path / ".env").write_text("PRIVATE_PASSWORD=fixture-private\n")
    commit_fixture(tmp_path)
    assert run_tool(tmp_path, ["git", "add", "--force", ".env"]).returncode == 0
    with pytest.raises(ReleaseFailure, match="Credential file excluded"):
        committed_inventory(tmp_path)


def test_archive_hashes_detect_modified_contents(tmp_path):
    revision, files = "f" * 40, {"README.md": b"Public review source.\n"}
    index = archive_index(revision, files, {})
    path = tmp_path / "review.zip"
    write_archive(path, files, index)
    assert verify_archive(path, revision)["revision"] == revision
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(ARCHIVE_MANIFEST, json.dumps(index))
        archive.writestr("README.md", b"Altered after packaging.\n")
    with pytest.raises(ReleaseFailure, match="consistency failed"):
        verify_archive(path, revision)


def test_offline_archive_verification_needs_no_git_or_services(tmp_path):
    path, revision = tmp_path / "review.zip", "f" * 40
    files = {"Makefile": b"up:\n\tdocker compose up --build -d\n"}
    write_archive(path, files, archive_index(revision, files, {}))
    import subprocess

    environment = {**os.environ, "PATH": ""}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "package_review.py"),
                             "--verify", str(path)], cwd=tmp_path, env=environment,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0 and "offline review archive" in result.stdout
