"""Practice sessions — study, weakness/speed/replay drills, blind & guided mock exams, partial credit."""

from __future__ import annotations

import json
import time
import uuid

from app import bank, config, curriculum, db, mastery
from app.doctor import ClusterDoctor
from app.models import ScenarioEnvelope
from app.scenario_engine import ScenarioEngine
from app.teardown import Teardown

VALID_MODES = ("study", "mock_exam")
VALID_VARIANTS = (
    "study",
    "weakness_drill",
    "speed_blitz",
    "mistake_replay",
    "guided_mock",
    "blind_exam",
)


class SessionError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def compute_item_credit(envelope: ScenarioEnvelope, report: dict) -> tuple[float, float]:
    """Return (pass_ratio 0..1, earned_weight) using per-check weight_ratio or uniform weights."""
    results = report.get("results") or []
    if report.get("infra_error"):
        return 0.0, 0.0
    if not results:
        ok = bool(report.get("all_passed"))
        return (1.0 if ok else 0.0), (float(envelope.weight) if ok else 0.0)

    ratio_map = {c.id: float(c.weight_ratio or 1.0) for c in envelope.checks}
    total_units = 0.0
    passed_units = 0.0
    for r in results:
        w = ratio_map.get(r.get("check_id", ""), 1.0)
        total_units += w
        if r.get("status") == "PASS":
            passed_units += w
    if total_units <= 0:
        return 0.0, 0.0
    pass_ratio = round(passed_units / total_units, 4)
    if bool(report.get("all_passed")):
        pass_ratio = 1.0
    earned_weight = round(float(envelope.weight) * pass_ratio, 2)
    return pass_ratio, earned_weight


class SessionService:
    def __init__(
        self,
        engine: ScenarioEngine,
        doctor: ClusterDoctor,
        terminals: object | None = None,
    ) -> None:
        self.engine = engine
        self.doctor = doctor
        self.terminals = terminals
        self.teardown = Teardown(engine, doctor)

    # ------------------------------------------------------------ helpers

    def _envelope(self, question_id: str) -> ScenarioEnvelope:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT envelope_json FROM bank_questions WHERE id = ?", (question_id,)
            ).fetchone()
        if not row:
            raise SessionError("question_missing", "question not found in bank", 404)
        return ScenarioEnvelope.model_validate(json.loads(row["envelope_json"]))

    def _session_row(self, session_id: str) -> dict:
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise SessionError("session_missing", "session not found", 404)
        return dict(row)

    def active_session_id(self) -> str | None:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE status = 'active' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def _items(self, session_id: str) -> list[dict]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT si.*, b.title, b.domain, b.difficulty, b.weight_pct, b.estimated_minutes,"
                " b.archetype_id"
                " FROM session_items si JOIN bank_questions b ON b.id = si.bank_question_id"
                " WHERE si.session_id = ? ORDER BY si.order_index",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _active_item(self, session_id: str) -> dict | None:
        return next((item for item in self._items(session_id) if item["state"] == "active"), None)

    def _collect_terminal_commands(self, session_id: str, item_id: str) -> list[str]:
        if self.terminals and hasattr(self.terminals, "collect_command_history"):
            try:
                return self.terminals.collect_command_history(session_id, item_id)
            except Exception:
                return []
        return []

    def _command_history_for_item(self, item_id: str) -> list[str]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT command_text FROM command_audit WHERE session_item_id = ?"
                " ORDER BY ran_at ASC",
                (item_id,),
            ).fetchall()
        return [str(r["command_text"]) for r in rows]

    # ------------------------------------------------------------ create

    async def create(
        self,
        count: int,
        *,
        domains: list[str] | None = None,
        difficulty: str | None = None,
        mode: str = "study",
        variant: str | None = None,
        archetype_id: str | None = None,
    ) -> dict:
        resolved_variant = variant
        if mode not in VALID_MODES:
            if mode in VALID_VARIANTS:
                resolved_variant = mode
                mode = "mock_exam" if mode in ("guided_mock", "blind_exam") else "study"
            else:
                raise SessionError("invalid_mode", f"invalid session mode: {mode}", 422)

        if not resolved_variant:
            resolved_variant = "guided_mock" if mode == "mock_exam" else "study"
        elif resolved_variant not in VALID_VARIANTS:
            raise SessionError("invalid_mode", f"invalid session variant: {resolved_variant}", 422)
        if resolved_variant in ("guided_mock", "blind_exam"):
            mode = "mock_exam"

        active = self.active_session_id()
        if active:
            raise SessionError("session_active", f"session {active} is still active", 409)

        strategy = (
            resolved_variant
            if resolved_variant in ("weakness_drill", "speed_blitz", "mistake_replay")
            else "exam_balanced"
        )
        sample = bank.draw_exam_sample(
            count,
            domains=domains,
            difficulty=difficulty,
            allow_destructive=(mode == "mock_exam"),
            ensure_disjoint_namespaces=(mode == "mock_exam"),
            strategy=strategy,
            archetype_id=archetype_id,
        )
        items = sample["items"]
        if not items:
            raise SessionError("bank_empty", "no published questions match this filter", 409)

        session_id = f"s-{uuid.uuid4().hex[:10]}"
        now = time.time()
        total_weight = sum(int(item.get("weight_pct") or item.get("weight") or 0) for item in items)
        time_limit = 120 if mode == "mock_exam" else (25 if resolved_variant == "speed_blitz" else None)
        title_map = {
            "blind_exam": f"Blind Mock Exam ({len(items)}Q)",
            "guided_mock": f"Mock Exam ({len(items)}Q)",
            "weakness_drill": f"Weakness Drill ({len(items)}Q)",
            "speed_blitz": f"Speed Blitz ({len(items)}Q)",
            "mistake_replay": f"Mistake Replay ({len(items)}Q)",
            "study": f"Practice {len(items)}",
        }
        title = title_map.get(resolved_variant, f"Practice {len(items)}")
        contexts = getattr(config, "KUBECTL_CONTEXTS", ("cka",))

        with db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, mode, variant, difficulty_filter, domains_json,"
                " sample_json, status, started_at, total_weight, time_limit_minutes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    title,
                    mode,
                    resolved_variant,
                    difficulty,
                    json.dumps(domains or []),
                    json.dumps({"allocation": sample["allocation"], "fallbacks": sample["fallbacks"]}),
                    "active",
                    now,
                    total_weight,
                    time_limit,
                ),
            )
            for index, item in enumerate(items):
                ctx_name = contexts[index % len(contexts)] if mode == "mock_exam" else config.KUBECTL_CONTEXT
                conn.execute(
                    "INSERT INTO session_items (id, session_id, bank_question_id, order_index, state, context_name)"
                    " VALUES (?, ?, ?, ?, 'pending', ?)",
                    (f"si-{uuid.uuid4().hex[:10]}", session_id, item["id"], index, ctx_name),
                )

        first = self._items(session_id)[0]
        await self._activate(session_id, first["id"])
        return await self.get(session_id)

    async def _activate(self, session_id: str, item_id: str) -> None:
        session = self._session_row(session_id)
        item = next((i for i in self._items(session_id) if i["id"] == item_id), None)
        if not item:
            raise SessionError("item_missing", "session item not found", 404)
        already_mounted = bool(item.get("mounted_at"))
        is_mock = session["mode"] == "mock_exam"
        if not (is_mock and already_mounted):
            envelope = self._envelope(item["bank_question_id"])
            await self.engine.apply_setup(envelope)
            bank.record_usage(item["bank_question_id"])
        now = time.time()
        with db.connect() as conn:
            conn.execute(
                "UPDATE session_items SET state = 'active', started_at = COALESCE(started_at, ?),"
                " mounted_at = COALESCE(mounted_at, ?) WHERE id = ?",
                (now, now, item_id),
            )

    # ------------------------------------------------------------ read

    async def get(self, session_id: str) -> dict:
        session = self._session_row(session_id)
        items = self._items(session_id)
        active = next((item for item in items if item["state"] == "active"), None)
        if not active:
            finished_items = [item for item in items if item["state"] in ("passed", "skipped")]
            active = finished_items[-1] if finished_items else None
        variant = session.get("variant") or ("guided_mock" if session["mode"] == "mock_exam" else "study")
        is_blind = variant == "blind_exam" and session["status"] == "active"

        active_payload = None
        if active:
            envelope = self._envelope(active["bank_question_id"])
            revealed = active["state"] in ("passed", "skipped") and not is_blind
            last_check = None
            if active.get("last_check_json") and not is_blind:
                try:
                    last_check = json.loads(active["last_check_json"])
                except ValueError:
                    last_check = None
            checked_tasks: list[int] = []
            if active.get("checked_tasks_json"):
                try:
                    checked_tasks = json.loads(active["checked_tasks_json"]) or []
                except ValueError:
                    checked_tasks = []
            ctx_name = active.get("context_name") or config.KUBECTL_CONTEXT
            ctx_cmd = f"kubectl config use-context {ctx_name}" if ctx_name else envelope.context_command

            active_payload = {
                "item_id": active["id"],
                "bank_question_id": active["bank_question_id"],
                "order_index": active["order_index"],
                "item_state": active["state"],
                "attempts": active["attempts"],
                "flagged": bool(active.get("flagged")),
                "mounted": bool(active.get("mounted_at")),
                "earned_weight": float(active.get("earned_weight") or 0.0),
                "check_pass_ratio": float(active.get("check_pass_ratio") or 0.0),
                "notes_text": active.get("notes_text") or "",
                "checked_tasks": checked_tasks,
                "hints_used": int(active.get("hints_used") or 0),
                "passed_at": active["passed_at"],
                "started_at": active["started_at"],
                "last_check": last_check,
                "envelope": {
                    "id": envelope.id,
                    "title": envelope.title,
                    "domain": envelope.domain,
                    "difficulty": envelope.difficulty,
                    "weight": envelope.weight,
                    "estimated_minutes": envelope.estimated_minutes,
                    "context_command": ctx_cmd,
                    "ssh_target": envelope.ssh_target,
                    "destructive": envelope.destructive,
                    "archetype_id": envelope.archetype_id or active.get("archetype_id"),
                    "prompt": envelope.prompt,
                    "copy_tokens": envelope.copy_tokens,
                    "docs_links": [link.model_dump() for link in envelope.docs_links],
                    "hints_count": 3,
                    "check_descriptions": [
                        {"id": check.id, "description": check.description}
                        for check in envelope.checks
                    ],
                    "reference_solution": envelope.reference_solution if revealed else None,
                    "fast_solution_commands": envelope.fast_solution_commands if revealed else [],
                },
            }

        total_weight = int(session.get("total_weight") or 0) or sum(
            int(i.get("weight_pct") or 0) for i in items
        )
        return {
            "session": {
                "id": session["id"],
                "title": session["title"],
                "mode": session["mode"],
                "variant": variant,
                "status": session["status"],
                "started_at": session["started_at"],
                "finished_at": session["finished_at"],
                "time_limit_minutes": session.get("time_limit_minutes"),
                "total_weight": total_weight,
                "counts": {
                    "total": len(items),
                    "passed": sum(1 for item in items if item["state"] == "passed"),
                    "skipped": sum(1 for item in items if item["state"] == "skipped"),
                    "pending": sum(1 for item in items if item["state"] == "pending"),
                    "active": sum(1 for item in items if item["state"] == "active"),
                    "mounted": sum(1 for item in items if item.get("mounted_at")),
                    "flagged": sum(1 for item in items if item.get("flagged")),
                },
            },
            "items": [
                {
                    "id": item["id"],
                    "bank_question_id": item["bank_question_id"],
                    "order_index": item["order_index"],
                    "state": item["state"],
                    "flagged": bool(item.get("flagged")),
                    "mounted": bool(item.get("mounted_at")),
                    "title": item["title"],
                    "domain": item["domain"],
                    "difficulty": item["difficulty"],
                    "weight": item["weight_pct"],
                    "earned_weight": float(item.get("earned_weight") or 0.0),
                    "check_pass_ratio": float(item.get("check_pass_ratio") or 0.0),
                    "estimated_minutes": item["estimated_minutes"],
                    "attempts": item["attempts"],
                    "started_at": item["started_at"],
                }
                for item in items
            ],
            "active": active_payload,
        }

    # ------------------------------------------------------------ actions

    async def check(self, session_id: str) -> dict:
        session = self._session_row(session_id)
        if session.get("variant") == "blind_exam":
            raise SessionError(
                "blind_exam",
                "Immediate Check is disabled during Blind Mock Exam — click Finish / Submit Exam to grade all tasks.",
                409,
            )
        active = self._active_item(session_id)
        if not active:
            raise SessionError("no_active_item", "no active question in this session", 409)
        self._collect_terminal_commands(session_id, active["id"])
        envelope = self._envelope(active["bank_question_id"])
        report = await self.engine.run_checks(envelope)
        now = time.time()
        passed_now = bool(report["all_passed"] and not report["infra_error"])
        pass_ratio, earned_weight = compute_item_credit(envelope, report)
        new_attempts = int(active["attempts"] or 0) + (0 if report.get("infra_error") else 1)

        with db.connect() as conn:
            conn.execute(
                "INSERT INTO check_runs (id, session_item_id, ran_at, all_passed, duration_ms,"
                " results_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"cr-{uuid.uuid4().hex[:10]}",
                    active["id"],
                    report["ran_at"],
                    1 if report["all_passed"] else 0,
                    report["duration_ms"],
                    json.dumps(report["results"]),
                ),
            )
            conn.execute(
                "UPDATE session_items SET attempts = ?, last_check_json = ?,"
                " check_pass_ratio = ?, earned_weight = ? WHERE id = ?",
                (new_attempts, json.dumps(report), pass_ratio, earned_weight, active["id"]),
            )
            if passed_now:
                conn.execute(
                    "UPDATE session_items SET state = 'passed', passed_at = ? WHERE id = ?",
                    (now, active["id"]),
                )

        if passed_now:
            solve_s = max(1.0, now - float(active.get("started_at") or now))
            bank.record_pass(active["bank_question_id"], solve_s, first_try=(new_attempts <= 1))
            arch_id = (
                envelope.archetype_id
                or active.get("archetype_id")
                or curriculum.infer_archetype_id(
                    envelope.domain, envelope.title, envelope.subtopics, envelope.id
                )
            )
            mastery.record_outcome(
                arch_id,
                envelope.domain,
                passed=True,
                first_try=(new_attempts <= 1),
                solve_seconds=solve_s,
                estimated_minutes=envelope.estimated_minutes,
                pass_ratio=1.0,
            )
        session_payload = await self.get(session_id)
        return {"report": report, "session": session_payload}

    async def skip(self, session_id: str) -> dict:
        session = self._session_row(session_id)
        active = self._active_item(session_id)
        if not active:
            raise SessionError("no_active_item", "no active question in this session", 409)
        self._collect_terminal_commands(session_id, active["id"])
        envelope = self._envelope(active["bank_question_id"])
        if session["mode"] != "mock_exam":
            await self.engine.cleanup(envelope)
        now = time.time()
        solve_s = max(1.0, now - float(active.get("started_at") or now))
        arch_id = (
            envelope.archetype_id
            or active.get("archetype_id")
            or curriculum.infer_archetype_id(
                envelope.domain, envelope.title, envelope.subtopics, envelope.id
            )
        )
        mastery.record_outcome(
            arch_id,
            envelope.domain,
            passed=False,
            first_try=False,
            solve_seconds=solve_s,
            estimated_minutes=envelope.estimated_minutes,
            pass_ratio=float(active.get("check_pass_ratio") or 0.0),
        )
        with db.connect() as conn:
            conn.execute("UPDATE session_items SET state = 'skipped' WHERE id = ?", (active["id"],))
        return await self.get(session_id)

    async def retire_active(self, session_id: str, reason: str = "reported by user") -> dict:
        active = self._active_item(session_id)
        if not active:
            raise SessionError("no_active_item", "no active question in this session", 409)
        envelope = self._envelope(active["bank_question_id"])
        await self.engine.cleanup(envelope)
        bank.retire_question(active["bank_question_id"], reason=reason)
        with db.connect() as conn:
            conn.execute("UPDATE session_items SET state = 'skipped' WHERE id = ?", (active["id"],))
        return await self.get(session_id)

    async def toggle_flag(self, session_id: str, item_id: str) -> dict:
        self._session_row(session_id)
        items = self._items(session_id)
        target = next((i for i in items if i["id"] == item_id), None)
        if not target:
            raise SessionError("item_missing", "session item not found", 404)
        new_val = 0 if target.get("flagged") else 1
        with db.connect() as conn:
            conn.execute("UPDATE session_items SET flagged = ? WHERE id = ?", (new_val, item_id))
        return await self.get(session_id)

    async def select_item(self, session_id: str, item_id: str) -> dict:
        session = self._session_row(session_id)
        if session["mode"] != "mock_exam":
            raise SessionError("mode_disallowed", "free navigation is only enabled in mock_exam mode", 409)
        items = self._items(session_id)
        target = next((i for i in items if i["id"] == item_id), None)
        if not target:
            raise SessionError("item_missing", "session item not found", 404)
        current = self._active_item(session_id)
        if current and current["id"] == item_id:
            return await self.get(session_id)
        if current:
            self._collect_terminal_commands(session_id, current["id"])
            # Non-destructive mock navigation: preserve mounted cluster changes until reset/finish
            with db.connect() as conn:
                conn.execute("UPDATE session_items SET state = 'pending' WHERE id = ?", (current["id"],))
        await self._activate(session_id, item_id)
        return await self.get(session_id)

    def update_item_state(
        self,
        session_id: str,
        item_id: str,
        *,
        notes_text: str | None = None,
        checked_tasks: list[int] | None = None,
    ) -> dict:
        self._session_row(session_id)
        items = self._items(session_id)
        if not any(i["id"] == item_id for i in items):
            raise SessionError("item_missing", "session item not found", 404)
        with db.connect() as conn:
            if notes_text is not None:
                conn.execute(
                    "UPDATE session_items SET notes_text = ? WHERE id = ?",
                    (notes_text[:4000], item_id),
                )
            if checked_tasks is not None:
                conn.execute(
                    "UPDATE session_items SET checked_tasks_json = ? WHERE id = ?",
                    (json.dumps(sorted({int(x) for x in checked_tasks})), item_id),
                )
        return {"ok": True}

    def get_hint(self, session_id: str, level: int = 1) -> dict:
        session = self._session_row(session_id)
        if session.get("variant") == "blind_exam":
            raise SessionError("blind_exam", "Hints are disabled during Blind Mock Exam.", 409)
        active = self._active_item(session_id)
        if not active:
            raise SessionError("no_active_item", "no active question in this session", 409)
        envelope = self._envelope(active["bank_question_id"])
        lvl = max(1, min(3, int(level)))
        if lvl == 1:
            text = (
                envelope.hints[0]
                if len(envelope.hints) >= 1 and envelope.hints[0]
                else (
                    f"Inspect resources in namespace(s) {', '.join(envelope.setup.namespaces or ['default'])} "
                    "using `k get all`, `k describe`, and check Pod events."
                )
            )
        elif lvl == 2:
            if len(envelope.hints) >= 2 and envelope.hints[1]:
                text = envelope.hints[1]
            else:
                doc_hint = envelope.docs_links[0].url if envelope.docs_links else "https://kubernetes.io/docs/"
                first_check_hint = next((c.failure_hint for c in envelope.checks if c.failure_hint), "")
                text = first_check_hint or f"Review official docs ({doc_hint}) for subtopics: {', '.join(envelope.subtopics)}."
        else:
            fast = (
                "\nFast CLI: " + " && ".join(envelope.fast_solution_commands)
                if envelope.fast_solution_commands
                else ""
            )
            text = (envelope.reference_solution or "Check solution manifests/commands.") + fast

        new_used = max(int(active.get("hints_used") or 0), lvl)
        with db.connect() as conn:
            conn.execute("UPDATE session_items SET hints_used = ? WHERE id = ?", (new_used, active["id"]))
        return {"level": lvl, "hint": text, "hints_used": new_used}

    def get_postmortem(self, session_id: str, item_id: str) -> dict:
        session = self._session_row(session_id)
        items = self._items(session_id)
        item = next((i for i in items if i["id"] == item_id), None)
        if not item:
            raise SessionError("item_missing", "session item not found", 404)
        envelope = self._envelope(item["bank_question_id"])
        is_blind_active = session.get("variant") == "blind_exam" and session["status"] == "active"
        if is_blind_active:
            raise SessionError("blind_exam", "Post-mortem unlocks after finishing Blind Mock Exam.", 409)
        cmds = self._command_history_for_item(item_id)
        started = float(item.get("started_at") or session["started_at"])
        ended = float(item.get("passed_at") or session.get("finished_at") or time.time())
        solve_s = max(1.0, ended - started)
        coach = mastery.analyze_command_efficiency(cmds, envelope, solve_s)
        return {
            "item_id": item_id,
            "title": envelope.title,
            "domain": envelope.domain,
            "reference_solution": envelope.reference_solution,
            "fast_solution_commands": envelope.fast_solution_commands,
            "solution_manifests": envelope.solution.manifests,
            "solution_commands": envelope.solution.commands,
            "coach": coach,
        }

    async def reset(self, session_id: str) -> dict:
        active = self._active_item(session_id)
        if not active:
            raise SessionError("no_active_item", "no active question in this session", 409)
        envelope = self._envelope(active["bank_question_id"])
        await self.engine.cleanup(envelope)
        await self.engine.apply_setup(envelope)
        now = time.time()
        with db.connect() as conn:
            conn.execute(
                "UPDATE session_items SET started_at = ?, mounted_at = ?, last_check_json = NULL WHERE id = ?",
                (now, now, active["id"]),
            )
        return await self.get(session_id)

    async def next(self, session_id: str) -> dict:
        session = self._session_row(session_id)
        current = self._active_item(session_id)
        if not current:
            finished_items = [
                item for item in self._items(session_id) if item["state"] in ("passed", "skipped")
            ]
            current = finished_items[-1] if finished_items else None
        if current and current["state"] not in ("passed", "skipped") and session["mode"] != "mock_exam":
            raise SessionError("item_not_done", "validate or skip the current question first", 409)
        prev_order = int(current["order_index"]) if current else -1
        was_active = bool(current and current["state"] == "active")
        if current:
            self._collect_terminal_commands(session_id, current["id"])
            if session["mode"] != "mock_exam":
                envelope = self._envelope(current["bank_question_id"])
                await self.engine.cleanup(envelope)
            if was_active:
                with db.connect() as conn:
                    conn.execute("UPDATE session_items SET state = 'pending' WHERE id = ?", (current["id"],))

        pending = [item for item in self._items(session_id) if item["state"] == "pending"]
        after = [item for item in pending if int(item["order_index"]) > prev_order]
        if after:
            nxt = after[0]
        elif session["mode"] != "mock_exam" and pending:
            nxt = pending[0]
        else:
            nxt = None

        if nxt is None:
            if session["mode"] == "mock_exam" and was_active and current:
                with db.connect() as conn:
                    conn.execute("UPDATE session_items SET state = 'active' WHERE id = ?", (current["id"],))
            session_data = await self.get(session_id)
            return {"finished": True, "session": session_data}
        await self._activate(session_id, nxt["id"])
        session_data = await self.get(session_id)
        return {"finished": False, "session": session_data}

    async def finish(self, session_id: str, *, reset: str = "fast") -> dict:
        session = self._session_row(session_id)
        if session["status"] == "finished":
            raise SessionError("session_finished", "session already finished", 409)

        items = self._items(session_id)
        active = self._active_item(session_id)
        if active:
            self._collect_terminal_commands(session_id, active["id"])

        now = time.time()
        variant = session.get("variant") or ("guided_mock" if session["mode"] == "mock_exam" else "study")

        # In blind_exam, grade every mounted non-skipped item live BEFORE cleaning up cluster!
        if variant == "blind_exam":
            for it in items:
                if it["state"] == "skipped" or not it.get("mounted_at"):
                    continue
                envelope = self._envelope(it["bank_question_id"])
                report = await self.engine.run_checks(envelope)
                passed_now = bool(report["all_passed"] and not report["infra_error"])
                pass_ratio, earned_w = compute_item_credit(envelope, report)
                attempts = int(it["attempts"] or 0) + (0 if report.get("infra_error") else 1)
                with db.connect() as conn:
                    conn.execute(
                        "INSERT INTO check_runs (id, session_item_id, ran_at, all_passed, duration_ms,"
                        " results_json) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"cr-{uuid.uuid4().hex[:10]}",
                            it["id"],
                            report.get("ran_at", now),
                            1 if passed_now else 0,
                            int(report.get("duration_ms") or 0),
                            json.dumps(report.get("results") or []),
                        ),
                    )
                    conn.execute(
                        "UPDATE session_items SET attempts = ?, last_check_json = ?,"
                        " check_pass_ratio = ?, earned_weight = ?,"
                        " state = ?, passed_at = COALESCE(passed_at, ?) WHERE id = ?",
                        (
                            attempts,
                            json.dumps(report),
                            pass_ratio,
                            earned_w,
                            "passed" if passed_now else "skipped",
                            now if passed_now else None,
                            it["id"],
                        ),
                    )
                solve_s = max(1.0, now - float(it.get("started_at") or session["started_at"]))
                if passed_now:
                    bank.record_pass(it["bank_question_id"], solve_s, first_try=True)
                arch_id = (
                    envelope.archetype_id
                    or it.get("archetype_id")
                    or curriculum.infer_archetype_id(
                        envelope.domain, envelope.title, envelope.subtopics, envelope.id
                    )
                )
                mastery.record_outcome(
                    arch_id,
                    envelope.domain,
                    passed=passed_now,
                    first_try=passed_now,
                    solve_seconds=solve_s,
                    estimated_minutes=envelope.estimated_minutes,
                    pass_ratio=pass_ratio,
                )
            items = self._items(session_id)

        has_destructive = False
        for it in items:
            try:
                env = self._envelope(it["bank_question_id"])
                if env.destructive:
                    has_destructive = True
                if it.get("mounted_at") or it["state"] == "active":
                    await self.engine.cleanup(env)
            except Exception:
                pass

        if reset == "baseline" or has_destructive:
            cleanup = await self.teardown.reset_clean()
        else:
            cleanup = await self.teardown.cleanup_session()

        passed = [item for item in items if item["state"] == "passed"]
        skipped = [item for item in items if item["state"] == "skipped"]
        per_domain: dict[str, dict] = {}
        item_breakdown: list[dict] = []
        total_weight = 0
        earned_weight = 0.0

        for item in items:
            w = int(item["weight_pct"] or 0)
            total_weight += w
            ew = float(item.get("earned_weight") or 0.0)
            if item["state"] == "passed" and ew <= 0:
                ew = float(w)
            earned_weight += ew
            bucket = per_domain.setdefault(
                item["domain"], {"total": 0, "passed": 0, "weight": 0, "earned_weight": 0.0}
            )
            bucket["total"] += 1
            bucket["weight"] += w
            bucket["earned_weight"] = round(bucket["earned_weight"] + ew, 2)
            if item["state"] == "passed":
                bucket["passed"] += 1
            item_breakdown.append({
                "item_id": item["id"],
                "title": item["title"],
                "domain": item["domain"],
                "weight": w,
                "earned_weight": round(ew, 2),
                "pass_ratio": float(item.get("check_pass_ratio") or (1.0 if item["state"] == "passed" else 0.0)),
                "state": item["state"],
                "flagged": bool(item.get("flagged")),
            })

        earned_rounded = round(earned_weight, 1)
        score_pct = round(100 * earned_weight / max(1, total_weight))
        with db.connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = 'finished', finished_at = ?, total_weight = ?, earned_weight = ?"
                " WHERE id = ?",
                (now, total_weight, int(round(earned_weight)), session_id),
            )

        first_try = sum(1 for item in passed if (item["attempts"] or 0) <= 1)
        return {
            "session_id": session_id,
            "mode": session["mode"],
            "variant": variant,
            "summary": {
                "total": len(items),
                "passed": len(passed),
                "skipped": len(skipped),
                "first_try_passes": first_try,
                "accuracy_pct": round(100 * len(passed) / max(1, len(items))),
                "total_weight": total_weight,
                "earned_weight": earned_rounded,
                "score_pct": score_pct,
                "passed_exam": score_pct >= 66,
                "duration_minutes": round((now - session["started_at"]) / 60, 1),
                "per_domain": per_domain,
                "items": item_breakdown,
            },
            "cleanup": cleanup,
        }
