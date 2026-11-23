"""Testes da seam de provider (multipass pass-through × kind/docker)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app import provider
from app.ssh_runner import ProcResult


@pytest.fixture(autouse=True)
def _reset_provider(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.CKA_DIR", tmp_path)
    provider.reset()
    yield
    provider.reset()


def test_default_provider_is_multipass(monkeypatch) -> None:
    monkeypatch.delenv("CKA_PROVIDER", raising=False)
    assert provider.provider_name() == "multipass"
    assert provider.get().name == "multipass"
    assert provider.get().transport == "ssh"
    assert provider.get().manages_ssh_keys is True


def test_provider_file_selects_kind(monkeypatch, tmp_path) -> None:
    (tmp_path / "provider").write_text("kind\n")
    monkeypatch.delenv("CKA_PROVIDER", raising=False)
    assert provider.provider_name() == "kind"
    assert provider.get().name == "kind"
    assert provider.get().transport == "docker"


def test_env_overrides_provider_file(monkeypatch, tmp_path) -> None:
    (tmp_path / "provider").write_text("kind\n")
    monkeypatch.setenv("CKA_PROVIDER", "multipass")
    assert provider.provider_name() == "multipass"


def test_multipass_nodes_map_vms(monkeypatch) -> None:
    async def fake_list_vms():
        return {
            "controlplane": {"state": "Running", "ips": ["192.168.1.123"]},
            "node01": {"state": "Running", "ips": ["192.168.1.124"]},
            "node02": {"state": "Stopped", "ips": []},
        }

    async def fake_resolve(ips, port=22):
        return ips[0] if ips else None

    monkeypatch.setattr("app.provider.multipass.ssh_runner.list_vms", fake_list_vms)
    monkeypatch.setattr("app.provider.multipass.ssh_runner.resolve_ip", fake_resolve)
    nodes = asyncio.run(provider.get().nodes())
    assert nodes["controlplane"].ip == "192.168.1.123"
    assert nodes["node02"].state == "Stopped" and nodes["node02"].ip is None


def test_multipass_exec_routes_to_ssh(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_list_vms():
        return {n: {"state": "Running", "ips": ["10.0.0.1"]} for n in ("controlplane", "node01", "node02")}

    async def fake_resolve(ips, port=22):
        return "10.0.0.1"

    async def fake_ssh(ip, command, timeout=20):
        calls.append(("ssh", ip, command))
        return ProcResult(0, "ok", "")

    async def fake_sudo(ip, command, timeout=20, password=None):
        calls.append(("sudo", ip, command))
        return ProcResult(0, "ok", "")

    monkeypatch.setattr("app.provider.multipass.ssh_runner.list_vms", fake_list_vms)
    monkeypatch.setattr("app.provider.multipass.ssh_runner.resolve_ip", fake_resolve)
    monkeypatch.setattr("app.provider.multipass.ssh_runner.ssh_run", fake_ssh)
    monkeypatch.setattr("app.provider.multipass.ssh_runner.sudo_run", fake_sudo)

    asyncio.run(provider.get().exec("node01", "hostname"))
    asyncio.run(provider.get().exec("node01", "systemctl restart kubelet", sudo=True))
    assert calls == [("ssh", "10.0.0.1", "hostname"),
                     ("sudo", "10.0.0.1", "systemctl restart kubelet")]


def test_multipass_terminal_command_is_ssh_alias() -> None:
    assert provider.get().terminal_command("node01") == ["ssh", "cka-node01"]


def test_kind_nodes_use_mapping_and_docker(monkeypatch, tmp_path) -> None:
    (tmp_path / "nodes.json").write_text(json.dumps({
        "controlplane": {"container": "cka-control-plane", "node": "cka-control-plane"},
        "node01": {"container": "cka-worker", "node": "cka-worker"},
        "node02": {"container": "cka-worker2", "node": "cka-worker2"},
    }))
    monkeypatch.setenv("CKA_PROVIDER", "kind")

    async def fake_docker(args, timeout=20):
        assert args[0] == "inspect"
        return ProcResult(0, "true", "")

    monkeypatch.setattr("app.provider.kind._docker", fake_docker)
    nodes = asyncio.run(provider.get().nodes())
    assert nodes["node01"].container == "cka-worker"
    assert nodes["node01"].real_name == "cka-worker"
    assert nodes["controlplane"].state == "Running"


def test_kind_exec_uses_docker_exec(monkeypatch, tmp_path) -> None:
    (tmp_path / "nodes.json").write_text(json.dumps({
        "node01": {"container": "cka-worker", "node": "cka-worker"},
    }))
    monkeypatch.setenv("CKA_PROVIDER", "kind")
    seen: list[list[str]] = []

    async def fake_docker(args, timeout=20):
        seen.append(args)
        return ProcResult(0, "ok", "")

    monkeypatch.setattr("app.provider.kind._docker", fake_docker)
    res = asyncio.run(provider.get().exec("node01", "cat /etc/hostname", sudo=True))
    assert res.ok
    assert seen[-1] == ["exec", "cka-worker", "sh", "-lc", "cat /etc/hostname"]


def test_kind_terminal_command_uses_docker_exec_it(monkeypatch, tmp_path) -> None:
    (tmp_path / "nodes.json").write_text(json.dumps({
        "node02": {"container": "cka-worker2", "node": "cka-worker2"},
    }))
    monkeypatch.setenv("CKA_PROVIDER", "kind")
    assert provider.get().terminal_command("node02") == [
        "docker", "exec", "-it", "cka-worker2", "bash",
    ]
