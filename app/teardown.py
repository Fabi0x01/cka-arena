"""Teardown L0/L1/L2 — provider-agnostic question, session, and clean reset."""

from __future__ import annotations

import json

from app import cluster, config, provider
from app.doctor import ClusterDoctor
from app.models import ScenarioEnvelope
from app.scenario_engine import MANAGED_LABEL, ScenarioEngine

PROBE_LABEL = "cka-arena.io/probe=true"
CLUSTER_SCOPED_KINDS = (
    "clusterrole",
    "clusterrolebinding",
    "pv",
    "sc",
    "crd",
    "priorityclass",
    "csr",
)
_SYSTEM_LABEL_PREFIXES = (
    "kubernetes.io/",
    "node-role.kubernetes.io/",
    "beta.kubernetes.io/",
    "node.kubernetes.io/",
    "topology.kubernetes.io/",
)


class Teardown:
    def __init__(self, engine: ScenarioEngine, doctor: ClusterDoctor) -> None:
        self.engine = engine
        self.doctor = doctor

    # ------------------------------------------------------------ L0

    async def cleanup_question(self, env: ScenarioEnvelope) -> dict:
        return await self.engine.cleanup(env)

    # ------------------------------------------------------------ L1

    async def cleanup_session(self) -> dict:
        """Global managed-label sweep + pending node backup restoration + drift check."""
        deleted: list[str] = []
        res = await cluster.kubectl(
            ["get", "ns", "-l", f"{MANAGED_LABEL}=true", "-o", "name"], timeout=15
        )
        for line in (res.out or "").splitlines():
            namespace = line.strip().split("/")[-1]
            if namespace:
                await cluster.kubectl(
                    ["delete", "namespace", namespace, "--ignore-not-found", "--wait=false"],
                    timeout=30,
                )
                deleted.append(namespace)

        await cluster.kubectl(
            ["delete", "pods", "-A", "-l", PROBE_LABEL, "--ignore-not-found", "--wait=false"],
            timeout=30,
        )
        for kind in CLUSTER_SCOPED_KINDS:
            await cluster.kubectl(
                ["delete", kind, "-l", f"{MANAGED_LABEL}=true", "--ignore-not-found", "--wait=false"],
                timeout=30,
            )

        restored: dict[str, dict] = {}
        node_provider = provider.get()
        try:
            nodes = await node_provider.nodes()
        except Exception:
            nodes = {}
        for name in config.VM_NAMES:
            info = nodes.get(name)
            if not info or info.state != "Running":
                restored[name] = {"ok": False, "detail": "node unreachable"}
                continue
            r = await node_provider.exec(name, self._restore_all_script(), sudo=True, timeout=120)
            restored[name] = {
                "ok": r.ok and "RESTORE_ALL_OK" in r.out,
                "detail": (r.err or "").strip()[:200],
            }

        drift = await self.drift()
        await self._restore_node_taints()
        return {
            "level": "L1",
            "namespaces_deleted": deleted,
            "probes_deleted": True,
            "node_backups_restored": restored,
            "drift": drift,
        }

    # ------------------------------------------------------------ L2 (clean reset)

    async def reset_baseline(self) -> dict:
        return await self.reset_clean()

    async def _restore_node_taints(self) -> None:
        """Remove scenario taints, scenario node labels, and uncordon cordoned nodes vs baseline."""
        await cluster.kubectl(
            ["taint", "nodes", "--all", "cka-arena/practice=critical:NoSchedule-"],
            timeout=20,
        )
        baseline: dict = {}
        try:
            if config.BASELINE_NODES_PATH.exists():
                baseline = json.loads(config.BASELINE_NODES_PATH.read_text())
        except (OSError, ValueError):
            baseline = {}

        res = await cluster.kubectl(["get", "nodes", "-o", "json"], timeout=15)
        if not res.ok:
            return
        try:
            items = json.loads(res.out).get("items") or []
        except ValueError:
            return

        for item in items:
            meta = item.get("metadata") or {}
            node_name = meta.get("name")
            if not node_name:
                continue
            spec = item.get("spec") or {}
            base_entry = baseline.get(node_name) or {}
            base_taints = {
                (t.get("key"), t.get("effect"))
                for t in (base_entry.get("taints") or [])
            }
            for taint in (spec.get("taints") or []):
                key = taint.get("key")
                effect = taint.get("effect")
                if not key:
                    continue
                if key.startswith("cka-arena") or (baseline and (key, effect) not in base_taints):
                    spec_str = f"{key}:{effect}-" if effect else f"{key}-"
                    await cluster.kubectl(["taint", "node", node_name, spec_str], timeout=15)

            if spec.get("unschedulable") and not base_entry.get("unschedulable"):
                await cluster.kubectl(["uncordon", node_name], timeout=15)

            base_labels = base_entry.get("labels") or {}
            for lkey in (meta.get("labels") or {}):
                is_arena = lkey.startswith("cka-arena")
                is_extra_non_sys = (
                    bool(base_labels)
                    and lkey not in base_labels
                    and not lkey.startswith(_SYSTEM_LABEL_PREFIXES)
                )
                if is_arena or is_extra_non_sys:
                    await cluster.kubectl(["label", "node", node_name, f"{lkey}-"], timeout=15)

    async def reset_clean(self) -> dict:
        """Clean reset: L1 + restore baseline node files + restart containerd/kubelet + taints."""
        l1 = await self.cleanup_session()
        node_provider = provider.get()
        try:
            nodes = await node_provider.nodes()
        except Exception:
            nodes = {}
        node_results: dict[str, dict] = {}
        for name in config.VM_NAMES:
            info = nodes.get(name)
            if not info or info.state != "Running":
                node_results[name] = {"ok": False, "detail": "node unreachable"}
                continue
            res = await node_provider.exec(
                name, self._baseline_restore_script(), sudo=True, timeout=240
            )
            node_results[name] = {
                "ok": res.ok and "RESET_OK" in res.out,
                "detail": (res.err or "").strip()[:200],
            }
        await self._restore_node_taints()
        ready = await cluster.wait_readyz(timeout_s=180)
        nodes_ready = await cluster.wait_nodes_ready(timeout_s=300)
        drift = await self.drift()
        return {
            "level": "L2-clean",
            "l1": l1,
            "node_reset": node_results,
            "api_ready": ready,
            "nodes_ready": nodes_ready,
            "drift": drift,
        }

    def _baseline_restore_script(self) -> str:
        return (
            "set -e\n"
            f"BK={config.BACKUP_ROOT}/baseline\n"
            "if [ -d \"$BK/manifests\" ]; then\n"
            "  rm -rf /etc/kubernetes/manifests.bak && mkdir -p /etc/kubernetes/manifests.bak\n"
            "  if [ -d /etc/kubernetes/manifests ]; then cp -a /etc/kubernetes/manifests/. /etc/kubernetes/manifests.bak/ || true; fi\n"
            "  rm -rf /etc/kubernetes/manifests/*\n"
            "  cp -a \"$BK/manifests\"/. /etc/kubernetes/manifests/\n"
            "fi\n"
            "[ -f \"$BK/kubelet-config.yaml\" ] && cp -a \"$BK/kubelet-config.yaml\" /var/lib/kubelet/config.yaml\n"
            "[ -f \"$BK/containerd-config.toml\" ] && cp -a \"$BK/containerd-config.toml\" /etc/containerd/config.toml\n"
            "[ -d \"$BK/kubelet.service.d\" ] && cp -a \"$BK/kubelet.service.d\"/. /etc/systemd/system/kubelet.service.d/\n"
            "systemctl daemon-reload\n"
            "systemctl restart containerd\n"
            "systemctl restart kubelet\n"
            "echo RESET_OK"
        )

    # ------------------------------------------------------------ drift

    async def drift(self) -> dict:
        node_provider = provider.get()
        try:
            nodes = await node_provider.nodes()
        except Exception:
            nodes = {}
        per_node: dict[str, dict] = {}
        any_drift = False
        for name in config.VM_NAMES:
            info = nodes.get(name)
            if not info or info.state != "Running":
                per_node[name] = {"diff": "", "leftovers": [], "reachable": False}
                any_drift = True
                continue
            res = await node_provider.exec(name, self._drift_script(), sudo=True, timeout=60)
            diff_text = ""
            leftovers: list[str] = []
            section = ""
            for line in (res.out or "").splitlines():
                if line.startswith("--- diff"):
                    section = "diff"
                    continue
                if line.startswith("--- leftover"):
                    section = "leftover"
                    continue
                if section == "diff" and line.strip():
                    diff_text += line + "\n"
                elif section == "leftover" and line.strip():
                    leftovers.append(line.strip())
            node_drift = bool(diff_text.strip()) or bool(leftovers)
            any_drift = any_drift or node_drift
            per_node[name] = {"diff": diff_text.strip(), "leftovers": leftovers, "reachable": True}
        return {"drift": any_drift, "nodes": per_node}

    # ------------------------------------------------------------ scripts

    def _restore_all_script(self) -> str:
        return (
            "set -e\n"
            f"BK={config.BACKUP_ROOT}\n"
            'if [ -d "$BK" ]; then\n'
            '  for d in "$BK"/*; do\n'
            '    [ -d "$d" ] || continue\n'
            '    [ "$(basename "$d")" = "baseline" ] && continue\n'
            '    cp -a "$d"/. / && rm -rf "$d"\n'
            "  done\n"
            "fi\n"
            "echo RESTORE_ALL_OK"
        )

    def _drift_script(self) -> str:
        return (
            "set -e\n"
            f"BK={config.BACKUP_ROOT}\n"
            'echo "--- diff"\n'
            f'diff -rq /etc/kubernetes/manifests "$BK/baseline/manifests" 2>&1 || true\n'
            'echo "--- leftover"\n'
            f'ls -1 "$BK" 2>/dev/null | grep -v "^baseline$" || true'
        )
