// markdown.js — safe DOM-based prompt renderer (headings, code blocks, numbered steps, copy-pills)
import { copyText } from "./ui.js";
import { iconEl } from "./icons.js";

function makeInlineCopyPill(text, focusAfter) {
  const span = document.createElement("span");
  span.className = "copy-pill";
  span.textContent = text;
  span.title = "Copy to clipboard";
  span.onclick = async () => {
    await copyText(text, span);
    focusAfter?.();
  };
  return span;
}

function appendInline(parent, text, focusAfter) {
  const parts = String(text).split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      parent.appendChild(makeInlineCopyPill(part.slice(1, -1), focusAfter));
    } else if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.appendChild(strong);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

export function renderPrompt(container, rawText, { focusAfter } = {}) {
  container.innerHTML = "";
  const lines = String(rawText || "").replace(/\r/g, "").split("\n");
  let i = 0;

  while (i < lines.length) {
    const raw = lines[i];
    const trimmed = raw.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    // Fenced code / YAML blocks
    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim() || "text";
      const codeLines = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence
      const codeText = codeLines.join("\n");
      const wrap = document.createElement("div");
      wrap.className = "code-block-wrap";
      const top = document.createElement("div");
      top.className = "code-block-top";
      const langLbl = document.createElement("span");
      langLbl.textContent = lang;
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn sm ghost";
      copyBtn.append(iconEl("copy", 13), document.createTextNode("Copy"));
      copyBtn.onclick = () => copyText(codeText, copyBtn);
      top.append(langLbl, copyBtn);
      const pre = document.createElement("pre");
      pre.className = "code-block";
      pre.textContent = codeText;
      wrap.append(top, pre);
      container.appendChild(wrap);
      continue;
    }

    // Headings (### / ## / Perform the following tasks:)
    if (/^#{1,3}\s+/.test(trimmed) || /^perform the following tasks:?$/i.test(trimmed)) {
      const h = document.createElement("h3");
      h.className = "prompt-heading";
      h.textContent = trimmed.replace(/^#{1,3}\s+/, "");
      container.appendChild(h);
      i += 1;
      continue;
    }

    // Numbered ordered steps
    if (/^\d+[.)]\s+/.test(trimmed)) {
      const ol = document.createElement("ol");
      ol.className = "prompt-steps";
      while (i < lines.length) {
        const m = lines[i].trim().match(/^(\d+)[.)]\s+(.+)$/);
        if (!m) break;
        const li = document.createElement("li");
        const num = document.createElement("span");
        num.className = "step-num";
        num.textContent = m[1];
        const body = document.createElement("span");
        appendInline(body, m[2], focusAfter);
        li.append(num, body);
        ol.appendChild(li);
        i += 1;
      }
      container.appendChild(ol);
      continue;
    }

    // Bullet list
    if (/^[-*]\s+/.test(trimmed)) {
      const ul = document.createElement("ul");
      while (i < lines.length) {
        const m = lines[i].trim().match(/^[-*]\s+(.+)$/);
        if (!m) break;
        const li = document.createElement("li");
        appendInline(li, m[1], focusAfter);
        ul.appendChild(li);
        i += 1;
      }
      container.appendChild(ul);
      continue;
    }

    // Regular paragraph (group adjacent non-empty lines that aren't special blocks)
    const paraLines = [];
    while (i < lines.length) {
      const t = lines[i].trim();
      if (
        !t ||
        t.startsWith("```") ||
        /^#{1,3}\s+/.test(t) ||
        /^perform the following tasks:?$/i.test(t) ||
        /^\d+[.)]\s+/.test(t) ||
        /^[-*]\s+/.test(t)
      ) {
        break;
      }
      paraLines.push(t);
      i += 1;
    }
    const p = document.createElement("p");
    appendInline(p, paraLines.join(" "), focusAfter);
    container.appendChild(p);
  }
}
