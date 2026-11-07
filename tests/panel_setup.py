"""The setup guide: four steps over the settings sheet's look, opened from the menu and once by itself on a new install.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_setup.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

A new user met a page of states and commands, and the settings that matter first were spread over Solver settings. Checked
here: the menu opens the guide on its first step; Escape and Finish close it, the keyboard back on the gear; a server with no
answer kept (fresh) opens it once in a browser and never again, and one with answers never; each step says how things stand
in the words and colours of the cards, marks itself done or not in the steps over the pane, and holds its settings, pressed
as in Solver settings; the screen step shows the screen the server sends back without starting a drawing on the screen card;
what is heard comes on the sound step as it is heard; the sample problem opens in a tab of its own, in the panel's language,
and the step follows the next answer to a screen to its answer line and the way to it. The page is a copy of panel/ over the
stand-in server of panel_harness.py. All answers are made up.
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
SHOWN = "() => document.getElementById('setup-overlay')?.hidden === false"
STEP = "() => document.querySelector('#setup-steps [aria-selected=\"true\"]')?.dataset.step"


def opened(p) -> None:
    """The guide opened as a person opens it: the gear, then its item, pressed with the pointer (a click from script moves no
    keyboard focus, and where the keyboard goes back to is part of what is checked)."""
    p.page.click("#more")
    p.wait(150)
    if p.js("() => !!document.getElementById('open-setup')"):   # an older panel has none: its checks fail on what is not there
        p.page.click("#open-setup")
    p.wait(300)


def go(p, i: int) -> None:
    p.js(f"() => document.querySelector('#setup-steps [data-step=\"{i}\"]')?.click()")
    p.wait(250)


def group_way_in(br, s) -> None:
    if not T.group("the way in and out"):
        return
    p = Page(br, s, [row(1), row(2)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    check("a server with answers kept does not open the guide by itself", not p.js(SHOWN))
    opened(p)
    got = p.js("""() => ({ steps: document.querySelectorAll('#setup-steps .setup-step').length, focus: document.activeElement?.id,
      title: document.getElementById('setup-title')?.textContent })""")
    check("the menu opens it on the first of four steps, the keyboard on Close", p.js(SHOWN) and got["steps"] == 4 and p.js(STEP) == "0"
          and got["focus"] == "setup-close", str(got))
    p.page.keyboard.press("Escape")
    p.wait(200)
    check("Escape closes it, the keyboard back on the gear", not p.js(SHOWN) and p.js("() => document.activeElement?.id") == "more",
          str(p.js("() => document.activeElement?.id")))
    opened(p)
    seen = []
    for _ in range(4):
        seen.append((p.js(STEP), p.js("() => document.getElementById('setup-next')?.textContent.trim()"),
                     p.js("() => document.getElementById('setup-back')?.hidden")))
        p.js("() => document.getElementById('setup-next')?.click()")
        p.wait(250)
    check("Next walks the four steps, Previous from the second on, and the last one's key is Finish",
          [x[0] for x in seen] == ["0", "1", "2", "3"] and seen[0][2] and not any(x[2] for x in seen[1:])
          and seen[3][1] != seen[0][1], str(seen))
    check("...which closes the guide", not p.js(SHOWN))
    opened(p)
    p.js("() => document.querySelector('#setup-steps [data-step=\"0\"]')?.focus()")
    p.page.keyboard.press("ArrowRight")
    p.wait(200)
    p.page.keyboard.press("End")
    p.wait(200)
    check("the steps are tabs: an arrow and End move the step, the keyboard with it",
          p.js(STEP) == "3" and p.js("() => document.activeElement?.dataset.step") == "3", str(p.js(STEP)))
    p.page.keyboard.press("Escape")
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_fresh(br, s) -> None:
    if not T.group("a new install"):
        return
    p = Page(br, s, [], w=1440, h=900, settle=300, status=False)
    status = {"type": "status", "text": "connected", "paused": False, "lang": "auto", "audio": True, "voice": True, "can_ask": False,
              "run_enabled": True, "runner": True, "engines": h.ENGINES, "fresh": True}
    p.send(status, support.settings_message())
    p.wait(400)
    check("a server that has kept no answer opens the guide by itself, on its first step", p.js(SHOWN) and p.js(STEP) == "0")
    p.js("() => document.getElementById('setup-close')?.click()")
    p.page.reload()
    p.wait(400)
    p.send(status, support.settings_message())
    p.wait(400)
    check("...once: the same browser, told so again, leaves it shut", not p.js(SHOWN))
    p.close()
    p = Page(br, s, [], w=1440, h=900, settle=300, status=False)
    p.send({**status, "fresh": False}, support.settings_message())
    p.wait(400)
    check("a status that does not say fresh opens nothing", not p.js(SHOWN))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_steps(br, s) -> None:
    if not T.group("each step"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    opened(p)
    cards = p.js("""() => [...document.querySelectorAll('#setup-body .setup-state')].map((c) => ({ name: c.querySelector('b').textContent,
      pill: c.querySelector('.pill').textContent, state: c.querySelector('.pill').dataset.state }))""")
    rail = p.js("() => ['local', 'agent'].map((id) => ({ pill: document.getElementById('pill-' + id).textContent, state: document.getElementById('pill-' + id).dataset.state }))")
    check("what solves: the local model and the agent, each in its card's word and colour",
          [(c["pill"], c["state"]) for c in cards] == [(r["pill"], r["state"]) for r in rail], str((cards, rail)))
    check("...and a step that works is ticked over the pane", p.js("() => document.querySelector('#setup-steps [data-step=\"0\"]')?.dataset.state") == "ok"
          and p.js("() => !!document.querySelector('#setup-steps [data-step=\"0\"] .n svg')"))
    rows = p.js("() => [...document.querySelectorAll('#setup-body .set [data-set]')].map((b) => b.dataset.set)")
    check("...with its settings, drawn as Solver settings draws them", {"local_llm", "local_model", "agent_mode"} <= set(rows), str(rows))
    p.js("() => { window.__sent.length = 0; document.querySelector('#setup-body [data-set=\"local_llm\"]')?.click(); }")
    p.wait(200)
    sent = p.js("() => window.__sent.filter((m) => m.type === 'setting')")
    check("...and pressed as there: the switch sends the setting", sent == [{"type": "setting", "key": "local_llm", "value": False}], str(sent))
    off = {**h.ENGINES, "local": {**h.ENGINES["local"], "on": False}, "agent": {**h.ENGINES["agent"], "mode": "off", "effective": "off"}}
    p.send({"type": "status", "engines": off})
    p.wait(250)
    check("with nothing able to solve, the step says so and is marked to do", p.js("() => document.querySelector('#setup-steps [data-step=\"0\"]')?.dataset.state") == "warn"
          and p.js("() => !!document.querySelector('#setup-body .setup-note.warn')"))
    p.send({"type": "status", "engines": h.ENGINES})
    go(p, 1)
    shot = p.js("() => ({ pill: document.querySelector('#setup-body .setup-state .pill')?.textContent, rail: document.getElementById('pill-screen')?.textContent })")
    check("the screen: the capture card's state", shot["pill"] == shot["rail"], str(shot))
    p.js("() => { window.__sent.length = 0; document.querySelector('[data-setup=\"shot\"]')?.click(); }")
    p.wait(150)
    check("...Show the screen it receives asks the server for it", p.js("() => window.__sent.map((m) => m.type)") == ["thumb"])
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    p.send({"type": "thumb", "url": png, "ts": p.js("() => Date.now() / 1000"), "live": True})
    p.wait(250)
    got = p.js("() => ({ img: document.querySelector('#setup-body .setup-shot img')?.getAttribute('src') || '', drawing: document.getElementById('shot')?.classList.contains('drawing') })")
    check("...shown on the step, and no drawing starts on the screen card", got["img"] == png and not got["drawing"], str(got)[:200])
    rows = p.js("() => [...document.querySelectorAll('#setup-body .set [data-set]')].map((b) => b.dataset.set)")
    check("...with the monitor and Skip windows", {"monitor", "skip_windows"} <= set(rows), str(rows))
    go(p, 2)
    p.send({"type": "transcript", "text": "What is the difference between a process and a thread?", "lang": "en"})
    p.wait(200)
    check("the sound: what is heard comes on the step as it is heard",
          "process and a thread" in p.js("() => document.getElementById('setup-heard')?.textContent || ''"))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_try(br, s) -> None:
    if not T.group("the sample problem"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    opened(p)
    go(p, 3)
    url = ""
    if p.js("() => !!document.querySelector('[data-setup=\"sample\"]')"):   # an older panel has no such key: no tab to wait for
        with p.page.expect_popup() as tab:
            p.js("() => document.querySelector('[data-setup=\"sample\"]')?.click()")
        sample = tab.value
        sample.wait_for_load_state()
        url = sample.url
        sample.close()
    check("Open the sample problem opens it in a tab of its own, in the panel's language", "sample.html?lang=" in url, url)
    check("...and the step waits for it on the screen", p.js("() => !!document.querySelector('#setup-body .setup-try .spin')"))
    now = p.js("() => Date.now() / 1000")
    p.send({"type": "analysis_start", "id": 41, "ts": now + 1, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None})
    p.wait(150)
    p.done(41, "TYPE: none\n")
    p.wait(250)
    check("a screen with no problem on it: the step says so and waits on",
          p.js("() => !!document.querySelector('#setup-body .setup-try .spin')") and not p.js("() => !!document.querySelector('[data-setup=\"see\"]')"))
    p.send({"type": "analysis_start", "id": 42, "ts": now + 2, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "delta", "id": 42, "text": "TYPE: mcq\nANSWER: ④\n\n풀이"})
    p.wait(150)
    p.done(42, "TYPE: mcq\nANSWER: ④\n\n풀이")
    p.wait(300)
    got = p.js("() => ({ answer: document.querySelector('#setup-body .setup-try.done mark.key')?.textContent, see: !!document.querySelector('[data-setup=\"see\"]'), step: document.querySelector('#setup-steps [data-step=\"3\"]')?.dataset.state, hl: getComputedStyle(document.querySelector('#setup-body .setup-try.done mark.key') || document.body).backgroundImage })")
    check("...the next answer to a screen: its answer line, a way to it, and the step ticked", {k: got[k] for k in ("answer", "see", "step")} == {"answer": "④", "see": True, "step": "ok"}, str(got))
    check("...the answer in the notebook's highlighter, as its answer line is", "gradient" in (got["hl"] or ""), str(got)[:200])
    p.js("() => document.querySelector('[data-setup=\"see\"]')?.click()")
    p.wait(400)
    check("...See the answer closes the guide on that answer", not p.js(SHOWN) and p.js("() => !!document.querySelector('.entry[data-id=\"42\"]')"))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()
    for lang, word in (("ko", "옳지 않은"), ("en", "NOT true")):
        ctx = br.new_context(viewport={"width": 1280, "height": 800})
        pg = ctx.new_page()
        pg.goto(s.url + f"sample.html?lang={lang}", wait_until="load")
        got = pg.evaluate("""() => ({ lang: document.documentElement.lang, title: document.title,
          shown: [...document.querySelectorAll('main')].filter((m) => m.offsetParent !== null).map((m) => m.lang),
          h1: [...document.querySelectorAll('main')].find((m) => m.offsetParent !== null)?.querySelector('h1')?.textContent || '' })""")
        check(f"the sample problem in {lang}: that language alone, and a title the capture does not take for the panel's",
              got["lang"] == lang and got["shown"] == [lang] and word in got["h1"] and not got["title"].lower().startswith("sidenote"), str(got))
        ctx.close()


def group_try_ends(br, s) -> None:
    """Every way the sample's analysis can end. Each of these left "Solving the sample problem" until the page was loaded again,
    showed the answer Practice keeps back, or said no problem was found under an answer the notebook showed."""
    if not T.group("how the sample can end"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    p.answer(70, "mcq", key="④")   # an answer from before, which a repeat points at
    p.wait(200)
    opened(p)
    go(p, 3)
    line = "() => document.querySelector('#setup-body .setup-try')?.textContent.trim() || ''"

    def sample():
        if p.js("() => !!document.querySelector('[data-setup=\"sample\"]')"):
            with p.page.expect_popup() as tab:
                p.js("() => document.querySelector('[data-setup=\"sample\"]')?.click()")
            tab.value.close()
        p.wait(150)

    def start(i):
        p.send({"type": "analysis_start", "id": i, "ts": p.js("() => Date.now() / 1000") + 1, "thumb": None, "transcript": "",
                "pages": 0, "trigger": "screen", "roi": None})
        p.wait(150)
        return p.js(line)

    sample()
    solving = start(61)
    p.send({"type": "error", "id": 61, "text": "the model stopped"})
    p.wait(200)
    after_error = p.js(line)
    start(62)
    p.send({"type": "analysis_cancelled", "id": 62, "reason": "not_sent"})
    p.wait(200)
    after_cancel = p.js(line)
    check("an error or a call-off ends the sample's Solving, and the step says to open it again",
          solving and after_error and after_error != solving and after_cancel == after_error, str((solving, after_error, after_cancel)))
    start(63)
    p.send({"type": "analysis_cancelled", "id": 63, "reason": "repeat", "of": 70})
    p.wait(250)
    got = p.js("() => document.querySelector('#setup-body .setup-try.done mark.key')?.textContent")
    check("...a call-off as a problem solved before (the sample opened again) has that answer", got == "④", str(got))
    sample()
    start(64)
    p.drop()
    p.wait(300)
    check("...and a dropped connection ends it too", p.js(line) not in ("", solving), p.js(line))
    p.close()
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    p.js("() => setPractice(true)")
    opened(p)
    go(p, 3)
    sample()
    start(65)
    p.done(65, "TYPE: mcq\nANSWER: ④\n\n풀이")
    p.wait(300)
    got = p.js("() => ({ shows: (document.querySelector('#setup-body .setup-try.done')?.textContent || '').includes('④'), done: !!document.querySelector('#setup-body .setup-try.done'), held: document.querySelector('.entry[data-id=\"65\"]')?.classList.contains('held') })")
    check("with Practice on, the step says the answer came and keeps it back, as the notebook does", got == {"shows": False, "done": True, "held": True}, str(got))
    p.js("() => setPractice(false)")
    sample()
    start(66)
    p.done(66, "Some words with no head line at all, which the notebook keeps")
    p.wait(300)
    got = p.js("() => ({ done: !!document.querySelector('#setup-body .setup-try.done'), shown: !!document.querySelector('.entry[data-id=\"66\"]') })")
    check("an answer the notebook keeps with no head line counts as answered, not as no problem found", got == {"done": True, "shown": True}, str(got))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_redraws(br, s) -> None:
    """What the guide keeps while the server talks: the screen step's ages change every second, and the whole pane drawn
    again closed an open list and made the picture again; a screen asked for and the guide closed before it came started a
    drawing on the screen card. Escape in its box of words does as in Solver settings: the words put back, nothing sent, closed."""
    if not T.group("what the guide keeps"):
        return
    p = Page(br, s, [row(1)], w=1440, h=900, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    opened(p)
    go(p, 1)
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    p.js("() => document.querySelector('[data-setup=\"shot\"]')?.click()")
    p.send({"type": "thumb", "url": png, "ts": p.js("() => Date.now() / 1000"), "live": False})
    p.wait(200)
    p.js("() => { const i = document.querySelector('#setup-body .setup-shot img'); if (i) i.dataset.same = '1'; }")
    p.js("() => document.querySelector('#setup-body .combo-btn[data-set=\"monitor\"]')?.click()")
    p.wait(150)
    p.js("() => { const l = document.querySelector('.combo-list:not([hidden])'); if (l) l.dataset.same = '1'; }")
    for k in range(3):   # the ages move on, as every second does
        now = p.js("() => Date.now() / 1000")
        p.send({**h.CAPTURE, "now": now, "last_frame": now - 3 - k * 7, "last_audio": now - 2})
        p.wait(300)
    got = p.js("() => ({ img: document.querySelector('#setup-body .setup-shot img')?.dataset.same, list: document.querySelector('.combo-list:not([hidden])')?.dataset.same })")
    check("the screen step's ages move on with no redraw of the picture or the open list", got == {"img": "1", "list": "1"}, str(got))
    p.page.keyboard.press("Escape")   # the list
    p.wait(150)
    box = "#setup-body textarea.words"
    p.js(f"() => {{ window.__sent.length = 0; const b = document.querySelector('{box}'); if (b) {{ b.focus(); b.value = b.value + ', Steam'; }} }}")
    p.page.keyboard.press("Escape")
    p.wait(150)
    first = p.js(f"() => ({{ open: document.getElementById('setup-overlay')?.hidden === false, words: document.querySelector('{box}')?.value.endsWith('Steam'), sent: window.__sent.filter((m) => m.type === 'setting').length }})")
    check("Escape in its box of words puts the words back, sends nothing and closes the guide, as Solver settings does",
          first == {"open": False, "words": False, "sent": 0}, str(first))
    opened(p)
    go(p, 1)
    p.js("() => document.querySelector('[data-setup=\"shot\"]')?.click()")
    p.page.keyboard.press("Escape")
    p.wait(150)
    p.send({"type": "thumb", "url": png, "ts": p.js("() => Date.now() / 1000"), "live": True})
    p.wait(250)
    check("a screen asked for and the guide closed before it came starts no drawing on the screen card",
          not p.js("() => document.getElementById('shot').classList.contains('drawing')"))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def group_narrow(br, s) -> None:
    if not T.group("a narrow window"):
        return
    p = Page(br, s, [row(1)], w=390, h=844, settle=500)
    p.send(support.settings_message())
    p.wait(200)
    opened(p)
    got = []
    for i in range(4):
        go(p, i)
        got.append(p.js("""() => { const g = document.getElementById('setup'); if (!g) return { over: 1, rows: 0 }; return { over: g.scrollWidth - g.clientWidth,
          rows: new Set([...document.querySelectorAll('#setup-steps .setup-step')].map((b) => Math.round(b.getBoundingClientRect().top))).size }; }"""))
    check("at 390 px nothing runs out sideways, and the four steps stand in two rows", all(x["over"] <= 0 and x["rows"] == 2 for x in got), str(got))
    check("no page errors", not p.errors, str(p.errors[:2]))
    p.close()


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("setup")
        group_way_in(br, s)
        group_fresh(br, s)
        group_steps(br, s)
        group_try(br, s)
        group_try_ends(br, s)
        group_redraws(br, s)
        group_narrow(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
