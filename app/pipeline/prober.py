"""Cluster Solvability Prober — ephemeral namespace parallelism, pre-cleanup digest, leak gate."""

from __future__ import annotations

import asyncio
import re
import shlex
import time
import uuid
from typing import Callable

from app import cluster, commands, provider
from app.models import ScenarioEnvelope
from app.pipeline.gates import RUNTIME_CHECK_TYPES, _references_missing_local_file
from app.scenario_engine import (
    SCENARIO_LABEL,
    ScenarioEngine,
    clone_with_ephemeral_namespaces,
    is_cluster_scoped,
)


class ScenarioProber:
    def __init__(self, engine: ScenarioEngine) -> None:
        self.engine = engine
        self._probe_lock = asyncio.Lock()
        self._ns_probe_sem = asyncio.Semaphore(2)
        self.last_probe_report: dict | None = None
        self.last_probe_digest: dict | None = None

    async def probe(
        self,
        env: ScenarioEnvelope,
        *,
        emit: Callable[[str], None] | None = None,
    ) -> tuple[bool, str, str]:
        """Run isolated solvability probe (concurrent for pure namespace-scoped scenarios)."""
        if not is_cluster_scoped(env) and env.setup.namespaces:
            probe_env = clone_with_ephemeral_namespaces(env, uuid.uuid4().hex[:5])
            async with self._ns_probe_sem:
                return await self.probe_locked(probe_env, emit=emit)
        async with self._probe_lock:
            return await self.probe_locked(env, emit=emit)

    async def probe_retry(
        self,
        env: ScenarioEnvelope,
        *,
        emit: Callable[[str], None] | None = None,
    ) -> tuple[bool, str, str]:
        ok, detail, kind = await self.probe(env, emit=emit)
        for infra_try in range(1, 4):
            if ok or kind != "infra":
                return ok, detail, kind
            if emit:
                emit(
                    f"probe infra error → retry {infra_try}/3 (cluster hiccup, not counted as a model error)"
                )
            await asyncio.sleep(3 * infra_try)
            ok, detail, kind = await self.probe(env, emit=emit)
        return ok, detail, kind

    async def capture_digest(self, env: ScenarioEnvelope) -> None:
        if hasattr(self.engine, "namespace_digest") and env.setup.namespaces:
            try:
                self.last_probe_digest = await self.engine.namespace_digest(env.setup.namespaces)
            except Exception:
                self.last_probe_digest = {}

    async def _wait_nodes_ready_after_solution(self, env: ScenarioEnvelope) -> None:
        target_nodes = {
            nc.node
            for nc in env.solution.node_commands
            if any(tok in nc.command for tok in ("kubelet", "containerd", "kubeadm", "systemctl start"))
        }
        if not target_nodes:
            return
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            nodes = {n["name"]: n["ready"] for n in await cluster.get_nodes()}
            if nodes and all(nodes.get(name) for name in target_nodes):
                return
            await asyncio.sleep(2.0)

    async def _check_post_cleanup_leaks(self, env: ScenarioEnvelope) -> str:
        """Detect cluster-scoped managed resources orphaned after scenario cleanup."""
        try:
            res = await cluster.kubectl(
                [
                    "get",
                    "pv,clusterrole,clusterrolebinding",
                    "-l",
                    f"{SCENARIO_LABEL}={env.id}",
                    "-o",
                    "name",
                ],
                timeout=12,
            )
        except Exception:
            return ""
        if not res.ok:
            return ""
        leftovers = [line.strip() for line in (res.out or "").splitlines() if line.strip()]
        if leftovers:
            return f"post-cleanup leaked cluster-scoped resources for {env.id}: {', '.join(leftovers[:6])}"
        return ""

    async def probe_locked(
        self,
        env: ScenarioEnvelope,
        *,
        emit: Callable[[str], None] | None = None,
    ) -> tuple[bool, str, str]:
        """Execute setup -> sanity-fail -> solution -> pass -> cleanup -> leak-check."""
        started = time.monotonic()

        def notify(msg: str) -> None:
            if emit:
                emit(msg)

        async def poll_sleep(index: int) -> None:
            await asyncio.sleep(1.5 if index < 4 else 3.5)

        async def run_checks_fast() -> dict:
            return await self.engine.run_checks(env, settle=False)

        self.last_probe_report = None
        self.last_probe_digest = None
        needs_double_confirm = any(c.type in RUNTIME_CHECK_TYPES for c in env.checks)

        try:
            notify("applying setup on the cluster")
            await self.engine.apply_setup(env)
            await self.engine.settle(env.setup.namespaces, timeout_s=45)
            notify("sanity: running checks — they must FAIL at setup")
            sanity = await self.engine.run_checks(env, settle=False)
            deadline = time.monotonic() + 35
            poll = 0
            while time.monotonic() < deadline:
                if sanity["infra_error"]:
                    await asyncio.sleep(2.5)
                    sanity = await run_checks_fast()
                    continue
                if not sanity["all_passed"]:
                    break
                await poll_sleep(poll)
                poll += 1
                notify(f"sanity: still passing — waiting for the fault to manifest ({int(time.monotonic() - started)}s)")
                sanity = await run_checks_fast()

            if sanity["infra_error"]:
                self.last_probe_report = sanity
                return (
                    False,
                    "erro de infraestrutura durante o sanity check:\n" + self.failure_detail(sanity),
                    "infra",
                )
            if sanity["all_passed"]:
                await self.capture_digest(env)
                return False, "sanity fail: all checks ALREADY PASSED right after setup", "content"

            notify("applying reference solution on the cluster")
            apply_err = await self.apply_solution(env)
            if apply_err:
                await self.capture_digest(env)
                return False, f"solution apply failed: {apply_err}", "content"

            await self._wait_nodes_ready_after_solution(env)
            await self.engine.settle(env.setup.namespaces, timeout_s=15)
            notify("verifying solution against all checks")
            final = await self.engine.run_checks(env, settle=False)
            deadline = time.monotonic() + 90
            poll = 0
            consecutive_full = 0
            required_full = 2 if needs_double_confirm else 1
            rounds: list[set[str]] = []
            while time.monotonic() < deadline:
                if final["infra_error"]:
                    await asyncio.sleep(2.5)
                    poll += 1
                    notify(f"verifying solution: check ERROR — retrying ({int(time.monotonic() - started)}s)")
                    final = await run_checks_fast()
                    continue
                check_ids = [r["check_id"] for r in final["results"]]
                passing = {r["check_id"] for r in final["results"] if r["status"] == "PASS"}
                rounds.append(passing)
                if check_ids and passing == set(check_ids):
                    consecutive_full += 1
                    if consecutive_full >= required_full:
                        final = {**final, "all_passed": True}
                        break
                else:
                    consecutive_full = 0
                    if len(rounds) >= 3:
                        last3 = rounds[-3:]
                        if check_ids and all(sum(cid in r for r in last3) >= 2 for cid in check_ids):
                            final = {**final, "all_passed": True}
                            break
                if final["all_passed"]:
                    await asyncio.sleep(1.5)
                else:
                    await poll_sleep(poll)
                poll += 1
                passed = sum(1 for r in final["results"] if r["status"] == "PASS")
                notify(f"verifying solution: {passed}/{len(final['results'])} checks passing ({int(time.monotonic() - started)}s)")
                final = await run_checks_fast()

            if final["infra_error"]:
                self.last_probe_report = final
                return (
                    False,
                    "erro de infraestrutura ao validar a solução:\n" + self.failure_detail(final),
                    "infra",
                )
            if not final["all_passed"]:
                self.last_probe_report = final
                await self.capture_digest(env)
                return False, "solução não resolve os checks:\n" + self.failure_detail(final), "content"

            notify("solvability probe passed")
            ok_result = (True, "sanity + solvability ok", "ok")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            infra_hints = (
                "apply do setup falhou",
                "setup apply failed",
                "ssh",
                "timeout",
                "connect",
                "unavailable",
                "connection",
                "dial tcp",
            )
            kind = "infra" if any(h in str(exc).lower() for h in infra_hints) else "content"
            if kind == "content":
                await self.capture_digest(env)
            return False, f"probe error: {type(exc).__name__}: {str(exc)[:300]}", kind
        finally:
            try:
                await asyncio.shield(self.engine.cleanup(env))
            except Exception:
                pass

        leak_err = await self._check_post_cleanup_leaks(env)
        if leak_err:
            return False, leak_err, "content"
        return ok_result

    def failure_detail(self, report: dict) -> str:
        lines: list[str] = []
        for result in report.get("results", []):
            if result.get("status") == "PASS":
                continue
            evidence = result.get("evidence") or {}
            bits = [f"{result['check_id']} ({result.get('description', '')[:60]})"]
            if evidence.get("expected") is not None or evidence.get("actual") is not None:
                bits.append(f"expected={evidence.get('expected')!r} got={evidence.get('actual')!r}")
            if evidence.get("exit_code") is not None:
                first = str(evidence.get("stdout") or evidence.get("stderr") or "").split("\n")[0]
                bits.append(f"exit={evidence['exit_code']} out={first[:100]}")
            if evidence.get("reason"):
                bits.append(str(evidence["reason"])[:120])
            if evidence.get("error"):
                bits.append(str(evidence["error"])[:120])
            lines.append(" - " + " · ".join(bits))
        return "\n".join(lines[:8]) or "all checks failed without evidence"

    async def apply_solution(self, env: ScenarioEnvelope) -> str:
        for node_cmd in env.solution.node_commands:
            if "etcdctl" not in node_cmd.command:
                res = await provider.get().exec(
                    node_cmd.node, node_cmd.command, sudo=node_cmd.sudo, timeout=60
                )
                if not res.ok:
                    return (
                        f"node_command solução falhou em {node_cmd.node}: "
                        f"{(res.err or res.out).strip()[:200]}"
                    )
        for raw in env.solution.commands:
            if _references_missing_local_file(shlex.split(raw)):
                return (
                    f"comando referencia arquivo local inexistente: {raw[:100]} — "
                    "envie o YAML em solution.manifests"
                )
            lowered = raw.lower()
            is_convergence_wait = "rollout status" in lowered or bool(re.search(r"\bwait\b", lowered))
            try:
                res = await commands.run_tool_command(raw, timeout=60)
            except commands.CommandRejected as exc:
                return str(exc)
            if not res.ok and not is_convergence_wait:
                return f"{raw[:80]}: {(res.err or res.out).strip()[:200]}"
        if env.solution.manifests:
            payload = "\n---\n".join(env.solution.manifests)
            res = await cluster.kubectl(["apply", "-f", "-"], timeout=90, stdin_data=payload)
            if not res.ok:
                return (res.err or res.out).strip()[:300]
        for node_cmd in env.solution.node_commands:
            if "etcdctl" in node_cmd.command:
                res = await provider.get().exec(
                    node_cmd.node, node_cmd.command, sudo=node_cmd.sudo, timeout=60
                )
                if not res.ok:
                    return (
                        f"node_command solução falhou em {node_cmd.node}: "
                        f"{(res.err or res.out).strip()[:200]}"
                    )
        return ""
