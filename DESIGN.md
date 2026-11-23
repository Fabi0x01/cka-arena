# CKA Arena — Design System "Orbital Control Console"

> Visual system authority for **CKA Arena**. Mode: **Operate** (high-focus technical mission control for Kubernetes CKA preparation). Product truth lives in [`PRODUCT.md`](./PRODUCT.md).

---

## 1. Visual World & Principles

**CKA Arena** is built as a recessed anodized-obsidian mission console (`oklch` hue `252`). Rather than decorative translucent chrome across primary panels, hierarchy comes from calibrated luminance steps (`--canvas` → `--bay` → `--surface` → `--surface-raised`), crisp `1px` structural hairline seams, and restrained semantic telemetry colors.

### Core Rules
1. **Single Window Shell:** Left `54px` Navigation Rail (`Arena ⌘1`, `Readiness ⌘2`, `Studio ⌘3`, `Settings ⌘4`, Command Palette `⌘K`, Cluster Power, Shortcuts `⌘/`) frames a `48px` Context Topbar and recessed dual-bay workspace.
2. **Matte Content Surfaces:** Question Reader and `xterm.js` PTY Viewport always render over flat matte surfaces (`--bay` and `--terminal-bg` `#0A0D13`) with zero `backdrop-filter` blur behind scrolling text.
3. **Top-Layer Glass Reserve:** Translucent blur (`backdrop-filter: blur(20px)`) is reserved strictly for interrupting top-layer `<dialog>` modals and Command Palette (`⌘K`).
4. **Hairline Edge OR Compact Drop:** Primary controls rely on defined `1px` borders; overlays pair hairline edges with compact crisp elevation (`0 6px 10px`).
5. **Unified Vector Iconography:** Zero emoji icons in UI chrome. Every icon uses inline `1.6px`-stroke SVGs from `static/js/icons.js`.

---

## 2. Color Tokens (`oklch()` Dark Theme)

Defined in [`static/css/tokens.css`](./static/css/tokens.css) using `@layer tokens`:

| Token | Value | Role |
| :--- | :--- | :--- |
| `--canvas` | `oklch(11.5% 0.009 252)` | Shell background & hairline divider wells |
| `--bay` | `oklch(14.2% 0.010 252)` | Left rail, topbar, recessed pane ground |
| `--surface` | `oklch(17.5% 0.011 252)` | Interactive cards, tabs, copy-pills, secondary controls |
| `--surface-raised` | `oklch(21.2% 0.012 252)` | Hovered controls, active subtabs, popovers |
| `--terminal-bg` | `oklch(10.0% 0.007 252)` | Matte OLED `xterm.js` viewport |
| `--ink` | `oklch(94.0% 0.006 252)` | Primary copy & headings |
| `--ink-muted` | `oklch(72.0% 0.012 252)` | Metadata, descriptions, labels |
| `--ink-faint` | `oklch(54.0% 0.014 252)` | Group eyebrows, disabled ink, workdir hint |
| `--accent` | `oklch(76.0% 0.145 208)` | Ice Cyan — primary Check CTA, active rail bar, cursor |
| `--pass` | `oklch(75.0% 0.165 158)` | Pass Mint — verified checks, unlocked `Next →`, Ready nodes |
| `--warn` | `oklch(81.0% 0.155 82)` | Warn Amber — mounted/ungraded exam items, `<90s` timer |
| `--fail` | `oklch(67.0% 0.205 18)` | Fail Coral — failed checks, `<60s` timer, danger reset |
| `--flag` | `oklch(71.0% 0.165 292)` | Flag Violet — flagged mock exam review markers |

Tints (`--accent-tint`, `--pass-tint`, `--warn-tint`, `--fail-tint`, `--flag-tint`, `--hover-bg`) are computed with `color-mix(in oklab, ...)` so neutrals remain strictly achromatic in Chromium.

---

## 3. Typography & Layout Architecture

- **Typefaces:** `Figtree` (`400–700`) for UI & formatted Markdown prompts (`max-inline-size: 68ch`); `JetBrains Mono` (`400–700`) with `font-variant-numeric: tabular-nums` for timers, weights, YAML blocks, terminal PTY, and scores.
- **Scale (`rem` fixed for Operate mode):** `--text-xs: 0.78rem` (`12.48px`) up to `--text-display: 2.75rem`. No body text renders below `12px`.
- **Layered CSS Cascade (`@layer reset, tokens, base, layout, components, views`):**
  - [`tokens.css`](./static/css/tokens.css)
  - [`base.css`](./static/css/base.css) (browser UI theming: scrollbars, selection, caret, focus rings, reduced motion)
  - [`layout.css`](./static/css/layout.css) (rail, topbar, split workspace, view-panels, Zen/Native modes)
  - [`components.css`](./static/css/components.css) (buttons, inputs, native `<dialog>` animations via `@starting-style` + `transition-behavior: allow-discrete`, `[popover="auto"]` anchored via CSS Anchor Positioning, Command Palette)
  - [`views.css`](./static/css/views.css) (Arena Mission Control & Markdown reader, Readiness Orbital Threshold Scale Bar & Skill Tree filters, Studio CI/CD Stage Stepper & clickable 5×3 Heatmap, Settings 3-node Hardware Grid)

---

## 4. Native Overlays, Transitions & Keyboard Contract

- **View Transitions:** Switching between `Arena`, `Readiness`, `Studio`, and `Settings` runs inside `document.startViewTransition()` on `view-transition-name: main-surface`.
- **Command Palette (`⌘K`):** Top-layer `<dialog>` providing single-keystroke access to view jumps, instant practice presets, Check/Next, SSH node tabs (`controlplane`, `node01`, `node02`), Zen Mode (`⌘B`), and scrollback Find (`⌘F`). (`⌘L` clears the active terminal.)
- **Anchored Popovers (`popover="auto"`):** Cluster Power menu (`#power-menu`) and Terminal `+ Shell` menu (`#new-tab-menu`) use native top-layer placement with `@supports (position-area: block-end)` anchor positioning and fixed-inset fallbacks.
