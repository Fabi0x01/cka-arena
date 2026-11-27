# CKA Arena — Product Truth

> Durable context for design and product. Single source of truth about what the platform is; visual decisions live in [`DESIGN.md`](./DESIGN.md).

## What it is

A local hands-on practice platform for the **Certified Kubernetes Administrator (CKA)** exam, in the style of exam simulators, running against a real `kubeadm` lab (three nodes: Multipass VMs on macOS/Linux or kind containers on WSL2/Linux with Docker). Four mechanisms combine:

1. **Real terminal in the browser** (host PTY in xterm.js) next to the question — solve and request validation without leaving the window.
2. **Lab managed by the platform** — on/off button, instrumented boot and clean reset (L2) at the end of the session, preserving the addons.
3. **AI scenario generator** — multi-stage pipeline (archetype planning → Builder → deterministic gates → Reviewer → solvability prove-out) that publishes questions to a question bank; practice draws them using the official exam weights.
4. **Data-driven pedagogy** — spaced repetition by archetype, Go/No-Go readiness report, targeted drills and the Study Codex.

## Who it is for

A single user: whoever is in front of the machine — an experienced engineer, studying for the CKA in high-concentration sessions (30–120 min), with the browser in full screen or close to it. There is no second user, no real mobile, no public demo.

## What the surface must prove

- **Operational trust:** the user reads the question prompt, solves it in the terminal, clicks Check and believes the verdict — the interface is the control panel of a real cluster, not an animated course.
- **Frictionless flow:** every second of interaction is study cost; no decorative animation, slow loading or context switching between screens.
- **State always visible:** cluster (on/off/degraded), question (queue, timer, check), session (progress, end, cleanup).

## Surface mode

**Operate** — a high-concentration tool. Scannability, consistency and native expectations above expression; the brand lives in precise details.

## Brand commitments

- **Orbital Control Console** visual identity: a mission console over dark anodized surfaces, hierarchy through luminance steps, with translucent glass reserved for the top layers (full contract in [`DESIGN.md`](./DESIGN.md)).
- A single frontend standard: **all views share the same shell** — no two "pages" differ from each other.
- Accessibility **explicitly out of scope** at this stage (maintainer's decision; `prefers-reduced-motion` remains respected at zero cost).
- **System language: 100% English** (UI, question prompts, hints, solutions, toasts) — the CKA exam is in English; reading tasks in the exam language is part of the training. All project documentation is in English.
