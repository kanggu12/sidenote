"""Practice mode, the keyboard shortcuts and Export to Anki, through the page's own paths over panel_harness.py's stand-in socket.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_study.py
    ONLY="practice,edges,keys,anki,words" ...       # only the groups named
    PANEL_DIR=/an/older/copy/of/panel ...           # watch the checks fail there

Practice keeps each answer that arrives back until it is asked for: its question shows, Show a hint opens the solution's own parts
one at a time and in their order, and Show the answer opens all of it, the answer line last. What it keeps back may not reach the
page another way: the answer line's Copy key, the c key, the contents' rows and their search, Problem text, the pictures drawn from
the answer, the line said to a screen reader. The keys do what the keys' sheet says, and nothing while a field has the keyboard or a
modifier is held. The Anki file is read as Anki reads it: its headers, then a line an answer of three tab-separated fields, none of
them ended or opened as something else by what an answer holds (code, tables, formulas, quote marks, a #).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
EN = "en-US"

# ---------------------------------------------------------------- answers of the shapes Practice cuts
# Three sections under headings; the first says nothing of the complexity the answer line gives, so a scale drawn early would show
HEADED = ("## 핵심 아이디어\n\n지금까지 본 값을 사전에 담고 `target - x` 가 이미 있으면 두 인덱스를 돌려줍니다.\n\n"
          "## 코드\n\n```python\ndef two_sum(nums, target):\n    seen = {}\n    for i, x in enumerate(nums):\n        if target - x in seen:\n"
          "            return [seen[target - x], i]\n        seen[x] = i\n```\n\n## 복잡도\n\n원소마다 한 번 보므로 시간 O(N), 공간 O(N)입니다.\n")
HEADED_KEY = "사전 한 번 훑기, 시간 O(N), 공간 O(N)"
PARTS = ["지금까지 본 값을 사전에 담고", "def two_sum", "원소마다 한 번 보므로"]
# Steps of a list, then a closing line: four parts
STEPS = ("1. **역할 확인**: 인스턴스에 붙은 역할에 읽기 권한이 있는지 봅니다.\n\n2. **버킷 정책 확인**: 명시적 거부가 허용보다 먼저입니다.\n\n"
         "3. **키 권한 확인**: 암호화된 객체는 복호화 권한도 필요합니다.\n\n어느 단계에서 막혔는지는 감사 기록에 남습니다.\n")
STEP_WORDS = ["읽기 권한이 있는지", "명시적 거부가", "복호화 권한도", "감사 기록에 남습니다"]
ONE = "한 문단으로 끝나는 풀이입니다."


def text_of(p, i):
    return p.js("(i) => entryEl(i)?.innerText || ''", i)


def held_state(p, i):
    """What a card shows of itself: kept back or not, its keys, its count, whether its answer row and its Copy keys are there."""
    return p.js("""(i) => { const e = entryEl(i); if (!e) return null; return {
        held: e.classList.contains('held'), keys: [...e.querySelectorAll('.row.practice [data-act]')].map((b) => b.dataset.act),
        count: e.querySelector('.hint-n')?.textContent || '', answerRow: !!e.querySelector(':scope > .row[data-answer]'),
        copy: !!e.querySelector('[data-copy-answer]'), copyAll: !!e.querySelector('[data-copy-item]'), live: !!e.querySelector('.row.practice .spin') }; }""", i)


def spy(p):
    """What the page copies, and what it says in its notices, from here on."""
    p.js("""() => { window.__copied = []; const was = window.copyText; window.copyText = (text, btn) => { window.__copied.push(text); return was(text, btn); };
                    window.__toasts = []; const said = window.toast; window.toast = (text, go, tone) => { window.__toasts.push(text); return said(text, go, tone); }; }""")


def menu_pick(p, which):
    """Open the gear menu and press one of Practice's two choices, as by hand."""
    p.page.click("#more")
    p.page.click(f"#practice-seg [data-practice='{which}']")
    p.page.keyboard.press("Escape")
    p.wait(150)


def no_errors(p, group):
    check(f"{group}: the page threw nothing", not p.errors, p.errors[:3])


def head(kind, asked, key):
    return f"TYPE: {kind}\nANSWER: {key}\nASKED: {asked}\n\n"


# ---------------------------------------------------------------- Practice
def group_practice(br, s):
    if not T.group("practice"):
        return
    old = row(10, "essay", "옛 물음", "옛 답 열쇠말", "옛 풀이입니다", ago=900)
    p = Page(br, s, [old], w=1600, h=1000)
    seg = "() => [...document.querySelectorAll('#practice-seg button')].map((b) => [b.dataset.practice, b.getAttribute('aria-pressed'), b.textContent.trim()])"
    check("the menu offers Practice beside Theme, Motion and Language, Off and On, Off at first",
          p.js(seg) == [["off", "true", "끔"], ["on", "false", "켬"]] and p.js("() => [...document.querySelectorAll('#menu h3')].map((x) => x.textContent.trim())") == ["화면 모드", "움직임", "언어", "연습"],
          [p.js(seg), p.js("() => [...document.querySelectorAll('#menu h3')].map((x) => x.textContent.trim())")])
    p.answer(11, "short", "첫 물음", "보이는 답", "보이는 풀이입니다")
    p.wait(200)
    check("off: an answer shows its answer line and its solution", "보이는 답" in text_of(p, 11) and "보이는 풀이입니다" in text_of(p, 11), text_of(p, 11))
    sent = p.js("() => window.__sent.length")
    menu_pick(p, "on")
    stored = p.js("() => [localStorage.getItem('sidenote-practice'), Date.now()]")
    check("on: kept in this browser, as when it was turned on", stored[0] is not None and abs(int(stored[0]) - stored[1]) < 5000, stored)
    check("...and the menu says so", p.js(seg)[1][1] == "true", p.js(seg))
    check("the answers from before it was turned on show as they did", not held_state(p, 10)["held"] and not held_state(p, 11)["held"]
          and "옛 답 열쇠말" in text_of(p, 10) and "보이는 답" in text_of(p, 11), [held_state(p, 10), held_state(p, 11)])
    spy(p)
    # An answer arrives: being written, it says so and shows none of it
    whole = head("algorithm", "두 수의 합을 이루는 두 인덱스", HEADED_KEY) + HEADED
    p.send({"type": "analysis_start", "id": 12, "ts": p.js("() => Date.now() / 1000"), "thumb": h.thumb(1280, 720), "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
           {"type": "delta", "id": 12, "text": whole})
    p.wait(250)
    live = text_of(p, 12)
    st = held_state(p, 12)
    check("being written, its card says so", st["held"] and st["live"] and "연습 모드라 가림" in live, [st, live])
    check("...and shows none of it: no answer line, no word of the solution", HEADED_KEY not in live and not any(w in live for w in PARTS) and not st["answerRow"], live)
    check("...but its question", "두 수의 합을 이루는 두 인덱스" in live, live)
    p.done(12, whole)
    p.wait(300)
    st = held_state(p, 12)
    done = text_of(p, 12)
    check("written: Show a hint and Show the answer, and how many hints there are", st["keys"] == ["hint", "reveal"] and st["count"] == "힌트 3개", st)
    check("...the answer line, the solution and their Copy keys still kept back", HEADED_KEY not in done and not any(w in done for w in PARTS)
          and not st["answerRow"] and not st["copy"] and not st["copyAll"], [st, done])
    check("no follow-up keys under it yet: they ask about an answer not seen", not p.js("() => !!entryEl(12).querySelector('.row.asks:not(.practice)')"))
    check("no picture drawn from what it keeps back (the complexity scale of its answer line)", not p.js("() => !!entryEl(12).querySelector('.v-bigo')"))
    check("a screen reader is told it is done, not its answer line", HEADED_KEY not in p.js("() => document.getElementById('live-note').textContent"),
          p.js("() => document.getElementById('live-note').textContent"))
    # Not through the contents, nor their search
    row_text = p.js("() => { const b = document.querySelector('#history .h[data-id=\"12\"]'); return b ? [b.textContent, b.title] : null; }")
    check("its row in the contents names its question, not its answer line", row_text and "두 수의 합을 이루는 두 인덱스" in row_text[0]
          and HEADED_KEY not in row_text[0] + row_text[1], row_text)
    p.js("() => { const q = $('hist-q'); q.value = '사전에'; q.dispatchEvent(new Event('input', { bubbles: true })); }")
    p.wait(150)
    found = p.js("() => [...document.querySelectorAll('#history .h')].map((b) => b.textContent + b.title).join('|')")
    check("a word only its hidden solution holds finds no row to show it", "지금까지 본 값을" not in found and "12" not in p.js("() => [...document.querySelectorAll('#history .h')].map((b) => b.dataset.id).join()"), found)
    p.js("() => { const q = $('hist-q'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); }")
    # Nor through Problem text: it writes out the question, and the card stays as it was
    p.js("() => entryEl(12).querySelector('[data-ptext]').click()")
    asked = p.js("() => window.__sent.filter((m) => m.type === 'problem_text').map((m) => m.id)")
    p.send({"type": "problem_text", "id": 12, "text": "정수 배열과 목표값이 주어질 때 합이 목표값인 두 원소의 인덱스를 구하시오"})
    p.wait(200)
    after = text_of(p, 12)
    check("Problem text writes out the question and keeps the rest back", asked == [12] and "정수 배열과 목표값이" in after and HEADED_KEY not in after
          and not any(w in after for w in PARTS) and held_state(p, 12)["held"], [asked, after])
    check("...with its own copy key, which copies the question alone", p.js("() => !!entryEl(12).querySelector('[data-copy-ptext]')"))
    # Nor through the c key: the current answer is this one
    p.js("() => { stick = true; updateView(); }")
    p.page.keyboard.press("c")
    p.wait(150)
    check("c on it copies nothing and says why", p.js("() => window.__copied.length") == 0 and "연습으로 가린 답" in p.js("() => window.__toasts.join('|')"),
          p.js("() => [window.__copied, window.__toasts]"))
    # One with no question written out is named in the contents as kept back, not by its answer line or its working's first words
    p.answer(18, "short", "", "물음 없는 답 열쇠말", "물음 없는 풀이입니다")
    p.wait(200)
    row_text = p.js("() => { const b = document.querySelector('#history .h[data-id=\"18\"]'); return b ? [b.textContent, b.title] : null; }")
    check("one with no question written out is named as kept back, not by its answer line or its first words", row_text and "연습으로 가린 답" in row_text[0]
          and "물음 없는 답 열쇠말" not in row_text[0] + row_text[1] and "물음 없는 풀이입니다" not in row_text[0] + row_text[1], row_text)
    # The hints, in their order, the answer line never one of them
    for n in range(1, 4):
        p.js("() => entryEl(12).querySelector('[data-act=hint]').click()")
        p.wait(250)
        txt = text_of(p, 12)
        shown = [w in txt for w in PARTS]
        check(f"hint {n}: the first {n} part{'s' if n > 1 else ''} of the solution, in order, and not the next", shown == [i < n for i in range(3)], [shown, txt[-200:]])
        check(f"hint {n}: the answer line still kept back", HEADED_KEY not in txt and not held_state(p, 12)["answerRow"], txt[-200:])
        if n == 1:   # the first part says nothing of the cost: a scale now would be the answer line's
            check("hint 1: no scale drawn from the answer line it keeps back", not p.js("() => !!entryEl(12).querySelector('.v-bigo')"))
    st = held_state(p, 12)
    check("the last hint out: only Show the answer is left, counted 3 of 3", st["keys"] == ["reveal"] and st["count"] == "힌트 3개 중 3개", st)
    check("...and the keyboard on it, where the hint key was", p.js("() => document.activeElement?.dataset.act") == "reveal", p.js("() => document.activeElement?.outerHTML?.slice(0, 80)"))
    p.js("() => entryEl(12).querySelector('[data-act=reveal]').click()")
    p.wait(300)
    st = held_state(p, 12)
    txt = text_of(p, 12)
    check("Show the answer: the answer line, the whole solution, its Copy keys", not st["held"] and st["answerRow"] and st["copy"] and st["copyAll"]
          and HEADED_KEY in txt and all(w in txt for w in PARTS), [st, txt[:200]])
    check("...the complexity scale comes with it", p.js("() => !!entryEl(12).querySelector('.v-bigo')"))
    check("...and the contents row says what it answers now", "두 수의 합을 이루는 두 인덱스" in p.js("() => document.querySelector('#history .h[data-id=\"12\"]').textContent"))
    # The newest answered, opened: its follow-up keys come with it, and its row is named by its answer line
    p.js("() => entryEl(18).querySelector('[data-act=reveal]').click()")
    p.wait(250)
    check("the newest opened gets its follow-up keys, and its row its answer line", p.js("() => !!entryEl(18).querySelector('.row.asks:not(.practice) [data-ask]')")
          and "물음 없는 답 열쇠말" in p.js("() => document.querySelector('#history .h[data-id=\"18\"]').textContent"))
    # One part: only the answer key; steps of a list: a part each
    p.answer(13, "short", "한 문단짜리", "한 줄 답", ONE)
    p.answer(14, "work", "단계로 푸는 물음", "단계 답", STEPS)
    p.wait(300)
    check("an answer of one part offers only Show the answer, and no count", held_state(p, 13)["keys"] == ["reveal"] and held_state(p, 13)["count"] == "", held_state(p, 13))
    check("steps of a list are a part each, the closing line one more", held_state(p, 14)["count"] == "힌트 4개", held_state(p, 14))
    p.js("() => entryEl(14).querySelector('[data-act=hint]').click()")
    p.wait(200)
    txt = text_of(p, 14)
    check("the first step alone, numbered as it was", [w in txt for w in STEP_WORDS] == [True, False, False, False] and p.js("() => entryEl(14).querySelectorAll('.md ol > li').length") == 1, txt[-160:])
    # A part headed by the answer is no hint: what starts with one has none, and one further down ends the hints before it
    p.answer(15, "mcq", "정답부터 쓴 물음", "③", "## 정답: ③\n\n셋째가 맞습니다.\n\n## 까닭\n\n까닭 문단입니다.\n")
    p.answer(16, "work", "정답을 끝에 쓴 물음", "끝 답", "## 살필 것\n\n첫째 살필 것입니다.\n\n## 다음 살필 것\n\n둘째 살필 것입니다.\n\n## 결론\n\n끝 답입니다.\n")
    p.answer(17, "work", "답 낱말로 시작하는 제목", "열쇠", "## 답안 쓰는 법\n\n첫 문단입니다.\n\n## Answers in tables\n\n둘째 문단입니다.\n")
    p.wait(300)
    check("an answer that opens with a part headed by the answer offers only Show the answer", held_state(p, 15)["keys"] == ["reveal"] and held_state(p, 15)["count"] == "", held_state(p, 15))
    check("headed by the answer further down: the hints end before that part", held_state(p, 16)["count"] == "힌트 2개", held_state(p, 16))
    for _ in range(2):
        p.js("() => entryEl(16).querySelector('[data-act=hint]').click()")
        p.wait(150)
    txt = text_of(p, 16)
    check("...so all its hints leave the answer kept back", "둘째 살필 것입니다" in txt and "끝 답입니다" not in txt, txt[-200:])
    check("a heading that only begins with such a word is an ordinary part", held_state(p, 17)["count"] == "힌트 2개", held_state(p, 17))
    # What the watching adds under it waits with it; the user's own follow-up shows
    now = p.js("() => Date.now() / 1000")
    p.send({"type": "analysis_start", "id": 15, "ts": now, "thumb": None, "transcript": "", "pages": 0, "trigger": "retry", "roi": None, "about": 14},
           {"type": "delta", "id": 15, "text": "TYPE: work\nANSWER: 다시 푼 답 열쇠말\n\n다시 푼 풀이"},
           {"type": "analysis_done", "id": 15, "text": "TYPE: work\nANSWER: 다시 푼 답 열쇠말\n\n다시 푼 풀이", "usage": {}, "cost_usd": None, "engine": "local", "sent": [], "stages": {}, "elapsed": 1.0})
    p.wait(150)
    check("a retry the watching wrote under it is not said to a screen reader either", "다시 푼 답 열쇠말" not in p.js("() => document.getElementById('live-note').textContent"),
          p.js("() => document.getElementById('live-note').textContent"))
    p.send({"type": "analysis_start", "id": 16, "ts": now, "thumb": None, "transcript": "왜 거부가 먼저인가요?", "pages": 0, "trigger": "ask", "roi": None, "about": 14},
           {"type": "delta", "id": 16, "text": "TYPE: followup\nANSWER: 정책 평가 순서\n\n거부가 먼저 평가됩니다."},
           {"type": "analysis_done", "id": 16, "text": "TYPE: followup\nANSWER: 정책 평가 순서\n\n거부가 먼저 평가됩니다.", "usage": {}, "cost_usd": None, "engine": "local", "sent": [], "stages": {}, "elapsed": 1.0})
    p.wait(300)
    txt = text_of(p, 14)
    check("a retry the watching started under it waits with the rest", "다시 푼 답 열쇠말" not in txt, txt[-200:])
    check("...a follow-up asked about it shows", "정책 평가 순서" in txt and "왜 거부가 먼저인가요?" in txt, txt[-200:])
    check("...with its own reply in its answer row, never the answer line kept back", "단계 답" not in txt
          and p.js("() => entryEl(14).querySelector('[data-turn=\"16\"] [data-aval]')?.textContent") == "정책 평가 순서", txt[-200:])
    check("Practice told the server nothing: every message since it was turned on was the page's own", p.js("(n) => window.__sent.slice(n).map((m) => m.type)", sent) == ["problem_text"],
          p.js("(n) => window.__sent.slice(n)", sent))
    # A reload: what was kept back stays so, as far as it was opened; what was opened stays open; what came before stays as it was.
    # The server keeps the answers (its /history), one more of them answered while the page was closed, and one from before Practice
    stamp = {i: p.js("(i) => items.get(i).ts / 1000", i) for i in (11, 12, 13, 14)}
    s.rows = [old, row(11, "short", "첫 물음", "보이는 답", "보이는 풀이입니다", ago=time.time() - stamp[11]),
              {**row(12, "algorithm", "두 수의 합을 이루는 두 인덱스", HEADED_KEY, HEADED, ago=time.time() - stamp[12])},
              row(13, "short", "한 문단짜리", "한 줄 답", ONE, ago=time.time() - stamp[13]),
              {**row(14, "work", "단계로 푸는 물음", "단계 답", STEPS, ago=time.time() - stamp[14]),
               "turns": [{"id": 15, "q": "", "text": "TYPE: work\nANSWER: 다시 푼 답 열쇠말\n\n다시 푼 풀이", "retry": True, "kind": "retry"},
                         {"id": 16, "q": "왜 거부가 먼저인가요?", "text": "TYPE: followup\nANSWER: 정책 평가 순서\n\n거부가 먼저 평가됩니다.", "retry": False, "kind": "ask"}]},
              row(17, "math", "닫혀 있던 동안 푼 물음", "닫힌 동안의 답", "닫힌 동안의 풀이", ago=1)]
    p.page.reload(wait_until="load")
    p.wait(150)
    p.open_messages()
    p.wait(700)
    states = {i: held_state(p, i) for i in (10, 11, 12, 13, 14, 17)}
    check("reloaded: what came before Practice shows as it did", not states[10]["held"] and not states[11]["held"] and "보이는 답" in text_of(p, 11), states)
    check("...the one opened in full stays open", not states[12]["held"] and HEADED_KEY in text_of(p, 12), states[12])
    check("...the ones kept back stay so, as far as they were opened", states[13]["held"] and states[14]["held"] and states[14]["count"] == "힌트 4개 중 1개"
          and [w in text_of(p, 14) for w in STEP_WORDS] == [True, False, False, False], [states[13], states[14]])
    check("...the retry under it still waits, the follow-up still shows", "다시 푼 답 열쇠말" not in text_of(p, 14) and "정책 평가 순서" in text_of(p, 14), text_of(p, 14)[-200:])
    check("an answer the server gave while the page was closed, after Practice was turned on, is kept back too", states[17]["held"] and "닫힌 동안의 답" not in text_of(p, 17), states[17])
    # Off: everything as it was; on again: what was kept back is again, and what was opened stays open
    menu_pick(p, "off")
    check("off: every answer shows whole again", not any(held_state(p, i)["held"] for i in (12, 13, 14, 17)) and "한 줄 답" in text_of(p, 13) and "닫힌 동안의 답" in text_of(p, 17))
    check("...and the server's retry with it", "다시 푼 답 열쇠말" in text_of(p, 14), text_of(p, 14)[-200:])
    menu_pick(p, "on")
    check("on again: those it kept back are kept back again, those opened stay open", held_state(p, 13)["held"] and held_state(p, 14)["held"] and not held_state(p, 12)["held"])
    # Two more answers: the one kept back is now older than the three that stay open
    p.answer(19, "short", "열아홉째 물음", "열아홉째 답", "풀이")
    p.answer(20, "short", "스무째 물음", "스무째 답", "풀이")
    p.wait(300)
    check("an older answer kept back is not folded to its answer line", p.js("() => olderThanOpen(items.get(13)) && !entryEl(13).classList.contains('folded') && !entryEl(13).querySelector('[data-fold]')")
          and "한 줄 답" not in text_of(p, 13), text_of(p, 13))
    # What it keeps is capped, the oldest going first
    capped = p.js("""() => { for (let i = 0; i < 450; i++) practiceCards.set(`x${i}`, 0); keepCards();
        const kept = JSON.parse(localStorage.getItem('sidenote-practice-cards')); return [kept.length, kept[kept.length - 1][0], kept.some(([id]) => id === 'x0')]; }""")
    check("what it remembers stops at 400 answers, the oldest going first", capped == [400, "x449", False], capped)
    no_errors(p, "practice")
    p.close()


# ---------------------------------------------------------------- where what is kept back ends, and the keys at the edges of the sheets
# A solution that gives its answer under each form the models write it in: the hints end before SECRET in every one
SECRET = "③ 숨은 값"
STEPS_BEFORE = "## 풀이\n\n첫 단계입니다.\n\n## 계산\n\n둘째 단계입니다.\n\n"
GIVEN = {"bold in a heading": STEPS_BEFORE + f"## **정답**\n\n{SECRET}", "final in a heading": STEPS_BEFORE + f"## 최종 정답\n\n{SECRET}",
         "numbered heading": STEPS_BEFORE + f"## 3. 정답\n\n{SECRET}", "numbered bold": f"**풀이**\n\n첫 단계입니다.\n\n**계산**\n\n둘째 단계입니다.\n\n**3. 정답**\n\n{SECRET}",
         "number before bold": f"1. **풀이**: 첫 단계입니다.\n2. **계산**: 둘째 단계입니다.\n3. **정답**\n\n{SECRET}",
         "list item": f"- 첫 단계입니다.\n- 둘째 단계입니다.\n- 정답: {SECRET}", "plain with a colon": f"첫 단계입니다.\n\n둘째 단계입니다.\n\n정답: {SECRET}",
         "plain sentence": f"첫 단계입니다.\n\n둘째 단계입니다.\n\n정답은 {SECRET}입니다", "closing sentence": f"첫 단계입니다.\n\n둘째 단계입니다.\n\n따라서 정답은 {SECRET}입니다",
         "lower heading": "## 풀이\n\n첫 단계입니다.\n\n## 살필 점\n\n둘째 단계입니다.\n\n### 정답\n\n" + SECRET,
         "answer and explanation": STEPS_BEFORE + f"## 정답 및 해설\n\n{SECRET}", "answer with working": STEPS_BEFORE + f"## 정답과 풀이\n\n{SECRET}",
         "english": "## Approach\n\nThe first step.\n\n## Working\n\nThe second step.\n\n## The answer\n\n" + SECRET,
         "inside a part": f"## 풀이\n\n첫 단계입니다.\n\n## 계산\n\n둘째 단계입니다.\n정답: {SECRET}"}
# Lines that only mention such a word end nothing: each of these has all its parts as hints
NOT_GIVEN = {"## 준비\n\n첫 문단입니다.\n\n## Answer format\n\n둘째 문단입니다.\n\n## 계산\n\n셋째 문단입니다.": 3,
             "정답 확인을 위해 표를 봅니다.\n\n둘째 문단입니다.": 2, "## 답 구하기\n\n첫 문단입니다.\n\n## 결론 도출 과정\n\n둘째 문단입니다.": 2,
             "## 풀이\n\n첫 문단입니다.\n\n```python\n# 정답: 코드의 주석\nprint(1)\n```\n\n## 복잡도\n\n둘째 문단입니다.": 2,
             "**답변 요령**\n\n첫 문단입니다.\n\n**결론적으로 볼 점**\n\n둘째 문단입니다.": 2}


def group_edges(br, s):
    if not T.group("edges"):
        return
    p = Page(br, s, [row(i, "essay", f"이전 물음 {i}", f"이전 답 {i}", "이전 풀이입니다", ago=900 - i) for i in range(1, 4)], w=1400, h=700)
    p.js("() => setPractice(true)")
    # Every hint out, by the page's own path: what shows then is all a student can get without asking for the answer
    all_hints = "(i) => { const it = items.get(i); while (showHint(it)); return entryEl(i).innerText; }"
    for n, (name, body) in enumerate(GIVEN.items()):
        i = 400 + n
        p.answer(i, "work", f"물음 {i}", "열쇠", body)
        p.wait(60)
        seen = p.js(all_hints, i)
        check(f"given as {name}: every hint out, the answer still kept back", SECRET not in seen, seen[-160:])
        check(f"...and {name} opens with Show the answer", p.js("(i) => { showAnswer(items.get(i)); return entryEl(i).innerText; }", i).count(SECRET) >= 1)
    for n, (body, parts) in enumerate(NOT_GIVEN.items()):
        i = 430 + n
        p.answer(i, "work", f"물음 {i}", "열쇠", body)
        p.wait(60)
        check(f"a line that only mentions the word ends no hint: {body[:24]!r}", p.js("(i) => practiceParts(items.get(i)).length", i) == parts,
              p.js("(i) => practiceParts(items.get(i))", i))
    # A shell's $$ in a sentence opens no formula, and a set formula with a blank line in it is still not cut
    p.answer(440, "work", "셸 물음", "열쇠", "## 첫째\n\n첫 문단입니다.\n\n## 셸\n\n`$$`는 셸의 PID입니다.\n\n## 셋째\n\n셋째 문단입니다.\n\n## 넷째\n\n넷째 문단입니다.")
    p.answer(441, "work", "수식 물음", "열쇠", "첫 문단입니다.\n\n$$\na = 1\n\nb = 2\n$$\n\n끝 문단입니다.")
    p.wait(60)
    check("`$$` in inline code leaves the parts after it apart", p.js("() => practiceParts(items.get(440)).length") == 4, p.js("() => practiceParts(items.get(440))"))
    cuts = p.js("() => { const b = items.get(441).head.body; return practiceParts(items.get(441)).map((c) => b.slice(0, c).split('$$').length % 2 === 1); }")
    check("...and a formula on lines of its own is still never cut inside", cuts and all(cuts), cuts)
    # The thinking line stands before the answer has a card to keep it back
    p.js("() => { manualUntil = Date.now() + 5000; }")
    thinking = [{"type": "analysis_start", "id": 450, "ts": p.js("() => Date.now() / 1000"), "thumb": None, "transcript": "", "pages": 0, "trigger": "screen"},
                {"type": "stage", "id": 450, "stage": "think", "thought": "따라서 값은 3이다."}]
    p.send(*thinking)
    p.wait(150)
    line = "() => [...document.querySelectorAll('[data-thought]')].filter((x) => !x.hidden && x.offsetParent).map((x) => x.textContent)"
    check("with Practice on the thinking line is not shown", p.js(line) == [], p.js(line))
    p.js("() => setPractice(false)")
    p.send({"type": "stage", "id": 450, "stage": "think", "thought": "따라서 값은 4이다."})
    p.wait(150)
    check("...with it off it is", p.js(line) == ["따라서 값은 4이다."], p.js(line))
    p.js("() => { dropItem(items.get(450)); setPractice(true); }")
    # Words selected in the answer put off a redraw: h and a show at once
    p.answer(451, "work", "선택할 물음", "열쇠", "## 첫째\n\n첫 문단입니다.\n\n## 둘째\n\n둘째 문단입니다.\n\n## 셋째\n\n셋째 문단입니다.")
    p.wait(100)
    pick = """() => { goTo(451); const r = document.createRange(); r.selectNodeContents(entryEl(451).querySelector('[data-asked]'));
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); }"""
    p.js(pick)
    p.wait(80)
    p.page.keyboard.press("h")
    p.wait(120)
    check("h with words selected in the answer: the hint shows at once", "첫 문단입니다" in text_of(p, 451) and held_state(p, 451)["count"] == "힌트 3개 중 1개", held_state(p, 451))
    p.js(pick)
    p.wait(80)
    p.page.keyboard.press("a")
    p.wait(120)
    check("a with words selected in it: the answer shows at once", "셋째 문단입니다" in text_of(p, 451) and not held_state(p, 451)["held"], held_state(p, 451))
    p.js("() => setPractice(false)")
    # A list open when a sheet opens goes, so its keys choose nothing behind the sheet
    p.js("() => document.querySelector('.combo-btn[data-proxy=hist-kind]').click()")
    p.wait(80)
    p.page.keyboard.press("?")
    p.wait(100)
    p.page.keyboard.press("ArrowDown")
    p.wait(80)
    state = "() => ({ sheet: !$('keys-overlay').hidden, list: !!comboOpen, inside: !!document.activeElement.closest('#keys') })"
    check("? with a list open: the list goes, and the keyboard stays in the sheet", p.js(state) == {"sheet": True, "list": False, "inside": True}, p.js(state))
    p.page.keyboard.press("Enter")   # the sheet's close key has the keyboard: this closes the sheet, and chooses no filter behind it
    p.wait(100)
    check("...and Enter chooses nothing behind the sheet", p.js("() => histKind") == "", p.js("() => histKind"))
    p.page.route("**/heard*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
        {"days": [{"day": "2026-11-04", "n": 200, "first": 1793800000, "last": 1793800200}], "day": "2026-11-04",
         "lines": [{"ts": 1793800000 + i, "text": f"문장 {i}"} for i in range(200)]})))
    p.js("() => document.querySelector('.combo-btn[data-proxy=hist-kind]').click()")
    p.wait(80)
    p.js("() => openHeard()")
    p.wait(250)
    check("...and when the sheet of what was heard opens", not p.js("() => !!comboOpen"))
    # Each list is reached with Tab and scrolled by the keys, with Tab still inside its sheet
    for _ in range(4):
        p.page.keyboard.press("Tab")
    check("the sheet of what was heard: Tab reaches its sentences", p.js("() => document.activeElement.id") == "heard-lines", p.js("() => document.activeElement.id"))
    p.page.keyboard.press("End")
    p.wait(250)
    check("...and End goes down them", p.js("() => $('heard-lines').scrollTop") > 500, p.js("() => $('heard-lines').scrollTop"))
    p.page.keyboard.press("Tab")
    check("...and Tab goes round to the close key", p.js("() => document.activeElement.id") == "heard-close", p.js("() => document.activeElement.id"))
    p.page.keyboard.press("Escape")
    p.wait(80)
    p.page.set_viewport_size({"width": 800, "height": 300})
    p.wait(80)
    p.js("() => { document.activeElement?.blur?.(); openKeys(); }")
    p.wait(80)
    p.page.keyboard.press("Tab")
    p.page.keyboard.press("End")
    p.wait(250)
    check("the keys' sheet in a low window: Tab and End reach its last rows", p.js("() => document.querySelector('.keys-list').scrollTop") > 50, p.js("() => document.querySelector('.keys-list').scrollTop"))
    p.page.keyboard.press("Escape")
    p.page.set_viewport_size({"width": 1400, "height": 700})
    p.wait(80)
    # / into the search, Escape out of it with its words kept
    p.page.keyboard.press("/")
    p.page.keyboard.type("이전")
    p.wait(80)
    p.page.keyboard.press("Escape")
    p.wait(80)
    check("Escape leaves the search and keeps its words", p.js("() => [document.activeElement.id, $('hist-q').value]") == ["", "이전"], p.js("() => [document.activeElement.id, $('hist-q').value]"))
    before = p.js("() => viewId")
    p.page.keyboard.press("k")
    p.wait(200)
    check("...and the letters are keys again", p.js("() => $('hist-q').value") == "이전" and p.js("() => viewId") != before, [before, p.js("() => viewId"), p.js("() => $('hist-q').value")])
    p.js("() => { const q = $('hist-q'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); }")
    # Drawing a region: no key starts anything behind it, and Escape still ends it
    p.js("() => { document.activeElement?.blur?.(); window.__sent.length = 0; drawing = { url: '', start: null, box: null }; }")
    for key in "rpj?":
        p.page.keyboard.press(key)
    p.wait(80)
    check("while a region is drawn r and p send nothing, and ? opens no sheet", p.js("() => [window.__sent.length, $('keys-overlay').hidden]") == [0, True], p.js("() => [window.__sent, $('keys-overlay').hidden]"))
    p.page.keyboard.press("Escape")
    check("...and Escape ends it", p.js("() => drawing") is None)
    # The keyboard after a sheet opened from Export's menu, and after the band's close key
    p.js("() => $('hist-export').focus()")
    p.page.keyboard.press("Enter")
    p.wait(80)
    p.page.keyboard.press("?")
    p.wait(80)
    p.page.keyboard.press("Escape")
    p.wait(80)
    check("the keys' sheet opened from Export's menu gives the keyboard back to Export", p.js("() => document.activeElement.id") == "hist-export", p.js("() => document.activeElement.id"))
    p.send({"type": "status", "update": {"version": "9.9.9", "url": "https://github.com/kanggu12/sidenote/releases/tag/v9.9.9"}})
    p.wait(80)
    p.js("() => document.querySelector('[data-act=update-hide]').focus()")
    p.page.keyboard.press("Enter")
    p.wait(80)
    check("the band's close key pressed: the keyboard goes to the bar's key above it", p.js("() => document.activeElement.id") == "more" and not p.js("() => !!document.querySelector('[data-act=update-hide]')"),
          p.js("() => document.activeElement.tagName"))
    # A carriage return alone would end a line of the Anki file
    p.answer(460, "work", "", "열쇠", "풀이입니다")
    p.js("() => { const it = items.get(460); it.head.asked = ''; it.trigger = 'voice'; it.transcript = '앞\\r뒤'; }")
    with p.page.expect_download() as got:
        p.js("() => exportAnki()")
    raw = Path(got.value.path()).read_bytes().decode("utf-8")
    check("a carriage return alone in a field does not reach the Anki file", "\r" not in raw and "앞<br>뒤" in raw, repr(raw[-120:]))
    no_errors(p, "edges")
    p.close()


# ---------------------------------------------------------------- the keys
KEYS = ["j", "k", "c", "r", "p", "/", "h", "a", "?", "Esc"]
WORDS_KO = ["다음 답", "이전 답", "정답 한 줄 복사", "다시 분석", "일시정지 또는 계속하기", "답 찾기", "힌트 보기", "정답 보기", "단축키", "닫기"]
WORDS_EN = ["Next answer", "Previous answer", "Copy the one-line answer", "Reanalyze", "Pause or continue", "Find an answer", "Show a hint", "Show the answer",
            "Keyboard shortcuts", "Close"]


def press_js(p, key, code, **mods):
    """A key as the page hears it, with modifiers a browser would keep for itself if they were pressed for real."""
    p.js("([key, code, mods]) => document.body.dispatchEvent(new KeyboardEvent('keydown', { key, code, bubbles: true, cancelable: true, ...mods }))", [key, code, mods])
    p.wait(120)


def group_keys(br, s):
    if not T.group("keys"):
        return
    rows = [row(200 + i, "essay", f"물음 {i}", f"열쇠말 {i}", "풀이입니다\n\n" + "문단입니다. " * 80, ago=600 - i * 60) for i in range(5)]
    p = Page(br, s, rows, w=1600, h=900)
    spy(p)
    view = lambda: p.js("() => viewId")   # noqa: E731
    ribbon = lambda: p.js("() => idOf(document.querySelector('#history .h[aria-current=\"true\"]')?.dataset.id)")   # noqa: E731
    check("at first the newest answer is the current one", view() == 204, view())
    p.page.keyboard.press("k")
    p.wait(500)
    top = p.js("() => entryEl(203).getBoundingClientRect().top - document.querySelector('header.bar').getBoundingClientRect().bottom")
    check("k: the answer before it is the current one, the contents' ribbon on it", view() == 203 and ribbon() == 203, [view(), ribbon()])
    check("...brought into view under the bar", -2 <= top <= 60, top)
    p.page.keyboard.press("k")
    p.wait(450)
    p.page.keyboard.press("j")
    p.wait(450)
    check("k again, then j: back to the one after", view() == 203, view())
    for _ in range(3):
        p.page.keyboard.press("j")
        p.wait(450)
    check("j past the last stays on the last", view() == 204, view())
    folded = p.js("() => [entryEl(200).classList.contains('folded'), unfolded.has(200)]")
    for _ in range(4):
        p.page.keyboard.press("k")
        p.wait(450)
    check("k down to the first, and a folded answer gone past stays folded", view() == 200 and folded == [True, False] and p.js("() => entryEl(200).classList.contains('folded')"),
          [view(), folded, p.js("() => entryEl(200).classList.contains('folded')")])
    p.page.keyboard.press("c")
    p.wait(150)
    check("c: the current answer's answer line, as its Copy key copies it", p.js("() => window.__copied") == ["열쇠말 0"], p.js("() => window.__copied"))
    check("...said on its key", p.js("() => entryEl(200).querySelector('[data-copy-answer]').textContent.trim()") == "복사됨",
          p.js("() => entryEl(200).querySelector('[data-copy-answer]').textContent.trim()"))
    p.js("() => { window.__sent.length = 0; }")
    p.page.keyboard.press("r")
    p.wait(120)
    check("r: Reanalyze", p.js("() => window.__sent.map((m) => m.type)") == ["reanalyze"], p.js("() => window.__sent"))
    p.page.keyboard.press("p")
    p.wait(120)
    p.send({"type": "status", "paused": True})
    p.wait(80)
    p.page.keyboard.press("p")
    p.wait(120)
    check("p: Pause, and Continue while paused", p.js("() => window.__sent.map((m) => m.type)") == ["reanalyze", "pause", "resume"], p.js("() => window.__sent"))
    p.send({"type": "status", "paused": False})
    p.page.keyboard.press("/")
    p.wait(150)
    check("/: the contents' search has the keyboard", p.js("() => document.activeElement?.id") == "hist-q", p.js("() => document.activeElement?.id"))
    # Typing in a field: the letters are typed, nothing else happens
    before = (view(), p.js("() => window.__sent.length"))
    p.page.keyboard.type("jkrp")
    p.wait(150)
    check("typed in the search, the letters go into it and do nothing else", p.js("() => $('hist-q').value") == "jkrp" and (view(), p.js("() => window.__sent.length")) == before,
          [p.js("() => $('hist-q').value"), view(), p.js("() => window.__sent")])
    p.js("() => { const q = $('hist-q'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); q.blur(); }")
    p.page.focus("#ask")
    p.page.keyboard.type("jkc/")
    p.wait(150)
    check("typed in the question box, the same", p.js("() => $('ask').value") == "jkc/" and view() == before[0] and p.js("() => window.__copied.length") == 1,
          [p.js("() => $('ask').value"), view(), p.js("() => window.__copied")])
    p.js("() => { $('ask').value = ''; $('ask').blur(); }")
    # Modifiers held: nothing (sent as the page would hear them; for real, Ctrl+R is the browser's reload)
    for mods in ({"ctrlKey": True}, {"altKey": True}, {"metaKey": True}):
        n = p.js("() => window.__sent.length")
        press_js(p, "r", "KeyR", **mods)
        press_js(p, "k", "KeyK", **mods)
        check(f"with {list(mods)[0][:-3]} held, r and k do nothing", p.js("() => window.__sent.length") == n and view() == 200, [view(), p.js("() => window.__sent")])
    press_js(p, "J", "KeyJ", shiftKey=True)
    check("Shift with a letter is no shortcut", view() == 200, view())
    press_js(p, "ㅓ", "KeyJ")
    p.wait(350)
    check("a Korean keyboard's ㅓ is the j key", view() == 201, view())
    # The sheet: ? opens it, and Escape, ? and its close key shut it
    p.page.keyboard.press("?")
    p.wait(200)
    sheet = p.js("""() => ({ open: !$('keys-overlay').hidden, focus: document.activeElement?.id, keys: [...document.querySelectorAll('#keys kbd')].map((k) => k.textContent),
                             words: [...document.querySelectorAll('#keys .set .lbl')].map((x) => x.textContent.trim()), title: $('keys-title').textContent })""")
    check("?: the keys' sheet, with the keyboard on its close key", sheet["open"] and sheet["focus"] == "keys-close", sheet)
    check("...each key and what it does, in Korean on a Korean page", sheet["keys"] == KEYS and sheet["words"] == WORDS_KO and sheet["title"] == "단축키", sheet)
    p.page.keyboard.press("j")
    p.wait(200)
    check("...and with it open the keys behind it do nothing", view() == 201, view())
    p.page.keyboard.press("Tab")
    p.page.keyboard.press("Tab")   # its list of keys takes the keyboard too, so it scrolls in a low window; then round to the close key
    check("...Tab stays inside it", p.js("() => document.activeElement?.id") == "keys-close", p.js("() => document.activeElement?.id"))
    p.page.keyboard.press("?")
    p.wait(150)
    check("? again shuts it", p.js("() => $('keys-overlay').hidden"))
    p.page.keyboard.press("?")
    p.wait(150)
    p.page.keyboard.press("Escape")
    p.wait(150)
    check("Escape shuts it", p.js("() => $('keys-overlay').hidden"))
    p.page.click("#more")
    p.page.click("#open-keys")
    p.wait(200)
    check("the gear menu's Keyboard shortcuts opens it", p.js("() => !$('keys-overlay').hidden && $('menu').hidden"))
    p.page.click("#keys-close")
    p.wait(150)
    check("...and its close key shuts it, the keyboard back on the gear", p.js("() => $('keys-overlay').hidden && document.activeElement?.id === 'more'"), p.js("() => document.activeElement?.id"))
    # Inside the settings sheet, and with Export's menu open: nothing
    p.js("() => openSettings()")
    p.wait(150)
    p.page.keyboard.press("k")
    p.wait(200)
    check("in the settings sheet the keys do nothing", view() == 201 and p.js("() => !$('settings-overlay').hidden"), view())
    p.page.keyboard.press("Escape")
    p.page.locator("#hist-export").scroll_into_view_if_needed()   # where the reader goes to press it
    p.page.click("#hist-export")
    p.wait(150)
    was = view()
    p.page.keyboard.press("k")
    p.wait(200)
    check("with Export's menu open the letters are its own: nothing moves", view() == was and p.js("() => !$('export-menu').hidden"), [was, view()])
    p.page.keyboard.press("Escape")
    p.wait(100)
    # h and a: Practice's keys on the current answer
    p.js("() => setPractice(true)")
    p.answer(210, "algorithm", "키로 푸는 물음", "키로 본 답", HEADED)
    p.wait(300)
    p.js("() => { goLatest(); }")
    p.wait(500)
    check("in practice mode the newest is kept back and current", view() == 210 and held_state(p, 210)["held"], [view(), held_state(p, 210)])
    p.page.keyboard.press("h")
    p.wait(250)
    check("h: the next hint of the current answer", held_state(p, 210)["count"] == "힌트 3개 중 1개" and PARTS[0] in text_of(p, 210), held_state(p, 210))
    p.page.keyboard.press("a")
    p.wait(250)
    check("a: its answer", not held_state(p, 210)["held"] and "키로 본 답" in text_of(p, 210), held_state(p, 210))
    p.js("() => { window.__toasts.length = 0; }")
    p.page.keyboard.press("h")
    p.wait(150)
    check("h on an answer not kept back does nothing", p.js("() => window.__toasts.length") == 0 and not held_state(p, 210)["held"])
    no_errors(p, "keys")
    p.close()
    # The sheet in English on an English page
    p = Page(br, s, rows[:1], w=1280, h=800, locale=EN)
    p.page.keyboard.press("?")
    p.wait(200)
    words = p.js("() => [...document.querySelectorAll('#keys .set .lbl')].map((x) => x.textContent.trim())")
    check("the sheet in English on an English page", words == WORDS_EN and p.js("() => $('keys-title').textContent") == "Keyboard shortcuts", words)
    p.page.keyboard.press("Escape")
    # And the rest of these features' words: the menu, an answer Practice keeps back, Export's menu, their tooltips
    # (a language named in its own words, lang="ko", is the menu's Language and stays Korean)
    hangul = """(sel) => { const H = /[\\u3131-\\u318e\\uac00-\\ud7a3]/, out = [];
        for (const e of document.querySelectorAll(sel)) {
          const c = e.cloneNode(true); c.querySelectorAll('[lang="ko"]').forEach((x) => x.remove());
          if (H.test(c.textContent || '')) out.push(c.textContent.trim().slice(0, 60));
          for (const x of [e, ...e.querySelectorAll('[title], [aria-label]')]) for (const a of ['title', 'aria-label']) if (H.test(x.getAttribute(a) || '')) out.push(x.getAttribute(a).slice(0, 60)); }
        return out; }"""
    p.js("() => setPractice(true)")
    p.answer(220, "algorithm", "Find the two indices", "a hash map, one pass", "## Idea\n\nKeep what was seen.\n\n## Cost\n\nOne pass.\n")
    p.answer(221, "short", "Being written", "one", "two", final=False)
    p.wait(250)
    p.page.click("#more")
    p.wait(150)
    seen = {"the menu": p.js(hangul, "#menu"), "the answers kept back": p.js(hangul, ".entry[data-id='220'] .row.practice, .entry[data-id='221'] .row.practice")}
    check("English: Practice and Keyboard shortcuts in the menu", p.js("() => [...document.querySelectorAll('#practice-seg button')].map((b) => b.textContent.trim()).concat($('open-keys').textContent.trim())")
          == ["Off", "On", "Keyboard shortcuts"])
    p.page.keyboard.press("Escape")
    p.page.locator("#hist-export").scroll_into_view_if_needed()
    p.page.click("#hist-export")
    p.wait(150)
    seen["Export's menu"] = p.js(hangul, "#export-menu, #hist-export")
    check("English: no Hangul in these features' words", not any(seen.values()), seen)
    check("English: an answer kept back says so in English", p.js("() => entryEl(221).querySelector('.row.practice').innerText.includes('Writing the answer · hidden in practice mode')")
          and p.js("() => entryEl(220).querySelector('.hint-n').textContent") == "2 hints")
    no_errors(p, "keys in English")
    p.close()


# ---------------------------------------------------------------- Export to Anki
TAB_CODE = "```go\nfunc main() {\n\tfmt.Println(\"a\\tb\")\n}\n```\n\n뒤의 글"
ANKI_ROWS = [
    # [id, kind, asked, answer line, body]
    (300, "coding", "두 수의 합을 구하는 함수를 쓰시오", "사전 한 번, 시간 $O(n)$", "```python\ndef two_sum(nums, target):\n    seen = {}\n    return seen\n```\n\n## 다음\n\n둘째 부분"),
    (301, "math", "근의 공식을 쓰시오", "$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$", "| 항 | 값 |\n|---|---|\n| a | 1 |\n| b | \"2\" |\n\n$$\nb^2 - 4ac\n$$\n\n둘째 문단"),
    (302, "work", "#include 는 무엇을 하나요?", "머리 파일을 그 자리에 넣습니다", "$$\na^2 + b^2 = c^2\n$$\n\n둘째 문단"),
    (303, "short", "\"hello\" 의 길이는?", "5", "따옴표 \"안의\" 글자 수입니다.\n\n둘째 문단"),
    (304, "algorithm", "탭이 든 코드", "탭은 그대로", TAB_CODE),
]


class Fields(HTMLParser):
    """The text of a field's HTML and the tags it opens, as a browser would read them."""

    def __init__(self):
        super().__init__()
        self.text, self.tags = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


def read_html(field):
    f = Fields()
    f.feed(field)
    return "".join(f.text), f.tags


def anki_rows(text):
    """The file as Anki reads it: the lines that start with # are its headers, and the rest tab-separated fields, a quote mark at a
    field's start opening a quoted one (Python's csv reads them as the csv crate Anki uses does)."""
    lines = text.split("\n")
    heads = [ln for ln in lines if ln.startswith("#")]
    data = [ln for ln in lines if ln and not ln.startswith("#")]
    return heads, data, list(csv.reader(io.StringIO("\n".join(data)), delimiter="\t"))


def group_review(br, s):
    """Starred chosen in the contents with Practice on: the starred answers, old as they are, are kept back for a review."""
    if not T.group("review"):
        return
    rows = [row(20, "essay", "별표 물음", "별표 열쇠말", ONE, ago=7200, starred=True),
            row(21, "essay", "보통 물음", "보통 열쇠말", ONE, ago=7100)]
    p = Page(br, s, rows, w=1400, h=900)
    p.js("() => setPractice(true)")
    p.wait(150)
    check("Practice on its own leaves answers from before it as they were", not held_state(p, 20)["held"] and not held_state(p, 21)["held"],
          [held_state(p, 20), held_state(p, 21)])
    p.js("() => { const d = $('hist-day'); d.value = 'starred'; d.dispatchEvent(new Event('change')); }")
    p.wait(600)
    check("with Starred chosen, the starred answer is kept back for a review", held_state(p, 20)["held"], held_state(p, 20))
    p.js("() => showAnswer(items.get(20))")
    p.wait(100)
    check("...and opens when asked, as a new one does", not held_state(p, 20)["held"], held_state(p, 20))
    p.js("() => { const d = $('hist-day'); d.value = ''; d.dispatchEvent(new Event('change')); }")
    p.wait(300)
    p.js("() => setPractice(false)")
    p.js("() => { const d = $('hist-day'); d.value = 'starred'; d.dispatchEvent(new Event('change')); }")
    p.wait(400)
    check("with Practice off, Starred shows its answers", not held_state(p, 20)["held"], held_state(p, 20))
    p.js("() => setPractice(true)")
    p.wait(150)
    check("turned on with Starred chosen, the one opened before is kept back again, the unstarred one not",
          held_state(p, 20)["held"] and not p.js("() => held(items.get(21))"), [held_state(p, 20), p.js("() => held(items.get(21))")])
    p.close()


def group_anki(br, s):
    if not T.group("anki"):
        return
    rows = [row(i, kind, asked, key, body, ago=600 - n * 60) for n, (i, kind, asked, key, body) in enumerate(ANKI_ROWS)]
    rows.append({**row(305, "short", "", "들은 문제의 답", "들은 문제의 풀이", ago=100), "trigger": "voice", "transcript": "스택과 큐의 차이는?"})
    p = Page(br, s, rows, w=1600, h=1000)
    p.send({"type": "error", "id": 306, "text": "분석 실패", "hint": "timeout"})   # a failure that wrote nothing: in the Markdown, no card for it
    p.wait(150)
    # The key opens a menu of the two files, held to the window under it
    p.page.locator("#hist-export").scroll_into_view_if_needed()
    p.page.click("#hist-export")
    p.wait(200)
    menu = p.js("""() => { const m = $('export-menu'), k = $('hist-export').getBoundingClientRect(), r = m.getBoundingClientRect();
        return { open: !m.hidden, role: m.getAttribute('role'), items: [...m.querySelectorAll('[role=menuitem]')].map((b) => b.textContent.trim()),
                 expanded: $('hist-export').getAttribute('aria-expanded'), focus: document.activeElement?.dataset.export,
                 inside: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight, under: Math.abs(r.top - k.bottom - 6) < 1.5 || Math.abs(k.top - r.bottom - 6) < 1.5,
                 edge: Math.abs(r.right - k.right) < 1.5 || r.left === 8 || r.right === innerWidth - 8 }; }""")
    check("Export opens a menu of Markdown and Anki, the keyboard on the first", menu["open"] and menu["role"] == "menu" and menu["items"] == ["Markdown", "Anki"]
          and menu["expanded"] == "true" and menu["focus"] == "md", menu)
    check("...under its key, its right edge on the key's, inside the window", menu["inside"] and menu["under"] and menu["edge"], menu)
    p.page.keyboard.press("ArrowDown")
    check("...the arrows go along it", p.js("() => document.activeElement?.dataset.export") == "anki")
    p.page.keyboard.press("Escape")
    p.wait(100)
    check("...and Escape closes it, the keyboard back on the key", p.js("() => $('export-menu').hidden && document.activeElement?.id === 'hist-export'"))
    # Markdown, as before
    p.page.click("#hist-export")
    with p.page.expect_download() as dl:
        p.page.click("#export-menu [data-export='md']")
    md = Path(dl.value.path()).read_text(encoding="utf-8")
    entries = re.findall(r"^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} ", md, re.M)   # an answer's own heading: its time first
    check("Markdown from the menu: the file it always was, the failure in it", dl.value.suggested_filename.endswith(".md") and len(entries) == 7 and "ANSWER:" not in md
          and "분석 실패" in md, [len(entries), md[:120]])
    # Anki
    p.page.click("#hist-export")
    with p.page.expect_download() as dl:
        p.page.click("#export-menu [data-export='anki']")
    name = dl.value.suggested_filename
    text = Path(dl.value.path()).read_text(encoding="utf-8")
    heads, data, parsed = anki_rows(text)
    check("Anki: a .txt file", re.fullmatch(r"sidenote-anki-\d{8}-\d{4}\.txt", name) is not None, name)
    check("...that opens with Anki's headers", heads == ["#separator:tab", "#html:true", "#notetype:Basic", "#columns:Front\tBack\tTags", "#tags column:3"]
          and text.startswith("#separator:tab\n"), heads)
    check("...then a line for each answer Export takes, one that wrote nothing left out", len(data) == 6, len(data))
    check("...each of three fields, read as Anki reads them as they read split", all(len(r) == 3 for r in parsed) and parsed == [ln.split("\t") for ln in data],
          [r for r in parsed if len(r) != 3][:2])
    check("...no field opens as a comment or a quoted field, nor holds a carriage return", all(not f.startswith(("#", '"')) and "\r" not in f for r in parsed for f in r),
          [f for r in parsed for f in r if f.startswith(("#", '"'))][:3])
    by = {r[0]: r for r in parsed}
    fronts = [r[0] for r in parsed]
    check("the front is the question as the panel shows it", fronts[0] == "두 수의 합을 구하는 함수를 쓰시오" and fronts[2] == "&#35;include 는 무엇을 하나요?"
          and fronts[3] == "&quot;hello&quot; 의 길이는?" and fronts[5] == "스택과 큐의 차이는?", fronts)
    code = parsed[0][1]
    check("code: the answer line in bold, then its first part, the code as it is, with its line breaks as <br>",
          code.startswith("<b>") and "def two_sum(nums, target):<br>    seen = {}" in code and "둘째 부분" not in code and "<pre><code>" in code, code)
    check("...a formula in the answer line as its TeX, in the delimiters Anki's MathJax reads", "\\(O(n)\\)" in code, code)
    table = parsed[1][1]
    txt, tags = read_html(table)
    check("a table stays a table, its quote marks written as entities", "<table>" in table and "&quot;2&quot;" in table and "둘째 문단" not in table and "\\(x = \\frac{-b" in table, table)
    check("a formula on its own lines is \\[ \\], on one line", "\\[a^2 + b^2 = c^2\\]" in parsed[2][1], parsed[2][1])
    tab = parsed[4][1]
    check("a tab in code is its entity, and nothing past the first part comes", "&#9;fmt.Println(&quot;a\\tb&quot;)" in tab and "뒤의 글" not in tab, tab)
    every = [f for r in parsed for f in r[:2]]
    check("no picture in any field, nothing that runs", not any(re.search(r"<(img|svg|script|iframe|object|style)\b", f) for f in every), [f for f in every if "<img" in f][:1])
    check("every field's HTML reads back to its words", all(read_html(f)[0].strip() for f in every), [f for f in every if not read_html(f)[0].strip()][:2])
    today = time.strftime("%Y-%m-%d", time.localtime(time.time() - 600))
    check("tags: its type and its day", parsed[0][2] == f"코딩 {today}" and parsed[1][2].startswith("수학 "), [r[2] for r in parsed])
    check("...and it says how many it wrote", "답 6개 내보냄 (Anki)" in p.js("() => $('toast').textContent"), p.js("() => $('toast').textContent"))
    # What the contents list: a type chosen, a word searched for
    p.js("() => { const k = $('hist-kind'); k.value = 'math'; k.dispatchEvent(new Event('change')); }")
    p.wait(250)
    p.page.click("#hist-export")
    with p.page.expect_download() as dl:
        p.page.click("#export-menu [data-export='anki']")
    _, data, _ = anki_rows(Path(dl.value.path()).read_text(encoding="utf-8"))
    check("a type chosen in the contents: only those answers", len(data) == 1 and data[0].startswith("근의 공식을 쓰시오"), data)
    p.js("() => { const k = $('hist-kind'); k.value = ''; k.dispatchEvent(new Event('change')); const q = $('hist-q'); q.value = '없는말없는말'; q.dispatchEvent(new Event('input', { bubbles: true })); }")
    p.wait(250)
    p.js("() => { window.__dl = 0; const c = URL.createObjectURL; URL.createObjectURL = (b) => { window.__dl++; return c.call(URL, b); }; }")
    p.page.click("#hist-export")
    p.wait(150)
    check("nothing in view: it says so at once, with no menu and no file", p.js("() => [$('export-menu').hidden, window.__dl, $('toast').textContent]") == [True, 0, "내보낼 답 없음"],
          p.js("() => [$('export-menu').hidden, window.__dl, $('toast').textContent]"))
    no_errors(p, "anki")
    p.close()
    # An answer Practice keeps back goes into the file whole: Export is the user's own act
    p = Page(br, s, [], w=1400, h=900)
    p.js("() => setPractice(true)")
    p.answer(320, "short", "가려 둔 물음", "가려 둔 답", "가려 둔 풀이")
    p.wait(250)
    p.page.locator("#hist-export").scroll_into_view_if_needed()
    p.page.click("#hist-export")
    with p.page.expect_download() as dl:
        p.page.click("#export-menu [data-export='anki']")
    _, data, parsed = anki_rows(Path(dl.value.path()).read_text(encoding="utf-8"))
    check("an answer Practice keeps back is exported whole", held_state(p, 320)["held"] and parsed and "가려 둔 답" in parsed[0][1], parsed)
    no_errors(p, "anki and practice")
    p.close()


# ---------------------------------------------------------------- the words
class DataT(HTMLParser):
    """The words index.html asks translateDom for: each data-t element's own text (or the key it names), and the attributes data-t-* name."""

    def __init__(self):
        super().__init__()
        self.words, self.open = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for attr, data in (("title", "data-t-title"), ("aria-label", "data-t-aria"), ("placeholder", "data-t-placeholder"), ("alt", "data-t-alt")):
            if data in a and a.get(attr):
                self.words.append(a[attr])
        if "data-t" in a:
            self.open.append([a["data-t"] or "", ""])

    def handle_data(self, data):
        for o in self.open:
            if not o[1] and data.strip():
                o[1] = data.strip()

    def close(self):
        super().close()
        self.words += [key or text for key, text in self.open if key or text]


def group_words(br, s):
    if not T.group("words"):
        return
    p = Page(br, s, [], w=1280, h=800)
    korean = set(p.js("() => Object.keys(CATALOGS.ko)"))
    p.close()
    app = (h.PANEL / "app.js").read_text(encoding="utf-8")
    keys = {json.loads(m) for m in re.findall(r'\bt\(\s*("(?:[^"\\]|\\.)*")', app)}
    missing = sorted(k for k in keys if k not in korean)
    check(f"every word the panel's script asks t() for has its Korean ({len(keys)})", not missing, missing[:8])
    dom = DataT()
    dom.feed((h.PANEL / "index.html").read_text(encoding="utf-8"))
    dom.close()
    missing = sorted({w for w in dom.words if w not in korean})
    check(f"every word index.html has translated has its Korean ({len(dom.words)})", not missing, missing[:8])
    mine = ["Practice", "Practice: Off", "Practice: On", "Show a hint", "Show the answer", "Keyboard shortcuts", "Next answer", "Exported {n} answers (Anki)"]
    check("...these features' words among them", all(w in korean for w in mine) and all(w in keys or w in dom.words for w in mine), [w for w in mine if w not in korean])


def main() -> int:
    h.support.need_vendor(h.PANEL)   # exits with a word if the panel's libraries are missing
    s = Stand("study")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_practice, group_edges, group_keys, group_review, group_anki, group_words):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
