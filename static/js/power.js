// power.js — Left Rail Cluster Power indicator + native [popover="auto"] control menu
import { api } from "./api.js";
import { el, toast } from "./ui.js";
import { iconEl } from "./icons.js";

const LABELS = {
  ready: "Cluster Ready (3/3)",
  off: "Cluster Powered Off",
  starting: "Starting Cluster…",
  stopping: "Stopping Cluster…",
  degraded: "Cluster Degraded",
  daemon_down: "Multipass Daemon Down",
  unknown: "Checking Cluster…",
};

export function initPower(bus, onChange) {
  const pill = el("power-rail-btn");
  const menu = el("power-menu");
  let state = "unknown";
  let busy = false;
  let pollTimer = null;

  function buildMenu() {
    if (!menu) return;
    menu.innerHTML = "";
    const statusLine = document.createElement("div");
    statusLine.className = "hint";
    statusLine.style.color = state === "ready" ? "var(--pass)" : state === "daemon_down" ? "var(--fail)" : "var(--ink-muted)";
    statusLine.textContent = LABELS[state] || state;
    menu.appendChild(statusLine);

    const add = (labelText, iconName, fn, danger = false) => {
      const button = document.createElement("button");
      button.type = "button";
      const left = document.createElement("span");
      left.style.display = "inline-flex";
      left.style.alignItems = "center";
      left.style.gap = "8px";
      left.append(iconEl(iconName, 14), document.createTextNode(labelText));
      button.appendChild(left);
      if (danger) button.style.color = "var(--fail)";
      button.onclick = () => {
        try { menu.hidePopover?.(); } catch { /* noop */ }
        fn();
      };
      menu.appendChild(button);
    };

    if (state === "off") add("Power on cluster", "power", () => action("start"));
    if (state === "ready" || state === "degraded") {
      add("Stop cluster", "power", () => action("stop"), true);
      add("Restart cluster", "refreshCw", () => action("restart"));
      add("Open Telemetry", "sliders", () => document.dispatchEvent(new CustomEvent("open-settings")));
    }
    if (state === "daemon_down") {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = "Run: sudo launchctl kickstart -k system/com.canonical.multipass";
      menu.appendChild(hint);
      add("Retry health check", "refreshCw", () => refresh());
    }
    if (state === "starting" || state === "stopping") {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = "Instrumented boot in progress…";
      menu.appendChild(hint);
    }
  }

  function render(status) {
    state = status.state || "unknown";
    busy = Boolean(status.active_job);
    if (pill) {
      pill.dataset.state = state;
      pill.title = LABELS[state] || state;
    }
    buildMenu();
    onChange?.(status);
    if (busy) schedulePoll(1500);
  }

  async function refresh() {
    try {
      const status = await api("/api/cluster/power");
      render(status);
      return status;
    } catch {
      state = "daemon_down";
      if (pill) {
        pill.dataset.state = "daemon_down";
        pill.title = LABELS.daemon_down;
      }
      buildMenu();
      return null;
    }
  }

  function schedulePoll(ms = 4000) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(refresh, ms);
  }

  async function action(kind) {
    try {
      await api("/api/cluster/power", { method: "POST", body: { action: kind } });
      toast(kind === "stop" ? "Stopping cluster…" : kind === "restart" ? "Restarting cluster…" : "Starting cluster…");
      schedulePoll(1200);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  menu?.addEventListener("beforetoggle", (event) => {
    if (event.newState === "open") buildMenu();
  });

  bus.on("cluster.power.progress", (progress) => {
    if (progress.total && pill) {
      pill.title = `${progress.step}/${progress.total} · ${progress.detail}`;
    }
  });
  bus.on("cluster.power.state_changed", () => refresh());

  refresh();
  setInterval(refresh, 20000);
  return { refresh, action, get state() { return state; } };
}
