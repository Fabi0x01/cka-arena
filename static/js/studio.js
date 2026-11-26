// studio.js — Scenario Studio, CI/CD Stepper, Clickable Heatmap 5x3, Bank Inspector & Practice <dialog>
import { api } from "./api.js";
import { el, toast, confirmDialog, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js";

const DOMAINS = [
  "Troubleshooting",
  "Cluster Architecture, Installation & Configuration",
  "Services & Networking",
  "Workloads & Scheduling",
  "Storage",
];
const DIFF_LABEL = { exam_standard: "Exam Standard", killer_hardcore: "Killer.sh Hardcore", boss_fight: "Boss Fight" };
const DIFFS = ["exam_standard", "killer_hardcore", "boss_fight"];
const STAGES = [
  { id: "A", label: "Plan" },
  { id: "B", label: "Build" },
  { id: "D", label: "Gates" },
  { id: "C", label: "Review" },
  { id: "E", label: "Probe" },
];

function domainChoices(container, { checkedAll = true } = {}) {
  container.innerHTML = "";
  for (const domain of DOMAINS) {
    const label = document.createElement("label");
    label.className = "choice";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = domain;
    input.checked = checkedAll;
    label.appendChild(input);
    label.appendChild(document.createTextNode(
      domain.replace("Cluster Architecture, Installation & Configuration", "Cluster Architecture")));
    container.appendChild(label);
  }
}

function selectedDomains(container) {
  return [...container.querySelectorAll("input:checked")].map((input) => input.value);
}

function countChoices(container, options, selected) {
  container.innerHTML = "";
  for (const value of options) {
    const label = document.createElement("label");
    label.className = "choice";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = container.id;
    input.value = String(value);
    input.checked = value === selected;
    label.appendChild(input);
    label.appendChild(document.createTextNode(String(value)));
    container.appendChild(label);
  }
}

function selectedCount(container) {
  return Number(container.querySelector("input:checked")?.value || 0);
}

function fmt(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function blankJob(id, total) {
  return {
    id,
    total: total || 1,
    status: "running",
    startedAt: Date.now(),
    finishedAt: null,
    duration: null,
    serverElapsed: null,
    serverElapsedAt: null,
    current: { stage: "queued", detail: "job accepted", scenario: null },
    scenarios: {},
    published: [],
    publishedCount: 0,
    quarantined: 0,
    attempted: 0,
    error: null,
  };
}

function snapshotToJob(snap) {
  return {
    id: snap.id,
    total: snap.total || 1,
    status: snap.status || "running",
    startedAt: snap.started_at ? snap.started_at * 1000 : Date.now(),
    finishedAt: snap.finished_at ? snap.finished_at * 1000 : null,
    duration: snap.duration_s,
    serverElapsed: null,
    serverElapsedAt: null,
    current: snap.current || { stage: "queued", detail: "", scenario: null },
    scenarios: snap.scenarios || {},
    published: snap.published || [],
    publishedCount: (snap.published || []).length,
    quarantined: snap.quarantined || 0,
    attempted: snap.attempted || 0,
    error: snap.error || null,
  };
}

export function initStudio({ bus, onSessionStarted, onBankChanged, openWorkspace, getActiveSession, onEndActiveSession }) {
  let job = null;
  let tickTimer = null;
  let logEntries = [];
  let previewed = null;

  function setStudioTab(name) {
    el("studio-tab-pipeline")?.classList.toggle("on", name === "pipeline");
    el("studio-tab-bank")?.classList.toggle("on", name === "bank");
    if (el("studio-pane-pipeline")) el("studio-pane-pipeline").hidden = name !== "pipeline";
    if (el("studio-pane-bank")) el("studio-pane-bank").hidden = name !== "bank";
  }

  el("studio-tab-pipeline")?.addEventListener("click", () => setStudioTab("pipeline"));
  el("studio-tab-bank")?.addEventListener("click", () => setStudioTab("bank"));

  function mergeSnapshot(snap) {
    const incoming = snapshotToJob(snap);
    job = {
      ...incoming,
      startedAt: job?.startedAt || incoming.startedAt,
      published: job?.published?.length ? job.published : incoming.published,
      publishedCount: Math.max(job?.publishedCount || 0, incoming.publishedCount),
    };
  }

  function appendLog(entry) {
    logEntries.push({ at: new Date(), ...entry });
    if (logEntries.length > 80) logEntries = logEntries.slice(-80);
  }

  function elapsedSeconds() {
    if (!job) return 0;
    if (job.status !== "running" && job.duration != null) return job.duration;
    if (job.serverElapsed != null && job.serverElapsedAt) {
      return job.serverElapsed + (Date.now() - job.serverElapsedAt) / 1000;
    }
    const end = job.finishedAt || Date.now();
    return Math.max(0, (end - job.startedAt) / 1000);
  }

  function quarantinedCount() {
    const rows = Object.values(job?.scenarios || {}).filter((row) => row.status === "quarantined").length;
    return Math.max(rows, job?.quarantined || 0);
  }

  function publishedCount() {
    return Math.max(job?.published?.length || 0, job?.publishedCount || 0);
  }

  function renderStepper() {
    const stepper = el("gen-stepper");
    if (!stepper || !job) return;
    stepper.innerHTML = "";
    const curStage = job.current?.stage || "A";
    const curIdx = STAGES.findIndex((s) => s.id === curStage);
    for (let i = 0; i < STAGES.length; i += 1) {
      const s = STAGES[i];
      const div = document.createElement("div");
      let cls = "stage-step";
      if (job.status === "done") cls += " done";
      else if (job.status === "error" && i === curIdx) cls += " fail";
      else if (i < curIdx || curStage === "publish") cls += " done";
      else if (i === curIdx) cls += " active";
      div.className = cls;
      div.textContent = `${s.id} · ${s.label}`;
      stepper.appendChild(div);
    }
  }

  function miniStages(row) {
    if (!row) return STAGES.map((s) => `<span class="mini">${s.id}</span>`).join("");
    if (row.status === "published") return STAGES.map((s) => `<span class="mini ok">${s.id}</span>`).join("");
    const index = STAGES.findIndex((s) => s.id === row.stage);
    return STAGES.map((s, position) => {
      if (position < index) return `<span class="mini ok">${s.id}</span>`;
      if (position === index) return `<span class="mini ${row.status === "quarantined" ? "fail" : "active"}">${s.id}</span>`;
      return `<span class="mini">${s.id}</span>`;
    }).join("");
  }

  function renderHeader() {
    if (!job) return;
    el("gen-idle").hidden = true;
    el("gen-card").hidden = false;
    const status = el("gen-status");
    status.className = `gen-status ${job.status === "error" ? "error" : job.status}`;
    status.textContent = job.status === "running" ? "running" : job.status === "done" ? "done" : "failed";
    el("btn-gen-cancel").hidden = job.status !== "running";
    const scenario = job.current?.scenario;
    const stage = job.current?.stage || "—";
    const detail = (job.current?.detail || "").slice(0, 72);
    el("gen-meta").textContent =
      `${scenario ? `Q${scenario}/${job.total}` : `job ${job.id.slice(0, 6)}`} · stage ${stage} · ${fmt(elapsedSeconds())}`
      + (detail ? ` — ${detail}` : "");
    el("gen-counts").textContent = `${publishedCount()} published · ${quarantinedCount()} quarantined · ${job.attempted}/${job.total}`;
    const done = publishedCount() + quarantinedCount();
    const fill = el("gen-bar-fill");
    fill.style.setProperty("--p", String(Math.min(1, done / Math.max(1, job.total))));
    fill.className = `gen-bar-fill ${job.status === "done" ? "done" : job.status === "error" ? "error" : ""}`;
    renderStepper();
  }

  function renderScenarios() {
    const container = el("gen-scenarios");
    container.innerHTML = "";
    if (!job) return;
    for (let index = 1; index <= job.total; index += 1) {
      const row = job.scenarios[String(index)];
      const status = row?.status || "pending";
      const active = job.status === "running" && job.current?.scenario === index;
      const div = document.createElement("div");
      div.className = "gen-row" + (active ? " active" : "") + (status === "quarantined" ? " failed" : "");
      const id = document.createElement("div");
      id.className = "gen-row-id";
      id.textContent = `Q${index}`;
      const stages = document.createElement("div");
      stages.innerHTML = miniStages(row);
      const chip = document.createElement("div");
      chip.className = `gen-row-status ${status}`;
      chip.textContent = status === "pending" ? "waiting" : status;
      const detail = document.createElement("div");
      detail.className = "gen-row-detail";
      const tries = row?.attempts > 1 ? ` · try ${row.attempts}` : "";
      detail.textContent = row ? `${row.detail || ""}${tries}` : active ? "starting…" : "waiting for a slot";
      div.append(id, stages, chip, detail);
      container.appendChild(div);
    }
  }

  function renderLog() {
    const container = el("gen-log");
    container.innerHTML = "";
    for (const entry of logEntries.slice(-40)) {
      const row = document.createElement("div");
      row.className = "row" + (entry.stage === "error" || entry.stage === "X" ? " error" : "")
        + (entry.stage === "done" || entry.stage === "publish" ? " done" : "");
      const time = entry.at.toLocaleTimeString([], { hour12: false });
      const prefix = entry.scenario ? `Q${entry.scenario} ` : "";
      row.textContent = `[${time}] ${prefix}[${entry.stage}] ${entry.detail}`;
      container.appendChild(row);
    }
    container.scrollTop = container.scrollHeight;
  }

  function renderJob() {
    if (!job) {
      el("gen-idle").hidden = false;
      el("gen-card").hidden = true;
      return;
    }
    renderHeader();
    renderScenarios();
    renderLog();
    if (job.status === "running") ensureTick(); else stopTick();
  }

  function ensureTick() {
    if (tickTimer) return;
    tickTimer = setInterval(() => { if (job && job.status === "running") renderHeader(); }, 1000);
  }

  function stopTick() {
    clearInterval(tickTimer);
    tickTimer = null;
  }

  function adoptSnapshot(snapshot, { force = false } = {}) {
    if (!snapshot) return false;
    if (job && job.id === snapshot.id && !force) mergeSnapshot(snapshot);
    else if (job && job.id !== snapshot.id && job.status === "running") return false;
    else {
      const recent = snapshot.finished_at ? Date.now() / 1000 - snapshot.finished_at < 3600 : true;
      if (snapshot.status !== "running" && !recent) return false;
      job = snapshotToJob(snapshot);
      logEntries = [];
    }
    renderJob();
    return true;
  }

  // ------------------------------------------------------------ SSE handlers
  bus.on("generation.progress", (event) => {
    if (!job || event.job_id !== job.id) {
      if (!job && event.job_id) job = blankJob(event.job_id, event.total || 1);
      else return;
    }
    if (job.status !== "running" && event.stage !== "done") return;
    job.current = { stage: event.stage, detail: event.detail, scenario: event.scenario };
    if (event.total) job.total = event.total;
    if (event.scenario) {
      const key = String(event.scenario);
      const row = job.scenarios[key] || { index: event.scenario, status: "running", attempts: 0 };
      row.stage = event.stage;
      row.detail = event.detail;
      if (event.status) row.status = event.status;
      if (event.question_id) row.question_id = event.question_id;
      const attemptMatch = /builder attempt (\d+)\//.exec(event.detail || "");
      if (attemptMatch) row.attempts = Number(attemptMatch[1]);
      job.scenarios[key] = row;
    }
    if (event.stage === "publish" && event.question_id && !job.published.includes(event.question_id)) {
      job.published.push(event.question_id);
      job.publishedCount = Math.max(job.publishedCount, job.published.length);
    }
    if (event.stage === "done") {
      job.status = "done";
      job.finishedAt = Date.now();
    }
    appendLog({ stage: event.stage, detail: event.detail, scenario: event.scenario });
    renderJob();
  });

  bus.on("generation.heartbeat", (event) => {
    if (!job || event.job_id !== job.id) return;
    job.serverElapsed = event.elapsed_s;
    job.serverElapsedAt = Date.now();
    job.scenarios = event.scenarios || job.scenarios;
    job.attempted = event.attempted ?? job.attempted;
    job.publishedCount = Math.max(job.publishedCount, event.published || 0);
    job.quarantined = Math.max(job.quarantined, event.quarantined || 0);
    if (event.current) job.current = event.current;
    renderJob();
  });

  bus.on("generation.snapshot", (event) => {
    if (!event.job) return;
    if (adoptSnapshot(event.job) && job?.status === "running") {
      appendLog({ stage: "sync", detail: "attached to running job" });
      renderJob();
    }
  });

  bus.on("generation.done", (event) => {
    if (!job || event.job_id !== job.id) return;
    if (event.job) mergeSnapshot(event.job);
    job.status = event.ok ? "done" : "error";
    job.finishedAt = Date.now();
    job.duration = event.duration_s ?? job.duration;
    job.error = event.error || job.error;
    if (event.published) {
      job.published = event.published;
      job.publishedCount = event.published.length;
    }
    job.quarantined = event.quarantined ?? job.quarantined;
    appendLog({
      stage: event.ok ? "done" : "error",
      detail: event.ok ? `published ${event.published?.length || 0} · ${event.duration_s}s` : event.error,
    });
    renderJob();
    toast(
      event.ok
        ? `Generation finished: ${event.published?.length || 0} published in ${event.duration_s}s`
        : `Generation failed: ${event.error}`,
      event.ok ? "success" : "error",
      6000,
    );
    refreshCoverage();
  });

  // ------------------------------------------------------------ generate + cancel
  el("btn-generate").onclick = async () => {
    if (job && job.status === "running") {
      toast("A generation job is already running", "error");
      return;
    }
    const llm = await api("/api/llm/config").catch(() => null);
    if (llm && !llm.has_key) {
      toast("No AI provider configured — add a key in Settings", "error", 5000);
      document.dispatchEvent(new CustomEvent("open-settings"));
      return;
    }
    const domains = selectedDomains(el("gen-domains"));
    if (!domains.length) return toast("Pick at least one domain", "error");
    const count = selectedCount(el("gen-count"));
    const button = el("btn-generate");
    button.disabled = true;
    button.classList.add("loading");
    try {
      const response = await api("/api/generate", {
        method: "POST",
        body: {
          domains,
          difficulty: el("gen-difficulty").value,
          count,
          focus_hint: el("gen-focus").value.trim() || null,
        },
      });
      if (!job || job.id !== response.job_id) job = blankJob(response.job_id, count);
      job.total = count;
      logEntries = [];
      appendLog({ stage: "A", detail: `job accepted · ${count} scenario(s)` });
      renderJob();
      setStudioTab("pipeline");
      toast("Generation job started");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
      button.classList.remove("loading");
    }
  };

  el("btn-gen-cancel").onclick = async () => {
    const ok = await confirmDialog("Cancel generation?", "The active job will abort and clean up probe namespaces.");
    if (!ok) return;
    try {
      await api("/api/generate/cancel", { method: "POST" });
      toast("Cancelling generation job…");
    } catch (error) {
      toast(error.message, "error");
    }
  };

  async function recoverJob() {
    try {
      const { job: snapshot } = await api("/api/generate/status");
      if (snapshot) adoptSnapshot(snapshot);
    } catch { /* no job */ }
  }

  // ------------------------------------------------------------ coverage, telemetry & bank inspector
  function targetBuilderCell(domain, difficulty) {
    el("gen-domains").querySelectorAll("input").forEach((inp) => {
      inp.checked = inp.value === domain;
    });
    el("gen-difficulty").value = difficulty;
    toast(`Selected ${domain.split(",")[0]} · ${difficulty.replace("_", " ")}`, "info", 2000);
    el("btn-generate")?.focus();
  }

  async function refreshCoverage() {
    try {
      const data = await api("/api/bank/coverage");
      const grid = el("coverage-grid");
      grid.innerHTML = "";
      const header = document.createElement("div");
      header.className = "hdr";
      header.textContent = "Domain";
      grid.appendChild(header);
      for (const difficulty of DIFFS) {
        const cell = document.createElement("div");
        cell.className = "hdr";
        cell.textContent = DIFF_LABEL[difficulty].split(" ")[0];
        grid.appendChild(cell);
      }
      const counts = new Map(data.cells.map((cell) => [`${cell.domain}|${cell.difficulty}`, cell.published]));
      for (const domain of DOMAINS) {
        const name = document.createElement("div");
        name.style.fontSize = "var(--text-xs)";
        name.style.color = "var(--ink-muted)";
        name.textContent = domain.replace("Cluster Architecture, Installation & Configuration", "Cluster Architecture");
        grid.appendChild(name);
        for (const difficulty of DIFFS) {
          const value = counts.get(`${domain}|${difficulty}`) || 0;
          const cell = document.createElement("button");
          cell.type = "button";
          cell.className = "cell " + (value === 0 ? "empty" : value >= 3 ? "ok" : "");
          cell.textContent = String(value);
          cell.title = `Target ${domain} (${difficulty}) in Builder`;
          cell.onclick = () => targetBuilderCell(domain, difficulty);
          grid.appendChild(cell);
        }
      }
      el("coverage-note").textContent = `${data.published} published scenarios. Click any cell to pre-select domain & tier.`;
      onBankChanged?.(data.published);
    } catch (error) {
      toast(error.message, "error");
    }
    await Promise.all([refreshPerformance(), refreshBankList()]);
  }

  async function refreshPerformance() {
    const body = el("perf-body");
    try {
      const data = await api("/api/telemetry");
      body.innerHTML = "";
      const add = (text, color = "var(--ink-muted)") => {
        const row = document.createElement("div");
        row.className = "row";
        row.style.color = color;
        row.textContent = text;
        body.appendChild(row);
      };
      if (!data.per_domain || Object.keys(data.per_domain).length === 0) {
        add("No sessions yet — practice to build history.");
      } else {
        for (const [domain, stats] of Object.entries(data.per_domain)) {
          add(
            `${domain.replace("Cluster Architecture, Installation & Configuration", "Cluster Arch")} — `
            + `${stats.passed}/${stats.total} passed · first-try ${stats.first_try_pct ?? 0}% · avg ${stats.avg_minutes ?? "-"} min`,
            (stats.accuracy_pct ?? 0) >= 80 ? "var(--pass)" : "var(--warn)",
          );
        }
      }
      if (data.pipeline) {
        const p = data.pipeline;
        const avgS = p.avg_llm_ms != null ? `${(p.avg_llm_ms / 1000).toFixed(1)}s` : "—";
        el("perf-note").textContent = p.attempted
          ? `Pipeline telemetry: ${p.published}/${p.attempted} published (${p.publish_rate_pct ?? 0}%) · avg LLM ${avgS}.`
          : "No AI generations recorded yet.";
      }
    } catch {
      body.innerHTML = '<div class="row">Telemetry unavailable.</div>';
    }
  }

  function updateDraftBadge(count) {
    const badge = el("studio-badge-draft");
    if (!badge) return;
    const n = Number(count || 0);
    badge.textContent = String(n);
    badge.hidden = n === 0;
    badge.classList.toggle("warn", n > 0);
  }

  async function refreshBankList() {
    const list = el("bank-list");
    if (!list) return;
    const state = document.querySelector('input[name="bank-state"]:checked')?.value || "published";
    const query = el("bank-search")?.value.trim() || "";
    try {
      const qs = new URLSearchParams({ state, limit: "200" });
      if (query) qs.set("q", query);
      const data = await api(`/api/bank/questions?${qs}`);
      el("cnt-published").textContent = String(data.counts?.published ?? 0);
      el("cnt-draft").textContent = String(data.counts?.draft ?? 0);
      el("cnt-retired").textContent = String(data.counts?.retired ?? 0);
      updateDraftBadge(data.counts?.draft ?? 0);
      list.innerHTML = "";
      if (!data.items.length) {
        list.innerHTML = `<div class="row" style="color:var(--ink-muted)">No ${state} questions found.</div>`;
        return;
      }
      for (const item of data.items) {
        const card = document.createElement("div");
        card.className = "bank-item";
        const head = document.createElement("div");
        head.className = "bank-item-head";
        const title = document.createElement("span");
        title.className = "bank-item-title";
        title.textContent = item.title || "(untitled)";
        const meta = document.createElement("span");
        meta.className = "bank-item-meta";
        const dom = item.domain.replace("Cluster Architecture, Installation & Configuration", "Cluster Arch");
        const qBadge = item.quality_score != null ? ` · Q:${item.quality_score}` : "";
        meta.textContent = `${dom} · ${item.difficulty} · ${item.source}${qBadge} · used ${item.times_used}x`;
        head.append(title, meta);
        card.appendChild(head);

        if (item.probe_error) {
          const err = document.createElement("div");
          err.className = "bank-item-err";
          err.textContent = item.probe_error;
          card.appendChild(err);
        } else if (item.retired_reason) {
          const reason = document.createElement("div");
          reason.className = "bank-item-meta";
          reason.textContent = `retired: ${item.retired_reason}`;
          card.appendChild(reason);
        }

        const actions = document.createElement("div");
        actions.className = "bank-item-actions";
        const addBtn = (label, cls, fn) => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = `btn sm ${cls}`;
          b.textContent = label;
          b.onclick = async () => {
            b.disabled = true;
            try { await fn(); } finally { b.disabled = false; }
          };
          actions.appendChild(b);
        };
        if (state === "draft") {
          addBtn("Re-probe", "", async () => {
            const res = await api(`/api/bank/questions/${item.id}/reprobe`, { method: "POST" });
            toast(res.ok ? "Published!" : `Still failing: ${res.error?.slice(0, 80)}`, res.ok ? "success" : "error");
            await refreshCoverage();
          });
          addBtn("AI Repair", "primary", async () => {
            const res = await api(`/api/bank/questions/${item.id}/repair`, { method: "POST" });
            toast(res.ok ? "Repaired & published!" : `Repair failed: ${res.error?.slice(0, 80)}`, res.ok ? "success" : "error");
            await refreshCoverage();
          });
        } else if (state === "published" && item.source === "llm") {
          addBtn("AI Polish", "", async () => {
            const res = await api(`/api/bank/questions/${item.id}/polish`, { method: "POST" });
            toast(
              res.ok ? `Polished to v1.2 (Q:${res.quality_score ?? "?"})` : `Polish skipped: ${res.error?.slice(0, 80)}`,
              res.ok ? "success" : "error",
            );
            await refreshCoverage();
          });
        }
        if (state !== "retired") {
          addBtn("Retire", "ghost", async () => {
            await api(`/api/bank/questions/${item.id}/retire`, {
              method: "POST",
              body: { reason: "retired from studio inspector" },
            });
            toast("Question retired");
            await refreshCoverage();
          });
        }
        addBtn("Delete", "danger", async () => {
          try {
            await api(`/api/bank/questions/${item.id}`, { method: "DELETE" });
            toast("Deleted");
            await refreshCoverage();
          } catch (error) {
            toast(error.message, "error");
          }
        });
        card.appendChild(actions);
        list.appendChild(card);
      }
    } catch (error) {
      list.innerHTML = `<div class="row error">${error.message}</div>`;
    }
  }

  el("btn-bank-refresh").onclick = refreshBankList;
  el("bank-search").oninput = () => {
    clearTimeout(refreshBankList._t);
    refreshBankList._t = setTimeout(refreshBankList, 200);
  };
  el("bank-state-filter").querySelectorAll("input").forEach((inp) => {
    inp.onchange = refreshBankList;
  });

  // ------------------------------------------------------------ practice <dialog>
  countChoices(el("practice-count"), [3, 5, 15], 5);
  domainChoices(el("practice-domains"));
  const practiceDialog = el("practice-modal");
  wireDialogBackdropDismiss(practiceDialog, closePractice);
  let previewSeq = 0;
  let previewDebounce = null;

  function schedulePracticePreview() {
    previewed = null;
    clearTimeout(previewDebounce);
    previewDebounce = setTimeout(runPracticePreview, 120);
  }

  practiceDialog?.querySelectorAll('input[name="practice-mode"], #practice-difficulty, #practice-allow-destructive')
    .forEach((ctrl) => ctrl.addEventListener("change", () => {
      const modeVal = document.querySelector('input[name="practice-mode"]:checked')?.value;
      const psiBox = el("practice-strict-psi");
      if (psiBox && ctrl.name === "practice-mode") {
        psiBox.checked = modeVal === "blind_exam";
      }
      schedulePracticePreview();
    }));
  el("practice-count")?.addEventListener("change", schedulePracticePreview);
  el("practice-domains")?.addEventListener("change", schedulePracticePreview);

  function openPractice() {
    previewed = null;
    el("practice-start").disabled = true;
    el("practice-preview").innerHTML = '<div class="row">Loading live bank allocation…</div>';
    openDialog(practiceDialog);
    void runPracticePreview();
  }

  function closePractice() {
    closeDialog(practiceDialog);
  }

  el("btn-practice").onclick = openPractice;
  el("empty-practice").onclick = openPractice;
  el("practice-cancel").onclick = closePractice;

  el("btn-fill-gaps")?.addEventListener("click", async () => {
    if (job && job.status === "running") {
      toast("A generation job is already running", "error");
      return;
    }
    const llm = await api("/api/llm/config").catch(() => null);
    if (llm && !llm.has_key) {
      toast("No AI provider configured — add a key in Settings", "error", 5000);
      document.dispatchEvent(new CustomEvent("open-settings"));
      return;
    }
    const btn = el("btn-fill-gaps");
    btn.disabled = true;
    btn.classList.add("loading");
    try {
      const res = await api("/api/generate/fill-gaps?max_count=5", { method: "POST" });
      if (res.status === "complete" || !res.job_id) {
        toast("All coverage cells already meet target threshold!", "success");
        return;
      }
      job = blankJob(res.job_id, res.count || 5);
      logEntries = [];
      appendLog({ stage: "A", detail: `fill-gaps started · ${res.count} cell(s)` });
      renderJob();
      setStudioTab("pipeline");
      toast(`Filling ${res.count} weak/empty cell(s)…`, "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      btn.disabled = false;
      btn.classList.remove("loading");
    }
  });

  el("btn-fill-archetypes")?.addEventListener("click", async () => {
    if (job && job.status === "running") {
      toast("A generation job is already running", "error");
      return;
    }
    const llm = await api("/api/llm/config").catch(() => null);
    if (llm && !llm.has_key) {
      toast("No AI provider configured — add a key in Settings", "error", 5000);
      document.dispatchEvent(new CustomEvent("open-settings"));
      return;
    }
    const btn = el("btn-fill-archetypes");
    btn.disabled = true;
    btn.classList.add("loading");
    try {
      const res = await api("/api/generate/fill-archetypes?max_count=8", { method: "POST" });
      if (!res.job_id) {
        toast("All eligible archetypes already have published questions!", "success");
        return;
      }
      job = blankJob(res.job_id, res.count || 5);
      logEntries = [];
      appendLog({ stage: "A", detail: `fill-archetypes started · ${res.count} archetype(s)` });
      renderJob();
      setStudioTab("pipeline");
      toast(`Generating scenarios for ${res.count} uncovered archetype(s)…`, "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      btn.disabled = false;
      btn.classList.remove("loading");
    }
  });

  el("btn-audit-bank")?.addEventListener("click", async () => {
    const btn = el("btn-audit-bank");
    btn.disabled = true;
    try {
      const preview = await api("/api/bank/audit", { method: "POST", body: { apply: false } });
      if (!preview.retired_count) {
        toast(`Bank audit clean — 0 retired across ${preview.scanned_total ?? preview.legacy_total} LLM question(s) (${preview.v11_flagged ?? 0} eligible for AI Polish)`, "success");
        return;
      }
      const ok = await confirmDialog(
        `Retire ${preview.retired_count} flawed LLM question(s)?`,
        `Scanned ${preview.scanned_total ?? preview.legacy_total} LLM scenarios: ${preview.spoilers_flagged} spoilers, ${preview.weak_boss_flagged ?? 0} weak boss fights, ${preview.cluster_leak_flagged ?? 0} cluster leaks, ${preview.no_docs_flagged} missing docs.`,
      );
      if (!ok) return;
      const applied = await api("/api/bank/audit", { method: "POST", body: { apply: true } });
      toast(`Retired ${applied.retired_count} legacy question(s)`, "success");
      await refreshCoverage();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      btn.disabled = false;
    }
  });

  async function runPracticePreview() {
    const seq = ++previewSeq;
    const count = selectedCount(el("practice-count"));
    const domains = selectedDomains(el("practice-domains"));
    const difficulty = el("practice-difficulty").value || null;
    const variant = document.querySelector('input[name="practice-mode"]:checked')?.value || "study";
    const mode = variant === "blind_exam" || variant === "guided_mock" ? "mock_exam" : "study";
    try {
      const allowDestr = Boolean(el("practice-allow-destructive")?.checked);
      const query = new URLSearchParams({
        count: String(count),
        mode,
        variant,
        allow_destructive: String(allowDestr),
      });
      if (domains.length && domains.length < DOMAINS.length) query.set("domains", domains.join(","));
      if (difficulty) query.set("difficulty", difficulty);
      const data = await api(`/api/bank/preview?${query}`);
      if (seq !== previewSeq) return;
      previewed = { count, domains, difficulty, mode, variant, returned: data.returned };
      const list = el("practice-preview");
      list.innerHTML = "";
      const allocation = document.createElement("div");
      allocation.className = "row";
      allocation.textContent = `Allocation (${variant.replace("_", " ")}): ${Object.entries(data.allocation)
        .filter(([, value]) => value > 0)
        .map(([domain, value]) => `${value}x ${domain.replace("Cluster Architecture, Installation & Configuration", "Cluster Arch")}`)
        .join(" · ")}`;
      list.appendChild(allocation);
      const items = document.createElement("div");
      items.className = "row";
      items.style.color = "var(--ink-muted)";
      items.style.whiteSpace = "pre-wrap";
      items.textContent = data.items.map((item) => `- ${item.title || "(untitled)"} (${item.domain.split(",")[0]} · ${item.difficulty} · ${item.weight || "?"}%)`).join("\n");
      list.appendChild(items);
      if (data.fallbacks.length) {
        const warning = document.createElement("div");
        warning.className = "row error";
        const missing = data.fallbacks.reduce((total, fallback) => total + fallback.missing, 0);
        warning.textContent = `${missing} slot(s) filled by fallback — generate more in Studio.`;
        list.appendChild(warning);
      }
      if (data.returned < count) {
        const short = document.createElement("div");
        short.className = "row error";
        short.textContent = `Only ${data.returned} of ${count} available in the bank.`;
        list.appendChild(short);
      }
      const hasActive = getActiveSession?.()?.session?.status === "active";
      if (hasActive) {
        const activeWarn = document.createElement("div");
        activeWarn.className = "row error";
        activeWarn.style.display = "flex";
        activeWarn.style.alignItems = "center";
        activeWarn.style.justifyContent = "space-between";
        activeWarn.style.gap = "10px";
        const msg = document.createElement("span");
        msg.textContent = "Active session running — end it before starting a new session.";
        const endBtn = document.createElement("button");
        endBtn.type = "button";
        endBtn.className = "btn sm danger";
        endBtn.textContent = "End Active Session";
        endBtn.onclick = () => {
          closePractice();
          onEndActiveSession?.();
        };
        activeWarn.append(msg, endBtn);
        list.prepend(activeWarn);
      }
      el("practice-start").disabled = hasActive || data.returned === 0;
    } catch (error) {
      if (seq === previewSeq) toast(error.message, "error");
    }
  }

  el("practice-preview-btn").onclick = runPracticePreview;

  el("practice-start").onclick = async () => {
    if (!previewed) return;
    const button = el("practice-start");
    button.disabled = true;
    button.classList.add("loading");
    try {
      const session = await api("/api/practice", {
        method: "POST",
        body: {
          count: previewed.count,
          domains: previewed.domains.length === DOMAINS.length ? null : previewed.domains,
          difficulty: previewed.difficulty,
          mode: previewed.mode,
          variant: previewed.variant,
          allow_destructive: Boolean(el("practice-allow-destructive")?.checked),
          strict_psi: Boolean(el("practice-strict-psi")?.checked),
        },
      });
      closePractice();
      onSessionStarted?.(session);
      openWorkspace?.();
      toast("Session started — first scenario mounted");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.classList.remove("loading");
      button.disabled = false;
    }
  };

  domainChoices(el("gen-domains"));
  countChoices(el("gen-count"), [1, 3, 5], 3);
  refreshCoverage();
  recoverJob();
  return { refreshCoverage, openPractice, recoverJob };
}
