# Architectural Analysis and Deep Improvements Plan — CKA Arena

> **Translated from the original pt-BR.**
>
> **Historical record (audit of 2026-11-21) — frozen.** Forensic diagnosis and improvement plan, implemented right afterwards (§7). Modules cited as defective (e.g. `app/composer.py`, `app/fault_units.py` and the monolithic `app/pipeline.py`) were removed or rewritten; line numbers, counts and measurements reflect that moment. Current state: `README.md` and `ARCHITECTURE.md`.

> **Audit date:** 2026-11-21 · **Scope:** Full audit of the code (`app/`, `static/`, `scenarios/seed/`, `tests/` — 8,630 lines of code, 106 green `pytest` tests), configuration (`llm_config.json`) and forensic evidence from the real question bank (`data/cka_arena.db`: 135 questions, 40 generation jobs, 618 LLM calls, 9 sessions, 36 check runs).
> **Goal:** Turn **CKA Arena** into a fast, reliable local CKA training platform pedagogically faithful to the real exam (CNCF 2025/2026 / Killer.sh), attacking at the root the 3 critical reported symptoms — **slow generation**, **low quality / nonsensical question construction** and **high quarantine rate** — plus the structural debt in the rest of the architecture.

---

## Executive Summary: Quantitative Diagnosis vs. Targets

| Indicator | Measured Reality (`data/cka_arena.db` / code) | Main Root Cause | Target (Post-Improvements) |
| :--- | :--- | :--- | :--- |
| **Quarantine rate (LLM)** | **60.2%** (71 `draft` vs. 47 `published` out of 118 LLM records; `boss_fight` reaches **76.9%**: 40 `draft` vs. 12 `published`) | Retries without `assistant` history, empty post-cleanup digest, broken `len_gte`, schema errors classified as `infra`, LIST-mode without `.items[*]`, writing `draft` on intermediate failures | **< 10%** in `exam_standard` and `killer_hardcore`; **< 15%** in `boss_fight` |
| **Generation time per batch** | **~29 min (1,734.6s)** on the last `exam_standard × 5` (`gen-989c40274b`, publishing only 3/5); 16–30 min on recent batches | **> 95% of the time spent on the cluster**, not the LLM: serialized `_probe_lock`, `settle()` blocking 45s on intentionally `Pending` pods, `ephemeral_probe` in a new pod per check/poll + 25s × 60s timeout mismatch, blind `_repair(deep=True)` | **20–45s per question** (~2–3 min per batch of 5 questions) |
| **LLM `exam_standard` distribution** | **12** Services & Networking · **1** Troubleshooting · **1** Workloads · **0** Storage · **0** Cluster Architecture | Extreme prompt bias (single `SOLVABLE PATTERN` in S&N), `setup.commands`/`solution.node_commands` omitted from the JSON contract, and no curriculum planning | **Balanced 5×3 coverage** across the 5 CNCF domains and 35–40 archetypes of the 2025/2026 curriculum |
| **Narrative quality (`killer`/`boss`)** | **6/9 (67%)** of Composer questions fell into the robotic fallback `"Repair N cluster faults (...)"` + 4 NetworkPolicy clones on the authoring path | Deterministic bug in `_narrate()` (requires `node_scoped` unit namespaces in the text), Composer gluing 3–5 disconnected faults in separate namespaces and leaking the root cause in the namespace name/symptom | **100% killer.sh/CKA format**, 0 spoilers, 0 clones, incidents with a real causal chain |
| **User `Check` latency** | Up to **60s** of waiting when the scenario has an intentionally `Pending` Pod | `SessionService.check()` calls `run_checks(settle=True)` and `settle()` treats any `Pending` pod as "unstable" | **< 3s** (immediate detection of terminal states `Unschedulable`/`ImagePullBackOff`/`CrashLoopBackOff`) |
| **Bank telemetry (`bank_questions`)** | `times_used=0`, `last_used_at=NULL`, `first_try_pass_count=0`, `avg_solve_seconds=NULL`, `sessions.total_weight=0` in **100%** of records | `sessions.py` never updates usage/pass statistics in `bank_questions` and `bank.draw_exam_sample()` does not return `weight_pct` | **100% instrumented**, feeding the anti-repetition exam-weight draw and time calibration |

---

## 1. Forensic Diagnosis: Root of the 3 Reported Symptoms

### 1.1 Why generation takes 15–30 minutes (the bottleneck is not where it seems)

The line-by-line temporal analysis of `llm_generations` and `bank_questions` in the last `exam_standard × 5` job (`gen-989c40274b`, using `deepseek-flash` with `thinking` off in the fast path) proves where the time goes:

- The **3 initial parallel LLM-B calls** finished at **+5.7s, +6.0s and +6.1s**.
- The **3 Reviewer (LLM-C) calls** finished at **+0.8s** (`+6.5s`, `+6.7s`, `+7.0s`).
- However, the first 3 slots only finished the Solvability Probe at **+221.9s**, **+331.8s** and **+437.0s** — and the whole job took **1,734.6s (~28.9 minutes)** to publish 3 of 5 questions.

The **6 real latency multipliers** in the current code are:

1. **`ScenarioEngine.settle()` blind to intentional faults (`app/scenario_engine.py:122-139`):**
   `settle()` considers any pod with `phase in ("Pending", "Unknown")` unstable. In any Scheduling, `nodeSelector`, `Taints/Tolerations`, `ResourceQuota`/`cpu` or pending `PVC` scenario, the pod is `Pending` **by design**. The `_probe_locked` (`app/pipeline.py:1225`) pays a **full 45s** stuck in `settle()` before even running the sanity check (and in user practice, `SessionService.check()` uses `settle=True` with a ceiling of **60s**).
2. **`self._probe_lock` serializes 100% of probes (`app/pipeline.py:306,1197`):**
   Although up to 3 Builders run in parallel (`asyncio.Semaphore(3)` on line 414), all of them queue behind a single global probe lock — even when creating isolated resources in distinct namespaces.
3. **Cascading effect on `ephemeral_probe` (`app/validator.py:33-38,149-180` × `app/pipeline.py:882`):**
   - Each HTTP check with `ephemeral_probe: true` creates a Pod `curlimages/curl:8.10.1` (`kubectl run`), polls at 1.5s intervals until `Succeeded`/`Failed`, fetches logs and deletes the pod — repeated on every poll round of both the sanity and the solution verification.
   - Additionally, there is a **timeout inversion**: `_probe_run(..., timeout=60)` (`validator.py:149`) runs inside `run_check()`, whose `TIMEOUTS["pod_exec_exit_zero"]` is **25s** (`validator.py:34`). If the ephemeral pod pull/start/exec exceeds 25s, `asyncio.wait_for` raises `TimeoutError`, which becomes `status="ERROR"`, forces **3 check retries (up to 75s)**, marks the round as `infra_error=True`, and triggers `_probe_retry` (`pipeline.py:882`), which re-runs the full probe up to **3 additional times** (backoff `3s + 6s + 9s`).
4. **Full double confirmation in the probe (`app/pipeline.py:1285`):**
   After applying the solution, `_probe_locked` requires `consecutive_full >= 2` complete `all_passed` rounds, re-running all checks (including spinning up new ephemeral `curl` pods) even for purely declarative API verifications.
5. **`_repair()` stuck on `deep=True` without live diagnostics (`app/pipeline.py:1396`):**
   Every repair forces `deep=True` (model reasoning mode, 10× slower), does not write a record to `llm_generations` (a total blind spot for latency/cost) and, as we will see in section 1.3, receives an empty `live_namespace_state`.
6. **Generic namespace collisions and `Terminating` (`app/scenario_engine.py:60-89,203` × `app/pipeline.py:1023-1028`):**
   The LLM frequently reuses fixed names (`web`, `shop`, `sched-fix`, `cka-netpol`). Since `cleanup()` uses `kubectl delete namespace ... --wait=false`, the next attempt (or a dry-run in the same namespace) falls into `Terminating` and pays 24–40s wait loops until forced finalization.

---

### 1.2 Why questions come with flimsy, nonsensical construction

The quality problem stems from **two architectures with distinct defects**: the **Composer v5** (used for `killer_hardcore` and `boss_fight`) and the **authoring LLM Builder** (used for `exam_standard` and as the fallback of the hard tiers).

#### A. The pedagogical failure of Composer v5 (`app/composer.py` + `app/fault_units.py`)

The Composer was introduced to reduce quarantine on the hard tiers, but sacrificed the technical and didactic coherence of the questions:

1. **"Frankenstein" questions with no causal nexus:**
   `composer.compose()` draws 3 (`killer_hardcore`) or 5 (`boss_fight`) independent units from `fault_units.py` and concatenates them into the same question prompt, each in its own namespace (`cka-b-*`), almost all of them using a Deployment called `web` and a Service called `web-svc`.
   - *Real example published in the bank (`q-60f4e53465ec`, `boss_fight`):* places in the same question (1) creating an `HTTPRoute` in `cka-b-gateway-route-sr77`, (2) fixing `CrashLoopBackOff` of `web` in `cka-b-crashloop-cmd-vv7w`, (3) fixing `ImagePullBackOff` of `web` in `cka-b-image-pull-osup`, (4) upgrading a Helm chart in `cka-b-helm-upgrade-24hv` and (5) starting `kubelet` on `node01`. There is no application architecture or cause-and-effect relationship whatsoever — 5 disconnected mini-exercises glued together.
2. **Explicit root-cause leakage (Spoilers) violating the CKA format:**
   - The generated namespaces carry the fault name in the identifier itself: `cka-b-crashloop-cmd-vv7w`, `cka-k-pod-wrong-clai-6u87`, `cka-b-svc-selector-iisj`, `cka-b-cpu-request-v0a0`.
   - The `symptom` texts in `fault_units.py` hand the diagnosis to the candidate on a plate (e.g. *"because its container command exits immediately"*, *"because its image tag does not exist"*, *"its selector does not match the Pods"*, *"its kubelet service is not running"*), directly violating the `LLM_SCENARIO_SPEC.md` §1.2 rule (*"sintomas observáveis — NUNCA a causa nem a solução"* [observable symptoms — NEVER the cause nor the solution]).
   - Generic tasks (*"Fix the workload..."*, *"Repair the Deployment..."*) without referencing the namespace when multiple `web`s exist in the same question prompt.
3. **Deterministic `_narrate()` bug (`app/pipeline.py:796-797` × `app/composer.py:100-103`):**
   - `composer.py:101-103` creates an entry in `ns_map` for **every** drawn unit — including `node_scoped` units without a namespace (`kubelet-down` and `etcd-snapshot`).
   - In `pipeline.py:796-797`, `_narrate()` validates the LLM Narrator response requiring:
     ```python
     for ns in meta["namespaces"].values():
         valid = valid and ns in prompt
     ```
   - Since an invented namespace like `cka-b-kubelet-down-xxxx` is never cited in the question prompt nor exists in the setup, **this validation returns `False` in 100% of `boss_fight` questions with a node and in ~50% of `killer_hardcore`**. Result: the LLM Narrator call is discarded (and not even logged in `llm_generations`), falling into the mechanical fallback `"Repair 5 cluster faults (Troubleshooting)"` — verified in **6 of 9 (67%)** questions published by the Composer.
4. **Internal structural bugs in `composer.py` and `fault_units.py`:**
   - `CHECK_LIMIT = {"boss_fight": 11, "killer_hardcore": 6}` (`composer.py:21,51`) is declared and read in `select_units()`, but **never enforced** (the bank contains Composer `boss_fight` questions with 12 checks and `killer_hardcore` with 7 checks).
   - **Ignores user filters:** `composer.compose()` and `select_units()` receive no `domains`, `subtopics` or `constraints` (`focus_hint`) from the request — if the user asks for `Storage` only, the Composer draws `Gateway`, `Helm` and `kubelet`.
   - **Cluster-scoped resource collision:** both `pv-claimref` (`fault_units.py:287`) and `pod-wrong-claim` (`fault_units.py:324`) create a cluster-scoped `PersistentVolume` with exactly the same name `pv-data`! If drawn together, the second overwrites the first and the cleanup of one deletes the other's PV.
   - **Cross-interference with `kubelet-down`:** stopping `kubelet` on `node01` affects pods of other workload units in the same scenario that the scheduler placed on `node01`; `_merge_solution` runs `node_commands` last, but if the pod is not ready or the check runs before node recovery, the composition fails.
   - **`etcd-snapshot` invalid for `boss_fight`:** `setup.node_commands` is empty (`[]`), so the `_tier_band_errors` gate rejects if it falls without another unit having `node_commands` in setup.
   - **`docs_links` always `[]`:** `composer.py:175` does not fill links to the official documentation allowed in the exam.

#### B. Quality defects on the LLM authoring path (`app/pipeline.py:_build_one`)

When generation goes through the LLM authoring path (`exam_standard` and fallback of `killer`/`boss`), 4 structural problems arise:

1. **Extreme bias from a single few-shot (diversity collapse):**
   - `BUILDER_SYSTEM` (`pipeline.py:179-186`) has only one explicit `SOLVABLE PATTERN`: Deployment `web` + Service `web-svc` in Services & Networking. Observed result in the bank: of the 14 `exam_standard` questions published by LLM, **12 are `Services & Networking`**, 1 Troubleshooting, 1 Workloads, **0 Storage** and **0 Cluster Architecture**.
   - `HARD_TIER_ADDENDUM` (`pipeline.py:242-244`) injects a single fixed exemplar (`sn-networkpolicy-dns.json`). Observed result in the bank: **4 clones published** with the exact title `"Allow Selected Traffic Through Default Deny"` in `killer_hardcore` of `Services & Networking` (plus dozens of `web` + `web-svc` variations).
2. **Incomplete schema contract in `BUILDER_SYSTEM` (`pipeline.py:126-129`):**
   - The `OUTPUT CONTRACT` shown to the LLM defines `setup` with only `namespaces`, `manifests`, `node_commands` — **omitting `setup.commands`** (needed for `helm install` or `kubectl taint`).
   - It defines `solution` with only `manifests`, `commands` — **omitting `solution.node_commands`** (making it impossible for the LLM to generate scenarios where the solution runs on the node, such as `systemctl start kubelet` or `etcdctl snapshot save`).
   - It defines `cleanup` with the legacy field `kubectl_commands` instead of `commands`.
3. **No coordination between parallel slots and bank history:**
   - `"avoid": "duplicate titles or topics from previous slots"` (`pipeline.py:558`) is just static text — the 3 parallel slots receive neither the titles already existing in the bank nor an archetype/domain assigned per slot. All slots converge on the easiest theme (Service selector / CrashLoop `web`).
4. **Missing quality validations in Gate D / Reviewer C:**
   - No deterministic anti-spoiler verification (several LLM prompts leak the solution or root-cause terms before `Perform the following tasks:`).
   - No validation of `docs_links` (the prompt asks for URLs of `kubernetes.io/...`, but no check verifies they exist or have a valid domain).

---

### 1.3 Why questions go to quarantine so often (Taxonomy of the 71 Drafts)

Inspecting all **71 questions in `draft` state** in `data/cka_arena.db` reveals exactly where the pipeline fails:

| Failure Category (evidence in `probe_result_json`) | Composer | Authoring LLM | Total | Technical Root Cause |
| :--- | :---: | :---: | :---: | :--- |
| **`infra_error` on sanity/final check** | 0 | 17 | **17** | `validator.py` classifies Python bugs in LLM params (`TypeError`, `KeyError`) as `ERROR`; short `settle`/25s timeout in `ephemeral_probe` |
| **Solution rejected on apply (`other` / `BadRequest` / `immutable` / `AlreadyExists` / `taint`)** | 2 | 15 | **17** | `solution.manifests` not run through `--dry-run=server` in Gate D; LLM attempts `kubectl patch` on immutable `PVC`/`Pod` fields; 2 Composer drafts failed due to invalid JSON patch in `svc-targetport` (fixed later, but no JSON `-p` gate) |
| **`kubectl_jsonpath` returns empty (`''`/`None`) or wrong string** | 0 | 11 | **11** | LIST mode with `label_selector` without `.items[*]` in the jsonpath; rigid regex on multi-lines |
| **Inconsistent logic between `setup`/`solution`/`checks`** | 1 | 7 | **8** | **Retry amnesia** (no `assistant` message across iterations) + **dead digest in `_repair()`** + logic error not detected in a pre-probe gate |
| **Exception in the probe (setup/SSH/timeout)** | 0 | 7 | **7** | `setup.commands` failing (e.g. `helm repo add` of a nonexistent repo, missing taint, invalid SSH/command) |
| **Other checks fail (`no pods match`, `Pending`, `HTTP stdout=''`, `len_gte`, `Helm missing`)** | 0 | 10 | **10** | Real bug in `len_gte` (`split(",")` over space/newline-separated output), `setup` without `helm install`, Service without ready endpoints |
| **Total** | **3** | **68** | **71** | **60.2% of all questions generated by LLM historically** |

The **7 concrete code bugs** explaining this rejection rate are:

1. **Critical bug — Amnesia across `_build_one` retries (`app/pipeline.py:612-614, 641-643, 655-657, 697-701`):**
   When an attempt fails on schema, gates, reviewer or probe, the loop appends `{"role": "user", "content": "Your previous output was invalid: ..."}` to the `messages` list, **but NEVER appends `{"role": "assistant", "content": text}` before it!** The model receives a complaint about a JSON that is not in the conversation history and must regenerate everything blindly from scratch.
2. **Critical bug — `live_namespace_state` always empty in `_repair()` (`app/pipeline.py:660, 679, 1324-1328, 1380`):**
   The comment in `pipeline.py:1363` and `LLM_PIPELINE_SPEC.md` promise that `_repair()` receives the live state of the namespaces (`pods`, `readiness`, `services`, `endpoints`). However, `_probe_locked()` executes `await self.engine.cleanup(env)` in the `finally` block (line 1326) **before returning**. When `_build_one()` calls `_repair()` on line 679 and runs `self.engine.namespace_digest(env.setup.namespaces)` (line 1380), all namespaces have already been deleted (`Terminating` or `NotFound`)! The repair operates blind.
3. **Critical bug — Deterministic check-definition errors become `infra_error` (`app/validator.py:438-439`):**
   In `run_check()`, any exception raised by `fn(params)` — such as `KeyError` (missing param), `TypeError` (e.g. incompatible `expected` as in `chk-iptables-removed` on line 73 of the drafts log), `ValueError` in `compare()` or `re.error` in a malformed regex — is caught and turned into `status = ERROR`. That marks `infra_error = True`, burns 3 check retries + 3 `_probe_retry` retries (wasting ~2 min) and returns `"infra"` without giving the model a chance to repair!
4. **Real bug — `compare(..., "len_gte", ...)` only accepts comma (`app/validator.py:66-68`):**
   `kubectl -o jsonpath="{.subsets[*].addresses[*].ip}"` separates multiple values with a **space** (and `range ... "\n"` with a **newline**), never with a comma. Since `validator.py:67` does `actual.split(",")`, `"10.40.0.2 10.40.0.3"` becomes a list of size `1`, failing any check with `min >= 2` (real evidence in `q-81441be4fcb1`).
5. **Contract bug — `kubectl_jsonpath` in LIST mode (`app/pipeline.py:166-169, 1136-1146`):**
   When using `kind="Pod"` + `label_selector="app=web"` without `name`, `kubectl` returns a `List` rooted at `.items[]`. The prompt does not explain that in LIST mode the jsonpath must start at `{.items[*].` or `{range .items[*]}`; the LLM writes `{.status.phase}` (which only works on a single object) and gets an empty string `""` (evidence in `q-f50b83a3fcfc`).
6. **Bank pollution with intermediate drafts (`app/pipeline.py:663, 670, 856, 867`):**
   The pipeline inserts a new `state="draft"` record in SQLite **on every intermediate failure** before the repair/retry loop even finishes. If a question fails twice and passes on the 3rd try, it generates 2 dead drafts + 1 published (inflating the table to 71 drafts from only 40 requests).
7. **Validation gaps in Gate D (`app/pipeline.py:916-1038`):**
   - `kubectl apply --dry-run=server` runs only on `env.setup.manifests` (line 1017), never on `env.solution.manifests`.
   - No validation of JSON syntax of `-p`/`--patch` flags in `commands` (nor blocking patches to immutable fields like `PVC.spec.storageClassName`, `PVC.spec.accessModes`, `Pod.spec.volumes`).
   - No validation of the rule documented in `LLM_PIPELINE_SPEC.md` §5.1 that `pod_exec_must_fail` needs an embedded timeout in the command.
   - `_tier_band_errors` (line 1187) only fails if `len(fails) >= 2` and ignores missing `setup.node_commands` unless the exact condition is hit.

---

## 2. Systemic Problems Beyond the AI (Full Architectural Audit)

The analysis of the entire project outside the LLM pipeline found **8 critical/medium architectural debts** that compromise the goal of having a solid local platform:

| Area | Evidence in Code / Bank | Real Impact |
| :--- | :--- | :--- |
| **1. Question telemetry completely disconnected** | `app/sessions.py` never updates `bank_questions.times_used`, `last_used_at`, `first_try_pass_count` nor `avg_solve_seconds` (all `0`/`NULL` across the 135 DB rows). `bank.draw_exam_sample()` (`app/bank.py:137-139`) does not return `weight_pct`, making `sessions.total_weight` recorded as `0` in all 9 sessions. | The anti-repetition exam-weight draw (`ORDER BY times_used`) is null; the mock exam percentage (`earned_weight / total_weight`) does not work; broken or badly calibrated questions are never detected over time. |
| **2. Zero bank curation / quarantine management** | `app/main.py` exposes only `/api/bank/coverage` and `/api/bank/preview`. There are no endpoints or UI to list, filter, inspect `drafts`, view `probe_result_json`, re-probe, repair, retire (`retired`) or delete questions. | The 71 `drafts` and duplicated clones stay trapped in SQLite as a "black hole"; if a published question has a bug in its prompt/check during practice, the user has no "Report / Retire" button. |
| **3. Asset paths broken by the scratch terminal** | `TerminalSession.spawn()` (`app/terminal.py:121,144`) starts the shell in `~/.cka-arena/scratch/<tab_id>`, but the seed `scenarios/seed/ca-helm-upgrade.json` instructs using `scenarios/seed/assets/helm-chart` (a path relative to the repo root). In the real DB `check_runs`, there are 2 consecutive failures on that seed. | The user in the integrated terminal cannot find the Helm chart or Kustomize overlays without manually navigating outside the scratch sandbox. |
| **4. `mock_exam` mode and `destructive` flag incomplete** | `app/sessions.py:95` records `mode = "study"` hardcoded; `sessions.get()` does not expose `ssh_target` or `destructive`; `static/js/workspace.js:98` hardcodes `ssh cka-node01` and hides `destructive` questions without a dedicated flow. Also, the last `Check` report disappears on page reload (F5). | Impossible to run a full timed mock exam (120 min, free navigation between questions, Flag for Review, score ≥ 66%), and `etcd restore` / `kubeadm upgrade` scenarios still lack a safe L2 flow. |
| **5. `Check` button missing on the terminal bar** | `README.md`, `PLAN.md` and `GAP_ANALYSIS.md` promise a `Check` button directly on the terminal footer bar. In `static/index.html:80-94`, the terminal footer only has `+ Shell`, `term-workdir`, `Native` and `Clear`. | Worse ergonomics when using only the right panel (though `⌘↵` works globally). |
| **6. Concurrency without Cluster Lease governance** | `app/main.py:43-44` instantiates two distinct `ScenarioEngine()`s (`pipeline` and `sessions`). There is no lock/lease preventing running AI generation at the same time as an active practice session, `reset-baseline` or `power stop`. There is also no `POST /api/generate/cancel` endpoint, leaving 4 `generation_requests` stuck as `running` in the DB. | Real risk of a generation altering nodes (`kubelet` stop, taints) or consuming resources during a user exam session, plus zombie jobs after restart. |
| **7. `teardown.py` coupled to SSH + `MultipassProvider` bottleneck** | `app/teardown.py` calls `ssh_runner.sudo_run(ip, ...)` directly instead of using `provider.get().exec(..., sudo=True)`, breaking L1/L2/drift on the `kind` driver (WSL2). `MultipassProvider.exec()` (`app/provider/multipass.py:34`) calls `self.nodes()` (running `multipass list` + TCP probes on 3 VMs) on **every SSH command**, with no TTL cache or `ControlMaster`. | `teardown` incompatible with WSL2/kind; avoidable overhead of hundreds of ms per node command; `reset_clean` only clears one hardcoded taint (`cka-arena/practice=critical:NoSchedule-`). |
| **8. `llm_client.py` + project hygiene** | `save_config()` (`app/llm_client.py:279-288`) drops `thinking` and `reasoning_effort` from the saved JSON; no preset for local **Ollama** (despite being cited in `PLAN.md`) nor free-form model input; `httpx.AsyncClient` recreated per request; `data/arena.db` (0 bytes) and stray YAMLs in the root (`deploy.yaml`, `role.yaml`, `rolebinding.yaml`); dead tables `terminal_sessions`/`command_audit` (0 rows); disabled test in `tests/test_composer.py:89` (`if False`); pt-BR messages leaking from `validator.py` into a 100% English UI. | Impossible to control `thinking` or use Ollama from the UI; accumulation of dead artifacts and language inconsistency in error evidence. |

---

## 3. Proposed Target Architecture (Generation v2 + Governed Platform)

To solve the three root problems, the pipeline moves from the *"generic prompt + gluing of disconnected fragments"* model to a **Blueprint-Guided + Cohesive Causal Incidents + Cluster Lease** architecture:

```mermaid
flowchart TD
    UI["Scenario Studio\n(domains · difficulty · count · focus)"] --> LEASE{"Cluster Lease\n(free of session/reset?)"}
    LEASE -->|busy| REJECT["409 Conflict made clear in the UI"]
    LEASE -->|free| A["Stage A · Normalizer + Slot Planner\n• Reads 5×3 grid and last 30 titles from the DB\n• Draws a distinct CNCF archetype per slot\n• Assigns neutral namespace + few-shot exemplar"]

    A --> STRAT{"Strategy per Tier"}
    STRAT -->|exam_standard / killer_hardcore| B1["Stage B · Blueprint-Guided Builder\n(assistant history preserved across retries)"]
    STRAT -->|boss_fight| B2["Stage B · Causal Incident Engine\n(cohesive multi-layer incidents in the same app)"]

    B1 --> D["Stage D1/D2 · Deterministic Gates (0 LLM)\n• YAML + JSON -p + immutability + anti-spoiler\n• LIST-mode .items[*] + must_fail timeout + docs_links\n• dry-run=server on BOTH setup AND solution"]
    B2 --> D

    D -->|structural error| B_FIX["Targeted retry (fast)"]
    B_FIX --> D
    D -->|ok| C["Stage C · Cold Reviewer (flash)\n• Semantic rubric + anti-spoiler + exam voice"]
    C -->|patch (≤1x)| B_FIX
    C -->|approve| E

    E["Stage E · Solvability Probe v2\n• Ephemeral namespace cka-prove-<slot> (parallel ≤2 ns-scoped)\n• Smart Settle event-driven (TerminalFault exits in 2-4s)\n• Warm Probe Pod (cka-arena-system) when no NetPol\n• Captures Live Digest (pods/events/logs/svc/pvc) PRE-cleanup"]

    E -->|real infra failure| RETRY_INFRA["Infra retry (without burning budget)"]
    E -->|content failure| REPAIR["Surgical Repair (1st fast → 2nd deep)\nwith real Live Digest + full matrix"]
    REPAIR --> D
    E -->|100% PASS| PUB[("bank_questions\nstate: published")]
    REPAIR -->|budget exhausted| DRAFT[("bank_questions\nstate: draft + history\n(1 final record per slot)")]
```

### 5 Principles of the New Architecture

1. **Explicit Curriculum Planning (Slot Planner before the Builder):** never ask the LLM to "invent any question". Each slot is born with a domain, an archetype from the CNCF 2025/2026 curriculum, topic-specific pitfalls, a neutral corporate namespace and a real `avoid_recent` list from the bank.
2. **Cohesion over Gluing (end of the Frankenstein Composer):** `killer_hardcore` and `boss_fight` questions must represent a single realistic system/incident in 1–2 business namespaces, with real dependencies between tasks (e.g. `kubelet` → `PVC/Pod` → `Service` → `NetworkPolicy/HTTPRoute`).
3. **Fail Fast and Cheap Before the Cluster:** `Gates D1/D2` (including `dry-run=server` of the solution) run **before** the `Reviewer C` and the `Probe E`. Syntactic/semantic errors never touch the VMs nor pay for a Reviewer call.
4. **Full Memory + Live Observability:** retries keep the `assistant` response in context; `_repair()` receives `events`, `logs`, `Pod conditions` and `Endpoints` captured **before** `cleanup()`.
5. **Cluster as a Governed Shared Resource:** ephemeral-namespace isolation in the probe, event-driven Smart Settle on Pod state, shared Warm Probe Pod, and a `ClusterLease` unifying session, generation and reset.

---

## 4. Detailed Improvement Plan in 6 Fronts (P0 → P2)

### Front 1 (P0) — Critical Pipeline Bug Fixes & Immediate Quarantine Relief
**Goal:** Immediately stop the deterministic bugs causing mass quarantine, repair amnesia and wasted time.

- **Technical Changes:**
  1. **Preserve `assistant` history in `app/pipeline.py:_build_one`:**
     Before each `messages.append({"role": "user", ...})` on lines 612, 641, 655 and 697, append `{"role": "assistant", "content": text}` (compacting only old rounds if the window limit is exceeded, always keeping the last complete envelope).
  2. **Capture `live_digest` pre-cleanup (`app/pipeline.py:_probe_locked` and `app/scenario_engine.py:namespace_digest`):**
     - Capture `digest = await self.engine.namespace_digest(env.setup.namespaces)` **inside `_probe_locked` before the `finally: cleanup(env)`** whenever sanity or final fail on content, returning it alongside the probe result (or storing it in the attempt report).
     - Enrich `namespace_digest()` with: recent Warning `events` (`kubectl get events -n <ns> --field-selector type=Warning`), `conditions` of `Pending` Pods (`Unschedulable` message), the last 15 lines of `logs` in `CrashLoopBackOff`, and `PersistentVolumeClaim` status (`phase`, `storageClassName`).
  3. **Immediate fixes in `app/validator.py`:**
     - **Fix `len_gte` (lines 66-68):** use `items = [part for part in re.split(r"[\s,]+", actual) if part.strip()]` to accept output separated by space, newline or comma from `kubectl jsonpath`.
     - **Separate `INVALID` from `ERROR` (lines 438-439):** create a clear status/classification for errors caused by invalid check parameters (`KeyError`, `TypeError`, `ValueError`, `re.error`) — treat as a **content** failure (`kind="content"`), never as `infra_error`, avoiding the 3 useless check retries + 3 probe retries.
     - **Align `ephemeral_probe` timeout:** raise `TIMEOUTS["pod_exec_exit_zero"]` / `pod_exec_must_fail` to `45s` when `ephemeral_probe` is true (or switch to the Warm Probe Pod of Front 3), ensuring `asyncio.wait_for` in `run_check` does not kill `_probe_run` before its internal timeout.
     - **Standardize messages in English:** translate the `reason`/`error` strings in `validator.py` (currently pt-BR, e.g. `"nenhum pod corresponde ao selector"`, `"arquivo não existe"`) to keep the UI 100% English per `PRODUCT.md`.
  4. **Complete contract and rules in `BUILDER_SYSTEM` (`app/pipeline.py:116-189`):**
     - Include `commands` in `setup` and `cleanup`, and `node_commands` in `solution` inside the JSON `OUTPUT CONTRACT`.
     - Explicitly document the mandatory LIST-mode syntax of `kubectl_jsonpath`: when `name` is empty and `label_selector` is set, the `jsonpath` **must** iterate over `.items[*]` (e.g. `{.items[*].spec.nodeName}`).
     - Explicitly forbid `kubectl patch` on immutable `PVC` fields (`storageClassName`, `accessModes`, `selector`) and `Pod` (`spec.volumes`, `spec.containers[*].ports` immutable via simple patch) — guide toward `solution.commands` with delete + `solution.manifests`.
  5. **Reorder and harden the Gates (`app/pipeline.py:_build_one` and `_gates`):**
     - **New order:** `Schema (Pydantic)` → `Band clamp` → **`Gates D1 (static) + D2 (server dry-run)`** → **`Reviewer C`** → **`Probe E`**. Never spend Reviewer LLM calls on envelopes that already fail the deterministic gates.
     - Run `kubectl apply --dry-run=server -f -` also on `env.solution.manifests` (not only `setup.manifests`).
     - Validate JSON syntax in `-p`/`--patch` payloads of `setup.commands`, `solution.commands` and `cleanup.commands`.
     - Reject `kubectl patch` targeting known immutable fields (`pvc` changing `storageClassName`/`accessModes`, `pod` changing `volumes`).
     - Validate that `kubectl_jsonpath` in LIST mode (`not name and selector`) contains `items` in the `jsonpath`.
     - Validate that `pod_exec_must_fail` includes a timeout flag/command (`--max-time`, `-w`, `-W`, `timeout`).
     - Validate non-empty `docs_links` with URLs under allowed domains (`kubernetes.io`, `helm.sh`, `gateway-api.sigs.k8s.io`).
     - Heuristic **Anti-Spoiler** gate: verify whether the narrative part before `Perform the following tasks:` contains literal forbidden diagnosis/fix patterns (e.g. `"because its selector"`, `"because the command exits"`, `"missing tag"`, `"patch"`, `"remove the"`) and forward that criterion explicitly to Reviewer C.
  6. **Eliminate intermediate draft pollution & fix the `_narrate()` hotfix:**
     - Write `bank.publish_question(..., state="draft")` **only once** at the end of `_build_one` / `_compose_one` when the slot exhausts all attempts (storing a structured summary of the last failures in `probe_result_json`).
     - In `_narrate()` (`app/pipeline.py:796-797`), validate only the namespaces present in `setup.namespaces` (never fictional `node_scoped` unit namespaces).

- **Expected Impact:** Immediate quarantine reduction from ~60% to ~20–25% even before swapping the generation engine; elimination of ~40% of lost LLM-C calls and of blind retries in repair.
- **Acceptance Criteria:** Unit tests covering `assistant` in history, `len_gte` with space/newline, `INVALID` without infra retry, `live_digest` captured pre-cleanup and dry-run on `solution.manifests`; batch of 5 `exam_standard` reducing quarantine to ≤ 1/5.

---

### Front 2 (P0) — New AI Generation Architecture: Blueprint-Guided + Cohesive Incidents
**Goal:** End Frankenstein questions, repeated clones, domain bias (12/14 in S&N) and spoilers in the question prompt.

- **Technical Changes:**
  1. **Curriculum Catalog (`app/curriculum.py` — new):**
     Model ~35–40 official archetypes from the CNCF CKA 2025/2026 curriculum across the 5 domains, each with:
     - `id`, `domain`, `subtopics`, `allowed_difficulties`
     - `requires_addons` (`gateway`, `metrics-server`, `local-path`, `helm`, `etcdctl`, `network_policy`)
     - `needs_node_ssh`, `destructive`
     - `example_seed_id` (reference to a validated real seed or a structural template for dynamic few-shot)
     - `pitfalls`: precise technical guidance to avoid LLM failures on that topic (e.g. *Gateway API `Accepted` vs `Programmed=False` without LoadBalancer*; *Kustomize `kubectl apply -k`*; *Native Sidecar `initContainers` with `restartPolicy: Always`*; *PVC `WaitForFirstConsumer` only binds after the Pod is schedulable*; *NetworkPolicy with Egress requires `kube-system` UDP/TCP 53*).
  2. **Bank-Aware Slot Planner (`app/planner.py` — new, integrated into Stage A):**
     - On receiving a `GenerateRequest`, read the current 5×3 matrix from the bank (`bank.coverage()`) and the last 30 published titles/archetypes.
     - Distribute the `N` slots across the selected domains prioritizing empty/deficient cells, and draw a **distinct archetype per slot** (filtered by the addons available returned by `ClusterDoctor` and by the `constraints` of `focus_hint`).
     - Assign each slot a **neutral business namespace** from a realistic pool (`checkout`, `billing`, `orders`, `inventory`, `edge-gw`, `auth-core`, `catalog`, `payments`, `telemetry`, `media`), adding a short random suffix in the probe when needed. **Forbidden** to use fault names in the namespace (`crashloop`, `wrong-claim`, `svc-selector`).
     - Inject `avoid_recent` with real bank titles + titles planned for sibling slots.
  3. **Dynamic Few-Shot per Domain/Tier in the Builder (`app/pipeline.py`):**
     Remove the fixed `web-svc` `SOLVABLE PATTERN` and the single NetworkPolicy `_HARD_EXAMPLE` from the global prompt. Dynamically inject the seed exemplar closest to the drawn `archetype` for that slot (e.g. a Storage seed for Storage, a Helm/RBAC/etcd seed for Cluster Arch, a Taint/Resources seed for Workloads).
  4. **Replace the Frankenstein Composer (`app/composer.py` / `app/fault_units.py`):**
     - **`exam_standard` and `killer_hardcore`:** become fully generated via **Blueprint-Guided LLM** (archetypes with calibrated complexity: 1–2 requirements in 1 namespace for `exam_standard`; 3–4 interlinked requirements + ≥ 1 fair trap in 1–2 namespaces for `killer_hardcore`).
     - **`boss_fight` via Causal Incident Blueprints:** replace the random gluing of 5 disconnected faults with **cohesive multi-layer incident blueprints** (6–8 architectures where all faults belong to the same system/flow):
       - *Example A (Node + Workload + Exposure):* `kubelet` stopped/misconfigured on `node01` + Deployment with `nodeAffinity`/taint + Service with wrong `targetPort` + end-to-end HTTP verification.
       - *Example B (Control-Plane/Static Pod + Workloads + Rollout):* broken static manifest/CoreDNS or probe + Deployment with invalid resource/command + post-recovery verification.
       - *Example C (Storage + RBAC + Gateway/NetworkPolicy):* `PV` with `claimRef`/StorageClass + app depending on the PVC + `NetworkPolicy`/`HTTPRoute` with negative and positive checks.
       - The LLM fills in neutral names, manifests, spoiler-free symptoms and didactic reference about the causal blueprint, and the Solvability Probe proves the chained fix resolves 100% of the checks.
     - Refactor `fault_units.py` (removing spoilers from names/symptoms, fixing the `pv-data` PV collision and enforcing `CHECK_LIMIT`) for exclusive use in offline fallback mode (when there is no LLM key) or unit tests.
  5. **Two-speed repair and full observability (`app/pipeline.py:_repair`):**
     - 1st `_repair()` attempt: run in **`fast` mode (`deep=False`)** — with the complete `live_digest` and the check matrix, mechanical errors are fixed in ~4–6s instead of ~60s.
     - 2nd `_repair()` attempt (if the first fails): trigger **`deep=True`** (reasoning).
     - Log all `_repair()` and `_narrate()` calls in the `llm_generations` table (with `stage="R"` and `stage="N"`).

- **Expected Impact:** Diverse questions across the 5 domains, end of Frankenstein questions and identical clones, zero spoilers in prompts, publication rate > 90%.
- **Acceptance Criteria:** Generate a mixed batch (`exam_standard` + `killer_hardcore` + `boss_fight`) covering the 5 domains without repetition, without the `"Repair N cluster faults"` title fallback, without spoilers in symptom texts, and with coverage of modern topics (Gateway API, Helm, NetworkPolicy DNS 53, Native Sidecar, Storage).

---

### Front 3 (P0/P1) — Radical Prove-Out Acceleration & Validation Engine v2
**Goal:** Cut validation time from minutes to seconds — both in the generation Solvability Probe and in the `Check` button click during study.

- **Technical Changes:**
  1. **Terminal-state-driven Smart Settle (`app/scenario_engine.py:settle`):**
     - Instead of checking only `phase in ("Pending", "Unknown")`, inspect `status.conditions` and `status.containerStatuses` / `initContainerStatuses` of each pod and classify it as:
       - `Ready`: `phase == "Running"` and all containers `ready=True`.
       - `TerminalFault`: `PodScheduled=False` with `reason == "Unschedulable"` (Scheduling/Taint/CPU/PVC Pending), or `waiting.reason` in `("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff", "CreateContainerConfigError", "InvalidImageName", "CreateContainerConfigError")`, or `terminated.reason == "OOMKilled"`, or `phase == "Failed"`.
       - `Transitioning`: `ContainerCreating`, `PodInitializing` or a freshly created pod without a failure reason yet.
     - **Fast-return rule:** when all pods are in `Ready` or `TerminalFault` (0 pods in `Transitioning`), `settle()` **returns immediately** (typically in **2–4s**, instead of waiting 45s in the sanity check or 60s in the user's `Check`!).
     - In the post-setup sanity check of the probe, keep only a short confirmation window (e.g. 10s if a container is still pulling its image or starting for the first time).
  2. **Shared Warm Probe Pod (`app/validator.py`):**
     - Create/maintain on demand 1 lightweight pod `cka-probe-runner` (image `curlimages/curl:8.10.1` or `nicolaka/netshoot` / `busybox` with command `sleep infinity`) in a dedicated namespace `cka-arena-system` (outside the scenario namespaces).
     - When a check uses `ephemeral_probe: true` and the scenario has **no** `NetworkPolicy` in the target namespace (or the check explicitly marks `probe_scope: "external"`), run `kubectl exec` directly on the Warm Probe Pod (< 300ms per call instead of 10–25s creating/deleting a pod per poll).
     - When the scenario involves restrictive `NetworkPolicy` by source namespace or requires execution inside the question's namespace, keep a single reusable probe pod in the namespace during `run_all` (or fall back to `_probe_run` with an aligned 45s timeout and guaranteed cleanup even on `asyncio.CancelledError`).
  3. **Ephemeral namespaces + controlled probe parallelism (`app/pipeline.py`):**
     - During Stage E, for namespace-scoped scenarios, temporarily rewrite in memory each namespace name of the envelope to `cka-prove-<slot>-<4hex>` before applying to the cluster (without changing the envelope saved to the bank). This eliminates 100% of the collisions between slots and the waits for `Terminating`.
     - Replace the single `self._probe_lock` with a **namespace-scoped probe semaphore (`Semaphore(2)`) + an exclusive lock only for cluster/node-scoped scenarios** (`node_commands`, `destructive`, `pv`, `clusterrole`, `taint`, `GatewayClass`).
     - In the post-solution probe verification, drop the double full-pass (`consecutive_full >= 2`) for purely declarative checks (`kubectl_resource_exists`, `kubectl_jsonpath` over spec, `kubectl_auth_can_i`, `helm_release_state`), keeping reconfirmation only for runtime/network checks (`pod_exec_*`, `pod_status_ready`, `node_status_ready`).
  4. **New Semantic Check Types (`app/validator.py` + `app/models.py`):**
     Reduce fragile LLM `jsonpath` and regex errors by adding 3 high-level check types (plus new operators on `kubectl_jsonpath`):
     - `service_endpoints_ready`: `{namespace, service_name, min_ready_addresses}` — queries `EndpointSlice` (`discovery.k8s.io/v1` with label `kubernetes.io/service-name`) with fallback to `Endpoints`, avoiding `len_gte` and `jsonpath` bugs over IPs.
     - `deployment_rollout_ready`: `{namespace, name, min_ready_replicas, expected_image?}` — validates observed generation, `readyReplicas` and image.
     - `pvc_bound`: `{namespace, name, storage_class?, min_storage?}` — validates `phase == Bound` and storage properties.
     - New operators on `kubectl_jsonpath`: `empty`, `not_empty`, `equals_int`, `not_contains`, `all_match` (verifies that every LIST-mode item satisfies an expected value without needing to write a regex like `^node01( node01)*$`).
     - Document `kubectl apply -k` (Kustomize) support in the `commands.py` contract and in the prompt.

- **Expected Impact:** Average probe drops from ~150–300s to ~15–35s; batch of 5 questions drops from ~29 min to ~2–3 min; `Check` in practice responds in < 3s even in scenarios with `Pending` pods.
- **Acceptance Criteria:** Live benchmark on the `cka` cluster validating `settle()` < 4s on `wl-resources-too-high` and `wl-taint-toleration`; HTTP check execution via Warm Probe < 500ms; unit tests of the 3 new check types and new operators.

---

### Front 4 (P1) — Question Bank Management, Quarantine & Real Telemetry
**Goal:** Turn `bank_questions` into a curated, traceable collection free of repetitions and historical junk.

- **Technical Changes:**
  1. **Instrument real telemetry (`app/bank.py`, `app/sessions.py`):**
     - Include `weight_pct` in the `SELECT` of `bank.draw_exam_sample()` (`app/bank.py:137-139`) so `sessions.create()` records a real `total_weight` (not `0`).
     - On activating a `session_item` (`_activate`), increment `times_used = times_used + 1` and update `last_used_at` in `bank_questions`.
     - On passing the check (`sessions.check()`), update `avg_solve_seconds` (moving average or recomputed via `session_items`) and increment `first_try_pass_count` when `attempts == 1`.
     - Improve semantic dedup (`app/bank.py:envelope_hash`): beyond the exact hash, add an `archetype_id` column and dedup by `(archetype_id, title_normalized)` or structural similarity to avoid multiple clones with lightly paraphrased titles.
  2. **Curation & Quarantine Endpoints (`app/main.py`, `app/bank.py`):**
     - `GET /api/bank/questions`: filters by `state` (`published|draft|retired`), `domain`, `difficulty`, `source`, text search, pagination and metrics (`times_used`, `avg_solve_seconds`).
     - `GET /api/bank/questions/{id}`: returns the complete `ScenarioEnvelope`, `probe_result_json` and `generator_meta_json`.
     - `POST /api/bank/questions/{id}/reprobe`: runs Gates + Solvability Probe on a `draft` or `published`; if it passes, promotes it to `published`.
     - `POST /api/bank/questions/{id}/repair`: runs the surgical repair on a `draft` and publishes it if the probe passes.
     - `POST /api/bank/questions/{id}/retire`: marks the question as `retired` with `retired_reason` (used by the "Report issue" button during study).
     - `DELETE /api/bank/questions/{id}`: removes a discarded `draft` (protected against deleting questions already referenced by `session_items`).
  3. **Curation UI in Studio & "Report Issue" in the Workspace (`static/js/studio.js`, `static/js/workspace.js`):**
     - Add to the Studio a **Bank & Quarantine** tab/section listing question totals per state, allowing opening any `draft` to see the exact probe error and clicking `Re-probe`, `AI Repair`, `Retire` or `Delete`.
     - Add to the Exam Workspace a discreet **Report / Retire** button next to `Skip`: if a question seems ambiguous or broken at runtime, the user retires it on the spot with a reason and unlocks the sequence.
  4. **Sanitizing the current bank (`python -m app.bank prune` or CLI script):**
     Provide an idempotent command to archive/clean the 71 old drafts, retire the duplicated clones (`Allow Selected Traffic Through Default Deny` ×4) and retire the Composer v5 Frankenstein scenarios — keeping the 17 validated seeds and the healthy LLM questions.

- **Expected Impact:** End of blind question repetition in sessions, full visibility of why something went to quarantine, and a complete heal/retire cycle without hand-editing SQLite.
- **Acceptance Criteria:** Sessions recording `total_weight > 0` and updating `times_used`/`first_try_pass_count`/`avg_solve_seconds`; complete UI flow to inspect a `draft`, repair/re-probe and promote or delete.

---

### Front 5 (P1/P2) — Practice Experience, Assets in Scratch & `mock_exam` Mode
**Goal:** Complete fidelity to the real CKA exam (PSI/Killer.sh) and fix practical workspace and terminal frictions.

- **Technical Changes:**
  1. **Full `mock_exam` mode (`app/sessions.py`, `static/js/studio.js`, `static/js/workspace.js`, `static/js/app.js`):**
     - In the **Practice** modal, allow choosing between **Study Mode** (immediate Check feedback → Next locked, current behavior) and **Mock Exam (120 min)** (a realistic PSI/Killer.sh-style exam simulation).
     - In `mock_exam`:
       - Global 120-minute countdown timer visible in the header.
       - Free navigation between questions in the queue (`Q1..Q15`), a **Flag for Review (`🚩`)** button and per-question state persistence (questions are applied/cleaned on demand or kept isolated per namespace).
       - Release of questions with `destructive: true` (with an explicit warning before activation and automatic L2 provisioning at the end).
       - Final report with the official weighted score (`earned_weight / total_weight`), the CKA cut line (`66%` PASS/FAIL) and per-domain breakdown.
  2. **Asset availability in the terminal scratch (`app/config.py`, `app/terminal.py`, `scenarios/seed/ca-helm-upgrade.json`):**
     - At app startup/setup, sync `scenarios/seed/assets/` to `~/.cka-arena/assets/` (Helm charts, Kustomize overlays).
     - In `TerminalSession.spawn()` (`app/terminal.py:120-124`), create a symlink `assets -> ~/.cka-arena/assets` inside each scratch dir `~/.cka-arena/scratch/<tab_id>/` and export `CKA_ASSETS=~/.cka-arena/assets`.
     - Update `ca-helm-upgrade.json` and the Builder prompt to reference `./assets/...` (working both at the repo root in the Probe and inside any browser terminal tab).
  3. **UX polish in Workspace and Studio (`static/index.html`, `static/js/`):**
     - Expose `ssh_target` and `destructive` in `SessionService.get()`. Render the SSH pill in the Workspace only when `ssh_target` is not null (or point dynamically to `ssh cka-<ssh_target>` instead of the fixed `ssh cka-node01` at `workspace.js:98`).
     - Include the results of the active question's last `check_run` in the `GET /api/sessions/{id}` payload, so an F5 in the browser does not wipe the diagnostics drawer.
     - Add a **Cancel** button (`POST /api/generate/cancel`) on the Studio Live Job Card using `asyncio.Task.cancel()` with clean cleanup of the active probe.
     - At startup (`lifespan` of `app/main.py`), mark any `generation_requests` left in `status='running'` by abruptly terminated processes as `status='aborted'`.
     - Add a **Check ⌘↵** button on the terminal footer bar (`static/index.html:80-94`), aligning the implemented UI with what `README.md`/`PLAN.md` specify.

- **Expected Impact:** Exam experience identical to the official test, zero relative-path failures in Helm/Kustomize questions and full job control in the UI.
- **Acceptance Criteria:** A complete `mock_exam` session computing the weighted score (`earned_weight/total_weight`); the `helm upgrade` of `ca-helm-upgrade.json` executable copying straight from the terminal scratch without `cd`; job cancellation cleaning up the ephemeral probe namespace.

---

### Front 6 (P2) — Infrastructure, Concurrency, LLM Ops & Code Hygiene
**Goal:** Guarantee operational stability under multiple uses, cross-provider compatibility (Multipass and `kind`), local model support and clean code.

- **Technical Changes:**
  1. **Cluster governance (`ClusterLease`) & single Engine (`app/main.py`):**
     - Share a **single instance** of `ScenarioEngine` across `SessionService`, `GenerationPipeline` and `Teardown`.
     - Introduce a `ClusterLease` coordinator preventing destructive conflicts: `reset-baseline` and `power stop/restart` return `409 Conflict` if a generation is running; generation with `node_commands` or `destructive=True` is blocked while a practice session is active (while purely namespace-scoped generation may use isolated `cka-prove-*` or warn).
  2. **SSH performance and `MultipassProvider` (`app/provider/multipass.py`, `app/ssh_runner.py`):**
     - Add a short-TTL cache (e.g. 20s) to the `MultipassProvider.nodes()` result, invalidated immediately on SSH errors or `ClusterPowerManager` actions.
     - Enable OpenSSH `ControlMaster=auto`, `ControlPath=~/.cka-arena/ssh-mux-%r@%h:%p`, `ControlPersist=120s` in `_ssh_base()` (`app/ssh_runner.py:104-113`), cutting the latency of repeated node commands from ~130ms to ~15ms.
  3. **Provider-agnostic Teardown & taint baseline (`app/teardown.py`):**
     - Migrate `cleanup_session()`, `reset_clean()` and `drift()` from `ssh_runner.sudo_run(ip, ...)` to `provider.get().exec(name, ..., sudo=True)`, making L1/L2/drift 100% functional on the `kind` provider too (WSL2).
     - Capture the baseline list of node taints and labels in `ClusterDoctor`, and in `reset_clean()` remove any divergent taints/labels added during scenarios (not just `cka-arena/practice=critical:NoSchedule-`).
  4. **LLM Client v2 & observability (`app/llm_client.py`, `app/db.py`, `static/js/settings.js`):**
     - Persist `thinking` and `reasoning_effort` in `save_config()` and expose a selector in the UI under **Settings → AI provider**.
     - Add an **`ollama`** preset (`http://127.0.0.1:11434/v1`, `openai` protocol, no real API key required — accepting the placeholder `"ollama"`) and allow typing a custom `model` in the UI beyond the dropdown presets.
     - Reuse a single persistent `httpx.AsyncClient` per instance (closed on `lifespan` shutdown).
     - Extend `llm_generations` with columns `job_id`, `duration_ms`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens` and surface generation health metrics in the Studio (7d publication rate, average time per question and top failure reasons).
  5. **Repository hygiene and test suite:**
     - Remove `data/arena.db` (0 bytes, orphan) and verify/move stray YAMLs in the root (`deploy.yaml`, `role.yaml`, `rolebinding.yaml`) to `scenarios/examples/` or remove them if they are old manual tests.
     - Resolve the dead tables `terminal_sessions` and `command_audit` (0 rows): implement opt-in auditing (G9) or remove them from the schema until prioritized.
     - Fix the broken test `tests/test_composer.py:89` (`if False`) and add regression tests covering all new gates, `Smart Settle`, `len_gte`, `INVALID` vs `ERROR`, `assistant` history, pre-cleanup digest and `ClusterLease`.

- **Expected Impact:** Zero race conditions on the cluster, SSH ~8× faster, full Multipass/kind parity in teardown, offline Ollama support and LLM cost/latency visibility.
- **Acceptance Criteria:** Expanded `pytest` suite 100% green; SSH latency measured in `doctor.health()` < 25ms after socket warm-up; L1/L2 tested against a mock `KindProvider`.

---

## 5. Execution Roadmap in 4 Waves

| Wave | Fronts | Est. Duration | Main Deliverables | Measurable Acceptance Criterion |
| :--- | :--- | :---: | :--- | :--- |
| **Wave 1 — Surgical Stabilization (P0)** | Front 1 + Smart Settle + Warm Probe + `len_gte`/`INVALID` | **2–3 days** | `assistant` history across retries; pre-cleanup digest; `len_gte` + `INVALID` + probe timeout; complete `BUILDER_SYSTEM`; reordering D1/D2 → C → E; `--dry-run=server` on `solution.manifests`; JSON `-p` gate / immutable fields / anti-spoiler; `Smart Settle` + `Warm Probe` | Batch of 5 `exam_standard` completes in **< 3 min** with **≥ 90% publication**; `Check` with `Pending` pod responds in **< 3s**; 0 false `infra_error` from invalid params |
| **Wave 2 — Generation Engine v2 (P0)** | Front 2 + Ephemeral Isolation + New Checks | **4–5 days** | `app/curriculum.py` (35–40 CNCF 2025/2026 archetypes); `app/planner.py` (5×3 coverage + neutral namespaces + `avoid_recent`); dynamic few-shot; Causal Incident Blueprints replacing the Frankenstein Composer; parallel probes in `cka-prove-*`; 3 new check types + operators | Batch of 5 `exam_standard` + 3 `killer_hardcore` + 2 `boss_fight` covering **5/5 domains**, **≥ 90% publication**, **0 spoilers**, **0 clones**, **0 disconnected Frankensteins**, average **< 45s/question** |
| **Wave 3 — Bank, Curation & Real Mock Exam (P1)** | Front 4 + Front 5 | **3–4 days** | `times_used`/`total_weight`/`avg_solve_seconds` telemetry; Bank & Quarantine Inspector API + UI; `Report / Retire` button; sanitization of the 71 current drafts and clones; `mock_exam` mode (120 min, flag, weighted score); assets symlink in the scratch; `Check` button in the terminal and `Cancel` in the Studio | A 15-question `mock_exam` end-to-end functional with weighted score; `ca-helm-upgrade` solvable straight from the terminal scratch; quarantine inspectable/repairable in the UI |
| **Wave 4 — Resilience, SSH/Kind & LLM Ops (P2)** | Front 6 | **2–3 days** | `ClusterLease` + single `ScenarioEngine`; node TTL cache + SSH `ControlMaster`; `teardown.py` via `provider.exec`; taint/label baseline; `thinking`/Ollama/custom model in the UI; `llm_generations` with tokens and duration; repo cleanup and tests | Expanded `pytest` 100% green; SSH in < 25ms; L1/L2 green on `KindProvider` and `MultipassProvider`; 0 zombie `generation_requests` after restart |

---

## 6. Risks, Trade-offs and Architectural Decisions

1. **Own orchestration vs. LangGraph/LangChain (decision upheld):**
   The current problems are **not** caused by the absence of an agent framework, but by flow bugs (missing `assistant` history, post-cleanup digest, absence of a Slot Planner and blind `settle()`). Keeping the own state machine in `async Python` remains the fastest, leanest and easiest-to-debug choice. *Revisit trigger:* only if in the future we want to give an interactive `kubectl` shell to an authoring agent iterating autonomously on highly exploratory control-plane scenarios.
2. **Trade-off: Warm Probe Pod × `NetworkPolicy`:**
   A shared pod in the `cka-arena-system` namespace may receive traffic or be blocked differently from a pod in the scenario's namespace when there is a `NetworkPolicy` filtering by `podSelector` or `namespaceSelector`. **Mandatory safety rule:** the validator uses the Warm Probe Pod only when the scenario neither declares nor applies a `NetworkPolicy` in the target namespace (or when the check explicitly sets `probe_scope: "external"`). Scenarios with `NetworkPolicy` keep using a pod inside the namespace (`label_selector` of `client`/`intruder` or an ephemeral pod in the namespace itself).
3. **Trade-off: parallel probes × shared cluster state:**
   Running probes in parallel greatly speeds up large batches, but scenarios with `node_commands`, cluster-scoped `PersistentVolume`, `taints`, `ClusterRole`/`ClusterRoleBinding`, `GatewayClass` or `destructive: true` change global cluster state. **Isolation rule:** only purely namespace-scoped scenarios run under the concurrent semaphore (max 2 at a time, with temporary namespace rewrite to `cka-prove-<slot>-<hex>`); all others automatically acquire the exclusive cluster lock.
4. **Trade-off: cost/latency × model per tier and stage:**
   With `deepseek-flash` (fast), generation calls take ~5s vs. 45–90s with reasoning on. **Recommended policy:**
   - Normalizer (A), Reviewer (C), 1st pass of `exam_standard` (B) and 1st repair (R1): **fast model (`thinking off` / effort `low`)**.
   - 1st pass of `killer_hardcore` / `boss_fight` (B): **main model (`model`)** in fast mode or low effort, using the few-shot exemplar and the causal blueprint.
   - 2nd repair (R2) and retries after a complex probe failure on hard tiers: trigger **`deep=True`** selectively.
   - Local **Ollama** support as a free offline option in the UI, mindful that local 7B–14B models will have a lower 1st-attempt approval rate in `killer_hardcore`/`boss_fight` than frontier models via API.

---

## 7. Status & Evidence After Implementation

All 4 waves (6 fronts) were implemented and verified against the automated suite, the SQLite bank, the LLM provider (`deepseek` / `deepseek-flash`) and the live Multipass Kubernetes cluster (`controlplane`, `node01`, `node02`).

### Before vs. After Comparison (Observed)

| Metric | Before | After (Measured) | Evidence / Command |
| :--- | :--- | :--- | :--- |
| **Test Suite** | `106 passed` (with `test_composer.py` neutralized by `if False`) | **`124 passed, 0 failed, 0 skipped`** in `45.58s` + **`node --check` OK** on the 8 `static/js/*.js` files | `.venv/bin/pytest -q` (`test_planner.py`, `test_smart_settle_and_api.py`, `test_composer.py`) |
| **Seed Validation (Real Cluster)** | blind `settle()` + `ca-helm-upgrade` coupled to the host path + 2 seeds with symptom spoilers | **`17/17 PROBE OK`** in **`2m 00.65s`** (`cka-probe-runner` 1/1 Running on `node02`) | `.venv/bin/python -m app.seed validate` (after the anti-spoiler fix in `ts-crashloop-fix.json` and `ts-image-pull.json`) |
| **LLM Quarantine / Publication** | **60.2%** historical quarantine (`71` drafts vs `47` published) | **`7/7` published (`100%`), `0` quarantined (`0%`)** in the live benchmark | Pipeline v2 on all 3 tiers (`exam_standard` 3/3, `killer_hardcore` 2/2, `boss_fight` 2/2) |
| **Generation Speed (`exam_standard`)** | `~29 min` (`1,734.6s`) for 5 questions | **`34.3s` for 3 questions** (`~11.4s`/question) with probes in parallel in ephemeral namespaces | `GenerationPipeline` benchmark (`q-580070cb3005`, `q-637e1e6d8a5e`, `q-68967483835d`) |
| **Quality & Diversity (`killer` / `boss`)** | 67% `"Repair N cluster faults..."` fallbacks · 12/14 in S&N · multiple `:` Frankensteins | **`killer_hardcore` 2/2 in `314.3s`** + **`boss_fight` 2/2 in `354.1s`** with cohesive causal incidents in a single stack, neutral namespaces (`billing`, `reviews`, `reporting`, `ingest`, `notifications`, `gateway-edge`), `0` spoilers and real `docs_links` | Direct inspection of `q-9d61d6afe97d`, `q-f7cb242f5261`, `q-be9cf367b3ec`, `q-4ee23d479628` |
| **SQLite Bank Sanitization** | `64` published · `71` drafts · orphan `running` jobs | **`5` interrupted jobs recovered**; `prune --apply` removed **`71` drafts** and archived **`9` Composer `:` + `4` duplicates** → final bank: **`58` published, `0` drafts, `13` retired** | `.venv/bin/python -m app.bank prune --apply` + post-benchmark |
| **SSH, Terminal & Drift Infra** | SSH without multiplexing · terminal scratch broke `./assets` · `teardown.py` coupled to SSH | `doctor.health()`: **`0.68s` / `0.64s`** (`ssh_ms`: **`12.4–13.4ms`** via `ControlMaster`) · symlink `./assets` + `CKA_ASSETS` ok in the scratch · `Teardown.drift()` == **`False`** (`0` diffs across the 3 nodes) | Direct check in `app/terminal.py`, `app/doctor.py`, `app/teardown.py` and mock `KindProvider` |
