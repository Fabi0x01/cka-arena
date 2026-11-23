// terminal.js — xterm.js + tabs + WebSocket PTY + native [popover="auto"] menu + scrollback find
import { api } from "./api.js";
import { el, toast } from "./ui.js";
import { iconEl } from "./icons.js";

const THEME = {
  background: "#0A0D13",
  foreground: "#E6ECF5",
  cursor: "#38D2E8",
  cursorAccent: "#0A0D13",
  selectionBackground: "rgba(56, 210, 232, 0.24)",
  black: "#181E2B",
  red: "#F5657B",
  green: "#3AD29F",
  yellow: "#EAB844",
  blue: "#4FA6F8",
  magenta: "#A88BFA",
  cyan: "#38D2E8",
  white: "#E6ECF5",
  brightBlack: "#637086",
  brightRed: "#FB90A0",
  brightGreen: "#73E3BD",
  brightYellow: "#F4D178",
  brightBlue: "#88C4FA",
  brightMagenta: "#C4B1FC",
  brightCyan: "#74E2F1",
  brightWhite: "#F8FAFC",
};

export function initTerminal() {
  const screen = el("term-screen");
  const tabsEl = el("term-tabs");
  const newTabMenu = el("new-tab-menu");
  const tabs = new Map();
  let activeId = null;
  let fontSize = Math.min(18, Math.max(11, Number(localStorage.getItem("cka_term_font_size")) || 13));

  function applyFontSize(nextSize) {
    fontSize = Math.min(18, Math.max(11, Math.round(nextSize)));
    localStorage.setItem("cka_term_font_size", String(fontSize));
    for (const tab of tabs.values()) tab.term.options.fontSize = fontSize;
    const active = activeTab();
    if (active) requestAnimationFrame(() => fitTab(active));
  }

  function adjustFont(delta) {
    applyFontSize(fontSize + delta);
    toast(`Terminal font: ${fontSize}px`, "info", 1200);
  }

  function resetFont() {
    applyFontSize(13);
    toast("Terminal font reset (13px)", "info", 1200);
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    for (const tab of tabs.values()) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tab" + (tab.id === activeId ? " active" : "");
      button.appendChild(iconEl("terminal", 13));
      const lbl = document.createElement("span");
      lbl.textContent = tab.label;
      button.appendChild(lbl);
      button.onclick = () => activate(tab.id);

      const kill = document.createElement("span");
      kill.className = "kill";
      kill.title = "Close tab";
      kill.appendChild(iconEl("x", 12));
      kill.onclick = (event) => {
        event.stopPropagation();
        closeTab(tab.id);
      };
      button.appendChild(kill);
      tabsEl.appendChild(button);
    }

    const add = document.createElement("button");
    add.type = "button";
    add.className = "tab";
    add.title = "Open new local host tab";
    add.appendChild(iconEl("plus", 13));
    add.onclick = () => openTab("host", null, "mac");
    tabsEl.appendChild(add);
  }

  function activate(tabId) {
    activeId = tabId;
    for (const [id, tab] of tabs) tab.holder.classList.toggle("active", id === tabId);
    renderTabs();
    renderWorkdir();
    requestAnimationFrame(() => fitTab(tabs.get(tabId)));
    tabs.get(tabId)?.term.focus();
  }

  function fitTab(tab) {
    if (!tab || document.body.classList.contains("native-mode")) return;
    const rect = tab.holder?.getBoundingClientRect();
    if (!rect || rect.width < 120 || rect.height < 60) return;
    try {
      tab.fit.fit();
      if (tab.ws?.readyState === 1) {
        tab.ws.send(JSON.stringify({ type: "resize", cols: tab.term.cols, rows: tab.term.rows }));
      }
    } catch { /* holder hidden */ }
  }

  async function connect(tab) {
    return new Promise((resolve) => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${protocol}://${location.host}/ws/terminal/${tab.id}`);
      tab.ws = ws;
      ws.onopen = () => {
        tab.reconnectAttempts = 0;
        fitTab(tab);
        resolve();
      };
      ws.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === "output" || message.type === "replay") tab.term.write(message.data);
        else if (message.type === "exit") tab.term.write("\r\n[process exited]\r\n");
      };
      ws.onclose = (event) => {
        if (tab.userClosed) return;
        if (event.code === 4409) {
          tab.userClosed = true;
          tab.term.write("\r\n[this terminal is already attached in another window]\r\n");
          return;
        }
        if (event.code === 4404) {
          tab.userClosed = true;
          tab.term.write("\r\n[session ended — open a new tab]\r\n");
          return;
        }
        tab.reconnectAttempts = (tab.reconnectAttempts || 0) + 1;
        if (tab.reconnectAttempts > 3) {
          tab.term.write("\r\n[session unreachable — open a new tab]\r\n");
          return;
        }
        tab.term.write("\r\n[reconnecting…]\r\n");
        setTimeout(() => connect(tab).catch(() => {}), 800);
      };
      ws.onerror = () => { try { ws.close(); } catch { /* noop */ } };
    });
  }

  async function attachExisting(info, label) {
    return openTab(info.preset, info.node, label, info.tab_id);
  }

  async function openTab(preset, node, label, existingId = null) {
    try {
      const info = existingId
        ? { tab_id: existingId, preset, node }
        : await api("/api/terminal/tabs", { method: "POST", body: { preset, node } });
      const holder = document.createElement("div");
      holder.className = "term-holder";
      screen.appendChild(holder);
      const term = new Terminal({
        fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize,
        lineHeight: 1.4,
        letterSpacing: 0,
        cursorBlink: true,
        scrollback: 5000,
        theme: THEME,
      });
      const fit = new FitAddon.FitAddon();
      term.loadAddon(fit);
      term.attachCustomKeyEventHandler((ev) => {
        if (ev.type !== "keydown") return true;
        const key = ev.key.toLowerCase();
        const isCopy = (ev.metaKey && !ev.ctrlKey && key === "c")
          || (ev.ctrlKey && ev.shiftKey && key === "c");
        if (isCopy && term.hasSelection()) {
          navigator.clipboard?.writeText(term.getSelection()).then(
            () => toast("Copied selection", "success", 1200),
            () => toast("Clipboard blocked — copy manually", "error"),
          );
          return false;
        }
        if (ev.ctrlKey && ev.shiftKey && key === "v") {
          navigator.clipboard?.readText().then(
            (text) => { if (text) term.paste(text); },
            () => toast("Clipboard read blocked — paste with Cmd+V", "error"),
          );
          return false;
        }
        if (ev.metaKey && !ev.ctrlKey && ["k", "l", "b", "f", "\\", "/", "1", "2", "3", "4", "enter", "=", "+", "-", "0"].includes(key)) {
          return false;
        }
        return true;
      });
      term.open(holder);
      if (tabs.has(info.tab_id)) {
        holder.remove();
        return tabs.get(info.tab_id);
      }
      const tab = { id: info.tab_id, preset, node, label, holder, term, fit, ws: null, userClosed: false };
      tabs.set(tab.id, tab);
      term.onData((data) => {
        if (tab.ws?.readyState === 1) tab.ws.send(JSON.stringify({ type: "input", data }));
      });
      new ResizeObserver(() => {
        if (activeId === tab.id) fitTab(tab);
      }).observe(holder);
      await connect(tab);
      activate(tab.id);
      return tab;
    } catch (error) {
      toast(error.message, "error");
      return null;
    }
  }

  async function closeTab(tabId) {
    const tab = tabs.get(tabId);
    if (!tab) return;
    tab.userClosed = true;
    try { tab.ws?.close(); } catch { /* noop */ }
    try { await api(`/api/terminal/tabs/${tabId}`, { method: "DELETE" }); } catch { /* noop */ }
    tab.holder.remove();
    tabs.delete(tabId);
    if (activeId === tabId) {
      const next = [...tabs.keys()][0];
      if (next) activate(next);
      else {
        activeId = null;
        renderTabs();
        el("term-workdir").textContent = "";
      }
    } else {
      renderTabs();
    }
  }

  function activeTab() {
    return tabs.get(activeId) || null;
  }

  function renderWorkdir() {
    const hint = el("term-workdir");
    const tab = activeTab();
    if (!tab || tab.preset !== "host") {
      hint.textContent = tab ? `ssh · ${tab.node || "node"}` : "";
      hint.title = "";
      return;
    }
    hint.textContent = `scratch/${tab.id}`;
    hint.title = "Isolated scratch workspace — deleted when tab closes";
  }

  newTabMenu?.querySelectorAll("[data-open-tab]").forEach((button) => {
    button.onclick = () => {
      try { newTabMenu.hidePopover?.(); } catch { /* noop */ }
      const node = button.dataset.node || null;
      openTab(button.dataset.openTab, node, node || "mac");
    };
  });

  el("btn-term-clear").onclick = () => activeTab()?.term.clear();

  let searchMatches = [];
  let searchCursor = -1;
  const searchBar = el("term-search");
  const searchInput = el("term-search-input");
  const searchCount = el("term-search-count");

  function runSearch(query) {
    const tab = activeTab();
    searchMatches = [];
    searchCursor = -1;
    const needle = String(query || "").trim().toLowerCase();
    if (!tab || !needle) {
      if (searchCount) searchCount.textContent = "0/0";
      return;
    }
    const buf = tab.term.buffer.active;
    for (let i = 0; i < buf.length; i += 1) {
      const line = buf.getLine(i)?.translateToString(true) || "";
      if (line.toLowerCase().includes(needle)) searchMatches.push(i);
    }
    if (searchMatches.length) {
      searchCursor = searchMatches.length - 1;
      tab.term.scrollToLine(searchMatches[searchCursor]);
      if (searchCount) searchCount.textContent = `${searchCursor + 1}/${searchMatches.length}`;
    } else if (searchCount) {
      searchCount.textContent = "0/0";
    }
  }

  function stepSearch(delta) {
    const tab = activeTab();
    if (!tab || !searchMatches.length) return;
    searchCursor = (searchCursor + delta + searchMatches.length) % searchMatches.length;
    tab.term.scrollToLine(searchMatches[searchCursor]);
    if (searchCount) searchCount.textContent = `${searchCursor + 1}/${searchMatches.length}`;
  }

  function openSearch() {
    if (!searchBar) return;
    searchBar.hidden = false;
    searchInput?.focus();
    searchInput?.select();
    if (searchInput?.value) runSearch(searchInput.value);
  }

  function closeSearch() {
    if (!searchBar) return;
    searchBar.hidden = true;
    activeTab()?.term.focus();
  }

  function sendCommand(cmd) {
    const tab = activeTab();
    if (!tab || tab.ws?.readyState !== 1) {
      toast("Open an active terminal tab first", "error");
      return;
    }
    tab.ws.send(JSON.stringify({ type: "input", data: `${cmd}\n` }));
    tab.term.focus();
    toast(`Executed in ${tab.label}`, "success", 1600);
  }

  el("btn-term-search")?.addEventListener("click", () => {
    if (searchBar?.hidden) openSearch();
    else closeSearch();
  });
  searchInput?.addEventListener("input", () => runSearch(searchInput.value));
  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      stepSearch(event.shiftKey ? -1 : 1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeSearch();
    }
  });
  el("term-search-prev")?.addEventListener("click", () => stepSearch(-1));
  el("term-search-next")?.addEventListener("click", () => stepSearch(1));
  el("term-search-close")?.addEventListener("click", closeSearch);

  renderTabs();

  return {
    openTab,
    ensureHost: async () => {
      if (tabs.size > 0) return;
      try {
        const { tabs: live } = await api("/api/terminal/tabs");
        const host = live.find((tab) => tab.preset === "host" && (tab.subscribers || 0) === 0);
        if (host) {
          await attachExisting(host, "mac");
          return;
        }
      } catch { /* follow create path */ }
      await openTab("host", null, "mac");
    },
    sendCommand,
    openSearch,
    closeSearch,
    focus: () => activeTab()?.term.focus(),
    clearActive: () => activeTab()?.term.clear(),
    fitActive: () => {
      const tab = activeTab();
      if (tab) requestAnimationFrame(() => fitTab(tab));
    },
    adjustFont,
    resetFont,
    activeTab,
  };
}
