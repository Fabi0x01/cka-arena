"""Provider kind — WSL2 / Linux com Docker Engine (sem Multipass, sem VM aninhada).

Nós = containers kind; transporte = `docker exec` (não há SSH). O mapeamento entre os
nomes lógicos da plataforma e os nomes reais do kind fica em ~/.cka-arena/nodes.json,
escrito por scripts/cluster/kind-up.sh.
"""

from __future__ import annotations

import json

from app import config
from app.provider.base import NodeInfo, Provider
from app.ssh_runner import ProcResult, run_local

def _mapping_path():
    return config.CKA_DIR / "nodes.json"


def _load_mapping() -> dict[str, dict]:
    try:
        data = json.loads(_mapping_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def _docker(args: list[str], timeout: float = 20.0) -> ProcResult:
    return await run_local(["docker", *args], timeout=timeout)


class KindProvider(Provider):
    name = "kind"
    transport = "docker"
    manages_ssh_keys = False

    async def nodes(self) -> dict[str, NodeInfo]:
        mapping = _load_mapping()
        out: dict[str, NodeInfo] = {}
        for name in config.VM_NAMES:
            entry = mapping.get(name) or {}
            container = entry.get("container") or f"cka-{name}"
            real = entry.get("node") or container
            res = await _docker(
                ["inspect", "-f", "{{.State.Running}}", container], timeout=10
            )
            if res.ok:
                state = "Running" if res.out.strip() == "true" else "Stopped"
            else:
                state = "Unknown"
            out[name] = NodeInfo(name=name, real_name=real, state=state, container=container)
        return out

    async def exec(self, node: str, command: str, *, sudo: bool = False,
                   timeout: float = 20.0) -> ProcResult:
        # kind nodes run as root inside the container: sudo is a no-op
        info = (await self.nodes()).get(node)
        if not info or not info.container:
            return ProcResult(255, "", f"node {node} has no kind container")
        return await _docker(["exec", info.container, "sh", "-lc", command], timeout=timeout)

    async def power(self, on: bool) -> ProcResult:
        info = await self.nodes()
        containers = [i.container for i in info.values() if i.container]
        if not containers:
            return ProcResult(1, "", "no kind containers found")
        # workers first on stop, control plane first on start
        ordered = containers if on else list(reversed(containers))
        for container in ordered:
            res = await _docker(["start" if on else "stop", container], timeout=120)
            if not res.ok:
                return res
        return ProcResult(0, "", "")

    def terminal_command(self, node: str) -> list[str]:
        mapping = _load_mapping()
        container = (mapping.get(node) or {}).get("container") or f"cka-{node}"
        return ["docker", "exec", "-it", container, "bash"]

    async def wait_ready(self, timeout_s: float = 240) -> dict[str, str]:
        ips: dict[str, str] = {}
        for name, info in (await self.nodes()).items():
            if info.state == "Running":
                ips[name] = info.container or name
        return ips
