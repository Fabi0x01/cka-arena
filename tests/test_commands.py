"""Testes do dispatcher de ferramentas locais (kubectl/helm)."""

from __future__ import annotations

import asyncio

from app import commands, config
from app.ssh_runner import ProcResult


def test_helm_runs_with_dedicated_kubeconfig(monkeypatch) -> None:
    captured: dict = {}

    async def fake_run_local(cmd, *, timeout=20, stdin_data=None, env=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return ProcResult(0, "", "")

    monkeypatch.setattr(commands, "run_local", fake_run_local)
    res = asyncio.run(commands.run_tool_command("helm list -n default"))
    assert res.ok
    assert captured["cmd"][0] == "helm"
    assert captured["env"]["KUBECONFIG"] == str(config.KUBECONFIG_PATH)


def test_kubectl_uses_cluster_wrapper(monkeypatch) -> None:
    captured: dict = {}

    async def fake_kubectl(args, timeout=20, stdin_data=None):
        captured["args"] = args
        return ProcResult(0, "", "")

    monkeypatch.setattr(commands.cluster, "kubectl", fake_kubectl)
    asyncio.run(commands.run_tool_command("kubectl get pods -A"))
    assert captured["args"] == ["get", "pods", "-A"]


def test_disallowed_tool_is_rejected() -> None:
    import pytest

    with pytest.raises(commands.CommandRejected):
        asyncio.run(commands.run_tool_command("bash -c rm -rf /"))
