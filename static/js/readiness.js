// readiness.js — Orbital Threshold Scale Bar, 4 Criteria Grid, Drills & Filterable 59-Archetype Skill Tree
import { api } from "./api.js";
import { el, toast, confirmDialog } from "./ui.js";
import { openExamReview } from "./review.js";

const DOMAIN_SHORT = {
  "Troubleshooting": "Troubleshooting",
  "Cluster Architecture, Installation & Configuration": "Cluster Arch",
  "Services & Networking": "Services & Net",
  "Workloads & Scheduling": "Workloads",
  "Storage": "Storage",
};

export function initReadiness({ onSessionStarted, openWorkspace, openStudio, onOpenCodex }) {
  let cachedData = null;
  let activeDomain = "all";

  async function startPresetSession(variant, count) {
    try {
      const sess = await api("/api/practice", {
        method: "POST",
        body: { count, mode: variant.includes("mock") || variant === "blind_exam" ? "mock_exam" : "study", variant },
      });
      onSessionStarted?.(sess);
      openWorkspace?.();
      toast(`${sess.session.title} started`, "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function launchArchetypePractice(archId) {
    try {
      const sess = await api("/api/practice", {
        method: "POST",
        body: { count: 1, mode: "study", archetype_id: archId },
      });
      onSessionStarted?.(sess);
      openWorkspace?.();
      toast(`Started practice for ${archId}`, "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function launchArchetypeGenerate(archId) {
    const ok = await confirmDialog(
      `Generate new scenario for ${archId}?`,
      "Starts AI generation targeting this specific CKA curriculum archetype.",
    );
    if (!ok) return;
    try {
      await api(`/api/generate/archetype/${encodeURIComponent(archId)}`, { method: "POST" });
      toast(`Generating ${archId}…`, "success");
      openStudio?.();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderCriterion(label, crit, unit = "%", invert = false) {
    const valText = crit.value === null || crit.value === undefined
      ? "—"
      : invert
        ? `${crit.value}x`
        : `${crit.value}${unit}`;
    const targetText = invert ? `≤ ${crit.target}x` : `≥ ${crit.target}${unit}`;
    let pct = 0;
    if (crit.value !== null && crit.value !== undefined) {
      pct = invert
        ? Math.max(8, Math.min(100, Math.round((crit.target / Math.max(0.2, crit.value)) * 100)))
        : Math.max(0, Math.min(100, Math.round((crit.value / Math.max(1, crit.target)) * 100)));
    }

    const card = document.createElement("div");
    card.className = "crit-card " + (crit.ok ? "ok" : "miss");

    const lbl = document.createElement("div");
    lbl.className = "label";
    lbl.textContent = label;
    const val = document.createElement("div");
    val.className = "crit-value";
    val.textContent = valText;
    const bar = document.createElement("div");
    bar.className = "crit-bar";
    const fill = document.createElement("div");
    fill.className = "crit-bar-fill";
    fill.style.inlineSize = `${pct}%`;
    bar.appendChild(fill);
    const tgt = document.createElement("div");
    tgt.className = "crit-target";
    tgt.textContent = `Target ${targetText} · ${crit.ok ? "PASS" : "PENDING"}`;

    card.append(lbl, val, bar, tgt);
    return card;
  }

  function renderSkillTree() {
    const treeEl = el("skill-tree-body");
    if (!treeEl || !cachedData) return;

    const statusFilter = document.querySelector('input[name="skill-status"]:checked')?.value || "all";
    const searchNeedle = (el("skill-search")?.value || "").trim().toLowerCase();

    treeEl.innerHTML = "";
    let renderedCount = 0;

    for (const group of cachedData.skill_tree || []) {
      if (activeDomain !== "all" && group.domain !== activeDomain) continue;
      const filteredArchs = group.archetypes.filter((arch) => {
        if (statusFilter !== "all" && arch.status !== statusFilter) return false;
        if (searchNeedle && !`${arch.id} ${arch.subtopics.join(" ")}`.toLowerCase().includes(searchNeedle)) {
          return false;
        }
        return true;
      });
      if (!filteredArchs.length) continue;
      renderedCount += filteredArchs.length;

      const section = document.createElement("div");
      section.className = "skill-domain";
      const head = document.createElement("div");
      head.className = "skill-domain-head";
      const left = document.createElement("span");
      left.textContent = `${DOMAIN_SHORT[group.domain] || group.domain} (${group.weight_pct}%)`;
      const right = document.createElement("span");
      right.className = "bank-item-meta";
      right.textContent = `${group.practiced_archetypes}/${group.total_archetypes} practiced · mastery ${group.domain_mastery}%`;
      head.append(left, right);
      section.appendChild(head);

      const grid = document.createElement("div");
      grid.className = "skill-grid";
      for (const arch of filteredArchs) {
        const card = document.createElement("div");
        card.className = `arch-card status-${arch.status}`;

        const top = document.createElement("div");
        top.className = "arch-top";
        const title = document.createElement("span");
        title.className = "arch-id";
        title.title = arch.id;
        title.textContent = arch.id;
        const badge = document.createElement("span");
        badge.className = `pill ${arch.status === "mastered" ? "pass" : arch.status === "weak" ? "bad" : arch.status === "review_due" ? "warn" : ""}`;
        badge.textContent = arch.attempts > 0 ? `${Math.round(arch.mastery_score)}%` : arch.status;
        top.append(title, badge);

        const sub = document.createElement("div");
        sub.className = "arch-sub";
        sub.textContent = `${arch.subtopics.slice(0, 3).join(" · ")} · bank: ${arch.published_count}`;

        const acts = document.createElement("div");
        acts.className = "arch-acts";
        if (arch.published_count > 0) {
          const pBtn = document.createElement("button");
          pBtn.type = "button";
          pBtn.className = "btn sm";
          pBtn.textContent = "Practice";
          pBtn.onclick = () => launchArchetypePractice(arch.id);
          acts.appendChild(pBtn);
        }
        const gBtn = document.createElement("button");
        gBtn.type = "button";
        gBtn.className = "btn sm ghost";
        gBtn.textContent = "+ Gen";
        gBtn.onclick = () => launchArchetypeGenerate(arch.id);
        acts.appendChild(gBtn);

        const meter = document.createElement("div");
        meter.className = "arch-meter";
        const mfill = document.createElement("div");
        mfill.className = "arch-meter-fill";
        mfill.style.inlineSize = `${Math.max(0, Math.min(100, arch.mastery_score || 0))}%`;
        meter.appendChild(mfill);

        card.append(top, sub, acts, meter);
        grid.appendChild(card);
      }
      section.appendChild(grid);
      treeEl.appendChild(section);
    }

    if (renderedCount === 0) {
      treeEl.innerHTML = '<div class="row" style="color:var(--ink-muted)">No archetypes match the selected filter.</div>';
    }
  }

  function renderDomainFilters(tree) {
    const box = el("skill-domain-filters");
    if (!box) return;
    box.innerHTML = "";
    const addTab = (id, label) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "subtab" + (activeDomain === id ? " on" : "");
      btn.textContent = label;
      btn.onclick = () => {
        activeDomain = id;
        renderDomainFilters(tree);
        renderSkillTree();
      };
      box.appendChild(btn);
    };
    addTab("all", "All Domains");
    for (const g of tree || []) {
      addTab(g.domain, `${DOMAIN_SHORT[g.domain] || g.domain} ${g.weight_pct}%`);
    }
  }

  function triggerMissionAction(item) {
    if (!item) return;
    if (item.action_type === "launch_variant") {
      startPresetSession(item.variant || "weakness_drill", item.count || 5);
    } else if (item.action_type === "codex_topic" && item.topic_id && onOpenCodex) {
      onOpenCodex(item.topic_id);
    } else if (item.archetype_id) {
      launchArchetypePractice(item.archetype_id);
    }
  }

  function renderDailyMission(plan) {
    const card = el("daily-mission-card");
    const dateInput = el("exam-target-date");
    if (dateInput && document.activeElement !== dateInput) {
      dateInput.value = plan?.exam_target_date || "";
    }
    if (!card || !plan) return;
    card.innerHTML = "";
    const top = document.createElement("div");
    top.className = "row";
    top.style.display = "flex";
    top.style.justifyContent = "space-between";
    top.style.alignItems = "center";
    top.style.gap = "8px";
    const info = document.createElement("span");
    info.textContent = plan.headline || `${plan.reviews_due || 0} SRS review(s) due`;
    const primaryItem = (plan.items || [])[0];
    top.appendChild(info);
    if (primaryItem) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn sm primary";
      btn.textContent = primaryItem.label || "Launch Mission";
      btn.onclick = () => triggerMissionAction(primaryItem);
      top.appendChild(btn);
    }
    card.appendChild(top);

    for (const item of (plan.items || []).slice(0, 4)) {
      const row = document.createElement("div");
      row.className = "row";
      row.style.display = "flex";
      row.style.justifyContent = "space-between";
      row.style.alignItems = "center";
      row.style.gap = "8px";
      const text = document.createElement("span");
      text.textContent = `${item.label} — ${item.detail}`;
      const go = document.createElement("button");
      go.type = "button";
      go.className = "btn sm ghost";
      go.textContent = item.action_type === "codex_topic" ? "Study Codex" : "Practice";
      go.onclick = () => triggerMissionAction(item);
      row.append(text, go);
      card.appendChild(row);
    }
  }

  async function refresh() {
    const summaryEl = el("readiness-summary");
    const critEl = el("readiness-criteria");
    const mocksEl = el("recent-mocks-body");
    if (!summaryEl || !critEl) return;

    try {
      const [data, mission] = await Promise.all([
        api("/api/readiness"),
        api("/api/study-plan/today").catch(() => null),
      ]);
      if (mission) renderDailyMission(mission);
      cachedData = data;
      const badgeCls = data.verdict === "go" ? "pass" : data.verdict === "almost" ? "warn" : "bad";
      const verdictText = data.verdict === "go"
        ? "READY FOR CKA EXAM"
        : data.verdict === "almost"
          ? "ALMOST READY"
          : "BUILDING FOUNDATION";
      const score = Math.max(0, Math.min(100, Number(data.readiness_score || 0)));

      summaryEl.innerHTML = "";
      const top = document.createElement("div");
      top.className = "readiness-top";

      const scoreBox = document.createElement("div");
      scoreBox.className = "readiness-score";
      scoreBox.innerHTML = `${score}<small>/100</small>`;

      const meta = document.createElement("div");
      meta.style.display = "flex";
      meta.style.flexDirection = "column";
      meta.style.alignItems = "flex-end";
      meta.style.gap = "6px";
      const badge = document.createElement("span");
      badge.className = `pill ${badgeCls}`;
      badge.textContent = verdictText;
      const sub = document.createElement("span");
      sub.style.fontSize = "var(--text-xs)";
      sub.style.color = "var(--ink-muted)";
      sub.textContent = `${data.mastered_or_passed_count}/${data.total_archetypes} archetypes cleared · ${data.reviews_due} SRS due`;
      meta.append(badge, sub);
      top.append(scoreBox, meta);

      const track = document.createElement("div");
      track.className = "threshold-track";
      const fill = document.createElement("div");
      fill.className = `threshold-fill ${data.verdict}`;
      fill.style.setProperty("--p", String(score / 100));
      const marker = document.createElement("div");
      marker.className = "threshold-marker";
      marker.title = "Official CKA Passing Threshold (66%)";
      track.append(fill, marker);

      const labels = document.createElement("div");
      labels.className = "threshold-labels";
      labels.innerHTML = "<span>0%</span><span>CKA Pass Threshold: 66%</span><span>100%</span>";

      summaryEl.append(top, track, labels);

      critEl.innerHTML = "";
      critEl.appendChild(renderCriterion("Last 3 Mock Avg", data.criteria.mock_exam_avg, "%", false));
      critEl.appendChild(renderCriterion("Lowest Domain", data.criteria.domain_floor, "%", false));
      critEl.appendChild(renderCriterion("Syllabus Coverage", data.criteria.syllabus_coverage_pct, "%", false));
      critEl.appendChild(renderCriterion("Median Pacing", data.criteria.median_pacing_ratio, "", true));

      if (mocksEl) {
        const chartEl = el("mock-trend-chart");
        if (chartEl) {
          const pts = (data.recent_mocks || []).slice().reverse();
          if (pts.length >= 2) {
            chartEl.hidden = false;
            const w = 320;
            const h = 72;
            const yAt = (pct) => Math.round(h - 8 - (Math.max(0, Math.min(100, pct)) / 100) * (h - 16));
            const poly = pts.map((m, idx) => {
              const x = Math.round(12 + (idx / Math.max(1, pts.length - 1)) * (w - 24));
              return `${x},${yAt(m.score_pct)}`;
            }).join(" ");
            chartEl.innerHTML =
              `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img" aria-label="Mock exam score trend">`
              + `<line x1="8" y1="${yAt(66)}" x2="${w - 8}" y2="${yAt(66)}" stroke="var(--warn)" stroke-dasharray="4 3" stroke-width="1"/>`
              + `<line x1="8" y1="${yAt(80)}" x2="${w - 8}" y2="${yAt(80)}" stroke="var(--pass)" stroke-dasharray="2 3" stroke-width="1"/>`
              + `<polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${poly}"/>`
              + pts.map((m, idx) => {
                const x = Math.round(12 + (idx / Math.max(1, pts.length - 1)) * (w - 24));
                const col = m.score_pct >= 66 ? "var(--pass)" : "var(--fail)";
                return `<circle cx="${x}" cy="${yAt(m.score_pct)}" r="3.5" fill="${col}"><title>${m.score_pct}%</title></circle>`;
              }).join("")
              + `</svg>`;
          } else {
            chartEl.hidden = true;
            chartEl.innerHTML = "";
          }
        }
        mocksEl.innerHTML = "";
        if (!data.recent_mocks.length) {
          mocksEl.innerHTML = '<div class="row">No finished Mock Exams yet — launch a Blind Mock Exam to calibrate your score.</div>';
        } else {
          const tbl = document.createElement("table");
          tbl.className = "score-table";
          tbl.innerHTML = "<thead><tr><th>Mock Exam</th><th>Variant</th><th>Score</th><th>Result</th></tr></thead>";
          const tb = document.createElement("tbody");
          for (const m of data.recent_mocks) {
            const tr = document.createElement("tr");
            tr.className = "clickable";
            tr.title = "Click to inspect full post-exam review";
            tr.onclick = () => openExamReview(m.id, { onOpenCodex });
            const tdTitle = document.createElement("td");
            tdTitle.textContent = m.title;
            const tdVar = document.createElement("td");
            tdVar.textContent = m.variant;
            const tdScore = document.createElement("td");
            tdScore.textContent = `${m.score_pct}% (${m.earned_weight}/${m.total_weight}%)`;
            const tdRes = document.createElement("td");
            tdRes.style.color = m.score_pct >= 66 ? "var(--pass)" : "var(--fail)";
            tdRes.textContent = m.score_pct >= 66 ? "PASS" : "FAIL";
            tr.append(tdTitle, tdVar, tdScore, tdRes);
            tb.appendChild(tr);
          }
          tbl.appendChild(tb);
          mocksEl.appendChild(tbl);
        }
      }

      renderDomainFilters(data.skill_tree);
      renderSkillTree();
    } catch (error) {
      summaryEl.innerHTML = `<div class="row error">${error.message}</div>`;
    }
  }

  el("btn-drill-weak")?.addEventListener("click", () => startPresetSession("weakness_drill", 5));
  el("btn-drill-speed")?.addEventListener("click", () => startPresetSession("speed_blitz", 5));
  el("btn-drill-replay")?.addEventListener("click", () => startPresetSession("mistake_replay", 5));
  el("btn-drill-blind")?.addEventListener("click", () => startPresetSession("blind_exam", 15));
  el("btn-readiness-refresh")?.addEventListener("click", refresh);
  el("btn-save-exam-date")?.addEventListener("click", async () => {
    const val = el("exam-target-date")?.value || "";
    try {
      await api("/api/settings/preferences", { method: "PUT", body: { exam_target_date: val } });
      toast("Target CKA exam date saved", "success");
      refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  });
  el("skill-search")?.addEventListener("input", renderSkillTree);
  el("skill-status-filters")?.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("change", renderSkillTree);
  });

  return { refresh };
}
