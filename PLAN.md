# Master Implementation Plan — CKA Arena

> **Historical record (November 2026) — frozen.** Original master plan and roadmap, with the acceptance evidence for each phase. It is not updated and does not describe the current state of the code: the UI, endpoints, and pipeline changed after this was written. Current state: `README.md` and `ARCHITECTURE.md`. Translated from the original pt-BR.

This document consolidates the reference research, technical feasibility analysis on the local `kubeadm` cluster (Apple Silicon / Multipass), UX/UI best practices, and the step-by-step roadmap for building the **CKA Arena**.

---

## 1. Reference Research & Applicable Lessons

We analyzed 5 main references from the CKA preparation ecosystem:

| Platform / Project | What it does best | Limitation in our context | What we adopt in CKA Arena |
| :--- | :--- | :--- | :--- |
| **KodeKloud (Labs)** | Granular checklist on clicking *Check*, clear feedback on which criterion failed, guided step-by-step progression, terminal embedded in the browser. | Static catalog, no on-demand generation. | **Check** button with item-by-item validation and the **Next** gate until 100% approval; **terminal embedded in the browser** (real host PTY, not a limited webapp) — user requirement, see `GAP_ANALYSIS.md` G1. |
| **Killer.sh (Official Simulator)** | Questions deliberately **harder** than the real exam, combining 3–4 requirements in the same task + subtle traps and a strict time limit. | Limited sessions (36h), no unlimited on-demand generation focused on a specific domain. | `Killer.sh Hardcore` and `Boss Fight` difficulty levels, per-question timer (6 min target) and multi-requirement scenarios. |
| **PSI Bridge (Real Exam)** | Explicit banner for the context command (`kubectl config use-context`), question percentage weight, question list with flagging (*Flag*) and direct links to `kubernetes.io/docs`. | Heavy interface via VNC/XFCE and no immediate feedback (*Check*). | PSI-style header with domain/weight badge, context/SSH command copyable with 1 click and allowed links to `kubernetes.io/docs`. |
| **K16S Exam Simulator (`immanuwell/k16s-exam-simulator`)** | Runs on a real `kubeadm` cluster (not `kind`/`k3s`), allowing you to break `kubelet`, `etcd`, certificates and static pods with `systemd`. | No rich graphical interface and no dynamic LLM-based generator. | The architectural pattern of the triad per question: **metadata + setup (cluster/node) + validate (real state)** running on real Linux nodes (`controlplane`, `node01`, `node02`). |
| **CK-X (`sailor-sh/CK-X`)** | Clean separation between cluster state, mock exam timer and validation scripts independent of how the user solved the problem. | Based on fixed scripts; coupled to its own VMs. | Validation **based on resulting state** (not on typed commands): whether the user solved it via an imperative command or YAML edited in `vim`, both pass if the cluster state is correct. |

### Architectural Conclusion of the Research
No existing platform combines:
1. A **real macOS host terminal** (PTY `zsh -l` with your aliases, `.vimrc` and native speed) **embedded in the browser** — with a native terminal as an optional mode +
2. A **real multi-node `kubeadm` cluster** (`v1.37.2`, `containerd`, `systemd`, static pods) with a **lifecycle managed by the platform itself** (on/off button) +
3. An **LLM scenario generation engine** (not a hint tutor) able to invent novel scenarios, apply real faults to nodes via SSH, and deterministically validate the solution.

---

## 2. CKA Curriculum Matrix (CNCF Curriculum 2025/2026)

The platform must structure both the **LLM Generator Studio** and the **Study Telemetry** exactly on the 5 official exam domains and their modern topics:

| Official Domain | Weight | Mandatory Sub-topics (Including 2025/2026 Updates) | Fault/Scenario Examples for the LLM |
| :--- | :--- | :--- | :--- |
| **1. Troubleshooting** | **30%** | `kubelet` (`systemd`, config, certs), Static Pods (`/etc/kubernetes/manifests/`), `kube-apiserver`/`etcd`/`scheduler`/`controller-manager`, `NotReady` nodes, `CoreDNS`, container/pod logs (`CrashLoopBackOff`, `ImagePullBackOff`, OOM), CNI/Weave. | `kubelet` stopped or with wrong `cgroupDriver` / port on `node01`; invalid flag in the `kube-apiserver` manifest; `CoreDNS` with corrupted ConfigMap; `CrashLoopBackOff` caused by wrong env/command. |
| **2. Cluster Architecture, Installation & Configuration** | **25%** | RBAC (`Role`, `ClusterRole`, `RoleBinding`, `ClusterRoleBinding`, `ServiceAccount`), `etcd` snapshot save & restore, **Helm** (install, upgrade, rollback, `--set`, `values.yaml`), **Kustomize** (`kubectl apply -k`, overlays), CRDs & Operators, `kubeadm` (certs check/renew, upgrade plan). | Create an SA with granular permissions across multiple namespaces and validate via `kubectl auth can-i`; `etcd` backup and restore to a specific directory; install/upgrade a Helm release fixing values; apply a Kustomize overlay with a replica/image patch. |
| **3. Services & Networking** | **20%** | **Gateway API** (`GatewayClass`, `Gateway`, `HTTPRoute`, traffic splitting), `Ingress` & `IngressClass`, `NetworkPolicy` (ingress/egress, namespaceSelector, podSelector, DNS port UDP/TCP 53), Services (`ClusterIP`, `NodePort`, endpoints), CoreDNS resolution. | Create an `HTTPRoute` routing `/api` and `/web` with distinct weights; a `NetworkPolicy` allowing traffic from `frontend` to `backend` on port 8080 while **not breaking DNS egress (53)**; diagnose a Service without Endpoints due to a label mismatch. |
| **4. Workloads & Scheduling** | **15%** | Deployments (rolling update, rollback, pause/resume), DaemonSets, Jobs/CronJobs, Multi-container Pods (`initContainers`, **Native Sidecar Containers** `restartPolicy: Always`), `nodeSelector`, `nodeAffinity`, `podAntiAffinity`, Taints & Tolerations, `ResourceQuota`, `LimitRange`, `PriorityClass`. | Deployment blocked by a node taint + mandatory affinity; native sidecar sharing an `emptyDir` volume with the main app; broken rollout requiring rollback to a specific revision and `resources` adjustment. |
| **5. Storage** | **10%** | `StorageClass` (`WaitForFirstConsumer`, `Immediate`, reclaim policy `Retain`/`Delete`), `PersistentVolume`, `PersistentVolumeClaim`, volume expansion, `accessModes`, `hostPath`/`local` on specific nodes. | Create a static PV with exact `storageClassName`, `capacity` and `accessModes` and bind a PVC consumed by a Pod; diagnose a PVC stuck in `Pending` due to a `storageClassName` or `nodeAffinity` mismatch. |

### Selectable Difficulty Modes (measurable rubric — `LLM_SCENARIO_SPEC.md` §5)

> The difference between levels is **verifiable in the envelope** (requirements, resource kinds, traps, causal chain, number of checks, time target, weight) and **enforced by the Reviewer** (Stage C): outside the band on ≥ 2 axes ⇒ regeneration with an explicit delta. Calibrated per-level examples in §5 of the spec.

1. **`Exam Standard` (CKA Standard):** 1–2 requirements, 1 namespace, 0 traps, single-step correction. Target: `≤ 4 min` · weight 2–5.
2. **`Killer.sh Hardcore` (Above Exam):** 3–4 interlinked requirements + ≥ 1 realistic trap (wrong Namespace, `NetworkPolicy` with `egress` blocking DNS 53, `nodeAffinity` + toleration on `node02`, manifest to save at `/opt/...`), diagnose → repair chain. Target: `≤ 7 min` · weight 6–10.
3. **`Boss Fight` (Critical Incident):** 4–6 requirements, node infrastructure failure via SSH (`kubelet`/static pod/systemd) + a dependent workload that only returns to `Ready` after restoring the root cause (chain ≥ 3), ≥ 2 traps. Target: `≤ 12 min` · weight 11–16.

---

## 3. Foundational Technical Decisions

1. **Terminal in the Browser (default) + Native Terminal (optional):** the browser concentrates the question prompt, Check, Studio **and a real terminal** — `TerminalService` with a host PTY (`zsh -l`) rendered in xterm.js over WebSocket, with tabs `mac · controlplane · node01 · node02` and a **Check** button within reach inside the terminal panel (details in `ARCHITECTURE.md` §8). A **Native Terminal Mode** toggle hides the embedded panel and restores the original 40/60 dual-window flow for those who prefer iTerm2/Ghostty.
2. **Backend in Python (`FastAPI` + `Uvicorn` + `SQLite`):**
   - Reuses the ecosystem already validated locally (`Python 3.14`, `uv`, `FastAPI`, `httpx`, `anthropic`).
   - Runs `kubectl` commands (via async subprocess with `--kubeconfig` / `--context=cka`) and direct SSH via `asyncssh` or native `ssh` with `ControlMaster`.
3. **Resilience to `multipass exec` Failure:**
   - As observed during environment verification, `multipass exec controlplane` fails with `No route to host` on the NAT network.
   - **CKA Arena** uses the **Bridged IPs (discovered at runtime)** via `kubectl get nodes -o wide` (with fallback to `multipass list --format json`), provisioning on first run a dedicated SSH key (`~/.cka-arena/id_ed25519`) on the 3 nodes.
4. **Multi-Engine LLM Providers:**
   - Native support for the user's provider catalog (GLM Coding Plan / Z.AI, OpenCode Go, DeepSeek, Anthropic Claude, OpenAI-compatible and local Ollama `qwen2.5-coder:7b-instruct-q8_0`), configured via the UI (Settings → AI provider), persisted in local `llm_config.json` (never copying the key into a versioned repository — read at runtime or stored locally in `.env`/`llm_config.json`, ignored via `.gitignore`).
5. **Anti-Catastrophe Mechanism (Snapshot & Rollback):**
   - Before applying any scenario that touches nodes (`etcd`, `/etc/kubernetes/manifests/`, `/var/lib/kubelet/`, `systemd`), the engine performs an automatic backup to `/var/backups/cka-arena/<scenario_id>/` on the target node.
   - The **`[Reset Question]`** button and the global **`[Cluster Doctor / Restore Baseline]`** button guarantee the cluster never becomes unusable if a test breaks `kube-apiserver`.
6. **Managed Cluster Lifecycle (`ClusterPowerManager`):**
   - The cluster is **started together with the application**: a **"⏻ Power On"** button/CTA on the home page when the VMs are `off`, instrumented 7-step boot via SSE (VMs → SSH → ssh-config regen → `/readyz` → nodes Ready → doctor → baseline) and a permanent status pill in the header (`off/starting/ready/degraded/daemon_down`).
   - Bridged IPs are **DHCP**: on each boot the manager regenerates the `~/.ssh/config` block and performs **self-heal of the dedicated kubeconfig** (`~/.cka-arena/kubeconfig`) if the controlplane IP changed (details in `ARCHITECTURE.md` §9).
   - The `auto_start_on_launch` setting powers the VMs on automatically when the app opens — **default ON** (decision D3 of `IMPLEMENTATION_READINESS.md`).

---

## 4. 5-Phase Implementation Roadmap

### Phase 1: Foundation, Cluster Power Manager, Doctor & SSH Bridge ✅ (implemented and verified on 2026-11-17)
**Objective:** Bring up the local FastAPI server and guarantee 100% stable communication with the Kubernetes API (`v1.37.2`) and with the 3 nodes via Bridged SSH.
- **Deliverables:**
  - Project structure `cka-arena/` with `pyproject.toml` (`uv`), `FastAPI`, `SQLite` (`aiosqlite` or `sqlite3` with WAL), `pyyaml`, `pydantic`, `httpx`.
  - Script/endpoint `setup_ssh_bridge`: tests TCP connectivity on port 22 to the current Bridged IPs (discovered via `multipass list --format json`; `kubectl` only when the cluster is already up), installs the public key `~/.cka-arena/id_ed25519.pub` on the nodes via **`SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`** (OpenSSH ≥ 8.4; no `sshpass` nor expect; lab password via `CKA_LAB_PASSWORD`, default `ubuntu`), writes the managed block in `~/.ssh/config` (`Host cka-controlplane`, `cka-node01`, `cka-node02`) and materializes the **dedicated kubeconfig** `~/.cka-arena/kubeconfig` copied from `admin.conf` (the backend never uses the global `~/.kube/config`, which may contain other contexts).
  - `ClusterPowerManager` module: `GET/POST /api/cluster/power` (start/stop/restart as a single async job), state machine `off → starting → ready → degraded` (+ `daemon_down` with fix guidance), instrumented boot with SSE progress, SSH block regeneration and kubeconfig self-heal post-DHCP.
  - `ClusterDoctor` module: checks health of the 3 nodes, `kube-system` pods, existence of `helm` and `etcdctl`, takes an initial **file baseline** of `/etc/kubernetes/manifests`, `/var/lib/kubelet/config.yaml`, `/etc/containerd/config.toml` and kubelet drop-ins on the nodes — input for the **L2 clean reset** (`LLM_PIPELINE_SPEC.md` §6). *Multipass VM snapshots are not supported on the macOS backend (verified live); the L2 does not depend on them.*
- **Acceptance Criterion:** `GET /api/cluster/health` returns `3/3 Ready`, `kubectl` OK and passwordless SSH working on the 3 nodes in `< 500ms`. With the VMs stopped: `POST /api/cluster/power {"action":"start"}` takes the cluster to `ready` via the instrumented boot (≤ 4 min typical), regenerating `~/.ssh/config` and self-healing the kubeconfig if the Bridged IPs changed.
  - **Acceptance evidence (2026-11-17):** `stop → off` in ~12s; `start → ready` in **32s** with all 7 steps emitted via SSE; `~/.ssh/config` block regenerated with only Bridged IPs; final health `3/3`, `baseline_files: true`, SSH `123.8–141.1 ms`; 11 `pytest` tests green.

### Phase 2: Scenario Execution Engine (`Setup`, `Check`, `Cleanup`) ✅ (implemented and verified on 2026-11-17)
**Objective:** Execute any structured scenario (JSON `ScenarioEnvelope`) on the real cluster, evaluating the user's answers with deterministic precision.
- **Deliverables:**
  - `ScenarioEngine`:
    - `apply_setup(scenario)`: creates namespaces, applies manifests via `kubectl apply -f -`, runs controlled-fault commands via SSH on the nodes after saving backups of the affected paths.
    - `run_checks(scenario)`: executes each assertion in parallel/sequence (using `kubectl get -o json`, `kubectl auth can-i`, `kubectl run` / ephemeral pod to test DNS/HTTP when needed, or read-only SSH commands on the nodes such as `systemctl is-active kubelet`).
    - `cleanup(scenario)`: restores node backups (if any) and removes namespaces/resources created by the scenario (`kubectl delete --ignore-not-found --wait=false`).
  - Catalog of **10+ deterministic Check Types** (documented in `LLM_SCENARIO_SPEC.md`).
  - `teardown.py` — Teardown in 3 levels: **L0** per question (on `Next`/`Skip`), **L1** end of session (sweep by label `cka-arena.io/managed`, backup restoration, drift check vs baseline) and **L2 clean reset**: L1 + restoration of the nodes' file baseline + `restart containerd/kubelet` + wait Ready + drift check. **No VM snapshots** — the Multipass/macOS backend does not implement them (verified); addons are preserved (`LLM_PIPELINE_SPEC.md` §6).
  - **3 Exemplary Seeds (decision D4):** `scenarios/seed/` with 1 question each from Troubleshooting, Cluster Architecture and Services & Networking (non-destructive; etcd only `snapshot save`) — they validate setup→check→cleanup in the engine **before** the LLM pipeline exists, and are published to the question bank as `source: seed`.
- **Acceptance Criterion:** A test scenario with 3 checks (1 pass, 2 fail) returns a detailed report per item, blocks advancing to the next question and, after fixing in the terminal, releases the `Next` button.
  - **Acceptance evidence (2026-11-17):** seed `ts-crashloop-fix` → **1 PASS / 2 FAIL** (blocks) → fix → **3/3 PASS**; seed `ca-rbac-pod-reader` → 2 PASS/2 FAIL → 4/4 PASS; seed `sn-expose-service` (ephemeral probe `curlimages/curl`) → 3 FAIL → 3/3 PASS; `cleanup` removes namespaces in all cases; `drift=false` on the 3 nodes after L1 (backups restored, no residue); node backup/restore validated E2E (`/etc/hosts` restored). 23 `pytest` tests green · 3 seeds published to the bank.

### Phase 3: Multi-Stage Generation Pipeline (A→E) + Question Bank ✅ (implemented and verified on 2026-11-17)
**Objective:** User selects domains + sub-topics + difficulty + quantity in the Studio and clicks "Generate with AI"; the agent pipeline (**A** Normalizer → **B** Builder → **C** Reviewer) with deterministic gates (**D**) and real prove-out on the cluster (**E**) **publishes provably solvable questions, in English in the exact exam format, to the bank**. Practice becomes a separate flow that draws from the bank using the exam percentages.
- **Deliverables:**
  - `LLMClient`: multi-provider adapter (Anthropic + OpenAI-compatible + Ollama), own multi-provider pattern (GLM Coding Plan, DeepSeek, OpenCode Go, Claude, custom), provider fallback on timeout/429 (DeepSeek as second choice, per `IMPLEMENTATION_READINESS.md` D1) — **no LangGraph/LangChain** (rationale and revision triggers documented in `LLM_PIPELINE_SPEC.md` §1).
  - `pipeline.py` — **A** Normalizer (flash model, temperature 0, canonical Pydantic `GenerationRequest` output); **B** Builder (main model, 1 envelope per call, N parallel calls, automatable `solution` block); **C** Reviewer (flash, fixed rubric, `approve|patch`); **D** code gates (schema, `yaml.safe_load_all`, blocklist, `--dry-run=server`, arm64 whitelist); **E** prove-out in an ephemeral exam namespace: **sanity** (checks MUST fail post-setup) + **Solvability Probe** (applies `solution` and requires 100% PASS). Auto-repair ≤ 2 with the exact error; rejected ones go to `draft` (quarantine, never served for practice).
  - `bank.py` — question bank: semantic dedup (`envelope_hash`), lifecycle `draft → probed → published → retired` (envelope immutable post-publication), per-question metrics (first-attempt hit rate, average time) and **`draw_exam_sample`**: largest remainder over the official weights (30/25/20/15/10), renormalization by filters, empty-cell fallback and `times_used ASC, random()` ordering.
  - **Settle Window:** between apply and sanity, wait for pods to be stable (`Running`/`CrashLoopBackOff`/`ImagePullBackOff` or 90s) — avoids a false verdict due to image pull latency (`GAP_ANALYSIS.md` G6).
- **Acceptance Criterion:** generating `Troubleshooting + Services & Networking` at `Killer.sh Hardcore` publishes ≥ 1 question that (a) **is in English in the exact exam format** (imperative title + context-symptom + "Perform the following tasks" + constraints), (b) **fails** the Check right after setup and (c) passes **100%** after applying the `solution` in the probe, with complexity within the level's band (Reviewer rejects poor fit); and drawing 15 questions from the bank returns exactly **5/4/3/2/1** per domain.
  - **Acceptance evidence (2026-11-17):** real job via `POST /api/generate` published `q-ff6f432969b5` — "Fix Broken Service Endpoints and Readiness" (Troubleshooting · **killer_hardcore** · weight 8 · 6 min · 6 checks), with the probe passing sanity (checks fail post-setup) + **solvability** (solution applied → 100% PASS) and the envelope in English in exam format; gates automatically rejected out-of-band proposals during the attempts (11 checks/weight 12, weight 16). **5/4/3/2/1** allocation validated by test with a synthetic bank of 15 questions (`largest_remainder`); draw on the real bank returns the available ones + flagged fallbacks. 37 `pytest` tests green. **Speed optimizations** (measured): `thinking: disabled` on DeepSeek (45.8s → 4.7s/call), fast-first/deep-retry, gates before the Reviewer, normalizer fast-path, parallel slots with serialized probe and single settle — job of **3 questions published in 76s** (~25s/question, previously ~200–300s/question).

### Phase 4: Integrated Web Interface (`Exam Workspace` + `Terminal` + `Scenario Studio`) ✅ (implemented and verified on 2026-11-17)
**Objective:** Build the lean web interface with **question and terminal integrated in the same window** (and optional native terminal mode), fully following the `UX_UI_SPEC.md`.
- **Deliverables:**
  - **Single-window** layout (question on the left ~44% · embedded terminal on the right ~56%, collapsible) with graceful degradation to the original 40% dual-window layout in **Native Terminal Mode** — **Liquid Glass** visual identity per `DESIGN.md` (3 glass materials, single persistent shell, motion 120–480ms), modular Vanilla JS or Alpine/HTMX without a heavy build, keeping instant setup.
  - **Design System before the views:** `static/css/tokens.css` + `glass.css` (`glass-1/2/clear`) + the **persistent shell** (header + content region + status strip) built first — it is the shell that guarantees no view looks like a different page (`DESIGN.md` §5/§10); visual reference: `design/mockup-workspace.svg`.
  - **View 1 — Exam Workspace (Study Screen):**
    - Collapsible side question queue / numbered pills (`Q1 ✓`, `Q2 ●`, `Q3 🔒`).
    - Question card with Domain + Difficulty + Weight badge + countdown Timer.
    - Copyable Context/Access banner (`kubectl config use-context cka` / `ssh cka-node01`).
    - **Automatic Copy-Pills** on pod names, namespaces, files and labels in the text.
    - `Check` Result Drawer (green/red list with the technical reason for each failure).
    - Fixed bottom bar: **`[Check]`** + **`[Next]`** (locked with a padlock until 100% `PASS`).
    - Controlled emergency button: **`[Reset Scenario]`**, **`[Skip (unlock after confirmation)]`** and **`[View Reference Solution]`** (only after passing the Check or confirming giving up).
    - **Integrated Terminal Panel (vendored xterm.js, no CDN):** tabs `mac · controlplane · node01 · node02`, automatic reconnection on page reload (PTY persists in the backend), Copy-Pills that copy **and** focus the terminal for ⌘V, and a **`Check`** button on the terminal's own footer bar (⌘↵ works while the terminal is focused).
  - **View 2 — Scenario Studio (LLM Generator):**
    - Checkboxes for the 5 CKA domains with their official weights + sub-topic chips.
    - Difficulty selector (`Exam Standard`, `Killer.sh Hardcore`, `Boss Fight`).
    - Quantity (`1 quick scenario`, `Battery 3 scenarios`, `Battery 5 scenarios`, `Mock exam 15 scenarios`).
    - **Live job card** via SSE reflecting stages A–E per scenario (mini-stages, attempts, current detail), 4s heartbeat, counters and progress bar, with recovery on reload (`GET /api/generate/status` + `generation.snapshot`) and a collapsible event log (`UX_UI_SPEC.md` §4), with a 5×3 coverage grid; **`[▶ Practice]`** CTA with a preview of the distribution by exam percentages and an end-of-session screen with L1/L2 cleanup (`UX_UI_SPEC.md` §5).
  - **View 3 — Settings (LLM + Cluster Doctor):**
    - Test the LLM connection, choose provider/model, test cluster health and restore baseline.
  - **Acceptance evidence (2026-11-17, Chromium headless via Playwright):** single shell with the 3 glass materials; **real terminal in the browser** (host PTY) running `kubectl get nodes` → 3/3 Ready; practice session drawn from the bank applied to the cluster with itemized **Check** (FAIL/PASS/FAIL with `expected/actual` evidence) and **Next locked** until passing; skip → next → **end of session with L1 cleanup and `drift=false`**; 560px viewport without horizontal scroll; **zero console errors**. Validation screenshots (shell, terminal, session, check, end of session and narrow viewport), not versioned. 40 `pytest` tests green. *(Verification done via HTTP with a real headless browser.)*

### Phase 5: Offline Seed Bank (15 Scenarios) + Infra Prerequisites & Telemetry ✅ (implemented and verified on 2026-11-17)
**Objective:** Guarantee immediate utility (zero LLM wait when you want instant training) + support for the new CNCF 2025/2026 curriculum topics + evolution history.
- **Deliverables:**
  - **Optional bootstrap of CKA tooling on the cluster:** verify/install on the `controlplane` and/or cluster `metrics-server` (scripts already exist in `certified-kubernetes-administrator-course/metrics-staging-scripts/`), `helm`, and **Gateway API** CRDs + a lightweight controller (e.g. Envoy Gateway or NGINX Gateway Fabric), or a clear flag informing which addons are active on the cluster.
  - **Remaining 12 Seed Scenarios (D4: 3 exemplars already delivered in Phase 2, totaling 15):** complete `scenarios/seed/` covering the 5 domains (including `etcd` snapshot save (restore only via LLM with `destructive`), broken `kubelet`, broken `kube-apiserver` static pod, `NetworkPolicy` DNS egress 53, `Helm` rollback, `Kustomize` overlay, `Gateway API`/`HTTPRoute`, native Sidecar and PVC expansion) and are **published to the bank** after passing the same A–E gates (seed does not skip prove-out).
  - **Per-Domain Performance Dashboard:** first-attempt hit rate, average time vs 6 min target, automatic recommendations for the next domain to generate and **bank coverage grid** (`published` count per domain×difficulty).
  - **Acceptance evidence (2026-11-17):** **17 seeds** passed the **deterministic gates + Solvability Probe on the cluster** (`python -m app.seed validate`: 17/17 PROBE OK, including kubelet/node01 via SSH, etcd snapshot save, Helm upgrade with a local chart, taints, PV/PVC, **NetworkPolicy with DNS egress 53 and negative check**, and **Gateway API `HTTPRoute` accepted by the controller**); bank with **21 published questions** covering the 5 domains; **per-domain telemetry** (`/api/telemetry`: first-attempt hit rate/average time + recommendation) in the Studio; **bootstrap plan** in Settings (empty after installation). 41 `pytest` tests green.
  - **Addons installed (2026-11-17):** metrics-server (patch `--kubelet-insecure-tls`; `kubectl top` OK), **Gateway API 1.2 CRDs + Envoy Gateway v1.2.0** (data plane validated with a real `HTTP 200`), **local-path-provisioner v0.0.30** (StorageClass `local-path`), and `weave-npc` **already present as a container of the weave-net DaemonSet** (detection fixed in the doctor). **L2-clean implemented and validated live** (VM snapshots not supported on Multipass/macOS): reset with `drift=false`, 3/3 Ready and **addons preserved**. *Gateway on kubeadm without a LoadBalancer stays `Programmed=False` for lack of an external IP; traffic via the data plane ClusterIP was validated (HTTP 200) and checks use the HTTPRoute `Accepted` status.*

---

## 5. Post-Implementation Readiness Verification

Once all phases are complete, the test plan must validate:
1. Unit tests (`pytest`) for the LLM parser, `Pydantic` schema, assertion rendering and the `Check -> Next` blocking logic.
2. Real integration test against the `cka` cluster (`v1.37.2`): apply one scenario of each type (K8s manifest + SSH node fault), confirm that `Check` fails before the fix, fix via `kubectl`/SSH, confirm that `Check` approves `100%`, advance with `Next` and verify complete `cleanup` of the test namespace.
3. Visual inspection of the UI in a narrow viewport (`480px`–`600px` simulating the left side of the screen with a terminal beside it) and desktop (`1440px`) — including **Liquid Glass design system compliance** (`DESIGN.md`): only the 3 defined glass materials, same radii/curves in all views, terminal never under glass, ≤ 2 stacked glass layers, no animation outside the motion grammar.
4. Tests for `TerminalService` (PTY session per tab, resize via `TIOCSWINSZ` echoing `stty size`, input→output, 6-tab limit, idle timeout) and for `ClusterPowerManager` (state transitions with `multipass` stubbed; kubeconfig self-heal simulating a controlplane IP change).
5. E2E smoke of the core integration requirement: app opened with cluster `off` → "⏻ Power On" CTA → instrumented boot completes → state `ready` → terminal opened in the browser runs `kubectl get nodes` (3/3 Ready) → seed scenario applied → solved **in the browser terminal** → `Check` 100% PASS → `Next` unlocked.
6. Bank and teardown tests: `draw_exam_sample` returns exactly `5/4/3/2/1` for N=15 and `2/1/1/1/0` for N=5 (largest remainder 30/25/20/15/10); empty-cell fallback fills proportionally and warns; E2E end of session: L1 removes everything with label `cka-arena.io/managed` and zeroes the drift check; L2-clean restores the file baseline, restarts containerd/kubelet, returns `drift=false` and preserves the addons.

---
