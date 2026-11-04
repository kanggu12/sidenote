"""The panel through the long, tangled scenarios a real sitting goes through, and what an answer can be at its worst.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_scenarios.py
    ONLY="place,hostile" ...                        # only the groups named
    PANEL_DIR=/an/older/copy/of/panel ...           # watch the checks fail there

Each group plays a sitting through the page's real paths, over the stand-in socket of panel_harness.py, with the server's CSP on, and any
error the page throws fails the group's last check. Most of what is here was found by driving the panel the same way:
a focus that moved the page, a row pressed that did not become the current one, what came during a dropped connection lost, boxes off the
picture on a portrait monitor. These checks fail on the panel of 999ddc8.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
LONG = "\n\n".join(f"## 부분 {i}\n\n" + "\n\n".join(f"문단 {i}-{j}: 이 문단은 쪽을 길게 만들기 위한 글입니다. " * 6 for j in range(4)) for i in range(1, 5))


def ids_of(p):
    return p.js("() => [...document.querySelectorAll('#history .h')].map((b) => idOf(b.dataset.id))")


def no_errors(p, group):
    check(f"{group}: the page threw nothing", not p.errors, p.errors[:3])


def group_reader(br, s):
    if not T.group("the place in the thread"):
        return
    rows = [row(100 + i, "essay", f"문제 {i}", f"답 {i}", LONG if i % 2 else "짧은 풀이", ago=5000 - i * 60) for i in range(12)]
    p = Page(br, s, rows, w=1600, h=900)
    # In the middle of the page: where a focus that moves the page shows, and a follow that is off
    p.js("() => window.scrollTo(0, 2000)")
    p.wait(250)
    seen = "(sel) => { const r = document.querySelector(sel).getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }"
    for what in ("#more", "#reanalyze", "#ask", "#hist-q"):
        y0 = p.js("() => window.scrollY")
        was = p.js(seen, what)
        p.js(f"() => document.querySelector('{what}').focus()")
        p.wait(120)
        if was:
            check(f"a focus on {what} leaves the page where it was", abs(p.js("() => window.scrollY") - y0) < 2, f"{y0} -> {p.js('() => window.scrollY')}")
        else:
            # The contents' search stands in a column that drifts with the page when it is taller than the window:
            # out of the window, a focus brings it into view, so nothing is typed into a box out of sight
            check(f"a focus on {what}, out of the window in the drifting column, brings it into view", p.js(seen, what), f"{y0} -> {p.js('() => window.scrollY')}")
    p.js("() => document.activeElement.blur()")
    y0 = p.js("() => window.scrollY")
    p.page.keyboard.press("Tab")
    p.wait(120)
    check("the Tab key from nowhere does not throw the page about", abs(p.js("() => window.scrollY") - y0) < 1400, p.js("() => window.scrollY"))
    # Every row pressed becomes the current one, and stays so, short answers and the last ones too
    wrong = []
    for i in ids_of(p):
        p.js("(i) => document.querySelector(`#history .h[data-id=\"${i}\"]`).click()", i)
        p.wait(560)
        if p.js("() => viewId") != i:
            wrong.append((i, p.js("() => viewId")))
    check("every row pressed becomes the current row", not wrong, wrong)
    check("...the ribbon on the page goes to the same answer", p.js("() => [...document.querySelectorAll('.entry[data-here]')].map((e) => idOf(e.dataset.id)).join()") == str(p.js("() => viewId")))
    check("...and exactly one row wears it", p.js("() => document.querySelectorAll('#history .h[aria-current=\"true\"]').length") == 1)
    # Picked, read for a long while, and a new answer comes: it is offered, and does not pull the page away
    pick = rows[3]["id"]
    p.js("(i) => document.querySelector(`#history .h[data-id=\"${i}\"]`).click()", pick)
    p.wait(560)
    jump0 = p.js("() => $('jump').hidden")
    check("a row pressed offers no new answer when none has come", jump0 is True)
    p.js("() => { handScrollAt = Date.now() - 60000; }")          # as if it had been read for a minute
    y0 = p.js("() => window.scrollY")
    p.answer(500, "short", "새 문제", "새 답", "풀이")
    p.wait(200)
    check("a new answer does not pull the page off what was picked, however long ago", abs(p.js("() => window.scrollY") - y0) < 3, f"{y0} -> {p.js('() => window.scrollY')}")
    check("...the current row stays on what was picked", p.js("() => viewId") == pick)
    check("...and the jump key offers it", p.js("() => $('jump').hidden") is False)
    # The wheel lets go of the pick; the jump key goes to the end and lets go too
    p.page.mouse.move(600, 500)
    p.page.mouse.wheel(0, 300)
    p.wait(250)
    check("scrolling by hand lets go of the pick", p.js("() => pinnedView") is None)
    p.js("() => $('jump').click()")
    p.wait(500)
    check("the jump key goes to the newest", p.js("() => viewId") == 500 and p.js("() => stick") is True)
    # A new answer offered and then cancelled leaves no key pointing at nothing
    p.js("() => { window.scrollTo(0, 800); stick = false; handScrollAt = Date.now(); }")
    p.wait(150)
    p.send({"type": "analysis_start", "id": 501, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "delta", "id": 501, "text": "TYPE: mcq\nANSWER: ②\n\n쓰는 중"})
    p.wait(150)
    check("an answer being written is offered to one reading above", p.js("() => $('jump').hidden") is False)
    p.send({"type": "analysis_cancelled", "id": 501, "reason": "superseded"})
    p.wait(150)
    check("...and its cancelling takes the key away", p.js("() => $('jump').hidden") is True)
    # Filters: what is being read stays at its height, and the current row stays right
    p.js("() => { window.scrollTo(0, 1500); stick = false; }")
    p.wait(250)
    anchor = p.js("""() => { const e = [...document.querySelectorAll('.entry:not([hidden])')].find((x) => x.getBoundingClientRect().bottom > innerHeight * .33);
                             return [idOf(e.dataset.id), e.getBoundingClientRect().top]; }""")
    p.js("() => { const k = $('hist-kind'); k.value = 'short'; k.dispatchEvent(new Event('change')); }")
    p.wait(200)
    p.js("() => { const k = $('hist-kind'); k.value = ''; k.dispatchEvent(new Event('change')); }")
    p.wait(250)
    after = p.js("(i) => document.querySelector(`.entry[data-id=\"${i}\"]`).getBoundingClientRect().top", anchor[0])
    check("a filter on and off leaves the page where it was", abs(after - anchor[1]) < 3, f"{anchor[1]} -> {after}")
    check("...and the current row is what is in view", p.js("() => viewId") == anchor[0] or p.js("() => { const e = entryEl(viewId); return e.getBoundingClientRect().top <= innerHeight * .33; }"))
    # Written under a filter: it stays until the filter changes
    p.js("() => { const k = $('hist-kind'); k.value = 'mcq'; k.dispatchEvent(new Event('change')); }")
    p.wait(120)
    text = p.answer(502, "essay", "필터 밖의 문제", "답", "풀이")
    p.send({"type": "status", "paused": False})
    p.wait(150)
    check("an answer written under a filter it does not match stays in sight when it is whole", p.js("() => !entryEl(502).hidden"), text[:40])
    p.js("() => { const k = $('hist-kind'); k.value = ''; k.dispatchEvent(new Event('change')); }")
    p.wait(120)
    # Resized while following: the end stays in view
    p.js("() => { $('jump').hidden || $('jump').click(); goLatest(); }")
    p.wait(450)
    for w, hh in ((1100, 800), (800, 800), (1920, 1040)):
        p.page.set_viewport_size({"width": w, "height": hh})
        p.wait(350)
        gap = p.js("() => stageEnd() - (window.scrollY + innerHeight)")
        check(f"following, resized to {w}x{hh}: the end stays in view", gap < 140, gap)
    no_errors(p, "the place in the thread")
    p.close()
    # The keyboard in the contents: one stop on the Tab order, and the arrows go down the list
    p = Page(br, s, [row(200 + i, "short", f"문제 {i}", "답", "풀이", ago=900 - i * 10) for i in range(10)], w=1600, h=1300)
    check("the contents take one Tab stop", p.js("() => [...document.querySelectorAll('#history .h')].filter((b) => b.tabIndex === 0).length") == 1)
    p.js("() => document.querySelector('#history .h').focus()")
    y0 = p.js("() => window.scrollY")
    first = p.js("() => document.activeElement.dataset.id")
    p.page.keyboard.press("ArrowDown")
    p.wait(80)
    check("the arrow goes to the next row", p.js("() => document.activeElement.dataset.id") != first and p.js("() => document.activeElement.classList.contains('h')"))
    check("...and does not move the page", abs(p.js("() => window.scrollY") - y0) < 2)
    p.page.keyboard.press("End")
    p.wait(80)
    check("End goes to the last row", p.js("() => document.activeElement === [...document.querySelectorAll('#history .h')].pop()"))
    p.page.keyboard.press("Enter")
    p.wait(560)
    check("Enter goes to that answer", p.js("() => viewId") == 200)
    no_errors(p, "the contents by keyboard")
    p.close()


def group_contents(br, s):
    if not T.group("the contents"):
        return
    day = 86400
    rows = [row(300 + i, "mcq" if i % 2 else "essay", f"서브넷 문제 {i}" if i == 3 else f"문제 {i}", f"답 {i}", "SYN 풀이" if i == 2 else "풀이", ago=(3 - i // 5) * day + i * 10)
            for i in range(15)]
    p = Page(br, s, rows, w=1600, h=1300)
    typed = lambda q: (p.page.fill("#hist-q", q), p.wait(120))   # noqa: E731
    count = lambda: p.js("() => document.querySelectorAll('#history .h').length")   # noqa: E731
    typed("서브넷")
    check("what the row says is found: a word of what was asked", count() == 1, count())
    typed("syn")
    check("a word of the working, in another case", count() == 1, count())
    for odd in ("(", "[", "\\", "*", "$", "+", ".*", "(?<=", "<b>"):
        typed(odd)
        check(f"{odd!r} typed: nothing breaks and it is searched as itself", count() >= 0 and not p.errors, p.errors[:1])
    typed("없는 말 없는 말")
    check("nothing found says so", p.js("() => !$('hist-nomatch').hidden && $('hist-nomatch').textContent.includes('없는 말')"))
    with_dl = p.js("() => document.querySelectorAll('#history .h').length")
    p.js("() => { window.__dl = 0; const c = URL.createObjectURL; URL.createObjectURL = (b) => { window.__dl++; return c.call(URL, b); }; $('hist-export').click(); }")
    p.wait(150)
    check("with nothing to export no empty file is made, and it says so", with_dl == 0 and p.js("() => window.__dl") == 0 and p.js("() => $('toast').textContent.includes('내보낼')"), p.js("() => $('toast').textContent"))
    typed("")
    check("an empty search shows them all again", count() == 15)
    # Export holds what was asked, every answer of it
    with p.page.expect_download() as dl:
        p.js("() => { $('hist-export').click(); document.querySelector('#export-menu [data-export=md]').click(); }")   # Export's menu: the Markdown file
    md = Path(dl.value.path()).read_text(encoding="utf-8")
    check("the file says what was asked", "서브넷 문제 3" in md and md.count("\n## ") == 15, md[:120])
    # Each day a tab saying how many
    tabs = p.js("() => [...document.querySelectorAll('#history .h-day')].map((d) => [d.querySelector('.h-tab')?.textContent, d.querySelector('.h-n')?.textContent])")
    check("each day stands on a tab with how many answers it holds", len(tabs) >= 3 and all(t[1] == "5개" for t in tabs), tabs)
    title = p.js("() => document.querySelector('#history .h').title")
    check("a row's whole text is in its tooltip", title.startswith("문제"), title)
    # The list keeps the ribbon in sight as the thread is read, unless the list itself is in use
    p.page.set_viewport_size({"width": 1600, "height": 860})
    p.wait(400)
    p.js("() => { window.scrollTo(0, 0); stick = false; }")
    p.wait(350)
    seen = p.js("""() => { const l = $('history').getBoundingClientRect(), r = document.querySelector('#history .h[aria-current="true"]')?.getBoundingClientRect();
                           return r ? r.top >= l.top - 1 && r.bottom <= l.bottom + 1 : null; }""")
    if p.js("() => $('history').scrollHeight > $('history').clientHeight"):
        check("read at the page's top, the current row is in view in the list", seen is True, seen)
    no_errors(p, "the contents")
    p.close()


def group_dropped(br, s):
    if not T.group("a dropped connection"):
        return
    p = Page(br, s, [row(400, "essay", "앞 문제", "답", "풀이", ago=100)], w=1400, h=900)
    # A follow-up being written when the connection falls, and finished by the server meanwhile
    p.js("() => { turns.set(401, { id: 401, parent: 400, q: '왜 그런가요?', raw: '반쯤 쓴', live: true, error: null, hint: '', meta: null, retry: false, kind: 'ask', check: null }); items.get(400).turns.push(401); renderEntry(items.get(400)); }")
    p.wait(80)
    p.drop()
    p.wait(120)
    check("the follow-up cut off says so", p.js("() => turns.get(401).hint") == "interrupted")
    s.rows[0]["turns"] = [{"id": 401, "q": "왜 그런가요?", "text": "TYPE: followup\nANSWER: 끝까지 쓴 답\n\n끝까지 쓴 풀이"}]
    p.wait(1800)                                     # it connects again by itself, and reads the history
    check("...and it comes back whole after the connection does", p.js("() => turns.get(401).hint") == "" and "끝까지" in p.js("() => turns.get(401).raw"), p.js("() => turns.get(401).raw"))
    check("...on the page too", "끝까지 쓴 풀이" in p.js("() => entryEl(400).textContent"))
    # An answer that came while it was down: followed by one at the end
    p.js("() => goLatest()")
    p.wait(300)
    p.drop()
    p.wait(50)
    s.rows.append(row(402, "short", "끊긴 사이 문제", "끊긴 사이 답", "풀이", ago=0))
    p.wait(1800)
    check("what was answered while it was down joins the thread", p.js("() => thread.includes(402)"))
    check("...and one following is at it", p.js("() => viewId") == 402 and p.js("() => stageEnd() - (window.scrollY + innerHeight)") < 140)
    # A stream cut part way and never finished: it says so, once, and a second drop adds nothing
    p.answer(403, "essay", "쓰는 중 문제", "답", "쓰는 중", final=False)
    p.wait(80)
    p.drop()
    p.wait(1800)
    check("an answer cut off by a restart says so", p.js("() => items.get(403)?.hint") == "interrupted")
    check("...and is there once", p.js("() => document.querySelectorAll('.entry[data-id=\"403\"]').length") == 1)
    no_errors(p, "a dropped connection")
    p.close()


def group_order(br, s):
    if not T.group("messages out of order"):
        return
    p = Page(br, s, [row(410, "essay", "앞 문제", "앞 답", "풀이", ago=50)], w=1400, h=900)
    n = lambda: p.js("() => document.querySelectorAll('.entry').length")   # noqa: E731
    before = n()
    p.send({"type": "delta", "id": 9999, "text": "TYPE: mcq\nANSWER: ①"})
    p.send({"type": "analysis_done", "id": 9998, "text": "TYPE: mcq\nANSWER: ①\n\n풀이", "usage": {}, "elapsed": 1.0, "sent": [], "stages": {}, "engine": "local", "model": "m"})
    p.send({"type": "analysis_cancelled", "id": 9997, "reason": "superseded"})
    p.send({"type": "stage", "id": 9996, "stage": "think", "detail": "x"})
    p.send({"type": "check", "id": 9995, "passed": 1, "total": 1})
    p.send({"type": "thumb", "id": 9994, "url": "data:,"})
    p.send({"type": "no such message", "id": 1})
    p.send({"type": "gpu", "none": True})
    p.send({"type": "usage"})
    p.send({"type": "capture"})
    p.js("() => window.__sock.onmessage({ data: 'this is not JSON' })")
    p.js("() => window.__sock.onmessage({ data: '' })")
    p.js("() => window.__sock.onmessage({ data: 'null' })")
    p.js("() => window.__sock.onmessage({ data: '[1, 2, 3]' })")
    check("messages about answers it never heard of, and ones that are not messages, change nothing and throw nothing", not [e for e in p.errors if "pageerror" in e], p.errors[:3])
    check("...the thread holds no more than it may", n() <= before + 1, n())
    p.errors.clear()
    # The end of an answer twice; a delta after its end; an error after its end: a whole answer stays whole, and no alarm for it
    text = p.answer(420, "short", "문제", "맞는 답", "풀이")
    p.wait(80)
    p.done(420, text)
    p.send({"type": "delta", "id": 420, "text": "뒤늦은 글"})
    p.js("() => { $('toast').classList.remove('show'); }")
    p.send({"type": "error", "id": 420, "text": "뒤늦은 오류", "hint": "timeout"})
    p.wait(80)
    check("a late error does not turn a whole answer into an error", p.js("() => !items.get(420).error"))
    check("...nor raise a notice about it", p.js("() => !$('toast').classList.contains('show')"), p.js("() => $('toast').textContent"))
    check("a late delta adds nothing", "뒤늦은 글" not in p.js("() => entryEl(420).textContent"))
    # Started twice, the second as if the server had forgotten: one entry
    now = p.js("() => Date.now() / 1000")
    for _ in range(2):
        p.send({"type": "analysis_start", "id": 430, "ts": now, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None})
    p.send({"type": "delta", "id": 430, "text": "TYPE: essay\nANSWER: 답\n\n풀이"})
    p.wait(80)
    check("an answer started twice is one entry", p.js("() => document.querySelectorAll('.entry[data-id=\"430\"]').length") == 1)
    # Another engine starts the answer over: its mark and its row follow while it is written
    p.send({"type": "stage", "id": 430, "stage": "restart"})
    p.send({"type": "delta", "id": 430, "text": "\n"})
    p.js("() => { const it = items.get(430); it.raw = ''; }")
    p.send({"type": "delta", "id": 430, "text": "TYPE: mcq\nANSWER: ③\nASKED: 다시 읽은 물음\n\n다시 쓴 풀이"})
    p.wait(250)
    check("the entry's kind follows the new text", p.js("() => entryEl(430).dataset.kind") == "mcq", p.js("() => entryEl(430).dataset.kind"))
    check("...and its row what is asked now", "다시 읽은 물음" in p.js("() => document.querySelector('#history .h[data-id=\"430\"]').textContent"))
    no_errors(p, "messages out of order")
    p.close()


HOSTILE = [
    '<img src=x onerror="window.__pwned=1">',
    '<script>window.__pwned=1</script>',
    '[press](javascript:window.__pwned=1)',
    '<svg onload="window.__pwned=1"></svg>',
    '<iframe srcdoc="<script>parent.__pwned=1</script>"></iframe>',
    '"><img src=x onerror=window.__pwned=1>',
]


def group_hostile(br, s):
    if not T.group("hostile and broken answers"):
        return
    p = Page(br, s, [], w=1400, h=900)
    i = 600
    for evil in HOSTILE:
        bodies = [
            evil,
            f"1. **{evil}**: 설명\n2. **이름**: {evil}\n",
            f"- **{evil}**: 설명\n- **이름**: {evil}\n",
            f"{evil} -> 다음 -> 마지막\n",
            f"**첫째 -> {evil} -> 셋째** 입니다\n",
            f"| 항목 | {evil} | 비교 |\n|---|---|---|\n| {evil} | 맞음 | 1 |\n| 둘 | 틀림 | 2 |\n| 셋 | 맞음 | 3 |\n",
            f"## {evil}\n\n글\n\n## 둘\n\n글\n\n## 셋\n\n글\n",
            f"시간 O({evil}) 공간 O(1)\n",
        ]
        for body in bodies:
            i += 1
            p.answer(i, "algorithm", evil, f"시간 O({evil}) -> {evil} -> 끝", body)
    p.wait(400)
    check("no hostile answer ran anything", p.js("() => window.__pwned === undefined"))
    check("...and left no handler or script in the thread",
          p.js("""() => !document.querySelector('#thread script, #thread iframe, #thread [onerror], #thread [onload], #thread [onclick], #thread a[href^="javascript"]')"""))
    check("...nor in the contents", p.js("() => !document.querySelector('#history script, #history img, #history [onerror]')"))
    no_errors(p, "hostile answers")
    p.close()
    # Answers broken in every way a stream can break them
    broken = [
        "TYPE: essay\nANSWER: 답\n\n```python\nprint('끝나지 않은 코드')\n",
        "TYPE: essay\nANSWER: 답\n\n| 머리 | 둘 |\n|---|\n| 어긋난 | 표 | 칸 | 넘침 |\n",
        "TYPE: essay\nANSWER: 답\n\n$$ 닫히지 않은 수식\n",
        "TYPE: essay\nANSWER: 답\n\n```chart\n{ 깨진 JSON\n```\n",
        "TYPE: essay\nANSWER: 답\n\n```mermaid\nflowchart LR\n  A[[[ --> \n```\n",
        "TYPE: nosuchkind\nANSWER: 모르는 유형\n\n풀이\n",
        "TYPE: essay\n\n",
        "TYPE: essay\nANSWER: \n\n",
        "ANSWER: 유형이 없음\n\n풀이\n",
        "그냥 글만\n",
        "",
        "TYPE: essay\nANSWER: " + "매우긴답" * 400 + "\n\n풀이\n",
        "TYPE: essay\nANSWER: 답\n\n" + "한줄에이어지는아주긴토큰" * 300 + "\n",
        "TYPE: essay\nANSWER: 답\n\n`" + "a" * 3000 + "`\n",
        "TYPE: essay\nANSWER: 답\n\n" + "\n".join("  " * d + f"- 깊이 {d}" for d in range(14)) + "\n",
        "TYPE: essay\nANSWER: 답\n\n" + "\n".join(f"{n}. 항목" for n in range(1, 140)) + "\n",
        "TYPE: essay\nANSWER: 답\n\n" + "| " + " | ".join(f"열{c}" for c in range(40)) + " |\n|" + "---|" * 40 + "\n| " + " | ".join("값" for _ in range(40)) + " |\n",
        "TYPE: essay\nANSWER: 🙂‍↔️ שלום مرحبا ♿︎\n\n‮뒤집힌 글 עברית 🧑🏽‍💻\n",
        "TYPE: essay\nANSWER: 답\n\n1. **이름만**\n2. **이름**:\n3. \n\n- **\n- ****\n",
        "TYPE: algorithm\nANSWER: 시간 O(, 공간 O()\n\n시간 O(((N)\n",
        "TYPE: essay\nANSWER: → → →\n\n→ → → →\n\n-> -> ->\n",
    ]
    for w, hh in ((1400, 900), (800, 700)):
        p = Page(br, s, [], w=w, h=hh)
        for n, text in enumerate(broken):
            now = p.js("() => Date.now() / 1000")
            p.send({"type": "analysis_start", "id": 700 + n, "ts": now, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
                   {"type": "delta", "id": 700 + n, "text": text})
            p.done(700 + n, text)
        p.js("() => { thread.forEach((id) => { unfolded.add(id); renderEntry(items.get(id)); }); }")
        p.wait(900)
        over = p.js("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"broken answers at {w} wide: the page does not scroll sideways", over <= 0, over)
        wide = p.js("""() => { const s = document.getElementById('thread').getBoundingClientRect(); return [...document.querySelectorAll('#thread .ct')]
                              .filter((c) => c.getBoundingClientRect().right > s.right + 2).length; }""")
        check(f"...and nothing stands outside the sheet at {w} wide", wide == 0, wide)
        no_errors(p, f"broken answers at {w}")
        p.close()
    # A sitting that has gone on for days: the list, the thread and the search still answer
    many = [row(1000 + n, "mcq", f"문제 {n}", f"답 {n}", "풀이 " * 50, ago=n * 30) for n in range(400)]
    p = Page(br, s, many, w=1600, h=1000, settle=1500)
    t = p.js("""() => { const t0 = performance.now(); $('hist-q').value = '문제 39'; $('hist-q').dispatchEvent(new Event('input')); const a = performance.now() - t0;
                        const t1 = performance.now(); $('hist-q').value = ''; $('hist-q').dispatchEvent(new Event('input')); return [a, performance.now() - t1, thread.length]; }""")
    check("a search over a long sitting answers at once (under 400 ms: CI's machine runs at about half this PC's speed)", t[0] < 400 and t[1] < 400, t)
    check("...over no more than it keeps", t[2] <= 200, t[2])
    no_errors(p, "a long sitting")
    p.close()


def group_region(br, s):
    if not T.group("the box on the screen"):
        return
    for w, hh, name in ((3840, 2160, "wide"), (1440, 2560, "portrait"), (5120, 1440, "ultrawide"), (1024, 768, "old")):
        r = row(800, "essay", "문제", "답", "풀이", ago=5, thumb=h.thumb(w // 4, hh // 4), region=[.25, .25, .75, .75], region_shown=True)
        p = Page(br, s, [r], w=1600, h=1000)
        p.wait(350)
        got = p.js("""() => { const i = $('thumb').getBoundingClientRect(), b = $('region').getBoundingClientRect();
                              return { hidden: $('region').hidden, x: (b.left - i.left) / i.width, y: (b.top - i.top) / i.height, w: b.width / i.width, h: b.height / i.height }; }""")
        ok = not got["hidden"] and abs(got["x"] - .25) < .03 and abs(got["y"] - .25) < .03 and abs(got["w"] - .5) < .03 and abs(got["h"] - .5) < .03
        check(f"on a {name} screen the answer's box stands on the picture, at the same fractions", ok, got)
        no_errors(p, f"the box, {name}")
        p.close()
    # An answer kept from before the box was what the crop took holds the model's first guess, often a part of the problem: it draws none
    p = Page(br, s, [row(805, "essay", "문제", "답", "풀이", ago=5, thumb=h.thumb(960, 540), region=[.25, .25, .43, .9])], w=1600, h=1000)
    p.wait(250)
    check("a kept answer whose box is only the model's guess draws no box", p.js("() => $('region').hidden") is True)
    check("...and the card says nothing of a box", "형광펜" not in p.js("() => $('shot-cap').textContent"), p.js("() => $('shot-cap').textContent"))
    p.answer(806, "essay", "새 문제", "답", "풀이", final=False)
    p.send({"type": "analysis_done", "id": 806, "text": "TYPE: essay\nANSWER: 답\n\n풀이", "usage": {}, "cost_usd": None, "model": "m", "engine": "local", "sent": [], "stages": {"local": True}, "elapsed": 3.0, "region": [.1, .1, .5, .5], "region_shown": False})
    check("nor does a new one the crop could not be told of", p.js("() => items.get(806).region") is None)
    no_errors(p, "the box and what it is")
    p.close()
    # Capture off while drawing: nothing left half-way
    p = Page(br, s, [row(801, "essay", "문제", "답", "풀이", ago=5, thumb=h.thumb(960, 540))], w=1600, h=1000)
    p.js("() => { drawing = { url: $('thumb').src || 'data:,', ts: serverNow(), live: true, start: null, box: null }; renderShot(); }")
    p.send({**h.CAPTURE, "now": p.js("() => Date.now() / 1000"), "screen_on": False})
    p.wait(120)
    check("the screen switched off while a box is drawn ends the drawing", p.js("() => drawing === null"))
    no_errors(p, "drawing and the switch")
    p.close()


def group_keys(br, s):
    if not T.group("the keys and what they say"):
        return
    p = Page(br, s, [row(810, "essay", "문제", "답", "풀이", ago=5)], w=1600, h=1100)
    engines = json.loads(json.dumps(h.ENGINES))
    engines["local"]["loaded"] = None
    p.send({"type": "status", "engines": engines})
    p.wait(100)
    p.js("() => { window.__sent.length = 0; $('gpu-load').click(); $('gpu-load').click(); $('gpu-load').click(); }")
    check("the GPU key pressed three times sends once", p.js("() => window.__sent.filter((m) => m.type === 'gpu_load').length") == 1, p.js("() => window.__sent"))
    p.wait(1200)
    check("...and is still held after the clock's tick", p.js("() => $('gpu-load').disabled") is True)
    p.send({"type": "status", "engines": engines})
    p.wait(80)
    check("...until the server has said", p.js("() => $('gpu-load').disabled") is False)
    # A toast gone is not reached by the keyboard
    p.js("() => { toast('이동', () => {}, ''); }")
    check("a pressable notice can be reached", p.js("() => $('toast').tabIndex") == 0)
    p.js("() => { clearTimeout(toast.timer); }")
    p.js("() => { $('toast').classList.remove('show'); toast('말', null, ''); }")
    check("one that is not, cannot", p.js("() => $('toast').tabIndex") == -1)
    # The capture program off: reanalysis says what it will look at
    p.send({**h.CAPTURE, "now": p.js("() => Date.now() / 1000"), "clients": 0})
    p.wait(80)
    p.js("() => reanalyze()")
    check("reanalysis with the capture program off says it looks at the last screen", "마지막" in p.js("() => $('toast').textContent"), p.js("() => $('toast').textContent"))
    # Words that name a key show its mark
    p.send({"type": "status", "paused": True})
    p.wait(120)
    check("a band naming a key shows the key's mark", p.js("() => !!document.querySelector('#alerts .key-hint svg')"))
    p.send({"type": "status", "paused": False})
    no_errors(p, "the keys")
    p.close()
    # A band up at the page's top: small wheel steps can still leave the top
    p = Page(br, s, [row(820 + i, "essay", f"문제 {i}", "답", LONG, ago=500 - i) for i in range(6)], w=1400, h=800)
    p.js("() => { window.scrollTo(0, 0); stick = false; }")
    p.send({"type": "status", "paused": True})
    p.wait(250)
    p.page.mouse.move(500, 500)
    for _ in range(14):
        p.page.mouse.wheel(0, 12)
        p.wait(40)
    p.wait(200)
    check("with a band up, small steps of the wheel leave the page's top", p.js("() => window.scrollY") > 40, p.js("() => window.scrollY"))
    no_errors(p, "a band and the wheel")
    p.close()
    # A follow-up that fails at the end of the page: the following comes back
    p = Page(br, s, [row(830, "essay", "문제", "답", "풀이", ago=5)], w=1400, h=800)
    p.js("""() => { turns.set(831, { id: 831, parent: 830, q: '왜요?', raw: '', live: true, error: null, hint: '', meta: null, retry: false, kind: 'ask', check: null });
                    items.get(830).turns.push(831); renderEntry(items.get(830)); stick = false; followTurn = 831; }""")
    p.send({"type": "error", "id": 831, "text": "실패", "hint": "timeout"})
    p.wait(120)
    check("a follow-up that failed at the end gives the following back", p.js("() => stick") is True and p.js("() => followTurn") is None)
    # A problem seen again: the follow-up keys go to the answer the server now answers about
    p.answer(832, "short", "둘째 문제", "둘째 답", "풀이")
    p.wait(100)
    p.send({"type": "analysis_start", "id": 833, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "analysis_cancelled", "id": 833, "reason": "repeat", "of": 830})
    p.wait(120)
    check("a problem seen again: what follow-ups are about goes back to its answer", p.js("() => lastAnsweredId()") == 830)
    p.answer(834, "short", "셋째 문제", "셋째 답", "풀이")
    p.wait(100)
    check("...until a new answer", p.js("() => lastAnsweredId()") == 834)
    no_errors(p, "a follow-up and a repeat")
    p.close()


def main() -> int:
    support_ok = h.support.need_vendor(h.PANEL)   # noqa: F841  (exits with a word if the panel's libraries are missing)
    s = Stand("scenarios")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_reader, group_contents, group_dropped, group_order, group_hostile, group_region, group_keys):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
