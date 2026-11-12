"""Starred answers in the panel: the star key on an answer's head, what pressing it sends and what the server's answer
draws on every panel, the star in the contents, the Starred choice of the day list in the contents and the notebook,
Export of the starred view, and Clear history taking the starred answers with the rest.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_star.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

The page is a copy of panel/ over the stand-in server of panel_harness.py: its /history gives the rows the checks set,
the starred ones alone when asked (starred=1), and its socket is the checks' own.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
support = h.support

# The state of one entry's star key and of its row in the contents, read off the page
KEY = """(id) => { const e = entryEl(id), k = e?.querySelector(':scope > .row.head [data-star]'), r = document.querySelector(`#history .h[data-id="${id}"]`);
  const tools = e?.querySelector(':scope > .row.head .tools');
  // first: the first of the head's keys after Right and Wrong, which stand before it (tests/panel_verdict.py)
  return { key: !!k, first: !!k && k.previousElementSibling?.matches('[data-wrong]') && tools.firstElementChild?.matches('[data-right]'), pressed: k?.getAttribute('aria-pressed'), title: k?.title || '',
           word: k?.textContent.trim() || '', fill: k ? getComputedStyle(k.querySelector('svg')).fill : '', row: !!r?.querySelector('.h-star'),
           rowWord: r?.querySelector('.h-star + .sr-only')?.textContent || '' }; }"""
# The highlighter's token, as this page's theme computes it: what a star is filled with
TOKEN = """() => { const p = document.createElement('i'); p.style.color = 'var(--hl-yellow)'; document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; }"""
SENT = "() => (window.__sent || []).filter((m) => m && m.type === 'star')"


def star(p: Page, i: int, on: bool) -> None:
    """The server's word that answer i is starred or not, as every panel gets it, with how many are starred. The stand-in
    server keeps it first, as server/history.py does, so what the page fetches after it agrees (new rows: they are shared)."""
    p.stand.rows = [{**r, "starred": on} if r["id"] == i else r for r in p.stand.rows]
    p.send({"type": "star", "id": i, "starred": on, "n": sum(1 for r in p.stand.rows if r.get("starred"))})
    p.wait(120)


def shown(p: Page) -> dict:
    """What the contents list and the notebook show, and the contents' count."""
    return p.js("""() => ({ rows: [...document.querySelectorAll('#history .h')].map((b) => +b.dataset.id),
        page: [...document.querySelectorAll('#thread > .entry')].filter((e) => !e.hidden).map((e) => +e.dataset.id),
        count: document.getElementById('hist-count').textContent })""")


def pick_day(p: Page, value: str) -> None:
    """A choice of the day list, through its dropdown as a person picks it. One the list does not offer is not picked: the checks
    after it then fail, and the suite goes on."""
    p.page.locator('.combo-btn[data-proxy="hist-day"]').click()
    p.wait(150)
    li = p.page.locator(f'#combo-hist-day li[data-val=\'"{value}"\']')
    if li.count():
        li.click()
    else:
        p.page.keyboard.press("Escape")
    p.wait(400)


def press(p: Page, i: int) -> None:
    """A click on answer i's star key, when it has one."""
    key = p.page.locator(f'.entry[data-id="{i}"] [data-star]')
    if key.count():
        key.click()


def group_key(br, s):
    if not T.group("the star key"):
        return
    rows = [row(100 + i, ["essay", "mcq", "work"][i % 3], f"문제 {i}", "답", "풀이", ago=600 - i * 30) for i in range(4)]
    for theme in ("dark", "light"):
        p = Page(br, s, rows, w=1600, h=1000, theme=theme)
        k = p.js(KEY, 103)
        check(f"{theme}: a finished answer has a star key, the first of its head's keys after Right and Wrong, not pressed",
              k["key"] and k["first"] and k["pressed"] == "false" and k["word"] == "별표" and k["title"].startswith("별표:"), k)
        check(f"{theme}: ...an outline, nothing in it", k["fill"] == "none", k["fill"])
        p.js("() => { window.__sent = []; }")
        press(p, 103)
        p.wait(150)
        check(f"{theme}: pressing it asks the server to star that answer", p.js(SENT) == [{"type": "star", "id": 103, "starred": True}], p.js(SENT))
        check(f"{theme}: ...and draws nothing until the server says it is kept", p.js(KEY, 103)["pressed"] == "false")
        star(p, 103, True)
        k, token = p.js(KEY, 103), p.js(TOKEN)
        check(f"{theme}: the server's star fills it with the highlighter", k["pressed"] == "true" and k["fill"] == token, [k["fill"], token])
        check(f"{theme}: ...its tooltip says how to take it off", k["title"] == "별표됨 · 누르면 해제", k["title"])
        check(f"{theme}: ...and its row in the contents wears the star, named for a screen reader", k["row"] and k["rowWord"] == "별표한 답", k)
        check(f"{theme}: the other answers are not starred", not p.js(KEY, 102)["row"] and p.js(KEY, 102)["pressed"] == "false")
        p.js("() => renderEntry(items.get(103))")   # a redraw of the whole entry, as a check or a follow-up makes
        check(f"{theme}: a redraw of the entry keeps the star", p.js(KEY, 103)["pressed"] == "true")
        p.js("() => { window.__sent = []; }")
        press(p, 103)
        p.wait(150)
        check(f"{theme}: pressed again, it asks to unstar", p.js(SENT) == [{"type": "star", "id": 103, "starred": False}], p.js(SENT))
        star(p, 103, False)
        k = p.js(KEY, 103)
        check(f"{theme}: unstarred, the key and the row are as before", k["pressed"] == "false" and k["fill"] == "none" and not k["row"], k)
        check(f"{theme}: the page threw nothing", not p.errors, p.errors[:2])
        p.close()
    # Every panel open shows a star, whichever pressed it: two pages get the server's one message
    a, b = Page(br, s, rows, w=1400, h=900), Page(br, s, rows, w=1400, h=900)
    press(a, 101)
    a.wait(100)
    for p in (a, b):
        star(p, 101, True)
    check("a star pressed on one panel shows on the other", a.js(KEY, 101)["pressed"] == "true" and b.js(KEY, 101)["pressed"] == "true"
          and b.js(KEY, 101)["row"], [a.js(KEY, 101), b.js(KEY, 101)])
    check("...which sent nothing itself", b.js(SENT) == [], b.js(SENT))
    a.close()
    b.close()
    # Only what the server keeps has a key: an answer still being written, a failure and a stopped one have none
    p = Page(br, s, [], w=1400, h=900)
    p.answer(200, "essay", "", "답", "풀이")
    p.answer(201, "essay", "", "답", "쓰는 중", final=False)
    p.send({"type": "analysis_start", "id": 202, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "error", "id": 202, "text": "RuntimeError: boom", "hint": ""})
    p.answer(203, "essay", "", "답", "멈춘 풀이", final=False)
    p.send({"type": "analysis_cancelled", "id": 203, "reason": "pause"})
    p.wait(250)
    keys = {i: p.js(KEY, i)["key"] for i in (200, 201, 202, 203)}
    check("a finished answer has the key; one being written, a failure and a stopped one have none", keys == {200: True, 201: False, 202: False, 203: False}, keys)
    p.send({"type": "analysis_done", "id": 201, "text": "TYPE: essay\nANSWER: 답\n\n다 쓴 풀이", "usage": {}, "cost_usd": None, "model": "m", "engine": "local",
            "sent": [], "stages": {}, "elapsed": 1.0, "region": None})
    p.wait(200)
    check("...and the one written gets it once it is done", p.js(KEY, 201)["key"])
    # With the connection down a press changes nothing, and the page says why
    p.drop()
    p.js("() => { window.__sent = []; }")
    press(p, 200)
    p.wait(120)
    said = p.js("() => document.getElementById('toast').textContent")
    check("offline, a press sends nothing and says there is no connection", p.js(SENT) == [] and "서버 연결 없음" in said
          and p.js(KEY, 200)["pressed"] == "false", said)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_history(br, s):
    if not T.group("starred answers kept by the server"):
        return
    rows = [row(300 + i, "essay", f"문제 {i}", "답", "풀이", ago=900 - i * 30, starred=i in (1, 3)) for i in range(5)]
    p = Page(br, s, rows, w=1600, h=1000)
    got = {i: (p.js(KEY, i)["pressed"], p.js(KEY, i)["row"]) for i in range(300, 305)}
    check("answers from /history come in with their stars, on their keys and their rows",
          got == {300: ("false", False), 301: ("true", True), 302: ("false", False), 303: ("true", True), 304: ("false", False)}, got)
    # A star changed while the page was away from the server: the history it fetches on reconnecting has the server's
    s.rows = [{**r, "starred": r["id"] in (302, 303)} for r in rows]
    p.drop()
    p.wait(1900)   # the page connects again by itself after 1.5 s, and fetches the history
    got = {i: p.js(KEY, i)["pressed"] for i in (301, 302, 303)}
    check("after a reconnect the stars are the server's", got == {301: "false", 302: "true", 303: "true"}, got)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_choice(br, s):
    if not T.group("the Starred choice"):
        return
    kinds = ["essay", "mcq", "work", "essay", "math", "mcq", "work", "essay"]
    rows = [row(400 + i, kinds[i], f"문제 {i}", "답", f"풀이 {i}", ago=86400 * (i // 4) + 900 - i * 30, starred=i in (1, 4, 6)) for i in range(8)]
    p = Page(br, s, rows, w=1600, h=1100)
    opts = p.js("() => [...document.getElementById('hist-day').options].map((o) => [o.value, o.textContent])")
    check("the day list offers Starred after All days, with how many", opts[1] == ["starred", "별표 · 3개"], opts[:3])
    check("...and every day after it, as before", [v for v, _ in opts[2:]] and all(len(v) == 10 for v, _ in opts[2:]), opts)
    s.asked.clear()
    pick_day(p, "starred")
    got = shown(p)
    # 401 is today's, 404 and 406 yesterday's
    check("chosen, the contents list the starred answers only, the newest first", got["rows"] == [401, 406, 404], got)
    check("...the notebook shows only them", sorted(got["page"]) == [401, 404, 406], got)
    check("...the count says how many of how many", got["count"] == "3/8", got["count"])
    check("...the server was asked for its starred answers", any("starred=1" in q for q in s.asked), s.asked)
    check("...and the closed list names it", p.js("() => document.querySelector('.combo-btn[data-proxy=\"hist-day\"] .combo-val').textContent") == "별표")
    types = p.js("() => [...document.getElementById('hist-kind').options].map((o) => o.value).filter(Boolean)")
    check("the type list offers the starred answers' types", sorted(types) == ["math", "mcq", "work"], types)
    # Export takes what is shown
    with p.page.expect_download() as dl:
        p.page.click("#hist-export")
        p.page.click("#export-menu [data-export='md']")   # Export's menu: the Markdown file
    md = Path(dl.value.path()).read_text(encoding="utf-8")
    check("Export writes the starred answers, and only them", md.count("\n## ") == 3 and all(f"풀이 {i}" in md for i in (1, 4, 6))
          and "풀이 0" not in md, md[:200])
    check("...and says how many", "답 3개" in p.js("() => document.getElementById('toast').textContent"))
    # The Anki file takes the same answers: one note per starred answer, after Anki's header lines
    with p.page.expect_download() as dl:
        p.page.click("#hist-export")
        p.page.click("#export-menu [data-export='anki']")
    notes = [l for l in Path(dl.value.path()).read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    check("...and the Anki file holds the starred answers, one note each", len(notes) == 3, notes[:3])
    # Unstarred while Starred is chosen, the answer stays in view until the choice changes
    star(p, 404, False)
    got = shown(p)
    check("unstarred under Starred, an answer stays in view until the choice changes", 404 in got["rows"] and 404 in got["page"], got)
    check("...its key and row show it unstarred", p.js(KEY, 404)["pressed"] == "false" and not p.js(KEY, 404)["row"])
    pick_day(p, "")
    pick_day(p, "starred")
    got = shown(p)
    check("chosen again, Starred no longer holds it", got["rows"] == [401, 406] and sorted(got["page"]) == [401, 406], got)
    check("...and says the new count", p.js("() => document.getElementById('hist-day').options[1].textContent") == "별표 · 2개")
    # A type with Starred: the starred of that type
    p.js("() => { const k = document.getElementById('hist-kind'); k.value = 'work'; k.dispatchEvent(new Event('change')); }")
    p.wait(300)
    check("a type chosen with Starred gives the starred of that type", shown(p)["rows"] == [406], shown(p))
    check("...asked of the server with the star", any("starred=1" in q and "kind=work" in q for q in s.asked), s.asked)
    p.js("() => clearChoice()")   # what the stage's way back does when a choice hides everything
    p.wait(250)
    got = shown(p)
    check("the way back shows every answer again", len(got["rows"]) == 8 and len(got["page"]) == 8 and got["count"] == "8", got)
    check("...with All days chosen", p.js("() => [histStar, document.getElementById('hist-day').value]") == [False, ""])
    # With nothing starred the choice is not offered
    for i in (401, 406):
        star(p, i, False)
    opts = p.js("() => [...document.getElementById('hist-day').options].map((o) => o.value)")
    check("with nothing starred, Starred is not offered", "starred" not in opts, opts)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # Starred on another panel, an answer this page does not hold (older than what it fetched): shown under Starred all the same
    p = Page(br, s, rows, w=1600, h=1100)
    pick_day(p, "starred")
    p.stand.rows = p.stand.rows + [row(499, "essay", "다른 패널에서 별표한 문제", "답", "풀이 499", ago=86400 * 30)]
    star(p, 499, True)
    p.wait(300)
    got = shown(p)
    check("a star from another panel on an answer this page does not hold brings it into Starred", 499 in got["rows"] and 499 in got["page"], got)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # Clear history takes the starred answers with the rest, and the choice with them
    s.rows = rows
    p = Page(br, s, rows, w=1600, h=1100)
    pick_day(p, "starred")
    p.js("() => { clearArmed = Date.now() - 1000; document.getElementById('clear').click(); }")   # its second press, a second after the first
    p.wait(300)
    got = p.js("() => [histStar, document.getElementById('hist-day').value, [...document.getElementById('hist-day').options].map((o) => o.value), thread.length]")
    check("Clear history takes the starred answers and the Starred choice with the rest", got == [False, "", [""], 0], got)
    check("...and asked the server to clear", any(m.get("type") == "history_clear" for m in p.js("() => window.__sent || []")))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def main() -> int:
    support.need_vendor(h.PANEL)
    s = Stand("star")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_key, group_history, group_choice):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
