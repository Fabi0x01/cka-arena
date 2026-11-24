"""GenerationPipeline v3 Orchestrator — Request Normalizer → Planner → Builder → Gates → Reviewer → Prober."""

from __future__ import annotations

import asyncio
import json
import platform
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app import bank, cluster, config, curriculum, db, planner, provider
from app.doctor import ClusterDoctor
from app.events import EventBroker
from app.llm_client import LLMClient
from app.models import DIFFICULTIES, DOMAINS, ScenarioEnvelope
from app.pipeline.gates import (
    clamp_band_scalars,
    consistency_errors,
    enrich_defaults,
    extract_json,
    host_path_errors,
    namespace_errors,
    param_errors,
    tier_band_errors,
    validate_gates,
)
from app.pipeline.prober import ScenarioProber
from app.pipeline.prompts import (
    _HARD_EXAMPLE,
    BUILDER_MAX_TOKENS,
    BUILDER_SYSTEM,
    HARD_TIER_ADDENDUM,
    NORMALIZER_MAX_TOKENS,
    NORMALIZER_SYSTEM,
    REPAIR_SYSTEM,
    REVIEW_MAX_TOKENS,
    REVIEWER_SYSTEM,
    band_text,
    repair_cycles_text,
    tier_budget,
)
from app.scenario_engine import ScenarioEngine

JSON_SNIPPET_LIMIT = 4000


class GenerateRequest(BaseModel):
    domains: list[str] = Field(default_factory=lambda: list(DOMAINS))
    subtopics: list[str] = Field(default_factory=list)
    difficulty: str = "exam_standard"
    count: int = Field(default=3, ge=1, le=15)
    focus_hint: str | None = None
    target_archetype_id: str | None = None


class GenerationRequestModel(BaseModel):
    domains: list[str]
    subtopics: list[str] = []
    difficulty: str
    count: int
    constraints: list[str] = []


class JobActiveError(RuntimeError):
    pass


class GenerationPipeline:
    def __init__(
        self,
        client: LLMClient,
        broker: EventBroker,
        engine: ScenarioEngine,
        doctor: ClusterDoctor,
    ) -> None:
        self.client = client
        self.broker = broker
        self.doctor = doctor
        self.prober = ScenarioProber(engine)
        self._active_job: dict | None = None
        self._job: dict | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def engine(self) -> ScenarioEngine:
        return self.prober.engine

    @engine.setter
    def engine(self, value: ScenarioEngine) -> None:
        self.prober.engine = value

    @property
    def _last_probe_report(self) -> dict | None:
        return self.prober.last_probe_report

    @_last_probe_report.setter
    def _last_probe_report(self, value: dict | None) -> None:
        self.prober.last_probe_report = value

    @property
    def _last_probe_digest(self) -> dict | None:
        return self.prober.last_probe_digest

    @_last_probe_digest.setter
    def _last_probe_digest(self, value: dict | None) -> None:
        self.prober.last_probe_digest = value

    # ------------------------------------------------------------ job control

    async def start(self, request: GenerateRequest) -> str:
        async with self._lock:
            if self._active_job:
                raise JobActiveError(self._active_job["id"])
            job_id = uuid.uuid4().hex[:12]
            self._active_job = {
                "id": job_id,
                "request": request.model_dump(),
                "generation_request_id": f"gen-{uuid.uuid4().hex[:10]}",
                "started_at": time.time(),
            }
            self._job = {
                "id": job_id,
                "request": request.model_dump(),
                "status": "running",
                "started_at": time.time(),
                "finished_at": None,
                "total": request.count,
                "current": {
                    "stage": "queued",
                    "detail": "job accepted",
                    "scenario": None,
                    "updated_at": time.time(),
                },
                "scenarios": {},
                "published": [],
                "quarantined": 0,
                "attempted": 0,
                "error": None,
                "duration_s": None,
            }
        self._task = asyncio.create_task(self._run(job_id, request))
        return job_id

    async def start_for_archetype(
        self, archetype_id: str, *, difficulty: str | None = None
    ) -> str:
        arch = curriculum.ARCHETYPES_BY_ID.get(archetype_id)
        if not arch:
            raise ValueError(f"unknown archetype: {archetype_id}")
        diff = difficulty if (difficulty and difficulty in DIFFICULTIES) else arch.difficulties[0]
        return await self.start(
            GenerateRequest(
                domains=[arch.domain],
                subtopics=list(arch.subtopics),
                difficulty=diff,
                count=1,
                focus_hint=f"focus on {arch.id}: {', '.join(arch.subtopics)}",
                target_archetype_id=arch.id,
            )
        )

    async def start_fill_gaps(self, max_count: int = 5) -> dict:
        """Pick the lowest-covered (domain, difficulty) cell in the 5x3 grid and generate a batch."""
        cov = {(c["domain"], c["difficulty"]): int(c["published"]) for c in bank.coverage()}
        avail = await self._addons_available()
        best_score = None
        best_diff = "exam_standard"
        scored_domains: list[tuple[int, str]] = []
        for diff in ("exam_standard", "killer_hardcore", "boss_fight"):
            total_empty = 0
            per_dom: list[tuple[int, str]] = []
            for dom in DOMAINS:
                if curriculum.eligible_archetypes(dom, diff, avail):
                    val = cov.get((dom, diff), 0)
                    per_dom.append((val, dom))
                    if val == 0:
                        total_empty += 1
            if not per_dom:
                continue
            min_val = min(v for v, _ in per_dom)
            rank = (min_val, -total_empty, 0 if diff == "killer_hardcore" else 1)
            if best_score is None or rank < best_score:
                best_score = rank
                best_diff = diff
                scored_domains = sorted(per_dom)

        chosen_domains = [dom for _v, dom in scored_domains[:max(1, min(5, max_count))]] or list(DOMAINS)
        count = max(1, min(max_count, len(chosen_domains)))
        job_id = await self.start(
            GenerateRequest(domains=chosen_domains, difficulty=best_diff, count=count)
        )
        return {"job_id": job_id, "difficulty": best_diff, "domains": chosen_domains, "count": count}

    async def cancel(self) -> bool:
        if not self._active_job or not self._task or self._task.done():
            return False
        self._task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        return True

    def recover_interrupted_jobs(self) -> int:
        try:
            with db.connect() as conn:
                cur = conn.execute(
                    "UPDATE generation_requests SET status = 'aborted' WHERE status = 'running'"
                )
            return cur.rowcount
        except Exception:
            return 0

    def snapshot(self) -> dict | None:
        return self._job

    @property
    def active_job_id(self) -> str | None:
        return self._active_job["id"] if self._active_job else None

    @property
    def active_request_id(self) -> str | None:
        return self._active_job["generation_request_id"] if self._active_job else None

    def _update(
        self,
        job_id: str | None,
        stage: str,
        detail: str,
        *,
        scenario: int | None = None,
        total: int | None = None,
        status: str | None = None,
        question_id: str | None = None,
    ) -> None:
        if not job_id:
            return
        payload = {
            "job_id": job_id,
            "stage": stage,
            "detail": detail,
            "scenario": scenario,
            "total": total,
            "status": status,
            "question_id": question_id,
            "ts": time.time(),
        }
        job = self._job
        if job and job["id"] == job_id:
            job["current"] = {
                "stage": stage,
                "detail": detail,
                "scenario": scenario,
                "updated_at": time.time(),
            }
            if scenario is not None:
                row = job["scenarios"].setdefault(
                    str(scenario),
                    {
                        "index": scenario,
                        "status": "running",
                        "stage": stage,
                        "detail": detail,
                        "attempts": 0,
                        "question_id": None,
                    },
                )
                row["stage"] = stage
                row["detail"] = detail
                if detail.startswith("builder attempt"):
                    try:
                        row["attempts"] = int(detail.split()[2].split("/")[0])
                    except (IndexError, ValueError):
                        pass
                if status:
                    row["status"] = status
                if question_id:
                    row["question_id"] = question_id
        self.broker.publish("generation.progress", payload)

    # ------------------------------------------------------------ main run

    async def _run(self, job_id: str, request: GenerateRequest) -> None:
        started = time.monotonic()
        request_id = self._active_job["generation_request_id"]
        published: list[str] = []
        attempted = 0
        job = self._job

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(4)
                if not self._job or self._job["id"] != job_id or self._job["status"] != "running":
                    return
                self.broker.publish(
                    "generation.heartbeat",
                    {
                        "job_id": job_id,
                        "elapsed_s": round(time.monotonic() - started, 1),
                        "current": self._job["current"],
                        "published": len(published),
                        "quarantined": self._job["quarantined"],
                        "attempted": attempted,
                        "scenarios": self._job["scenarios"],
                    },
                )

        hb = asyncio.create_task(heartbeat())
        try:
            self._db_request(request_id, request, "running")
            self._update(job_id, "A", "normalizing request & planning curriculum slots")
            normalized = await self._normalize(request)
            topology, avail_addons = await asyncio.gather(
                self._topology(),
                self._addons_available(),
            )
            slots = planner.plan_slots(
                domains=normalized.domains,
                difficulty=normalized.difficulty,
                count=normalized.count,
                constraints=normalized.constraints,
                available_addons=avail_addons,
                coverage_cells=bank.coverage(),
                recent_rows=bank.recent_published(40),
                seed=job_id,
                target_archetype_id=request.target_archetype_id,
            )
            self._update(
                job_id,
                "A",
                f"planned {len(slots)} slot(s): {', '.join(s.archetype.id for s in slots)}"[:120],
            )

            semaphore = asyncio.Semaphore(3)
            llm_ready = self.client.is_configured()

            async def run_slot(slot_plan: planner.SlotPlan) -> None:
                nonlocal attempted
                index = slot_plan.slot_index
                scenario = index + 1
                async with semaphore:
                    attempted += 1
                    job["attempted"] = attempted
                    meta = {
                        "strategy": "blueprint_v3",
                        "archetype_id": slot_plan.archetype.id,
                        "incident_id": slot_plan.incident.id if slot_plan.incident else None,
                        "namespace": slot_plan.namespace,
                    }
                    last_candidate: ScenarioEnvelope | None = None
                    if llm_ready:
                        envelope, error, last_candidate = await self._build_one(
                            job_id, normalized, topology, slot_plan
                        )
                    else:
                        envelope, error, last_candidate = None, "no AI provider configured", None

                if envelope is None:
                    job["quarantined"] += 1
                    if last_candidate is not None:
                        bank.publish_question(
                            last_candidate,
                            source="llm",
                            state="draft",
                            probe_result={"error": error[:1000]},
                            generator_meta=meta,
                        )
                    self._update(
                        job_id,
                        "X",
                        f"quarantined (draft): {error}",
                        scenario=scenario,
                        total=normalized.count,
                        status="quarantined",
                    )
                    return

                result = bank.publish_question(
                    envelope, source="llm", state="published", generator_meta=meta
                )
                published.append(result["id"])
                job["published"] = published
                self._update(
                    job_id,
                    "publish",
                    f"published {result['id']}",
                    scenario=scenario,
                    total=normalized.count,
                    status="published",
                    question_id=result["id"],
                )

            await asyncio.gather(*(run_slot(sp) for sp in slots))

            duration = round(time.monotonic() - started, 1)
            self._db_request(request_id, request, "done", attempted, len(published))
            job.update(
                status="done",
                finished_at=time.time(),
                duration_s=duration,
                published=published,
                attempted=attempted,
            )
            self._update(job_id, "done", f"published {len(published)}/{attempted} in {duration}s")
            self.broker.publish(
                "generation.done",
                {
                    "job_id": job_id,
                    "ok": True,
                    "published": published,
                    "quarantined": job["quarantined"],
                    "duration_s": duration,
                    "job": self.snapshot(),
                },
            )
        except asyncio.CancelledError:
            duration = round(time.monotonic() - started, 1)
            self._db_request(request_id, request, "cancelled", attempted, len(published))
            job.update(
                status="error",
                finished_at=time.time(),
                error="cancelled by user",
                duration_s=duration,
            )
            self._update(job_id, "error", "generation cancelled by user")
            self.broker.publish(
                "generation.done",
                {"job_id": job_id, "ok": False, "error": "cancelled by user", "job": self.snapshot()},
            )
            raise
        except Exception as exc:
            self._db_request(request_id, request, "error", attempted, len(published))
            job.update(
                status="error",
                finished_at=time.time(),
                error=str(exc)[:300],
                duration_s=round(time.monotonic() - started, 1),
            )
            self._update(job_id, "error", f"pipeline failed: {str(exc)[:300]}")
            self.broker.publish(
                "generation.done",
                {"job_id": job_id, "ok": False, "error": str(exc)[:300], "job": self.snapshot()},
            )
        finally:
            hb.cancel()
            self._active_job = None
            self._task = None

    # ------------------------------------------------------------ curation: reprobe & repair

    async def reprobe_question(self, question_id: str) -> dict:
        row = bank.get_question(question_id)
        if not row or not row.get("envelope"):
            raise ValueError("question not found")
        env = ScenarioEnvelope.model_validate(row["envelope"])
        self._enrich_defaults(env)
        gates = await self._gates(env)
        if gates:
            err = "gates: " + " | ".join(gates)[:500]
            bank.update_after_probe(question_id, env, state="draft", probe_result={"error": err})
            return {"ok": False, "state": "draft", "error": err}
        ok, detail, _kind = await self._probe_retry(env, job_id=None, scenario=1, total=1)
        if ok:
            bank.update_after_probe(question_id, env, state="published", probe_result={"ok": True})
            return {"ok": True, "state": "published", "error": None}
        bank.update_after_probe(question_id, env, state="draft", probe_result={"error": detail[:800]})
        return {"ok": False, "state": "draft", "error": detail}

    async def repair_question(self, question_id: str) -> dict:
        row = bank.get_question(question_id)
        if not row or not row.get("envelope"):
            raise ValueError("question not found")
        env = ScenarioEnvelope.model_validate(row["envelope"])
        self._enrich_defaults(env)
        prev_err = (row.get("probe_result") or {}).get("error") or "solvability check failed"
        ok, detail, _kind = await self._probe_retry(env, job_id=None, scenario=1, total=1)
        if ok:
            bank.update_after_probe(question_id, env, state="published", probe_result={"ok": True})
            return {"ok": True, "state": "published", "error": None}
        detail = detail or prev_err
        for deep in (False, True):
            repaired = await self._repair(env, detail, deep=deep)
            if not repaired:
                continue
            self._enrich_defaults(repaired)
            if await self._gates(repaired):
                continue
            ok2, detail2, _kind2 = await self._probe_retry(repaired, job_id=None, scenario=1, total=1)
            if ok2:
                bank.update_after_probe(question_id, repaired, state="published", probe_result={"ok": True})
                return {"ok": True, "state": "published", "error": None}
            detail = detail2
            env = repaired
        bank.update_after_probe(question_id, env, state="draft", probe_result={"error": detail[:800]})
        return {"ok": False, "state": "draft", "error": detail}

    # ------------------------------------------------------------ stage A + topology

    async def _normalize(self, request: GenerateRequest) -> GenerationRequestModel:
        fallback = GenerationRequestModel(
            domains=[d for d in request.domains if d in DOMAINS] or list(DOMAINS),
            subtopics=request.subtopics,
            difficulty=request.difficulty if request.difficulty in DIFFICULTIES else "exam_standard",
            count=request.count,
            constraints=[request.focus_hint] if request.focus_hint else [],
        )
        if (
            not request.focus_hint
            and request.difficulty in DIFFICULTIES
            and request.domains
            and all(d in DOMAINS for d in request.domains)
        ):
            return fallback

        user = json.dumps(
            {
                "domains": request.domains,
                "subtopics": request.subtopics,
                "difficulty": request.difficulty,
                "count": request.count,
                "focus_hint": request.focus_hint or "",
            },
            ensure_ascii=False,
        )
        try:
            text, meta = await self.client.complete(
                [{"role": "system", "content": NORMALIZER_SYSTEM}, {"role": "user", "content": user}],
                role="flash",
                temperature=0.0,
                max_tokens=NORMALIZER_MAX_TOKENS,
                json_mode=True,
            )
            self._db_generation("A", meta, user, text, "ok", job_id=self.active_job_id)
            data = extract_json(text)
            model = GenerationRequestModel.model_validate(data)
            model.domains = [d for d in model.domains if d in DOMAINS] or fallback.domains
            if model.difficulty not in DIFFICULTIES:
                model.difficulty = fallback.difficulty
            model.count = max(1, min(15, int(model.count)))
            return model
        except Exception as exc:
            self._db_generation(
                "A", {"provider": "-", "model": "-"}, user, "", "fallback",
                str(exc)[:300], job_id=self.active_job_id,
            )
            return fallback

    async def _topology(self) -> str:
        nodes = await cluster.get_nodes()
        version = await self._k8s_version()
        addons = [f"{a['name']}={a['status']}" for a in await self.doctor.addons()]
        node_lines = "\n".join(
            f"- {n['name']} (ready={n['ready']}, internalIP={n['internal_ip']})" for n in nodes
        ) or "- controlplane, node01, node02"
        return (
            f"Kubernetes: {version} (kubeadm, {platform.machine()}, {provider.get().name}, containerd)\n"
            f"Nodes:\n{node_lines}\n"
            f"kubectl context: {config.KUBECTL_CONTEXT}\n"
            f"Addons: {', '.join(addons)}"
        )

    async def _k8s_version(self) -> str:
        res = await cluster.kubectl(["version", "-o", "json"], timeout=10)
        if res.ok:
            try:
                data = json.loads(res.out)
                return data.get("serverVersion", {}).get("gitVersion", "v1.37.2")
            except ValueError:
                pass
        return "v1.37.2"

    async def _addons_available(self) -> set[str]:
        try:
            addons = await self.doctor.addons()
        except Exception:
            return set()
        available: set[str] = set()
        for addon in addons:
            if addon.get("status") != "present":
                continue
            name = (addon.get("name") or "").lower()
            if "gateway" in name:
                available.add("gateway")
            elif "helm" in name:
                available.add("helm")
            elif "etcdctl" in name:
                available.add("etcdctl")
            elif "metrics" in name:
                available.add("metrics-server")
            elif "network_policy" in name:
                available.add("network_policy")
            elif "local_path" in name:
                available.add("local-path")
        return available

    # ------------------------------------------------------------ stages B/D/C/E

    def _trim_messages(self, messages: list[dict[str, str]], max_len: int = 8) -> list[dict[str, str]]:
        if len(messages) <= max_len:
            return messages
        return messages[:2] + messages[-(max_len - 2):]

    async def _build_one(
        self,
        job_id: str,
        request: GenerationRequestModel,
        topology: str,
        slot_plan: planner.SlotPlan,
    ) -> tuple[ScenarioEnvelope | None, str, ScenarioEnvelope | None]:
        index = slot_plan.slot_index
        namespaces_hint = [slot_plan.namespace]
        if slot_plan.secondary_namespace:
            namespaces_hint.append(slot_plan.secondary_namespace)

        slot_brief: dict[str, Any] = {
            "assigned_domain": slot_plan.domain,
            "assigned_archetype": slot_plan.archetype.id,
            "subtopics": list(slot_plan.archetype.subtopics),
            "difficulty": request.difficulty,
            "assigned_namespaces": namespaces_hint,
            "constraints": request.constraints,
            "guidance": slot_plan.archetype.guidance,
            "required_kinds": list(slot_plan.archetype.required_kinds),
            "required_check_types": list(slot_plan.archetype.required_check_types),
            "destructive": slot_plan.archetype.destructive,
            "avoid_titles_already_in_bank": slot_plan.avoid_titles,
        }
        if slot_plan.incident:
            slot_brief["boss_fight_causal_incident"] = {
                "id": slot_plan.incident.id,
                "theme": slot_plan.incident.title_theme,
                "blueprint": slot_plan.incident.guidance,
            }

        system = (
            BUILDER_SYSTEM
            .replace("{{TOPOLOGY}}", topology)
            .replace("{{DIFFICULTY}}", request.difficulty)
            .replace("{{BAND}}", band_text(request.difficulty))
            .replace("{{SLOT_BRIEF}}", json.dumps(slot_brief, indent=1, ensure_ascii=False))
            .replace("{{FEW_SHOT}}", slot_plan.example_json or _HARD_EXAMPLE)
        )
        if request.difficulty in ("killer_hardcore", "boss_fight"):
            system += HARD_TIER_ADDENDUM

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Generate the assigned scenario envelope now."},
        ]
        last_error = "no attempt"
        last_candidate: ScenarioEnvelope | None = None
        review_cycles = 0
        correction_cycles = 0
        repairs_done = 0
        hard_tier = request.difficulty in ("killer_hardcore", "boss_fight")
        max_attempts, correction_limit = tier_budget(request.difficulty)
        failure_kind = ""

        for attempt in range(max_attempts):
            deep = attempt > 0 and (
                failure_kind in ("schema", "probe") or (hard_tier and attempt > 2)
            )
            role = "main" if (hard_tier or attempt > 0) else "flash"
            self._update(
                job_id,
                "B",
                f"builder attempt {attempt + 1}/{max_attempts} · {slot_plan.archetype.id} · thinking {'on' if deep else 'off'}",
                scenario=index + 1,
                total=request.count,
            )
            try:
                text, meta = await self.client.complete(
                    self._trim_messages(messages),
                    role=role,
                    temperature=0.6 if attempt == 0 else 0.3,
                    max_tokens=BUILDER_MAX_TOKENS,
                    json_mode=True,
                    deep=deep,
                )
            except Exception as exc:
                last_error = f"LLM: {str(exc)[:240]}"
                self._db_generation(
                    "B", {"provider": "-", "model": "-"}, "", "", "error", last_error, job_id=job_id
                )
                await asyncio.sleep(1)
                continue

            self._db_generation("B", meta, slot_plan.archetype.id, text, "ok", job_id=job_id)
            self._update(
                job_id,
                "B",
                f"builder returned {len(text)} chars",
                scenario=index + 1,
                total=request.count,
            )

            try:
                data = extract_json(text)
                envelope = ScenarioEnvelope.model_validate(data)
            except (ValueError, ValidationError) as exc:
                last_error = f"schema: {str(exc)[:400]}"
                failure_kind = "schema"
                messages.append({"role": "assistant", "content": text[:12000]})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous output failed JSON/Pydantic validation: {last_error}. "
                        "Return ONLY the corrected JSON."
                    ),
                })
                continue

            self._enrich_defaults(envelope, slot_plan)
            last_candidate = envelope
            clamped = self._clamp_band_scalars(envelope)
            if clamped:
                self._update(
                    job_id,
                    "D",
                    "band clamp: " + ", ".join(clamped),
                    scenario=index + 1,
                    total=request.count,
                )

            self._update(
                job_id,
                "D",
                "running static + archetype + dry-run gates (setup & solution)",
                scenario=index + 1,
                total=request.count,
            )
            gate_errors = await self._gates(envelope, archetype=slot_plan.archetype)
            if gate_errors:
                self._update(
                    job_id,
                    "D",
                    f"gates rejected: {gate_errors[0][:360]}",
                    scenario=index + 1,
                    total=request.count,
                )
                correction_cycles += 1
                failure_kind = "gates"
                last_error = "gates: " + " | ".join(gate_errors)[:500]
                if correction_cycles > correction_limit:
                    return None, last_error, last_candidate
                messages.append({"role": "assistant", "content": envelope.model_dump_json()})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your envelope failed deterministic gates: {last_error}. "
                        "Fix every listed issue and return ONLY the corrected JSON envelope."
                    ),
                })
                continue
            self._update(job_id, "D", "gates passed", scenario=index + 1, total=request.count)

            verdict, issues, review_meta = await self._review(envelope, request.difficulty)
            self._db_generation(
                "C",
                review_meta,
                envelope.model_dump_json()[:1500],
                json.dumps({"verdict": verdict, "issues": issues}),
                "ok",
                job_id=job_id,
            )
            self._update(
                job_id,
                "C",
                f"reviewer {'approved' if verdict == 'approve' else 'requested patch'}"
                + (f" ({len(issues)} issue(s))" if issues else ""),
                scenario=index + 1,
                total=request.count,
            )
            if verdict == "patch" and issues and review_cycles < 1:
                review_cycles += 1
                failure_kind = "review"
                last_error = f"review: {'; '.join(issues)[:300]}"
                messages.append({"role": "assistant", "content": envelope.model_dump_json()})
                messages.append({
                    "role": "user",
                    "content": (
                        f"The exam reviewer requested fixes: {last_error}. "
                        "Address them and return ONLY the corrected JSON envelope."
                    ),
                })
                continue

            ok, detail, failure_kind_probe = await self._probe_retry(
                envelope, job_id=job_id, scenario=index + 1, total=request.count
            )
            if not ok and failure_kind_probe == "infra":
                return None, f"infra: {detail[:400]}", last_candidate

            if not ok:
                correction_cycles += 1
                failure_kind = "probe"
                last_error = f"probe: {detail[:400]}"
                self._update(
                    job_id,
                    "E",
                    f"probe failed → repairing: {detail[:160]}",
                    scenario=index + 1,
                    total=request.count,
                )

                while repairs_done < 2:
                    use_deep = repairs_done > 0
                    repairs_done += 1
                    repaired = await self._repair(envelope, detail, deep=use_deep, job_id=job_id)
                    if repaired:
                        self._enrich_defaults(repaired, slot_plan)
                        last_candidate = repaired
                        repair_gates = await self._gates(repaired, archetype=slot_plan.archetype)
                        if not repair_gates:
                            ok2, detail2, _kind2 = await self._probe_retry(
                                repaired, job_id=job_id, scenario=index + 1, total=request.count
                            )
                            if ok2:
                                self._update(
                                    job_id,
                                    "E",
                                    "solver-repair resolved the probe",
                                    scenario=index + 1,
                                    total=request.count,
                                )
                                return repaired, "", repaired
                            detail = detail2
                            envelope = repaired
                        else:
                            detail = "gates: " + " | ".join(repair_gates)[:400]
                    self._update(
                        job_id,
                        "E",
                        f"solver-repair attempt failed ({repair_cycles_text(repairs_done)})",
                        scenario=index + 1,
                        total=request.count,
                    )
                    if repairs_done == 1:
                        continue
                    break

                if correction_cycles > correction_limit:
                    return None, last_error, last_candidate
                messages.append({"role": "assistant", "content": envelope.model_dump_json()})
                messages.append({
                    "role": "user",
                    "content": (
                        f"The solvability probe failed:\n{detail[:1500]}\n"
                        "Fix the solution (or checks/setup) so applying the solution makes EVERY check PASS. "
                        "Return ONLY the corrected JSON envelope."
                    ),
                })
                continue

            self._update(
                job_id,
                "E",
                "probe passed (sanity + solvability)",
                scenario=index + 1,
                total=request.count,
            )
            return envelope, "", envelope

        return None, last_error, last_candidate

    async def _review(
        self, envelope: ScenarioEnvelope, difficulty: str
    ) -> tuple[str, list[str], dict]:
        try:
            text, meta = await self.client.complete(
                [
                    {"role": "system", "content": REVIEWER_SYSTEM},
                    {"role": "user", "content": envelope.model_dump_json()},
                ],
                role="flash",
                temperature=0.0,
                max_tokens=REVIEW_MAX_TOKENS,
                json_mode=True,
            )
            data = extract_json(text)
            verdict = "patch" if data.get("verdict") == "patch" else "approve"
            issues = [str(item) for item in (data.get("issues") or [])][:6]
            return verdict, issues, meta
        except Exception as exc:
            return "approve", [], {"provider": "-", "model": f"review-error:{type(exc).__name__}"}

    async def _repair(
        self,
        env: ScenarioEnvelope,
        failure_detail: str,
        *,
        deep: bool = False,
        job_id: str | None = None,
    ) -> ScenarioEnvelope | None:
        report = self.prober.last_probe_report or {}
        matrix = [
            {
                "check_id": result.get("check_id"),
                "description": result.get("description"),
                "status": result.get("status"),
                "evidence": result.get("evidence"),
            }
            for result in report.get("results", [])
        ]
        if self.prober.last_probe_digest is not None:
            digest = self.prober.last_probe_digest
        elif self.engine and hasattr(self.engine, "namespace_digest"):
            try:
                digest = await self.engine.namespace_digest(env.setup.namespaces)
            except Exception:
                digest = {}
        else:
            digest = {}

        user = json.dumps(
            {
                "envelope": env.model_dump(),
                "failure": failure_detail[:2500],
                "checks": matrix,
                "live_namespace_state": digest,
            },
            ensure_ascii=False,
        )
        try:
            text, meta = await self.client.complete(
                [{"role": "system", "content": REPAIR_SYSTEM}, {"role": "user", "content": user}],
                role="main",
                temperature=0.2,
                max_tokens=BUILDER_MAX_TOKENS,
                json_mode=True,
                deep=deep,
            )
            self._db_generation("R", meta, failure_detail[:400], text, "ok", job_id=job_id)
        except Exception as exc:
            self._db_generation(
                "R",
                {"provider": "-", "model": "-"},
                failure_detail[:400],
                "",
                "error",
                str(exc)[:300],
                job_id=job_id,
            )
            return None
        try:
            data = extract_json(text)
            merged = env.model_dump()
            if isinstance(data.get("solution"), dict):
                merged["solution"] = data["solution"]
            checks = data.get("checks")
            if isinstance(checks, list) and checks:
                merged["checks"] = checks
            return ScenarioEnvelope.model_validate(merged)
        except (ValueError, ValidationError):
            return None

    # ------------------------------------------------------------ delegate helpers (kept for unit tests & direct callers)

    def _enrich_defaults(
        self, env: ScenarioEnvelope, slot_plan: planner.SlotPlan | None = None
    ) -> None:
        enrich_defaults(env, slot_plan)

    def _clamp_band_scalars(self, env: ScenarioEnvelope) -> list[str]:
        return clamp_band_scalars(env)

    async def _gates(
        self, env: ScenarioEnvelope, *, archetype: curriculum.Archetype | None = None
    ) -> list[str]:
        return await validate_gates(env, archetype=archetype)

    def _host_path_errors(self, env: ScenarioEnvelope) -> list[str]:
        return host_path_errors(env)

    def _namespace_errors(self, env: ScenarioEnvelope) -> list[str]:
        return namespace_errors(env)

    def _consistency_errors(self, env: ScenarioEnvelope) -> list[str]:
        return consistency_errors(env)

    def _param_errors(self, env: ScenarioEnvelope) -> list[str]:
        return param_errors(env)

    def _tier_band_errors(self, env: ScenarioEnvelope) -> list[str]:
        return tier_band_errors(env)

    def _failure_detail(self, report: dict) -> str:
        return self.prober.failure_detail(report)

    async def _capture_digest(self, env: ScenarioEnvelope) -> None:
        await self.prober.capture_digest(env)

    async def _apply_solution(self, env: ScenarioEnvelope) -> str:
        return await self.prober.apply_solution(env)

    async def _probe(
        self,
        env: ScenarioEnvelope,
        *,
        job_id: str | None = None,
        scenario: int | None = None,
        total: int | None = None,
    ) -> tuple[bool, str, str]:
        return await self.prober.probe(
            env,
            emit=lambda msg: self._update(job_id, "E", msg, scenario=scenario, total=total),
        )

    async def _probe_retry(
        self,
        env: ScenarioEnvelope,
        *,
        job_id: str | None,
        scenario: int,
        total: int,
    ) -> tuple[bool, str, str]:
        return await self.prober.probe_retry(
            env,
            emit=lambda msg: self._update(job_id, "E", msg, scenario=scenario, total=total),
        )

    async def _probe_locked(
        self,
        env: ScenarioEnvelope,
        *,
        job_id: str | None = None,
        scenario: int | None = None,
        total: int | None = None,
    ) -> tuple[bool, str, str]:
        return await self.prober.probe_locked(
            env,
            emit=lambda msg: self._update(job_id, "E", msg, scenario=scenario, total=total),
        )

    # ------------------------------------------------------------ persistence

    def _db_request(
        self,
        request_id: str,
        request: GenerateRequest,
        status: str,
        attempted: int = 0,
        published: int = 0,
    ) -> None:
        try:
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO generation_requests (id, request_json, status, scenarios_attempted,"
                    " scenarios_published, created_at) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(id) DO UPDATE SET status = excluded.status,"
                    " scenarios_attempted = excluded.scenarios_attempted,"
                    " scenarios_published = excluded.scenarios_published",
                    (request_id, request.model_dump_json(), status, attempted, published, time.time()),
                )
        except Exception:
            pass

    def _db_generation(
        self,
        stage: str,
        meta: dict[str, Any],
        prompt_excerpt: str,
        raw_response: str,
        status: str,
        error: str = "",
        *,
        job_id: str | None = None,
    ) -> None:
        try:
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO llm_generations (id, created_at, stage, provider, model,"
                    " prompt_params_json, attempts_used, raw_response, status, error_message,"
                    " job_id, duration_ms, prompt_tokens, completion_tokens, reasoning_tokens)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"lg-{uuid.uuid4().hex[:12]}",
                        time.time(),
                        stage,
                        meta.get("provider", "-"),
                        meta.get("model", "-"),
                        json.dumps({"excerpt": prompt_excerpt[:600]}),
                        1,
                        (raw_response or "")[:JSON_SNIPPET_LIMIT],
                        status,
                        error or None,
                        job_id,
                        meta.get("duration_ms"),
                        meta.get("prompt_tokens"),
                        meta.get("completion_tokens"),
                        meta.get("reasoning_tokens"),
                    ),
                )
        except Exception:
            pass
