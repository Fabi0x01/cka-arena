# Scenario Specification & LLM Contract (`ScenarioEnvelope`)

The LLM in **CKA Arena** plays a strict role: **architect and generator of lab/exam scenarios**. It never delivers the answer during solving, and its output goes through a rigid pipeline of parsing, security guardrails, real application to the cluster, and a sanity check before reaching the study screen. The multi-stage orchestration (**A** Normalizer → **B** Builder → **C** Reviewer → **D** Gates → **E** Prove-out with Solvability Probe), the question bank, the exam-weight draw, and the formal evaluation contract (PASS/FAIL/SKIP/ERROR) are specified in [`LLM_PIPELINE_SPEC.md`](./LLM_PIPELINE_SPEC.md).

> **Reference document.** The living contract is the Pydantic model in `app/models.py` and the gates in `app/pipeline/gates.py`; the actual prompt (in English) is in `app/pipeline/prompts.py`. Where they diverge, the code prevails.

---

## 1. Strict JSON Contract (`ScenarioEnvelope v1.2`)

The LLM must return **exclusively a valid JSON object** following this schema (validated via `Pydantic` in `app/models.py`; the model's fields and types take precedence over the example). Abbreviated example — manifests cut with `...` — based on the seed `scenarios/seed/sn-networkpolicy-dns.json`, which is the complete reference:

```json
{
  "schema_version": "1.2",
  "id": "scn-netpol-dns-01",
  "title": "Allow Selected Traffic Through Default Deny",
  "domain": "Services & Networking",
  "subtopics": ["NetworkPolicy", "egress", "DNS", "default-deny"],
  "difficulty": "killer_hardcore",
  "weight": 7,
  "estimated_minutes": 6,
  "context_command": "kubectl config use-context cka",
  "ssh_target": null,
  "archetype_id": "sn-networkpolicy-dns",
  "prompt": "Allow Selected Traffic Through Default Deny\nTask weight: 7%\nUse context: kubectl config use-context cka\n\nNamespace `cka-netpol` has a `default-deny` NetworkPolicy that blocks all ingress and egress. The Pod `client` must reach `api-svc` (backing Pods labeled `app=api` on port `80`) and must still resolve cluster DNS, while the Pod `intruder` must remain unable to reach the API.\n\nPerform the following tasks:\n1. Create a NetworkPolicy named `allow-client-api` that allows `client` to reach the `api` Pods on port `80`.\n2. Allow DNS egress from `client` to the `kube-system` namespace on UDP and TCP port `53`.\n3. Keep `intruder` blocked from reaching the API.",
  "copy_tokens": ["cka-netpol", "default-deny", "allow-client-api", "client", "api-svc", "app=api", "intruder", "53"],
  "docs_links": [
    {"label": "Network Policies", "url": "https://kubernetes.io/docs/concepts/services-networking/network-policies/"}
  ],
  "hints": [
    "Inspect existing NetworkPolicies in `cka-netpol` (`k -n cka-netpol describe netpol`) and check both Ingress and Egress isolation.",
    "Allow TCP port 80 between the required client/backend pods AND allow UDP/TCP port 53 egress so CoreDNS resolution succeeds."
  ],
  "fast_solution_commands": ["k -n cka-netpol get netpol,pods --show-labels"],
  "setup": {
    "namespaces": ["cka-netpol"],
    "manifests": [
      "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: default-deny\n  namespace: cka-netpol\nspec:\n  podSelector: {}\n  policyTypes:\n  - Ingress\n  - Egress\n",
      "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n  namespace: cka-netpol\n...",
      "apiVersion: v1\nkind: Service\nmetadata:\n  name: api-svc\n  namespace: cka-netpol\n...",
      "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: client\n  namespace: cka-netpol\n...",
      "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: intruder\n  namespace: cka-netpol\n..."
    ],
    "commands": [],
    "node_commands": []
  },
  "checks": [
    {
      "id": "chk-client-http",
      "description": "`client` can reach `api-svc` with HTTP 200",
      "type": "pod_exec_exit_zero",
      "params": {
        "namespace": "cka-netpol",
        "label_selector": "app=client",
        "command": ["curl", "-sS", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}", "http://api-svc.cka-netpol.svc.cluster.local"],
        "stdout_contains": "200"
      },
      "failure_hint": "Allow ingress to app=api from app=client on port 80 and egress from client to the API.",
      "weight_ratio": 1.0
    },
    {
      "id": "chk-client-dns",
      "description": "`client` can resolve `api-svc` through cluster DNS",
      "type": "pod_exec_exit_zero",
      "params": {
        "namespace": "cka-netpol",
        "label_selector": "app=client",
        "command": ["sh", "-c", "nslookup api-svc.cka-netpol.svc.cluster.local | grep -q Address"]
      },
      "failure_hint": "Allow egress from client to kube-system on UDP/TCP 53.",
      "weight_ratio": 1.0
    },
    {
      "id": "chk-policy-exists",
      "description": "NetworkPolicy `allow-client-api` exists",
      "type": "kubectl_resource_exists",
      "params": {"kind": "networkpolicy", "name": "allow-client-api", "namespace": "cka-netpol"},
      "failure_hint": "Create the policy with exactly that name.",
      "weight_ratio": 1.0
    },
    {
      "id": "chk-intruder-denied",
      "description": "`intruder` cannot reach the API",
      "type": "pod_exec_must_fail",
      "params": {
        "namespace": "cka-netpol",
        "label_selector": "app=intruder",
        "command": ["curl", "-sS", "--max-time", "5", "http://api-svc.cka-netpol.svc.cluster.local"]
      },
      "failure_hint": "Do not allow app=intruder — the default deny must keep it blocked.",
      "weight_ratio": 1.0
    }
  ],
  "solution": {
    "manifests": [
      "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: allow-client-api\n  namespace: cka-netpol\n...",
      "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: allow-client-dns\n  namespace: cka-netpol\n..."
    ],
    "commands": [],
    "node_commands": []
  },
  "cleanup": {"namespaces": ["cka-netpol"], "commands": [], "node_commands": []},
  "reference_solution": "Add the allow policies alongside the default deny:\n- `allow-client-api`: podSelector `app=api`, ingress from `app=client` on port 80\n- `allow-client-dns`: podSelector `app=client`, egress to `kube-system` on UDP/TCP 53 and to `app=api` on port 80",
  "destructive": false
}
```

### 1.1 Envelope v1.1 Extensions (pipeline + bank)

- **`solution` (mandatory block):** YAML manifests and/or commands that solve the scenario in an **automated** way (applicable via `kubectl apply`/`exec` without a human in the loop). It is the input of the **Solvability Probe** (Stage E): the platform applies the `solution` to an exam clone and requires 100% of the checks to be `PASS` **before** the question enters the bank — eliminates unsolvable questions. Didactic prose remains in `reference_solution`.
- **Immutability after publication:** once published to the bank (`bank_questions.state = published`), the envelope no longer changes (`envelope_hash`); corrections generate a new version (`supersedes_question_id`) and the old one is retired.
- **Semantic dedup:** fingerprint of `(domain, sorted subtopics, normalized title, hash of the setup manifests)` — collision with a `published` question discards the new one (the bank doesn't fill up with clones).
- **`destructive` (boolean flag, default `false` — decision D2):** mandatory for every scenario whose solution changes global cluster state (`etcdctl snapshot restore`, `kubeadm certs renew`/`upgrade`, apiserver restart). Gate D rejects undeclared destructive operations; `destructive: true` scenarios stay out of Practice by default (they go into `mock_exam`, or with explicit opt-in via `allow_destructive`) and a session containing them ends with **L2 (clean reset)**, because state cannot be restored via L0/L1.
- **`hints` and `fast_solution_commands` (v1.2):** at least 2 progressive hints without spoilers (level 1: where to inspect; level 2: relevant concept or spec) and imperative shortcuts for the exam shell — they feed the Hint Drawer and the Speed Coach.
- **`archetype_id`:** the curriculum archetype (`app/curriculum.py`) the question belongs to — feeds the Skill Tree, spaced repetition, and the Slot Planner.
- **`checks[].weight_ratio`:** relative weight of each check in the question's partial credit (mock exams).
- **`setup.commands`, `solution.node_commands` and `cleanup.commands`:** complete the original contract, which only provided `manifests`, `setup.node_commands` and the legacy `cleanup.kubectl_commands` (still accepted).

### 1.2 Exact Exam Format (`prompt` in English — killer.sh / PSI Bridge anatomy)

> Decision (Revision 3): **the system is 100% English** — the CKA exam is in English and reading tasks in English is part of the training. The `prompt` field follows the anatomy of the real exam, mirroring the official simulator [killer.sh](https://killer.sh/cka) (included with the exam purchase) and the PSI Bridge delivery:

```text
Fix Node & Scale Deployment                 ← short imperative title (3–6 words)
Task weight: 8%                            ← the question's simulated weight
Use context: kubectl config use-context cka← always present (used to be context_command)

A Deployment `web-api` in namespace `prod-checkout` is running only 1 of its 3
desired replicas.                            ← context: 1–2 sentences in the present,
                                              observable symptoms — NEVER the cause
                                              nor the fix
Perform the following tasks:
1. Restore the `kubelet` service on `node01` until the node reports `Ready`.
2. Scale `web-api` to `3` replicas in `prod-checkout`.
3. Pin all `web-api` pods to `node01` using `nodeSelector`.

Do not modify any resource outside the mentioned namespaces.   ← constraints
```

**Exam voice (mandatory):** direct imperative (`Create`, `Scale`, `Fix`, `Save`, `Copy`); neutral, with no solution hints and no justifications; every critical identifier in `backticks` (becomes a Copy-Pill); no mention of the checks; clear technical English; explicit restrictions (`Do not modify/delete ...`, target namespace, naming, output paths under `/opt/...`).

---

## 2. Supported Deterministic Check Catalog (`validator.py`)

The user is never evaluated by an LLM when clicking **Check** — verification must be **100% deterministic, fast (< 5s total), and impartial**, like the real exam's evaluation engine. The formal semantics — status `PASS`/`FAIL`/`SKIP`/`ERROR`, retry policy (FAIL never re-runs on its own; ERROR does), per-question *all-or-nothing* verdict, per-item evidence, and settle window — are contracted in `LLM_PIPELINE_SPEC.md` §5.

| `type` | What it verifies | Parameters (`params`) | Typical CKA use |
| :--- | :--- | :--- | :--- |
| `kubectl_resource_exists` | Existence of any K8s API object (`Deployment`, `NetworkPolicy`, `HTTPRoute`, `PVC`, `Role`, etc.) | `kind`, `name`, `namespace` (optional) | Confirm resource creation and exact name. |
| `kubectl_jsonpath` | Compares a JSONPath-extracted value against the expectation (`equals`, `equals_int`, `contains`, `not_contains`, `gte`, `regex`, `len_gte`, `empty`, `not_empty`, `all_match`) | `kind`, `name` **or** `label_selector`, `namespace`, `jsonpath`, `operator`, `expected` | Verify `replicas`, `image`, `storageClassName`, `tolerations`, `serviceAccountName`, `accessModes`, `type: NodePort`. In LIST mode (no `name`, with `label_selector`) the jsonpath starts at `{.items[*].…}`. |
| `pod_status_ready` | Confirms that at least `min_ready` pods matching the selector are `Running` and `Ready=True` | `namespace`, `label_selector`, `min_ready` | Validate that pods left `Pending`/`CrashLoopBackOff`. |
| `node_status_ready` | Confirms the specified node has condition `Ready=True` | `node_name` (`controlplane`, `node01`, `node02`) | `kubelet` troubleshooting or node in `NotReady` scenarios. |
| `kubectl_auth_can_i` | Runs `kubectl auth can-i <verb> <resource> --as=system:serviceaccount:<ns>:<sa>` | `service_account`, `namespace`, `verb`, `resource`, `target_namespace`, `expected_allowed` (`true`/`false`) | RBAC questions (`Role`, `ClusterRole`, `RoleBinding`). |
| `pod_exec_exit_zero` | Runs a command inside a live pod (or an ephemeral `curlimages/curl` / `busybox` pod) and validates exit code `0` plus optional `stdout_contains` | `namespace`, `label_selector` (or `ephemeral_probe: true`), `command`, `stdout_contains` | Test real pod-to-pod connectivity, Service DNS, `NetworkPolicy` (allow what must pass and **deny what must not**), `HTTPRoute`/`Ingress`. |
| `pod_exec_must_fail` | Ensures a connectivity command fails (timeout/exit != 0) | `namespace`, `label_selector`, `command` | Mandatory negative check in `NetworkPolicy` (confirm `frontend` **cannot** reach `postgres` directly). |
| `node_command_exit_zero` | Runs a command on the specified node (SSH on Multipass, `docker exec` on kind) and checks exit code `0` / `stdout_contains` | `node`, `command`, `stdout_contains` | Verify `systemctl is-active kubelet`, static files, or an `etcd` backup file saved to `/opt/backup/etcd.db`. |
| `host_file_contains` | Checks a file saved on the host or node (e.g. output of `kubectl get ... > /tmp/result.txt`) | `location` (`host` \| `controlplane` \| `node01` \| `node02`), `path`, `regex_patterns` | Classic CKA questions asking to save sorted node/pod names to a specific file. |
| `helm_release_state` | Checks via `helm list -n <ns> -o json` the status `deployed`, chart, and version/revision | `namespace`, `release_name`, `expected_status`, `min_revision` | Helm questions (install, upgrade, rollback). |
| `service_endpoints_ready` | At least `min_ready_addresses` ready endpoints behind the Service (via `EndpointSlice`, with fallback to `Endpoints`) | `namespace`, `service_name`, `min_ready_addresses` | Validate Services without depending on `jsonpath` over IPs. |
| `deployment_rollout_ready` | Deployment with completed rollout and `min_ready_replicas` ready (optionally with the expected image) | `namespace`, `name`, `min_ready_replicas`, `expected_image` | Validate scaling, image correctness, and rollouts. |
| `pvc_bound` | PVC in `Bound` phase, optionally with minimum StorageClass and capacity | `namespace`, `name`, `storage_class`, `min_storage` | Validate PVC binding and dynamic StorageClass. |

---

## 3. Guardrails & Self-Repair Loop (`Self-Healing Pipeline`)

LLMs occasionally hallucinate obsolete APIs (e.g. `extensions/v1beta1`), image names that don't exist on `arm64`, or produce a scenario whose `setup` fails or whose `checks` are born passing. To guarantee maximum reliability:

### Deterministic Gates (Stages D + E.1 of Pipeline A→E)

> The full pipeline has 5 stages — **A** Normalizer · **B** Builder · **C** Reviewer (LLM agents; B uses the main model, A/C use flash) · **D** code gates below (items 1–3) · **E** prove-out on the cluster (item 4: sanity + **Solvability Probe**: applies the `solution` and requires 100% PASS) — orchestrated **without an agent framework** (decision grounded in `LLM_PIPELINE_SPEC.md` §1). Item 5 is the self-repair loop that returns the exact error to the Builder (≤ 2 retries).

1. **Schema & Syntax Gate:**
   - All strings in `setup.manifests` and `solution.manifests` go through `yaml.safe_load_all()`.
   - Image whitelist (`app/pipeline/gates.py`): only known repositories and pinned tags; the lab may be `arm64` or `amd64`, so use multi-arch images. Prompt suggestions: `nginx:1.27-alpine`, `busybox:1.36`, `redis:7-alpine`, `postgres:16-alpine`, `alpine:3.20`, `httpd:2.4-alpine`, `curlimages/curl:8.10.1`, `registry.k8s.io/pause:3.10`.
2. **Security Blocklist Gate:**
   - Rejects SSH commands without a declared `backup_paths` when they touch system directories.
   - **Destructiveness declaration (D2):** operations like `etcdctl snapshot restore`, `kubeadm certs renew/upgrade` or restarting the `kube-apiserver` only pass with `destructive: true` declared; without the flag, the envelope is rejected with an explicit error.
   - Rejects dangerous commands (`rm -rf /`, `kubeadm reset`, changes outside `/etc/kubernetes`, `/var/lib/kubelet`, `/opt/cka`, `/tmp`).
3. **Dry-Run Server Gate:**
   - When the `kube-apiserver` is not the target of the breakage, runs `kubectl apply --dry-run=server -f -` on the `setup` manifests to ensure API `v1.37.2` accepts exactly those fields (`apiVersion`, `spec`).
4. **Apply + Initial Fail Sanity Check:**
   - Applies the `setup` to the cluster.
   - Runs all `checks` immediately after the `setup`:
     - **Golden Rule:** At least 1 check **MUST fail** before the user starts! If all checks already return `PASS` at instant zero, the scenario is poorly formulated and is discarded/regenerated automatically.
5. **Self-Repair with Feedback (Max 2 retries):**
   - If stages 1, 3 or 4 fail, the backend immediately rolls back the partial scenario and sends the exact error (`kubectl` `stderr` or the Sanity Check reason) back to the LLM, asking only for the corrected `ScenarioEnvelope`.

---

## 4. LLM System Prompt Rules

> The authoritative prompt (in English) is `BUILDER_SYSTEM` in `app/pipeline/prompts.py`, assembled with the placeholders `{{TOPOLOGY}}`, `{{DIFFICULTY}}`, `{{BAND}}`, `{{SLOT_BRIEF}}` and `{{FEW_SHOT}}`. The block below is a reference rendering of the rules, not the text sent to the model.

```text
You are a Senior CNCF Exam Architect (question author in the style of Killer.sh and the official CKA).
Your mission is to generate original hands-on scenarios to be executed on a REAL kubeadm Kubernetes cluster.

CANDIDATE CLUSTER REAL TOPOLOGY:
- Kubernetes version: <version detected at runtime>
- Node architecture: <architecture> — USE MULTI-ARCH IMAGES ONLY!
- Runtime: containerd
- CNI: <lab CNI>
- Available nodes:
  1. controlplane (role: control-plane, IP: <controlplane-ip>)
  2. node01 (role: worker, IP: <node01-ip>)
  3. node02 (role: worker, IP: <node02-ip>)
- kubectl context: cka
- Add-ons installed dynamically: {{INSTALLED_ADDONS}}

STRICT SCENARIO CONSTRUCTION RULES:
1. **All user-facing text in English (exam voice):** `prompt`, check `description`, `failure_hint`, `docs_links` labels and `reference_solution` must be in clear, concise technical English — imperative, neutral, zero solution hints — mirroring the real CKA / killer.sh question voice (anatomy in §1.2). Use Kubernetes resource terms verbatim (`Pod`, `Deployment`, `NetworkPolicy`).
2. Requested difficulty: {{DIFFICULTY}} — follow the measurable band of §5 exactly (requirements, resource kinds, traps, causal chain, checks, time target, weight); the Reviewer stage will reject scenarios outside the band:
   - `exam_standard`: 1–2 requirements, 1 namespace, no deliberate traps, single-step fix (target ≤ 4 min, weight 2–5).
   - `killer_hardcore`: 3–4 requirements, ≥ 1 fair trap (incompatible label selector, NetworkPolicy egress breaking DNS port 53, node taint, pre-existing broken manifest), diagnose-then-repair chain (target ≤ 7 min, weight 6–10).
   - `boss_fight`: multi-layer incident combining node infrastructure failure (kubelet/static pod/systemd via SSH) + dependent workload/network recovery, ≥ 2 traps, causal chain ≥ 3 (target ≤ 12 min, weight 11–16).
3. Every critical identifier in the question prompt (namespaces, resource names, ports, labels, file paths) MUST be in backticks (`example`) and listed in `copy_tokens`.
4. `setup` must create a realistic (or deliberately broken) environment guaranteeing the `checks` FAIL before the candidate intervenes.
5. The `checks` must test the RESULTING STATE on the cluster or node, accepting any valid form the candidate uses to solve (imperative or declarative). Never require the candidate to use a specific command when the API state is equivalent.
6. Every command in `setup.node_commands` that modifies node files MUST list the original paths in `backup_paths` for automatic restoration.
7. Never use the `kube-system`, `default`, `kube-public` namespaces to create new application workloads; use dedicated thematic namespaces (e.g. `cka-alpha`, `payments`, `ingress-lab`) to make cleanup easier. (Exception: CoreDNS troubleshooting or control-plane static pods).
8. Return ONLY valid JSON adhering to the `ScenarioEnvelope v1.2` schema. Do not include text outside the JSON.
9. `etcd` operations (`etcdctl snapshot save/restore`, `ETCDCTL_API=3`) must ALWAYS run on the `controlplane` node via `node_commands` with `node: controlplane` — never on the candidate host or on workers. Use the `etcdctl` binary and the node's certificates (`/etc/kubernetes/pki/etcd/`); any `etcdctl` installed on the candidate host does not participate in the checks.
10. The `solution` block must solve the scenario in an AUTOMATED way (YAML manifests and/or `kubectl` commands applicable without human intervention) — it feeds the Solvability Probe, which applies the solution to an exam clone and requires 100% of the checks to `PASS`. Didactic prose goes only in `reference_solution`.
```

---

## 5. Measurable Difficulty Rubric (genuinely distinct levels)

> Requirement (Revision 3): the difference between levels is **not subjective** — it is a complexity band measured directly from the envelope and **enforced at Stage C** of the pipeline: outside the band on ≥ 2 axes ⇒ `verdict: patch` with the explicit delta (e.g. *"`boss_fight` has only 2 requirements and 3 checks — needs 4–6 requirements and ≥ 6 checks"*). Gate D also rejects `boss_fight` without `node_commands`/infrastructure failure.

| Axis (measured on the envelope) | `exam_standard` | `killer_hardcore` | `boss_fight` |
| :--- | :--- | :--- | :--- |
| Requirements in the `prompt` (bullets) | 1–2 | 3–4 | 4–6 |
| Resource kinds (setup + solution) | 0–2 kinds | ≥ 2 kinds | ≥ 3 kinds + node infrastructure |
| Scope | 0–1 namespace | 0–2 namespaces | multi-namespace **or** node failure (kubelet / static pod / systemd) |
| Deliberate traps (fair) | 0 | ≥ 1 (label mismatch, egress DNS 53, taint, pre-existing broken manifest) | ≥ 2 |
| Causal chain depth | 1 (action → result) | 2 (diagnose → repair) | ≥ 3 (restore infrastructure → dependent workload → validate) |
| Checks | 2–3 | 4–6 | 6–10, including ≥ 1 negative check |
| Time target | ≤ 4 min | ≤ 7 min | ≤ 12 min |
| Mock exam weight (`weight`) | 2–5 | 6–10 | 11–16 |

**Example of what separates the levels** (same domain, Services & Networking): `exam_standard` = "Create a Service `svc-a` of type NodePort `30080` for Deployment `frontend`"; `killer_hardcore` = the same Service + a NetworkPolicy that isolates `backend` allowing only `frontend` on `8080` **without breaking DNS egress 53** + saving the manifest to `/opt/cka/netpol.yaml`; `boss_fight` = `node01` kubelet stopped (SSH) + `frontend` stuck in `ContainerCreating` + Service without endpoints due to a label mismatch + NodePort required on a specific node via toleration.
