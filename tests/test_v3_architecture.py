"""Unit & integration tests for CKA Arena v3 architecture (all 5 pillars)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app import bank, cluster, config, curriculum, db, mastery, ssh_runner, terminal
from app.models import (
    CheckSpec,
    DocLink,
    ScenarioEnvelope,
    SetupSpec,
    SolutionSpec,
)
from app.pipeline import gates
from app.pipeline.prober import ScenarioProber
from app.scenario_engine import ScenarioEngine
from app.sessions import SessionError, SessionService, compute_item_credit


def _sample_envelope(
    qid: str,
    *,
    domain: str = "Workloads & Scheduling",
    archetype_id: str | None = "wl-hpa-autoscale",
    namespace: str = "ns-one",
    weight: int = 8,
    checks: list[CheckSpec] | None = None,
) -> ScenarioEnvelope:
    return ScenarioEnvelope(
        id=qid,
        title=f"Scenario {qid}",
        domain=domain,
        subtopics=["HorizontalPodAutoscaler", "metrics-server"],
        difficulty="exam_standard",
        weight=weight,
        estimated_minutes=6.0,
        archetype_id=archetype_id,
        prompt=(
            "Context: Configure autoscaling cleanly.\n\n"
            "Tasks:\n1. Inspect deployment `api`.\n2. Create HPA for `api`."
        ),
        docs_links=[DocLink(label="HPA", url="https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/")],
        hints=[
            "Check deployment requests before wiring HPA.",
            "Target cpuUtilization=70 between 2 and 5 replicas.",
        ],
        fast_solution_commands=[f"k autoscale deploy api -n {namespace} --cpu-percent=70 --min=2 --max=5"],
        setup=SetupSpec(
            namespaces=[namespace],
            manifests=[
                f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: {namespace}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
      - name: web
        image: nginx:1.27-alpine
        resources:
          requests:
            cpu: 50m
"""
            ],
        ),
        solution=SolutionSpec(
            manifests=[
                f"""apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
  namespace: {namespace}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 2
  maxReplicas: 5
"""
            ],
            commands=[f"kubectl apply -k assets/kustomize/overlays/prod -n {namespace}"],
        ),
        checks=checks
        or [
            CheckSpec(
                id="chk-hpa",
                description="HPA api-hpa targets api",
                type="kubectl_resource_exists",
                weight_ratio=1.0,
                params={"kind": "hpa", "name": "api-hpa", "namespace": namespace},
            )
        ],
        reference_solution="Create HPA api-hpa targeting Deployment api.",
    )


class _MockEngine:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.cleaned: list[str] = []
        self.reports: dict[str, dict] = {}
        self.default_report = {
            "all_passed": False,
            "infra_error": False,
            "results": [{"check_id": "chk-1", "status": "FAIL"}],
            "duration_ms": 2,
            "ran_at": 1.0,
        }

    async def apply_setup(self, env: ScenarioEnvelope) -> None:
        self.applied.append(env.id)

    async def cleanup(self, env: ScenarioEnvelope) -> None:
        self.cleaned.append(env.id)

    async def run_checks(self, env: ScenarioEnvelope, *, settle: bool = True) -> dict:
        return self.reports.get(env.id, self.default_report)


class _DummyDoctor:
    pass


# 1. ScenarioEngine transactional setup rollback
def test_apply_setup_rolls_back_via_cleanup_on_failure(monkeypatch) -> None:
    engine = ScenarioEngine()
    env = _sample_envelope("rollback-1")
    cleaned: list[str] = []

    async def ok_kubectl(args, **kwargs):
        return SimpleNamespace(ok=False, out="", err="boom apply error")

    async def fake_ensure_ns(name, labels):
        return None

    async def fake_cleanup(target):
        cleaned.append(target.id)
        return {"deleted": True}

    monkeypatch.setattr(engine, "_ensure_namespace", fake_ensure_ns)
    monkeypatch.setattr(engine, "cleanup", fake_cleanup)
    monkeypatch.setattr(cluster, "kubectl", ok_kubectl)

    with pytest.raises(RuntimeError, match="setup apply failed"):
        asyncio.run(engine.apply_setup(env))
    assert cleaned == ["rollback-1"]


# 2. Pipeline gates: archetype alignment, kustomize assets/, gateway docs domain
def test_gates_archetype_alignment_kustomize_and_gateway_domain(monkeypatch) -> None:
    valid_hpa = _sample_envelope("gate-ok", archetype_id="wl-hpa-autoscale")
    assert gates.archetype_alignment_errors(valid_hpa) == []

    # Missing required HPA resource + keyword should fail alignment
    bad_hpa = _sample_envelope("gate-bad", archetype_id="wl-hpa-autoscale")
    bad_hpa.setup.manifests = []
    bad_hpa.solution.manifests = []
    bad_hpa.checks = [
        CheckSpec(
            id="chk-pod",
            description="Pod exists",
            type="pod_status_ready",
            params={"namespace": "ns-one"},
        )
    ]
    bad_hpa.prompt = "1. Deploy a basic pod named web."
    errs = gates.archetype_alignment_errors(bad_hpa)
    assert errs and "wl-hpa-autoscale" in errs[0]

    # -k assets/... allowed; -k /tmp/bad rejected
    assert gates._references_missing_local_file(["kubectl", "apply", "-k", "assets/kustomize/overlays/prod"]) is False
    assert gates._references_missing_local_file(["kubectl", "apply", "-k", "/tmp/outside"]) is True

    # gateway.networking.k8s.io domain allowed cleanly
    gw_env = _sample_envelope(
        "gate-gw",
        domain="Services & Networking",
        archetype_id="sn-gateway-api-route",
        checks=[
            CheckSpec(
                id="chk-gw",
                description="HTTPRoute exists",
                type="kubectl_resource_exists",
                params={"kind": "httproute", "name": "api-route", "namespace": "ns-one"},
            )
        ],
    )
    gw_env.docs_links = [DocLink(label="Gateway API", url="https://gateway.networking.k8s.io/guides/")]
    gw_env.solution.manifests = [
        """apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: ns-one
spec:
  rules: []
"""
    ]
    gw_env.solution.commands = []

    async def noop_kubectl(args, **kwargs):
        return SimpleNamespace(ok=True, out="", err="")

    monkeypatch.setattr(cluster, "kubectl", noop_kubectl)
    gate_errs = asyncio.run(gates.validate_gates(gw_env))
    assert not any("allowed exam docs" in e for e in gate_errs)


# 3. Post-Cleanup Leak Gate
def test_prober_check_post_cleanup_leaks_detects_leftover_resources(monkeypatch) -> None:
    prober = ScenarioProber(ScenarioEngine())
    env = _sample_envelope("leak-check")

    async def fake_kubectl(args, **kwargs):
        return SimpleNamespace(ok=True, out="persistentvolume/pv-orphaned\nclusterrole/cr-left", err="")

    monkeypatch.setattr(cluster, "kubectl", fake_kubectl)
    leak_msg = asyncio.run(prober._check_post_cleanup_leaks(env))
    assert "pv-orphaned" in leak_msg
    assert "cr-left" in leak_msg


# 4. Multi-context kubeconfig aliasing
def test_ensure_exam_contexts_is_idempotent(tmp_path) -> None:
    kc = tmp_path / "kubeconfig"
    kc.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Config",
                "clusters": [{"name": "kubernetes", "cluster": {"server": "https://127.0.0.1:6443"}}],
                "users": [{"name": "kubernetes-admin", "user": {}}],
                "contexts": [
                    {"name": "cka", "context": {"cluster": "kubernetes", "user": "kubernetes-admin"}}
                ],
                "current-context": "cka",
            },
            sort_keys=False,
        )
    )
    first = ssh_runner.ensure_exam_contexts(kc)
    second = ssh_runner.ensure_exam_contexts(kc)
    assert set(first) == {"cka", "cka-ops", "cka-edge"}
    assert second == first


# 5. Exam shell files & secret-filtered command history collection
def test_terminal_exam_shell_files_and_command_audit(tmp_path, monkeypatch) -> None:
    db.init_db()
    workdir = tmp_path / "scratch" / "tab-1"
    terminal.write_exam_shell_files(workdir)
    assert (workdir / ".vimrc").is_file()
    env_text = (workdir / ".cka_env.sh").read_text()
    assert "alias k=kubectl" in env_text
    assert 'export do="--dry-run=client -o yaml"' in env_text
    assert 'export now="--force --grace-period=0"' in env_text

    # Prepare session & item FK rows
    e = _sample_envelope("shell-q1")
    qid = bank.publish_question(e, source="seed")["id"]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, mode, variant, started_at, status)"
            " VALUES ('s-cmd', 'Test', 'study', 'study', 100.0, 'active')"
        )
        conn.execute(
            "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state)"
            " VALUES ('si-cmd', 's-cmd', ?, 0, 'active')",
            (qid,),
        )

    (workdir / ".cmd_history.log").write_text(
        "k get pods -A\n"
        "export OPENAI_API_KEY=sk-secret123456\n"
        "k autoscale deploy api --cpu-percent=70 $do\n"
    )
    reg = terminal.TerminalRegistry()
    reg._sessions["tab-1"] = terminal.TerminalSession(tab_id="tab-1", preset="host", workdir=workdir)
    collected = reg.collect_command_history("s-cmd", "si-cmd")
    assert len(collected) == 2
    assert all("sk-secret" not in c for c in collected)
    assert (workdir / ".cmd_history.log").read_text() == ""

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT command_text FROM command_audit WHERE session_item_id = 'si-cmd'"
        ).fetchall()
    assert len(rows) == 2


# 6. SessionService v3 lifecycle: partial credit, non-destructive mock_exam, blind_exam, hints & postmortem
def test_compute_item_credit_partial_weights() -> None:
    env = _sample_envelope(
        "partial-q",
        weight=10,
        checks=[
            CheckSpec(id="c1", description="step 1", type="pod_status_ready", weight_ratio=0.4, params={"namespace": "ns"}),
            CheckSpec(id="c2", description="step 2", type="pod_status_ready", weight_ratio=0.6, params={"namespace": "ns"}),
        ],
    )
    ratio, earned = compute_item_credit(
        env,
        {
            "all_passed": False,
            "infra_error": False,
            "results": [{"check_id": "c1", "status": "PASS"}, {"check_id": "c2", "status": "FAIL"}],
        },
    )
    assert ratio == pytest.approx(0.4)
    assert earned == pytest.approx(4.0)


def _patch_teardown(svc: SessionService, monkeypatch) -> None:
    async def ok_l1():
        return {"level": "L1", "namespaces_deleted": [], "drift": {"drift": False, "nodes": {}}}

    async def ok_l2():
        return {"level": "L2-clean", "api_ready": True, "nodes_ready": True, "drift": {"drift": False, "nodes": {}}}

    monkeypatch.setattr(svc.teardown, "cleanup_session", ok_l1)
    monkeypatch.setattr(svc.teardown, "reset_clean", ok_l2)


def test_non_destructive_mock_exam_navigation_and_blind_batch_grading(monkeypatch) -> None:
    db.init_db()
    e1 = _sample_envelope("mock-q1", domain="Troubleshooting", archetype_id="ts-crashloop-app", namespace="ns-m1", weight=10)
    e2 = _sample_envelope("mock-q2", domain="Storage", archetype_id="st-pvc-sc", namespace="ns-m2", weight=10,
                          checks=[
                              CheckSpec(id="c1", description="step1", type="kubectl_resource_exists", weight_ratio=0.5, params={"kind": "pvc", "name": "pvc1", "namespace": "ns-m2"}),
                              CheckSpec(id="c2", description="step2", type="pvc_bound", weight_ratio=0.5, params={"namespace": "ns-m2", "name": "pvc1"}),
                          ])
    e3 = _sample_envelope("mock-q3", domain="Workloads & Scheduling", archetype_id="wl-hpa-autoscale", namespace="ns-m3", weight=10)
    for e in (e1, e2, e3):
        bank.publish_question(e, source="seed")

    engine = _MockEngine()
    engine.reports[e1.id] = {
        "all_passed": True,
        "infra_error": False,
        "results": [{"check_id": "chk-hpa", "status": "PASS"}],
        "duration_ms": 2,
        "ran_at": 1.0,
    }
    engine.reports[e2.id] = {
        "all_passed": False,
        "infra_error": False,
        "results": [{"check_id": "c1", "status": "PASS"}, {"check_id": "c2", "status": "FAIL"}],
        "duration_ms": 2,
        "ran_at": 1.0,
    }

    svc = SessionService(engine, _DummyDoctor())  # type: ignore[arg-type]
    _patch_teardown(svc, monkeypatch)

    async def flow() -> None:
        s = await svc.create(3, mode="mock_exam", variant="blind_exam")
        sid = s["session"]["id"]
        assert s["session"]["variant"] == "blind_exam"
        assert s["active"]["envelope"]["reference_solution"] is None

        # Blind exam blocks immediate check & hint
        with pytest.raises(SessionError, match="Blind Mock Exam"):
            await svc.check(sid)
        with pytest.raises(SessionError, match="Blind Mock Exam"):
            svc.get_hint(sid, 1)

        # State notepad & checklist persistence
        item1_id = s["items"][0]["id"]
        svc.update_item_state(sid, item1_id, notes_text="check pod logs", checked_tasks=[0])
        refreshed = await svc.get(sid)
        assert refreshed["active"]["notes_text"] == "check pod logs"
        assert refreshed["active"]["checked_tasks"] == [0]

        # Advance Q1 -> Q2 -> Q3 cleanly without calling cleanup()
        step1 = await svc.next(sid)
        assert step1["finished"] is False
        assert step1["session"]["active"]["order_index"] == 1
        assert engine.cleaned == [], "mock_exam next must NOT clean up cluster mid-exam"

        # Revisiting Q1 skips re-applying setup (lazy mounted_at cache)
        applied_before = list(engine.applied)
        await svc.select_item(sid, item1_id)
        assert engine.applied == applied_before

        # Advancing from last Q returns finished=True while keeping active question intact
        await svc.select_item(sid, s["items"][2]["id"])
        end_step = await svc.next(sid)
        assert end_step["finished"] is True
        assert end_step["session"]["active"] is not None

        # Finish blind exam batch-grades Q1 (10/10) + Q2 (5/10 partial) + Q3 (0/10) = 15/30 = 50%
        finished = await svc.finish(sid, reset="fast")
        assert finished["variant"] == "blind_exam"
        assert finished["summary"]["total_weight"] == 30
        assert finished["summary"]["earned_weight"] == pytest.approx(15.0)
        assert finished["summary"]["score_pct"] == 50
        assert len(engine.cleaned) == 3

    asyncio.run(flow())


def test_study_hints_and_postmortem_unlock_flow(monkeypatch) -> None:
    db.init_db()
    e = _sample_envelope("study-h1")
    bank.publish_question(e, source="seed")
    engine = _MockEngine()
    engine.reports[e.id] = {
        "all_passed": True,
        "infra_error": False,
        "results": [{"check_id": "chk-hpa", "status": "PASS"}],
        "duration_ms": 2,
        "ran_at": 1.0,
    }
    svc = SessionService(engine, _DummyDoctor())  # type: ignore[arg-type]
    _patch_teardown(svc, monkeypatch)

    async def flow() -> None:
        s = await svc.create(1, mode="study", variant="study")
        sid = s["session"]["id"]
        item_id = s["active"]["item_id"]
        h1 = svc.get_hint(sid, 1)
        h2 = svc.get_hint(sid, 2)
        h3 = svc.get_hint(sid, 3)
        assert h1["level"] == 1 and "requests" in h1["hint"]
        assert h2["level"] == 2 and "cpuUtilization" in h2["hint"]
        assert h3["level"] == 3 and "Fast CLI" in h3["hint"]

        await svc.check(sid)
        pm = svc.get_postmortem(sid, item_id)
        assert pm["fast_solution_commands"]
        assert "coach" in pm and pm["coach"]["pacing_ratio"] >= 0

    asyncio.run(flow())


# 7. Mastery, Readiness, Adaptive Bank Draw, & Legacy Audit
def test_mastery_readiness_adaptive_draw_and_audit() -> None:
    db.init_db()
    # Populate 2 questions with colliding ns vs disjoint ns + 1 weak mastery cell
    q_weak = _sample_envelope("b-weak", domain="Workloads & Scheduling", archetype_id="wl-hpa-autoscale", namespace="ns-a")
    q_other = _sample_envelope("b-other", domain="Workloads & Scheduling", archetype_id="wl-pdb-disruption", namespace="ns-b")
    q_dup_ns = _sample_envelope("b-dupns", domain="Storage", archetype_id="st-pvc-sc", namespace="ns-a")
    q_clean_ns = _sample_envelope("b-clean", domain="Storage", archetype_id="st-pv-reclaim", namespace="ns-c")

    id_weak = bank.publish_question(q_weak, source="seed")["id"]
    bank.publish_question(q_other, source="seed")
    bank.publish_question(q_dup_ns, source="seed")
    bank.publish_question(q_clean_ns, source="seed")

    # Mark wl-hpa-autoscale as failed & weak
    mastery.record_outcome(
        "wl-hpa-autoscale",
        "Workloads & Scheduling",
        passed=False,
        first_try=False,
        solve_seconds=450.0,
        estimated_minutes=6.0,
        pass_ratio=0.0,
    )
    # Mark st-pv-reclaim as mastered
    mastery.record_outcome(
        "st-pv-reclaim",
        "Storage",
        passed=True,
        first_try=True,
        solve_seconds=120.0,
        estimated_minutes=6.0,
        pass_ratio=1.0,
    )

    rep = mastery.readiness_report()
    assert rep["total_archetypes"] == len(curriculum.ARCHETYPES)
    assert rep["mastered_or_passed_count"] == 1
    assert rep["verdict"] in ("not_yet", "almost", "go")
    assert set(rep["criteria"].keys()) == {
        "mock_exam_avg",
        "domain_floor",
        "syllabus_coverage_pct",
        "median_pacing_ratio",
    }

    # Disjoint namespace enforcement in mock_exam draw
    sample = bank.draw_exam_sample(
        2,
        domains=["Workloads & Scheduling", "Storage"],
        ensure_disjoint_namespaces=True,
        strategy="weakness_drill",
    )
    picked_ids = [it["id"] for it in sample["items"]]
    assert id_weak in picked_ids
    ns_sets = [
        set(json.loads(bank.get_question(it["id"])["envelope_json"])["setup"]["namespaces"])
        for it in sample["items"]
    ]
    assert not (ns_sets[0] & ns_sets[1]), "Mock sample must keep namespaces disjoint"

    # Legacy audit flags symptom spoiler on archetype_id IS NULL LLM question
    spoiler = _sample_envelope("legacy-spoil", archetype_id=None, namespace="ns-leg")
    spoiler.prompt = "Pod fails because selector does not match.\n\nPerform the following tasks:\n1. Fix."
    leg_id = bank.publish_question(spoiler, source="llm")["id"]
    preview = bank.audit_legacy_questions(apply=False)
    assert preview["spoilers_flagged"] >= 1
    applied = bank.audit_legacy_questions(apply=True)
    assert applied["retired_count"] >= 1
    assert bank.get_question(leg_id)["state"] == "retired"

    eff = mastery.analyze_command_efficiency(
        ["kubectl get pods", "kubectl describe pod x"],
        q_weak,
        solve_seconds=600.0,
    )
    assert any("alias" in tip for tip in eff["tips"])


# 8. FastAPI TestClient smoke tests for v3 routes
def test_api_v3_endpoints(monkeypatch) -> None:
    import app.main as main_mod

    db.init_db()
    e1 = _sample_envelope("api-q1", domain="Workloads & Scheduling", archetype_id="wl-hpa-autoscale", namespace="ns-api1")
    bank.publish_question(e1, source="seed")

    fake_engine = _MockEngine()
    fake_engine.reports[e1.id] = {
        "all_passed": True,
        "infra_error": False,
        "results": [{"check_id": "chk-hpa", "status": "PASS"}],
        "duration_ms": 1,
        "ran_at": 1.0,
    }
    monkeypatch.setattr(main_mod.sessions, "engine", fake_engine)
    _patch_teardown(main_mod.sessions, monkeypatch)

    async def ready_status():
        return {"state": "ready"}

    async def fake_fill_gaps(max_count: int = 5):
        return {"job_id": "job-fill", "count": 2, "targets": []}

    async def fake_arch_gen(archetype_id: str, difficulty: str | None = None):
        if archetype_id not in curriculum.ARCHETYPES_BY_ID:
            raise ValueError("unknown archetype")
        return "job-arch"

    monkeypatch.setattr(main_mod.power, "status", ready_status)
    monkeypatch.setattr(main_mod.pipeline, "start_fill_gaps", fake_fill_gaps)
    monkeypatch.setattr(main_mod.pipeline, "start_for_archetype", fake_arch_gen)

    client = TestClient(main_mod.app)

    r_ready = client.get("/api/readiness")
    assert r_ready.status_code == 200
    assert "skill_tree" in r_ready.json()

    r_audit = client.post("/api/bank/audit", json={"apply": False})
    assert r_audit.status_code == 200
    assert "legacy_total" in r_audit.json()

    r_fill = client.post("/api/generate/fill-gaps?max_count=3")
    assert r_fill.status_code == 202
    assert r_fill.json()["job_id"] == "job-fill"

    r_arch = client.post("/api/generate/archetype/ca-kustomize-overlay")
    assert r_arch.status_code == 202
    assert r_arch.json()["job_id"] == "job-arch"

    r_prac = client.post("/api/practice", json={"count": 1, "mode": "study", "variant": "study"})
    assert r_prac.status_code == 201
    sess = r_prac.json()
    sid = sess["session"]["id"]
    iid = sess["active"]["item_id"]

    assert client.put(
        f"/api/sessions/{sid}/items/{iid}/state",
        json={"notes_text": "hello", "checked_tasks": [0]},
    ).status_code == 200
    assert client.post(f"/api/sessions/{sid}/hint", json={"level": 1}).status_code == 200
    assert client.post(f"/api/sessions/{sid}/check").status_code == 200
    r_pm = client.get(f"/api/sessions/{sid}/postmortem/{iid}")
    assert r_pm.status_code == 200
    assert "coach" in r_pm.json()
    assert client.post(f"/api/sessions/{sid}/finish", json={"reset": "fast"}).status_code == 200


def test_seeds_have_canonical_archetypes_and_hints() -> None:
    from app.seed import load_seeds

    seeds = load_seeds()
    assert len(seeds) == 30
    for _path, env in seeds:
        assert env.schema_version == "1.2", env.id
        assert env.archetype_id in curriculum.ARCHETYPES_BY_ID, env.id
        assert len(env.hints) >= 2, env.id
        assert len(env.fast_solution_commands) >= 1, env.id


def test_infer_and_backfill_archetypes() -> None:
    db.init_db()
    legacy = _sample_envelope(
        "legacy-netpol-q",
        domain="Services & Networking",
        archetype_id=None,
        namespace="ns-legacy-np",
    )
    legacy.title = "Repair DNS Egress NetworkPolicy"
    legacy.subtopics = ["NetworkPolicy", "DNS", "egress"]
    qid = bank.publish_question(legacy, source="llm")["id"]

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, mode, variant, status, started_at, finished_at)"
            " VALUES ('s-hist', 'History', 'study', 'study', 'finished', 100.0, 220.0)"
        )
        conn.execute(
            "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state,"
            " started_at, passed_at, attempts, check_pass_ratio)"
            " VALUES ('si-hist', 's-hist', ?, 0, 'passed', 100.0, 220.0, 1, 1.0)",
            (qid,),
        )

    res1 = bank.backfill_archetypes()
    assert res1["questions_updated"] == 1
    assert res1["mastery_seeded"] == 1

    q_row = bank.get_question(qid)
    assert q_row is not None
    assert q_row["archetype_id"] == "sn-networkpolicy-dns"

    # Idempotent second run must not double-count
    res2 = bank.backfill_archetypes()
    assert res2["questions_updated"] == 0
    assert res2["mastery_seeded"] == 0
