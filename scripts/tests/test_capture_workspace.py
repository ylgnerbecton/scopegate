"""Isolation and cleanup ownership for the real screenshot capture deployment."""

import copy
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "capture_workspace.py"
SPEC = importlib.util.spec_from_file_location("capture_workspace", SOURCE)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def canonical():
    backend = {"build": {"context": ".", "dockerfile": "backend/Dockerfile"},
               "environment": {"SCOPEGATE_DATABASE_URL": "original-runtime-url",
                               "SCOPEGATE_OUTBOX_KEY": "original-outbox-key"},
               "labels": {}, "ports": [{"published": "8457", "target": 8457}]}
    services = {name: copy.deepcopy(backend) for name in ("initialize", "identity", "api", "worker")}
    services["initialize"]["environment"].update({
        "SCOPEGATE_MIGRATION_DATABASE_URL": "original-admin-url",
        "SCOPEGATE_PUBLIC_ORIGIN": "http://localhost:5187",
        "SCOPEGATE_OIDC_ISSUER": "http://localhost:8901"})
    for name in ("identity", "api"):
        services[name]["environment"].update({"SCOPEGATE_OIDC_ISSUER": "http://localhost:8901",
                                              "SCOPEGATE_OIDC_REDIRECT_URI": "http://localhost:5187/auth/callback"})
    services["api"]["environment"]["SCOPEGATE_PUBLIC_ORIGIN"] = "http://localhost:5187"
    services["api"]["environment"]["SCOPEGATE_OIDC_INTERNAL_URL"] = "http://identity:8901"
    services["database"] = {"environment": {"POSTGRES_PASSWORD": "original-password"},
                            "ports": [{"published": "5547", "target": 5432}]}
    services["web"] = {"build": {"context": "./frontend"}, "ports": [{"published": "5187", "target": 8080}]}
    return {"name": "scopegate", "services": services,
            "volumes": {"database": {"name": "scopegate_database"}},
            "networks": {"default": {"name": "scopegate_default"}}}


def test_capture_has_independent_endpoints_secrets_images_and_volume_ownership():
    source = canonical()
    preserved = copy.deepcopy(source)
    owner = "a1b2c3d4e5f6"
    result = capture.capture_configuration(source, owner, 5189, 8902)
    assert source == preserved
    project = "scopegate-capture-a1b2c3d4e5f6"
    assert result["name"] == project
    assert result["volumes"]["database"]["name"] == f"{project}_database"
    assert result["networks"]["default"]["name"] == f"{project}_default"
    for name in ("database", "initialize", "api", "worker"):
        assert "ports" not in result["services"][name]
    for name in ("initialize", "identity", "api", "worker"):
        assert result["services"][name]["image"] == f"{project}-backend:local"
        assert result["services"][name]["labels"][capture.OWNER_LABEL] == owner
        assert result["services"][name]["build"]["labels"][capture.OWNER_LABEL] == owner
    assert result["services"]["web"]["image"] == f"{project}-web:local"
    assert result["services"]["identity"]["environment"]["SCOPEGATE_OIDC_REDIRECT_URI"] == "http://localhost:5189/auth/callback"
    assert result["services"]["api"]["environment"]["SCOPEGATE_OIDC_ISSUER"] == "http://localhost:8902"
    assert result["services"]["api"]["environment"]["SCOPEGATE_OIDC_INTERNAL_URL"] == "http://identity:8901"
    assert result["services"]["initialize"]["environment"]["SCOPEGATE_PUBLIC_ORIGIN"] == "http://localhost:5189"
    assert result["services"]["database"]["environment"]["POSTGRES_PASSWORD"] != "original-password"
    assert result["services"]["initialize"]["environment"]["SCOPEGATE_DATABASE_URL"] == result["services"]["api"]["environment"]["SCOPEGATE_DATABASE_URL"]
    assert result["services"]["initialize"]["environment"]["SCOPEGATE_OUTBOX_KEY"] == result["services"]["worker"]["environment"]["SCOPEGATE_OUTBOX_KEY"]


def test_capture_refuses_external_storage_and_ambiguous_ports():
    source = canonical()
    source["volumes"]["database"]["external"] = True
    with pytest.raises(ValueError, match="externally owned"):
        capture.capture_configuration(source, "a1b2c3d4e5f6", 5189, 8902)
    with pytest.raises(ValueError, match="distinct unprivileged"):
        capture.capture_configuration(canonical(), "a1b2c3d4e5f6", 5189, 5189)


@pytest.mark.parametrize("kind", ["container", "volume", "network"])
def test_cleanup_requires_both_project_and_capture_owner_for_every_resource(kind):
    project, owner = "scopegate-capture-a1b2c3d4e5f6", "a1b2c3d4e5f6"
    labels = {"com.docker.compose.project": project, capture.OWNER_LABEL: owner}
    resource = {"Config": {"Labels": labels}} if kind == "container" else {"Labels": labels}
    capture.assert_owned([resource], project, owner, kind)
    foreign = copy.deepcopy(resource)
    foreign_labels = foreign["Config"]["Labels"] if kind == "container" else foreign["Labels"]
    foreign_labels[capture.OWNER_LABEL] = "another-owner"
    with pytest.raises(RuntimeError, match="Refusing to remove"):
        capture.assert_owned([resource, foreign], project, owner, kind)
    foreign_labels[capture.OWNER_LABEL] = owner
    foreign_labels["com.docker.compose.project"] = "scopegate"
    with pytest.raises(RuntimeError, match="Refusing to remove"):
        capture.assert_owned([foreign], project, owner, kind)


def test_capture_diagnostics_redact_configuration_secrets_and_identity_redirect_values():
    diagnostic = "database-password http://localhost:5189/auth/callback?code=private-code&state=private-state /accept#token=private-token"
    redacted = capture.redact(diagnostic, {"database-password"})
    assert all(value not in redacted for value in ("database-password", "private-code", "private-state", "private-token"))
    assert redacted.count("[redacted]") == 4
    headers = "Cookie: opaque-session\nX-CSRF-Token: csrf-value\nAuthorization: Bearer access-value"
    protected = capture.redact(headers, set())
    assert all(value not in protected for value in ("opaque-session", "csrf-value", "access-value"))
