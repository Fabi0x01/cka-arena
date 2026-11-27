# Implementation Readiness — Final Audit Verdict

> **Historical record (2026-11-17) — frozen.** Pre-implementation authorization gate; all phases were implemented afterwards. Kept as a record of the D1–D4 decisions and accepted risks. Current state: `README.md` and `ARCHITECTURE.md`.
>
> Translated from the original pt-BR.

> End-to-end coherence audit of the documentation (10 files, 3 revisions) before implementation authorization. Date: 2026-11-17.

---

## Verdict: ✅ READY WITH CONDITIONS

The specification covers **all 5 roadmap phases** with verifiable contracts (schema, endpoints, machine states, rubrics, design system). Nothing blocks the start of **Phase 1**. **4 owner decisions** are recommended before coding phases 3–5 (none blocks Phases 1–2).

### Fixes applied by this audit (mechanical gaps closed)

| Finding | Fix |
| :--- | :--- |
| Inconsistent management labels (`cka-arena/scenario-id` vs `cka-arena.io/managed`) | Single policy in `ARCHITECTURE.md` §4.3: `cka-arena.io/managed="true"` (L1 sweep) + `cka-arena.io/scenario="<id>"` (L0 cleanup) + `cka-arena.io/probe="true"` (probes, TTL 120s) |
| API without a consolidated reference; `/api/generate` without a contract; `{tab}` vs `{tab_id}` | New `ARCHITECTURE.md` §13 — complete table of 13 endpoints + cross-cutting rules (`202 {job_id}`, error envelope, session check/next/skip/reset endpoints) |
| Overlap between `llm_generator.py` and `pipeline.py` in the tree | Merged: `pipeline.py` absorbs the prompt builder and the self-repair loop |
| Consistency sweep | Zero leftovers from older revisions (dual-window, pt-BR UI, `scenarios` table, `prompt_pt_br`); fences, envelope JSON, SVG and internal links validated |

---

## Coverage Matrix by Phase (what is already specified, and where)

| Phase | Output contract | Specification | Gaps |
| :--- | :--- | :--- | :--- |
| **1. Foundation + Power Manager + Doctor + SSH Bridge** | `pyproject`, setup_ssh_bridge (expect + dedicated kubeconfig), machine states, 7-step boot, node file baseline | `ARCHITECTURE.md` §3, §9, §13 · `PLAN.md` Phase 1 | none |
| **2. ScenarioEngine + Teardown** | setup/check/cleanup, 10 check types, PASS/FAIL/SKIP/ERROR contract, L0/L1/L2 | `LLM_SCENARIO_SPEC.md` §2 · `LLM_PIPELINE_SPEC.md` §5–§6 · `ARCHITECTURE.md` §12 | none |
| **3. Pipeline A→E + Question Bank** | envelope v1.1 (English, killer.sh format, `solution`), stages A–E, prove-out + Solvability Probe, difficulty rubric §5, `draw_exam_sample` | `LLM_SCENARIO_SPEC.md` §1, §1.2, §4, §5 · `LLM_PIPELINE_SPEC.md` §1–§4 · `ARCHITECTURE.md` §11 | none **for the design**; requires decisions D1 (default provider) and D2 (destructive scenarios) |
| **4. Integrated UI + Liquid Glass** | single shell, tokens, 3 glass materials, components, motion, performance floor, EN wireframes | `DESIGN.md` (with ready CSS) · `UX_UI_SPEC.md` §1–§6 · `design/mockup-workspace.svg` | none |
| **5. Seeds + Telemetry** | 15 seeds published via gates A–E, coverage grid, dashboard | `PLAN.md` Phase 5 · `ARCHITECTURE.md` §7, §11 | authoring effort (not design); see D4 |

---

## Owner Decisions (D1–D4) — **ALL CLOSED on 2026-11-17** ✅

### D1 — Primary LLM provider and key origin ✅ **DECIDED**
Supported catalog: GLM Coding Plan (Z.AI), OpenCode Go, DeepSeek, Anthropic, OpenAI-compatible/Ollama.
**Decision:** GLM Coding Plan (`glm-5.3` primary / `glm-5.3-flash` for Normalizer+Reviewer) with **DeepSeek as fallback** — same multi-provider pattern already validated locally. Configuration is done **through the UI (Settings → AI provider)** and persisted in a local `llm_config.json` (git-ignored); the key never enters the repository.

### D2 — Destructive scenario policy ✅ **DECIDED (recommendation accepted)**
The CKA curriculum includes tasks that change the global state of the cluster (e.g. `etcdctl snapshot restore` + apiserver restart). During practice, this leaves the cluster in a non-clean state for the next question.
**Decision:** the envelope gains a `destructive: true` flag (Gate D forces declaring it — already propagated to `LLM_SCENARIO_SPEC.md` §1.1/§3); destructive questions only enter `mock_exam` sessions; upon completing them, the UI offers L2 (clean reset) automatically before `Next`; the 15 initial seeds include only `etcd snapshot save` (no restore), with restore variants entering later via the LLM and the `destructive` flag.

### D3 — Behavior flag defaults ✅ **DECIDED (recommendation accepted)** *(applicable from Phase 1 on)*
| Flag | Recommendation | Rationale |
| :--- | :--- | :--- |
| `auto_start_on_launch` | **ON** | original requirement: "cluster initialized along with the application" |
| `auto_publish` (question bank) | **ON** | questions that passed gates A–E are already trustworthy; `draft` continues to exist for rejected ones |
| `command_audit` | **OFF** | privacy by default; turn on when approach telemetry is wanted |
| `CKA_ARENA_TOKEN` | undefined | local-only; set only if exposing on the home network |

### D4 — Internal ordering of Phase 5 ✅ **DECIDED (recommendation accepted)**
**Decision:** **3 exemplary seeds** (Troubleshooting, Cluster Architecture, Services & Networking) enter at the end of **Phase 2** — they validate the engine (setup→check→cleanup) before the LLM exists; the **remaining 12** follow in Phase 5, published by the same gates A–E (already reflected in `PLAN.md` Phases 2/5).

---

## Authorization Checklist

- [x] D1 confirmed (provider + key origin) — GLM + DeepSeek fallback
- [x] D2 confirmed (destructive policy) — `destructive` flag + L2 before `Next`
- [x] D3 confirmed — defaults accepted (`auto_start_on_launch` ON · `auto_publish` ON · `command_audit` OFF · no token)
- [x] D4 confirmed — 3 seeds in Phase 2, 12 in Phase 5
- [x] **Project authorized for implementation** — all decisions closed; start with Phase 1

## Known and accepted risks (no decision required now)

1. **DHCP may change the Bridged IPs** — mitigation already specified (kubeconfig self-heal + ssh-config regeneration on every boot, `ARCHITECTURE.md` §9.3).
2. **`feDisplacementMap` refraction is Chrome-only** — progressive enhancement; the visual does not depend on it (`DESIGN.md` §4).
3. **VM snapshots are not supported on the Multipass/macOS backend** (verified live: `The snapshots feature is not implemented on this backend`) — L2 was redefined as a **clean reset** (file baseline + agent restart), validated with `drift=false` and addons preserved.
4. **LLM generation cost** — Normalizer/Reviewer on a flash model and 1 call per scenario in the Builder; rejected ones ≤ 2 retries (`LLM_PIPELINE_SPEC.md` §2).
