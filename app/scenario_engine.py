"""ScenarioEngine — apply_setup, smart settle, run_checks, rich digest & cleanup."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import time

import yaml

from app import cluster, commands, config, provider
from app.models import NodeCommand, ScenarioEnvelope
from app.validator import run_all

MANAGED_LABEL = "cka-arena.io/managed"
SCENARIO_LABEL = "cka-arena.io/scenario"

TERMINAL_WAIT_REASONS = frozenset({
    "ImagePullBackOff",
    "ErrImagePull",
    "CrashLoopBackOff",
    "CreateContainerConfigError",
    "InvalidImageName",
    "RunContainerError",
})
TERMINAL_TERM_REASONS = frozenset({"OOMKilled", "Error", "Completed"})
CLUSTER_SCOPED_MANIFEST_KINDS = frozenset({
    "PersistentVolume",
    "ClusterRole",
    "ClusterRoleBinding",
    "StorageClass",
    "GatewayClass",
    "PriorityClass",
    "CustomResourceDefinition",
    "Namespace",
})


def is_cluster_scoped(env: ScenarioEnvelope) -> bool:
    """True if running probes concurrently could collide on global cluster/node state."""
    if env.destructive:
        return True
    if env.setup.node_commands or env.solution.node_commands or env.cleanup.node_commands:
        return True
    for cmd in list(env.setup.commands) + list(env.solution.commands) + list(env.cleanup.commands):
        lowered = cmd.lower()
        if any(tok in lowered for tok in (" taint ", " label node", " drain ", " cordon ", " uncordon ", "helm ")):
            return True
    for c in env.checks:
        if c.type in ("node_status_ready", "node_command_exit_zero", "host_file_contains", "helm_release_state"):
            return True
    for text in list(env.setup.manifests) + list(env.solution.manifests):
        try:
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict) and doc.get("kind") in CLUSTER_SCOPED_MANIFEST_KINDS:
                    return True
        except yaml.YAMLError:
            return True
    return False


def _replace_ns_text(text: str, ns_map: dict[str, str]) -> str:
    for old in sorted(ns_map, key=len, reverse=True):
        new = ns_map[old]
        text = re.sub(rf"(?<![A-Za-z0-9-]){re.escape(old)}(?![A-Za-z0-9-])", new, text)
    return text


def _replace_ns_obj(obj, ns_map: dict[str, str]):
    if isinstance(obj, str):
        return _replace_ns_text(obj, ns_map)
    if isinstance(obj, list):
        return [_replace_ns_obj(item, ns_map) for item in obj]
    if isinstance(obj, dict):
        return {k: _replace_ns_obj(v, ns_map) for k, v in obj.items()}
    return obj


def clone_with_ephemeral_namespaces(env: ScenarioEnvelope, tag: str) -> ScenarioEnvelope:
    """Return an isolated copy with probe-scoped namespace names (leaves original intact)."""
    if not env.setup.namespaces:
        return env
    ns_map = {
        ns: f"cka-p-{tag}-{ns[:16]}".rstrip("-")[:63]
        for ns in env.setup.namespaces
    }
    data = env.model_dump()
    for section in ("setup", "checks", "solution", "cleanup"):
        data[section] = _replace_ns_obj(data[section], ns_map)
    return ScenarioEnvelope.model_validate(data)


def _pod_is_transitioning(pod: dict, now: float) -> bool:
    phase = pod.get("phase")
    if phase in ("Failed", "Succeeded"):
        return False
    if phase == "Running" and pod.get("ready"):
        return False
    if pod.get("unschedulable"):
        return False
    if any(r in TERMINAL_WAIT_REASONS for r in pod.get("waiting_reasons") or ()):
        return False
    if any(r in TERMINAL_TERM_REASONS for r in pod.get("terminated_reasons") or ()):
        return False
    # Running but not Ready with no waiting fault yet (e.g. readinessProbe still failing)
    if phase == "Running":
        created = pod.get("created_ts")
        if created is not None and (now - created) > 8.0:
            return False
        return True
    return phase in ("Pending", "Unknown", None)


class ScenarioEngine:
    def __init__(self, backup_root: str | None = None) -> None:
        self.backup_root = backup_root or config.BACKUP_ROOT

    # ------------------------------------------------------------ setup

    def label_args(self, env: ScenarioEnvelope) -> list[str]:
        return [f"{MANAGED_LABEL}=true", f"{SCENARIO_LABEL}={env.id}"]

    def _translate_node_refs(self, obj):
        if isinstance(obj, list):
            return [self._translate_node_refs(item) for item in obj]
        if not isinstance(obj, dict):
            return obj
        out = {}
        for k, v in obj.items():
            if k == "nodeName" and isinstance(v, str) and v in config.VM_NAMES:
                out[k] = provider.resolve_node_name(v)
            elif k == "nodeSelector" and isinstance(v, dict):
                sel = dict(v)
                host = sel.get("kubernetes.io/hostname")
                if isinstance(host, str) and host in config.VM_NAMES:
                    sel["kubernetes.io/hostname"] = provider.resolve_node_name(host)
                out[k] = sel
            else:
                out[k] = self._translate_node_refs(v)
        return out

    def _labeled_manifests(self, env: ScenarioEnvelope) -> list[dict]:
        docs: list[dict] = []
        translate_nodes = provider.provider_name() == "kind"
        for text in env.setup.manifests:
            for doc in yaml.safe_load_all(text):
                if not isinstance(doc, dict):
                    continue
                if translate_nodes:
                    doc = self._translate_node_refs(doc)
                meta = doc.setdefault("metadata", {})
                labels = meta.setdefault("labels", {})
                labels[MANAGED_LABEL] = "true"
                labels[SCENARIO_LABEL] = env.id
                docs.append(doc)
        return docs

    def render_manifests_payload(self, manifests: list[str]) -> str:
        """Render YAML manifests into a multi-doc payload with kind node-name translation."""
        if provider.provider_name() != "kind":
            return "\n---\n".join(manifests)
        rendered: list[str] = []
        for text in manifests:
            try:
                docs = [
                    self._translate_node_refs(doc)
                    for doc in yaml.safe_load_all(text)
                    if doc is not None
                ]
            except yaml.YAMLError:
                rendered.append(text)
                continue
            rendered.extend(yaml.safe_dump(doc, sort_keys=False) for doc in docs)
        return "\n---\n".join(rendered)

    async def _force_finalize_namespace(self, name: str) -> bool:
        """Remove stuck kubernetes finalizer on Terminating namespaces."""
        got = await cluster.kubectl(["get", "namespace", name, "-o", "json"], timeout=10)
        if not got.ok:
            return False
        try:
            data = json.loads(got.out)
        except ValueError:
            return False
        data.setdefault("spec", {})["finalizers"] = []
        res = await cluster.kubectl(
            ["replace", "--raw", f"/api/v1/namespaces/{name}/finalize", "-f", "-"],
            timeout=20, stdin_data=json.dumps(data),
        )
        return res.ok

    async def _ensure_namespace(self, name: str, labels: list[str]) -> None:
        """Create namespace, waiting out or force-finalizing any prior Terminating one."""
        for _ in range(12):  # ~24s max
            res = await cluster.kubectl(
                ["get", "namespace", name, "-o", "jsonpath={.status.phase}"], timeout=10
            )
            if not res.ok:
                break
            if (res.out or "").strip() != "Terminating":
                break
            await asyncio.sleep(2)
        phase = await cluster.kubectl(
            ["get", "namespace", name, "-o", "jsonpath={.status.phase}"], timeout=10
        )
        if phase.ok and (phase.out or "").strip() == "Terminating":
            await self._force_finalize_namespace(name)
            for _ in range(10):
                await asyncio.sleep(1)
                check = await cluster.kubectl(
                    ["get", "namespace", name, "-o", "jsonpath={.status.phase}"], timeout=10
                )
                if not check.ok or (check.out or "").strip() != "Terminating":
                    break
        await cluster.kubectl(["create", "namespace", name], timeout=15)  # AlreadyExists ok
        res = await cluster.kubectl(["label", "namespace", name, *labels, "--overwrite"], timeout=10)
        if not res.ok:
            raise RuntimeError(f"failed to label namespace {name}: {res.err[:200]}")

    async def apply_setup(self, env: ScenarioEnvelope) -> dict:
        started = time.monotonic()
        try:
            for namespace in env.setup.namespaces:
                await self._ensure_namespace(namespace, self.label_args(env))

            # Preparation commands (e.g. taints/helm) run BEFORE manifests
            for raw in env.setup.commands:
                res = await commands.run_tool_command(raw, timeout=180)
                if not res.ok:
                    raise RuntimeError(f"setup command failed ({raw[:70]}): {(res.err or res.out).strip()[:250]}")

            docs = self._labeled_manifests(env)
            if docs:
                payload = "\n---\n".join(yaml.safe_dump(doc, sort_keys=False) for doc in docs)
                res = await cluster.kubectl(["apply", "-f", "-"], timeout=90, stdin_data=payload)
                if not res.ok:
                    raise RuntimeError(f"setup apply failed: {(res.err or res.out).strip()[:300]}")

            for node_cmd in env.setup.node_commands:
                await self._run_node_command(env, node_cmd, with_backup=True)

            return {
                "ok": True,
                "namespaces": env.setup.namespaces,
                "manifests_applied": len(docs),
                "node_commands": len(env.setup.node_commands),
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await asyncio.shield(self.cleanup(env))
            except Exception:
                pass
            raise

    # ------------------------------------------------------------ checks

    async def settle(self, namespaces: list[str], timeout_s: float = 60) -> bool:
        """Smart settle: return as soon as no pod is actively Transitioning."""
        if not namespaces:
            return True
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            now = time.time()
            transitioning = False
            for namespace in namespaces:
                for pod in await cluster.pods_detailed(namespace):
                    if _pod_is_transitioning(pod, now):
                        transitioning = True
                        break
                if transitioning:
                    break
            if not transitioning:
                return True
            await asyncio.sleep(1.5)
        return False

    async def run_checks(
        self,
        env: ScenarioEnvelope,
        *,
        settle: bool = True,
        settle_timeout: float | None = None,
    ) -> dict:
        if settle:
            await self.settle(env.setup.namespaces, timeout_s=settle_timeout if settle_timeout is not None else 60)
        has_netpol = any(
            "NetworkPolicy" in m
            for m in list(env.setup.manifests) + list(env.solution.manifests)
        ) or any(c.type == "pod_exec_must_fail" for c in env.checks)
        return await run_all(env.checks, allow_warm_probe=not has_netpol)

    # ------------------------------------------------------------ digest & cleanup

    async def namespace_digest(self, namespaces: list[str]) -> dict:
        """Live namespace state (pods, events, services, PVCs, failing pod logs) for repair."""
        digest: dict[str, dict] = {}
        for namespace in namespaces[:3]:
            entry: dict[str, list] = {"pods": [], "services": [], "events": [], "pvcs": [], "pod_logs": []}
            pods = await cluster.kubectl(["get", "pods", "-n", namespace, "-o", "json"], timeout=15)
            failing_pods: list[str] = []
            if pods.ok:
                try:
                    for item in json.loads(pods.out).get("items", [])[:8]:
                        pod_name = (item.get("metadata") or {}).get("name")
                        status = item.get("status") or {}
                        statuses = status.get("containerStatuses") or []
                        waiting = [
                            (cs.get("state") or {}).get("waiting", {}).get("reason")
                            for cs in statuses
                            if (cs.get("state") or {}).get("waiting")
                        ]
                        unsched = next(
                            (
                                c.get("message")
                                for c in (status.get("conditions") or [])
                                if c.get("type") == "PodScheduled" and c.get("status") == "False"
                            ),
                            None,
                        )
                        is_ready = bool(statuses) and all(cs.get("ready") for cs in statuses)
                        reason = waiting[0] if waiting else (unsched[:120] if unsched else status.get("reason"))
                        entry["pods"].append({
                            "name": pod_name,
                            "phase": status.get("phase"),
                            "ready": is_ready,
                            "reason": reason,
                        })
                        if not is_ready and pod_name:
                            failing_pods.append(str(pod_name))
                except ValueError:
                    pass

            for pod_name in failing_pods[:2]:
                logs = await cluster.kubectl(["logs", pod_name, "-n", namespace, "--tail=12"], timeout=8)
                if logs.ok and logs.out.strip():
                    entry["pod_logs"].append({"pod": pod_name, "tail": logs.out.strip()[-400:]})

            services = await cluster.kubectl(["get", "svc", "-n", namespace, "-o", "json"], timeout=15)
            endpoints = await cluster.kubectl(["get", "endpoints", "-n", namespace, "-o", "json"], timeout=15)
            endpoint_counts: dict[str, int] = {}
            if endpoints.ok:
                try:
                    for ep in json.loads(endpoints.out).get("items", []):
                        name = (ep.get("metadata") or {}).get("name", "")
                        subsets = ep.get("subsets") or []
                        endpoint_counts[name] = sum(len(s.get("addresses") or []) for s in subsets)
                except ValueError:
                    pass
            if services.ok:
                try:
                    for svc in json.loads(services.out).get("items", [])[:6]:
                        name = (svc.get("metadata") or {}).get("name", "")
                        entry["services"].append({
                            "name": name,
                            "type": (svc.get("spec") or {}).get("type"),
                            "selector": (svc.get("spec") or {}).get("selector"),
                            "ports": (svc.get("spec") or {}).get("ports"),
                            "ready_endpoints": endpoint_counts.get(name, 0),
                        })
                except ValueError:
                    pass

            events = await cluster.kubectl(
                ["get", "events", "-n", namespace, "--field-selector", "type=Warning", "-o", "json"],
                timeout=10,
            )
            if events.ok:
                try:
                    ev_items = json.loads(events.out).get("items") or []
                    for ev in ev_items[-8:]:
                        entry["events"].append({
                            "reason": ev.get("reason"),
                            "object": (ev.get("involvedObject") or {}).get("name"),
                            "message": (ev.get("message") or "")[:180],
                        })
                except ValueError:
                    pass

            pvcs = await cluster.kubectl(["get", "pvc", "-n", namespace, "-o", "json"], timeout=10)
            if pvcs.ok:
                try:
                    for pvc in json.loads(pvcs.out).get("items") or []:
                        entry["pvcs"].append({
                            "name": (pvc.get("metadata") or {}).get("name"),
                            "phase": (pvc.get("status") or {}).get("phase"),
                            "storageClassName": (pvc.get("spec") or {}).get("storageClassName"),
                            "volumeName": (pvc.get("spec") or {}).get("volumeName"),
                        })
                except ValueError:
                    pass

            digest[namespace] = entry
        return digest

    async def cleanup(self, env: ScenarioEnvelope) -> dict:
        deleted: list[str] = []
        for namespace in (env.cleanup.namespaces or env.setup.namespaces):
            res = await cluster.kubectl(
                ["delete", "namespace", namespace, "--ignore-not-found", "--wait=false"], timeout=30
            )
            deleted.append(namespace if res.ok else f"{namespace}:failed")

        command_results: list[dict] = []
        for raw in list(env.cleanup.commands) + list(env.cleanup.kubectl_commands):
            try:
                res = await commands.run_tool_command(raw, timeout=120)
            except commands.CommandRejected as exc:
                command_results.append({"command": raw, "ok": False, "stderr": str(exc)})
                continue
            command_results.append({"command": raw, "ok": res.ok, "stderr": res.err[-200:]})

        node_results: dict[str, dict] = {}
        for node_cmd in env.cleanup.node_commands:
            res = await provider.get().exec(
                node_cmd.node, node_cmd.command, sudo=node_cmd.sudo, timeout=90
            )
            node_results[node_cmd.node] = {"ok": res.ok, "detail": res.err[-200:]}

        restored: dict[str, bool] = {}
        backup_nodes = {nc.node for nc in env.setup.node_commands if nc.backup_paths}
        for node in backup_nodes:
            res = await provider.get().exec(
                node, self._restore_script(env.id), sudo=True, timeout=90
            )
            restored[node] = res.ok and "RESTORE_OK" in res.out

        return {
            "namespaces_deleted": deleted,
            "kubectl_commands": command_results,
            "node_commands": node_results,
            "node_backups_restored": restored,
        }

    # ------------------------------------------------------------ node helpers

    def _backup_script(self, scenario_id: str, paths: list[str]) -> str:
        lines = [
            "set -e",
            f"BK={shlex.quote(self.backup_root)}/{shlex.quote(scenario_id)}",
            'mkdir -p "$BK"',
        ]
        for path in paths:
            quoted = shlex.quote(path)
            lines.append(f'mkdir -p "$BK$(dirname {quoted})"')
            lines.append(f'if [ -e {quoted} ]; then cp -a {quoted} "$BK$(dirname {quoted})/"; fi')
        lines.append("echo BACKUP_OK")
        return "\n".join(lines)

    def _restore_script(self, scenario_id: str) -> str:
        return (
            "set -e\n"
            f"BK={shlex.quote(self.backup_root)}/{shlex.quote(scenario_id)}\n"
            'if [ -d "$BK" ]; then cp -a "$BK"/. / && rm -rf "$BK" && echo RESTORE_OK; '
            'else echo NO_BACKUP; fi'
        )

    async def _run_node_command(
        self, env: ScenarioEnvelope, node_cmd: NodeCommand, *, with_backup: bool
    ) -> None:
        node_provider = provider.get()
        if with_backup and node_cmd.backup_paths:
            res = await node_provider.exec(
                node_cmd.node, self._backup_script(env.id, node_cmd.backup_paths),
                sudo=True, timeout=90,
            )
            if not res.ok or "BACKUP_OK" not in res.out:
                raise RuntimeError(
                    f"backup failed on {node_cmd.node}: {(res.err or res.out).strip()[:250]}"
                )
        res = await node_provider.exec(
            node_cmd.node, node_cmd.command, sudo=node_cmd.sudo, timeout=90
        )
        if not res.ok:
            raise RuntimeError(
                f"node_command failed on {node_cmd.node}: {(res.err or res.out).strip()[:250]}"
            )
