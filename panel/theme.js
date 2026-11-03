// Theme before first paint: dark unless the viewer picked another, since this panel sits beside an
// editor and a terminal all day. "Auto" follows the system and is a choice like the other two, kept in
// storage as "auto"; storage may be unavailable, and then it is dark.
// A file of its own, not inline: the panel's Content-Security-Policy allows scripts from the server only.
// Auto is written out as what the system says now, so every rule that names a theme holds for it too: left unset, a light
// system got the dark keys and dropdowns with dark ink on them.
const AUTO_THEME = window.matchMedia("(prefers-color-scheme: light)");
const autoTheme = () => (AUTO_THEME.matches ? "light" : "dark");
try {
  const t = localStorage.getItem("sidenote-theme");
  document.documentElement.dataset.theme = t === "light" || t === "dark" ? t : t === "auto" ? autoTheme() : "dark";
} catch (_) { document.documentElement.dataset.theme = "dark"; }
AUTO_THEME.addEventListener?.("change", () => {   // the system turned over while the panel was open
  try { if (localStorage.getItem("sidenote-theme") === "auto") document.documentElement.dataset.theme = autoTheme(); } catch (_) {}
});
// One design, Classic. New (Beta) is switched off: the menu no longer offers it and a "new" stored by an
// earlier pick is not read, so everyone sees the same page. Its rules stay in new.css, which is not loaded.
document.documentElement.dataset.skin = "classic";
// Motion (the menu's): on unless it is turned off or set to follow the system. On by default, though the system asks for less: with
// Windows' animation effects off, every motion of the panel was off, and it seemed to be missing
const LESS_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");
const motionPicked = () => { try { return localStorage.getItem("sidenote-motion") || "on"; } catch (_) { return "on"; } };
const motionNow = () => { const m = motionPicked(); return m === "off" || (m === "system" && LESS_MOTION.matches) ? "off" : "on"; };
document.documentElement.dataset.motion = motionNow();
LESS_MOTION.addEventListener?.("change", () => { document.documentElement.dataset.motion = motionNow(); });   // the system changed while open
// Until the answers kept are in, the page shows placeholders: it used to flash the welcome page on every reload (app.js, endBoot)
document.documentElement.classList.add("booting");
