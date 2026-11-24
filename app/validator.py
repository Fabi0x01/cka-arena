"""Deterministic check engine — PASS/FAIL/SKIP/ERROR contract (LLM_PIPELINE_SPEC §5)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import time
import uuid
from typing import Any

from app import cluster, config, provider
from app.models import CheckSpec
from app.ssh_runner import ProcResult, run_local

PASS, FAIL, SKIP, ERROR = "PASS", "FAIL", "SKIP", "ERROR"

# Execution groups: 1=API reads (parallel), 2=pods (parallel), 3=nodes/SSH (parallel)
GROUP = {
    "kubectl_resource_exists": 1,
    "kubectl_jsonpath": 1,
    "kubectl_auth_can_i": 1,
    "helm_release_state": 1,
    "node_status_ready": 1,
    "service_endpoints_ready": 1,
    "deployment_rollout_ready": 1,
    "pvc_bound": 1,
    "pod_status_ready": 2,
    "pod_exec_exit_zero": 2,
    "pod_exec_must_fail": 2,
    "node_command_exit_zero": 3,
    "host_file_contains": 3,
}

TIMEOUTS = {
    "pod_exec_exit_zero": 45,
    "pod_exec_must_fail": 45,
    "node_command_exit_zero": 15,
    "helm_release_state": 20,
}
DEFAULT_TIMEOUT = 10
PROBE_IMAGE = "curlimages/curl:8.10.1"

_INFRA_PATTERNS = (
    "unable to connect to the server",
    "connection refused",
    "was refused",
    "i/o timeout",
    "no route to host",
    "connection reset by peer",
    "timeout after",
    "operation timed out",
)

_WARM_PROBE_LOCK = asyncio.Lock()
_WARM_PROBE_READY_AT: float = 0.0


def _split_tokens(actual: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", actual.strip()) if part.strip()]


def compare(actual: str, operator: str, expected: Any) -> bool:
    actual = actual.strip()
    if operator == "equals":
        return actual == str(expected).strip()
    if operator == "equals_int":
        try:
            return int(float(actual)) == int(float(expected))
        except (ValueError, TypeError):
            return False
    if operator == "contains":
        return str(expected) in actual
    if operator == "not_contains":
        return str(expected) not in actual
    if operator == "empty":
        return actual == ""
    if operator == "not_empty":
        return actual != ""
    if operator == "gte":
        try:
            return float(actual) >= float(expected)
        except (ValueError, TypeError):
            return False
    if operator == "regex":
        return re.search(str(expected), actual) is not None
    if operator == "len_gte":
        return len(_split_tokens(actual)) >= int(expected)
    if operator == "all_match":
        tokens = _split_tokens(actual)
        want = str(expected).strip()
        return bool(tokens) and all(tok == want for tok in tokens)
    raise ValueError(f"unknown operator: {operator}")


def classify(res: ProcResult) -> str:
    """FAIL = user/cluster state; ERROR = infra (does not consume candidate attempts)."""
    if res.ok:
        return PASS
    text = f"{res.err}\n{res.out}".lower()
    if any(pattern in text for pattern in _INFRA_PATTERNS):
        return ERROR
    return FAIL


def _tail(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    return text[-limit:]


def _parse_k8s_bytes(value: str | int | float) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(Ki|Mi|Gi|Ti|K|M|G|T)?", text)
    if not m:
        raise ValueError(f"invalid storage quantity: {text}")
    num = float(m.group(1))
    unit = m.group(2) or ""
    factors = {
        "": 1,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
    }
    return int(num * factors[unit])


def normalize_params(check_type: str, params: dict) -> dict:
    """Accept common LLM param aliases and normalize jsonpath braces."""
    p = dict(params or {})
    if "kind" not in p and "resource" in p:
        p["kind"] = p["resource"]
    if check_type == "pod_status_ready":
        if "min_ready" not in p and "ready" in p:
            p["min_ready"] = p["ready"]
        if "label_selector" not in p and "selector" in p:
            p["label_selector"] = p["selector"]
    elif check_type == "kubectl_jsonpath":
        jsonpath = str(p.get("jsonpath") or "").strip()
        if jsonpath and not jsonpath.startswith("{"):
            jsonpath = "{" + jsonpath + "}"
        if jsonpath:
            p["jsonpath"] = jsonpath
        if "expected_count" in p:
            p.setdefault("operator", "len_gte")
            p.setdefault("expected", p["expected_count"])
        if "expected_contains" in p:
            p.setdefault("operator", "contains")
            p.setdefault("expected", p["expected_contains"])
    elif check_type in ("pod_exec_exit_zero", "pod_exec_must_fail"):
        pod_name = p.get("pod") or p.get("name")
        if pod_name:
            p.setdefault("pod_name", pod_name)
        if "label_selector" not in p and "selector" in p:
            p["label_selector"] = p["selector"]
    elif check_type == "service_endpoints_ready":
        if "service_name" not in p:
            for alias in ("name", "service"):
                if p.get(alias):
                    p["service_name"] = p[alias]
                    break
        if "min_ready_addresses" not in p and "min_ready" in p:
            p["min_ready_addresses"] = p["min_ready"]
    elif check_type == "deployment_rollout_ready":
        if "name" not in p and p.get("deployment"):
            p["name"] = p["deployment"]
        if "min_ready_replicas" not in p:
            for alias in ("min_ready", "replicas"):
                if alias in p:
                    p["min_ready_replicas"] = p[alias]
                    break
        if "expected_image" not in p and p.get("image"):
            p["expected_image"] = p["image"]
    elif check_type == "pvc_bound":
        if "name" not in p and p.get("pvc"):
            p["name"] = p["pvc"]
        if "storage_class" not in p and p.get("storageClassName"):
            p["storage_class"] = p["storageClassName"]
    return p


async def _pod_by_name(namespace: str, name: str) -> dict | None:
    res = await cluster.kubectl(["get", "pod", name, "-n", namespace, "-o", "json"], timeout=12)
    if not res.ok:
        return None
    data = json.loads(res.out)
    statuses = data.get("status", {}).get("containerStatuses") or []
    return {
        "name": name,
        "phase": data.get("status", {}).get("phase"),
        "ready": bool(statuses) and all(cs.get("ready") for cs in statuses),
    }


async def _pods(namespace: str, selector: str | None = None) -> list[dict]:
    args = ["get", "pods", "-n", namespace, "-o", "json"]
    if selector:
        args = ["get", "pods", "-n", namespace, "-l", selector, "-o", "json"]
    res = await cluster.kubectl(args, timeout=12)
    if not res.ok:
        return []
    data = json.loads(res.out)
    pods: list[dict] = []
    for item in data.get("items", []):
        statuses = item.get("status", {}).get("containerStatuses") or []
        pods.append({
            "name": item.get("metadata", {}).get("name", ""),
            "phase": item.get("status", {}).get("phase"),
            "ready": bool(statuses) and all(cs.get("ready") for cs in statuses),
        })
    return pods


async def ensure_warm_probe() -> bool:
    """Keep a lightweight warm probe Pod running in cka-arena-system for fast HTTP/DNS checks."""
    global _WARM_PROBE_READY_AT
    now = time.monotonic()
    if now - _WARM_PROBE_READY_AT < 30.0:
        return True
    async with _WARM_PROBE_LOCK:
        if time.monotonic() - _WARM_PROBE_READY_AT < 30.0:
            return True
        ns = config.WARM_PROBE_NAMESPACE
        pod = config.WARM_PROBE_POD
        existing = await _pod_by_name(ns, pod)
        if existing and existing["phase"] == "Running" and existing["ready"]:
            _WARM_PROBE_READY_AT = time.monotonic()
            return True
        await cluster.kubectl(["create", "namespace", ns], timeout=10)
        if existing and existing["phase"] in ("Failed", "Succeeded"):
            await cluster.kubectl(["delete", "pod", pod, "-n", ns, "--ignore-not-found"], timeout=10)
            existing = None
        if not existing:
            manifest = (
                "apiVersion: v1\n"
                "kind: Pod\n"
                "metadata:\n"
                f"  name: {pod}\n"
                f"  namespace: {ns}\n"
                "  labels:\n"
                "    cka-arena.io/warm-probe: \"true\"\n"
                "spec:\n"
                "  restartPolicy: Never\n"
                "  containers:\n"
                "  - name: probe\n"
                f"    image: {PROBE_IMAGE}\n"
                "    command: [\"sleep\", \"infinity\"]\n"
            )
            applied = await cluster.kubectl(["apply", "-f", "-"], timeout=20, stdin_data=manifest)
            if not applied.ok:
                return False
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            cur = await _pod_by_name(ns, pod)
            if cur and cur["phase"] == "Running" and cur["ready"]:
                _WARM_PROBE_READY_AT = time.monotonic()
                return True
            await asyncio.sleep(1.0)
        return False


async def _probe_run(namespace: str, command: str, timeout: float = 35) -> tuple[int, str]:
    """Ephemeral probe pod with probe label; returns (rc, logs) and always deletes it."""
    name = f"cka-probe-{uuid.uuid4().hex[:6]}"
    created = await cluster.kubectl(
        [
            "run", name, "-n", namespace,
            "--image", PROBE_IMAGE,
            "--restart", "Never",
            "--labels", "cka-arena.io/probe=true",
            "--command", "--", "sh", "-c", command,
        ],
        timeout=25,
    )
    if not created.ok:
        return 1, _tail(created.err or created.out)
    phase = ""
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            res = await cluster.kubectl(
                ["get", "pod", name, "-n", namespace, "-o", "jsonpath={.status.phase}"], timeout=10
            )
            phase = res.out.strip() if res.ok else phase
            if phase in ("Succeeded", "Failed"):
                break
            await asyncio.sleep(1.2)
        logs = await cluster.kubectl(["logs", name, "-n", namespace], timeout=12)
        return (0 if phase == "Succeeded" else 1), logs.out or logs.err
    finally:
        try:
            await asyncio.shield(
                cluster.kubectl(
                    ["delete", "pod", name, "-n", namespace, "--ignore-not-found", "--wait=false"],
                    timeout=10,
                )
            )
        except Exception:
            pass


async def _exec_or_probe(params: dict, *, allow_warm_probe: bool = True) -> tuple[int, str, str]:
    """Execute command inside target pod, warm probe pod, or ephemeral probe pod."""
    namespace = params["namespace"]
    selector = params.get("label_selector")
    command = params.get("command") or []
    cmd_str = command if isinstance(command, str) else " ".join(shlex.quote(str(c)) for c in command)

    pod_name = params.get("pod_name")
    if pod_name:
        pod = await _pod_by_name(namespace, pod_name)
        pods = [pod] if pod else []
    elif selector:
        pods = await _pods(namespace, selector)
    else:
        pods = []
    target = next((p for p in pods if p["ready"]), None)
    if target:
        exec_args = ["exec", "-n", namespace, target["name"]]
        container = params.get("container")
        if container:
            exec_args += ["-c", container]
        res = await cluster.kubectl([*exec_args, "--", "sh", "-c", cmd_str], timeout=25)
        return res.rc, f"{res.out}{res.err}", f"exec:{target['name']}"
    if params.get("ephemeral_probe"):
        if allow_warm_probe and params.get("probe_scope") != "in_namespace":
            if await ensure_warm_probe():
                res = await cluster.kubectl(
                    ["exec", "-n", config.WARM_PROBE_NAMESPACE, config.WARM_PROBE_POD, "--", "sh", "-c", cmd_str],
                    timeout=20,
                )
                err_lower = (res.err or "").lower()
                warm_broken = any(
                    hint in err_lower
                    for hint in ("not found", "unable to upgrade connection", "container not found", "is not running")
                )
                if not warm_broken:
                    return res.rc, f"{res.out}{res.err}", "warm_probe"
                global _WARM_PROBE_READY_AT
                _WARM_PROBE_READY_AT = 0.0
        rc, logs = await _probe_run(namespace, cmd_str)
        return rc, logs, "probe"
    return 127, "no pods match selector", "none"


# ---------------------------------------------------------------- checks

async def chk_kubectl_resource_exists(params: dict) -> tuple[str, dict]:
    kind, name = params["kind"], params["name"]
    namespace = params.get("namespace")
    args = ["get", kind, name, "-o", "name"]
    if namespace:
        args = ["get", kind, name, "-n", namespace, "-o", "name"]
    res = await cluster.kubectl(args, timeout=10)
    status = PASS if res.ok else classify(res)
    return status, {"kind": kind, "name": name, "namespace": namespace, "stderr": _tail(res.err)}


async def chk_kubectl_jsonpath(params: dict) -> tuple[str, dict]:
    kind = params["kind"]
    name = str(params.get("name") or "").strip()
    namespace = params.get("namespace")
    jsonpath = params["jsonpath"]
    operator = params.get("operator", "equals")
    expected = params.get("expected")
    selector = params.get("label_selector") or params.get("selector")
    args = ["get", kind]
    if name:
        args.append(name)
    elif selector:
        args += ["-l", selector]
    if namespace:
        args += ["-n", namespace]
    args += ["-o", f"jsonpath={jsonpath}"]
    res = await cluster.kubectl(args, timeout=10)
    evidence = {"kind": kind, "name": name or None, "namespace": namespace,
                "label_selector": selector, "jsonpath": jsonpath,
                "operator": operator, "expected": expected}
    if not res.ok:
        evidence["stderr"] = _tail(res.err)
        return classify(res), evidence
    actual = res.out.strip()
    evidence["actual"] = actual
    passed = compare(actual, operator, expected)
    if not passed and isinstance(expected, str) and expected in config.VM_NAMES:
        resolved_exp = provider.resolve_node_name(expected)
        if resolved_exp != expected:
            passed = compare(actual, operator, resolved_exp)
    return (PASS if passed else FAIL), evidence


async def chk_pod_status_ready(params: dict) -> tuple[str, dict]:
    namespace = params["namespace"]
    selector = params.get("label_selector")
    min_ready = int(params.get("min_ready", 1))
    pods = await _pods(namespace, selector)
    ready = sum(1 for p in pods if p["ready"] and p["phase"] == "Running")
    evidence = {"namespace": namespace, "label_selector": selector,
                "matched": len(pods), "ready": ready, "min_ready": min_ready,
                "pods": [{"name": p["name"], "phase": p["phase"], "ready": p["ready"]} for p in pods][:8]}
    if not pods:
        return SKIP, {**evidence, "reason": "no pods match selector"}
    return (PASS if ready >= min_ready else FAIL), evidence


async def chk_node_status_ready(params: dict) -> tuple[str, dict]:
    node_name = params["node_name"]
    resolved = provider.resolve_node_name(node_name)
    nodes = await cluster.get_nodes()
    match = next((n for n in nodes if n["name"] in (node_name, resolved)), None)
    evidence = {"node_name": node_name, "resolved_node_name": resolved, "found": bool(match),
                "ready": bool(match and match["ready"]),
                "nodes": [{"name": n["name"], "ready": n["ready"]} for n in nodes]}
    if not match:
        return ERROR, {**evidence, "reason": "node not found in API"}
    return (PASS if match["ready"] else FAIL), evidence


async def chk_kubectl_auth_can_i(params: dict) -> tuple[str, dict]:
    verb, resource = params["verb"], params["resource"]
    namespace = params["namespace"]
    sa = params["service_account"]
    target_ns = params.get("target_namespace") or namespace
    expected_allowed = bool(params.get("expected_allowed", True))
    args = [
        "auth", "can-i", verb, resource,
        "--as", f"system:serviceaccount:{namespace}:{sa}",
        "-n", target_ns,
    ]
    res = await cluster.kubectl(args, timeout=10)
    evidence = {"verb": verb, "resource": resource, "service_account": sa,
                "namespace": namespace, "target_namespace": target_ns,
                "expected_allowed": expected_allowed, "stdout": res.out.strip()}
    # `kubectl auth can-i` exits 1 when the answer is "no" — stdout carries the verdict.
    answer = res.out.strip().lower()
    if answer not in ("yes", "no"):
        evidence["stderr"] = _tail(res.err)
        return classify(res), evidence
    allowed = answer == "yes"
    return (PASS if allowed == expected_allowed else FAIL), evidence


async def chk_pod_exec_exit_zero(params: dict, *, allow_warm_probe: bool = True) -> tuple[str, dict]:
    rc, output, how = await _exec_or_probe(params, allow_warm_probe=allow_warm_probe)
    evidence = {"command": params.get("command"), "exit_code": rc, "how": how,
                "stdout": _tail(output)}
    if how == "none":
        return SKIP, {**evidence, "reason": "no pods match selector (and ephemeral_probe is disabled)"}
    if rc != 0:
        return FAIL, evidence
    want = params.get("stdout_contains")
    if want and str(want) not in output:
        return FAIL, {**evidence, "stdout_contains": want}
    return PASS, evidence


async def chk_pod_exec_must_fail(params: dict, *, allow_warm_probe: bool = True) -> tuple[str, dict]:
    rc, output, how = await _exec_or_probe(params, allow_warm_probe=allow_warm_probe)
    evidence = {"command": params.get("command"), "exit_code": rc, "how": how,
                "stdout": _tail(output)}
    if how == "none":
        return SKIP, {**evidence, "reason": "no pods match selector"}
    return (PASS if rc != 0 else FAIL), evidence


async def chk_node_command_exit_zero(params: dict) -> tuple[str, dict]:
    node = params["node"]
    command = params["command"]
    want = params.get("stdout_contains")
    node_provider = provider.get()
    try:
        info = (await node_provider.nodes()).get(node)
    except Exception as exc:
        return ERROR, {"node": node, "error": f"node unreachable: {str(exc)[:120]}"}
    if not info or info.state != "Running":
        return ERROR, {"node": node, "error": "node not reachable"}
    res = await node_provider.exec(node, command, timeout=15)
    evidence = {"node": node, "real_name": info.real_name, "command": command,
                "exit_code": res.rc, "stdout": _tail(res.out), "stderr": _tail(res.err)}
    if res.rc != 0:
        return (ERROR if "timeout after" in (res.err or "") else FAIL), evidence
    if want and str(want) not in res.out:
        return FAIL, {**evidence, "stdout_contains": want}
    return PASS, evidence


async def chk_host_file_contains(params: dict) -> tuple[str, dict]:
    location = params["location"]
    path = params["path"]
    patterns = params.get("regex_patterns") or []
    evidence = {"location": location, "path": path, "regex_patterns": patterns}
    if location == "host":
        try:
            content = open(path).read()
        except FileNotFoundError:
            return FAIL, {**evidence, "reason": "file does not exist"}
        except OSError as exc:
            return ERROR, {**evidence, "error": str(exc)[:200]}
    else:
        node_provider = provider.get()
        try:
            info = (await node_provider.nodes()).get(location)
        except Exception as exc:
            return ERROR, {**evidence, "error": f"node unreachable: {str(exc)[:120]}"}
        if not info or info.state != "Running":
            return ERROR, {"node": location, "error": "node not reachable"}
        quoted = shlex.quote(path)
        res = await node_provider.exec(location, f"cat {quoted}", timeout=12)
        if res.rc != 0:
            # /etc/kubernetes files are root-only: try sudo before failing
            res = await node_provider.exec(location, f"cat {quoted}", sudo=True, timeout=12)
        if res.rc != 0:
            stderr = _tail(res.err)
            reason = ("permission denied" if "permission denied" in stderr.lower()
                      else "file does not exist")
            return FAIL, {**evidence, "reason": reason, "stderr": stderr}
        content = res.out
    missing = [p for p in patterns if re.search(p, content) is None]
    evidence["missing_patterns"] = missing
    evidence["sample"] = _tail(content, 160)
    return (FAIL if missing else PASS), evidence


async def chk_helm_release_state(params: dict) -> tuple[str, dict]:
    namespace = params["namespace"]
    release = params["release_name"]
    expected_status = params.get("expected_status", "deployed")
    min_revision = int(params.get("min_revision", 0))
    env = {**os.environ, "KUBECONFIG": str(config.KUBECONFIG_PATH)}
    res = await run_local(["helm", "list", "-n", namespace, "-o", "json"], timeout=20, env=env)
    evidence = {"namespace": namespace, "release_name": release,
                "expected_status": expected_status, "min_revision": min_revision}
    if not res.ok:
        return classify(res), {**evidence, "stderr": _tail(res.err)}
    try:
        entries = json.loads(res.out or "[]")
    except ValueError:
        return ERROR, {**evidence, "error": "helm list returned invalid JSON"}
    match = next((e for e in entries if e.get("name") == release), None)
    if not match:
        return FAIL, {**evidence, "reason": "release not found"}
    evidence["status"] = match.get("status")
    evidence["revision"] = match.get("revision")
    ok = match.get("status") == expected_status and int(match.get("revision") or 0) >= min_revision
    return (PASS if ok else FAIL), evidence


async def chk_service_endpoints_ready(params: dict) -> tuple[str, dict]:
    namespace = params["namespace"]
    service_name = params["service_name"]
    min_ready = int(params.get("min_ready_addresses", 1))
    evidence: dict[str, Any] = {
        "namespace": namespace,
        "service_name": service_name,
        "min_ready_addresses": min_ready,
    }
    ready_ips: set[str] = set()
    res = await cluster.kubectl(
        ["get", "endpointslices", "-n", namespace, "-l", f"kubernetes.io/service-name={service_name}", "-o", "json"],
        timeout=10,
    )
    if res.ok:
        try:
            items = json.loads(res.out).get("items") or []
        except ValueError:
            items = []
        for slice_obj in items:
            for ep in slice_obj.get("endpoints") or []:
                if (ep.get("conditions") or {}).get("ready") is False:
                    continue
                for addr in ep.get("addresses") or []:
                    ready_ips.add(str(addr))
    if not ready_ips:
        ep_res = await cluster.kubectl(["get", "endpoints", service_name, "-n", namespace, "-o", "json"], timeout=10)
        if not ep_res.ok and not res.ok:
            evidence["stderr"] = _tail(ep_res.err or res.err)
            return classify(ep_res), evidence
        if ep_res.ok:
            try:
                ep_data = json.loads(ep_res.out)
            except ValueError:
                ep_data = {}
            for subset in ep_data.get("subsets") or []:
                for addr in subset.get("addresses") or []:
                    if addr.get("ip"):
                        ready_ips.add(str(addr["ip"]))
    evidence["ready_addresses"] = len(ready_ips)
    evidence["addresses"] = sorted(ready_ips)[:8]
    return (PASS if len(ready_ips) >= min_ready else FAIL), evidence


async def chk_deployment_rollout_ready(params: dict) -> tuple[str, dict]:
    namespace = params["namespace"]
    name = params["name"]
    min_ready = int(params.get("min_ready_replicas", 1))
    expected_image = params.get("expected_image")
    res = await cluster.kubectl(["get", "deployment", name, "-n", namespace, "-o", "json"], timeout=10)
    evidence: dict[str, Any] = {
        "namespace": namespace,
        "name": name,
        "min_ready_replicas": min_ready,
        "expected_image": expected_image,
    }
    if not res.ok:
        evidence["stderr"] = _tail(res.err)
        return classify(res), evidence
    data = json.loads(res.out)
    meta = data.get("metadata") or {}
    status = data.get("status") or {}
    containers = ((data.get("spec") or {}).get("template") or {}).get("spec", {}).get("containers") or []
    actual_image = containers[0].get("image") if containers else None
    gen = int(meta.get("generation") or 0)
    obs = int(status.get("observedGeneration") or 0)
    ready_replicas = int(status.get("readyReplicas") or 0)
    available_replicas = int(status.get("availableReplicas") or 0)
    evidence.update({
        "generation": gen,
        "observed_generation": obs,
        "ready": ready_replicas,
        "available_replicas": available_replicas,
        "actual_image": actual_image,
    })
    ok = obs >= gen and ready_replicas >= min_ready and available_replicas >= min_ready
    if expected_image and actual_image != expected_image:
        ok = False
    return (PASS if ok else FAIL), evidence


async def chk_pvc_bound(params: dict) -> tuple[str, dict]:
    namespace = params["namespace"]
    name = params["name"]
    storage_class = params.get("storage_class")
    min_storage = params.get("min_storage")
    res = await cluster.kubectl(["get", "pvc", name, "-n", namespace, "-o", "json"], timeout=10)
    evidence: dict[str, Any] = {
        "namespace": namespace,
        "name": name,
        "expected": "Bound",
    }
    if not res.ok:
        evidence["stderr"] = _tail(res.err)
        return classify(res), evidence
    data = json.loads(res.out)
    spec = data.get("spec") or {}
    status = data.get("status") or {}
    phase = status.get("phase") or ""
    actual_sc = spec.get("storageClassName")
    actual_cap = (status.get("capacity") or {}).get("storage") or ((spec.get("resources") or {}).get("requests") or {}).get("storage")
    evidence["actual"] = phase
    evidence["storage_class"] = actual_sc
    evidence["capacity"] = actual_cap
    ok = phase == "Bound"
    if storage_class and actual_sc != storage_class:
        evidence["expected_storage_class"] = storage_class
        ok = False
    if min_storage:
        if not actual_cap or _parse_k8s_bytes(actual_cap) < _parse_k8s_bytes(min_storage):
            evidence["min_storage"] = min_storage
            ok = False
    return (PASS if ok else FAIL), evidence


CHECKS = {
    "kubectl_resource_exists": chk_kubectl_resource_exists,
    "kubectl_jsonpath": chk_kubectl_jsonpath,
    "pod_status_ready": chk_pod_status_ready,
    "node_status_ready": chk_node_status_ready,
    "kubectl_auth_can_i": chk_kubectl_auth_can_i,
    "pod_exec_exit_zero": chk_pod_exec_exit_zero,
    "pod_exec_must_fail": chk_pod_exec_must_fail,
    "node_command_exit_zero": chk_node_command_exit_zero,
    "host_file_contains": chk_host_file_contains,
    "helm_release_state": chk_helm_release_state,
    "service_endpoints_ready": chk_service_endpoints_ready,
    "deployment_rollout_ready": chk_deployment_rollout_ready,
    "pvc_bound": chk_pvc_bound,
}


async def run_check(spec: CheckSpec, *, allow_warm_probe: bool = True) -> dict:
    """Execute one check with timeout + ERROR retries (FAIL/invalid_check never auto-retry)."""
    fn = CHECKS.get(spec.type)
    timeout = TIMEOUTS.get(spec.type, DEFAULT_TIMEOUT)
    params = normalize_params(spec.type, spec.params)
    if fn is None:
        return {"check_id": spec.id, "description": spec.description, "status": ERROR,
                "duration_ms": 0,
                "evidence": {"error": f"unknown check type: {spec.type}", "invalid_check": True},
                "hint": None}

    started = time.perf_counter()
    status, evidence = ERROR, {"error": "not executed"}
    for attempt in range(3):  # 1 run + 2 retries only for transient infra ERROR
        try:
            if spec.type in ("pod_exec_exit_zero", "pod_exec_must_fail") and not allow_warm_probe:
                status, evidence = await asyncio.wait_for(
                    fn(params, allow_warm_probe=False), timeout=timeout
                )
            else:
                status, evidence = await asyncio.wait_for(fn(params), timeout=timeout)
        except asyncio.TimeoutError:
            status, evidence = ERROR, {"error": f"timeout after {timeout}s"}
        except (KeyError, TypeError, ValueError, re.error) as exc:
            # Deterministic check-definition error — do NOT retry as infra hiccup
            status = ERROR
            evidence = {"error": f"{type(exc).__name__}: {str(exc)[:200]}", "invalid_check": True}
            break
        except Exception as exc:
            status, evidence = ERROR, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        if status != ERROR or (evidence or {}).get("invalid_check"):
            break
        if attempt < 2:
            await asyncio.sleep(1)
    duration_ms = round((time.perf_counter() - started) * 1000)
    return {
        "check_id": spec.id,
        "description": spec.description,
        "status": status,
        "duration_ms": duration_ms,
        "evidence": evidence,
        "hint": spec.failure_hint if status in (FAIL, SKIP) else None,
    }


async def run_all(checks: list[CheckSpec], *, allow_warm_probe: bool | None = None) -> dict:
    """Execute checks in groups (API -> pods -> nodes), parallel per group. All-or-nothing verdict."""
    started = time.perf_counter()
    if allow_warm_probe is None:
        allow_warm_probe = not any(spec.type == "pod_exec_must_fail" for spec in checks)
    buckets: dict[int, list[int]] = {1: [], 2: [], 3: []}
    for index, spec in enumerate(checks):
        buckets[GROUP.get(spec.type, 3)].append(index)

    results: list[dict | None] = [None] * len(checks)

    async def execute() -> None:
        for group in (1, 2, 3):
            async def one(index: int) -> None:
                results[index] = await run_check(checks[index], allow_warm_probe=allow_warm_probe)

            await asyncio.gather(*(one(index) for index in buckets[group]))

    try:
        await asyncio.wait_for(execute(), timeout=90)
    except asyncio.TimeoutError:
        for index, spec in enumerate(checks):
            if results[index] is None:
                results[index] = {
                    "check_id": spec.id, "description": spec.description, "status": ERROR,
                    "duration_ms": 90000,
                    "evidence": {"error": "check run timeout (90s total)"}, "hint": None,
                }

    ordered = [r for r in results if r is not None]
    infra_error = any(
        r["status"] == ERROR and not (r.get("evidence") or {}).get("invalid_check")
        for r in ordered
    )
    all_passed = bool(ordered) and all(r["status"] == PASS for r in ordered)
    return {
        "all_passed": all_passed,
        "infra_error": infra_error,
        "results": ordered,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "ran_at": time.time(),
    }
