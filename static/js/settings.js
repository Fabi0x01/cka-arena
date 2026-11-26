// settings.js — 3-node hardware telemetry cards, addon status badges, LLM provider & Clean Reset L2
import { api } from "./api.js";
import { el, toast, confirmDialog } from "./ui.js";
import { iconEl } from "./icons.js";

export function initSettings({ onPowerChanged }) {
  async function refreshHealth() {
    const summaryEl = el("health-summary");
    const nodesEl = el("health-nodes");
    const addonsEl = el("health-addons");
    const bootstrapEl = el("bootstrap-body");
    if (summaryEl) summaryEl.innerHTML = '<div class="row">Probing cluster nodes &amp; addons…</div>';
    if (nodesEl) nodesEl.innerHTML = "";
    if (addonsEl) addonsEl.innerHTML = "";

    try {
      const health = await api("/api/cluster/health");
      if (summaryEl) {
        summaryEl.innerHTML = "";
        const row = document.createElement("div");
        row.className = "row";
        row.style.color = health.nodes_ready === health.total_nodes && health.kubectl_ok ? "var(--pass)" : "var(--warn)";
        row.textContent = `${health.nodes_ready}/${health.total_nodes} nodes Ready · K8s ${health.k8s_version || "?"} · kubectl ${health.kubectl_ok ? "ok" : "unreachable"} · baseline files ${health.baseline_files ? "present" : "missing"}`;
        summaryEl.appendChild(row);
      }

      if (nodesEl) {
        nodesEl.innerHTML = "";
        for (const node of health.nodes || []) {
          const card = document.createElement("div");
          card.className = `node-card ${node.ready ? "ready" : "down"}`;
          const head = document.createElement("div");
          head.className = "node-card-head";
          const nameWrap = document.createElement("span");
          nameWrap.style.display = "inline-flex";
          nameWrap.style.alignItems = "center";
          nameWrap.style.gap = "6px";
          nameWrap.append(iconEl("server", 14), document.createTextNode(node.name));
          const pill = document.createElement("span");
          pill.className = `pill ${node.ready ? "pass" : "bad"}`;
          pill.textContent = node.ready ? "Ready" : "NotReady";
          head.append(nameWrap, pill);

          const ipLine = document.createElement("div");
          ipLine.className = "node-card-meta";
          ipLine.textContent = `IP ${node.ssh_ip || node.internal_ip || "-"}`;

          const sshLine = document.createElement("div");
          sshLine.className = "node-card-meta";
          sshLine.style.color = node.ssh_ok ? "var(--pass)" : "var(--fail)";
          sshLine.textContent = node.ssh_ok ? `SSH ok · ${node.ssh_ms}ms` : "SSH unreachable";

          card.append(head, ipLine, sshLine);
          nodesEl.appendChild(card);
        }
      }

      if (addonsEl) {
        addonsEl.innerHTML = "";
        for (const addon of health.addons || []) {
          const chip = document.createElement("span");
          chip.className = `pill ${addon.status === "present" ? "pass" : addon.status === "degraded" ? "warn" : "bad"}`;
          chip.append(
            iconEl(addon.status === "present" ? "checkCircle" : "alertTriangle", 13),
            document.createTextNode(`${addon.name}${addon.detail ? ` · ${addon.detail}` : ""}`),
          );
          addonsEl.appendChild(chip);
        }
      }

      if (bootstrapEl) {
        bootstrapEl.innerHTML = "";
        if (!health.bootstrap_plan || health.bootstrap_plan.length === 0) {
          const row = document.createElement("div");
          row.className = "row done";
          row.textContent = "All optional addons are present.";
          bootstrapEl.appendChild(row);
        } else {
          for (const item of health.bootstrap_plan) {
            const row = document.createElement("div");
            row.className = "row";
            row.textContent = `${item.addon} (${item.status}) — ${item.hint}`;
            bootstrapEl.appendChild(row);
          }
        }
      }
    } catch (error) {
      if (summaryEl) {
        summaryEl.innerHTML = "";
        const row = document.createElement("div");
        row.className = "row error";
        row.textContent = error.message;
        summaryEl.appendChild(row);
      }
    }
  }

  let llmConfig = null;

  function llmPayload() {
    const customModel = el("llm-model-custom").value.trim();
    const payload = {
      provider: el("llm-provider").value,
      base_url: el("llm-base-url").value.trim(),
      auth_mode: el("llm-auth-mode").value,
      thinking: el("llm-thinking").value,
      model: customModel || el("llm-model").value.trim(),
      model_flash: el("llm-model-flash").value.trim(),
      timeout_s: Number(el("llm-timeout").value || 120),
    };
    const key = el("llm-api-key").value.trim();
    if (key) payload.api_key = key;
    if (el("llm-clear-key").checked) payload.clear_key = true;
    return payload;
  }

  function fillModelOptions(select, models, current) {
    select.innerHTML = "";
    const options = (models || []).map((model) => ({ ...model }));
    if (current && !options.some((model) => model.id === current)) {
      options.unshift({ id: current, label: `${current} (saved)` });
    }
    for (const model of options) {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.label || model.id;
      select.appendChild(option);
    }
    if (current) select.value = current;
  }

  function currentPreset() {
    if (!llmConfig) return null;
    return llmConfig.providers.find((item) => item.id === el("llm-provider").value) || null;
  }

  function applyPreset() {
    const preset = currentPreset();
    if (!preset) return;
    el("llm-base-url").value = preset.base_url;
    el("llm-auth-mode").value = preset.auth_mode;
    el("llm-model-custom").value = "";
    fillModelOptions(el("llm-model"), preset.models, preset.model);
    fillModelOptions(el("llm-model-flash"), preset.models, preset.model_flash);
  }

  function renderLlmStatus(cfg) {
    const body = el("llm-body");
    body.innerHTML = "";
    const add = (text, kind) => {
      const row = document.createElement("div");
      row.className = "row" + (kind ? ` ${kind}` : "");
      row.textContent = text;
      body.appendChild(row);
    };
    const sourceLabel = {
      file: "stored in llm_config.json",
      env: "from environment",
      local: "local endpoint (no key required)",
      unconfigured: "not configured",
    }[cfg.source] || cfg.source;
    add(
      cfg.has_key ? `key: ${cfg.api_key_masked || "none"} · ${sourceLabel}` : `no API key — ${sourceLabel} (AI generation disabled)`,
      cfg.has_key ? "done" : "error",
    );
    add(`active: ${cfg.provider} · model ${cfg.model} · flash ${cfg.model_flash} · thinking ${cfg.thinking}`);
  }

  async function refreshLlm() {
    try {
      const cfg = await api("/api/llm/config");
      llmConfig = cfg;
      const select = el("llm-provider");
      select.innerHTML = "";
      for (const preset of cfg.providers) {
        const option = document.createElement("option");
        option.value = preset.id;
        option.textContent = preset.id;
        select.appendChild(option);
      }
      select.value = cfg.provider;
      el("llm-base-url").value = cfg.base_url;
      el("llm-auth-mode").value = cfg.auth_mode;
      el("llm-thinking").value = cfg.thinking || "off";
      const preset = cfg.providers.find((item) => item.id === cfg.provider);
      fillModelOptions(el("llm-model"), preset?.models, cfg.model);
      fillModelOptions(el("llm-model-flash"), preset?.models, cfg.model_flash);
      el("llm-model-custom").value = "";
      el("llm-timeout").value = cfg.timeout_s;
      el("llm-api-key").value = "";
      el("llm-api-key").placeholder = cfg.auth_mode === "none"
        ? "not required for local Ollama"
        : cfg.has_key
          ? `stored key ${cfg.api_key_masked} — leave blank to keep`
          : "paste your provider API key";
      el("llm-clear-key").checked = false;
      renderLlmStatus(cfg);
    } catch (error) {
      const body = el("llm-body");
      body.innerHTML = `<div class="row error">${error.message}</div>`;
    }
  }

  el("llm-provider").onchange = applyPreset;
  el("btn-llm-save").onclick = async () => {
    const button = el("btn-llm-save");
    button.disabled = true;
    button.textContent = "Saving…";
    try {
      const cfg = await api("/api/llm/config", { method: "PUT", body: llmPayload() });
      llmConfig = cfg;
      el("llm-api-key").value = "";
      el("llm-clear-key").checked = false;
      renderLlmStatus(cfg);
      toast("AI provider saved", "success");
    } catch (error) {
      toast(`Save failed: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Save provider";
    }
  };

  el("btn-health-refresh").onclick = refreshHealth;
  el("btn-llm-test").onclick = async () => {
    const button = el("btn-llm-test");
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      const result = await api("/api/llm/test", { method: "POST", body: llmPayload() });
      toast(`AI provider ok · ${result.provider} · ${result.latency_ms}ms`, "success");
    } catch (error) {
      toast(`AI test failed: ${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Test connection";
    }
  };

  el("btn-baseline").onclick = async () => {
    const ok = await confirmDialog(
      "Run clean baseline reset (L2)?",
      "Removes all scenario resources, restores node baseline files and restarts containerd/kubelet while keeping installed addons (~1–2 minutes).",
    );
    if (!ok) return;
    try {
      await api("/api/cluster/reset-baseline", { method: "POST" });
      toast("Clean reset started (L2) — cluster agents restarting");
      onPowerChanged?.();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  async function refreshBackup() {
    const box = el("backup-status");
    if (!box) return;
    try {
      const st = await api("/api/backup/status");
      box.innerHTML = "";
      const row = document.createElement("div");
      row.className = "row";
      if (st.backup?.exists) {
        const kb = Math.round((st.backup.size_bytes || 0) / 1024);
        const pub = st.backup.counts?.published_questions ?? "?";
        const ts = st.manifest?.created_at_utc ? ` · ${st.manifest.created_at_utc}` : "";
        row.textContent = `Snapshot ready (${kb} KB · ${pub} published questions${ts}) — API keys excluded`;
      } else {
        row.textContent = "No portable backup snapshot created yet.";
      }
      box.appendChild(row);
    } catch (error) {
      box.innerHTML = `<div class="row error">${error.message}</div>`;
    }
  }

  el("btn-install-addons")?.addEventListener("click", async () => {
    const btn = el("btn-install-addons");
    btn.disabled = true;
    btn.textContent = "Installing…";
    try {
      const res = await api("/api/cluster/install-addons", { method: "POST" });
      toast(res.ok ? "Addons installed / verified" : "Some addons failed — check cluster logs", res.ok ? "success" : "warn");
      await refreshHealth();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Install missing addons";
    }
  });

  el("btn-backup-create")?.addEventListener("click", async () => {
    const btn = el("btn-backup-create");
    btn.disabled = true;
    btn.textContent = "Creating…";
    try {
      const meta = await api("/api/backup/create", { method: "POST" });
      toast(`Backup saved (${Math.round((meta.size_bytes || 0) / 1024)} KB)`, "success");
      await refreshBackup();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Create backup snapshot";
    }
  });

  async function refreshAll() {
    await Promise.all([refreshHealth(), refreshLlm(), refreshBackup()]);
  }

  return { refreshAll, refreshHealth, refreshLlm, refreshBackup };
}
