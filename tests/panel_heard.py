"""The spoken side of the panel: why a sentence on What is heard was not taken, the key to what is kept and its sheet (a day's
lines, Copy all, a .md file), the Speech section's new settings, and two answers one after the other when speech goes on while one
is being written.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_heard.py
    PANEL_DIR=/an/older/copy/of/panel ...        # watch the checks fail there

The page is a copy of panel/ over the stand-in server of panel_harness.py. All sentences are made up.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand  # noqa: E402

T = h.Tally()
check = T.check
support = h.support
NOW = 1793800000.0
DAYS = [{"day": "2026-11-04", "n": 3, "first": NOW, "last": NOW + 80}, {"day": "2026-11-03", "n": 1, "first": NOW - 86400, "last": NOW - 86400}]
LINES = [{"ts": NOW, "secs": 3.1, "lang": "en", "text": "So we drained the node first.", "day": "2026-11-04"},
         {"ts": NOW + 40, "secs": 2.0, "lang": "ko", "text": "커널을 올리고 <다시> 부팅했습니다.", "day": "2026-11-04"},
         {"ts": NOW + 80, "secs": 1.1, "lang": "ko", "text": "GTID가 뭔가요?", "day": "2026-11-04"},
         {"ts": NOW - 86400, "secs": 1.5, "lang": "en", "text": "A line of the day before.", "day": "2026-11-03"}]
KEPT = {"days": DAYS, "day": "2026-11-04", "lines": LINES}
CARD = """() => { const b = document.getElementById('hear-text');
  return { said: [...b.children].map((e) => [e.className, e.textContent]), why: [...b.querySelectorAll('.why')].map((e) => e.textContent),
           ink: getComputedStyle(b.querySelector('.why') || b).color, state: getComputedStyle(document.getElementById('hear-state')).color,
           box: b.clientHeight, end: Math.abs(b.scrollHeight - b.clientHeight - b.scrollTop) < 2 }; }"""


def keep_on(p: Page, on: bool = True) -> None:
    """The server's settings, with Keep what is heard as a check wants it."""
    msg = support.settings_message()
    msg["values"]["speech_keep"] = on
    p.send(msg)
    p.wait(120)


def group_why(br, s):
    if not T.group("why a sentence was not taken"):
        return
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    p.send({"type": "transcript", "text": "We moved the team last year. GTID가 뭐?", "lang": "ko"})
    p.wait(100)
    check("a sentence with no word from the server has no note", p.js(CARD)["why"] == [], p.js(CARD))
    p.send({"type": "utterance", "text": "GTID가 뭐?", "lang": "ko", "why": "short"})
    p.wait(100)
    c = p.js(CARD)
    check("too short: a line under the sentence says so", c["said"][-2:] == [["now", "GTID가 뭐?"], ["why", "너무 짧음 · 풀지 않음"]], c["said"])
    check("...in the card's own muted words", c["ink"] == c["state"], [c["ink"], c["state"]])
    check("...and kept in view: it is the last thing there", c["end"], c)
    p.send({"type": "utterance", "text": "We moved the team last year.", "lang": "en", "why": "none"})
    p.wait(100)
    c = p.js(CARD)
    check("no question: said under that sentence, which stays where it is", c["said"] == [["said", "We moved the team last year."], ["why", "질문 없음 · 풀지 않음"],
                                                                                      ["now", "GTID가 뭐?"], ["why", "너무 짧음 · 풀지 않음"]], c["said"])
    # The words of a closed sentence and of the card's own writing of the same sound differ by a word or two
    p.send({"type": "transcript", "text": "So the reboot took about nine minutes, right?", "lang": "en"})
    p.send({"type": "utterance", "text": "So that reboot took about nine minutes, right?", "lang": "en", "why": "told"})
    p.wait(100)
    c = p.js(CARD)
    check("written a little differently, it still goes under its sentence", c["said"][-2:] == [["now", "So the reboot took about nine minutes, right?"], ["why", "이야기 속 물음 · 풀지 않음"]], c["said"])
    # A group of sentences, said once
    p.send({"type": "transcript", "text": "The disk was full. So we moved the logs.", "lang": "en"})
    p.send({"type": "utterance", "text": "The disk was full. So we moved the logs.", "lang": "en", "why": "none"})
    p.wait(100)
    c = p.js(CARD)
    check("a run of sentences is said once, under its last", c["said"][-2:] == [["now", "So we moved the logs."], ["why", "질문 없음 · 풀지 않음"]] and not any(k == "why" and i < len(c["said"]) - 1 and c["said"][i - 1] == ["said", "The disk was full."] for i, (k, _) in enumerate(c["said"])), c["said"])
    p.send({"type": "transcript", "text": "The disk was full. So we moved the logs. What is the plan for the logs?", "lang": "en"})
    p.wait(100)
    c = p.js(CARD)
    check("a sentence said after does not wear it, for sharing some of its words", c["said"][-1] == ["now", "What is the plan for the logs?"], c["said"])
    # Nothing of it on the card any more, or the card's writing of it far off: it brings its sentence along
    p.send({"type": "transcript", "text": "Something else entirely now.", "lang": "en"})
    p.send({"type": "utterance", "text": "데이터베이스 인덱스", "lang": "ko", "why": "short"})
    p.wait(100)
    c = p.js(CARD)
    check("a sentence no longer on the card comes with its note, the words being said after them", ["said", "데이터베이스 인덱스"] in c["said"] and ["why", "너무 짧음 · 풀지 않음"] in c["said"] and c["said"][-1] == ["now", "Something else entirely now."], c["said"])
    p.send({"type": "utterance", "text": "A very long first sentence of a story. A second one that goes on. The last of them here.", "lang": "en", "why": "none"})
    p.wait(50)
    c = p.js(CARD)
    check("...of a long run of speech, its last sentence alone", ["said", "The last of them here."] in c["said"] and not any("first sentence" in x for _, x in c["said"]), c["said"])
    # Only so long
    p.js("() => { heardNotes.forEach((n) => { n.at -= 26000; }); renderHear(); }")
    p.wait(50)
    check("its time up, the note goes", p.js(CARD)["why"] == [], p.js(CARD))
    p.send({"type": "transcript", "text": "", "lang": "en"})
    p.send({"type": "utterance", "text": "짧다", "lang": "ko", "why": "short"})
    p.wait(50)
    c = p.js(CARD)
    check("with the card's words gone it is still said, and no 'no speech' under it", c["said"] == [["said", "짧다"], ["why", "너무 짧음 · 풀지 않음"]], c["said"])
    p.send({"type": "utterance", "text": "A sentence that was taken.", "lang": "en"})
    p.send({"type": "utterance", "text": "x", "lang": "en", "why": "nonsense"})
    p.wait(50)
    check("a sentence that was taken says nothing, nor does a word this panel does not know", p.js(CARD)["why"] == ["너무 짧음 · 풀지 않음"], p.js(CARD))
    p.send({"type": "transcript", "text": "A <b>marked</b> line.", "lang": "en"})
    p.send({"type": "utterance", "text": "<img src=x onerror=alert(1)>", "lang": "en", "why": "short"})
    p.wait(50)
    check("what was heard is written as words, never as markup", p.js("() => !document.querySelector('#hear-text img, #hear-text b')"))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    p = Page(br, s, [], w=1600, h=1000, settle=300, locale="en-US")
    p.send({"type": "transcript", "text": "What now?", "lang": "en"})
    p.send({"type": "utterance", "text": "What now?", "lang": "en", "why": "short"})
    p.wait(80)
    check("in English: Too short · not solved", p.js(CARD)["why"] == ["Too short · not solved"], p.js(CARD))
    for why, words in (("told", "Part of a story · not solved"), ("none", "No question · not solved")):
        p.send({"type": "utterance", "text": "What now?", "lang": "en", "why": why})
        p.wait(50)
        check(f"in English: {words}", p.js(CARD)["why"] == [words], p.js(CARD))
    p.close()


def group_keys(br, s):
    if not T.group("the keys to what is kept"):
        return
    s.heard = {"days": [], "day": "", "lines": []}
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    keys = "() => [document.getElementById('hear-kept').hidden, document.getElementById('open-heard').hidden]"
    check("switch off and nothing kept: no key anywhere", p.js(keys) == [True, True], p.js(keys))
    keep_on(p)
    check("the switch on: a key on the card and an item in the menu", p.js(keys) == [False, False], p.js(keys))
    box = p.js("() => { const k = document.getElementById('hear-kept').getBoundingClientRect(), c = document.getElementById('hear').getBoundingClientRect(); return k.right <= c.right && k.left >= c.left && k.width > 0; }")
    check("...inside the card", box)
    keep_on(p, False)
    p.wait(150)
    check("the switch off again and nothing kept: gone again", p.js(keys) == [True, True], p.js(keys))
    keep_on(p)
    s.heard = KEPT       # sentences kept while the page was open
    keep_on(p, False)
    p.wait(200)
    check("switched off with something kept meanwhile: there to read it, the server says so", p.js(keys) == [False, False], p.js(keys))
    p.close()
    s.heard = KEPT
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    check("switch off with something kept: there to read it", p.js(keys) == [False, False], p.js(keys))
    p.js("() => document.getElementById('more').click()")
    p.wait(150)
    mark = p.js("() => getComputedStyle(document.getElementById('open-heard'), '::before').webkitMaskImage")
    check("the menu's item wears a mark of its own, as the others do", mark.startswith("url("), mark)
    p.page.locator("#open-heard").click()
    p.wait(250)
    check("the menu's item opens the sheet, and the menu closes", p.js("() => [document.getElementById('heard-overlay').hidden, document.getElementById('menu').hidden]") == [False, True])
    p.js("() => closeHeard()")
    # Clear history: nothing is left to read, and the switch is off
    p.js("() => document.getElementById('more').click()")
    p.wait(100)
    p.page.locator("#clear").click()
    p.page.locator("#clear").click()
    p.wait(100)
    check("Clear history takes the keys with it", p.js(keys) == [True, True], p.js(keys))
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_sheet(br, s):
    if not T.group("the sheet of what was heard"):
        return
    s.heard = KEPT
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    p.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    keep_on(p)
    p.page.locator("#hear-kept").click()
    p.wait(300)
    lines = "() => [...document.querySelectorAll('#heard-lines .heard-line')].map((l) => [l.querySelector('time').textContent, l.querySelector('span').textContent])"
    got = p.js(lines)
    check("the card's key opens the sheet on the newest day, a row a sentence", [x[1] for x in got] == [l["text"] for l in LINES[:3]], got)
    want = p.js("(ts) => { const d = new Date(ts * 1000), n = (x) => String(x).padStart(2, '0'); return `${n(d.getHours())}:${n(d.getMinutes())}:${n(d.getSeconds())}`; }", NOW)
    check("...each with its time, to the second", got[0][0] == want, [got[0][0], want])
    check("...what was heard written as words, never as markup", p.js("() => !document.querySelector('#heard-lines b, #heard-lines 다시')") and "<다시>" in got[1][1], got[1])
    check("...in the panel's sheet", p.js("() => document.getElementById('heard').classList.contains('settings') && document.getElementById('heard').getAttribute('aria-modal') === 'true'"))
    check("...the keyboard inside it", p.js("() => document.activeElement.id") == "heard-close", p.js("() => document.activeElement.id"))
    # another day, through its dropdown as a person picks it
    p.page.locator('.combo-btn[data-proxy="heard-day"]').click()
    p.wait(150)
    options = p.js("() => [...document.querySelectorAll('#combo-heard-day li')].map((l) => l.textContent)")
    check("the dropdown lists the days, with how many sentences", len(options) == 2 and "3문장" in options[0] and "1문장" in options[1], options)
    p.page.locator("#combo-heard-day li[data-val='\"2026-11-03\"']").click()
    p.wait(300)
    check("picking a day reads that day", [x[1] for x in p.js(lines)] == ["A line of the day before."], p.js(lines))
    check("...asking the server for it", p.js("() => document.getElementById('heard-day').value") == "2026-11-03")
    p.js("() => document.getElementById('heard-day').value = '2026-11-04'")
    p.js("() => loadHeard('2026-11-04')")
    p.wait(250)
    # Copy all
    p.page.locator("#heard-copy").click()
    p.wait(150)
    copied = p.js("() => navigator.clipboard.readText()")
    clocks = p.js("(all) => all.map((ts) => heardClock(ts))", [line["ts"] for line in LINES[:3]])
    check("Copy all copies every line with its time", copied == "\n".join(f"{c} {line['text']}" for c, line in zip(clocks, LINES)), copied)
    # The .md file
    with p.page.expect_download(timeout=4000) as dl:
        p.page.locator("#heard-save").click()
    d = dl.value
    text = Path(d.path()).read_text(encoding="utf-8")
    check("Save as .md saves one file named by its day", d.suggested_filename == "sidenote-heard-2026-11-04.md", d.suggested_filename)
    check("...the day as its title, a line of a list for each sentence, with its time", text.splitlines()[0] == "# 들린 말 기록 (2026-11-04)" and sum(x.startswith("- ") for x in text.splitlines()) == 3 and "GTID가 뭔가요?" in text.splitlines()[-1], text)
    check("...and says so", "3문장" in p.js("() => document.getElementById('toast').textContent"), p.js("() => document.getElementById('toast').textContent"))
    # the ways out, as the keys' sheet has them
    letters = "() => { const was = document.getElementById('keys-overlay').hidden; document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true })); return [was, document.getElementById('keys-overlay').hidden]; }"
    check("a shortcut does nothing behind it", p.js(letters) == [True, True], p.js(letters))
    p.page.keyboard.press("Escape")
    p.wait(100)
    check("Escape closes it", p.js("() => document.getElementById('heard-overlay').hidden"))
    check("...and the keyboard goes back to the key that opened it", p.js("() => document.activeElement.id") == "hear-kept", p.js("() => document.activeElement.id"))
    p.page.locator("#hear-kept").click()
    p.wait(200)
    p.page.locator("#heard-close").click()
    check("its close key closes it", p.js("() => document.getElementById('heard-overlay').hidden"))
    p.page.locator("#hear-kept").click()
    p.wait(200)
    p.page.mouse.click(4, 500)
    p.wait(100)
    check("a press on the veil closes it", p.js("() => document.getElementById('heard-overlay').hidden"))
    p.page.locator("#hear-kept").click()
    p.wait(200)
    tabs = []
    for _ in range(6):
        p.page.keyboard.press("Tab")
        tabs.append(p.js("() => !!document.activeElement.closest('#heard')"))
    check("Tab stays inside it", all(tabs), tabs)
    p.page.keyboard.press("Escape")
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()
    # A sheet with nothing kept
    s.heard = {"days": [], "day": "", "lines": []}
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    keep_on(p)
    p.js("() => openHeard()")
    p.wait(250)
    empty = "() => ({ none: document.getElementById('heard-none').hidden, words: document.getElementById('heard-none').textContent, tools: !!document.getElementById('heard-copy').offsetParent, list: document.getElementById('heard-lines').hidden })"
    e = p.js(empty)
    check("nothing kept yet: it says so, with no day to choose and nothing to copy or save", e == {"none": False, "words": "보관한 말 없음", "tools": False, "list": True}, e)
    p.js("() => closeHeard()")
    keep_on(p, False)
    p.js("() => openHeard()")
    p.wait(200)
    check("with the switch off it says where the switch is", "풀이 설정" in p.js(empty)["words"], p.js(empty))
    p.close()
    # The server's own words reach it in English too
    s.heard = KEPT
    p = Page(br, s, [], w=1600, h=1000, settle=300, locale="en-US")
    keep_on(p)
    p.js("() => openHeard()")
    p.wait(250)
    words = p.js("() => document.getElementById('heard').innerText")
    check("in English the sheet is in English, what was heard as it was said", "What was heard" in words and "Copy all" in words and "Save as .md" in words and "Stays on this PC" in words, words)
    p.close()


def group_settings(br, s):
    if not T.group("the Speech section"):
        return
    msg = support.settings_message()
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    p.send(msg)
    p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='speech']\").click(); }")
    p.wait(250)
    words = p.js("() => document.querySelector('#settings .set-pane').innerText")
    check("Keep what is heard is there, with what it means", "들린 말 보관" in words and "이 PC에만 남습니다" in words and "다른 사람" in words, words)
    check("...as a switch, off", p.js("() => document.querySelector('#settings [data-set=speech_keep]').getAttribute('aria-checked')") == "false")
    box = "#settings textarea[data-set=speech_terms]"
    check("Extra terms is a box of words", p.js(f"() => !!document.querySelector('{box}')"))
    p.page.locator(box).click()
    p.page.keyboard.type("Zabbix, Open OnDemand")
    p.page.keyboard.press("Tab")
    p.wait(150)
    sent = p.js("() => (window.__sent || []).filter((m) => m && m.type === 'setting' && m.key === 'speech_terms').map((m) => m.value)")
    check("its words go to the server as a list", sent and sent[-1] == ["Zabbix", "Open OnDemand"], sent)
    keys = p.js("() => [...document.querySelectorAll('#settings button[data-set=whisper_model]')].map((b) => [b.textContent, b.getAttribute('aria-pressed')])")
    check("the speech model is a choice of small, the default, and medium", keys == [["small", "true"], ["medium", "false"]], keys)
    check("...saying what the one chosen costs", "CPU" in words and "초" in words, words)
    p.page.locator("#settings button[data-set=whisper_model]", has_text="medium").click()
    p.wait(150)
    sent = p.js("() => (window.__sent || []).filter((m) => m && m.type === 'setting' && m.key === 'whisper_model').map((m) => m.value)")
    check("...and pressing the other asks the server for it", sent == ["medium"], sent)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def group_two_answers(br, s):
    if not T.group("speech goes on while an answer is written"):
        return
    p = Page(br, s, [], w=1600, h=1000, settle=300)
    now = p.js("() => Date.now() / 1000")
    first = "TYPE: essay\nANSWER: 첫 답\nASKED: 첫 물음\n\n첫 풀이입니다."
    second = "TYPE: essay\nANSWER: 둘째 답\nASKED: 둘째 물음\n\n둘째 풀이입니다."
    p.send({"type": "analysis_start", "id": 701, "ts": now, "thumb": None, "transcript": "What does a write ahead log do?", "pages": 0, "trigger": "voice", "roi": None},
           {"type": "delta", "id": 701, "text": first})
    p.wait(120)
    # What the server sends once the running answer ends: its end, then the newer problem's start
    p.done(701, first)
    p.send({"type": "analysis_start", "id": 702, "ts": now + 9, "thumb": None, "transcript": "And what is a checkpoint?", "pages": 0, "trigger": "voice", "roi": None},
           {"type": "delta", "id": 702, "text": second})
    p.wait(120)
    p.done(702, second)
    p.wait(200)
    shown = p.js("""() => [...document.querySelectorAll('#thread > .entry')].map((e) => ({ id: +e.dataset.id, words: e.innerText }))""")
    check("the panel shows both, in the order they were asked", [e["id"] for e in shown] == [701, 702], shown)
    check("...each with its own answer", "첫 풀이" in shown[0]["words"] and "둘째 풀이" in shown[1]["words"] and "둘째" not in shown[0]["words"], shown)
    rows = p.js("() => [...document.querySelectorAll('#history .h')].map((b) => +b.dataset.id)")
    check("...and both are in the contents", sorted(rows) == [701, 702], rows)
    heard = p.js("() => [items.get(701).transcript, items.get(702).transcript]")
    check("...each with its own words heard", heard == ["What does a write ahead log do?", "And what is a checkpoint?"], heard)
    check("the page threw nothing", not p.errors, p.errors[:2])
    p.close()


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(h.PANEL)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        s = Stand("heard")
        group_why(br, s)
        group_keys(br, s)
        group_sheet(br, s)
        group_settings(br, s)
        group_two_answers(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
