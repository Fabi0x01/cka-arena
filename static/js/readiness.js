// readiness.js — Orbital Threshold Scale Bar, 4 Criteria Grid, Drills & Filterable 59-Archetype Skill Tree
import { api } from "./api.js";
import { el, toast, confirmDialog } from "./ui.js";

const DOMAIN_SHORT = {
  "Troubleshooting": "Troubleshooting",
  "Cluster Architecture, Installation & Configuration": "Cluster Arch",
  "Services & Networking": "Services & Net",
  "Workloads & Scheduling": "Workloads",
  "Storage": "Storage",
};

export function initReadiness({ onSessionStarted, openWorkspace, openStudio }) {
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

  async function refresh() {
    const summaryEl = el("readiness-summary");
    const critEl = el("readiness-criteria");
    const mocksEl = el("recent-mocks-body");
    if (!summaryEl || !critEl) return;

    try {
      const data = await api("/api/readiness");
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
  el("skill-search")?.addEventListener("input", renderSkillTree);
  el("skill-status-filters")?.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("change", renderSkillTree);
  });

  return { refresh };
}
