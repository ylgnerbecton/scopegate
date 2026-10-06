"""Verify process credential boundaries without publishing resolved secrets."""

import json
import subprocess
from pathlib import Path


def test_compose_limits_each_process_to_required_credentials():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, "The owned Compose configuration could not be resolved"
    services = json.loads(result.stdout)["services"]
    for service in ["api", "worker", "identity"]:
        env = services[service]["environment"]
        assert "SCOPEGATE_DB_PASSWORD" not in env
        assert "SCOPEGATE_APP_DB_PASSWORD" not in env
        assert "SCOPEGATE_MIGRATION_OPS_KEY" not in env
        assert not env.get("SCOPEGATE_MIGRATION_DATABASE_URL")
    assert set(services["identity"]["environment"]) == {
        "SCOPEGATE_ENVIRONMENT", "SCOPEGATE_OIDC_ISSUER", "SCOPEGATE_OIDC_REDIRECT_URI",
    }
    assert not any(key.endswith(("PLATFORM_KEY", "CATALOG_KEY", "SESSION_SECRET", "CURSOR_SECRET"))
                   for key in services["worker"]["environment"])
    initializer = services["initialize"]["environment"]
    assert initializer["SCOPEGATE_DATABASE_URL"].split("@", 1)[0].split(":")[-1] != initializer["SCOPEGATE_MIGRATION_DATABASE_URL"].split("@", 1)[0].split(":")[-1]
