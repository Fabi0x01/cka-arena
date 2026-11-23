"""Regression suite covering Smart Settle, Validator v2, Pipeline v2 gates,
Bank curation/telemetry, Mock Exam sessions, ClusterLease, Infra, LLM presets, and FastAPI routes."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app import (
    bank,
    cluster,
    config,
    curriculum,
    db,
    llm_client,
    main,
    pipeline,
    planner,
    scenario_engine,
    teardown,
    validator,
)
from app.cluster_lease import ClusterBusyError, ClusterLease
from app.doctor import ClusterDoctor
from app.events import EventBroker
from app.models import (
    CheckSpec,
    NodeCommand,
    ScenarioEnvelope,
)
from app.provider.kind import KindProvider
from app.provider.multipass import MultipassProvider
from app.sessions import SessionService
from app.ssh_runner import ProcResult


def _make_pipeline(engine=None) -> pipeline.GenerationPipeline:
    return pipeline.GenerationPipeline(
        llm_client.LLMClient(),
        EventBroker(),
        engine or scenario_engine.ScenarioEngine(),
        ClusterDoctor(),
    )


def _valid_envelope(*, ns: str = "billing", difficulty: str = "exam_standard") -> ScenarioEnvelope:
    return ScenarioEnvelope.model_validate({
        "id": "sc-billing-test",
        "title": "Restore Backend Service Endpoints",
        "domain": "Services & Networking",
        "difficulty": difficulty,
        "weight": 4,
        "estimated_minutes": 3,
        "subtopics": ["Services", "Endpoints"],
        "prompt": (
            f"Restore Backend Service Endpoints\n"
            f"Task weight: 7%\n"
            f"Use context: kubectl config use-context cka\n\n"
            f"Service `api-svc` in namespace `{ns}` returns no endpoints when queried.\n\n"
            f"Perform the following tasks:\n"
            f"1. Inspect Service `api-svc` and Deployment `api` in namespace `{ns}`.\n"
            f"2. Update the routing configuration so `api-svc` serves ready endpoints on port `80`.\n\n"
            f"Do not delete Deployment `api`."
        ),
        "copy_tokens": [ns, "api-svc", "api"],
        "setup": {
            "namespaces": [ns],
            "manifests": [
                f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n  namespace: {ns}\nspec:\n"
                f"  replicas: 1\n  selector:\n    matchLabels:\n      app: api\n  template:\n    metadata:\n"
                f"      labels:\n        app: api\n    spec:\n      containers:\n      - name: web\n"
                f"        image: nginx:1.27-alpine\n        ports:\n        - containerPort: 80\n---\n"
                f"apiVersion: v1\nkind: Service\nmetadata:\n  name: api-svc\n  namespace: {ns}\nspec:\n"
                f"  selector:\n    app: wrong-app\n  ports:\n  - port: 80\n    targetPort: 80\n"
            ],
            "commands": [],
            "node_commands": [],
        },
        "checks": [
            {
                "id": "c1",
                "type": "service_endpoints_ready",
                "description": "Service api-svc has at least 1 ready endpoint",
                "params": {"namespace": ns, "service_name": "api-svc", "min_ready_addresses": 1},
            },
            {
                "id": "c2",
                "type": "deployment_rollout_ready",
                "description": "Deployment api is rolled out",
                "params": {"namespace": ns, "name": "api", "min_ready_replicas": 1},
            },
        ],
        "solution": {
            "commands": [],
            "manifests": [
                f"apiVersion: v1\nkind: Service\nmetadata:\n  name: api-svc\n  namespace: {ns}\nspec:\n"
                f"  selector:\n    app: api\n  ports:\n  - port: 80\n    targetPort: 80\n"
            ],
            "node_commands": [],
        },
        "cleanup": {"namespaces": [ns], "commands": [], "node_commands": []},
        "reference_solution": f"Update selector on Service `api-svc` in `{ns}` to `app=api`.",
        "destructive": False,
    })


# ---------------------------------------------------------------- Smart Settle & Isolation


def test_smart_settle_exits_early_on_terminal_states(monkeypatch):
    engine = scenario_engine.ScenarioEngine()
    calls = 0

    async def fake_pods(ns):
        nonlocal calls
        calls += 1
        return [
            {
                "name": "broken-sched",
                "phase": "Pending",
                "ready": False,
                "unschedulable": True,
                "waiting_reasons": [],
                "terminated_reasons": [],
                "created_ts": time.time(),
            },
            {
                "name": "broken-img",
                "phase": "Pending",
                "ready": False,
                "unschedulable": False,
                "waiting_reasons": ["ImagePullBackOff"],
                "terminated_reasons": [],
                "created_ts": time.time(),
            },
            {
                "name": "broken-crash",
                "phase": "Running",
                "ready": False,
                "unschedulable": False,
                "waiting_reasons": ["CrashLoopBackOff"],
                "terminated_reasons": ["Error"],
                "created_ts": time.time(),
            },
        ]

    monkeypatch.setattr(cluster, "pods_detailed", fake_pods)
    t0 = time.monotonic()
    settled = asyncio.run(engine.settle(["orders"], timeout_s=30))
    elapsed = time.monotonic() - t0
    assert settled is True
    assert calls == 1
    assert elapsed < 0.5


def test_smart_settle_waits_for_container_creating(monkeypatch):
    engine = scenario_engine.ScenarioEngine()
    calls = 0

    async def fake_pods(ns):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{
                "name": "starting",
                "phase": "Pending",
                "ready": False,
                "unschedulable": False,
                "waiting_reasons": ["ContainerCreating"],
                "terminated_reasons": [],
                "created_ts": time.time(),
            }]
        return [{
            "name": "starting",
            "phase": "Running",
            "ready": True,
            "unschedulable": False,
            "waiting_reasons": [],
            "terminated_reasons": [],
            "created_ts": time.time(),
        }]

    monkeypatch.setattr(cluster, "pods_detailed", fake_pods)
    settled = asyncio.run(engine.settle(["orders"], timeout_s=5))
    assert settled is True
    assert calls == 2


def test_cluster_scope_detection_and_ephemeral_clone():
    ns_env = _valid_envelope(ns="billing")
    assert scenario_engine.is_cluster_scoped(ns_env) is False

    cloned = scenario_engine.clone_with_ephemeral_namespaces(ns_env, "abc12")
    assert cloned.setup.namespaces == ["cka-p-abc12-billing"]
    assert "cka-p-abc12-billing" in cloned.setup.manifests[0]
    assert cloned.checks[0].params["namespace"] == "cka-p-abc12-billing"
    assert cloned.solution.manifests[0].find("cka-p-abc12-billing") != -1
    assert ns_env.setup.namespaces == ["billing"]  # original untouched

    pv_env = ns_env.model_copy(deep=True)
    pv_env.setup.manifests.append("apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: pv-1\n")
    assert scenario_engine.is_cluster_scoped(pv_env) is True

    node_env = ns_env.model_copy(deep=True)
    node_env.setup.node_commands.append(NodeCommand(node="node01", command="systemctl stop kubelet"))
    assert scenario_engine.is_cluster_scoped(node_env) is True


# ---------------------------------------------------------------- Validator v2


def test_validator_compare_and_normalize():
    assert validator.compare("10.244.0.1 10.244.0.2", "len_gte", 2) is True
    assert validator.compare("10.244.0.1\n10.244.0.2\n10.244.0.3", "len_gte", 3) is True
    assert validator.compare("node01 node01", "all_match", "node01") is True
    assert validator.compare("node01 node02", "all_match", "node01") is False
    assert validator.compare("3", "equals_int", "3") is True
    assert validator.compare("allow-all", "not_contains", "deny") is True
    assert validator.compare("", "empty", "") is True
    assert validator.compare("ready", "not_empty", "") is True

    norm = validator.normalize_params("pod_exec_exit_zero", {"namespace": "x", "selector": "app=api", "pod": "api-1", "command": ["true"]})
    assert norm["label_selector"] == "app=api"
    assert norm["pod_name"] == "api-1"


def test_validator_invalid_check_not_treated_as_infra_error():
    bad_spec = CheckSpec(
        id="bad-1",
        type="kubectl_resource_exists",
        description="Missing name parameter",
        params={"kind": "pod", "namespace": "default"},  # missing 'name'
    )
    out = asyncio.run(validator.run_all([bad_spec]))
    assert out["all_passed"] is False
    assert out["infra_error"] is False
    assert out["results"][0]["status"] == validator.ERROR
    assert out["results"][0]["evidence"].get("invalid_check") is True


def test_validator_semantic_checks(monkeypatch):
    async def _run():
        async def fake_kubectl(args, timeout=15, stdin_data=None):
            joined = " ".join(args)
            if "endpointslices" in joined:
                payload = {"items": [{"endpoints": [{"conditions": {"ready": True}, "addresses": ["10.244.1.5", "10.244.2.6"]}]}]}
                return ProcResult(0, json.dumps(payload), "")
            if "get deployment api" in joined:
                payload = {
                    "metadata": {"generation": 2},
                    "spec": {"template": {"spec": {"containers": [{"image": "nginx:1.27-alpine"}]}}},
                    "status": {"observedGeneration": 2, "readyReplicas": 2, "availableReplicas": 2},
                }
                return ProcResult(0, json.dumps(payload), "")
            if "get pvc data-pvc" in joined:
                payload = {
                    "spec": {"storageClassName": "local-path"},
                    "status": {"phase": "Bound", "capacity": {"storage": "1Gi"}},
                }
                return ProcResult(0, json.dumps(payload), "")
            return ProcResult(1, "", "unexpected kubectl call")

        monkeypatch.setattr(cluster, "kubectl", fake_kubectl)

        s1, _ = await validator.chk_service_endpoints_ready({"namespace": "billing", "service_name": "api-svc", "min_ready_addresses": 2})
        assert s1 == validator.PASS

        s2, _ = await validator.chk_deployment_rollout_ready({"namespace": "billing", "name": "api", "min_ready_replicas": 2, "expected_image": "nginx:1.27-alpine"})
        assert s2 == validator.PASS

        s3, _ = await validator.chk_pvc_bound({"namespace": "billing", "name": "data-pvc", "storage_class": "local-path", "min_storage": "1Gi"})
        assert s3 == validator.PASS

    asyncio.run(_run())


# ---------------------------------------------------------------- Pipeline v2 Gates, Retry History, Digest


def test_pipeline_gates_rejects_spoilers_bad_json_immutable_patch_list_jsonpath_and_timeout(monkeypatch):
    async def _run():
        monkeypatch.setattr(cluster, "kubectl", AsyncMock(return_value=ProcResult(0, "configured", "")))
        gp = _make_pipeline()

        # 1. Spoiler leak
        spoiler_env = _valid_envelope()
        spoiler_env.prompt = (
            "Restore Service\nTask weight: 7%\nUse context: kubectl config use-context cka\n\n"
            "Service fails because selector is wrong on api-svc.\n\nPerform the following tasks:\n1. Fix service."
        )
        errs = await gp._gates(spoiler_env)
        assert any("spoiler" in e.lower() for e in errs)

        # 2. Invalid JSON in -p
        bad_patch = _valid_envelope()
        bad_patch.solution.commands = ["kubectl patch svc api-svc -n billing -p '{not json}'"]
        errs = await gp._gates(bad_patch)
        assert any("json" in e.lower() for e in errs)

        # 3. Immutable PVC patch
        imm_patch = _valid_envelope()
        imm_patch.solution.commands = ['kubectl patch pvc data -n billing -p \'{"spec":{"storageClassName":"local-path"}}\'']
        errs = await gp._gates(imm_patch)
        assert any("imut" in e.lower() or "storageclassname" in e.lower() for e in errs)

        # 4. LIST-mode kubectl_jsonpath without .items[*]
        bad_jp = _valid_envelope()
        bad_jp.checks.append(CheckSpec(
            id="c3",
            type="kubectl_jsonpath",
            description="Pods scheduled on node01",
            params={"kind": "pod", "namespace": "billing", "label_selector": "app=api", "jsonpath": "{.spec.nodeName}", "operator": "all_match", "expected": "node01"},
        ))
        errs = await gp._gates(bad_jp)
        assert any(".items[*]" in e for e in errs)

        # 5. pod_exec_must_fail missing timeout
        no_to = _valid_envelope()
        no_to.checks.append(CheckSpec(
            id="c4",
            type="pod_exec_must_fail",
            description="Traffic blocked",
            params={"namespace": "billing", "ephemeral_probe": True, "command": ["curl", "-sS", "http://api-svc.billing.svc"]},
        ))
        errs = await gp._gates(no_to)
        assert any("timeout" in e.lower() for e in errs)

        # 6. Accepts pod_name on pod_exec_exit_zero
        pod_name_env = _valid_envelope()
        pod_name_env.checks.append(CheckSpec(
            id="c5",
            type="pod_exec_exit_zero",
            description="Pod responds",
            params={"namespace": "billing", "pod_name": "api-pod", "command": ["true"]},
        ))
        errs = await gp._gates(pod_name_env)
        assert errs == []

        # 7. solution.manifests server dry-run rejection
        monkeypatch.setattr(cluster, "kubectl", AsyncMock(return_value=ProcResult(1, "", "Invalid value: unknown field foo")))
        errs = await gp._gates(_valid_envelope())
        assert any("dry-run" in e.lower() for e in errs)

    asyncio.run(_run())


def test_pipeline_build_one_gates_before_review_and_assistant_history(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        db.init_db()
        gp = _make_pipeline()

        seen_calls: list[list[dict]] = []
        spoiler = _valid_envelope(ns="billing")
        spoiler.prompt = (
            "Fix Service\nTask weight: 7%\n\n"
            "Traffic fails because wrong selector points elsewhere.\n\n"
            "Perform the following tasks:\n1. Fix `api-svc` in `billing`."
        )
        clean = _valid_envelope(ns="billing")

        async def fake_complete(messages, **kwargs):
            seen_calls.append(messages)
            if len(seen_calls) == 1:
                return spoiler.model_dump_json(), {"provider": "mock", "model": "mock-main"}
            return clean.model_dump_json(), {"provider": "mock", "model": "mock-main"}

        review_mock = AsyncMock(return_value=("approve", [], {"provider": "mock", "model": "mock-flash"}))
        monkeypatch.setattr(gp.client, "complete", fake_complete)
        monkeypatch.setattr(gp, "_review", review_mock)
        monkeypatch.setattr(cluster, "kubectl", AsyncMock(return_value=ProcResult(0, "configured", "")))
        monkeypatch.setattr(gp, "_probe_retry", AsyncMock(return_value=(True, "ok", "ok")))

        slots = planner.plan_slots(
            domains=["Services & Networking"],
            difficulty="exam_standard",
            count=1,
            constraints=[],
            available_addons={"network_policy"},
            coverage_cells=[],
            recent_rows=[],
            seed="unit",
        )
        slots[0].namespace = "billing"
        env, err, _ = await gp._build_one(
            "job-1",
            pipeline.GenerationRequestModel(domains=["Services & Networking"], difficulty="exam_standard", count=1),
            "Control plane + 2 workers",
            slots[0],
        )
        assert err == ""
        assert env is not None
        # Reviewer called ONLY after attempt 2 passed deterministic gates
        assert review_mock.await_count == 1
        # Retry preserved the assistant message before user feedback
        assert [m["role"] for m in seen_calls[1]] == ["system", "user", "assistant", "user"]

    asyncio.run(_run())


def test_probe_locked_captures_digest_before_cleanup():
    order: list[str] = []

    class FakeEngine:
        async def apply_setup(self, env):
            order.append("apply_setup")

        async def settle(self, namespaces, timeout_s=60):
            return True

        async def apply_solution(self, env):
            order.append("apply_solution")

        async def run_checks(self, env, **kwargs):
            if "apply_solution" not in order:
                return {"all_passed": False, "infra_error": False, "results": [{"check_id": "c1", "status": "FAIL", "description": "x", "evidence": {}}]}
            return {"all_passed": False, "infra_error": False, "results": [{"check_id": "c1", "status": "FAIL", "description": "x", "evidence": {"actual": "0"}}]}

        async def namespace_digest(self, namespaces):
            order.append("namespace_digest")
            return {"billing": {"pods": [], "events": ["BackOff"]}}

        async def cleanup(self, env):
            order.append("cleanup")
            return {}

    gp = _make_pipeline(engine=FakeEngine())
    env = _valid_envelope()
    ok, _detail, kind = asyncio.run(gp._probe_locked(env))
    assert ok is False and kind == "content"
    assert order.index("namespace_digest") < order.index("cleanup")
    assert gp._last_probe_digest == {"billing": {"pods": [], "events": ["BackOff"]}}


# ---------------------------------------------------------------- Bank, Sessions, Lease


def test_bank_upgrade_curation_and_mock_exam_flow(tmp_path, monkeypatch):
    async def _run():
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        db.init_db()

        env = _valid_envelope(ns="billing")
        env.weight = 7
        draft = bank.publish_question(env, source="llm", state="draft")
        assert bank.get_question(draft["id"])["state"] == "draft"
        upgraded = bank.publish_question(env, source="llm", state="published")
        assert upgraded["id"] == draft["id"]
        assert bank.count_published() == 1

        engine = AsyncMock()
        engine.apply_setup = AsyncMock(return_value={})
        engine.cleanup = AsyncMock(return_value={})
        engine.run_checks = AsyncMock(return_value={
            "all_passed": True,
            "infra_error": False,
            "ran_at": time.time(),
            "duration_ms": 50,
            "results": [{"check_id": "c1", "status": "PASS"}],
        })
        doctor_mock = AsyncMock()
        mgr = SessionService(engine=engine, doctor=doctor_mock)
        mgr.teardown.cleanup_session = AsyncMock(return_value={"drift": False})

        env2 = _valid_envelope(ns="orders")
        env2.id = "sc-orders-test"
        env2.title = "Scale Stateful Web Service"
        env2.weight = 14
        bank.publish_question(env2, source="llm", state="published")

        created = await mgr.create(2, mode="mock_exam")
        sid = created["session"]["id"]
        assert created["session"]["mode"] == "mock_exam"
        assert created["session"]["time_limit_minutes"] == 120
        assert created["session"]["total_weight"] == 21

        first_item_id = created["items"][0]["id"]
        second_item_id = created["items"][1]["id"]
        flagged = await mgr.toggle_flag(sid, first_item_id)
        assert flagged["active"]["flagged"] is True

        if created["active"]["envelope"]["weight"] != 14:
            await mgr.select_item(sid, second_item_id)
            other_item_id = first_item_id
        else:
            other_item_id = second_item_id

        checked = await mgr.check(sid)
        assert checked["report"]["all_passed"] is True
        assert checked["session"]["active"]["item_state"] == "passed"
        assert checked["session"]["active"]["last_check"]["all_passed"] is True

        row = bank.get_question(checked["session"]["active"]["bank_question_id"])
        assert row["times_used"] == 1
        assert row["first_try_pass_count"] == 1
        assert row["avg_solve_seconds"] is not None

        selected = await mgr.select_item(sid, other_item_id)
        assert selected["active"]["item_id"] == other_item_id
        retired_qid = selected["active"]["bank_question_id"]

        await mgr.retire_active(sid, "bad setup")
        assert bank.get_question(retired_qid)["state"] == "retired"

        finished = await mgr.finish(sid, reset="none")
        assert finished["summary"]["passed_exam"] is True
        assert finished["summary"]["total_weight"] == 21
        assert finished["summary"]["earned_weight"] == 14

        assert bank.list_questions(state="published")["total"] == 1
        assert bank.list_questions(state="retired")["total"] == 1
        # Referenced question cannot be hard-deleted; unreferenced draft can
        ref_deleted, _reason = bank.delete_question(retired_qid)
        assert ref_deleted is False
        unused = _valid_envelope(ns="catalog")
        unused.id = "sc-catalog-unused"
        unused.title = "Unused Catalog Question"
        pub_unused = bank.publish_question(unused, source="llm", state="draft")
        ok_del, _ = bank.delete_question(pub_unused["id"])
        assert ok_del is True

    asyncio.run(_run())


def test_cluster_lease_mutual_exclusion():
    class FakeSessions:
        def __init__(self, active):
            self._active = active

        def active_session_id(self):
            return self._active

    class FakePipeline:
        def __init__(self, job_id):
            self.active_job_id = job_id

    class FakePower:
        def __init__(self, running):
            self._active_job = {"action": "stop"} if running else None

    lease = ClusterLease(power=FakePower(False), pipeline=FakePipeline(None), sessions=FakeSessions("s-1"))
    try:
        lease.ensure_for_generation()
        raise AssertionError("expected ClusterBusyError")
    except ClusterBusyError:
        pass
    try:
        lease.ensure_for_reset()
        raise AssertionError("expected ClusterBusyError")
    except ClusterBusyError:
        pass

    lease2 = ClusterLease(power=FakePower(False), pipeline=FakePipeline("gen-1"), sessions=FakeSessions(None))
    try:
        lease2.ensure_for_practice()
        raise AssertionError("expected ClusterBusyError")
    except ClusterBusyError:
        pass
    try:
        lease2.ensure_for_power("stop")
        raise AssertionError("expected ClusterBusyError")
    except ClusterBusyError:
        pass


# ---------------------------------------------------------------- Infra & LLM Presets


def test_multipass_ttl_cache_and_kind_teardown(monkeypatch):
    async def _run():
        calls = 0

        async def fake_list_vms():
            nonlocal calls
            calls += 1
            return {
                "controlplane": {"state": "Running", "ips": ["192.168.1.10"]},
                "node01": {"state": "Running", "ips": ["192.168.1.11"]},
                "node02": {"state": "Running", "ips": ["192.168.1.12"]},
            }

        async def fake_resolve_ip(ips):
            return ips[0] if ips else None

        monkeypatch.setattr("app.ssh_runner.list_vms", fake_list_vms)
        monkeypatch.setattr("app.ssh_runner.resolve_ip", fake_resolve_ip)

        mp = MultipassProvider()
        await mp.nodes(use_cache=True)
        await mp.nodes(use_cache=True)
        assert calls == 1
        mp.invalidate_cache()
        await mp.nodes(use_cache=True)
        assert calls == 2

        kind_prov = KindProvider()
        exec_calls: list[str] = []

        async def fake_kind_exec(node, command, *, sudo=False, timeout=20.0):
            exec_calls.append(node)
            return ProcResult(0, "", "")

        monkeypatch.setattr(kind_prov, "nodes", AsyncMock(return_value={
            name: mp._cache[name] for name in config.VM_NAMES
        }))
        monkeypatch.setattr(kind_prov, "exec", fake_kind_exec)
        monkeypatch.setattr("app.provider.get", lambda: kind_prov)
        monkeypatch.setattr(cluster, "kubectl", AsyncMock(return_value=ProcResult(0, "", "")))

        td = teardown.Teardown(scenario_engine.ScenarioEngine(), main.doctor)
        monkeypatch.setattr(td, "drift", AsyncMock(return_value={"drift": False}))
        res = await td.cleanup_session()
        assert set(exec_calls) == set(config.VM_NAMES)
        assert res["drift"]["drift"] is False

    asyncio.run(_run())


def test_ollama_preset_and_thinking_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_CONFIG_PATH", tmp_path / "llm_config.json")
    for var in ("LLM_PROVIDER", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "CKA_LLM_PROVIDER", "CKA_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    saved = llm_client.save_config({
        "provider": "ollama",
        "model": "qwen2.5:14b",
        "model_flash": "qwen2.5:14b",
        "thinking": "off",
        "reasoning_effort": "medium",
    })
    assert saved["provider"] == "ollama"
    assert saved["auth_mode"] == "none"
    assert saved["thinking"] == "off"
    assert saved["reasoning_effort"] == "medium"

    client = llm_client.LLMClient()
    assert client.is_configured() is True


# ---------------------------------------------------------------- FastAPI Smoke


def test_fastapi_routes_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_CONFIG_PATH", tmp_path / "llm_config.json")
    monkeypatch.setattr(main.power, "detect", AsyncMock(return_value={"state": "on", "vms": []}))
    monkeypatch.setattr(main.scenario_engine, "apply_setup", AsyncMock(return_value={}))
    monkeypatch.setattr(main.scenario_engine, "cleanup", AsyncMock(return_value={}))
    monkeypatch.setattr(main.sessions.teardown, "cleanup_session", AsyncMock(return_value={"drift": False}))

    db.init_db()
    bank.publish_question(_valid_envelope(ns="billing"), source="seed", state="published")

    with TestClient(main.app) as client:
        r_list = client.get("/api/bank/questions")
        assert r_list.status_code == 200
        assert r_list.json()["total"] == 1

        r_cancel = client.post("/api/generate/cancel")
        assert r_cancel.status_code == 200
        assert r_cancel.json()["cancelled"] is False

        r_put_llm = client.put(
            "/api/llm/config",
            json={"provider": "ollama", "model": "qwen2.5:14b", "thinking": "off", "reasoning_effort": "high"},
        )
        assert r_put_llm.status_code == 200
        assert r_put_llm.json()["provider"] == "ollama"
        assert r_put_llm.json()["thinking"] == "off"
        assert r_put_llm.json()["reasoning_effort"] == "high"

        r_prac = client.post("/api/practice", json={"count": 1, "mode": "mock_exam"})
        assert r_prac.status_code == 201
        sess = r_prac.json()
        sid = sess["session"]["id"]
        item_id = sess["items"][0]["id"]

        r_flag = client.post(f"/api/sessions/{sid}/flag/{item_id}")
        assert r_flag.status_code == 200
        assert r_flag.json()["active"]["flagged"] is True

        r_fin = client.post(f"/api/sessions/{sid}/finish", json={"reset": "none"})
        assert r_fin.status_code == 200
        assert "summary" in r_fin.json()
