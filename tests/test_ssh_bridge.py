"""Testes dos helpers puros da ponte SSH (sem tocar no cluster)."""

from __future__ import annotations

from pathlib import Path

from app import config
from app.ssh_runner import (
    bridge_ips,
    render_ssh_block,
    rewrite_kubeconfig_server,
    write_managed_ssh_config,
)

KUBECONFIG_SAMPLE = """apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: AAAA
    server: https://192.168.1.99:6443
  name: kubernetes
contexts:
- context:
    cluster: kubernetes
    user: kubernetes-admin
  name: kubernetes-admin@kubernetes
current-context: kubernetes-admin@kubernetes
kind: Config
"""


def test_rewrite_kubeconfig_server_only_touches_server_line() -> None:
    out = rewrite_kubeconfig_server(KUBECONFIG_SAMPLE, "192.168.1.123")
    assert "server: https://192.168.1.123:6443" in out
    assert "certificate-authority-data: AAAA" in out
    assert "current-context: kubernetes-admin@kubernetes" in out
    assert "192.168.1.99" not in out


def test_rewrite_kubeconfig_same_ip_is_noop_but_valid() -> None:
    out = rewrite_kubeconfig_server(KUBECONFIG_SAMPLE, "192.168.1.99")
    assert out == KUBECONFIG_SAMPLE


def test_rewrite_kubeconfig_raises_without_server_line() -> None:
    import pytest

    with pytest.raises(ValueError):
        rewrite_kubeconfig_server("apiVersion: v1\n", "192.168.1.123")


def test_bridge_ips_excludes_nat_and_overlay() -> None:
    assert bridge_ips(["192.168.252.3", "192.168.1.123", "10.38.0.1"]) == ["192.168.1.123"]
    assert bridge_ips(["192.168.252.4"]) == []


def test_render_ssh_block_contains_aliases_and_ips() -> None:
    block = render_ssh_block(
        {"controlplane": "192.168.1.123", "node01": "192.168.1.124", "node02": "192.168.1.125"}
    )
    assert config.SSH_BLOCK_START in block and config.SSH_BLOCK_END in block
    assert "Host cka-controlplane" in block and "HostName 192.168.1.123" in block
    assert "Host cka-node02" in block and "HostName 192.168.1.125" in block
    assert "BatchMode" not in block


def test_write_managed_block_is_idempotent_and_preserves_user_config(tmp_path: Path) -> None:
    ssh_config = tmp_path / "config"
    ssh_config.write_text("Host github.com\n  HostName github.com\n  User git\n")

    ips_v1 = {"controlplane": "192.168.1.123", "node01": "192.168.1.124", "node02": "192.168.1.125"}
    write_managed_ssh_config(ips_v1, path=ssh_config)

    ips_v2 = {"controlplane": "192.168.1.200", "node01": "192.168.1.124", "node02": "192.168.1.125"}
    write_managed_ssh_config(ips_v2, path=ssh_config)
    final = ssh_config.read_text()

    assert final.count(config.SSH_BLOCK_START) == 1
    assert final.count(config.SSH_BLOCK_END) == 1
    assert "Host github.com" in final
    assert "HostName 192.168.1.200" in final
    assert "192.168.1.123" not in final
