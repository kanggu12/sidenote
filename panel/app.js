// The panel's script (served as a file: the Content-Security-Policy allows scripts from the server only).
"use strict";
const $ = (id) => document.getElementById(id);
const MAX_ITEMS = 200;
// The words are in the panel's language (panel/i18n.js, loaded before this file): it is fixed for the page's life.
translateDom();   // the static words of index.html, before anything below reads or draws them
// The message a style sheet writes itself (index.html, .shot.stale), as a CSS string
document.documentElement.style.setProperty("--t-stale", JSON.stringify(t("Old screen")));
const TYPE_LABEL = { mcq: t("MCQ"), short: t("Short"), essay: t("Essay"), coding: t("Coding"), algorithm: t("Algorithm"),
  work: t("Work"), math: t("Math"), diagram: t("Diagram"), other: t("Other"), conceptual: t("Concept"), followup: t("Follow-up") };
// The same kinds by their whole names, where a list has room for them (the contents' type filter); the margin's chip keeps the short ones
const TYPE_NAME = { ...TYPE_LABEL, mcq: t("Multiple choice"), short: t("Short answer") };
const ANSWER_LABEL = { mcq: t("Answer"), short: t("Answer"), math: t("Result"), followup: t("Reply"), coding: t("Approach"), algorithm: t("Approach") };
// Getters where a line names the agent: the box is drawn long after this runs, once the server has said which.
// The desktop app has no ./sidenote and no server's terminal: there a card says what to do in the app, with no command to copy.
const HINT = {
  auth: { get title() { return t("{agent} sign-in needed", { agent: AG() }); },
    get text() { return status.desktop ? t("Not signed in, or the sign-in expired. Open a terminal, type {cmd} and press Enter, then sign in · resumes within 20 seconds", { cmd: `<code class="cmd">${LOGIN()}</code>` })
      : t("Not signed in, or the sign-in expired. Sign in from the server's terminal and it resumes within 20 seconds"); },
    // in the app the command is in the sentence already, the CLI's own name: no chip of its own after it, only its copy key
    get cmd() { return status.desktop ? "" : LOGIN(); }, get copy() { return LOGIN(); } },
  // with the agent resting on its plan's limit, until when: "in a moment" under a band that says two days was wrong
  limit: { title: t("Usage limit"), get text() {
    const until = eng()?.agent?.limit_until, L = eng()?.local;
    if (!until) return t("{redo} in a moment", { redo: REDO_KEY() });
    return t("The agent rests until {when}", { agent: AG(), when: restAt(until) }) + (L && L.ok && (L.on || L.stand_in) ? t(" · the local model solves meanwhile") : "");
  } },
  timeout: { title: t("Stopped: timed out"), get text() { return t("Try again with {redo}", { redo: REDO_KEY() }); } },
  // the desktop app's server is the app itself: it is up again when the app is
  interrupted: { title: t("Stopped: connection lost"), get text() { return status.desktop ? t("{redo} once Sidenote is running again", { redo: REDO_KEY() }) : t("{redo} once the server is up", { redo: REDO_KEY() }); } },
  nosolver: { title: t("No engine to solve"),
    get text() { return status.desktop ? t("Neither the local model nor the agent can be used. Turn one on in Solver settings", { agent: AG() })
      : t("Neither the local model nor the agent can be used. Turn one on in Solver settings, or check the server's terminal", { agent: AG() }); },
    get cmd() { return status.desktop ? "" : "./sidenote doctor"; } },
  // the command as a chip with its copy key, as the other failures give theirs
  "": { title: t("Analysis failed"),
    get text() { return status.desktop ? t("Try again with {redo}", { redo: REDO_KEY() }) : t("Try again with {redo}. If it keeps failing, check the server's terminal", { redo: REDO_KEY() }); },
    get cmd() { return status.desktop ? "" : "./sidenote events --errors"; } },
};

// Quotes too: this is used inside attributes as often as in text, and textContent leaves them alone.
// Without it `data-val="${escapeHtml(JSON.stringify("auto"))}"` closed the attribute on its own quote,
// so three settings (Think before answering, Problems the agent solves, What is sent to the agent) did nothing when clicked.
// (The Korean particle after a word is the translation's own: "{name|이/가}" in panel/i18n/ko.js, panel/i18n.js particle.)
// A text cut into its sentences: after . ! ? and their full-width forms where a space follows, and not after e.g., i.e.,
// etc., vs., cf. or a title such as Dr. or Mr., whose dots end no sentence
function sentences(text) {
  const kept = String(text ?? "").replace(/\b(e\.g|i\.e|etc|vs|cf|Dr|Mr|Mrs|Ms|St|Jr|Sr|Prof|Fig)\./gi, (m) => m.replace(/\./g, "\u2024"));
  return kept.split(/(?<=[.!?\u3002\uFF01\uFF1F])\s+(?=\S)/).map((x) => x.replace(/\u2024/g, ".").trim()).filter(Boolean);
}
// A summary's sentences, for the split under its point: the whole of it when a cut would fall inside a pair that marks
// something, **bold**, `code` or $math$, which a split showed as a stray mark at each end
function summarySentences(text) {
  const parts = sentences(text);
  const odd = (s, re) => (s.match(re) || []).length % 2 === 1;
  return parts.some((p) => odd(p, /\*\*/g) || odd(p.replace(/\*\*/g, ""), /`/g) || odd(p, /(?<!\\)\$/g)) ? [String(text)] : parts;
}
// What was heard, as it was said: three sentences a paragraph, its first lines when it does not fit in them (heardFit, once
// it is laid out) and the whole on a press, kept so for the entry across a redraw (heardOpen); folded, its end alone, where
// the question usually is
const heardOpen = new Set();
function heardHtml(text, id) {
  const parts = sentences(text), paras = [], key = String(id ?? ""), open = heardOpen.has(key);
  for (let i = 0; i < parts.length; i += 3) paras.push(parts.slice(i, i + 3).join(" "));
  // The tail: the last sentence, with the one before it when it is short ("And then what?"); laid out from its end, so a line
  // too narrow for it cuts its start and never the question at its end (index.html, .heard-tail)
  const last = parts.at(-1) || "", tail = last.length < 40 && parts.length > 1 ? parts.slice(-2).join(" ") : last;
  return `<div class="heard-text${open ? " open" : ""}" data-heard-id="${escapeHtml(key)}">${paras.map((p) => `<p>${escapeHtml(p)}</p>`).join("")}</div>`
    + `<button type="button" class="btn sm ghost heard-more" data-heard-more aria-expanded="${open}" hidden>${OPEN_MARK}<span>${open ? t("Fold") : t("Show it all")}</span></button>`
    + `<div class="heard-tail"><span>${escapeHtml(tail)}</span></div>`;
}
// Each text heard cut to its first lines, with the key for the rest, only when it is taller than them as laid out: by its
// length alone a text that fit in four lines on a wide window had a faded last line and a key that changed nothing.
// Measured where it shows; a folded entry is measured when it opens, as it is drawn again then
function heardFit(root = document) {
  for (const box of root.querySelectorAll(".heard-text")) {
    const key = box.nextElementSibling;
    if (!key?.matches("[data-heard-more]") || box.offsetParent === null) continue;
    const open = box.classList.contains("open");
    box.classList.remove("open"); box.classList.add("clamp");
    const over = box.scrollHeight > box.clientHeight + 2;
    box.classList.toggle("clamp", over);
    box.classList.toggle("open", over && open);
    key.hidden = !over;
  }
}
const escapeHtml = (s) => {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
// Weekdays and times in the panel's language. en-GB for English: a 24-hour clock that starts the day at 00, as ko-KR does
const LOCALE = LANG === "ko" ? "ko-KR" : "en-GB";
// One way of writing a date everywhere: 11.02(월) 02:42 AM. A time alone does not say when: answers are kept for days
const fmtDay = (ms) => { const d = new Date(ms); return `${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}(${d.toLocaleDateString(LOCALE, { weekday: "short" })})`; };
const fmtClock = (ms) => { const d = new Date(ms), h = d.getHours(); return `${String(h % 12 || 12).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
const fmtWhen = (ms) => `${fmtDay(ms)} ${fmtClock(ms)}`;
const fmtShort = (ms) => new Date(ms).toLocaleTimeString(LOCALE, { hour12: false, hour: "2-digit", minute: "2-digit" });
function fmtAgo(sec) {
  if (sec < 5) return t("just now");
  if (sec < 60) return t("{n} s ago", { n: Math.floor(sec) });
  if (sec < 3600) return t("{n} min ago", { n: Math.floor(sec / 60) });
  return t("{n} h ago", { n: Math.floor(sec / 3600) });
}

// ---------- markdown (model output is untrusted: it can echo what was on screen) ----------
const canHtml = () => typeof window.marked !== "undefined" && typeof window.DOMPurify !== "undefined";
// Keep $...$ / $$...$$ away from marked (it would eat _ and * inside them), outside code. Inline
// math must hug its dollars and not run into a digit, so prices ("$20 ... $240") stay text.
function protectMath(md) {
  const store = [];
  const parts = md.split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g);
  for (let i = 0; i < parts.length; i += 2) {
    parts[i] = parts[i].replace(/\$\$[\s\S]+?\$\$|\$[^\s$](?:[^$\n]*?[^\s$])?\$(?!\d)/g,
      (m) => { store.push(m); return `@@M${store.length - 1}@@`; });
    // A lone tilde between two words or numbers is a range in Korean ("20~50 items", "ranks 1~4"), but marked reads a
    // pair of them as strikethrough and struck out everything from one range to the next ("open 20~50 of them ...
    // top 1~4" came out crossed through). Escaped, it stays a tilde; a double ~~ still strikes through, and a
    // tilde after a slash (a path or URL: /~user) is left alone.
    parts[i] = parts[i].replace(/(?<=[\p{L}\p{N}%)\]\s])~(?=[\p{L}\p{N}(\[\s])/gu, "\\~");
  }
  return { md: parts.join(""), store };
}
// The math goes back into text nodes only, as <span class="math">, after sanitizing: put back into
// the HTML string, a placeholder that sat in an attribute would let the math's quotes break out.
function restoreMath(root, store) {
  if (!store.length) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), hits = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.includes("@@M")) hits.push(walker.currentNode);
  for (const node of hits) {
    const s = node.nodeValue, frag = document.createDocumentFragment();
    let last = 0;
    // Inside code the dollars are the code's own: protectMath leaves out only ``` blocks and single-backtick code, so
    // a ~~~ block, an indented one or ``code`` had `$HOME`, `"$A$B"` set as math, on screen, in the copy and in what
    // `Run` ran. There the text goes back as it was written.
    const asCode = !!node.parentElement?.closest("code, pre");
    for (const m of s.matchAll(/@@M(\d+)@@/g)) {
      frag.append(s.slice(last, m.index));
      if (asCode) frag.append(store[+m[1]] ?? m[0]);
      else {
        const span = document.createElement("span"); span.className = "math"; span.textContent = store[+m[1]] ?? m[0];
        frag.append(span);
      }
      last = m.index + m[0].length;
    }
    frag.append(s.slice(last)); node.replaceWith(frag);
  }
}
// Beyond stripping scripts: nothing in an answer may load from elsewhere (an <img> echoed from the
// screen would call out to its server), restyle the page, or pose as a control. No ids (they would
// take over the panel's own elements), no data-* (the panel's buttons are found by them), and a
// class only as marked writes it on code blocks, for highlighting.
const PURIFY = { FORBID_TAGS: ["img", "picture", "source", "video", "audio", "svg", "math", "iframe", "object", "embed",
  "style", "link", "meta", "form", "input", "button", "textarea", "select"], FORBID_ATTR: ["style", "srcset", "id", "name"],
  ALLOW_DATA_ATTR: false };
if (typeof window.DOMPurify !== "undefined") {
  window.DOMPurify.addHook("uponSanitizeAttribute", (node, data) => {
    if (data.attrName === "class" && !(node.nodeName === "CODE" && /^language-[\w+#.-]+$/.test(data.attrValue))) data.keepAttr = false;
  });
  window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {   // a link opens beside the panel, never in place of it
    if (node.nodeName === "A" && node.hasAttribute("href")) { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener noreferrer"); }
  });
}
function renderInto(el, md, inline = false) {
  if (el.dataset) delete el.dataset.drawn;   // new words: what was drawn on the old ones (infographics) is gone with them
  if (!canHtml()) { el.classList.add("plain"); el.textContent = md; return; }
  const { md: safe, store } = protectMath(md);
  const html = inline ? window.marked.parseInline(safe) : window.marked.parse(safe);
  el.classList.remove("plain");
  el.innerHTML = window.DOMPurify.sanitize(html, PURIFY);
  restoreMath(el, store);
}
// CommonMark won't close ** when punctuation is inside and a letter follows, so Korean bold
// such as "**virtualization(VM)**" followed by a particle prints its asterisks. The CJK-friendly extension (needs marked 18:
// it overrides the del tokenizer through rules only 18 has) fixes that. Without it the panel
// still works, just with those asterisks.
function loadMarkdownExtensions() {
  if (typeof window.marked === "undefined" || typeof window.markedCjkFriendly !== "function") return;
  try { window.marked.use(window.markedCjkFriendly()); } catch (e) { console.warn("CJK-friendly emphasis not loaded:", e); }
}
// Three dots: the same drawing as the ⋯ button on the bar, for the button that opens an answer's tokens
// and cost (it was the character "⋯", drawn by whatever font has it, beside drawn marks).
const DOTS_MARK = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2"/>'
  + '<circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>';
// Two sheets of paper, one behind the other: the mark for copying that every editor uses.
const COPY_MARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
  + 'stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11.5" height="11.5" rx="2.5"/>'
  + '<path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-7A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15"/></svg>';
// And a tick, for the second and a half after it worked.
const DONE_MARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" '
  + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 12.5l5 5L19.5 7"/></svg>';
// The rest of the marks the buttons in a thread entry wear. They are drawn the same way as the two
// above (one 24x24 box, no fill, 1.8 stroke, round joins), so a row of them reads as one set
// instead of one button with a picture beside three without.
const mark = (d, w = 1.8) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="'
  + w + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
// The dropdown's own chevron, and the tick that marks the choice it is on now.
const COMBO_MARK = '<svg class="combo-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
  + 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9.5l6 6 6-6"/></svg>';
const TICK_MARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
  + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
// A chevron, pointing the way the entry is about to move: down opens it, up folds it away.
const OPEN_MARK = mark('<path d="M5 9l7 7 7-7"/>', 2.1);
const FOLD_MARK = mark('<path d="M5 15l7-7 7 7"/>', 2.1);
// Lines of text with a pen over them: the model writes the problem out as words.
const PTEXT_MARK = mark('<path d="M4 6h11M4 11h8M4 16h6"/><path d="M14.5 17.5l5-5 2 2-5 5-2.3.3z"/>');
// Copying the problem's words: the copy sheets with lines of text on the front one. The answer's head had two keys with the same two sheets,
// told apart only by their tooltips.
const PTEXT_COPY_MARK = mark('<rect x="9" y="9" width="11.5" height="11.5" rx="2.5"/><path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-7A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15"/>'
  + '<path d="M12 13h5.5M12 16.5h3.5"/>');
// A sheet with a line pulled out of it: the one line that is the answer.
const ANSWER_MARK = mark('<rect x="4" y="3.5" width="12" height="17" rx="2.5"/><path d="M8 9.5h4M8 14h5"/>'
  + '<path d="M16.5 12h4M18.5 10l2 2-2 2"/>');
// A light bulb: a hint, the next part of the working (Practice)
const HINT_MARK = mark('<path d="M9.5 18h5M10.5 21h3"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.4 1.1 2.2h5c0-.8.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>');
// A star, for an answer kept past the history's limits: an outline, filled with the highlighter once starred (index.html, [data-star])
const STAR_PATH = '<path d="M12 3.4l2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 16.8l-5.3 2.8 1.1-5.9-4.3-4.1 5.9-.8z"/>';
const STAR_MARK = mark(STAR_PATH);
// The same star, small, before the words of a starred row of the contents; its word is for a screen reader
const STAR_ROW = () => `<svg class="h-star" viewBox="0 0 24 24" stroke-width="2" stroke-linejoin="round" aria-hidden="true">${STAR_PATH}</svg>`
  + `<span class="sr-only">${t("Starred answer")}</span>`;
// The code block's own copy button: the mark changes with the word, so the state is visible from
// across the page and not only to whoever is reading the label.
async function copyCode(from, btn) {
  const ok = await copyText(codeText(from), null);        // the code as written (no line numbers); null: paint here
  copied(btn, ok);                                        // and say so on the button
  return ok;
}
// A bar's copy button after a press (a code block's, a table's): the tick and "Copied", or "Copy failed", then back.
function copied(btn, ok) {
  btn.classList.toggle("done", ok);                       // the colour of a thing that worked
  btn.innerHTML = (ok ? DONE_MARK : COPY_MARK)            // tick when copied, the sheets when not
    + `<span>${ok ? t("Copied") : t("Copy failed")}</span>`;
  clearTimeout(btn._back);                                // a second press restarts the wait
  btn._back = setTimeout(() => {                          // back to how it started, after a moment
    btn.classList.remove("done");
    btn.innerHTML = COPY_MARK + `<span>${t("Copy")}</span>`;
  }, 1500);
}
// A table's cell as one line of text: a formula as the TeX it was written in (its rendered letters lose their
// superscripts, and KaTeX keeps a second copy of them for screen readers), a line break as a space.
function cellText(cell) {
  const c = cell.cloneNode(true);                         // a copy, so the table on the page is left as it is
  c.querySelectorAll(".katex").forEach((k) => {           // a typeset formula: back to what was written
    const tex = k.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
    k.replaceWith(tex != null ? `$${tex}$` : (k.querySelector(".katex-html")?.textContent || k.textContent));
  });
  c.querySelectorAll("br").forEach((b) => b.replaceWith(" "));   // two lines in one cell stay one cell
  return c.textContent.replace(/\s+/g, " ").trim();       // tabs and line ends would split the cell when pasted
}
// Tables are copyable too. A table goes to the clipboard two ways at once: a bare <table> of its cells, which a
// spreadsheet or a document pasted into keeps as rows and columns, and the same rows as tab-separated lines for a
// paste where only text goes (a note, a chat), which a spreadsheet also splits into cells.
async function copyTable(table, btn) {
  const rows = [...table.rows].map((tr) => [...tr.cells].map(cellText));
  const tsv = rows.map((r) => r.join("\t")).join("\n");
  const esc = (v) => v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const head = table.tHead ? table.tHead.rows.length : 0;  // the head's rows stay a head where it is pasted
  const html = "<table>" + rows.map((r, i) => "<tr>" + r.map((v) => (i < head ? `<th>${esc(v)}</th>` : `<td>${esc(v)}</td>`))
    .join("") + "</tr>").join("") + "</table>";
  let ok = false;
  try {
    await navigator.clipboard.write([new ClipboardItem({ "text/plain": new Blob([tsv], { type: "text/plain" }),
                                                         "text/html": new Blob([html], { type: "text/html" }) })]);
    ok = true;
  } catch (_) {
    ok = await copyText(tsv, null);                       // no rich clipboard here: the text alone
  }
  copied(btn, ok);
  return ok;
}
async function copyText(text, btn) {
  let done = false;
  try { await navigator.clipboard.writeText(text); done = true; } catch (_) {
    const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { done = document.execCommand("copy"); } catch (_) {}
    ta.remove();
  }
  if (btn) {
    // How the button looked before it was pressed, taken on the first press only. Taken on every press,
    // a second one inside the wait below took "Copied" and the tick as the look to go back to, and the
    // button kept them for good (the alert's Copy command and the answer's Copy both did).
    if (btn._rest == null) btn._rest = btn.innerHTML;
    // Say it on the button that was pressed. The word is in a span when the button wears a mark,
    // and writing textContent on the button itself would take the mark with it.
    const word = btn.querySelector("span") || btn;
    word.textContent = done ? t("Copied") : t("Copy failed");
    const drawn = btn.querySelector("svg");
    if (drawn && done) drawn.outerHTML = DONE_MARK;     // a tick while it says so
    btn.classList.toggle("done", done);
    clearTimeout(btn._back);                            // a second press restarts the wait
    btn._back = setTimeout(() => {
      btn.innerHTML = btn._rest;                        // the look from before the first press
      btn._rest = null;                                 // the next press takes it afresh
      btn.classList.remove("done");
    }, 1400);
  }
  return done;
}
// Map a code fence's `language-xxx` class to a runner language, or "" if we don't run it. The class
// is read before highlight.js runs: it adds a guessed language to fences that had none.
const RUN_LANG = { python: "python", py: "python", python3: "python",
  c: "c", cpp: "cpp", "c++": "cpp", cc: "cpp", cxx: "cpp", h: "cpp",
  js: "javascript", javascript: "javascript", node: "javascript", mjs: "javascript",
  ts: "typescript", typescript: "typescript", java: "java", kotlin: "kotlin", kt: "kotlin",
  go: "go", golang: "go", bash: "bash", sh: "bash", shell: "bash" };
// What a code block's language is called on its bar: the names people write, not the fence word.
const LANG_LABEL = {
  python: "Python", py: "Python", javascript: "JavaScript", js: "JavaScript", typescript: "TypeScript",
  ts: "TypeScript", java: "Java", kotlin: "Kotlin", cpp: "C++", "c++": "C++", c: "C", csharp: "C#",
  cs: "C#", go: "Go", rust: "Rust", ruby: "Ruby", php: "PHP", swift: "Swift", sql: "SQL",
  bash: "bash", sh: "bash", shell: "bash", zsh: "bash", console: t("Terminal"), json: "JSON", yaml: "YAML",
  yml: "YAML", html: "HTML", css: "CSS", xml: "XML", text: t("Text"), plaintext: t("Text"), diff: "diff",
  chart: t("Chart data"), mermaid: t("Diagram (mermaid)"),
};
const fenceLang = (code) => { const m = /\blanguage-([\w+#.-]+)/.exec(code.className || ""); return m ? m[1].toLowerCase() : ""; };
// A table's own entry for a key, never one inherited from Object: a fence written ```constructor read the
// prototype's constructor and was labelled "function Object() { [native code] }" with a run box.
const own = (table, key) => (key != null && Object.hasOwn(table, key) ? table[key] : undefined);
// Commands to type rather than a program: a shell's fence, or a block with no language whose first line starts with a
// command nobody's program starts with.
const COMMAND_RE = /^\s*(?:\$\s*)?(?:sudo\s+)?(?:kubectl|docker|docker-compose|helm|k3d|git|gh|curl|wget|npm|npx|pnpm|yarn|pip3?|uv|cargo|make|ssh|scp|rsync|ls|cd|cat|grep|sed|awk|systemctl|journalctl|apt|apt-get|brew|terraform|aws|gcloud|az|nvidia-smi|ps|kill|tar|chmod|chown|mkdir|rm|cp|mv|ollama|\.\/[\w.-]+)\s/;
const SHELL_LANGS = new Set(["bash", "sh", "shell", "zsh", "console", "terminal"]);
function isCommand(code, text) {
  const lang = code.dataset.lang ?? "";
  const first = (text || "").split("\n").find((l) => l.trim()) || "";
  return SHELL_LANGS.has(lang) || (!lang && (COMMAND_RE.test(first) || /^\s*\$\s/.test(first)));   // a line that opens with its own prompt says so itself
}
function runnableLang(code) { return own(RUN_LANG, code.dataset.lang ?? fenceLang(code)) || ""; }
// How each language asks for standard input. A solution to a problem nearly always reads its case
// from there, and run with nothing to read it dies on its first line: in Python with a traceback
// ending in EOFError, in C++ with no complaint at all and a zero where the number should be. The
// box for the input is there but folded away, so the person at the PC meets the traceback first and has to
// work out from it that the empty box above was the point. These patterns are read before the run.
const READS_STDIN = {
  python: /\binput\s*\(|\bsys\.stdin\b/,
  c: /\bscanf\s*\(|\bgetchar\s*\(|\bfgets\s*\([^;]*\bstdin\b|\bgets\s*\(/,
  cpp: /\bcin\s*>>|\bgetline\s*\(\s*(std::)?cin\b|\bscanf\s*\(|\bcin\.get/,
  java: /new\s+Scanner\s*\(\s*System\.in|System\.in\b|BufferedReader\s*\(/,
  javascript: /\bprocess\.stdin\b|require\(['"]readline['"]\)|readFileSync\s*\(\s*(0|['"]\/dev\/stdin['"])/,
  typescript: /\bprocess\.stdin\b|require\(['"]readline['"]\)|readFileSync\s*\(\s*(0|['"]\/dev\/stdin['"])/,
  go: /\bos\.Stdin\b|\bfmt\.Scan/,
  rust: /\bstdin\s*\(\s*\)/,
  ruby: /\bSTDIN\b|\bgets\b|\breadlines?\b/,
  php: /\bSTDIN\b|php:\/\/stdin/,
  swift: /\breadLine\s*\(/,
  cs: /\bConsole\.Read/,
  kotlin: /\breadLine\s*\(|\breadln\s*\(|System\.in\b/,
  bash: /(^|\s)read(\s|$)|\/dev\/stdin/m,
};
const readsStdin = (lang, code) => !!READS_STDIN[lang]?.test(code);
// A solution whose runner reads the input box when it holds something and runs the problem's examples when it is
// empty (server/analyzer.py asks for that runner, with a comment naming the I/O examples in Korean): run as it is, the empty box
// is no mistake there. The examples were written into the runner alone, so a value typed into the box changed
// nothing: a run with a value of one's own as input printed nothing.
// The comment is asked for in Korean; an answer written in English may give it in English.
const runsExamples = (lang, code) => readsStdin(lang, code) && /입출력\s*예|\bI\/O examples?\b|on\s+the\s+input\s+if\s+given/i.test(code);
// What the input box asks for: the function's arguments, for such a runner; else the problem's input as written.
const stdinHint = (lang, code) => (runsExamples(lang, code)
  ? t("The function's arguments, one per line, as the I/O examples write them (e.g. \"aabbaccc\", [1, 2, 3] or nums = [1, 2], target = 3). Left empty, it runs the problem's I/O examples")
  : t("Paste an example input (it goes to standard input)"));
// What a program that ran out of input says when it dies. C and C++ say nothing at all, which is
// why the check above happens before the run and this one only tidies up after it.
const ATE_EOF = /EOFError|NoSuchElementException|EndOfStreamException|unexpected end of (input|file)|EOF when reading/i;
const NEED_STDIN = t("Input needed");   // the run box's state line while it is waiting for an example input
// The run bar's own two marks, drawn like the rest: a play triangle, and a line of text going into
// a tray. The triangle used to be the character "▶", which sits on the text baseline and is drawn
// by whatever font happens to own it.
const REDO_MARK = mark('<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v5h-5"/>');
const ROI_MARK = mark('<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>', 1.9);
// A key named in a sentence, with its mark: the keys show only the mark, so the word alone names nothing to look for
const keyHint = (m, word) => `<span class="key-hint">${m}${word}</span>`;
const REDO_KEY = () => keyHint(REDO_MARK, t("Reanalyze"));
const RUN_MARK = mark('<path d="M7 4.5l12 7.5-12 7.5z" fill="currentColor" stroke-linejoin="round"/>', 1.4);
const STDIN_MARK = mark('<path d="M4 4.5h9M4 9h6"/><path d="M12 13.5h8M17 10.5l3 3-3 3"/>'
  + '<path d="M4 19.5h8"/>');
// A question mark inside a speech bubble: one more thing asked about the answer above it.
const ASK_MARK = mark('<path d="M20.5 13.5a7.5 7.5 0 0 1-7.5 7.5H8l-4.5 2.5.9-4.2A7.5 7.5 0 0 1 3 13.5'
  + 'a7.5 7.5 0 0 1 7.5-7.5h2.5a7.5 7.5 0 0 1 7.5 7.5z" transform="translate(0 -2)"/>'
  + '<path d="M9.6 9.3a2.4 2.4 0 1 1 2.9 2.4v1.6"/><path d="M12.5 16.2v.1"/>', 1.6);
// A run box's state lives here, keyed by where its code block is (entry or follow-up, nth runnable
// block), so output, typed input and a pending run survive the entry being drawn again.
function runKey(code) {
  const owner = code.closest("[data-turn]") || code.closest(".entry");
  if (!owner) return null;
  const mine = [...owner.querySelectorAll("pre > code")].filter((c) => (c.closest("[data-turn]") || c.closest(".entry")) === owner && runnableLang(c));
  return `${owner.dataset.turn != null ? "t" + owner.dataset.turn : "e" + owner.dataset.id}:${mine.indexOf(code)}`;
}
const runBox = (key) => document.querySelector(`.runbox[data-key="${CSS.escape(key)}"]`);
// The Run and Input buttons of a run box: in its own bar, the foot of the code block above it (addRunBox).
const runTools = (box) => box.querySelector(":scope > .runbar .runtools");
function paintRun(box, st) {
  const outEl = box.querySelector(".run-out"), stdinEl = box.querySelector(".stdin"), tools = runTools(box);
  const run = tools?.querySelector(".run"), toggle = tools?.querySelector(".stdin-toggle");
  if (run) run.disabled = !!st.pending;
  box.querySelector(".run-stat").textContent = st.pending ? t("Running…") : st.stat || "";
  outEl.hidden = !!st.pending || st.out == null;
  outEl.className = "run-out" + (st.cls ? " " + st.cls : "");
  outEl.textContent = st.out ?? "";
  stdinEl.hidden = !st.stdinOpen;
  if (toggle) toggle.setAttribute("aria-expanded", String(!!st.stdinOpen));
  if (stdinEl.value !== st.stdin) stdinEl.value = st.stdin;
}
function addRunBox(code) {
  const pre = code.parentElement;
  if (!pre || pre.nextElementSibling?.classList?.contains("runbox")) return;   // already added
  const lang = runnableLang(code), key = lang && runKey(code);
  if (!key) return;
  // A shell block outside a coding answer is commands for one's own machine (kubectl, docker, jstat <pid>):
  // run in the sandbox, with no network and none of that machine, it shows nothing, and its bar made a one-line
  // command three times its height.
  const kind = code.closest("[data-kind]")?.dataset.kind;
  if (lang === "bash" && kind !== "algorithm" && kind !== "coding") return;
  // Run and Input belong at the bottom of the code box: they sit in a bar of their own at the foot of the code, over
  // the input and the output they open, which come under it. They had been moved up into the code's head bar beside
  // Copy, because a foot under every block made a one-line shell command three times its height; a shell block
  // outside a coding answer gets no run box at all since (above).
  const box = document.createElement("div");
  box.className = "runbox"; box.dataset.key = key;
  box.innerHTML = `<div class="runbar"><span class="run-stat" aria-live="polite"></span><span class="runtools">`
    + `<button type="button" class="btn sm run" title="${t("Run this code in an isolated runner and see its output")}">${RUN_MARK}<span>${t("Run")}</span></button>`
    + `<button type="button" class="btn sm stdin-toggle" aria-expanded="false" title="${t("Give it standard input (stdin)")}">${STDIN_MARK}<span>${t("Input")}</span></button>`
    + `</span></div>
    <textarea class="stdin" rows="2" aria-label="${t("Standard input")}" placeholder="${escapeHtml(stdinHint(lang, codeText(code)))}" hidden></textarea>
    <pre class="run-out" hidden></pre>`;
  pre.after(box);
  const tools = runTools(box);
  if (!runState.has(key)) runState.set(key, { stdin: "", stdinOpen: false, cls: "", out: null, stat: "", pending: null });
  const st = runState.get(key), stdinEl = box.querySelector(".stdin");
  stdinEl.oninput = () => { st.stdin = stdinEl.value; };
  tools.querySelector(".stdin-toggle").onclick = () => { st.stdinOpen = !st.stdinOpen; paintRun(box, st); if (st.stdinOpen) stdinEl.focus(); };
  tools.querySelector(".run").onclick = () => {
    // Nothing to read and code that reads: open the box, say what it needs, and stop here. A second
    // press runs it anyway, for the time it was meant to run with no input.
    if (!st.stdin.trim() && st.stat !== NEED_STDIN && readsStdin(lang, codeText(code)) && !runsExamples(lang, codeText(code))) {
      Object.assign(st, { stdinOpen: true, cls: "warn", stat: NEED_STDIN, pending: null,
                          out: t("This code reads input: put an example input in the box below and run it again\nTo run it with no input, press Run once more") });
      paintRun(box, st);
      box.querySelector(".stdin").focus();
      return;
    }
    const runId = `${PAGE_ID}-${++runSeq}`;   // unique per page: another panel or a reload never takes this result
    // What was typed goes with it whether the box is open or folded away: the toggle shows the box,
    // it does not throw the text out.
    if (!send({ type: "run", id: runId, lang, code: codeText(code), stdin: st.stdin })) {
      Object.assign(st, { pending: null, cls: "err", out: t("No connection to the server"), stat: "" });
    } else { st.pending = runId; runOwners.set(runId, key); }
    paintRun(box, st);
  };
  paintRun(box, st);
}
function failPendingRuns(text) {   // the connection dropped: those results will never come
  for (const [rid, key] of runOwners) {
    const st = runState.get(key);
    if (st && st.pending === rid) { Object.assign(st, { pending: null, cls: "err", out: text, stat: "" }); const b = runBox(key); if (b) paintRun(b, st); }
  }
  runOwners.clear();
}

// ---------- pictures in an answer: ```chart (drawn here as SVG) and ```mermaid (drawn by mermaid) ----------
// The models are asked (server/analyzer.py, SYSTEM_PROMPT) for a ```chart block, a JSON spec, when numbers
// are compared or change, and for a ```mermaid block when a flow, an exchange or a structure is shown. What
// they write is untrusted like the rest of the answer (it can echo the screen): a chart is drawn by this
// code from the numbers and the words of its spec, every word set as text and never as markup, and a
// diagram is drawn by mermaid and shown as an <img>, where nothing in it can run, restyle the panel or
// load anything. A spec or a diagram that cannot be drawn stays the code block it came as, with a line
// saying why, so nothing the model wrote is lost.
// How the marks look follows the data-viz method the chart tokens in index.html come from: bars at most
// 24px thick with the value end rounded and the baseline end square, a 2px gap of the sheet between
// touching marks, 2px lines, end dots ringed in the sheet colour, hairline grid, words in text colours
// (never the series colour), a legend from two series up, and the numbers in a table under every chart.
const SVG_NS = "http://www.w3.org/2000/svg";
// The names a model may give a kind of chart, onto the four this file draws.
const CHART_ALIAS = { bar: "bar", bars: "bar", column: "bar", columns: "bar", hbar: "bar", barh: "bar",
  line: "line", lines: "line", area: "line", stack: "stack", stacked: "stack", stackedbar: "stack",
  gantt: "gantt", timeline: "gantt", schedule: "gantt" };
// How much one chart may hold: past these a chart stops being read and the numbers belong in a table.
const CHART_CAP = { x: 40, points: 400, series: 8, tasks: 80 };
// The words inside a chart are cut to these lengths (in characters); the table under it has them whole.
const CHART_TEXT = { title: 90, unit: 12, label: 60, name: 40, task: 24 };
// Numbers as Korean readers write them: 1,234.5, and from ten thousand up on an axis, 1.2 with the sign for 10,000.
const fmtFull = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });
const fmtCompact = new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 });

// One SVG element with its attributes, appended to a parent when one is given.
function svgEl(tag, attrs, parent) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== undefined && v !== null) el.setAttribute(k, String(v));
  if (parent) parent.appendChild(el);
  return el;
}
// A piece of text in the chart: always textContent, so a label can never become markup.
function svgText(parent, x, y, text, attrs) {
  const t = svgEl("text", { x, y, ...attrs }, parent);
  t.textContent = text;
  return t;
}
// What a mark says on hover: the browser's own tooltip, read by screen readers too.
function svgTip(el, text) { svgEl("title", {}, el).textContent = text; }

// A number from the spec: a JSON number, or a string that is plainly one ("1,200", "3.5"). Anything else
// is NaN, and the spec is turned down rather than drawn with a guess.
function specNumber(v) {
  if (typeof v === "number") return Number.isFinite(v) ? v : NaN;
  if (typeof v === "string" && /^\s*[-+]?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?\s*$/.test(v) && /\d/.test(v)) return Number(v.replace(/[,\s]/g, ""));
  return NaN;
}
// A word from the spec, trimmed and cut to a length; a missing one is "".
const specWord = (v, n) => (v === undefined || v === null ? "" : String(v)).trim().slice(0, n);

// Read a ```chart block into a spec this file can draw: { spec } or { error } (what was wrong, in the panel's language,
// for the line shown over the code block when it cannot be drawn).
function chartSpec(src) {
  let raw;
  try { raw = JSON.parse(src); }
  catch (_) {
    // A comma before a closing bracket is the slip models make most; past that the block is not JSON.
    try { raw = JSON.parse(src.replace(/,\s*([}\]])/g, "$1")); }
    catch (e) { return { error: t("Chart data error: not JSON") }; }
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { error: t("Chart data error: not an object") };
  const asked = specWord(raw.type, 20).toLowerCase().replace(/[\s_-]/g, "");
  const type = CHART_ALIAS[asked];
  if (!type) return { error: t("Unknown chart type: {type}", { type: asked || t("none") }) };
  const spec = { type, title: specWord(raw.title, CHART_TEXT.title), unit: specWord(raw.unit, CHART_TEXT.unit),
                 // bars across instead of up when asked; long labels turn them across anyway (drawBars)
                 across: asked === "hbar" || asked === "barh" || raw.horizontal === true };
  if (type === "gantt") {                                        // a timetable: named spans on a time axis
    const tasks = Array.isArray(raw.tasks) ? raw.tasks : null;
    if (!tasks || !tasks.length) return { error: t("No timetable rows (tasks)") };
    if (tasks.length > CHART_CAP.tasks) return { error: t("Too many timetable rows ({n})", { n: tasks.length }) };
    spec.tasks = [];
    for (const task of tasks) {
      const start = specNumber(task?.start), end = specNumber(task?.end);
      // a span with no start, no end, or its end before its start says nothing true about the schedule
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
        return { error: t("A timetable row's start or end is wrong") };
      }
      spec.tasks.push({ name: specWord(task.name, CHART_TEXT.task) || "?", start, end, row: specWord(task.row, CHART_TEXT.task) });
    }
    return { spec };
  }
  // bar, line and stack: categories along x and one or more series of numbers over them
  const x = Array.isArray(raw.x) ? raw.x : Array.isArray(raw.labels) ? raw.labels : null;
  let series = Array.isArray(raw.series) ? raw.series : raw.series && typeof raw.series === "object" ? [raw.series] : null;
  if (!series && Array.isArray(raw.values)) series = [{ name: raw.name ?? "", values: raw.values }];   // one series, written flat
  if (!x || !x.length) return { error: t("No items on the x-axis (x)") };
  if (!series || !series.length) return { error: t("No values (series)") };
  if (x.length > (type === "line" ? CHART_CAP.points : CHART_CAP.x)) return { error: t("Too many items ({n})", { n: x.length }) };
  if (series.length > CHART_CAP.series) return { error: t("Too many series ({n})", { n: series.length }) };
  spec.x = x.map((v) => specWord(v, CHART_TEXT.label));
  spec.series = [];
  for (const sr of series) {
    const vals = Array.isArray(sr?.values) ? sr.values : Array.isArray(sr?.data) ? sr.data : null;
    // a value count that does not match the categories would put numbers under the wrong names
    if (!vals || vals.length !== x.length) {
      return { error: t("The number of values ({values}) differs from the number of items ({items})", { values: vals ? vals.length : 0, items: x.length }) };
    }
    const values = vals.map((v) => (v === null || v === "" ? null : specNumber(v)));   // null: no value there
    if (values.some((v) => v !== null && !Number.isFinite(v))) return { error: t("A value is not a number") };
    if (type === "stack" && values.some((v) => v !== null && v < 0)) return { error: t("A stacked bar has a negative value") };
    spec.series.push({ name: specWord(sr.name, CHART_TEXT.name), values });
  }
  if (spec.series.every((s) => s.values.every((v) => v === null))) return { error: t("No values to draw") };
  // The one bar the answer is about (by its label or its place): that bar in colour, the rest grey.
  if (raw.highlight !== undefined && raw.highlight !== null && type === "bar" && spec.series.length === 1) {
    const h = typeof raw.highlight === "number" ? raw.highlight : spec.x.indexOf(specWord(raw.highlight, CHART_TEXT.label));
    if (Number.isInteger(h) && h >= 0 && h < spec.x.length) spec.highlight = h;
  }
  return { spec };
}

// A value as it is written beside a mark and in the table: grouped digits, and the unit. A unit that is
// a word in Latin letters (ms, MB) stands apart; %, Korean counters (times, items, fold) and signs follow the number.
function fmtValue(v, unit) {
  if (v === null || v === undefined) return "-";
  if (!unit) return fmtFull.format(v);
  return fmtFull.format(v) + (/^[A-Za-zμµ]/.test(unit) ? " " : "") + unit;
}
// An axis tick: compact from ten thousand up (1.2 and the sign for 10,000), so the tick labels stay short.
const fmtTick = (v, top) => (Math.abs(top) >= 10000 ? fmtCompact.format(v) : fmtFull.format(v));

// Ticks at round steps (1, 2, 2.5 or 5 times a power of ten) covering lo..hi, about `count` of them.
function niceTicks(lo, hi, count = 4) {
  if (lo === hi) { if (lo === 0) hi = 1; else if (lo > 0) lo = 0; else hi = 0; }   // one value: from zero to it
  const raw = (hi - lo) / count, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  const step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
  const first = Math.floor(lo / step + 1e-9) * step, last = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let i = 0, t = first; t <= last + step / 2 && i < 50; i++, t = first + i * step) ticks.push(Math.abs(t) < step * 1e-9 ? 0 : +t.toFixed(10));
  return ticks;
}

// How wide a piece of text will be in the chart, in px, measured in the page's own font.
let measureCtx = null;
function textWidth(s, px = 12, weight = 400) {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  measureCtx.font = `${weight} ${px}px ${getComputedStyle(document.body).fontFamily}`;
  return measureCtx.measureText(s).width;
}
// The text, or as much of it as fits in `max` px with an ellipsis; the whole of it is in the tooltip and the table.
function clipText(s, max, px = 12, weight = 400) {
  if (textWidth(s, px, weight) <= max) return s;
  let t = s;
  while (t.length > 1 && textWidth(t + "…", px, weight) > max) t = t.slice(0, -1);
  return t.length > 1 ? t + "…" : "";
}

// A bar standing on its baseline: the end at the value rounded by 4px, the end on the baseline square.
// Up the page (a column) when `across` is false, along it (a bar) when true. Empty for a bar too short to see.
function barPath(across, base, end, at, thick) {
  const len = Math.abs(end - base), r = Math.min(thick >= 28 ? 6 : 4, thick / 2, len);
  if (len < 0.5) return "";
  if (!across) {                                  // a column: x = at, from y = base to y = end
    const x = at, w = thick, d = end < base ? 1 : -1;   // d: which way the value end lies (1: up the page)
    return `M${x},${base}V${end + d * r}Q${x},${end} ${x + r},${end}H${x + w - r}Q${x + w},${end} ${x + w},${end + d * r}V${base}Z`;
  }
  const y = at, h = thick, d = end > base ? -1 : 1;     // a bar: y = at, from x = base to x = end
  return `M${base},${y}H${end + d * r}Q${end},${y} ${end},${y + r}V${y + h - r}Q${end},${y + h} ${end + d * r},${y + h}H${base}Z`;
}

// The legend: a swatch (or a short line for a line chart) and the name, in text colours, for two series up.
function legendEl(keys) {
  const box = document.createElement("div");
  box.className = "viz-legend";
  for (const k of keys) {
    const item = document.createElement("span"), sw = document.createElement("i"), name = document.createElement("span");
    item.className = "key";
    sw.className = `sw ${k.cls}${k.line ? " ln" : ""}`;   // the colour comes from the slot's class (index.html)
    name.textContent = k.name;
    item.append(sw, name);
    box.append(item);
  }
  return box;
}

// The chart's numbers as a table, folded under it: every value can be read and copied without the
// colours, which three light series colours need (they are under 3:1 on white).
function tableView(spec) {
  const more = document.createElement("details"), sum = document.createElement("summary");
  more.className = "viz-more";
  sum.textContent = t("View as a table");
  const wrap = document.createElement("div"), table = document.createElement("table");
  wrap.className = "tablewrap";
  const head = table.createTHead().insertRow(), body = table.createTBody();
  const th = (text, num) => { const c = document.createElement("th"); c.textContent = text; if (num) c.className = "num"; head.append(c); };
  const td = (row, text, num) => { const c = row.insertCell(); c.textContent = text; if (num) c.className = "num"; };
  if (spec.type === "gantt") {
    const rows = new Set(spec.tasks.map((t) => t.row)).size > 1;   // a row column only when there are rows
    th(t("Name")); if (rows) th(t("Row")); th(t("Start"), true); th(t("End"), true); th(t("Length"), true);
    for (const t of spec.tasks) {
      const r = body.insertRow();
      td(r, t.name); if (rows) td(r, t.row);
      td(r, fmtValue(t.start, spec.unit), true); td(r, fmtValue(t.end, spec.unit), true); td(r, fmtValue(t.end - t.start, spec.unit), true);
    }
  } else {
    th(t("Item"));
    spec.series.forEach((s) => th(s.name || t("Value"), true));
    if (spec.type === "stack") th(t("Total"), true);
    spec.x.forEach((x, i) => {
      const r = body.insertRow();
      td(r, x);
      spec.series.forEach((s) => td(r, fmtValue(s.values[i], spec.unit), true));
      if (spec.type === "stack") td(r, fmtValue(spec.series.reduce((a, s) => a + (s.values[i] || 0), 0), spec.unit), true);
    });
  }
  wrap.append(table);
  more.append(sum, wrap);
  return more;
}

// Bars, up the page or along it, one series or a group of them side by side, or stacked (type "stack").
function drawBars(spec, W) {
  const stack = spec.type === "stack", n = spec.x.length, m = spec.series.length;
  const totals = spec.x.map((_, i) => spec.series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const vals = spec.series.flatMap((s) => s.values).filter((v) => v !== null);
  const ticks = niceTicks(Math.min(0, ...(stack ? [0] : vals)), Math.max(0, ...(stack ? totals : vals)), 4);
  const lo = ticks[0], hi = ticks[ticks.length - 1], top = Math.max(Math.abs(lo), Math.abs(hi));
  const one = m === 1 && !stack;                               // a single series: one colour, labels at the ends
  const labelW = Math.max(...spec.x.map((s) => textWidth(s, 12)));
  const tickW = Math.max(...ticks.map((t) => textWidth(fmtTick(t, top), 12)));
  // Up the page while every category's name fits under its own column; along it when one does not, as a
  // name can then be read whole on the left instead of cut or turned on its side.
  const across = spec.across || labelW > (W - tickW - 16) / n - 8;
  const svg = svgEl("svg", { xmlns: SVG_NS, "data-across": across ? "1" : "0" });
  const color = (j, i) => (one && spec.highlight !== undefined ? (i === spec.highlight ? "s1" : "dim") : `s${j + 1}`);
  const label = (v) => fmtValue(v, spec.unit);
  // which values get their number written at the bar: all of a few bars, else the highlighted or largest one
  const shown = (i, v) => one && v !== null && (n <= 8 || i === spec.highlight || v === Math.max(...vals));
  // A negative bar's number is written past its end, below the zero line: room for it under the plot (up the
  // page) or left of the zero line (along it), so it never lands on the category names.
  const below = one && vals.some((v) => v < 0);
  if (!across) {
    const padL = tickW + 10, padR = 6, padT = 22, plotH = 200, padB = 26 + (below ? 16 : 0), H = padT + plotH + padB;
    const y = (v) => padT + ((hi - v) / (hi - lo || 1)) * plotH;
    const band = (W - padL - padR) / n;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    if (spec.unit) svgText(svg, 0, 12, t("Unit: {unit}", { unit: spec.unit }), { class: "unit" });
    for (const t of ticks) {                                   // hairline grid, the zero line as the axis
      svgEl("line", { x1: padL, x2: W - padR, y1: y(t), y2: y(t), class: t === 0 ? "axis" : "grid" }, svg);
      svgText(svg, padL - 8, y(t) + 4, fmtTick(t, top), { "text-anchor": "end" });
    }
    const gap = 2, groups = stack ? 1 : m;                     // the 2px of sheet between touching bars
    // up to 40 px a bar: at 24 three bars stood thin in a wide empty field
    const thick = Math.max(3, Math.min(40, (band * 0.62 - gap * (groups - 1)) / groups));
    spec.x.forEach((name, i) => {
      const left = padL + i * band + (band - (thick * groups + gap * (groups - 1))) / 2;
      let cum = 0;
      spec.series.forEach((s, j) => {
        const v = s.values[i];
        if (v === null) return;
        let d;
        if (stack) {                                           // each segment on the one below, 2px of sheet between
          const last = spec.series.slice(j + 1).every((r) => !r.values[i]);
          const base = y(cum) - (cum > 0 ? gap : 0), end = y(cum + v);
          d = last ? barPath(false, base, end, left, thick) : `M${left},${base}V${end}H${left + thick}V${base}Z`;
          cum += v;
          if (end >= base) return;                             // too thin to show once the gap is taken
        } else {
          d = barPath(false, y(0), y(v), left + j * (thick + gap), thick);
        }
        if (!d) return;
        const bar = svgEl("path", { d, class: `mark ${color(j, i)}` }, svg);
        svgTip(bar, `${name}${s.name ? ` · ${s.name}` : ""}: ${label(v)}`);
        if (shown(i, v)) {                                     // the number at the bar's end, above it (below a negative)
          const tx = left + j * (thick + gap) + thick / 2, ty = v >= 0 ? y(v) - 6 : y(v) + 15;
          if (textWidth(label(v), 12, 600) <= band - 2) svgText(svg, tx, ty, label(v), { class: "val", "text-anchor": "middle" });
        }
      });
      if (stack && n <= 12 && textWidth(label(totals[i]), 12, 600) <= band - 2) {   // a stack's total over it
        svgText(svg, left + thick / 2, y(totals[i]) - 6, label(totals[i]), { class: "val", "text-anchor": "middle" });
      }
      svgText(svg, padL + i * band + band / 2, padT + plotH + (below ? 16 : 0) + 18, clipText(name, band - 4), { "text-anchor": "middle" });
    });
    return { svg, keys: m > 1 ? spec.series.map((s, j) => ({ name: s.name || t("Series {n}", { n: j + 1 }), cls: `s${j + 1}` })) : [] };
  }
  // Along the page: names on the left, bars from the zero line, the number at each bar's end.
  const nameW = Math.min(Math.ceil(labelW) + 12, Math.floor(W * 0.4));
  const valW = one || stack ? Math.max(...(stack ? totals : vals).map((v) => textWidth(label(v), 12, 600))) + 10 : 6;
  const padT = spec.unit ? 20 : 4, padB = 22, gap = 2;
  const thick = one || stack ? 16 : Math.max(6, Math.min(12, 22 / m));
  const rowH = (stack ? thick : thick * m + gap * (m - 1)) + 14;
  const negW = below ? Math.max(...vals.filter((v) => v < 0).map((v) => textWidth(label(v), 12, 600))) + 10 : 0;
  const H = padT + n * rowH + padB, left = nameW + negW, right = W - valW;
  const x = (v) => left + ((v - lo) / (hi - lo || 1)) * (right - left);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  if (spec.unit) svgText(svg, 0, 12, t("Unit: {unit}", { unit: spec.unit }), { class: "unit" });
  let tickEnd = -Infinity;
  for (const t of ticks) {                                     // vertical hairlines, the zero line as the axis
    svgEl("line", { x1: x(t), x2: x(t), y1: padT, y2: padT + n * rowH, class: t === 0 ? "axis" : "grid" }, svg);
    // a label only where it fits beside the one before: at 360 px they ran together ("0 5천1만.5만")
    const label = fmtTick(t, top), half = label.length * 4;
    if (x(t) - half >= tickEnd) { svgText(svg, x(t), H - 6, label, { "text-anchor": "middle" }); tickEnd = x(t) + half + 4; }
  }
  spec.x.forEach((name, i) => {
    const rowTop = padT + i * rowH + 7;
    svgText(svg, 0, rowTop + (rowH - 14) / 2 + 4, clipText(name, nameW - 10));
    let cum = 0;
    spec.series.forEach((s, j) => {
      const v = s.values[i];
      if (v === null) return;
      let d;
      if (stack) {
        const last = spec.series.slice(j + 1).every((r) => !r.values[i]);
        const base = x(cum) + (cum > 0 ? gap : 0), end = x(cum + v);
        d = last ? barPath(true, base, end, rowTop, thick) : `M${base},${rowTop}H${end}V${rowTop + thick}H${base}Z`;
        cum += v;
        if (end <= base) return;
      } else {
        d = barPath(true, x(0), x(v), rowTop + j * (thick + gap), thick);
      }
      if (!d) return;
      const bar = svgEl("path", { d, class: `mark ${color(j, i)}` }, svg);
      svgTip(bar, `${name}${s.name ? ` · ${s.name}` : ""}: ${label(v)}`);
      if (one) svgText(svg, (v >= 0 ? x(v) + 6 : x(v) - 6), rowTop + thick / 2 + 4, label(v), { class: "val", "text-anchor": v >= 0 ? "start" : "end" });
    });
    if (stack) svgText(svg, x(totals[i]) + 6, rowTop + thick / 2 + 4, label(totals[i]), { class: "val" });
  });
  return { svg, keys: m > 1 ? spec.series.map((s, j) => ({ name: s.name || t("Series {n}", { n: j + 1 }), cls: `s${j + 1}` })) : [] };
}

// Lines over the categories (or over numbers on x, spaced as numbers are), each ending in a ringed dot.
function drawLines(spec, W) {
  const n = spec.x.length, m = spec.series.length;
  const vals = spec.series.flatMap((s) => s.values).filter((v) => v !== null);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (lo >= 0 && lo <= hi * 0.5) lo = 0;                       // near zero anyway: from zero, so heights compare
  const ticks = niceTicks(lo, hi, 4), t0 = ticks[0], t1 = ticks[ticks.length - 1];
  const top = Math.max(Math.abs(t0), Math.abs(t1)), label = (v) => fmtValue(v, spec.unit);
  // Numbers along x, rising and about evenly apart (seconds, years): spaced by their values. Numbers that
  // grow by tens (n = 10, 100, 1000 in a complexity chart) are spaced evenly instead, as steps: spaced by
  // value, the first three sat in the first hundredth of the axis on top of each other.
  const xs = spec.x.map((v) => specNumber(v)), gaps = xs.slice(1).map((v, i) => v - xs[i]);
  const numeric = n > 2 && xs.every(Number.isFinite) && gaps.every((g) => g > 0) && Math.max(...gaps) <= 3 * Math.min(...gaps);
  const ends = spec.series.map((s) => { for (let i = n - 1; i >= 0; i--) if (s.values[i] !== null) return i; return -1; });
  // the end of each line is labelled (name and value) when there are few lines; past four, the legend
  const endText = spec.series.map((s, j) => (ends[j] < 0 ? "" : (m > 1 ? `${s.name || t("Series {n}", { n: j + 1 })} ` : "") + label(s.values[ends[j]])));
  const tickW = Math.max(...ticks.map((t) => textWidth(fmtTick(t, top), 12)));
  const padL = tickW + 10, padT = 22, plotH = 200, padB = 26, H = padT + plotH + padB;
  const y = (v) => padT + ((t1 - v) / (t1 - t0 || 1)) * plotH;
  // End labels only when they stand clear of each other (15px apart): nudged apart they would leave their
  // lines, so past that, or past four lines, the legend names them instead and no margin is kept for them.
  const endY = spec.series.map((s, j) => (ends[j] < 0 ? null : y(s.values[ends[j]]))).filter((v) => v !== null).sort((a, b) => a - b);
  const clear = m <= 4 && endY.every((v, k) => k === 0 || v - endY[k - 1] >= 15);
  const padR = clear ? Math.min(Math.max(...endText.map((t) => textWidth(t, 12, 600))) + 14, W * 0.35) : 10;
  const x = (i) => padL + (n === 1 ? (W - padL - padR) / 2
    : numeric ? ((xs[i] - xs[0]) / (xs[n - 1] - xs[0])) * (W - padL - padR) : (i / (n - 1)) * (W - padL - padR));
  const svg = svgEl("svg", { xmlns: SVG_NS, viewBox: `0 0 ${W} ${H}` });
  if (spec.unit) svgText(svg, 0, 12, t("Unit: {unit}", { unit: spec.unit }), { class: "unit" });
  for (const t of ticks) {
    svgEl("line", { x1: padL, x2: W - padR, y1: y(t), y2: y(t), class: t === t0 ? "axis" : "grid" }, svg);
    svgText(svg, padL - 8, y(t) + 4, fmtTick(t, top), { "text-anchor": "end" });
  }
  // x labels: from the left, each one that stands clear of the one before it (6px), and the last one always
  // (dropping the one before it if they would touch), so no two are ever drawn over each other.
  const room = Math.max(40, (W - padL - padR) / Math.min(n, 8));
  const placed = [];
  spec.x.forEach((name, i) => {
    const text = clipText(name, room - 6), w = textWidth(text, 12), at = x(i);
    const box = { i, text, at, l: at - w / 2, r: at + w / 2 };
    while (i === n - 1 && placed.length && placed[placed.length - 1].r + 6 > box.l) placed.pop();
    if (!placed.length || placed[placed.length - 1].r + 6 <= box.l) placed.push(box);
  });
  for (const b of placed) svgText(svg, b.at, padT + plotH + 18, b.text, { "text-anchor": "middle", class: "xl" });
  if (m === 1 && t0 === 0) {                                   // one line from zero: a light wash under it
    const pts = spec.series[0].values.map((v, i) => (v === null ? null : [x(i), y(v)])).filter(Boolean);
    if (pts.length > 1) {
      svgEl("path", { d: `M${pts[0][0]},${y(0)}` + pts.map(([a, b]) => `L${a},${b}`).join("") + `L${pts[pts.length - 1][0]},${y(0)}Z`,
                      class: "wash s1" }, svg);
    }
  }
  const dots = [];
  spec.series.forEach((s, j) => {
    let d = "", pen = false;
    s.values.forEach((v, i) => {                               // a null breaks the line instead of joining over it
      if (v === null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i)},${y(v)}`;
      pen = true;
    });
    if (d) svgEl("path", { d, class: `line s${j + 1}` }, svg);
    s.values.forEach((v, i) => {                               // a target bigger than the dot for each point's tooltip
      if (v === null) return;
      const hit = svgEl("circle", { cx: x(i), cy: y(v), r: 9, class: "hit" }, svg);
      svgTip(hit, `${spec.x[i]}${s.name ? ` · ${s.name}` : ""}: ${label(v)}`);
    });
    if (ends[j] >= 0) dots.push({ j, cx: x(ends[j]), cy: y(s.values[ends[j]]) });
  });
  for (const d of dots) svgEl("circle", { cx: d.cx, cy: d.cy, r: 4, class: `dot s${d.j + 1}` }, svg);
  if (clear) for (const d of dots) svgText(svg, d.cx + 8, d.cy + 4, clipText(endText[d.j], padR - 10, 12, 600), { class: "val" });
  return { svg, keys: m > 1 ? spec.series.map((s, j) => ({ name: s.name || t("Series {n}", { n: j + 1 }), cls: `s${j + 1}`, line: true })) : [] };
}

// A timetable: each span a block on its row, coloured by its name (a CPU schedule: the same process in the
// same colour every time it runs), with the time of every boundary under the axis when they fit.
function drawGantt(spec, W) {
  const rows = [...new Set(spec.tasks.map((t) => t.row))], named = rows.length > 1 || rows[0] !== "";
  const names = [...new Set(spec.tasks.map((t) => t.name))];
  const slot = (name) => { const k = names.indexOf(name); return k < 8 ? `s${k + 1}` : "dim"; };   // never cycled
  const t0 = Math.min(...spec.tasks.map((t) => t.start)), t1 = Math.max(...spec.tasks.map((t) => t.end));
  const nameW = named ? Math.min(Math.ceil(Math.max(...rows.map((r) => textWidth(r, 12)))) + 12, Math.floor(W * 0.3)) : 0;
  const padR = 12, padT = spec.unit ? 20 : 4, barH = 26, rowGap = 10;
  const H = padT + rows.length * (barH + rowGap) - rowGap + 30;
  const x = (v) => nameW + ((v - t0) / (t1 - t0 || 1)) * (W - nameW - padR);
  const svg = svgEl("svg", { xmlns: SVG_NS, viewBox: `0 0 ${W} ${H}` });
  if (spec.unit) svgText(svg, 0, 12, t("Unit: {unit}", { unit: spec.unit }), { class: "unit" });
  const axisY = padT + rows.length * (barH + rowGap) - rowGap + 6;
  svgEl("line", { x1: nameW, x2: W - padR, y1: axisY, y2: axisY, class: "axis" }, svg);
  let inside = true;                                           // whether every name could be written in its block
  rows.forEach((r, k) => {
    const top = padT + k * (barH + rowGap);
    if (named) svgText(svg, 0, top + barH / 2 + 4, clipText(r, nameW - 10));
    for (const t of spec.tasks.filter((u) => u.row === r)) {
      const a = x(t.start) + 1, w = x(t.end) - x(t.start) - 2;   // 1px off each side: 2px of sheet between neighbours
      if (w < 1) { inside = false; continue; }
      const block = svgEl("rect", { x: a, y: top, width: w, height: barH, rx: Math.min(4, w / 2), class: `mark ${slot(t.name)}` }, svg);
      svgTip(block, `${t.name}: ${fmtValue(t.start, spec.unit)} ~ ${fmtValue(t.end, spec.unit)} (${fmtValue(t.end - t.start, spec.unit)})`);
      if (slot(t.name) !== "dim" && textWidth(t.name, 12, 650) + 8 <= w) {   // the name in the block when it fits, else the legend has it
        // black or white by the block's own colour (index.html, --in-1 to --in-8), whichever reads on it
        svgText(svg, a + w / 2, top + barH / 2 + 4, t.name, { class: `in i${slot(t.name).slice(1)}`, "text-anchor": "middle" });
      } else inside = false;
    }
  });
  // every boundary's time under the axis, skipping one that would touch the one before it
  const marks = [...new Set(spec.tasks.flatMap((t) => [t.start, t.end]))].sort((a, b) => a - b);
  const at = marks.length <= 30 ? marks : niceTicks(t0, t1, 6).filter((v) => v >= t0 && v <= t1);
  let lastRight = -Infinity;
  for (const v of at) {
    const px = x(v), text = fmtFull.format(v), w = textWidth(text, 12);
    svgEl("line", { x1: px, x2: px, y1: axisY, y2: axisY + 4, class: "axis" }, svg);
    if (px - w / 2 < lastRight + 4) continue;
    svgText(svg, px, axisY + 17, text, { "text-anchor": "middle" });
    lastRight = px + w / 2;
  }
  return { svg, keys: !inside || names.length > 8 ? names.map((nm) => ({ name: nm, cls: slot(nm) })) : [] };
}

// Draw (or draw again, at a new width) the chart a figure holds.
const chartSpecs = new WeakMap();                              // figure -> the spec it was drawn from
function drawChart(fig) {
  const spec = chartSpecs.get(fig);
  if (!spec) return;
  fig.replaceChildren();
  if (spec.title || fig.dataset.caption) {                     // the title, in text colours, over the plot
    const cap = document.createElement("figcaption");
    cap.className = "viz-title";
    capInto(cap, fig.dataset.caption || spec.title);
    fig.append(cap);
  }
  const plot = document.createElement("div");
  plot.className = "viz-plot";
  fig.append(plot);
  // The width the plot has now; a figure in a folded entry has none, and is drawn again when it gets one.
  const W = Math.max(260, Math.floor(plot.clientWidth || 600));
  fig.dataset.w = String(W);
  const { svg, keys } = { bar: drawBars, stack: drawBars, line: drawLines, gantt: drawGantt }[spec.type](spec, W);
  fig.dataset.way = spec.type === "gantt" || svg.getAttribute("data-across") === "1" ? "across" : "up";
  svg.querySelectorAll(".line").forEach((l) => l.setAttribute("pathLength", "1"));
  svg.querySelectorAll(".mark").forEach((m, i) => m.style.setProperty("--n", String(Math.min(i, 40))));
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", spec.title || t("Chart"));
  svg.setAttribute("width", "100%");
  plot.append(svg);
  if (keys.length) fig.append(legendEl(keys));
  fig.append(tableView(spec));
}
// A chart is drawn for the width it has, so when that changes (the window, the index opening beside the
// thread, an entry unfolding) it is drawn again rather than stretched with its text.
const chartSizes = typeof ResizeObserver === "undefined" ? null : new ResizeObserver((entries) => {
  for (const e of entries) {
    const fig = e.target;
    // A body drawn again (a later paint, an entry folded or opened) leaves its old figures out of the page;
    // the observer is told when one goes, and lets it go, or it would hold every chart ever drawn.
    if (!fig.isConnected) { chartSizes.unobserve(fig); continue; }
    const w = Math.floor(fig.querySelector(".viz-plot")?.clientWidth || 0);
    if (w && Math.abs(w - Number(fig.dataset.w || 0)) >= 4) requestAnimationFrame(() => drawChart(fig));
  }
});

// ---- mermaid: loaded the first time an answer has a diagram (3.5 MB), from the server like the rest ----
let mermaidLoading = null, mermaidThemeKey = "", diagramSeq = 0;
const diagramCache = new Map();                                // theme + source -> { svg } or { error }
const diagramSources = new WeakMap();                          // figure -> the mermaid source it shows
// The diagram is drawn in system fonts: it is shown as an <img>, which cannot use the page's web font, and
// mermaid sizes its boxes by measuring the text in the page, so both must be the same font.
const DIAGRAM_FONT = '"Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", "Segoe UI", sans-serif';
function loadMermaid() {
  if (window.mermaid) return Promise.resolve(window.mermaid);
  mermaidLoading ??= new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = "vendor/mermaid.min.js";
    s.onload = () => (window.mermaid ? ok(window.mermaid) : fail(new Error("mermaid did not load")));
    s.onerror = () => { mermaidLoading = null; fail(new Error("mermaid did not load")); };   // tried again next time
    document.head.append(s);
  });
  return mermaidLoading;
}
// Which theme the page is in now, as the sheet colour: a diagram drawn for one theme is not shown in the other.
const themeKey = () => getComputedStyle(document.documentElement).getPropertyValue("--sheet").trim();
// Mermaid in the panel's colours: nodes on the second sheet colour with graphite edges and ink words, lines
// in ink-2, notes in the warn tint. "strict" keeps a diagram from carrying links or scripts.
function mermaidConfig() {
  const css = getComputedStyle(document.documentElement), v = (n) => css.getPropertyValue(n).trim();
  return {
    startOnLoad: false, securityLevel: "strict", theme: "base", darkMode: css.colorScheme === "dark",
    fontFamily: DIAGRAM_FONT, htmlLabels: false, suppressErrorRendering: true, maxTextSize: 8000, maxEdges: 300,
    flowchart: { htmlLabels: false, useMaxWidth: false, padding: 10 },
    // A sequence with long names and a timetable came out twice as wide as their frame, and their words half their size
    sequence: { useMaxWidth: false, mirrorActors: false, wrap: true, width: 120, actorMargin: 36, messageMargin: 30, boxMargin: 8 }, state: { useMaxWidth: false },
    er: { useMaxWidth: false }, class: { useMaxWidth: false }, gantt: { useMaxWidth: false, useWidth: 860, leftPadding: 90 },
    themeVariables: {
      fontFamily: DIAGRAM_FONT, fontSize: "14px", background: v("--sheet"),
      primaryColor: v("--sheet-2"), primaryTextColor: v("--ink"), primaryBorderColor: v("--series-1"),
      secondaryColor: v("--code-bar"), tertiaryColor: v("--sheet"), lineColor: v("--ink-2"), textColor: v("--ink"),
      mainBkg: v("--sheet-2"), nodeBorder: v("--series-1"), clusterBkg: v("--sheet"), clusterBorder: v("--rule-2"),
      edgeLabelBackground: v("--sheet"), actorBkg: v("--sheet-2"), actorBorder: v("--graphite"),
      actorTextColor: v("--ink"), actorLineColor: v("--rule-2"), signalColor: v("--ink-2"), signalTextColor: v("--ink"),
      labelBoxBkgColor: v("--sheet-2"), labelBoxBorderColor: v("--graphite"), labelTextColor: v("--ink"),
      loopTextColor: v("--ink"), noteBkgColor: v("--warn-soft"), noteTextColor: v("--ink"), noteBorderColor: v("--warn"),
      activationBkgColor: v("--code-bar"), activationBorderColor: v("--graphite"),
      // An ER table's rows: mermaid's own are light, under the dark theme's light words
      attributeBackgroundColorOdd: v("--sheet-2"), attributeBackgroundColorEven: v("--sheet"), rowOdd: v("--sheet-2"), rowEven: v("--sheet"),
      // A pie's slices and a mind map's branches in the series' colours: they all came out one colour
      pieTitleTextColor: v("--ink"), pieSectionTextColor: v("--ink"), pieLegendTextColor: v("--ink"), pieStrokeColor: v("--sheet"), pieOuterStrokeColor: v("--rule-2"),
      ...Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`pie${i + 1}`, v(`--series-${i + 1}`)])),
      ...Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`cScale${i}`, v(`--series-${i + 1}`)])),
      ...Object.fromEntries(Array.from({ length: 8 }, (_, i) => [`cScaleLabel${i}`, v(`--in-${i + 1}`) || v("--ink")])),
    },
  };
}
// The SVG mermaid made, with its drawn size written into width and height (it writes width="100%" and a
// max-width style, which an <img> cannot size from), as text for a data: URL.
function sizedSvg(text) {
  const doc = new DOMParser().parseFromString(text, "image/svg+xml"), root = doc.documentElement;
  if (root.nodeName !== "svg" || doc.querySelector("parsererror")) throw new Error("mermaid's SVG did not parse");
  const box = (root.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number);
  if (box.length !== 4 || !(box[2] > 0) || !(box[3] > 0)) throw new Error("mermaid's SVG has no size");
  root.setAttribute("width", String(Math.ceil(box[2])));
  root.setAttribute("height", String(Math.ceil(box[3])));
  root.removeAttribute("style");
  return { svg: new XMLSerializer().serializeToString(root), w: Math.ceil(box[2]) };
}
// The prompt asks for labels in double quotes, as flowcharts need, and a sequence's or a state's keep them on the page: "클라이언트" with its marks
function unquoteDiagram(src) {
  if (!/^\s*(sequenceDiagram|stateDiagram)/m.test(src || "")) return src;
  return src.replace(/^(\s*(?:participant|actor)\s+\S+\s+as\s+)"([^"\n]*)"\s*$/gm, "$1$2").replace(/^(\s*\S+\s*(?:-->>|->>|-->|->|--x|-x|--\)|-\))[+-]?\s*\S+\s*:\s*)"([^"\n]*)"\s*$/gm, "$1$2");
}
const DIAGRAM_LEAST = 0.72;                                    // of its drawn size, below which its words are too small to read
// Draw a diagram into its figure; when mermaid cannot read it, put the code block back with the reason.
async function drawDiagram(fig, pre) {
  const src = unquoteDiagram(diagramSources.get(fig)), key = themeKey() + "\n" + src;
  let got = diagramCache.get(key);
  if (!got) {
    try {
      const mm = await loadMermaid();
      if (mermaidThemeKey !== themeKey()) { mm.initialize(mermaidConfig()); mermaidThemeKey = themeKey(); }
      const { svg } = await mm.render(`sn-diagram-${++diagramSeq}`, src);
      got = sizedSvg(svg);
      // Laid out sideways and much wider than the thread, it would shrink to 7 px type (never a sideways scrollbar). The
      // same flow drawn downwards fits at a size that can be read.
      const down = src.replace(/^(\s*(?:flowchart|graph)\s+)(?:LR|RL)\b/m, "$1TD");
      if (down !== src && got.w * DIAGRAM_LEAST > (fig.clientWidth || 700)) {
        got = sizedSvg((await mm.render(`sn-diagram-${++diagramSeq}`, down)).svg);
      }
    } catch (e) {
      got = { error: String(e?.message || e).split("\n")[0].slice(0, 140), loaded: !!window.mermaid };
    }
    // Kept for the next drawing of the same diagram only when mermaid ran: a failed load is tried again next
    // time (loadMermaid clears its promise), and remembered it left that diagram as code for the whole session
    // after the file became reachable.
    if (!got.error || got.loaded) diagramCache.set(key, got);
  }
  if (!fig.isConnected) return;                                // the body was drawn again meanwhile
  if (got.error) {
    asCode(pre.querySelector("code"), "mermaid", "language-plaintext");   // left as code from now on
    fig.replaceWith(pre);
    vizNote(pre, t("The diagram's syntax is wrong, so its source is shown ({error})", { error: got.error }));
    enhance(pre.parentElement);                                // its code bar and copy button
    return;
  }
  const box = document.createElement("div"), img = document.createElement("img");
  box.className = "viz-diagram";
  img.alt = t("Diagram: ") + (src.split("\n").find((l) => l.trim() && !/^\s*(%%|flowchart|graph|sequenceDiagram|stateDiagram|erDiagram|classDiagram)/.test(l)) || "").trim().slice(0, 80);
  img.decoding = "async";
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(got.svg);
  // It takes the thread's width and no more (never a sideways scrollbar); a small one keeps its size.
  if (got.w) img.style.width = `${Math.round(got.w)}px`;
  box.append(img);
  const more = document.createElement("details"), sum = document.createElement("summary"), code = document.createElement("pre");
  more.className = "viz-more";
  sum.textContent = t("View the source");                       // the mermaid text, to copy into another tool
  code.className = "viz-src";
  code.textContent = src;
  more.append(sum, code);
  fig.replaceChildren(box, more);
  figureTitle(fig);
}
// A picture's block that stays code: marked so drawPictures passes it by, named on its bar for what it is
// (LANG_LABEL), and given a language highlight.js knows (it has none called chart or mermaid).
function asCode(code, lang, cls) {
  if (!code) return;
  code.dataset.viz = "failed";
  code.dataset.lang = lang;
  code.className = cls;
}
// The line over a code block that could not be drawn, saying why (once).
function vizNote(pre, text) {
  if (pre.previousElementSibling?.classList.contains("viz-note")) return;
  const p = document.createElement("p");
  p.className = "viz-note";
  p.textContent = text;
  pre.before(p);
}
// Turn the ```chart and ```mermaid code blocks of a finished answer into pictures.
function drawPictures(el) {
  el.querySelectorAll("pre > code.language-chart:not([data-viz]), pre > code.language-mermaid:not([data-viz])").forEach((code) => {
    const pre = code.parentElement, src = code.textContent.trim(), fig = document.createElement("figure");
    if (code.classList.contains("language-chart")) {
      const { spec, error } = chartSpec(src);
      if (error) { asCode(code, "chart", "language-json"); vizNote(pre, error); return; }   // stays a code block
      fig.className = "viz viz-chart";
      chartSpecs.set(fig, spec);
      pre.replaceWith(fig);
      drawChart(fig);
      chartSizes?.observe(fig);
      return;
    }
    fig.className = "viz viz-diagram-fig";
    fig.textContent = t("Drawing the diagram…");
    diagramSources.set(fig, src);
    pre.replaceWith(fig);
    drawDiagram(fig, pre);
  });
}
// While an answer is still being written, a picture's block is shown as a short line instead of its
// JSON or mermaid text arriving piece by piece; it is drawn once the answer is complete (enhance).
function holdPictures(el) {
  el.querySelectorAll("pre > code.language-chart, pre > code.language-mermaid").forEach((code) => {
    const wait = document.createElement("p");
    wait.className = "viz-wait";
    wait.textContent = t("Drawing the diagram…");
    code.parentElement.replaceWith(wait);
  });
}
// A diagram is drawn in the theme's colours, so when the theme changes the diagrams are drawn again.
function redrawDiagrams() {
  document.querySelectorAll("figure.viz-diagram-fig").forEach((fig) => {
    const src = diagramSources.get(fig);
    if (!src) return;
    const pre = document.createElement("pre"), code = document.createElement("code");
    code.className = "language-mermaid";
    code.textContent = src;
    pre.append(code);
    drawDiagram(fig, pre);
  });
}
new MutationObserver(() => requestAnimationFrame(redrawDiagrams)).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => requestAnimationFrame(redrawDiagrams));

// ---------- code blocks: line numbers, wrapped lines, indent guides, and what a function is on hover ----------
// Code reads as an editor shows it: numbered lines, long lines wrapped onto the
// next row instead of a box that scrolls sideways, the indentation drawn as guides, and a built-in or library
// function explained when the pointer rests on it. highlight.js has already coloured the block; lineCode cuts its
// output into one element per line, keeping a colour span open across a break (a multi-line string or comment is
// one span in its output), and the code's own text is kept apart for copying and running (codeText), since the
// block's text now holds the line numbers too.
const CODE_SRC = new WeakMap();                                // <code> -> its text as written, without line numbers
const codeText = (code) => CODE_SRC.get(code) ?? code.innerText;

// The highlighted block as one HTML string per line, every span that is open at a line break closed at its end and
// opened again at the start of the next line, so each line can stand in an element of its own.
function highlightedLines(code) {
  const lines = [""], open = [];                               // open: the classes of the spans enclosing the text
  // A line's spans are opened again where its first text that is not indentation starts: the indentation stands
  // outside them, at the code's own size. Inside a comment, set a size smaller, it fell short of its column, and
  // the next lines of a Javadoc or a /* */ stood at 4.4 columns for 5.
  let fresh = false;                                           // a line begun whose spans are not opened again yet
  const put = (html) => { lines[lines.length - 1] += html; };
  const opened = () => { if (fresh) { put(open.map((c) => `<span class="${c}">`).join("")); fresh = false; } };
  (function walk(node) {
    for (const n of node.childNodes) {
      if (n.nodeType === Node.TEXT_NODE) {
        n.nodeValue.split("\n").forEach((part, i) => {
          if (i > 0) {                                         // a line break: close what is open, start the next line
            if (!fresh) put("</span>".repeat(open.length));
            lines.push("");
            fresh = open.length > 0;
          }
          if (fresh) {                                         // the indentation first, then the spans again
            const lead = part.match(/^[ \t]*/)[0];
            put(escapeHtml(lead));
            part = part.slice(lead.length);
            if (part) opened();
          }
          put(escapeHtml(part));
        });
      } else if (n.nodeType === Node.ELEMENT_NODE) {
        opened();
        const cls = (n.getAttribute("class") || "").replace(/[^\w -]/g, "");   // highlight.js's class names only
        put(`<span class="${cls}">`);
        open.push(cls);
        walk(n);
        open.pop();
        if (fresh) fresh = open.length > 0;                    // it ended on a line where it was not opened again
        else put("</span>");
      }
    }
  })(code);
  // A block ending in a line break has an empty last line that is not a line of the code.
  if (lines.length > 1 && !lines[lines.length - 1].replace(/<[^>]*>/g, "")) lines.pop();
  return lines;
}

// How far each line is indented, in columns (a tab is four), and the step the code indents by: the smallest
// indentation above zero, which is 4 in most answers and 2 in some JavaScript and C++ (none: 4).
function indentation(text) {
  const cols = text.split("\n").map((l) => {
    let n = 0;
    for (const ch of l) { if (ch === " ") n += 1; else if (ch === "\t") n += 4 - (n % 4); else break; }
    return l.trim() ? n : -1;                                  // a blank line takes the indentation around it (below)
  });
  // A blank line inside a block keeps the guides running through it: the smaller of the lines around it.
  for (let i = 0; i < cols.length; i++) {
    if (cols[i] >= 0) continue;
    const before = cols.slice(0, i).reverse().find((c) => c >= 0) ?? 0, after = cols.slice(i + 1).find((c) => c >= 0) ?? 0;
    cols[i] = Math.min(before, after);
  }
  const step = Math.min(...cols.filter((c) => c > 0), Infinity);
  return { cols, step: Number.isFinite(step) && step <= 8 ? step : 4 };
}

// One block, highlighted, into numbered lines with their indentation, once.
function lineCode(code) {
  const text = code.textContent.replace(/\n$/, "");
  CODE_SRC.set(code, text);                                    // copying and running read this (codeText)
  const lines = highlightedLines(code);
  const { cols, step } = indentation(text);
  code.style.setProperty("--step", String(step));              // the guides' spacing, in columns
  // Commands are not numbered lines of a program: each starts at a prompt, and a line a backslash carries on has none
  const shell = isCommand(code, text), src = text.split("\n");
  code.classList.toggle("shell", shell);
  // A block that writes its own prompts has commands and their output: the prompts move to the column (no "$ $"), the output gets none,
  // and copying takes the commands alone, which is what can be pasted back
  const PROMPT = /^\s*\$\s/, prompted = shell && src.some((l) => PROMPT.test(l));
  const carries = (i) => i > 0 && /\\\s*$/.test(src[i - 1]);
  const gutter = (i) => (!shell ? i + 1 : prompted ? (PROMPT.test(src[i]) ? "$" : "")
    : carries(i) || !src[i]?.trim() || /^\s*#/.test(src[i]) ? "" : "$");
  if (prompted) {
    src.forEach((l, i) => { if (PROMPT.test(l)) lines[i] = lines[i].replace(/^(\s*(?:<[^>]+>)*\s*)\$\s/, "$1"); });
    let inCommand = false;
    CODE_SRC.set(code, src.filter((l, i) => { inCommand = PROMPT.test(l) || (inCommand && carries(i)); return inCommand; })
      .map((l) => l.replace(PROMPT, "")).join("\n"));
  }
  code.style.setProperty("--gw", shell ? "1ch" : `${String(lines.length).length}ch`);   // the column, as wide as the widest
  code.innerHTML = lines.map((html, i) =>
    // --ind: the line's indentation, which its wrapped rows hang from and its guides run across
    `<span class="ln" style="--ind:${cols[i] ?? 0}"><span class="no" aria-hidden="true">${gutter(i)}</span>`
    + `<span class="tx">${html || " "}</span></span>`).join("");
  code.classList.add("lined");
}

// A selection copied out of numbered lines: an empty line of the code is drawn as one space (so the line keeps its
// height), and the browser copied that space. The copy is the selection's text with those lines empty again.
document.addEventListener("copy", (e) => {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !e.clipboardData) return;
  const node = sel.getRangeAt(0).commonAncestorContainer;
  const code = (node.nodeType === 1 ? node : node.parentElement)?.closest?.("code.lined");
  if (!code) return;
  e.clipboardData.setData("text/plain", sel.toString().split("\n").map((l) => (l === " " ? "" : l)).join("\n"));
  e.preventDefault();
});

// ---- what a function is, on hover: panel/code-docs.json (runner/make_code_docs.py), loaded the first time ----
let codeDocs = null, codeDocsLoading = null;
function loadCodeDocs() {
  codeDocsLoading ??= fetch("code-docs.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({}))
    .then((d) => { codeDocs = d; return d; });
  return codeDocsLoading;
}
// The docs' languages, by the name a code block's fence uses (LANG_LABEL's keys).
const DOC_LANG = { python: "python", py: "python", python3: "python", cpp: "cpp", "c++": "cpp", cc: "cpp", c: "cpp",
  java: "java", kotlin: "java", js: "javascript", javascript: "javascript", node: "javascript", ts: "typescript",
  typescript: "typescript", go: "go", golang: "go" };
// Names worth explaining, as written in code: dotted (heapq.heappush, Arrays.sort, fmt.Println) or with :: (std::sort).
const DOC_NAME = /[A-Za-z_][\w]*(?:(?:\.|::)[A-Za-z_]\w*)*/g;
// Python's imports, so a name from `from collections import deque` and a module under `import numpy as np` are read
// as what they stand for: {name or alias: full name}.
function pythonImports(text) {
  const map = {};
  // Within one line ([ \t], never \s, which reached across the line break and read the next lines into the name),
  // or within the parentheses of an import written over several lines.
  for (const m of text.matchAll(/^[ \t]*import[ \t]+([^\n#;]+)/gm)) {
    for (const part of m[1].split(",")) {
      const [mod, alias] = part.trim().split(/[ \t]+as[ \t]+/);
      if (/^[\w.]+$/.test(mod)) map[alias || mod] = mod;
    }
  }
  for (const m of text.matchAll(/^[ \t]*from[ \t]+([\w.]+)[ \t]+import[ \t]+(\([^)]*\)|[^\n#;]+)/gm)) {
    for (const part of m[2].replace(/[()]/g, "").split(",")) {
      const [name, alias] = part.trim().split(/\s+as\s+/);
      if (/^\w+$/.test(name || "")) map[alias || name] = `${m[1]}.${name}`;
    }
  }
  return map;
}
// The entry a name in a code block stands for, or null: a full name the docs know (after the imports for Python, and
// without `std::` once `using namespace std` is there), else a method called on a value (`.append(`).
function docFor(lang, docs, name, method, imports) {
  if (!docs) return null;
  if (lang === "python") {
    const [head, ...rest] = name.split(".");
    const full = imports[head] ? [imports[head], ...rest].join(".") : name;
    if (own(docs.names, full)) return { key: full, ...docs.names[full] };
    if (!rest.length && !imports[head] && own(docs.names, name)) return { key: name, ...docs.names[name] };
  } else if (own(docs.names, name)) {
    return { key: name, ...docs.names[name] };
  }
  if (method && docs.methods && own(docs.methods, method)) return { key: "." + method, ...docs.methods[method] };
  return null;
}
// Wrap the names a block uses that the docs explain, outside its strings and comments, in a span the hover reads.
async function docTips(code) {
  const lang = own(DOC_LANG, code.dataset.lang);
  if (!lang) return;
  const all = await loadCodeDocs(), docs = all?.[lang];
  if (!docs || !code.isConnected) return;
  const imports = lang === "python" ? pythonImports(codeText(code)) : {};
  // Every text node in order, the skipped ones too: the highlighter puts a method of the standard library in a span
  // of its own (v.<span>push_back</span>(1)), so the dot before a name and the parenthesis after it are often in the
  // next node over, and were not seen.
  const nodes = [];
  const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) nodes.push(walker.currentNode);
  const skipped = (n) => n.parentElement.closest(".no, .hljs-string, .hljs-comment, .hljs-meta, .doc");
  const texts = nodes.map((n) => n.nodeValue);   // read before any node is replaced below
  for (const [i, node] of nodes.entries()) {
    if (skipped(node)) continue;
    const s = texts[i], before = i > 0 ? texts[i - 1].slice(-1) : "", next = texts[i + 1] || "";
    let last = 0, frag = null;
    for (const m of s.matchAll(DOC_NAME)) {
      // a method call: `.name(` right after a value (the dot is just before this match, maybe in the node before)
      const rest = s.slice(m.index + m[0].length);
      const after = /^\s*\(/.test(rest.trim() ? rest : rest + next);
      const method = (m.index > 0 ? s[m.index - 1] : before) === "." && after ? m[0].split(/\.|::/)[0] : null;
      let hit = docFor(lang, docs, m[0], method, imports), at = m.index, word = m[0];
      // A dotted name the docs do not know, called: a method on a value (nums.append(, v.push_back(, seen.get(),
      // looked up by its last part and marked on that part alone. The whole name was looked up and missed, so
      // no method on a named value was ever explained.
      const parts = m[0].split(/\.|::/);
      if (!hit && after && parts.length > 1) {
        const tail = parts[parts.length - 1];
        hit = docFor(lang, docs, "\u0000", tail, imports);   // no full name can match, so only the method is read
        if (hit) { at = m.index + m[0].length - tail.length; word = tail; }
      }
      if (!hit) continue;
      frag ??= document.createDocumentFragment();
      frag.append(s.slice(last, at));
      const span = document.createElement("span");
      span.className = "doc";
      // what the box shows (text only): the signature, the Korean and the reference's own line
      span.dataset.doc = JSON.stringify({ sig: hit.sig, doc: hit.doc, ko: hit.ko, in: hit.in, out: hit.out });
      span.textContent = word;
      frag.append(span);
      last = at + word.length;
    }
    if (frag) { frag.append(s.slice(last)); node.replaceWith(frag); }
  }
}
// One box for the whole page, shown beside the name the pointer rests on, like an editor's hover.
let docTip = null, docTimer = 0;
function showDocTip(span) {
  let d;
  try { d = JSON.parse(span.dataset.doc || "{}"); } catch (_) { return; }
  docTip ??= Object.assign(document.createElement("div"), { className: "doc-tip", role: "tooltip" });
  if (!docTip.isConnected) document.body.append(docTip);
  docTip.replaceChildren();
  const add = (parent, tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = text;
    parent.append(el);
    return el;
  };
  add(docTip, "code", "doc-sig", d.sig || span.textContent);
  if (d.ko && LANG === "ko") {
    // What it does in Korean, what goes in and what comes out, then the reference's own line, small: the English
    // line alone was one more thing to translate before it said anything.
    add(docTip, "p", "doc-ko", d.ko);
    const io = add(docTip, "dl", "doc-io", "");
    for (const [label, text] of [[t("Input"), d.in], [t("Output"), d.out]]) {
      if (!text) continue;
      add(io, "dt", "", label);
      add(io, "dd", "", text);
    }
    if (!io.childElementCount) io.remove();
    if (d.doc) add(docTip, "p", "doc-en", d.doc).lang = "en";
  } else {
    add(docTip, "p", "doc-ko", d.doc || "");   // English, or a file written before the Korean: the English as the text
  }
  docTip.hidden = false;
  // below the name, or above it when that would leave the window; kept inside the window sideways
  const r = span.getBoundingClientRect(), w = docTip.offsetWidth, h = docTip.offsetHeight;
  const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
  const top = r.bottom + 6 + h > window.innerHeight ? r.top - h - 6 : r.bottom + 6;
  docTip.style.left = `${left}px`;
  docTip.style.top = `${Math.max(8, top)}px`;
}
document.addEventListener("mouseover", (e) => {
  const span = e.target.closest?.(".md code .doc");
  clearTimeout(docTimer);
  if (span) docTimer = setTimeout(() => showDocTip(span), 300);   // a pause, as an editor waits before its hover
  else if (docTip && !e.target.closest?.(".doc-tip")) docTip.hidden = true;
});
document.addEventListener("scroll", () => { if (docTip) docTip.hidden = true; }, { passive: true });
// Leaving the window (the panel sits beside an editor) fires no mouseover, so the box stayed up, and a name crossed on
// the way out put one up 300 ms later that stayed too.
const hideDocTip = () => { clearTimeout(docTimer); if (docTip) docTip.hidden = true; };
document.addEventListener("mouseout", (e) => { if (!e.relatedTarget) hideDocTip(); });
window.addEventListener("blur", hideDocTip);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && docTip) docTip.hidden = true; });

// A cell that holds one number, with at most a sign, a currency mark and a short unit after it ("1,234",
// "-3.5", "95%", "100 ns", "₩1,000", "3" with a Korean counter). An IP address, a version (1.2.3) or O(n) is not one.
const NUMBER_CELL = /^[-+−]?[$₩€£]?\s*\d{1,3}(,\d{3})*(\.\d+)?\s*(%|‰|[A-Za-zμµ]{1,4}(\/[A-Za-z]{1,3})?|[가-힣]{1,2})?$|^[-+−]?[$₩€£]?\s*\d+(\.\d+)?\s*(%|‰|[A-Za-zμµ]{1,4}(\/[A-Za-z]{1,3})?|[가-힣]{1,2})?$/;
// Mark the columns of a table whose cells are numbers: every filled body cell of the column one, a dash
// or an empty cell let through, at least one number in it. The header cell over it is marked too.
function markNumberColumns(table) {
  const rows = [...table.rows], body = [...(table.tBodies[0]?.rows || [])];
  if (!body.length) return;
  const cols = Math.max(...rows.map((r) => r.cells.length));
  for (let j = 0; j < cols; j++) {
    const cells = body.map((r) => (r.cells[j]?.textContent || "").trim()).filter((t) => t && !/^[-–—]$/.test(t) && !/^[-+−]?∞$/.test(t));
    if (!cells.length || !cells.every((t) => NUMBER_CELL.test(t))) continue;
    rows.forEach((r) => r.cells[j]?.classList.add("num"));
  }
}
// Only the spans protectMath picked out become math: KaTeX's auto-render would pair any two "$". protectMath picks out
// closed formulas only, so this runs on an answer still streaming too: a formula is set as soon as its closing $
// arrives, where raw TeX used to show until the answer's last line. Each
// formula's HTML is kept by its source, so repainting the stream costs a lookup, not a KaTeX run.
const mathHtml = new Map();
function typesetMath(el) {
  if (typeof window.katex === "undefined") return;
  el.querySelectorAll("span.math:not(.done)").forEach((sp) => {
    const src = sp.textContent, display = src.startsWith("$$");
    let html = mathHtml.get(src);
    if (html === undefined) {
      try {
        html = window.katex.renderToString(display ? src.slice(2, -2) : src.slice(1, -1), { displayMode: display, throwOnError: false });
      } catch (_) { html = null; }
      if (mathHtml.size > 600) mathHtml.clear();   // a long session's formulas, not kept without a bound
      mathHtml.set(src, html);
    }
    if (html != null) { sp.innerHTML = html; sp.classList.add("done"); }
  });
}
// While an answer is written, its code blocks wear what a finished one does: colours, numbered lines, indent guides and
// the bar with the language. They turned into that only when the answer was done, so the code went in as plain text
// and changed its look all at once at the end. The body is rendered afresh every frame, so a block that is no longer
// the last one (its text is finished) is kept as it was lined, by its language and text, and only the block still
// being written is worked out again. The buttons come with the finished answer (enhance); until then the bar holds
// their place, so it keeps its height when they come.
// The code block at the very end of an answer's body (inside the last list item too), the one still being written.
function lastBlock(el) {
  let n = el.lastElementChild;
  while (n && n.tagName !== "PRE" && n.lastElementChild) n = n.lastElementChild;
  return n?.tagName === "PRE" ? n : null;
}
const LIVE_CODE = new Map();                                    // "lang\ntext" -> what lineCode made of it
// The block being written, as it was last lined, while it is long: {lang, text, at, cls, html, step, gw}
let liveWriting = null, liveWritingTimer = 0;
const LIVE_LONG_LINES = 150;   // a block this long being written is lined again at most every LIVE_LONG_MS
const LIVE_LONG_MS = 150;
function liveCode(el) {
  const writing = lastBlock(el);
  el.querySelectorAll("pre > code").forEach((code) => {
    const pre = code.parentElement;
    if (code.dataset.lang === undefined) code.dataset.lang = fenceLang(code);
    const text = code.textContent;
    const key = code.dataset.lang + "\n" + text;
    const kept = LIVE_CODE.get(key);
    // A long block being written, lined less than LIVE_LONG_MS ago: shown as it was then, a few characters behind.
    // Lined again on every piece, a thousand lines of it took 22 ms a frame at the 95th percentile; copying still
    // takes all of it.
    const recent = pre === writing && liveWriting && liveWriting.lang === code.dataset.lang
      && text.startsWith(liveWriting.text) && performance.now() - liveWriting.at < LIVE_LONG_MS
      && (text.match(/\n/g) || []).length >= LIVE_LONG_LINES ? liveWriting : null;
    const shown = kept || recent;
    if (shown) {                                                // as it was lined, last frame or a moment ago
      code.className = shown.cls;
      code.innerHTML = shown.html;
      code.style.setProperty("--step", shown.step);
      code.style.setProperty("--gw", shown.gw);
      CODE_SRC.set(code, text.replace(/\n$/, ""));
      if (!kept) {
        // Shown a moment behind: lined again once the moment is over, or the last piece stayed unseen for as long as
        // the stream paused after it
        clearTimeout(liveWritingTimer);
        liveWritingTimer = setTimeout(() => {
          if (!code.isConnected || !code.closest(".md.cursor")) return;   // drawn again since, or the answer ended
          code.textContent = text;
          code.className = recent.cls.replace(/\b(hljs|lined)\b/g, "").trim();
          if (window.hljs) { try { window.hljs.highlightElement(code); } catch (_) {} }
          lineCode(code);
          liveWriting = { lang: code.dataset.lang, text, at: performance.now(), cls: code.className, html: code.innerHTML,
                          step: code.style.getPropertyValue("--step"), gw: code.style.getPropertyValue("--gw") };
        }, LIVE_LONG_MS);
      }
    } else {
      // A block with no language is not guessed at while it is written: highlight.js's guess ran over the whole
      // block every frame (63 ms for 200 lines) and changed its mind as lines came (ruby, shell, lua), recolouring
      // it each time. It is plain text until it is written, and guessed once then.
      if (pre === writing && !code.dataset.lang) code.classList.add("language-plaintext");
      // A command with no language is a shell line: left to guess, "kubectl debug <pod> -it --copy-to=dbg" came out as a comment
      else if (!code.dataset.lang && isCommand(code, code.textContent)) code.classList.add("language-bash");
      if (window.hljs) { try { window.hljs.highlightElement(code); } catch (_) {} }
      lineCode(code);
      if (pre === writing) {
        liveWriting = { lang: code.dataset.lang, text, at: performance.now(), cls: code.className, html: code.innerHTML,
                        step: code.style.getPropertyValue("--step"), gw: code.style.getPropertyValue("--gw") };
      }
      // Kept once the block is written: the one still being written is new text every frame, and kept it filled the
      // map with a copy of itself per frame
      if (pre !== writing) {
        if (LIVE_CODE.size > 300) LIVE_CODE.clear();            // a long session's blocks, not kept without a bound
        LIVE_CODE.set(key, { cls: code.className, html: code.innerHTML,
                             step: code.style.getPropertyValue("--step"), gw: code.style.getPropertyValue("--gw") });
      }
    }
    if (pre.querySelector(".codebar")) return;
    const bar = document.createElement("div");
    bar.className = "codebar";
    const lang = document.createElement("span");
    lang.className = "lang";
    lang.textContent = isCommand(code, code.textContent) ? t("Command") : own(LANG_LABEL, code.dataset.lang) || code.dataset.lang || t("Code");
    const wait = document.createElement("span");                // where the copy button comes, as wide as it
    wait.className = "wait";
    // Only the block still being written says so: every block said "Writing" until the whole answer ended, the
    // ones finished long before too. The empty one keeps the bar's height.
    wait.textContent = pre === writing ? t("Writing") : "";
    bar.append(lang, wait);
    pre.insertBefore(bar, pre.firstChild);
  });
}
// How an answer's text is set, the same while it is written as at its end: it was done only at the end, so an answer
// changed its look the moment it finished. Cheap enough for every frame of the stream.
// A table's bar, as a code block has: "Table" on the left and, once the answer is done, a copy button on the right
// (enhance). While the answer is written the button's place holds a quiet space of its size, so the bar keeps its
// height when the button comes. The table goes into a scroller of its own under the bar: a wide table scrolls
// sideways and the bar with its button stays where it is.
function tableBar(wrap) {
  if (!wrap || wrap.querySelector(":scope > .codebar")) return;   // once per table
  const table = wrap.querySelector(":scope > table");
  if (!table) return;
  const scroll = document.createElement("div");           // what scrolls when the table is wider than the column
  scroll.className = "tablescroll";
  table.replaceWith(scroll);
  scroll.appendChild(table);
  const bar = document.createElement("div");
  bar.className = "codebar tablebar";                     // the code bar's look, so the two read as one kind of thing
  const label = document.createElement("span");
  label.className = "lang";
  label.textContent = t("Table");
  const wait = document.createElement("span");            // where the copy button comes, as wide as it
  wait.className = "wait";
  bar.append(label, wait);
  wrap.insertBefore(bar, scroll);
}
// Several questions answered at once: each numbered heading and what follows it, up to the next, is set as a block of its own, so the
// questions can be told apart and found down a long answer. Only when two or more headings of one kind are numbered; done on the
// finished answer, since what is still being written has not got its next heading.
// The number must end there: "2.5배 빠른 이유" and "1.1 개요" are not questions 2 and 1.
const QA_HEAD = /^\s*(\(\d+\)|\d+[.)](?!\d)|Q\d*[.:)]|질문\s*\d+)/i;
const qaRank = (h) => (/^H[1-4]$/.test(h.tagName) ? +h.tagName[1] : 5);   // a bold line stands under every real heading
// The numbers run on from each other: steps numbered again under each question are not themselves the questions
const qaRuns = (heads) => {
  const ns = heads.map((h) => +(h.textContent.match(QA_HEAD)?.[1].match(/\d+/)?.[0] ?? NaN));
  return ns.every((n, i) => Number.isNaN(n) || !i || n === ns[i - 1] + 1);
};
function groupAnswers(root) {
  root.querySelectorAll(".md").forEach((md) => {
    if (md.classList.contains("cursor") || md.querySelector(":scope > .qa")) return;
    const heads = [...md.children].filter((c) => c.matches("h1, h2, h3, h4, p.lead, p.para-head") && QA_HEAD.test(c.textContent));
    const kinds = {};
    heads.forEach((h) => { const k = h.tagName + h.className; (kinds[k] = kinds[k] || []).push(h); });
    // The outermost kind numbered that way, not the most numerous: three steps under "## 1." outnumber the questions themselves
    const numbered = Object.values(kinds).filter((a) => a.length >= 2 && qaRuns(a)).sort((a, b) => qaRank(a[0]) - qaRank(b[0]))[0];
    // Every kind of answer is set this way: a heading without a number starts a block too, at the numbered ones'
    // level if there are any, or else at the outermost level that has two
    const real = [...md.children].filter((c) => c.matches("h1, h2, h3, h4"));
    const levels = [1, 2, 3, 4].filter((l) => real.filter((h) => qaRank(h) === l).length >= 2);
    const level = numbered ? qaRank(numbered[0]) : levels[0];
    const chosen = numbered && level === 5 ? numbered : real.filter((h) => qaRank(h) === level);
    if (chosen.length < 2) return;
    const rank = qaRank(chosen[0]);
    chosen.forEach((h, i) => {
      const box = document.createElement("section");
      box.className = "qa";
      h.before(box);
      let n = h;
      // Up to the next question, or a heading as high as these ("## 정리" closing the answer is not part of the last one)
      while (n && n !== chosen[i + 1] && (n === h || !(n.matches("h1, h2, h3, h4") && qaRank(n) <= rank))) { const next = n.nextElementSibling; box.append(n); n = next; }
      const num = h.textContent.match(QA_HEAD)?.[1];
      if (num && h.firstChild?.nodeType === 3) {               // the number in the red pen, the words after it as they were
        const at = h.firstChild.textContent.indexOf(num);
        if (at >= 0) { const tail = h.firstChild.splitText(at + num.length), mark = document.createElement("span"); mark.className = "qa-no"; mark.textContent = h.firstChild.textContent; h.firstChild.replaceWith(mark); void tail; }
      }
    });
  });
}
function textStyle(el) {
  // A paragraph that is nothing but a bold line is a step heading the model wrote ("**1. ...**"): marked
  // .lead, it is set in the kind colour like the headings (index.html, .md p.lead).
  el.querySelectorAll(".md p").forEach((p) => {
    // A bold line with a formula set right under it, no blank line between, is that same heading: the formula goes to a paragraph of its own,
    // or "**2. ...**" was drawn as stressed words while "**1. ...**" over a list was drawn as a heading
    const parts = [...p.childNodes].filter((n) => !(n.nodeType === 3 && !n.nodeValue.trim()) && n.nodeName !== "BR");
    if (parts[0]?.nodeName === "STRONG" && parts.length > 1 && parts.slice(1).every((n) => n.nodeType === 1 && n.matches("span.math") && (n.textContent.startsWith("$$") || n.querySelector(".katex-display")))) {
      const below = document.createElement("p");
      below.append(...parts.slice(1));
      p.after(below);
      p.classList.toggle("para-head", p.textContent.trim().length <= 60);   // as it would have been with a blank line under it
    }
    const b = p.firstElementChild;
    p.classList.toggle("lead", p.childElementCount === 1 && b?.tagName === "STRONG" && p.textContent.trim() === b.textContent.trim());
  });
  // A short bold label that opens a paragraph ("요지:", "설명:") names the paragraph and stresses nothing: under the highlighter
  // every paragraph began with a stripe and a stripe stopped meaning anything. It is written in the red pen instead (index.html, .lab).
  el.querySelectorAll(".md :is(p, li) > strong:first-child").forEach((b) => {
    const t = b.textContent.trim(), before = b.previousSibling;
    b.classList.toggle("lab", /^[^\s:]{1,8}\s?:$/.test(t) && !(before && before.textContent.trim()));
  });
  el.querySelectorAll(".md ol[start]").forEach((o) => o.style.setProperty("--start", o.getAttribute("start")));
  // A table column of numbers is set right-aligned with even digits (index.html, .num), so they compare.
  el.querySelectorAll(".md table").forEach(markNumberColumns);
  el.querySelectorAll("table").forEach((t) => {
    if (t.closest(".check-runs")) return;                 // a code check's list has its own frame, and no caption or copy of its own
    if (!t.closest(".tablewrap")) {                       // an answer's table: framed here (a chart's comes framed)
      const w = document.createElement("div"); w.className = "tablewrap"; t.replaceWith(w); w.appendChild(t);
    }
    tableBar(t.closest(".tablewrap"));
  });
  // Inline code of a few characters is a token (`-n`, `line 3`, `i += 1`): kept on one line (index.html, .short)
  el.querySelectorAll(".md :not(pre) > code").forEach((c) => c.classList.toggle("short", c.textContent.length <= 24));
}
// ---------- an answer drawn, not only written ----------
// What an answer says by its shape is drawn from that shape once it is whole: terms as cards, a chain of arrows as a flow, the time and space it costs on
// their scale, a table's figures as bars, what it is made of as a strip to go by, so an answer reads as infographics and not as a wall of text.
// Numbered steps are a ladder by the stylesheet alone, so they look the same while they are written. Of 491 real answers 53% hold numbered steps, 27% terms
// and half of the coding ones a complexity. All of it is drawn here from what the answer already says: no word is left out or written anew, and no model is asked,
// so a kept answer gets it too. Where the shape is not certain the answer stays as it was written.
const V_ARROW = /\s*(?:→|➜|⟶|⇒|=>|->)\s*/;
const vEl = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
// The bold words that open a list item, when they name it: "**Term**: ...", "**A whole sentence.** ...". Not bold words that begin a sentence ("**sort** first, then ...")
function vLead(holder, longest = 48) {
  let first = holder.firstChild;
  while (first && first.nodeType === 3 && !first.textContent.trim()) first = first.nextSibling;
  if (first?.nodeName !== "STRONG") return null;
  const said = first.textContent.trim(), next = first.nextSibling;
  if (!said || said.length > longest) return null;
  const closed = /[:：.。!?！？]$/.test(said), goesOn = next?.nodeType === 3 && /^\s*(?:\([^()]{1,14}\)\s*)?[:：\-–—]/.test(next.textContent);
  const listNext = next?.nodeType === 3 && !next.textContent.trim() ? next.nextSibling : next;
  return closed || goesOn || !next || (longest > 48 && ["UL", "OL"].includes(listNext?.nodeName)) ? first : null;
}
// What holds a list item's first words: the item, or the paragraph that opens it in a list with blank lines between its items
function vHolder(li) {
  const first = li.firstElementChild;
  return first?.tagName === "P" && !first.previousSibling?.textContent.trim() ? first : li;
}
function vSplitLead(li, longest) {
  const holder = vHolder(li), lead = vLead(holder, longest);
  if (!lead) return false;
  const head = vEl("div", "v-t"), body = vEl("div", "v-b");
  const after = lead.nextSibling, note = after?.nodeType === 3 ? after.textContent.match(/^\s*\(([^()]{1,14})\)\s*[:：\-–—]\s*/) : null;
  if (after?.nodeType === 3) after.textContent = after.textContent.replace(/^\s*(?:\([^()]{1,14}\)\s*)?[:：\-–—]\s*/, "");
  // Its own colon goes: the card says it is a name by where it stands
  for (let t = lead.lastChild; t; t = t.lastChild) { if (t.nodeType === 3) { t.textContent = t.textContent.replace(/\s*[:：]\s*$/, ""); break; } }
  lead.classList.remove("lab");
  head.append(lead);
  if (note) head.append(vEl("span", "v-t-note", note[1]));   // "(correct)": said beside the name, in the name's colour
  const named = head.textContent.trim().replace(/\s*\([^()]*\)$/, "");
  const note_ = note ? note[1] : "";
  if (/^(장점|이점|좋은 점|정답|맞음|옳음|pros?|advantages?|benefits?|correct)$/i.test(named) || /^(정답|맞음|옳음|correct)$/i.test(note_)) head.dataset.tone = "good";
  else if (/^(오답|틀림|wrong|incorrect)$/i.test(named) || /^(오답|틀림|wrong|incorrect)$/i.test(note_)) head.dataset.tone = "off";
  else if (/^(단점|한계|위험|주의|함정|cons?|disadvantages?|drawbacks?|limitations?|risks?|pitfalls?|caveats?)$/i.test(named)) head.dataset.tone = "bad";
  if (holder === li) { while (li.firstChild) body.append(li.firstChild); li.append(head); if (body.textContent.trim() || body.childElementCount) li.append(body); }
  else { li.prepend(head); holder.classList.add("v-b"); if (!holder.textContent.trim()) holder.remove(); }
  return true;
}
function vTerms(md) {
  md.querySelectorAll(":scope > ul, :scope > .qa > ul").forEach((ul) => {
    const items = [...ul.children].filter((c) => c.tagName === "LI");
    if (items.length < 2) return;
    if (!items.every((li) => vLead(vHolder(li)))) return;     // terms all, or a plain list
    items.forEach((li) => vSplitLead(li));
    ul.classList.add("v-terms");
  });
}
function vStepLeads(md) {
  md.querySelectorAll(":scope > ol, :scope > .qa > ol").forEach((ol) => [...ol.children].forEach((li) => { if (li.tagName === "LI") vSplitLead(li, 120); }));
}
// The links of a chain, or nothing: "A -> B -> C" with short links, none of them a list of its own ("80% -> 21ns, 90% -> 11ns" pairs figures, it does not go anywhere)
function vChain(text) {
  const links = String(text).split(V_ARROW).map((x) => x.trim()).filter(Boolean);
  if (links.length < 3 || links.length > 9 || links.some((x) => x.length > 40)) return null;
  if (links.slice(1, -1).some((x) => /[,，;]/.test(x))) return null;
  if (links.some((x) => /[.!?。！？]$|[.!?。！？]\s|니다$|[한된있없]다$/.test(x) || (x.match(/["“”]/g) || []).length % 2)) return null;   // a sentence that happens to hold arrows: its pieces read as nothing in boxes
  return links;
}
function vFlow(links, said) {
  const box = vEl("div", "v-flow");
  box.setAttribute("role", "img"); box.setAttribute("aria-label", said || links.join(t(", then ")));
  links.forEach((x, i) => {
    if (i) box.insertAdjacentHTML("beforeend", mark('<path d="M4 12h15M13.5 6.5 19 12l-5.5 5.5"/>', 2));
    box.append(vEl("span", "", x));
  });
  return box;
}
function vFlows(md) {
  md.querySelectorAll("p, li").forEach((node) => {
    if (node.closest("table, pre, blockquote, .v-flow")) return;
    const plain = node.tagName === "LI" ? [...node.childNodes].filter((c) => !["UL", "OL"].includes(c.nodeName)).map((c) => c.textContent).join("").trim() : node.textContent.trim();
    const whole = node.childElementCount <= 1 && !node.querySelector("code, .math, a, ul, ol") ? vChain(plain) : null;
    if (whole) { node.textContent = ""; node.classList.add("v-flow-line"); node.append(vFlow(whole, plain)); return; }
    // A chain in bold or code inside a sentence, or written with no spaces in its links: the sentence stays and the chain is drawn under it
    const run = [...node.children].find((c) => ["STRONG", "EM"].includes(c.tagName) && vChain(c.textContent));
    let links = run ? vChain(run.textContent) : null;
    if (!links) {
      const prose = node.cloneNode(true);
      prose.querySelectorAll("code, pre, ul, ol").forEach((x) => x.remove());   // what is in code stays code: `a -> b -> c` may be a type, or a pointer's path
      const own = prose.textContent.match(/(?:[^\s→>]+\s*(?:→|->|=>|⇒)\s*){2,8}[^\s→>]+/)?.[0];
      links = own ? vChain(own.replace(/([A-Za-z0-9)\]])(?:의|로|를|을|가|이|은|는|와|과|에|로서|까지|부터)$/, "$1")) : null;
      if (links && links.some((x) => x.length > 22)) links = null;
    }
    if (links) node.append(vFlow(links));
  });
}
// A note the answer marks as one
function vNotes(md) {
  md.querySelectorAll(":scope > p, :scope > .qa > p, li > p").forEach((p) => {
    if (/^\s*(주의|경고|함정|유의|위험|Warning|Caution|Pitfall|Trap)\s*[:：]/i.test(p.textContent)) p.classList.add("v-note");
  });
}
// The cost of an answer on its scale. Read from what it says, its key line first; two different figures in the body with none in the key line are not guessed between
const V_SCALE = ["O(1)", "O(log N)", "O(N)", "O(N log N)", "O(N²)", "O(N³)", "O(2ᴺ)"];
function vBigOClass(expr) {
  const s = String(expr).replace(/\\(?:,|;|!|\s)/g, "").replace(/\\(log|cdot|times|sqrt)/g, "$1").replace(/[\s{}`$\\]/g, "").replace(/cdot|times|[·×⋅]/g, "*").toLowerCase().replace(/log(?:\^\d+|[²³])/g, "log");
  if (/^(1|c|상수)$/.test(s)) return 0;
  if (/^log(\(\w+\)|\w)$/.test(s) || /^log[_\d]*\w$/.test(s)) return 1;
  if (/^(sqrt|√)/.test(s)) return 1.5;
  if (/^\d+\^|!$|\^[a-z]/.test(s)) return 6;
  if (/\^3|³/.test(s)) return 5;
  if (/\^2|²/.test(s)) return 4;
  if (/log/.test(s)) return /^(\(?[a-z](\+[a-z])?\)?)\*?log/.test(s) ? 3 : null;
  if (/^\d*[a-z](\/\d+)?([+-]\d*[a-z](\/\d+)?)*$/.test(s)) return 2;
  if (/^[a-z]\*?[a-z]$/.test(s)) return 4;
  return null;
}
function vBigOSaid(text, word) {
  const out = [], find = new RegExp(`(?:${word})(?:\\s*복잡도|\\s*complexity)?(?:\\s*(?:은|는|이|가|:|：|=))?\\s*(?:\\*\\*)?\\s*[\`$]*\\s*O\\(`, "gi");
  for (let m; (m = find.exec(text));) {
    let depth = 1, i = find.lastIndex;
    for (; i < text.length && depth; i++) { if (text[i] === "(") depth++; if (text[i] === ")") depth--; }
    if (!depth) out.push(text.slice(find.lastIndex, i - 1).trim());
  }
  return out;
}
function vBigOPick(answer, whole, word) {
  const key = vBigOSaid(answer, word);
  if (key.length) return key[0];
  const all = [...new Set(vBigOSaid(whole, word).map((x) => x.replace(/\s+/g, "")))];
  return all.length === 1 ? vBigOSaid(whole, word)[0] : null;
}
function vBigO(md, answer, whole) {
  if (md.querySelector(":scope > .v-bigo")) return;
  const time = vBigOPick(answer, whole, "시간|time"), space = vBigOPick(answer, whole, "공간|space");
  const tAt = time != null ? vBigOClass(time) : null, sAt = space != null ? vBigOClass(space) : null;
  if (tAt == null && sAt == null) return;
  const clean = (x) => `O(${String(x).replace(/\\(log|cdot|times|sqrt)/g, "$1 ").replace(/[`$\\{}]/g, "").replace(/\^2/g, "²").replace(/\^3/g, "³").replace(/\s+/g, " ").trim()})`;
  const at = (v) => `${(v / (V_SCALE.length - 1)) * 100}%`;
  const fig = vEl("figure", "v-bigo");
  fig.setAttribute("role", "img");
  fig.setAttribute("aria-label", [tAt != null ? t("Time complexity {o}", { o: clean(time) }) : "", sAt != null ? t("Space complexity {o}", { o: clean(space) }) : ""].filter(Boolean).join(", "));
  const pin = (cls, word, v, said) => `<span class="v-pin ${cls}" style="left:${at(v)}" data-edge="${v >= 5 ? "end" : v <= 0.5 ? "start" : ""}"><b>${word}</b> ${escapeHtml(clean(said))}</span><i class="v-dot ${cls}" style="left:${at(v)}"></i>`;
  fig.innerHTML = `<div class="v-bigo-track">
      <i class="v-rail"></i>${V_SCALE.map((c, i) => `<span class="v-tick${i % 2 ? " minor" : ""}" style="left:${at(i)}" data-edge="${i === 0 ? "start" : i === V_SCALE.length - 1 ? "end" : ""}">${c}</span>`).join("")}
      ${sAt != null ? pin("space", t("Space"), sAt, space) : ""}${tAt != null ? pin("time", t("Time"), tAt, time) : ""}
    </div>`;
  md.prepend(fig);
}
// A table: its figures as bars under them, its verdicts in their colours, and the columns of a comparison told apart
const V_YES = /^(맞음|정답|옳음|참|가능|지원|있음|예|O|○|◯|✓|✔|✅|Yes|True|Correct|Supported)$/i, V_NO = /^(틀림|오답|그름|거짓|불가|불가능|미지원|없음|아니오|아니요|X|×|✗|✘|❌|No|False|Wrong|Incorrect|Unsupported)$/i;
function vTables(md) {
  md.querySelectorAll("table").forEach((table) => {
    if (table.closest(".check-runs, figure") || table.dataset.drawn) return;
    table.dataset.drawn = "1";
    // A column empty from its head down is a slip of the writing: it stood as a coloured strip with nothing in it
    for (let j = Math.max(0, ...[...table.rows].map((r) => r.cells.length)) - 1; j >= 0; j--) {
      if ([...table.rows].every((r) => !r.cells[j]?.textContent.trim() && !r.cells[j]?.querySelector("img, svg"))) [...table.rows].forEach((r) => r.cells[j]?.remove());
    }
    // So is a head row with nothing in any of its cells ("| | |" over a table of names and values): a grey band that said nothing
    const blank = (r) => [...r.cells].every((c) => !c.textContent.trim() && !c.querySelector("img, svg"));
    if (table.tHead && table.tBodies[0]?.rows.length && [...table.tHead.rows].every(blank)) table.tHead.remove();
    const body = [...(table.tBodies[0]?.rows || [])], heads = [...(table.tHead?.rows[0]?.cells || [])];
    if (!body.length) return;
    const cols = Math.max(...body.map((r) => r.cells.length));
    // A comparison: what is compared along the first column and two to four things across the top
    const compare = heads.length >= 3 && heads.length <= 5 && (!heads[0].textContent.trim() || /^(항목|구분|비교|기준|특징|특성|관점|차이|측면|요소|종류|aspect|criteri|feature|item|category|property|dimension)/i.test(heads[0].textContent.trim()));
    if (compare) {
      table.classList.add("v-compare");
      heads.forEach((c) => { if (/^(비고|설명|참고|메모|note|notes|remarks?|comments?)$/i.test(c.textContent.trim())) c.classList.add("v-plain"); });   // not one of the things compared
    }
    for (let j = 0; j < cols; j++) {
      const cells = body.map((r) => r.cells[j]).filter(Boolean);
      if (cells.length < 3 || !cells.every((c) => c.classList.contains("num"))) continue;
      if (/번호|순번|^#$|^no\.?$|^id$|연도|년도|year|버전|version|포트|port/i.test(heads[j]?.textContent.trim() || "")) continue;
      if (!cells.some((c) => /[%‰$₩€£A-Za-zμµ가-힣]/.test(c.textContent))) continue;   // a measure has a unit: plain numbers are the states of a table worked by hand, and their bars read as a column with no name
      const vals = cells.map((c) => parseFloat(c.textContent.replace(/[,\s$₩€£]/g, "").replace(/[−]/g, "-")));
      const max = Math.max(...vals);
      // Numbers that only count the rows off say nothing as bars, and a bar needs a length that starts from nothing
      if (vals.some((v) => !Number.isFinite(v) || v < 0) || max <= 0 || vals.every((v, i) => v === i + 1) || vals.every((v) => v === vals[0])) continue;
      cells.forEach((c, i) => { c.classList.add("v-bar"); c.style.setProperty("--bar", String(vals[i] / max)); });
    }
    for (const r of body) for (const c of r.cells) {
      const t = c.textContent.trim();
      if (V_YES.test(t)) { c.classList.add("v-yes"); if (!compare && /^(맞음|정답|옳음|correct)$/i.test(t) && ![...r.cells].some((x) => V_NO.test(x.textContent.trim()))) r.classList.add("v-right"); }
      else if (V_NO.test(t)) c.classList.add("v-no");
    }
  });
}
// What the answer is made of, as long as each part is: a strip to go by, on an answer of three parts or more
function vMap(md, many) {
  if (md.querySelector(":scope > .v-map")) return;
  const parts = [...md.querySelectorAll(":scope > .qa")];
  if (parts.length < 3 || parts.length > 12 || (many && many === parts.length)) return;
  const nav = vEl("nav", "v-map");
  nav.setAttribute("aria-label", t("The parts of this answer"));
  parts.forEach((part, i) => {
    const head = part.firstElementChild, name = head?.textContent.trim() || `${i + 1}`;
    const b = vEl("button", "v-seg");
    b.type = "button"; b.title = name;
    b.style.flexGrow = String(Math.max(1, Math.round(part.textContent.length / 120)));
    b.append(vEl("span", "v-seg-name", name), vEl("i"));
    b.onclick = () => vGoTo(part);
    nav.append(b);
  });
  md.prepend(nav);
}
function vGoTo(part) {
  stopFollowing();
  autoUntil = Date.now() + 900;
  part.scrollIntoView({ block: "start", behavior: motion() });
}
// Several answers in one key line, each a tile that goes to the part of the working about it
function vAnswerTiles(el, md) {
  const list = el.querySelector(":scope > .row[data-answer] .ans-list, :scope .ans-list");
  if (!list) return 0;
  const tiles = [...list.children], parts = md ? [...md.querySelectorAll(":scope > .qa")] : [];
  tiles.forEach((li) => { const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT); let last = null; for (let n = w.nextNode(); n; n = w.nextNode()) if (n.nodeValue.trim()) last = n; if (last) last.nodeValue = last.nodeValue.replace(/[,，;；]\s*$/, ""); });
  if (parts.length === tiles.length) tiles.forEach((li, i) => { li.classList.add("v-tile"); li.title = t("Go to this part of the solution"); li.tabIndex = 0; li.onclick = () => vGoTo(parts[i]); li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); vGoTo(parts[i]); } }; });
  return tiles.length;
}
function infographics(el) {
  const it = el.matches?.(".entry") ? items.get(idOf(el.dataset.id)) : el.dataset?.turn ? turns.get(idOf(el.dataset.turn)) : null;
  // Kept back by Practice: drawn from the hints shown alone, or a complexity scale would say what the rest of it keeps back
  const head = it ? (el.matches?.(".entry") && held(it) ? { type: it.head.type, answer: "", body: shownText(it) } : splitHead(it.raw || "", true)) : null;
  el.querySelectorAll(".md").forEach((md) => {
    if (md.closest(".ptext, .check-runs") || md.dataset.drawn === "1") return;
    md.dataset.drawn = "1";
    vTerms(md); vStepLeads(md); vFlows(md); vNotes(md); vTables(md);
    const main = md.matches("[data-body]");
    const many = main ? vAnswerTiles(el, md) : 0;
    if (main) vMap(md, many);
    if (main && head && ["algorithm", "coding"].includes(head.type)) vBigO(md, head.answer || "", `${head.answer || ""}\n${head.body || ""}`);
  });
  // The key line, when all it says is a chain
  const key = el.querySelector("[data-aval]");
  if (key && !key.parentElement.querySelector(".v-flow")) {
    const links = vChain(key.textContent.replace(/^\s*[①-⑳]\s*/, ""));
    if (links) key.parentElement.append(vFlow(links));
  }
}
// What is drawn comes in once, the first time it is seen: an answer that goes by unseen, or is drawn again, does not start over
const COME_IN = ".v-terms, .v-flow, .v-bigo, .v-map, .check-runs, .tablewrap, figure.viz";   // not the steps, and not a table's rows: those were watched as they were written
function playIn(p) {
  p.cameIn?.();
  p.classList.add("v-in");
  p.querySelectorAll("td.v-bar").forEach((c) => c.classList.add("v-grow"));
  setTimeout(() => { p.classList.remove("v-in"); p.querySelectorAll(".v-grow").forEach((c) => c.classList.remove("v-grow")); }, 2200);   // done: a chart drawn again at a new width does not play it over
}
const liveDone = new Set(), cameIn = new Map();   // the answers finished since the page opened, and which of their parts have come in
const seenOnce = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((seen) => {
  for (const s of seen) {
    if (!s.isIntersecting) continue;
    seenOnce.unobserve(s.target);
    playIn(s.target);
  }
}, { threshold: 0, rootMargin: "0px 0px -6% 0px" });   // as it comes up over the foot of the window: at a share of its height, a long table went blank in plain view
function comeIn(el) {
  if (!seenOnce || !el?.matches?.(".entry") || calm()) return;
  const id = idOf(el.dataset.id);
  if (!liveDone.has(id)) return;                  // an old answer scrolled to is simply there
  const done = cameIn.get(id) || new Set(), kinds = new Map();
  cameIn.set(id, done);
  el.querySelectorAll(COME_IN).forEach((p) => {
    if (p.closest(".viz-more, .turn")) return;
    const kind = p.classList[0] || p.tagName, n = (kinds.get(kind) || 0) + 1;
    kinds.set(kind, n);
    const key = `${kind}${n}`;                    // by place, not by node: an answer drawn again has new nodes, and it has come in all the same
    if (done.has(key)) return;
    if (p.getBoundingClientRect().height > innerHeight * .9) { done.add(key); return; }   // taller than the window: what is being read does not go away
    // Their order, for the delay of each
    const kids = p.matches(".v-map") ? p.querySelectorAll(".v-seg i") : p.children;
    [...kids].forEach((k, i) => k.style?.setProperty("--n", String(Math.min(i, 16))));
    p.cameIn = () => done.add(key);
    const at = p.getBoundingClientRect();
    if (at.top < innerHeight * .94 && at.bottom > 0) playIn(p);
    else seenOnce.observe(p);
  });
}
// The highlighter goes along the key line of an answer just finished, once: by itself on these nodes, so a redraw does not start it over
function sweepKey(entry) {
  if (!entry || calm()) return;
  entry.querySelectorAll(":scope > .row[data-answer] .hl").forEach((h) => h.animate?.([{ backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%" }], { duration: 700, easing: "cubic-bezier(.3, .6, .3, 1)" }));
}
function enhance(el) {   // once an answer is final: pictures, math, tables, code highlight, copy buttons
  // A short line that is all bold is a heading the model wrote as bold: it reads as one
  el.querySelectorAll?.("p").forEach((p) => {
    if (p.parentElement !== el && !p.parentElement.classList.contains("md")) return;
    const only = p.childNodes.length === 1 && p.firstChild.nodeName === "STRONG";
    p.classList.toggle("para-head", only && p.textContent.length <= 60);
  });
  // ```chart and ```mermaid blocks become pictures before the code blocks get their bars below.
  drawPictures(el);
  textStyle(el);
  groupAnswers(el);
  infographics(el);
  comeIn(el);
  typesetMath(el);
  // Each table's bar gets its copy button in the place kept for it (tableBar).
  el.querySelectorAll(".tablewrap > .codebar > .wait").forEach((wait) => {
    const table = wait.closest(".tablewrap").querySelector(":scope > .tablescroll > table");
    if (!table) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn sm copy";                          // the code block's button, the same size and look
    b.innerHTML = COPY_MARK + `<span>${t("Copy")}</span>`;
    b.title = t("Copy the table: a table in Excel and documents, tab-separated text in Notepad");
    b.onclick = () => copyTable(table, b);                // copy, then say so on the button itself
    wait.replaceWith(b);
  });
  // A code block from the markdown is a <pre> holding a <code>, and only that gets the bar. The other
  // <pre>s in an entry are messages kept as they were written: Problem text (it has its own copy button in the
  // head), the failed examples of the check and the error details. Given the bar they read as code with
  // "Code" over them, and a failed example lost its padding, which a code block keeps on its <code>.
  el.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector(":scope > code");
    if (!code) return;                                    // a message, not code: left as it is
    if (code.dataset.lang === undefined) code.dataset.lang = fenceLang(code);
    if (!code.classList.contains("lined")) {              // once per block: lined, it is no longer plain code
      if (!code.dataset.lang && isCommand(code, code.textContent)) code.classList.add("language-bash");   // as in the live drawing above
      if (window.hljs) { try { window.hljs.highlightElement(code); } catch (_) {} }
      lineCode(code);                                     // numbered lines that wrap, with indent guides
    }
    // the hover over built-in and library functions, once per block (a block lined while it was written has none yet)
    if (!code.dataset.docs) { code.dataset.docs = "1"; docTips(code); }
    // The bar of a block lined while it was written holds "Writing" where the buttons go: it gives way to them now.
    const had = pre.querySelector(":scope > .codebar");
    if (had && !had.querySelector(".wait")) return;
    had?.remove();
    // A bar of its own above the code: the language on the left, the buttons on the right, so the
    // copy button no longer floats over the first line of the answer.
    const bar = document.createElement("div");
    bar.className = "codebar";
    const lang = document.createElement("span");
    lang.className = "lang";
    lang.textContent = isCommand(code, code.textContent) ? t("Command") : own(LANG_LABEL, code.dataset.lang) || code.dataset.lang || t("Code");
    const b = document.createElement("button");           // one button, built once per block
    b.type = "button";                                    // inside no form, but say so anyway
    b.className = "btn sm copy";                          // bordered: a ghost here read as a label
    b.innerHTML = COPY_MARK + `<span>${t("Copy")}</span>`;  // the mark first, then the word for it
    b.title = t("Copy this code to the clipboard");          // the same thing in full, on hover
    b.onclick = () => copyCode(code, b);                  // copy, then say so on the button itself
    bar.append(lang, b);
    pre.insertBefore(bar, pre.firstChild);
  });
  captionFigures(el);
  // A runnable code block gets a "Run" button that runs it in the isolated runner and shows the
  // real output right under it, so the user can check the solution against an actual run.
  if (status.runEnabled) el.querySelectorAll("pre > code").forEach(addRunBox);
}
// A picture's caption: its first child, at the top of its frame. Drawn again whenever the picture is
function figureTitle(fig) {
  const text = fig.dataset.caption;
  if (!text) return;
  let cap = fig.querySelector(":scope > .viz-title");
  if (!cap) { cap = document.createElement("figcaption"); cap.className = "viz-title"; fig.prepend(cap); }
  capInto(cap, text);
}
// "그림 1. 무엇": the number in the ink, the words after it
const FIGURE_NUM = new RegExp(`^(${t("Figure {n}", { n: "\\d+" })}\\.?)\\s*(.*)$`);   // the panel's own "Figure 1." (captionFigures)
function capInto(cap, text) {
  const m = FIGURE_NUM.exec(text);
  if (m) cap.replaceChildren(Object.assign(document.createElement("b"), { textContent: m[1] }), m[2] ? ` ${m[2]}` : "");
  else cap.textContent = text;
}
// What a heading says of the thing under it: not its detail in brackets ("예제 검증 (P = 7 2 1)"), and nothing when all it says is what the thing is ("코드 (Python)" over a program)
const capWords = (t) => { const w = String(t).trim(); return /^(코드|code|소스\s*코드|표|그림|명령어?)(\s*[(（][^()（）]*[)）])?$/i.test(w) ? "" : w; };
// A formula as it was written, for a caption: what KaTeX draws comes out of the page with its marks lost ("x^2" as "x2")
const texWords = (tex) => tex.replace(/\^\{?2\}?/g, "²").replace(/\^\{?3\}?/g, "³").replace(/\\[a-zA-Z]+/g, (m) => `${m.slice(1)} `).replace(/[{}$]/g, "").replace(/\s+/g, " ").trim();
// Every table, picture, program and command of an answer is numbered and says what it is, as in a paper: "표 1. 대기 시간".
// What it is comes from the heading it stands under, or a short line ending in a colon just before it; failing those, from itself.
// What a diagram is, by what mermaid is told to draw
function diagramName(src) {
  const first = String(src || "").trim().split(/\s+/)[0]?.toLowerCase() || "";
  if (!first) return "";
  return /^(flowchart|graph)/.test(first) ? t("Flowchart") : /^sequence/.test(first) ? t("Sequence diagram") : /^class/.test(first) ? t("Class diagram") : /^state/.test(first) ? t("State diagram") : /^er/.test(first) ? t("ER diagram") : /^gantt/.test(first) ? t("Schedule") : /^pie/.test(first) ? t("Pie chart") : /^mindmap/.test(first) ? t("Mind map") : t("Schematic");
}
// What a program is when the heading over it says only that it is one ("코드 (Python)" gave "코드 1. Python" for every program): the first function or
// class it defines that is not an entry point or a judge's wrapper, else the comment it opens with, so the caption gives the number and then what the program is
// A comment line, and not a C preprocessor line ("#include") or a shebang ("#!"), which a bare "#" took for one
const COMMENT_LINE = /^[ \t]*(?:#(?![!a-z])|\/\/)[ \t]*(.{4,60}?)[ \t]*$/;
const capWordsOf = (w) => { w = w.trim().replace(/[.。]\s*$/, "").replace(/(입니다|합니다|한다)$/, "").trim(); return w.length > 40 ? `${w.slice(0, 39)}…` : w; };
function codeTopic(text) {
  const generic = /^(main|Main|Solution|solution|solve|run)$/;
  const found = [];
  for (const re of [/^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(/gm, /^\s*class\s+([A-Za-z_]\w*)/gm, /\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/g,
    /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(/g, /\b(?:fun|func)\s+([A-Za-z_]\w*)\s*\(/g,
    /^\s*(?:(?:public|private|protected|static|final|inline|virtual|const)\s+)*[A-Za-z_][\w:<>,\[\]*&\s]*?\s[*&]?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{/gm]) {
    // where the definition's own line starts: a match takes in the blank lines over it, and the lines next to it are read below
    for (const m of text.matchAll(re)) found.push({ at: m.index + Math.max(0, m[0].search(/\S/)), name: m[1], cls: /^\s*class\b/.test(m[0]) });
  }
  found.sort((a, b) => a.at - b.at);
  const real = found.filter((f) => !/^(if|for|while|switch|return|catch)$/.test(f.name));
  // A program whose first definition is the judge's own wrapper (solution, main) is about what that wrapper says of itself: its docstring, or
  // a comment on the line right under it or right over it. A helper defined inside it named the program after a detail ("time_to_minutes
  // 함수"); a comment further in is about a step ("# edge case: empty input", "// read the grid") and names nothing
  const said = (from) => {
    const rest = text.slice(from);
    const doc = /^[^\n]*\n\s*(?:"""|'''|\/\*\*?)\s*\n?\s*([^\n"*]{4,60})/.exec(rest)
      || COMMENT_LINE.exec(rest.split("\n")[1] || "") || COMMENT_LINE.exec(text.slice(0, from).replace(/\s+$/, "").split("\n").pop() || "");
    return doc ? capWordsOf(doc[1]) : "";
  };
  if (real.length && generic.test(real[0].name)) { const w = said(real[0].at); if (w) return w; }
  const pick = real.find((f) => !generic.test(f.name));
  if (pick) return pick.cls ? t("{name} class", { name: pick.name }) : t("{name} function", { name: pick.name });
  // Nothing it defines to go by: the comment it opens with, past its includes and imports
  const head = text.split("\n").find((l) => l.trim() && !/^\s*(?:#\s*(?:include|define|pragma|import|if|ifdef|ifndef|endif)\b|#!|using\s|import\s|from\s+\S+\s+import\s|package\s)/.test(l));
  const note = head ? COMMENT_LINE.exec(head) : null;
  return note ? capWordsOf(note[1]) : "";
}
function captionFigures(el) {
  // Over the whole answer and what was asked after it: "표 1" stood twice on one page
  const whole = el.closest?.(".entry") || el;
  const n = { table: 0, figure: 0, code: 0, command: 0 };
  [...(whole.matches?.(".md") ? [whole] : []), ...whole.querySelectorAll(".md")].forEach((md) => {
    const about = (node) => {
      // Inside a step or a named item: it goes by that, and steps under one heading are not all called the same
      const item = node.closest?.("li");
      const lead = item && md.contains(item) ? item.querySelector(":scope > .v-t, :scope > strong, :scope > p:first-child > strong") : null;
      if (lead) return capWords(lead.textContent.trim().replace(/[:：]$/, ""));
      let c = node;
      while (c.parentElement && c.parentElement !== md && !c.parentElement.classList.contains("qa")) c = c.parentElement;
      for (let p = c.previousElementSibling; p; p = p.previousElementSibling) {
        const shown = p.cloneNode(true);
        shown.querySelectorAll(".katex").forEach((x) => x.replaceWith(texWords(x.querySelector("annotation")?.textContent || x.textContent)));   // what a formula keeps for screen readers: its heading came out in three copies
        shown.querySelectorAll(".sr-only").forEach((x) => x.remove());
        const t = shown.textContent.trim();
        if (p.matches("h1, h2, h3, h4, p.lead, p.para-head")) return capWords(t.replace(QA_HEAD, "").replace(/^[\s.:)]+/, ""));
        // A paragraph led by its words in bold ("**단계 2: 공간 확보** ...") names what follows it, however long the rest: the scan
        // went past it and took a line further up about something else. Only a bold lead that is a label, though: one with a colon or a
        // full stop in it or right after it, or the whole paragraph. A sentence's own bold subject ("**The side that opens the
        // connection** sends SYN ...") names nothing, and the heading above it does
        const lead = p.matches("p") ? p.querySelector(":scope > strong:first-child") : null;
        const leadText = lead ? lead.textContent.trim() : "", after = lead ? t.slice(t.indexOf(leadText) + leadText.length).trimStart() : "";
        const label = lead && (/[:：.]/.test(leadText) || /^[:：.—–-]/.test(after) || !after);
        if (label && t.startsWith(leadText.slice(0, 4))) return capWords(leadText.replace(/[:：.]\s*$/, ""));
        // A short line ending in a colon names what follows it, when it is one phrase: "It keeps the order. As a picture:" is two
        // sentences leading in, and the heading names it better
        const said = t.replace(/[:：]$/, "");
        if (p.matches("p") && t.length <= 48 && /[:：]$/.test(t) && !/[.!?。](\s|$)/.test(said)) return capWords(said);
      }
      return "";
    };
    // The number in the ink, what it is after it
    const capText = (label, num, words) => {
      label.replaceChildren(Object.assign(document.createElement("b"), { textContent: words ? `${num}.` : num }), words ? ` ${words}` : "");
      label.title = label.textContent;
    };
    md.querySelectorAll(".tablewrap, figure.viz, pre > code").forEach((node) => {
      if (node.closest(".check-runs, .viz-more") || (node.matches("code") && node.closest("figure"))) return;
      if (node.matches(".tablewrap")) {
        if (node.closest("figure")) return;   // a chart's own table of its figures
        const label = node.querySelector(":scope > .codebar .lang");
        if (!label) return;
        const heads = [...node.querySelectorAll("thead th")].map((h) => h.textContent.trim()).filter(Boolean).slice(0, 4).join(", ");
        capText(label, t("Table {n}", { n: ++n.table }), about(node) || heads);
      } else if (node.matches("figure")) {
        // What the picture calls itself says more than the heading it stands under
        const words = chartSpecs.get(node)?.title || about(node) || diagramName(diagramSources.get(node));
        node.dataset.caption = words ? `${t("Figure {n}", { n: ++n.figure })}. ${words}` : t("Figure {n}", { n: ++n.figure });
        figureTitle(node);
      } else {
        const label = node.parentElement.querySelector(":scope > .codebar .lang");
        if (!label) return;
        label.dataset.base ??= label.textContent;
        const command = node.classList.contains("shell");   // lineCode's verdict: what the copy holds has lost its prompts
        const kind = command ? "command" : "code";
        const lang = command || [t("Code"), t("Command"), t("Text")].includes(label.dataset.base) ? "" : `${label.dataset.base}: `;
        const program = command ? commandName(codeText(node)) : codeTopic(codeText(node));
        capText(label, command ? t("Command {n}", { n: ++n[kind] }) : t("Code {n}", { n: ++n[kind] }), `${lang}${about(node) || program}`.replace(/:\s*$/, "").trim());
      }
    });
  });
}
// The program a command block runs, for its caption: the first word of its first line that is not a comment, past what only
// wraps a command (sudo, env, time, nohup and the like, a VAR=value, and a wrapper's own options). "sudo lsof | grep deleted"
// is lsof, and a block opened by "# what this does" goes by its command: they said "명령어 1. sudo" and "명령어 2. #".
const WRAPPERS = new Set(["sudo", "doas", "env", "time", "nohup", "exec", "command", "nice"]);
function commandName(text) {
  const line = text.split("\n").map((l) => l.replace(/^\s*\$\s*/, "").trim()).find((l) => l && !/^(#|\/\/)/.test(l)) || "";
  const words = line.split(/\s+/);
  let i = 0, wrapped = false;
  while (i < words.length - 1 && (WRAPPERS.has(words[i]) || /^[A-Za-z_]\w*=/.test(words[i]) || (wrapped && words[i].startsWith("-")))) {
    wrapped = wrapped || WRAPPERS.has(words[i]);
    i++;
  }
  return words[i] || "";
}
// "TYPE: x", then optional "ANSWER: y" and "REGION: ..." head lines (REGION is for the server:
// where the problem is on screen). While streaming, a head line still arriving is held back so
// it never flashes as body text ("TYP", "ANS") or as half a type ("m" of mcq).
// Where the head (TYPE line) starts: the first line, or after a preamble of at most three lines the
// model sometimes adds although told not to. A TYPE further down, or after a code block, is content
// (YAML "type: none", code). Same rule as the server's head_start.
function headStart(body) {
  let off = 0, seen = 0;
  for (const line of body.split("\n")) {
    if (line.trim()) {
      if (line.trimStart().startsWith("```")) return -1;
      if (/^[^\S\n]*TYPE:[^\S\n]*[A-Za-z_]+/.test(line)) return off;
      if (++seen >= 4) return -1;
    }
    off += line.length + 1;
  }
  return -1;
}
function splitHead(text, final = false) {
  let type = null, answer = null, asked = null, body = text.replace(/^\s+/, "");
  const t = headStart(body);
  if (t > 0) body = body.slice(t).replace(/^\s+/, "");
  const held = (s, word) => !final && !s.includes("\n") && (word.startsWith(s) || s.startsWith(word));
  if (held(body, "TYPE:")) return { type, answer, body: "" };
  const m = body.match(/^TYPE:[^\S\n]*([a-zA-Z_]+)[^\n]*\n?/);
  if (m) { type = m[1].toLowerCase(); body = body.slice(m[0].length).replace(/^\s+/, ""); }
  const a = body.match(/^ANSWER:[^\S\n]*(.*)\n?/);
  if (a) { answer = a[1].trim(); body = body.slice(a[0].length); }
  else if (held(body, "ANSWER:")) body = "";
  // the last head lines, in either order: the region (the server's) and what the problem asks, in one Korean
  // line whatever language it is in itself (the server's asked_of is the twin)
  for (let k = 0; k < 2; k++) {
    const r = body.match(/^\s*REGION:[^\n]*\n?/);
    if (r) { body = body.slice(r[0].length); continue; }
    const q = body.match(/^\s*ASKED:[^\S\n]*(.*)\n?/);
    if (q) { asked = q[1].trim(); body = body.slice(q[0].length); continue; }
    if (held(body.replace(/^\s+/, ""), "REGION:") || held(body.replace(/^\s+/, ""), "ASKED:")) body = "";
    break;
  }
  return { type, answer, asked, body };
}

// An answer line as plain text: for the index, the copy button and the screen-reader note.
function texPlain(t) {
  return t.replace(/\\(?:begin|end)\s*\{[^{}]*\}/g, " ").replace(/\\\\/g, " ").replace(/&/g, "").replace(/\\(?:d|t)?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, "$1/$2").replace(/\\sqrt\s*\{([^{}]*)\}/g, "√$1")
    .replace(/\\(?:left|right)\b/g, "").replace(/\\times\b/g, "×").replace(/\\cdot\b/g, "·").replace(/\\(?:le|leq)\b/g, "≤")
    .replace(/\\(?:ge|geq)\b/g, "≥").replace(/\\(?:ne|neq)\b/g, "≠").replace(/\\infty\b/g, "∞").replace(/\\pi\b/g, "π")
    .replace(/\\(log|ln|sin|cos|tan|max|min)\b/g, "$1").replace(/\\[,;:! ]/g, " ").replace(/\\int(?![A-Za-z])/g, "∫").replace(/\\sum(?![A-Za-z])/g, "Σ").replace(/\\sqrt(?![A-Za-z])/g, "√").replace(/\\[A-Za-z]+/g, "").replace(/[{}]/g, "").replace(/\s+/g, " ").trim();
}
// The line as the page draws it (inline Markdown): only the marks drawn away go, the emphasis, the code ticks and a formula's
// dollars. A "#", ">" or "|" is what was written (C#, i >= n, ps aux | grep), so the copy key gives it as it stands.
// `block`: a line of the body, whose own marks open it (a heading's hashes, a quote's ">", a table row's bars), for the contents.
function plainAnswer(md, block = false) {
  const code = [];
  // code spans first, kept as written without their ticks: nothing inside one is a mark
  let s = String(md || "").replace(/`([^`\n]*)`/g, (_, c) => `\u0000${code.push(c) - 1}\u0000`);
  s = s.replace(/\$\$([^$]+)\$\$|\$([^$]+)\$/g, (_, a, b) => texPlain(a || b))
    // a pair of ** or __ round words is emphasis; a lone one (2 ** 10) is drawn as it is
    .replace(/(\*\*|__)(?=\S)(.*?\S)\1/g, "$2").replace(/(^|\s)[*_]([^*_\s][^*_]*)[*_](?=\s|$)/g, "$1$2");
  if (block) {
    // the marks that open a block, at the start of its line only
    s = s.replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, "").replace(/^[ \t]{0,3}>[ \t]?/gm, "")
      .replace(/^[ \t]*\|(.*)\|[ \t]*$/gm, (_, cells) => cells.replace(/\|/g, " "));
  }
  // the code spans back in, then one line
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => code[+i]).replace(/\s+/g, " ").trim();
}
function announce(text) {   // one short line per finished answer for screen readers (the notebook is not live)
  const n = $("live-note"); if (!n) return;
  n.textContent = ""; requestAnimationFrame(() => { n.textContent = text; });
}

// ---------- state ----------
const items = new Map();      // screen/voice analyses by id
const turns = new Map();      // follow-up answers by id
let thread = [];              // ids of the entries on the page, oldest first
let viewId = null;            // the entry in view (its screen goes in the rail)
let stick = true;             // keep following the newest at the bottom (off while reading above)
const unfolded = new Set();   // older entries opened by hand
const KEEP_OPEN = 3;          // the newest entries stay open; older ones fold to their answer line
let sock = null, paused = false;
let wsState = "connecting";   // connecting | up | down; "down" only after an attempt failed
let status = { engines: null, audio: false, voice: false, lang: null, canAsk: false, runEnabled: false, runner: false };
let settingsMeta = null;            // the settings sheet: sections and items, from the server
const settingsValues = {};          // current values (the server confirms each change)
const confirms = new Map();         // cid -> what would go to the agent, waiting for Send / Do not send
let drawing = null;                 // drawing a box on the screen thumbnail: { url, start, box }
let gpuPending = false;             // a GPU key was pressed and the server has not said yet what became of it
const GPU_WAIT_MS = 15000;
const PAGE_ID = Math.random().toString(36).slice(2, 8);   // run ids differ between panels and reloads
let runSeq = 0;
const runState = new Map();           // run box key -> { stdin, stdinOpen, cls, out, stat, pending }
const runOwners = new Map();          // run id waiting for its result -> run box key
let capture = { clients: null, last_frame: null, last_audio: null, screen_on: true, audio_on: true, caps: {} };
// How far this browser's clock is ahead of the server's, in seconds. Every age in the rail is a
// server stamp, and reading it against Date.now() alone was wrong by whatever the two differ by.
let clockSkew = 0;
const serverNow = () => Date.now() / 1000 - clockSkew;
let usage = null;
let buildAtLoad = null;   // which build this page came from; a later one means a reload is due
let lastNone = null;          // { ts, voice }: when the screen (or what was heard) last had nothing to solve
let demo = false;

function newItem(m) {
  return { id: m.id, trigger: m.trigger || "screen", transcript: m.transcript || "", pages: m.pages || 0,
    thumb: m.thumb || null, region: null, ts: Date.now(), raw: "", head: { type: null, answer: null, body: "" },
    live: true, shown: false, error: null, hint: "", meta: null, turns: [], fresh: false, stage: null, check: null };
}
const latestId = () => thread[thread.length - 1] ?? null;

// ---------- status: header signals, the connection card, notes ----------
// A card answers four questions in order: is it working, what is it running on, what does
// it do with what it sees, and is there anything I should do about it. Prose said all of that in
// one paragraph and said some of it three times ("Solves every problem found. ... This PC's model is
// off, so the agent solves everything for now."), so each card is a state, a few facts and at most one
// note now.
// One shape for every card in the rail, so the renderer below never has to know which card it is
// drawing: `s` is the state's colour (ok | warn | bad | off | idle), `pill` the word for it,
// `facts` the label/value rows, `note` the one thing to do about it.
// The agent's card as a picture (index.html, .agent-viz). The facts stay on the card object: the signal's tooltip reads them.
function agentViz(C, pay, forced) {
  const A = C.account || {}, plan = A.plan || C.plan || "";
  const planWord = plan ? `${plan.charAt(0).toUpperCase()}${plan.slice(1)}` : "";
  const name = A.email || (C.method === "api-key" ? t("Connected with an API key") : t("This PC's sign-in"));
  const how = [C.product || AG(), planWord].filter(Boolean).join(" ");
  const scale = (label, order, at, word, warn) => `<div class="agent-scale${warn ? " warn" : ""}"><div class="t"><span>${label}</span><b title="${word}">${word}</b></div>
    <div class="steps3" role="img" aria-label="${label}: ${word}">${order.map((_, i) => `<i class="${i <= at ? "on" : ""}"></i>`).join("")}</div></div>`;
  const modes = ["verify", "hard", "all"], pays = ["text", "crop", "screen"];
  return `<div class="agent-viz">
    <div class="agent-who"><span class="ava" aria-hidden="true">${escapeHtml(name.charAt(0).toUpperCase())}</span>
      <span class="mail" title="${escapeHtml(name)}">${escapeHtml(name)}</span><span class="how" title="${escapeHtml(how)}">${planWord
        // the product's name in its own span: folded to one line (snug), the card's title says it already and the plan alone stays whole
        ? `<span class="prod">${escapeHtml(C.product || AG())} </span>${escapeHtml(planWord)}` : escapeHtml(how)}</span></div>
    ${quotaHtml(C)}
    ${scale(t("Takes"), modes, modes.indexOf(C.effective), MODE_TEXT[C.effective] || "", false)}
    ${scale(t("Sends"), pays, pays.indexOf(pay), escapeHtml(payloadName(pay)), forced)}
      </div>`;
}
// The plan's usage, read by the server where Claude Code's own /usage reads it: the five-hour session and the week, each a meter of the share
// used in the agent's colour, amber from three quarters and red from nine tenths, and when it starts again. It shows the usage itself, not
// what is left. A session not running has used nothing. Nothing from a server that does not read it
function quotaHtml(C) {
  const q = C.quota;
  if (!q || (!q.session && !q.week && !(q.models || []).length && q.at == null)) return "";
  const now = serverNow();
  // A window whose reset has passed runs again only once it is used, as the usage address says of it (none): the share read before the
  // reset no longer holds, and it stood at that share "1분 뒤 초기화" for as long as no new reading came
  const live = (w) => (w && w.resets && w.resets <= now ? null : w);
  // A reading grown old (the login's token ran out while Claude Code was not used, or the address did not answer) is drawn faint, with its age
  const age = q.at ? Math.max(0, now - q.at) : 0, old = age >= 600;
  const row = (key, name, w0, what) => {
    const w = live(w0);
    const used = Math.max(0, Math.min(100, Math.round(w ? w.used : 0)));
    const tone = used >= 90 ? " bad" : used >= 75 ? " warn" : "";
    // when it starts again: in days on a week, in hours and minutes inside one, the clock time in the tooltip
    const secs = w && w.resets ? Math.max(0, w.resets - serverNow()) : null;
    const again = !w ? t("Not started") : secs == null ? "" : secs >= 86400 ? t("Resets in {n} d", { n: Math.floor(secs / 86400) }) : t("Resets in {left}", { left: restLeft(w.resets) });
    const tip = t("{what}: {used}% used", { what, used }) + (w && w.resets ? t(", resets {when}", { when: fmtWhen(w.resets * 1000) }) : !w ? t(", 5 hours from the first use") : "")
      + (old ? t(" (read {ago})", { ago: fmtAgo(age) }) : "");
    return `<div class="quota${tone}${old ? " old" : ""}" data-k="${key}" title="${escapeHtml(tip)}"><span class="q-k">${escapeHtml(name)}</span>`
      + `<span class="q-bar" role="img" aria-label="${escapeHtml(t("{name} {used}% used", { name, used }))}"><i style="width:${used}%" data-fill="${used}"></i></span>`
      + `<span class="q-v">${t("{pct} used", { pct: `<b>${used}%</b>` })}${again ? `<span class="sub"> · ${again}</span>` : ""}</span></div>`;
  };
  return `<div class="quotas">${row("session", t("Session"), q.session, t("5-hour session limit"))}${row("week", t("Week"), q.week, t("Weekly limit (all models)"))}`
    + `${(q.models || []).filter(live).map((m, i) => row(`m${i}`, m.name, m, t("{name} weekly limit", { name: m.name }))).join("")}</div>`;
}
// What each meter last showed: a redraw that changed nothing leaves it still, a new share runs from the old one, the first from empty
const quotaShown = new Map();
function growQuotas() {
  for (const q of document.querySelectorAll("#st-agent .quota")) {
    const bar = q.querySelector(".q-bar > i");
    if (!bar || bar.dataset.ran) continue;   // an element that has run already: the card was not redrawn
    bar.dataset.ran = "1";
    const to = Number(bar.dataset.fill), from = quotaShown.has(q.dataset.k) ? quotaShown.get(q.dataset.k) : 0;
    quotaShown.set(q.dataset.k, to);
    if (from === to || calm()) continue;
    bar.style.transition = "none";
    bar.style.width = `${from}%`;
    bar.getBoundingClientRect();             // the old share drawn once, so the change runs from it
    bar.style.transition = "";
    bar.style.width = `${to}%`;
  }
}
function card(s, pill, facts, note = "") {
  // A fact with no value is dropped here rather than at every call site: whether a card knows its
  // model, its device or its monitor depends on what the server has sent so far.
  return { s, pill, facts: facts.filter(([, v]) => v), note };
}
function screenState() {
  const caps = capture.caps || {};
  // No socket, or no capture message yet: nothing is known, so nothing is claimed.
  if (wsState !== "up" || capture.clients == null) return card("idle", t("Checking"), []);
  // The switch may be on, but with no program connected nothing is being received at all; the one
  // thing worth saying is how to start it.
  if (capture.clients === 0) {
    // started on the PC whose screen it reads, the server's own only in the default set-up (a server, with the capture PC as its client).
    // In the desktop app the tray icon is the capture program's own, gone with it: the app is quit and started again
    // The pill is a word or two: its column beside the switch has some 120 px at 1366
    return card("idle", t("Program off"), [], status.desktop
      ? t("The capture program stopped · quit Sidenote and start it again")
      : t("Run {cmd} on the capture PC", { cmd: `<code class="cmd">./sidenote capture</code>` }));
  }
  // Switched off here in the panel: the monitor still matters, because it is what will be read
  // again the moment it goes back on.
  if (!capture.screen_on) return card("off", t("Off"), [[t("Monitor"), monitorText()]], t("Turn it on to receive again"));
  // The age is a server stamp, so it is read against the server's clock (serverNow), not this
  // browser's. Null when no frame has arrived yet, which is not an error, only a quiet start.
  const age = capture.last_frame ? fmtAgo(serverNow() - capture.last_frame) : null;
  const facts = [[t("Monitor"), monitorText()], [t("Last screen"), age || t("When the screen changes")]];
  // A window of Skip windows is on screen, so the capture program sends nothing: said as a caution, and never which
  // window (its title stays in that program). It goes on by itself once the window is gone
  if (caps.skipping) return card("warn", t("Skipped window"), facts, t("No screen is sent while it shows · Skip windows in Solver settings"));
  // Screens are going out, and the list in the settings cannot do all it says here: a list that looks in force and is not is
  // worse than none. The program clears this with an empty list, where there is nothing to look for
  if (caps.skip_limit === "none") return card("warn", t("Windows not skipped"), facts, t("This desktop does not say which windows are open · Turn the screen off while a private window shows"));
  if (caps.skip_limit === "front") return card("warn", t("Front window only"), facts, t("This desktop does not list the windows behind the front one · Turn the screen off while a private window shows"));
  // The watching slowed itself down: every answer in a row found nothing, so this is somebody
  // working rather than a problem waiting. A tool that quietly looks less often is worse than one
  // that keeps asking, so the card says it while it holds and says what brings it back.
  if (capture.quiet_sec) {
    return card("ok", t("Watching quietly"), facts,
      t("No problem {n} times in a row · small changes checked every {s} s. A window switch, a question or Reanalyze brings it back",
        { n: capture.empty_run, s: Math.round(capture.quiet_sec) }));
  }
  return card("ok", t("Receiving"), facts);
}
// Which screen is being watched. It decides everything the tool sees, and a problem on the other
// monitor is simply never read, so it is said where the capture is reported.
function monitorText() {
  const caps = capture.caps || {};
  const chosen = settingsValues.monitor ?? caps.monitor;
  const sizes = Array.isArray(caps.monitors) ? caps.monitors : [];
  if (chosen === 0) return sizes.length ? t("All monitors ({n})", { n: sizes.length }) : t("All monitors");
  if (!chosen) return "";
  const size = sizes[chosen - 1];
  return `${t("#{n}", { n: chosen })}${size ? ` ${size[0]}x${size[1]}` : ""}`;
}
const LANG_FULL = { ko: t("Korean"), en: t("English"), auto: t("Auto") };
function audioState() {
  const caps = capture.caps || {};
  const device = caps.audio_device ? escapeHtml(caps.audio_device) : "";
  const lang = LANG_FULL[status.lang] || "";
  if (wsState !== "up" || capture.clients == null) return card("idle", t("Checking"), []);
  // The server itself has transcription off: no switch here can change that.
  if (!status.audio) return card("off", t("Off on the server"), [], t("Start it with {cmd} to listen", { cmd: "<code class=\"cmd\">SIDENOTE_AUDIO=1</code>" }));
  // Said by the screen card too, and once is enough: no note here.
  if (capture.clients === 0) return card("idle", t("Program off"), []);
  // Started with --no-audio: the program never opened a device, so the panel's switch is moot.
  if (caps.no_audio) return card("off", t("No sound"), [], t("The capture was started with {cmd}", { cmd: "<code class=\"cmd\">--no-audio</code>" }));
  if (caps.audio === false) {
    return card("warn", t("Device error"), [[t("Device"), device || t("Not found")]],
      t("Check the speakers and microphone, then restart the capture"));
  }
  if (!capture.audio_on) return card("off", t("Off"), [[t("Device"), device]], t("Turn it on to take spoken problems too"));
  const age = capture.last_audio ? serverNow() - capture.last_audio : null;
  return card(age != null && age < 15 ? "ok" : "ok", age != null && age < 15 ? t("Listening") : t("On"),
    [[t("Device"), device], [t("Language"), lang], [t("Last sound"), age == null ? t("None yet") : fmtAgo(age)]]);
}
const eng = () => status.engines;
// The word for the cloud agent in the panel's sentences; which product it is is on its card (agentState: product).
function AG() { return status?.engines?.agent?.label || t("Agent"); }
// The same word for where room is short (the header's signal, a settings tab).
function AGS() { return status?.engines?.agent?.short || AG(); }
// What signs that agent in on the PC (./sidenote login, ./sidenote login codex), as the server gives it.
function LOGIN() { return status?.engines?.agent?.login || "./sidenote login"; }
const localTrouble = (L) => (L.missing ? (L.pull ? t("No local model yet") : t("Model {model} missing", { model: escapeHtml(L.model || "") }))
  : t("The local model does not respond"));
// Which command actually helps: pull a model that was never downloaded, look at a server that is
// there but not answering. The rail and the alert band must not disagree about this.
const localFix = (L) => (L && L.missing ? "./sidenote llm pull" : "./sidenote doctor");
// Why this PC's model, switched off, answers for now (engines.local.stand_in)
const STAND_IN_TEXT = { get limit() { return t("The agent reached its usage limit", { agent: AG() }); }, get signin() { return t("The agent is signed out", { agent: AG() }); },
  get brake() { return t("The agent reached its hourly cost limit", { agent: AG() }); } };
// How long until the agent may be asked again after its plan's limit (engines.agent.limit_until, the server's clock):
// "2일 4시간", "3시간 20분", "12분"
function restLeft(until) {
  // whole minutes first, rounded up, then split: rounding the minutes alone said "3시간 60분" at 3 h 59 m 30 s
  const mins = Math.ceil(Math.max(0, until - serverNow()) / 60), d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  return d ? t("{d} d {h} h", { d, h }) : h ? t("{h} h {m} min", { h, m }) : t("{m} min", { m: Math.max(1, m) });
}
// The time it gives, in everyday terms: "11월 3일 03:00"
function restAt(until) {
  return fmtWhen(until * 1000);
}
// Where a load has got to, under the Cancel key. Ollama says nothing while it loads, so this is read from what can be seen: the time, and
// the GPU's memory filling once the file has been read.
let loadSeen = null, gpuLast = null;
function loadStepsHtml() {
  loadSeen ??= { at: Date.now(), from: gpuLast?.used ?? null };
  const grew = gpuLast && loadSeen.from != null ? gpuLast.used - loadSeen.from : 0;
  const at = grew > 512 ? 2 : 1;           // half a gigabyte: the model has begun to arrive, past what anything else moves it by
  const steps = [t("Request"), t("Read file"), t("Load to GPU"), t("Ready")];
  return `<span class="load-steps">${steps.map((s, i) => `<span class="${i < at ? "done" : i === at ? "now" : ""}">${s}</span>`).join("")}</span>`
    + `<span class="load-now">${t("{n} s", { n: Math.round((Date.now() - loadSeen.at) / 1000) })}${gpuLast ? t(" · GPU memory {gb} GB", { gb: (gpuLast.used / 1024).toFixed(1) }) : ""}</span>`;
}
// The model download the desktop app offers (engines.local.pull, the server's SIDENOTE_LOCAL_PULL): the model for this
// GPU, fetched through Ollama when its key is pressed, and how far it got (the server's llm_pull messages).
let pullNow = null;
const OLLAMA_LINK = `<a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">ollama.com/download</a>`;
function pullNote(p) {
  if (p.status === "tuning") return t("Preparing the model for Sidenote");
  if (!p.total) return t("Starting the download");
  const pct = Math.floor((100 * p.completed) / p.total);
  return `<span class="pull-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></span>`
    + t("{done} of {total} GB", { done: (p.completed / 1e9).toFixed(1), total: (p.total / 1e9).toFixed(1) });
}
// What the card and the alert band offer for a missing model: which one and why, and the key that downloads it
function pullOffer(L) {
  const name = (L.want || [])[0];
  if (!name) return "";
  const size = L.want_gb ? t(", about {gb} GB to download", { gb: L.want_gb }) : "";
  const why = L.fits === false
    ? (eng()?.agent?.ok ? t("No model fits this GPU's memory, so the agent answers every problem. This one also runs on the CPU, slowly", { agent: AG() })
      : t("No model fits this GPU's memory. This one runs on the CPU, slowly")) + size
    : (L.gpu_gb ? t("The model for this GPU ({gb} GB of memory)", { gb: Math.round(L.gpu_gb) }) : t("The model for this PC")) + size;
  return `${why} <button type="button" class="btn sm pull-model" data-model="${escapeHtml(name)}">${t("Download")}</button>`;
}
function localState() {
  if (!eng()?.local?.loading) loadSeen = null;
  const L = eng()?.local;
  // with the server away the card says when it will know, as the welcome's checklist does: it stood empty over a bare rule
  if (wsState !== "up" || !L) return card("idle", t("Checking"), [], wsState !== "up" ? t("Checked once the server is connected") : "");
  // The server was started without a local engine at all (SIDENOTE_ANALYZER=cli): not a fault.
  if (!L.present) return card("off", t("Not used"), [], t("Start the server with {cmd} to use it", { cmd: "<code class=\"cmd\">SIDENOTE_ANALYZER=local</code>" }));
  // Shown in every state below, including the broken ones: which model is meant is half the answer.
  const model = L.model ? `<span class="model">${escapeHtml(L.model)}</span>` : "";
  // Switched off, and answering for the agent while it cannot (its limit, its sign-in, the spend brake): the server's
  // stand-in (Pipeline.standing_in), which ends by itself and takes the model off the GPU again. One word for the pill: beside Free
  // the GPU it has some 78 px at 1366
  if (!L.on && L.stand_in && L.ok) return card("warn", t("Stand-in"), [[t("Model"), model]],
    t("{why}, so this model solves for now though it is off. It leaves the GPU once sending works again", { why: STAND_IN_TEXT[L.stand_in] || t("The agent cannot be used", { agent: AG() }) }));
  if (!L.on) return card("off", t("Off"), [[t("Model"), model]], t("Turn it on to find problems on the GPU and answer the easy ones at once"));
  if (!L.ok) {
    // A missing model is pulled; a server that does not answer is looked at. L.missing is what the
    // server sends; guessing it from the words of the message never matched.
    const missing = !!L.missing || (L.reason || L.why || "").includes("missing");
    const pulling = pullNow || L.pulling;
    if (pulling) return card("warn", t("Downloading"), [[t("Model"), `<span class="model">${escapeHtml(pulling.model)}</span>`]], pullNote(pulling));
    if (missing && L.pull) return card("bad", t("No model"), [[t("Model"), model]], pullOffer(L));
    if (!missing && status.desktop) return card("bad", t("No response"), [[t("Model"), model]],
      t("Ollama does not answer · install it from {link}, or start it: Sidenote finds it within 20 seconds", { link: OLLAMA_LINK }));
    // What to do, as the band says it: the pill and the model's row already say what is wrong, and the note said it again
    const cmd = `<code class="cmd">${missing ? "./sidenote llm pull" : "./sidenote doctor"}</code>`;
    return card("bad", missing ? t("No model") : t("No response"), [[t("Model"), model]],
      missing ? t("Get the model with {cmd} in the server's terminal, then {up}", { cmd, up: `<code class="cmd">./sidenote up</code>` })
        : t("Run {cmd} in the server's terminal", { cmd }));
  }
  const g = L.loaded;
  // Whether the model sits on the GPU now, ready to answer, or the GPU was given back and the model goes on again
  // with the next problem. "unloaded (loads on the next problem)" did not say what it meant.
  // the state lit and in words, what it means quieter beside it ("loaded · answers at once" read as faint). Loaded, the pill says
  // "On GPU" already: the lit words are what that means, so the card does not say the same state twice
  const gpu = !g ? `<span class="lit off">${t("Empty")}</span> <span class="sub gpu-says">· <mark class="key">${t("Loads by itself when a problem comes")}</mark></span>`
    : g.unknown ? "" : `<span class="lit ok">${t("Solves at once")}</span> <span class="sub gpu-says">${[g.vram_gb ? `${g.vram_gb} GB` : "", g.params, g.quant, g.ctx ? t("Context {n}", { n: Number(g.ctx).toLocaleString() }) : ""].filter(Boolean).map((x, i) => `${i ? " · " : "· "}${escapeHtml(String(x))}`).join("")}</span>`;
  if (L.busy) {   // another program keeps the GPU busy: a smaller model answers for a while
    // L.busy.until is the server's clock: read against this browser's, a clock some minutes apart
    // counted the hold down to nothing (or up to hours)
    const left = Math.max(0, Math.round(L.busy.until - serverNow()));
    const when = left < 60 ? t("{n} s", { n: Math.max(5, Math.round(left / 5) * 5) }) : t("{m} min", { m: Math.ceil(left / 60) });
    return card("warn", t("GPU busy"), [[t("Model now"), `<span class="model">${escapeHtml(L.busy.model)}</span>`],
      [t("Usual model"), model], [t("Back"), t("in {when}", { when })], ["GPU", gpu]],
      t("The GPU is busy, so a smaller model solves"));
  }
  // The pill says the same in a word: ready on the GPU, or resting with the GPU free (still working: it goes on again
  // by itself, or with Load to GPU)
  if (L.loading) return card("ok", t("Loading"), [[t("Model"), model]], loadStepsHtml());
  return card("ok", !g ? t("Idle") : g.unknown ? t("Connected") : t("On GPU"), [[t("Model"), model], ["GPU", gpu]]);
}
// What the agent takes, as a value after "Takes" (the card's scale, the sheet's note): a noun phrase in each mode
const MODE_TEXT = { hard: t("Hard problems of chosen types"), verify: t("Local answers to check"), all: t("Every problem") };
// What is sent, by one name wherever it is said (the card, the sheet's note, the welcome's picture): the setting's own option as the
// server words it, these until its list has come
const PAYLOAD_TEXT = { crop: t("Problem area"), text: t("Problem text"), screen: t("Whole screen") };
const payloadName = (p) => (settingItem("agent_payload")?.options || []).find(([v]) => v === p)?.[1] || PAYLOAD_TEXT[p] || "";
// What will actually leave this PC. The crop and the written-out problem both come from this PC's
// model: with it off or down there is neither, and the whole screen goes instead. Saying "Problem
// crop" then is a promise the tool does not keep.
function payloadNow(C) {
  const L = eng()?.local;
  const working = !!(L && L.present && L.on && L.ok);
  return !working ? "screen" : (C.payload || "crop");
}
// Which model is answering and how hard it is told to think. The local card has said its model all
// along; this one only ever said "the agent".
const EFFORT_TEXT = { low: t("Low"), medium: t("Medium"), high: t("High"), xhigh: t("Very high"), max: t("Max") };
function agentModelLine(C) {
  const name = C.model || C.asked_model || "";
  return name ? `<span class="model">${escapeHtml(name)}</span>` : `<span class="sub">${t("Unknown")}</span>`;
}
// How hard it is told to think, a line of its own (it trailed the model's name, "· thinking default", and was missed). Its value in the
// words of the setting that moves it (Solver settings, Thinking effort), these until the server's list has come. The CLI's own default
// is marked with its one short word ("Medium · default" took the row's second half and more, and the row broke in two)
const effortName = (e) => (settingItem("agent_effort")?.options || []).find(([v]) => v === e)?.[1] || EFFORT_TEXT[e] || e;
const agentEffortLine = (C) => (C.effort ? `${escapeHtml(effortName(C.effort))}${C.effort_own ? ` <span class="sub" title="${t("The CLI's default; change it in Solver settings")}">· ${t("CLI")}</span>` : ""}` : t("Unknown"));
// Where an agent's CLI is installed from, for a PC that has none: the agent is optional, and this is how to add it
const AGENT_GET = { "claude-code": "https://docs.anthropic.com/en/docs/claude-code", codex: "https://github.com/openai/codex" };
function agentGet(C) {
  const url = AGENT_GET[C?.provider];
  const name = escapeHtml(C?.product || AG());
  return url ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${name}</a>` : name;
}
// What the card and the setup say of an agent not installed: the pill or the step's state says it is optional, this what adding it gives
const agentOptional = (C) => t("The local model answers on its own. To have the hard problems solved too, install {agent} and sign in once", { agent: agentGet(C) });
function agentState() {
  const C = eng()?.agent;
  if (wsState !== "up" || !C) return card("idle", t("Checking"), [], wsState !== "up" ? t("Checked once the server is connected") : "");
  if (!C.present) return card("off", t("Not used"), [], t("The server was started with {cmd}", { cmd: "<code class=\"cmd\">SIDENOTE_AGENT=off</code>" }));
  if (C.mode === "off") return card("off", t("Off"), [], t("Only the local model solves"));
  // No CLI on this PC: optional, said as such, at rest in grey rather than red as a fault (renderSignals, data-rest)
  if (!C.ok && C.installed === false) return card("idle", t("Optional"), [], agentOptional(C));
  if (!C.ok) {
    return card("bad", C.rejected ? t("Sign-in expired") : t("Sign-in needed"), [],
      t(status.desktop ? "Open a terminal, type {cmd} and press Enter, then sign in" : "Run {cmd} in the server's terminal", { cmd: `<code class="cmd">${LOGIN()}</code>` }));
  }
  // What will actually leave, which is not always what the setting says (see payloadNow).
  const pay = payloadNow(C);
  // The setting asked for part of the screen and the whole of it is going instead: the one thing
  // on this card worth a colour and a sentence.
  const forced = pay === "screen" && (C.payload || "crop") !== "screen";
  // One note, not three sentences that each say the local model is off.
  const note = forced ? t("The local model is off, so the whole screen is sent")
    : C.effective === "all" && C.mode === "hard" ? t("The local model is off, so the agent solves every problem", { agent: AG() })
    : "";
  // The model and its effort, one row of two, with no rows for details such as thinking or the maximum output;
  // the scales say what it is asked to take and to send, the profile who it is, and the meters what is left of the plan
  const core = [[t("Model"), agentModelLine(C)], [t("Effort"), agentEffortLine(C)]];
  // Resting on its plan's limit: nothing goes to it until then, questions asked by hand included (they can only fail)
  if (C.limit_until) {
    const L = eng()?.local, who = L && L.ok && (L.on || L.stand_in) ? t("the local model solves") : t("no engine to solve");
    // on the agent's own card: the limit is its own, said without naming it again
    return { ...card("warn", t("Resting at its limit"), [...core, [t("Sends again"), `${restAt(C.limit_until)} <span class="sub">· ${t("in {when}", { when: restLeft(C.limit_until) })}</span>`]],
      t("Usage limit · until then {who}", { agent: AG(), who })), viz: agentViz(C, pay, forced) };
  }
  // The spend brake holds: the watching sends nothing by itself until it lifts. This card is where
  // that is said, for as long as it lasts, because the answers list is not the place to repeat it.
  if (C.brake) return { ...card("warn", t("Auto sending paused"), core, escapeHtml(C.brake)), viz: agentViz(C, pay, forced) };
  // The scales say what it is asked to take and to send, so the rows under them say the rest
  return { ...card("ok", t("Connected"), core, note), viz: agentViz(C, pay, forced) };
}
// The GPU's readings of the last two minutes (the server sends one every two seconds while the model is on the GPU)
const GPU_KEEP = 60;
let gpuSeen = [];
let gpuStale = null;
// No reading: nothing shown, and the next one starts a new line rather than joining this one across the gap
function hideGpu() {
  clearTimeout(gpuStale);
  gpuSeen = [];
  $("gpu-viz").hidden = true;
}
function drawGpu(m) {
  if (m.none) { hideGpu(); return; }
  gpuLast = m;
  clearTimeout(gpuStale);
  gpuStale = setTimeout(hideGpu, 10000);   // the server gone quiet says nothing at all: figures must not stand as now
  gpuSeen.push(m.util);
  if (gpuSeen.length > GPU_KEEP) gpuSeen.shift();
  const gb = (mib) => (mib / 1024).toFixed(1), W = 100, H = 34;
  const at = (i) => W - (gpuSeen.length - 1 - i) * (W / (GPU_KEEP - 1)), y = (v) => H - (Math.min(100, v) / 100) * (H - 2) - 1;
  const line = gpuSeen.map((v, i) => `${at(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const left = gpuSeen.length ? at(0).toFixed(1) : W;
  const full = Math.round((m.used / m.total) * 100);
  const viz = $("gpu-viz"), kept = viz.querySelector(".meter i");
  if (kept) {
    const [useB, memB] = viz.querySelectorAll(".k > b"), small = viz.querySelectorAll("small")[1];
    useB.textContent = `${m.util}%`; memB.textContent = `${full}%`; small.textContent = `${gb(m.used)} / ${gb(m.total)} GB`;
    kept.style.width = `${full}%`;
    viz.querySelector(".area").setAttribute("points", `${left},${H} ${line} ${W},${H}`);
    viz.querySelector(".line").setAttribute("points", line);
    viz.querySelector("svg").setAttribute("aria-label", t("GPU use {n}%, last 2 minutes", { n: m.util }));
    viz.querySelector(".meter").setAttribute("aria-label", t("GPU memory {used} / {total} GB", { used: gb(m.used), total: gb(m.total) }));
    viz.querySelector(".foot").innerHTML = `<span>${t("Temp {v}", { v: `<b>${m.temp}°C</b>` })}</span>${m.power != null ? `<span>${t("Power {v}", { v: `<b>${m.power} W</b>` })}</span>` : ""}`;
    viz.hidden = false;
    if (eng()?.local?.loading) renderSignals();
    return;
  }
  viz.innerHTML = `<div title="${t("GPU use, last 2 minutes")}"><div class="k"><span>${t("GPU use")}</span><b>${m.util}%</b></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${t("GPU use {n}%, last 2 minutes", { n: m.util })}"><line class="base" x1="0" x2="${W}" y1="${H - .5}" y2="${H - .5}"/>
      <polygon class="area" points="${left},${H} ${line} ${W},${H}"/><polyline class="line" points="${line}"/></svg><div class="k"><small>${t("Last 2 minutes")}</small></div></div>
    <div title="${t("GPU memory")}"><div class="k"><span>${t("GPU memory")}</span><b>${full}%</b></div>
      <div class="meter" role="img" aria-label="${t("GPU memory {used} / {total} GB", { used: gb(m.used), total: gb(m.total) })}"><i style="width:${full}%"></i></div>
      <div class="k"><small>${gb(m.used)} / ${gb(m.total)} GB</small></div></div>
    <div class="foot"><span>${t("Temp {v}", { v: `<b>${m.temp}°C</b>` })}</span>${m.power != null ? `<span>${t("Power {v}", { v: `<b>${m.power} W</b>` })}</span>` : ""}</div>`;
  $("gpu-viz").hidden = false;
  if (eng()?.local?.loading) renderSignals();   // the steps under Cancel go on with the readings
}
function setSignal(id, state, title) {
  const el = $(id), plainTitle = title.replace(/<[^>]+>/g, "");
  el.dataset.state = state; el.title = plainTitle;
  el.setAttribute("aria-label", plainTitle);   // the state is a colour and a tooltip otherwise: a screen reader heard only the name
}
function setHtml(id, html) { const el = $(id); if (el.dataset.html !== html) { el.dataset.html = html; el.innerHTML = html; if (el.querySelector(".fact")) fitFacts(el); } }
function fitFacts(root = document) {
  root.querySelectorAll(".rail .fact").forEach((f) => { f.classList.remove("wide"); if (f.scrollWidth > f.clientWidth + 1) f.classList.add("wide"); });
  // The capture card's two sources share their second half's name column: a name wider than the column ("Last screen" in
  // English) pushed its value 4 px past the other source's ("Last sound"), where the names of one width lined up
  for (const card of document.querySelectorAll(".rail .card.conn:not(.engine)")) {
    card.style.removeProperty("--col-name-2");
    const widest = Math.max(0, ...[...card.querySelectorAll(".fact:nth-child(even) dt")].map((d) => d.getBoundingClientRect().width));
    if (widest) card.style.setProperty("--col-name-2", `${Math.ceil(widest)}px`);
  }
}
// The card as it is drawn: the state as a pill, the facts as rows, and the one thing to do about
// it underneath, if there is one.
function cardHtml(c) {
  // The label is text (escaped); the value is already HTML, because values carry their own marks:
  // a model name in mono, a warning colour, a command chip.
  const rows = c.facts.map(([k, v]) => `<div class="fact" title="${escapeHtml(`${k}: ${String(v).replace(/<[^>]+>/g, "").trim()}`)}"><dt>${escapeHtml(k)}</dt><dd>${v}</dd></div>`).join("");
  // A card with no facts (Checking, Off with nothing to say) draws no empty list.
  return (c.viz || "") + (rows ? `<dl class="facts">${rows}</dl>` : "")
    + (c.note ? `<p class="src-note">${c.note}</p>` : "");
}
// The same card as one line of plain text, for the title of the little signal in the top bar:
// tags are stripped because a title attribute shows them as they are.
const plain = (c) => [c.pill, ...c.facts.map(([k, v]) => `${k} ${v}`), c.note]
  .filter(Boolean).join(", ").replace(/<[^>]+>/g, "");
function renderSignals() {
  const server = { up: ["ok", t("Server connected")], down: ["bad", t("Server disconnected")], connecting: ["idle", t("Connecting to the server")] }[wsState];
  setSignal("sig-server", server[0], server[1]);
  const lo = localState(), c = agentState(), sc = screenState(), au = audioState();
  setSignal("sig-local", lo.s, t("Local model: ") + plain(lo));
  setSignal("sig-agent", c.s, `${AG()}: ` + plain(c));
  // the header's signal and the card are named after the agent the server uses
  const sig = document.querySelector("#sig-agent .name");
  if (sig && sig.textContent !== AGS()) sig.textContent = AGS();               // the header has room for the short name
  for (const el of document.querySelectorAll(".agent-name")) if (el.textContent !== AG()) el.textContent = AG();
  setSignal("sig-screen", sc.s, t("Screen capture: ") + plain(sc));
  setSignal("sig-audio", au.s, t("Sound capture: ") + plain(au));
  // Every card is drawn the same way: its rows, then the word and the colour of its state.
  for (const [id, st] of [["screen", sc], ["audio", au], ["local", lo], ["agent", c]]) {
    setHtml(`st-${id}`, cardHtml(st));   // setHtml, so an unchanged card is not rebuilt
    if (id === "agent") growQuotas();
    const pill = $(`pill-${id}`);
    if (pill.textContent !== st.pill && pill.dataset.state !== "idle") replay(pill, "changed");
    pill.textContent = st.pill;          // text, not HTML: the pill is one word
    pill.dataset.state = st.s;           // the CSS picks the colour from this
    pill.closest(".src")?.setAttribute("data-state", st.s);   // and the source's mark lights in it (index.html)
    // A model resting off the GPU, or an agent switched off or not installed (it is optional), is at rest and not at fault: grey, not
    // green or red (index.html, [data-rest])
    const A = eng()?.agent;
    pill.closest(".src")?.toggleAttribute("data-rest", (id === "local" && eng()?.local?.ok && !eng()?.local?.loaded && !eng()?.local?.loading)
      || (id === "agent" && !!A && (A.mode === "off" || (!A.ok && A.installed === false))));
  }
  syncSrc();   // what can be folded goes with the state and the details just drawn
  const L = eng()?.local;
  // Ollama lists a model while it is still loading: the load, once begun, keeps its own button until it has ended
  $("gpu-release").hidden = !(wsState === "up" && L && L.ok && L.loaded && !L.loaded.unknown && !L.loading);
  $("gpu-release").disabled = gpuPending;            // pressed: held until the server has said what became of it
  $("gpu-load").disabled = gpuPending;
  // Put back on the GPU from here, not only by the next problem: a model taken off the GPU can be loaded again by hand
  $("gpu-load").hidden = !(wsState === "up" && L && L.present && L.on && L.ok && (L.loading || (!L.loaded && !L.busy)));
  // While it loads the button says so, with a bar running through it, and a press stops it
  const loadBtn = $("gpu-load"), isLoading = !!L?.loading;
  loadBtn.classList.toggle("loading", isLoading);
  loadBtn.textContent = isLoading ? t("Cancel") : t("Load to GPU");
  loadBtn.title = isLoading ? t("Stop and free the GPU") : t("Load it onto the GPU now and the first problem is solved at once");
  // The agent on and off from its own card, as the screen and the sound are (it was only in Solving settings)
  const C = eng()?.agent, swc = $("sw-agent");
  swc.hidden = !(C && C.present);
  swc.setAttribute("aria-checked", String(!!(C && C.mode !== "off")));
  swc.disabled = wsState !== "up";
  // On with no CLI on this PC, it does nothing yet: quiet, as the capture switches are with no program connected
  swc.dataset.idle = String(!!(C && !C.ok && C.installed === false));
  $("sw-screen").setAttribute("aria-checked", String(!!capture.screen_on));
  $("sw-audio").setAttribute("aria-checked", String(!!capture.audio_on));
  // Nothing connected to switch: greyed out and not pressable
  $("sw-screen").disabled = $("sw-audio").disabled = wsState !== "up" || capture.clients === 0;
  // Nor can the bar's two buttons: they stayed at full strength while the server was gone, and a press
  // only brought up a toast saying there was nothing connected.
  $("reanalyze").disabled = $("pause").disabled = wsState !== "up";
  // A switch that is on while no capture program is connected is not doing anything: it says so
  // by going quiet, rather than looking as if sound were coming in.
  const idle = String(!(capture.clients > 0));
  $("sw-screen").dataset.idle = $("sw-audio").dataset.idle = idle;
  // Known to be off, not just not known yet: at rest, in grey, like the pill beside it
  $("sw-screen").dataset.dead = $("sw-audio").dataset.dead = String(capture.clients === 0);
  renderUsage();
  renderSetup();   // the guide says each state as its card does
}
// The numbers of the sitting, as a line of type rather than a table of labels: what was answered and
// how fast first, what it cost underneath.
// One bar per answer this sitting, in the order they came: how long each took, and which engine
// answered it. Drawn from the answers already on the page, so it needs nothing from the server.
// Each answer of one engine as a bar: how long it took, its lower part the wait for the first token and the rest the writing
function answerBars(recent) {
  const rows = (recent || []).filter((r) => typeof r.elapsed === "number").slice(-24);
  if (rows.length < 2) return "";
  const max = Math.max(...rows.map((r) => r.elapsed), 1);
  const secs = (v) => (v >= 100 ? Math.round(v) : Math.round(v * 10) / 10);
  const bars = rows.map((r, i) => {
    const wait = typeof r.first_token === "number" ? Math.min(100, (r.first_token / Math.max(r.elapsed, .01)) * 100) : 0;
    const said = [fmtClock(r.ts * 1000), t("Total {n} s", { n: secs(r.elapsed) }), typeof r.first_token === "number" ? t("TTFT {n} s", { n: secs(r.first_token) }) : "", typeof r.tps === "number" ? `${Math.round(r.tps)} TPS` : ""].filter(Boolean).join(" · ");
    return `<i class="bar" style="--i:${i};height:${Math.max(10, Math.round((r.elapsed / max) * 100))}%" title="${escapeHtml(said)}"><b style="height:${Math.round(wait)}%"></b></i>`;
  }).join("");
  return `<div class="bars" role="img" aria-label="${t("Time taken by {n} answers, one bar per answer, longest {max} s", { n: rows.length, max: secs(max) })}">${bars}</div>`
    + `<p class="bars-key"><span class="key wait">TTFT</span><span class="key write">${t("Writing time")}</span><span class="axis">${t("Max {n} s", { n: secs(max) })}</span></p>`;
}

// What one engine has done today, in its own card
function engineUsage(u, which) {
  if (!u || !u.answers) return `<p class="usage-none">${which === "agent" ? t("No answers from the agent yet", { agent: AG() }) : t("No answers from the local model yet")}</p>`;
  const money = (v) => (v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : v >= 100 ? `$${Math.round(v)}` : v >= 0.1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`);
  const much = (v) => (v >= 1e7 ? `${(v / 1e6).toFixed(1)}M` : Number(v || 0).toLocaleString());
  const stat = (v, k, tip = "") => `<span class="stat"${tip ? ` title="${escapeHtml(tip)}"` : ""}><b>${v}</b><span class="k">${k}</span></span>`;
  // Over the last day, or, with none in it, over the last answers it gave. The label says what it counts in the room a tile has (60 px:
  // "Answers, 24 h" ran into the next one), the tooltip over what
  const top = [stat(t("{answers}", { answers: u.answers }), u.window === "recent" ? t("Recent") : t("Answers"),
    u.window === "recent" ? t("None in the last 24 hours: its latest answers") : t("Answers in the last 24 hours"))];
  // One decimal in every tile, three figures at most from a hundred up: "88.64초" beside "61.3초" read as two kinds of figure
  const one = (v) => (Math.abs(v) >= 100 ? Math.round(v) : Math.round(v * 10) / 10);
  if (u.elapsed_p50 != null) top.push(stat(t("{n} s", { n: one(u.elapsed_p50) }), t("Response p50")));
  if (u.first_token_avg != null) top.push(stat(t("{n} s", { n: one(u.first_token_avg) }), t("Avg TTFT")));
  if (u.tps_avg != null) top.push(stat(`${one(u.tps_avg)}`, t("Avg TPS")));
  const tokens = t("In {a} · out {b} tokens", { a: much(u.tokens_in), b: much(u.tokens_out) });
  const cost = `<span class="cost" title="${t("Cost")}">${which !== "agent" ? t("No cost") : u.cost_usd ? money(u.cost_usd) : t("In the subscription")}</span>`;
  const err = u.errors ? `<p class="usage-err">${u.errors === 1 ? t("{n} error", { n: u.errors }) : t("{n} errors", { n: u.errors })}${u.last_error ? t(" · last {when}", { when: fmtClock(u.last_error * 1000) }) : ""}</p>` : "";
  return `<div class="usage-top">${top.join("")}</div>${answerBars(u.recent)}<p class="usage-sub" title="${t("In {a} · out {b} tokens", { a: Number(u.tokens_in || 0).toLocaleString(), b: Number(u.tokens_out || 0).toLocaleString() })}"><span>${tokens}</span>${cost}</p>${err}`;
}
// A figure's number run from `from` to the one drawn, in its own unit and decimals, over 0.7 s, easing out; it ends on the exact text drawn
function countTo(b, from) {
  const m = b.textContent.match(/^(-?[\d.,]+)(.*)$/s);
  if (!m || calm() || !isFinite(from)) return;
  const to = parseFloat(m[1].replace(/,/g, "")), unit = m[2], dec = (m[1].split(".")[1] || "").length, start = performance.now();
  if (!isFinite(to) || from === to) return;
  const step = (now) => {
    const t = Math.min(1, (now - start) / 700), ease = 1 - Math.pow(1 - t, 3);
    if (!b.isConnected) return;                       // redrawn meanwhile: the new one runs on its own
    b.textContent = t < 1 ? `${(from + (to - from) * ease).toFixed(dec)}${unit}` : m[0];
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
const usageDrawn = {};     // what each card holds now, so an unchanged one is left alone
function renderUsage() {
  // A server from before the engines were told apart says only the sums: they go under this PC's card
  const by = usage?.engines || (usage ? { local: usage } : {});
  for (const which of ["local", "agent"]) {
    const html = usage ? engineUsage(by[which], which) : "";
    // Redrawn only when the numbers moved: this runs once a second from the clock tick, and replacing the bars every time threw away any text selected in the card.
    if (html === usageDrawn[which]) continue;
    usageDrawn[which] = html;
    const box = $(`usage-${which}`), was = [...box.querySelectorAll(".stat b")].map((b) => b.textContent), lastBar = box.querySelector(".bar:last-child")?.title;
    box.innerHTML = html;
    // A figure counts up from nothing when first drawn and from its old value when it changes: motion that says something
    box.querySelectorAll(".stat b").forEach((b, i) => {
      if (!was.length) countTo(b, 0);
      else if (b.textContent !== was[i]) { b.classList.add("tick"); countTo(b, parseFloat(String(was[i]).replace(/,/g, ""))); }
    });
    const bars = box.querySelector(".bars");
    if (bars) {
      if (lastBar === undefined) bars.classList.add("grow");
      else if (bars.lastElementChild?.title !== lastBar) bars.lastElementChild?.classList.add("grown");
      setTimeout(() => { bars.classList.remove("grow"); bars.querySelector(".grown")?.classList.remove("grown"); }, 1400);
    }
  }
  syncSrc();
}
// The mark says what kind of notice this is without reading it, and it is the same mark on a band and on a toast:
// a triangle for something to fix (bad: it broke; warn: it was not done), a circle for something only worth knowing
// (info), with a tick when it is what was asked for, done (done).
const ALERT_ICON = {
  bad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 4.2 2.6 20h18.8L12 4.2Z"/><path d="M12 10v4.4M12 17.3h.01"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 4.2 2.6 20h18.8L12 4.2Z"/><path d="M12 10v4.4M12 17.3h.01"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.7h.01"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8.2 12.3 2.6 2.6 5-5.4"/></svg>',
};
function alertHtml(kind, msgHtml, actionHtml = "") {
  return `<div class="alert ${kind}">${ALERT_ICON[kind] || ALERT_ICON.info}`
    + `<div class="msg">${msgHtml}</div>${actionHtml}</div>`;
}
// A toast's words as a band's: the fact in bold, then what follows from it or what to do. They come as one line, the
// fact before its first " · " or ": " (the translations keep those marks); `cmd`, a command in them, is a chip as on a band.
function noticeMsg(text, cmd = "") {
  const s = String(text ?? ""), code = cmd ? escapeHtml(cmd) : "";
  // outside brackets only: "(CUDA error: out of memory)" is what went wrong, not where the fact ends
  let cut = null;
  for (let i = 0, depth = 0; i < s.length && !cut; i++) {
    const c = s[i];
    if (c === "(" || c === "[") depth++;
    else if ((c === ")" || c === "]") && depth) depth--;
    else if (!depth && (s.startsWith(": ", i) || s.startsWith(" · ", i))) cut = { index: i, 0: s.startsWith(": ", i) ? ": " : " · " };
  }
  const chip = (x) => code ? escapeHtml(x).split(code).join(`<code class="cmd">${code}</code>`) : escapeHtml(x);
  return `<b>${chip(cut ? s.slice(0, cut.index) : s)}</b>${cut ? ` ${chip(s.slice(cut.index + cut[0].length))}` : ""}`;
}
// The bands stand in the bar's free middle, covering nothing of the thread, where that leaves them room (index.html, html.bands-in-bar)
// Whether the bands take their room over the thread (html.bands-room): where they do not go in the bar at the top of the
// page. Decided where that can be seen, at the top or in one column, and kept while the page scrolls, so the thread never
// moves by their height: in the bar at the top they take none and scrolled they float under it, as before; out of it they
// take their room at the top and keep it scrolled. Floating there, they lay over the first answer and its keys.
let bandsRoom = false;
function placeBands() {
  const shown = document.querySelector(".signals"), sig = (shown?.offsetParent ? shown : document.querySelector(".brand"))?.getBoundingClientRect(), act = document.querySelector(".actions")?.getBoundingClientRect();
  if (!sig || !act) return;
  const left = sig.right + 16, right = window.innerWidth - act.left + 12;
  // Only at the very top of the page: there a band would lie over the head of the thread. Scrolled, it floats under the bar as a toast does.
  // Not in one column (1000 px and narrower), where the bands take their room over the thread (index.html): in the bar at the
  // top and in the page once scrolled, they moved the thread by their height as it scrolled
  let fits = !window.matchMedia("(max-width: 1000px)").matches && window.scrollY <= 4 && window.innerWidth - left - right >= 380 && sig.top < 40;
  document.documentElement.classList.toggle("bands-in-bar", fits);
  document.documentElement.style.setProperty("--band-l", `${Math.round(left)}px`);
  document.documentElement.style.setProperty("--band-r", `${Math.round(right)}px`);
  const bands = document.getElementById("alerts");
  // Only if each says all it has to say there: three in a row were cut to "서버가 응답하지 않습..." with the rest in a tooltip
  if (fits && [...(bands?.querySelectorAll(".alert .msg") || [])].some((m) => m.scrollWidth > m.clientWidth + 1)) {
    fits = false;
    document.documentElement.classList.remove("bands-in-bar");
  }
  if (window.matchMedia("(max-width: 1000px)").matches || window.scrollY <= 4) bandsRoom = !fits;
  document.documentElement.classList.toggle("bands-room", bandsRoom && !!bands?.children.length);
  // A passing notice stands over the thread's own column, wherever that is at this width
  const col = document.getElementById("stage")?.getBoundingClientRect();
  if (col?.width) {
    document.documentElement.style.setProperty("--col-mid", `${Math.round(col.left + col.width / 2)}px`);
    document.documentElement.style.setProperty("--col-w", `${Math.round(col.width)}px`);
  }
  if (bands) document.documentElement.style.setProperty("--alerts-h", `${Math.ceil(bands.getBoundingClientRect().height)}px`);
  document.documentElement.classList.toggle("no-anchor", !!bands?.children.length && window.scrollY < 300);
  // A passing notice under the bands that float, 8 px under their foot: their height alone left out the margin over them, and the
  // notice lay 8 px into the last band. The notice's own top is the bar's foot and 18 px (index.html, .toast)
  const barFoot = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bar-h")) || 56;
  document.documentElement.style.setProperty("--toast-off", !fits && bands?.children.length
    ? `${Math.max(0, Math.round(bands.getBoundingClientRect().bottom - barFoot - 18 + 8))}px` : "0px");
}
addEventListener("resize", placeBands);
addEventListener("scroll", () => schedule("bands", placeBands), { passive: true });
// ---------- the version, and a newer release ----------
// The server's release (status.version) stands at the foot of the gear menu. A newer one, found by the server's check of
// GitHub (server/updates.py, status.update), is one line in the band: its number, a link to its release notes, and a key
// that hides it for that version in this browser. The link is used only when it is one of this repository's releases.
const NOTES_PREFIX = "https://github.com/kanggu12/sidenote/releases/";
const UPDATE_HIDDEN_KEY = "sidenote-update-hidden";   // the version whose notice was closed here
const hiddenNow = new Set();   // closed on this page: the key works where the browser keeps nothing
const CLOSE_MARK = mark('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>', 2.2);   // the settings sheet's close key's drawing
function releaseLink(url) {
  if (typeof url !== "string" || !url.startsWith(NOTES_PREFIX)) return "";
  const tail = url.slice(NOTES_PREFIX.length);
  // Plain path segments only: no query, fragment, quote or space, and no "." or ".." that the browser would resolve out of the releases
  const plain = /^[A-Za-z0-9._~+-]+(\/[A-Za-z0-9._~+-]+)*$/.test(tail) && !tail.split("/").some((s) => s === "." || s === "..");
  return plain ? url : "";
}
function updateHidden(version) {
  if (hiddenNow.has(version)) return true;
  try { return localStorage.getItem(UPDATE_HIDDEN_KEY) === version; } catch (_) { return false; }
}
function hideUpdate(version) {
  hiddenNow.add(version);
  try { localStorage.setItem(UPDATE_HIDDEN_KEY, version); } catch (_) {}   // a newer version than this one shows again
  const had = document.activeElement?.dataset?.act === "update-hide";     // the key is about to go, and the keyboard with it
  renderAlerts();
  if (had) $("more").focus({ preventScroll: true });                      // the bar's key above the band: not back at the page's top
}
function updateBand() {
  const u = status.update;
  // Three numbers, as the server writes them; not while the switch is off (at once, before the server says so) or once hidden here
  if (wsState !== "up" || !u || !/^\d+\.\d+\.\d+$/.test(u.version || "") || settingsValues.update_check === false || updateHidden(u.version)) return "";
  const href = releaseLink(u.url), hide = t("Hide for this version");
  return alertHtml("info", `<b>${t("Sidenote {version} is out", { version: u.version })}</b>`
    + (href ? ` <a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${t("Release notes")}</a>` : ""),
    `<button type="button" class="btn sm icon" data-act="update-hide" data-version="${u.version}" title="${hide}" aria-label="${hide}">${CLOSE_MARK}</button>`);
}
function renderVersion() {
  // a release's number, with a pre-release or build part when the code carries one; anything else is not shown
  const v = typeof status.version === "string" && /^\d+\.\d+\.\d+([-+][0-9A-Za-z.+-]+)?$/.test(status.version) ? status.version : "";
  $("menu-about").hidden = !v;
  $("menu-ver").textContent = v ? t("Version {version}", { version: v }) : "";
}
function renderAlerts() {
  const out = [];
  if (!demo && wsState === "down") {
    // the desktop app runs its own server: what to do there is to start the app again, with no command to copy
    out.push(status.desktop
      ? alertHtml("bad", t("{title} Reconnecting · if Sidenote was closed, start the Sidenote app again", { title: `<b>${t("Server disconnected")}</b>` }), "")
      : alertHtml("bad", t("{title} Reconnecting · if the server is off, run {cmd} in its terminal", { title: `<b>${t("Server disconnected")}</b>`, cmd: `<code class="cmd">./sidenote up</code>` }),
        `<button class="btn sm" data-copy="./sidenote up">${COPY_MARK}<span>${t("Copy command")}</span></button>`));
  } else if (wsState === "up" && eng()) {
    // One engine down while the other answers is a warning; nothing left to answer is an error.
    const E = eng(), L = E.local, C = E.agent, kind = E.ready ? "warn" : "bad";
    // An agent with no CLI on this PC is optional: its card and the setup say how to add it, and no band nags about it
    const localBad = L.present && L.on && !L.ok, agentBad = C.present && C.mode !== "off" && !C.ok && C.installed !== false;
    if (localBad && (L.pull || status.desktop) && !(pullNow || L.pulling)) {
      // The desktop app: the download key itself, or where to get Ollama; no command to run
      out.push(alertHtml(kind, `<b>${localTrouble(L)}</b> ` + (L.missing && L.pull ? pullOffer(L)
        : t("Ollama does not answer · install it from {link}, or start it: Sidenote finds it within 20 seconds", { link: OLLAMA_LINK }))
        + `${E.ready ? t(" · the agent solves meanwhile", { agent: AG() }) : ""}`, ""));
    } else if (localBad && !(pullNow || L.pulling)) {
      // The same command the rail gives: pull only when the model was never downloaded, otherwise
      // look at a server that is there and not answering.
      const fix = localFix(L);
      const title = `<b>${localTrouble(L)}</b>`, cmd = `<code class="cmd">${fix}</code>`;
      out.push(alertHtml(kind, (L.missing
        ? t("{title} Get the model with {cmd} in the server's terminal, then {up} · resumes within 20 seconds", { title, cmd, up: `<code class="cmd">./sidenote up</code>` })
        : t("{title} Run {cmd} in the server's terminal · resumes within 20 seconds", { title, cmd }))
        + `${E.ready ? t(" · the agent solves meanwhile", { agent: AG() }) : ""}`,
        `<button class="btn sm" data-copy="${fix}">${COPY_MARK}<span>${t("Copy command")}</span></button>`));
    }
    if (agentBad) {
      const why = C.rejected ? t("{agent} sign-in expired", { agent: AG() }) : t("{agent} sign-in needed", { agent: AG() });
      // in the desktop app the CLI's own sign-in, in any terminal; with the launcher, its command in the server's terminal
      const where = status.desktop ? "{title} Open a terminal, type {cmd} and press Enter, then sign in · resumes within 20 seconds"
        : "{title} Run {cmd} in the server's terminal · resumes within 20 seconds";
      out.push(alertHtml(kind, t(where, { title: `<b>${why}</b>`, cmd: `<code class="cmd">${LOGIN()}</code>` })
        + (E.ready ? t(" · the local model solves meanwhile") : ""),
        `<button class="btn sm" data-copy="${LOGIN()}">${COPY_MARK}<span>${t("Copy command")}</span></button>`));
    }
    // The agent resting on its plan's limit, at the top, with until when: the card says it only when opened
    const resting = C.present && C.mode !== "off" && C.limit_until;
    if (resting) {
      // Which of this PC's model's states it is: on and answering, off and standing in, on but not answering (its own band above says what
      // to do; "켜면" said to turn on a model that was on), or off
      const sub = L.ok && (L.on || L.stand_in) ? (L.on ? t(" · the local model solves meanwhile") : t(" · the local model, though off, stands in meanwhile"))
        : L.on ? t(" · no engine to solve meanwhile · the local model does not respond")
        : t(" · no engine to solve meanwhile · turn on the local model and it solves");
      // until when only: the band is drawn on the server's messages, not every second, and a time left here went
      // stale beside the agent's card, which counts it down
      // in the tone of the agent's card, which says it in orange; red when nothing answers meanwhile. It was green, the colour
      // of a connected engine
      out.push(alertHtml(kind, `<b>${t("{agent} usage limit: resting until {when}", { agent: AG(), when: restAt(C.limit_until) })}</b>${sub}`));
    }
    // An agent resting on its limit is on: the band above says what answers meanwhile, and this one said both were off
    if (!E.ready && !localBad && !agentBad && !resting) {
      out.push(alertHtml("bad", t("{title} Turn on the local model or the agent in Solver settings", { title: `<b>${t("Every engine is off")}</b>`, agent: AG() }),
        `<button class="btn sm" data-act="settings">${t("Solver settings")}</button>`));
    }
  }
  if (wsState === "up" && capture.clients === 0 && (capture.screen_on || capture.audio_on)) {
    out.push(alertHtml("warn", `<b>${t("Capture program off")}</b> ${status.desktop
      ? t("The capture program stopped · quit Sidenote and start it again")
      : t("Run {cmd} on the capture PC", { cmd: `<code class="cmd">./sidenote capture</code>` })}`, ""));
  }
  // A drawn region is easy to forget and it decides everything that follows: with one set, the models
  // only ever see that patch. It once cost a sitting: a region drawn on an old screen left every answer
  // as "nothing to solve" (the patch held a corner of an editor).
  const roi = settingsValues.roi_box;
  if (wsState === "up" && Array.isArray(roi) && roi.length === 4) {
    const pc = (v) => Math.round(v * 100);
    out.push(alertHtml("info", `<b>${t("Watching part of the screen")}</b> ${t("x {x0}~{x1}%, y {y0}~{y1}%", { x0: pc(roi[0]), x1: pc(roi[2]), y0: pc(roi[1]), y1: pc(roi[3]) })}`,
      `<button class="btn sm" data-act="roi-clear">${t("Clear the region")}</button>`));
  }
  if (status.build && buildAtLoad && status.build !== buildAtLoad) {
    out.push(alertHtml("info", t("{title} Reload to apply", { title: `<b>${t("New version")}</b>` })
      + (settingsValues?.history_keep === false ? t(" · answers are not kept, so a reload loses them: copy what you need first") : ""),
      `<button class="btn sm" data-act="reload">${t("Reload")}</button>`));
  }
  if (paused) {
    out.push(alertHtml("warn", t("{title} No automatic analysis · {redo} takes the current screen only", { title: `<b>${t("Paused")}</b>`, redo: REDO_KEY() })));
  }
  out.push(updateBand());   // a newer release, last: only worth knowing ("" when there is none to show)
  setHtml("alerts", out.join(""));   // redrawn every few seconds: a diff keeps the focus where it was
  $("alerts").querySelectorAll(".msg").forEach((m) => { m.title = m.textContent.trim(); });   // cut to a line in the bar: all of it on the pointer
  placeBands();
}

// ---------- the thread: one notebook page that keeps filling, newest at the bottom ----------
function liveSeconds(it) { return Math.max(0, Math.round((Date.now() - it.ts) / 1000)); }
// `quiet`: an automatic analysis not said yet (onStart): most of them find nothing within a second or two, or are
// stopped by the next change, and are never drawn at all.
function pendingItems() { return [...items.values()].filter((it) => it.live && !it.shown && !it.quiet); }
// What a running analysis is doing (the server's stage messages): shown in the foot of the page until
// its answer starts, then on its headline.
// Getters where a stage names the agent: this runs when the page loads, before the server has said which agent it is.
const STAGE_TEXT = { think: t("The local model is thinking"), local: t("The local model is solving"), get agent() { return t("The agent is solving", { agent: AG() }); },
  extract: t("Writing out the problem as text"), get confirm() { return t("Asking whether to send it to the agent", { agent: AG() }); },
  // Asked again on a screen the first look found nothing on: the screen is read once more in two
  // halves, each at its own resolution, which is what finds a problem in a narrow window.
  halves: t("Looking again at each half of the screen") };
function stageText(it) {
  const st = it.stage;
  if (!st || !STAGE_TEXT[st.stage]) return "";
  // The agent says what went out; the thinking pass how far it has thought ("thought 1,240 characters"), the one long wait with
  // nothing else on the card while it runs.
  return STAGE_TEXT[st.stage] + ((st.stage === "agent" || st.stage === "think") && st.detail ? ` · ${st.detail}` : "");
}
// One way of saying it at the foot of the page and in the answer's head, parts set apart by "·": the foot said "(생각 1,200자) (2초)",
// two brackets in a row, and the head ", 5초째" for the same wait
const pendingText = (it) => t("{what} · {n} s", { what: stageText(it) || (it.trigger === "voice" ? t("Looking at the problem heard") : t("Looking at the new screen")), n: liveSeconds(it) });
const liveText = (it) => (stageText(it) ? t("{what} · {n} s", { what: stageText(it), n: liveSeconds(it) }) : t("Solving · {n} s", { n: liveSeconds(it) }));
// in the clock every other time on the page is written in ("04:53 AM"), not a 24-hour one with seconds
const noneText = () => `${fmtClock(lastNone.ts)} ${lastNone.voice ? t("No problem to solve in what was heard") : t("No problem to solve")}`;
const row = (mg, ct, cls = "", attrs = "") => `<div class="row ${cls}" ${attrs}><div class="mg">${mg}</div><div class="ct">${ct}</div></div>`;

// How a screen becomes an answer, drawn rather than described: the welcome page was a wall of text
// about a tool whose whole job is visual. Every box and arrow is labelled, and the two engines carry
// the same colours as the bars in the usage card.
function flowDiagram() {
  const L = eng()?.local, C = eng()?.agent;
  const live = wsState === "up";                       // anything below is last-seen, not now
  const localOn = !!(live && L && L.present && L.on && L.ok);
  const agentOn = !!(live && C && C.present && C.ok && C.mode !== "off");
  // The inputs are drawn the same way: a switch that is off, or no capture program at all, is not
  // a live source, and the picture used to show both as if they were feeding the model.
  const screenOn = !!(live && capture.clients > 0 && capture.screen_on);
  const soundOn = !!(live && capture.clients > 0 && capture.audio_on && status.audio);
  const off = (on) => (on ? "" : " off");
  // Off, not signed in, not there at all and not known yet are four different things, and the
  // picture used to call all of them Off while the checklist under it said Needed or Checking.
  // A download under way is said as the card says it, not as a model still to get
  const localWhy = !eng() || wsState !== "up" ? t("Checking")
    : !L || !L.present ? t("Not on this server")
    : !L.on ? t("Off")
    : pullNow || L.pulling ? t("Downloading")
    : L.missing ? t("Model download needed")
    : !L.ok ? t("No response") : "";
  // An agent with no CLI on this PC is optional, as its card and the setup say: not a sign-in to make
  const agentWhy = !eng() || wsState !== "up" ? t("Checking")
    : !C || !C.present ? t("Not on this server")
    : C.mode === "off" ? t("Off")
    : !C.ok && C.installed === false ? t("Optional")
    : !C.ok ? t("Sign-in needed") : "";
  // What actually goes out, not what the setting says: cutting the problem out needs this PC's
  // model, so with it off the whole screen goes however the setting reads (the same rule as the
  // rail's own line, payloadNow), by the name the setting gives it.
  const goes = payloadName(!localOn ? "screen" : C?.payload || "crop");
  // The same picture twice: one row for a wide column, one column for a narrow one. Only one is
  // ever displayed (the container query in the stylesheet picks it). The wide one needs 600px, and
  // below that it used to be dragged sideways inside the card, which reads as a card cut in half.
  const label = t("The local model takes the screen and the sound, solves the easy problems at once and leaves the hard ones to the agent, and the answers are written here", { agent: AG() });
  // Nothing named on the arrow before the server has said what the agent is set to: "모두" stood there with the server down
  const edge = !eng() || wsState !== "up" ? ""
    : !localOn ? t("All")
    : C?.effective === "all" ? t("All")
    : C?.effective === "verify" ? t("Check") : t("If hard");
  const localSub = localOn
    ? (C?.effective === "all" ? t("Finds, sends to the agent", { agent: AG() })
      : C?.effective === "verify" ? t("Finds and solves all")
      : t("Finds, solves the easy"))
    : localWhy;
  // Stacked: the two sources side by side at the top, then one line straight down. The bypass runs
  // down the left margin, so it never crosses the boxes it skips.
  const tall = `<svg class="flow tall" viewBox="0 0 300 302" role="img" aria-label="${label}">
    <defs><marker id="tip2" viewBox="0 0 8 8" refX="6.5" refY="4" markerWidth="6.5" markerHeight="6.5" orient="auto">
      <path d="M0 .6 7.4 4 0 7.4z"/></marker></defs>

    <rect x="14" y="6" width="126" height="38" rx="8" class="node${off(screenOn)}"/>
    <text x="77" y="30">${t("Screen")}</text>
    <rect x="160" y="6" width="126" height="38" rx="8" class="node${off(soundOn)}"/>
    <text x="223" y="30">${t("Sound")}</text>
    <path d="M77 44C77 60 150 52 150 66" class="${screenOn ? "" : "off"}"/>
    <path d="M223 44C223 60 150 52 150 66" class="${soundOn ? "" : "off"}"/>
    <path d="M150 64v10" marker-end="url(#tip2)"/>

    <rect x="22" y="78" width="256" height="50" rx="8" class="node${off(localOn)}"/>
    <text x="150" y="100">${t("Local model")}</text>
    <text x="150" y="117" class="sub">${localSub}</text>

    <path d="M150 128v28" marker-end="url(#tip2)" class="${agentOn ? "" : "off"}"/>
    <text x="159" y="147" class="edge side">${edge}</text>

    <rect x="22" y="162" width="256" height="50" rx="8" class="node${off(agentOn)}"/>
    <text x="150" y="184">${AG()}</text>
    <text x="150" y="201" class="sub">${agentOn ? goes : agentWhy}</text>
    <path d="M150 212v28" marker-end="url(#tip2)" class="${agentOn ? "" : "off"}"/>

    <path d="M22 103H12a6 6 0 0 0-6 6v152a6 6 0 0 0 6 6h4" marker-end="url(#tip2)"
          class="${localOn ? "" : "off"}"/>

    <rect x="22" y="246" width="256" height="50" rx="8" class="out"/>
    <text x="150" y="268" class="outt">${t("This notebook")}</text>
    <text x="150" y="285" class="sub inmark">${t("Answers pile up")}</text>
  </svg>`;
  // One row, one height, one centre line: Screen and Sound meet, the model answers what it can
  // straight into the notebook (the curve below), and what it cannot goes on to the agent.
  return tall + `<svg class="flow wide" viewBox="0 0 640 126" role="img"
      aria-label="${label}">
    <defs><marker id="tip" viewBox="0 0 8 8" refX="6.5" refY="4" markerWidth="6.5" markerHeight="6.5" orient="auto">
      <path d="M0 .6 7.4 4 0 7.4z"/></marker></defs>

    <rect x="2" y="8" width="78" height="38" rx="8" class="node${off(screenOn)}"/>
    <text x="41" y="32">${t("Screen")}</text>
    <rect x="2" y="62" width="78" height="38" rx="8" class="node${off(soundOn)}"/>
    <text x="41" y="86">${t("Sound")}</text>
    <path d="M80 27C104 27 104 54 126 54" class="${screenOn ? "" : "off"}"/>
    <path d="M80 81C104 81 104 54 126 54" class="${soundOn ? "" : "off"}"/>
    <path d="M126 54h8" marker-end="url(#tip)"/>

    <rect x="140" y="31" width="160" height="46" rx="8" class="node${off(localOn)}"/>
    <text x="220" y="51">${t("Local model")}</text>
    <text x="220" y="68" class="sub">${localSub}</text>

    <path d="M300 54h52" marker-end="url(#tip)" class="${agentOn ? "" : "off"}"/>
    <text x="330" y="44" class="edge">${edge}</text>

    <rect x="360" y="31" width="120" height="46" rx="8" class="node${off(agentOn)}"/>
    <text x="420" y="51">${AG()}</text>
    <text x="420" y="68" class="sub">${agentOn ? goes : agentWhy}</text>
    <path d="M480 54h32" marker-end="url(#tip)" class="${agentOn ? "" : "off"}"/>

    <path d="M220 77v23a8 8 0 0 0 8 8h343a8 8 0 0 0 8-8V84" marker-end="url(#tip)"
          class="${localOn ? "" : "off"}"/>

    <rect x="520" y="31" width="118" height="46" rx="8" class="out"/>
    <text x="579" y="51" class="outt">${t("This notebook")}</text>
    <text x="579" y="68" class="sub inmark">${t("Answers pile up")}</text>
  </svg>`;
}

// What the agent does in each mode, as a sentence. MODE_TEXT is a value for a label ("Takes: ..."): put in
// front of a fixed particle it read "찾은 문제 모두을 Claude 가 풉니다" and "이 PC 의 답을 검토을 ...", with the wrong particle.
function agentDoes(mode) {
  if (mode === "verify") return t("The agent checks the local model's answers", { agent: AG() });
  // whole sentences in English; the Korean reads as it did, "<what> <agent> solves"
  if (mode === "hard") return t("The agent solves the hard problems of the chosen kinds", { agent: AG() });
  if (mode === "all") return t("The agent solves every problem", { agent: AG() });
  return t("The agent solves: {what}", { agent: AG(), what: MODE_TEXT[mode] || t("the chosen problems") });
}
let welcomeDrawn = "";   // the page as it is now: rebuilt only when something in it changed
function renderWelcome() {
  // The engines as last heard while the server is away: unknown, as the cards and the capture step say it, not still ticked
  const L = wsState === "up" ? eng()?.local : null, C = wsState === "up" ? eng()?.agent : null;
  const capOk = capture.clients == null ? null : capture.clients > 0;
  const srv = wsState === "up" ? true : wsState === "down" ? false : null;
  // A done step is ticked with the drawn tick the dropdown uses (it was the character "✓", put in by the
  // stylesheet, the one undrawn mark on the page next to the flow picture's drawn ones).
  // `bad`: a step that failed outright, said in red like the alert over the page (the server not reached); the others
  // that are not done yet wait on the person at the PC and are said in the warning tone
  const step = (done, t, d, s, bad = false) => `<li data-done="${done === null ? "" : done}"${bad ? " data-bad" : ""}><span class="box">${done === true ? TICK_MARK : ""}</span><div><div class="t">${t}</div><div class="d">${d}</div></div><span class="s">${s}</span></li>`;
  // The first analysis on an empty page is said here, at the foot of the welcome, and no longer on a
  // second sheet of its own under it that held this one line. A send-to-the agent question still opens
  // the thread, which then says it there. The seconds go in from the clock tick (fillPending), so this
  // markup stays the same while it runs and the page is not rebuilt every second.
  const pend = pendingItems().length && !confirms.size
    ? row("", `<div class="topline pending"><span class="spin"></span><span data-pending></span></div><p class="thought" data-thought hidden></p>`) : "";
  return `<article class="sheet welcome">
    ${row(t("Start"), `<h1>${t("Put a problem on the screen and {mark}", { mark: `<mark class="key">${t("its solution is written here")}</mark>` })}</h1>
      <p class="lede">${t("Finds the problems on the screen and in speech, solves them and writes them here in order")}</p>
      <div class="flow-wrap">${flowDiagram()}</div>`)}
    ${row(t("Setup"), `<ul class="steps">
      ${step(srv, t("Server"), status.desktop ? t("The Sidenote app runs it: start the app again if it is not running")
        : t("Run {cmd} in the server's terminal", { cmd: "<code class=\"cmd\">./sidenote up</code>" }), { true: t("Connected"), false: t("Not connected"), null: t("Checking") }[srv], srv === false)}
      ${L && L.present ? step(L.on && !(pullNow || L.pulling) ? L.ok : null, t("Local model"), L.pull && !L.ok && !L.missing
        ? t("Finds problems on the GPU and answers what it can at once. First install Ollama from {link}", { link: OLLAMA_LINK })
        : L.pull ? t("Finds problems on the GPU and answers what it can at once. With no model yet: the Download button on the Local model card")
        : t("Finds problems on the GPU and answers what it can at once. With no model yet: {cmd}", { cmd: "<code class=\"cmd\">./sidenote llm pull</code>" }),
        // a download under way is the step being done, as the card's own pill says
        !L.on ? t("Off") : L.ok ? t("Connected") : pullNow || L.pulling ? t("Downloading") : t("Needed")) : ""}
      ${C && C.present ? step(C.mode === "off" || C.installed === false ? null : C.ok, `${AG()}`, C.mode === "off"
        ? t("Off. Turned on in Solver settings, the agent solves the hard problems of the chosen types", { agent: AG() })
        : C.installed === false ? agentOptional(C)
          // the sign-in to make, said as an instruction: where the command is typed is the app's terminal, or the server's
          : t(status.desktop ? "{does}. It uses the sign-in this PC has; if there is none, open a terminal and run {cmd}"
            : "{does}. It uses the sign-in this PC has; if there is none, run {cmd} in the server's terminal",
          { does: agentDoes(C.mode), agent: AG(), cmd: `<code class="cmd">${LOGIN()}</code>` }),
        C.mode === "off" ? t("Off") : C.installed === false ? t("Optional") : C.ok ? t("Connected") : t("Needed")) : ""}
      ${!L && !C ? step(null, t("Solving engines"), t("Checked once the server is connected"), t("Checking")) : ""}
      ${step(capOk, t("Capture program"), status.desktop ? t("The Sidenote app starts it with no window; quitting it from its tray icon ends the app")
        : t("{cmd} (runs with no window; quit it from its tray icon)", { cmd: "<code class=\"cmd\">./sidenote capture</code>" }), capOk === null ? t("Checking") : capOk ? t("On") : t("Not running"))}
    </ul>`)}
    ${row(t("Tips"), `<ul class="tips">
      <li>${t("The same problem is not solved twice; move on to the next one and it is solved at once")}</li>
      <li>${t("Not happy with an answer: {redo} above. More to ask: the box below", { redo: REDO_KEY() })}</li>
      ${status.runEnabled ? `<li>${t("Run a code answer with {run} to see its output", { run: keyHint(RUN_MARK, t("Run")) })}</li>` : ""}
      <li>${t("For a long problem, turn on {setting} in Solver settings and scroll", { setting: `<b>${escapeHtml(settingItem("stitch")?.label || t("Scroll stitching"))}</b>` })}</li>
      <li>${t("{roi} on the screen card: only the place you draw is looked at and sent", { roi: keyHint(ROI_MARK, t("Draw a region")) })}</li>
    </ul>`)}
    ${pend || (lastNone ? row("", `<p class="cap">${noneText()}</p>`) : "")}
  </article>`;
}
// Who answered, how long it took and what left this PC are on the card; the tokens and the cost are
// behind the dots, since they are the same four numbers under every answer.
// Where a search word or a page read went, named in the answer's details
const SENT_TO = { get agent() { return AG(); }, search: t("Web search"), page: t("Page reading") };
function metaHtml(m) {
  if (!m) return "";
  const parts = [], rest = [];
  // Which engine answered is the one thing in this line worth telling apart at a glance: it says
  // whether the answer left the PC. The two take the colours the header's own signals use for them.
  if (m.engine) parts.push(`<span class="by ${m.engine === "agent" ? "cloud" : "here"}">`
    + `<b>${m.engine === "agent" ? `${AG()}` : t("Local model")}</b>${m.model ? `<span class="model">${escapeHtml(m.model)}</span>` : ""}</span>`);
  else if (m.model) parts.push(`<span class="model">${escapeHtml(m.model)}</span>`);
  if (m.elapsed != null) parts.push(`<span class="took">${t("{n} s", { n: `<b>${Number(m.elapsed).toFixed(1)}</b>` })}</span>`);
  if (m.first_token != null) {
    parts.push(`<span class="took">${t("TTFT {n} s", { n: `<b>${Number(m.first_token).toFixed(1)}</b>` })}</span>`);
    const out = m.usage?.output_tokens, run = m.elapsed - m.first_token;
    if (out > 0 && run >= 0.2) parts.push(`<span class="took"><b>${(out / run).toFixed(1)}</b> TPS</span>`);
  }
  if (Array.isArray(m.sent) && !m.sent.length) parts.push(`<span class="none-out">${t("Nothing sent out")}</span>`);
  if (m.usage) {
    const u = m.usage, cached = (u.cache_read || 0) + (u.cache_write || 0), input = (u.input_tokens || 0) + cached;
    rest.push(`<span>${t("In {n} tokens", { n: `<b>${input.toLocaleString()}</b>` })}${cached ? t(" (cache {n})", { n: cached.toLocaleString() }) : ""}</span>`);
    rest.push(`<span>${t("Out {n} tokens", { n: `<b>${(u.output_tokens || 0).toLocaleString()}</b>` })}</span>`);
  }
  if (m.cost_usd != null) rest.push(`<span class="cost">${t("Cost {v}", { v: `<b>$${m.cost_usd.toFixed(4)}</b>` })}</span>`);
  // What left this PC, in the details: the search words and the pages read. What went to the agent is not written: "에이전트에 보냄
  // 문제 부분 화면 1344×1600", as a row of its own and then here, said nothing of use; the screen card still says when only the marked
  // part went, where the picture it is about stands.
  const out = Array.isArray(m.sent) ? m.sent.filter((x) => x.to !== "agent") : [];
  if (out.length) rest.push(...out.map((x) => `<span class="sent-one">${t("Sent to {to}: {what}", { to: escapeHtml(SENT_TO[x.to] || x.to || ""), what: `<b>${escapeHtml(x.what || "")}</b>` })}</span>`));
  else if (m.model === "mock" && !(Array.isArray(m.sent) && m.sent.length)) rest.push(`<span>${t("Mock reply")}</span>`);
  // The tokens and the cost, behind a button that says what it opens: a grey ⋯ at the line's size was not seen.
  // It opens and folds them, and stays open through a redraw (m.open).
  const more = rest.length ? `<button class="meta-more" data-meta type="button" aria-expanded="${m.open ? "true" : "false"}"`
    + ` title="${t("Input and output tokens, the cost, and the search words and pages sent out of this PC")}">${t("Details")}${OPEN_MARK}</button><span class="meta-rest">${rest.join("")}</span>` : "";
  return `<div class="meta${m.open ? " open" : ""}">${parts.join("")}${more}</div>`;
}
// The automatic check of a code answer against the problem's examples (runner sandbox).
const jsonText = (v) => { try { return JSON.stringify(v); } catch (_) { return String(v); } };
const CHECK_LANG = { python: "Python", javascript: "JavaScript", typescript: "TypeScript", cpp: "C++", c: "C",
  java: "Java", kotlin: "Kotlin", go: "Go", bash: "Bash" };
const vDots = (passed, total) => (total > 0 && total <= 24 ? `<span class="v-dots" role="img" aria-label="${t("{passed} of {total} passed", { passed, total })}">${'<i class="on"></i>'.repeat(passed)}${"<i></i>".repeat(total - passed)}</span>` : "");
// A code check drawn as a judge's result, kept concise: the verdict
// large in its colour with the count and its dots, the language and what was run; a tab for each run, the first failed one in view; and for the
// run in view what went in, what came out and what was expected, each in a box of its own. Not a table: it was read as one in another look
function checkHtml(c) {
  if (c.running) return `<div class="topline pending"><span class="spin"></span><span>${t("Running the code")}</span></div>`;
  if (c.cancelled) return `<p class="cap">${t("Check stopped: moved on to the next problem")}</p>`;
  if (c.none) return `<p class="cap">${t("Not run: no I/O examples")}</p>`;
  if (c.skipped) return `<p class="cap">${t("Not run: {why}", { why: escapeHtml(c.skipped) })}</p>`;
  if (c.error) return `<p class="cap check bad">${t("Run failed: {why}", { why: escapeHtml(c.error) })}</p>`;
  const probe = !!c.probe, call = c.how === "design";
  // no examples on the screen: inputs this PC's model made up, judged only by ending without an error
  const runs = probe ? (c.rows || c.outputs || (c.fails || []).map((f) => ({ input: f.input, got: f.got, ok: false })))
    : (c.rows || (c.fails || []).map((f) => ({ input: f.input, expected: f.expected, got: f.got, ok: false, order: f.order_only })));
  const ok = c.passed === c.total;
  const one = c.total === 1;
  const count = probe ? (one ? t("{n} made-up input", { n: c.total }) : t("{n} made-up inputs", { n: c.total }))
    : call ? (one ? t("{n} call", { n: c.total }) : t("{n} calls", { n: c.total })) : one ? t("{n} example", { n: c.total }) : t("{n} examples", { n: c.total });
  const meta = [CHECK_LANG[c.lang], c.total ? count : ""].filter(Boolean).join(" · ");
  // what the problem's own words changed about the judging ("any order", "tolerance 1e-09"), and a result in another order said as the fact it is
  const notes = [probe ? t("No examples, so it ran on made-up inputs; the answers were not checked") : "", c.rule ? escapeHtml(c.rule) : "", runs.some((r) => r.order) ? t("Some results hold the same values in another order") : ""].filter(Boolean);
  const head = `<div class="vc-head"><b class="vc-verdict">${probe ? (ok ? t("No errors") : t("Error")) : ok ? t("Passed") : t("Failed")}</b>`
    + `${c.total ? `<span class="vc-count">${c.passed}/${c.total}</span>${vDots(c.passed, c.total)}` : ""}<span class="vc-meta">${escapeHtml(meta)}</span></div>`
    + `${notes.length ? `<p class="vc-note">${notes.join(" · ")}</p>` : ""}`;
  if (!runs.length) return `<div class="vcheck ${ok ? "ok" : "bad"}">${head}</div>`;
  // A value as an example writes it, a space after each comma ([3, 1, 4], {"a": 1}); a string keeps its own lines
  const valueText = (v) => (Array.isArray(v) ? `[${v.map(valueText).join(", ")}]`
    : v && typeof v === "object" ? `{${Object.entries(v).map(([k, x]) => `${jsonText(k)}: ${valueText(x)}`).join(", ")}}` : jsonText(v));
  const box = (v) => { const s = v == null ? "" : typeof v === "string" ? v.replace(/\n$/, "") : valueText(v); return s.trim() ? `<pre>${escapeHtml(s)}</pre>` : `<pre class="none">${t("(none)")}</pre>`; };
  // A function's input is its arguments (the server sends them as one list): one a line, as the run box takes them, not one nested list
  const input = (v) => (c.how === "function" && Array.isArray(v) ? v.map(valueText).join("\n") : v);
  const first = Math.max(0, runs.findIndex((r) => r.ok === false));
  const label = probe ? t("Input") : call ? t("Call") : t("Example");
  const tabs = runs.length > 1 ? `<div class="vc-tabs" role="tablist">${runs.map((r, i) => `<button type="button" role="tab" class="vc-tab ${r.ok === false ? "bad" : "ok"}" data-case="${i}" aria-selected="${i === first}"><i></i>${label} ${i + 1}</button>`).join("")}</div>` : "";
  const cases = runs.map((r, i) => {
    const expected = !probe && "expected" in r;
    return `<div class="vc-case${r.ok === false ? " bad" : ""}" data-case="${i}" role="tabpanel"${i === first ? "" : " hidden"}>`
      + `<div class="vc-io"><span class="vc-k">${call ? t("Call") : t("Input")}</span>${box(input(r.input))}</div>`
      + `<div class="vc-pair${expected ? "" : " one"}"><div class="vc-io got"><span class="vc-k">${t("Output")}</span>${box(r.got)}</div>`
      + `${expected ? `<div class="vc-io"><span class="vc-k">${t("Expected")}</span>${box(r.expected)}</div>` : ""}</div></div>`;
  }).join("");
  return `<div class="vcheck ${ok ? "ok" : "bad"}">${head}${tabs}${cases}</div>`;
}
// Problem text: the newest answered screen problem written out by the local model, as plain text to copy. The
// server keeps only that problem's screen (as for follow-up questions), so only its card offers it.
let repeatOf = null;   // the answer a problem seen again went back to: the server answers follow-ups about it (app.py, analysis_repeat)
function lastAnsweredId() {
  if (repeatOf != null && items.has(repeatOf)) return repeatOf;
  for (let i = thread.length - 1; i >= 0; i--) {
    const it = items.get(thread[i]);
    // A stopped one is not: the server answers follow-ups about the one before it
    if (it && !it.live && !it.error && !it.stopped && it.head.type && it.head.type !== "none") return it.id;
  }
  return null;
}
const ptextOffered = (it) => !it.ptext && it.thumb && it.trigger !== "voice" && it.id === lastAnsweredId()
  && settingsValues.extract !== false && settingsValues.local_llm !== false && !!eng()?.local?.ok;

// What to ask next, offered as buttons under the latest answer. An answer that is right but thin
// used to mean working out what to type to get the rest of it; these ask it for them.
// The text each one sends is the whole instruction, so the depth comes from what is asked rather
// than from a longer first pass. A first pass told to go deep every time pays for it on every
// screen, including the 1,001 of 1,014 that hold nothing worth a word.
const DIG = t("Explain the last answer in more depth. Do not repeat the conclusion: write step by step the principle of why it works that way, the evidence for it, the usual mistakes and traps, the reasons behind its performance or complexity, and the conditions that matter in practice.");
const NEXT_ASKS = {
  algorithm: [[t("Another approach"), t("Show a different approach to the same problem with code, and compare when it or the current answer is better.")],
              [t("Why this complexity"), t("Work out why the time and space complexity come out as they do, from the loop counts and the data structures. If the worst and average cases differ, give each.")],
              [t("Find a counterexample"), t("Find inputs on which the current code could be wrong. Check boundary values, empty input, the maximum size, duplicates, negative numbers and overflow one by one, and write down the results.")]],
  coding: [[t("Edge cases"), t("Find the inputs and situations that break this code. For each, say what happens and how to fix it.")],
           [t("Test code"), t("Write tests that check this code, covering the normal path, the boundaries and the failure paths.")]],
  mcq: [[t("The other options"), t("Explain one by one why each of the other options is wrong, and in what case it would be right.")]],
  short: [[t("The reasoning"), t("Explain step by step, starting from the definitions, the reasoning that leads to that answer.")]],
  essay: [[t("More examples"), t("Add concrete cases or figures for each point of the answer.")],
          [t("Shorter"), t("Rewrite the same content at half the length, keeping only the core.")]],
  work: [[t("How to confirm"), t("List in order the commands, logs and metrics that confirm the diagnosis, and what each command tells apart.")],
         [t("Other causes"), t("If it is not the cause named, list what to suspect next in order of likelihood, and how to tell them apart.")]],
  math: [[t("Another method"), t("Show how to reach the same answer by another method.")],
         [t("Check the answer"), t("Check the answer with another method.")]],
  diagram: [[t("Each part"), t("Explain what each box and arrow in the diagram means and why it is where it is.")]],
};
// Offered on the newest answer only: a follow-up is asked about the last one the server answered,
// so a button under an older entry would send the question somewhere it was not meant to go.
// Not on one Practice keeps back: they ask about an answer not seen yet.
const nextAsks = (it) => (!it.live && !it.error && it.head.type && it.head.type !== "none"
                          && it.id === lastAnsweredId() && status.canAsk && !held(it))
  ? [[t("Go deeper"), DIG], ...(NEXT_ASKS[it.head.type] || [])] : [];
// A dropped connection loses the replies still on their way: a Problem text being written out goes back to its
// button, and an agent check in progress says it was not received.
function dropPending() {
  for (const it of items.values()) {
    if (it.ptext?.pending) it.ptext = null;
    if (it.verify?.running) it.verify = { lost: true };
  }
}
function ptextHtml(p) {
  if (p.pending) return `<div class="topline pending"><span class="spin"></span><span>${t("Writing out the problem as text")}</span></div>`;
  if (p.error) return `<p class="cap">${escapeHtml(p.error)}</p>`;
  return `<pre class="ptext">${escapeHtml(p.text)}</pre>`;
}
// The verify mode: the agent's check of a local answer (its corrected solution, or any other reply, is
// painted into [data-vbody] by paintItem, like the solution itself).
function verifyHtml(v) {
  if (v.running) return `<div class="topline pending"><span class="spin"></span><span>${t("The agent is checking this solution", { agent: AG() })}</span></div>`;
  if (v.cancelled) return `<p class="cap">${t("Check stopped")}</p>`;
  if (v.lost) return `<p class="cap">${t("Connection lost: no check result")}</p>`;
  if (v.not_sent) return `<p class="cap">${v.why ? escapeHtml(v.why) + " · " : ""}${t("Not checked")}</p>`;
  if (v.error) return `<p class="cap check bad">${t("Check failed ({why})", { why: escapeHtml(HINT[v.error]?.title || v.error) })}</p>`;
  if (v.verdict === "ok") return `<p class="cap check ok"><b>${t("The agent gives the same answer", { agent: AG() })}</b></p>`;
  // the pill, then its answer: the line is a row with gaps (index.html, .cap.check), and a ": " between them stood alone in it
  const lead = v.verdict === "fix" ? `<b>${t("The agent sees it differently", { agent: AG() })}</b>${splitHead(v.text || "", true).answer ? "<span data-vans></span>" : ""}`
    : `<b>${t("The agent's answer", { agent: AG() })}</b> ${t("(not in the format; shown as written)")}`;
  return `<p class="cap check bad">${lead}</p><div class="md" data-vbody></div>`;
}
function errorHtml(err, hint) {
  const h = HINT[hint] || HINT[""];
  // the command's chip after the sentence, and its copy key; a sentence that names the command itself keeps only the key (h.copy)
  const copy = h.copy || h.cmd;
  return `<div class="errbox"><h2>${h.title}</h2><p>${h.text}${h.cmd ? ` <code class="cmd">${h.cmd}</code>` : ""}${copy ? ` <button class="btn sm" data-copy="${copy}">${COPY_MARK}<span>${t("Copy command")}</span></button>` : ""}</p>
    <details><summary>${t("Error details")}</summary><pre>${escapeHtml(err)}</pre></details></div>`;
}
function turnHtml(turn) {
  return `<div class="turn" data-turn="${turn.id}">
    ${row(turn.kind === "continue" ? t("Update") : turn.retry ? t("Retry") : t("Question"), `<div class="q">${escapeHtml(turn.q)}</div>`)}
    ${!turn.error || turnWrote(turn) ? `
      ${row(`<span data-albl>${t("Reply")}</span>`, `<div class="answer"><span class="answer-text"><mark class="hl" data-aval></mark></span></div>`, "", "data-answer hidden")}
      ${row(turn.error ? t("Unfinished answer") : "", `<div class="md${turn.live ? " cursor" : ""}" data-body></div>`)}
      ${turn.stopped ? row(t("Stopped"), `<p class="cap stopped">${escapeHtml(turn.stopped)}</p>`) : ""}
      ${turn.check ? row(t("Tests"), checkHtml(turn.check)) : ""}
      ${turn.meta ? row("", metaHtml(turn.meta)) : ""}
` : ""}
    ${turn.error ? row(t("Error"), errorHtml(turn.error, turn.hint)) : ""}
  </div>`;
}

const olderThanOpen = (it) => { const i = thread.indexOf(it.id); return i >= 0 && i < thread.length - KEEP_OPEN; };
// Something was written before it failed. An answer that stops half way is still worth reading, and
// it used to be thrown away: the error replaced the whole card.
const wrote = (it) => !!((it.head?.body || "").trim() || (it.head?.answer || "").trim());
// The same question for a follow-up, whose text is kept raw and parsed on the way out. Both
// fields are null until their line arrives, which is the usual shape of a turn that failed early.
const turnWrote = (t) => {
  const h = splitHead(t.raw || "", true);
  return !!((h.body || "").trim() || (h.answer || "").trim());
};
// Errors are short: never folded. An entry stays open while a follow-up about it is being written.
// One kept back by Practice is not folded either: folded, it would show the answer line it keeps back.
const foldable = (it) => olderThanOpen(it) && !it.live && !it.error && !held(it);
const folded = (it) => foldable(it) && !unfolded.has(it.id) && !it.turns.some((t) => turns.get(t)?.live);
// When an answer was, with its day when that was not today
function answerItems(text) {
  // The numbered forms an answer line comes in: "(1) a (2) b", "1) a 2) b", "1. a 2. b", "① a ② b". One form throughout:
  // only the one that starts the line counts, so a "(2)" or a "3." inside an item's own words starts nothing.
  const forms = [
    (n) => `\\(${n}\\)\\s*`,
    (n) => `${n}\\)\\s+`,
    (n) => `${n}\\.\\s+`,
    (n) => (n <= 20 ? `${String.fromCodePoint(0x2460 + n - 1)}\\s*` : "(?!)"),
  ];
  const t = String(text || "").trim();
  const form = forms.find((f) => new RegExp(`^${f(1)}`).test(t));
  if (!form) return null;
  const at = [];
  let want = 1, from = 0;
  for (;;) {
    const m = new RegExp(`(?:^|\\s)${form(want)}`).exec(t.slice(from));
    if (!m) break;
    const lead = /^\s/.test(m[0]) ? 1 : 0, start = from + m.index + lead;
    at.push({ start, body: start + m[0].length - lead });
    from = at[at.length - 1].body; want++;
  }
  if (at.length < 2) return null;   // a "2" after the "1", or it is only a number
  return at.map((a, i) => t.slice(a.body, i + 1 < at.length ? at[i + 1].start : t.length).trim());
}

// ---------- Practice: an answer kept back until it is asked for ----------
// For a student who wants to try first. With Practice on (the gear menu), an answer that arrives shows its question and
// keeps the rest back: Show a hint opens the solution's own parts one at a time, in their order, and Show the answer
// opens all of it, the answer line too. It is a way of showing only: the server is not told and solves as before. This
// browser keeps the choice, and for each answer that came while it was on how far it has been opened.
const PRACTICE_KEY = "sidenote-practice";               // when Practice was turned on (ms); nothing while it is off
const PRACTICE_CARDS_KEY = "sidenote-practice-cards";   // [id, hints shown] of the answers it kept back, oldest first
const PRACTICE_KEEP = 400;                              // answers remembered: days of study, a few KB of storage
const OPENED = -1;                                      // "hints shown" of an answer opened in full: it stays open
let practiceSince = null;                               // when Practice was turned on, or null while it is off
const practiceCards = new Map();                        // String(id) -> hints shown, or OPENED
// Read once as the page opens, as the menu's other choices are; storage may be unavailable, and then nothing is kept
try {
  const since = Number(localStorage.getItem(PRACTICE_KEY));   // a time, or 0 for nothing stored
  practiceSince = since > 0 ? since : null;                   // anything else is off
  for (const [id, n] of JSON.parse(localStorage.getItem(PRACTICE_CARDS_KEY) || "[]")) {
    if (Number.isInteger(n) && n >= OPENED) practiceCards.set(String(id), n);   // a count of hints, or OPENED; nothing else is ours
  }
} catch (_) { practiceCards.clear(); }                        // unreadable: start with nothing kept back
function keepCards() {
  // Over the limit the oldest go: a Map keeps the order its keys were first set in
  while (practiceCards.size > PRACTICE_KEEP) practiceCards.delete(practiceCards.keys().next().value);
  try { localStorage.setItem(PRACTICE_CARDS_KEY, JSON.stringify([...practiceCards])); } catch (_) {}
}
// Kept back now: Practice is on, the answer came while it was, it was not opened in full, and there is something to keep
// back (one being written, or one that wrote an answer line or a solution: a failure that wrote nothing shows as it is)
function held(it) {
  if (practiceSince == null || !it || !practiceCards.has(String(it.id))) return false;
  return practiceCards.get(String(it.id)) !== OPENED && (it.live || wrote(it));
}
// An answer comes into the notebook: with Practice on it is kept back from now on, across a reload. One from the history
// counts as come while Practice was on when it was answered after Practice was turned on (with the panel closed, say)
function practiceArrived(it, restored = false) {
  if (practiceSince == null) return;                                       // off
  const id = String(it.id), card = practiceCards.get(id);
  // In a review of the starred ones (reviewStarred), one the Starred choice brings in is kept back as those already here
  // were, an answer opened before among them: it was let through as known and came in opened
  if (restored && histStar && it.starred) {
    if (card == null || card === OPENED) { practiceCards.set(id, 0); keepCards(); }
    return;
  }
  if (card != null) return;                                                // known already
  if (restored && it.ts < practiceSince) return;                           // answered before: shown as it was
  practiceCards.set(id, 0);                                                // kept back, no hint shown yet
  keepCards();
}
// Where each of an answer's parts ends in its text: the solution's own sections in their order. The hints shown so far
// are the text up to one of these, so they read as the whole does, only shorter. Under headings when two or more stand
// at one level; else under lines that are only bold (the steps as the models write them); else block by block, each step
// of a list a part of its own. A heading, a rule or a line ending in a colon goes with what follows it.
function answerCuts(md) {
  const text = String(md || "");
  const first = text.search(/\S/);                     // where the writing begins
  if (first < 0) return [];                            // nothing written: no part
  // The blocks as the panel's Markdown reads them, each with where it starts; the items of a list are blocks of their own
  let toks = null;
  try { toks = typeof window.marked?.lexer === "function" ? window.marked.lexer(text) : null; } catch (_) { toks = null; }
  const blocks = [];
  if (toks && toks.map((k) => k.raw).join("") === text) {   // the tokens make up the text exactly: their offsets hold
    let at = 0;
    for (const k of toks) {
      const from = at;
      at += k.raw.length;
      if (k.type === "space") continue;                       // the blank lines between blocks
      if (k.type === "list" && k.items?.length > 1 && k.items.map((i) => i.raw).join("") === k.raw) {
        let p = from;                                         // each step at its own place in the list
        for (const i of k.items) { blocks.push({ type: "item", from: p, raw: i.raw }); p += i.raw.length; }
      } else blocks.push({ type: k.type, depth: k.depth, from, raw: k.raw });
    }
  } else {
    // No Markdown reader here: the paragraphs, as blank lines divide them outside code
    let fence = false, at = 0, open = true;
    for (const line of text.split("\n")) {
      if (/^\s*(```|~~~)/.test(line)) fence = !fence;         // a code block's blank lines divide nothing
      if (!line.trim()) open = open || !fence;                // a blank line ends the paragraph
      else if (open) { blocks.push({ type: /^\s{0,3}#{1,6}\s/.test(line) ? "heading" : "paragraph", from: at, raw: line }); open = false; }
      at += line.length + 1;
    }
  }
  const words = (b) => b.raw.trim();
  let starts;
  // Headings: the outermost level with two or more, and any heading above it
  const level = [1, 2, 3, 4, 5, 6].find((d) => blocks.filter((b) => b.type === "heading" && b.depth === d).length >= 2);
  if (level) starts = blocks.filter((b) => b.type === "heading" && b.depth <= level).map((b) => b.from);
  else {
    // Lines that are only bold, two or more ("**1. Read the input**")
    const bold = blocks.filter((b) => b.type === "paragraph" && /^\*\*[^*\n]{1,60}\*\*[:：]?$/.test(words(b)));
    if (bold.length >= 2) starts = bold.map((b) => b.from);
    else {
      starts = [];
      let join = false;                                       // the block before leads into this one
      for (const b of blocks) {
        if (!join) starts.push(b.from);
        join = b.type === "heading" || b.type === "hr" || /[:：]$/.test(words(b));
      }
    }
  }
  // A part starts at each, what stands before the first is a part too, and none starts inside a formula set on lines of
  // its own (a $$ block with a blank line in it reads as two paragraphs)
  // Counted without code, and only where a formula's fence stands, at a line's start or end: a shell's `$$` in a sentence opens no
  // formula, and counted as one it took away every cut after it, which ran the rest of the solution into one hint
  const evenMath = (c) => {
    let fences = 0;
    const prose = text.slice(0, c).replace(/(```|~~~)[\s\S]*?(?:\1|$)/g, "").replace(/`[^`\n]*`/g, "");
    for (const line of prose.split("\n")) {
      const l = line.trim();
      if (l === "$$") fences++;                              // the fence alone on its line is one, not a start and an end
      else fences += Number(l.startsWith("$$")) + Number(l.endsWith("$$"));
    }
    return fences % 2 === 0;
  };
  const cuts = [...new Set(starts.filter((s) => s > first))].sort((a, b) => a - b).filter(evenMath);
  return [...cuts, text.length];                              // each part ends where the next starts, the last at the end
}
// The words that name the answer, the longest of each first so "최종 정답" is not read as a word "최종" and the rest
const ANSWER_WORD = /^(?:최종\s*(?:정답|답안|답|결론)|정답|해답|답안|답|결론|the\s+final\s+answer|final\s+answer|the\s+answer|answer|conclusion)/iu;
// What a line's words may start after: a quote mark, a heading's hashes, a list's mark, a number and bold, in any order ("## 3. **정답**")
const LINE_MARK = /^(?:>\s*|#{1,6}\s+|[-*+]\s+|\d+[.)]\s*|\(\d+\)\s*|[①-⑳]\s*|\*\*|__)/u;
// The word that leads into a closing sentence ("따라서 정답은 ③입니다")
const LEAD_IN = /^(?:따라서|그러므로|그래서|결국|즉|so|thus|therefore|hence)[,\s]+/iu;
// Whether a line of the solution gives the answer. On any line, the word with a colon, 은 or 는, or "is" after it, or alone on the
// line; a heading or a bold line may also go on as a title does ("정답 및 해설", "**정답** ③"). Other words after it make it a line
// about something else ("## Answer format", "**답 구하기**", "정답 확인을 위해").
function answerLine(line) {
  let s = line.trim(), titled = false;
  for (let m = LINE_MARK.exec(s); m; m = LINE_MARK.exec(s)) {
    if (/^(?:#|\*\*|__)/.test(m[0])) titled = true;   // a heading or bold: what may read as a title
    s = s.slice(m[0].length);
  }
  s = s.replace(/^[^\p{L}\p{N}]+/u, "").replace(LEAD_IN, "");   // brackets or a sign before the word ("[정답]")
  const word = ANSWER_WORD.exec(s);
  if (!word) return false;
  const rest = s.slice(word[0].length);
  if (/^\s*[:：]/u.test(rest) || /^[은는](?:[\s*_]|$)/u.test(rest) || /^\s+is\b/iu.test(rest)) return true;   // it says the answer
  if (/^[\s*_.)\]]*$/u.test(rest)) return true;       // the word alone on its line, closing marks aside: what follows is the answer
  if (!titled) return false;                          // a plain sentence that only starts with the word
  if (/^\s*(?:\*\*|__)/u.test(rest)) return true;     // the bold ends at the word: it is the label of what follows
  if (/^\s*(?:및|과|와|and|&)(?:\s|$)/iu.test(rest)) return true;      // "정답 및 해설", "정답과 풀이", "Answer and explanation"
  if (/^\s+(?:코드|풀이|해설)(?:[\s*_.:：)\]]|$)/u.test(rest)) return true;   // "정답 코드"
  return /^\s*[^\p{L}\s]/u.test(rest);                // a value or a bracket straight after it: "## 정답 ③", "## 정답 (③)"
}
// Where the first line that gives the answer starts, outside fenced code (a comment there is the code's), or -1
function answerAt(md) {
  let fence = "", at = 0;
  for (const line of md.split("\n")) {
    const open = /^\s*(`{3,}|~{3,})/.exec(line);
    // a fence ends at the kind of mark that opened it: ~~~ inside ``` is the code's own
    if (open && (!fence || open[1][0] === fence)) fence = fence ? "" : open[1][0];
    else if (!fence && answerLine(line)) return at;
    at += line.length + 1;
  }
  return -1;
}
// An answer's parts, worked out once for the text it has. The hints end where the first line that gives the answer starts: Show
// the answer opens that, so an answer that starts with it has no hints at all. Here and not in answerCuts, since the Anki file's
// back takes its key point from those cuts whether or not it holds the answer
function practiceParts(it) {
  const body = it.head?.body || "";
  if (it.cutsOf !== body) {
    const cuts = answerCuts(body), stop = answerAt(body);
    if (stop < 0) it.cuts = cuts;
    else {
      const before = cuts.filter((c) => c < stop);
      // What stands between the last cut before it and that line is a part too, ending at the line
      it.cuts = body.slice(before[before.length - 1] || 0, stop).trim() ? [...before, stop] : before;
    }
    it.cutsOf = body;
  }
  return it.cuts;
}
const hintsShown = (it) => Math.max(0, Math.min(practiceCards.get(String(it.id)) || 0, practiceParts(it).length));
// What a kept-back answer shows of its solution: its first parts, as many as hints were asked for
function shownText(it) {
  const n = hintsShown(it);
  return n ? (it.head?.body || "").slice(0, practiceParts(it)[n - 1]) : "";
}
// The rows of a kept-back answer, under its question: the keys that show more, then what they have shown. The keys stay where
// they are as the hints come in under them, so they are pressed again without moving the pointer.
function practiceRows(it) {
  // Being written: the card says so, and shows none of it
  if (it.live) return row(t("Practice"), `<div class="topline pending"><span class="spin"></span><span>${t("Writing the answer · hidden in practice mode")}</span></div>`, "practice");
  const total = practiceParts(it).length, n = hintsShown(it);
  // A hint while parts are left; an answer of one part has the answer key alone
  const hint = total > 1 && n < total ? `<button class="btn sm" type="button" data-act="hint" title="${t("Show the next part of the solution")}">${HINT_MARK}<span>${t("Show a hint")}</span></button>` : "";
  const all = `<button class="btn sm" type="button" data-act="reveal" title="${t("Show the answer line and the whole solution")}">${ANSWER_MARK}<span>${t("Show the answer")}</span></button>`;
  // How many there are, and how many are out
  const count = total > 1 ? `<span class="hint-n">${n ? t("{n} of {total} hints", { n, total }) : t("{n} hints", { n: total })}</span>` : "";
  // The follow-up row's look (.asks), with a name of its own, so the code that keeps that row in step leaves this one alone
  return row(t("Practice"), `${hint}${all}${count}`, "asks practice")
    + (n ? row(t("Hints"), `<div class="md" data-body></div>`) : "");
}
// Asked for more of an answer: words selected in it would put off the drawing (renderEntry, selectionIn) until the selection ends, the
// count going up with nothing to see. The selection goes, so what was asked for shows at once
function dropSelection(it) {
  const el = entryEl(it.id);
  if (el && selectionIn(el)) window.getSelection().removeAllRanges();
}
// The next part of the current answer's solution; false when there is none to show
// What a press opened on an answer, brought above the question box that floats over the page's foot: on the newest answer
// a hint, the answer or the details opened under the box and the page stayed where it was. Moved only as far as needed,
// and never so far that the top of what opened goes under the bar.
function showOpened(el) {
  const box = $("askform")?.getBoundingClientRect(), r = el?.getBoundingClientRect();
  if (!box || !r || !r.height) return;
  const room = Math.min(box.top, window.innerHeight) - 12;
  const top = (document.querySelector("header.bar")?.getBoundingClientRect().bottom || 56) + 12;
  const over = r.bottom - room;
  if (over <= 0) return;
  // up to six tenths of the room at a time, so what was in view stays partly in view; not past its own top while that shows
  let step = Math.min(over, (room - top) * 0.6);
  if (r.top > top) step = Math.min(step, r.top - top);
  if (step > 0) { autoUntil = Date.now() + 120; window.scrollBy(0, step); }   // the panel's own scroll, not one by hand
}
function showHint(it, key = null) {
  if (!it || !held(it) || it.live) return false;                     // only an answer kept back, once it is written
  const total = practiceParts(it).length, n = hintsShown(it);
  if (total < 2 || n >= total) return false;                          // one part, or all of them out
  practiceCards.set(String(it.id), n + 1);                            // one more, kept across a reload
  keepCards();
  dropSelection(it);
  renderEntry(it);
  // A key pressed keeps the keyboard; once the last hint is out, the answer key next to it takes it
  afterDraw(it, (el) => {
    if (key && !el.contains(document.activeElement)) el.querySelector("[data-act='hint'], [data-act='reveal']")?.focus({ preventScroll: true });
    showOpened(el);
  });
  return true;
}
// All of it: the answer line, the whole solution and what came with it. Opened once, it stays open
function showAnswer(it, key = null) {
  if (!it || !held(it) || it.live) return false;
  practiceCards.set(String(it.id), OPENED);
  keepCards();
  dropSelection(it);
  unfolded.add(it.id);              // opened by hand: an older answer shows whole, as one opened from its fold does
  renderEntry(it); renderIndex();   // the contents row says what it answers now
  afterDraw(it, (el) => {
    if (key && !el.contains(document.activeElement)) el.querySelector("[data-copy-answer]")?.focus({ preventScroll: true });   // the key's place
    sweepKey(el);                   // the highlighter goes along the answer line, as on an answer that has come in
    showOpened(el);
  });
  announce(`${TYPE_LABEL[it.head.type] || t("Solution")}: ${plainAnswer(it.head.answer) || t("Solution done")}`);
  return true;
}
// After the entry is drawn again: a press under way draws it when the press ends (renderEntry, endPress), which is queued first
function afterDraw(it, fn) { setTimeout(() => { const el = entryEl(it.id); if (el) fn(el); }, 0); }
// Practice turned on or off in the menu; kept in this browser
function setPractice(on) {
  if (on === (practiceSince != null)) { syncPracticeSeg(); return; }   // already so
  practiceSince = on ? Date.now() : null;                              // the answers from now on are kept back
  try { if (on) localStorage.setItem(PRACTICE_KEY, String(practiceSince)); else localStorage.removeItem(PRACTICE_KEY); } catch (_) {}
  syncPracticeSeg();
  if (on) reviewStarred();   // turned on with Starred chosen: a review of them
  // Those kept back come and go with it: only the entries whose look changes are drawn again, the one read kept in its place
  keepPlace(() => thread.forEach((id) => { const it = items.get(id), el = entryEl(id); if (it && el && el.classList.contains("held") !== held(it)) renderEntry(it); }));
  renderIndex(); syncNextAsks();
}
// Starred chosen in the contents with Practice on is a review: the starred answers are kept back again, whenever they were
// answered, and each opens hint by hint as a new one does. One opened before is kept back once more; one part way through
// its hints stays where it is.
function reviewStarred() {
  if (practiceSince == null || !histStar) return;
  let changed = false;
  for (const it of items.values()) {
    const id = String(it.id), card = practiceCards.get(id);
    if (!it.starred || (card != null && card !== OPENED)) continue;
    practiceCards.set(id, 0); changed = true;
  }
  if (!changed) return;
  keepCards();
  keepPlace(() => thread.forEach((id) => { const it = items.get(id), el = entryEl(id); if (it && el && el.classList.contains("held") !== held(it)) renderEntry(it); }));
  renderIndex(); syncNextAsks();
}
function syncPracticeSeg() {
  const on = practiceSince != null;
  document.querySelectorAll("#practice-seg button").forEach((b) => b.setAttribute("aria-pressed", String((b.dataset.practice === "on") === on)));
}
function entryWhen(it) {
  const d = new Date(it.ts);
  return `<time class="stamped">${fmtWhen(d.getTime())}</time>`;
}
// An answer that can be starred: finished, not failed or stopped (the server keeps only those), and with the server's own id
const starrable = (it) => !it.live && !it.error && !it.stopped && it.meta != null && typeof it.id === "number";
const starTitle = (it) => (it.starred ? t("Starred · press to unstar") : t("Star: kept when old answers are deleted, and listed under Starred in the contents"));
// The star key drawn again on its own, for a star changed from this panel or another: the rest of the entry stays as it is
function paintStar(it) {
  const key = entryEl(it.id)?.querySelector(`:scope > .row.head [data-star]`);
  if (!key) return;
  key.setAttribute("aria-pressed", String(!!it.starred));
  key.title = starTitle(it);
}
function entryHtml(it) {
  const kind = it.error ? `<span class="kind err">${t("Error")}</span>`
    : it.live && !it.head.type ? `<span class="kind live">${t("Analyzing")}</span>`
    : `<span class="kind${it.live ? " live" : ""}">${escapeHtml(TYPE_LABEL[it.head.type] || it.head.type || t("Result"))}</span>`;
  const via = [];
  if (it.trigger === "voice") via.push(`<span>${t("A problem heard by voice")}</span>`);
  if (it.pages) via.push(`<span>${t("A problem gathered by scrolling, {n} pages", { n: it.pages })}</span>`);
  if (it.live) via.push(`<span data-elapsed>${liveText(it)}</span>`);
  const asks = nextAsks(it);          // what can be asked next about this answer
  const hold = held(it);              // kept back by Practice: its question, and the keys that show more
  const tools = [];
  // Every one of these wears its mark, the same drawing as the copy button inside a code block.
  if (foldable(it)) tools.push(`<button class="btn sm ghost" data-fold="${it.id}" aria-expanded="${!folded(it)}">${folded(it) ? OPEN_MARK + `<span>${t("Show the solution")}</span>` : FOLD_MARK + `<span>${t("Fold")}</span>`}</button>`);
  if (ptextOffered(it)) tools.push(`<button class="btn sm ghost" data-ptext="${it.id}" title="${t("Write out the problem on the screen as text")}">${PTEXT_MARK}<span>${t("Problem text")}</span></button>`);
  if (it.ptext?.text) tools.push(`<button class="btn sm ghost" data-copy-ptext="${it.id}" title="${t("Copy the problem text written out")}">${PTEXT_COPY_MARK}<span>${t("Copy problem text")}</span></button>`);
  // The star and Copy all come last, so they keep their places from one answer to the next whatever comes before them.
  // The star is on a whole answer the server keeps, by its id (a follow-up's stand-in parent has none)
  if (starrable(it)) tools.push(`<button class="btn sm ghost" data-star="${it.id}" aria-pressed="${!!it.starred}" title="${starTitle(it)}">${STAR_MARK}<span>${t("Star")}</span></button>`);
  if (!it.live && !it.error && !hold) tools.push(`<button class="btn sm ghost" data-copy-item="${it.id}" title="${t("Copy the whole solution as Markdown")}">${COPY_MARK}<span>${t("Copy all")}</span></button>`);
  // An error says what went wrong on its first line, beside its label. Its head used to be the headline
  // row, which an error leaves empty (no buttons, and mostly nothing about how it came in), so the label
  // stood beside a blank line and the message began some 50 px further down. A half-written answer
  // under it follows the message, labelled as cut off. The class keeps a narrow window from setting the
  // message beside the label, where it would have a third of the width (index.html, .row.head).
  const head = it.error
    ? row(`${kind}${entryWhen(it)}`, `${via.length ? `<div class="headline">${via.join("")}</div>` : ""}${errorHtml(it.error, it.hint)}`, "head err")
    : row(`${kind}${entryWhen(it)}`, `<div class="headline">${via.join("")}<span class="tools">${tools.join("")}</span></div>`, "head");
  // The follow-up buttons can be pressed only while the socket is up: syncNextAsks keeps them in step
  // after this, and takes the row away when the server says it cannot answer them.
  const offline = wsState === "up" ? "" : " disabled";
  // Kept back by Practice: in place of the answer line and the solution, the keys and the hints shown, and the problem text
  // written out (a question too). What the watching added under it by itself (a retry, the answer filled out) waits with
  // the rest, and the follow-ups asked about it show.
  return `${head}
    ${it.trigger === "voice" && it.transcript ? row(t("Heard"), heardHtml(it.transcript, it.id), "heard-row") : ""}
    ${row(t("Question"), `<div class="asked" data-asked></div>`, "", "data-askedrow hidden")}
    ${it.stopped ? row(t("Stopped"), `<p class="cap stopped">${escapeHtml(it.stopped)}${t(" · to solve it again: {redo}", { redo: REDO_KEY() })}</p>`) : ""}
    ${hold ? `${practiceRows(it)}${it.ptext ? row(t("Problem"), ptextHtml(it.ptext)) : ""}` : !it.error || wrote(it) ? `
      ${row(`<span data-albl>${t("Answer")}</span>`, `<div class="answer"><span class="answer-text"><mark class="hl" data-aval></mark></span>
        <button class="btn sm ghost" data-copy-answer="${it.id}" title="${t("Copy the one-line answer")}">${COPY_MARK}<span>${t("Copy")}</span></button></div>`, "", "data-answer hidden")}
      ${row(it.error ? t("Unfinished solution") : t("Solution"), `<div class="md${it.live ? " cursor" : ""}" data-body></div>`, "fold-hide")}
      ${it.check ? row(t("Tests"), checkHtml(it.check), "fold-hide", "data-checkrow") : ""}
      ${it.verify ? row(t("Review"), verifyHtml(it.verify), "fold-hide") : ""}
      ${it.ptext ? row(t("Problem"), ptextHtml(it.ptext), "fold-hide") : ""}
      ${it.meta ? row("", metaHtml(it.meta), "fold-hide") : ""}
` : ""}
    <div data-thread class="fold-hide">${(hold ? it.turns.filter((tid) => !turns.get(tid)?.retry) : it.turns).map((tid) => turnHtml(turns.get(tid))).join("")}</div>
    ${asks.length ? row(t("More"), asks.map(([label, text]) =>
        `<button class="btn sm" data-ask="${escapeHtml(text)}" title="${escapeHtml(text)}"${offline}>${ASK_MARK}<span>${escapeHtml(label)}</span></button>`).join(""),
      "fold-hide asks") : ""}`;
}
const entryEl = (id) => document.querySelector(`.entry[data-id="${id}"]`);
const idOf = (s) => (isNaN(+s) ? s : +s);
// What the person at the PC is doing inside an entry survives the entry being drawn again (a check starting or ending, the next
// answer finishing, a follow-up): a press under way finishes first, and the focus, with its caret, comes back to the
// same control. Rebuilt under them, typing into the run box's input lost its keys and a Copy or Run pressed across
// the rebuild did nothing.
let pressIn = null;   // the entry (or the foot of the thread) a pointer press started in, until it ends
document.addEventListener("pointerdown", (e) => { pressIn = e.target.closest?.(".entry, #thread-tail, #history") || null; }, true);
const endPress = () => {
  const el = pressIn; pressIn = null;
  if (!el) return;
  const follow = el.dataset.follow; delete el.dataset.follow;
  if (el.dataset.redraw) {
    delete el.dataset.redraw;
    if (el.id === "thread-tail") renderTail();
    else if (el.id === "history") renderIndex();
    else { const it = items.get(el.dataset.id) || items.get(+el.dataset.id); if (it) renderEntry(it); }
  }
  if (follow) {   // the following held back during the press (toBottom, showTurn)
    const t = followTurn != null ? turns.get(followTurn) : null;
    if (t) showTurn(t); else followEnd();
  }
};
// after the click the press makes (it is dispatched after pointerup, in the same turn)
document.addEventListener("pointerup", () => setTimeout(endPress, 0), true);
document.addEventListener("pointercancel", endPress, true);
// A control inside an entry, as a selector and its place among the entry's matches: found again after a rebuild
function focusKey(el, root) {
  const f = document.activeElement;
  if (!f || f === document.body || !root.contains(f)) return null;
  const sel = f.tagName.toLowerCase() + [...f.classList].filter((c) => !/^(on|done|fresh)$/.test(c)).map((c) => "." + CSS.escape(c)).join("")
    + (f.dataset.act ? `[data-act="${CSS.escape(f.dataset.act)}"]` : "");
  const at = [...root.querySelectorAll(sel)].indexOf(f);
  const caret = typeof f.selectionStart === "number" ? [f.selectionStart, f.selectionEnd] : null;
  return at < 0 ? null : { sel, at, caret };
}
function refocus(key, root) {
  const f = key && root.querySelectorAll(key.sel)[key.at];
  if (!f) return;
  f.focus({ preventScroll: true });
  if (key.caret && typeof f.setSelectionRange === "function") { try { f.setSelectionRange(...key.caret); } catch (_) {} }
}
function renderEntry(it) {   // create or rebuild one entry in place
  let el = entryEl(it.id);
  if (el && pressIn === el) { el.dataset.redraw = "1"; return; }   // drawn when the press ends (endPress)
  // Text being selected to copy goes with a rebuild: the rebuild waits for the selection to end (selectionchange below)
  if (el && !it.live && selectionIn(el)) { el.dataset.redraw = "1"; return; }
  const keep = el ? focusKey(document.activeElement, el) : null;
  const opened = el ? [...el.querySelectorAll("details")].map((d) => d.open) : [];   // "표로 보기" and the like stay as they were left
  if (!el) {
    el = document.createElement("section");
    el.className = "entry view"; el.dataset.id = it.id;
    $("thread").insertBefore(el, $("thread-tail"));
  }
  el.classList.toggle("folded", folded(it));
  el.classList.toggle("held", held(it));   // kept back by Practice: turning it off or on draws again only these (setPractice)
  el.classList.toggle("fresh", !!it.fresh); it.fresh = false;
  if (it.id === viewId) el.dataset.here = "1";
  // The kind of problem is what the entry is coloured by: the word in the margin, the same word in
  // the index, and the band under the answer all read --t off this (index.html, [data-kind]).
  el.dataset.kind = it.error ? "" : (it.head.type || "");
  el.innerHTML = entryHtml(it);
  paintItem(it, true);
  if (!folded(it)) it.turns.forEach((tid) => paintTurn(turns.get(tid), true));
  // A button that shows only its mark still says what it does, on the pointer: its word as the tooltip where it has none
  el.querySelectorAll(":is(.btn, .copy):has(svg):not([title])").forEach((b) => { const w = b.textContent.trim(); if (w) b.title = w; });
  el.querySelectorAll("details").forEach((d, i) => { if (opened[i] != null) d.open = opened[i]; });
  heardFit(el);   // what was heard, cut to its first lines only if it does not fit in them
  if (keep) refocus(keep, el);
}
function selectionIn(el) {
  const sel = window.getSelection?.();
  return !!sel && !sel.isCollapsed && sel.rangeCount > 0 && el.contains(sel.getRangeAt(0).commonAncestorContainer);
}
document.addEventListener("selectionchange", () => {
  if (!window.getSelection()?.isCollapsed) return;
  document.querySelectorAll(".entry[data-redraw]").forEach((el) => {
    if (pressIn === el) return;                     // the press's end draws it
    delete el.dataset.redraw;
    const it = items.get(el.dataset.id) || items.get(+el.dataset.id);
    if (it) renderEntry(it);
  });
});
function renderThread() {   // full rebuild (clear, first load); normally entries update one by one
  $("thread").querySelectorAll(".entry").forEach((e) => e.remove());
  thread.forEach((id) => renderEntry(items.get(id)));
  renderTail(); syncEmpty(); applyChoice();
}
// The entries as the thread now has them, drawing only the new ones: what is open and in focus in the others stays
function syncThread() {
  const box = $("thread");
  box.querySelectorAll(".entry").forEach((e) => { if (!items.has(idOf(e.dataset.id))) e.remove(); });
  let at = box.firstElementChild;
  for (const id of thread) {
    let el = entryEl(id);
    if (!el) { renderEntry(items.get(id)); el = entryEl(id); }
    if (el === at) at = at.nextElementSibling;
    else box.insertBefore(el, at);
  }
  renderTail(); syncEmpty(); applyChoice();
}
// Run `change` with the entry being read kept where it stands on the screen, when the view is not at the end
function keepPlace(change) {
  if (stick) { change(); toBottom(); return; }
  const line = window.innerHeight * 0.33;
  const anchor = [...document.querySelectorAll(".entry:not([hidden])")].find((e) => e.getBoundingClientRect().bottom > line);
  const id = anchor?.dataset.id, top = anchor?.getBoundingClientRect().top;
  change();
  const again = id != null ? entryEl(idOf(id)) : null;
  if (again && !again.hidden) { autoUntil = Date.now() + 120; window.scrollBy(0, again.getBoundingClientRect().top - top); return; }
  // Filtered away: the nearest answer still shown takes its place at the same height
  if (again) {
    const all = [...$("thread").children].filter((e) => e.classList.contains("entry")), at = all.indexOf(again);
    const near = [...all.slice(at + 1), ...all.slice(0, at).reverse()].find((e) => !e.hidden);
    if (near) { autoUntil = Date.now() + 120; window.scrollBy(0, near.getBoundingClientRect().top - top); }
  }
}
function inView(el) { const r = el.getBoundingClientRect(); return r.bottom > 60 && r.top < window.innerHeight; }
function refold() {   // only the newest KEEP_OPEN entries stay open; older ones fold to the answer line
  thread.forEach((id) => {
    const it = items.get(id), el = entryEl(id);
    if (it && el && !stick && folded(it) && !el.classList.contains("folded") && inView(el)) unfolded.add(id);   // being read
    if (it && el && (el.classList.contains("folded") !== folded(it) || !!el.querySelector("[data-fold]") !== foldable(it))) renderEntry(it);
  });
}
function syncEmpty() {
  const empty = thread.length === 0;
  // An empty page opens the thread only for a send-to-the agent question. An analysis running on it is
  // said at the foot of the welcome (renderWelcome): opening the thread for it put a second sheet under
  // the welcome that held that one line and nothing else.
  $("thread").hidden = empty && !confirms.size; $("welcome").hidden = !empty;
  // Redrawn only when it actually changed: this runs on every capture message (one every few
  // seconds), and rebuilding it reset the flow picture's sideways scroll in a narrow window.
  if (empty) {
    const html = renderWelcome();
    if (html !== welcomeDrawn) { welcomeDrawn = html; $("welcome").innerHTML = html; }
  }
  fillPending();   // a line just drawn says its seconds at once, not a second later
}
// Every line that says what is being looked at now, with its seconds: the foot of the thread, or of
// the welcome on an empty page. The clock tick calls this too, so the markup itself never changes
// while an analysis runs.
function fillPending() {
  const pend = pendingItems();
  // nothing pending: a thinking line left from the look that just ended goes with it (it stayed under the answer)
  if (!pend.length) { document.querySelectorAll("[data-thought]").forEach((p) => { p.hidden = true; }); return; }
  document.querySelectorAll("[data-pending]").forEach((p) => { p.textContent = pendingText(pend[0]); });
  // the thinking pass's last finished sentence (pipeline.thought_line), quieter, under the status while it thinks
  // Not with Practice on: this comes before the answer has a card to keep it back, and a last sentence can be the answer itself
  const th = pend[0].stage?.stage === "think" && practiceSince == null ? pend[0].stage.thought || "" : "";
  document.querySelectorAll("[data-thought]").forEach((p) => { if (p.textContent !== th) p.textContent = th; p.hidden = !th; });
}
// Counted from when this panel heard about it. Reading the server's own ts against the browser's
// clock showed the wrong number of seconds whenever the two differ (the browser is Windows, the
// server is a container), and a clock a minute behind made the countdown start at two minutes.
function confirmLeft(c) { return Math.max(0, Math.round(c.timeout - (Date.now() / 1000 - (c.gotAt ?? c.ts)))); }
// c.timeout is what the server says is left when it sends it (a panel opened half way through a
// wait is told the remainder, not the whole), and gotAt is this browser's own clock from then.
// A picture in the thread takes its room when it arrives (a flowchart is drawn after the answer ended, a screen to confirm loads after its card): the end stays in view
document.addEventListener("load", (e) => { if (e.target.closest?.("#thread")) followEnd(); }, true);
function confirmHtml(c) {
  const what = escapeHtml(c.what || "");
  const preview = c.thumb ? `<img src="${escapeHtml(c.thumb)}" alt="${t("Screen to send to the agent", { agent: AG() })}" />` : c.text ? `<pre>${escapeHtml(c.text)}</pre>` : "";
  return row(t("Confirm"), `<div class="alert warn confirm"><div class="msg"><b>${t("Send to the agent?", { agent: AG() })}</b> ${what}
      <span class="cap" data-countdown="${escapeHtml(c.cid)}">${t("Skipped in {n} s", { n: confirmLeft(c) })}</span>${preview}</div>
      <div class="acts"><button class="btn sm pen" data-confirm="${escapeHtml(c.cid)}" data-send="1">${t("Send")}</button>
      <button class="btn sm" data-confirm="${escapeHtml(c.cid)}" data-send="0">${t("Don't send")}</button></div></div>`);
}
function renderTail() {   // the foot of the page: a send to confirm, "looking at a new screen", "nothing to solve here"
  const pend = pendingItems();
  const last = items.get(latestId());
  let html = [...confirms.values()].map(confirmHtml).join("");
  if (pend.length) html += row("", `<div class="topline pending"><span class="spin"></span><span data-pending></span></div><p class="thought" data-thought hidden></p>`);
  else if (lastNone && (!last || lastNone.ts > last.ts)) html += row("", `<p class="cap">${noneText()}</p>`);
  // Written only when it changed: a send-to-the agent card rebuilt by an analysis starting beside it lost the keyboard
  // focus on its Send and a press that straddled the rebuild. The pending line's words
  // and seconds are filled in by fillPending (syncEmpty, and the clock), so its markup stays the same while it runs.
  const tail = $("thread-tail");
  if (html !== tailDrawn) {
    if (pressIn === tail) { tail.dataset.redraw = "1"; syncEmpty(); return; }   // after the press (endPress)
    const keep = focusKey(document.activeElement, tail);
    tailDrawn = html; tail.innerHTML = html;
    if (keep) refocus(keep, tail);
  }
  syncEmpty();
}
let tailDrawn = null;   // what renderTail last wrote
function askEnabled() { return status.canAsk && wsState === "up"; }
// A placeholder wider than the field is simply cut, mid-word, with nothing to say it was cut, and
// the field is only as wide as the window leaves it (246px of text at 360px). So every state gives
// its wording from the fullest down to the shortest, and the widest one that fits is the one shown.
const ASK_TEXT = {
  on: [t("Ask more about the problem just solved (e.g. why is 3 the answer?)"), t("Ask more about the problem just solved"), t("Ask a follow-up")],
  down: [t("Questions once the server is connected"), t("Questions once connected"), t("Ask once connected")],
  stale: [t("Server restarted: questions from the next answer"),
    t("Questions from the next answer"), t("Ask after the next answer")],
  empty: [t("Questions once an answer is in"), t("Questions once an answer is in"), t("Ask after an answer")],
};
let askRuler = null;   // one canvas, kept: a new one per call would churn on every resize frame
function fitText(el, texts) {
  const s = getComputedStyle(el);
  // clientWidth already leaves the border out; the padding is what the text itself cannot use.
  const room = el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight) - 2;
  if (!(room > 0)) return texts[texts.length - 1];   // not laid out yet: the shortest always fits
  askRuler = askRuler || document.createElement("canvas").getContext("2d");
  askRuler.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
  return texts.find((t) => askRuler.measureText(t).width <= room) || texts[texts.length - 1];
}
function syncAsk() {
  const on = askEnabled();
  const ask = $("ask");
  // Disabled while the connection is down, the box drops the keyboard's focus: it comes back with the connection
  if (!on && document.activeElement === ask) askHadFocus = true;
  ask.disabled = !on; $("askbtn").disabled = !on;
  if (on && askHadFocus) { askHadFocus = false; if (document.activeElement === document.body) ask.focus({ preventScroll: true }); }
  ask.placeholder = fitText(ask, ASK_TEXT[on ? "on" : wsState !== "up" ? "down" : thread.length ? "stale" : "empty"]);
}

let askHadFocus = false;
function paintAnswer(root, type, answer, label) {
  const box = root.querySelector("[data-answer]");
  if (!box) return;
  // No answer line, yet or any more: an engine that starts the answer over throws away what the first
  // one wrote, its answer line with it, and returning here kept that discarded line up over the body
  // the new engine was writing. Within one engine's stream the line only ever grows.
  if (!answer) { box.hidden = true; return; }
  box.hidden = false;
  const length = answer.replace(/[`*$\\]/g, "").length;   // what is read, without the marks around it
  box.classList.toggle("short", length <= 10);
  // A long line is set smaller (index.html, .long): at the highlighter's size a 90-character answer
  // filled five lines of a 420 px window and pushed the reasoning below the fold.
  box.classList.toggle("long", length > 40);
  const lb = box.querySelector("[data-albl]");
  if (lb) lb.textContent = label;
  // Several problems answered at once come as one line, "1) ... 2) ...": a line each
  const many = answerItems(answer), holder = box.querySelector(".answer-text");
  if (many && holder) {
    holder.innerHTML = `<ol class="ans-list">${many.map(() => '<li><mark class="hl"></mark></li>').join("")}</ol>`;
    holder.querySelectorAll("mark").forEach((m, i) => renderInto(m, many[i], true));
    return;
  }
  // A summary of several sentences: the first, the point, marked; the rest under it a line each and unmarked. Marked
  // whole, five lines of it read as one block
  const parts = answer && String(answer).length > 90 ? summarySentences(answer) : [];
  if (parts.length > 1 && holder) {
    holder.innerHTML = `<mark class="hl" data-aval></mark><span class="ans-more">${parts.slice(1).map(() => "<span></span>").join("")}</span>`;
    renderInto(holder.querySelector("[data-aval]"), parts[0], true);
    holder.querySelectorAll(".ans-more > span").forEach((sp, i) => renderInto(sp, parts[i + 1], true));
    return;
  }
  if (holder && (!holder.querySelector("[data-aval]") || holder.querySelector(".ans-more"))) holder.innerHTML = '<mark class="hl" data-aval></mark>';
  renderInto(box.querySelector("[data-aval]"), answer, true);
}
// An answer being written is drawn again on every frame, and past some thousands of characters drawing it took longer
// than a frame: at 30,000 characters the main thread was 91% busy and the stream took twice its time to arrive. Blocks
// that have ended do not change, so from LIVE_FROM on they stay in the page and only what comes after the last safe
// blank line is drawn again. The final drawing, when the answer ends, is the whole text as before.
const LIVE_FROM = 4000;
// Where the finished blocks of `md` end: after a blank line outside any code fence or $$ block, when what follows it is
// not a list item, a table row or an indented line (which may still belong to the block above)
function stableCut(md) {
  let fence = false, math = false, off = 0, cut = 0;
  const lines = md.split("\n");
  for (let i = 0; i < lines.length - 1; i++) {
    const l = lines[i];
    off += l.length + 1;
    if (/^\s*(```|~~~)/.test(l)) fence = !fence;
    else if (!fence && (l.match(/\$\$/g) || []).length % 2) math = !math;
    if (!fence && !math && !l.trim()) {
      const next = lines[i + 1];
      if (next && !/^(\s|[-*+] |\d+[.)] |\|)/.test(next)) cut = off;
    }
  }
  return cut;
}
function paintLive(el, md) {
  let st = el.__live;
  // the start of a stream, or the engine starting over: from nothing
  if (!st || !md.startsWith(st.text)) { st = el.__live = { text: "", tail: [] }; el.textContent = ""; }
  st.tail.forEach((n) => n.remove());
  const rest = md.slice(st.text.length), cut = stableCut(rest);
  const add = (src) => {
    if (!src) return [];
    const holder = document.createElement("div"), box = document.createElement("div");
    box.className = "md"; holder.append(box);
    renderInto(box, src); holdPictures(box); textStyle(holder); typesetMath(box); liveCode(box);
    const nodes = [...box.childNodes];
    el.append(...nodes);
    return nodes;
  };
  if (cut) { add(rest.slice(0, cut)); st.text += rest.slice(0, cut); }
  st.tail = add(rest.slice(cut));
}
function paintItem(it, final) {
  const el = entryEl(it.id);
  if (!el || (it.error && !wrote(it))) return;
  const { type, answer, asked, body } = it.head;
  // The stream stopped part way: say so beside the answer too, not only beside the body (the
  // ANSWER line may itself have been cut off).
  const label = ANSWER_LABEL[type] || t("Summary");
  // Not on one Practice keeps back: it has no answer row, and the first one in it would be a follow-up's
  if (!held(it)) paintAnswer(el, type, answer, it.error ? t("{label}, unfinished", { label }) : label);
  // a problem that is not in Korean: what it asks, in Korean, above the answer it is answered in
  const askedRow = el.querySelector("[data-askedrow]"), askedEl = el.querySelector("[data-asked]");
  if (askedRow && askedEl) {
    askedRow.hidden = !asked;
    el.classList.toggle("has-asked", !!asked);   // folded, a card with its question shows it, and not the end of what was heard
    // Inline markdown, sanitised like the answer line: as text, a file name in backticks was shown
    // with its backticks ("`count.py` when it runs ...").
    if (asked) renderInto(askedEl, asked, true);
  }
  // A folded answer is drawn when it is opened: parsing, formulas and highlighting for what is display:none were most of
  // what 200 restored answers cost (560 ms and 80,000 nodes, against 285 ms and 23,000)
  if (folded(it)) { typesetMath(el); return; }   // its answer line shows, and may hold a formula
  const bodyEl = el.querySelector(":scope > .row [data-body]");
  if (!bodyEl) return;
  // Kept back by Practice: the hints asked for, drawn as the whole would be, and nothing while it is written
  if (held(it)) {
    if (it.live) return;
    renderInto(bodyEl, shownText(it));
    if (final) enhance(el);
    return;
  }
  if (it.live && (body || "").length >= LIVE_FROM) { paintLive(bodyEl, body); return; }
  bodyEl.__live = null;
  renderInto(bodyEl, body || "");
  const vb = el.querySelector("[data-vbody]");
  if (vb && it.verify?.text) {   // the agent's corrected solution (or its reply as it is) under the local one
    const v = splitHead(it.verify.text, true), va = el.querySelector("[data-vans]");
    if (va && v.answer) renderInto(va, v.answer, true);
    renderInto(vb, it.verify.verdict === "fix" ? v.body : it.verify.text);
  }
  if (!it.live) { bodyEl.classList.remove("cursor"); if (final) enhance(el); }
  else { holdPictures(bodyEl); textStyle(el); typesetMath(el); liveCode(bodyEl); }
}
function paintTurn(turn, final) {
  const el = document.querySelector(`[data-turn="${turn.id}"]`);
  // Nothing was written before it failed: there is no half answer to paint, only the error box.
  if (!el || (turn.error && !turnWrote(turn))) return;
  const h = splitHead(turn.raw, !turn.live);
  paintAnswer(el, h.type, h.answer, t("Reply"));
  const bodyEl = el.querySelector("[data-body]");
  if (turn.live && (h.body || "").length >= LIVE_FROM) { paintLive(bodyEl, h.body); return; }
  bodyEl.__live = null;
  renderInto(bodyEl, h.body || "");
  if (!turn.live) { bodyEl.classList.remove("cursor"); if (final) enhance(el); }
  else { holdPictures(bodyEl); textStyle(el); typesetMath(el); liveCode(bodyEl); }
}

const raf = new Set();
function schedule(key, fn) {
  if (raf.has(key)) return;
  raf.add(key);
  requestAnimationFrame(() => { raf.delete(key); fn(); });
}

// ---------- following the newest without yanking the view ----------
// "The bottom" is the end of the notebook (its question box), not of the page: in the one-column
// layout the rail sits below it, and following new answers must not land in the rail. Following
// holds while that end is on screen (in two columns the rail can make the page a little longer)
// or just below it; scrolling up by wheel, keys or touch stops it at once, however small the step.
// The thread's end, where the question box rests after it: the column's foot less the room under a thread shorter than the page
// (index.html, .stage-fill). Following goes to the thread's end, not to the foot of a page a taller right column made longer
const stageEnd = () => $("stage").getBoundingClientRect().bottom - ($("stage-fill")?.getBoundingClientRect().height || 0) + window.scrollY;
const nearBottom = () => { const end = stageEnd(); return end <= window.scrollY + window.innerHeight + 140 && end >= window.scrollY + 80; };
const motion = () => (calm() ? "auto" : "smooth");
let autoUntil = 0;   // scrolls the panel makes itself (following, keeping a follow-up in view) are not ones made by hand
function toBottom(smooth = false) {
  // Not while a press is under way in the thread: the page moved under the pointer and the press landed on whatever
  // came under it (endPress follows once the press is over)
  if (pressIn) { pressIn.dataset.follow = "1"; return; }
  autoUntil = Date.now() + (smooth ? 900 : 120);
  window.scrollTo({ top: Math.max(0, stageEnd() - window.innerHeight), behavior: smooth ? motion() : "auto" });
}
// Reading stops the following, but only while the reading goes on: once nothing has been scrolled
// by hand for FOLLOW_AGAIN_MS (up or down), the NEXT new answer brings the page back to the newest.
// The same answer growing or finishing never pulls the view down.
const FOLLOW_AGAIN_MS = 8000;
let handScrollAt = 0;
let followTurn = null;   // a follow-up being written: kept in view instead of the end of the page
// The answer picked in the contents, or pointed at by a notice: the ribbon and the screen stay on it until the page is scrolled by hand.
// By position, a short answer lost the place to the one under it and the end of the page to the newest (5 rows of 22 went elsewhere)
let pinnedView = null, pinnedAt = 0;
function unpin() { if (pinnedView != null) { pinnedView = null; updateView(); } }
function readerMoved() { handScrollAt = Date.now(); }
function stopFollowing() { stick = false; followTurn = null; readerMoved(); }
function following() {   // asked only when a new entry joins the notebook
  if (followTurn != null || pinnedView != null) return false;   // picked from the contents: a new answer offers the jump, however long it is read
  if (!stick && Date.now() - handScrollAt > FOLLOW_AGAIN_MS) { stick = true; $("jump").hidden = true; }
  return stick;
}
function followEnd() { if (stick && followTurn == null) toBottom(); }   // an entry grew: keep the end in view if following
// Resized, the text wraps anew and the end moves: that is not a scroll away from it by hand, so the scrolls it brings do not stop the following
addEventListener("resize", () => { autoUntil = Math.max(autoUntil, Date.now() + 500); schedule("resize-follow", followEnd); clearTimeout(followEnd.later); followEnd.later = setTimeout(followEnd, 250); });
// The newest answer the day and the kind chosen let be seen
function latestShown() {
  for (let i = thread.length - 1; i >= 0; i--) { const it = items.get(thread[i]); if (it && (inChoice(it) || it.live)) return thread[i]; }
  return latestId();
}
let jumpFor = null;   // the new answer the jump key offers
function afterGrow() {   // a new entry joined at the bottom: follow it, or offer a jump if reading above
  if (following()) toBottom();
  else { const it = items.get(latestId()); if (it && (inChoice(it) || it.live)) { $("jump").hidden = false; jumpFor = it.id; } }   // not to an answer the filter hides
  updateView();
}
function showTurn(t) {   // keep a follow-up's newest line in view, above the question box
  const el = document.querySelector(`[data-turn="${t.id}"]`);
  if (!el) return;
  if (pressIn) { pressIn.dataset.follow = "1"; return; }   // after the press (endPress)
  autoUntil = Date.now() + 120;
  el.scrollIntoView({ block: "end" });
}
function updateView() {   // the entry under the upper third of the window; its screen goes in the rail
  let id = latestShown();
  const picked = pinnedView != null && items.has(pinnedView) && !entryEl(pinnedView)?.hidden ? pinnedView : null;
  const asking = followTurn != null ? turns.get(followTurn)?.parent : null;   // a follow-up being written: the answer it is about
  if (picked != null) id = picked;
  else if (asking != null && items.has(asking)) id = asking;
  else if (!stick) {
    // The last entry that has begun above the line: in the gap between two it stays on the one just read. Going by
    // "the one the line is in", a gap fell back to the latest, and the screen and the row flickered at every boundary.
    const line = window.innerHeight * 0.33;
    // By halves over the thread's own children: walking every entry on each scroll frame was 43% of a long thread's scrolling
    const shown = [...$("thread").children].filter((e) => e.classList.contains("entry") && !e.hidden);
    let lo = 0, hi = shown.length - 1, at = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (shown[mid].getBoundingClientRect().top <= line) { at = mid; lo = mid + 1; } else hi = mid - 1;
    }
    if (at >= 0) id = idOf(shown[at].dataset.id);
  }
  if (id !== viewId) { viewId = id; renderShot(); markIndex(); }
}
let lastY = window.scrollY;
window.addEventListener("scroll", () => schedule("scroll", () => {
  const down = window.scrollY > lastY; lastY = window.scrollY;
  const auto = Date.now() < autoUntil;
  if (!auto) { followTurn = null; if (!stick) readerMoved(); }     // a scroll by hand while reading: the 8 s clock restarts
  if (!auto && pinnedView != null && Date.now() - pinnedAt > 1500) pinnedView = null;   // scrolled by hand (the pick's own smooth scroll is over by then)
  if (stick && !auto && !nearBottom()) stopFollowing();              // dragged the scrollbar or jumped away
  else if (!stick && !auto && down && nearBottom()) stick = true;    // came back down to the end
  if (stick) $("jump").hidden = true;
  updateView();
}), { passive: true });
function scrollsInside(el) {   // an inner box (the rail, the transcript) that can still scroll up takes the wheel itself
  for (; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
    const oy = getComputedStyle(el).overflowY;
    if ((oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight && el.scrollTop > 0) return true;
  }
  return false;
}
window.addEventListener("wheel", (e) => { if (!e.target.closest?.("#history, .hear-body")) unpin(); if (e.deltaY < 0 && !scrollsInside(e.target)) stopFollowing(); else if (!stick) readerMoved(); }, { passive: true });
let touchY = null;
window.addEventListener("touchstart", (e) => { touchY = e.touches[0]?.clientY ?? null; }, { passive: true });
window.addEventListener("touchmove", (e) => { if (!e.target.closest?.("#history, .hear-body")) unpin(); const y = e.touches[0]?.clientY; if (touchY != null && y > touchY + 8) stopFollowing(); else if (!stick) readerMoved(); }, { passive: true });

// ---------- rail ----------
// The picture's box changes with the column's fit, and with it where the picture stands in its frame: the boxes on it go with it
if (typeof ResizeObserver !== "undefined") { const boxes = new ResizeObserver(() => { for (const id of ["region", "roi"]) { const e = document.getElementById(id); if (e?.box && !e.hidden) placeBox(e, e.box); } }); boxes.observe(document.getElementById("shot")); boxes.observe(document.getElementById("thumb")); }
function placeBox(el, box) {
  el.box = box;
  if (!box || box.length !== 4) { el.hidden = true; return; }
  const [x0, y0, x1, y1] = box, frame = $("shot").getBoundingClientRect(), img = $("thumb"), pic = img.getBoundingClientRect();
  // In percent of the frame, so a frame resized keeps them on the picture; the frame keeps its shape, and so does the picture in it
  const on = !img.hidden && pic.width > 0 && frame.width > 0 && frame.height > 0;
  const fx = on ? pic.width / frame.width : 1, fy = on ? pic.height / frame.height : 1;
  const ox = on ? (pic.left - frame.left) / frame.width : 0, oy = on ? (pic.top - frame.top) / frame.height : 0;
  Object.assign(el.style, { left: `${(ox + x0 * fx) * 100}%`, top: `${(oy + y0 * fy) * 100}%`, width: `${(x1 - x0) * fx * 100}%`, height: `${(y1 - y0) * fy * 100}%` });
  el.hidden = false;
}
$("thumb").addEventListener("load", () => { for (const el of [$("region"), $("roi")]) if (el.box) placeBox(el, el.box); });
function renderShot() {
  const it = viewId != null ? items.get(viewId) : null;
  const img = $("thumb"), reg = $("region"), roi = $("roi");
  // No answer to show the screen of yet, but an analysis running on a screen it came with: the first one
  // on an empty page. That screen is shown, so this card agrees with the capture card above it, which
  // says screens are coming in, where it used to say that none had arrived.
  const looking = !it && !drawing && capture.screen_on ? pendingItems().find((p) => p.thumb) || null : null;
  // Screen capture off: don't keep showing the last screenshot of the viewed solution; clear it.
  const noneShot = !it && !looking && lastNone && lastNone.thumb && capture.screen_on ? lastNone : null;
  const thumb = drawing ? drawing.url
    : capture.screen_on ? ((it && it.thumb) || (looking && looking.thumb) || (noneShot && noneShot.thumb)) : null;
  const drawn = settingsValues.roi_box || null;
  const stale = !!drawing && !drawing.live;
  // The age of the last screen is a server stamp (drawing.ts, in the server's seconds), so it is read
  // against the server's clock: against this browser's, ten minutes apart made 2 min ago into 12 min ago.
  const stamp = (t) => { const [d, ...r] = String(t).split(" "); return `<span class="when"><b>${escapeHtml(d)}</b> ${escapeHtml(r.join(" "))}</span>`; };
  const shotTitle = drawing
    ? (drawing.live ? `<span class="now-dot"></span>${t("Screen now")}` : t("Last screen {when}", { when: stamp(fmtAgo(serverNow() - (drawing.ts ?? serverNow()))) }))
    // "This answer's screen" only over a screen that is then shown: a spoken problem has none, and the title
    // used to promise one above a frame that said there was none. It names the card, not a state ("Solved ..." read as one), in words
    // that leave its date room at 1366 (229 px for both)
    : it && thumb ? t("Screen at {when}", { when: stamp(fmtWhen(it.ts)) })
    : looking ? `<span class="now-dot"></span>${t("Analyzing {when}", { when: stamp(fmtWhen(looking.ts)) })}`
    : noneShot ? t("No problem {when}", { when: stamp(fmtWhen(noneShot.ts)) }) : t("Screen");
  // The words and the date in one line of their own, so they stand on one baseline, and that line centred with the title's mark (index.html)
  setHtml("shot-title", `<span class="st-t">${shotTitle}</span>`);
  $("shot").classList.toggle("stale", stale);
  // The screen now and an answer's screen are two different things and looked the same (index.html, .shot[data-of])
  $("shot").dataset.of = drawing?.live || looking ? "now" : drawing ? "last" : it && thumb ? "answer" : noneShot ? "none" : "";
  $("shot").classList.toggle("drawing", !!drawing);
  if (thumb) {
    if (img.src !== thumb) { img.src = thumb; replay(img, "swap"); }
    img.hidden = false; $("shot-empty").hidden = true;
    if (!drawing && it && it.region) placeBox(reg, it.region); else reg.hidden = true;
    placeBox(roi, drawing ? drawing.box : drawn);
  } else {
    img.hidden = true; reg.hidden = true; roi.hidden = true; $("shot-empty").hidden = false;
    // An empty frame with a line through it: the card keeps its shape while there is nothing in it,
    // instead of a line of grey text floating in a box.
    const mark = `<svg class="empty-mark" viewBox="0 0 48 34" fill="none" stroke="currentColor"
      stroke-width="1.6" aria-hidden="true"><rect x="1.5" y="1.5" width="45" height="31" rx="3"/>
      <path d="M8 26l9.5-11 7 7.5 5.5-5.5L40 26" stroke-linejoin="round"/><circle cx="16" cy="11" r="2.6"/></svg>`;
    $("shot-empty").innerHTML = mark + `<span>` + (!capture.screen_on ? t("Screen capture off")
      : it && it.forgot ? t("Screen cleared: the capture was turned off")
      : it && it.trigger === "voice" ? t("No screen: a spoken problem")
      : it ? t("No screen")
      // Screens are coming in (the capture card says so) and none has been answered yet: say that,
      // rather than that no screen has arrived.
      : capture.last_frame ? t("No screen solved yet") : t("No screen received")) + `</span>`;
  }
  // A problem that runs off the top or the bottom of the screen is usually longer than the screen:
  // say so, since scrolling it is what joins the rest (the capture program then sends one page).
  const r = it && it.region;
  const EDGE = 0.012;
  const cutTop = r && r[1] <= EDGE, cutBottom = r && r[3] >= 1 - EDGE;
  // What went to the agent is said in the server's words: a Korean server's, or an English one's (server/pipeline.py, _agent_payload)
  const sentCrop = it?.meta?.engine === "agent" && (it.meta.sent || []).some((x) => x.to === "agent" && /^(문제 부분|이어 붙인|problem (part|area|crop)|stitched|joined problem)/i.test(x.what || ""));
  const boxSize = drawing?.box
    ? t(" region {w}% wide · {h}% high", { w: Math.round((drawing.box[2] - drawing.box[0]) * 100), h: Math.round((drawing.box[3] - drawing.box[1]) * 100) })
    : "";
  $("shot-cap").textContent = drawing
    ? (stale ? t("Capture off: not the screen now. The region holds from the next screen") + boxSize
             : t("Drag to draw a region · Esc cancels") + boxSize)
    : it && it.region && thumb ? t("Highlight: where the problem was seen")
        + `${cutTop || cutBottom ? (cutTop && cutBottom ? t(" · it goes on above and below; scroll and it reads on") : cutTop ? t(" · it goes on above; scroll and it reads on") : t(" · it goes on below; scroll and it reads on")) : ""}`
        + `${sentCrop ? t(" · only this part went to the agent", { agent: AG() }) : ""}`
    : noneShot && thumb ? t("No problem found · if there is one, Reanalyze or draw a region")
    : drawn && thumb ? t("Only what is inside the dotted box is looked at and sent") : "";
  $("roi-clear").hidden = !drawn || !!drawing;
  $("roi-draw").querySelector(".lab-word").textContent = drawing ? t("Stop drawing") : drawn ? t("Redraw") : t("Draw a region");
  $("roi-draw").disabled = wsState !== "up" || !capture.screen_on;
}
// Drawing the box: the current screen comes from the server (not the viewed answer's older one),
// a drag on it gives the box in screen fractions, and the server keeps it as a setting.
function startDrawing() {
  if (drawing) { stopDrawing(); return; }
  if (send({ type: "thumb" })) toast(capture.clients ? t("Loading the screen now") : t("Loading the last screen"));
}
function stopDrawing() { drawing = null; renderShot(); }
function shotPoint(e) {
  const r = $("thumb").getBoundingClientRect();
  return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
}
$("shot").addEventListener("pointerdown", (e) => {
  if (!drawing || $("thumb").hidden) return;
  e.preventDefault();
  $("shot").setPointerCapture(e.pointerId);
  drawing.start = shotPoint(e); drawing.box = null;
});
$("shot").addEventListener("pointermove", (e) => {
  if (!drawing || !drawing.start) return;
  const [x, y] = shotPoint(e), [sx, sy] = drawing.start;
  drawing.box = [Math.min(sx, x), Math.min(sy, y), Math.max(sx, x), Math.max(sy, y)];
  placeBox($("roi"), drawing.box);
});
$("shot").addEventListener("pointerup", () => {
  if (!drawing || !drawing.start) return;
  const b = drawing.box;
  drawing.start = null;
  if (!b || b[2] - b[0] < 0.03 || b[3] - b[1] < 0.03) { toast(t("The region is too small"), null, "warn"); drawing.box = null; renderShot(); return; }
  const box = b.map((v) => Math.round(v * 1000) / 1000);
  if (setSetting("roi_box", box)) toast(t("Watching this region only"), null, "done");
  stopDrawing();
});
function forgetScreens() {   // screen capture off: the screenshots kept for the rail are deleted, not just hidden
  for (const it of items.values()) if (it.thumb) { it.thumb = null; it.region = null; it.forgot = true; }
  $("thumb").removeAttribute("src");
}
// Everything an answer can be found by: its kind, what was heard, the answer with its follow-ups (questions and
// answers), lower-cased once per search
// (the answer as read: its head lines, "TYPE:", "ANSWER:", kept every row for "type" and showed in the row)
function readText(raw) { const h = splitHead(raw || "", true); return [h.answer || "", h.body || ""].join("\n"); }
// The same words as the page shows them, for the search and its rows: what drawPictures draws as a picture (a chart's
// numbers, a diagram's source) is no words on the page, nor are the fences round code or a formula's TeX outside code
// (rows read "```mermaid flowchart L…" and were found by "mermaid"). The code inside a fence is kept as it is written, so
// "__init__" or "$files" still finds the answer that has it.
const PICTURE_FENCES = /^(chart|mermaid)$/i;
function plainRead(md) {
  const out = [], prose = [];
  const flush = () => {
    if (!prose.length) return;
    prose.join("\n").replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => texPlain(tex)).split("\n")
      .filter((line) => !/^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$/.test(line))   // a table's rule under its head
      .forEach((line) => { const p = plainAnswer(line, true); if (p) out.push(p); });
    prose.length = 0;
  };
  let fence = null;   // the open fence's marks and whether it is a picture, while inside one
  for (const line of String(md || "").split("\n")) {
    const open = /^[ \t]*(`{3,}|~{3,})[ \t]*([\w+-]*)/.exec(line);
    if (!fence && open) { flush(); fence = { mark: open[1], picture: PICTURE_FENCES.test(open[2]) }; continue; }
    if (fence && line.trim().startsWith(fence.mark) && !line.trim().slice(fence.mark.length).trim()) { fence = null; continue; }
    if (!fence) prose.push(line);
    else if (!fence.picture && line.trim()) out.push(line.trim());
  }
  flush();
  return out.join("\n");
}
// One Practice keeps back is found by what it shows: its question and the hints out, not the answer it keeps back, which a row
// found by it would show
function searchText(it) {
  const hold = held(it);
  const parts = [TYPE_LABEL[it.head.type] || it.head.type || "", it.transcript || "", it.head.asked || "", plainRead(hold ? shownText(it) : readText(it.raw)), it.error || ""];
  for (const tid of it.turns) { const t = turns.get(tid); if (t && !(hold && t.retry)) parts.push(t.q || "", plainRead(readText(t.raw))); }
  return parts.join("\n").toLowerCase();
}
// The row's text with the words searched for marked, escaped; around the first match when it is further in than
// the row can show, so the reason the row was kept is in view
function markedRow(text, words) {
  let t = text;
  const at = words.length ? t.toLowerCase().indexOf(words[0]) : -1;
  if (at > 60) t = "…" + t.slice(at - 20);
  t = t.slice(0, 120);
  // marked on the text and escaped piece by piece: marking the escaped text found words inside its entities ("amp")
  const low = t.toLowerCase(), hit = new Array(t.length).fill(false);
  for (const w of words) for (let i = low.indexOf(w); i >= 0; i = low.indexOf(w, i + 1)) hit.fill(true, i, i + w.length);
  let html = "", i = 0;
  while (i < t.length) {
    let j = i;
    while (j < t.length && hit[j] === hit[i]) j++;
    html += hit[i] ? `<mark>${escapeHtml(t.slice(i, j))}</mark>` : escapeHtml(t.slice(i, j));
    i = j;
  }
  return html;
}
let histQuery = "";   // what the index is narrowed to (the search field), lower-cased words
let histDay = "", histKind = "", historyDays = [];   // the day and the kind chosen; the days the server keeps
// Starred, chosen in the day list (its value STARRED): the starred answers of every day; and how many the server keeps
const STARRED = "starred";
let histStar = false, historyStarred = 0;
const dayOf = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function dayLabel(day) {
  const [y, m, d] = day.split("-").map(Number), now = new Date();
  return (y === now.getFullYear() ? t("{m}/{d}", { m, d }) : t("{y}/{m}/{d}", { y, m, d })) + (day === dayOf(now.getTime()) ? t(" (today)") : "");
}
const shownAnyway = new Set();   // answers written, or asked about, while a filter was on: they stay until the filter changes
const inChoice = (it) => (!histDay || dayOf(it.ts) === histDay) && (!histKind || it.head.type === histKind) && (!histStar || !!it.starred)
  || shownAnyway.has(it.id);
// The thread shows what the contents list: an entry outside the day or the kind chosen is out of sight
function applyChoice() {
  let shown = 0;
  for (const id of thread) {
    const it = items.get(id), el = entryEl(id);
    if (!it || !el) continue;
    // an answer being written, or being asked about, stays: a question would otherwise go into a hidden card
    if ((histDay || histKind || histStar) && (it.live || it.turns.some((t) => turns.get(t)?.live))) shownAnyway.add(it.id);
    el.hidden = !inChoice(it);
    if (!el.hidden) shown++;
  }
  const none = $("choice-none");     // the whole thread filtered away is said, not a blank page
  none.hidden = !(thread.length && !shown && (histDay || histKind || histStar));
}
// The Starred choice as the server's /history asks for it: only while it is chosen
const starParam = () => (histStar ? { starred: 1 } : {});
// A row of the server's history as the entry it was (server/history.py). What was asked of it goes on as it is.
function restore(row) {
  const had = items.get(row.id);
  // A card the dropped connection cut off is replaced by the whole answer, if the server finished it after all
  if (had && !(had.hint === "interrupted" && !had.live)) {
    let mended = false;
    for (const t of row.turns || []) {
      const mine = turns.get(t.id);
      if (mine && !mine.live && mine.hint === "interrupted" && t.text) {
        Object.assign(mine, { raw: t.text, error: null, hint: "", meta: t, check: t.check || null });
        mended = true;
      }
    }
    // A star changed while this page was away from the server (another panel, a dropped connection): the server's is the one
    const restar = typeof row.starred === "boolean" && row.starred !== !!had.starred;
    if (restar) had.starred = row.starred;
    if (mended) renderEntry(had); else if (restar) paintStar(had);
    return false;
  }
  if (had) { had.turns.forEach((t) => turns.delete(t)); items.delete(row.id); entryEl(row.id)?.remove(); thread = thread.filter((id) => id !== row.id); }
  const it = newItem({ id: row.id, trigger: row.trigger, transcript: row.transcript, thumb: row.thumb });
  it.ts = row.ts * 1000; it.raw = row.text || ""; it.live = false; it.shown = true; it.restored = true; it.starred = !!row.starred;
  // Only a box the server says is what the crop took: one kept from before holds the model's first guess, often a part of the problem
  it.meta = row; it.region = (row.region_shown && row.region) || null; it.check = row.check || null; it.verify = row.verify || null; it.head = splitHead(it.raw, true);
  for (const t of row.turns || []) {
    turns.set(t.id, { id: t.id, parent: it.id, q: t.q || "", raw: t.text || "", live: false, error: null, hint: "",
      meta: t, retry: !!t.retry, kind: t.kind, check: t.check || null });
    it.turns.push(t.id);
  }
  practiceArrived(it, true);   // answered while Practice was on, the panel closed or not: kept back like one that came here
  items.set(it.id, it); thread.push(it.id);
  return true;
}
async function loadHistory(params = {}) {
  if (demo) return;
  try {
    const url = new URLSearchParams(params).toString();
    const [rows, days] = await Promise.all([fetch(`history?${url}`).then((r) => r.json()), fetch("history/days").then((r) => r.json())]);
    let added = false;
    for (const row of rows.answers || []) added = restore(row) || added;
    historyDays = days.days || [];
    historyStarred = days.starred || 0;
    heardAny = !!days.heard; syncHeardKeys();
    if (added) {
      thread.sort((a, b) => items.get(a).ts - items.get(b).ts);
      // Over the limit the oldest go, but not what this request just found: an old answer searched for was the first out
      const found = new Set((rows.answers || []).map((r) => r.id));
      while (thread.length > MAX_ITEMS) {
        const at = thread.findIndex((id) => !found.has(id) && !items.get(id)?.live);
        const old = thread.splice(Math.max(0, at), 1)[0], o = items.get(old);
        if (o) o.turns.forEach((t) => turns.delete(t));
        items.delete(old); unfolded.delete(old);
      }
      keepPlace(syncThread);
      renderAll();
    } else renderIndex();
    return true;
  } catch (_) { return false; /* a server without the history, or none yet: the panel holds what it hears from now on */ }
}
// What was being read when a filter went on, to come back to when the last filter goes: with each change keeping only the height of what is in view, the
// view ended up at the answer the filter had left, a whole page from where it had been
let placeBefore = null;
function choiceChange(change) {
  if (!histDay && !histKind && !histStar && !stick) {
    const line = window.innerHeight * 0.33, e = [...document.querySelectorAll(".entry:not([hidden])")].find((x) => x.getBoundingClientRect().bottom > line);
    placeBefore = e ? { id: idOf(e.dataset.id), top: e.getBoundingClientRect().top } : null;
  }
  keepPlace(() => { shownAnyway.clear(); change(); renderIndex(); });
  if (!histDay && !histKind && !histStar && placeBefore) {
    const e = entryEl(placeBefore.id);
    if (e && !e.hidden && !stick) { autoUntil = Date.now() + 120; window.scrollBy(0, e.getBoundingClientRect().top - placeBefore.top); }
    placeBefore = null;
  }
  updateView();
}
function clearChoice() {
  choiceChange(() => { histDay = ""; histKind = ""; histStar = false; $("hist-day").value = ""; $("hist-kind").value = ""; });
}
function fillChoices() {
  const day = $("hist-day"), kind = $("hist-kind");
  // The server's days and counts, and what this page holds that they do not have yet (answers since they were asked for)
  const here = new Map();
  for (const it of items.values()) { const d = dayOf(it.ts); here.set(d, (here.get(d) || 0) + 1); }
  const known = new Map(historyDays.map((d) => [d.day, d.n]));
  for (const [d, n] of here) known.set(d, Math.max(known.get(d) || 0, n));
  const dayList = [...known].sort((a, b) => (a[0] < b[0] ? 1 : -1));
  // Starred stands first among the days, with how many: the server's count, or this page's while it has more. Offered while there
  // are some, and while it is chosen, so the choice shows as it is
  const stars = Math.max(historyStarred, [...items.values()].filter((it) => it.starred).length);
  const starHtml = stars || histStar ? `<option value="${STARRED}" data-short="${escapeHtml(t("Starred"))}">${escapeHtml(t("Starred"))} · ${stars === 1 ? t("{n} answer", { n: stars }) : t("{n} answers", { n: stars })}</option>` : "";
  const dayHtml = `<option value="">${t("All days")}</option>` + starHtml + dayList.map(([d, n]) => {
    const name = fmtDay(new Date(`${d}T12:00:00`).getTime());
    // From when to when, of the server's kept answers and those on this page
    const server = historyDays.find((x) => x.day === d), ts = [...items.values()].filter((it) => dayOf(it.ts) === d).map((it) => it.ts);
    if (server?.first) ts.push(server.first * 1000, server.last * 1000);
    const span = ts.length ? ` · ${fmtClock(Math.min(...ts))} ~ ${fmtClock(Math.max(...ts))}` : "";
    return `<option value="${d}" data-short="${name}">${name} · ${n === 1 ? t("{n} answer", { n }) : t("{n} answers", { n })}${span}</option>`;
  }).join("");
  if (day.dataset.html !== dayHtml) { day.dataset.html = dayHtml; day.innerHTML = dayHtml; day.value = histStar ? STARRED : histDay; }
  // The kinds of the day chosen, each with how many, as the days have theirs: every kind of every day was offered, and one picked for a day
  // that had none of it gave "0/22 맞는 답 없음". The kind already picked stays offered, so the choice shows as it is
  const perKind = new Map();
  for (const it of items.values()) {
    const t = it.head.type;
    if (t && TYPE_LABEL[t] && (!histDay || dayOf(it.ts) === histDay) && (!histStar || it.starred)) perKind.set(t, (perKind.get(t) || 0) + 1);
  }
  if (histKind && TYPE_LABEL[histKind] && !perKind.has(histKind)) perKind.set(histKind, 0);
  // the list names each kind in full, as the settings' types do; the closed button keeps the margin's short name
  const kindHtml = `<option value="">${t("All types")}</option>` + [...perKind].map(([type, n]) => `<option value="${type}" data-short="${escapeHtml(TYPE_LABEL[type])}">${escapeHtml(TYPE_NAME[type])} · ${n === 1 ? t("{n} answer", { n }) : t("{n} answers", { n })}</option>`).join("");
  if (kind.dataset.html !== kindHtml) { kind.dataset.html = kindHtml; kind.innerHTML = kindHtml; kind.value = histKind; }
  syncPick(day); syncPick(kind);
}
function renderIndex() {
  $("hist-none").hidden = thread.length > 0;
  $("hist-tools").hidden = thread.length === 0;
  const words = histQuery.split(/\s+/).filter(Boolean);
  // every word somewhere in the answer, in any order, as a search box is read; and the day and the kind chosen
  const ids = [...thread].reverse().filter((id) => {
    const it = items.get(id);
    return inChoice(it) && (!words.length || ((s) => words.every((w) => s.includes(w)))(searchText(it)));
  });
  applyChoice();
  fillChoices();
  const narrowed = words.length || histDay || histKind || histStar;
  $("hist-count").textContent = !thread.length ? "" : narrowed ? `${ids.length}/${thread.length}` : String(thread.length);
  const miss = $("hist-nomatch");
  miss.hidden = !(narrowed && !ids.length && thread.length);
  if (!miss.hidden) {
    const typed = $("hist-q").value.trim();   // as it was typed, not lower-cased
    // no particle after what was typed: a Latin word's ("GPU") is not told by its letters
    miss.textContent = words.length ? t("No answers contain {q}", { q: `'${typed}'` }) : t("No matching answer");
  }
  // rebuilt on every status message: a row with the keyboard's focus gets it back
  const focused = document.activeElement?.closest?.("#history .h")?.dataset.id;
  const listEl = $("history");
  if (pressIn === listEl) { listEl.dataset.redraw = "1"; return; }   // a row under a press stays until it is a click (endPress)
  let lastDay = null;
  const perDay = new Map();   // how many answers each day's tab heads, of those listed
  for (const id of ids) { const d = dayOf(items.get(id).ts); perDay.set(d, (perDay.get(d) || 0) + 1); }
  const listHtml = ids.map((id) => {
    const it = items.get(id);
    const day = dayOf(it.ts), head = day !== lastDay ? `<li class="h-day"><span class="h-tab">${fmtDay(it.ts)}</span>${perDay.size > 1 ? `<span class="h-n">${perDay.get(day) === 1 ? t("{n} answer", { n: 1 }) : t("{n} answers", { n: perDay.get(day) })}</span>` : ""}</li>` : "";
    lastDay = day;
    const label = it.error ? t("Error") : it.live && !it.head.type ? t("Analyzing") : (TYPE_LABEL[it.head.type] || it.head.type || t("Result"));
    // What was asked names a row: that is what the eye looks for. The answer stands in where no question was written out, unless it
    // is a bare mark ("④" names nothing), and then the first sentence of the working, and last the kind
    const says = (s, block = false) => { const t = plainAnswer(s, block); return /[\p{L}\p{N}]{2,}/u.test(t) ? t : ""; };
    // a line of the body is read as a block: its heading's hashes and a table row's bars are marks there
    const firstLine = (s) => says(String(s || "").split(/(?<=[.?!。])\s|\n/).find((l) => says(l, true)), true);
    // One Practice keeps back is named by its question alone, or by what was heard: never its answer line or the first words of its working
    const hold = held(it);
    let text = it.error && !hold ? (HINT[it.hint] || HINT[""]).title
      : hold ? (plainAnswer(it.head.asked) || (it.trigger === "voice" ? says(it.transcript) : "") || t("Answer hidden for practice"))
      : (plainAnswer(it.head.asked) || says(it.head.answer) || firstLine(it.head.body) || label);
    // a row kept for words that are not in its first line shows where they are
    if (words.length && !words.every((w) => text.toLowerCase().includes(w))) {
      const whole = plainRead(hold ? shownText(it) : readText(it.raw)), at = whole.toLowerCase().indexOf(words[0]);
      if (at >= 0) text = whole.replace(/\s+/g, " ");
    }
    return `${head}<li><button class="h${it.error ? " err" : ""}${it.live ? " live" : ""}" data-id="${id}" title="${escapeHtml(text)}"
      data-kind="${it.error ? "" : escapeHtml(it.head.type || "")}">
      <span class="hk">${escapeHtml(label)}</span><span class="ht">${it.starred ? STAR_ROW() : ""}${markedRow(text, words)}</span><time>${fmtClock(it.ts)}</time></button></li>`;
  }).join("");
  // On every status message the same rows came out, and writing them again cost a layout of the whole rail
  if (listEl.dataset.html !== listHtml) { listEl.dataset.html = listHtml; listEl.innerHTML = listHtml; }
  markIndex();
  if (focused) $("history").querySelector(`.h[data-id="${focused}"]`)?.focus({ preventScroll: true });
}
// What Export takes, oldest first: the finished answers the contents list (the day and the kind chosen, and the words searched for)
function exportItems() {
  const words = histQuery.split(/\s+/).filter(Boolean);
  return thread.map((id) => items.get(id)).filter((it) => it && !it.live && inChoice(it) && words.every((w) => searchText(it).includes(w)));
}
// An answer's own headings two levels down, under the heading the file gives each answer (##): kept as they were, a body's
// "## Approach" stood level with the answers themselves, and a follow-up's (###) under the body's last heading. Lines in
// code blocks are left alone: "# a comment" there is code.
function nestHeadings(md) {
  let fence = "";
  return md.split("\n").map((line) => {
    const f = /^\s*(`{3,}|~{3,})/.exec(line);
    if (f) { if (!fence) fence = f[1][0]; else if (f[1][0] === fence) fence = ""; return line; }
    return fence ? line : line.replace(/^(#{1,4})(?=\s)/, (h) => "#".repeat(h.length + 2));
  }).join("\n");
}
// The answers in view as one Markdown file, oldest first: each with its time, kind and who answered, what was heard when
// it was a spoken problem, the answer without the engine's own TYPE, ANSWER and REGION lines, and its follow-ups.
function exportMarkdown() {
  const pad = (n) => String(n).padStart(2, "0");
  const when = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const out = [`# ${t("Sidenote answers ({when})", { when: when(Date.now()) })}`, ""];
  let written = 0;
  for (const it of exportItems()) {
    written++;
    const kind = it.error ? t("Error") : TYPE_LABEL[it.head.type] || it.head.type || t("Result");
    const who = it.meta ? `${it.meta.engine === "agent" ? AG() : t("Local model")}${it.meta.model ? ` · ${it.meta.model}` : ""}${it.meta.elapsed != null ? ` · ${t("{n} s", { n: it.meta.elapsed })}` : ""}` : "";
    out.push(`## ${when(it.ts)} ${kind}${who ? ` (${who})` : ""}`, "");
    if (it.trigger === "voice" && it.transcript) out.push(`> ${t("Heard: {text}", { text: it.transcript.replace(/\s+/g, " ") })}`, "");
    if (it.head.asked) out.push(`> ${t("Question: {text}", { text: String(it.head.asked).replace(/\s+/g, " ") })}`, "");
    if (it.error) out.push(t("Error: {text}", { text: it.error }), "");
    else {
      if (it.head.answer) out.push(`**${t("Answer: {text}", { text: it.head.answer })}**`, "");
      out.push(nestHeadings((it.head.body || "").trim()) || it.stopped || "", "");
    }
    for (const tid of it.turns) {
      const turn = turns.get(tid);
      if (!turn || turn.live) continue;
      out.push(`### ${turn.retry ? t("Solved again") : t("Follow-up: {q}", { q: turn.q })}`, "", turn.error ? t("Error: {text}", { text: turn.error }) : nestHeadings(readText(turn.raw).trim()), "");
    }
  }
  if (!written) { toast(t("No answers to export"), null, "warn"); return; }
  saveFile(out.join("\n"), "text/markdown;charset=utf-8", `sidenote-${fileStamp()}.md`);
  toast(written === 1 ? t("Exported {n} answer (Markdown)", { n: written }) : t("Exported {n} answers (Markdown)", { n: written }), null, "done");
}
// A file made here, downloaded as a link to it is
function saveFile(text, type, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);   // the download has its copy by then
}
// The time in a file's name: 20261104-1042
function fileStamp(d = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
}

// ---------- Export to Anki ----------
// The same answers as notes for Anki to import, one line each: Anki's headers, then each answer's question on the front and on the back
// its answer line and its key point (the solution's first part, as Practice cuts it), drawn by the panel's own Markdown and cleaned by
// its own sanitizing, tagged with its type and its day. Anki reads the file as tab-separated text whose fields are HTML, so nothing in
// a field may end it: a tab is written as its entity and a line break as <br>. Anki takes a line that starts with # for a comment and a
// field that starts with a quote mark for a quoted one, so those two are written as entities too. A formula keeps its TeX, in the
// \( \) and \[ \] Anki's MathJax reads; code keeps its text; nothing is a picture.
const ANKI_QUOTE = "\uE000";   // a quote mark in the words while they are written out: back as &quot; after, unlike an attribute's own
function ankiHtml(md, inline = false) {
  const box = document.createElement("div");
  renderInto(box, String(md || ""), inline);                  // the panel's Markdown, cleaned as an answer on the page is (PURIFY)
  // A formula as the TeX it was written in, set off as Anki's MathJax reads it; its line ends are spaces to TeX, and stay out of it
  box.querySelectorAll("span.math").forEach((m) => {
    const s = m.textContent, block = s.startsWith("$$") && s.endsWith("$$") && s.length >= 4;
    const tex = (block ? s.slice(2, -2) : s.replace(/^\$|\$$/g, "")).trim().replace(/\s*\n\s*/g, " ");
    m.replaceWith(block ? `\\[${tex}\\]` : `\\(${tex}\\)`);
  });
  box.querySelectorAll("pre > code").forEach((c) => { c.textContent = c.textContent.replace(/\n$/, ""); });   // a block's last line break is no line of its own
  // What the panel puts on its own elements says nothing in Anki: the class of a code block, a link's way of opening
  box.querySelectorAll("[class], [target], [rel]").forEach((e) => { e.removeAttribute("class"); e.removeAttribute("target"); e.removeAttribute("rel"); });
  box.querySelectorAll("*").forEach((e) => { for (const a of [...e.attributes]) if (/[\t\r\n]/.test(a.value)) e.setAttribute(a.name, a.value.replace(/\s+/g, " ")); });
  // The line breaks between blocks are only the Markdown's layout: they go, and those in the words become <br> (ankiField)
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT), texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const n of texts) {
    const up = n.parentElement, beside = (x) => ANKI_BLOCK.test(x?.nodeName || "");
    // between blocks, or in a list or a table where words never stand loose: not a break in the words
    if (!up.closest("pre") && /^\s*\n\s*$/.test(n.nodeValue) && (n.parentNode === box || ANKI_LAYOUT.test(up.nodeName) || beside(n.previousSibling) || beside(n.nextSibling))) { n.remove(); continue; }
    n.nodeValue = n.nodeValue.replace(/\r/g, "").replace(/"/g, ANKI_QUOTE);
  }
  return ankiField(box.innerHTML.replaceAll(ANKI_QUOTE, "&quot;"));
}
const ANKI_LAYOUT = /^(OL|UL|TABLE|THEAD|TBODY|TFOOT|TR|BLOCKQUOTE)$/;              // what holds blocks only
const ANKI_BLOCK = /^(P|DIV|OL|UL|LI|TABLE|BLOCKQUOTE|PRE|H[1-6]|HR|SECTION)$/;   // what stands as a block of its own
// Words as they are, made safe for a field
const ankiText = (s) => ankiField(escapeHtml(String(s || "")));
// One field of a line: a tab or a line break never ends it, and it does not open as a comment or a quoted field
const ankiField = (html) => html.trim().replace(/\t/g, "&#9;").replace(/\r\n?|\n/g, "<br>").replace(/^#/, "&#35;").replace(/^"/, "&quot;");
// The front: the question as the panel shows it, what was heard for a spoken one, the problem written out, or else its kind and time
// (never empty: Anki leaves out a note whose first field is)
function ankiFront(it) {
  return (it.head.asked && ankiHtml(it.head.asked, true))
    || (it.trigger === "voice" && it.transcript && ankiText(it.transcript))
    || (it.ptext?.text && ankiText(it.ptext.text))
    || ankiText(`${TYPE_NAME[it.head.type] || it.head.type || t("Result")} · ${fmtWhen(it.ts)}`);
}
// The back: the answer line, bold as on the page, then the solution's first part; nothing when the answer wrote neither
function ankiBack(it) {
  const parts = [];
  if (it.head.answer) parts.push(`<b>${ankiHtml(it.head.answer, true)}</b>`);
  const body = it.head.body || "", key = body.slice(0, answerCuts(body)[0] || 0);
  if (key.trim()) parts.push(ankiHtml(key));
  return parts.join("<br><br>");
}
// Its type and its day, as Anki's tags: words with no spaces in them
const ankiTags = (it) => [TYPE_LABEL[it.head.type] || it.head.type || t("Result"), dayOf(it.ts)].map((x) => String(x).trim().replace(/\s+/g, "_")).join(" ");
function exportAnki() {
  // Anki's headers: how the file is cut, that its fields are HTML, the note type, the columns' names and which of them holds the tags
  const lines = ["#separator:tab", "#html:true", "#notetype:Basic", "#columns:Front\tBack\tTags", "#tags column:3"];
  let written = 0;
  for (const it of exportItems()) {
    const back = ankiBack(it);
    if (!back) continue;          // a failure that wrote nothing: nothing to learn from it
    lines.push([ankiFront(it), back, ankiTags(it)].join("\t"));
    written++;
  }
  if (!written) { toast(t("No answers to export"), null, "warn"); return; }
  saveFile(lines.join("\n") + "\n", "text/plain;charset=utf-8", `sidenote-anki-${fileStamp()}.txt`);
  toast(written === 1 ? t("Exported {n} answer (Anki)", { n: written }) : t("Exported {n} answers (Anki)", { n: written }), null, "done");
}
// Export offers its two files in a menu of the panel's own under its key, held to the window as the dropdowns are (comboPlace): the
// contents' card would cut it off at its edge, and its glass would hold a fixed menu inside itself
let exportAt = "";   // where the key stood when the menu opened: the menu goes when the key moves
const exportWhere = () => { const b = $("hist-export").getBoundingClientRect(); return `${Math.round(b.top)}:${Math.round(b.left)}`; };
function exportMenu(open, back = false) {
  const m = $("export-menu"), key = $("hist-export");
  if (!open) {
    if (m.hidden) return;
    m.hidden = true;
    key.setAttribute("aria-expanded", "false");
    if (back) key.focus({ preventScroll: true });          // Escape, or a choice: the keyboard goes back to the key
    return;
  }
  toggleMenu(false); comboClose(false);                    // one menu open at a time
  key.scrollIntoView({ block: "nearest", behavior: "instant" });   // the key in the window, for the menu to hang from
  m.hidden = false;
  key.setAttribute("aria-expanded", "true");
  // Under the key, its right edge on the key's, inside the window; over it when there is no room under it
  m.style.left = "8px"; m.style.top = "8px";               // measured first where nothing squeezes it
  const b = key.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  const up = b.bottom + 6 + h > innerHeight - 8 && b.top - 6 - h >= 8;
  m.classList.toggle("up", up);
  m.style.top = `${Math.round(up ? b.top - 6 - h : b.bottom + 6)}px`;
  m.style.left = `${Math.round(Math.min(Math.max(8, b.right - w), innerWidth - 8 - w))}px`;
  exportAt = exportWhere();
  m.querySelector(".item")?.focus({ preventScroll: true });   // the first choice, for the arrows and Enter
}
$("hist-export").addEventListener("click", () => {
  if (!$("export-menu").hidden) { exportMenu(false); return; }   // a second press closes it
  // Nothing in view: said at once, with no choice of file to make first
  if (!exportItems().length) { toast(t("No answers to export"), null, "warn"); return; }
  exportMenu(true);
});
$("export-menu").addEventListener("click", (e) => {
  const pick = e.target.closest("[data-export]");
  if (!pick) return;
  exportMenu(false, true);
  if (pick.dataset.export === "anki") exportAnki(); else exportMarkdown();
});
// The keys of a menu: the arrows, Home and End go along it, Tab leaves it from the key it hangs from (Escape: the page's own, below)
$("export-menu").addEventListener("keydown", (e) => {
  const opts = [...$("export-menu").querySelectorAll(".item")], at = opts.indexOf(document.activeElement);
  const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: opts.length - 1 }[e.key];
  if (to != null) { e.preventDefault(); e.stopPropagation(); opts[(to + opts.length) % opts.length].focus(); return; }
  if (e.key === "Tab") exportMenu(false, true);             // the Tab goes on from the key
});
// A press outside it, the window resized, or the key moved by a scroll: the menu would hang where nothing is
addEventListener("pointerdown", (e) => { if (!$("export-menu").hidden && !e.target.closest("#export-menu, #hist-export")) exportMenu(false); }, true);
addEventListener("resize", () => exportMenu(false));
addEventListener("scroll", () => { if (!$("export-menu").hidden && exportWhere() !== exportAt) exportMenu(false); }, true);
// A search looks through everything kept, not only what is on the page
let searchWait = 0;
$("hist-q").addEventListener("input", (e) => {
  histQuery = e.target.value.toLowerCase(); renderIndex();
  clearTimeout(searchWait);
  if (histQuery.trim()) searchWait = setTimeout(() => loadHistory({ q: histQuery, day: histDay, kind: histKind, ...starParam(), limit: 60 }), 300);
});
$("hist-day").addEventListener("change", (e) => {
  // Starred is one of the day list's choices: the starred answers of every day
  choiceChange(() => { histStar = e.target.value === STARRED; histDay = histStar ? "" : e.target.value; });
  reviewStarred();   // with Practice on, the starred answers already here are kept back for a review
  if (histDay || histStar) loadHistory(histStar ? { starred: 1, limit: 200 } : { day: histDay, limit: 200 }).then(() => {
    // Still in that day, the view stays. Otherwise today and Starred open on their newest answer and an earlier day on its first
    const now = items.get(viewId);
    if (now && inChoice(now)) return;
    const inDay = thread.filter((id) => inChoice(items.get(id)));
    const to = histStar || histDay === dayOf(Date.now()) ? inDay[inDay.length - 1] : inDay[0];
    if (to != null) goTo(to);
  });
});
$("hist-kind").addEventListener("change", (e) => {
  choiceChange(() => { histKind = e.target.value; });
  if (histKind) loadHistory({ kind: histKind, day: histDay, ...starParam(), limit: 60 });
});
$("choice-reset").addEventListener("click", clearChoice);
let ribbonAt;   // the answer the ribbon last fell on: undefined until the page has first been drawn, when nothing falls
function markIndex() {
  const rows = [...document.querySelectorAll("#history .h")];
  // One stop on the Tab order, the current row; the arrows go down the list from there (below)
  const stop = rows.find((b) => idOf(b.dataset.id) === viewId) || rows[0];
  rows.forEach((b) => {
    const now = String(idOf(b.dataset.id) === viewId);
    if (b.getAttribute("aria-current") !== now) b.setAttribute("aria-current", now);
    b.tabIndex = b === stop || b === document.activeElement ? 0 : -1;
  });
  // The ribbon in the page goes on the answer the column is showing (index.html, .entry[data-here])
  document.querySelectorAll("#thread .entry[data-here]").forEach((e) => { if (idOf(e.dataset.id) !== viewId) delete e.dataset.here; });
  const here = viewId != null ? entryEl(viewId) : null;
  if (here) here.dataset.here = "1";
  if (viewId !== ribbonAt) {
    if (ribbonAt != null && viewId != null) { replay(stop, "drop"); replay(here, "drop"); setTimeout(() => { stop?.classList.remove("drop"); here?.classList.remove("drop"); }, 500); }
    ribbonAt = viewId;
  }
  keepRowInView();
}
// Reading on down the thread must not leave the ribbon scrolled out of the contents' own list. Not while that list is in use: it would pull the row from under the pointer
$("history").addEventListener("keydown", (e) => {
  const rows = [...$("history").querySelectorAll(".h")], at = rows.indexOf(document.activeElement);
  if (at < 0) return;
  const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: rows.length - 1 }[e.key];
  if (to == null || !rows[to]) return;
  e.preventDefault();                 // the arrows moved the page before, with the focus left where it was
  rows[at].tabIndex = -1; rows[to].tabIndex = 0;
  rows[to].focus({ preventScroll: true });
  rows[to].scrollIntoView({ block: "nearest" });
});
$("history").addEventListener("scroll", () => $("history").classList.toggle("scrolled", $("history").scrollTop > 0), { passive: true });
function keepRowInView() {
  const list = $("history"), row = list.querySelector('.h[aria-current="true"]');
  if (!row || list.scrollHeight <= list.clientHeight || list.matches(":hover") || list.contains(document.activeElement)) return;
  const box = list.getBoundingClientRect(), at = row.getBoundingClientRect();
  const tab = list.querySelector(".h-day")?.getBoundingClientRect().height || 0;   // the day's tab stands over the top of the list
  if (at.top < box.top + tab) list.scrollTop -= box.top + tab - at.top;
  else if (at.bottom > box.bottom) list.scrollTop += at.bottom - box.bottom;
}
const LANG_NAME = { ko: t("Korean"), en: t("English") };
let heard = { text: "", lang: "", waiting: false, pending: false };
let heardAt = 0;   // when words last came: the card's marks move while they do
let refitRail = () => {};   // the column's fit, from where it is set up
// A sentence that has ended has been heard for good; the one still going is what the microphone is
// on now. Whisper punctuates both languages, so the split is the same for either.
const SENTENCE_END = /(?<=[.!?…。？！])\s+/;
function hearState() {
  if (paused && status.voice) return `<b>${t("Paused")}</b> ${t("Not solving what is heard")}`;
  if (paused) return `<b>${t("Paused")}</b>`;
  // Paused with voice solving off: Continue would not make it solve anything, so it is not offered.
  // The section is named as the settings sheet names it (the server's words), the panel's own word until they come.
  const speech = settingsMeta?.sections?.find(([sec]) => sec === "speech")?.[1] || t("Speech");
  if (!status.voice) return t("Writing it down only · to solve spoken problems: {where}", { where: `<b>${t("Solver settings")} &gt; ${escapeHtml(speech)}</b>` });
  if (!eng()?.ready) return t("No engine to solve, so writing it down only");
  if (heard.pending) return t("<b>Solving</b> what was heard as a problem");
  if (heard.waiting) return t("Solves it as a problem <b>once the speech ends</b>");
  return t("Read a problem aloud and it is solved");
}
const HEAR_FRESH = 8;   // longer than the 5 s between the server's capture messages, so the bars
//                         do not blink off and on between two of them
// Sentences that ended and were not taken, and why (the server's `utterance` messages with a `why`). The card writes down the last
// seconds of sound, so a sentence the user can see and nothing came of would look ignored: each is said under its sentence.
const HEARD_WHY = { get short() { return t("Too short · not solved"); }, get told() { return t("Part of a story · not solved"); }, get none() { return t("No question · not solved"); } };
const HEARD_NOTE_MS = 25000;   // a little longer than the card's words stay
let heardNotes = [];
const wordsIn = (s) => String(s).toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
function noteHeard(text, why) {
  if (!text || !HEARD_WHY[why]) return;
  // Its last sentence is the one to go under: a run of speech can be two minutes of it, and a sentence said after shares its words
  const last = text.trim().split(SENTENCE_END).pop();
  heardNotes = [...heardNotes.slice(-7), { text: last, why, words: new Set(wordsIn(last)), at: Date.now() }];
  renderHear();
  $("hear-text").scrollTop = $("hear-text").scrollHeight;
}
// The sentence on the card a note belongs to: the last one whose words are mostly the note's. The card and the note wrote the same
// sound down apart, and they can differ by a word or two. -1 when none is: the note then brings its sentence along.
function noteAt(note, lines) {
  for (let i = lines.length - 1; i >= 0; i--) {
    const w = wordsIn(lines[i]);
    if (w.length && w.filter((x) => note.words.has(x)).length / w.length >= 0.6) return i;
  }
  return -1;
}
function renderHear(text, lang, flags) {
  // Called two ways: with new words from the server, and once a second with nothing, to keep the
  // listening bars and the "last heard" wording current. Only the first kind replaces the state.
  if (text !== undefined) heard = { text: text || "", lang: lang || heard.lang, ...(flags || {}) };
  // The card is about sound that is actually arriving: the server's own transcription is on, the
  // panel's switch is on, a capture program is connected, and it was not started with --no-audio.
  // Also hidden when the capture program could not open a sound device at all: the card would
  // otherwise say it is listening to something that never arrives.
  const on = !!(status.audio && capture.audio_on && capture.clients > 0
    && !capture.caps?.no_audio && capture.caps?.audio !== false);
  $("hear").hidden = !on;
  if (!on) return;   // nothing below would be true, and the card is hidden anyway
  const fresh = !!(capture.last_audio && serverNow() - capture.last_audio < HEAR_FRESH);
  if (text !== undefined) heardAt = Date.now();
  $("hear").classList.toggle("live", fresh && !paused && Date.now() - heardAt < 3000);
  // Sentences that have ended are settled; the last chunk is what is being said right now.
  const said = heard.text.trim() ? heard.text.trim().split(SENTENCE_END) : [];
  const now = said.pop() || "";   // pop: `said` keeps only the finished ones
  // Why each sentence that was not taken was not, under it; one no longer on the card goes when its time is up
  heardNotes = heardNotes.filter((n) => Date.now() - n.at < HEARD_NOTE_MS);
  const lines = now ? [...said, now] : said, under = new Map(), loose = [];
  for (const n of heardNotes) { const i = noteAt(n, lines); if (i >= 0) under.set(i, n); else loose.push(n); }
  const why = (n) => (n ? `<span class="why">${escapeHtml(HEARD_WHY[n.why])}</span>` : "");
  // setHtml, not innerHTML: this runs once a second, and replacing the text while it was being read
  // threw away where it had been scrolled to and anything selected in it to copy.
  setHtml("hear-text", said.map((t, i) => `<span class="said">${escapeHtml(t)}</span>${why(under.get(i))}`).join("")
    + loose.map((n) => `<span class="said">${escapeHtml(n.text)}</span>${why(n)}`).join("")
    + (now ? `<span class="now">${escapeHtml(now)}</span>${why(under.get(said.length))}`
           : loose.length ? ""
           : `<span class="quiet">${paused ? t("Not written down while paused")
              : fresh ? t("No speech") : t("Nothing heard")}</span>`));
  if (text !== undefined) $("hear-text").scrollTop = $("hear-text").scrollHeight;   // only on new words
  setHtml("hear-lang", heard.text.trim() ? escapeHtml(LANG_NAME[heard.lang] || (heard.lang || "").toUpperCase()) : "");
  setHtml("hear-state", hearState());
}
// The follow-up buttons under the newest answer depend on two things that change while that entry is not
// drawn again: whether the server can answer a follow-up at all (a restarted one has nothing to answer it
// against, and says can_ask false) and whether the socket is up. They used to stay live through a dropped
// connection and after reconnecting to a restarted server, while the question box under them said that
// neither would work, and a press asked a server that could only say so. The row comes and goes with
// what the server can answer, and its buttons can be pressed while the socket is up.
function syncNextAsks() {
  const id = lastAnsweredId();                         // the only entry that carries them (nextAsks)
  const it = id != null ? items.get(id) : null, el = id != null ? entryEl(id) : null;
  if (!it || !el) return;
  const row = el.querySelector(":scope > .row.asks:not(.practice)");      // not Practice's keys, which wear its look
  // The row comes or goes, and the end with it: followed, as an entry that grows is. On opening, the answers came before the
  // server's word that questions can be asked, and the keys that came then stood half under the question box
  if (!!row !== (nextAsks(it).length > 0)) { renderEntry(it); followEnd(); return; }
  // a button just pressed keeps its own two seconds (the click handler's busy time) either way
  if (row) row.querySelectorAll("[data-ask]").forEach((b) => { b.disabled = wsState !== "up" || Date.now() < (b._busyUntil || 0); });
}
function renderAll() {
  renderSignals(); renderAlerts(); renderShot(); renderIndex(); syncAsk(); syncNextAsks(); renderSettings();
  if (!thread.length) syncEmpty();
  noteChange();
}
// Trouble that starts while the page is read: the server's connection and the capture program, as they were at the last look
let prevState = { up: false, clients: null };
// The bands stay in view at any scroll now (in the bar at the top, floating under it further down), so a toast is said only where no
// band says the same: one over the other said it twice.
function noteChange() {
  const up = wsState === "up";
  // The server gone always raises its band (renderAlerts), and the capture program gone raises one while a capture switch is on:
  // with both switches off, only this toast tells it
  if (up && prevState.clients > 0 && capture.clients === 0 && !(capture.screen_on || capture.audio_on)) toast(status.desktop ? t("The capture program stopped")
    : t("Capture program off: run ./sidenote capture on the capture PC"), null, "warn");
  prevState = { up, clients: capture.clients };
}

// ---------- thread bookkeeping ----------
function addToThread(it) {
  if (it.shown) return false;
  it.shown = true;
  thread.push(it.id);
  while (thread.length > MAX_ITEMS) {
    const old = thread.shift(), o = items.get(old);
    if (o) o.turns.forEach((t) => turns.delete(t));
    items.delete(old); unfolded.delete(old); entryEl(old)?.remove();
    pruneRuns();
  }
  return true;
}
// Run boxes' state goes with the answers it belongs to
function pruneRuns() {
  for (const k of [...runState.keys()]) { const o = k.split(":")[0], id = idOf(o.slice(1)); if (o[0] === "e" ? !items.has(id) : !turns.has(id)) runState.delete(k); }
}
function dropItem(it) {   // cancelled, or nothing to solve: leave no trace
  items.delete(it.id);
  clearTimeout(it.revealTimer);
  if (practiceCards.delete(String(it.id))) keepCards();   // nor in what Practice keeps
  const i = thread.indexOf(it.id);
  // The index and the folds change only when the entry was in the thread: rebuilt for every analysis that never got
  // there, the index dropped the keyboard focus on one of its rows every few seconds.
  if (i >= 0) { thread.splice(i, 1); entryEl(it.id)?.remove(); if (jumpFor === it.id) { jumpFor = null; $("jump").hidden = true; } refold(); renderIndex(); updateView(); }
  if (i >= 0 || !it.quiet || lastNone?.dropped === it.id) {
    renderTail(); syncEmpty();
    renderShot();   // the screen it was looking at goes from the rail too (updateView redraws only on a move)
  }
}

// ---------- messages ----------
const REVEAL_MS = 2000;   // how long an automatic analysis runs before the page says it is looking (onStart)
let manualUntil = 0;      // Reanalyze was pressed: the analysis it starts is said at once (reanalyze)
function onStart(m) {
  // retry: the automatic one after a failed example; continue: the answer filled out from a problem scrolled together
  if (m.trigger === "ask" || m.trigger === "retry" || m.trigger === "continue") {
    // `about` is the analysis the server answers it against (not whatever is newest: an error, or
    // the next problem still streaming); an older server does not say, then the newest entry.
    let parent = m.about != null ? items.get(m.about) : items.get(latestId());
    if (!parent) {   // panel reloaded or cleared: the server still remembers the problem
      parent = newItem({ id: `p${m.id}`, trigger: "screen" });
      Object.assign(parent, { live: false, head: { type: "other", answer: t("An earlier problem"), body: "" } });
      items.set(parent.id, parent); addToThread(parent); syncEmpty();
    }
    // `retry` marks a turn the watching started by itself (a retry or a continuation): it does not take the view
    const turn = { id: m.id, parent: parent.id, q: m.transcript || "", raw: "", live: true, error: null, hint: "", meta: null,
      retry: m.trigger !== "ask", kind: m.trigger };
    turns.set(turn.id, turn); parent.turns.push(turn.id);
    renderEntry(parent); renderIndex();   // a folded entry opens while its follow-up is written (folded())
    // A question the user asked stays in view while it is answered; the automatic retry does not pull
    // the view back to an older answer.
    if (!turn.retry) { stick = false; followTurn = turn.id; readerMoved(); showTurn(turn); }
    return;
  }
  if (items.get(m.id)?.shown) return;   // a start heard twice is one answer: it counted twice in the contents
  const it = newItem(m);
  items.set(it.id, it);
  // A look the watching started by itself is said only once it has run REVEAL_MS: most find nothing within a second or
  // two, or are stopped by the next change of the screen, and drawing each of them moved the thread 15 px and flipped
  // the rail's screen card every few seconds while the person at the PC worked. A spoken problem and
  // Reanalyze are said at once: they are being waited for.
  const manual = Date.now() < manualUntil;
  if (m.trigger === "screen" && !manual) {
    it.quiet = true;
    it.revealTimer = setTimeout(() => {
      if (items.get(it.id) !== it || !it.live || it.shown) return;
      it.quiet = false;
      renderTail(); renderShot(); followEnd();
    }, REVEAL_MS);
    return;
  }
  manualUntil = 0;
  renderTail();
  renderShot();   // on an empty page the rail shows the screen this analysis is looking at
  followEnd();
}
function onDelta(m) {
  const t = turns.get(m.id);
  if (t) {
    if (t.live) { t.raw += m.text; schedule(`t${t.id}`, () => { if (t.live) { paintTurn(t, false); if (followTurn === t.id) showTurn(t); else followEnd(); } }); }
    return;
  }
  const it = items.get(m.id);
  if (!it || !it.live) return;
  it.raw += m.text;
  it.head = splitHead(it.raw);
  if (it.head.type && it.head.type !== "none" && !it.shown) {   // a real problem: it joins the thread
    practiceArrived(it);   // with Practice on, kept back from the first word
    addToThread(it); syncEmpty();
    it.fresh = true;   // its answer line rises in once, when it first appears (not again when it finishes)
    renderEntry(it); refold(); renderTail(); renderIndex(); afterGrow();
    return;
  }
  if (it.shown) schedule(`i${it.id}`, () => {
    // finalized meanwhile: its full render (math, code, copy buttons) must not be overwritten
    if (!it.live || !entryEl(it.id)) return;
    const k = entryEl(it.id).querySelector(".kind");
    if (k && it.head.type) k.textContent = TYPE_LABEL[it.head.type] || it.head.type;
    if (it.head.type) entryEl(it.id).dataset.kind = it.head.type;
    if (it.head.type !== it.rowType || it.head.asked !== it.rowAsked) { it.rowType = it.head.type; it.rowAsked = it.head.asked; renderIndex(); }
    paintItem(it, false);
    followEnd();
  });
}
function clearVoiceState() {
  // The server says "waiting" and "pending" with the transcript; nothing says when it is over.
  if (heard.pending || heard.waiting) { heard.pending = heard.waiting = false; renderHear(); }
}
function onDone(m) {
  if (endsVoice(m.id)) clearVoiceState();
  const turn = turns.get(m.id);
  if (turn) {
    turn.raw = m.text || turn.raw; turn.live = false; turn.meta = m;
    // Marked as cut off when the socket dropped, and then the same server went on and finished it: the
    // answer is whole, so the mark goes. (A restarted server never sends this; its analysis died with it.)
    if (turn.hint === "interrupted") { turn.error = null; turn.hint = ""; }
    const p = items.get(turn.parent);
    // Open while it was written (folded() keeps an entry with a live turn open), it folded the moment the answer was
    // whole when three newer answers had come meanwhile, and the view was sent to a hidden turn. One followed
    // or in view stays open, as an entry opened by hand does.
    const tEl = document.querySelector(`[data-turn="${turn.id}"]`);
    if (p && (followTurn === turn.id || (tEl && inView(tEl)))) unfolded.add(p.id);
    if (p) renderEntry(p);
    if (followTurn === turn.id) { showTurn(turn); followTurn = null; readerMoved(); if (nearBottom()) stick = true; }
    else followEnd();
    // Not one the watching wrote under an answer Practice keeps back: it waits with that answer, and so do its words
    if (!(p && held(p) && turn.retry)) announce(t("Follow-up answer: {text}", { text: plainAnswer(splitHead(turn.raw, true).answer) || t("Answer done") }));
    return;
  }
  const before = lastAnsweredId();   // the Problem text button moves from that answer to this one (taken while this one is live)
  repeatOf = null;                   // a new answer is what follow-ups are about now
  const it = items.get(m.id) || newItem(m);
  items.set(it.id, it);
  it.raw = m.text || it.raw; it.live = false; it.meta = m; it.region = (m.region_shown !== false && m.region) || null;
  // As for a follow-up above: cut off by a dropped socket, but finished by the server all the same.
  // It used to stay "Error" with its whole answer labelled Unfinished answer / Unfinished solution.
  if (it.hint === "interrupted") { it.error = null; it.hint = ""; }
  it.head = splitHead(it.raw, true);
  if (it.head.type === "none" || (!it.head.body.trim() && !it.head.answer)) {
    // The answer is dropped, but the screen it was about is kept: the card beside it used to say
    // "No screen received yet" while the page said this screen had nothing to solve.
    // `dropped`: which analysis it was, so dropItem redraws the foot and the rail for it even when it was never said
    lastNone = { ts: Date.now(), voice: it.trigger === "voice", thumb: it.thumb || null, dropped: it.id };
    dropItem(it);
    return;
  }
  const wasShown = it.shown;   // on the page already while it was being written
  if (!wasShown) practiceArrived(it);   // all of it in one message: with Practice on, kept back as it comes
  addToThread(it); syncEmpty();
  if (before != null && before !== it.id && items.get(before) && entryEl(before)) renderEntry(items.get(before));
  status.canAsk = true; syncAsk();
  it.fresh = !wasShown;
  renderEntry(it); refold(); renderTail(); renderIndex();
  if (wasShown) { followEnd(); updateView(); } else afterGrow();   // finishing is not a new answer: no pull
  // Its kind for a screen reader, and its answer line unless Practice keeps it back
  announce(`${TYPE_LABEL[it.head.type] || t("Solution")}: ${(!held(it) && plainAnswer(it.head.answer)) || t("Solution done")}`);
  if (viewId === it.id) renderShot();   // its problem region arrives only now
}
// Stopped on purpose (pause, a switch turned off): a half-written answer stays, with a note. Any
// other cancel means a newer analysis replaces it (a new screen, a new spoken problem, Reanalyze).
const STOP_NOTE = { pause: t("Stopped: paused"), screen_off: t("Stopped: screen capture was turned off"),
  sound_off: t("Stopped: sound capture was turned off"), get not_sent() { return t("Not solved: not sent to the agent", { agent: AG() }); },
  local_off: t("Stopped: the local model was turned off") };
// Whether a message ends the spoken problem's own run: the status "solving … what was heard" went whenever any analysis was
// stopped, a screen's superseded one included. An id the panel does not know (reloaded)
// is taken to be it, as before.
const endsVoice = (id) => { const it = items.get(id); return !it || it.trigger === "voice"; };
function onCancelled(m) {
  if (endsVoice(m.id)) clearVoiceState();   // the spoken problem is no longer being solved
  if (m.reason === "repeat" && m.of != null && items.has(m.of) && lastAnsweredId() !== m.of) {
    const was = lastAnsweredId();
    repeatOf = m.of;
    for (const id of [was, m.of]) if (id != null && items.has(id) && entryEl(id)) renderEntry(items.get(id));
  }
  const turn = turns.get(m.id);
  if (turn) {
    const p = items.get(turn.parent);
    // One the watching started and that wrote nothing goes without a trace: each stopped continuation left a
    // "Stopped: this answer was stopped" stub of 140 px under the answer.
    if (turn.retry && !turn.raw.trim() && !STOP_NOTE[m.reason]) {
      turns.delete(turn.id);
      if (p) { p.turns = p.turns.filter((x) => x !== turn.id); renderEntry(p); }
      return;
    }
    const followed = followTurn === turn.id;
    if (followed) followTurn = null;
    Object.assign(turn, { live: false, stopped: (STOP_NOTE[m.reason] || t("Stopped")) });
    if (p) renderEntry(p);
    if (followed) { readerMoved(); if (nearBottom()) stick = true; }
    return;
  }
  const it = items.get(m.id);
  if (!it) return;
  if ((it.shown || m.reason === "not_sent") && STOP_NOTE[m.reason]) {   // not sent: said even before any answer line
    Object.assign(it, { live: false, stopped: STOP_NOTE[m.reason] });
    addToThread(it); syncEmpty();
    renderEntry(it);
    // the answer before it is still the last one answered: drawn again, with its asks and Problem text
    const last = lastAnsweredId();
    if (last != null && last !== it.id && entryEl(last)) renderEntry(items.get(last));
    refold(); renderTail(); renderIndex();
    return;
  }
  dropItem(it);
}
function onError(m) {
  clearVoiceState();   // it failed, so the card must stop saying it is being solved
  const h = HINT[m.hint] || HINT[""];
  const turn = turns.get(m.id);
  if (turn) {
    toast(h.title + (h.cmd ? `: ${h.cmd}` : ""), null, "bad", h.cmd);
    turn.live = false; turn.error = m.text || t("Error"); turn.hint = m.hint || "";
    const p = items.get(turn.parent); if (p) renderEntry(p);
    if (followTurn === turn.id) { showTurn(turn); followTurn = null; readerMoved(); if (nearBottom()) stick = true; }
    return;
  }
  const it = items.get(m.id) || newItem(m);
  if (it.meta && !it.live && !it.error) return;   // a whole answer is not turned into an error by a late message, nor told as one
  toast(h.title + (h.cmd ? `: ${h.cmd}` : ""), null, "bad", h.cmd);
  items.set(it.id, it);
  it.live = false; it.error = m.text || t("Error"); it.hint = m.hint || "";
  addToThread(it); syncEmpty();
  renderEntry(it); refold(); renderTail(); renderIndex(); afterGrow();
}

function handle(m) {
  if (!bootEnded && /^(analysis_|delta|thumb)/.test(m.type || "")) endBoot();   // an answer is arriving: nothing is left to wait for
  switch (m.type) {
    case "status":
      if (m.build) { status.build = m.build; if (buildAtLoad === null) buildAtLoad = m.build; }
      if (m.paused !== undefined) setPaused(m.paused);
      if (m.lang !== undefined) setLang(m.lang);
      if (m.audio !== undefined) status.audio = !!m.audio;
      if (m.voice !== undefined) status.voice = !!m.voice;   // Solve spoken problems automatically (the Heard speech card reads it)
      if (m.engines !== undefined) { status.engines = m.engines; gpuPending = false; clearTimeout(gpuPressed.timer); renderSettings(); }
      if (m.desktop !== undefined) status.desktop = !!m.desktop;   // the desktop app's server: no ./sidenote commands
      if (m.can_ask !== undefined) status.canAsk = !!m.can_ask;   // a restarted server has nothing to ask about
      if (m.run_enabled !== undefined) status.runEnabled = !!m.run_enabled;
      if (m.runner !== undefined) status.runner = !!m.runner;
      if (m.version !== undefined) { status.version = m.version; renderVersion(); }   // this server's release, in the gear menu
      if (m.update !== undefined) status.update = m.update;   // a newer release, or null: one line in the band (updateBand)
      if (m.update_check !== undefined) status.updateCheck = m.update_check !== false;   // false: the environment turned the check off
      renderAll();
      if (m.fresh) setupFirst();   // nothing answered yet on this server: the setup guide, once in this browser
      break;
    case "capture": {
      const wasOn = capture.screen_on;
      // The message carries the server's own clock, so the offset is known before anything is
      // measured against it.
      if (typeof m.now === "number") clockSkew = Date.now() / 1000 - m.now;
      capture = { clients: m.clients, last_frame: m.last_frame, last_audio: m.last_audio,
        screen_on: m.screen_on !== false, audio_on: m.audio_on !== false, caps: m.caps || {},
        // The run of answers that found nothing and how long a small change waits because of it:
        // the screen card says so while it holds.
        empty_run: m.empty_run || 0, quiet_sec: m.quiet_sec || 0 };
      if (wasOn && !capture.screen_on) { forgetScreens(); if (drawing) drawing = null; }   // a box drawn on a screen no longer kept: the key to end it was off with the capture
      renderSignals(); renderAlerts(); renderShot(); noteChange();
      renderHear(capture.audio_on ? undefined : "", "");
      if (!thread.length) syncEmpty();
      break;
    }
    case "usage": usage = m; renderUsage(); break;
    case "history_cleared": clearShown(); break;   // cleared from this panel or another one: what is shown goes too
    // a notice that points at an answer above (a problem seen again: m.of) takes the view there when pressed
    case "gpu": drawGpu(m); break;
    // the model download the local model's card started: its progress, then done or why it failed
    case "llm_pull":
      pullNow = m.status === "done" || m.status === "failed" ? null : m;
      if (m.status === "failed") toast(t("The download of {model} failed: {error}", { model: m.model || "", error: m.error || "" }), null, "bad");
      if (m.status === "done") toast(t("{model} is ready", { model: m.model || "" }), null, "done");
      renderAll();
      break;
    // The server words what it could not do this way; said once here rather than at each of its notices
    // The server says what kind of notice it is (level: info, done, warn or bad, the bands' kinds); an older one does not,
    // and its Korean words tell it instead
    case "notice": toast(m.text || "", m.of != null && items.has(m.of) ? () => goTo(m.of) : null,
      m.level || (/못했|못합니다|실패|수 없습니다|못 |안 보냄|없음|불가/.test(m.text || "") ? "warn" : "info")); break;
    case "transcript": renderHear(m.text, m.lang, { waiting: !!m.waiting, pending: !!m.pending }); setupHeardNow(m.text); break;
    case "utterance": noteHeard(m.text, m.why); break;   // a sentence that ended: with a `why` when it was not taken
    // An answer being written when this page opened comes with its words so far (the server's LIVE)
    case "analysis_start": onStart(m); if (m.text) onDelta({ type: "delta", id: m.id, text: m.text }); setupSaw(m, false); break;
    case "delta": onDelta(m); break;
    case "analysis_done": liveDone.add(idOf(m.id)); onDone(m); sweepKey(entryEl(m.id)); setupSaw(m, true); break;
    case "analysis_cancelled": onCancelled(m); setupLost(m); break;
    case "error": onError(m); setupLost(m); break;
    case "run_started": onRunStarted(m); break;
    case "run_result": onRunResult(m); break;
    case "stage": {
      const it = items.get(m.id);
      if (it && it.live) {
        it.stage = { stage: m.stage, detail: m.detail || "", thought: m.thought || "" };
        // Another engine is starting this answer over (the agent declined, or stopped partway): what it
        // wrote goes, or the new answer is written underneath it for as long as it takes to finish.
        if (m.restart && it.raw) {
          it.raw = ""; it.head = splitHead("");
          if (it.shown) { paintItem(it, false); followEnd(); } else renderTail();
        }
        if (it.shown) { const el = entryEl(it.id)?.querySelector("[data-elapsed]"); if (el) el.textContent = liveText(it); }
        else renderTail();
      }
      break;
    }
    case "check": {
      const it = items.get(m.id);
      if (it) {
        it.check = m;
        // Only its row: drawing the whole entry again parsed and highlighted the answer twice for each check (90 ms at 30,000 characters)
        const row = entryEl(it.id)?.querySelector(":scope > .row[data-checkrow] > .ct");
        if (row) { row.innerHTML = checkHtml(m); comeIn(row.closest(".entry")); followEnd(); }
        else if (entryEl(it.id)) { keepPlace(() => renderEntry(it)); followEnd(); }
      }
      const t = !it && turns.get(m.id), owner = t && items.get(t.parent);   // a retry's: the turn under its answer
      if (t) { t.check = m; if (owner && entryEl(owner.id)) { keepPlace(() => renderEntry(owner)); followEnd(); } }
      break;
    }
    case "problem_text": {   // Problem text, for this panel's request
      const it = items.get(m.id);
      if (it) { it.ptext = m.error ? { error: m.error } : { text: m.text || "" }; if (entryEl(it.id)) renderEntry(it); }
      break;
    }
    case "star": {   // an answer starred or unstarred, from this panel or another; with how many are starred now
      if (typeof m.n === "number") historyStarred = m.n;
      const it = items.get(idOf(m.id));
      if (it) {
        // Unstarred while Starred is chosen, it stays in view until the choice changes: it does not go from under the pointer that pressed it
        if (histStar && it.starred && !m.starred) shownAnyway.add(it.id);
        it.starred = !!m.starred;
        paintStar(it);
      } else if (m.starred && histStar) loadHistory({ starred: 1, limit: 200 });   // starred elsewhere, not on this page: Starred brings it in
      renderIndex();
      break;
    }
    case "verify": {   // the verify mode: the agent's check of this local answer; what it sent joins the card's list
      const it = items.get(m.id);
      if (it) {
        it.verify = m;
        if (m.sent?.length) it.meta = { ...(it.meta || {}), sent: [...(it.meta?.sent || []), ...m.sent] };
        if (entryEl(it.id)) { renderEntry(it); followEnd(); }
      }
      break;
    }
    case "settings":
      if (m.meta) settingsMeta = m.meta;
      if (m.values) Object.assign(settingsValues, m.values);
      if (m.options && settingsMeta) for (const [k, o] of Object.entries(m.options)) { const i = settingsMeta.items.find((x) => x.key === k); if (i) i.options = o; }
      // The controls show what the server sent (after turning a value down, it sends the one it kept),
      // and so do the places outside the sheet that read the same values: the 'part of the screen'
      // note (roi_box) and the screen card's monitor. Those two waited for the next capture or status
      // message, so a region cleared elsewhere stayed announced here for seconds.
      renderSettings(); renderShot(); renderAlerts(); renderSignals(); syncHeardKeys();
      break;
    case "agent_confirm":
      m.gotAt = Date.now() / 1000;   // this browser's own clock, not the server's (they can differ)
      confirms.set(m.cid, m); renderTail(); followEnd();
      toast(t("Choose whether to send it to the agent", { agent: AG() }));
      break;
    case "agent_confirm_done":
      if (confirms.delete(m.cid)) renderTail();
      break;
    case "thumb":
      if (setupShotAsked) { setupShotFrom(m); break; }
      if (m.url) {
        // ts stays in the server's seconds: renderShot reads its age against serverNow()
        drawing = { url: m.url, ts: typeof m.ts === "number" ? m.ts : serverNow(), live: m.live !== false, start: null, box: null };
        renderShot();
        $("shot").scrollIntoView({ block: "nearest" });
      }
      else toast(m.text || t("No screen received"), null, "warn");
      break;
  }
}

function onRunStarted() {}   // the box already says Running
function onRunResult(m) {
  const key = runOwners.get(m.id);
  if (!key) return;
  runOwners.delete(m.id);
  const st = runState.get(key);
  if (!st || st.pending !== m.id) return;
  st.pending = null;
  const CUT = t("\n…(output cut)");
  if (m.error) Object.assign(st, { cls: "err", out: m.error, stat: "" });
  else if (m.stage === "compile" && !m.ok) {   // nothing ran: the compiler's message, or that it took too long
    const msg = (m.stderr || "").trim() + (m.stderr_truncated ? CUT : "");
    Object.assign(st, m.timed_out
      ? { cls: "err", stat: t("Compile timed out"), out: t("Stopped: the compile timed out") + (msg ? "\n" + msg : "") }
      : { cls: "err", stat: t("Compile error"), out: msg || t("(no compiler message)") });
  } else {
    const bits = [];
    if (m.timed_out) bits.push(t("Timed out"));
    else if (m.output_limited) bits.push(t("Stopped: too much output"));
    else if (typeof m.exit === "number") bits.push(t("Exit code {n}", { n: m.exit }));
    if (typeof m.elapsed === "number") bits.push(t("{n} s", { n: m.elapsed.toFixed(2) }));
    let out = m.stdout || "";
    if (m.stdout_truncated) out += CUT;
    if ((m.stderr || "").trim()) out += (out ? "\n" : "") + "─ stderr ─\n" + m.stderr + (m.stderr_truncated ? CUT : "");
    if (m.timed_out) out += (out ? "\n" : "") + t("(stopped: timed out)");
    Object.assign(st, { cls: m.ok ? "" : "warn", stat: bits.join(", "), out: out || t("(no output)") });
    // It ran out of input. The traceback is kept underneath, but what it means comes first, and
    // the box to fix it is opened: a stack trace is not an answer to "what do I do now".
    if (!m.ok && ATE_EOF.test(m.stderr || "")) {
      Object.assign(st, { stdinOpen: true, cls: "warn", stat: NEED_STDIN,
                          out: t("It ended before it read all its input: there was none to read\nPut an example input in the box below and run it again\n\n─ original message ─\n") + out });
    }
  }
  const box = runBox(key);
  if (box) paintRun(box, st);
}

// ---------- the settings sheet ----------
// Drawn from the server's list (server/settings.py): a switch, a row of choices, a list, ticks or the
// drawn box. A setting whose prerequisite is off is dimmed and says which one to turn on.
// What this server was started without cannot be switched on here (its environment decides).
const noSearch = () => !eng()?.search?.present && t("No search server (SIDENOTE_SEARCH_URL)");
const noAgent = () => !eng()?.agent?.present && t("The server was started without the agent (SIDENOTE_AGENT)", { agent: AG() });
const noRunner = () => !status.runner && t("No code runner (SIDENOTE_RUNNER_URL)");
const noAudio = () => !status.audio && t("Speech recognition off (SIDENOTE_AUDIO)");
const UNAVAILABLE = {
  local_llm: () => !eng()?.local?.present && t("The server was started without the local model (SIDENOTE_ANALYZER)"),
  web_search: noSearch, web_fetch: noSearch, agent_mode: noAgent, agent_payload: noAgent, agent_hard_types: noAgent,
  agent_confirm: noAgent, run_button: noRunner, autocheck: noRunner, voice_auto: noAudio, whisper_hint: noAudio,
  update_check: () => status.updateCheck === false && t("Version check off (SIDENOTE_UPDATE_CHECK)"),
};
const ACTIVE_WHEN = {   // prerequisites that are not plain switches
  agent_payload: (v) => v.agent_mode !== "off", agent_confirm: (v) => v.agent_mode !== "off",
  agent_hard_types: (v) => v.agent_mode === "hard",
};
function outboundNote() {
  const C = eng()?.agent, S = eng()?.search;
  // Web search also leaves this PC, with words taken from the screen: saying "nothing leaves" while
  // it is on would be a promise the tool does not keep.
  const web = S && S.present && S.on ? t("Web search is on: search words go to the search engine") : "";
  if (!C || !C.present) return web;
  if (C.mode === "off") return (web ? t("Nothing goes to the agent. ", { agent: AG() }) + web
                                    : t("<b>Nothing</b> leaves this PC"));
  if (!C.ok) return t("The agent is not signed in, so nothing goes out", { agent: AG() }) + (web ? ". " + web : "");
  const ask = settingsValues.agent_confirm ? t(" · asks before sending") : "";
  const pay = payloadNow(C);
  const forced = pay === "screen" && (C.payload || "crop") !== "screen";
  // What goes and which problems take it, under the agent card's own two names (Sends, Takes), one line of facts set apart by
  // "·" as the card's are: written as two sentences of their own words ("Going out now: ... Problems it solves: ...") they read
  // as fragments, and named what goes a third way
  const mode = MODE_TEXT[C.effective] ? ` · ${t("Takes")}: ${MODE_TEXT[C.effective]}` : "";
  return `${t("Sends")}: <b>${escapeHtml(payloadName(pay))}</b>${mode}${ask}`
    + `${forced ? t(" · the local model is off, so the problem area cannot be cut out") : ""}${web ? ` · ${web}` : ""}`;
}
function settingItem(key) { return settingsMeta?.items.find((i) => i.key === key); }
function settingBlocker(item) {
  const gone = UNAVAILABLE[item.key]?.();
  if (gone) return gone;
  for (const n of item.needs || []) {
    if (!settingsValues[n]) {
      const label = settingItem(n)?.label || n;
      return t("Needs {setting} on", { setting: `'${label}'` });
    }
  }
  const f = ACTIVE_WHEN[item.key];
  if (f && !f(settingsValues)) {
    if (item.key !== "agent_hard_types") return t("Needs the agent on", { agent: AG() });
    // the setting's own label and option as the server words them, so the warning and the setting read the same
    const mode = settingItem("agent_mode");
    const hard = (mode?.options || []).find((o) => o[0] === "hard")?.[1] || t("Hard problems");
    return t("Used when {setting} is {value}", { setting: `'${mode?.label || t("Problems the agent solves", { agent: AG() })}'`, value: `'${hard}'` });
  }
  return "";
}
function boxText(b) { return t("x {x0}~{x1}%, y {y0}~{y1}%", { x0: Math.round(b[0] * 100), x1: Math.round(b[2] * 100), y0: Math.round(b[1] * 100), y1: Math.round(b[3] * 100) }); }
function settingControl(item, v, off) {
  const dis = off || wsState !== "up" ? " disabled" : "";
  const k = escapeHtml(item.key);
  if (item.kind === "bool") return `<button class="switch" role="switch" aria-checked="${!!v}" aria-label="${escapeHtml(item.label)}" data-set="${k}" data-bool="1"${dis}></button>`;
  if ((item.kind === "choice" || item.kind === "int") && (item.options.length > 4 || ["local_model", "local_busy_model", "monitor", "agent_model_name"].includes(item.key))) {
    // A list too long for a row of buttons. Not a <select>: that one is drawn by the operating
    // system, so it ignores every surface this panel is made of and opens a list in the system's
    // own font and colours in the middle of a glass sheet. This is the same control in the panel's
    // language, and it is a listbox for a screen reader as well (combo() below runs it).
    const now = item.options.find(([ov]) => ov === v);
    return `<div class="combo" data-combo="${k}">
      <button type="button" class="combo-btn" data-set="${k}" data-kind="${item.kind}" role="combobox"
        aria-expanded="false" aria-haspopup="listbox" aria-controls="combo-${k}"
        aria-label="${escapeHtml(item.label)}"${dis}><span class="combo-val">${escapeHtml(now ? now[1] : String(v ?? ""))}</span>${COMBO_MARK}</button>
      <ul class="combo-list" id="combo-${k}" role="listbox" aria-label="${escapeHtml(item.label)}" hidden>${item.options.map(([ov, ol], i) =>
        `<li role="option" id="combo-${k}-${i}" data-val="${escapeHtml(JSON.stringify(ov))}"
          aria-selected="${ov === v}"><span class="combo-tick">${TICK_MARK}</span><span>${escapeHtml(ol)}</span></li>`).join("")}</ul></div>`;
  }
  if (item.kind === "choice" || item.kind === "int") {
    return `<div class="seg" role="group" aria-label="${escapeHtml(item.label)}">${item.options.map(([ov, ol]) =>
      `<button type="button" data-set="${k}" data-val="${escapeHtml(JSON.stringify(ov))}" aria-pressed="${ov === v}"${dis}>${escapeHtml(ol)}</button>`).join("")}</div>`;
  }
  if (item.kind === "box") {
    return `<button type="button" class="btn sm" data-act="draw"${wsState !== "up" ? " disabled" : ""}>${v ? t("Redraw") : t("Draw")}</button>`
      + (v ? `<button type="button" class="btn sm ghost" data-set="${k}" data-val="null">${t("Clear")}</button>` : "");
  }
  return "";
}
let settingsSection = "solve";
let drawnSection = null;        // what the pane holds now, so a redraw is not mistaken for a move
function settingRow(item) {
  const v = settingsValues[item.key], why = settingBlocker(item);
  // Several of a list switched on and off: the buttons of a row of choices, each pressed in while it is
  // on. They were checkboxes, drawn by the operating system in its own boxes and accent colour: the
  // one control in the sheet still drawn that way after the dropdowns stopped being <select>s.
  const multi = item.kind === "multi" ? `<div class="seg checks" role="group" aria-label="${escapeHtml(item.label)}">${item.options.map(([ov, ol]) =>
    `<button type="button" data-set="${escapeHtml(item.key)}" data-multi="${escapeHtml(ov)}" aria-pressed="${(v || []).includes(ov)}"${why || wsState !== "up" ? " disabled" : ""}>${escapeHtml(ol)}</button>`).join("")}</div>` : "";
  // Free words (Skip windows): a text box under the label across the row, as the ticks of a list are, the words set
  // apart by commas. Sent when Enter is pressed or the keyboard leaves it (wordsCommit)
  const words = item.kind === "words" ? `<textarea class="words" rows="1" data-set="${escapeHtml(item.key)}" aria-label="${escapeHtml(item.label)}"
    placeholder="${escapeHtml(t("Words, separated by commas"))}" spellcheck="false" autocomplete="off"${why || wsState !== "up" ? " disabled" : ""}>${escapeHtml((Array.isArray(v) ? v : []).join(", "))}</textarea>` : "";
  // the drawn box as it stands, set apart from the server's help after it: "none" alone, the help says what none means
  const extra = item.kind === "box" ? ` · ${t("Now: {box}", { box: v ? boxText(v) : t("none") })}` : "";
  const pick = (item.opt_help || {})[String(v)];
  return `<div class="set" aria-disabled="${!!why}"><span class="lbl">${escapeHtml(item.label)}</span><span class="ctl">${settingControl(item, v, !!why)}</span>
    ${multi}${words}${pick ? `<p class="help pick">${escapeHtml(pick)}</p>` : ""}
    <p class="help">${escapeHtml(extra ? (item.help || "").replace(/[.。]\s*$/, "") : item.help || "")}${extra}${why ? ` <span class="warn">${escapeHtml(why)}</span>` : ""}</p></div>`;
}
// Two dozen settings in one column meant scrolling past the ones you were not looking for. The
// sections become tabs down the side, so every setting is one click from any other.
function renderSettings() {
  renderSetup();   // the setup guide holds settings and states too, and is drawn with them
  const body = $("settings-body");
  if (!body || $("settings-overlay").hidden) return;
  if (sheetBusy()) { sheetDue = true; return; }   // drawn once the press or the typing is over (sheetSettle)
  // The sheet is drawn again on every status message from the server, not only when something here
  // changed, and that replaces the row an open dropdown is in. The list goes back up afterwards on
  // the same row and the same choice: dropping it meant a model loading a second later shut a list
  // somebody was in the middle of reading, and leaving it alone left it on a node nobody can reach.
  const reopen = comboOpen && { key: comboOpen.btn.dataset.set, at: comboAt() };
  comboClose(false);
  if (!settingsMeta) { body.innerHTML = `<p class="cap">${t("Settings once the server is connected")}</p>`; return; }
  // Keep the keyboard where it was across a redraw: the sheet is drawn again on every status
  // message from the server, not only when something here changed.
  // Which control had the keyboard, precisely: several buttons in a choice group share one key,
  // so the value (or the checkbox's own option) is what tells them apart.
  const was = document.activeElement?.dataset || {};
  const focus = was.set;
  const focusVal = was.val;       // a choice button
  const focusMulti = was.multi;   // a checkbox in a type group
  const tabFocus = was.sec;
  const actFocus = was.act;
  const has = (sec) => settingsMeta.items.some((i) => i.section === sec) || (sec === "resource" && !!eng()?.local?.present);
  const secs = settingsMeta.sections.filter(([sec]) => has(sec));
  if (!secs.some(([sec]) => sec === settingsSection)) settingsSection = secs[0]?.[0] || "solve";
  const nav = secs.map(([sec, title]) =>
    `<button type="button" role="tab" class="set-tab" data-sec="${escapeHtml(sec)}" aria-selected="${sec === settingsSection}"
       tabindex="${sec === settingsSection ? 0 : -1}">${escapeHtml(sec === "agent" ? AGS() : title)}</button>`).join("");
  const sec = settingsSection;
  const rows = settingsMeta.items.filter((i) => i.section === sec).map(settingRow).join("");
  const gpu = sec === "resource" && eng()?.local?.present
    ? (eng().local.loaded
      ? `<div class="set"><span class="lbl">${t("Free GPU")}</span><span class="ctl"><button type="button" class="btn sm" data-act="gpu"${wsState !== "up" ? " disabled" : ""}>${t("Free")}</button></span>
        <p class="help">${t("Unloads it from the GPU · loads again with the next problem")}</p></div>`
      : `<div class="set"><span class="lbl">${t("Load to GPU")}</span><span class="ctl"><button type="button" class="btn sm" data-act="gpu-load"${wsState !== "up" ? " disabled" : ""}>${t("Load")}</button></span>
        <p class="help">${t("Load it onto the GPU now and the first problem is solved at once")}</p></div>`) : "";
  const note = sec === "agent" ? outboundNote() : "";
  const keep = body.querySelector(".set-pane")?.scrollTop || 0;
  // The pane slides in when another section is picked, and only then: it is redrawn every
  // few seconds otherwise, and an animation on that is a flicker nobody asked for.
  const moved = sec !== drawnSection;
  drawnSection = sec;
  // --tab-cols: half the tabs, rounded up, so a narrow sheet (index.html, max-width 720px) sets them in
  // two even rows; seven used to wrap six and one, with GPU alone on the second row.
  body.innerHTML = `<nav class="set-nav" role="tablist" aria-label="${t("Settings sections")}" style="--tab-cols: ${Math.max(1, Math.ceil(secs.length / 2))}">${nav}</nav>`
    + `<div class="set-pane${moved ? " enter" : ""}" role="tabpanel" aria-label="${escapeHtml(secs.find(([x]) => x === sec)?.[1] || "")}">`
    + `${note ? `<p class="sec-note">${note}</p>` : ""}${rows}${gpu}</div>`;
  const pane = body.querySelector(".set-pane");
  fitWords(body);                // a box of words as tall as its lines, before the pane's place is put back
  if (pane) pane.scrollTop = moved ? 0 : keep;
  if (focus) {
    // The same option, not the first one with that key.
    const sel = `[data-set="${CSS.escape(focus)}"]`
      + (focusVal !== undefined ? `[data-val="${CSS.escape(focusVal)}"]`
        : focusMulti !== undefined ? `[data-multi="${CSS.escape(focusMulti)}"]` : "");
    (body.querySelector(sel) || body.querySelector(`[data-set="${CSS.escape(focus)}"]`))?.focus();
  }
  else if (tabFocus) body.querySelector(`[data-sec="${CSS.escape(tabFocus)}"]`)?.focus();
  else if (actFocus) body.querySelector(`[data-act="${CSS.escape(actFocus)}"]`)?.focus();
  if (reopen) {
    const btn = body.querySelector(`.combo-btn[data-set="${CSS.escape(reopen.key)}"]:not([disabled])`);
    if (btn) { comboToggle(btn); if (reopen.at >= 0) comboMove(reopen.at); }
  }
}
function showSection(sec) {
  if (sec === settingsSection) return;
  settingsSection = sec;
  renderSettings();
  $("settings-body").querySelector(`[data-sec="${CSS.escape(sec)}"]`)?.focus();
}
function setSetting(key, value) {
  if (!send({ type: "setting", key, value })) return false;
  settingsValues[key] = value;   // shown at once; the server sends the stored value back
  renderSettings(); renderShot();
  return true;
}
// The panes that hold rows of settings: Solver settings and the setup guide, each row pressed and typed into the same way
const onSheets = (type, fn) => { for (const id of ["settings-body", "setup-body"]) $(id).addEventListener(type, fn); };
// ---------- a box of words in the sheet (Skip windows) ----------
// The sheet is drawn again on every message from the server, and two moments wait for that: a press in it (the control
// under the pointer replaced between the press and the release takes no click), and the keyboard in a box of words (a
// redraw puts the caret back at the start and cuts a Korean syllable being put together)
let sheetPress = false, sheetDue = false;
function sheetBusy() { return sheetPress || !!document.activeElement?.matches?.(":is(#settings-body, #setup-body) textarea.words"); }
// The redraw that waited, once neither holds: after the focus has moved on (a Tab out of the box) or the click has landed
function sheetSettle() { setTimeout(() => { if (sheetDue && !sheetBusy()) { sheetDue = false; renderSettings(); } }, 0); }
for (const o of ["settings-overlay", "setup-overlay"]) $(o).addEventListener("pointerdown", () => { sheetPress = true; }, true);
for (const ev of ["pointerup", "pointercancel"]) window.addEventListener(ev, () => { if (sheetPress) { sheetPress = false; sheetSettle(); } }, true);
// The words in a box: split at commas (and at line ends, for a list pasted one to a line), trimmed, none of them empty
const wordsOf = (text) => text.split(/[,\n]/).map((w) => w.trim()).filter(Boolean);
// Each box as tall as its lines, up to the stylesheet's limit (index.html, .set textarea.words)
function fitWords(root = document) {
  for (const box of root.querySelectorAll(":is(#settings-body, #setup-body) textarea.words")) {
    box.style.height = "auto";                                                         // its own height first, so fewer lines shrink it
    box.style.height = `${box.scrollHeight + box.offsetHeight - box.clientHeight}px`;   // then its lines, with its edges
  }
}
// The words typed go to the server when they differ from what it holds; the sheet shows what it sends back
function wordsCommit(box) {
  const key = box.dataset.set, list = wordsOf(box.value);
  if (JSON.stringify(list) === JSON.stringify(settingsValues[key] || [])) return;
  if (send({ type: "setting", key, value: list })) settingsValues[key] = list;
}
onSheets("input", (e) => { if (e.target.matches?.("textarea.words")) fitWords(); });
onSheets("keydown", (e) => {
  const box = e.target.closest?.("textarea.words");
  if (!box) return;
  // Enter sends them, tidied as they are kept; not while a Korean syllable is being put together (that Enter is the IME's)
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    box.value = wordsOf(box.value).join(", ");
    wordsCommit(box);
    fitWords();
  }
  // Escape puts back what the server holds; the sheet's own Escape then closes it, as it does from anywhere in it
  else if (e.key === "Escape") box.value = (settingsValues[box.dataset.set] || []).join(", ");
});
// Leaving the box sends what was typed, and the redraw that waited comes once the focus has moved on
onSheets("focusout", (e) => {
  if (!e.target.matches?.("textarea.words")) return;
  wordsCommit(e.target);
  sheetDue = true;
  sheetSettle();
});
window.addEventListener("resize", () => { if (!$("settings-overlay").hidden) fitWords(); });   // the lines wrap at another width
let settingsOpener = null;
function openSettings() {
  toggleMenu(false);
  settingsOpener = document.activeElement;
  $("settings-overlay").hidden = false;
  renderSettings();
  $("settings-close").focus({ preventScroll: true });
}
function closeSettings() {
  $("settings-overlay").hidden = true;
  resetArmed = 0;                      // armed, closed, reopened: one click would have sent it
  const rb = $("settings-reset");
  rb.textContent = t("Reset to defaults");
  rb.classList.remove("on");
  // offsetParent: the ⋯ menu closes as the sheet opens, so the item it was opened from is hidden
  // by now and focusing it would put the keyboard nowhere.
  const back = settingsOpener && document.body.contains(settingsOpener) && settingsOpener.offsetParent
    ? settingsOpener : $("more");
  settingsOpener = null;
  back.focus({ preventScroll: true });
}
const CAN_FOCUS = 'button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), [href], [tabindex="0"]';
$("settings").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.stopPropagation(); closeSettings(); return; }
  if (e.key !== "Tab") return;
  // Without this the keyboard walks out of the dialog and into the page behind it, which is still
  // there: the next Tab lands on a card button nobody can see.
  const f = [...$("settings").querySelectorAll(CAN_FOCUS)].filter((el) => el.offsetParent !== null);
  if (!f.length) return;
  const edge = e.shiftKey ? f[0] : f[f.length - 1];
  if (document.activeElement === edge) { (e.shiftKey ? f[f.length - 1] : f[0]).focus(); e.preventDefault(); }
});
let resetArmed = 0;
$("settings-reset").onclick = () => {
  const b = $("settings-reset");
  if (Date.now() > resetArmed) {          // asked once, done on the second press
    resetArmed = Date.now() + 5000;
    b.textContent = t("Press again to reset");
    b.classList.add("on");
    setTimeout(() => { if (Date.now() > resetArmed) { b.textContent = t("Reset to defaults"); b.classList.remove("on"); } }, 5200);
    return;
  }
  resetArmed = 0;
  b.textContent = t("Reset to defaults");
  b.classList.remove("on");
  send({ type: "settings_reset" });
};
$("settings-close").onclick = closeSettings;
// Closing on a click outside, but only when the press and the release are both outside: selecting
// help text inside the sheet and letting go over the veil used to close it.
let overlayPress = false;
$("settings-overlay").addEventListener("mousedown", (e) => { overlayPress = e.target === $("settings-overlay"); });
$("settings-overlay").addEventListener("click", (e) => {
  if (overlayPress && e.target === $("settings-overlay")) closeSettings();
  overlayPress = false;
});
$("settings-body").addEventListener("keydown", (e) => {
  const tab = e.target.closest(".set-tab");
  if (!tab || !["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
  const tabs = [...$("settings-body").querySelectorAll(".set-tab")];
  const i = tabs.indexOf(tab);
  const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1
    : i + (e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : -1);
  const pick = tabs[(next + tabs.length) % tabs.length];
  // Stopped here, as the dropdown's keys are: the page reads arrow up and Home as scrolling up
  // the notebook, and walking the tabs used to stop it following new answers.
  if (pick) { e.preventDefault(); e.stopPropagation(); showSection(pick.dataset.sec); }
});
// The contents' dropdowns: the same list, opened from outside the settings sheet
document.addEventListener("keydown", (e) => {
  if (!comboOpen?.btn.dataset.proxy) return;
  const n = comboOpen.list.querySelectorAll("li").length, at = comboAt();
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); comboMove((at + (e.key === "ArrowDown" ? 1 : n - 1)) % n); }
  else if (e.key === "Enter") { e.preventDefault(); comboPick(comboOpen.list.querySelectorAll("li")[Math.max(0, at)]); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); comboClose(); }
  else if (e.key === "Tab") comboClose(false);   // focus moves on, and the list does not stay behind
}, true);
// The local model's Download key (pullOffer), on its card or in the alert band: one press asks the server once
document.addEventListener("click", (e) => {
  const key = e.target.closest?.(".pull-model");
  if (!key || key.disabled) return;
  key.disabled = true;
  send({ type: "llm_pull", model: key.dataset.model });
});
document.addEventListener("click", (e) => {
  const btn = e.target.closest?.(".combo-btn[data-proxy]");
  if (btn) { e.preventDefault(); comboToggle(btn); return; }
  if (comboOpen?.btn.dataset.proxy) {
    const li = e.target.closest?.(".combo-list li");
    if (li) comboPick(li); else comboClose(false);           // a click anywhere else closes it
  }
});
onSheets("click", (e) => {
  const tab = e.target.closest("[data-sec]");
  if (tab) { showSection(tab.dataset.sec); return; }
  const t = e.target.closest("[data-set]");
  if (!t || t.disabled || t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;   // a box is typed into, not pressed
  const item = settingItem(t.dataset.set);
  if (!item) return;
  if (t.dataset.multi !== undefined) {
    // one of several: turned on or off, and sent as the whole list, in the order the options come in
    const now = new Set(settingsValues[item.key] || []);
    if (now.has(t.dataset.multi)) now.delete(t.dataset.multi); else now.add(t.dataset.multi);
    setSetting(item.key, item.options.map(([ov]) => ov).filter((ov) => now.has(ov)));
  } else if (t.dataset.bool) setSetting(item.key, !settingsValues[item.key]);
  else if (t.dataset.val !== undefined) setSetting(item.key, JSON.parse(t.dataset.val));
});
// ---------- the dropdown ----------
// One list open at a time, and it closes on a choice, on Escape, on a click elsewhere and when the
// focus leaves it. The sheet behind it can be scrolled while it is open, so it closes on that too
// rather than hanging in the air over a row that has moved.
let comboOpen = null;

function comboClose(pick) {
  if (!comboOpen) return;
  const { btn, list, home } = comboOpen;
  comboOpen = null;
  list.hidden = true;
  list.classList.remove("up", "start");
  list.removeAttribute("style");
  if (home && list.parentElement !== home) home.appendChild(list);   // back where the markup put it
  btn.setAttribute("aria-expanded", "false");
  btn.removeAttribute("aria-activedescendant");
  list.querySelectorAll(".on").forEach((e) => e.classList.remove("on"));
  if (pick !== false) btn.focus();          // the focus goes back where it was pressed
}

// Where the open list goes. The settings pane is a scroller, and a scroller cuts off whatever
// sticks out of it: left in place, a list opened near the bottom of the pane lost 72 px of itself
// (measured). So while it is open it hangs off the end of the page instead, positioned against the
// window, and the room it has is the pane's own visible height rather than the whole window.
// Where the control sits in the window, to the pixel: the list is placed against this and goes when
// it changes.
function comboWhere() {
  const b = comboOpen.btn.getBoundingClientRect();
  return `${Math.round(b.top)}:${Math.round(b.left)}`;
}

function comboPlace() {
  const { btn, list } = comboOpen;
  const b = btn.getBoundingClientRect();
  const pane = btn.closest(".set-pane");
  const p = pane ? pane.getBoundingClientRect() : { top: 0, bottom: innerHeight };
  const top = Math.max(8, p.top), bottom = Math.min(innerHeight - 8, p.bottom);
  list.style.minWidth = `${Math.round(b.width)}px`;
  list.style.maxHeight = `${Math.round(Math.max(120, Math.max(bottom - b.bottom, b.top - top) - 10))}px`;
  // Its laid-out size, not its drawn one: while it opens it is drawn a little smaller (its pop, index.html), and a width read then put
  // it 4 px off its key
  const h = list.offsetHeight;
  // below unless it does not fit there and does above
  const up = b.bottom + 6 + h > bottom && b.top - 6 - h >= top;
  list.classList.toggle("up", up);
  const w = list.offsetWidth;
  // Lined up with the control on the side the sheet lines it up on: right edges on a wide sheet, where
  // the controls stand at the right, and left edges on a narrow one, where each sits under its label at
  // the left. Lining up the right edges there hung the list out past the sheet's left edge (by 8 px at
  // 420 px, and 29 px to the left of its own control). Kept inside the sheet and the window either way.
  const sheet = btn.closest(".settings")?.getBoundingClientRect() || { left: 0, right: innerWidth };
  const atLeft = b.left - sheet.left < sheet.right - b.right;
  const lo = Math.max(8, sheet.left + 1), hi = Math.min(innerWidth - 8, sheet.right - 1) - w;
  const want = atLeft ? b.left : b.right - w;
  list.style.left = `${Math.round(Math.min(Math.max(want, lo), Math.max(lo, hi)))}px`;
  list.classList.toggle("start", atLeft);                 // its pop grows from that edge (index.html)
  list.style.top = up ? "" : `${Math.round(b.bottom + 6)}px`;
  list.style.bottom = up ? `${Math.round(innerHeight - b.top + 6)}px` : "";
  comboOpen.where = comboWhere();
}

function comboMove(to) {
  const { list, btn } = comboOpen;
  const opts = [...list.querySelectorAll("li")];
  if (!opts.length) return;
  const at = Math.max(0, Math.min(opts.length - 1, to));
  opts.forEach((o) => o.classList.remove("on"));
  opts[at].classList.add("on");
  btn.setAttribute("aria-activedescendant", opts[at].id);
  // keep the one being moved to in sight when the list is longer than its box
  opts[at].scrollIntoView({ block: "nearest" });
}

function comboAt() {
  const opts = [...comboOpen.list.querySelectorAll("li")];
  return opts.findIndex((o) => o.classList.contains("on"));
}

function comboToggle(btn) {
  if (comboOpen && comboOpen.btn === btn) return comboClose();
  comboClose(false);
  const list = btn.parentElement.querySelector(".combo-list");
  if (!list) return;
  const home = list.parentElement;
  list.hidden = false;
  document.body.appendChild(list);        // out of the scroller, so nothing can cut it off
  btn.setAttribute("aria-expanded", "true");
  if (btn.dataset.proxy) document.body.appendChild(list);   // the card's frosted glass would hold a fixed list inside itself, cut off
  comboOpen = { btn, list, home };
  comboPlace();
  const opts = [...list.querySelectorAll("li")];
  comboMove(Math.max(0, opts.findIndex((o) => o.getAttribute("aria-selected") === "true")));
}

// The contents' two filters wear the settings' dropdown: the browser's own list opened in its own font and colours, the one
// thing on the page not made of the page. The <select> stays underneath, as the value and the change event everyone reads.
function syncPick(sel) {
  const box = sel.nextElementSibling?.classList?.contains("pick") ? sel.nextElementSibling : null;
  const opts = [...sel.options].map((o) => [o.value, o.textContent, o.dataset.short]);
  const now = opts.find(([v]) => v === sel.value) || opts[0] || ["", ""];
  const label = sel.getAttribute("aria-label") || "";
  const html = `<button type="button" class="combo-btn" data-proxy="${sel.id}" role="combobox" aria-expanded="false" aria-haspopup="listbox" aria-controls="combo-${sel.id}"
      aria-label="${escapeHtml(label)}"><span class="combo-val">${escapeHtml(now[2] || now[1])}</span>${COMBO_MARK}</button>
    <ul class="combo-list" id="combo-${sel.id}" role="listbox" aria-label="${escapeHtml(label)}" hidden>${opts.map(([v, l], i) =>
      `<li role="option" id="combo-${sel.id}-${i}" data-val="${escapeHtml(JSON.stringify(v))}" aria-selected="${v === sel.value}"><span class="combo-tick">${TICK_MARK}</span><span>${escapeHtml(l)}</span></li>`).join("")}</ul>`;
  const el = box || sel.insertAdjacentElement("afterend", Object.assign(document.createElement("div"), { className: "combo pick" }));
  if (el.dataset.html !== html && !(comboOpen && comboOpen.btn.parentElement === el)) { el.dataset.html = html; el.innerHTML = html; }
}
function comboPick(li) {
  const proxy = comboOpen?.btn.dataset.proxy;
  if (proxy) {
    const sel = $(proxy);
    comboClose();
    sel.value = JSON.parse(li.dataset.val);
    sel.dispatchEvent(new Event("change"));
    syncPick(sel);
    document.querySelector(`.combo-btn[data-proxy="${proxy}"]`)?.focus();   // syncPick drew the button again: focus went with the old one
    return;
  }
  const btn = comboOpen?.btn;
  const item = btn && settingItem(btn.dataset.set);
  comboClose();
  if (item && li) setSetting(item.key, JSON.parse(li.dataset.val));
}

onSheets("click", (e) => {
  const btn = e.target.closest(".combo-btn");
  if (btn && !btn.disabled) { e.preventDefault(); comboToggle(btn); return; }
});
// the open list is a child of the page, not of the sheet, so its own clicks are caught here
addEventListener("click", (e) => {
  const li = comboOpen && e.target.closest(".combo-list li");
  if (li) { e.preventDefault(); comboPick(li); }
});
// Escape belongs to the open list wherever the keyboard happens to be: a press on the list itself
// leaves the focus on nothing in particular, and without this the sheet closed under it.
addEventListener("keydown", (e) => {
  if (e.key === "Escape" && comboOpen) { e.preventDefault(); e.stopPropagation(); comboClose(); }
}, true);
onSheets("keydown", (e) => {
  const btn = e.target.closest(".combo-btn");
  if (!btn || btn.disabled) return;
  const open = comboOpen && comboOpen.btn === btn;
  if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ")) {
    e.preventDefault(); e.stopPropagation(); return comboToggle(btn);
  }
  if (!open) return;
  // The page reads these keys too: arrow up and home stop the notebook following a streaming
  // answer, arrow down and space tell it the view was moved by hand. Walking a list of settings is neither.
  if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " ", "Tab"].includes(e.key) || e.key.length === 1) {
    e.stopPropagation();
  }
  const n = comboOpen.list.querySelectorAll("li").length;
  if (e.key === "ArrowDown") { e.preventDefault(); comboMove(comboAt() + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); comboMove(comboAt() - 1); }
  else if (e.key === "Home") { e.preventDefault(); comboMove(0); }
  else if (e.key === "End") { e.preventDefault(); comboMove(n - 1); }
  else if (e.key === "Enter" || e.key === " ") {
    e.preventDefault(); comboPick(comboOpen.list.querySelectorAll("li")[comboAt()]);
  } else if (e.key === "Tab") comboClose(false);
  else if (e.key.length === 1) {
    // typing jumps to the next option that starts with that letter, the way a list is used
    const opts = [...comboOpen.list.querySelectorAll("li")];
    const from = comboAt() + 1;
    const hit = opts.slice(from).concat(opts.slice(0, from))
      .find((o) => o.textContent.trim().toLowerCase().startsWith(e.key.toLowerCase()));
    if (hit) comboMove(opts.indexOf(hit));
  }
});
// the list is no longer inside .combo while it is open, so a press on it counts as inside
addEventListener("pointerdown", (e) => {
  if (comboOpen && !e.target.closest(".combo") && !e.target.closest(".combo-list")) comboClose(false);
}, true);
addEventListener("resize", () => comboClose(false));
// The list is fixed to the window, so it has to go when the control it points at moves. Which
// scroll did it does not matter and asking is the wrong question: this panel scrolls itself all the
// time without touching the sheet (it follows a streaming answer, keeps the heard words at their
// last line, brings a new screenshot into view), and closing on those made the list unusable for as
// long as the tool was working. So the control's own position is what is watched.
addEventListener("scroll", () => {
  if (comboOpen && comboWhere() !== comboOpen.where) comboClose(false);
}, true);

// ---------- controls ----------
// A toast is a band that passes: the same mark, words and box (alertHtml, noticeMsg), over the page for a few seconds.
// `go`: what pressing it does (it then says where it goes, and stays a little longer); null for none
// `tone`: the bands' kinds: "info" (or "") something to know, "done" what was asked for went through, "warn" it was
// not done, "bad" something broke. `cmd`: a command the words name, drawn as a chip
const TOAST_TONES = new Set(["info", "done", "warn", "bad"]);
function toast(text, go = null, tone = "", cmd = "") {
  const el = $("toast"), kind = TOAST_TONES.has(tone) ? tone : "info";
  el.innerHTML = alertHtml(kind, noticeMsg(text, cmd), go ? `<span class="btn sm">${t("To the answer")}</span>` : "");
  el.dataset.tone = kind;
  el.onclick = go ? () => { go(); el.classList.remove("show"); } : null;
  el.tabIndex = go ? 0 : -1;                                 // a pressable one is reached by the keyboard too
  el.onkeydown = go ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.onclick(); } } : null;
  el.classList.toggle("go", !!go);
  // Every notice comes in one place, under the bar, below any bands that are up; Classic places it, in index.html
  el.classList.add("show");
  // Long enough to be read: 3.6 s for a few words and more for more, up to 9 s; one to press stays 3 s longer
  const ms = Math.min(9000, Math.max(3600, 1600 + String(text ?? "").length * 70)) + (go ? 3000 : 0);
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.classList.remove("show"); el.tabIndex = -1; el.onclick = el.onkeydown = null; }, ms);   // gone: not to be reached by the keyboard, unseen
}
function send(msg) {
  if (demo) { toast(t("A preview: nothing is sent")); return false; }
  if (!sock || sock.readyState !== WebSocket.OPEN) { toast(t("No connection to the server"), null, "bad"); return false; }
  sock.send(JSON.stringify(msg)); return true;
}
// Play a one-shot animation again, whatever state it was left in
function replay(el, cls) {
  if (!el) return;
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}
function setPaused(p) {
  const changed = paused !== p;
  paused = p;
  // "Start again" beside the blue "Reanalyze" had people pressing the wrong one: it analyses once and
  // leaves the pause on. The word and the icon both change instead.
  $("pause-text").textContent = p ? t("Continue") : t("Pause");
  $("pause").classList.toggle("on", p);
  // Its mark is what pressing it does, as its word and its tooltip are: the two bars while it watches, the triangle while paused.
  // Its colour stays the state's: green watching, orange paused
  $("pause-icon").innerHTML = p ? '<path d="M7 4.5v15l13-7.5z"/>'
    : '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>';
  if (changed) replay($("pause"), "swap");
  $("pause").title = p ? t("Continue automatic analysis") : t("Pause automatic analysis");
}
function setLang(lang) {        // Speech language is a setting (Solving settings > Speech); this keeps them in step
  status.lang = lang;
  if (lang && settingsValues.speech_lang !== lang) { settingsValues.speech_lang = lang; renderSettings(); }
}
// Motion off by a choice in the menu, or by the system's when the menu is set to follow it (theme.js)
const calm = () => document.documentElement.dataset.motion === "off";
function setMotion(m) {
  try { localStorage.setItem("sidenote-motion", m); } catch (_) {}
  document.documentElement.dataset.motion = motionNow();
  document.querySelectorAll("#motion-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.motion === m)));
}
function themeNow() {
  try { if (localStorage.getItem("sidenote-theme") === "auto") return "auto"; } catch (_) {}   // the attribute holds what auto came to
  return document.documentElement.dataset.theme || "dark";
}
function setTheme(t) {
  // "Auto" is stored too, so that leaving it unset means dark (what a panel beside an editor wants).
  document.documentElement.dataset.theme = t === "auto" ? autoTheme() : t;
  try { localStorage.setItem("sidenote-theme", t); } catch (_) {}
  document.querySelectorAll("#theme-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.theme === t)));
}
// The panel's language, picked in the menu and kept in this browser (i18n.js reads it before the first paint). Every word on
// the page and the server's messages follow it, so the page opens again in it, without an address's ?lang= that would win
function setUiLang(l) {
  try { if (l === "auto") localStorage.removeItem("sidenote-lang"); else localStorage.setItem("sidenote-lang", l); } catch (_) {}
  document.querySelectorAll("#lang-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === l)));
  const url = new URL(location.href);
  url.searchParams.delete("lang");
  if ((l === "auto" ? browserLang() : l) !== LANG || url.href !== location.href) location.replace(url.href);
}
// The design (theme.js sets it before the first paint; Classic only since New (Beta) was switched off). Diagrams draw from its colours.
function setSkin(skin) {
  document.documentElement.dataset.skin = skin;
  syncSrc();
}
// A connection's row keeps its details in the name's tooltip: a chevron on every row was one more thing to read and press
function syncSrc() {
  document.querySelectorAll(".conn .src").forEach((src) => {
    src.classList.remove("folds", "open");
    srcNameTitle(src);
  });
}
// A card name's tooltip: the card's facts, which a folded card hides, then what a press on the name does. The fold kept its
// own words there and the facts were gone after one press, or the facts and no word of the fold
function srcNameTitle(src) {
  const name = src?.querySelector(".src-name"), facts = src?.querySelector(".facts");
  if (!name) return;
  const lines = facts ? [...facts.querySelectorAll("dt")].map((d) => `${d.textContent}: ${d.nextElementSibling?.textContent || ""}`) : [];
  if (name.matches("[data-card-fold]")) lines.push(name.closest(".card")?.classList.contains("shut") ? t("Open the card") : t("Fold the card"));
  if (lines.length) name.title = lines.join("\n"); else name.removeAttribute("title");
}
function toggleMenu(open) {
  const m = $("menu"), want = open ?? m.hidden;
  m.hidden = !want; $("more").setAttribute("aria-expanded", String(want));
  $("menu-veil").hidden = !want;
  if (!want && clearArmed) { clearArmed = 0; $("clear").textContent = t("Clear history"); $("clear").classList.remove("on"); }   // armed only while it is in view
}
function reanalyze() {
  if (!send({ type: "reanalyze" })) return;
  manualUntil = Date.now() + 10000;   // the analysis this starts was asked for by hand: said at once (onStart)
  toast(!capture.screen_on ? t("Solving again from what was heard") : capture.clients === 0 ? t("Capture off: reanalyzing the last screen") : t("Reanalyzing the screen now"));
}
function togglePause() { send({ type: paused ? "resume" : "pause" }); }
function goLatest() { pinnedView = null; stick = true; $("jump").hidden = true; toBottom(true); setTimeout(updateView, 400); }
// From the index: open the entry if folded and bring it into view. `open: false` (the j and k keys) leaves a folded one folded
function goTo(id, { open = true } = {}) {
  const it = items.get(id), el = entryEl(id);
  if (!it || !el) return;
  if (el.hidden) clearChoice();   // pointed at from a notice, an answer the filter hides: going there lifts the filter
  if (open && folded(it)) { unfolded.add(id); renderEntry(it); }
  stopFollowing();   // reading what was picked: a new answer offers the jump instead of pulling the page away
  pinnedView = id; pinnedAt = Date.now(); updateView();   // the ribbon goes to what was picked, at once
  autoUntil = Date.now() + 900;
  entryEl(id).scrollIntoView({ block: "start", behavior: motion() });
  entryEl(id).classList.remove("flash"); void entryEl(id).offsetWidth; entryEl(id).classList.add("flash");
  // No new answer has come for picking a row: the jump stays as it was, and goes only if the page has reached the end
  setTimeout(() => { stick = pinnedView == null && nearBottom(); if (stick) $("jump").hidden = true; updateView(); }, 500);
}
function switchCapture(which) {
  const on = !(which === "screen" ? capture.screen_on : capture.audio_on);
  if (send({ type: "capture_set", [which]: on })) {
    capture[which === "screen" ? "screen_on" : "audio_on"] = on;   // optimistic; the server confirms
    if (which === "screen" && !on) { forgetScreens(); if (drawing) drawing = null; }
    renderSignals(); renderAlerts(); renderShot();
    toast(which === "screen" ? (on ? t("Screen capture turned on") : t("Screen capture turned off")) : on ? t("Sound capture turned on") : t("Sound capture turned off"), null, "done");
  }
}

$("menu-veil").onclick = () => { toggleMenu(false); $("more").focus({ preventScroll: true }); };
$("reanalyze").onclick = reanalyze;
$("open-settings").onclick = openSettings;
function gpuPressed() {   // a press went out: both keys wait for the server's word on the engines, and for no longer than GPU_WAIT_MS if none comes
  gpuPending = true; $("gpu-release").disabled = $("gpu-load").disabled = true;
  clearTimeout(gpuPressed.timer); gpuPressed.timer = setTimeout(() => { gpuPending = false; renderAll(); }, GPU_WAIT_MS);
}
$("gpu-release").onclick = () => { if (send({ type: "gpu_release" })) gpuPressed(); };
const gpuLoad = () => { if (send({ type: "gpu_load" })) { gpuPressed(); toast(t("Loading onto the GPU · tens of seconds")); } };
$("gpu-load").onclick = () => { if (eng()?.local?.loading) { if (send({ type: "gpu_load_cancel" })) gpuPressed(); } else gpuLoad(); };
// The local model's and the agent's cards fold to their top line on a press of their name, and open again; each as it was
// left, in this browser (open at first, and open where the browser keeps nothing)
const CARD_FOLD_KEY = "sidenote.cardFold";
function cardFold(id, shut, keep = true) {
  const card = $(id), key = card?.querySelector("[data-card-fold]");
  if (!card || !key) return;
  card.classList.toggle("shut", shut);
  key.setAttribute("aria-expanded", String(!shut));
  srcNameTitle(key.closest(".src"));
  if (!keep) return;
  try {
    const kept = JSON.parse(localStorage.getItem(CARD_FOLD_KEY) || "{}");
    kept[id] = shut;
    localStorage.setItem(CARD_FOLD_KEY, JSON.stringify(kept));
  } catch {}
}
for (const id of ["card-local", "card-agent"]) {
  let kept = {};
  try { kept = JSON.parse(localStorage.getItem(CARD_FOLD_KEY) || "{}"); } catch {}
  cardFold(id, kept[id] === true, false);
  const key = $(id)?.querySelector("[data-card-fold]");
  key?.addEventListener("click", () => cardFold(id, !$(id).classList.contains("shut")));
  key?.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); key.click(); } });
}
// the agent's switch: off keeps the mode it had, so turning it back on restores what had been chosen
const AGENT_MODE_KEY = "sidenote.agentMode";
$("sw-agent").onclick = () => {
  const C = eng()?.agent;
  if (!C) return;
  const on = C.mode === "off";
  let mode = "off";
  if (on) { try { mode = localStorage.getItem(AGENT_MODE_KEY) || "hard"; } catch (_) { mode = "hard"; } }
  else { try { localStorage.setItem(AGENT_MODE_KEY, C.mode); } catch (_) {} }
  if (!setSetting("agent_mode", mode)) return;
  C.mode = mode; renderSignals();   // at once; the server's engines message confirms it
  toast(on ? t("{agent} turned on", { agent: AG() }) : t("{agent} turned off · only the local model solves", { agent: AG() }), null, "done");
};
$("roi-draw").onclick = startDrawing;
const clearRoi = () => { if (setSetting("roi_box", null)) toast(t("Region cleared · watching the whole screen"), null, "done"); };
$("roi-clear").onclick = clearRoi;
$("pause").onclick = togglePause;
$("sw-screen").onclick = () => switchCapture("screen");
$("sw-audio").onclick = () => switchCapture("audio");
$("jump").onclick = () => { goLatest(); if (!$("ask").disabled) $("ask").focus({ preventScroll: true }); };   // the button hides itself: the focus goes somewhere
$("more").onclick = (e) => { e.stopPropagation(); toggleMenu(); };
// The window is resized while the panel is open, so the wording is measured again when the field's
// own width changes. Writing a placeholder cannot change that width, so this cannot feed itself.
new ResizeObserver(() => syncAsk()).observe($("ask"));
// The question box grows with what is written, to its six lines (index.html, .composer textarea), and goes back to one when it is sent
function growAsk() {
  const a = $("ask");
  a.style.height = "auto";                       // its own height first, so a shorter question shrinks it again
  a.style.height = `${a.scrollHeight}px`;        // then as tall as its lines; the stylesheet's max-height stops it and it scrolls
}
$("ask").addEventListener("input", growAsk);
// Enter sends, Shift+Enter starts a new line. Not while a Korean syllable is being put together: that Enter belongs to the IME, and taking
// it sent the question with its last letter left behind
$("ask").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  $("askform").requestSubmit();
});
$("askform").onsubmit = (ev) => {
  ev.preventDefault();
  const q = $("ask").value.trim();
  if (q && send({ type: "ask", text: q })) { $("ask").value = ""; growAsk(); }
};
// Tab out of the open menu closes it, or the focus goes on under it
document.addEventListener("focusin", (e) => {
  if (!$("menu").hidden && !e.target.closest(".menu") && e.target.id !== "more") toggleMenu(false);
});
document.addEventListener("click", (e) => {
  if (!$("menu").hidden && !e.target.closest(".menu")) toggleMenu(false);
  const vtab = e.target.closest(".vc-tab");   // a code check's run tab: its run in view (checkHtml)
  if (vtab) {
    const box = vtab.closest(".vcheck");
    box.querySelectorAll(".vc-tab").forEach((t) => t.setAttribute("aria-selected", String(t === vtab)));
    box.querySelectorAll(".vc-case").forEach((k) => { k.hidden = k.dataset.case !== vtab.dataset.case; });
    return;
  }
  const copy = e.target.closest("[data-copy]");
  if (copy) copyText(copy.dataset.copy, copy);
  // One of the follow-up buttons under the latest answer: it carries the whole question it asks.
  const more = e.target.closest("[data-ask]");
  if (more && !more.disabled) {
    if (send({ type: "ask", text: more.dataset.ask })) {
      more.disabled = true;                  // it is on its way: pressing again would ask twice
      more._busyUntil = Date.now() + 2000;   // and syncNextAsks does not let it go any sooner
      setTimeout(() => { more.disabled = wsState !== "up"; }, 2000);   // back, unless the socket went
    }
  }
  const act = e.target.closest("[data-act]");
  if (act?.dataset.act === "resume") togglePause();
  if (act?.dataset.act === "settings") openSettings();
  if (act?.dataset.act === "draw") { closeSettings(); startDrawing(); }
  if (act?.dataset.act === "roi-clear") clearRoi();
  if (act?.dataset.act === "reload") location.reload();
  if (act?.dataset.act === "update-hide") hideUpdate(act.dataset.version || "");
  if (act?.dataset.act === "gpu") send({ type: "gpu_release" });
  if (act?.dataset.act === "gpu-load") gpuLoad();
  const cf = e.target.closest("[data-confirm]");
  if (cf && send({ type: "agent_confirm_reply", cid: cf.dataset.confirm, send: cf.dataset.send === "1" })) {
    confirms.delete(cf.dataset.confirm); renderTail();
  }
  const hb = e.target.closest(".h[data-id]");
  if (hb) goTo(idOf(hb.dataset.id));
  const fb = e.target.closest("[data-fold]");
  if (fb) { const id = idOf(fb.dataset.fold), it = items.get(id); if (it) { if (folded(it)) unfolded.add(id); else unfolded.delete(id); renderEntry(it); } }
  const hm = e.target.closest("[data-heard-more]");
  if (hm) {   // what was heard, whole or its first lines, kept so for the entry when it is drawn again
    const open = hm.getAttribute("aria-expanded") !== "true", box = hm.previousElementSibling;
    box?.classList.toggle("open", open);
    if (open) heardOpen.add(box?.dataset.heardId ?? ""); else heardOpen.delete(box?.dataset.heardId ?? "");
    hm.setAttribute("aria-expanded", String(open));
    hm.querySelector("span").textContent = open ? t("Fold") : t("Show it all");
  }
  // (never of one Practice keeps back, whose keys these are not drawn on)
  const ca = e.target.closest("[data-copy-answer]");
  if (ca) { const it = items.get(idOf(ca.dataset.copyAnswer)); if (it?.head.answer && !held(it)) copyText(plainAnswer(it.head.answer), ca); }
  const ci = e.target.closest("[data-copy-item]");
  if (ci) { const it = items.get(idOf(ci.dataset.copyItem)); if (it && !held(it)) copyText((it.head.answer ? `${ANSWER_LABEL[it.head.type] || t("Summary")}: ${it.head.answer}\n\n` : "") + it.head.body.trim(), ci); }
  // Practice's keys on an answer it keeps back: the next hint, or all of it
  const pk = e.target.closest(".entry [data-act='hint'], .entry [data-act='reveal']");
  if (pk) { const it = items.get(idOf(pk.closest(".entry").dataset.id)); if (pk.dataset.act === "hint") showHint(it, pk); else showAnswer(it, pk); }
  // The star key asks the server, which keeps the star and tells every panel (the "star" message); offline, send() says so
  const sk = e.target.closest("[data-star]");
  if (sk) { const it = items.get(idOf(sk.dataset.star)); if (it) send({ type: "star", id: it.id, starred: !it.starred }); }
  const pt = e.target.closest("[data-ptext]");
  if (pt) { const it = items.get(idOf(pt.dataset.ptext)); if (it && send({ type: "problem_text", id: it.id })) { it.ptext = { pending: true }; renderEntry(it); } }
  const mm = e.target.closest("[data-meta]");
  if (mm) {   // the tokens and the cost: opened or folded, and kept that way through a redraw of the entry
    const box = mm.closest(".meta"), open = !box.classList.contains("open");
    box.classList.toggle("open", open);
    mm.setAttribute("aria-expanded", String(open));
    const tEl = mm.closest("[data-turn]");
    const owner = tEl ? turns.get(idOf(tEl.dataset.turn)) : items.get(idOf(mm.closest(".entry")?.dataset.id));
    if (owner?.meta) owner.meta.open = open;
    if (open) showOpened(box);
  }
  const cpt = e.target.closest("[data-copy-ptext]");
  if (cpt) { const it = items.get(idOf(cpt.dataset.copyPtext)); if (it?.ptext?.text) copyText(it.ptext.text, cpt); }
});
$("theme-seg").onclick = (e) => { const b = e.target.closest("button"); if (b) setTheme(b.dataset.theme); };
$("motion-seg").onclick = (e) => { const b = e.target.closest("button"); if (b) setMotion(b.dataset.motion); };
$("lang-seg").onclick = (e) => { const b = e.target.closest("button"); if (b) setUiLang(b.dataset.lang); };
$("practice-seg").onclick = (e) => { const b = e.target.closest("button"); if (b) setPractice(b.dataset.practice === "on"); };
$("open-keys").onclick = openKeys;
let clearArmed = 0;
$("clear").onclick = () => {
  if (Date.now() - clearArmed > 3000) {   // first click: ask once more (there is no undo)
    // armed: the words change and so does the colour (.menu .item.on), as the sheet's reset does when armed
    clearArmed = Date.now(); $("clear").textContent = t("Press again to clear"); $("clear").classList.add("on");
    setTimeout(() => { if (Date.now() - clearArmed >= 3000) { $("clear").textContent = t("Clear history"); $("clear").classList.remove("on"); } }, 3100);
    return;
  }
  clearArmed = 0; $("clear").textContent = t("Clear history"); $("clear").classList.remove("on");
  // Not while offline: it said done, deleted nothing on the server, and a reload brought it all back. The server says when it is done.
  if (!send({ type: "history_clear" })) { toggleMenu(false); $("more").focus({ preventScroll: true }); toast(t("No connection to the server, so the history cannot be cleared"), null, "bad"); return; }
  clearShown();
  toggleMenu(false); $("more").focus({ preventScroll: true });
};
// What this page shows of the history, gone with it: here when Clear history is pressed, and in every other open panel when the
// server says it was cleared (history_cleared). The others kept every answer, and a star pressed on one was refused.
function clearShown() {
  // answers still being written stay (with their labels); everything finished goes
  const keep = new Set([...items.values()].filter((it) => it.live || it.turns.some((t) => turns.get(t)?.live)).map((it) => it.id));
  for (const [id, it] of [...items]) if (!keep.has(id)) { it.turns.forEach((t) => turns.delete(t)); items.delete(id); unfolded.delete(id); }
  for (const id of [...practiceCards.keys()]) if (!keep.has(idOf(id))) practiceCards.delete(id);   // what Practice kept of them goes too
  keepCards();
  thread = thread.filter((id) => keep.has(id));
  pruneRuns();
  viewId = null; stick = true; lastNone = null; $("jump").hidden = true;
  histQuery = ""; $("hist-q").value = "";   // a search left in the hidden field hid the next answer from the contents
  histDay = ""; histKind = ""; $("hist-day").value = ""; $("hist-kind").value = "";
  historyDays = [];
  histStar = false; historyStarred = 0;   // the starred answers go with the rest (server/history.py, clear)
  heardAny = false; syncHeardKeys();      // and so does what was heard
  renderThread(); renderAll();
}
// ---------- the keyboard ----------
// A letter for what is done most, each listed in the keys' sheet (Keyboard shortcuts in the menu, or ?). Every one of them also
// has its button. Never while typing in a field or a list or inside the settings sheet, and never with Ctrl, Alt or Meta held:
// those keys belong to the browser and to what is typed. Escape closes what is open, and the scroll keys that stop the
// following of new answers stay as they were.
// The letter a key stands for: what it types, or where a layout or an input method types another script there (ㅓ for j on a
// Korean keyboard), the letter of its place on the keyboard. A letter with Shift held is none (? is Shift with /, and is one)
function shortcutKey(e) {
  if (e.key === "?" || e.key === "/") return e.key;
  if (e.shiftKey) return "";
  if (/^[a-z]$/i.test(e.key)) return e.key.toLowerCase();                 // Caps Lock on: still the letter
  const at = /^Key([A-Z])$/.exec(e.code || "");
  return at && !/^[\x20-\x7e]$/.test(e.key) ? at[1].toLowerCase() : "";   // a typed Latin sign is its own, never a letter's
}
const SHORTCUTS = {
  j: () => stepAnswer(1), k: () => stepAnswer(-1), c: () => copyCurrent(), r: () => reanalyze(), p: () => togglePause(),
  "/": () => findAnswer(), h: () => practiceKey("hint"), a: () => practiceKey("answer"),
  "?": () => ($("keys-overlay").hidden ? openKeys() : closeKeys()),
};
// j and k: the next or the previous answer in the notebook, brought into view and made the current one, the contents' ribbon on
// it. A folded one stays folded: going past an answer is not opening it
function stepAnswer(by) {
  const shown = [...$("thread").children].filter((e) => e.classList.contains("entry") && !e.hidden);
  if (!shown.length) return;
  const at = shown.findIndex((e) => idOf(e.dataset.id) === viewId);
  const to = at < 0 ? (by > 0 ? 0 : shown.length - 1) : at + by;
  if (to < 0 || to >= shown.length) return;   // past the first or the last: nothing further that way
  goTo(idOf(shown[to].dataset.id), { open: false });
}
// c: the current answer's answer line, as its Copy key copies it, said on the key and in a notice (the key may be out of view)
async function copyCurrent() {
  const it = viewId != null ? items.get(viewId) : null;
  if (it && held(it)) { toast(t("Answer hidden for practice"), null, "warn"); return; }   // not a way round Practice
  if (!it?.head.answer) { toast(t("No answer line to copy"), null, "warn"); return; }
  const ok = await copyText(plainAnswer(it.head.answer), entryEl(it.id)?.querySelector("[data-copy-answer]") || null);
  toast(ok ? t("Answer line copied") : t("Copy failed"), null, ok ? "done" : "bad");
}
// /: the contents' search, its words picked so what is typed takes their place
function findAnswer() {
  const q = $("hist-q");
  if (q.offsetParent === null) return;   // no answers yet: the search is not there
  q.focus();
  q.select();
}
// h and a: Practice's two keys, on the current answer while Practice keeps it back
function practiceKey(which) {
  const it = viewId != null ? items.get(viewId) : null;
  if (!it || !held(it) || it.live) return;
  if (which === "answer") showAnswer(it);
  else if (!showHint(it)) toast(t("No more hints"), null, "warn");
}
// The keys' sheet: the settings sheet's look, a row a key. The menu's item, ? and Escape open and close it, and so do its close key
// and a press on the veil
let keysOpener = null;
// Where the keyboard goes when a sheet closes: where it was, or for a menu closed by then the key that menu hangs from
function focusBack(was) {
  if (was && was !== document.body && document.body.contains(was) && was.offsetParent) was.focus({ preventScroll: true });
  else if (was?.closest?.("#export-menu")) $("hist-export").focus({ preventScroll: true });
  else if (was?.closest?.(".menu")) $("more").focus({ preventScroll: true });
  else document.activeElement?.blur?.();
}
function openKeys() {
  toggleMenu(false); exportMenu(false);
  comboClose(false);   // a list stands on the page's body, over the sheet, and its arrows and Enter would still choose behind it
  keysOpener = document.activeElement;
  $("keys-overlay").hidden = false;
  $("keys-close").focus({ preventScroll: true });
}
function closeKeys() {
  if ($("keys-overlay").hidden) return;
  $("keys-overlay").hidden = true;
  // The keyboard goes back where it was: to the gear when the sheet came from the menu (closed by now), to nothing from the page
  const was = keysOpener;
  keysOpener = null;
  focusBack(was);
}
$("keys-close").onclick = closeKeys;
// The keyboard stays inside the sheet while it is open, as in the settings sheet
$("keys").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const f = [...$("keys").querySelectorAll(CAN_FOCUS)].filter((el) => el.offsetParent !== null);
  if (!f.length) return;
  const edge = e.shiftKey ? f[0] : f[f.length - 1];
  if (document.activeElement === edge) { (e.shiftKey ? f[f.length - 1] : f[0]).focus(); e.preventDefault(); }
});
// Closed by a press on the veil only when the press and the release are both on it (the settings sheet's rule)
let keysPress = false;
$("keys-overlay").addEventListener("mousedown", (e) => { keysPress = e.target === $("keys-overlay"); });
$("keys-overlay").addEventListener("click", (e) => { if (keysPress && e.target === $("keys-overlay")) closeKeys(); keysPress = false; });
// ---------- What was heard, kept ----------
// One day's sentences, from the server's /heard (Keep what is heard), in the keys' sheet's look: the time and the words of each, Copy all,
// and a .md file. The keys to it, on the card and in the menu, are there while the switch is on or something is kept: with the sound
// off the card is gone, and what was kept can still be read.
let heardAny = false, heardKept = false, heardDay = "", heardLines = [], heardOpener = null, heardPress = false;
// Called when the server's settings come, when /history/days says what is kept, and when it is cleared
function syncHeardKeys() {
  // Switched off: what it kept meanwhile is still there to read, which the server knows
  if (heardKept && !settingsValues.speech_keep) fetch("history/days").then((r) => r.json()).then((d) => { heardAny = !!d.heard; syncHeardKeys(); }).catch(() => {});
  heardKept = !!settingsValues.speech_keep;
  const on = !!settingsValues.speech_keep || heardAny;
  $("hear-kept").hidden = !on;
  $("open-heard").hidden = !on;
}
// The time of a line, to the second: 15:04:09
// A heard line's time, with its seconds, in the clock the rest of the panel uses (fmtClock): it was the only 24-hour one
const heardClock = (ts) => { const d = new Date(ts * 1000), h = d.getHours(), p = (n) => String(n).padStart(2, "0");
  return `${p(h % 12 || 12)}:${p(d.getMinutes())}:${p(d.getSeconds())} ${h < 12 ? "AM" : "PM"}`; };
// One day, or with none named the newest the server holds; a failed request reads as nothing kept
async function loadHeard(day = "") {
  let got = { days: [], day: "", lines: [] };
  try { got = await fetch(`heard${day ? `?day=${encodeURIComponent(day)}` : ""}`).then((r) => r.json()); } catch (_) {}
  heardDay = got.day || ""; heardLines = got.lines || [];
  // The days, from when to when, in the contents' dropdown (syncPick draws it over the select)
  const sel = $("heard-day");
  sel.innerHTML = (got.days || []).map((d) => {
    const name = fmtDay(new Date(`${d.day}T12:00:00`).getTime());
    const span = d.first ? ` · ${fmtClock(d.first * 1000)} ~ ${fmtClock(d.last * 1000)}` : "";
    return `<option value="${escapeHtml(d.day)}" data-short="${escapeHtml(name)}">${escapeHtml(name)} · ${d.n === 1 ? t("{n} sentence", { n: d.n }) : t("{n} sentences", { n: d.n })}${span}</option>`;
  }).join("");
  sel.value = heardDay;
  syncPick(sel);
  // With nothing kept there is no day to choose and nothing to copy: the sheet says why, and where the switch is
  const none = !heardLines.length;
  sel.closest(".heard-tools").hidden = none;
  $("heard-lines").hidden = none;
  $("heard-lines").innerHTML = heardLines.map((l) => `<li class="heard-line"><time>${heardClock(l.ts)}</time><span>${escapeHtml(l.text)}</span></li>`).join("");
  $("heard-lines").scrollTop = 0;
  $("heard-none").hidden = !none;
  $("heard-none").textContent = settingsValues.speech_keep ? t("Nothing kept yet") : t("Nothing kept · Keep what is heard is off in Solver settings");
}
function openHeard() {
  toggleMenu(false); exportMenu(false);
  comboClose(false);   // as for the keys' sheet
  heardOpener = document.activeElement;
  $("heard-overlay").hidden = false;
  $("heard-close").focus({ preventScroll: true });
  loadHeard();   // the newest day: left open overnight, the page still knows yesterday
}
function closeHeard() {
  if ($("heard-overlay").hidden) return;
  $("heard-overlay").hidden = true;
  comboClose(false);   // the day list stands on the page's body, and would stay behind
  // The keyboard goes back where it was, as from the keys' sheet
  const was = heardOpener;
  heardOpener = null;
  focusBack(was);
}
$("heard-close").onclick = closeHeard;
$("hear-kept").onclick = openHeard;
$("open-heard").onclick = openHeard;
$("heard-day").addEventListener("change", (e) => loadHeard(e.target.value));
$("heard-copy").onclick = () => copyText(heardLines.map((l) => `${heardClock(l.ts)} ${l.text}`).join("\n"), $("heard-copy"));
// One Markdown file: the day as its title, a line of the list a sentence
$("heard-save").onclick = () => {
  const out = [`# ${t("What was heard")} (${heardDay})`, "", ...heardLines.map((l) => `- ${heardClock(l.ts)} ${l.text.replace(/\s+/g, " ")}`), ""];
  saveFile(out.join("\n"), "text/markdown;charset=utf-8", `sidenote-heard-${heardDay}.md`);
  toast(heardLines.length === 1 ? t("Saved {n} sentence (Markdown)", { n: 1 }) : t("Saved {n} sentences (Markdown)", { n: heardLines.length }), null, "done");
};
$("heard").addEventListener("keydown", (e) => {   // the keyboard stays inside the sheet, as in the keys' sheet
  if (e.key !== "Tab") return;
  const f = [...$("heard").querySelectorAll(CAN_FOCUS)].filter((el) => el.offsetParent !== null);
  if (!f.length) return;
  const edge = e.shiftKey ? f[0] : f[f.length - 1];
  if (document.activeElement === edge) { (e.shiftKey ? f[f.length - 1] : f[0]).focus(); e.preventDefault(); }
});
// Closed by a press on the veil only when the press and the release are both on it (the settings sheet's rule)
$("heard-overlay").addEventListener("mousedown", (e) => { heardPress = e.target === $("heard-overlay"); });
$("heard-overlay").addEventListener("click", (e) => { if (heardPress && e.target === $("heard-overlay")) closeHeard(); heardPress = false; });
// ---------- The setup guide ----------
// Four steps in the settings sheet's look: what solves, the screen, the sound, and a sample problem to try. Each says how things
// stand as the cards say it (the same states, words and notes: localState and the others), what to do where something is
// missing, and holds the settings that step is about, drawn and pressed as in Solver settings (settingRow, onSheets). From the
// menu, and once by itself on a new install: the server says fresh while it has kept no answer, and this browser remembers it.
const SETUP_SEEN = "sidenote.setupSeen";
const SETUP_STEPS = [["solve", () => t("Solving")], ["screen", () => t("Screen")], ["sound", () => t("Sound")], ["try", () => t("Try it")]];
let setupStep = 0, setupOpener = null, setupPress = false;
let setupShot = null, setupShotAsked = false;   // the screen the screen step asked for: shown there, and no drawing starts on the screen card
let setupHeard = "";                            // the last words heard, on the sound step
let setupTry = null;                            // the sample problem: { state: "open" | "solving" | "done", at, id, answer, missed }
// How a step stands: ok when what it is about works, warn when something comes first, idle while not known or left as optional
function setupState(id) {
  const L = eng()?.local, C = eng()?.agent;
  if (wsState !== "up" || !eng()) return "idle";
  if (id === "solve") return (L?.present && L.on && L.ok) || (C?.present && C.ok && C.mode !== "off") ? "ok" : "warn";
  if (id === "screen") return screenState().s === "ok" ? "ok" : "warn";
  if (id === "sound") return audioState().s === "ok" ? "ok" : "idle";   // the sound is optional: off is no fault
  return setupTry?.state === "done" ? "ok" : "idle";
}
// One thing as its card says it: the name and the pill in its colour, then the card's facts and note (the agent's meters stay on
// its card)
const setupCard = (name, st) => `<div class="setup-state" data-state="${st.s}"><div class="setup-top"><b>${escapeHtml(name)}</b>`
  + `<span class="pill" data-state="${st.s}">${escapeHtml(st.pill)}</span></div>${cardHtml({ ...st, viz: "" })}</div>`;
// The rows of the settings named, as Solver settings draws them: those the server has
const setupRows = (...keys) => keys.map(settingItem).filter(Boolean).map(settingRow).join("");
const onMac = () => /Mac/i.test(navigator.userAgentData?.platform || navigator.platform || "");
// A step's pane, as parts each drawn again only when it changed: the screen step's ages change every second, and the whole
// pane drawn again took the picture away and back and shut an open list, which came back with its animation each second
function setupParts(id) {
  const L = eng()?.local, C = eng()?.agent, up = wsState === "up";
  if (id === "solve") {
    return [
      ["lede", `<p class="setup-lede">${t("What answers the problems: the model on this PC, the agent, or both. One of them is enough", { agent: AG() })}</p>`],
      ["cards", (L?.present ? setupCard(t("Local model"), localState()) : "") + (C?.present ? setupCard(AG(), agentState()) : "")],
      ["none", up && eng() && setupState("solve") === "warn"
        ? `<p class="setup-note warn">${t("Nothing can solve yet · get the local model, or sign in to the agent", { agent: AG() })}</p>` : ""],
      ["rows", setupRows("local_llm", "local_model", "agent_mode")],
    ];
  }
  if (id === "screen") {
    const shot = setupShot?.url
      ? `<figure class="setup-shot"><img src="${escapeHtml(setupShot.url)}" alt="${escapeHtml(t("The screen Sidenote receives"))}">`
        + `<figcaption>${setupShot.live ? t("Screen now") : t("Last screen {when}", { when: fmtAgo(serverNow() - setupShot.ts) })}</figcaption></figure>`
      : setupShot?.text ? `<p class="setup-note warn">${escapeHtml(setupShot.text)}</p>` : "";
    return [
      ["lede", `<p class="setup-lede">${t("What Sidenote reads: the screen the capture program sends. A problem on another monitor is not read")}</p>`],
      ["card", setupCard(t("Screen capture"), screenState())],
      ["act", `<div class="setup-act"><button type="button" class="btn sm" data-setup="shot"${up ? "" : " disabled"}>${t("Show the screen it receives")}</button></div>`],
      ["shot", shot],
      ["mac", onMac() ? `<p class="setup-note">${t("On a Mac, the capture program needs Screen Recording in System Settings, Privacy & Security")}</p>` : ""],
      ["rows", setupRows("monitor", "skip_windows")],
    ];
  }
  if (id === "sound") {
    return [
      ["lede", `<p class="setup-lede">${t("The sound is optional: with it, a problem asked aloud is solved too")}</p>`],
      ["card", setupCard(t("Sound capture"), audioState())],
      ["heard", `<p class="setup-heard" id="setup-heard">${escapeHtml(setupHeard || t("Nothing heard yet · play a video or say something"))}</p>`],
      ["mac", onMac() ? `<p class="setup-note">${t("On a Mac, the sound of other apps comes in through a loopback input such as BlackHole (the user guide)")}</p>` : ""],
      ["rows", setupRows("voice_auto", "speech_lang")],
    ];
  }
  // The sample problem: opened in a tab of its own, then how far it has come. Its answer as the notebook marks an answer, or,
  // with Practice keeping it back there, that it came and no more
  const tr = setupTry, ready = setupState("solve") === "ok" && setupState("screen") === "ok";
  const it = tr?.id != null ? items.get(tr.id) : null;
  const says = !tr ? ""
    : tr.state === "done" ? `<p class="setup-try done">${TICK_MARK}<span>${held(it) ? t("Answered · Practice keeps it back in the notebook")
      : tr.answer ? t("Answered: {answer}", { answer: `<mark class="key">${escapeHtml(tr.answer)}</mark>` }) : t("Answered")}</span>`
      + `<button type="button" class="btn sm" data-setup="see">${t("See the answer")}</button></p>`
    : `<p class="setup-try"><span class="spin"></span><span>${tr.state === "solving" ? t("Solving the sample problem")
      : tr.failed ? t("No answer came that time · open the sample problem again")
      : tr.missed ? t("No problem found on that screen · bring the sample tab to the front") : t("Waiting for it on the screen · keep the sample tab in view")}</span></p>`;
  return [
    ["lede", `<p class="setup-lede">${t("Opens a sample problem in a new tab. With it on the screen, Sidenote finds it and writes its answer in this notebook in some seconds")}</p>`],
    ["ready", ready || !up ? "" : `<p class="setup-note warn">${t("A solving engine and the screen come first")}</p>`],
    ["act", `<div class="setup-act"><button type="button" class="btn sm" data-setup="sample"${up ? "" : " disabled"}>${t("Open the sample problem")}</button></div>`],
    ["says", says],
  ];
}
function renderSetup() {
  const body = $("setup-body");
  if (!body || $("setup-overlay").hidden) return;
  if (sheetBusy()) { sheetDue = true; return; }   // drawn once the press or the typing is over (sheetSettle), as Solver settings is
  // The steps over the pane: a number, or the tick once the step works, in the colour of how it stands
  const nav = SETUP_STEPS.map(([id, name], i) => {
    const st = setupState(id);
    return `<button type="button" role="tab" class="setup-step" data-step="${i}" data-state="${st}" aria-selected="${i === setupStep}"`
      + ` tabindex="${i === setupStep ? 0 : -1}"><span class="n">${st === "ok" ? TICK_MARK : i + 1}</span><span class="name">${escapeHtml(name())}</span></button>`;
  }).join("");
  const steps = $("setup-steps");
  if (steps.dataset.html !== nav) {
    const at = steps.contains(document.activeElement) ? document.activeElement.dataset.step : null;
    steps.dataset.html = nav;
    steps.innerHTML = nav;
    if (at != null) steps.querySelector(`[data-step="${at}"]`)?.focus({ preventScroll: true });
  }
  // The pane: a holder for each part, made again only with another step; then each part drawn again only when it changed, the
  // keyboard put back on its row (by the keys renderSettings uses) and an open list opened again on the same choice
  const parts = setupParts(SETUP_STEPS[setupStep][0]);
  const shape = `${setupStep}:${parts.map(([k]) => k).join(",")}`, moved = body.dataset.step !== String(setupStep);
  if (body.dataset.shape !== shape) {
    if (comboOpen && body.contains(comboOpen.btn)) comboClose(false);
    body.innerHTML = parts.map(([k]) => `<div class="setup-part" data-part="${k}"></div>`).join("");
    body.dataset.shape = shape;
  }
  for (const [k, html] of parts) {
    const part = body.querySelector(`:scope > [data-part="${k}"]`);
    if (!part || part.dataset.html === html) continue;
    const was = part.contains(document.activeElement) ? { ...document.activeElement.dataset } : null;
    const reopen = comboOpen && part.contains(comboOpen.btn) ? { key: comboOpen.btn.dataset.set, at: comboAt() } : null;
    if (reopen) comboClose(false);
    part.dataset.html = html;
    part.innerHTML = html;
    fitWords(part);
    const sel = was?.set ? `[data-set="${CSS.escape(was.set)}"]` + (was.val !== undefined ? `[data-val="${CSS.escape(was.val)}"]`
      : was.multi !== undefined ? `[data-multi="${CSS.escape(was.multi)}"]` : "") : was?.setup ? `[data-setup="${CSS.escape(was.setup)}"]` : "";
    if (sel) (part.querySelector(sel) || (was.set ? part.querySelector(`[data-set="${CSS.escape(was.set)}"]`) : null))?.focus({ preventScroll: true });
    if (reopen) {
      const btn = part.querySelector(`.combo-btn[data-set="${CSS.escape(reopen.key)}"]:not([disabled])`);
      if (btn) { comboToggle(btn); if (reopen.at >= 0) comboMove(reopen.at); }
    }
  }
  if (moved) { body.dataset.step = String(setupStep); body.scrollTop = 0; body.classList.remove("enter"); void body.offsetWidth; body.classList.add("enter"); }
  $("setup-back").hidden = setupStep === 0;
  $("setup-next").textContent = setupStep === SETUP_STEPS.length - 1 ? t("Finish") : t("Next");
}
function openSetup(step) {
  toggleMenu(false); exportMenu(false); comboClose(false);
  // One sheet at a time: the guide holds some of the same settings, and two dialogs would each keep the keyboard
  if (!$("settings-overlay").hidden) closeSettings();
  closeKeys(); closeHeard();
  setupOpener = document.activeElement;
  if (typeof step === "number") setupStep = step;
  try { localStorage.setItem(SETUP_SEEN, "1"); } catch (_) {}
  $("setup-overlay").hidden = false;
  $("setup-body").dataset.shape = "";             // drawn afresh: the parts as they are now
  $("setup-body").dataset.step = "";
  $("setup-steps").dataset.html = "";
  renderSetup();
  $("setup-close").focus({ preventScroll: true });
}
function closeSetup() {
  if ($("setup-overlay").hidden) return;
  $("setup-overlay").hidden = true;
  comboClose(false);          // a list stands on the page's body, and would stay behind
  const was = setupOpener;
  setupOpener = null;
  focusBack(was);
}
// Once by itself, for a new install: not over a sheet already open, and not again in this browser. With nothing to remember it by
// (storage refused) it is not opened unasked, or it would come back with every page
function setupFirst() {
  let seen = true;
  try { seen = !!localStorage.getItem(SETUP_SEEN); } catch (_) {}
  if (seen || ["setup-overlay", "settings-overlay", "keys-overlay", "heard-overlay"].some((o) => !$(o).hidden)) return;
  openSetup(0);
}
function setupGo(i) {
  if (i < 0 || i >= SETUP_STEPS.length || i === setupStep) return;
  comboClose(false);
  setupStep = i;
  renderSetup();
}
$("open-setup").onclick = () => openSetup();
$("setup-close").onclick = closeSetup;
$("setup-back").onclick = () => setupGo(setupStep - 1);
$("setup-next").onclick = () => (setupStep === SETUP_STEPS.length - 1 ? closeSetup() : setupGo(setupStep + 1));
$("setup-steps").addEventListener("click", (e) => { const s = e.target.closest("[data-step]"); if (s) setupGo(+s.dataset.step); });
// The steps are tabs: the arrows walk them, Home and End go to the first and the last
$("setup-steps").addEventListener("keydown", (e) => {
  const s = e.target.closest("[data-step]");
  if (!s || !["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
  e.preventDefault(); e.stopPropagation();
  const n = SETUP_STEPS.length, i = +s.dataset.step;
  setupGo(e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : n - 1)) % n);
  $("setup-steps").querySelector(`[data-step="${setupStep}"]`)?.focus();
});
// The guide's own keys in its pane: the screen it receives, the sample problem, and the way to its answer
$("setup-body").addEventListener("click", (e) => {
  const k = e.target.closest("[data-setup]");
  if (!k || k.disabled) return;
  if (k.dataset.setup === "shot") { if (send({ type: "thumb" })) setupShotAsked = true; }
  else if (k.dataset.setup === "sample") {
    window.open(`sample.html?lang=${encodeURIComponent(LANG)}`, "_blank", "noopener");
    setupTry = { state: "open", at: serverNow(), id: null, answer: "", missed: false };
    renderSetup();
  } else if (k.dataset.setup === "see") {
    const id = setupTry?.id;
    closeSetup();
    if (id != null && items.has(id)) goTo(id);
  }
});
// The screen asked for, as the server sends it back: shown on the step with its age, or why there is none
function setupShotFrom(m) {
  setupShotAsked = false;
  if ($("setup-overlay").hidden) return;   // the guide closed while it was on its way: it goes to nobody, and starts no drawing
  setupShot = m.url ? { url: m.url, ts: typeof m.ts === "number" ? m.ts : serverNow(), live: m.live !== false } : { text: m.text || t("No screen received") };
  renderSetup();
}
// What is heard, on the sound step as it comes: its line alone, so the pane is not drawn again for every word
function setupHeardNow(text) {
  if (!text) return;
  setupHeard = String(text).trim().slice(-280);
  const el = $("setup-overlay").hidden ? null : document.getElementById("setup-heard");
  if (el) el.textContent = setupHeard;
}
// The sample problem on its way: the first answer to a screen started after it was opened, then that answer's line once done. A
// screen with no problem on it says so, and the step waits on
function setupSaw(m, done) {
  const tr = setupTry;
  if (!tr || tr.state === "done") return;
  if (!done) {
    if (tr.state !== "open" || ["ask", "retry", "continue", "voice"].includes(m.trigger)) return;
    if (typeof m.ts === "number" && m.ts < tr.at - 2) return;
    setupTry = { ...tr, state: "solving", id: idOf(m.id) };
  } else {
    if (tr.id !== idOf(m.id)) return;
    const it = items.get(idOf(m.id));   // onDone has kept it, or dropped one with nothing to solve
    setupTry = !it ? { ...tr, state: "open", id: null, missed: true, failed: false } : { ...tr, state: "done", answer: it.head?.answer || "" };
  }
  renderSetup();
}
// The sample's analysis that came to no answer: an error, called off, or the connection gone. The step waits again and says
// so, where it said "Solving" until the page was loaded again. One called off as a problem solved before (a repeat, the sample
// opened a second time) has that answer
function setupLost(m) {
  const tr = setupTry;
  if (!tr || tr.state !== "solving" || (m && tr.id !== idOf(m.id))) return;
  const of = m?.reason === "repeat" && m.of != null ? items.get(idOf(m.of)) : null;
  setupTry = of ? { ...tr, state: "done", id: of.id, answer: of.head?.answer || "" } : { ...tr, state: "open", id: null, failed: true, missed: false };
  renderSetup();
}
// Closed by a press on the veil only when the press and the release are both on it, and the keyboard stays inside while it is open
$("setup-overlay").addEventListener("mousedown", (e) => { setupPress = e.target === $("setup-overlay"); });
$("setup-overlay").addEventListener("click", (e) => { if (setupPress && e.target === $("setup-overlay")) closeSetup(); setupPress = false; });
$("setup").addEventListener("keydown", (e) => {
  if (e.key !== "Tab") return;
  const f = [...$("setup").querySelectorAll(CAN_FOCUS)].filter((el) => el.offsetParent !== null);
  if (!f.length) return;
  const edge = e.shiftKey ? f[0] : f[f.length - 1];
  if (document.activeElement === edge) { (e.shiftKey ? f[f.length - 1] : f[0]).focus(); e.preventDefault(); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!$("keys-overlay").hidden) { closeKeys(); return; }
    if (!$("heard-overlay").hidden) { closeHeard(); return; }
    if (!$("setup-overlay").hidden) { closeSetup(); return; }
    if (!$("settings-overlay").hidden) { closeSettings(); return; }
    if (!$("export-menu").hidden) { exportMenu(false, true); return; }
    if (drawing) { stopDrawing(); return; }
    const open = !$("menu").hidden; toggleMenu(false);
    if (open) $("more").focus({ preventScroll: true });
    else if (document.activeElement?.id === "ask") document.activeElement.blur();
    else if (document.activeElement?.id === "hist-q") {   // the letters are shortcuts again; the search goes on narrowing the contents
      e.preventDefault();                                 // a search field's own Escape empties it
      document.activeElement.blur();
    }
    return;
  }
  if (e.target.closest("input, textarea, select") || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  // The settings sheet is a dialog over the page: a key pressed in it (Space on a choice, an arrow on a
  // tab or a switch) is not a scroll of the notebook behind it.
  if (!$("settings-overlay").hidden) return;
  const key = shortcutKey(e);
  // The keys' sheet is one too: its own key closes it, and nothing else acts behind it
  if (!$("keys-overlay").hidden) { if (key === "?") { e.preventDefault(); closeKeys(); } return; }
  if (!$("heard-overlay").hidden) return;   // and so is the sheet of what was heard
  if (!$("setup-overlay").hidden) return;   // and the setup guide
  // A menu or a list open over the page keeps the letters to itself; ? still opens the keys' sheet
  // Drawing a region is its own mode, ended by Escape: nothing starts behind it
  if (SHORTCUTS[key] && !drawing && (key === "?" || ($("menu").hidden && $("export-menu").hidden && !comboOpen))) {
    e.preventDefault();                                    // the letter is not typed anywhere, and / opens no find bar
    if (!e.repeat || key === "j" || key === "k") SHORTCUTS[key]();   // held down, only j and k go on
    return;
  }
  if (["ArrowUp", "PageUp", "Home"].includes(e.key) || (e.key === " " && e.shiftKey)) stopFollowing();
  else if (["ArrowDown", "PageDown", "End", " "].includes(e.key) && !stick) readerMoved();
});
setInterval(() => {   // keep the "N s ago / N s so far" readouts current
  renderSignals();
  renderHear();        // the listening bars stop when sound stops arriving
  document.querySelectorAll("[data-elapsed]").forEach((el) => {
    const it = items.get(idOf(el.closest(".entry")?.dataset.id)); if (it && it.live) el.textContent = liveText(it);
  });
  document.querySelectorAll("[data-countdown]").forEach((el) => {
    const c = confirms.get(el.dataset.countdown); if (!c) return;
    const left = confirmLeft(c);
    el.textContent = left ? t("Skipped in {n} s", { n: left }) : t("Time ran out: not sent");
    if (!left) el.closest(".confirm")?.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  });
  fillPending();        // the seconds on the line that says a screen is being looked at
}, 1000);

function interruptLive() {   // the server went away mid-answer: those answers will never finish
  let changed = false;
  for (const it of [...items.values()]) {
    if (!it.live) continue;
    if (!it.shown) { items.delete(it.id); continue; }      // was only "looking at a new screen"
    Object.assign(it, { live: false, error: t("Stopped: connection lost"), hint: "interrupted" }); renderEntry(it); changed = true;
  }
  for (const turn of turns.values()) {
    if (!turn.live) continue;
    Object.assign(turn, { live: false, error: t("Stopped: connection lost"), hint: "interrupted" });
    const parent = items.get(turn.parent); if (parent) renderEntry(parent); changed = true;
  }
  renderTail();
  if (changed) { refold(); renderIndex(); }
}
let historyLoaded = false;
// The page is ready to be seen: the placeholders go and what is there rises in once (index.html, Opening the page)
let bootEnded = false;
function endBoot() {
  if (bootEnded) return;
  bootEnded = true;
  const root = document.documentElement;
  root.classList.remove("booting");
  root.classList.add("booted");
  setTimeout(() => root.classList.remove("booted"), 700);   // once: an answer redrawn later does not rise again
}
setTimeout(endBoot, 1800);                                  // no server, or a slow one: the page does not wait on it for long
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try { sock = new WebSocket(`${proto}://${location.host}/panel`); }
  catch (_) { wsState = "down"; renderAll(); setTimeout(connect, 3000); return; }   // e.g. opened as a file
  sock.onopen = () => {
    // The panel's language first, before anything else is sent: the server writes its words in it (notices, cards, settings)
    sock.send(JSON.stringify({ type: "ui_lang", lang: LANG }));
    wsState = "up"; renderAll();
    // What was answered before this page opened, or while the connection was down; tried again at the next connection if it failed
    const first = !historyLoaded, before = latestId();
    loadHistory({ limit: 40 }).then((ok) => {
      if (ok) historyLoaded = true;
      endBoot();
      if (ok && !first && latestId() !== before) { refold(); afterGrow(); }   // what was answered while it was down: followed, or offered, as any new answer
      if (ok && first && stick && thread.length) { toBottom(); updateView(); }   // a page opens on the newest answer, its screen in the rail; the welcome page, at its top
    });
  };
  sock.onclose = () => {   // a failed connection attempt closes too: only a connection that was up drops answers
    const was = wsState; wsState = "down"; capture.clients = null;
    hideGpu();
    setupLost(null);   // the sample being solved will not come
    if (was === "up") {
      interruptLive();
      failPendingRuns(t("Connection lost: no result · run it again"));
      confirms.clear(); drawing = null; dropPending();
      clearVoiceState();   // "solving what was heard" ended with the connection
      renderTail();   // the "Send to the agent?" card goes with the connection it belonged to
    }
    renderAll(); setTimeout(connect, 1500);
  };
  sock.onmessage = (ev) => { try { handle(JSON.parse(ev.data)); } catch (e) { console.error(e); } };
}

{
  const bar = document.querySelector("header.bar");
  const setBarH = () => document.documentElement.style.setProperty("--bar-h", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
  setBarH(); if (window.ResizeObserver) new ResizeObserver(setBarH).observe(bar);
}

// The bar shows a lower edge (a hairline and a soft shadow, index.html .bar.under) only while the thread is scrolled
// under it. At the top of the page it lies on the page colour with no edge, as part of the frame round the sheets.
{
  const bar = document.querySelector("header.bar");
  const under = () => bar.classList.toggle("under", window.scrollY > 1);
  under();
  addEventListener("scroll", under, { passive: true });
}

// The question box has two shapes (index.html, .composer). It floats, narrower and with a shadow, only while its
// sticky place is what holds it on screen: the end of the thread, where it belongs, is still below the window.
// Where it rests at that end (nothing to scroll, or scrolled to the bottom) it takes the thread's width. Measured
// from the column it ends: sticky moves the box without moving the column, so the column's lower edge, less the
// box's own bottom margin, is where the box stands when it rests.
{
  const form = document.getElementById("askform"), stage = document.getElementById("stage");
  const dock = () => {
    if (!form || !stage) return;
    const cs = getComputedStyle(form);
    const rest = stage.getBoundingClientRect().bottom - (parseFloat(cs.marginBottom) || 0);   // its lower edge at rest
    const hold = window.innerHeight - (parseFloat(cs.bottom) || 0);                           // where sticky holds it
    const floating = rest > hold + 1;   // a pixel of slack, so rounding at the very bottom does not flicker it
    if (form.classList.contains("floating") !== floating) form.classList.toggle("floating", floating);
  };
  dock();
  addEventListener("scroll", dock, { passive: true });
  addEventListener("resize", dock);
  // The thread grows as an answer streams in, which moves the column's end without a scroll; an alert appearing or
  // going above it moves the whole column without resizing it (the box kept its old shape, 4 px over the sheet).
  if (window.ResizeObserver) { const ro = new ResizeObserver(dock); ro.observe(stage); ro.observe($("alerts")); }
}

// The right column shows everything it holds at every size of window: nothing folds, shrinks or hides to fit the window.
// While all of it fits under the bar it follows the view down a long thread. Taller than the window it follows too (drift):
// going down it moves with the page until its foot is in the window and stays there, going up it moves back until its head
// is one gap under the bar and stays there, so every card is reached by scrolling toward it and the column beside a long
// thread is never left empty. It never scrolls inside itself; the contents' list alone keeps a scroll of its own.
{
  const rail = document.querySelector(".rail");
  const bar = document.querySelector("header.bar");
  const list = document.getElementById("history");
  const alerts = document.getElementById("alerts");
  const stage = document.getElementById("stage");
  // What a short window used to take away, in turn, before everything was shown at every size: none is set now, and one
  // left on the column from before is taken off
  const RAIL_STEPS = ["tight", "no-cap", "no-gpu-foot", "no-bars", "no-bars-key", "no-usage-sub", "no-usage", "no-hear", "no-gpu", "no-scales", "no-src-facts", "snug", "no-hist-filters", "no-usage-err", "no-shot-head", "tighter", "tightest"];
  // The contents' list shows this many lines (its rows and the days' tabs over them), whole, and scrolls inside its card for the rest
  const LIST_LINES = 9;
  // The column's two groups of cards: the controls, and the screen with the contents (index.html). On a wide window they stand side by side
  const [ctl, see] = rail ? [...rail.querySelectorAll(":scope > .rail-col")] : [];
  const sideBySide = () => !!(ctl && see) && getComputedStyle(ctl).display !== "contents";   // the styles decide, by the window's width and the design
  // The drifting column's top in the window (null while it fits or stands in the page), the scroll it was set at, and how high
  // and low it may stand: its head one gap under the bar, its foot level with the question box's
  let driftAt = null, driftY = 0, driftLo = 0, driftHi = 0;
  // Moves it with the page as far as its head or foot allows. True when the end of its column held it higher than that
  const drift = () => {
    if (driftAt == null) return false;
    const want = Math.min(driftHi, Math.max(driftLo, driftAt - (scrollY - driftY)));
    driftY = scrollY;
    rail.style.setProperty("--drift-top", `${Math.round(want)}px`);
    // The page's two ends hold it where the sticky top cannot place it: near the top its own place in the page, near the
    // foot the end of its column. It goes on from where it stands, or the next scroll would first make up the difference
    const real = rail.getBoundingClientRect().top;
    driftAt = Math.abs(real - want) > 0.5 ? Math.min(driftHi, Math.max(driftLo, real)) : want;
    return real < want - 0.5;
  };
  const driftOff = () => { driftAt = null; rail.style.removeProperty("--drift-top"); };
  // in use (typed into, pointed at): it is not moved by itself while a hand is on it
  const inUse = () => rail.contains(document.activeElement) || rail.matches(":hover");
  // Held up by the page's end after a move the panel made itself (following the newest answer) or a change of its cards:
  // its foot shows whole rather than cut at the window's edge. Never on a scroll by hand, where it would jump
  const footWhole = () => { if (!inUse()) { driftAt = driftLo; drift(); } };
  addEventListener("scroll", () => { if (drift() && Date.now() < autoUntil) footWhole(); }, { passive: true });
  const fitRail = (e) => {
    if (!rail) return;
    // The list growing and shrinking under the words typed in its search is not measured again; a window resized is
    const searching = document.activeElement?.id === "hist-q" || !!document.getElementById("hist-q")?.value.trim();
    if (!(e instanceof Event) && searching) return;
    // One column (index.html: 1000 px and narrower) puts the rail under the thread, where it does not follow: the
    // index is then shown whole, not as a box inside a page that scrolls anyway.
    if (oneColumn.matches) {
      if (alerts) document.documentElement.style.setProperty("--alerts-h", `${Math.ceil(alerts.getBoundingClientRect().height)}px`);
      if (list && list.style.maxHeight) list.style.maxHeight = "";
      if (rail.style.top) rail.style.top = "";
      rail.classList.remove("stick", "drift", ...RAIL_STEPS);   // narrowed from two columns: it stands in the page
      driftOff();
      list?.style.removeProperty("--h-air");
      rail.style.maxHeight = ""; rail.style.overflow = "";  // and nothing a short window asked of it before stays
      document.documentElement.style.removeProperty("--shot-h");
      return;
    }
    // Under the bar at one gap, whatever else is on the page: the bands stand over the page's column, not over this one
    const bands = alerts ? alerts.getBoundingClientRect().height : 0;
    const root = document.documentElement;
    root.style.setProperty("--alerts-h", `${Math.ceil(bands)}px`);
    const top = (bar ? bar.getBoundingClientRect().height : 52) + 18;
    const railBox = rail.getBoundingClientRect();   // the wash behind the column (index.html, body::before) stands where the column stands
    root.style.setProperty("--rail-x", `${Math.round(railBox.left)}px`);
    root.style.setProperty("--rail-w", `${Math.round(railBox.width)}px`);
    // Sticky stops at the end of its grid cell, which ends above the layout's bottom padding. A foot held lower than that was pushed
    // up by the difference at the very end of the page, a pixel or two, so this is the lowest it ever stands.
    const footGap = Math.ceil(parseFloat(getComputedStyle(rail.parentElement).paddingBottom) || 16) + 2;   // the column's foot level with the question box's beside it
    const room = window.innerHeight - top - footGap;
    root.style.setProperty("--rail-top", `${Math.round(top)}px`);
    root.style.setProperty("--rail-room", `${Math.floor(room)}px`);
    // Everything shows: no step of before is left on, the picture keeps its own size, and nothing caps the column
    rail.classList.remove(...RAIL_STEPS);
    rail.style.maxHeight = ""; rail.style.overflow = "";
    fitFacts(rail);
    root.style.removeProperty("--shot-h");
    root.style.removeProperty("--bars-h");
    list?.style.removeProperty("--h-air");
    // The contents' list: its first lines whole, measured from the list's own top however far it has been scrolled,
    // and given back the place it was scrolled to
    const listAt = list ? list.scrollTop : 0;
    if (list) {
      list.style.maxHeight = "";
      const base = list.getBoundingClientRect().top, ends = [...list.children].map((c) => c.getBoundingClientRect().bottom - base).filter((b) => b > 0);
      if (ends.length > LIST_LINES) list.style.maxHeight = `${Math.ceil(ends[LIST_LINES - 1])}px`;
    }
    // Follows the view while it fits under the bar, its foot inside the window; taller, it drifts (above). Side by side,
    // each group is measured on its own, and the taller of the two decides
    const two = sideBySide();
    const height = two ? Math.max(ctl.getBoundingClientRect().height, see.getBoundingClientRect().height) : rail.getBoundingClientRect().height;
    const tall = height > room + 0.5;
    const shownAt = rail.getBoundingClientRect().top;   // where it stands now, before the class below moves it
    rail.classList.toggle("stick", !tall);
    rail.classList.toggle("drift", tall);
    if (tall) {
      const atFoot = driftAt != null && driftAt <= driftLo + 0.5;      // held with its foot in the window, before this measure
      driftHi = top;
      driftLo = Math.min(top, window.innerHeight - footGap - height);
      // It starts drifting from where it is seen; with the page already scrolled past the column's own place (it grew while
      // the page followed the newest answer), from its foot, where it would stand had it drifted down with the page
      if (driftAt == null) { driftAt = stage && stage.getBoundingClientRect().top < top - 0.5 ? driftLo : shownAt; driftY = scrollY; }
      else if (atFoot && !inUse()) driftAt = driftLo;                   // grown or shrunk there, it keeps its foot in view
      if (drift()) footWhole();                                         // inside the bounds of this window and height
    } else if (driftAt != null) driftOff();
    // Following, the room the column leaves under it goes to the contents' list, in whole lines, and what is left under the last one into
    // the lines it shows, a little more air in each: a tall window shows more of the list, not empty space, and the column's foot stands
    // level with the question box's
    const leftUnder = () => room - (two ? see.getBoundingClientRect().height : rail.getBoundingClientRect().height);
    if (!tall && list && leftUnder() >= 1 && list.scrollHeight > list.clientHeight + 1) {
      const top = list.getBoundingClientRect().top - list.scrollTop, now = list.getBoundingClientRect().height, more = now + leftUnder();
      const ends = [...list.children].map((c) => c.getBoundingClientRect().bottom - top).filter((b) => b > 0 && b <= more + 0.5);
      if (ends.length) list.style.maxHeight = `${Math.ceil(ends[ends.length - 1])}px`;
      const rest = leftUnder();
      if (rest >= 1 && list.scrollHeight > list.clientHeight + 1) {
        const box = list.getBoundingClientRect();
        const shown = [...list.querySelectorAll(".h")].filter((x) => { const r = x.getBoundingClientRect(); return r.top >= box.top - 1 && r.bottom <= box.bottom + 1; }).length;
        if (shown) {
          list.style.setProperty("--h-air", `${(rest - 0.5) / shown / 2}px`);
          list.style.maxHeight = `${box.height + rest - 0.5}px`;
        }
      }
    }
    // Side by side and following, height the controls do not need goes to the answers' bars, the column's chart of how long each
    // answer took: at 20 px they were too low to read, and the live chart looked gone.
    // Up to 64 px, the same for both engines. No card is stretched round empty room
    if (two && !tall) {
      const bars = [...ctl.querySelectorAll(".usage .bars")].filter((b) => b.getBoundingClientRect().height > 0);
      const spare = room - ctl.getBoundingClientRect().height;
      if (bars.length && spare >= 2 * bars.length) {
        const now = bars[0].getBoundingClientRect().height;
        root.style.setProperty("--bars-h", `${Math.floor(Math.min(64, now + (spare - 1) / bars.length))}px`);
      }
    }
    if (list) list.scrollTop = listAt <= 3 ? 0 : listAt;   // a few pixels of scroll are no place chosen on purpose, and show a sliver of the next row
    const said = document.getElementById("hear-text");
    if (said) said.scrollTop = said.scrollHeight;   // the latest words are the ones to see
  };
  const oneColumn = window.matchMedia("(max-width: 1000px)");   // the layout's one-column width (index.html)
  fitRail();
  addEventListener("resize", fitRail);
  let pressing = false;
  addEventListener("pointerdown", () => { pressing = true; }, true);
  addEventListener("pointerup", () => { pressing = false; }, true);
  addEventListener("pointercancel", () => { pressing = false; }, true);
  document.getElementById("hist-q")?.addEventListener("blur", () => {
    if (document.getElementById("hist-q").value.trim()) return;   // the search still stands: what is pressed stays where it is, and a list opened from it with it
    if (pressing) addEventListener("pointerup", () => setTimeout(fitRail, 40), { once: true });
    else fitRail();
  });
  refitRail = () => fitRail(new Event("refit"));
  oneColumn.addEventListener?.("change", fitRail);
  window.matchMedia("(min-width: 2400px)").addEventListener?.("change", fitRail);   // the groups go side by side or back under each other (index.html)
  // the cards grow and shrink as answers arrive, a screen is drawn, the index fills: the observer
  // catches all of that without every renderer having to remember to call this
  // Each card, not the rail: the rail's own box stops changing once its height limit holds it
  if (window.ResizeObserver && rail) {
    const seen = new ResizeObserver(fitRail);
    rail.querySelectorAll(".card").forEach((c) => seen.observe(c));   // the cards, inside their two groups
    if (stage) seen.observe(stage);                 // the thread growing past the rail is what starts the following
  }
  if (window.ResizeObserver && alerts) new ResizeObserver(fitRail).observe(alerts);
}

// ---------- preview (?demo=1): sample answers without a server, for screenshots ----------
function runDemo() {
  demo = true; wsState = "up"; endBoot();
  const THUMB = "data:image/svg+xml;utf8," + encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'><rect width='640' height='360' fill='#20242c'/>` +
    `<rect x='14' y='16' width='300' height='328' rx='6' fill='#2b3039'/><rect x='330' y='16' width='296' height='328' rx='6' fill='#ffffff'/>` +
    `<text x='346' y='48' fill='#333' font-family='sans-serif' font-size='15' font-weight='700'>네트워크 모의고사 12번</text>` +
    [0, 1, 2, 3, 4].map((i) => `<rect x='346' y='${70 + i * 26}' width='${250 - i * 18}' height='9' rx='3' fill='#cfd3dc'/>`).join("") +
    [0, 1, 2, 3, 4, 5, 6].map((i) => `<rect x='30' y='${40 + i * 22}' width='${200 - (i % 3) * 40}' height='8' rx='3' fill='#4a5160'/>`).join("") + `</svg>`);
  handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: true,
    engines: { local: { present: true, on: true, ok: true, method: "local", model: "sidenote-gemma4:26b", loaded: { model: "sidenote-gemma4:26b", vram_gb: 21.9 } },
      agent: { present: true, ok: true, method: "claude.ai", mode: "hard", effective: "hard", payload: "crop" }, search: { present: true, on: true }, ready: true } });
  handle({ type: "capture", clients: 1, last_frame: Date.now() / 1000 - 2, last_audio: Date.now() / 1000 - 1, screen_on: true, audio_on: true,
    caps: { screen: true, audio: true, audio_device: "스피커 (Realtek Audio)", monitor: 1 } });
  for (let i = 0; i < 40; i++) handle({ type: "gpu", util: Math.round(30 + 26 * Math.sin(i / 3.2) + (i % 7) * 3), used: 7900 + i * 12, total: 23028, temp: 63, power: 118 });
  handle({ type: "usage", answers: 3, tokens_in: 33401, tokens_out: 560, cost_usd: 0.0269, errors: 0, elapsed_p50: 3.2, first_token_p50: 1.6 });
  handle({ type: "transcript", text: "다음 문제입니다. 스택과 큐의 차이를 설명해 보세요.", lang: "ko" });
  const steps = [];
  const stream = (id, text, done) => {
    for (const tok of (text.match(/\S+\s*|\n/g) || [text])) steps.push(() => handle({ type: "delta", id, text: tok }));
    steps.push(() => handle(Object.assign({ type: "analysis_done", id, text }, done)));
  };
  steps.push(() => handle({ type: "analysis_start", id: 11, thumb: THUMB, transcript: "", trigger: "screen" }));
  stream(11, "TYPE: short\nANSWER: ACID\nREGION: 52 6 97 30\n트랜잭션이 안전하게 수행되기 위한 네 성질: 원자성(Atomicity), 일관성(Consistency), 고립성(Isolation), 지속성(Durability).",
    { usage: { input_tokens: 980, output_tokens: 60, cache_read: 0, cache_write: 0 }, cost_usd: null, model: "sidenote-gemma4:26b", engine: "local", sent: [], elapsed: 1.2, region: [0.53, 0.07, 0.96, 0.3] });
  steps.push(() => handle({ type: "analysis_start", id: 12, thumb: THUMB, transcript: "", trigger: "screen" }));
  stream(12, "TYPE: algorithm\nANSWER: 해시맵에 본 값을 담으며 한 번 순회, 시간 $O(n)$\nREGION: 52 6 97 52\n" +
    "지금까지 본 값을 해시맵에 담고 `target - x` 가 이미 있으면 두 인덱스를 돌려준다.\n\n```python\ndef two_sum(nums, target):\n    seen = {}\n    for i, x in enumerate(nums):\n        if target - x in seen:\n            return [seen[target - x], i]\n        seen[x] = i\n```",
    { usage: { input_tokens: 2, output_tokens: 140, cache_read: 8600, cache_write: 1300 }, cost_usd: 0.0061, model: "claude-code", engine: "agent",
      sent: [{ to: "agent", what: "문제 부분 화면 1180x900" }], elapsed: 3.6, region: [0.53, 0.07, 0.96, 0.51] });
  steps.push(() => handle({ type: "check", id: 12, passed: 2, total: 2, how: "function", fails: [] }));
  steps.push(() => handle({ type: "analysis_start", id: 13, thumb: null, transcript: "다음 문제입니다. 프로세스와 스레드의 차이를 한 문장으로 말해 보세요.", trigger: "voice" }));
  stream(13, "TYPE: short\nANSWER: 프로세스는 메모리를 따로 쓰고, 스레드는 한 프로세스 안에서 메모리를 함께 쓴다.\n" +
    "그래서 스레드끼리는 통신이 빠르지만 공유 데이터에 동기화가 필요하다.",
    { usage: { input_tokens: 2, output_tokens: 70, cache_read: 7000, cache_write: 900 }, cost_usd: 0.0039, model: "claude-code", elapsed: 2.4 });
  // a schedule, with the Gantt chart a ```chart block draws (drawPictures)
  steps.push(() => handle({ type: "analysis_start", id: 4, thumb: THUMB, transcript: "", trigger: "screen" }));
  stream(4, "TYPE: math\nANSWER: 평균 대기 시간 $10/3 \\approx 3.33$\nREGION: 52 6 97 52\n" +
    "## 실행 순서\n\n**1. 타임 퀀텀 2로 차례를 돈다**\n\n" +
    "```chart\n{\"type\":\"gantt\",\"title\":\"Round Robin (q = 2)\",\"unit\":\"ms\",\"tasks\":[{\"name\":\"P1\",\"start\":0,\"end\":2},{\"name\":\"P2\",\"start\":2,\"end\":4},{\"name\":\"P3\",\"start\":4,\"end\":5},{\"name\":\"P1\",\"start\":5,\"end\":7},{\"name\":\"P2\",\"start\":7,\"end\":8},{\"name\":\"P1\",\"start\":8,\"end\":9}]}\n```\n\n" +
    "## 대기 시간\n\n| 프로세스 | 완료 | 대기 |\n|---|---|---|\n| P1 | 9 | 4 |\n| P2 | 8 | 4 |\n| P3 | 5 | 2 |\n\n" +
    "평균 대기 시간은 **(4 + 4 + 2) / 3 ≈ 3.33** 이다.",
    { usage: { input_tokens: 2, output_tokens: 230, cache_read: 9100, cache_write: 1200 }, cost_usd: 0.0094, model: "claude-code", elapsed: 4.4, region: [0.53, 0.07, 0.96, 0.51] });
  steps.push(() => handle({ type: "analysis_start", id: 1, thumb: THUMB, transcript: "", trigger: "screen" }));
  stream(1, "TYPE: essay\nANSWER: 스택은 LIFO, 큐는 FIFO로 꺼내는 순서가 다르다.\nREGION: 52 6 97 52\n" +
    "스택은 마지막에 넣은 데이터를 먼저 꺼내는 **LIFO** 구조로 함수 호출 스택, 되돌리기(undo) 등에 쓰인다. " +
    "큐는 먼저 넣은 데이터를 먼저 꺼내는 **FIFO** 구조로 작업 대기열, BFS 등에 쓰인다. 두 구조 모두 삽입과 삭제가 $O(1)$ 이다.",
    { usage: { input_tokens: 2, output_tokens: 160, cache_read: 9200, cache_write: 1400 }, cost_usd: 0.0071, model: "claude-code", elapsed: 3.2, region: [0.53, 0.07, 0.96, 0.51] });
  steps.push(() => handle({ type: "analysis_start", id: 2, thumb: THUMB, transcript: "", trigger: "screen" }));
  stream(2, "TYPE: mcq\nANSWER: ④\nREGION: 52 6 97 52\n" +
    "**문제**: TCP에 대한 설명으로 옳지 않은 것은?\n\n" +
    "| 보기 | 판단 | 이유 |\n|---|---|---|\n| ① 연결 지향 | 맞음 | 3-way handshake로 연결을 맺는다 |\n" +
    "| ② 흐름 제어와 혼잡 제어 | 맞음 | 슬라이딩 윈도와 혼잡 윈도를 쓴다 |\n| ③ 순서 보장 | 맞음 | 시퀀스 번호로 재정렬한다 |\n" +
    "| ④ 브로드캐스트 지원 | **틀림** | 1:1 연결이라 브로드캐스트는 UDP에서 쓴다 |",
    { usage: { input_tokens: 2, output_tokens: 210, cache_read: 9784, cache_write: 1682 }, cost_usd: 0.0112, model: "claude-code", elapsed: 4.1, region: [0.53, 0.07, 0.96, 0.51] });
  steps.push(() => handle({ type: "analysis_start", id: 3, thumb: null, transcript: "UDP로 신뢰성 있게 보내려면 어떻게 해?", trigger: "ask" }));
  stream(3, "TYPE: followup\nANSWER: 응용 계층에서 순서 번호, ACK, 재전송을 직접 구현하거나 QUIC을 쓴다.\n" +
    "UDP 자체에는 순서 보장과 재전송이 없으므로 위 계층에서 보완한다.\n\n```python\nseq = 0\nfor chunk in chunks:\n    send(seq, chunk)\n    wait_ack(seq, timeout=0.2)  # 없으면 다시 보낸다\n    seq += 1\n```",
    { usage: { input_tokens: 2, output_tokens: 190, cache_read: 10119, cache_write: 900 }, cost_usd: 0.0086, model: "claude-code", elapsed: 2.8 });
  let t = 150;
  for (const s of steps) { setTimeout(s, t); t += 8; }
}

setTheme(themeNow());
setMotion(motionPicked());
document.querySelectorAll("#lang-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === pickedLang())));
syncPracticeSeg();
setSkin(document.documentElement.dataset.skin || "classic");
renderThread();
renderAll();
loadMarkdownExtensions();
if (new URLSearchParams(location.search).has("demo")) runDemo();
else connect();
