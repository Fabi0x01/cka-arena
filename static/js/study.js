// study.js — CKA Study Codex v2 (36 Deep Topics, 59 Archetypes, Matrices, Playbooks, 3-Q Gauntlets & Speed Recall)
import { api } from "./api.js";
import { el, toast, confirmDialog, copyText, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js";
import { iconEl } from "./icons.js?v=3.4";

const DOMAIN_SHORT = {
  "Troubleshooting": "Troubleshooting",
  "Cluster Architecture, Installation & Configuration": "Cluster Arch",
  "Services & Networking": "Services & Net",
  "Workloads & Scheduling": "Workloads",
  "Storage": "Storage",
};

const STAGE_LIST = [
  { id: "theory", label: "1 Concept & Theory", xp: 25 },
  { id: "practice", label: "2 Hands-On Practice", xp: 35 },
  { id: "cheatsheet", label: "3 Cheat Sheet", xp: 20 },
  { id: "quiz", label: "4 Boss Gauntlet", xp: 40 },
];

export function initStudy({
  onSessionStarted,
  openWorkspace,
  openStudio,
  getActiveSession,
  onEndActiveSession,
  runInTerminal,
}) {
  let overview = null;
  let activeTopicId = null;
  let activeTopic = null;
  let activeStage = "theory";
  let activeQuizIdx = 0;
  let filterDomain = "all";
  let sprintTimer = null;
  let sprintSecLeft = 0;
  let selectedChoice = null;
  let lastQuizResult = null;
  let drillState = null;

  const drillDialog = el("study-drill-modal");
  if (drillDialog) {
    wireDialogBackdropDismiss(drillDialog, () => closeDialog(drillDialog));
    el("study-drill-close")?.addEventListener("click", () => closeDialog(drillDialog));
  }

  function buildTable(headers, rows, { copyableCols = true } = {}) {
    const wrap = document.createElement("div");
    wrap.className = "study-table-wrap";
    const table = document.createElement("table");
    table.className = "study-table";
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    for (const h of headers) {
      const th = document.createElement("th");
      th.textContent = h;
      hr.appendChild(th);
    }
    thead.appendChild(hr);
    const tbody = document.createElement("tbody");
    for (const cells of rows) {
      const tr = document.createElement("tr");
      cells.forEach((cell, cIdx) => {
        const td = document.createElement("td");
        appendRichText(td, cell, { copyable: copyableCols && cIdx > 0 });
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function appendCodeTokens(parent, text, { copyable = false } = {}) {
    const segs = String(text || "").split(/(`[^`]+`)/g);
    for (const seg of segs) {
      if (!seg) continue;
      if (seg.startsWith("`") && seg.endsWith("`") && seg.length > 2) {
        const raw = seg.slice(1, -1);
        const code = document.createElement("code");
        code.className = copyable ? "study-inline-code copyable" : "study-inline-code";
        code.textContent = raw;
        if (copyable) {
          code.title = "Copy to clipboard";
          code.onclick = () => copyText(raw, code);
        }
        parent.appendChild(code);
      } else {
        parent.appendChild(document.createTextNode(seg));
      }
    }
  }

  function appendRichText(parent, text, { copyable = false } = {}) {
    const s = String(text || "");
    let i = 0;
    while (i < s.length) {
      if (s[i] === "`") {
        const end = s.indexOf("`", i + 1);
        if (end > i + 1) {
          appendCodeTokens(parent, s.slice(i, end + 1), { copyable });
          i = end + 1;
          continue;
        }
      }
      if (s[i] === "*" && s[i + 1] === "*") {
        let end = i + 2;
        while (end < s.length - 1) {
          if (s[end] === "`") {
            const ce = s.indexOf("`", end + 1);
            if (ce !== -1) {
              end = ce + 1;
              continue;
            }
          }
          if (s[end] === "*" && s[end + 1] === "*") break;
          end += 1;
        }
        if (end < s.length - 1 && s[end] === "*" && s[end + 1] === "*" && end > i + 2) {
          const strong = document.createElement("strong");
          strong.style.color = "var(--ink)";
          appendCodeTokens(strong, s.slice(i + 2, end), { copyable });
          parent.appendChild(strong);
          i = end + 2;
          continue;
        }
      }
      let next = s.length;
      const nb = s.indexOf("`", i);
      const ns = s.indexOf("**", i);
      if (nb !== -1) next = Math.min(next, nb);
      if (ns !== -1) next = Math.min(next, ns);
      if (next === i) next = i + 1;
      parent.appendChild(document.createTextNode(s.slice(i, next)));
      i = next;
    }
  }

  function makeCmdBox(cmdText, { allowRun = false } = {}) {
    const box = document.createElement("div");
    box.className = "study-cmd-box";
    const code = document.createElement("code");
    code.textContent = cmdText;
    const acts = document.createElement("div");
    acts.className = "study-cmd-actions";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn sm ghost";
    copyBtn.append(iconEl("copy", 13), document.createTextNode("Copy"));
    copyBtn.onclick = () => copyText(cmdText, copyBtn);
    acts.appendChild(copyBtn);

    if (allowRun && runInTerminal) {
      const runBtn = document.createElement("button");
      runBtn.type = "button";
      runBtn.className = "btn sm";
      runBtn.title = "Send command to Arena terminal";
      runBtn.append(iconEl("play", 12), document.createTextNode("Run"));
      runBtn.onclick = () => runInTerminal(cmdText);
      acts.appendChild(runBtn);
    }
    box.append(code, acts);
    return box;
  }

  function makePreBlock(text, label = "Copy YAML") {
    const wrap = document.createElement("div");
    wrap.className = "yaml-card";
    const bar = document.createElement("div");
    bar.className = "yaml-card-head";
    const lbl = document.createElement("span");
    lbl.textContent = "yaml";
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn sm ghost";
    copyBtn.append(iconEl("copy", 13), document.createTextNode(label));
    copyBtn.onclick = () => copyText(text, copyBtn);
    bar.append(lbl, copyBtn);
    const pre = document.createElement("pre");
    pre.textContent = text;
    wrap.append(bar, pre);
    return wrap;
  }

  function toggleSprint() {
    if (sprintTimer) {
      clearInterval(sprintTimer);
      sprintTimer = null;
      sprintSecLeft = 0;
      renderHud();
      toast("Focus Sprint stopped");
      return;
    }
    sprintSecLeft = 15 * 60;
    toast("15m Focus Sprint started — clear 1 topic cleanly!", "success");
    renderHud();
    sprintTimer = setInterval(() => {
      sprintSecLeft = Math.max(0, sprintSecLeft - 1);
      const btn = el("study-sprint-btn");
      if (btn) {
        const m = String(Math.floor(sprintSecLeft / 60)).padStart(2, "0");
        const s = String(sprintSecLeft % 60).padStart(2, "0");
        btn.textContent = `Sprint ${m}:${s}`;
      }
      if (sprintSecLeft === 0) {
        clearInterval(sprintTimer);
        sprintTimer = null;
        toast("Focus Sprint finished! Claim your next Boss Check or rest 3m.", "success", 5500);
        renderHud();
      }
    }, 1000);
  }

  function renderHud() {
    const hud = el("study-hud");
    if (!hud || !overview) return;
    hud.innerHTML = "";

    const top = document.createElement("div");
    top.className = "study-hud-top";
    const rankBadge = document.createElement("span");
    rankBadge.className = "study-rank-badge";
    rankBadge.append(
      iconEl("award", 14),
      document.createTextNode(`${overview.rank.level} · ${overview.rank.title}`),
    );
    const xpRead = document.createElement("span");
    xpRead.className = "study-xp-readout";
    xpRead.textContent = `${overview.total_xp} / ${overview.max_xp} XP`;
    top.append(rankBadge, xpRead);
    hud.appendChild(top);

    const track = document.createElement("div");
    track.className = "study-bar-track";
    const fill = document.createElement("div");
    fill.className = "study-bar-fill";
    fill.style.setProperty("--p", String(overview.rank.progress_ratio ?? 0));
    track.appendChild(fill);
    hud.appendChild(track);

    const metrics = document.createElement("div");
    metrics.className = "study-hud-metrics";

    const streak = document.createElement("span");
    streak.className = `study-stat-chip${overview.streak_days > 0 ? " hot" : ""}`;
    streak.append(
      iconEl("flame", 14),
      document.createTextNode(`${overview.streak_days}d streak`),
    );

    const goalDone = overview.today_completed >= overview.daily_goal;
    const daily = document.createElement("span");
    daily.className = `study-stat-chip${goalDone ? " done" : ""}`;
    daily.append(
      iconEl("checkCircle", 14),
      document.createTextNode(`Today ${overview.today_completed}/${overview.daily_goal}`),
    );

    const cleared = document.createElement("span");
    cleared.className = "study-stat-chip";
    cleared.append(
      iconEl("shield", 14),
      document.createTextNode(`${overview.completed_topics}/${overview.total_topics} topics`),
    );

    const qCountChip = document.createElement("span");
    qCountChip.className = "study-stat-chip";
    qCountChip.append(
      iconEl("zap", 14),
      document.createTextNode(`${overview.passed_questions ?? 0}/${overview.total_questions ?? 108} checks`),
    );

    metrics.append(streak, daily, cleared, qCountChip);
    hud.appendChild(metrics);

    const acts = document.createElement("div");
    acts.className = "study-hud-actions";

    const contBtn = document.createElement("button");
    contBtn.type = "button";
    contBtn.id = "study-continue-btn";
    contBtn.className = "btn sm primary";
    const rec = overview.topics.find((t) => t.id === overview.recommended_topic_id);
    contBtn.textContent = rec
      ? (rec.progress.completed ? "Review Codex →" : `Continue #${rec.order} →`)
      : "Continue →";
    contBtn.onclick = () => {
      if (overview.recommended_topic_id) selectTopic(overview.recommended_topic_id);
    };

    const drillBtn = document.createElement("button");
    drillBtn.type = "button";
    drillBtn.id = "study-drill-btn";
    drillBtn.className = "btn sm";
    drillBtn.append(iconEl("zap", 13), document.createTextNode("Speed Recall"));
    drillBtn.onclick = openSpeedRecall;

    const sprintBtn = document.createElement("button");
    sprintBtn.type = "button";
    sprintBtn.id = "study-sprint-btn";
    sprintBtn.className = `btn sm${sprintTimer ? " warn-active" : ""}`;
    if (sprintTimer) {
      const m = String(Math.floor(sprintSecLeft / 60)).padStart(2, "0");
      const s = String(sprintSecLeft % 60).padStart(2, "0");
      sprintBtn.textContent = `Sprint ${m}:${s}`;
    } else {
      sprintBtn.append(iconEl("clock", 13), document.createTextNode("15m Focus Sprint"));
    }
    sprintBtn.onclick = toggleSprint;

    acts.append(contBtn, drillBtn, sprintBtn);
    hud.appendChild(acts);
  }

  function renderDomains() {
    const bar = el("study-domains");
    if (!bar || !overview) return;
    bar.innerHTML = "";

    const addChip = (id, label, unlocked = false) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `study-shield-btn${filterDomain === id ? " active" : ""}${unlocked ? " shielded" : ""}`;
      if (unlocked) btn.appendChild(iconEl("shield", 13));
      btn.appendChild(document.createTextNode(label));
      btn.onclick = () => {
        filterDomain = id;
        renderDomains();
        renderTopicList();
      };
      bar.appendChild(btn);
    };

    addChip("all", "All Domains");
    for (const d of overview.domain_shields) {
      const short = DOMAIN_SHORT[d.domain] || d.domain;
      addChip(d.domain, `${short} ${d.completed}/${d.total}`, d.shield_unlocked);
    }
  }

  function renderTopicList() {
    const container = el("study-topic-list");
    if (!container || !overview) return;
    const statusFilter = document.querySelector('input[name="study-status"]:checked')?.value || "all";
    const query = (el("study-search")?.value || "").trim().toLowerCase();

    container.innerHTML = "";
    const filtered = overview.topics.filter((t) => {
      if (filterDomain !== "all" && t.domain !== filterDomain) return false;
      if (statusFilter === "cleared" && !t.progress.completed) return false;
      if (statusFilter === "remaining" && t.progress.completed) return false;
      if (query && !t.search_blob.includes(query)) return false;
      return true;
    });

    if (!filtered.length) {
      container.innerHTML = '<div class="row" style="color:var(--ink-muted)">No study topics match that filter.</div>';
      return;
    }

    const byDomain = new Map();
    for (const t of filtered) {
      if (!byDomain.has(t.domain)) byDomain.set(t.domain, []);
      byDomain.get(t.domain).push(t);
    }

    for (const [domain, items] of byDomain.entries()) {
      const group = document.createElement("div");
      group.className = "study-domain-group";

      const shield = overview.domain_shields.find((s) => s.domain === domain);
      const hdr = document.createElement("div");
      hdr.className = "study-domain-header";
      const hTitle = document.createElement("strong");
      hTitle.textContent = `${DOMAIN_SHORT[domain] || domain} (${shield?.weight_pct ?? ""}% exam)`;
      const hCount = document.createElement("span");
      hCount.textContent = shield ? `${shield.completed}/${shield.total} cleared` : `${items.length}`;
      hdr.append(hTitle, hCount);
      group.appendChild(hdr);

      for (const topic of items) {
        const row = document.createElement("button");
        row.type = "button";
        row.dataset.topicId = topic.id;
        row.className = "study-topic-row"
          + (topic.id === activeTopicId ? " active" : "")
          + (topic.progress.completed ? " cleared" : "");

        const info = document.createElement("div");
        info.className = "study-topic-info";
        const title = document.createElement("div");
        title.className = "study-topic-title";
        title.appendChild(document.createTextNode(`${String(topic.order).padStart(2, "0")}. `));
        appendRichText(title, topic.title);
        const meta = document.createElement("div");
        meta.className = "study-topic-meta";
        meta.textContent = `~${topic.estimated_minutes}m · ${topic.exam_frequency} · bank ${topic.bank_count}`;
        info.append(title, meta);

        const dots = document.createElement("div");
        dots.className = "study-dots";
        const flags = [
          topic.progress.theory_done,
          topic.progress.practice_done,
          topic.progress.cheatsheet_done,
          topic.progress.quiz_passed,
        ];
        for (const on of flags) {
          const dot = document.createElement("span");
          dot.className = `study-dot${on ? " on" : ""}`;
          dots.appendChild(dot);
        }

        row.append(info, dots);
        row.onclick = () => selectTopic(topic.id);
        group.appendChild(row);
      }

      container.appendChild(group);
    }
  }

  async function launchPracticeLab(archId) {
    if (getActiveSession?.()?.session?.status === "active") {
      const ok = await confirmDialog(
        "End current active session?",
        `Starting a focused lab for ${archId} requires closing the currently active session first.`,
      );
      if (!ok) return;
      onEndActiveSession?.();
      return;
    }
    try {
      const sess = await api("/api/practice", {
        method: "POST",
        body: { count: 1, mode: "study", archetype_id: archId },
      });
      onSessionStarted?.(sess);
      openWorkspace?.();
      toast(`Started practice lab: ${archId}`, "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function launchGenerateLab(archId) {
    const ok = await confirmDialog(
      `Generate new lab for ${archId}?`,
      "Starts verified AI generation in Scenario Studio targeting this archetype.",
    );
    if (!ok) return;
    try {
      await api(`/api/generate/archetype/${encodeURIComponent(archId)}`, { method: "POST" });
      toast(`Generating lab for ${archId}…`, "success");
      openStudio?.();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function markStageAndAdvance(stageId, nextStageId) {
    if (!activeTopic) return;
    try {
      const res = await api(`/api/study/topics/${encodeURIComponent(activeTopic.id)}/stage`, {
        method: "POST",
        body: { stage: stageId, done: true },
      });
      const prevRank = overview?.rank?.level;
      overview = res.overview;
      activeTopic.progress = res.progress;
      if (res.xp_delta > 0) {
        toast(`+${res.xp_delta} XP · ${stageId} complete`, "success", 2400);
      }
      if (prevRank && overview.rank.level !== prevRank) {
        toast(`Rank Up! Reached ${overview.rank.level} · ${overview.rank.title}`, "success", 5000);
      }
      if (res.newly_completed) {
        toast(`Topic Cleared! 120/120 XP earned on #${activeTopic.order}`, "success", 4500);
      }
      if (nextStageId) activeStage = nextStageId;
      renderHud();
      renderDomains();
      renderTopicList();
      renderReader();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function submitBossQuiz(qIdx = activeQuizIdx) {
    if (!activeTopic || selectedChoice === null) return;
    try {
      const res = await api(`/api/study/topics/${encodeURIComponent(activeTopic.id)}/quiz`, {
        method: "POST",
        body: { choice_index: selectedChoice, question_index: qIdx },
      });
      lastQuizResult = res;
      const prevRank = overview?.rank?.level;
      overview = res.overview;
      activeTopic.progress = res.progress;
      const qList = activeTopic.quizzes || [activeTopic.quiz];
      if (res.correct && qList[qIdx]) {
        qList[qIdx].passed = true;
        qList[qIdx].correct_index = res.correct_index;
        qList[qIdx].explanation = res.explanation;
        if (res.xp_delta > 0) {
          toast(`+${res.xp_delta} XP · Boss Gauntlet cleared (3/3)!`, "success", 3400);
        } else {
          toast(`Boss Check Q${qIdx + 1}/${res.quiz_total} passed! (${res.quiz_passed_count}/${res.quiz_total})`, "success", 2600);
        }
        if (prevRank && overview.rank.level !== prevRank) {
          toast(`Rank Up! Reached ${overview.rank.level} · ${overview.rank.title}`, "success", 5000);
        }
        if (res.newly_completed) {
          toast(`Topic #${activeTopic.order} 100% Cleared!`, "success", 4500);
        }
      } else {
        toast("Not quite right — check the feedback below and retry", "error", 2800);
      }
      renderHud();
      renderDomains();
      renderTopicList();
      renderReader();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderReader() {
    if (!activeTopic) return;
    const t = activeTopic;
    const p = t.progress;

    el("study-topic-meta").textContent = `${DOMAIN_SHORT[t.domain] || t.domain} · TOPIC #${t.order} · ${t.exam_frequency.toUpperCase()} · ~${t.estimated_minutes} MIN`;
    const xpBadge = el("study-topic-xp");
    xpBadge.textContent = p.completed ? `${p.xp_earned} / ${p.max_xp} XP · CLEARED` : `${p.xp_earned} / ${p.max_xp} XP`;
    xpBadge.className = p.completed ? "badge pass" : "badge accent";

    const titleEl = el("study-topic-title");
    titleEl.textContent = "";
    appendRichText(titleEl, t.title);
    const subEl = el("study-topic-sub");
    subEl.textContent = "";
    appendRichText(subEl, t.subtitle);

    const prevBtn = el("study-prev");
    const nextBtn = el("study-next");
    prevBtn.disabled = !t.prev_topic_id;
    nextBtn.disabled = !t.next_topic_id;
    prevBtn.onclick = () => t.prev_topic_id && selectTopic(t.prev_topic_id);
    nextBtn.onclick = () => t.next_topic_id && selectTopic(t.next_topic_id);

    const tabsEl = el("study-stage-tabs");
    tabsEl.innerHTML = "";
    const doneMap = {
      theory: p.theory_done,
      practice: p.practice_done,
      cheatsheet: p.cheatsheet_done,
      quiz: p.quiz_passed,
    };
    for (const st of STAGE_LIST) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.dataset.stage = st.id;
      btn.className = `subtab${activeStage === st.id ? " on" : ""}`;
      if (doneMap[st.id]) btn.appendChild(iconEl("checkCircle", 13));
      btn.appendChild(document.createTextNode(st.label));
      const badge = document.createElement("span");
      badge.className = "subtab-badge";
      if (st.id === "quiz" && !doneMap.quiz && (p.quiz_passed_count || 0) > 0) {
        badge.textContent = `${p.quiz_passed_count}/${p.quiz_total}`;
      } else {
        badge.textContent = doneMap[st.id] ? "✓" : `+${st.xp}`;
      }
      btn.appendChild(badge);
      btn.onclick = () => {
        activeStage = st.id;
        renderReader();
      };
      tabsEl.appendChild(btn);
    }

    const body = el("study-stage-body");
    body.innerHTML = "";

    if (activeStage === "theory") {
      const sumCard = document.createElement("div");
      sumCard.className = "study-card";
      const h = document.createElement("h3");
      h.textContent = "Concept Overview";
      const para = document.createElement("p");
      appendRichText(para, t.summary, { copyable: true });
      sumCard.append(h, para);
      body.appendChild(sumCard);

      if (t.architecture_flow) {
        const flowCard = document.createElement("div");
        flowCard.className = "study-card";
        const fh = document.createElement("h3");
        fh.textContent = "Architecture & Data Flow";
        const flowBox = document.createElement("div");
        flowBox.className = "study-flow-box";
        appendRichText(flowBox, t.architecture_flow);
        flowCard.append(fh, flowBox);
        body.appendChild(flowCard);
      }

      const ptsCard = document.createElement("div");
      ptsCard.className = "study-card";
      const ph = document.createElement("h3");
      ph.textContent = "Core Exam Mechanics";
      const ul = document.createElement("ul");
      ul.className = "study-bullets";
      for (const point of t.theory_points) {
        const li = document.createElement("li");
        appendRichText(li, point, { copyable: true });
        ul.appendChild(li);
      }
      ptsCard.append(ph, ul);
      body.appendChild(ptsCard);

      if (t.decision_matrix?.length) {
        const matSec = document.createElement("div");
        const matHdr = document.createElement("div");
        matHdr.className = "section-title";
        matHdr.textContent = "Compare & Choose (Exam Decision Matrix)";
        matSec.append(
          matHdr,
          buildTable(
            ["Concept / Flag", "Behavior", "When to Use"],
            t.decision_matrix.map((r) => [r.concept, r.behavior, r.when_to_use]),
          ),
        );
        body.appendChild(matSec);
      }

      const docSec = document.createElement("div");
      const docHdr = document.createElement("div");
      docHdr.className = "section-title";
      docHdr.textContent = "Allowed Exam Official Documentation";
      const docGrid = document.createElement("div");
      docGrid.className = "study-doc-list";
      for (const d of t.docs_links) {
        const a = document.createElement("a");
        a.className = "study-doc-card";
        a.href = d.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const lbl = document.createElement("span");
        lbl.className = "study-doc-label";
        lbl.append(iconEl("externalLink", 14), document.createTextNode(d.label));
        const hint = document.createElement("span");
        hint.className = "study-doc-hint";
        hint.textContent = `PSI search: "${d.exam_search_term}"`;
        a.append(lbl, hint);
        docGrid.appendChild(a);
      }
      docSec.append(docHdr, docGrid);
      body.appendChild(docSec);

      const foot = document.createElement("div");
      foot.className = "study-stage-footer";
      const stNote = document.createElement("span");
      stNote.style.fontSize = "var(--text-xs)";
      stNote.style.color = "var(--ink-muted)";
      stNote.textContent = p.theory_done ? "Concept & Theory completed (+25 XP earned)." : "Read the mental model & docs, then advance to Practice.";
      const actBtn = document.createElement("button");
      actBtn.type = "button";
      actBtn.className = p.theory_done ? "btn" : "check-btn";
      actBtn.textContent = p.theory_done ? "Next: Hands-On Practice →" : "Mark Theory Complete (+25 XP) →";
      actBtn.onclick = () => {
        if (p.theory_done) {
          activeStage = "practice";
          renderReader();
        } else {
          markStageAndAdvance("theory", "practice");
        }
      };
      foot.append(stNote, actBtn);
      body.appendChild(foot);
      return;
    }

    if (activeStage === "practice") {
      t.practice_steps.forEach((step, idx) => {
        const card = document.createElement("div");
        card.className = "study-step-card";
        const head = document.createElement("div");
        head.className = "study-step-head";
        const num = document.createElement("span");
        num.className = "study-step-num";
        num.textContent = String(idx + 1);
        head.appendChild(num);
        appendRichText(head, step.title);
        const exp = document.createElement("p");
        exp.style.fontSize = "var(--text-sm)";
        exp.style.color = "var(--ink-secondary)";
        appendRichText(exp, step.explanation, { copyable: true });
        card.append(head, exp);
        if (step.command) card.appendChild(makeCmdBox(step.command, { allowRun: true }));
        if (step.yaml_snippet) card.appendChild(makePreBlock(step.yaml_snippet, "Copy Snippet"));
        if (step.verify_command || step.expected_output) {
          const vBox = document.createElement("div");
          vBox.className = "study-verify-box";
          const vh = document.createElement("div");
          vh.className = "study-verify-head";
          vh.append(iconEl("checkCircle", 13), document.createTextNode("Verify & Expected Output"));
          vBox.appendChild(vh);
          if (step.verify_command) vBox.appendChild(makeCmdBox(step.verify_command, { allowRun: true }));
          if (step.expected_output) {
            const vExp = document.createElement("div");
            vExp.className = "study-verify-exp";
            const strongExp = document.createElement("strong");
            strongExp.textContent = "Expected: ";
            vExp.appendChild(strongExp);
            appendRichText(vExp, step.expected_output, { copyable: true });
            vBox.appendChild(vExp);
          }
          card.appendChild(vBox);
        }
        body.appendChild(card);
      });

      if (t.debug_playbook?.length) {
        const pbSec = document.createElement("div");
        const pbHdr = document.createElement("div");
        pbHdr.className = "section-title";
        pbHdr.textContent = "Troubleshooting Triage Playbook";
        pbSec.append(
          pbHdr,
          buildTable(
            ["Symptom", "Root Cause", "Fast Fix"],
            t.debug_playbook.map((r) => [r.symptom, r.cause, r.fix]),
          ),
        );
        body.appendChild(pbSec);
      }

      const trap = document.createElement("div");
      trap.className = "study-trap-card";
      const ico = document.createElement("span");
      ico.className = "study-trap-icon";
      ico.appendChild(iconEl("alertTriangle", 17));
      const trapText = document.createElement("div");
      const strong = document.createElement("strong");
      strong.style.display = "block";
      strong.style.marginBlockEnd = "3px";
      strong.textContent = "PSI Exam Trap";
      trapText.appendChild(strong);
      appendRichText(trapText, t.exam_trap, { copyable: true });
      trap.append(ico, trapText);
      body.appendChild(trap);

      const labSec = document.createElement("div");
      const labHdr = document.createElement("div");
      labHdr.className = "section-title";
      labHdr.textContent = "Live Cluster Practice Labs (CKA Arena Bank)";
      const labGrid = document.createElement("div");
      labGrid.className = "study-lab-grid";
      for (const arch of t.archetypes) {
        const ac = document.createElement("div");
        ac.className = "arch-card";
        const aHead = document.createElement("div");
        aHead.className = "arch-head";
        const aId = document.createElement("span");
        aId.className = "arch-id";
        aId.textContent = arch.id;
        const aSt = document.createElement("span");
        aSt.className = `arch-status ${arch.status}`;
        aSt.textContent = arch.status === "unseen" ? "unseen" : `${Math.round(arch.mastery_score)}%`;
        aHead.append(aId, aSt);

        const aSub = document.createElement("div");
        aSub.className = "arch-sub";
        aSub.textContent = `${arch.subtopics.slice(0, 3).join(" · ")} · bank: ${arch.bank_count}`;

        const aActs = document.createElement("div");
        aActs.className = "arch-actions";
        if (arch.bank_count > 0) {
          const pBtn = document.createElement("button");
          pBtn.type = "button";
          pBtn.className = "btn sm primary";
          pBtn.textContent = "Launch Practice Lab →";
          pBtn.onclick = () => launchPracticeLab(arch.id);
          aActs.appendChild(pBtn);
        }
        const gBtn = document.createElement("button");
        gBtn.type = "button";
        gBtn.className = "btn sm ghost";
        gBtn.textContent = arch.bank_count > 0 ? "+ Gen" : "Generate AI Lab";
        gBtn.onclick = () => launchGenerateLab(arch.id);
        aActs.appendChild(gBtn);

        ac.append(aHead, aSub, aActs);
        labGrid.appendChild(ac);
      }
      labSec.append(labHdr, labGrid);
      body.appendChild(labSec);

      const foot = document.createElement("div");
      foot.className = "study-stage-footer";
      const note = document.createElement("span");
      note.style.fontSize = "var(--text-xs)";
      note.style.color = "var(--ink-muted)";
      note.textContent = p.practice_done ? "Hands-On Practice completed (+35 XP earned)." : "Review the commands or launch a live cluster lab above.";
      const actBtn = document.createElement("button");
      actBtn.type = "button";
      actBtn.className = p.practice_done ? "btn" : "check-btn";
      actBtn.textContent = p.practice_done ? "Next: Cheat Sheet →" : "Mark Practice Complete (+35 XP) →";
      actBtn.onclick = () => {
        if (p.practice_done) {
          activeStage = "cheatsheet";
          renderReader();
        } else {
          markStageAndAdvance("practice", "cheatsheet");
        }
      };
      foot.append(note, actBtn);
      body.appendChild(foot);
      return;
    }

    if (activeStage === "cheatsheet") {
      const cmdHdr = document.createElement("div");
      cmdHdr.className = "section-title";
      cmdHdr.textContent = "Rapid Exam Command Reference";
      body.appendChild(cmdHdr);

      for (const item of t.cheatsheet) {
        const row = document.createElement("div");
        row.className = "study-cheat-row";
        const rh = document.createElement("div");
        rh.className = "study-cheat-head";
        const lbl = document.createElement("strong");
        lbl.textContent = item.label;
        const note = document.createElement("span");
        appendRichText(note, item.note || "", { copyable: true });
        rh.append(lbl, note);
        row.append(rh, makeCmdBox(item.command));
        body.appendChild(row);
      }

      if (t.yaml_template) {
        const yHdr = document.createElement("div");
        yHdr.className = "section-title";
        yHdr.textContent = "Minimal YAML Skeleton";
        body.append(yHdr, makePreBlock(t.yaml_template, "Copy Template"));
      }

      const foot = document.createElement("div");
      foot.className = "study-stage-footer";
      const note = document.createElement("span");
      note.style.fontSize = "var(--text-xs)";
      note.style.color = "var(--ink-muted)";
      note.textContent = p.cheatsheet_done ? "Cheat Sheet mastered (+20 XP earned)." : "Bookmark the shortcuts, then tackle the Boss Check!";
      const actBtn = document.createElement("button");
      actBtn.type = "button";
      actBtn.className = p.cheatsheet_done ? "btn" : "check-btn";
      actBtn.textContent = p.cheatsheet_done ? "Next: Boss Check →" : "Mark Cheat Sheet Mastered (+20 XP) →";
      actBtn.onclick = () => {
        if (p.cheatsheet_done) {
          activeStage = "quiz";
          renderReader();
        } else {
          markStageAndAdvance("cheatsheet", "quiz");
        }
      };
      foot.append(note, actBtn);
      body.appendChild(foot);
      return;
    }

    // stage === "quiz" (3-Question Boss Gauntlet)
    const quizzes = t.quizzes?.length ? t.quizzes : [t.quiz];
    if (activeQuizIdx < 0 || activeQuizIdx >= quizzes.length) activeQuizIdx = 0;
    const q = quizzes[activeQuizIdx];

    const qCard = document.createElement("div");
    qCard.className = "study-card";

    const gBar = document.createElement("div");
    gBar.className = "study-gauntlet-bar";
    const gPills = document.createElement("div");
    gPills.className = "study-gauntlet-pills";
    quizzes.forEach((item, idx) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "study-gauntlet-pill"
        + (idx === activeQuizIdx ? " active" : "")
        + (item.passed ? " passed" : "");
      if (item.passed) pill.appendChild(iconEl("checkCircle", 12));
      pill.appendChild(document.createTextNode(`Q${idx + 1} · ${item.tag || "Check"}`));
      pill.onclick = () => {
        activeQuizIdx = idx;
        selectedChoice = null;
        lastQuizResult = null;
        renderReader();
      };
      gPills.appendChild(pill);
    });
    const gProg = document.createElement("span");
    gProg.className = p.quiz_passed ? "badge pass" : "badge accent";
    gProg.textContent = `${p.quiz_passed_count ?? (p.quiz_passed ? quizzes.length : 0)} / ${quizzes.length} Cleared (+40 XP)`;
    gBar.append(gPills, gProg);
    qCard.appendChild(gBar);

    const qHead = document.createElement("h3");
    qHead.textContent = `Boss Gauntlet Q${activeQuizIdx + 1}/${quizzes.length} · ${q.tag || "Scenario"}`;
    const qText = document.createElement("p");
    qText.style.whiteSpace = "pre-wrap";
    appendRichText(qText, q.question, { copyable: true });
    qCard.append(qHead, qText);

    const choicesBox = document.createElement("div");
    choicesBox.className = "study-quiz-choices";
    q.choices.forEach((choiceText, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "study-quiz-choice";
      const passedIdx = q.correct_index;
      if (q.passed && idx === passedIdx) {
        btn.classList.add("correct");
      } else if (lastQuizResult && !lastQuizResult.correct && lastQuizResult.question_index === activeQuizIdx && idx === selectedChoice) {
        btn.classList.add("wrong");
      } else if (selectedChoice === idx) {
        btn.classList.add("selected");
      }
      const keyTag = document.createElement("kbd");
      keyTag.textContent = String.fromCharCode(65 + idx);
      const span = document.createElement("span");
      appendRichText(span, choiceText);
      btn.append(keyTag, span);
      btn.onclick = () => {
        selectedChoice = idx;
        lastQuizResult = null;
        renderReader();
      };
      choicesBox.appendChild(btn);
    });
    qCard.appendChild(choicesBox);

    if (q.passed && q.explanation) {
      const okBox = document.createElement("div");
      okBox.className = "check-item pass";
      okBox.style.marginBlockStart = "12px";
      const r1 = document.createElement("div");
      r1.className = "check-row";
      const badge = document.createElement("span");
      badge.className = "check-badge PASS";
      badge.append(iconEl("checkCircle", 14), document.createTextNode("CLEARED"));
      const exp = document.createElement("span");
      exp.className = "check-desc";
      appendRichText(exp, q.explanation, { copyable: true });
      r1.append(badge, exp);
      okBox.appendChild(r1);
      qCard.appendChild(okBox);
    } else if (lastQuizResult && !lastQuizResult.correct && lastQuizResult.question_index === activeQuizIdx) {
      const errBox = document.createElement("div");
      errBox.className = "check-item fail";
      errBox.style.marginBlockStart = "12px";
      const r1 = document.createElement("div");
      r1.className = "check-row";
      const badge = document.createElement("span");
      badge.className = "check-badge FAIL";
      badge.append(iconEl("xCircle", 14), document.createTextNode("RETRY"));
      const exp = document.createElement("span");
      exp.className = "check-desc";
      exp.textContent = lastQuizResult.explanation;
      r1.append(badge, exp);
      errBox.appendChild(r1);
      qCard.appendChild(errBox);
    }

    body.appendChild(qCard);

    const foot = document.createElement("div");
    foot.className = "study-stage-footer";
    const leftInfo = document.createElement("span");
    leftInfo.style.fontSize = "var(--text-xs)";
    leftInfo.style.color = "var(--ink-muted)";
    leftInfo.textContent = p.quiz_passed
      ? `All ${quizzes.length} Boss Checks passed (${p.quiz_attempts} total attempt${p.quiz_attempts === 1 ? "" : "s"}).`
      : `Clear all ${quizzes.length} Boss Checks (${p.quiz_passed_count ?? 0}/${quizzes.length} done) to earn +40 XP.`;

    const acts = document.createElement("div");
    acts.className = "pill-row";
    if (!q.passed) {
      const subBtn = document.createElement("button");
      subBtn.type = "button";
      subBtn.id = "study-quiz-submit";
      subBtn.className = "check-btn";
      subBtn.disabled = selectedChoice === null;
      subBtn.textContent = `Submit Q${activeQuizIdx + 1} Answer`;
      subBtn.onclick = () => submitBossQuiz(activeQuizIdx);
      acts.appendChild(subBtn);
    } else {
      const nextUnpassed = quizzes.findIndex((item) => !item.passed);
      if (nextUnpassed !== -1) {
        const nxtQBtn = document.createElement("button");
        nxtQBtn.type = "button";
        nxtQBtn.className = "check-btn";
        nxtQBtn.textContent = `Next Question (Q${nextUnpassed + 1}/${quizzes.length}) →`;
        nxtQBtn.onclick = () => {
          activeQuizIdx = nextUnpassed;
          selectedChoice = null;
          lastQuizResult = null;
          renderReader();
        };
        acts.appendChild(nxtQBtn);
      } else if (t.next_topic_id) {
        const nxtBtn = document.createElement("button");
        nxtBtn.type = "button";
        nxtBtn.className = "check-btn";
        nxtBtn.textContent = "Advance to Next Topic →";
        nxtBtn.onclick = () => selectTopic(t.next_topic_id);
        acts.appendChild(nxtBtn);
      }
    }
    foot.append(leftInfo, acts);
    body.appendChild(foot);
  }

  async function selectTopic(topicId) {
    activeTopicId = topicId;
    selectedChoice = null;
    lastQuizResult = null;
    try {
      activeTopic = await api(`/api/study/topics/${encodeURIComponent(topicId)}`);
      const qList = activeTopic?.quizzes || [];
      const firstUnpassedQ = qList.findIndex((item) => !item.passed);
      activeQuizIdx = firstUnpassedQ >= 0 ? firstUnpassedQ : 0;
      if (activeTopic?.progress && !activeTopic.progress.completed) {
        const p = activeTopic.progress;
        activeStage = !p.theory_done
          ? "theory"
          : !p.practice_done
            ? "practice"
            : !p.cheatsheet_done
              ? "cheatsheet"
              : "quiz";
      } else {
        activeStage = "theory";
      }
      renderTopicList();
      renderReader();
      const scrollEl = el("study-reader-scroll");
      if (scrollEl) scrollEl.scrollTop = 0;
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function refresh() {
    try {
      overview = await api("/api/study/overview");
      renderHud();
      renderDomains();
      renderTopicList();
      const targetId = activeTopicId || overview.recommended_topic_id || overview.topics[0]?.id;
      if (targetId && (!activeTopic || activeTopic.id !== targetId)) {
        await selectTopic(targetId);
      } else if (activeTopic) {
        await selectTopic(activeTopic.id);
      }
    } catch (error) {
      toast(`Failed to load Study Codex: ${error.message}`, "error");
    }
  }

  function renderDrillModal() {
    const body = el("study-drill-body");
    const acts = el("study-drill-actions");
    const counter = el("study-drill-counter");
    if (!body || !acts || !drillState) return;
    body.innerHTML = "";
    acts.innerHTML = "";

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.id = "study-drill-close";
    closeBtn.className = "btn ghost";
    closeBtn.textContent = "Close";
    closeBtn.onclick = () => closeDialog(drillDialog);

    if (drillState.done || drillState.idx >= drillState.items.length) {
      if (counter) counter.textContent = `${drillState.items.length} / ${drillState.items.length}`;
      const sum = document.createElement("div");
      sum.className = "study-card";
      const h = document.createElement("h3");
      h.textContent = "Speed Recall Blitz Complete";
      const p = document.createElement("p");
      p.textContent = `Score: ${drillState.correctCount} / ${drillState.items.length} correct · Bonus earned: +${drillState.xpEarned} XP`;
      sum.append(h, p);
      body.appendChild(sum);

      const againBtn = document.createElement("button");
      againBtn.type = "button";
      againBtn.className = "btn primary";
      againBtn.textContent = "Run Another Blitz →";
      againBtn.onclick = openSpeedRecall;
      acts.append(closeBtn, againBtn);
      return;
    }

    const item = drillState.items[drillState.idx];
    if (counter) counter.textContent = `${drillState.idx + 1} / ${drillState.items.length}`;

    const meta = document.createElement("div");
    meta.className = "study-drill-meta";
    const mLeft = document.createElement("span");
    mLeft.textContent = `${DOMAIN_SHORT[item.domain] || item.domain} · #${item.topic_order} · ${item.tag}`;
    const mRight = document.createElement("span");
    mRight.textContent = `Score: ${drillState.correctCount}/${drillState.idx}`;
    meta.append(mLeft, mRight);
    body.appendChild(meta);

    const qP = document.createElement("p");
    qP.style.fontSize = "var(--text-sm)";
    qP.style.lineHeight = "1.6";
    qP.style.marginBlockEnd = "12px";
    qP.style.whiteSpace = "pre-wrap";
    appendRichText(qP, item.question, { copyable: false });
    body.appendChild(qP);

    const list = document.createElement("div");
    list.className = "study-quiz-choices";
    item.choices.forEach((txt, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "study-quiz-choice";
      if (drillState.result) {
        if (drillState.result.correct && idx === drillState.result.correct_index) btn.classList.add("correct");
        else if (!drillState.result.correct && idx === drillState.selected) btn.classList.add("wrong");
      } else if (drillState.selected === idx) {
        btn.classList.add("selected");
      }
      const k = document.createElement("kbd");
      k.textContent = String.fromCharCode(65 + idx);
      const sp = document.createElement("span");
      appendRichText(sp, txt);
      btn.append(k, sp);
      btn.onclick = () => {
        if (drillState.result) return;
        drillState.selected = idx;
        renderDrillModal();
      };
      list.appendChild(btn);
    });
    body.appendChild(list);

    if (drillState.result) {
      const fb = document.createElement("div");
      fb.className = `check-item ${drillState.result.correct ? "pass" : "fail"}`;
      fb.style.marginBlockStart = "12px";
      const r1 = document.createElement("div");
      r1.className = "check-row";
      const b = document.createElement("span");
      b.className = `check-badge ${drillState.result.correct ? "PASS" : "FAIL"}`;
      b.textContent = drillState.result.correct ? "PASS" : "MISS";
      const desc = document.createElement("span");
      desc.className = "check-desc";
      appendRichText(desc, drillState.result.explanation, { copyable: true });
      r1.append(b, desc);
      fb.appendChild(r1);
      body.appendChild(fb);
    }

    acts.appendChild(closeBtn);
    if (!drillState.result) {
      const chkBtn = document.createElement("button");
      chkBtn.type = "button";
      chkBtn.className = "btn primary";
      chkBtn.disabled = drillState.selected === null;
      chkBtn.textContent = "Check Answer";
      chkBtn.onclick = async () => {
        if (drillState.selected === null) return;
        try {
          const res = await api(`/api/study/topics/${encodeURIComponent(item.topic_id)}/quiz`, {
            method: "POST",
            body: { choice_index: drillState.selected, question_index: item.question_index },
          });
          drillState.result = res;
          if (res.correct) drillState.correctCount += 1;
          drillState.xpEarned += res.xp_delta || 0;
          overview = res.overview;
          renderHud();
          renderDomains();
          renderTopicList();
          if (activeTopic && activeTopic.id === item.topic_id) {
            await selectTopic(activeTopic.id);
          }
          renderDrillModal();
        } catch (error) {
          toast(error.message, "error");
        }
      };
      acts.appendChild(chkBtn);
    } else {
      const nxtBtn = document.createElement("button");
      nxtBtn.type = "button";
      nxtBtn.className = "btn primary";
      nxtBtn.textContent = drillState.idx + 1 >= drillState.items.length ? "View Blitz Summary →" : "Next Card →";
      nxtBtn.onclick = () => {
        drillState.idx += 1;
        drillState.selected = null;
        drillState.result = null;
        if (drillState.idx >= drillState.items.length) drillState.done = true;
        renderDrillModal();
      };
      acts.appendChild(nxtBtn);
    }
  }

  async function openSpeedRecall() {
    if (!drillDialog) return;
    const domParam = filterDomain !== "all" ? `&domain=${encodeURIComponent(filterDomain)}` : "";
    try {
      const deck = await api(`/api/study/drill?limit=10${domParam}`);
      const subEl = el("study-drill-sub");
      if (subEl) {
        subEl.textContent = filterDomain === "all"
          ? `Rapid active-recall deck (${deck.count} cards across all 5 CKA domains)`
          : `Rapid active-recall deck scoped to ${DOMAIN_SHORT[filterDomain] || filterDomain} (${deck.count} cards)`;
      }
      drillState = {
        items: deck.items || [],
        idx: 0,
        selected: null,
        result: null,
        correctCount: 0,
        xpEarned: 0,
        done: !(deck.items && deck.items.length),
      };
      renderDrillModal();
      openDialog(drillDialog);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openRecommended() {
    if (overview?.recommended_topic_id) {
      selectTopic(overview.recommended_topic_id);
    } else {
      refresh();
    }
  }

  el("study-status-filters")?.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("change", renderTopicList);
  });
  el("study-search")?.addEventListener("input", () => {
    clearTimeout(refresh._st);
    refresh._st = setTimeout(renderTopicList, 120);
  });

  return { refresh, selectTopic, openRecommended, openSpeedRecall };
}
