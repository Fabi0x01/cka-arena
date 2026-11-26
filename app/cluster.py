"""Wrapper kubectl — sempre kubeconfig dedicado + contexto `cka`."""

from __future__ import annotations

import asyncio
import datetime
import json
import time

from app import config
from app.ssh_runner import ProcResult, _run


def kubectl_cmd(args: list[str]) -> list[str]:
    base = ["kubectl"]
    if config.KUBECONFIG_PATH.exists():
        base += ["--kubeconfig", str(config.KUBECONFIG_PATH)]
    base += ["--context", config.KUBECTL_CONTEXT]
    return base + args


async def kubectl(
    args: list[str],
    *,
    timeout: float = 20,
    stdin_data: str | None = None,
) -> ProcResult:
    return await _run(kubectl_cmd(args), timeout=timeout, stdin_data=stdin_data)


async def current_context(*, timeout: float = 8) -> str | None:
    """Return the active kubeconfig context name (used to verify student context switching)."""
    cmd = ["kubectl"]
    if config.KUBECONFIG_PATH.exists():
        cmd += ["--kubeconfig", str(config.KUBECONFIG_PATH)]
    cmd += ["config", "current-context"]
    res = await _run(cmd, timeout=timeout)
    if not res.ok:
        return None
    ctx = (res.out or "").strip()
    return ctx or None


async def readyz(*, timeout: float = 6) -> bool:
    res = await kubectl(["get", "--raw", "/readyz"], timeout=timeout)
    return res.ok and res.out.strip() == "ok"


async def get_nodes(*, timeout: float = 15) -> list[dict]:
    res = await kubectl(["get", "nodes", "-o", "json"], timeout=timeout)
    if not res.ok:
        return []
    data = json.loads(res.out)
    nodes: list[dict] = []
    for item in data.get("items", []):
        internal_ip = None
        for addr in item.get("status", {}).get("addresses", []):
            if addr.get("type") == "InternalIP":
                internal_ip = addr.get("address")
                break
        ready = any(
            cond.get("type") == "Ready" and cond.get("status") == "True"
            for cond in item.get("status", {}).get("conditions", [])
        )
        nodes.append({
            "name": item.get("metadata", {}).get("name", ""),
            "ready": ready,
            "internal_ip": internal_ip,
        })
    return nodes


async def pods(namespace: str, *, timeout: float = 15) -> list[dict]:
    res = await kubectl(["get", "pods", "-n", namespace, "-o", "json"], timeout=timeout)
    if not res.ok:
        return []
    data = json.loads(res.out)
    out: list[dict] = []
    for item in data.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses") or []
        out.append({
            "name": item.get("metadata", {}).get("name", ""),
            "phase": item.get("status", {}).get("phase"),
            "ready": bool(statuses) and all(cs.get("ready") for cs in statuses),
        })
    return out


def _parse_k8s_ts(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


async def pods_detailed(namespace: str, *, timeout: float = 15) -> list[dict]:
    """Pod status with scheduling conditions and waiting/terminated container reasons."""
    res = await kubectl(["get", "pods", "-n", namespace, "-o", "json"], timeout=timeout)
    if not res.ok:
        return []
    try:
        data = json.loads(res.out)
    except ValueError:
        return []
    out: list[dict] = []
    for item in data.get("items", []):
        meta = item.get("metadata") or {}
        status = item.get("status") or {}
        conditions = status.get("conditions") or []
        unschedulable = any(
            c.get("type") == "PodScheduled"
            and c.get("status") == "False"
            and c.get("reason") == "Unschedulable"
            for c in conditions
        )
        c_statuses = status.get("containerStatuses") or []
        init_statuses = status.get("initContainerStatuses") or []
        all_cs = [*init_statuses, *c_statuses]
        waiting_reasons: list[str] = []
        terminated_reasons: list[str] = []
        for cs in all_cs:
            state = cs.get("state") or {}
            waiting = state.get("waiting") or {}
            if waiting.get("reason"):
                waiting_reasons.append(str(waiting["reason"]))
            terminated = state.get("terminated") or {}
            if terminated.get("reason"):
                terminated_reasons.append(str(terminated["reason"]))
            last_term = (cs.get("lastState") or {}).get("terminated") or {}
            if last_term.get("reason"):
                terminated_reasons.append(str(last_term["reason"]))
        out.append({
            "name": meta.get("name", ""),
            "phase": status.get("phase"),
            "ready": bool(c_statuses) and all(cs.get("ready") for cs in c_statuses),
            "unschedulable": unschedulable,
            "waiting_reasons": waiting_reasons,
            "terminated_reasons": terminated_reasons,
            "created_ts": _parse_k8s_ts(meta.get("creationTimestamp")),
        })
    return out


async def crd_exists(name: str) -> bool:
    return (await kubectl(["get", "crd", name, "-o", "name"], timeout=10)).ok


async def storage_class_exists(name: str) -> bool:
    return (await kubectl(["get", "sc", name, "-o", "name"], timeout=10)).ok


async def wait_readyz(timeout_s: float = 180, interval: float = 3) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await readyz():
            return True
        await asyncio.sleep(interval)
    return False


async def wait_nodes_ready(
    count: int = 3,
    timeout_s: float = 300,
    interval: float = 3,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        nodes = await get_nodes()
        if len(nodes) >= count and all(n["ready"] for n in nodes):
            return True
        await asyncio.sleep(interval)
    return False
