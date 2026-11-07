// The sample problem in the language the panel asked for (sample.html?lang=ko), else the browser's. Run in the page's head, before
// its body is drawn, so the other language never shows
(() => {
  let lang = "";
  try { lang = new URLSearchParams(location.search).get("lang") || ""; } catch (_) {}   // an address it cannot read: the browser's
  if (!["ko", "en"].includes(lang)) lang = /^ko\b/i.test(navigator.language || "") ? "ko" : "en";
  document.documentElement.lang = lang;                                   // sample.html shows the main of this language
  document.title = lang === "ko" ? "예제 문제" : "Sample problem";        // the tab says what it is in that language too
})();
