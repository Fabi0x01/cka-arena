// review.js — Post-Mock Exam Detailed Review modal
import { api } from "./api.js";
import { el, toast, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js";

let bound = false;

function bindModal() {
  if (bound) return;
  const dlg = el("review-modal");
  if (!dlg) return;
  bound = true;
  wireDialogBackdropDismiss(dlg);
  el("review-close")?.addEventListener("click", () => closeDialog(dlg));
}

export async function openExamReview(sessionId, { onOpenCodex } = {}) {
  bindModal();
  const dlg = el("review-modal");
  const body = el("review-body");
  const sub = el("review-sub");
  if (!dlg || !body) return;
  body.innerHTML = '<div class="row">Loading detailed exam review…</div>';
  openDialog(dlg);

  try {
    const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/review`);
    const s = data.summary || {};
    if (sub) {
      sub.textContent = `${data.title} · Score ${s.score_pct}% (${s.earned_weight}/${s.total_weight} weight · ${s.passed_exam ? "PASS" : "FAIL"}) · ${s.duration_minutes}m`;
    }
    body.innerHTML = "";

    const domSummary = document.createElement("div");
    domSummary.className = "progress-list";
    domSummary.style.marginBlockEnd = "12px";
    for (const [dom, st] of Object.entries(s.per_domain || {})) {
      const row = document.createElement("div");
      row.className = "row";
      row.textContent = `${dom}: ${st.passed}/${st.total} passed · ${st.earned_weight}/${st.weight}% weight`;
      domSummary.appendChild(row);
    }
    body.appendChild(domSummary);

    for (const item of data.items || []) {
      const card = document.createElement("div");
      card.className = `review-card ${item.state === "passed" ? "pass" : "fail"}`;

      const head = document.createElement("div");
      head.className = "review-card-head";
      const title = document.createElement("strong");
      title.textContent = `Q${Number(item.order_index) + 1}. ${item.title}`;
      const badges = document.createElement("span");
      badges.className = "bank-item-meta";
      const mins = (Number(item.active_seconds || 0) / 60).toFixed(1);
      const ctxBadge = item.context_switched ? "ctx ok" : `ctx ${item.context_name}`;
      badges.textContent = `${item.domain.split(",")[0]} · ${item.difficulty} · ${item.earned_weight}/${item.weight}% · ${mins}m/${item.estimated_minutes}m · ${ctxBadge}${item.flagged ? " · Flagged" : ""}`;
      head.append(title, badges);
      card.appendChild(head);

      if (item.check_results?.length) {
        const ul = document.createElement("div");
        ul.className = "review-checks";
        for (const cr of item.check_results) {
          const line = document.createElement("div");
          line.className = cr.status === "PASS" ? "row done" : "row error";
          line.textContent = `[${cr.status}] ${cr.description}`;
          ul.appendChild(line);
        }
        card.appendChild(ul);
      }

      if (item.coach?.tips?.length) {
        const tips = document.createElement("div");
        tips.className = "bank-item-meta";
        tips.style.marginBlock = "4px";
        tips.textContent = `Speed Coach (${item.coach.command_count || 0} cmds · ${item.coach.pacing_ratio}x): ${item.coach.tips[0]}`;
        card.appendChild(tips);
      }

      if (item.reference_solution || item.fast_solution_commands?.length) {
        const det = document.createElement("details");
        det.style.marginBlockStart = "6px";
        const sum = document.createElement("summary");
        sum.style.cursor = "pointer";
        sum.style.fontSize = "var(--text-xs)";
        sum.textContent = "Reference Solution & Fast CLI";
        const pre = document.createElement("pre");
        pre.className = "code-block";
        pre.style.marginBlockStart = "6px";
        const fast = item.fast_solution_commands?.length
          ? `Fast CLI:\n${item.fast_solution_commands.join("\n")}\n\n`
          : "";
        pre.textContent = `${fast}${item.reference_solution || ""}`.trim();
        det.append(sum, pre);
        card.appendChild(det);
      }

      if (item.codex_topic_id && onOpenCodex) {
        const actRow = document.createElement("div");
        actRow.style.marginBlockStart = "6px";
        const codexBtn = document.createElement("button");
        codexBtn.type = "button";
        codexBtn.className = "btn sm ghost";
        codexBtn.textContent = "Study Concept in Codex →";
        codexBtn.onclick = () => {
          closeDialog(dlg);
          onOpenCodex(item.codex_topic_id);
        };
        actRow.appendChild(codexBtn);
        card.appendChild(actRow);
      }

      body.appendChild(card);
    }
  } catch (error) {
    body.innerHTML = `<div class="row error">${error.message}</div>`;
    toast(error.message, "error");
  }
}
