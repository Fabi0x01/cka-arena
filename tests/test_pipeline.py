"""Testes do pipeline: extração JSON, gates determinísticos e tier band."""

from __future__ import annotations

import asyncio
import json

import pytest

from app import pipeline as pl
from app.events import EventBroker
from app.models import ScenarioEnvelope
from app.ssh_runner import ProcResult

BASE = {
    "id": "gen-test",
    "title": "Fix a Failing Workload",
    "domain": "Troubleshooting",
    "difficulty": "exam_standard",
    "weight": 4,
    "estimated_minutes": 4,
    "prompt": (
        "A Deployment is failing.\n\n"
        "Perform the following tasks:\n"
        "1. Fix the `web` Deployment in `cka-gen`.\n"
        "2. Keep the image `nginx:1.27-alpine`."
    ),
    "copy_tokens": ["web", "cka-gen", "nginx:1.27-alpine"],
    "setup": {
        "namespaces": ["cka-gen"],
        "manifests": [
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n  namespace: cka-gen\n"
        ],
    },
    "checks": [
        {"id": "c1", "description": "pod ready", "type": "pod_status_ready",
         "params": {"namespace": "cka-gen", "label_selector": "app=web", "min_ready": 1}},
        {"id": "c2", "description": "image kept", "type": "kubectl_jsonpath",
         "params": {"kind": "deployment", "name": "web", "namespace": "cka-gen",
                    "jsonpath": "{.spec.template.spec.containers[0].image}",
                    "operator": "equals", "expected": "nginx:1.27-alpine"}},
    ],
    "solution": {"manifests": [], "commands": ["kubectl -n cka-gen rollout restart deployment web"]},
    "cleanup": {"namespaces": ["cka-gen"]},
}


def make_envelope(**overrides) -> ScenarioEnvelope:
    payload = {**BASE, **overrides}
    return ScenarioEnvelope.model_validate(payload)


def make_pipeline() -> pl.GenerationPipeline:
    return pl.GenerationPipeline(client=None, broker=EventBroker(), engine=None, doctor=None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _patch_kubectl(monkeypatch):
    async def ok(_args, timeout=20, stdin_data=None):
        return ProcResult(0, "", "")

    monkeypatch.setattr(pl.cluster, "kubectl", ok)


def test_extract_json_accepts_plain_fenced_and_wrapped() -> None:
    assert pl.extract_json('{"a": 1}') == {"a": 1}
    assert pl.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert pl.extract_json('Here it is:\n{"a": 2}\nThanks') == {"a": 2}
    with pytest.raises(ValueError):
        pl.extract_json("no json here")


def test_valid_exam_standard_envelope_passes_gates() -> None:
    env = make_envelope()
    errors = asyncio.run(make_pipeline()._gates(env))
    assert errors == [], errors


def test_tier_band_rejects_two_axis_mismatch() -> None:
    env = make_envelope(
        prompt=(
            "A Deployment is failing.\n\nPerform the following tasks:\n"
            "1. Fix the `web` Deployment.\n2. Scale it to `2` replicas.\n"
            "3. Keep the image `nginx:1.27-alpine`."
        ),
        checks=BASE["checks"] + [
            {"id": "c3", "description": "replicas", "type": "kubectl_jsonpath",
             "params": {"kind": "deployment", "name": "web", "namespace": "cka-gen",
                        "jsonpath": "{.spec.replicas}", "operator": "gte", "expected": 2}},
            {"id": "c4", "description": "svc", "type": "kubectl_resource_exists",
             "params": {"kind": "service", "name": "web", "namespace": "cka-gen"}},
            {"id": "c5", "description": "sa", "type": "kubectl_resource_exists",
             "params": {"kind": "serviceaccount", "name": "deployer", "namespace": "cka-gen"}},
        ],
    )
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("tier band" in error for error in errors), errors


def test_gates_block_dangerous_commands() -> None:
    env = make_envelope(solution={"manifests": [], "commands": ["rm -rf / --no-preserve-root"]})
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("perigoso" in error for error in errors), errors


def test_gates_require_destructive_flag() -> None:
    env = make_envelope(solution={"manifests": [], "commands": ["etcdctl snapshot restore /tmp/x.db"]})
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("destrutiva" in error for error in errors), errors

    flagged = make_envelope(
        destructive=True,
        solution={"manifests": [], "commands": ["etcdctl snapshot restore /tmp/x.db"]},
    )
    errors = asyncio.run(make_pipeline()._gates(flagged))
    assert not any("destrutiva" in error for error in errors)


def test_gates_reject_latest_tag_and_unknown_images() -> None:
    env = make_envelope(
        setup={
            "namespaces": ["cka-gen"],
            "manifests": ["apiVersion: v1\nkind: Pod\nmetadata:\n  name: p\n  namespace: cka-gen\n"
                          "spec:\n  containers:\n  - name: c\n    image: nginx:latest\n"],
        }
    )
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("latest" in error for error in errors), errors


def test_gates_enforce_exam_voice() -> None:
    env = make_envelope(
        prompt="Você precisa consertar o Deployment.\n\nPerform the following tasks:\n1. Fix `web`."
    )
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("inglês" in error for error in errors), errors

    missing_block = make_envelope(prompt="Fix the Deployment `web` in `cka-gen`.")
    errors = asyncio.run(make_pipeline()._gates(missing_block))
    assert any("Perform the following tasks" in error for error in errors), errors


def test_image_whitelist_accepts_untagged_repos_and_rejects_latest() -> None:
    from app.pipeline import image_allowed

    assert image_allowed("nginx")
    assert image_allowed("nginx:1.27-alpine")
    assert image_allowed("curlimages/curl:8.10.1")
    assert image_allowed("registry.k8s.io/pause:3.10")
    assert not image_allowed("nginx:latest")
    assert not image_allowed("nginx-ingress/controller:1.0")


def test_gates_reject_solution_command_with_local_file() -> None:
    env = make_envelope(
        solution={"manifests": [], "commands": ["kubectl -n cka-gen apply -f api-svc.yaml"]}
    )
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("arquivo local" in error for error in errors), errors


def test_job_state_tracks_scenarios_and_current_step() -> None:
    pipeline = make_pipeline()
    pipeline._job = {
        "id": "job1", "status": "running", "scenarios": {},
        "current": {"stage": "queued", "detail": "", "scenario": None},
    }
    queue = pipeline.broker.subscribe()
    pipeline._update("job1", "B", "builder attempt 2/6 · thinking on", scenario=1, total=2)
    snapshot = pipeline.snapshot()
    assert snapshot["current"]["stage"] == "B"
    assert snapshot["scenarios"]["1"]["attempts"] == 2
    assert snapshot["scenarios"]["1"]["status"] == "running"
    event = queue.get_nowait()
    assert event["job_id"] == "job1" and event["stage"] == "B"

    pipeline._update("job2", "B", "ignored", scenario=1, total=2)
    assert pipeline.snapshot()["scenarios"]["1"]["detail"].startswith("builder attempt")


def test_band_clamp_fixes_scalars_without_llm_round() -> None:
    env = make_envelope(weight=9, estimated_minutes=9)  # exam_standard: weight 2-5, minutes 1-4
    changes = make_pipeline()._clamp_band_scalars(env)
    assert env.weight == 5 and env.estimated_minutes == 4.0
    assert changes == ["weight→5", "minutes→4"]

    in_band = make_envelope()
    assert make_pipeline()._clamp_band_scalars(in_band) == []


def test_consistency_gate_flags_unreachable_check_target() -> None:
    env = make_envelope(checks=[
        {"id": "c1", "description": "svc exists", "type": "kubectl_resource_exists",
         "params": {"kind": "service", "name": "web-svc", "namespace": "cka-gen"}},
    ])
    errors = make_pipeline()._consistency_errors(env)
    assert any("web-svc" in e for e in errors)

    fixed = make_envelope(solution={"manifests": [], "commands": [
        "kubectl -n cka-gen expose deployment web --name=web-svc --port=80"]},
        checks=[{"id": "c1", "description": "svc exists", "type": "kubectl_resource_exists",
                 "params": {"kind": "service", "name": "web-svc", "namespace": "cka-gen"}}])
    assert make_pipeline()._consistency_errors(fixed) == []


def test_reviewer_prompt_delegates_numeric_band_to_gate() -> None:
    assert "{{BAND}}" not in pl.REVIEWER_SYSTEM
    assert "DO NOT judge numeric band" in pl.REVIEWER_SYSTEM


def test_failure_detail_carries_evidence_for_the_corrector() -> None:
    detail = make_pipeline()._failure_detail({
        "results": [
            {"check_id": "c1", "description": "svc exists", "status": "PASS"},
            {"check_id": "c2", "description": "curl 200", "status": "FAIL",
             "evidence": {"expected": "200", "actual": "000", "exit_code": 1,
                          "stderr": "curl: (7) connection refused"}},
        ]
    })
    assert "c1" not in detail
    assert "expected='200'" in detail and "got='000'" in detail
    assert "exit=1" in detail and "connection refused" in detail


def test_probe_settles_once_per_phase_not_per_poll() -> None:
    """settle() custa até 60s; rodá-lo a cada ciclo de poll multiplicava o probe."""
    pipeline = make_pipeline()
    settle_calls: list[float] = []
    run_calls: list[bool | None] = []
    reports = [
        {"all_passed": False, "infra_error": False,
         "results": [{"check_id": "c1", "status": "FAIL", "description": "x"}]},
        {"all_passed": True, "infra_error": False,
         "results": [{"check_id": "c1", "status": "PASS", "description": "x"}]},
        {"all_passed": True, "infra_error": False,   # confirmação (2 consecutivos)
         "results": [{"check_id": "c1", "status": "PASS", "description": "x"}]},
    ]

    class FakeEngine:
        async def apply_setup(self, env):
            return {"ok": True}

        async def settle(self, namespaces, timeout_s=60):
            settle_calls.append(timeout_s)
            return True

        async def run_checks(self, env, settle=True):
            run_calls.append(settle)
            return reports.pop(0)

        async def cleanup(self, env):
            return {"ok": True}

    pipeline.engine = FakeEngine()  # type: ignore[assignment]
    ok, detail, _kind = asyncio.run(pipeline._probe_locked(make_envelope()))
    assert ok, detail
    assert settle_calls == [45, 15]          # 1× após setup (45s) e 1× após solution (15s; poll cobre)
    assert run_calls == [False, False, False]  # sanity + final + confirmação; polls nunca re-settlem


def test_gates_reject_heredoc_commands() -> None:
    env = make_envelope(solution={"manifests": [], "commands": [
        "kubectl -n cka-gen apply -f - <<EOF\nkind: NetworkPolicy\nEOF"]})
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("heredoc" in e for e in errors), errors


def test_dry_run_retries_once_when_namespace_terminating(monkeypatch) -> None:
    calls: list[str] = []
    dry_runs = [
        ProcResult(1, "", "Error from server (Forbidden): namespaces \"cka-gen\" is being terminated"),
        ProcResult(0, "", ""),
    ]

    async def fake_kubectl(args, timeout=20, stdin_data=None):
        calls.append(args[0])
        if args[0] == "apply":
            return dry_runs.pop(0)
        if args[0] == "get":
            return ProcResult(0, "Terminating", "") if len(calls) < 3 else ProcResult(1, "", "NotFound")
        return ProcResult(0, "", "")

    monkeypatch.setattr(pl.cluster, "kubectl", fake_kubectl)
    errors = asyncio.run(make_pipeline()._gates(make_envelope()))
    assert errors == [], errors
    assert calls.count("apply") == 2      # retentou o dry-run após o Terminating


def test_rollout_status_timeout_is_not_a_solution_failure(monkeypatch) -> None:
    async def slow(_raw, timeout=60):
        return ProcResult(1, "", "error: timed out waiting for the condition")

    monkeypatch.setattr(pl.commands, "run_tool_command", slow)
    env = make_envelope(solution={"manifests": [], "commands": [
        "kubectl -n cka-gen rollout status deployment/web --timeout=180s"]})
    assert asyncio.run(make_pipeline()._apply_solution(env)) == ""


def test_apply_setup_waits_out_terminating_namespace(monkeypatch) -> None:
    from app.scenario_engine import ScenarioEngine

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr("app.scenario_engine.asyncio.sleep", fast_sleep)
    phases = ["Terminating", "Terminating", None, None]  # None → get falha (NotFound)
    seen: list[str] = []

    async def fake_kubectl(args, timeout=20, stdin_data=None):
        seen.append(" ".join(args[:2]))
        if args[0] == "get":
            if phases and phases.pop(0) is None:
                return ProcResult(1, "", "NotFound")
            return ProcResult(0, "Terminating", "")
        return ProcResult(0, "", "")

    monkeypatch.setattr("app.scenario_engine.cluster.kubectl", fake_kubectl)
    engine = ScenarioEngine()
    asyncio.run(engine.apply_setup(make_envelope()))
    assert seen.count("get namespace") == 4     # esperou o Terminating sumir
    assert seen.count("create namespace") == 1  # criou só depois


def test_apply_setup_force_finalizes_stuck_namespace(monkeypatch) -> None:
    from app.scenario_engine import ScenarioEngine

    async def fast_sleep(_seconds):
        return None

    monkeypatch.setattr("app.scenario_engine.asyncio.sleep", fast_sleep)
    state = {"finalized": False, "replaces": 0}

    async def fake_kubectl(args, timeout=20, stdin_data=None):
        if args[0] == "replace":            # --raw .../finalize
            state["finalized"] = True
            state["replaces"] += 1
            return ProcResult(0, "{}", "")
        if args[0] == "get":
            if "-o" in args and args[args.index("-o") + 1] == "json":
                return ProcResult(0, '{"metadata": {"name": "cka-gen"}, "spec": {"finalizers": ["kubernetes"]}}', "")
            if state["finalized"]:
                return ProcResult(1, "", "NotFound")
            return ProcResult(0, "Terminating", "")
        return ProcResult(0, "", "")

    monkeypatch.setattr("app.scenario_engine.cluster.kubectl", fake_kubectl)
    engine = ScenarioEngine()
    asyncio.run(engine.apply_setup(make_envelope()))
    assert state["replaces"] == 1               # removeu o finalizer travado
    assert state["finalized"] is True


def test_gates_reject_absolute_file_and_url_targets() -> None:
    env = make_envelope(solution={"manifests": [], "commands": [
        "kubectl apply -f /tmp/atlas-configmap.yaml"]})
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("/tmp/atlas" in e for e in errors), errors


def test_gates_reject_kubectl_inside_node_commands() -> None:
    env = make_envelope(setup={
        "namespaces": ["cka-gen"],
        "node_commands": [{"node": "node01", "command": "kubectl get pods", "sudo": False}],
    })
    errors = asyncio.run(make_pipeline()._gates(env))
    assert any("node_command não pode usar kubectl" in e for e in errors), errors


def test_auto_sudo_uplifts_system_path_mutations() -> None:
    env = make_envelope(setup={
        "namespaces": ["cka-gen"],
        "node_commands": [{"node": "node01", "command": "mkdir -p /opt/cka-slot4",
                           "sudo": False, "backup_paths": []}],
    })
    errors = asyncio.run(make_pipeline()._gates(env))
    assert env.setup.node_commands[0].sudo is True
    assert not any("backup_paths" in e for e in errors)  # cria o próprio dir: sem backup


def test_node_commands_get_mkdir_p_and_sudo_uplift() -> None:
    env = make_envelope(setup={
        "namespaces": ["cka-gen"],
        "node_commands": [{"node": "node01", "command": "mkdir /tmp/cka-boss-checks",
                           "sudo": False, "backup_paths": []}],
    })
    errors = asyncio.run(make_pipeline()._gates(env))
    cmd = env.setup.node_commands[0]
    assert cmd.command == "mkdir -p /tmp/cka-boss-checks"   # idempotente entre tentativas
    assert cmd.sudo is True                                  # dir pode ter ficado root
    assert not any("backup_paths" in e for e in errors)      # cria o próprio dir


def test_probe_accepts_oscillating_checks_by_two_of_three() -> None:
    pipeline = make_pipeline()

    class FakeEngine:
        def __init__(self, final_reports):
            self.reports = [{"all_passed": False, "infra_error": False,
                             "results": [{"check_id": "c1", "status": "FAIL", "description": "x"}]}
                            ] + final_reports
            self.settles = 0

        async def apply_setup(self, env): return {"ok": True}
        async def settle(self, ns, timeout_s=60):
            self.settles += 1
            # segundos "passam" rápido: os sleeps do probe são curtos (2s) e o teste
            # tolera os poucos awaits reais
            return True

        async def run_checks(self, env, settle=True):
            report = self.reports.pop(0)
            return {**report,
                    "results": list(report["results"])}

        async def cleanup(self, env): return {"ok": True}

    def report(passing):
        return {"all_passed": len(passing) == 2, "infra_error": False,
                "results": [{"check_id": c, "status": "PASS" if c in passing else "FAIL",
                             "description": "x"} for c in ("c1", "c2")]}

    # P,P → F(c1) → P,P: c1 passa em 2 dos últimos 3 rounds → aceito (anti-oscilação)
    engine = FakeEngine([report({"c1", "c2"}), report({"c2"}),
                         report({"c1", "c2"}), report({"c1", "c2"})])
    pipeline.engine = engine  # type: ignore[assignment]
    ok, detail, _kind = asyncio.run(pipeline._probe_locked(make_envelope()))
    assert ok, detail


def test_hard_tier_addendum_has_rules_and_example() -> None:
    assert "node_commands run over SSH" in pl.HARD_TIER_ADDENDUM
    assert "DETERMINISTIC" in pl.HARD_TIER_ADDENDUM
    assert pl._HARD_EXAMPLE.strip().startswith("{") and "killer_hardcore" in pl._HARD_EXAMPLE


def test_backup_script_tolerates_missing_paths() -> None:
    from app.scenario_engine import ScenarioEngine

    script = ScenarioEngine()._backup_script("scen1", ["/opt/edge/marker"])
    assert "if [ -e " in script
    assert "cp -a /opt/edge/marker" in script


def test_jsonpath_list_mode_is_allowed_with_selector() -> None:
    env = make_envelope(checks=[
        {"id": "c1", "description": "pods on node01", "type": "kubectl_jsonpath",
         "params": {"kind": "pods", "namespace": "cka-gen", "label_selector": "app=web",
                    "jsonpath": "{.items[*].spec.nodeName}", "operator": "regex",
                    "expected": "node01"}},
    ])
    errors = make_pipeline()._param_errors(env)
    assert errors == [], errors
    assert make_pipeline()._consistency_errors(env) == []


def test_jsonpath_without_name_or_selector_is_rejected() -> None:
    env = make_envelope(checks=[
        {"id": "c1", "description": "all pods", "type": "kubectl_jsonpath",
         "params": {"kind": "pods", "namespace": "cka-gen",
                    "jsonpath": "{.items[*].spec.nodeName}"}},
    ])
    errors = make_pipeline()._param_errors(env)
    assert any("name ou label_selector" in e for e in errors), errors


def test_namespace_gate_requires_declared_namespaces() -> None:
    env = make_envelope(solution={"manifests": [
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: svc\n  namespace: undeclared\n"
    ], "commands": []})
    errors = make_pipeline()._namespace_errors(env)
    assert any("undeclared" in e for e in errors), errors


def test_probe_reports_infra_failure_kind() -> None:
    pipeline = make_pipeline()

    class FakeEngine:
        async def apply_setup(self, env): return {"ok": True}
        async def settle(self, ns, timeout_s=60): return True
        async def run_checks(self, env, settle=True):
            return {"all_passed": False, "infra_error": True,
                    "results": [{"check_id": "c1", "status": "ERROR", "description": "x"}]}
        async def cleanup(self, env): return {"ok": True}

    pipeline.engine = FakeEngine()  # type: ignore[assignment]
    ok, detail, kind = asyncio.run(pipeline._probe_locked(make_envelope()))
    assert not ok and kind == "infra", (ok, detail, kind)


def test_repair_merges_only_solution_and_checks() -> None:
    pipeline = make_pipeline()
    calls: list[str] = []

    class FakeClient:
        async def complete(self, messages, **kwargs):
            calls.append(messages[-1]["content"][:20])
            return json.dumps({
                "solution": {"manifests": [], "commands": ["kubectl -n cka-gen rollout restart deployment web"]},
                "checks": BASE["checks"],
            }), {"provider": "fake", "model": "fake"}

    pipeline.client = FakeClient()  # type: ignore[assignment]
    env = make_envelope()
    repaired = asyncio.run(pipeline._repair(env, "solução não resolve os checks:\n - c1"))
    assert repaired is not None
    assert repaired.setup.namespaces == env.setup.namespaces
    assert repaired.title == env.title
    assert repaired.solution.commands[0].startswith("kubectl")
    assert calls


def test_tier_budget_grows_with_difficulty() -> None:
    assert pl.tier_budget("exam_standard") == (6, 2)
    assert pl.tier_budget("killer_hardcore") == (8, 4)
    assert pl.tier_budget("boss_fight") == (10, 5)


def test_namespace_digest_reports_readiness_and_endpoints(monkeypatch) -> None:
    from app.scenario_engine import ScenarioEngine

    async def fake_kubectl(args, timeout=20, stdin_data=None):
        if args[0] == "get" and args[1] == "pods":
            return ProcResult(0, json.dumps({"items": [
                {"metadata": {"name": "web-1"}, "status": {
                    "phase": "Running",
                    "containerStatuses": [{"ready": False, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}},
            ]}), "")
        if args[0] == "get" and args[1] == "svc":
            return ProcResult(0, json.dumps({"items": [
                {"metadata": {"name": "web-svc"},
                 "spec": {"type": "ClusterIP", "selector": {"app": "web"}, "ports": [{"port": 80}]}},
            ]}), "")
        if args[0] == "get" and args[1] == "endpoints":
            return ProcResult(0, json.dumps({"items": [
                {"metadata": {"name": "web-svc"}, "subsets": [{"addresses": [{"ip": "10.0.0.1"}]}]},
            ]}), "")
        return ProcResult(0, "{}", "")

    monkeypatch.setattr("app.scenario_engine.cluster.kubectl", fake_kubectl)
    digest = asyncio.run(ScenarioEngine().namespace_digest(["cka-gen"]))
    pods = digest["cka-gen"]["pods"]
    assert pods[0]["ready"] is False and pods[0]["reason"] == "CrashLoopBackOff"
    svc = digest["cka-gen"]["services"][0]
    assert svc["selector"] == {"app": "web"} and svc["ready_endpoints"] == 1


def test_repair_receives_full_check_matrix_and_namespace_state() -> None:
    pipeline = make_pipeline()
    captured: dict = {}

    class FakeClient:
        async def complete(self, messages, **kwargs):
            captured["user"] = json.loads(messages[-1]["content"])
            return json.dumps({"solution": {"manifests": [], "commands": []},
                               "checks": BASE["checks"]}), {"provider": "fake", "model": "fake"}

    class FakeEngine:
        async def namespace_digest(self, namespaces):
            return {namespaces[0]: {"pods": [{"name": "web-1", "phase": "Pending",
                                              "ready": False, "reason": "Unschedulable"}]}}

    pipeline.client = FakeClient()  # type: ignore[assignment]
    pipeline.engine = FakeEngine()  # type: ignore[assignment]
    pipeline._last_probe_report = {"results": [
        {"check_id": "c1", "description": "pod ready", "status": "FAIL",
         "evidence": {"ready": 0, "min_ready": 1}},
        {"check_id": "c2", "description": "image kept", "status": "PASS", "evidence": {}},
    ]}
    asyncio.run(pipeline._repair(make_envelope(), "solução não resolve os checks"))
    assert [c["check_id"] for c in captured["user"]["checks"]] == ["c1", "c2"]
    assert captured["user"]["checks"][0]["status"] == "FAIL"
    assert captured["user"]["live_namespace_state"]["cka-gen"]["pods"][0]["reason"] == "Unschedulable"
