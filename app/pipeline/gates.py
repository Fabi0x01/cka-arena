"""Deterministic gates, normalization, archetype-alignment, and server dry-run validation."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import time

import yaml

from app import cluster, commands, curriculum, planner
from app.models import DocLink, ScenarioEnvelope
from app.pipeline.prompts import BANDS

BLOCKLIST = (
    "rm -rf /",
    "mkfs",
    "dd if=",
    "kubeadm reset",
    "shred ",
    ":(){",
    "> /dev/sd",
    "chmod -R 777 /",
    "iptables -F",
)

DESTRUCTIVE_PATTERNS = (
    "etcdctl snapshot restore",
    "kubeadm certs renew",
    "kubeadm upgrade",
    "systemctl restart kube-apiserver",
)

IMAGE_WHITELIST = (
    "nginx", "busybox", "redis", "postgres", "alpine", "httpd",
    "curlimages/curl", "registry.k8s.io/pause", "python", "node",
    "mongo", "mysql", "traefik", "envoyproxy", "ghcr.io",
)

ALLOWED_DOC_DOMAINS = (
    "https://kubernetes.io/",
    "https://helm.sh/",
    "https://gateway.networking.k8s.io/",
    "https://gateway-api.sigs.k8s.io/",
)

RUNTIME_CHECK_TYPES = frozenset({
    "pod_status_ready",
    "pod_exec_exit_zero",
    "pod_exec_must_fail",
    "node_status_ready",
    "service_endpoints_ready",
    "deployment_rollout_ready",
})

HOST_PATH_ROOTS = (
    "/etc/kubernetes",
    "/var/lib/kubelet",
    "/etc/containerd",
    "/etc/systemd",
    "/etc/cni",
    "/opt",
    "/var/lib/etcd",
    "/tmp",
    "/home",
)

_SPOILER_PATTERNS = (
    re.compile(
        r"\bbecause\s+(?:of\s+)?(?:the\s+|its?\s+|a\s+|an\s+|wrong\s+|missing\s+|incorrect\s+)?(?:selector|container\s+command|image\s+tag|targetport|readiness\s*probe|liveness\s*probe|rolebinding|networkpolicy|port\s+mismatch|wrong\s+command|typo|missing\s+port)\b",
        re.I,
    ),
    re.compile(
        r"\bhas\s+(?:a\s+|an\s+)?(?:wrong\s+(?:selector|targetport|image|command|tag|rolebinding|mountpath)|typo\s+in|missing\s+(?:selector|label|port|volumemount))\b",
        re.I,
    ),
    re.compile(r"\b(?:run|execute)\s+`?kubectl\s+(?:patch|set\s+image|edit|taint|expose)\b", re.I),
    re.compile(r"\bmissing\s+(?:tolerations?|egress\s+rule\s+for\s+port\s+53|label)\s+is\s+the\s+cause\b", re.I),
)

_SPOILER_NAMESPACE_RE = re.compile(
    r"^(?:broken|fix|wrong|crashloop|oom|taint|rbac-fix|netpol-broken|fail|error|bad)(?:-|$)",
    re.I,
)

CLUSTER_SCOPED_MANIFEST_KINDS = frozenset({
    "persistentvolume",
    "clusterrole",
    "clusterrolebinding",
    "storageclass",
    "customresourcedefinition",
    "priorityclass",
    "certificatesigningrequest",
})


def image_allowed(image: str) -> bool:
    if image.endswith(":latest"):
        return False
    for repo in IMAGE_WHITELIST:
        if (
            image == repo
            or image.startswith(repo + ":")
            or image.startswith(repo + "/")
            or image.startswith(repo + "@sha256:")
        ):
            return True
    return False


def _references_missing_local_file(args: list[str]) -> bool:
    for index, token in enumerate(args):
        if token in ("-f", "--filename") and index + 1 < len(args):
            target = args[index + 1]
            if target in ("-", "stdin"):
                continue
            return True
        if token.startswith("--filename="):
            target = token.split("=", 1)[1]
            if target in ("-", "stdin"):
                continue
            return True
        if token in ("-k", "--kustomize") and index + 1 < len(args):
            target = args[index + 1]
            if target.startswith("assets/"):
                continue
            return True
        if token.startswith("--kustomize="):
            target = token.split("=", 1)[1]
            if target.startswith("assets/"):
                continue
            return True
    return False


def _extract_patch_payloads(tokens: list[str]) -> list[str]:
    payloads: list[str] = []
    for idx, tok in enumerate(tokens):
        if tok.startswith("-p=") and len(tok) > 3:
            payloads.append(tok[3:])
        elif tok.startswith("--patch=") and len(tok) > 8:
            payloads.append(tok[8:])
        elif tok in ("-p", "--patch") and idx + 1 < len(tokens):
            payloads.append(tokens[idx + 1])
    return payloads


def extract_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response (tolerates fences and surrounding prose)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("resposta sem objeto JSON")
    return json.loads(stripped[start:end + 1])


def enrich_defaults(env: ScenarioEnvelope, slot_plan: planner.SlotPlan | None = None) -> None:
    if slot_plan and not env.archetype_id:
        env.archetype_id = slot_plan.archetype.id
    if not env.docs_links:
        defaults = curriculum.DOMAIN_DOCS.get(env.domain, [])
        env.docs_links = [DocLink(**d) for d in defaults]


def clamp_band_scalars(env: ScenarioEnvelope) -> list[str]:
    band = BANDS.get(env.difficulty)
    changes: list[str] = []
    if not band:
        return changes
    if "weight" in band:
        low, high = band["weight"]
        if not low <= env.weight <= high:
            env.weight = max(low, min(high, env.weight))
            changes.append(f"weight→{env.weight}")
    if "minutes" in band:
        low, high = band["minutes"]
        minutes = int(round(env.estimated_minutes))
        if not low <= minutes <= high:
            env.estimated_minutes = float(max(low, min(high, minutes)))
            changes.append(f"minutes→{int(env.estimated_minutes)}")
    return changes


def host_path_errors(env: ScenarioEnvelope) -> list[str]:
    errors: list[str] = []
    for check in env.checks:
        if check.type != "host_file_contains":
            continue
        path = str((check.params or {}).get("path") or "")
        if not path.startswith("/"):
            errors.append(f"check {check.id}: host_file_contains path deve ser absoluto: {path[:60]}")
        elif not any(path == root or path.startswith(root + "/") for root in HOST_PATH_ROOTS):
            errors.append(
                f"check {check.id}: host_file_contains fora dos locais válidos "
                f"({', '.join(HOST_PATH_ROOTS)}): {path[:60]}"
            )
    return errors


def namespace_errors(env: ScenarioEnvelope) -> list[str]:
    declared = set(env.setup.namespaces)
    used: set[str] = set()
    for text in list(env.setup.manifests) + list(env.solution.manifests):
        try:
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict):
                    ns = (doc.get("metadata") or {}).get("namespace")
                    if ns:
                        used.add(str(ns))
        except yaml.YAMLError:
            continue
    missing = sorted(used - declared)
    if missing:
        return [f"namespaces usados em manifests mas ausentes de setup.namespaces: {missing}"]
    return []


def consistency_errors(env: ScenarioEnvelope) -> list[str]:
    solution_blob = "\n".join(
        list(env.solution.manifests)
        + list(env.solution.commands)
        + [nc.command for nc in env.solution.node_commands]
    )
    setup_blob = "\n".join(
        list(env.setup.manifests)
        + list(env.setup.commands)
        + [nc.command for nc in env.setup.node_commands]
    )
    errors: list[str] = []
    for check in env.checks:
        if check.type not in (
            "kubectl_resource_exists",
            "kubectl_jsonpath",
            "service_endpoints_ready",
            "deployment_rollout_ready",
            "pvc_bound",
        ):
            continue
        params = dict(check.params)
        name = str(
            params.get("name")
            or params.get("service_name")
            or params.get("deployment")
            or params.get("pvc")
            or ""
        )
        if not name:
            continue
        if name not in solution_blob and name not in setup_blob:
            errors.append(
                f"check {check.id} espera {params.get('kind', params.get('resource', check.type))}/"
                f"{name}, mas nem setup nem solution criam/mencionam esse objeto"
            )
    return errors


def param_errors(env: ScenarioEnvelope) -> list[str]:
    required = {
        "kubectl_resource_exists": ("kind", "name"),
        "kubectl_jsonpath": ("kind", "name", "jsonpath"),
        "pod_status_ready": ("namespace",),
        "node_status_ready": ("node_name",),
        "kubectl_auth_can_i": ("verb", "resource", "service_account", "namespace"),
        "pod_exec_exit_zero": ("namespace", "command"),
        "pod_exec_must_fail": ("namespace", "command"),
        "node_command_exit_zero": ("node", "command"),
        "host_file_contains": ("location", "path"),
        "helm_release_state": ("namespace", "release_name"),
        "service_endpoints_ready": ("namespace", "service_name"),
        "deployment_rollout_ready": ("namespace", "name"),
        "pvc_bound": ("namespace", "name"),
    }
    errors: list[str] = []
    for check in env.checks:
        params = dict(check.params or {})
        if "kind" not in params and "resource" in params:
            params["kind"] = params["resource"]
        if check.type == "service_endpoints_ready" and "service_name" not in params:
            params["service_name"] = params.get("name") or params.get("service")
        if check.type == "deployment_rollout_ready" and "name" not in params and params.get("deployment"):
            params["name"] = params["deployment"]
        if check.type == "pvc_bound" and "name" not in params and params.get("pvc"):
            params["name"] = params["pvc"]

        if check.type in ("pod_exec_exit_zero", "pod_exec_must_fail"):
            if not any(key in params for key in ("label_selector", "selector", "pod", "pod_name", "name", "ephemeral_probe")):
                errors.append(f"check {check.id}: sem label_selector/pod/ephemeral_probe")
            if check.type == "pod_exec_must_fail":
                cmd = params.get("command") or ""
                cmd_str = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
                if not any(flag in cmd_str for flag in ("--max-time", "-m ", "timeout ", "-w ", "-W ")):
                    errors.append(f"check {check.id}: pod_exec_must_fail must embed an explicit command timeout (--max-time / timeout)")
        if check.type == "pod_status_ready" and "min_ready" not in params and "ready" in params:
            params["min_ready"] = params["ready"]

        required_keys = list(required.get(check.type, ()))
        if check.type == "kubectl_auth_can_i":
            required_keys = ["verb", "resource"]
            if not params.get("service_account") and not params.get("user"):
                errors.append(f"check {check.id}: kubectl_auth_can_i precisa de service_account ou user")
            if params.get("service_account") and not params.get("namespace"):
                required_keys.append("namespace")
            if not params.get("cluster_scoped") and not params.get("target_namespace") and not params.get("namespace"):
                errors.append(f"check {check.id}: kubectl_auth_can_i precisa de namespace ou cluster_scoped=true")
        if check.type == "kubectl_jsonpath":
            jsonpath = str(params.get("jsonpath") or "").strip()
            if jsonpath and not jsonpath.startswith("{"):
                jsonpath = "{" + jsonpath + "}"
            if params.get("label_selector") or params.get("selector"):
                required_keys.remove("name")
                if jsonpath and "items" not in jsonpath and not str(params.get("name") or "").strip():
                    errors.append(
                        f"check {check.id}: LIST-mode kubectl_jsonpath (with label_selector and no name) "
                        f"must iterate `.items[*]` (got {jsonpath})"
                    )
            elif not str(params.get("name") or "").strip():
                errors.append(f"check {check.id}: kubectl_jsonpath precisa de name ou label_selector")
                continue
        missing = [key for key in required_keys if key not in params or params[key] in (None, "")]
        if missing:
            errors.append(f"check {check.id}: params faltando {missing}")
    return errors


def tier_band_errors(env: ScenarioEnvelope) -> list[str]:
    band = BANDS[env.difficulty]
    manifest_kinds: set[str] = set()
    namespaces: set[str] = set(env.setup.namespaces)
    for text in list(env.setup.manifests) + list(env.solution.manifests):
        try:
            for doc in yaml.safe_load_all(text):
                if not isinstance(doc, dict):
                    continue
                manifest_kinds.add(doc.get("kind", ""))
                ns = (doc.get("metadata") or {}).get("namespace")
                if ns:
                    namespaces.add(ns)
        except yaml.YAMLError:
            continue
    measured = {
        "requirements": len(re.findall(r"(?m)^\s*\d+\.\s+\S", env.prompt)),
        "kinds": len({kind for kind in manifest_kinds if kind}),
        "namespaces": len(namespaces),
        "checks": len(env.checks),
        "weight": env.weight,
        "minutes": int(round(env.estimated_minutes)),
    }
    if env.setup.node_commands:
        measured["node_commands"] = len(env.setup.node_commands)

    fails: list[str] = []
    for axis, (low, high) in band.items():
        value = measured.get(axis)
        if value is None:
            if axis == "node_commands" and env.difficulty == "boss_fight":
                fails.append("boss_fight sem node_commands (falha de infra de nó)")
            continue
        if not (low <= value <= high):
            fails.append(f"{axis}={value} fora da banda {low}–{high}")
    if len(fails) >= 2:
        return ["tier band: " + " | ".join(fails)]
    return []


def archetype_alignment_errors(
    env: ScenarioEnvelope, archetype: curriculum.Archetype | None = None
) -> list[str]:
    """Verify the generated scenario actually fulfills its assigned curriculum archetype."""
    arch = archetype or curriculum.ARCHETYPES_BY_ID.get(env.archetype_id or "")
    if not arch:
        return []
    errors: list[str] = []
    kinds: set[str] = set()
    for text in list(env.setup.manifests) + list(env.solution.manifests):
        try:
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict) and doc.get("kind"):
                    kinds.add(str(doc["kind"]).lower())
        except yaml.YAMLError:
            pass
    for c in env.checks:
        k = (c.params or {}).get("kind") or (c.params or {}).get("resource")
        if k:
            kinds.add(str(k).lower())

    blob = "\n".join([
        env.prompt,
        *env.setup.manifests,
        *env.solution.manifests,
        *env.setup.commands,
        *env.solution.commands,
        *(nc.command for nc in env.setup.node_commands),
        *(nc.command for nc in env.solution.node_commands),
        *(json.dumps(c.params) for c in env.checks),
    ]).lower()

    if arch.required_kinds:
        if not any(req.lower() in kinds or req.lower() in blob for req in arch.required_kinds):
            errors.append(
                f"archetype {arch.id}: esperado recurso {list(arch.required_kinds)} ausente em manifests/checks"
            )
    if arch.required_check_types:
        used_types = {c.type for c in env.checks}
        if not any(rt in used_types for rt in arch.required_check_types):
            errors.append(
                f"archetype {arch.id}: esperado ao menos um check do tipo {list(arch.required_check_types)}"
            )
    if arch.required_keywords:
        if not any(kw.lower() in blob for kw in arch.required_keywords):
            errors.append(
                f"archetype {arch.id}: tópico/keyword esperado ausente ({list(arch.required_keywords)})"
            )
    return errors


async def wait_namespace_gone(namespace: str, timeout_s: float = 40) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        res = await cluster.kubectl(
            ["get", "namespace", namespace, "-o", "jsonpath={.status.phase}"], timeout=10
        )
        if not res.ok or (res.out or "").strip() != "Terminating":
            return
        await asyncio.sleep(2)


async def validate_gates(
    env: ScenarioEnvelope,
    *,
    archetype: curriculum.Archetype | None = None,
    require_pedagogy: bool = False,
) -> list[str]:
    errors: list[str] = []

    def parse_all(blocks: list[str], label: str) -> list[dict]:
        docs: list[dict] = []
        for text in blocks:
            try:
                for doc in yaml.safe_load_all(text):
                    if doc is not None:
                        docs.append(doc)
            except yaml.YAMLError as exc:
                errors.append(f"{label}: YAML inválido ({str(exc)[:120]})")
        return docs

    parse_all(env.setup.manifests, "setup")
    parse_all(env.solution.manifests, "solution")

    contents = list(env.setup.manifests) + list(env.solution.manifests)
    contents += list(env.setup.commands) + list(env.solution.commands)
    contents += list(env.cleanup.commands) + list(env.cleanup.kubectl_commands)
    contents += [nc.command for nc in env.setup.node_commands]
    contents += [nc.command for nc in env.solution.node_commands]
    contents += [nc.command for nc in env.cleanup.node_commands]
    blob = "\n".join(contents)
    lowered = blob.lower()
    for pattern in BLOCKLIST:
        if pattern in lowered:
            errors.append(f"comando perigoso bloqueado: {pattern}")
    destructive_ops = [p for p in DESTRUCTIVE_PATTERNS if p in lowered]
    if destructive_ops and not env.destructive:
        errors.append(
            "operação destrutiva sem flag destructive: " + ", ".join(sorted(set(destructive_ops)))
        )

    images = re.findall(r"image:\s*[\"']?([^\s\"']+)", blob)
    for image in images:
        if image.endswith(":latest"):
            errors.append(f"imagem sem pin de versão: {image}")
        elif not image_allowed(image):
            errors.append(f"imagem fora da whitelist arm64: {image}")

    for raw in list(env.solution.commands) + list(env.setup.commands):
        if "<<" in raw:
            errors.append(f"comando com heredoc não é suportado (use manifests): {raw[:70]}")

    for raw in env.solution.commands:
        tokens = shlex.split(raw)
        if _references_missing_local_file(tokens):
            errors.append(
                f"solução referencia arquivo local inexistente: {raw[:80]} (use solution.manifests)"
            )
        if not commands.tool_allowed(raw):
            errors.append(f"comando não permitido no solution: {raw[:60]} (kubectl/helm)")
        for payload in _extract_patch_payloads(tokens):
            try:
                json.loads(payload)
            except ValueError as exc:
                errors.append(f"JSON inválido em `-p` de solution.commands: {str(exc)[:100]}")
        low_cmd = raw.lower()
        if " patch " in f" {low_cmd} ":
            if (" pvc " in low_cmd or " persistentvolumeclaim " in low_cmd) and any(
                f in low_cmd for f in ("storageclassname", "accessmodes", "selector", "volumename")
            ):
                errors.append("PVC spec fields (storageClassName/accessModes/selector) are immutable — delete and recreate via solution.manifests")
            if " pod " in low_cmd and "volumes" in low_cmd:
                errors.append("Pod spec.volumes is immutable — delete and recreate via solution.manifests")

    for raw in env.setup.commands:
        if not commands.tool_allowed(raw):
            errors.append(f"comando não permitido no setup: {raw[:60]} (kubectl/helm)")
        for payload in _extract_patch_payloads(shlex.split(raw)):
            try:
                json.loads(payload)
            except ValueError as exc:
                errors.append(f"JSON inválido em `-p` de setup.commands: {str(exc)[:100]}")

    for raw in env.cleanup.commands:
        if not commands.tool_allowed(raw):
            errors.append(f"comando não permitido no cleanup: {raw[:60]} (kubectl/helm)")

    system_paths = ("/etc/kubernetes", "/var/lib/kubelet", "/etc/systemd", "/etc/containerd")
    mutation_start = re.compile(
        r"^\s*(sudo\s+)?(rm|mv|cp|sed\s+-i|tee|chmod|chown|mkdir|truncate|dd|install)\b"
    )
    redirect = re.compile(
        r"(>>?|tee\s+)\s*[^\n;&|]*?(/etc/kubernetes|/var/lib/kubelet|/etc/systemd|/etc/containerd)"
    )

    def mutates_system(command: str) -> bool:
        for segment in re.split(r"&&|\|\||;|\|", command):
            if any(path in segment for path in system_paths) and (
                mutation_start.search(segment) or redirect.search(segment)
            ):
                return True
        return False

    for node_cmd in list(env.setup.node_commands) + list(env.solution.node_commands):
        head = node_cmd.command.strip().split()
        if head and head[0] in ("kubectl", "helm"):
            errors.append(
                f"node_command não pode usar {head[0]} (nó sem kubeconfig; "
                f"use setup.commands): {node_cmd.command[:70]}"
            )
    for node_cmd in list(env.setup.node_commands) + list(env.solution.node_commands):
        if re.search(r"\bmkdir\b(?! -p)", node_cmd.command):
            node_cmd.command = re.sub(r"\bmkdir\b(?! -p)", "mkdir -p", node_cmd.command)
        mutates_abs = mutation_start.search(node_cmd.command) and re.search(
            r"(?<![\w~])(/etc|/var|/opt|/usr|/tmp|/srv|/run)\b", node_cmd.command
        )
        if not node_cmd.sudo and mutates_abs:
            node_cmd.sudo = True
        if node_cmd.sudo and not node_cmd.backup_paths and mutates_system(node_cmd.command):
            errors.append(f"node_command sudo que muta sistema sem backup_paths: {node_cmd.command[:70]}")

    if not env.checks:
        errors.append("envelope sem checks")
    if "perform the following tasks" not in env.prompt.lower():
        errors.append("prompt sem o bloco 'Perform the following tasks'")
    if re.search(
        r"[ãõáéíóúçêôàâÁÉÍÓÚÇÊÔÀÂ]",
        env.prompt + " ".join(c.description for c in env.checks) + (env.reference_solution or ""),
    ):
        errors.append("texto fora do inglês (diacríticos encontrados)")
    if not env.copy_tokens:
        errors.append("copy_tokens vazio")

    symptom_part = env.prompt.lower().split("perform the following tasks")[0]
    for pat in _SPOILER_PATTERNS:
        if pat.search(symptom_part):
            errors.append(f"spoiler leaked in symptom context ({pat.pattern[:40]}): describe only observable symptoms")
            break

    for link in env.docs_links:
        if not link.url.startswith(ALLOWED_DOC_DOMAINS):
            errors.append(f"docs_link url outside allowed exam docs domains: {link.url[:80]}")

    for label, manifests in (("setup", env.setup.manifests), ("solution", env.solution.manifests)):
        if not manifests:
            continue
        payload = "\n---\n".join(manifests)
        res = await cluster.kubectl(["apply", "--dry-run=server", "-f", "-"], timeout=45, stdin_data=payload)
        if not res.ok:
            stderr = (res.err or res.out).strip()
            if "being terminated" in stderr:
                for namespace in env.setup.namespaces:
                    await wait_namespace_gone(namespace)
                res = await cluster.kubectl(["apply", "--dry-run=server", "-f", "-"], timeout=45, stdin_data=payload)
                stderr = (res.err or res.out).strip()
            if not res.ok and "not found" not in stderr.lower():
                errors.append(f"dry-run server rejeitou {label} manifests: {stderr[:250]}")

    errors.extend(param_errors(env))
    errors.extend(host_path_errors(env))
    errors.extend(consistency_errors(env))
    errors.extend(namespace_errors(env))
    errors.extend(neutral_namespace_errors(env))
    errors.extend(boss_fight_fault_errors(env))
    errors.extend(etcd_snapshot_check_errors(env))
    errors.extend(cluster_cleanup_errors(env))
    if require_pedagogy:
        errors.extend(pedagogy_errors(env))
    errors.extend(tier_band_errors(env))
    errors.extend(archetype_alignment_errors(env, archetype))
    return errors


def neutral_namespace_errors(env: ScenarioEnvelope) -> list[str]:
    errors: list[str] = []
    for ns in env.setup.namespaces:
        if ns.startswith("cka-gen"):
            continue
        if _SPOILER_NAMESPACE_RE.match(ns):
            errors.append(
                f"namespace spoiler não-neutro '{ns}': use namespace neutro de negócio (ex: checkout, billing, orders)"
            )
    return errors


def boss_fight_fault_errors(env: ScenarioEnvelope) -> list[str]:
    if env.difficulty != "boss_fight":
        return []
    real_faults = []
    for nc in env.setup.node_commands:
        cmd = (nc.command or "").strip()
        if cmd and cmd not in ("true", ":") and not re.fullmatch(r"echo\b.*", cmd):
            real_faults.append(cmd)
    if not real_faults:
        return [
            "boss_fight requer ao menos 1 falha real em setup.node_commands (ex: stop kubelet, manifest estático, config no nó)"
        ]
    return []


def etcd_snapshot_check_errors(env: ScenarioEnvelope) -> list[str]:
    errors: list[str] = []
    for check in env.checks:
        if check.type == "host_file_contains":
            path = str((check.params or {}).get("path") or "").lower()
            pats = [str(p) for p in ((check.params or {}).get("regex_patterns") or [])]
            if ("etcd" in path or path.endswith(".db")) and any(p in ("(?s).+", ".+", ".*") for p in pats):
                errors.append(
                    f"check {check.id}: snapshot etcd não deve usar regex trivial '{pats[0]}' — use node_command_exit_zero com etcdutl/etcdctl snapshot status"
                )
    return errors


def cluster_cleanup_errors(env: ScenarioEnvelope) -> list[str]:
    created_cluster_kinds: set[str] = set()
    for text in list(env.setup.manifests) + list(env.solution.manifests):
        try:
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict):
                    kind = str(doc.get("kind") or "").lower()
                    if kind in CLUSTER_SCOPED_MANIFEST_KINDS:
                        created_cluster_kinds.add(kind)
        except yaml.YAMLError:
            continue
    if not created_cluster_kinds:
        return []
    has_cleanup = bool(env.cleanup.commands or env.cleanup.kubectl_commands)
    manifests_blob = "\n".join(env.setup.manifests)
    has_label_teardown = "cka-arena/scenario" in manifests_blob
    if not has_cleanup and not has_label_teardown:
        return [
            f"recursos cluster-scoped {sorted(created_cluster_kinds)} exigem remoção explícita em cleanup.commands"
        ]
    return []


def pedagogy_errors(env: ScenarioEnvelope) -> list[str]:
    errors: list[str] = []
    if len(env.hints) < 2 or any(not str(h).strip() for h in env.hints[:2]):
        errors.append("cenário v1.2 requer ao menos 2 hints progressivos sem spoilers")
    if not env.fast_solution_commands or not any(str(c).strip() for c in env.fast_solution_commands):
        errors.append("cenário v1.2 requer ao menos 1 fast_solution_commands real")
    return errors
