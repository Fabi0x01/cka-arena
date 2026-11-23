"""Dispatcher de comandos de ferramentas locais (kubectl/helm) — setup/solution/cleanup."""

from __future__ import annotations

import os
import shlex

from app import cluster, config
from app.ssh_runner import ProcResult, run_local

ALLOWED_TOOLS = ("kubectl", "helm")


class CommandRejected(ValueError):
    pass


def resolve_asset_token(token: str) -> str:
    """Resolve relative asset paths (assets/... or scenarios/seed/assets/...) to an existing path."""
    for prefix in ("scenarios/seed/assets/", "assets/"):
        if token.startswith(prefix):
            rel = token[len(prefix):]
            for base in (config.ASSETS_DIR, config.SOURCE_ASSETS_DIR):
                candidate = base / rel
                if candidate.exists():
                    return str(candidate)
            fallback = config.SOURCE_ASSETS_DIR / rel
            return str(fallback)
    return token


async def run_tool_command(raw: str, *, timeout: float = 120) -> ProcResult:
    tokens = [resolve_asset_token(t) for t in shlex.split(raw)]
    if not tokens:
        raise CommandRejected("empty command")
    tool = tokens[0]
    if tool not in ALLOWED_TOOLS:
        raise CommandRejected(f"disallowed tool: {tool} (use {'/'.join(ALLOWED_TOOLS)})")
    if tool == "kubectl":
        return await cluster.kubectl(tokens[1:], timeout=timeout)
    # helm/rede: sempre o kubeconfig dedicado — nunca o ~/.kube/config do usuário
    env = {**os.environ, "KUBECONFIG": str(config.KUBECONFIG_PATH)}
    return await run_local(tokens, timeout=timeout, env=env)


def tool_allowed(raw: str) -> bool:
    tokens = shlex.split(raw)
    return bool(tokens) and tokens[0] in ALLOWED_TOOLS
