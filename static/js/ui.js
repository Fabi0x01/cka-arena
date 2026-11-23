// ui.js — native <dialog> top-layer helpers, toast with SVG icons, confirmDialog, clipboard
import { iconEl } from "./icons.js";

export const el = (id) => document.getElementById(id);

let _supportsDisplayTransition;
function canTransitionDisplay() {
  if (_supportsDisplayTransition !== undefined) return _supportsDisplayTransition;
  if (!window.CSS?.supports?.("transition-behavior", "allow-discrete") || !document.body) {
    _supportsDisplayTransition = false;
    return false;
  }
  const probe = document.createElement("div");
  probe.style.cssText = "transition: display 1s allow-discrete !important; display: block;";
  document.body.appendChild(probe);
  getComputedStyle(probe).display;
  probe.style.display = "none";
  _supportsDisplayTransition = getComputedStyle(probe).display === "block";
  probe.remove();
  return _supportsDisplayTransition;
}

function supportsTopLayerExit() {
  return Boolean(window.CSS?.supports?.("overlay", "auto") && canTransitionDisplay());
}

export async function closeDialog(dialog) {
  if (!dialog || !dialog.open) return;
  if (!supportsTopLayerExit()) {
    dialog.setAttribute("data-closing", "");
    const animations = dialog.getAnimations ? dialog.getAnimations({ subtree: true }) : [];
    if (animations.length > 0) {
      await Promise.race([
        Promise.allSettled(animations.map((a) => a.finished)),
        new Promise((resolve) => setTimeout(resolve, 250)),
      ]);
    }
    dialog.removeAttribute("data-closing");
  }
  if (dialog.open) dialog.close();
}

export function openDialog(dialog) {
  if (!dialog) return;
  dialog.removeAttribute("data-closing");
  if (!dialog.open) dialog.showModal();
}

export function wireDialogBackdropDismiss(dialog, onDismiss) {
  if (!dialog || dialog._backdropWired) return;
  dialog._backdropWired = true;
  if (!("closedBy" in HTMLDialogElement.prototype)) {
    const outside = (e) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    dialog.addEventListener("pointerdown", (e) => { pressedOutside = outside(e); });
    dialog.addEventListener("pointerup", (e) => {
      if (pressedOutside && outside(e)) {
        if (onDismiss) onDismiss();
        else closeDialog(dialog);
      }
    });
  }
  dialog.addEventListener("cancel", (e) => {
    e.preventDefault();
    if (onDismiss) onDismiss();
    else closeDialog(dialog);
  });
}

export function toast(message, kind = "info", ms = 3800) {
  const node = el("toast");
  if (!node) return;
  node.innerHTML = "";
  const icoName = kind === "success" ? "checkCircle" : kind === "error" ? "xCircle" : "zap";
  const ico = iconEl(icoName, 16);
  ico.style.color = kind === "success" ? "var(--pass)" : kind === "error" ? "var(--fail)" : "var(--accent)";
  const span = document.createElement("span");
  span.textContent = message;
  node.append(ico, span);
  node.className = `toast show${kind ? ` ${kind}` : ""}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => node.classList.remove("show"), ms);
}

export function confirmDialog(title, text) {
  return new Promise((resolve) => {
    const dialog = el("confirm-modal");
    el("confirm-title").textContent = title;
    el("confirm-text").textContent = text;
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      el("confirm-yes").onclick = null;
      el("confirm-no").onclick = null;
      closeDialog(dialog);
      resolve(value);
    };
    wireDialogBackdropDismiss(dialog, () => finish(false));
    el("confirm-yes").onclick = () => finish(true);
    el("confirm-no").onclick = () => finish(false);
    openDialog(dialog);
  });
}

export async function copyText(text, node) {
  try {
    await navigator.clipboard.writeText(text);
    if (node) {
      node.classList.add("copied");
      setTimeout(() => node.classList.remove("copied"), 700);
    }
    toast(`Copied: ${text}`, "success", 1300);
    return true;
  } catch {
    toast("Clipboard blocked — select and copy manually", "error");
    return false;
  }
}
