"""Answers marked right or wrong in the panel: Right and Wrong on an answer's head, what pressing them sends and what the server's
word draws on every panel, the marks the history brings and a reconnect brings back, the answers they are not on (one being
written, a failure, a stopped one, one Practice keeps back), the line Export writes for them, and the head kept on one line at
390, 1366 and 1920 px, and on the phones of 375 and 430, with the two keys in it.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_verdict.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

The page is a copy of panel/ over the stand-in server of panel_harness.py: its /history gives the rows the checks set, and its
socket is the checks' own.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row, thumb  # noqa: E402

T = h.Tally()
check = T.check
EN = "en-US"

# The state of one entry's two keys, read off the page: each key's place among the head's keys, pressed or not, its word, tooltip
# and mark, the colour its mark is drawn in and whether it stands pressed in (the theme's sunken shadow, where a key not pressed
# casts the raised one); the colours of what worked and what failed as this page's theme computes them
KEYS = """(id) => { const e = entryEl(id), tools = e?.querySelector(':scope > .row.head .tools');
  const names = tools ? [...tools.children].map((b) => Object.keys(b.dataset)[0]) : [];
  const probe = (prop, v) => { const p = document.createElement('i'); p.style[prop] = `var(${v})`; document.body.append(p);
    const c = getComputedStyle(p)[prop]; p.remove(); return c; };
  const sunken = probe('boxShadow', '--sunken');
  const one = (v) => { const k = tools?.querySelector(`:scope > [data-${v}]`); if (!k) return {}; const svg = k.querySelector('svg');
    return { pressed: k.getAttribute('aria-pressed'), word: k.textContent.trim(), title: k.title, path: svg?.innerHTML || '',
             stroke: getComputedStyle(svg).stroke, ink: getComputedStyle(k).color, inset: getComputedStyle(k).boxShadow === sunken }; };
  return { names, right: one('right'), wrong: one('wrong'), ok: probe('color', '--ok'), bad: probe('color', '--bad') }; }"""
SENT = "() => (window.__sent || []).filter((m) => m && m.type === 'verdict')"
TICK, CROSS = 'd="M4.5 12.5l5 5L19.5 7"', 'd="M6.5 6.5l11 11M17.5 6.5l-11 11"'


def say(p: Page, i: int, v) -> None:
    """The server's word that answer i is marked v ("right", "wrong" or None), as every panel gets it. The stand-in server keeps it
    first, as server/history.py does, so what the page fetches after it agrees."""
    p.stand.rows = [{**r, "verdict": v} if r["id"] == i else r for r in p.stand.rows]
    p.send({"type": "verdict", "id": i, "verdict": v})
    p.wait(120)


def press(p: Page, i: int, v: str) -> None:
    """A click on answer i's Right or Wrong key, when it has one."""
    key = p.page.locator(f'.entry[data-id="{i}"] > .row.head [data-{v}]')
    if key.count():
        key.click()


def state(p: Page, i: int) -> tuple:
    """Which of answer i's two keys is pressed: ("true"/"false" of Right, of Wrong), None for a key it does not have."""
    k = p.js(KEYS, i)
    return (k["right"].get("pressed"), k["wrong"].get("pressed"))


def menu_pick(p: Page, which: str) -> None:
    """Practice on or off, from the gear menu as by hand."""
    p.page.click("#more")
    p.page.click(f"#practice-seg [data-practice='{which}']")
    p.page.keyboard.press("Escape")
    p.wait(150)


def group_keys(br, s):
    if not T.group("the keys"):
        return
    rows = [row(100 + i, ["essay", "mcq", "work"][i % 3], f"문제 {i}", "답", "풀이", ago=600 - i * 30) for i in range(4)]
    for theme in ("dark", "light"):
        p = Page(br, s, rows, w=1600, h=1000, theme=theme)
        k = p.js(KEYS, 103)
        check(f"{theme}: a finished answer has Right and Wrong, just before the star, neither pressed",
              k["names"][-5:] == ["right", "wrong", "star", "copyItem", "delete"] and state(p, 103) == ("false", "false"), k["names"])
        check(f"{theme}: ...each a mark and its word, the tooltip saying what a press does",
              k["right"].get("word") == "맞음" and k["wrong"].get("word") == "틀림"
              and k["right"].get("title") == "맞음: 맞은 답으로 채점" and k["wrong"].get("title") == "틀림: 틀린 답으로 채점", [k["right"], k["wrong"]])
        check(f"{theme}: ...the tick of a copy that worked and the cross of the close key, in the key's own ink",
              TICK in k["right"].get("path", "") and CROSS in k["wrong"].get("path", "") and k["right"].get("stroke") == k["right"].get("ink")
              and k["wrong"].get("stroke") == k["wrong"].get("ink") and not k["right"].get("inset"), k)
        p.js("() => { window.__sent = []; }")
        press(p, 103, "right")
        p.wait(150)
        check(f"{theme}: pressing Right asks the server to mark that answer right", p.js(SENT) == [{"type": "verdict", "id": 103, "verdict": "right"}], p.js(SENT))
        check(f"{theme}: ...and draws nothing until the server says it is kept", state(p, 103) == ("false", "false"))
        say(p, 103, "right")
        k = p.js(KEYS, 103)
        check(f"{theme}: the server's word presses Right in: its tick in the colour of what worked, the key pressed in",
              state(p, 103) == ("true", "false") and k["right"].get("stroke") == k["ok"] and k["right"].get("inset") and not k["wrong"].get("inset"),
              [k["right"], k["ok"]])
        check(f"{theme}: ...its tooltip says how to take it off", k["right"].get("title") == "맞음으로 채점됨 · 누르면 해제", k["right"].get("title"))
        check(f"{theme}: the other answers are not marked", state(p, 102) == ("false", "false"))
        p.js("() => renderEntry(items.get(103))")   # a redraw of the whole entry, as a check or a follow-up makes
        check(f"{theme}: a redraw of the entry keeps the mark", state(p, 103) == ("true", "false"))
        p.js("() => { window.__sent = []; }")
        press(p, 103, "right")
        p.wait(150)
        check(f"{theme}: Right pressed again asks to take the mark off", p.js(SENT) == [{"type": "verdict", "id": 103, "verdict": None}], p.js(SENT))
        p.js("() => { window.__sent = []; }")
        press(p, 103, "wrong")
        p.wait(150)
        check(f"{theme}: Wrong asks to change it", p.js(SENT) == [{"type": "verdict", "id": 103, "verdict": "wrong"}], p.js(SENT))
        say(p, 103, "wrong")
        k = p.js(KEYS, 103)
        check(f"{theme}: the server's change moves the press: Wrong in, its cross in the colour of what failed, Right out",
              state(p, 103) == ("false", "true") and k["wrong"].get("stroke") == k["bad"] and k["wrong"].get("inset")
              and not k["right"].get("inset") and k["right"].get("stroke") == k["right"].get("ink"), [k["right"], k["wrong"], k["bad"]])
        check(f"{theme}: ...and its tooltip says how to take it off", k["wrong"].get("title") == "틀림으로 채점됨 · 누르면 해제", k["wrong"].get("title"))
        say(p, 103, None)
        check(f"{theme}: taken off, neither is pressed, and the page threw nothing", state(p, 103) == ("false", "false") and not p.errors,
              [state(p, 103), p.errors[:2]])
        p.close()
    # The keyboard stays on the key it pressed, through the server's word and through a redraw of the entry
    p = Page(br, s, rows, w=1600, h=1000)
    p.js("() => entryEl(102)?.querySelector(':scope > .row.head [data-wrong]')?.focus()")   # none to focus fails the check below
    p.page.keyboard.press("Enter")
    p.wait(120)
    say(p, 102, "wrong")
    p.js("() => renderEntry(items.get(102))")
    focus = p.js("() => [document.activeElement?.dataset.wrong, document.activeElement?.getAttribute('aria-pressed')]")
    check("Enter on Wrong sends it, and the keyboard stays on that key, pressed, through a redraw", focus == ["102", "true"]
          and p.js(SENT) == [{"type": "verdict", "id": 102, "verdict": "wrong"}], [focus, p.js(SENT)])
    # With the connection down a press changes nothing, and the page says why
    p.drop()
    p.js("() => { window.__sent = []; }")
    press(p, 101, "right")
    p.wait(120)
    said = p.js("() => document.getElementById('toast').textContent")
    check("offline, a press sends nothing and says there is no connection (and the page threw nothing)", p.js(SENT) == []
          and "서버 연결 없음" in said and state(p, 101) == ("false", "false") and not p.errors, [said, p.errors[:2]])
    p.close()


def group_panels(br, s):
    if not T.group("every panel"):
        return
    rows = [row(200 + i, "essay", f"문제 {i}", "답", "풀이", ago=600 - i * 30) for i in range(3)]
    a, b = Page(br, s, rows, w=1400, h=900), Page(br, s, rows, w=1400, h=900)
    for p in (a, b):
        p.js("() => { window.__sent = []; }")
    press(a, 201, "wrong")
    a.wait(100)
    for p in (a, b):
        say(p, 201, "wrong")
    check("a mark given on one panel shows on the other", state(a, 201) == ("false", "true") and state(b, 201) == ("false", "true"),
          [state(a, 201), state(b, 201)])
    check("...which sent nothing itself", b.js(SENT) == [] and a.js(SENT) == [{"type": "verdict", "id": 201, "verdict": "wrong"}],
          [a.js(SENT), b.js(SENT)])
    for p in (a, b):
        say(p, 201, None)
    check("...and taken off there, it is off on both (and the pages threw nothing)", state(a, 201) == ("false", "false")
          and state(b, 201) == ("false", "false") and not a.errors and not b.errors, (a.errors + b.errors)[:2])
    a.close()
    b.close()


def group_history(br, s):
    if not T.group("marks kept by the server"):
        return
    # 302 has a mark the panel does not know (a file from elsewhere), 304 none at all (a server before verdicts)
    marks = {300: None, 301: "right", 302: "maybe", 303: "wrong"}
    rows = [row(300 + i, "essay", f"문제 {i}", "답", "풀이", ago=900 - i * 30, verdict=marks[300 + i]) for i in range(4)]
    rows.append(row(304, "essay", "문제 4", "답", "풀이", ago=700))
    p = Page(br, s, rows, w=1600, h=1000)
    got = {i: state(p, i) for i in range(300, 305)}
    check("answers from /history come in with their marks, an unknown one or none as no mark",
          got == {300: ("false", "false"), 301: ("true", "false"), 302: ("false", "false"), 303: ("false", "true"), 304: ("false", "false")}, got)
    # Marks changed while the page was away from the server: the history it fetches on reconnecting has the server's
    s.rows = [{**r, "verdict": {300: "wrong", 301: None, 303: "right"}.get(r["id"], r.get("verdict"))} for r in rows]
    p.drop()
    try:   # the page connects again by itself after 1.5 s and fetches the history: waited for until 300 shows the server's mark
        p.page.wait_for_function("() => entryEl(300)?.querySelector(':scope > .row.head [data-wrong]')?.getAttribute('aria-pressed') === 'true'",
                                 timeout=10000)
    except Exception:   # not by then: the check below says what it shows
        pass
    got = {i: state(p, i) for i in (300, 301, 303)}
    check("after a reconnect the marks are the server's (and the page threw nothing)",
          got == {300: ("false", "true"), 301: ("false", "false"), 303: ("true", "false")} and not p.errors, [got, p.errors[:2]])
    p.close()


def group_where(br, s):
    if not T.group("where the keys are not"):
        return
    p = Page(br, s, [], w=1400, h=900)
    p.answer(400, "essay", "", "답", "풀이")
    p.answer(401, "essay", "", "답", "쓰는 중", final=False)
    p.send({"type": "analysis_start", "id": 402, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "error", "id": 402, "text": "RuntimeError: boom", "hint": ""})
    p.answer(403, "essay", "", "답", "멈춘 풀이", final=False)
    p.send({"type": "analysis_cancelled", "id": 403, "reason": "pause"})
    p.wait(250)
    keys = {i: state(p, i) for i in (400, 401, 402, 403)}
    check("a finished answer has the keys; one being written, a failure and a stopped one have none",
          keys == {400: ("false", "false"), 401: (None, None), 402: (None, None), 403: (None, None)}, keys)
    p.done(401, "TYPE: essay\nANSWER: 답\n\n다 쓴 풀이")
    p.wait(200)
    check("...and the one written gets them once it is done (and the page threw nothing)", state(p, 401) == ("false", "false")
          and not p.errors, [state(p, 401), p.errors[:2]])
    p.close()
    # Practice: an answer it keeps back is not judged unseen; shown, it has its keys, with a mark given meanwhile. 409 came before
    # Practice was turned on, and shows as it was
    p = Page(br, s, [row(409, "short", "앞선 물음", "앞선 답", "앞선 풀이", ago=300)], w=1400, h=900)
    menu_pick(p, "on")
    p.answer(410, "short", "물음", "가린 답", "가린 풀이입니다")
    p.wait(250)
    held = p.js("() => entryEl(410).classList.contains('held')")
    check("an answer Practice keeps back has no Right or Wrong and keeps its star, where one from before it has both",
          held and state(p, 410) == (None, None) and "star" in p.js(KEYS, 410)["names"] and state(p, 409) == ("false", "false"),
          [held, p.js(KEYS, 410)["names"], state(p, 409)])
    say(p, 410, "right")   # marked on another panel, where Practice is off
    unseen = state(p, 410)
    p.js("() => entryEl(410).querySelector('[data-act=reveal]').click()")
    p.wait(300)
    menu_pick(p, "off")
    check("a mark given elsewhere meanwhile draws no key on it; shown in full, it has them, with that mark (and the page threw nothing)",
          unseen == (None, None) and state(p, 410) == ("true", "false") and not p.errors, [unseen, state(p, 410), p.errors[:2]])
    p.close()


def group_export(br, s):
    if not T.group("export"):
        return
    rows = [row(500 + i, "essay", f"문제 {i}", "답", f"풀이 {i}", ago=600 - i * 30, verdict=[None, "right", "wrong"][i]) for i in range(3)]
    for locale, right, wrong in ((None, "채점: 맞음", "채점: 틀림"), (EN, "Marked right", "Marked wrong")):
        p = Page(br, s, rows, w=1400, h=900, locale=locale)
        with p.page.expect_download() as dl:
            p.page.click("#hist-export")
            p.page.click("#export-menu [data-export='md']")   # Export's menu: the Markdown file
        md = Path(dl.value.path()).read_text(encoding="utf-8")
        # each answer's part of the file: its heading's line, then what follows it
        parts = {next((i for i in range(3) if f"풀이 {i}" in part), -1): part.split("\n") for part in md.split("\n## ")[1:]}
        lines = {i: [x for x in part[1:] if x.strip()][:1] for i, part in parts.items()}
        check(f"{locale or 'ko'}: Export says each mark in a line of its own under the answer's heading, and none for no mark",
              lines.get(1) == [right] and lines.get(2) == [wrong] and right not in "\n".join(parts.get(0, []))
              and wrong not in "\n".join(parts.get(0, [])) and not p.errors, [lines, p.errors[:2]])
        p.close()


# The newest answer's head, one folded and one open, as laid out: its keys, whether they stand on the line of its time, and inside the window
HEAD = """(id) => { const e = entryEl(id), head = e?.querySelector(':scope > .row.head'); if (!head) return null;
  const keys = [...head.querySelectorAll('.tools > .btn')], time = head.querySelector('time').getBoundingClientRect();
  const mid = (r) => (r.top + r.bottom) / 2;
  return { names: keys.map((b) => Object.keys(b.dataset)[0]), sizes: [...new Set(keys.map((b) => Math.round(b.getBoundingClientRect().width)))],
           oneLine: keys.every((b) => Math.abs(mid(b.getBoundingClientRect()) - mid(time)) <= 4),
           inside: keys.every((b) => b.getBoundingClientRect().right <= innerWidth && b.getBoundingClientRect().left >= 0),
           h: Math.round(head.getBoundingClientRect().height) }; }"""


def group_line(br, s):
    if not T.group("the head on one line"):
        return
    # Algorithm and MCQ: the longest kind's word and a short one. The newest has Problem text (a screen, this PC's model up), the
    # fourth newest is folded, with Show the solution
    rows = [row(600 + i, ["algorithm", "mcq"][i % 2], f"문제 {i}", "답", "풀이 " * 30, ago=4000 - i * 300) for i in range(5)]
    for locale in (None, EN):
        bad = []
        for w, ht in ((375, 812), (390, 844), (430, 932), (1366, 768), (1920, 1080)):
            for theme in ("dark", "light"):
                p = Page(br, s, rows, w=w, h=ht, theme=theme, locale=locale, settle=350)
                now = p.js("() => Date.now() / 1000")
                p.send({"type": "analysis_start", "id": 700, "ts": now, "thumb": thumb(1600, 900), "transcript": "", "pages": 0,
                        "trigger": "screen", "roi": None})
                text = "TYPE: algorithm\nANSWER: 답\nASKED: 무엇을 묻는가\n\n풀이"
                p.send({"type": "delta", "id": 700, "text": text})
                p.done(700, text)
                p.wait(300)
                say(p, 700, "right")
                for i, want in ((700, "ptext"), (602, "fold"), (603, "")):
                    m = p.js(HEAD, i)
                    ok = (m is not None and m["oneLine"] and m["inside"] and len(m["sizes"]) == 1 and "right" in m["names"] and "wrong" in m["names"]
                          and (not want or m["names"][0] == want))
                    if not ok:
                        bad.append([w, theme, i, m])
                if w == 390:
                    p.shot(f"verdict-head-{locale or 'ko'}-{theme}-{w}")
                if p.errors:   # a page that threw fails the check below with what it threw
                    bad.append([w, theme, "the page threw", p.errors[:2]])
                p.close()
        check(f"{locale or 'ko'}: at 375, 390, 430, 1366 and 1920 px the head keeps one line with Right and Wrong in it: the newest answer's six keys "
              "(Problem text first), a folded answer's, an open one's, all one size and inside the window", not bad, bad[:3])


def main() -> int:
    support = h.support
    support.need_vendor(h.PANEL)
    s = Stand("verdict")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_keys, group_panels, group_history, group_where, group_export, group_line):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
