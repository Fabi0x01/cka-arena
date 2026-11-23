"""Multipass provider — VM nodes over Bridged SSH with short TTL cache for exec()."""

from __future__ import annotations

import time

from app import config, ssh_runner
from app.provider.base import NodeInfo, Provider
from app.ssh_runner import ProcResult

NODES_CACHE_TTL_S = 20.0


class MultipassProvider(Provider):
    name = "multipass"
    transport = "ssh"
    manages_ssh_keys = True

    def __init__(self) -> None:
        self._cache: dict[str, NodeInfo] | None = None
        self._cache_at: float = 0.0

    def invalidate_cache(self) -> None:
        self._cache = None
        self._cache_at = 0.0

    async def nodes(self, *, use_cache: bool = False) -> dict[str, NodeInfo]:
        now = time.monotonic()
        if use_cache and self._cache is not None and (now - self._cache_at) < NODES_CACHE_TTL_S:
            return dict(self._cache)
        vms = await ssh_runner.list_vms()
        out: dict[str, NodeInfo] = {}
        for name in config.VM_NAMES:
            info = vms.get(name) or {}
            ip = await ssh_runner.resolve_ip(info.get("ips") or [])
            out[name] = NodeInfo(
                name=name,
                real_name=name,          # VM name == k8s node name
                state=info.get("state", "Unknown"),
                ip=ip,
            )
        self._cache = dict(out)
        self._cache_at = time.monotonic()
        return out

    async def exec(self, node: str, command: str, *, sudo: bool = False,
                   timeout: float = 20.0) -> ProcResult:
        try:
            info = (await self.nodes(use_cache=True)).get(node)
        except Exception as exc:
            self.invalidate_cache()
            return ProcResult(255, "", f"multipass unreachable: {str(exc)[:160]}")
        if not info or not info.ip:
            self.invalidate_cache()
            return ProcResult(255, "", f"node {node} has no SSH IP")
        if sudo:
            res = await ssh_runner.sudo_run(info.ip, command, timeout=timeout)
        else:
            res = await ssh_runner.ssh_run(info.ip, command, timeout=timeout)
        if res.rc == 255:
            self.invalidate_cache()
        return res

    async def power(self, on: bool) -> ProcResult:
        self.invalidate_cache()
        action = "start" if on else "stop"
        res = await ssh_runner.multipass([action, *config.VM_NAMES], timeout=300)
        self.invalidate_cache()
        return res

    def terminal_command(self, node: str) -> list[str]:
        return ["ssh", f"cka-{node}"]

    async def wait_ready(self, timeout_s: float = 240) -> dict[str, str]:
        self.invalidate_cache()
        return await ssh_runner.wait_vm_ips(timeout_s=timeout_s)
