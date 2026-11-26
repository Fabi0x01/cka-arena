"""CKA Arena — FastAPI server, ClusterLease, curation APIs, sessions, terminal PTY & SSE."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import addons as addons_mod, backup as backup_mod, bank, config, db, mastery, provider, setup_wire, ssh_runner, study, telemetry
from app.cluster_lease import ClusterBusyError, ClusterLease
from app.doctor import ClusterDoctor
from app.events import EventBroker, sse_format
from app.llm_client import LLMClient, merge_for_test, public_config, save_config, test_config
from app.models import (
    DIFFICULTIES,
    DOMAINS,
    HealthResponse,
    PowerRequest,
    PowerStatus,
    SetupSshRequest,
    SetupSshResponse,
)
from app.pipeline import GenerateRequest, GenerationPipeline, JobActiveError as GenerationJobActiveError
from app.power import ClusterPowerManager, JobActiveError
from app.scenario_engine import ScenarioEngine
from app.sessions import SessionError, SessionService
from app.teardown import Teardown
from app.terminal import TerminalError, TerminalRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("cka-arena")

broker = EventBroker()
doctor = ClusterDoctor()
power = ClusterPowerManager(broker, doctor)
scenario_engine = ScenarioEngine()
pipeline = GenerationPipeline(LLMClient(), broker, scenario_engine, doctor)
terminals = TerminalRegistry()
sessions = SessionService(scenario_engine, doctor, terminals=terminals)
reset_teardown = Teardown(scenario_engine, doctor)
lease = ClusterLease(power=power, pipeline=pipeline, sessions=sessions)

STATIC_DIR = config.BASE_DIR / "static"
ALLOWED_ORIGINS = {f"http://127.0.0.1:{config.PORT}", f"http://localhost:{config.PORT}"}


class PracticeRequest(BaseModel):
    count: int = 3
    domains: list[str] | None = None
    difficulty: str | None = None
    mode: str = "study"
    variant: str | None = None
    archetype_id: str | None = None
    allow_destructive: bool | None = None
    strict_psi: bool = False


class ItemStateRequest(BaseModel):
    notes_text: str | None = None
    checked_tasks: list[int] | None = None


class HintRequest(BaseModel):
    level: int = 1


class AuditRequest(BaseModel):
    apply: bool = False


class FinishRequest(BaseModel):
    reset: str = "fast"


class RetireRequest(BaseModel):
    reason: str = "retired by user"
    reason_code: str = "other"


class FeedbackRequest(BaseModel):
    reason_code: str = "other"
    note: str = ""


class TerminalTabRequest(BaseModel):
    preset: str = "host"
    node: str | None = None
    strict_psi: bool | None = None


class PreferencesRequest(BaseModel):
    exam_target_date: str | None = None
    strict_psi_default: bool | None = None
    allow_destructive_practice: bool | None = None


class StudyStageRequest(BaseModel):
    stage: Literal["theory", "practice", "cheatsheet"]
    done: bool = True


class StudyQuizRequest(BaseModel):
    choice_index: int
    question_index: int = 0


class LlmConfigRequest(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    auth_mode: str | None = None
    api_key: str | None = None
    model: str | None = None
    model_flash: str | None = None
    timeout_s: float | None = None
    thinking: str | None = None
    reasoning_effort: str | None = None
    clear_key: bool = False


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    lease.app_state = app_instance.state
    config.ensure_dirs()
    ssh_runner.ensure_exam_contexts()
    db.init_db()
    backfill = bank.backfill_archetypes()
    if backfill.get("questions_updated") or backfill.get("mastery_seeded"):
        logger.info("archetype backfill: %s", backfill)
    aborted = pipeline.recover_interrupted_jobs()
    if aborted:
        logger.info("marked %d interrupted generation_requests as aborted", aborted)
    stale = terminals.sweep_scratch()
    if stale:
        logger.info("swept %d stale terminal workdir(s)", len(stale))
    status = await power.detect()
    logger.info("cluster state on launch: %s", status["state"])
    if config.AUTO_START_ON_LAUNCH and status["state"] == "off":
        logger.info("auto_start_on_launch: starting cluster")
        await power.start_action("start")

    async def prune_terminals() -> None:
        while True:
            await asyncio.sleep(60)
            terminals.prune_idle()

    prune_task = asyncio.create_task(prune_terminals())
    try:
        yield
    finally:
        prune_task.cancel()
        await pipeline.client.aclose()


app = FastAPI(title="CKA Arena", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def err_body(code: str, message: str, detail: str | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if detail:
        body["error"]["detail"] = detail
    return body


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(err_body("http_error", str(exc.detail)), status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return JSONResponse(err_body("internal_error", "internal server error", str(exc)[:300]), status_code=500)


@app.middleware("http")
async def optional_token_auth(request: Request, call_next):
    if config.API_TOKEN and request.url.path.startswith("/api") and request.url.path != "/api/events":
        if request.headers.get("authorization") != f"Bearer {config.API_TOKEN}":
            return JSONResponse(err_body("unauthorized", "invalid or missing token"), status_code=401)
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith(("/static/css/", "/static/js/")):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", include_in_schema=False)
async def health_probe():
    import time as _time
    from pathlib import Path as _Path
    from app import curriculum as _curriculum, llm_client as _llm
    from app import pipeline as _pipeline, planner as _planner
    from app import scenario_engine as _engine, validator as _validator
    try:
        newest = max(
            _Path(module.__file__).stat().st_mtime
            for module in (_pipeline, _engine, _validator, _llm, _curriculum, _planner)
        )
        build = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(newest))
    except OSError:
        build = "unknown"
    return {"ok": True, "app": "cka-arena", "version": app.version, "build": build}


@app.get("/api/cluster/power", response_model=PowerStatus)
async def get_power() -> PowerStatus:
    return PowerStatus(**await power.status())


@app.post("/api/cluster/power", status_code=202)
async def post_power(body: PowerRequest):
    try:
        lease.ensure_for_power(body.action.value)
        job_id = await power.start_action(body.action.value)
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    except JobActiveError as exc:
        return JSONResponse(
            err_body("job_active", f"another job is already running ({exc})"), status_code=409
        )
    return JSONResponse({"job_id": job_id, "action": body.action.value}, status_code=202)


@app.get("/api/cluster/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse(**await doctor.health())


@app.post("/api/cluster/setup-ssh", response_model=SetupSshResponse)
async def setup_ssh(body: SetupSshRequest | None = None):
    password = body.password if body and body.password else config.LAB_PASSWORD
    try:
        vms = await ssh_runner.list_vms()
    except Exception as exc:
        return JSONResponse(
            err_body("multipass_unavailable", "multipass list failed", str(exc)[:300]), status_code=503
        )

    resolved: dict[str, str] = {}
    for name in config.VM_NAMES:
        info = vms.get(name) or {}
        if info.get("state") != "Running":
            return JSONResponse(
                err_body("vm_not_running", f"{name} is not running", "start the cluster first"),
                status_code=409,
            )
        ip = await ssh_runner.resolve_ip(info.get("ips") or [])
        if not ip:
            return JSONResponse(
                err_body("ssh_unreachable", f"{name}: SSH port 22 unreachable"), status_code=503
            )
        resolved[name] = ip

    ssh_runner.ensure_keypair()
    rows: list[dict] = []
    for name in config.VM_NAMES:
        ip = resolved[name]
        authorized = await ssh_runner.ssh_authorized(ip)
        if not authorized:
            copy = await ssh_runner.install_key(ip, password)
            authorized = copy.ok or await ssh_runner.ssh_authorized(ip)
        rows.append({"name": name, "ip": ip, "authorized": authorized})

    ssh_runner.write_managed_ssh_config(resolved)
    kubeconfig_ok = True
    try:
        await ssh_runner.ensure_dedicated_kubeconfig(resolved["controlplane"], password)
    except Exception as exc:
        kubeconfig_ok = False
        rows.append({"name": "kubeconfig", "ip": resolved["controlplane"], "authorized": False,
                     "detail": str(exc)[:200]})

    ok = all(row["authorized"] for row in rows if row["name"] in config.VM_NAMES) and kubeconfig_ok
    return SetupSshResponse(
        ok=ok,
        nodes=rows,
        ssh_config_path=str(config.SSH_CONFIG_PATH),
        kubeconfig_path=str(config.KUBECONFIG_PATH),
    )


@app.post("/api/cluster/sync-profile")
async def sync_cluster_profile():
    prov = provider.get()
    if prov.name == "kind":
        results = await setup_wire.sync_kind_node_exam_profile()
        return {"ok": any(results.values()), "nodes": results}
    nodes = await prov.nodes()
    ips = {name: info.ip for name, info in nodes.items() if info.ip}
    if not ips:
        return JSONResponse(
            err_body("cluster_unreachable", "no cluster node IPs available for SSH sync"),
            status_code=503,
        )
    results = await ssh_runner.sync_node_exam_profile(ips)
    return {"ok": all(results.values()), "nodes": results}


@app.post("/api/cluster/install-addons")
async def install_cluster_addons():
    results = {
        "metrics_server": await addons_mod.install_metrics_server(),
        "gateway_api": await addons_mod.install_gateway(),
        "local_path_storage": await addons_mod.install_local_path(),
    }
    return {"ok": all(results.values()), "results": results}


@app.get("/api/backup/status")
def get_backup_status():
    return backup_mod.status_report()


@app.post("/api/backup/create")
def create_backup_snapshot():
    return backup_mod.create_backup()


# ------------------------------------------------------------ generation

@app.post("/api/generate", status_code=202)
async def generate(body: GenerateRequest):
    if not body.domains or any(domain not in DOMAINS for domain in body.domains):
        return JSONResponse(err_body("invalid_domains", "one or more domains are invalid"), status_code=422)
    if body.difficulty not in DIFFICULTIES:
        return JSONResponse(err_body("invalid_difficulty", "invalid difficulty"), status_code=422)
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    status = await power.status()
    if status["state"] != "ready":
        return JSONResponse(
            err_body("cluster_not_ready", f"cluster state is '{status['state']}'", "start the cluster first"),
            status_code=409,
        )
    try:
        job_id = await pipeline.start(body)
    except GenerationJobActiveError as exc:
        return JSONResponse(
            err_body("generation_active", f"a generation job is already running ({exc})"), status_code=409
        )
    return JSONResponse(
        {"job_id": job_id, "generation_request_id": pipeline.active_request_id}, status_code=202
    )


@app.post("/api/generate/cancel")
async def cancel_generation():
    cancelled = await pipeline.cancel()
    return {"cancelled": cancelled}


@app.post("/api/generate/fill-gaps", status_code=202)
async def generate_fill_gaps(max_count: int = 5):
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    status = await power.status()
    if status["state"] != "ready":
        return JSONResponse(
            err_body("cluster_not_ready", f"cluster state is '{status['state']}'", "start the cluster first"),
            status_code=409,
        )
    try:
        info = await pipeline.start_fill_gaps(max_count=max(1, min(10, max_count)))
    except GenerationJobActiveError as exc:
        return JSONResponse(err_body("generation_active", f"a generation job is already running ({exc})"), status_code=409)
    return JSONResponse(info, status_code=202)


@app.post("/api/generate/fill-archetypes", status_code=202)
async def generate_fill_archetypes(max_count: int = 8):
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    status = await power.status()
    if status["state"] != "ready":
        return JSONResponse(
            err_body("cluster_not_ready", f"cluster state is '{status['state']}'", "start the cluster first"),
            status_code=409,
        )
    try:
        info = await pipeline.start_fill_archetypes(max_count=max(1, min(15, max_count)))
    except GenerationJobActiveError as exc:
        return JSONResponse(err_body("generation_active", f"a generation job is already running ({exc})"), status_code=409)
    return JSONResponse(info, status_code=202)


@app.post("/api/generate/archetype/{archetype_id}", status_code=202)
async def generate_for_archetype(archetype_id: str, difficulty: str | None = None):
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    status = await power.status()
    if status["state"] != "ready":
        return JSONResponse(
            err_body("cluster_not_ready", f"cluster state is '{status['state']}'", "start the cluster first"),
            status_code=409,
        )
    try:
        job_id = await pipeline.start_for_archetype(archetype_id, difficulty=difficulty)
    except ValueError as exc:
        return JSONResponse(err_body("not_found", str(exc)), status_code=404)
    except GenerationJobActiveError as exc:
        return JSONResponse(err_body("generation_active", f"a generation job is already running ({exc})"), status_code=409)
    return JSONResponse({"job_id": job_id, "generation_request_id": pipeline.active_request_id}, status_code=202)


@app.get("/api/generate/status")
async def generation_status():
    return {"job": pipeline.snapshot()}


# ------------------------------------------------------------ telemetry, readiness & bank curation

@app.get("/api/readiness")
async def readiness():
    return mastery.readiness_report()


@app.get("/api/study-plan/today")
async def study_plan_today():
    return mastery.daily_study_plan()


@app.get("/api/telemetry")
async def telemetry_summary():
    return telemetry.summary()


@app.get("/api/bank/coverage")
async def bank_coverage():
    return {"cells": bank.coverage(), "published": bank.count_published(), "states": bank.state_counts()}


@app.post("/api/bank/audit")
async def audit_bank(body: AuditRequest | None = None):
    return bank.audit_legacy_questions(apply=bool(body.apply) if body else False)


@app.get("/api/bank/preview")
async def bank_preview(
    count: int = 5,
    domains: str | None = None,
    difficulty: str | None = None,
    mode: str = "study",
    variant: str | None = None,
    archetype_id: str | None = None,
    allow_destructive: bool | None = None,
):
    domain_list = [domain for domain in (domains or "").split(",") if domain] or None
    strategy = variant if variant in ("weakness_drill", "speed_blitz", "mistake_replay") else "exam_balanced"
    is_mock = mode == "mock_exam" or variant in ("guided_mock", "blind_exam")
    effective_destructive = is_mock if allow_destructive is None else allow_destructive
    sample = bank.draw_exam_sample(
        count,
        domains=domain_list,
        difficulty=difficulty,
        allow_destructive=effective_destructive,
        ensure_disjoint_namespaces=is_mock,
        strategy=strategy,
        archetype_id=archetype_id or None,
    )
    return {
        "allocation": sample["allocation"],
        "returned": sample["returned"],
        "fallbacks": sample["fallbacks"],
        "items": [
            {"title": item["title"], "domain": item["domain"], "difficulty": item["difficulty"],
             "weight": item.get("weight_pct")}
            for item in sample["items"]
        ],
    }


@app.get("/api/bank/questions")
async def list_bank_questions(
    state: str | None = None,
    domain: str | None = None,
    difficulty: str | None = None,
    source: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    return bank.list_questions(
        state=state or None, domain=domain or None, difficulty=difficulty or None,
        source=source or None, query=q or None, limit=limit, offset=offset,
    )


@app.get("/api/bank/questions/{question_id}")
async def get_bank_question(question_id: str):
    item = bank.get_question(question_id)
    if not item:
        return JSONResponse(err_body("not_found", "question not found"), status_code=404)
    return item


@app.post("/api/bank/questions/{question_id}/reprobe")
async def reprobe_bank_question(question_id: str):
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    try:
        return await pipeline.reprobe_question(question_id)
    except ValueError as exc:
        return JSONResponse(err_body("not_found", str(exc)), status_code=404)


@app.post("/api/bank/questions/{question_id}/repair")
async def repair_bank_question(question_id: str):
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    try:
        return await pipeline.repair_question(question_id)
    except ValueError as exc:
        return JSONResponse(err_body("not_found", str(exc)), status_code=404)


@app.post("/api/bank/questions/{question_id}/polish")
async def polish_bank_question(question_id: str):
    try:
        lease.ensure_for_generation()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    try:
        return await pipeline.polish_question(question_id)
    except ValueError as exc:
        return JSONResponse(err_body("not_found", str(exc)), status_code=404)


@app.post("/api/bank/questions/{question_id}/feedback")
async def feedback_bank_question(question_id: str, body: FeedbackRequest):
    if not bank.get_question(question_id):
        return JSONResponse(err_body("not_found", "question not found"), status_code=404)
    return bank.record_feedback(question_id, body.reason_code, body.note)


@app.post("/api/bank/questions/{question_id}/retire")
async def retire_bank_question(question_id: str, body: RetireRequest | None = None):
    ok = bank.retire_question(question_id, reason=(body.reason if body else "retired by user"))
    if not ok:
        return JSONResponse(err_body("not_found", "question not found"), status_code=404)
    return {"ok": True, "state": "retired"}


@app.delete("/api/bank/questions/{question_id}")
async def delete_bank_question(question_id: str):
    ok, msg = bank.delete_question(question_id)
    if not ok:
        return JSONResponse(err_body("delete_failed", msg), status_code=409)
    return {"ok": True}


# ------------------------------------------------------------ study codex

@app.get("/api/study/overview")
async def get_study_overview():
    return study.get_overview()


@app.get("/api/study/topics/{topic_id}")
async def get_study_topic(topic_id: str):
    topic = study.get_topic(topic_id)
    if not topic:
        return JSONResponse(err_body("not_found", f"study topic {topic_id} not found"), status_code=404)
    return topic


@app.post("/api/study/topics/{topic_id}/stage")
async def update_study_stage(topic_id: str, body: StudyStageRequest):
    try:
        return study.set_stage(topic_id, body.stage, body.done)
    except KeyError:
        return JSONResponse(err_body("not_found", f"study topic {topic_id} not found"), status_code=404)
    except ValueError as exc:
        return JSONResponse(err_body("invalid_stage", str(exc)), status_code=422)


@app.get("/api/study/drill")
async def get_study_drill(domain: str | None = None, limit: int = 10):
    return study.get_drill_deck(domain=domain, limit=limit)


@app.post("/api/study/topics/{topic_id}/quiz")
async def submit_study_quiz(topic_id: str, body: StudyQuizRequest):
    try:
        return study.submit_quiz(topic_id, body.choice_index, body.question_index)
    except KeyError:
        return JSONResponse(err_body("not_found", f"study topic {topic_id} not found"), status_code=404)
    except ValueError as exc:
        return JSONResponse(err_body("invalid_choice", str(exc)), status_code=422)


# ------------------------------------------------------------ sessions

@app.get("/api/sessions/active")
async def active_session():
    session_id = sessions.active_session_id()
    if not session_id:
        return {"active": None}
    return {"active": await sessions.get(session_id)}


@app.get("/api/sessions/history")
async def sessions_history(limit: int = 20):
    return {"sessions": sessions.history(limit=limit)}


@app.get("/api/sessions/{session_id}/review")
async def session_review(session_id: str):
    try:
        return sessions.review(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/prev")
async def session_prev(session_id: str):
    try:
        return await sessions.prev(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/practice", status_code=201)
async def practice(body: PracticeRequest):
    try:
        lease.ensure_for_practice()
        return await sessions.create(
            body.count,
            domains=body.domains,
            difficulty=body.difficulty,
            mode=body.mode,
            variant=body.variant,
            archetype_id=body.archetype_id,
            allow_destructive=body.allow_destructive,
            strict_psi=body.strict_psi,
        )
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    try:
        return await sessions.get(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.put("/api/sessions/{session_id}/items/{item_id}/state")
async def update_session_item_state(session_id: str, item_id: str, body: ItemStateRequest):
    try:
        return sessions.update_item_state(
            session_id,
            item_id,
            notes_text=body.notes_text,
            checked_tasks=body.checked_tasks,
        )
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/hint")
async def session_hint(session_id: str, body: HintRequest | None = None):
    try:
        return sessions.get_hint(session_id, level=(body.level if body else 1))
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.get("/api/sessions/{session_id}/postmortem/{item_id}")
async def session_postmortem(session_id: str, item_id: str):
    try:
        return sessions.get_postmortem(session_id, item_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/check")
async def session_check(session_id: str):
    try:
        return await sessions.check(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/next")
async def session_next(session_id: str):
    try:
        return await sessions.next(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/skip")
async def session_skip(session_id: str):
    try:
        return await sessions.skip(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/retire")
async def session_retire_active(session_id: str, body: RetireRequest | None = None):
    try:
        return await sessions.retire_active(
            session_id,
            reason=(body.reason if body else "reported by user"),
            reason_code=(body.reason_code if body else "other"),
        )
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/flag/{item_id}")
async def session_toggle_flag(session_id: str, item_id: str):
    try:
        return await sessions.toggle_flag(session_id, item_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/select/{item_id}")
async def session_select_item(session_id: str, item_id: str):
    try:
        return await sessions.select_item(session_id, item_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/reset")
async def session_reset(session_id: str):
    try:
        return await sessions.reset(session_id)
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.post("/api/sessions/{session_id}/finish")
async def session_finish(session_id: str, body: FinishRequest | None = None):
    try:
        return await sessions.finish(session_id, reset=(body.reset if body else "fast"))
    except SessionError as exc:
        return JSONResponse(err_body(exc.code, exc.message), status_code=exc.status)


@app.get("/api/settings/preferences")
async def get_preferences():
    with db.connect() as conn:
        rows = conn.execute("SELECT key, value_json FROM user_settings").fetchall()
    prefs: dict = {"exam_target_date": None, "strict_psi_default": False, "allow_destructive_practice": False}
    for r in rows:
        try:
            prefs[r["key"]] = json.loads(r["value_json"])
        except (ValueError, TypeError):
            prefs[r["key"]] = r["value_json"]
    return prefs


@app.put("/api/settings/preferences")
async def update_preferences(body: PreferencesRequest):
    now = time.time()
    updates: dict = {}
    if body.exam_target_date is not None:
        updates["exam_target_date"] = body.exam_target_date.strip() or None
    if body.strict_psi_default is not None:
        updates["strict_psi_default"] = bool(body.strict_psi_default)
    if body.allow_destructive_practice is not None:
        updates["allow_destructive_practice"] = bool(body.allow_destructive_practice)
    with db.connect() as conn:
        for k, v in updates.items():
            conn.execute(
                "INSERT INTO user_settings (key, value_json, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                (k, json.dumps(v), now),
            )
    return await get_preferences()


# ------------------------------------------------------------ terminals

@app.post("/api/terminal/tabs", status_code=201)
async def create_terminal_tab(body: TerminalTabRequest):
    strict = body.strict_psi
    if strict is None:
        sid = sessions.active_session_id()
        if sid:
            with db.connect() as conn:
                row = conn.execute("SELECT strict_psi, variant FROM sessions WHERE id = ?", (sid,)).fetchone()
            if row:
                strict = bool(row["strict_psi"]) or row["variant"] == "blind_exam"
    try:
        session = terminals.create(body.preset, body.node, strict_psi=bool(strict))
    except TerminalError as exc:
        return JSONResponse(err_body("terminal_error", str(exc)), status_code=409)
    return session.info()


@app.get("/api/terminal/tabs")
async def list_terminal_tabs():
    return {"tabs": terminals.list()}


@app.delete("/api/terminal/tabs/{tab_id}")
async def close_terminal_tab(tab_id: str):
    if not terminals.close(tab_id):
        return JSONResponse(err_body("tab_missing", "tab not found"), status_code=404)
    return {"ok": True}


@app.websocket("/ws/terminal/{tab_id}")
async def terminal_ws(websocket: WebSocket, tab_id: str):
    origin = websocket.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS and not config.ALLOW_REMOTE:
        await websocket.close(code=4403)
        return
    session = terminals.get(tab_id)
    if not session or session.exit_status is not None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    if session._subscribers:
        await websocket.close(code=4409)
        return
    queue = session.subscribe()
    try:
        if not session.spawned:
            session.spawn()
        await websocket.send_json({"type": "replay", "data": session.replay()})

        async def sender() -> None:
            try:
                while True:
                    message = await queue.get()
                    await websocket.send_json(message)
                    if message.get("type") == "exit":
                        return
            except (WebSocketDisconnect, asyncio.CancelledError):
                return

        async def receiver() -> None:
            try:
                while True:
                    payload = await websocket.receive_json()
                    if payload.get("type") == "input":
                        session.write(str(payload.get("data", "")))
                    elif payload.get("type") == "resize":
                        session.resize(int(payload.get("cols", 120)), int(payload.get("rows", 30)))
            except (WebSocketDisconnect, asyncio.CancelledError):
                return

        sender_task = asyncio.create_task(sender())
        receiver_task = asyncio.create_task(receiver())
        _, pending = await asyncio.wait(
            {sender_task, receiver_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    finally:
        session.unsubscribe(queue)


@app.post("/api/cluster/reset-baseline", status_code=202)
async def reset_baseline():
    try:
        lease.ensure_for_reset()
    except ClusterBusyError as exc:
        return JSONResponse(err_body(exc.owner, exc.detail), status_code=409)
    if getattr(app.state, "reset_running", False):
        return JSONResponse(err_body("reset_active", "clean reset already running"), status_code=409)
    app.state.reset_running = True

    async def run_reset() -> None:
        try:
            result = await reset_teardown.reset_clean()
            broker.publish("cluster.reset.done", {
                "ok": True,
                "level": result.get("level"),
                "drift": (result.get("drift") or {}).get("drift"),
                "nodes_ready": result.get("nodes_ready"),
            })
        except Exception as exc:
            broker.publish("cluster.reset.done", {"ok": False, "error": str(exc)[:300]})
        finally:
            app.state.reset_running = False

    asyncio.create_task(run_reset())
    return {"started": True, "mode": "clean-reset"}


# ------------------------------------------------------------ LLM config & events

@app.get("/api/llm/status")
async def llm_status():
    cfg = pipeline.client.cfg
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "model_flash": cfg["model_flash"],
        "thinking": cfg.get("thinking", "on"),
        "has_key": bool(cfg.get("api_key")) or cfg.get("auth_mode") == "none",
        "source": cfg.get("_source", "unconfigured"),
        "chain": [{"id": prov.id, "model": prov.model} for prov in pipeline.client.chain],
    }


@app.get("/api/llm/config")
async def get_llm_config():
    return public_config()


@app.put("/api/llm/config")
async def put_llm_config(body: LlmConfigRequest):
    try:
        public = save_config(body.model_dump(exclude_none=True))
    except ValueError as exc:
        return JSONResponse(err_body("invalid_llm_config", str(exc)), status_code=400)
    pipeline.client.reload_config()
    return public


@app.post("/api/llm/test")
async def llm_test(body: LlmConfigRequest | None = None):
    cfg = merge_for_test(body.model_dump(exclude_none=True) if body else None)
    try:
        return await test_config(cfg)
    except Exception as exc:
        return JSONResponse(err_body("llm_error", "provider call failed", str(exc)[:300]),
                            status_code=502)


@app.get("/api/events")
async def events(request: Request):
    queue = broker.subscribe()

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            snapshot = pipeline.snapshot()
            if snapshot:
                yield sse_format({"topic": "generation.snapshot", "ts": time.time(),
                                  "job": snapshot})
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                yield sse_format(message)
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
