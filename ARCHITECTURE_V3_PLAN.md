# CKA Arena v3 — Architectural Upgrade Report

> **Historical record (2026-11-22) — frozen.** v3 upgrade report. Later work (v4 mastery and review, frontend redesign) is not covered here, and some file names have changed since. Current state: `README.md` and `ARCHITECTURE.md`.

**Date:** 2026-11-22  
**Status:** Implemented & Verified (Unit/API Tests, JS Validation, Live Cluster Seed Validation, Live DeepSeek Pipeline Benchmark)

---

## Executive Summary

Upgraded **CKA Arena** across **5 architectural pillars** to eliminate flakiness/orphaned cluster state, match authentic **PSI CNCF CKA 2025/2026** exam ergonomics, expand curriculum & deterministic gates to **59 archetypes** across all 5 CKA domains, introduce an **SM-2 Spaced Repetition & Readiness Engine**, and upgrade the web workspace UI for speed and clarity.

---

## Pillar 1 — Core Reliability & Maintainability

- **Test Isolation (`tests/conftest.py`)**: Global `autouse=True` fixture isolates `config.DATA_DIR`, `config.LLM_CONFIG_PATH`, and clears `db._WAL_INITIALIZED` on every pytest test, preventing tests from polluting production `data/cka_arena.db`.
- **Pipeline Modularization (`app/pipeline/`)**: Split monolithic `app/pipeline.py` (`1,783 LOC`) into:
  - `app/pipeline/prompts.py` — tier rubrics, Prompt/Normalizer/Builder/Reviewer/Repair system prompts.
  - `app/pipeline/gates.py` — static/schema validation, blocklist, image whitelist, docs domain allowlist, `-k assets/` support, server dry-run, `archetype_alignment_errors()`.
  - `app/pipeline/prober.py` — isolated ephemeral-namespace probing (`Semaphore(2)`), post-node-command readiness wait (`_wait_nodes_ready_after_solution`), and **Post-Cleanup Leak Gate** (`_check_post_cleanup_leaks` verifying no orphaned `pv`, `clusterrole`, `clusterrolebinding` with scenario label remain after cleanup).
  - `app/pipeline/orchestrator.py` — `GenerationPipeline`, `start_fill_gaps()`, `start_for_archetype()`, 2-tier repair.
  - Deleted deprecated legacy modules: `app/composer.py`, `app/fault_units.py`, `tests/test_composer.py`.
- **Transactional Setup Rollback (`app/scenario_engine.py`)**: `apply_setup()` catches setup errors and executes `asyncio.shield(self.cleanup(env))` before re-raising (preserving `asyncio.CancelledError`).
- **SQLite Concurrency & Schema v3 (`app/db.py`)**: Per-path WAL initialization cache (`_WAL_INITIALIZED`), `timeout=10`, `PRAGMA busy_timeout=10000`, `PRAGMA synchronous=NORMAL`, Schema v3 additions (`sessions.variant`, `session_items.{mounted_at, earned_weight, check_pass_ratio, notes_text, checked_tasks_json, hints_used, context_name}`, `archetype_mastery` table, `idx_command_audit_item` index).
- **Legacy Bank Auditor (`app/bank.py`)**: Added `audit_legacy_questions(apply=...)` and CLI `python -m app.bank audit [--apply]`.

---

## Pillar 2 — PSI-Fidelity Mock Exam Runtime & Exam Shell

- **6 Session Variants (`app/sessions.py`)**:
  - `study`, `weakness_drill`, `speed_blitz`, `mistake_replay`, `guided_mock`, `blind_exam`.
- **Non-Destructive Mock Exam Navigation (`mock_exam`)**: Lazy setup mounting cached per item via `mounted_at`; navigating with `Next →` or queue pills preserves prior cluster state without intermediate `cleanup`, and revisiting avoids re-running `apply_setup`. Fixed forward queue indexing (`next()` preserves progression and keeps active question if End Modal is cancelled).
- **Blind Mock Exam (`variant="blind_exam"`)**: Disables immediate `Check`, `Hint`, and post-mortem during active exam; displays **Submit Exam**; batch-grades every mounted item via live `run_checks` inside `finish()` prior to cluster teardown.
- **Weighted Partial Credit (`compute_item_credit` + `CheckSpec.weight_ratio`)**: Computes `pass_ratio` and `earned_weight = envelope.weight * pass_ratio` per item across checks.
- **Multi-Context Exam Kubeconfig (`app/config.py`, `app/ssh_runner.py`)**: `ensure_exam_contexts()` materializes `cka`, `cka-ops`, `cka-edge` in `~/.cka-arena/kubeconfig`, rotated per item in sessions.
- **Exam-Ready Terminal Shell (`app/terminal.py`)**: Writes isolated `.vimrc` (`tabstop=2`, `shiftwidth=2`, `expandtab`), `.cka_env.sh` (`alias k=kubectl`, `$do="--dry-run=client -o yaml"`, `$now="--force --grace-period=0"`, completion), and `.cmd_history.log` preexec logging flushed (secret-redacted) into `command_audit`.
- **Bundled Kustomize Assets (`scenarios/seed/assets/kustomize/`)**: Added base Deployment/Service + `overlays/prod` synced into `~/.cka-arena/assets/kustomize/` via `config.ensure_dirs()`.

---

## Pillar 3 — Full CNCF CKA Curriculum & Pipeline v3

- **Expanded Curriculum (`app/curriculum.py`)**: **59 archetypes** (`Troubleshooting: 13`, `Cluster Architecture: 14`, `Services & Networking: 11`, `Workloads & Scheduling: 13`, `Storage: 8`) + **10 causal incidents**.
- **Gateway API Docs & Gate Alignment (`app/pipeline/gates.py`)**: Added `https://gateway.networking.k8s.io/` and `https://gateway-api.sigs.k8s.io/` to `ALLOWED_DOC_DOMAINS`; enforced `archetype_alignment_errors()` checking `required_kinds`, `required_check_types`, and `required_keywords`; added Reviewer `task_map` rubric and Schema v1.2 `hints` + `fast_solution_commands`.
- **Targeted Generation API (`app/main.py`, `app/planner.py`)**: Added `POST /api/generate/fill-gaps` and `POST /api/generate/archetype/{archetype_id}`.

---

## Pillar 4 — Pedagogical Engine (`app/mastery.py`, `app/bank.py`)

- **SM-2 Spaced Repetition (`mastery.record_outcome`)**: Tracks `attempts`, `passes`, `first_try_passes`, `ewma_solve_ratio`, `mastery_score`, `interval_days`, and `next_review_at` per archetype.
- **CKA Go/No-Go Readiness Report (`GET /api/readiness`)**: Evaluates 4 objective criteria: Last-3 Mock Exam Average (`≥ 78%`), Lowest Domain Floor (`≥ 65%`), Syllabus Coverage (`≥ 80%`), and Median Pacing (`≤ 1.10x`) alongside a 5-domain interactive **Skill Tree**.
- **3-Level Progressive Hints & Speed Coach**:
  - `POST /api/sessions/{id}/hint` (`L1` orientation → `L2` docs/check clue → `L3` reference solution + fast commands).
  - `GET /api/sessions/{id}/postmortem/{item_id}` analyzes `command_audit` usage of `k`, `$do`, `$now`, pacing ratio, and fast imperative commands.
- **Adaptive Disjoint Exam Sampler (`bank.draw_exam_sample`)**: Enforces disjoint setup namespaces and non-colliding node fault targets during mock exam generation, plus prioritized sorting (`due_rank` → `weak_rank` → `unseen_rank`) for `weakness_drill`, `speed_blitz`, and `mistake_replay`.

---

## Pillar 5 — Workspace & Exam UX Pro (`static/`)

- **Fixed Double `renderReport()` Bug (`static/js/workspace.js`)**: Eliminated duplicate check drawer rendering and doubled failure hint counts.
- **CKA Readiness View (`static/js/readiness.js`, `⌘2`)**: Go/No-Go readiness gauge, 4 criteria cards, 1-click drills (`Weakness Drill`, `Speed Blitz`, `Mistake Replay`, `Blind Mock Exam`), and 5-domain Skill Tree with `Practice` and `+ Gen` buttons.
- **Workspace Pro Features (`static/index.html`, `static/css/app.css`, `static/js/{app,workspace,terminal,studio}.js`)**:
  - Draggable split pane (`--split-left` persisted in `localStorage`) + `⌘B` **Zen Terminal** toggle + `⌘/` **Keyboard Shortcuts & Shell Cheat-Sheet** modal.
  - Native scrollback search (`⌘F`) inside xterm terminal buffer.
  - `▶` Quick-Run buttons on context & SSH pills, clickable **Task Checklist**, per-question **Exam Notepad** (`PUT /api/sessions/{id}/items/{item_id}/state`), Allowed CKA Docs bar, cluster transition loading spinner (`#workspace-loading`), `◐` mounted queue indicators, live pacing indicator (`#exam-pacing`), 3-level Hint Drawer, Post-Mortem & Speed Coach Drawer, and per-item partial credit score breakdown table at Finish.
  - Studio **Fill Weak Cells (`5×3`)**, **Audit Legacy Bank**, and 6-mode Practice selector.

---

## Verified Test & Live Benchmark Metrics (2026-11-22)

- **Pytest Suite**: **125 passed, 0 failed** (`tests/test_v3_architecture.py` + all existing unit/API tests in isolated `tmp_path` DBs).
- **Frontend Validation**:
  - `node --check` passed on all `static/js/*.js` files (`ALL JS VALID`).
  - Static audit confirmed **142/142 HTML element IDs** and **44/44 frontend API route calls** match backend FastAPI endpoints.
  - ASGI HTTP `200 OK` verified for `/` and all 7 static CSS/JS assets.
- **Database Cleanup & Legacy Audit (`data/cka_arena.db`)**:
  - Removed `2` leaked `model='fake'` rows from `llm_generations` (`2 → 0`).
  - `python -m app.bank audit --apply` scanned `34` legacy LLM questions and retired `7` excess `Services & Networking` `exam_standard` clone bloat rows.
- **Multi-Context & Kustomize Asset Dry-Run**:
  - Verified contexts `cka`, `cka-ops`, `cka-edge` in `~/.cka-arena/kubeconfig` against live Kubernetes `v1.37.2` (`controlplane`, `node01`, `node02` Ready).
  - `kubectl apply -k ~/.cka-arena/assets/kustomize/overlays/prod --dry-run=server` succeeded.
- **Live Seed Validation (`python -m app.seed validate`)**:
  - **17 / 17 `PROBE OK`** in **2m 06.60s** with Post-Cleanup Leak Gate active.
- **Live DeepSeek + Multipass Pipeline v3 Benchmark**:
  - `archetype:ca-kustomize-overlay` → **1/1 published (`q-521ad325ff06`) in 22.5s** (`schema_version=1.2`, `hints=2`, `fast_cmds=3`, `alignment_errors=[]`).
  - `archetype:wl-hpa-autoscale` → **1/1 published (`q-20223ee1c288`) in 18.9s** (`schema_version=1.2`, `hints=2`, `fast_cmds=1`, `alignment_errors=[]`).
  - `fill-gaps:2` (`killer_hardcore`) → **2/2 published (`q-e64deeae3b2e` Search SecurityContext, `q-016861636b12` etcd Snapshot) in 296.4s**, `quarantined=0`, filled the `Workloads & Scheduling · killer_hardcore` empty cell.
  - **Post-Benchmark Cluster Drift (`Teardown.drift()`)**: `drift: false` across `controlplane`, `node01`, `node02` (`leftovers: []`).
  - Active published question bank after benchmark: **55 published scenarios** across 5 CKA domains (`38 llm` + `17 seed`).
