# Gap Analysis & Improvements — CKA Arena

> **Historical record (audit of 2026-11-17, three revisions) — frozen.** The diagnosis that originated the current specifications; it is not updated and does not describe the current state of the code (the UI, endpoints, and terminal changed after this). Current state: `README.md`, `ARCHITECTURE.md`, and the `LLM_*` specs. The author's private environment identifiers were genericized.

> Audit of the existing documentation (`PLAN.md`, `ARCHITECTURE.md`, `LLM_SCENARIO_SPEC.md`, `UX_UI_SPEC.md`, `README.md`) against the real environment and the user's new requirement: **terminal in the browser itself** + **button to power on the cluster together with the application**.
>
> Audit date: 2026-11-17 · Auditor: automated analysis with live verification of the environment.

---

## 0. Evidence Collected in the Environment (Ground Truth)

Checks executed on the machine during this analysis:

| Check | Command | Result |
| :--- | :--- | :--- |
| VM state | `multipass list` | `controlplane`, `node01`, `node02` — **Running**, with IPs on the Bridged network (local subnet) + Multipass NAT IPs |
| Cluster health | `kubectl --context cka get nodes -o wide` | **3/3 Ready**, `v1.37.2`, `containerd://2.2.1`, kernel `5.15.0-203-generic (arm64)` |
| kubectl context | `kubectl config get-contexts` | Context `cka` is the **current** one; other (work) contexts also exist in the same kubeconfig |
| SSH to nodes (Bridged network) | `nc -z -G 2 <ip> 22` | **OK on all 3 nodes** (`PasswordAuthentication yes`, user/password `ubuntu`/`ubuntu` per `01-setup-hosts.sh`) |
| Tools on the Mac | `which` | `kubectl`, `helm`, `etcdctl`, `multipass` **present** |
| Tools missing on the Mac | `which` | `tmux` **missing**, `ttyd`/`gotty`/`wetty` **missing** |
| Current platform state | `ls ~/.cka-arena` | Does **not exist yet** (no provisioning done) |
| `~/.ssh/config` | `grep cka` | **0 occurrences** — the CKA Arena managed block has not been created yet |
| LLM reference standard | Own multi-provider client | Catalog (GLM Coding Plan/Anthropic-protocol, OpenCode Go, DeepSeek, Anthropic, OpenAI-compatible) + `llm_config.json` with `provider/model/api_key/timeout_s`, configurable from the UI |
| Cluster provisioning | `deploy-virtual-machines.sh` + `scripts/01-setup-hosts.sh` | `BUILD_MODE=BRIDGE`; password `ubuntu:ubuntu` via `chpasswd`; `PRIMARY_IP` exported in the nodes' `/etc/environment` |

**Conclusion:** the technical base described in the documents is real and verified. The gaps below are **planning** gaps, not feasibility ones.

---

## 1. Strengths to Keep (The Plan Already Gets It Right)

1. **Deterministic validation by resulting state** (never by typed command) — same as KodeKloud/Killer.sh; the `ScenarioEnvelope` contract with 10 check types is solid and **remains valid unchanged**.
2. **LLM self-healing pipeline** (schema gate → blocklist → dry-run → apply → "golden rule" sanity check → retry with the exact error) — the right pattern for generation reliability.
3. **Snapshot & Rollback in 3 layers** (global baseline + pre-command backup + parser guardrails) — necessary for scenarios that break the control plane.
4. **Dynamic IP discovery via `kubectl get nodes -o json`** instead of hardcode — the right decision (see G3 for the cluster-powered-off case).
5. **Complete CNCF 2025/2026 curriculum matrix** with 5 domains and correct weights, including new topics (Gateway API, native sidecar, Helm/Kustomize).
6. **Anti-triviality sanity check** (a scenario born 100% PASS is regenerated) — a detail most generators ignore.

---

## 2. Critical Gaps (Block the New Requirement)

### 🔴 G1 — Central contradiction: "Zero Terminal in the Browser" × new requirement "terminal in the browser"
- **Evidence:** `PLAN.md` decision no. 1 ("Zero Terminal no Browser... o terminal nativo do Mac executa kubectl e ssh" [original pt-BR: Zero Terminal in the Browser... the Mac's native terminal runs kubectl and ssh]) and `UX_UI_SPEC.md` §1 (40/60 ergonomics with a mandatory native terminal).
- **Impact:** the entire UX (480px split, wireframe, copy-pills designed for a narrow window) and the architecture (the backend has no terminal component at all) need to be revised.
- **Fix applied:** decision no. 1 rewritten to **Integrated Web Terminal (default) + native terminal mode (optional)**. A new `TerminalService` component specified in `ARCHITECTURE.md` §8; new layout in `UX_UI_SPEC.md` §2. The user can keep using the native terminal if preferred — the embedded one becomes the primary flow, which **enables the Check button next to the terminal** (requirement: "executar os comandos dos cenarios e pedir validaçao" [original pt-BR: run the scenario commands and ask for validation] in the same place).

### 🔴 G2 — Total absence of cluster lifecycle management (power on/off)
- **Evidence:** no document mentions `multipass start/stop`. The `ClusterDoctor` assumes an already-healthy cluster; `ARCHITECTURE.md` §4 talks about restoring the baseline via SSH but not about **booting the VMs**.
- **Impact:** the user's central requirement ("cluster inicializado junto com a aplicação, com botão na tela para ligar" [original pt-BR: cluster started together with the application, with an on-screen button to power it on]) has no owner in the design.
- **Fix applied:** new component **ClusterPowerManager** (`ARCHITECTURE.md` §9): state machine `off → starting → ready → degraded`, endpoint `POST /api/cluster/power`, instrumented boot sequence (VMs → SSH 22 → ssh-config regen → `/readyz` → nodes Ready → quick doctor → baseline if absent) with progress via SSE. UI: state pill in the header + "Ligar Cluster" [Power On Cluster] CTA when `off` (`UX_UI_SPEC.md` §3). Optional `auto_start_on_launch` flag in Settings.

### 🔴 G3 — Bridged IPs are DHCP: kubeconfig and `~/.ssh/config` can break after VM reboot
- **Evidence:** `deploy-virtual-machines.sh` uses `--bridged` (router DHCP); `README.md`/`ARCHITECTURE.md` treat lab IPs as fixed; the `cka` context kubeconfig points to the controlplane IP hardcoded.
- **Impact:** if DHCP reassigns IPs after `multipass stop/start`, **everything** stops working (kubectl, SSH, checks) with no obvious diagnosis. This is the gap most likely to become a real incident.
- **Fix applied:** at the end of boot, the PowerManager (a) reads current IPs via `multipass list --format json`, (b) **regenerates the managed block** `# >>> CKA-ARENA MANAGED >>>` in `~/.ssh/config`, and (c) performs **kubeconfig self-heal**: if `kubectl --context cka get --raw /readyz` fails but SSH responds, it downloads `/etc/kubernetes/admin.conf` from the controlplane via SSH, rewrites `server: https://<ip-atual>:6443`, and updates the `cka` context via `kubectl config set-cluster`. Detailed in `ARCHITECTURE.md` §9.3.

### 🔴 G4 — SSH key bootstrap: first-run flow unspecified (and no `sshpass`)
- **Evidence:** `PLAN.md` Phase 1 mentions "solicitando/usando a senha padrão do lab `ubuntu` uma única vez" [original pt-BR: asking for/using the lab's default `ubuntu` password a single time], but with no mechanism; `sshpass` is **not installed** on the Mac (verified).
- **Fix applied:** **`SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`** (OpenSSH ≥ 8.4) to install the public key without interaction — without `sshpass` and without expect. Specified in `ARCHITECTURE.md` §3 (item 5) and validated during the Phase 1 implementation.

### 🔴 G5 — No web terminal component specified (neither backend nor frontend)
- **Evidence:** `ARCHITECTURE.md` §5 (directory tree) has no `terminal.py` nor xterm assets; `pyproject` dependencies list nothing WebSocket/PTY-related.
- **Impact:** central requirement with no design.
- **Fix applied:** complete **TerminalService** in `ARCHITECTURE.md` §8: in-process PTY (`pty.openpty` + `TIOCSWINSZ` + reader task per session, zero extra dependencies — FastAPI/uvicorn already support WebSocket), frontend `xterm.js` **vendored in `static/vendor/`** (no CDN, works offline), tabs with presets (`mac`, `controlplane`, `node01`, `node02`), resize, reconnect on page reload (PTY lives in the backend), session limit and idle timeout. **Rejected** alternatives: `ttyd`/`gotty` (external binary, no telemetry audit, no lifecycle control) and `tmux` (not installed — verified; unnecessary given PTY recording in the backend).

---

## 3. Medium Gaps (Real Risks, Non-Blocking)

### 🟡 G6 — Sanity check can produce a false "scenario OK" due to image pull latency
- **Evidence:** `LLM_SCENARIO_SPEC.md` stage 4 applies setup and runs checks immediately; a `pod_status_ready` check can "fail initially" merely because the image is still downloading — and **pass on its own** seconds later, or worse: a legitimate scenario rejected because the check took too long to fail for a real state.
- **Proposed fix:** after the apply, wait for a **settle window** (pods reaching a stable condition: `Running`/`CrashLoopBackOff`/`ImagePullBackOff` or a 90s timeout) **before** running the sanity check; documented as a pipeline improvement (P1) in `PLAN.md` Phase 3.

### 🟡 G7 — `multipass` daemon down is not handled
- **Evidence:** `deploy-virtual-machines.sh` has watchdogs for a stuck daemon (comments in the script), but the CKA Arena plan ignores the case.
- **Proposed fix:** PowerManager detects `multipass list` failing and returns state `daemon_down` with an actionable instruction (`sudo launchctl kickstart -k system/com.canonical.multipass`). Added to `ARCHITECTURE.md` §9.

### 🟡 G8 — Terminal WebSocket security unspecified
- **Evidence:** new attack vector: host shell PTY exposed via WS. Remote exposure (e.g., a tunnel in front of the port) is an intended use by whoever accesses their own machine from outside.
- **Fix applied:** terminal WS **only on `127.0.0.1`**, `Origin` header validation (same-origin), explicit refusal if the app is bound outside loopback without auth, permanent warning on the Settings screen. `ARCHITECTURE.md` §10.

### 🟡 G9 — Current telemetry does not see *how* the user solved it
- **Evidence:** `check_runs` records attempts, but nothing captures the approach (imperative × declarative, use of `--dry-run`, etc.).
- **Proposed fix (optional, opt-in):** with the terminal in the browser, the backend can keep a ring buffer of the PTY and extract commands (split on prompt) linked to the active `scenario_id` — a `command_audit` table. **Privacy:** local-only, opt-in in Settings, purge per session. `ARCHITECTURE.md` §6.

### 🟡 G10 — Port collision and kubeconfig conflict with other projects
- **Evidence:** app planned on `8765` (free port). However, the shared `~/.kube/config` contains **other work contexts** (verified); any backend `kubectl` operation **must** always pass an explicit `--context cka` (never trust the current-context, which the user switches during the day).
- **Fix applied:** explicit rule in `ARCHITECTURE.md` §3 (the `cluster.py` wrapper always injects `--context`); the backend uses a dedicated kubeconfig `~/.cka-arena/kubeconfig` copied from `admin.conf` at the first doctor (immune to the user's current-context switches).

### 🟡 G11 — `etcd` restore scenarios: `etcdctl` exists on the Mac, but restore must run on the node
- **Evidence:** `/opt/homebrew/bin/etcdctl` present on the Mac; however, CKA snapshot/restore requires the certificates and the `etcdctl` of the correct version **on the controlplane**, with API v3 and `--data-dir`.
- **Proposed fix:** the generator spec (system prompt) must already restrict etcd commands to `node: controlplane` via SSH; added as a note in `LLM_SCENARIO_SPEC.md` (check `node_command_exit_zero` with `node: controlplane`). *(Minor adjustment applied to the template in §4 of the spec.)*

### 🟡 G12 — Weave Net × NetworkPolicy: dependency on `weave-npc`
- **Evidence:** NetworkPolicy scenarios assume enforcement; Weave only enforces NetworkPolicy if `weave-npc` is running.
- **Proposed fix:** `ClusterDoctor` checks `weave-npc-*` pods and reports the addon "NetworkPolicy enforcement: on/off". Added to the addons list in `ARCHITECTURE.md` §7.

---

## 4. Recommended Improvements (Prioritized)

| ID | Improvement | Priority | Where it lands |
| :--- | :--- | :--- | :--- |
| M1 | Integrated web terminal (PTY + xterm.js) with per-node tabs and Check within reach | **P0** | `ARCHITECTURE.md` §8, `UX_UI_SPEC.md` §2, `PLAN.md` Phase 2/4 |
| M2 | Cluster Power Manager with instrumented boot + "Ligar Cluster" [Power On Cluster] CTA + `auto_start_on_launch` | **P0** | `ARCHITECTURE.md` §9, `UX_UI_SPEC.md` §3, `PLAN.md` Phase 1 |
| M3 | kubeconfig self-heal + SSH block regeneration post-boot (DHCP) | **P0** | `ARCHITECTURE.md` §9.3 |
| M4 | Dedicated kubeconfig `~/.cka-arena/kubeconfig` (immune to the user's current-context) | **P1** | `ARCHITECTURE.md` §3 |
| M5 | Key bootstrap via `SSH_ASKPASS` (without `sshpass`/expect) with manual fallback | **P1** | `ARCHITECTURE.md` §3 |
| M6 | Settle window before the sanity check (G6) | **P1** | `PLAN.md` Phase 3 |
| M7 | Optional terminal command audit → approach telemetry | **P2** | `ARCHITECTURE.md` §6, §8.5 |
| M8 | Provider catalog (GLM/OpenCode/DeepSeek/Claude/OpenAI-compat) as the base of `llm_client.py` | **P1** | `PLAN.md` Phase 3 |
| M9 | multipass `daemon_down` state with correction instruction | **P1** | `ARCHITECTURE.md` §9 |
| M10 | Import of an external study history for next-domain recommendation | **P2** | `PLAN.md` Phase 5 |
| M11 | Gateway API / metrics-server / local-path: install via Cluster Doctor with `weave-npc` detection | **P1** | `ARCHITECTURE.md` §7 |

---

## 5. Integration Decisions (Synthesis of What Was Specified)

```mermaid
flowchart LR
    subgraph Browser["Browser — http://127.0.0.1:8765 (single window)"]
        UI["Exam Workspace\n(question · check · timer)"]
        Term["Integrated Terminal (xterm.js)\ntabs: mac · controlplane · node01 · node02"]
        Pwr["Cluster Pill: ⏻ Off / ⟳ Starting / ● Ready"]
    end
    subgraph Backend["FastAPI (127.0.0.1)"]
        WS["/ws/terminal/{tab}\nTerminalService (host PTY)"]
        PM["ClusterPowerManager\nmultipass start/stop + boot checks"]
        SE["ScenarioEngine\nsetup → check → cleanup"]
        LLM["LLM Generator\n(envelope + self-healing)"]
    end
    Term <-->|WebSocket| WS
    WS -->|zsh on host: kubectl/ssh/helm| Host["macOS Host"]
    Pwr -->|POST /api/cluster/power| PM
    PM -->|multipass CLI| MPX["Multipass Daemon\ncontrolplane · node01 · node02"]
    PM -->|SSH bridged (dynamic IPs)| MPX
    UI -->|Check| SE
    SE -->|kubectl --context cka / SSH| MPX
    LLM -->|envelope| SE
```

**Fixed principles:**
1. The terminal runs **on the macOS host** (where `kubectl`, `helm`, `~/.ssh/config` live) — never inside a container; node tabs are automatic `ssh cka-<node>`.
2. A **single active scenario at a time** in the cluster (next one's setup only on the Next click) — rule kept.
3. The terminal is **persistent in the backend**: a page reload reconnects to the same PTY (session registry by `tab_id`).
4. `Check` is reachable **from the terminal panel** (button + global shortcut ⌘↵) — the "run and ask for validation" requirement in the same place.
5. Cluster `off` **blocks** Studio and Workspace; the only available action is Power On (or restoring the baseline with the cluster in a degraded state).

---

## 6. Traceability Matrix (Gap → Documentation)

| Gap | Fix documented in |
| :--- | :--- |
| G1 browser terminal | `ARCHITECTURE.md` §1/§5/§8 · `UX_UI_SPEC.md` §1/§2 · `PLAN.md` §3.1 |
| G2 lifecycle | `ARCHITECTURE.md` §9 · `UX_UI_SPEC.md` §3 · `PLAN.md` §3.6/Phase 1 |
| G3 DHCP/kubeconfig | `ARCHITECTURE.md` §9.3 |
| G4 key bootstrap | `ARCHITECTURE.md` §3 |
| G5 terminal spec | `ARCHITECTURE.md` §8 · tree §5 · DB §6 |
| G6 settle window | `PLAN.md` Phase 3 |
| G7 multipass daemon | `ARCHITECTURE.md` §9 |
| G8 WS security | `ARCHITECTURE.md` §10 |
| G9 command audit | `ARCHITECTURE.md` §6/§8.5 (opt-in) |
| G10 dedicated kubeconfig | `ARCHITECTURE.md` §3 |
| G11 etcd on the node | `LLM_SCENARIO_SPEC.md` §4 (note) |
| G12 weave-npc | `ARCHITECTURE.md` §7 |

## 7. Out of Scope for This Review

- Code implementation (the project is still in planning; the specs now cover the new requirements).
- Multi-user / remote exposure of the platform (local-only by design; see §10 of the architecture).
- Support for clusters other than the `cka` Multipass one (kind/k3s/minikube) — the architecture allows it in the future via the `ClusterDriver` interface, but it is not planned.


---

## 8. Second Audit — LLM Generation, Question Bank, Check & Teardown (Revision 2)

> New round over: the agent-based generation flow (LangGraph?), the question bank with the exam-weight draw, the Check contract, and the clean reset of the cluster at the end of the session. Resulting specification: **`LLM_PIPELINE_SPEC.md`** (new).

### 🔴 G13 — Generation coupled to the session (no question bank)
- **Evidence:** original `ARCHITECTURE.md` §6: `scenarios` table with `session_id` — the generated queue *was* the session; good questions were not reused and "practice again" required new generation (LLM cost + risk).
- **Fix applied:** full decoupling — generation **publishes** to `bank_questions` (cycle `draft → probed → published → retired`, semantic dedup, immutable envelope, per-question metrics); sessions only reference it (`session_items`). `ARCHITECTURE.md` §6/§11 · `LLM_PIPELINE_SPEC.md` §3.

### 🔴 G14 — No exam-weight draw
- **Evidence:** no document defined how to assemble the practice battery; the old Studio generated N questions straight into the queue.
- **Fix applied:** `draw_exam_sample` with **largest remainder** over the CNCF weights (30/25/20/15/10), renormalization by filters, empty-cell fallback, and anti-repetition (`times_used ASC, random()`); distribution preview in the UI before starting. Calibration: N=15 → 5/4/3/2/1; N=5 → 2/1/1/1/0; N=3 → 1/1/1/0/0. `LLM_PIPELINE_SPEC.md` §4 · `UX_UI_SPEC.md` §5a.

### 🔴 G15 — No guarantee the question is solvable
- **Evidence:** the sanity check only proved that the checks **failed** before the user acted — nothing proved a solution path existed; an unsolvable question would only be discovered during practice (the worst moment).
- **Fix applied:** mandatory **`solution`** block in the envelope (automatable manifests/commands) + **Solvability Probe** in Stage E: applies the solution to a proof clone and requires 100% PASS before publishing. `LLM_SCENARIO_SPEC.md` §1.1 · `LLM_PIPELINE_SPEC.md` §2E.

### 🔴 G16 — End-of-session teardown nonexistent
- **Evidence:** cleanup was only per question (`cleanup(scenario)`); aborting a session mid-Boss-Fight left residue accumulating across sessions. The "cluster zeroed and restarted clean" requirement had no owner.
- **Fix applied:** teardown in 3 levels — **L0** per question, **L1** end of session (label sweep `cka-arena.io/managed` + drift check) and **L2 clean reset** (L1 + restoration of the nodes' file baseline + restart of `containerd`/`kubelet` + drift check). **Phase 5 update (live evidence):** VM snapshots are **not implemented** in the Multipass/macOS backend (`The snapshots feature is not implemented on this backend`) — L2 was redefined without snapshots and validated with `drift=false`, 3/3 Ready, and addons preserved. `LLM_PIPELINE_SPEC.md` §6 · `ARCHITECTURE.md` §12 · `UX_UI_SPEC.md` §5b.

### 🟡 G17 — Check semantics informal
- **Evidence:** the catalog defined *what* to verify, but not *how to decide*: no FAIL (user state) × ERROR (infra) distinction, no retry policy, no formal question verdict.
- **Fix applied:** formal contract — status `PASS`/`FAIL`/`SKIP`/`ERROR` with a retry policy (FAIL never re-runs on its own; ERROR 2× with backoff; an invalid round does not consume an attempt), **all-or-nothing** verdict (like the real CKA), `expected/actual` evidence per item, hint with progressive reveal, per-type timeouts, and settle window. `LLM_PIPELINE_SPEC.md` §5 · `LLM_SCENARIO_SPEC.md` §2.

### 🟡 G18 — Agent framework (LangGraph/LangChain) without a recorded evaluation
- **Evidence:** the user's proposal of 3 chained agents (normalizer → builder → validator) with no orchestration analysis.
- **Fix applied:** comparative evaluation (`LLM_PIPELINE_SPEC.md` §1): the 3 agents **are kept** as LLM stages with a strict contract, orchestrated by an **own state machine in async Python** — no LangGraph/LangChain (a linear flow with limited retries does not justify the weight/dependency/churn; provider independence already comes from the own multi-provider client). Revisit triggers documented (autonomous tool-use, resumable human-in-the-loop).

### Revision 2 Traceability

| Gap | Fix documented in |
| :--- | :--- |
| G13 bank | `LLM_PIPELINE_SPEC.md` §3 · `ARCHITECTURE.md` §6/§11 · `PLAN.md` Phase 3 |
| G14 draw | `LLM_PIPELINE_SPEC.md` §4 · `UX_UI_SPEC.md` §5a · `PLAN.md` verification 6 |
| G15 solvability | `LLM_SCENARIO_SPEC.md` §1.1 + rule 10 · `LLM_PIPELINE_SPEC.md` §2E |
| G16 teardown | `LLM_PIPELINE_SPEC.md` §6 · `ARCHITECTURE.md` §12 · `UX_UI_SPEC.md` §5b · `PLAN.md` Phases 1/2 |
| G17 check contract | `LLM_PIPELINE_SPEC.md` §5 · `LLM_SCENARIO_SPEC.md` §2 |
| G18 orchestration | `LLM_PIPELINE_SPEC.md` §1 (comparison + triggers) |

---

## 9. Third Audit — Language, Exam Format and Difficulty (Revision 3)

> Scope change from the owner: **system 100% English** (the CKA exam is in English), questions in the **exact exam format** and difficulty levels **measurably distinct**.

### 🔴 G19 — System specified in pt-BR, opposite to the exam language
- **Evidence:** envelope with `prompt_pt_br`/`reference_solution_pt_br`, rule 1 of the system prompt requiring "Português do Brasil" [Brazilian Portuguese], UI with labels `[Verificar]`/`[Próxima]`/`[Ligar Cluster]` [Check/Next/Power On Cluster] in all wireframes and the mockup.
- **Impact:** training by reading tasks in pt-BR does not build the muscle memory of reading the question prompt in English — a real part of exam performance.
- **Fix applied:** fields renamed `prompt`/`reference_solution`; rule 1 of the prompt and the Reviewer's rubric (item 6) require **exam voice in English**; UI 100% English in all specs, wireframes, CTAs (`[Check]`, `[Next]`, `[Skip]`, `⏻ Power On & Practice`, `▶ Practice`, `SESSION COMPLETE`…) and the mockup. `PRODUCT.md` records the commitment; internal docs stay in pt-BR. Format reference: [killer.sh](https://killer.sh/cka) (official simulator) — new section `LLM_SCENARIO_SPEC.md` §1.2 with the exact anatomy (imperative title · Task weight · Use context · context-symptom · "Perform the following tasks" · restrictions).

### 🔴 G20 — Subjective difficulty levels (not verifiable)
- **Evidence:** the previous definition of the levels was prose ("1 to 2 clear requirements…") with no measurable band nor enforcement — a weak `boss_fight` would pass.
- **Fix applied:** **measurable rubric** (`LLM_SCENARIO_SPEC.md` §5): 8 axes measured straight from the envelope (requirements, kinds, scope, traps, causal chain, checks, time target, weight) with disjoint bands per level + **enforcement in the Reviewer** (outside the band in ≥ 2 axes ⇒ regeneration with delta) and at Gate D (a `boss_fight` without node failure is rejected). Recalibrated targets: ≤ 4 / ≤ 7 / ≤ 12 min; calibrated examples of the same domain at the three levels illustrate the real separation.

### 🟡 G21 — Question format did not adhere to the exam standard
- **Evidence:** the old `prompt` was free prose in pt-BR ("No namespace X, existem os deployments…" [original pt-BR: In namespace X, there are the deployments…]), with no title, no `Task weight`, no "Use context:", no restrictions block.
- **Fix applied:** canonical exam anatomy (§1.2) as an obligation of the Builder and a criterion of the Reviewer; the Phase 3 acceptance criterion (`PLAN.md`) requires a question "(a) in English in the exact exam format".

### Revision 3 Traceability

| Gap | Fix documented in |
| :--- | :--- |
| G19 language | `LLM_SCENARIO_SPEC.md` §1/§1.2/§4-rule 1 · `LLM_PIPELINE_SPEC.md` §2 A–C · `UX_UI_SPEC.md` §1/labels · `PRODUCT.md` · `README.md` · `design/mockup-workspace.svg` |
| G20 difficulty | `LLM_SCENARIO_SPEC.md` §5 (+ rule 2 of the prompt) · `PLAN.md` §2 and Phase 3 |
| G21 exam format | `LLM_SCENARIO_SPEC.md` §1.2 · `PLAN.md` Phase 3 (acceptance criterion) |
