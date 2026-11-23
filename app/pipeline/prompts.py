"""LLM prompt templates, tier bands, and repair instructions for CKA Arena v3."""

from __future__ import annotations

import json

from app import config

BUILDER_MAX_TOKENS = 40000
REVIEW_MAX_TOKENS = 6000
NORMALIZER_MAX_TOKENS = 4000

BANDS: dict[str, dict[str, tuple[int, int]]] = {
    "exam_standard": {
        "requirements": (1, 2),
        "kinds": (0, 2),
        "namespaces": (0, 2),
        "checks": (2, 3),
        "weight": (2, 5),
        "minutes": (1, 4),
    },
    "killer_hardcore": {
        "requirements": (3, 4),
        "kinds": (2, 99),
        "namespaces": (0, 2),
        "checks": (4, 6),
        "weight": (6, 10),
        "minutes": (4, 7),
    },
    "boss_fight": {
        "requirements": (4, 6),
        "kinds": (3, 99),
        "namespaces": (0, 99),
        "checks": (6, 11),
        "weight": (11, 16),
        "minutes": (7, 12),
        "node_commands": (1, 99),
    },
}


def band_text(difficulty: str) -> str:
    band = BANDS.get(difficulty, BANDS["exam_standard"])
    axes = []
    for axis, (low, high) in band.items():
        axes.append(f"{axis}>={low}" if high >= 99 else f"{axis}={low}-{high}")
    return ", ".join(axes)


def repair_cycles_text(count: int) -> str:
    return f"repair {count}/2"


def tier_budget(difficulty: str) -> tuple[int, int]:
    if difficulty == "boss_fight":
        return 10, 5
    if difficulty == "killer_hardcore":
        return 8, 4
    return 6, 2


NORMALIZER_SYSTEM = """You normalize CKA practice requests into a strict JSON contract.
Return ONLY valid JSON with this shape:
{"domains": ["..."], "subtopics": ["..."], "difficulty": "exam_standard|killer_hardcore|boss_fight",
 "count": <int>, "constraints": ["..."]}
Allowed domains exactly: Troubleshooting; Cluster Architecture, Installation & Configuration;
Services & Networking; Workloads & Scheduling; Storage.
Convert the free-text focus hint into short English constraints (e.g. "no Helm" -> "exclude Helm").
Never invent domains outside the allowed list. Never add commentary."""

BUILDER_SYSTEM = """You are a Senior CNCF Exam Architect writing CKA 2025/2026 practice scenarios that run on a REAL kubeadm cluster.

REAL CLUSTER TOPOLOGY:
{{TOPOLOGY}}

OUTPUT CONTRACT: return ONLY one JSON object (no fences, no prose) with exactly these keys:
{"schema_version":"1.2","id":"<slug>","title":"<3-6 word imperative title>","domain":"<one allowed domain>",
 "subtopics":["..."],"difficulty":"<requested>","weight":<int>,"estimated_minutes":<number>,
 "context_command":"kubectl config use-context cka","ssh_target":null,"archetype_id":"<slot archetype>",
 "prompt":"<exam-standard English text>","copy_tokens":["..."],"docs_links":[{"label":"...","url":"https://kubernetes.io/..."}],
 "hints":["<Level 1: where/what to inspect without giving the answer>","<Level 2: relevant Kubernetes concept or API spec>"],
 "fast_solution_commands":["<short imperative CKA CLI shortcuts using kubectl ... --dry-run=client -o yaml>"],
 "setup":{"namespaces":["..."],"manifests":["<YAML string>"],"commands":["<optional setup kubectl/helm>"],"node_commands":[{"node":"node01","command":"...","backup_paths":[],"sudo":false}]},
 "checks":[{"id":"chk-...","description":"...","type":"<check type>","params":{...},"failure_hint":"..."}],
 "solution":{"manifests":["<YAML string>"],"commands":["<kubectl/helm command>"],"node_commands":[{"node":"node01","command":"...","backup_paths":[],"sudo":false}]},
 "cleanup":{"namespaces":["..."],"commands":["<optional cleanup kubectl/helm>"],"node_commands":[{"node":"node01","command":"...","backup_paths":[],"sudo":false}]},
 "reference_solution":"<short English guide>","destructive":false}

QUESTION FORMAT (must mirror killer.sh / real CKA):
<imperative title>
Task weight: <n>%
Use context: kubectl config use-context cka
<1-2 sentences of observable symptoms ONLY — NEVER leak root cause, missing field, or solution!>
Perform the following tasks:
1. <imperative task, every identifier in backticks>
...
<explicit constraints, e.g. "Do not modify ...">

RULES:
1. All user-facing text in English, exam voice: imperative, neutral, ZERO spoilers or root-cause hints in the symptom context.
2. Requested difficulty: {{DIFFICULTY}}. HARD BAND — match every axis: {{BAND}}.
3. Every critical identifier in the prompt is wrapped in backticks and listed in copy_tokens.
4. Strictly match the assigned archetype goal, required resource kinds, and subtopics in SLOT BRIEF!
5. `setup` must create a broken/incomplete environment where AT LEAST ONE check FAILS before the candidate acts.
6. `checks` test resulting cluster/node STATE, never specific commands. Every numbered task MUST have at least one corresponding check.
7. Node file changes require backup_paths; use node: controlplane for etcd/pki operations. Never run kubectl/helm inside node_commands.
8. Never create app workloads in kube-system/default/kube-public; use the assigned business namespace(s) in `setup.namespaces`.
9. Only use pinned arm64-compatible images (NEVER `:latest`): nginx:1.27-alpine, busybox:1.36, redis:7-alpine, postgres:16-alpine, alpine:3.20, httpd:2.4-alpine, curlimages/curl:8.10.1, registry.k8s.io/pause:3.10.
10. `solution` MUST be fully automated (executed by the solvability probe).
   - Never use `-f <local-file>` or heredocs `<<EOF` — put all YAML in `solution.manifests`.
   - For Helm scenarios, ALWAYS use the bundled chart `assets/helm-chart`.
   - For Kustomize scenarios using `-k`, use ONLY the bundled overlay `assets/kustomize/overlays/prod` (never external URLs or arbitrary local dirs).
   - PVC (`storageClassName`, `accessModes`, `selector`) and Pod (`spec.volumes`) are IMMUTABLE: never `kubectl patch` immutable fields — delete and recreate via `solution.manifests`!
   - Cluster-scoped resources (PV, CRD, ClusterRole, ClusterRoleBinding, StorageClass, PriorityClass, CSR, node taints/labels) MUST use unique names containing `<ns>` and be deleted in `cleanup.commands`.
11. Allowed docs_links domains ONLY: `https://kubernetes.io/...`, `https://helm.sh/...`, `https://gateway.networking.k8s.io/...`.
12. Mark destructive operations (etcd restore, kubeadm upgrade/certs, static controlplane manifests) with `"destructive": true`.
13. Allowed check types (PREFER semantic checks `service_endpoints_ready`, `deployment_rollout_ready`, `pvc_bound` over fragile jsonpath!):
    - kubectl_resource_exists {kind, name, namespace?}
    - kubectl_jsonpath {kind, name OR label_selector, namespace?, jsonpath, operator: equals|equals_int|contains|not_contains|gte|regex|len_gte|empty|not_empty|all_match, expected}
      * IMPORTANT: LIST mode (name empty + label_selector set) queries a List object — jsonpath MUST start with `{.items[*].` (e.g. `{.items[*].spec.nodeName}` with operator `all_match`, expected `node01`).
    - service_endpoints_ready {namespace, service_name, min_ready_addresses}
    - deployment_rollout_ready {namespace, name, min_ready_replicas, expected_image?}
    - pvc_bound {namespace, name, storage_class?, min_storage?}
    - pod_status_ready {namespace, label_selector, min_ready}
    - node_status_ready {node_name}
    - kubectl_auth_can_i {verb, resource, service_account, namespace, target_namespace, expected_allowed}
    - pod_exec_exit_zero {namespace, label_selector OR pod_name OR ephemeral_probe:true, command:[...], stdout_contains?}
    - pod_exec_must_fail {namespace, label_selector OR pod_name OR ephemeral_probe:true, command:[...]} (MUST embed timeout e.g. curl --max-time 5)
    - node_command_exit_zero {node, command, stdout_contains?}
    - host_file_contains {location:"host"|controlplane|node01|node02, path, regex_patterns:[...]}
    - helm_release_state {namespace, release_name, expected_status, min_revision}

ASSIGNED SLOT BRIEF:
{{SLOT_BRIEF}}

REFERENCE EXAMPLE FOR THIS DOMAIN/TIER (match structure & realism, invent fresh scenario):
{{FEW_SHOT}}"""

REVIEWER_SYSTEM = """You are a cold exam reviewer for CKA scenarios. Judge ONLY this envelope and reply with JSON:
{"verdict":"approve|patch","issues":["..."],"task_map":{"1":["chk-..."]}}
Rubric:
(1) Every numbered requirement in the prompt has at least one corresponding check in `checks` (fill `task_map` mapping each task number to check IDs), and every check corresponds to a stated task.
(2) Traps are fair — no interpretation traps or missing constraints.
(3) Checks assert resulting state, not commands.
(4) All critical identifiers appear in copy_tokens.
(5) `solution` actually resolves every check (walk through each check against the solution).
(6) English exam voice (title, symptom context, "Perform the following tasks", constraints).
(7) NO SPOILERS: the symptom paragraph before "Perform the following tasks:" MUST describe observable symptoms only — reject with "patch" if it leaks the root cause (e.g. "because selector is wrong", "because command exits") or reveals the fix!
(8) Cluster-scoped resources (PV, CRD, ClusterRole, ClusterRoleBinding, CSR, taints) MUST have cleanup steps in `cleanup.commands`.
DO NOT judge numeric band axes (requirements/kinds/namespaces/checks count, weight, estimated_minutes):
a deterministic gate already enforces the exact band and clamps scalars. Be brief and concrete."""


def _load_hard_example() -> str:
    try:
        data = json.loads(
            (config.BASE_DIR / "scenarios/seed/sn-networkpolicy-dns.json").read_text()
        )
        keep = {
            k: data[k]
            for k in (
                "id",
                "title",
                "domain",
                "difficulty",
                "weight",
                "estimated_minutes",
                "prompt",
                "copy_tokens",
                "setup",
                "checks",
                "solution",
            )
            if k in data
        }
        keep["prompt"] = keep["prompt"][:500]
        return json.dumps(keep, indent=1, ensure_ascii=False)
    except Exception:
        return ""


_HARD_EXAMPLE = _load_hard_example()

HARD_TIER_ADDENDUM = """
HARD-TIER RULES (killer_hardcore & boss_fight) — deterministic gates reject violations:
A. solution.commands may only use `-f -` (stdin). NEVER `-f <file>` (any path, including
   /tmp/...) and NEVER heredocs (`<<EOF`) — the probe has no filesystem. Only `-k assets/kustomize/...`
   is allowed for local kustomize directories. All inline YAML lives in solution.manifests.
B. `kubectl expose`/`create` fail with AlreadyExists when the object exists; prefer
   solution.manifests (kubectl apply upserts) for anything setup may already have created broken.
C. node_commands run over SSH ON the node — there is no kubectl/helm there (cluster operations
   belong in setup.commands/solution.commands). Any command touching /etc, /var/lib, /opt or
   /usr needs "sudo": true; every system file it MODIFIES must be in backup_paths (files the
   command itself creates do not). Create directories with `sudo mkdir -p`.
D. Checks must be DETERMINISTIC — no races. `kubectl_jsonpath` supports LIST mode
   (kind + label_selector, no name, jsonpath `{.items[*].field}` + operator `all_match`).
   For HTTP reachability via pod_exec, embed retries in the command itself, e.g.
   ["sh","-c","for i in $(seq 1 8); do curl -sS --max-time 3 -o /dev/null -w '%{http_code}' http://SVC.NS.svc.cluster.local | grep -q 200 && exit 0; sleep 1; done; exit 1"].
E. boss_fight: cohesive multi-layer incident in ONE stack (node fault + dependent workload + networking/storage/RBAC).
   Ensure every layer depends causally on the layers below it; no unrelated multi-namespace grab-bag!
"""

REPAIR_SYSTEM = """You are a CKA lab scenario repairer. A solvability probe failed on a real cluster.
Reply with ONLY JSON: {"solution": {...}, "checks": [...]}
Rules:
- Keep setup/prompt/title/weight unchanged (do not return them).
- Fix the SOLUTION so every check passes; if a check is genuinely wrong or racy,
  change the minimal set of checks — never weaken the intended behavior.
- solution.manifests for YAML; solution.commands only kubectl/helm with `-f -` (or `-k assets/kustomize/...`);
  node commands need sudo/backup_paths.
- For immutable fields (PVC storageClassName/accessModes/selector, Pod volumes),
  delete in solution.commands and recreate in solution.manifests.
- LIST-mode kubectl_jsonpath requires `.items[*]`.
You also receive EVERY check with its result/evidence and the live state captured
BEFORE cleanup (pods, events, logs, services, endpoints, PVCs). Walk every check against the solution."""
