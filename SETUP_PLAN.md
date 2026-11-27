# SETUP_PLAN — `setup.sh` universal + OSS publication of CKA Arena

> **Historical record (November 2026) — frozen**, yet still the reference for the provider abstraction design (§2.1, cited in `app/provider/base.py`). What the document calls the "plan" is already implemented (§10). Known divergences from the current `setup.sh`: there is also a `--restart` flag; `--step` accepts `deps|cluster|wire|addons|seeds|server` (not the nine numbered steps of §4); and the file names cited in §2 (`cluster/addons.sh`, `.env.example`) do not exist — addons live in `app/addons.py`. Real usage: `./setup.sh --help`. Translated from the original pt-BR.

> Plan for adapting the repo so that anyone can clone it on GitHub and run
> `./setup.sh` to get the platform working locally. Owner requirements (verbal, 2026-11-18):
> (1) the script brings everything up — cluster, database, addons; (2) it detects distro/OS; (3) it detects prerequisites
> and, if any are missing, warns **what** is missing and asks for confirmation to install; (4) dynamic and
> colorful loaders; (5) at the end it shows the URL and what to configure; (6) **output 100% in English**.
>
> **Revision 2 (2026-11-18):** new owner requirement — **WSL2 must also work**.
> Nested virtualization inside WSL2 (`/dev/kvm`) is unreliable → Multipass **inside**
> WSL is ruled out; the viable path is an **alternative node driver (kind/Docker)**, which
> requires a small provider abstraction in the platform (§2.1, D7–D9).

---

## 1. Inventory — what exists vs. what is missing for OSS

| Need | State today | Gap for the public `setup.sh` |
| :--- | :--- | :--- |
| Run the server | `uv run cka-arena` (FastAPI, `127.0.0.1:8765`) | none — just ensure `uv sync` |
| Database | SQLite in `data/cka_arena.db`, **auto-init** at startup (`db.init_db`) | none — the script only publishes the seeds (`python -m app.seed`) |
| **Node driver** | ❌ Multipass **hardcoded**: `ssh_runner.multipass()` (single choke point), SSH by IP in checks/node_commands, `power._boot/_stop`, terminal preset `ssh cka-<node>` | **provider abstraction** (§2.1) to fit WSL2/kind without touching the Multipass path |
| Host `kubectl` | `cluster.py` calls the host `kubectl` binary | explicit setup prerequisite (missing in Rev.1 — applies to **all** OSes) |
| **Provision the cluster** | ❌ **does not exist in the repo**: the VMs were created by `certified-kubernetes-administrator-course/kubeadm-clusters/apple-silicon/deploy-virtual-machines.sh` (**macOS/arm64-only**, BRIDGE, jq+multipass, external cloud-init) | **central gap**: vendor + generalize (Linux, x86_64, per-OS bridge detection) |
| Addons (metrics-server, Gateway API+Envoy, local-path) | ❌ installed **manually**; `doctor.py` only detects and suggests `bootstrap_plan` | new idempotent `app/addons.py` called by setup |
| SSH bridge (key + `~/.ssh/config` cka-*) | ✅ `ssh_runner.py` installs via `SSH_ASKPASS` with `LAB_PASSWORD` (default `ubuntu`) | none — requires cloud-init with `ssh_pwauth: true` + ubuntu password |
| Dedicated kubeconfig (context `cka`) | ✅ `~/.cka-arena/kubeconfig` with self-heal | export by setup from the controlplane `admin.conf` |
| LLM config (Studio) | loader: project `llm_config.json` → `CKA_LLM_CONFIG` → env `CKA_LLM_*`; **configurable from the UI (Settings → AI provider)** | no gap — generation is optional (Practice works without LLM) |
| VMs | fixed names `controlplane/node01/node02`, `NODE_ALIAS cka-*`, `BRIDGE_PREFIX 192.168.1.` | network prefix is already detectable — setup detects the bridge subnet and exports `CKA_BRIDGE_PREFIX` |
| Idempotency/restart | `power.py` powers on/off; `auto_start` on launch | setup does not re-provision what already exists (`multipass list` + marker) |

**Structural decision of the plan:** the course cluster script is **vendored** into
`scripts/cluster/` (with credit) and generalized; the setup orchestrates, but each step is
a script testable in isolation.

---

## 2. Architecture

```text
setup.sh                      # thin orchestrator (≤200 lines): flag parsing, step order, final banner
scripts/
  lib/ui.sh                   # colors/spinner/confirm/banner  (§5 — the "dynamic colorful loader")
  lib/detect.sh               # OS/distro/arch/TTY/package manager
  lib/pkg.sh                  # install per manager (brew/apt/dnf/pacman/snap) + confirm
  lib/state.sh                # idempotency markers in ~/.cka-arena/setup.state
  cluster/up.sh               # Multipass VMs + cloud-init + kubeadm init/join (generalized vendor)
  cluster/kind-up.sh           # WSL/Linux-Docker driver: kind 3 nodes + weave CNI + name mapping
  cluster/addons.sh           # → calls `uv run python -m app.addons` (idempotent)
app/addons.py                 # addon bootstrap via cluster.py (same path as the runtime)
.env.example                   # CKA_LAB_PASSWORD, CKA_LLM_CONFIG, CKA_BRIDGE_PREFIX (documented in English)
```

**Flags:** `--yes` (non-interactive/CI), `--check` (dry-run: only audits prereqs and exits),
`--provider multipass|kind` (default: auto per environment — WSL2 → kind, §2.1),
`--skip-cluster` (I already have nodes), `--bridge <iface>` (override detection; multipass provider),
`--llm-config <path>`, `--with-addons|--no-addons` (default: with), `--step <name>` (re-run one step).

**Idempotency:** each step writes a key to `~/.cka-arena/setup.state`
(`cluster_up`, `ssh_bridge`, `kubeconfig`, `addons`, `seeds`); re-running skips what is
done and re-verifies (not merely trusting the marker — it validates the effect).

### 2.1 Node provider (what enables WSL2)

Today Multipass is glued at 4 points: `ssh_runner.multipass()` (CLI), exec over SSH
(checks `node_command`/`host_file_contains`, L2 backups), `power._boot/_stop` and the
terminal preset `ssh cka-<node>`. The adaptation creates a single seam:

```text
app/provider/
  base.py        # interface: nodes() -> [{name, ip, state}] · exec(node, cmd, sudo)
                 #            power_on() / power_off() · transport ("ssh"|"docker")
  multipass.py   # current behavior, 1:1 (pass-through — zero regression on macOS)
  kind.py        # WSL2/Linux+Docker: nodes = kind containers; exec = docker exec
```

Selection: `CKA_PROVIDER=multipass|kind` (env) — the setup chooses the default per environment
(WSL2 → kind; macOS/Linux with Multipass → multipass) and records it in `~/.cka-arena/provider`.

**`scripts/cluster/kind-up.sh` (external script, creates the cluster):**
1. `kind create cluster --name cka --config` — 1 control-plane + 2 workers,
   `networking.disableDefaultCNI: true`;
2. applies **weave-net** (same CNI as the Multipass driver → NetworkPolicy/NPC keeps
   working in netpol questions);
3. exports the kubeconfig to `~/.cka-arena/kubeconfig` (context `cka`);
4. writes the **name mapping** `~/.cka-arena/nodes.json` — kind names workers
   `cka-worker/cka-worker2`; the platform keeps speaking `controlplane/node01/node02`
   (logical) and the provider translates (D8);
5. addons via the same `app/addons.py`.

**WSL2 mappings:** power on/off = `docker start/stop` of the node containers (kubelet
resumes inside the container); `node_commands` and `host_file_contains` = `docker exec`;
node terminal preset = `docker exec -it <node> bash` (no SSH, no key); L2-clean =
teardown + `kind create` again (~90 s — simpler than restoring node files).

**Why not Multipass inside WSL:** a nested VM requires `/dev/kvm` exposed by
Windows to WSL2 — unavailable on most hosts/versions; Docker in WSL2 uses the
shared-kernel namespaces/cgroups and works **without** nested virtualization
(bonus: `--provider kind` also serves Linux without Multipass and future CI environments).

---

## 3. OS and prerequisite detection

### 3.1 Support matrix (proposed decision — P1 explicit, the rest warns and continues)

| OS | Support | Provisioning |
| :--- | :--- | :--- |
| macOS (arm64/x86_64) | ✅ P1 (already validated path) | Multipass via `brew` — bridge via `netstat -rn -f inet` |
| Ubuntu/Debian (x86_64/arm64) | ✅ P1 | Multipass via `snap` — bridge via `ip route` |
| Fedora/Arch | ⚠️ best-effort (warns: "tested on macOS/Ubuntu") | multipass via `dnf`/AUR when available |
| WSL2 (Windows 11, systemd enabled) | ✅ via the **kind driver** (§2.1) — native Docker Engine inside WSL, no Docker Desktop and no nested VM | `kind create` 3 nodes + weave |
| WSL2 (Windows 10 / no systemd) | ⚠️ blocks with explanation (WSL ≥ 2.0 / Win11 required for cgroup v2 + systemd in the kind nodes) | — |

### 3.2 Audited prerequisites (in order)

1. `bash ≥ 4` (the script itself), TTY/`tput` (degrades to no color — §5)
2. **kubectl** (host binary — the app's `cluster.py` calls `kubectl` directly; applies to EVERY OS)
3. **Multipass** — `multipass` provider (macOS/Ubuntu/Debian; `snap` on Linux)
4. **uv** — official installer `curl ... | sh` (never an old apt/brew)
5. **Python ≥ 3.12** (via uv if absent — uv manages the project runtime)
6. `jq` (cluster scripts) · `ssh`/`ssh-keygen` (openssh-clients; multipass provider only)
7. Resources: ≥ 16 GB RAM (warn < 8 GB blocks; 8–16 warn), ≥ 30 GB disk, virtualization enabled (Linux: checks `/dev/kvm`)
8. Bridge network: detects default interface + subnet → validates ≥ 3 free IPs (warning, non-blocking) — `multipass` provider only

**WSL2 branch (provider `kind`)** — replaces items 3/6/7/8:

9. systemd active in WSL (`ps -p 1 -o comm=` → `systemd`) and cgroup v2 (`stat -fc %T /sys/fs/cgroup` → `cgroup2fs`) — otherwise blocks with upgrade instructions (Win11 / WSL ≥ 2.0)
10. **Docker Engine** native to WSL (installable via apt with confirmation — does **not** require Docker Desktop)
11. **kind** (single binary, downloaded from the official release with confirmation) + `jq`
12. Resources: same RAM/disk limits (no `/dev/kvm` — kind does not need it)

Behavior required by the owner: **something missing → named list** (`[MISSING] multipass — required to run the lab VMs`)
and asks for confirmation **per item** (`Install multipass via Homebrew? [y/N]`); `--yes` installs everything; refusal → aborts
with the manual command the person can run later (the script never installs without explicit consent).

---

## 4. `setup.sh` flow (9 steps, all in English)

```text
CKA ARENA — setup                                  # ASCII banner + repo version
[1/9] Detecting environment          macOS 15 · arm64 · provider=multipass
                                     Ubuntu 24.04 · x86_64 · provider=multipass
                                     WSL2 · Win11 · provider=kind            (✓ green)
[2/9] Checking prerequisites         all found                      (or list + confirm)
[3/9] Installing Python deps         uv sync                        (spinner: resolving/installing)
[4/9] Launching nodes                multipass: 3 VMs (bar/VM)    or kind: 3 containers
[5/9] Bootstrapping Kubernetes       kubeadm+join+weave             or kind config + weave CNI
[6/9] Wiring access                  multipass: SSH bridge+kubeconfig · kind: kubeconfig+nodes.json
[7/9] Installing addons              metrics-server · Gateway API/Envoy · local-path
[8/9] Seeding question bank          17 published
[9/9] Starting server                http://127.0.0.1:8765  (smoke: /api/health 200)
```

Rules: long step = spinner with frame + current sub-step message (not just "wait…");
error = last ~20 log lines on screen + full log path; `Ctrl-C` clears the spinner via `trap`;
each step can be re-run in isolation (`./setup.sh --step addons`).

### Final banner (exact, in English, colored)

```text
───────────────────────────────────────────────────────────────
 ✔ CKA Arena is ready

 ▸ Open:            http://127.0.0.1:8765
 ▸ Terminal:        real shell on this machine (auto-opened tab "mac")

 Configure (all optional):
 ▸ AI generation  — drop a provider key into  llm_config.json
                    (see llm_config.example.json; Practice works without it)
 ▸ Lab password   — VMs use user "ubuntu" / password "ubuntu"
                    (override with CKA_LAB_PASSWORD before re-running setup)
 ▸ Power          — stop/start the cluster from the header pill; the app
                    auto-starts it on launch

 Logs: ~/.cka-arena/setup.log · data: ./data/ · state: ~/.cka-arena/
───────────────────────────────────────────────────────────────
```

---

## 5. Terminal UX — "dynamic and colorful loaders" (`lib/ui.sh`)

- **Colors**: fixed ANSI palette (green ✓ / yellow ! / red ✗ / cyan info / bold titles);
  `NO_COLOR`, pipe (`[ -t 1 ]` false) and `TERM=dumb` → plain mode with prefixes `[ok]/[warn]/[err]`.
- **Spinner**: braille frames `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` at 80 ms in a thread via `&` + `wait $pid` +
  `trap cleanup INT TERM`; supports a mutable message (`spinner_set "joining node02…"`).
- **Node progress**: multipass → bar per VM via `multipass info` (Running/cloud-init);
  kind → bar per container via `docker inspect` (health/running) — never a blind sleep.
- **Confirm**: `y/N` safe default; 30 s timeout → N; `--yes` skips.
- Step counter `[n/9]` aligned; width 72 columns (detected, clamp 60–100).
- Everything also goes to `~/.cka-arena/setup.log` (no color codes).

---

## 6. Repo changes to publish on GitHub

1. **`llm_client.py`**: local-only configuration — `llm_config.json` → `CKA_LLM_CONFIG` → env `CKA_LLM_*`,
   editable from the UI (Settings → AI provider). Create `llm_config.example.json`.
2. **`.gitignore`**: already covers `data/`; add `llm_config.json`, `*.db*`, keep `design/`, `.venv`.
3. **README**: new top section **Quickstart (EN, ~15 lines)** — prereqs, `./setup.sh`, URL;
   the current PT-BR content moves down to "Documentation (pt-BR)"; decision on the language of
   internal docs: they remain PT-BR (historical product decision), quickstart and script in EN.
4. **LICENSE** MIT + `NOTICE` crediting `certified-kubernetes-administrator-course`
   (origin of the vendored cluster scripts).
5. **CI (GitHub Actions)**: `shellcheck scripts/`, `bash -n setup.sh`, `uv run pytest`,
   `python -m app.seed validate` (gates without cluster — probe stays out of CI).
6. **Secrets**: final `git log -p` audit before push (history was born local —
   consider a clean `git init` + squash, no personal history).

---

## 7. Assumed decisions (confirmable by the owner)

| # | Decision | Rejected alternative |
| :--- | :--- | :--- |
| D1 | P1 = macOS + Ubuntu/Debian; Fedora/Arch warned; **WSL2 supported via kind** (D7) | support everything for free (QA cost) |
| D2 | Prereq installation **always** with per-item confirmation (`--yes` skips) | silent auto-install |
| D3 | Provider `multipass` stays **BRIDGE** (runtime requirement: local IPs for SSH) | NAT/port-forward (would break the ssh bridge) |
| D4 | LLM key is **optional** in setup (Studio disabled without it, Practice 100%) | require key (would block onboarding) |
| D5 | Addons inside the app (`app/addons.py`) reusing `cluster.py` — same path as doctor | pure shell (would duplicate kubectl/ssh bridge) |
| D6 | Public repo with PT-BR internal docs + EN quickstart/script | translate everything (scope explodes) |
| D7 | **WSL2 = provider `kind`** (Docker Engine in WSL, weave CNI, no nested VM); `app/provider/` with 1:1 pass-through for Multipass (zero macOS regression) | Multipass inside WSL (`/dev/kvm` unreliable) or Multipass on Windows (Hyper-V Win Pro + unsupported bridge) |
| D8 | **Logical** names `controlplane/node01/node02` across the platform; provider translates via `~/.cka-arena/nodes.json` | rename kind nodes (not supported by kind) |
| D9 | Node transport per provider: `ssh` (multipass) × `docker exec` (kind, including node terminal tabs); L2-clean on kind = recreate cluster (~90 s) | emulate SSH on kind (complexity without gain) |

---

## 8. Verification plan (acceptance)

1. `shellcheck setup.sh scripts/**/*.sh` clean; `bash -n` ok.
2. `./setup.sh --check` on a machine with everything → exit 0, green list; removing `multipass`
   from PATH → lists `[MISSING] multipass` and does **not** install without confirmation.
3. **Real macOS run (controlled-destructive)**: `multipass delete --purge` the 3 VMs →
   `./setup.sh` → final banner → `curl /api/health` 200 → 1-question practice PASS.
4. **Idempotency**: second run → all steps `already done ✓` in < 10 s.
5. **Ubuntu 24.04 VM** (manual on the first pass): same script 3–4.
6. **WSL2 (Win11 + systemd)**: `./setup.sh` with the kind provider → final banner →
   practice with 1 **NetworkPolicy** question (proves weave/NPC works on kind)
   + node terminal tab via `docker exec` + L2-clean (recreation) runs to the end.
7. **Provider regression on macOS**: the `app/provider/` refactor is pass-through — full
   suite (64+ tests) green + power/terminal/check flow identical to today's
   (evidence: run 3 on the same machine).
8. `NO_COLOR=1 ./setup.sh --check` and `./setup.sh --check | cat` → readable plain output.
9. Existing suite of 64 tests stays green (addons.py and provider/kind get theirs).

## 9. Implementation order (when approved)

- **Phase A** — `lib/ui.sh` + `lib/detect.sh` + `setup.sh --check` (immediate feedback, no risk)
- **Phase B1** — refactor `app/provider/` with **multipass 1:1 pass-through** (seam first,
  no behavior change; green suite = zero regression before kind exists)
- **Phase B2** — `provider/kind.py` + `scripts/cluster/kind-up.sh` (weave + nodes.json);
  validated on WSL2 before becoming the default for that environment
- **Phase C** — vendor + generalization `scripts/cluster/up.sh` (multipass Linux) + `app/addons.py`
  + steps 6–9 + final banner
- **Phase D** — OSS: README/LICENSE/CI/cleanup of personal defaults + full verification (§8)


---

## 10. Implementation status (2026-11-18) — evidence

| Phase | Delivered | Verification |
| :--- | :--- | :--- |
| A — Shell libs | `scripts/lib/{ui,detect,pkg,state}.sh` + `setup.sh` (flags, 9 steps, `--check`, `--step`, spinner/colors/trap) | `./setup.sh --check` exit 0 on this machine; `PATH=/usr/bin:/bin ./setup.sh --check` lists `[MISSING] kubectl` and exits 1 **without installing**; `shellcheck -S warning` clean; `bash -n` on everything |
| B1 — Provider seam | `app/provider/{base,multipass,kind}.py`; engine/pipeline/validator/doctor/power/terminal routed via `provider.get()` (no direct `ssh_runner` in checks) | 76 tests green (12 new: `tests/test_provider.py` + `tests/test_commands.py`); real `provider.get().nodes()` → 3 VMs Running with bridge IPs |
| B2 — WSL/kind | `scripts/cluster/kind-up.sh` (3 nodes, weave→Calico fallback, kubeconfig `cka`, `nodes.json`); `KindProvider` (docker exec, power start/stop, terminal `docker exec -it`) | `CKA_PROVIDER=kind` → `power.detect()` degrades gracefully without Docker (no crash); provider unit mapping/tests |
| C — Cluster/addons | `scripts/cluster/up.sh` (generalized Multipass: bridge per OS, cloud-init kubeadm, join, weave); `app/setup_wire.py`; idempotent `app/addons.py` | real `python -m app.setup_wire`: 3 nodes ready, `~/.ssh/config` updated; real `python -m app.addons`: metrics-server/gateway/envoy/local-path "already present"; `./setup.sh --step addons` idempotent no-op |
| D — OSS | README Quickstart EN (OS table incl. WSL2), `LICENSE` MIT, `NOTICE`, `llm_config.example.json`, **AI provider configurable in the frontend (Settings → AI provider: presets, models by dropdown, masked key, connection test)**, `/api/health`, CI (pytest + shellcheck), `seed validate --gates-only` | 76 tests; `seed validate --gates-only` 17/17 GATES OK; `./setup.sh --step server` detects a live server; `/api/health` → `{"ok":true}` |

**Known pending items (outside this delivery):** first real run of `kind-up.sh` on Windows 11/WSL2 and of `up.sh` on a clean Ubuntu (the current test machines are macOS with Multipass already provisioned — the paths were validated by unit tests/idempotency, not by provisioning from scratch on those two platforms).
