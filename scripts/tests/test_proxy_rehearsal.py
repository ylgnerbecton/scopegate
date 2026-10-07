"""Automatic-IPAM platforms must retain the real proxy recovery assertions."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rehearse_proxy as proxy


class AutomaticIpamDocker:
    """Model Linux Docker rejecting static addresses on automatic subnets."""

    def __init__(self, *, same_address=False, replace_web=False, fail_replacement=False, no_old_address=False):
        self.old_address = "172.28.0.7"
        self.api_address = self.old_address
        self.api_present = True
        self.probes = {}
        self.probe_addresses = []
        self.web = "web-original"
        self.same_address = same_address
        self.replace_web = replace_web
        self.fail_replacement = fail_replacement
        self.no_old_address = no_old_address
        self.up_attempts = 0
        self.static_requests = 0
        self.history = []

    def result(self, stdout="", *, exit_code=0, stderr=""):
        return SimpleNamespace(returncode=exit_code, stdout=stdout, stderr=stderr)

    def run(self, root, arguments, timeout=30):
        self.history.append(tuple(arguments))
        if arguments == ["docker", "compose", "ps", "-q", "web"]:
            return self.result(self.web)
        if arguments == ["docker", "compose", "ps", "-q", "api"]:
            return self.result("api-current" if self.api_present else "")
        if arguments == ["docker", "inspect", "api-current"]:
            assert self.api_present
            return self.result(json.dumps([{
                "Config": {"Labels": {"com.docker.compose.project": "scopegate"}, "Image": "synthetic-api"},
                "NetworkSettings": {"Networks": {"scopegate_default": {"IPAddress": self.api_address}}},
            }]))
        if arguments[:4] == ["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}"]:
            return self.result(json.dumps({
                "scopegate_default": {"IPAddress": self.probes[arguments[4]]},
            }))
        if arguments == ["docker", "compose", "rm", "--stop", "--force", "api"]:
            self.api_present = False
            return self.result()
        if arguments[:3] == ["docker", "run", "--detach"]:
            if "--ip" in arguments:
                self.static_requests += 1
                return self.result(exit_code=125, stderr=(
                    "user specified IP address is supported only when connecting to networks "
                    "with user configured subnets"
                ))
            assert not self.api_present
            assert arguments[arguments.index("--network") + 1] == "scopegate_default"
            name = arguments[arguments.index("--name") + 1]
            assert name not in self.probes
            index = len(self.probe_addresses)
            if self.no_old_address:
                address = f"172.28.0.{20 + index}"
            else:
                address = "172.28.0.5" if index == 0 else self.old_address
            self.probes[name] = address
            self.probe_addresses.append(address)
            return self.result("probe-container")
        if arguments == ["docker", "compose", "up", "--detach", "--no-deps", "api"]:
            self.up_attempts += 1
            if self.fail_replacement and self.up_attempts == 1:
                return self.result(exit_code=1, stderr="Synthetic replacement startup failure")
            if self.api_present:
                return self.result()
            self.api_present = True
            reserved = self.old_address in self.probes.values()
            self.api_address = self.old_address if self.same_address or not reserved else "172.28.0.8"
            if self.replace_web:
                self.web = "web-recreated"
            return self.result()
        if arguments[:3] == ["docker", "rm", "--force"]:
            for name in arguments[3:]:
                assert name in self.probes
                del self.probes[name]
            return self.result()
        raise AssertionError(f"Unmodeled Docker command: {arguments[:3]}")

    def client(self, **kwargs):
        docker = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                assert url == "http://localhost:5187/health/ready"
                return httpx.Response(200 if docker.api_present else 503, json={"status": "ready"})

        return Client()


def install(monkeypatch, tmp_path, **options):
    docker = AutomaticIpamDocker(**options)
    monkeypatch.setattr(proxy, "ROOT", tmp_path)
    monkeypatch.setattr(proxy, "run_tool", docker.run)
    monkeypatch.setattr(proxy.httpx, "Client", docker.client)
    return docker


def test_automatic_subnet_replacement_changes_address_and_preserves_web(monkeypatch, tmp_path):
    docker = install(monkeypatch, tmp_path)
    proxy.main()
    report = json.loads((tmp_path / "artifacts/operations/proxy-recovery.json").read_text())
    assert docker.static_requests == 0
    assert docker.probe_addresses == ["172.28.0.5", docker.old_address]
    assert docker.api_address != docker.old_address and docker.api_present
    assert docker.web == "web-original" and not docker.probes
    assert docker.up_attempts == 2
    assert report["passed"] is True and report["upstream_address_changed"] is True
    assert report["web_recreated"] is False and report["observed_http_statuses"] == [200]


@pytest.mark.parametrize("options,message", [
    ({"same_address": True}, "did not replace the upstream address"),
    ({"replace_web": True}, "without being recreated"),
])
def test_replacement_proof_rejects_unchanged_address_or_recreated_web(
    monkeypatch, tmp_path, options, message,
):
    docker = install(monkeypatch, tmp_path, **options)
    with pytest.raises(proxy.ReleaseFailure, match=message):
        proxy.main()
    assert not docker.probes and docker.api_present
    assert docker.up_attempts == 2
    assert not (tmp_path / "artifacts/operations/proxy-recovery.json").exists()


def test_failed_replacement_removes_probe_and_restores_api(monkeypatch, tmp_path):
    docker = install(monkeypatch, tmp_path, fail_replacement=True)
    with pytest.raises(proxy.ReleaseFailure, match="Synthetic replacement startup failure"):
        proxy.main()
    assert not docker.probes and docker.api_present
    assert docker.up_attempts == 2 and docker.web == "web-original"
    assert docker.history[-2][:3] == ("docker", "rm", "--force")
    assert docker.history[-1] == ("docker", "compose", "up", "--detach", "--no-deps", "api")
    assert not (tmp_path / "artifacts/operations/proxy-recovery.json").exists()


def test_reservation_limit_rejects_missing_old_address_and_restores_api(monkeypatch, tmp_path):
    docker = install(monkeypatch, tmp_path, no_old_address=True)
    with pytest.raises(proxy.ReleaseFailure):
        proxy.main()
    assert len(docker.probe_addresses) == 8
    assert docker.old_address not in docker.probe_addresses
    assert docker.static_requests == 0 and not docker.probes
    assert docker.api_present and docker.api_address == docker.old_address
    assert docker.up_attempts == 1 and docker.web == "web-original"
    assert not (tmp_path / "artifacts/operations/proxy-recovery.json").exists()


@pytest.mark.parametrize("stream", ["stderr", "stdout"])
def test_failed_command_diagnostic_identifies_stage_and_redacts_private_values(
    monkeypatch, tmp_path, stream,
):
    secret = "synthetic-private-diagnostic-value"
    monkeypatch.setenv("SCOPEGATE_DIAGNOSTIC_SECRET", secret)
    monkeypatch.setattr(proxy, "ROOT", tmp_path)
    diagnostic = f"{tmp_path}/scratch {secret} /accept#token=synthetic-private-token"
    result = SimpleNamespace(returncode=125, stderr="", stdout="")
    setattr(result, stream, diagnostic)
    monkeypatch.setattr(proxy, "run_tool", lambda *args, **kwargs: result)
    with pytest.raises(proxy.ReleaseFailure) as raised:
        proxy.run(["docker", "run", "--detach", "--env", "private=" + secret])
    message = str(raised.value)
    assert "docker run --detach" in message and "125" in message
    assert all(value not in message for value in (str(tmp_path), secret, "synthetic-private-token", "--env"))
    assert "[REDACTED]" in message and "<workspace>" in message
