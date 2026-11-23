"""ClusterPowerManager — ciclo de vida das VMs Multipass + boot instrumentado (7 passos)."""

from __future__ import annotations

import asyncio
import time
import uuid

from app import cluster, config, provider, ssh_runner
from app.doctor import ClusterDoctor
from app.events import EventBroker

STEP_TOTAL = 7
JOBS = ("start", "stop", "restart")


class JobActiveError(RuntimeError):
    pass


class ClusterPowerManager:
    def __init__(self, broker: EventBroker, doctor: ClusterDoctor) -> None:
        self.broker = broker
        self.doctor = doctor
        self.state = "unknown"
        self.last_ready_at: float | None = None
        self._detail: str | None = None
        self._active_job: dict | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------ lifecycle

    async def detect(self) -> dict:
        """Detecção passiva do estado (sem job ativo)."""
        try:
            nodes = await provider.get().nodes()
        except Exception as exc:
            self._set_state("daemon_down", detail=str(exc)[:300])
            return {"state": self.state, "vms": [], "detail": self._detail}

        vm_rows = [
            {
                "name": name,
                "state": info.state,
                "ips": [info.ip] if info.ip else [],
            }
            for name, info in nodes.items()
        ]
        states = [row["state"] for row in vm_rows]

        if all(state == "Stopped" for state in states):
            self._set_state("off")
        elif any(state == "Running" for state in states):
            if await cluster.readyz():
                nodes = await cluster.get_nodes()
                if len(nodes) >= 3 and all(node["ready"] for node in nodes):
                    self.last_ready_at = time.time()
                    self._set_state("ready", detail="3/3 nodes Ready")
                else:
                    self._set_state("degraded", detail="API responde, mas nem todos os nós estão Ready")
            else:
                self._set_state("degraded", detail="VMs ligadas, kube-apiserver não responde")
        else:
            self._set_state("degraded", detail=f"estados das VMs: {states}")

        return {"state": self.state, "vms": vm_rows, "detail": self._detail}

    async def status(self) -> dict:
        if self._active_job:
            return {
                "state": self.state,
                "vms": await self._vms_soft(),
                "last_ready_at": self.last_ready_at,
                "active_job": self._active_job["id"],
                "detail": self._detail,
            }
        detected = await self.detect()
        return {
            "state": detected["state"],
            "vms": detected["vms"],
            "last_ready_at": self.last_ready_at,
            "active_job": None,
            "detail": self._detail,
        }

    async def start_action(self, action: str) -> str:
        if action not in JOBS:
            raise ValueError(f"ação inválida: {action}")
        async with self._lock:
            if self._active_job:
                raise JobActiveError(self._active_job["id"])
            job_id = uuid.uuid4().hex[:12]
            self._active_job = {"id": job_id, "action": action, "started_at": time.time()}
        self._task = asyncio.create_task(self._run(action, job_id))
        return job_id

    async def _run(self, action: str, job_id: str) -> None:
        try:
            if action == "stop":
                await self._stop(job_id)
            elif action == "restart":
                await self._stop(job_id)
                await self._boot(job_id)
            else:
                await self._boot(job_id)
        except Exception as exc:
            self._publish_progress(job_id, 0, STEP_TOTAL, f"error: {str(exc)[:400]}")
            self._set_state("degraded", detail=str(exc)[:400])
        finally:
            self._active_job = None

    # ------------------------------------------------------------ stop / boot

    async def _stop(self, job_id: str) -> None:
        node_provider = provider.get()
        self._set_state("stopping", detail="stopping nodes")
        self._publish_progress(job_id, 1, 1, f"{node_provider.name}: stopping all nodes")
        res = await node_provider.power(False)
        if not res.ok:
            raise RuntimeError(f"{node_provider.name} stop falhou: {(res.err or res.out).strip()[:300]}")
        self._set_state("off", detail="nodes stopped")

    async def _boot(self, job_id: str) -> None:
        self._set_state("starting", detail="boot in progress")

        # 1/7 — nós
        node_provider = provider.get()
        self._publish_progress(job_id, 1, STEP_TOTAL, f"{node_provider.name}: starting nodes")
        res = await node_provider.power(True)
        if not res.ok:
            raise RuntimeError(f"{node_provider.name} start falhou: {(res.err or res.out).strip()[:300]}")

        # 2/7 — nós alcançáveis (+ ponte SSH só no provider multipass)
        self._publish_progress(job_id, 2, STEP_TOTAL, "waiting for all 3 nodes")
        ips = await node_provider.wait_ready(timeout_s=240)
        if node_provider.manages_ssh_keys:
            ssh_runner.ensure_keypair()
            for name, ip in ips.items():
                if not await ssh_runner.ssh_authorized(ip):
                    copy = await ssh_runner.install_key(ip, config.LAB_PASSWORD)
                    if not copy.ok and not await ssh_runner.ssh_authorized(ip):
                        raise RuntimeError(
                            f"ssh-copy-id falhou em {name} ({ip}): {(copy.err or copy.out).strip()[:200]}"
                        )

        # 3/7 — ssh config gerenciado (multipass) / no-op no kind
        self._publish_progress(job_id, 3, STEP_TOTAL, "wiring node access")
        if node_provider.manages_ssh_keys:
            ssh_runner.write_managed_ssh_config(ips)

        # 4/7 — API de pé (+ self-heal de kubeconfig se o IP mudou)
        self._publish_progress(job_id, 4, STEP_TOTAL, "waiting for kube-apiserver /readyz")
        api_ok = await cluster.wait_readyz(timeout_s=45)
        if not api_ok or not config.KUBECONFIG_PATH.exists():
            if not node_provider.manages_ssh_keys:
                raise RuntimeError(
                    "kube-apiserver não responde e o provider kind não tem self-heal de "
                    "kubeconfig — re-rode scripts/cluster/kind-up.sh"
                )
            self._publish_progress(
                job_id, 4, STEP_TOTAL,
                "kubeconfig self-heal: refreshing admin.conf from controlplane",
            )
            await ssh_runner.ensure_dedicated_kubeconfig(ips["controlplane"], config.LAB_PASSWORD)
            if not await cluster.wait_readyz(timeout_s=180):
                raise RuntimeError("kube-apiserver não ficou pronto (/readyz)")

        # 5/7 — nós Ready
        self._publish_progress(job_id, 5, STEP_TOTAL, "waiting for nodes Ready")
        if not await cluster.wait_nodes_ready(timeout_s=300):
            raise RuntimeError("nós não ficaram Ready a tempo")

        # 6/7 — doctor quick
        self._publish_progress(job_id, 6, STEP_TOTAL, "cluster doctor: health/addons")
        health = await self.doctor.health()

        # 7/7 — baseline de arquivos nos nós
        self._publish_progress(job_id, 7, STEP_TOTAL, "ensuring node baseline files")
        await self.doctor.ensure_baseline_files(config.LAB_PASSWORD)

        self.last_ready_at = time.time()
        self._set_state("ready", detail=f"{health['nodes_ready']}/3 nodes Ready")

    # ------------------------------------------------------------ helpers

    async def _vms_soft(self) -> list[dict]:
        try:
            nodes = await provider.get().nodes()
        except Exception:
            return []
        return [
            {"name": name, "state": info.state,
             "ips": [info.ip] if info.ip else []}
            for name, info in nodes.items()
        ]

    def _set_state(self, state: str, detail: str | None = None) -> None:
        changed = state != self.state
        self.state = state
        self._detail = detail
        if changed:
            self.broker.publish("cluster.power.state_changed", {"state": state, "detail": detail})

    def _publish_progress(self, job_id: str, step: int, total: int, detail: str) -> None:
        self.broker.publish(
            "cluster.power.progress",
            {"job_id": job_id, "step": step, "total": total, "detail": detail},
        )
