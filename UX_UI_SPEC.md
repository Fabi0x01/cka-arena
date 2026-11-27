# UX & UI Spec — CKA Arena

> **Surface Mode:** *Operate* (a high-concentration operational tool). The interface must disappear into the task: zero gratuitous decoration, zero slow animations, instant scannability, and visual comfort for long study sessions.

> UX **reference document**. Where it diverges from what is implemented in `static/`, the code prevails.

---

## 1. Core Principle: Single Window with Integrated Terminal (Dual-Window Optional)

The primary flow is **everything inside the browser**, in a single window:
- **Left column (~44%):** question prompt, required context, Copy-Pills, Check result, and the **Check → Next** bar.
- **Right column (~56%):** a **real terminal** (xterm.js over a host PTY) with tabs created by the **`+ Shell`** popover (`Local shell · controlplane · node01 · node02`) — `kubectl`, `vim`, `helm`, and `ssh` run right there. The local shell starts in an **isolated workdir** (`~/.cka-arena/scratch/<tab>`, shown in the footer): YAMLs and temp files never pollute the project folder, and `kubectl` uses the dedicated kubeconfig (context `cka`).
- **Check has a single action** — a button in the question column's footer, repeated in the terminal bar — and can be triggered from any focus via **`⌘↵`** (intercepted before xterm): the *edit → check → fix* cycle happens without switching panels.
- **Toggle `[⌗ Native]`** (terminal footer): collapses the embedded panel and restores the original dual-window ergonomics (40% browser / 60% native terminal) for those who prefer the OS terminal; the Copy-Pills keep copying to the clipboard.
- **UI language: 100% English** (Revision 3): labels, buttons, toasts, previews, prompts, and hints — the CKA exam is in English and training includes reading tasks and feedback in the exam's language. UI strings shown in this spec (wireframes, CTAs) are already in English.

**Structural Responsiveness Rule:**
- `≥ 1100px`: Question | Terminal split side by side (study default).
- `700–1099px`: the terminal becomes a panel switchable via tabs in the footer (`[Question] ⇄ [Terminal]`) — never horizontal scroll.
- `480–699px`: single column; the terminal opens as a `70vh` bottom-sheet (preserves use in a narrow window beside the native terminal).
- The `Check Result Drawer` expands **inline below the prompt** and never covers the terminal during a Check.

---

## 2. Wireframes (Integrated Workspace · Home with Cluster Off)

**a) Exam Workspace — the two columns below live side by side in the same window (≥ 1100px):**

```text
┌──────────── Coluna Esquerda ~44% (Questão) ────────────┐
│ CKA ARENA [Q1 ✓][Q2 ●][Q3 🔒]  Cluster: ● 3/3 [⏻]      │  ← header GLOBAL (ver c)
│ Troubleshooting (30%) · Peso 8% · Hardcore ⏱ 04:32/07:00 │
│ ────────────────────────────────────────────────────── │
│ REQUIRED CONTEXT                                        │
│ > kubectl config use-context cka                 [Copy] │
│ > ssh cka-node01                                  [Copy] │
│ ────────────────────────────────────────────────────── │
│ TASK                                                   │
│ A Deployment `web-api` in `prod-checkout` is running   │
│ 1/3 replicas after node maintenance...                │
│ Perform the following tasks:                          │
│ 1. Restore the `kubelet` on `node01` until Ready      │
│ 2. Scale `web-api` to `3` replicas                   │
│ 3. Pin all pods to `node01` via `nodeSelector`       │
│ Docs: ↗ Node Troubleshooting ↗ Assigning Pods to Nodes │
│ ────────────────────────────────────────────────────── │
│ CHECK RESULTS (after clicking Check)                  │
│ ✅ [PASS] Node `node01` reports `Ready=True`          │
│ ❌ [FAIL] `web-api` has 1/3 replicas ready            │
│    ↳ Expected 3 ready; current: 1.                    │
│ ❌ [FAIL] Pods missing nodeSelector for `node01`      │
│    ↳ `spec.template.spec.nodeSelector` missing.       │
│ ────────────────────────────────────────────────────── │
│ [↻ Reset] [🏳 Skip] [✓ Check (⌘↵)]  [🔒 Next →]       │
└────────────────────────────────────────────────────────┘

┌──────────── Coluna Direita ~56% (Terminal) ────────────┐
│ TERMINAL  [mac][controlplane][node01][node02] [+] [⏹] │
│ $ kubectl config use-context cka                       │
│ Switched to context "cka".                             │
│ $ kubectl -n prod-checkout get deploy web-api          │
│ NAME      READY   UP-TO-DATE   AVAILABLE               │
│ web-api   1/3     1            1                       │
│ $ ▌                                                    │
│        (PTY do host · reconecta em reload)             │
│ ────────────────────────────────────────────────────── │
│ [⌥T New Tab] [⌘K Clear]   [✓ Check (⌘↵)]  📋        │
│   ↑ same endpoint as the question's Check:            │
│     validate without leaving the terminal             │
└────────────────────────────────────────────────────────┘
```

**b) Home with cluster off (`off` state → single CTA):**

```text
┌────────────────────────────────────────────────────────┐
│ CKA ARENA                                    ⏻ Off     │
│                                                        │
│            ⏻  POWER ON & PRACTICE                     │
│   (live boot: ✓ VMs ✓ SSH ⟳ API … step 4/7)           │
│                                                        │
│   [Studio locked · cluster must be Ready]             │
│   [Workspace locked · cluster must be Ready]          │
└────────────────────────────────────────────────────────┘
```

**c) Global header — cluster state pill (`power.js`):**

| State | Pill | Available action |
| :--- | :--- | :--- |
| `ready` | `● Ready 3/3` (green) | Menu: Power off · Restart · Doctor |
| `off` | `⏻ Off` (gray) | **Power On** (large home CTA) |
| `starting` | `⟳ Starting · step N/7` (amber, animated) | Cancel boot |
| `degraded` | `▲ Degraded` (amber) | View diagnosis · Restore Baseline |
| `daemon_down` | `⨯ Multipass` (coral) | Fix instructions (restart the node provider daemon) |

---

## 3. Interaction Rules & the `Check -> Next` Mechanic

### A. Automatic Copy-Pills (Zero Typing Errors)
- On the real CKA exam, losing 30 seconds to a typo in a namespace or resource name is expensive.
- Every token surrounded by backticks `` `...` `` in the prompt (e.g. `` `prod-checkout` ``, `` `web-api` ``, `` `allow-api-to-db` ``) is rendered as a **clickable chip (`Copy-Pill`)** in monospace.
- Clicking the chip copies the exact text (without backticks) to the clipboard and shows subtle micro-interactive feedback (green `border` + a quick `Copied` tooltip).

### B. The Rigid `Check` → `Next` Cycle
1. **Question initial state:**
   - The **`[✓ Check (⌘↵)]`** button is active in the primary style.
   - The **`[🔒 Next →]`** button is visibly **disabled**, with a padlock icon and explanatory title: *"Validate 100% of the criteria in the Check to unlock the next question"*.
2. **On clicking `Check`:**
   - The button enters a loading state (`Checking cluster…`) and double-clicks are disabled.
   - The backend runs all deterministic assertions in parallel and returns the results array.
   - The **Check Result Drawer** opens inline above the footer bar, listing each criterion with a green (`PASS`) or coral (`FAIL`) icon and the technical `failure_hint` (pointing at the real cluster symptom, **without giving the ready-made command**).
3. **On reaching 100% `PASS`:**
   - The question timer freezes, recording the final time (e.g. `Completed in 04:18 · Within target!`).
   - The **`[🔓 Next →]`** button transitions (`200ms`) to the active state in **Emerald Green** (or becomes **`[🏆 Finish Session]`** on the last question).
   - The **`[View Reference Solution]`** button unlocks as a collapsed toggle in case the user wants to compare their imperative approach with the ideal solution.
4. **On clicking `Next →`:**
   - Automatically runs the current question's `cleanup`, applies the next question's `setup` (showing a light 1–3s overlay: *"Preparing scenario Q3 on the cluster…"*) and restarts the timer for the new question.
5. **Controlled Escape Valve (Anti-Deadlock):**
   - If a scenario is genuinely blocking or the user wants to abort, the discreet **`Skip / Give up`** button opens a 1-step confirmation (*"Mark this question as unsolved and unlock the next one?"*). Only after explicit confirmation does its state change to `skipped`, unlocking progression + solution.

### C. Check Without Leaving the Terminal (Core Integration Requirement)
1. `⌘↵` and `⌘⇧↵` are intercepted **before** reaching xterm: the shortcuts work even with the terminal focused; the Check button (question column) shows `Checking… Ns` during the round (90s backend deadline — never an infinite loading).
2. Once the Check result arrives, focus **returns to the terminal** (the user reads the drawer in the left column without losing the cursor).
3. Copy-Pills, besides copying, move focus to the terminal (flow: click the pill → ⌘V in the terminal).
4. Confirmed `Reset`/`Skip` restart the scenario **without closing the terminal tabs**; with no active session, `Reset`/`Skip`/`Check` stay `disabled`.
5. Node tabs (`controlplane`, `node01`, `node02`) open `ssh cka-<node>` already authenticated with the dedicated key; if the bridge has not been provisioned yet, the tab shows a Cluster Doctor hint instead of a stuck password prompt.

---

## 4. "Scenario Studio" Anatomy (LLM-Based Scenario Generator)

Accessible via the **Studio** view of the segmented control (`⌘2`; also via the empty state's "Generate with AI" CTA). **Generation publishes to the question bank** — it does not create another active queue: practicing is a separate flow (§5), which draws from the bank according to the exam percentages:

1. **CKA Domain Selector (Multi-Select with Official Weights):**
   - `[x] Troubleshooting (30%)`
   - `[x] Cluster Architecture, Installation & Config (25%)`
   - `[ ] Services & Networking (20%)`
   - `[ ] Workloads & Scheduling (15%)`
   - `[ ] Storage (10%)`
   - *Optional per-domain sub-chips:* when *Cluster Architecture* is checked, clickable chips appear (`etcd backup/restore`, `RBAC`, `Helm`, `Kustomize`, `CRDs`). When *Services & Networking* is checked, they appear (`Gateway API`, `NetworkPolicy`, `Ingress`, `CoreDNS`). If no chip is checked, the LLM draws freely within the chosen domains.
2. **Difficulty Selector:**
   - `Exam Standard` — Faithful to the official exam
   - `Killer.sh Hardcore` *(Recommended default)* — Harder than the exam, 3–4 requirements + traps
   - `Boss Fight` — Multi-node chaos + dependent workload
3. **Battery Size & Extra Focus (Optional Prompt):**
   - Quick chips: `1 Scenario` | `3 Scenarios` | `5 Scenarios` | `Full Mock Exam (15)`
   - Optional 1-line field: *"Extra focus or constraint (optional)"* — e.g. *"I want to practice broken static pods and avoid Helm in this batch"*.
4. **Transparent Pipeline Progress (SSE + live card):**
   - The **live job card** is always visible during and after generation: status chip (`running` pulsing / `done` / `failed`), `Qn/total · stage · elapsed` with the current step's detail, counters (`published · quarantined · attempted`), a progress bar, and **one line per scenario** with mini-stages `A B C D E` (✓ done, ● current, ✗ failed), attempt (`try N`), and live detail.
   - Collapsible **event log** (last 40 events with timestamps) to audit what the pipeline was doing.
   - The backend's **4s heartbeat** keeps the card alive even during long LLM calls, probes, and convergence loops (sanity/rollout); without a heartbeat for >10s the elapsed keeps running and the detail stays on the last step.
   - **Recovery on reload/SSE drop:** the backend keeps the job state and the card is rebuilt via `GET /api/generate/status` + a `generation.snapshot` event on connect — generation never "disappears" from the screen.
   - Failed scenarios appear as `Q1 ✗ quarantined (draft): <reason>`; after the fix budget is exhausted, the question goes to `draft` (never served for practice).
   - *UX note:* during generation, the cluster is used **only** in the ephemeral proof namespace (`cka-arena-prove-<uuid>`, discarded at the end) — no real question setup is applied at this stage; setup happens at **Practice** time (§5).
5. **Cluster-state gating:** with the cluster `off`/`starting`, Studio stays locked with an explanatory pill and the **"⏻ Power On"** CTA; generation is only allowed when `ready` (or `degraded`, with a risk warning and a Restore Baseline suggestion).
6. **Bank Coverage Grid (5 domains × 3 difficulties):** Studio footer with per-cell counts (`GET /api/bank/coverage`); cells with < 3 `published` questions highlighted in amber + contextual CTA "Generate 3× {cell}". `draft`/`retired` questions do not count.

---

## 5. Practice from Bank & Session End

**a) "Practice" modal** (`[▶ Practice]` CTA in the header; requires cluster `ready`):
1. **Quantity:** chips `3 · 5 · 15 (mock exam) · custom` — the draw follows the **official exam percentages** via *largest remainder* (Troubleshooting 30% · Cluster Architecture 25% · Services & Networking 20% · Workloads 15% · Storage 10%).
2. **Optional filters:** domains and/or difficulty (default: all; weights renormalized over the subset).
3. **Distribution preview before starting:** *"You will get: 5× Troubleshooting · 4× Cluster Architecture · 3× Services & Networking · 2× Workloads · 1× Storage"* — with an amber badge when there is an empty-cell fallback (*"Storage Hardcore: empty — filled with S&N"*) and a "Generate more first" CTA.
4. `[Start Session]` → draw (sorted by `times_used ASC, random()`; no repeats within the session) → Q1 setup applied to the cluster → question screen + terminal (§2a).

**b) Session End — summary + cluster cleanup** (requirement: the cluster is zeroed and clean at the end):

```text
┌──────────────────────────────────────────────────────┐
│  SESSION COMPLETE · 11/15 · 68% first-try passes     │
│  Total time 78 min · weakest: Storage (2/5)          │
│ ──────────────────────────────────────────────────── │
│  Clean up the cluster now?                           │
│  [✓ Fast Cleanup (L1 · ~30s)]     ← default          │
│  [⟳ Clean Reset (L2 · ~2 min)]                        │
│   (drift detected → L2 recommended; mock exams       │
│    always run L2 automatically)                      │
```

- **L1 (default):** global sweep of resources labeled `cka-arena.io/managed: "true"` + application of pending node backups + drift check (~30s) — cluster ready for the next session.
- **L2 (Clean Reset):** L1 + restoration of the nodes' file baseline + restart of `containerd`/`kubelet` + wait for Ready + drift check (~1–2 min) — addons preserved; VM snapshots are not supported on Multipass/macOS. Automatic after `mock_exam` mock exams and recommended when the drift check reports divergence.
- L0/L1/L2 level spec and full policy: `LLM_PIPELINE_SPEC.md` §6 · `ARCHITECTURE.md` §12.

---

## 6. Visual System — Orbital Control Console (full contract in `DESIGN.md`)

Identity: an **operational mission console over dark anodized surfaces in `oklch()`** (`--canvas` → `--bay` → `--surface` → `--surface-raised`), `1px` hairline structural lines, surgical **Ice Cyan** accent (`oklch(76% 0.145 208)`), critical content (question Markdown, PTY `xterm.js` terminals on `#0A0D13`) always matte and opaque, with `backdrop-filter` reserved exclusively for top-layer `<dialog>` (`Command Palette ⌘K` and modals). Full contract in [`DESIGN.md`](./DESIGN.md).

- **Single-Shell Structure (`54px` Rail + `48px` Topbar):** left side Rail with unified SVG icons (`stroke 1.6px`), cluster status `[popover="auto"]` in the Rail footer, and a clean contextual Topbar containing only the question queue, timer/pacing, and session CTA.
- **Typography & Hierarchy:** interface and Markdown in `Figtree` (`400–700`, `max-inline-size: 68ch`); terminal, timers, tables, and YAML in `JetBrains Mono` with `tabular-nums`. Fixed `rem` scale with a floor of ≥ `12px`.
- **Native Web Primitives:** view switching with `document.startViewTransition()`, modals as `<dialog>` with `@starting-style` + `transition-behavior: allow-discrete`, `+ Shell` and `Cluster Power` menus as `[popover="auto"]` anchored via CSS Anchor Positioning with fallback.
- **Sub-tabs in Arena & Studio:** the question panel is split into `Task & Check`, `Checklist & Notes`, and `Hints & Docs`; the Studio's right column is split into `Pipeline & Coverage` (with a clickable `5×3` heatmap) and `Bank Inspector`.
- **Keyboard Shortcuts:**
  - `⌘ + K` → Opens the global **Command Palette** (navigation, drills, SSH tabs, commands)
  - `⌘ + Enter` → Triggers **Check** — global, including with the terminal focused
  - `⌘ + Shift + Enter` → Triggers **Next** when unlocked
  - `⌘ + B` → Toggles **Zen Terminal** (full-width terminal)
  - `⌘ + F` → Search the terminal scrollback history
  - `⌘ + L` → Clear the active terminal · `⌘ + 1..5` → Switch view (Arena/Readiness/Studio/Settings/Study Codex) · `⌘ + /` → Shortcuts modal · `Esc` → Close modal/search
- In the shortcuts above, `⌘` applies to macOS; on Linux/WSL2 the modifier is `Ctrl` (and `Ctrl+Shift` when the terminal is focused). The list shown in the UI is the one from the shortcuts modal (`⌘/`).
