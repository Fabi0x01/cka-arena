"""Unit & integration tests for CKA Arena v4 architecture (Phases 1-6)."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app import bank, cluster, config, db, mastery, provider, terminal
from app.doctor import ClusterDoctor
from app.models import (
    CheckSpec,
    DocLink,
    ScenarioEnvelope,
    SetupSpec,
    SolutionSpec,
)
from app.scenario_engine import ScenarioEngine
from app.sessions import SessionService
from app.ssh_runner import ProcResult
from app.teardown import Teardown
from app import validator


def _env(
    qid: str,
    *,
    domain: str = "Workloads & Scheduling",
    archetype_id: str | None = "wl-hpa-autoscale",
    namespace: str = "orders",
    weight: int = 8,
    difficulty: str = "exam_standard",
    prompt: str | None = None,
    checks: list[CheckSpec] | None = None,
) -> ScenarioEnvelope:
    return ScenarioEnvelope(
        id=qid,
        title=f"Configure {qid}",
        domain=domain,  # type: ignore[arg-type]
        subtopics=["HorizontalPodAutoscaler", "metrics-server"],
        difficulty=difficulty,  # type: ignore[arg-type]
        weight=weight,
        estimated_minutes=5.0,
        archetype_id=archetype_id,
        prompt=prompt
        or (
            "Configure workload autoscaling in `orders`.\n\n"
            "Perform the following tasks:\n1. Inspect Deployment `api`.\n2. Create HPA `api-hpa`."
        ),
        copy_tokens=["orders", "api", "api-hpa"],
        docs_links=[DocLink(label="HPA", url="https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/")],
        hints=[
            "Inspect CPU requests on deployment api first.",
            "HPA requires CPU resource requests on containers.",
        ],
        fast_solution_commands=[f"kubectl autoscale deploy api -n {namespace} --name=api-hpa --cpu-percent=70 --min=2 --max=4"],
        setup=SetupSpec(namespaces=[namespace], manifests=[]),
        checks=checks
        or [
            CheckSpec(
                id="chk-1",
                description="HPA exists",
                type="kubectl_resource_exists",
                params={"kind": "hpa", "name": "api-hpa", "namespace": namespace},
                weight_ratio=1.0,
            ),
        ],
        solution=SolutionSpec(manifests=[], commands=[f"kubectl -n {namespace} autoscale deploy api --name=api-hpa --min=2 --max=4"]),
        reference_solution="Autoscale deployment api.",
    )


def test_validator_v4_hardened_checks(monkeypatch) -> None:
    async def _run() -> None:
        # 1. deployment_rollout_ready checks updatedReplicas & unavailableReplicas
        async def deploy_stale(args, timeout=15, stdin_data=None):
            return ProcResult(
                0,
                json.dumps({
                    "metadata": {"generation": 3},
                    "spec": {"template": {"spec": {"containers": [{"image": "nginx:1.27-alpine"}]}}},
                    "status": {
                        "observedGeneration": 3,
                        "updatedReplicas": 1,
                        "readyReplicas": 2,
                        "availableReplicas": 2,
                        "unavailableReplicas": 1,
                    },
                }),
                "",
            )

        monkeypatch.setattr(cluster, "kubectl", deploy_stale)
        st, ev = await validator.chk_deployment_rollout_ready(
            {"namespace": "orders", "name": "api", "min_ready_replicas": 2}
        )
        assert st == validator.FAIL and ev["updated_replicas"] == 1

        # 2. service_endpoints_ready excludes ready=False or terminating=True
        async def eps_not_ready(args, timeout=15, stdin_data=None):
            joined = " ".join(args)
            if "endpointslices" in joined:
                return ProcResult(
                    0,
                    json.dumps({
                        "items": [{
                            "endpoints": [
                                {"conditions": {"ready": False}, "addresses": ["10.0.0.1"]},
                                {"conditions": {"ready": True, "terminating": True}, "addresses": ["10.0.0.2"]},
                                {"conditions": {"ready": True}, "addresses": ["10.0.0.3"]},
                            ]
                        }]
                    }),
                    "",
                )
            return ProcResult(0, json.dumps({"subsets": []}), "")

        monkeypatch.setattr(cluster, "kubectl", eps_not_ready)
        st_ep, ev_ep = await validator.chk_service_endpoints_ready(
            {"namespace": "orders", "service_name": "api-svc", "min_ready_addresses": 2}
        )
        assert st_ep == validator.FAIL and ev_ep["ready_addresses"] == 1

        # 3. kubectl_auth_can_i supports cluster_scoped, subresource, and user
        seen_args: list[list[str]] = []

        async def can_i_mock(args, timeout=15, stdin_data=None):
            seen_args.append(list(args))
            return ProcResult(0, "yes\n", "")

        monkeypatch.setattr(cluster, "kubectl", can_i_mock)
        st_c, _ = await validator.chk_kubectl_auth_can_i({
            "verb": "get",
            "resource": "pods",
            "subresource": "log",
            "user": "jane",
            "cluster_scoped": True,
            "expected_allowed": True,
        })
        assert st_c == validator.PASS
        assert "--subresource=log" in seen_args[-1]
        assert "--as" in seen_args[-1] and "jane" in seen_args[-1]
        assert "-n" not in seen_args[-1]

    asyncio.run(_run())


def test_session_active_timer_and_exact_weights(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()

    q1 = _env("q1", namespace="ns-1", weight=5, checks=[
        CheckSpec(id="c1", description="c1", type="kubectl_resource_exists", params={"kind": "hpa", "name": "a1", "namespace": "ns-1"}, weight_ratio=1.0),
        CheckSpec(id="c2", description="c2", type="kubectl_resource_exists", params={"kind": "hpa", "name": "a2", "namespace": "ns-1"}, weight_ratio=2.0),
    ])
    q2 = _env("q2", namespace="ns-2", weight=10)
    bank.publish_question(q1, source="seed")
    bank.publish_question(q2, source="seed")

    class FakeEngine:
        async def apply_setup(self, env): return {"ok": True}
        async def cleanup(self, env): return {"ok": True}
        async def run_checks(self, env, *, settle=True):
            # Partial pass on q1 (c2 fails), full pass on q2
            if env.id == "q1":
                return {
                    "all_passed": False, "infra_error": False, "duration_ms": 5, "ran_at": time.time(),
                    "results": [{"check_id": "c1", "status": "PASS"}, {"check_id": "c2", "status": "FAIL"}],
                }
            return {
                "all_passed": True, "infra_error": False, "duration_ms": 5, "ran_at": time.time(),
                "results": [{"check_id": "chk-1", "status": "PASS"}],
            }

    class FakeDoctor:
        async def snapshot_node_metadata(self): pass

    class FakeTeardown:
        def __init__(self, *a, **kw): pass
        async def cleanup_session(self): return {"level": "L1"}
        async def reset_clean(self): return {"level": "L2-clean"}

    monkeypatch.setattr("app.sessions.Teardown", FakeTeardown)
    svc = SessionService(FakeEngine(), FakeDoctor())  # type: ignore[arg-type]

    async def _run():
        sess = await svc.create(2, mode="mock_exam", variant="guided_mock")
        sid = sess["session"]["id"]
        item0_id = sess["items"][0]["id"]
        item1_id = sess["items"][1]["id"]
        # Simulate working 5 seconds on item 0, switching to item 1, finishing without clicking check first
        with db.connect() as conn:
            conn.execute("UPDATE session_items SET last_entered_at = ? WHERE id = ?", (time.time() - 5.0, item0_id))
        await svc.select_item(sid, item1_id)
        items_after_switch = svc._items(sid)
        assert items_after_switch[0]["active_seconds"] >= 4.5
        assert items_after_switch[0]["last_entered_at"] is None

        finished = await svc.finish(sid, reset="fast")
        # Both mounted items should be graded: q1 partial (1/3 * 5 = 1.67), q2 full (10.0) -> 11.7
        assert finished["summary"]["earned_weight"] == pytest.approx(11.7, abs=0.2)
        with db.connect() as conn:
            srow = conn.execute("SELECT earned_weight_exact FROM sessions WHERE id = ?", (sid,)).fetchone()
            assert float(srow["earned_weight_exact"]) == pytest.approx(11.67, abs=0.2)

    asyncio.run(_run())


def test_readiness_requires_three_full_mocks_and_filters_study_zero_skips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    q = _env("qr1", namespace="ns-r1")
    qid = bank.publish_question(q, source="seed")["id"]

    now = time.time()
    with db.connect() as conn:
        # Insert 1 partial mock (2 items) -> should NOT satisfy 3 full mocks requirement!
        conn.execute(
            "INSERT INTO sessions (id, title, mode, variant, status, started_at, finished_at, total_weight, earned_weight)"
            " VALUES ('s-short', 'Short Mock', 'mock_exam', 'guided_mock', 'finished', ?, ?, 10, 10)",
            (now - 200, now - 100),
        )
        conn.execute(
            "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state) VALUES ('si-1', 's-short', ?, 0, 'passed')",
            (qid,),
        )
        # Insert 1 zero-attempt skipped study item -> should not count in domain_floor
        conn.execute(
            "INSERT INTO sessions (id, title, mode, variant, status, started_at, finished_at)"
            " VALUES ('s-study', 'Study', 'study', 'study', 'finished', ?, ?)",
            (now - 50, now - 10),
        )
        conn.execute(
            "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state, attempts)"
            " VALUES ('si-skip0', 's-study', ?, 0, 'skipped', 0)",
            (qid,),
        )

    rep = mastery.readiness_report()
    assert rep["criteria"]["mock_exam_avg"]["ok"] is False
    assert rep["criteria"]["mock_exam_avg"]["mocks_completed"] == 0
    assert rep["criteria"]["mock_exam_avg"]["mocks_required"] == 3
    # Only the passed item counted (zero-attempt skipped study item filtered out)
    assert rep["per_domain_accuracy"]["Workloads & Scheduling"] == 100


def test_audit_scans_all_published_llm_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()

    # Archetype-assigned boss fight with fake no-op node command + v1.1 schema
    weak_boss = _env(
        "llm-weak-boss",
        difficulty="boss_fight",
        archetype_id="wl-hpa-autoscale",
    )
    weak_boss.schema_version = "1.1"
    weak_boss.hints = []
    weak_boss.fast_solution_commands = []
    weak_boss.solution = SolutionSpec(manifests=[], commands=["kubectl get pods"], node_commands=[])
    bank.publish_question(weak_boss, source="llm")

    # Spoiler even when archetype_id is NOT null
    spoiler_item = _env(
        "llm-spoil-arch",
        archetype_id="wl-hpa-autoscale",
        prompt="Service fails because wrong selector on web.\n\nPerform the following tasks:\n1. Fix selector.",
    )
    bank.publish_question(spoiler_item, source="llm")

    dry = bank.audit_legacy_questions(apply=False)
    assert dry["scanned_total"] == 2
    assert dry["spoilers_flagged"] >= 1
    assert dry["weak_boss_flagged"] >= 1


def test_terminal_strict_psi_profile_and_no_duplicate_bash_hook(tmp_path) -> None:
    wd_strict = tmp_path / "strict"
    terminal.write_exam_shell_files(wd_strict, strict_psi=True)
    strict_env = (wd_strict / ".cka_env.sh").read_text()
    assert "Strict PSI" in strict_env
    assert "alias k=" not in strict_env
    assert "export do=" not in strict_env

    wd_norm = tmp_path / "norm"
    terminal.write_exam_shell_files(wd_norm, strict_psi=False)
    norm_env = (wd_norm / ".cka_env.sh").read_text()
    assert norm_env.count("PROMPT_COMMAND=") <= 1
    assert "_cka_bash_prompt" in norm_env
    assert "alias k=" in norm_env


def test_teardown_uncordons_and_removes_custom_node_labels(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "BASELINE_NODES_PATH", tmp_path / "baseline_nodes.json")
    (tmp_path / "baseline_nodes.json").write_text(json.dumps({
        "node02": {
            "taints": [],
            "labels": {"kubernetes.io/hostname": "node02"},
            "unschedulable": False,
        }
    }))

    calls: list[list[str]] = []

    async def fake_kubectl(args, timeout=15, stdin_data=None):
        calls.append(list(args))
        if args[:2] == ["get", "nodes"]:
            return ProcResult(
                0,
                json.dumps({
                    "items": [{
                        "metadata": {
                            "name": "node02",
                            "labels": {
                                "kubernetes.io/hostname": "node02",
                                "disktype": "ssd",
                                "cka-arena/role": "test",
                            },
                        },
                        "spec": {
                            "unschedulable": True,
                            "taints": [{"key": "cka-arena/slot", "value": "1", "effect": "NoSchedule"}],
                        },
                    }]
                }),
                "",
            )
        return ProcResult(0, "ok", "")

    monkeypatch.setattr(cluster, "kubectl", fake_kubectl)
    td = Teardown(ScenarioEngine(), ClusterDoctor())
    asyncio.run(td._restore_node_taints())

    joined = [" ".join(c) for c in calls]
    assert any("uncordon node02" in c for c in joined)
    assert any("label node node02 disktype-" in c for c in joined)
    assert any("label node node02 cka-arena/role-" in c for c in joined)
    assert any("taint node node02 cka-arena/slot:NoSchedule-" in c for c in joined)


# ---------------------------------------------------------------- Phase 2: AI Generation Engine v4


def test_v4_gates_reject_boss_noop_spoiler_ns_etcd_trivial_and_cluster_leak(monkeypatch) -> None:
    from app.pipeline import gates
    from app.models import NodeCommand

    monkeypatch.setattr(cluster, "kubectl", lambda *a, **kw: asyncio.sleep(0, result=ProcResult(0, "ok", "")))

    # 1. boss_fight without real node fault rejected
    boss = _env("boss-noop", difficulty="boss_fight", weight=12)
    boss.setup.node_commands = [NodeCommand(node="node01", command="true")]
    errs = asyncio.run(gates.validate_gates(boss))
    assert any("boss_fight" in e for e in errs)

    # 2. spoiler namespace rejected (except cka-gen*)
    spoil_ns = _env("spoil-ns", namespace="broken-svc")
    errs_ns = asyncio.run(gates.validate_gates(spoil_ns))
    assert any("namespace spoiler" in e for e in errs_ns)

    # 3. etcd trivial (?s).+ snapshot check rejected
    etcd_bad = _env(
        "etcd-bad",
        namespace="orders",
        checks=[
            CheckSpec(
                id="chk-snap",
                description="Snapshot non-empty",
                type="host_file_contains",
                params={"location": "controlplane", "path": "/opt/etcd.db", "regex_patterns": ["(?s).+"]},
            )
        ],
    )
    errs_etcd = asyncio.run(gates.validate_gates(etcd_bad))
    assert any("snapshot status" in e for e in errs_etcd)

    # 4. cluster-scoped manifest without cleanup rejected
    leak_pv = _env("leak-pv", namespace="orders")
    leak_pv.setup.manifests = [
        "apiVersion: v1\nkind: PersistentVolume\nmetadata:\n  name: pv-leak\nspec:\n  capacity:\n    storage: 1Gi\n  accessModes: [ReadWriteOnce]\n  hostPath:\n    path: /tmp/pv-leak\n"
    ]
    errs_leak = asyncio.run(gates.validate_gates(leak_pv))
    assert any("cluster-scoped" in e for e in errs_leak)

    # 5. pedagogy gate enforces hints + fast_solution_commands
    no_ped = _env("no-ped", namespace="orders")
    no_ped.hints = []
    no_ped.fast_solution_commands = []
    errs_ped = asyncio.run(gates.validate_gates(no_ped, require_pedagogy=True))
    assert any("hints" in e for e in errs_ped)
    assert any("fast_solution_commands" in e for e in errs_ped)


def test_feedback_feeds_planner_and_architect_reviewer_v2(tmp_path, monkeypatch) -> None:
    from app import planner
    from app.events import EventBroker
    from app.llm_client import LLMClient
    from app.pipeline.orchestrator import GenerationPipeline
    from app.pipeline.prober import ProbeOutcome

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()

    q = _env(
        "fb-1",
        archetype_id="wl-hpa-autoscale",
        weight=4,
        checks=[
            CheckSpec(
                id="chk-1",
                description="HorizontalPodAutoscaler api-hpa exists",
                type="kubectl_resource_exists",
                params={"kind": "HorizontalPodAutoscaler", "name": "api-hpa", "namespace": "orders"},
                weight_ratio=1.0,
            ),
            CheckSpec(
                id="chk-2",
                description="Deployment api ready",
                type="deployment_rollout_ready",
                params={"namespace": "orders", "name": "api", "min_ready_replicas": 1},
                weight_ratio=1.0,
            ),
        ],
    )
    q.setup.manifests = [
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n  namespace: orders\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: api\n  template:\n    metadata:\n      labels:\n        app: api\n    spec:\n      containers:\n      - name: web\n        image: nginx:1.27-alpine\n"
    ]
    qid = bank.publish_question(q, source="llm", quality_score=88, quality_report={"clarity": 18})["id"]
    bank.record_feedback(qid, "broken_check", "Check asserted wrong metric target")
    pitfalls = bank.recent_feedback_pitfalls()
    assert "wl-hpa-autoscale" in pitfalls and "broken_check" in pitfalls["wl-hpa-autoscale"][0]

    slots = planner.plan_slots(
        domains=["Workloads & Scheduling"],
        difficulty="boss_fight",
        count=1,
        constraints=[],
        available_addons={"metrics-server", "gateway", "network_policy", "helm", "etcdctl"},
        coverage_cells=[],
        recent_rows=[],
        seed="v4",
        feedback_pitfalls=pitfalls,
    )
    assert slots[0].incident is not None
    assert slots[0].incident.primary_archetype_id == slots[0].archetype.id

    targeted = planner.plan_slots(
        domains=["Workloads & Scheduling"],
        difficulty="exam_standard",
        count=1,
        constraints=[],
        available_addons=set(),
        coverage_cells=[],
        recent_rows=[],
        seed="v4",
        target_archetype_id="wl-hpa-autoscale",
        feedback_pitfalls=pitfalls,
    )
    assert targeted[0].learned_pitfalls

    gp = GenerationPipeline(LLMClient(), EventBroker(), ScenarioEngine(), ClusterDoctor())

    async def _run():
        # Mock _review directly via complete so Reviewer C v2 parses quality_score & blockers
        async def rev_complete(messages, **kwargs):
            return json.dumps({
                "verdict": "patch",
                "quality_score": 74,
                "scores": {"clarity": 14, "realism": 16, "anti_spoiler": 18, "check_completeness": 12, "solution_hygiene": 14},
                "blockers": ["Port 8080 missing in prompt"],
                "suggestions": ["Clarify namespace"],
                "task_map": {"1": ["chk-1"]},
            }), {"provider": "mock", "model": "mock"}

        monkeypatch.setattr(gp.client, "complete", rev_complete)
        verdict, issues, _meta = await gp._review(q, "exam_standard")
        assert verdict == "patch"
        assert gp._last_review_report is not None
        assert gp._last_review_report["quality_score"] == 74
        assert "Port 8080 missing in prompt" in issues

        # Test polish_question upgrades schema and stores quality_score
        async def polish_complete(messages, **kwargs):
            sys_p = messages[0]["content"]
            if "exam reviewer" in sys_p.lower():
                return json.dumps({
                    "verdict": "approve",
                    "quality_score": 92,
                    "scores": {"clarity": 19, "realism": 18, "anti_spoiler": 19, "check_completeness": 18, "solution_hygiene": 18},
                    "blockers": [],
                    "suggestions": [],
                    "task_map": {"1": ["chk-1"]},
                }), {"provider": "mock", "model": "mock"}
            upgraded = q.model_dump()
            upgraded["schema_version"] = "1.2"
            return json.dumps(upgraded), {"provider": "mock", "model": "mock"}

        monkeypatch.setattr(gp.client, "complete", polish_complete)
        monkeypatch.setattr(cluster, "kubectl", lambda *a, **kw: asyncio.sleep(0, result=ProcResult(0, "configured", "")))
        monkeypatch.setattr(
            gp.prober,
            "probe_retry_detailed",
            lambda *a, **kw: asyncio.sleep(0, result=ProbeOutcome(ok=True, detail="ok", kind="ok")),
        )
        res = await gp.polish_question(qid)
        assert res["ok"] is True, res
        assert res["quality_score"] == 92
        updated_row = bank.get_question(qid)
        assert updated_row["quality_score"] == 92

    asyncio.run(_run())


# ---------------------------------------------------------------- Phase 3: PSI Mock Fidelity, Review & Preferences


def test_phase3_mock_normalization_prev_history_review_and_prefs(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app import main, models

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "KUBECONFIG_PATH", tmp_path / "kubeconfig")
    db.init_db()

    domains = list(models.DOMAINS)
    diffs = ["exam_standard", "exam_standard", "killer_hardcore", "boss_fight"]
    for i in range(12):
        dom = domains[i % len(domains)]
        diff = diffs[i % len(diffs)]
        env = _env(
            f"p3-q{i}",
            domain=dom,
            namespace=f"ns-p3-{i}",
            weight=4 + (i % 7),
            difficulty=diff,
            archetype_id=f"wl-arch-{i}",
            prompt=f"Context mismatch test.\nUse context: kubectl config use-context old-ctx\n\nPerform the following tasks:\n1. Task {i} on `ns-p3-{i}`.",
        )
        bank.publish_question(env, source="seed")

    class FakeEng:
        async def apply_setup(self, env): return {"ok": True}
        async def cleanup(self, env): return {"ok": True}
        async def run_checks(self, env, *, settle=True):
            return {"all_passed": True, "infra_error": False, "duration_ms": 2, "ran_at": time.time(), "results": [{"check_id": "chk-1", "status": "PASS", "description": "ok"}]}

    class FakeDoc:
        async def snapshot_node_metadata(self): pass

    class FakeTd:
        def __init__(self, *a, **kw): pass
        async def cleanup_session(self): return {"level": "L1", "drift": {"drift": False}}
        async def reset_clean(self): return {"level": "L2-clean", "drift": {"drift": False}}

    monkeypatch.setattr("app.sessions.Teardown", FakeTd)
    monkeypatch.setattr(cluster, "current_context", lambda *a, **kw: asyncio.sleep(0, result="cka"))

    test_svc = SessionService(FakeEng(), FakeDoc())  # type: ignore[arg-type]
    monkeypatch.setattr(main, "sessions", test_svc)
    monkeypatch.setattr(main, "lease", type("L", (), {"ensure_for_practice": lambda self: None})())

    client = TestClient(main.app)
    r_pref = client.put("/api/settings/preferences", json={"exam_target_date": "2026-12-20", "strict_psi_default": True})
    assert r_pref.status_code == 200
    assert r_pref.json()["exam_target_date"] == "2026-12-20"
    assert client.get("/api/settings/preferences").json()["strict_psi_default"] is True

    r_create = client.post("/api/practice", json={"count": 10, "mode": "mock_exam", "variant": "blind_exam", "strict_psi": True})
    assert r_create.status_code == 201, r_create.text
    sess = r_create.json()
    sid = sess["session"]["id"]
    assert sess["session"]["total_weight"] == 100
    assert sum(it["weight"] for it in sess["items"]) == 100
    assert sess["session"]["strict_psi"] is True
    active_ctx = sess["active"]["envelope"]["context_command"]
    assert f"Use context: {active_ctx}" in sess["active"]["envelope"]["prompt"]

    # Terminal inherits strict_psi when blind_exam is active
    r_tab = client.post("/api/terminal/tabs", json={"preset": "host"})
    assert r_tab.status_code == 201
    tab_id = r_tab.json()["tab_id"]
    assert main.terminals.get(tab_id).strict_psi is True
    client.delete(f"/api/terminal/tabs/{tab_id}")

    # Navigate next -> prev cleanly
    r_next = client.post(f"/api/sessions/{sid}/next")
    assert r_next.status_code == 200
    assert r_next.json()["session"]["active"]["order_index"] == 1
    r_prev = client.post(f"/api/sessions/{sid}/prev")
    assert r_prev.status_code == 200
    assert r_prev.json()["session"]["active"]["order_index"] == 0

    # Blind review forbidden before finish
    assert client.get(f"/api/sessions/{sid}/review").status_code == 409

    r_fin = client.post(f"/api/sessions/{sid}/finish", json={"reset": "fast"})
    assert r_fin.status_code == 200
    assert r_fin.json()["summary"]["total_weight"] == 100

    r_hist = client.get("/api/sessions/history")
    assert r_hist.status_code == 200
    assert any(row["id"] == sid for row in r_hist.json()["sessions"])

    r_rev = client.get(f"/api/sessions/{sid}/review")
    assert r_rev.status_code == 200
    rev = r_rev.json()
    assert rev["session_id"] == sid
    assert len(rev["items"]) == 10
    assert rev["items"][0]["check_results"]
    assert rev["items"][0]["reference_solution"]


def test_daily_study_plan_speed_coach_and_codex_verified():
    from fastapi.testclient import TestClient
    from app import main, mastery, study
    from app.models import CheckSpec, ScenarioEnvelope, SetupSpec, SolutionSpec

    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO user_settings (key, value_json, updated_at) VALUES (?, ?, 1.0)",
            ("exam_target_date", json.dumps("2026-12-25")),
        )
        conn.execute(
            "INSERT INTO archetype_mastery (archetype_id, domain, attempts, passes, first_try_passes, ewma_solve_ratio, mastery_score, last_practiced_at, next_review_at, interval_days)"
            " VALUES ('ca-etcd-snapshot-save', 'Cluster Architecture, Installation & Configuration', 2, 1, 1, 1.4, 60.0, 100.0, 100.0, 1.0)"
        )

    assert study.topic_id_for_archetype("ca-etcd-snapshot-save") == "ca-etcd-backup-restore"
    overview = study.get_overview()
    etcd_row = next(t for t in overview["topics"] if t["id"] == "ca-etcd-backup-restore")
    assert etcd_row["lab_verified"] is True
    assert study.get_topic("ca-etcd-backup-restore")["lab_verified"] is True

    plan = mastery.daily_study_plan()
    assert plan["exam_target_date"] == "2026-12-25"
    assert plan["days_remaining"] is not None
    assert plan["mocks_required"] == 3
    assert isinstance(plan["items"], list)

    env = ScenarioEnvelope(
        id="coach-test",
        title="Coach Test",
        domain="Workloads & Scheduling",
        difficulty="exam_standard",
        weight=4,
        estimated_minutes=3,
        prompt="Create deployment web",
        setup=SetupSpec(namespaces=["cka-coach"], manifests=[]),
        checks=[
            CheckSpec(id="c1", description="c1", type="kubectl_resource_exists", params={"kind": "deployment", "name": "web", "namespace": "cka-coach"}),
            CheckSpec(id="c2", description="c2", type="deployment_rollout_ready", params={"namespace": "cka-coach", "name": "web", "min_ready_replicas": 1}),
        ],
        solution=SolutionSpec(manifests=[], commands=[]),
        fast_solution_commands=["k -n cka-coach create deploy web --image=nginx"],
    )
    coach = mastery.analyze_command_efficiency(
        [
            "kubectl get pods",
            "kubectl describe pods",
            "kubectl edit deployment web",
            "kubectl edit deployment web",
        ],
        env,
        solve_seconds=360.0,
    )
    joined_tips = " ".join(coach["tips"])
    assert "`k` alias" in joined_tips
    assert "shortnames" in joined_tips.lower()
    assert "`kubectl edit`" in joined_tips
    assert "Fast shortcuts" in joined_tips

    client = TestClient(main.app)
    r_plan = client.get("/api/study-plan/today")
    assert r_plan.status_code == 200
    assert "headline" in r_plan.json()


def test_doctor_v4_and_backup_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import backup, main

    db.init_db()

    class FakeProv:
        transport = "ssh"
        name = "multipass"
        async def nodes(self):
            return {
                n: type("N", (), {"ip": "10.0.0.1", "real_name": n, "state": "Running"})()
                for n in ("controlplane", "node01", "node02")
            }
        async def exec(self, node, cmd, **kw):
            return ProcResult(0, "yes BASELINE_OK", "")

    monkeypatch.setattr(provider, "get", lambda *a, **kw: FakeProv())
    monkeypatch.setattr(cluster, "get_nodes", lambda *a, **kw: asyncio.sleep(0, result=[
        {"name": n, "ready": True, "internal_ip": "10.0.0.1"} for n in ("controlplane", "node01", "node02")
    ]))

    async def fake_kubectl(args, **kw):
        if args and args[0] == "version":
            return ProcResult(0, json.dumps({"serverVersion": {"gitVersion": "v1.34.2"}}), "")
        return ProcResult(0, json.dumps({"items": [], "status": {"conditions": [{"type": "Available", "status": "True"}]}}), "")

    monkeypatch.setattr(cluster, "kubectl", fake_kubectl)
    monkeypatch.setattr(cluster, "crd_exists", lambda *a, **kw: asyncio.sleep(0, result=True))
    monkeypatch.setattr(cluster, "storage_class_exists", lambda *a, **kw: asyncio.sleep(0, result=True))

    h = asyncio.run(ClusterDoctor().health())
    assert h["k8s_version"] == "v1.34.2"
    addon_names = {a["name"]: a["status"] for a in h["addons"]}
    assert "etcdutl (controlplane)" in addon_names
    assert addon_names["etcdutl (controlplane)"] == "present"

    monkeypatch.setattr(config, "BACKUP_DB_PATH", tmp_path / "arena-backup.db")
    monkeypatch.setattr(config, "BACKUP_MANIFEST_PATH", tmp_path / "manifest.json")
    client = TestClient(main.app)
    r_st = client.get("/api/backup/status")
    assert r_st.status_code == 200
    assert r_st.json()["backup"]["exists"] is False

    r_cr = client.post("/api/backup/create")
    assert r_cr.status_code == 200
    assert r_cr.json()["ai_keys_included"] is False
    assert (tmp_path / "arena-backup.db").is_file()
    assert backup.status_report()["backup"]["exists"] is True
