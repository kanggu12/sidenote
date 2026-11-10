// The panel's words in the browser's language. The code is written in English; every other language is a table from
// the English to its own words (panel/i18n/<lang>.js, which adds itself to CATALOGS). English is the default, and
// Korean is used when the browser lists Korean first. The menu's Language picks one by hand and this browser keeps it;
// `?lang=en` or `?lang=ko` in the address picks one for that page alone.
//
//   t("Pause")                               the word itself, or its translation
//   t("{n} answers", { n: 3 })               placeholders by name
//   a Korean table entry may write "{name|이/가}": the word, then 이 after a final consonant or 가 after a vowel
//
// To add a language: copy panel/i18n/ko.js to panel/i18n/<code>.js, translate the right-hand sides, load it in
// index.html after this file, and add the code to SUPPORTED below. The keys must stay the English as written in the code.

const SUPPORTED = ["en", "ko"];
const CATALOGS = {};

// The browser's own language among those supported: Korean when it lists Korean first, else English
function browserLang() {
  const first = ((navigator.languages && navigator.languages[0]) || navigator.language || "en").toLowerCase();
  return first.startsWith("ko") ? "ko" : "en";
}
// The language picked in the menu, kept in this browser; "auto" when none is: the browser's
function pickedLang() {
  try { const v = localStorage.getItem("sidenote-lang"); return SUPPORTED.includes(v) ? v : "auto"; } catch (_) { return "auto"; }
}
const LANG = (() => {
  let asked = null;
  try { asked = new URLSearchParams(location.search).get("lang"); } catch (_) {}
  if (SUPPORTED.includes(asked)) return asked;
  const picked = pickedLang();
  return picked === "auto" ? browserLang() : picked;
})();
document.documentElement.lang = LANG;

// The Korean particle after a word, by whether its last letter ends in a consonant: "{name|이/가}". Hangul only: after
// a Latin word or a number the first of the two is used. A bracketed aside at the end is passed over, and so is the
// closing quote of a word given quoted ('{name}' then the particle goes by the word inside the quotes).
function particle(word, pair) {
  const [withFinal, withoutFinal] = pair.split("/");
  // markup round a value (a setting's name in <b>) is not its last letter: ">" chose "을" after "붙이기"
  const last = String(word || "").replace(/<[^>]*>/g, "").replace(/['"\u2019\u201d]$/, "").replace(/\s*\([^()]*\)\s*$/, "").trim().slice(-1);
  const code = last.charCodeAt(0);
  if (!last || code < 0xac00 || code > 0xd7a3) return withFinal;
  return (code - 0xac00) % 28 ? withFinal : withoutFinal;
}

function t(text, vars) {
  const table = LANG === "en" ? null : CATALOGS[LANG];
  let out = (table && table[text]) || text;
  if (vars) {
    out = out.replace(/\{(\w+)(?:\|([^}]+))?\}/g, (whole, key, pair) => {
      if (!(key in vars)) return whole;
      const value = String(vars[key]);
      return pair ? value + particle(value, pair) : value;
    });
  }
  return out;
}

// The static words in index.html: an element with data-t has its English text translated, and data-t-title,
// data-t-aria, data-t-placeholder and data-t-alt do the same for those attributes. Run once, before the first paint.
// The text is the element's own words: an element that also holds a mark (an icon, a dot) keeps it, and only its
// first stretch of text beside the mark is translated. A data-t with a value names the key to translate by, for a word
// another language says otherwise in that one place: <button data-t="Practice: Off">Off</button> is 끔 in Korean, where
// "Off" alone is the state word 꺼 둠.
function translateDom(root = document) {
  if (LANG === "en") return;
  for (const el of root.querySelectorAll("[data-t]")) {
    const node = [...el.childNodes].find((n) => n.nodeType === Node.TEXT_NODE && n.nodeValue.trim());
    if (node) node.nodeValue = node.nodeValue.replace(node.nodeValue.trim(), () => t(el.dataset.t || node.nodeValue.trim()));
  }
  for (const [attr, data] of [["title", "data-t-title"], ["aria-label", "data-t-aria"], ["placeholder", "data-t-placeholder"], ["alt", "data-t-alt"]]) {
    for (const el of root.querySelectorAll(`[${data}]`)) el.setAttribute(attr, t(el.getAttribute(attr) || ""));
  }
}
