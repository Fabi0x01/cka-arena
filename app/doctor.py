"""ClusterDoctor — saúde, addons, baseline de arquivos e snapshot clean-baseline."""

from __future__ import annotations

import json
import shutil
import time

from app import cluster, config, provider


class ClusterDoctor:
    async def resolve_node_ips(self) -> dict[str, str | None]:
        """IPs de SSH (provider multipass). No provider kind não há SSH — None."""
        try:
            nodes = await provider.get().nodes()
        except Exception:
            return {name: None for name in config.VM_NAMES}
        return {name: info.ip for name, info in nodes.items()}

    async def health(self) -> dict:
        nodes = await cluster.get_nodes()
        kubectl_ok = (await cluster.kubectl(["version", "--request-timeout=5s"], timeout=10)).ok
        ssh_ips = await self.resolve_node_ips()
        node_rows: list[dict] = []
        for name in config.VM_NAMES:
            ip = ssh_ips.get(name)
            kb = next((n for n in nodes if n["name"] == name), {})
            row = {
                "name": name,
                "ready": bool(kb.get("ready")),
                "internal_ip": kb.get("internal_ip"),
                "ssh_ip": ip,
                "ssh_ok": False,
                "ssh_ms": None,
            }
            t0 = time.perf_counter()
            probe = await provider.get().exec(name, "true", timeout=6)
            row["ssh_ok"] = probe.ok          # campo mantido: "node exec ok"
            row["transport"] = provider.get().transport
            row["ssh_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            node_rows.append(row)
        addons = await self.addons()
        bootstrap_plan = [
            {"addon": addon["name"], "status": addon["status"], "hint": self.BOOTSTRAP_HINTS[addon["name"]]}
            for addon in addons
            if addon["name"] in self.BOOTSTRAP_HINTS and addon["status"] not in ("present",)
        ]
        return {
            "nodes_ready": sum(1 for row in node_rows if row["ready"]),
            "total_nodes": len(config.VM_NAMES),
            "nodes": node_rows,
            "kubectl_ok": kubectl_ok,
            "kubeconfig": str(config.KUBECONFIG_PATH),
            "addons": addons,
            "bootstrap_plan": bootstrap_plan,
            "baseline_files": await self.baseline_files_present(ssh_ips),
            "checked_at": time.time(),
        }

    BOOTSTRAP_HINTS = {
        "metrics-server": "kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml (arm64 ok)",
        "gateway_api": "kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.0/standard-install.yaml",
        "local_path_storage": "kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml",
        "network_policy_enforcement": "install a NetworkPolicy-capable CNI (the current Weave setup has no weave-npc pods)",
    }

    async def addons(self) -> list[dict]:
        addons: list[dict] = [
            {"name": "helm (Mac)", "status": "present" if shutil.which("helm") else "absent"},
        ]
        etcdctl = "unknown"
        try:
            control = (await provider.get().nodes()).get("controlplane")
        except Exception:
            control = None
        if control and control.state == "Running":
            etcdctl = "present" if (await provider.get().exec(
                "controlplane", "command -v etcdctl", timeout=8
            )).ok else "absent"
        addons.append({"name": "etcdctl (controlplane)", "status": etcdctl})

        pods = await cluster.pods("kube-system")

        def pod_state(prefix: str) -> str:
            matched = [p for p in pods if p["name"].startswith(prefix)]
            if not matched:
                return "absent"
            return "present" if all(p["ready"] for p in matched) else "degraded"

        addons.append({"name": "metrics-server", "status": await self._metrics_state()})
        npc = await self._weave_npc_state()
        addons.append({
            "name": "network_policy_enforcement",
            "status": npc,
            "detail": "weave-npc (container no weave-net)" if npc != "absent"
            else "sem weave-npc — NetworkPolicy não é aplicada",
        })

        gateway_crd = await cluster.crd_exists("gateways.gateway.networking.k8s.io")
        if not gateway_crd:
            addons.append({"name": "gateway_api", "status": "absent"})
        else:
            controller_status, detail = await self._gateway_controller_state()
            addons.append({"name": "gateway_api", "status": controller_status, "detail": detail})
        local_path = await cluster.storage_class_exists("local-path")
        addons.append({"name": "local_path_storage", "status": "present" if local_path else "absent"})
        return addons

    async def _metrics_state(self) -> str:
        res = await cluster.kubectl(
            ["get", "apiservice", "v1beta1.metrics.k8s.io", "-o", "json"], timeout=10
        )
        if not res.ok:
            return "absent"
        try:
            data = json.loads(res.out)
        except ValueError:
            return "degraded"
        for condition in data.get("status", {}).get("conditions", []):
            if condition.get("type") == "Available":
                return "present" if condition.get("status") == "True" else "degraded"
        return "degraded"

    async def _weave_npc_state(self) -> str:
        res = await cluster.kubectl(
            ["get", "pods", "-n", "kube-system", "-o", "json"], timeout=15
        )
        if not res.ok:
            return "unknown"
        try:
            data = json.loads(res.out)
        except ValueError:
            return "unknown"
        for item in data.get("items", []):
            statuses = item.get("status", {}).get("containerStatuses") or []
            npc = [cs for cs in statuses if cs.get("name") == "weave-npc"]
            if npc:
                return "present" if all(cs.get("ready") for cs in npc) else "degraded"
        return "absent"

    async def _gateway_controller_state(self) -> tuple[str, str | None]:
        for namespace in ("envoy-gateway-system", "nginx-gateway", "envoy-gateway"):
            res = await cluster.kubectl(
                ["get", "deployment", "-n", namespace, "-o", "json"], timeout=10
            )
            if not res.ok:
                continue
            try:
                data = json.loads(res.out)
            except ValueError:
                continue
            for item in data.get("items", []):
                name = item.get("metadata", {}).get("name", "")
                ready = (item.get("status") or {}).get("readyReplicas") or 0
                if "gateway" in name and ready >= 1:
                    return "present", f"{namespace}/{name} (ready {ready})"
        return "absent", "controller não encontrado"

    # ------------------------------------------------------------ baseline

    async def baseline_files_present(self, ssh_ips: dict[str, str | None] | None = None) -> bool:
        marker = f"{config.BACKUP_ROOT}/baseline/manifests"
        for name in config.VM_NAMES:
            res = await provider.get().exec(
                name, f"test -d {marker} && echo yes", sudo=True, timeout=8
            )
            if not (res.ok and "yes" in res.out):
                return False
        return True

    async def ensure_baseline_files(self, password: str | None = None) -> dict:
        """Snapshot de arquivos do nó (manifests, kubelet, containerd, systemd) — idempotente."""
        script = f"""
set -e
mkdir -p {config.BACKUP_ROOT}/baseline
test -d {config.BACKUP_ROOT}/baseline/manifests || cp -a /etc/kubernetes/manifests {config.BACKUP_ROOT}/baseline/manifests
test -f {config.BACKUP_ROOT}/baseline/kubelet-config.yaml || cp -a /var/lib/kubelet/config.yaml {config.BACKUP_ROOT}/baseline/kubelet-config.yaml
test -f {config.BACKUP_ROOT}/baseline/containerd-config.toml || cp -a /etc/containerd/config.toml {config.BACKUP_ROOT}/baseline/containerd-config.toml
test -d {config.BACKUP_ROOT}/baseline/kubelet.service.d || cp -a /etc/systemd/system/kubelet.service.d {config.BACKUP_ROOT}/baseline/kubelet.service.d
echo BASELINE_OK
"""
        results: dict[str, dict] = {}
        for name in config.VM_NAMES:
            res = await provider.get().exec(name, script, sudo=True, timeout=60)
            results[name] = {
                "ok": res.ok and "BASELINE_OK" in res.out,
                "detail": (res.err or "").strip()[:200],
            }
        await self.snapshot_node_metadata()
        return results

    async def snapshot_node_metadata(self) -> None:
        """Capture baseline node taints so teardown can remove any scenario-added taints."""
        res = await cluster.kubectl(["get", "nodes", "-o", "json"], timeout=15)
        if not res.ok:
            return
        try:
            items = json.loads(res.out).get("items") or []
        except ValueError:
            return
        snapshot: dict[str, dict] = {}
        for item in items:
            name = (item.get("metadata") or {}).get("name")
            if not name:
                continue
            taints = [
                {
                    "key": t.get("key"),
                    "value": t.get("value"),
                    "effect": t.get("effect"),
                }
                for t in ((item.get("spec") or {}).get("taints") or [])
                if t.get("key")
            ]
            snapshot[name] = {"taints": taints}
        try:
            config.BASELINE_NODES_PATH.parent.mkdir(parents=True, exist_ok=True)
            config.BASELINE_NODES_PATH.write_text(json.dumps(snapshot, indent=2))
        except OSError:
            pass

    # Nota: snapshots de VM não são suportados no backend QEMU do Multipass/macOS
    # ("The snapshots feature is not implemented on this backend"). O reset limpo vive em
    # teardown.reset_clean(): baseline de arquivos + varredura de recursos + restart de agentes.

