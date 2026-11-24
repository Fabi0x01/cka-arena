"""Dispatcher de comandos de ferramentas locais (kubectl/helm) — setup/solution/cleanup."""

from __future__ import annotations

import os
import shlex

from app import cluster, config, provider
from app.ssh_runner import ProcResult, run_local

ALLOWED_TOOLS = ("kubectl", "helm")
_NODE_TARGET_VERBS = frozenset({"taint", "label", "annotate"})
_DIRECT_NODE_VERBS = frozenset({"cordon", "uncordon", "drain"})


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


def _translate_kubectl_node_tokens(tokens: list[str]) -> list[str]:
    """Translate logical node names (controlplane/node01/node02) to kind node names when active."""
    if len(tokens) < 3 or tokens[0] != "kubectl" or provider.provider_name() != "kind":
        return tokens
    out = list(tokens)
    verb = ""
    verb_idx = -1
    skip_next = False
    for idx in range(1, len(out)):
        if skip_next:
            skip_next = False
            continue
        tok = out[idx]
        if tok.startswith("-"):
            if "=" not in tok and idx + 1 < len(out):
                skip_next = True
            continue
        verb = tok
        verb_idx = idx
        break
    if verb in _DIRECT_NODE_VERBS:
        for idx in range(verb_idx + 1, len(out)):
            if out[idx] in config.VM_NAMES:
                out[idx] = provider.resolve_node_name(out[idx])
    elif verb in _NODE_TARGET_VERBS:
        saw_node_resource = False
        for idx in range(verb_idx + 1, len(out)):
            tok = out[idx]
            if tok.startswith("-"):
                continue
            if not saw_node_resource:
                if tok in ("node", "nodes", "no"):
                    saw_node_resource = True
                elif tok.startswith(("node/", "nodes/")):
                    prefix, _, name = tok.partition("/")
                    if name in config.VM_NAMES:
                        out[idx] = f"{prefix}/{provider.resolve_node_name(name)}"
                    saw_node_resource = True
                continue
            if tok in config.VM_NAMES:
                out[idx] = provider.resolve_node_name(tok)
    return out


async def run_tool_command(raw: str, *, timeout: float = 120) -> ProcResult:
    tokens = [resolve_asset_token(t) for t in shlex.split(raw)]
    if not tokens:
        raise CommandRejected("empty command")
    tool = tokens[0]
    if tool not in ALLOWED_TOOLS:
        raise CommandRejected(f"disallowed tool: {tool} (use {'/'.join(ALLOWED_TOOLS)})")
    if tool == "kubectl":
        tokens = _translate_kubectl_node_tokens(tokens)
        return await cluster.kubectl(tokens[1:], timeout=timeout)
    # helm/rede: sempre o kubeconfig dedicado — nunca o ~/.kube/config do usuário
    env = {**os.environ, "KUBECONFIG": str(config.KUBECONFIG_PATH)}
    return await run_local(tokens, timeout=timeout, env=env)


def tool_allowed(raw: str) -> bool:
    tokens = shlex.split(raw)
    return bool(tokens) and tokens[0] in ALLOWED_TOOLS
