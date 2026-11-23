"""Testes do motor de checks: comparadores, classificação e orquestração."""

from __future__ import annotations

import asyncio

import pytest

from app import validator
from app.models import CheckSpec
from app.validator import ERROR, FAIL, PASS, SKIP


def test_compare_operators() -> None:
    assert validator.compare("nginx:1.27-alpine", "equals", "nginx:1.27-alpine")
    assert not validator.compare("nginx", "equals", "nginx:alpine")
    assert validator.compare("hello world", "contains", "world")
    assert validator.compare("3", "gte", 3)
    assert not validator.compare("2", "gte", 3)
    assert validator.compare("200", "regex", r"^2\d\d$")
    assert validator.compare("a,b,c", "len_gte", 3)
    assert not validator.compare("a,b", "len_gte", 3)
    with pytest.raises(ValueError):
        validator.compare("x", "nope", "x")


def test_classify_infra_vs_user_failure() -> None:
    from app.ssh_runner import ProcResult

    assert validator.classify(ProcResult(0, "ok", "")) == PASS
    assert validator.classify(ProcResult(1, "", 'Error from server (NotFound): pods "x" not found')) == FAIL
    assert validator.classify(ProcResult(1, "", "The connection to the server was refused")) == ERROR
    assert validator.classify(ProcResult(-1, "", "timeout after 10s")) == ERROR


def test_run_all_all_or_nothing(monkeypatch) -> None:
    async def ok(_params):
        return PASS, {"ok": True}

    async def fail(_params):
        return FAIL, {"ok": False}

    monkeypatch.setitem(validator.CHECKS, "kubectl_resource_exists", ok)
    monkeypatch.setitem(validator.CHECKS, "pod_status_ready", fail)

    checks = [
        CheckSpec(id="a", description="a", type="kubectl_resource_exists", params={}),
        CheckSpec(id="b", description="b", type="pod_status_ready", params={}),
    ]
    report = asyncio.run(validator.run_all(checks))
    assert report["all_passed"] is False
    assert [r["status"] for r in report["results"]] == [PASS, FAIL]
    assert all(r["duration_ms"] >= 0 for r in report["results"])


def test_error_retries_twice_before_giving_up(monkeypatch) -> None:
    calls = {"n": 0}

    async def always_error(_params):
        calls["n"] += 1
        return ERROR, {"error": "boom"}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setitem(validator.CHECKS, "node_status_ready", always_error)
    monkeypatch.setattr(validator.asyncio, "sleep", no_sleep)

    spec = CheckSpec(id="n", description="n", type="node_status_ready", params={})
    result = asyncio.run(validator.run_check(spec))
    assert result["status"] == ERROR
    assert calls["n"] == 3  # 1 execução + 2 retries


def test_skip_carries_reason_and_hint(monkeypatch) -> None:
    async def skip(_params):
        return SKIP, {"reason": "no pods"}

    monkeypatch.setitem(validator.CHECKS, "pod_exec_exit_zero", skip)
    spec = CheckSpec(
        id="s", description="s", type="pod_exec_exit_zero", params={}, failure_hint="hint"
    )
    result = asyncio.run(validator.run_check(spec))
    assert result["status"] == SKIP
    assert result["hint"] == "hint"
    assert result["evidence"]["reason"] == "no pods"


def test_auth_can_i_no_with_rc1_is_evaluated_correctly(monkeypatch) -> None:
    from app.ssh_runner import ProcResult

    async def fake_kubectl(_args, timeout=10):
        return ProcResult(1, "no\n", "")  # kubectl sai 1 quando a resposta é "no"

    monkeypatch.setattr(validator.cluster, "kubectl", fake_kubectl)
    params = {"verb": "delete", "resource": "pods", "service_account": "sa",
              "namespace": "ns", "expected_allowed": False}
    status, evidence = asyncio.run(validator.chk_kubectl_auth_can_i(params))
    assert status == PASS, evidence


def test_normalize_params_aliases() -> None:
    p = validator.normalize_params("kubectl_jsonpath", {"resource": "deployment", "name": "web", "expected_count": 2})
    assert p["kind"] == "deployment" and p["operator"] == "len_gte" and p["expected"] == 2
    p = validator.normalize_params("pod_status_ready", {"namespace": "x", "ready": 2, "selector": "app=web"})
    assert p["min_ready"] == 2 and p["label_selector"] == "app=web"
    p = validator.normalize_params("pod_exec_exit_zero", {"namespace": "x", "name": "client", "command": ["curl", "-sf", "http://x"]})
    assert p["pod_name"] == "client"


def test_run_check_catches_param_crash(monkeypatch) -> None:
    async def boom(_params):
        raise KeyError("kind")

    monkeypatch.setitem(validator.CHECKS, "kubectl_jsonpath", boom)
    spec = CheckSpec(id="x", description="x", type="kubectl_jsonpath", params={})
    result = asyncio.run(validator.run_check(spec))
    assert result["status"] == ERROR
    assert "KeyError" in result["evidence"]["error"]


def test_jsonpath_list_mode_queries_with_selector(monkeypatch) -> None:
    from app import validator
    from app.ssh_runner import ProcResult

    seen: list[list[str]] = []

    async def fake_kubectl(args, timeout=20, stdin_data=None):
        seen.append(args)
        return ProcResult(0, "node01 node01", "")

    monkeypatch.setattr(validator.cluster, "kubectl", fake_kubectl)
    status, evidence = asyncio.run(validator.chk_kubectl_jsonpath({
        "kind": "pods", "namespace": "cka-gen", "label_selector": "app=web",
        "jsonpath": "{.items[*].spec.nodeName}", "operator": "regex", "expected": "^node01( node01)*$",
    }))
    assert seen[0] == ["get", "pods", "-l", "app=web", "-n", "cka-gen",
                       "-o", "jsonpath={.items[*].spec.nodeName}"]
    assert status == validator.PASS, evidence


def test_jsonpath_without_braces_is_normalized() -> None:
    from app import validator

    params = validator.normalize_params("kubectl_jsonpath", {
        "kind": "service", "name": "web-svc", "jsonpath": ".spec.selector.app",
    })
    assert params["jsonpath"] == "{.spec.selector.app}"


def test_host_file_contains_falls_back_to_sudo(monkeypatch) -> None:
    from app import provider, validator
    from app.ssh_runner import ProcResult

    calls: list[bool] = []

    class FakeProvider:
        name = "multipass"

        async def nodes(self):
            return {"controlplane": __import__("app.provider.base", fromlist=["NodeInfo"]).NodeInfo(
                name="controlplane", real_name="controlplane", state="Running", ip="10.0.0.1")}

        async def exec(self, node, command, *, sudo=False, timeout=20):
            calls.append(sudo)
            if not sudo:
                return ProcResult(1, "", "cat: Permission denied")
            return ProcResult(0, "image: kube-controller-manager:v1.37.2", "")

    monkeypatch.setattr(provider, "get", lambda: FakeProvider())
    status, evidence = asyncio.run(validator.chk_host_file_contains({
        "location": "controlplane",
        "path": "/etc/kubernetes/manifests/kube-controller-manager.yaml",
        "regex_patterns": ["kube-controller-manager:v1.37.2"],
    }))
    assert calls == [False, True]
    assert status == validator.PASS, evidence
