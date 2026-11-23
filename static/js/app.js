// app.js — Orbital Control Console shell, rail navigation, View Transitions, Command Palette (⌘K), dialogs
import { api, createEventBus } from "./api.js";
import { el, toast, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js";
import { iconEl } from "./icons.js?v=3.4";
import { initPower } from "./power.js";
import { initTerminal } from "./terminal.js?v=3.4";
import { initWorkspace } from "./workspace.js";
import { initStudio } from "./studio.js?v=3.4";
import { initReadiness } from "./readiness.js";
import { initStudy } from "./study.js?v=3.7";
import { initSettings } from "./settings.js";
import { initPalette } from "./palette.js";

const bus = createEventBus();
const state = { session: null, cluster: null, bank: null, panel: null };
let examTimerHandle = null;
let expiredNotifiedId = null;

const terminal = initTerminal();
const workspace = initWorkspace({
  onSessionChanged: (session) => {
    state.session = session;
    renderQueue();
    syncExamTimer();
    syncSessionControls();
  },
  onFinished: (session) => openEndModal(session),
  onSubmitExam: (session) => openEndModal(session),
  onBankInvalidated: () => studio.refreshCoverage(),
  focusTerminal: () => terminal.focus(),
  sendCommand: (cmd) => {
    if (document.body.classList.contains("native-mode")) toggleNative(false);
    terminal.sendCommand(cmd);
  },
});
const power = initPower(bus, (status) => {
  state.cluster = status;
});
const studio = initStudio({
  bus,
  onSessionStarted: (session) => {
    workspace.setSession(session);
    showPanel(null);
  },
  onBankChanged: (count) => {
    state.bank = count;
    renderBankLine();
  },
  openWorkspace: () => showPanel(null),
  getActiveSession: () => state.session,
  onEndActiveSession: () => {
    if (state.session?.session?.status === "active") openEndModal(state.session, { early: true });
  },
});
const readiness = initReadiness({
  onSessionStarted: (session) => {
    workspace.setSession(session);
    showPanel(null);
  },
  openWorkspace: () => showPanel(null),
  openStudio: () => showPanel("studio"),
});
const study = initStudy({
  onSessionStarted: (session) => {
    workspace.setSession(session);
    showPanel(null);
  },
  openWorkspace: () => showPanel(null),
  openStudio: () => showPanel("studio"),
  getActiveSession: () => state.session,
  onEndActiveSession: () => {
    if (state.session?.session?.status === "active") openEndModal(state.session, { early: true });
  },
  runInTerminal: (cmd) => {
    showPanel(null);
    if (document.body.classList.contains("native-mode")) toggleNative(false);
    terminal.sendCommand(cmd);
  },
});
const settings = initSettings({ onPowerChanged: () => power.refresh() });

bus.on("cluster.reset.done", (event) => {
  if (event.ok) {
    toast(`Clean reset finished (nodes ready: ${event.nodes_ready}) · drift: ${event.drift}`, event.drift ? "error" : "success", 6000);
  } else {
    toast(`Clean reset failed: ${event.error}`, "error", 6000);
  }
  power.refresh();
  settings.refreshAll();
});

// ------------------------------------------------------------ views & View Transitions

const PANEL_TITLES = {
  null: "Arena",
  readiness: "CKA Readiness",
  studio: "Scenario Studio",
  settings: "Cluster & Settings",
  study: "CKA Study Codex",
};

function applyPanelDOM(name) {
  state.panel = name || null;
  el("content").hidden = Boolean(name);
  el("view-readiness")?.classList.toggle("active", name === "readiness");
  el("view-studio").classList.toggle("active", name === "studio");
  el("view-settings").classList.toggle("active", name === "settings");
  el("view-study")?.classList.toggle("active", name === "study");
  el("btn-view-arena").classList.toggle("on", !name);
  el("btn-view-readiness")?.classList.toggle("on", name === "readiness");
  el("btn-view-studio").classList.toggle("on", name === "studio");
  el("btn-view-settings").classList.toggle("on", name === "settings");
  el("btn-view-study")?.classList.toggle("on", name === "study");

  const topbarTitle = el("topbar-view-title");
  if (topbarTitle) {
    if (!name && state.session?.session) {
      topbarTitle.textContent = state.session.session.title || "Arena";
    } else {
      topbarTitle.textContent = PANEL_TITLES[String(name)] || "Arena";
    }
  }
  el("queue").hidden = Boolean(name);

  if (name === "readiness") readiness.refresh();
  if (name === "settings") settings.refreshAll();
  if (name === "study") study.refresh();
  if (name === "studio") {
    studio.refreshCoverage();
    studio.recoverJob?.();
  }
  if (!name) requestAnimationFrame(() => terminal.fitActive?.());
}

function showPanel(name) {
  const target = name || null;
  if (target === state.panel) {
    applyPanelDOM(target);
    return;
  }
  if (document.startViewTransition) {
    document.startViewTransition(() => applyPanelDOM(target));
  } else {
    applyPanelDOM(target);
  }
}

el("btn-view-arena").onclick = () => showPanel(null);
el("btn-view-readiness")?.addEventListener("click", () => showPanel("readiness"));
el("btn-view-studio").onclick = () => showPanel("studio");
el("btn-view-settings").onclick = () => showPanel("settings");
el("btn-view-study")?.addEventListener("click", () => showPanel("study"));
el("empty-generate").onclick = () => showPanel("studio");
document.addEventListener("open-settings", () => showPanel("settings"));

function toggleNative(force) {
  const next = typeof force === "boolean" ? force : !document.body.classList.contains("native-mode");
  if (next && document.body.classList.contains("zen-mode")) {
    document.body.classList.remove("zen-mode");
    const zenBtn = el("btn-zen");
    if (zenBtn) {
      zenBtn.classList.remove("primary");
      zenBtn.textContent = "Zen";
    }
  }
  document.body.classList.toggle("native-mode", next);
  el("btn-native")?.classList.toggle("primary", next);
  const showBtn = el("btn-show-terminal");
  if (showBtn) showBtn.hidden = !next;
  if (next) {
    toast("Built-in terminal hidden — click Show Terminal or press ⌘\\ to restore");
  } else {
    requestAnimationFrame(() => terminal.fitActive?.());
  }
}

function toggleZen(force) {
  const next = typeof force === "boolean" ? force : !document.body.classList.contains("zen-mode");
  if (next && document.body.classList.contains("native-mode")) toggleNative(false);
  document.body.classList.toggle("zen-mode", next);
  const zenBtn = el("btn-zen");
  if (zenBtn) {
    zenBtn.classList.toggle("primary", next);
    zenBtn.textContent = next ? "Exit Zen" : "Zen";
  }
  requestAnimationFrame(() => terminal.fitActive?.());
}

el("btn-native")?.addEventListener("click", () => toggleNative());
el("btn-show-terminal")?.addEventListener("click", () => toggleNative(false));
el("btn-zen")?.addEventListener("click", () => toggleZen());
el("btn-term-check").onclick = () => workspace.check();

function syncSessionControls() {
  const active = state.session?.session?.status === "active";
  if (el("btn-end-session")) el("btn-end-session").hidden = !active;
}

el("btn-end-session")?.addEventListener("click", () => {
  if (state.session?.session?.status === "active") openEndModal(state.session, { early: true });
});

// Resizable split-pane
(function initSplit() {
  const handle = el("split-handle");
  const saved = localStorage.getItem("cka_split_pct");
  if (saved) document.documentElement.style.setProperty("--split-left", `${saved}%`);
  if (!handle) return;
  let dragging = false;
  handle.addEventListener("mousedown", (e) => {
    dragging = true;
    handle.classList.add("dragging");
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const rect = el("content").getBoundingClientRect();
    if (!rect.width) return;
    const pct = Math.min(66, Math.max(26, Math.round(((e.clientX - rect.left) / rect.width) * 100)));
    document.documentElement.style.setProperty("--split-left", `${pct}%`);
    localStorage.setItem("cka_split_pct", String(pct));
    terminal.fitActive?.();
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove("dragging");
    terminal.fitActive?.();
  });
})();

const shortcutsDialog = el("shortcuts-modal");
wireDialogBackdropDismiss(shortcutsDialog, () => closeDialog(shortcutsDialog));
el("btn-shortcuts")?.addEventListener("click", () => openDialog(shortcutsDialog));
el("shortcuts-close")?.addEventListener("click", () => closeDialog(shortcutsDialog));

// ------------------------------------------------------------ Command Palette (⌘K)
const palette = initPalette({
  getActions: () => {
    const hasActive = state.session?.session?.status === "active";
    const isNative = document.body.classList.contains("native-mode");
    return [
      { group: "Navigation", label: "Arena Workspace", icon: "terminal", shortcut: "⌘1", run: () => showPanel(null) },
      { group: "Navigation", label: "CKA Readiness & Skill Tree", icon: "gauge", shortcut: "⌘2", run: () => showPanel("readiness") },
      { group: "Navigation", label: "Scenario Studio & Bank", icon: "sparkles", shortcut: "⌘3", run: () => showPanel("studio") },
      { group: "Navigation", label: "Cluster Telemetry & Settings", icon: "sliders", shortcut: "⌘4", run: () => showPanel("settings") },
      { group: "Navigation", label: "CKA Study Codex & Cheat Sheets", icon: "bookOpen", shortcut: "⌘5", run: () => showPanel("study") },
      { group: "Navigation", label: "Continue Next Study Topic", icon: "award", run: () => { showPanel("study"); study.openRecommended(); } },
      { group: "Navigation", label: "Study Speed Recall Blitz (10 Qs)", icon: "zap", run: () => { showPanel("study"); study.openSpeedRecall(); } },
      { group: "Exam Actions", label: "Configure New Session…", icon: "play", run: () => studio.openPractice() },
      ...(hasActive
        ? [{ group: "Exam Actions", label: "End Active Session & Clean Cluster", icon: "square", run: () => openEndModal(state.session, { early: true }) }]
        : []),
      { group: "Exam Actions", label: "Run Check on Active Question", icon: "checkCircle", shortcut: "⌘↵", run: () => workspace.check() },
      { group: "Exam Actions", label: "Advance to Next Question", icon: "arrowRight", shortcut: "⌘⇧↵", run: () => workspace.next() },
      { group: "Exam Actions", label: "Start Study Mode (5)", icon: "check", run: () => { showPanel(null); workspace.launchQuick("study", 5); } },
      { group: "Exam Actions", label: "Start Blind Mock Exam (15)", icon: "clock", run: () => { showPanel(null); workspace.launchQuick("blind_exam", 15); } },
      { group: "Exam Actions", label: "Start Weakness Drill (5)", icon: "zap", run: () => { showPanel(null); workspace.launchQuick("weakness_drill", 5); } },
      { group: "Terminal & Nodes", label: isNative ? "Show Built-in Terminal" : "Hide Built-in Terminal (Native Mode)", icon: "layoutSplit", shortcut: "⌘\\", run: () => { showPanel(null); toggleNative(); } },
      { group: "Terminal & Nodes", label: "Toggle Zen Terminal", icon: "maximize", shortcut: "⌘B", run: () => { showPanel(null); toggleZen(); } },
      { group: "Terminal & Nodes", label: "Search Terminal Scrollback", icon: "search", shortcut: "⌘F", run: () => { showPanel(null); if (isNative) toggleNative(false); terminal.openSearch?.(); } },
      { group: "Terminal & Nodes", label: "Increase Terminal Font", icon: "plus", shortcut: "⌘+", run: () => { showPanel(null); terminal.adjustFont?.(1); } },
      { group: "Terminal & Nodes", label: "Decrease Terminal Font", icon: "command", shortcut: "⌘-", run: () => { showPanel(null); terminal.adjustFont?.(-1); } },
      { group: "Terminal & Nodes", label: "Reset Terminal Font", icon: "refreshCw", shortcut: "⌘0", run: () => { showPanel(null); terminal.resetFont?.(); } },
      { group: "Terminal & Nodes", label: "Open Local Scratch Tab", icon: "terminal", run: () => { showPanel(null); toggleNative(false); terminal.openTab("host", null, "mac"); } },
      { group: "Terminal & Nodes", label: "Open SSH: controlplane", icon: "server", run: () => { showPanel(null); toggleNative(false); terminal.openTab("node", "controlplane", "controlplane"); } },
      { group: "Terminal & Nodes", label: "Open SSH: node01", icon: "server", run: () => { showPanel(null); toggleNative(false); terminal.openTab("node", "node01", "node01"); } },
      { group: "Terminal & Nodes", label: "Open SSH: node02", icon: "server", run: () => { showPanel(null); toggleNative(false); terminal.openTab("node", "node02", "node02"); } },
      { group: "Cluster & Reference", label: "Keyboard Shortcuts & Shell Profile", icon: "helpCircle", shortcut: "⌘/", run: () => openDialog(shortcutsDialog) },
      { group: "Cluster & Reference", label: "Refresh Cluster Health", icon: "refreshCw", run: () => { power.refresh(); settings.refreshHealth?.(); } },
    ];
  },
});

el("btn-palette")?.addEventListener("click", () => palette.open());
el("btn-topbar-palette")?.addEventListener("click", () => palette.open());

// ------------------------------------------------------------ queue + mock/blitz exam timer
function syncExamTimer() {
  clearInterval(examTimerHandle);
  examTimerHandle = null;
  const badge = el("exam-timer");
  const paceEl = el("exam-pacing");
  const sess = state.session?.session;
  if (!sess || !sess.time_limit_minutes || sess.status !== "active") {
    badge.hidden = true;
    if (paceEl) paceEl.hidden = true;
    return;
  }
  badge.hidden = false;
  if (paceEl) paceEl.hidden = false;
  const label = sess.variant === "speed_blitz" ? "BLITZ" : "EXAM";
  const totalSec = sess.time_limit_minutes * 60;
  const startMs = (sess.started_at || Date.now() / 1000) * 1000;
  const targetPerItem = sess.time_limit_minutes / Math.max(1, sess.counts?.total || 15);
  const update = () => {
    const elapsed = Math.max(0, (Date.now() - startMs) / 1000);
    const rem = Math.max(0, totalSec - elapsed);
    const mins = Math.floor(rem / 60);
    const secs = Math.floor(rem % 60);
    badge.textContent = `${label} ${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    badge.classList.toggle("warn", rem <= 15 * 60 && rem > 5 * 60);
    badge.classList.toggle("bad", rem <= 5 * 60);
    if (paceEl) {
      const mountedOrDone = Math.max(1, sess.counts?.mounted || 1);
      const avgMin = (elapsed / 60) / mountedOrDone;
      paceEl.textContent = `pace ${avgMin.toFixed(1)}m/q · target ${targetPerItem.toFixed(1)}m`;
      paceEl.classList.toggle("ok", avgMin <= targetPerItem);
      paceEl.classList.toggle("slow", avgMin > targetPerItem * 1.15);
    }
    if (rem === 0 && expiredNotifiedId !== sess.id) {
      expiredNotifiedId = sess.id;
      toast("Time is up! Submit your session for grading.", "error", 6000);
      if (sess.mode === "mock_exam" && !endDialog.open && state.session) {
        openEndModal(state.session, { timedOut: true });
      }
    }
  };
  update();
  examTimerHandle = setInterval(update, 1000);
}

function renderQueue() {
  const queue = el("queue");
  queue.innerHTML = "";
  const topbarTitle = el("topbar-view-title");
  if (!state.session) {
    if (topbarTitle && !state.panel) topbarTitle.textContent = "Arena";
    return;
  }
  if (topbarTitle && !state.panel) topbarTitle.textContent = state.session.session.title || "Arena";
  const isMock = state.session.session?.mode === "mock_exam";
  for (const item of state.session.items) {
    const pill = document.createElement("span");
    const index = item.order_index + 1;
    if (item.state === "passed") {
      pill.className = "pill pass";
      pill.append(iconEl("checkCircle", 12), document.createTextNode(`Q${index}`));
    } else if (item.state === "active") {
      pill.className = "pill active";
      pill.append(iconEl("terminal", 12), document.createTextNode(`Q${index}`));
    } else if (item.state === "skipped") {
      pill.className = "pill bad";
      pill.append(iconEl("xCircle", 12), document.createTextNode(`Q${index}`));
    } else if (item.mounted) {
      pill.className = "pill warn";
      pill.append(iconEl("clock", 12), document.createTextNode(`Q${index}`));
    } else {
      pill.className = "pill";
      pill.textContent = `Q${index}`;
    }
    if (item.flagged) {
      pill.classList.add("flagged");
      const flg = iconEl("flag", 11);
      flg.style.color = "var(--flag)";
      pill.appendChild(flg);
    }
    if (isMock && item.state !== "active") {
      pill.classList.add("clickable");
      pill.title = `Switch to Q${index}: ${item.title}`;
      pill.onclick = () => workspace.selectItem(item.id);
    }
    queue.appendChild(pill);
  }
}

function renderBankLine() {
  el("bank-line").textContent = state.bank !== null
    ? `${state.bank} published scenarios · drawn by official CKA weights.`
    : "Bank …";
}

// ------------------------------------------------------------ session end <dialog>
let endingSession = null;
const endDialog = el("end-modal");
wireDialogBackdropDismiss(endDialog, () => {
  endingSession = null;
  closeDialog(endDialog);
});

function openEndModal(session, { early = false, timedOut = false } = {}) {
  endingSession = session;
  const variant = session.session.variant || (session.session.mode === "mock_exam" ? "guided_mock" : "study");
  const passed = session.session.counts?.passed ?? 0;
  const total = session.session.counts?.total ?? 0;
  const isBlind = variant === "blind_exam";
  if (el("end-title")) {
    el("end-title").textContent = timedOut
      ? "Time's Up — Submit Exam"
      : isBlind
        ? "Submit Blind Mock Exam"
        : early
          ? "End Active Session"
          : "Session Complete";
  }
  el("end-sub").textContent = timedOut
    ? "The exam timer reached 00:00. Submit now to grade all mounted tasks and clean the cluster."
    : isBlind
      ? "Submit your Blind Mock Exam? All mounted tasks will be graded before cluster cleanup."
      : early
        ? `${passed}/${total} passed so far · ending will stop this session and clean the mounted cluster scenario.`
        : `${passed}/${total} passed · choose how to clean the cluster.`;
  el("end-summary").innerHTML = "";
  el("end-cleanup-field").style.display = "";
  const finishLabel = isBlind ? "Grade Exam & clean up" : early ? "End & clean up" : "Finish & clean up";
  el("end-finish").textContent = finishLabel;
  el("end-finish").dataset.label = finishLabel;
  el("end-finish").hidden = false;
  el("end-cancel").hidden = false;
  el("end-close").hidden = true;
  openDialog(endDialog);
}

el("end-cancel")?.addEventListener("click", () => {
  endingSession = null;
  closeDialog(endDialog);
});

el("end-finish").onclick = async () => {
  if (!endingSession) return;
  const reset = document.querySelector('input[name="end-reset"]:checked')?.value || "fast";
  const button = el("end-finish");
  button.disabled = true;
  button.textContent = "Grading & cleaning…";
  try {
    const result = await api(`/api/sessions/${endingSession.session.id}/finish`, {
      method: "POST",
      body: { reset },
    });
    const summary = result.summary;
    const list = el("end-summary");
    list.innerHTML = "";
    const addRow = (text, color = "var(--ink-muted)") => {
      const row = document.createElement("div");
      row.className = "row";
      row.style.color = color;
      row.textContent = text;
      list.appendChild(row);
    };
    const isMock = result.mode === "mock_exam";
    const scoreLine = isMock
      ? `score ${summary.score_pct}% (${summary.earned_weight}/${summary.total_weight} weight · ${summary.passed_exam ? "PASS >=66%" : "FAIL <66%"})`
      : `passed ${summary.passed}/${summary.total} · first try ${summary.first_try_passes} · accuracy ${summary.accuracy_pct}%`;
    addRow(scoreLine, isMock ? (summary.passed_exam ? "var(--pass)" : "var(--fail)") : "var(--ink)");
    addRow(`duration ${summary.duration_minutes} min · mode: ${result.variant || result.mode}`);
    for (const [domain, data] of Object.entries(summary.per_domain)) {
      const ew = data.earned_weight !== undefined ? ` · ${data.earned_weight}/${data.weight}w` : "";
      addRow(`${domain}: ${data.passed}/${data.total}${ew}`);
    }
    if (summary.items?.length) {
      const tbl = document.createElement("table");
      tbl.className = "score-table";
      tbl.innerHTML = "<thead><tr><th>Task</th><th>Result</th><th>Credit</th></tr></thead>";
      const tb = document.createElement("tbody");
      for (const it of summary.items) {
        const tr = document.createElement("tr");
        const stColor = it.state === "passed" ? "var(--pass)" : it.pass_ratio > 0 ? "var(--warn)" : "var(--fail)";
        const tdTitle = document.createElement("td");
        tdTitle.textContent = `${it.title}${it.flagged ? " [Flagged]" : ""}`;
        const tdRes = document.createElement("td");
        tdRes.style.color = stColor;
        tdRes.textContent = `${it.state} (${Math.round((it.pass_ratio || 0) * 100)}%)`;
        const tdCred = document.createElement("td");
        tdCred.textContent = `${it.earned_weight}/${it.weight}%`;
        tr.append(tdTitle, tdRes, tdCred);
        tb.appendChild(tr);
      }
      tbl.appendChild(tb);
      list.appendChild(tbl);
    }
    const level = result.cleanup.level || "L1";
    const drift = result.cleanup.drift?.drift;
    addRow(`cleanup ${level}${drift !== undefined ? ` · drift: ${drift}` : ""}`, drift ? "var(--warn)" : "var(--pass)");
    el("end-cleanup-field").style.display = "none";
    el("end-cancel").hidden = true;
    button.hidden = true;
    el("end-close").hidden = false;
    endingSession = null;
    workspace.clear();
    power.refresh();
    studio.refreshCoverage();
    readiness.refresh();
    toast("Session finished and cluster cleaned", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = button.dataset.label || "Finish & clean up";
  }
};
el("end-close").onclick = () => closeDialog(endDialog);

// ------------------------------------------------------------ keyboard
document.addEventListener("keydown", (event) => {
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const inTerm = Boolean(event.target?.closest?.(".xterm, #term-screen"));
  const mod = isMac
    ? (event.metaKey && !event.ctrlKey)
    : (inTerm ? (event.ctrlKey && event.shiftKey) : event.ctrlKey);
  const key = event.key.toLowerCase();

  if (mod && key === "k") {
    event.preventDefault();
    palette.toggle();
  } else if (mod && event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    workspace.check();
  } else if (mod && event.shiftKey && event.key === "Enter") {
    event.preventDefault();
    workspace.next();
  } else if (mod && key === "l") {
    event.preventDefault();
    terminal.clearActive();
  } else if (mod && key === "b") {
    event.preventDefault();
    if (!el("content").hidden) toggleZen();
  } else if (mod && event.key === "\\") {
    event.preventDefault();
    if (!el("content").hidden) toggleNative();
  } else if (mod && key === "f") {
    if (!el("content").hidden) {
      event.preventDefault();
      terminal.openSearch?.();
    }
  } else if (mod && (event.key === "=" || event.key === "+")) {
    event.preventDefault();
    terminal.adjustFont?.(1);
  } else if (mod && event.key === "-") {
    event.preventDefault();
    terminal.adjustFont?.(-1);
  } else if (mod && event.key === "0") {
    event.preventDefault();
    terminal.resetFont?.();
  } else if (mod && event.key === "/") {
    event.preventDefault();
    if (shortcutsDialog.open) closeDialog(shortcutsDialog);
    else openDialog(shortcutsDialog);
  } else if (mod && ["1", "2", "3", "4", "5"].includes(event.key)) {
    event.preventDefault();
    showPanel({ 1: null, 2: "readiness", 3: "studio", 4: "settings", 5: "study" }[event.key]);
  } else if (event.key === "Escape") {
    if (inTerm) {
      if (el("term-search") && !el("term-search").hidden) terminal.closeSearch?.();
      return;
    }
    terminal.closeSearch?.();
    if (document.querySelector("dialog[open]")) return;
    showPanel(null);
  }
});

// ------------------------------------------------------------ boot
(async function boot() {
  try {
    const active = await api("/api/sessions/active");
    if (active.active) workspace.setSession(active.active);
  } catch { /* no session */ }
  await terminal.ensureHost();
  try {
    const coverage = await api("/api/bank/coverage");
    state.bank = coverage.published;
  } catch { /* ignore */ }
  renderBankLine();
  renderQueue();
  syncSessionControls();
})();
