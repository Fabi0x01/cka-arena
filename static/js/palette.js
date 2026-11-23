// palette.js — Command Palette (⌘K) powered by native <dialog>
import { el, openDialog, closeDialog, wireDialogBackdropDismiss } from "./ui.js";
import { iconEl } from "./icons.js";

export function initPalette({ getActions }) {
  const dialog = el("command-palette");
  const input = el("palette-input");
  const listEl = el("palette-list");
  if (!dialog || !input || !listEl) return { open: () => {}, close: () => {}, toggle: () => {} };

  let filtered = [];
  let cursor = 0;

  wireDialogBackdropDismiss(dialog, () => close());

  function render() {
    const q = input.value.trim().toLowerCase();
    const all = getActions() || [];
    filtered = q
      ? all.filter((a) => `${a.group} ${a.label} ${a.keywords || ""}`.toLowerCase().includes(q))
      : all;
    if (cursor >= filtered.length) cursor = Math.max(0, filtered.length - 1);

    listEl.innerHTML = "";
    if (!filtered.length) {
      const empty = document.createElement("div");
      empty.className = "palette-group";
      empty.textContent = "No matching commands";
      listEl.appendChild(empty);
      return;
    }

    let lastGroup = null;
    filtered.forEach((act, idx) => {
      if (act.group !== lastGroup) {
        const grp = document.createElement("div");
        grp.className = "palette-group";
        grp.textContent = act.group;
        listEl.appendChild(grp);
        lastGroup = act.group;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "palette-item" + (idx === cursor ? " selected" : "");
      const left = document.createElement("span");
      left.className = "palette-item-left";
      left.appendChild(iconEl(act.icon || "command", 15));
      const title = document.createElement("span");
      title.className = "palette-item-title";
      title.textContent = act.label;
      left.appendChild(title);
      btn.appendChild(left);
      if (act.shortcut) {
        const kbd = document.createElement("kbd");
        kbd.textContent = act.shortcut;
        btn.appendChild(kbd);
      }
      btn.onmouseenter = () => {
        cursor = idx;
        updateSelection();
      };
      btn.onclick = () => {
        close();
        act.run();
      };
      listEl.appendChild(btn);
    });
  }

  function updateSelection() {
    listEl.querySelectorAll(".palette-item").forEach((node, idx) => {
      node.classList.toggle("selected", idx === cursor);
    });
  }

  function open() {
    input.value = "";
    cursor = 0;
    render();
    openDialog(dialog);
    requestAnimationFrame(() => input.focus());
  }

  function close() {
    closeDialog(dialog);
  }

  function toggle() {
    if (dialog.open) close();
    else open();
  }

  input.addEventListener("input", () => {
    cursor = 0;
    render();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (filtered.length) {
        cursor = (cursor + 1) % filtered.length;
        updateSelection();
        listEl.querySelector(".palette-item.selected")?.scrollIntoView({ block: "nearest" });
      }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (filtered.length) {
        cursor = (cursor - 1 + filtered.length) % filtered.length;
        updateSelection();
        listEl.querySelector(".palette-item.selected")?.scrollIntoView({ block: "nearest" });
      }
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = filtered[cursor];
      if (item) {
        close();
        item.run();
      }
    }
  });

  return { open, close, toggle };
}
