"""Provider de nós — abstrai Multipass VMs (macOS/Linux) e kind containers (WSL2/Linux+Docker).

A plataforma fala apenas nomes LÓGICOS (controlplane/node01/node02); o provider traduz
para o nome real do nó e para o transporte (SSH ou docker exec). Ver SETUP_PLAN.md §2.1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app import config
from app.ssh_runner import ProcResult


@dataclass
class NodeInfo:
    name: str                    # lógico: controlplane/node01/node02
    real_name: str               # nome no cluster (kubectl get nodes)
    state: str                   # Running / Stopped / Unknown
    ip: str | None = None
    container: str | None = None  # kind: container docker do nó


class Provider:
    name = "base"
    transport = "ssh"
    manages_ssh_keys = False     # multipass instala chave; kind não usa SSH

    async def nodes(self) -> dict[str, NodeInfo]:
        raise NotImplementedError

    async def exec(self, node: str, command: str, *, sudo: bool = False,
                   timeout: float = 20.0) -> ProcResult:
        raise NotImplementedError

    async def power(self, on: bool) -> ProcResult:
        raise NotImplementedError

    def terminal_command(self, node: str) -> list[str]:
        raise NotImplementedError

    async def wait_ready(self, timeout_s: float = 240) -> dict[str, str]:
        raise NotImplementedError


def provider_name() -> str:
    explicit = os.environ.get("CKA_PROVIDER", "").strip()
    if explicit in ("multipass", "kind"):
        return explicit
    try:
        value = (config.CKA_DIR / "provider").read_text().strip()
    except OSError:
        return "multipass"
    return value if value in ("multipass", "kind") else "multipass"


_PROVIDER: Provider | None = None


def get() -> Provider:
    global _PROVIDER
    wanted = provider_name()
    if _PROVIDER is None or _PROVIDER.name != wanted:
        if wanted == "kind":
            from app.provider.kind import KindProvider
            _PROVIDER = KindProvider()
        else:
            from app.provider.multipass import MultipassProvider
            _PROVIDER = MultipassProvider()
    return _PROVIDER


def reset() -> None:
    """Troca de provider em runtime (setup/tests)."""
    global _PROVIDER
    _PROVIDER = None
