// study.js — Editorial CKA Study Path v4.2: Collapsible domain chapters, accessible tabs, container tables, Speed Recall & Focus Sprint
import { api } from "./api.js?v=4.2";
import { el, toast, confirmDialog, copyText, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js?v=4.2";
import { iconEl } from "./icons.js?v=4.2";

const DOMAIN_LABEL = {
  "Troubleshooting": "Troubleshooting",
  "Cluster Architecture, Installation & Configuration": "Cluster Architecture",
  "Services & Networking": "Services & Networking",
  "Workloads & Scheduling": "Workloads & Scheduling",
  "Storage": "Storage",
};

const STAGE_LIST = [
  { id: "theory", label: "Concept" },
  { id: "practice", label: "Practice" },
  { id: "cheatsheet", label: "Cheat sheet" },
  { id: "quiz", label: "Quiz" },
];

const STAGE_DONE_FLAG = {
  theory: "theory_done",
  practice: "practice_done",
  cheatsheet: "cheatsheet_done",
  quiz: "quiz_passed",
};

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
  let statusFilter = "all";
  let searchTimer = null;
  let sprintTimer = null;
  let sprintSecLeft = 0;
  let selectedChoice = null;
  let lastQuizResult = null;
  let stagePending = false;
  let quizPending = false;
  let drillState = null;
  const openDomains = new Set();

  const drillDialog = el("study-drill-modal");
  if (drillDialog) {
    wireDialogBackdropDismiss(drillDialog, () => closeDialog(drillDialog));
    el("study-drill-close")?.addEventListener("click", () => closeDialog(drillDialog));
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
          code.title = "Click to copy";
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

  function appendBulletText(parent, point) {
    const s = String(point || "");
    const colonIdx = s.indexOf(": ");
    if (!s.startsWith("**") && colonIdx > 3 && colonIdx <= 52 && !s.slice(0, colonIdx).includes("`")) {
      const lead = `**${s.slice(0, colonIdx)}**: `;
      appendRichText(parent, lead + s.slice(colonIdx + 2), { copyable: true });
      return;
    }
    appendRichText(parent, s, { copyable: true });
  }

  function buildTable(headers, rows, caption, { copyableCols = true } = {}) {
    const wrap = document.createElement("div");
    wrap.className = "study-table-wrap";
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", caption || headers.join(", "));

    const table = document.createElement("table");
    table.className = "study-table";
    if (headers[1]) table.style.setProperty("--col-2", JSON.stringify(headers[1]));
    if (headers[2]) table.style.setProperty("--col-3", JSON.stringify(headers[2]));

    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    for (const h of headers) {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = h;
      hr.appendChild(th);
    }
    thead.appendChild(hr);

    const tbody = document.createElement("tbody");
    for (const cells of rows) {
      const tr = document.createElement("tr");
      cells.forEach((cell, cIdx) => {
        const cellEl = document.createElement(cIdx === 0 ? "th" : "td");
        if (cIdx === 0) cellEl.scope = "row";
        appendRichText(cellEl, cell, { copyable: copyableCols && cIdx > 0 });
        tr.appendChild(cellEl);
      });
      tbody.appendChild(tr);
    }
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function renderFlowStrip(text) {
    const container = document.createElement("div");
    container.className = "study-flow-list";
    const branches = String(text || "").split(/\s*\|\|\s*|\s+\|\s+/);
    for (const branch of branches) {
      const steps = branch.split(/\s*->\s*/).map((s) => s.trim()).filter(Boolean);
      const strip = document.createElement("div");
      strip.className = "study-flow-strip";
      if (!steps.length) {
        const node = document.createElement("span");
        node.className = "study-flow-node";
        node.textContent = branch.trim();
        strip.appendChild(node);
      } else {
        steps.forEach((stepText, idx) => {
          if (idx > 0) {
            const arr = document.createElement("span");
            arr.className = "study-flow-arrow";
            arr.textContent = "→";
            strip.appendChild(arr);
          }
          const node = document.createElement("span");
          node.className = "study-flow-node";
          node.textContent = stepText;
          strip.appendChild(node);
        });
      }
      container.appendChild(strip);
    }
    return container;
  }

  function isTemplateOrNodeCommand(cmdText) {
    if (/<[A-Za-z0-9_.:-]+>|\bYOUR_[A-Z0-9_]+\b|\.\.\./.test(cmdText)) return true;
    if (/^\s*(?:sudo\s+)?(?:crictl|journalctl|systemctl|kubeadm|etcdutl|etcdctl)\b/.test(cmdText)) return true;
    if (/^\s*(?:sudo\s+)?(?:vi|vim|nano)\s+\/etc\//.test(cmdText)) return true;
    return false;
  }

  function isDestructiveCommand(cmdText) {
    return /\b(delete|drain|cordon|uncordon|replace\s+--force|rm\s+-)\b/i.test(cmdText);
  }

  function makeSection(heading) {
    const sec = document.createElement("section");
    sec.className = "study-section";
    if (heading) {
      const h = document.createElement("h2");
      h.className = "study-h";
      h.textContent = heading;
      sec.appendChild(h);
    }
    return sec;
  }

  function copyOnBlankClick(text, node) {
    return () => {
      if (window.getSelection()?.toString()) return;
      copyText(text, node);
    };
  }

  function makeCmdRow(cmdText, { allowRun = false } = {}) {
    const row = document.createElement("div");
    row.className = "study-cmd";
    row.title = "Click to copy";

    const code = document.createElement("code");
    code.textContent = cmdText;

    const acts = document.createElement("div");
    acts.className = "study-cmd-actions";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn sm ghost";
    copyBtn.title = "Copy command";
    copyBtn.setAttribute("aria-label", "Copy command");
    copyBtn.appendChild(iconEl("copy", 13));
    copyBtn.onclick = () => copyText(cmdText, row);
    acts.appendChild(copyBtn);

    if (allowRun && runInTerminal && !isTemplateOrNodeCommand(cmdText)) {
      const runBtn = document.createElement("button");
      runBtn.type = "button";
      runBtn.className = "btn sm";
      runBtn.title = "Send command to Arena terminal";
      runBtn.append(iconEl("play", 12), document.createTextNode("Run"));
      runBtn.onclick = async () => {
        if (isDestructiveCommand(cmdText)) {
          const ok = await confirmDialog("Execute destructive command in terminal?", cmdText);
          if (!ok) return;
        }
        runInTerminal(cmdText);
      };
      acts.appendChild(runBtn);
    }

    row.append(code, acts);
    row.onclick = (event) => {
      if (event.target.closest("button")) return;
      copyOnBlankClick(cmdText, row)();
    };
    return row;
  }

  function makePre(text) {
    const wrap = document.createElement("div");
    wrap.className = "study-pre-wrap";

    const pre = document.createElement("pre");
    pre.className = "study-pre";
    pre.textContent = text;
    pre.title = "Click to copy snippet";
    pre.onclick = copyOnBlankClick(text, pre);

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn sm ghost study-pre-copy";
    copyBtn.setAttribute("aria-label", "Copy snippet");
    copyBtn.title = "Copy snippet";
    copyBtn.appendChild(iconEl("copy", 13));
    copyBtn.onclick = () => copyText(text, pre);

    wrap.append(pre, copyBtn);
    return wrap;
  }

  function makeFold(title, hint, content, { defaultOpen = false } = {}) {
    const fold = document.createElement("details");
    fold.className = "study-fold";
    if (defaultOpen) fold.open = true;
    const summary = document.createElement("summary");
    summary.appendChild(document.createTextNode(title));
    if (hint) {
      const hintEl = document.createElement("span");
      hintEl.className = "study-fold-hint";
      hintEl.textContent = hint;
      summary.appendChild(hintEl);
    }
    const body = document.createElement("div");
    body.className = "study-fold-body";
    body.appendChild(content);
    fold.append(summary, body);
    return fold;
  }

  function makeVerdict(ok, explanation, label) {
    const box = document.createElement("div");
    box.className = `check-item ${ok ? "pass" : "fail"}`;
    const row = document.createElement("div");
    row.className = "check-row";
    const badge = document.createElement("span");
    badge.className = `check-badge ${ok ? "PASS" : "FAIL"}`;
    badge.append(iconEl(ok ? "checkCircle" : "xCircle", 14), document.createTextNode(label));
    const desc = document.createElement("span");
    desc.className = "check-desc";
    appendRichText(desc, explanation, { copyable: true });
    row.append(badge, desc);
    box.appendChild(row);
    return box;
  }

  function makeCta(label, onclick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "check-btn";
    btn.textContent = label;
    btn.onclick = onclick;
    return btn;
  }

  function renderSprintButton() {
    const btn = el("study-sprint-btn");
    if (!btn) return;
    btn.innerHTML = "";
    btn.classList.toggle("warn-active", Boolean(sprintTimer));
    if (sprintTimer) {
      const m = String(Math.floor(sprintSecLeft / 60)).padStart(2, "0");
      const s = String(sprintSecLeft % 60).padStart(2, "0");
      btn.textContent = `${m}:${s}`;
      btn.title = "Focus sprint running — click to stop";
    } else {
      btn.append(iconEl("clock", 13), document.createTextNode("Sprint"));
      btn.title = "Start a 15-minute focus sprint";
    }
  }

  function toggleSprint() {
    if (sprintTimer) {
      clearInterval(sprintTimer);
      sprintTimer = null;
      sprintSecLeft = 0;
      renderSprintButton();
      toast("Focus sprint stopped");
      return;
    }
    sprintSecLeft = 15 * 60;
    toast("Focus sprint started — 15 minutes on one topic", "success");
    sprintTimer = setInterval(() => {
      sprintSecLeft = Math.max(0, sprintSecLeft - 1);
      if (sprintSecLeft === 0) {
        clearInterval(sprintTimer);
        sprintTimer = null;
        toast("Focus sprint finished — take a short break", "success", 5500);
      }
      renderSprintButton();
    }, 1000);
    renderSprintButton();
  }

  function renderPath() {
    if (!overview) return;
    const count = el("study-path-count");
    if (count) count.textContent = `${overview.completed_topics} / ${overview.total_topics}`;
    const ratio = overview.total_topics ? overview.completed_topics / overview.total_topics : 0;
    el("study-path-fill")?.style.setProperty("--p", String(ratio));
    el("study-path-bar")?.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));

    const status = el("study-foot-status");
    if (!status) return;
    const bits = [`${overview.rank.level}`];
    bits.push(`Today ${overview.today_completed}/${overview.daily_goal}`);
    if (overview.streak_days > 0) bits.push(`${overview.streak_days}d`);
    status.textContent = bits.join(" · ");
    status.title = `${overview.rank.level} ${overview.rank.title} · ${overview.total_xp} XP · ${overview.passed_questions}/${overview.total_questions} quizzes passed`;
  }

  function renderTopicList() {
    const container = el("study-topic-list");
    if (!container || !overview) return;
    const query = (el("study-search")?.value || "").trim().toLowerCase();
    const isFiltering = Boolean(query) || statusFilter !== "all";

    container.innerHTML = "";
    const filtered = overview.topics.filter((t) => {
      if (statusFilter === "cleared" && !t.progress.completed) return false;
      if (statusFilter === "remaining" && t.progress.completed) return false;
      if (query && !t.search_blob.includes(query)) return false;
      return true;
    });

    if (!filtered.length) {
      const empty = document.createElement("p");
      empty.className = "study-empty";
      empty.textContent = "No topics match this filter.";
      container.appendChild(empty);
      return;
    }

    const byDomain = new Map();
    for (const t of filtered) {
      if (!byDomain.has(t.domain)) byDomain.set(t.domain, []);
      byDomain.get(t.domain).push(t);
    }

    if (!openDomains.size && activeTopic?.domain) {
      openDomains.add(activeTopic.domain);
    }

    for (const [domain, items] of byDomain.entries()) {
      const shield = overview.domain_shields.find((s) => s.domain === domain);
      const group = document.createElement("details");
      group.className = "study-domain-group";
      group.open = isFiltering || openDomains.has(domain);
      group.addEventListener("toggle", () => {
        if (isFiltering) return;
        if (group.open) openDomains.add(domain);
        else openDomains.delete(domain);
      });

      const summary = document.createElement("summary");
      summary.className = "study-domain-summary";

      const dName = document.createElement("span");
      dName.className = "study-domain-name";
      dName.textContent = DOMAIN_LABEL[domain] || domain;

      const dWeight = document.createElement("span");
      dWeight.className = "study-domain-weight";
      if (shield) dWeight.textContent = `${shield.weight_pct}%`;

      const dCount = document.createElement("span");
      dCount.className = "study-domain-count";
      dCount.textContent = shield ? `${shield.completed}/${shield.total}` : String(items.length);

      summary.append(dName, dWeight, dCount);
      group.appendChild(summary);

      const listWrap = document.createElement("div");
      listWrap.className = "study-domain-items";

      for (const topic of items) {
        const p = topic.progress;
        const row = document.createElement("button");
        row.type = "button";
        row.dataset.topicId = topic.id;
        row.className = "study-topic-row"
          + (topic.id === activeTopicId ? " active" : "")
          + (p.completed ? " cleared" : "");

        const num = document.createElement("span");
        num.className = "study-topic-num";
        num.textContent = String(topic.order).padStart(2, "0");

        const cleanTitle = topic.title.replace(/`/g, "");
        const title = document.createElement("span");
        title.className = "study-topic-title";
        title.title = cleanTitle;
        title.textContent = cleanTitle;

        row.append(num, title);

        if (p.completed) {
          const check = iconEl("checkCircle", 14);
          check.classList.add("study-topic-check");
          check.setAttribute("aria-label", "Cleared");
          row.appendChild(check);
        } else if (topic.id === overview.recommended_topic_id) {
          const next = document.createElement("span");
          next.className = "study-topic-badge next";
          next.textContent = "Next";
          row.appendChild(next);
        } else if (p.stages_done > 0) {
          const frac = document.createElement("span");
          frac.className = "study-topic-badge";
          frac.textContent = `${p.stages_done}/4`;
          row.appendChild(frac);
        } else if (topic.lab_verified) {
          const dot = document.createElement("span");
          dot.className = "study-topic-badge lab";
          dot.title = "Verified on cluster";
          row.appendChild(dot);
        }

        row.onclick = () => selectTopic(topic.id);
        listWrap.appendChild(row);
      }

      group.appendChild(listWrap);
      container.appendChild(group);
    }
  }

  function revealActiveRow() {
    el("study-topic-list")?.querySelector(".study-topic-row.active")?.scrollIntoView({ block: "nearest" });
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

  function resetReaderScroll() {
    const scroller = el("study-reader-scroll");
    if (scroller) scroller.scrollTop = 0;
  }

  function setStage(stageId) {
    activeStage = stageId;
    renderReader();
    resetReaderScroll();
  }

  function setQuestion(idx) {
    activeQuizIdx = idx;
    selectedChoice = null;
    lastQuizResult = null;
    renderReader();
    resetReaderScroll();
  }

  function progressToast(res, doneText, rankUp) {
    const parts = [];
    if (res.xp_delta > 0) parts.push(`+${res.xp_delta} XP`);
    parts.push(doneText);
    if (res.newly_completed) parts.push("topic cleared");
    if (rankUp) parts.push(`rank up: ${overview.rank.level} ${overview.rank.title}`);
    return parts.join(" · ");
  }

  async function markStageAndAdvance(stageId, nextStageId) {
    if (!activeTopic || stagePending) return;
    const ctaBtn = el("study-foot-cta")?.firstElementChild;
    if (ctaBtn) ctaBtn.disabled = true;
    stagePending = true;
    try {
      const res = await api(`/api/study/topics/${encodeURIComponent(activeTopic.id)}/stage`, {
        method: "POST",
        body: { stage: stageId, done: true },
      });
      const prevRank = overview?.rank?.level;
      overview = res.overview;
      activeTopic.progress = res.progress;
      const rankUp = prevRank && overview.rank.level !== prevRank;
      activeStage = nextStageId;
      const label = STAGE_LIST.find((s) => s.id === stageId)?.label ?? stageId;
      toast(progressToast(res, `${label} complete`, rankUp), "success", res.newly_completed || rankUp ? 5000 : 2600);
      renderPath();
      renderTopicList();
      renderReader();
      resetReaderScroll();
    } catch (error) {
      if (ctaBtn) ctaBtn.disabled = false;
      toast(error.message, "error");
    } finally {
      stagePending = false;
    }
  }

  async function submitBossQuiz(qIdx = activeQuizIdx) {
    if (!activeTopic || selectedChoice === null || quizPending) return;
    quizPending = true;
    try {
      const res = await api(`/api/study/topics/${encodeURIComponent(activeTopic.id)}/quiz`, {
        method: "POST",
        body: { choice_index: selectedChoice, question_index: qIdx },
      });
      lastQuizResult = res;
      const prevRank = overview?.rank?.level;
      overview = res.overview;
      activeTopic.progress = res.progress;
      const rankUp = prevRank && overview.rank.level !== prevRank;
      const qList = activeTopic.quizzes || [activeTopic.quiz];
      if (res.correct && qList[qIdx]) {
        qList[qIdx].passed = true;
        qList[qIdx].correct_index = res.correct_index;
        qList[qIdx].explanation = res.explanation;
        const doneText = res.xp_delta > 0
          ? "Quiz complete"
          : `Question ${qIdx + 1} passed (${res.quiz_passed_count}/${res.quiz_total})`;
        toast(progressToast(res, doneText, rankUp), "success", res.newly_completed || rankUp ? 5000 : 2600);
      } else {
        toast("Not quite — read the feedback and try again", "error", 2800);
      }
      renderPath();
      renderTopicList();
      renderReader();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      quizPending = false;
    }
  }

  function renderConcept(body, t) {
    const lead = document.createElement("p");
    lead.className = "study-lead";
    appendRichText(lead, t.summary, { copyable: true });
    body.appendChild(lead);

    if (t.architecture_flow) {
      const sec = makeSection("Architecture flow");
      sec.appendChild(renderFlowStrip(t.architecture_flow));
      body.appendChild(sec);
    }

    if (t.theory_points?.length) {
      const sec = makeSection("Key mechanics");
      const ul = document.createElement("ul");
      ul.className = "study-bullets";
      for (const point of t.theory_points) {
        const li = document.createElement("li");
        appendBulletText(li, point);
        ul.appendChild(li);
      }
      sec.appendChild(ul);
      body.appendChild(sec);
    }

    if (t.exam_trap) {
      const trap = document.createElement("aside");
      trap.className = "study-trap";
      trap.appendChild(iconEl("alertTriangle", 16));
      const trapText = document.createElement("div");
      const trapTitle = document.createElement("strong");
      trapTitle.textContent = "Exam trap: ";
      trapText.appendChild(trapTitle);
      appendRichText(trapText, t.exam_trap, { copyable: true });
      trap.appendChild(trapText);
      body.appendChild(trap);
    }

    if (t.decision_matrix?.length) {
      body.appendChild(makeFold(
        "Decision matrix",
        `${t.decision_matrix.length} comparisons`,
        buildTable(
          ["Concept", "Behavior", "When to use"],
          t.decision_matrix.map((r) => [r.concept, r.behavior, r.when_to_use]),
          "Decision matrix",
        ),
      ));
    }

    if (t.docs_links?.length) {
      const docsList = document.createElement("ul");
      docsList.className = "study-docs";
      for (const d of t.docs_links) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = d.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.append(document.createTextNode(d.label), iconEl("externalLink", 12));
        const search = document.createElement("button");
        search.type = "button";
        search.className = "study-doc-search";
        search.title = "Copy search term for the PSI exam browser";
        search.append(document.createTextNode("PSI: "));
        const code = document.createElement("code");
        code.textContent = d.exam_search_term;
        search.appendChild(code);
        search.onclick = () => copyText(d.exam_search_term, search);
        li.append(a, search);
        docsList.appendChild(li);
      }
      body.appendChild(makeFold("Official docs & PSI search terms", `${t.docs_links.length} links`, docsList));
    }
  }

  function renderPractice(body, t) {
    const timeline = document.createElement("div");
    timeline.className = "study-timeline";

    t.practice_steps.forEach((step, idx) => {
      const sec = document.createElement("section");
      sec.className = "study-step";

      const head = document.createElement("h2");
      head.className = "study-step-title";
      const num = document.createElement("span");
      num.className = "study-step-num";
      num.textContent = String(idx + 1);
      head.appendChild(num);
      appendRichText(head, step.title);
      sec.appendChild(head);

      const exp = document.createElement("p");
      exp.className = "study-text";
      appendRichText(exp, step.explanation, { copyable: true });
      sec.appendChild(exp);

      sec.appendChild(makeCmdRow(step.command, { allowRun: true }));
      if (step.yaml_snippet) sec.appendChild(makeFold("YAML equivalent", "", makePre(step.yaml_snippet)));

      if (step.verify_command || step.expected_output) {
        const verify = document.createElement("div");
        verify.className = "study-verify";
        const vh = document.createElement("div");
        vh.className = "study-verify-head";
        vh.append(iconEl("checkCircle", 13), document.createTextNode("Verify"));
        verify.appendChild(vh);
        if (step.verify_command) verify.appendChild(makeCmdRow(step.verify_command, { allowRun: true }));
        if (step.expected_output) {
          const ve = document.createElement("p");
          ve.className = "study-expected";
          const strong = document.createElement("strong");
          strong.textContent = "Expected: ";
          ve.appendChild(strong);
          appendRichText(ve, step.expected_output, { copyable: true });
          verify.appendChild(ve);
        }
        sec.appendChild(verify);
      }

      timeline.appendChild(sec);
    });
    body.appendChild(timeline);

    if (t.debug_playbook?.length) {
      body.appendChild(makeFold(
        "Troubleshooting playbook",
        `${t.debug_playbook.length} symptoms`,
        buildTable(
          ["Symptom", "Root cause", "Fast fix"],
          t.debug_playbook.map((r) => [r.symptom, r.cause, r.fix]),
          "Troubleshooting playbook",
        ),
      ));
    }

    if (t.archetypes?.length) {
      const sec = makeSection("Cluster labs");
      const list = document.createElement("ul");
      list.className = "study-labs";
      for (const arch of t.archetypes) {
        const li = document.createElement("li");
        li.className = "study-lab";

        const info = document.createElement("div");
        info.className = "study-lab-info";
        const id = document.createElement("span");
        id.className = "study-lab-id";
        id.textContent = arch.id;
        info.appendChild(id);
        if (arch.subtopics?.length) {
          const sub = document.createElement("span");
          sub.className = "study-lab-sub";
          sub.textContent = arch.subtopics.join(", ");
          info.appendChild(sub);
        }

        const meta = document.createElement("span");
        meta.className = "study-lab-meta";
        const stText = arch.status && arch.status !== "unseen"
          ? `${arch.status.replace("_", " ")} · `
          : "";
        const action = document.createElement("button");
        action.type = "button";
        if (arch.bank_count > 0) {
          meta.textContent = `${stText}${arch.bank_count} lab${arch.bank_count === 1 ? "" : "s"}`;
          action.className = "btn sm";
          action.textContent = "Start lab";
          action.onclick = () => launchPracticeLab(arch.id);
        } else {
          meta.textContent = `${stText}0 labs`;
          action.className = "btn sm ghost";
          action.textContent = "Generate";
          action.title = "Generate a lab with AI in Scenario Studio";
          action.onclick = () => launchGenerateLab(arch.id);
        }

        li.append(info, meta, action);
        list.appendChild(li);
      }
      sec.appendChild(list);
      body.appendChild(sec);
    }
  }

  function renderCheatsheet(body, t) {
    const list = document.createElement("ul");
    list.className = "study-cheats";
    for (const item of t.cheatsheet) {
      const li = document.createElement("li");
      li.className = "study-cheat";

      const label = document.createElement("div");
      label.className = "study-cheat-label";
      const strong = document.createElement("strong");
      strong.textContent = item.label;
      label.appendChild(strong);
      if (item.note) {
        const note = document.createElement("span");
        note.className = "study-cheat-note";
        appendRichText(note, item.note);
        label.appendChild(note);
      }

      li.append(label, makeCmdRow(item.command));
      list.appendChild(li);
    }
    body.appendChild(list);

    if (t.yaml_template) {
      body.appendChild(makeFold("Exam-ready YAML & command skeleton", "Click snippet to copy", makePre(t.yaml_template), { defaultOpen: true }));
    }
  }

  function renderQuiz(body, t) {
    const quizzes = t.quizzes?.length ? t.quizzes : [t.quiz];
    if (activeQuizIdx < 0 || activeQuizIdx >= quizzes.length) activeQuizIdx = 0;
    const q = quizzes[activeQuizIdx];

    const sec = makeSection();
    sec.classList.add("study-quiz");

    const steps = document.createElement("div");
    steps.className = "subtabs study-quiz-steps";
    quizzes.forEach((item, idx) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = `subtab${idx === activeQuizIdx ? " on" : ""}${item.passed ? " passed" : ""}`;
      pill.title = item.tag || "Question";
      pill.setAttribute("aria-pressed", String(idx === activeQuizIdx));
      if (item.passed) pill.appendChild(iconEl("check", 13));
      pill.appendChild(document.createTextNode(`Q${idx + 1}`));
      pill.onclick = () => setQuestion(idx);
      steps.appendChild(pill);
    });
    sec.appendChild(steps);

    const head = document.createElement("h2");
    head.className = "study-quiz-title";
    head.appendChild(document.createTextNode(`Question ${activeQuizIdx + 1} of ${quizzes.length}`));
    if (q.tag) {
      const tag = document.createElement("span");
      tag.className = "study-quiz-tag";
      tag.textContent = q.tag;
      head.appendChild(tag);
    }
    sec.appendChild(head);

    const qText = document.createElement("p");
    qText.className = "study-question";
    appendRichText(qText, q.question, { copyable: true });
    sec.appendChild(qText);

    const choicesBox = document.createElement("div");
    choicesBox.className = "study-quiz-choices";
    q.choices.forEach((choiceText, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "study-quiz-choice";
      const answeredWrong = lastQuizResult && !lastQuizResult.correct && lastQuizResult.question_index === activeQuizIdx;
      if (q.passed && idx === q.correct_index) {
        btn.classList.add("correct");
      } else if (answeredWrong && idx === selectedChoice) {
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
    sec.appendChild(choicesBox);

    if (q.passed && q.explanation) {
      sec.appendChild(makeVerdict(true, q.explanation, "Correct"));
    } else if (lastQuizResult && !lastQuizResult.correct && lastQuizResult.question_index === activeQuizIdx) {
      sec.appendChild(makeVerdict(false, lastQuizResult.explanation, "Try again"));
    }

    body.appendChild(sec);
  }

  function renderTabs() {
    const tabsEl = el("study-stage-tabs");
    const bodyEl = el("study-stage-body");
    if (!tabsEl) return;
    tabsEl.innerHTML = "";
    tabsEl.hidden = !activeTopic;
    if (!activeTopic) return;
    const p = activeTopic.progress;
    STAGE_LIST.forEach((st, idx) => {
      const done = Boolean(p[STAGE_DONE_FLAG[st.id]]);
      const isSelected = activeStage === st.id;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.role = "tab";
      btn.id = `study-tab-${st.id}`;
      btn.dataset.stage = st.id;
      btn.className = done ? "passed" : "";
      btn.setAttribute("aria-selected", String(isSelected));
      btn.tabIndex = isSelected ? 0 : -1;
      if (isSelected) btn.setAttribute("focusgroupstart", "");
      if (done) btn.appendChild(iconEl("checkCircle", 13));
      btn.appendChild(document.createTextNode(st.label));
      if (st.id === "quiz") {
        const badge = document.createElement("span");
        badge.className = "study-tab-count";
        badge.textContent = `${p.quiz_passed_count || 0}/${p.quiz_total || 3}`;
        btn.appendChild(badge);
      }
      btn.onclick = () => setStage(st.id);
      btn.onkeydown = (ev) => {
        let nextIdx = -1;
        if (ev.key === "ArrowRight") nextIdx = (idx + 1) % STAGE_LIST.length;
        else if (ev.key === "ArrowLeft") nextIdx = (idx - 1 + STAGE_LIST.length) % STAGE_LIST.length;
        else if (ev.key === "Home") nextIdx = 0;
        else if (ev.key === "End") nextIdx = STAGE_LIST.length - 1;
        if (nextIdx >= 0) {
          ev.preventDefault();
          const targetId = STAGE_LIST[nextIdx].id;
          setStage(targetId);
          el(`study-tab-${targetId}`)?.focus();
        }
      };
      tabsEl.appendChild(btn);
      if (isSelected && bodyEl) bodyEl.setAttribute("aria-labelledby", btn.id);
    });
    const activeTabBtn = el(`study-tab-${activeStage}`);
    activeTabBtn?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  function renderStageBody() {
    const body = el("study-stage-body");
    if (!body) return;
    body.innerHTML = "";
    if (!activeTopic) {
      const loading = document.createElement("p");
      loading.className = "study-empty";
      loading.textContent = "Loading topic…";
      body.appendChild(loading);
      return;
    }
    if (activeStage === "theory") renderConcept(body, activeTopic);
    else if (activeStage === "practice") renderPractice(body, activeTopic);
    else if (activeStage === "cheatsheet") renderCheatsheet(body, activeTopic);
    else renderQuiz(body, activeTopic);
  }

  function renderFoot() {
    const left = el("study-foot-left");
    const cta = el("study-foot-cta");
    if (!left || !cta) return;
    left.innerHTML = "";
    cta.innerHTML = "";
    if (!activeTopic) return;

    const stageIdx = STAGE_LIST.findIndex((st) => st.id === activeStage);
    const prevStage = STAGE_LIST[stageIdx - 1];
    if (prevStage) {
      const back = document.createElement("button");
      back.type = "button";
      back.className = "btn sm ghost";
      back.textContent = `← ${prevStage.label}`;
      back.onclick = () => setStage(prevStage.id);
      left.appendChild(back);
    }

    const t = activeTopic;
    if (activeStage !== "quiz") {
      const nextStage = STAGE_LIST[stageIdx + 1];
      const done = t.progress[STAGE_DONE_FLAG[activeStage]];
      const ctaBtn = makeCta(`Continue to ${nextStage.label} →`, () => {
        if (done) setStage(nextStage.id);
        else markStageAndAdvance(activeStage, nextStage.id);
      });
      if (!done) ctaBtn.title = `Marks ${STAGE_LIST[stageIdx].label} as complete`;
      cta.appendChild(ctaBtn);
      return;
    }

    const quizzes = t.quizzes?.length ? t.quizzes : [t.quiz];
    if (!quizzes[activeQuizIdx].passed) {
      const submit = makeCta("Submit answer", () => submitBossQuiz(activeQuizIdx));
      submit.disabled = selectedChoice === null;
      cta.appendChild(submit);
      return;
    }
    const nextUnpassed = quizzes.findIndex((item) => !item.passed);
    if (nextUnpassed !== -1) {
      cta.appendChild(makeCta("Next question →", () => setQuestion(nextUnpassed)));
    } else if (t.next_topic_id) {
      cta.appendChild(makeCta("Next topic →", () => selectTopic(t.next_topic_id)));
    } else {
      const done = document.createElement("span");
      done.className = "pill pass";
      done.textContent = "Topic cleared";
      cta.appendChild(done);
    }
  }

  function renderReader() {
    const t = activeTopic;
    const metaEl = el("study-topic-meta");
    const titleEl = el("study-topic-title");
    const subEl = el("study-topic-sub");
    if (metaEl) metaEl.innerHTML = "";
    if (t && metaEl) {
      const shield = overview?.domain_shields?.find((s) => s.domain === t.domain);
      const parts = [
        `${DOMAIN_LABEL[t.domain] || t.domain}${shield ? ` (${shield.weight_pct}%)` : ""}`,
        `#${String(t.order).padStart(2, "0")}`,
        t.exam_frequency,
        `~${t.estimated_minutes}m`,
      ];
      parts.forEach((seg, idx) => {
        if (idx > 0) {
          const sep = document.createElement("span");
          sep.className = "study-meta-sep";
          sep.textContent = "·";
          metaEl.appendChild(sep);
        }
        const span = document.createElement("span");
        span.textContent = seg;
        metaEl.appendChild(span);
      });
      if (t.lab_verified) {
        const sep = document.createElement("span");
        sep.className = "study-meta-sep";
        sep.textContent = "·";
        const lab = document.createElement("span");
        lab.className = "study-meta-lab";
        lab.textContent = "Lab verified";
        metaEl.append(sep, lab);
      }
      if (titleEl) {
        titleEl.textContent = "";
        appendRichText(titleEl, t.title);
      }
      if (subEl) {
        subEl.textContent = "";
        appendRichText(subEl, t.subtitle);
      }
    }
    el("study-prev").disabled = !t?.prev_topic_id;
    el("study-next").disabled = !t?.next_topic_id;
    renderTabs();
    renderStageBody();
    renderFoot();
  }

  async function selectTopic(topicId) {
    activeTopicId = topicId;
    try {
      const topic = await api(`/api/study/topics/${encodeURIComponent(topicId)}`);
      if (activeTopicId !== topicId) return;
      activeTopic = topic;
      if (topic?.domain) openDomains.add(topic.domain);
      const qList = topic?.quizzes || [];
      const firstUnpassedQ = qList.findIndex((item) => !item.passed);
      activeQuizIdx = firstUnpassedQ >= 0 ? firstUnpassedQ : 0;
      const p = topic?.progress;
      if (p && !p.completed) {
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
      selectedChoice = null;
      lastQuizResult = null;
      renderTopicList();
      revealActiveRow();
      renderReader();
      resetReaderScroll();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function refresh() {
    try {
      overview = await api("/api/study/overview");
      renderPath();
      const targetId = activeTopicId || overview.recommended_topic_id || overview.topics[0]?.id;
      if (targetId) {
        await selectTopic(targetId);
      } else {
        renderTopicList();
      }
    } catch (error) {
      toast(`Failed to load the study path: ${error.message}`, "error");
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
    mLeft.textContent = `${DOMAIN_LABEL[item.domain] || item.domain} · #${item.topic_order} · ${item.tag}`;
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
          renderPath();
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
    const activeDom = activeTopic?.domain;
    const domParam = activeDom ? `&domain=${encodeURIComponent(activeDom)}` : "";
    try {
      const deck = await api(`/api/study/drill?limit=10${domParam}`);
      const subEl = el("study-drill-sub");
      if (subEl) {
        subEl.textContent = activeDom
          ? `Rapid active-recall deck scoped to ${DOMAIN_LABEL[activeDom] || activeDom} (${deck.count} cards)`
          : `Rapid active-recall deck (${deck.count} cards across all 5 CKA domains)`;
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

  el("study-status-select")?.addEventListener("change", (ev) => {
    statusFilter = ev.target.value || "all";
    renderTopicList();
  });
  el("study-search")?.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderTopicList, 120);
  });
  el("study-prev").onclick = () => activeTopic?.prev_topic_id && selectTopic(activeTopic.prev_topic_id);
  el("study-next").onclick = () => activeTopic?.next_topic_id && selectTopic(activeTopic.next_topic_id);

  const drillBtn = el("study-drill-btn");
  if (drillBtn) {
    drillBtn.prepend(iconEl("zap", 13));
    drillBtn.onclick = openSpeedRecall;
  }
  if (el("study-sprint-btn")) el("study-sprint-btn").onclick = toggleSprint;
  renderSprintButton();

  document.addEventListener("keydown", (ev) => {
    if (!el("view-study")?.classList.contains("active")) return;
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.target?.closest?.("input, textarea, select, [contenteditable]")) return;
    if (ev.key === "[" && activeTopic?.prev_topic_id) {
      ev.preventDefault();
      selectTopic(activeTopic.prev_topic_id);
    } else if (ev.key === "]" && activeTopic?.next_topic_id) {
      ev.preventDefault();
      selectTopic(activeTopic.next_topic_id);
    } else if (["1", "2", "3", "4"].includes(ev.key) && activeTopic) {
      const idx = Number(ev.key) - 1;
      if (STAGE_LIST[idx]) {
        ev.preventDefault();
        setStage(STAGE_LIST[idx].id);
      }
    }
  });

  return { refresh, selectTopic, openRecommended, openSpeedRecall };
}
