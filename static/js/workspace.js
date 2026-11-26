// workspace.js — mission launcher, Markdown prompt, subtabs, Quick-Run context pills, checks, hints & postmortem
import { api } from "./api.js";
import { el, toast, confirmDialog, copyText, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js";
import { iconEl } from "./icons.js";
import { renderPrompt } from "./markdown.js";

const failCounts = new Map();

function makeCopyPill(text, onAfter) {
  const span = document.createElement("span");
  span.className = "copy-pill";
  span.textContent = text;
  span.title = "Copy to clipboard";
  span.onclick = async () => {
    await copyText(text, span);
    onAfter?.();
  };
  return span;
}

export function initWorkspace({ onSessionChanged, onFinished, onBankInvalidated, focusTerminal, sendCommand, onSubmitExam, onOpenCodex }) {
  let session = null;
  let timerHandle = null;
  let checking = false;
  let notesTimer = null;

  function setSubtab(tabName) {
    const tabs = { task: el("q-tab-task"), notes: el("q-tab-notes"), hints: el("q-tab-hints") };
    const panes = { task: el("q-pane-task"), notes: el("q-pane-notes"), hints: el("q-pane-hints") };
    for (const key of ["task", "notes", "hints"]) {
      tabs[key]?.classList.toggle("on", key === tabName);
      if (panes[key]) panes[key].hidden = key !== tabName;
    }
  }

  el("q-tab-task")?.addEventListener("click", () => setSubtab("task"));
  el("q-tab-notes")?.addEventListener("click", () => setSubtab("notes"));
  el("q-tab-hints")?.addEventListener("click", () => setSubtab("hints"));

  function stripExamHeader(text, title) {
    const lines = String(text).replace(/\r/g, "").split("\n");
    while (lines.length) {
      const line = lines[0].trim();
      if (!line || line === title || /^task weight:/i.test(line) || /^use context:/i.test(line)) {
        lines.shift();
        continue;
      }
      break;
    }
    return lines.join("\n").trimStart();
  }

  function copyAndRunPill(text, allowRun = true) {
    const wrap = document.createElement("span");
    wrap.className = "pill-wrap-run";
    wrap.appendChild(makeCopyPill(text, focusTerminal));
    if (sendCommand && allowRun) {
      const runBtn = document.createElement("button");
      runBtn.type = "button";
      runBtn.className = "pill-run";
      runBtn.title = `Run in active terminal: ${text}`;
      runBtn.append(iconEl("play", 11), document.createTextNode("Run"));
      runBtn.onclick = (e) => {
        e.stopPropagation();
        sendCommand(text);
      };
      wrap.appendChild(runBtn);
    }
    return wrap;
  }

  async function saveItemState(itemId, patch) {
    if (!session?.session?.id || !itemId) return;
    try {
      await api(`/api/sessions/${session.session.id}/items/${itemId}/state`, {
        method: "PUT",
        body: patch,
      });
    } catch { /* non-blocking background persistence */ }
  }

  async function withLoading(label, fn) {
    const loader = el("workspace-loading");
    const loaderText = el("workspace-loading-text");
    if (loaderText) loaderText.textContent = label || "Preparing cluster scenario…";
    if (loader) loader.hidden = false;
    try {
      return await fn();
    } finally {
      if (loader) loader.hidden = true;
    }
  }

  async function launchQuick(variant, count) {
    try {
      await withLoading(`Mounting ${variant.replace("_", " ")} onto cluster…`, async () => {
        const mode = variant === "blind_exam" || variant === "guided_mock" ? "mock_exam" : "study";
        const payload = await api("/api/practice", {
          method: "POST",
          body: { count, mode, variant },
        });
        setSession(payload);
        toast(`${payload.session.title} started`, "success");
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  el("quick-study")?.addEventListener("click", () => launchQuick("study", 5));
  el("quick-blind")?.addEventListener("click", () => launchQuick("blind_exam", 15));
  el("quick-weak")?.addEventListener("click", () => launchQuick("weakness_drill", 5));
  el("quick-speed")?.addEventListener("click", () => launchQuick("speed_blitz", 5));

  function setSession(payload) {
    const prevItem = session?.active?.item_id;
    session = payload;
    if (prevItem !== payload?.active?.item_id) {
      failCounts.clear();
      const hintDrawer = el("hint-drawer");
      if (hintDrawer) {
        hintDrawer.hidden = true;
        hintDrawer.innerHTML = "";
      }
      setSubtab("task");
    }
    render();
    onSessionChanged?.(payload);
  }

  function clear() {
    session = null;
    render();
    onSessionChanged?.(null);
  }

  function resolveSshCommand(envelope) {
    if (envelope.ssh_target) {
      return envelope.ssh_target.startsWith("ssh ")
        ? envelope.ssh_target
        : `ssh cka-${envelope.ssh_target}`;
    }
    const lower = `${envelope.prompt || ""} ${envelope.title || ""}`.toLowerCase();
    for (const node of ["controlplane", "node01", "node02"]) {
      if (lower.includes(node)) return `ssh cka-${node}`;
    }
    return null;
  }

  function extractChecklistSteps(bodyText, envelope) {
    const steps = [];
    for (const raw of String(bodyText || "").split("\n")) {
      const m = raw.match(/^\s*(?:\d+[.)]|[-*])\s+(.+)$/);
      if (m && m[1].trim().length > 4) steps.push(m[1].trim());
      if (steps.length >= 8) break;
    }
    if (steps.length >= 2) return steps;
    return (envelope.check_descriptions || []).map((c) => c.description).filter(Boolean);
  }

  function renderChecklist(active, bodyText) {
    const box = el("q-checklist");
    const badge = el("q-check-badge");
    if (!box) return;
    const steps = extractChecklistSteps(bodyText, active.envelope);
    box.innerHTML = "";
    const checkedSet = new Set(active.checked_tasks || []);
    if (badge) badge.textContent = `${checkedSet.size}/${steps.length}`;
    if (!steps.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    const hdr = document.createElement("div");
    hdr.className = "section-title";
    hdr.textContent = "Task checkpoints";
    box.appendChild(hdr);
    steps.forEach((stepText, idx) => {
      const label = document.createElement("label");
      label.className = "task-step" + (checkedSet.has(idx) ? " done" : "");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = checkedSet.has(idx);
      cb.onchange = () => {
        if (cb.checked) checkedSet.add(idx);
        else checkedSet.delete(idx);
        label.classList.toggle("done", cb.checked);
        active.checked_tasks = [...checkedSet].sort((a, b) => a - b);
        if (badge) badge.textContent = `${checkedSet.size}/${steps.length}`;
        saveItemState(active.item_id, { checked_tasks: active.checked_tasks });
      };
      const span = document.createElement("span");
      span.textContent = stepText;
      label.append(cb, span);
      box.appendChild(label);
    });
  }

  async function loadPostmortem(sessionId, itemId) {
    const drawer = el("postmortem-drawer");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.innerHTML = "";
    try {
      const data = await api(`/api/sessions/${sessionId}/postmortem/${itemId}`);
      if (session?.session?.id !== sessionId || session?.active?.item_id !== itemId) return;
      drawer.hidden = false;
      const card = document.createElement("div");
      card.className = "postmortem-card";
      const h = document.createElement("div");
      h.className = "label";
      h.textContent = "Post-Mortem & Speed Coach";
      card.appendChild(h);

      const coach = data.coach || {};
      const stats = document.createElement("div");
      stats.className = "coach-stats";
      stats.textContent = `time ${coach.solve_seconds ?? "?"}s · pace ${coach.pacing_ratio ?? "?"}x target · commands ${coach.command_count ?? 0}`;
      card.appendChild(stats);

      if (data.fast_solution_commands?.length) {
        const fastLabel = document.createElement("div");
        fastLabel.className = "label";
        fastLabel.style.marginBlockStart = "4px";
        fastLabel.textContent = "Fast imperative workflow";
        card.appendChild(fastLabel);
        const fastRow = document.createElement("div");
        fastRow.className = "pill-row";
        for (const cmd of data.fast_solution_commands) {
          fastRow.appendChild(copyAndRunPill(cmd));
        }
        card.appendChild(fastRow);
      }

      if (coach.tips?.length) {
        const tips = document.createElement("div");
        tips.className = "coach-tips";
        for (const tip of coach.tips) {
          const line = document.createElement("div");
          line.style.display = "flex";
          line.style.alignItems = "center";
          line.style.gap = "6px";
          line.append(iconEl("zap", 13), document.createTextNode(tip));
          tips.appendChild(line);
        }
        card.appendChild(tips);
      }
      drawer.appendChild(card);
    } catch {
      drawer.hidden = true;
    }
  }

  async function refreshEmptyMission() {
    const box = el("empty-daily-mission");
    if (!box) return;
    try {
      const plan = await api("/api/study-plan/today");
      if (!plan) {
        box.hidden = true;
        return;
      }
      box.hidden = false;
      box.innerHTML = "";
      const row = document.createElement("div");
      row.className = "row";
      row.style.display = "flex";
      row.style.justifyContent = "space-between";
      row.style.alignItems = "center";
      row.style.gap = "8px";
      const txt = document.createElement("span");
      txt.textContent = `Today’s Mission: ${plan.headline || `${plan.reviews_due || 0} SRS due`}`;
      const primaryItem = (plan.items || [])[0];
      row.appendChild(txt);
      if (primaryItem) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn sm primary";
        btn.textContent = primaryItem.label || "Start Mission";
        btn.onclick = async () => {
          if (primaryItem.action_type === "launch_variant") {
            launchQuick(primaryItem.variant || "weakness_drill", primaryItem.count || 5);
          } else if (primaryItem.action_type === "codex_topic" && primaryItem.topic_id && onOpenCodex) {
            onOpenCodex(primaryItem.topic_id);
          } else if (primaryItem.archetype_id) {
            try {
              await withLoading(`Mounting ${primaryItem.archetype_id}…`, async () => {
                const payload = await api("/api/practice", {
                  method: "POST",
                  body: { count: 1, mode: "study", archetype_id: primaryItem.archetype_id },
                });
                setSession(payload);
              });
            } catch (err) {
              toast(err.message, "error");
            }
          }
        };
        row.appendChild(btn);
      }
      box.appendChild(row);
    } catch {
      box.hidden = true;
    }
  }

  function render() {
    const empty = el("workspace-empty");
    const body = el("workspace-body");
    const checkBtn = el("btn-check");
    const termCheckBtn = el("btn-term-check");
    const submitExamBtn = el("btn-submit-exam");
    const hintBtn = el("btn-hint");
    const nextBtn = el("btn-next");
    const flagBtn = el("btn-flag");
    const retireBtn = el("btn-retire");
    const drawer = el("check-drawer");
    const hintDrawer = el("hint-drawer");
    const pmDrawer = el("postmortem-drawer");
    const active = session?.active;
    const isMock = session?.session?.mode === "mock_exam";
    const variant = session?.session?.variant || (isMock ? "guided_mock" : "study");
    const isBlindActive = variant === "blind_exam" && session?.session?.status === "active";

    if (!active) {
      empty.hidden = false;
      body.hidden = true;
      refreshEmptyMission();
      checkBtn.hidden = false;
      checkBtn.disabled = true;
      if (termCheckBtn) {
        termCheckBtn.hidden = false;
        termCheckBtn.disabled = true;
      }
      if (submitExamBtn) submitExamBtn.hidden = true;
      if (hintBtn) {
        hintBtn.hidden = false;
        hintBtn.disabled = true;
        hintBtn.textContent = "Hint";
      }
      nextBtn.disabled = true;
      nextBtn.classList.remove("next-ready");
      if (el("btn-prev")) el("btn-prev").hidden = true;
      el("btn-reset").disabled = true;
      el("btn-skip").hidden = false;
      el("btn-skip").disabled = true;
      if (el("q-triage-alert")) el("q-triage-alert").hidden = true;
      flagBtn.hidden = true;
      retireBtn.disabled = true;
      drawer.hidden = true;
      drawer.innerHTML = "";
      if (hintDrawer) {
        hintDrawer.hidden = true;
        hintDrawer.innerHTML = "";
      }
      if (pmDrawer) {
        pmDrawer.hidden = true;
        pmDrawer.innerHTML = "";
      }
      stopTimer();
      return;
    }

    el("btn-reset").disabled = false;
    el("btn-skip").disabled = false;
    retireBtn.disabled = false;
    flagBtn.hidden = !isMock;
    flagBtn.innerHTML = "";
    flagBtn.append(iconEl("flag", 14), document.createTextNode(active.flagged ? "Flagged" : "Flag"));
    flagBtn.classList.toggle("warn-active", Boolean(active.flagged));

    empty.hidden = true;
    body.hidden = false;
    el("q-scroll").scrollTop = 0;
    const envelope = active.envelope;

    el("q-domain").textContent = envelope.domain;
    el("q-weight").textContent = `weight ${envelope.weight}% · ${envelope.difficulty.replace("_", " ")}`;
    el("q-destructive").hidden = !envelope.destructive;
    el("q-title").textContent = envelope.title;

    const context = el("q-context");
    context.innerHTML = "";
    const allowRun = !isBlindActive;
    if (envelope.context_command) context.appendChild(copyAndRunPill(envelope.context_command, allowRun));
    const sshCmd = resolveSshCommand(envelope);
    if (sshCmd) context.appendChild(copyAndRunPill(sshCmd, allowRun));

    const bodyText = stripExamHeader(envelope.prompt, envelope.title);
    renderPrompt(el("q-prompt"), bodyText, { focusAfter: focusTerminal });
    renderChecklist(active, bodyText);

    const notesEl = el("q-notes");
    if (notesEl) {
      notesEl.value = active.notes_text || "";
      notesEl.oninput = () => {
        active.notes_text = notesEl.value;
        clearTimeout(notesTimer);
        notesTimer = setTimeout(() => {
          saveItemState(active.item_id, { notes_text: notesEl.value });
        }, 400);
      };
    }

    const docs = el("q-docs");
    const docsSection = el("q-docs-section");
    docs.innerHTML = "";
    docs.hidden = isBlindActive;
    if (docsSection) docsSection.hidden = isBlindActive;
    if (!isBlindActive) {
      for (const link of envelope.docs_links || []) {
        const anchor = document.createElement("a");
        anchor.href = link.url;
        anchor.target = "_blank";
        anchor.rel = "noreferrer";
        anchor.append(iconEl("externalLink", 13), document.createTextNode(link.label));
        docs.appendChild(anchor);
      }
      if (envelope.codex_topic_id && onOpenCodex) {
        const codexLink = document.createElement("button");
        codexLink.type = "button";
        codexLink.className = "btn sm ghost";
        codexLink.textContent = "Study Concept in Codex →";
        codexLink.onclick = () => onOpenCodex(envelope.codex_topic_id);
        docs.appendChild(codexLink);
      }
    }

    const done = active.item_state !== "active";
    checkBtn.hidden = isBlindActive;
    checkBtn.disabled = done || isBlindActive;
    if (termCheckBtn) {
      termCheckBtn.hidden = isBlindActive;
      termCheckBtn.disabled = done || isBlindActive;
    }
    if (submitExamBtn) submitExamBtn.hidden = !isBlindActive;
    const prevBtn = el("btn-prev");
    if (prevBtn) {
      prevBtn.hidden = !isMock;
      prevBtn.disabled = !isMock || active.order_index <= 0;
    }
    el("btn-skip").hidden = isMock;

    const usedHints = Number(active.hints_used || 0);
    if (el("q-hint-badge")) el("q-hint-badge").textContent = `${usedHints}/3`;
    if (hintBtn) {
      hintBtn.hidden = isBlindActive;
      hintBtn.disabled = done || isBlindActive;
      hintBtn.innerHTML = "";
      hintBtn.append(
        iconEl("lightbulb", 14),
        document.createTextNode(usedHints > 0 ? `Hint (L${usedHints}/3)` : "Hint"),
      );
    }

    const canAdvance = done || isMock;
    nextBtn.disabled = !canAdvance;
    nextBtn.classList.toggle("next-ready", done);
    nextBtn.textContent = "Next →";

    if (active.last_check && !isBlindActive) {
      renderReport(active.last_check);
    } else {
      drawer.hidden = true;
      drawer.innerHTML = "";
    }

    if ((active.item_state === "passed" || active.item_state === "skipped") && !isBlindActive) {
      stopTimer(true);
      drawReference(envelope.reference_solution);
      loadPostmortem(session.session.id, active.item_id);
    } else {
      if (pmDrawer) {
        pmDrawer.hidden = true;
        pmDrawer.innerHTML = "";
      }
      startTimer(active);
    }
  }

  function drawReference(solution) {
    if (!solution) return;
    const drawer = el("check-drawer");
    drawer.hidden = false;
    const details = document.createElement("details");
    details.style.marginBlockStart = "8px";
    const summary = document.createElement("summary");
    summary.textContent = "View reference solution";
    summary.style.cursor = "pointer";
    summary.style.color = "var(--ink-muted)";
    summary.style.fontSize = "var(--text-xs)";
    const pre = document.createElement("pre");
    pre.className = "code-block";
    pre.style.marginBlockStart = "8px";
    pre.style.border = "1px solid var(--line-subtle)";
    pre.style.borderRadius = "var(--r-sm)";
    pre.textContent = solution;
    details.append(summary, pre);
    drawer.appendChild(details);
  }

  // ------------------------------------------------------------ timer
  function stopTimer(freeze = false) {
    clearInterval(timerHandle);
    timerHandle = null;
    if (!freeze) {
      el("q-timer").textContent = "--:--";
      const fill = el("q-progress-fill");
      if (fill) {
        fill.style.setProperty("--p", "0");
        fill.className = "q-progress-fill";
      }
    }
  }

  function startTimer(active) {
    stopTimer(false);
    const total = Math.max(60, (active.envelope.estimated_minutes || 5) * 60);
    const triageEl = el("q-triage-alert");
    if (triageEl) triageEl.hidden = true;
    const isMock = session?.session?.mode === "mock_exam";
    const priorSeconds = Number(active.active_seconds || 0);
    const enteredAt = active.last_entered_at || active.started_at;
    const tick = () => {
      const liveDelta = enteredAt ? Math.max(0, Date.now() / 1000 - enteredAt) : 0;
      const elapsed = priorSeconds + liveDelta;
      const remaining = Math.max(0, total - elapsed);
      const timer = el("q-timer");
      timer.textContent = `${fmt(elapsed)} / ${fmt(total)}`;
      const isWarn = remaining <= 90 && remaining > 60;
      const isBad = remaining <= 60;
      timer.classList.toggle("warn", isWarn);
      timer.classList.toggle("bad", isBad);
      const fill = el("q-progress-fill");
      if (fill) {
        fill.style.setProperty("--p", String(Math.min(1, elapsed / total)));
        fill.className = "q-progress-fill" + (isBad ? " bad" : isWarn ? " warn" : "");
      }
      if (triageEl) {
        triageEl.hidden = !(isMock && elapsed > total * 1.5);
      }
    };
    tick();
    timerHandle = setInterval(tick, 1000);
  }

  function fmt(seconds) {
    const s = Math.floor(seconds);
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  // ------------------------------------------------------------ actions
  async function check() {
    if (!session?.active || session.active.item_state !== "active") return;
    if (checking) return;
    setSubtab("task");
    checking = true;
    const button = el("btn-check");
    const termButton = el("btn-term-check");
    button.disabled = true;
    button.classList.add("loading");
    if (termButton) {
      termButton.disabled = true;
      termButton.classList.add("loading");
    }
    let seconds = 0;
    button.textContent = "Checking… 0s";
    if (termButton) termButton.textContent = "Checking… 0s";
    const tick = setInterval(() => {
      const lbl = `Checking… ${++seconds}s`;
      button.textContent = lbl;
      if (termButton) termButton.textContent = lbl;
    }, 1000);
    try {
      const result = await api(`/api/sessions/${session.session.id}/check`, { method: "POST" });
      setSession(result.session);
      if (!result.session?.active?.last_check && result.report) {
        renderReport(result.report);
      }
      if (result.report.all_passed && !result.report.infra_error) {
        toast("All checks passed — Next unlocked", "success");
      } else if (result.report.infra_error) {
        toast("Infrastructure error during check — inspect Settings telemetry", "error");
      }
    } catch (error) {
      toast(error.message, "error");
    } finally {
      clearInterval(tick);
      checking = false;
      button.classList.remove("loading");
      button.innerHTML = "Check <kbd>⌘↵</kbd>";
      const inactive = session?.active?.item_state !== "active";
      button.disabled = inactive;
      if (termButton) {
        termButton.classList.remove("loading");
        termButton.textContent = "Check";
        termButton.disabled = inactive;
      }
    }
  }

  async function requestHint() {
    if (!session?.active) return;
    const current = Number(session.active.hints_used || 0);
    const nextLevel = Math.min(3, current + 1);
    const btn = el("btn-hint");
    if (btn) btn.disabled = true;
    try {
      const res = await api(`/api/sessions/${session.session.id}/hint`, {
        method: "POST",
        body: { level: nextLevel },
      });
      session.active.hints_used = res.hints_used;
      const drawer = el("hint-drawer");
      if (drawer) {
        drawer.hidden = false;
        const card = document.createElement("div");
        card.className = "hint-card";
        const lbl = document.createElement("div");
        lbl.className = "label";
        lbl.style.marginBlockEnd = "6px";
        lbl.textContent = `Hint Level ${res.level}/3`;
        const txt = document.createElement("div");
        txt.textContent = res.hint;
        card.append(lbl, txt);
        drawer.appendChild(card);
      }
      if (el("q-hint-badge")) el("q-hint-badge").textContent = `${res.hints_used}/3`;
      if (btn) {
        btn.innerHTML = "";
        btn.append(iconEl("lightbulb", 14), document.createTextNode(`Hint (L${res.hints_used}/3)`));
      }
      setSubtab("hints");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      if (btn) btn.disabled = session?.active?.item_state !== "active";
    }
  }

  function renderReport(report) {
    const drawer = el("check-drawer");
    drawer.hidden = false;
    drawer.innerHTML = "";
    const heading = document.createElement("div");
    const passed = report.results.filter((r) => r.status === "PASS").length;
    heading.className = report.all_passed ? "label pass" : "label fail";
    heading.textContent = report.all_passed
      ? `Check Results · All ${report.results.length} Passed`
      : `Check Results · ${passed}/${report.results.length} Passed`;
    drawer.appendChild(heading);

    for (const result of report.results) {
      const count = (failCounts.get(result.check_id) || 0) + (result.status === "FAIL" ? 1 : 0);
      if (result.status === "FAIL") failCounts.set(result.check_id, count);

      const card = document.createElement("div");
      card.className = `check-item ${result.status === "PASS" ? "pass" : "fail"}`;

      const row = document.createElement("div");
      row.className = "check-row";
      const badge = document.createElement("span");
      badge.className = `check-badge ${result.status}`;
      badge.append(iconEl(result.status === "PASS" ? "checkCircle" : "xCircle", 14), document.createTextNode(result.status));
      const desc = document.createElement("span");
      desc.className = "check-desc";
      desc.textContent = result.description;
      row.append(badge, desc);
      card.appendChild(row);

      const evidence = evidenceLine(result);
      if (evidence) {
        const line = document.createElement("div");
        line.className = "check-evidence";
        line.textContent = evidence;
        card.appendChild(line);
      }
      if (result.status === "FAIL" && result.hint && count >= 2) {
        const hint = document.createElement("div");
        hint.className = "check-hint";
        hint.textContent = `Hint: ${result.hint}`;
        card.appendChild(hint);
      }
      drawer.appendChild(card);
    }
  }

  function evidenceLine(result) {
    const evidence = result.evidence || {};
    if (result.status === "PASS") return "";
    if (evidence.actual !== undefined) {
      return `expected ${evidence.expected ?? "?"} · got ${evidence.actual || "(empty)"}`;
    }
    if (evidence.ready_addresses !== undefined) {
      return `ready endpoints ${evidence.ready_addresses}/${evidence.min_ready_addresses ?? "?"}`;
    }
    if (evidence.ready !== undefined) {
      return `ready ${evidence.ready}/${evidence.min_ready ?? evidence.min_ready_replicas ?? "?"}`;
    }
    if (evidence.exit_code !== undefined) {
      return `exit ${evidence.exit_code} · ${(evidence.stdout || evidence.stderr || "").split("\n")[0].slice(0, 120)}`;
    }
    return evidence.reason || evidence.error || "";
  }

  async function next() {
    if (!session) return;
    try {
      await withLoading("Transitioning to next scenario…", async () => {
        const result = await api(`/api/sessions/${session.session.id}/next`, { method: "POST" });
        if (result.finished) {
          onFinished?.(result.session);
        } else {
          setSession(result.session);
          toast("Next scenario mounted");
        }
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function prev() {
    if (!session) return;
    try {
      await withLoading("Loading previous scenario…", async () => {
        const result = await api(`/api/sessions/${session.session.id}/prev`, { method: "POST" });
        if (result.session) setSession(result.session);
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function selectItem(itemId) {
    if (!session) return;
    try {
      await withLoading("Mounting selected task onto cluster…", async () => {
        const updated = await api(`/api/sessions/${session.session.id}/select/${itemId}`, { method: "POST" });
        setSession(updated);
        toast("Question loaded");
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function toggleFlag() {
    if (!session?.active) return;
    try {
      const updated = await api(`/api/sessions/${session.session.id}/flag/${session.active.item_id}`, {
        method: "POST",
      });
      setSession(updated);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function submitRetire(reasonCode, reasonNote) {
    if (!session?.active) return;
    try {
      await withLoading("Retiring question & cleaning cluster…", async () => {
        const updated = await api(`/api/sessions/${session.session.id}/retire`, {
          method: "POST",
          body: { reason_code: reasonCode || "other", reason: reasonNote || reasonCode || "reported by user" },
        });
        setSession(updated);
        onBankInvalidated?.();
        toast("Question retired & feedback recorded", "success");
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function retireActive() {
    if (!session?.active) return;
    const modal = el("report-modal");
    if (!modal) {
      const ok = await confirmDialog(
        "Report & retire this question?",
        "It will be retired from your bank (never drawn again) and skipped in this session.",
      );
      if (ok) await submitRetire("other", "reported by user in workspace");
      return;
    }
    const noteEl = el("report-reason-note");
    if (noteEl) noteEl.value = "";
    openDialog(modal);
  }

  const reportModal = el("report-modal");
  if (reportModal) {
    wireDialogBackdropDismiss(reportModal);
    el("report-cancel")?.addEventListener("click", () => closeDialog(reportModal));
    el("report-submit")?.addEventListener("click", async () => {
      const code = el("report-reason-code")?.value || "other";
      const note = el("report-reason-note")?.value.trim() || code;
      closeDialog(reportModal);
      await submitRetire(code, note);
    });
  }

  async function skip() {
    if (!session) return;
    const ok = await confirmDialog(
      "Skip this question?",
      "It will be marked unsolved and the next scenario will unlock.",
    );
    if (!ok) return;
    try {
      await withLoading("Marking skipped & cleaning scenario…", async () => {
        setSession(await api(`/api/sessions/${session.session.id}/skip`, { method: "POST" }));
        toast("Question skipped");
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function reset() {
    if (!session) return;
    const ok = await confirmDialog(
      "Reset this scenario?",
      "Cluster resources for this question will be cleaned and re-applied.",
    );
    if (!ok) return;
    try {
      await withLoading("Resetting & re-applying scenario…", async () => {
        setSession(await api(`/api/sessions/${session.session.id}/reset`, { method: "POST" }));
        el("check-drawer").hidden = true;
        toast("Scenario reset");
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  el("btn-check").onclick = check;
  el("btn-next").onclick = next;
  el("btn-prev")?.addEventListener("click", prev);
  el("btn-skip").onclick = skip;
  el("btn-reset").onclick = reset;
  el("btn-flag").onclick = toggleFlag;
  el("btn-hint")?.addEventListener("click", requestHint);
  el("btn-submit-exam")?.addEventListener("click", () => { if (session) onSubmitExam?.(session); });
  el("btn-retire").onclick = retireActive;
  render();

  return { setSession, clear, check, next, selectItem, launchQuick, get session() { return session; } };
}
