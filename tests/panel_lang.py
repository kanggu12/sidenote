"""The panel's language: English for an English browser, Korean for a Korean one or with ?lang=ko, and the language the
server is told before anything else.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_lang.py
    ONLY="english,korean,menu,download,marks" ...   # only the groups named

The other panel suites read the Korean words (their browsers ask for Korean, support.LOCALE). This one opens the
English page in the states a sitting goes through (the first page, answers of each kind, a dropped server, a pause,
a send to confirm, the menu, the settings sheet) and finds no Hangul in what it shows: the words, the tooltips, the
labels a screen reader reads and the style sheet's own words. What an answer says is the model's and is left out, and
so are the server's own words in the settings sheet (server/settings.py), which this page is given in a stand-in.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, row  # noqa: E402

T = h.Tally()
check = T.check
EN = "en-US"

# Where Hangul may stand on an English page: what an answer, a question or the speech says, the settings the server
# words itself, and a language's name in its own words (lang="ko": the menu's Language)
CONTENT = ".md, .asked, .q, .answer-text, #hear-text, .ptext, .ht, .alert.confirm pre, [lang='ko']"

# The visible text, the tooltips and the labels of the page that hold Hangul, outside `skip`
HANGUL_SEEN = """(skip) => {
  const HANGUL = /[\\u3131-\\u318e\\uac00-\\ud7a3]/, out = [];
  const away = (el) => !!el.closest(skip);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, el = n.parentElement;
    if (!el || !HANGUL.test(n.nodeValue) || away(el) || el.closest("script, style")) continue;
    // A box of words holds the person's own list, which names windows as their programs title them (시크릿, 사생활 보호)
    if (el.closest("textarea.words")) continue;
    if (!el.getClientRects().length) continue;   // not drawn
    out.push(`text: ${n.nodeValue.trim().slice(0, 90)} (${el.id || el.className || el.tagName})`);
  }
  for (const el of document.querySelectorAll("[title], [aria-label], [placeholder], [alt]")) {
    if (away(el)) continue;
    for (const a of ["title", "aria-label", "placeholder", "alt"]) {
      if (a === "title" && el.matches("#history .h")) continue;   // a contents row's tooltip is its answer's words
      const v = el.getAttribute(a);
      if (v && HANGUL.test(v)) out.push(`${a}: ${v.slice(0, 90)} (${el.id || el.className || el.tagName})`);
    }
  }
  for (const el of document.querySelectorAll(".shot, .toast")) {
    const c = getComputedStyle(el, "::after").content;
    if (HANGUL.test(c)) out.push(`::after ${c}`);
  }
  return out;
}"""

CODE = "Two pointers from both ends.\n\n```python\ndef two_sum(nums, target):\n    seen = {}\n    for i, x in enumerate(nums):\n        if target - x in seen:\n            return [seen[target - x], i]\n        seen[x] = i\n```"
TABLE = "| Option | Verdict | Why |\n|---|---|---|\n| A | Yes | connection oriented |\n| B | No | broadcast is UDP's |\n| C | Yes | ordered |"
CHART = 'The waits compared.\n\n```chart\n{"type": "bar", "title": "Waiting time", "unit": "ms", "x": ["P1", "P2", "P3"], "series": [{"name": "wait", "values": [4, 4, 2]}]}\n```'


def english_rows():
    return [row(201, "mcq", "Which is not true of TCP?", "4", TABLE, ago=900),
            row(202, "coding", "Return the two indices", "a hash map, one pass", CODE, ago=700),
            row(203, "short", "What does ACID stand for?", "ACID", "Atomicity, consistency, isolation, durability.", ago=500),
            row(204, "essay", "Stack and queue", "LIFO and FIFO", CHART, ago=300),
            row(205, "math", "Average wait", "10/3", "The average is (4 + 4 + 2) / 3.", ago=100)]


def hangul(p, skip=CONTENT):
    return p.js(HANGUL_SEEN, skip)


def english_settings():
    """The settings message with the server's words in a stand-in English: what stays Hangul is the panel's own."""
    msg = h.support.settings_message()
    meta = msg["meta"]
    meta["sections"] = [[sec, f"Section {sec}"] for sec, _ in meta["sections"]]
    for i in meta["items"]:
        i["label"], i["help"] = f"Label {i['key']}", f"Help {i['key']}"
        if i.get("options"):
            i["options"] = [[v, f"Option {v}"] for v, _ in i["options"]]
        if i.get("opt_help"):
            i["opt_help"] = {k: f"Option help {k}" for k in i["opt_help"]}
    return msg


def group_english(br, s):
    if not T.group("english"):
        return
    # The first page, connected
    p = Page(br, s, [], w=1920, h=1040, locale=EN)
    check("an English browser gets the English page (lang en)", p.js("() => [document.documentElement.lang, LANG]") == ["en", "en"],
          p.js("() => [document.documentElement.lang, LANG]"))
    check("its first words are English", p.js("() => [$('pause-text').textContent, $('reanalyze').textContent.trim(), $('settings-title').textContent]")
          == ["Pause", "Reanalyze", "Solver settings"], p.js("() => [$('pause-text').textContent, $('reanalyze').textContent.trim(), $('settings-title').textContent]"))
    check("the server is told English before anything else", p.js("() => window.__sent[0]") == {"type": "ui_lang", "lang": "en"},
          p.js("() => window.__sent.slice(0, 3)"))
    found = hangul(p)
    check("the first page shows no Hangul", not found, found[:6])
    p.js("() => $('more').click()")
    p.wait(200)
    found = hangul(p)
    check("nor does the menu", not found, found[:6])
    p.js("() => $('more').click()")
    # The server gone: the band, the cards and the checklist say so
    p.drop()
    p.wait(300)
    found = hangul(p)
    check("nor the page with the server gone", not found, found[:6])
    no_errors(p, "first page")
    p.close()

    # Answers of each kind, one being written, a pause, a send to confirm
    p = Page(br, s, english_rows(), w=1920, h=1040, locale=EN, settle=1200)
    found = hangul(p)
    check("answers of each kind: no Hangul outside what they say", not found, found[:6])
    check("the kinds are named in English", p.js("() => [...document.querySelectorAll('#history .hk')].map((x) => x.textContent)")
          == ["Math", "Essay", "Short", "Coding", "MCQ"],
          p.js("() => [...document.querySelectorAll('#history .hk')].map((x) => x.textContent)"))
    check("a date is written with an English weekday", p.js("() => fmtDay(new Date(2026, 10, 2, 12).getTime())") == "11.02(Mon)",
          p.js("() => fmtDay(new Date(2026, 10, 2, 12).getTime())"))
    p.answer(206, "algorithm", "Find the shortest path", "BFS", "Breadth first from the source.", final=False)
    p.send({"type": "status", "text": "connected", "paused": True, "lang": "en", "audio": True, "voice": True, "can_ask": True,
            "run_enabled": True, "runner": True, "engines": h.ENGINES})
    p.send({"type": "agent_confirm", "cid": "c1", "what": "the problem part", "timeout": 30, "ts": p.js("() => Date.now() / 1000"),
            "thumb": None, "text": "the problem as text"})
    p.wait(400)
    found = hangul(p)
    check("a live answer, a pause and a send to confirm: no Hangul", not found, found[:6])
    # The notices: the server's level when it gives one, its Korean words when it does not (an older server)
    tone = "() => $('toast').dataset.tone"
    p.send({"type": "notice", "text": "Could not load the model onto the GPU", "level": "warn"})
    warn = p.js(tone)
    p.send({"type": "notice", "text": "Loaded onto the GPU (12 s)", "level": "info"})
    info = p.js(tone)
    p.send({"type": "notice", "text": "GPU에 올리기 실패"})
    old = p.js(tone)
    check("a notice takes the server's level, and an older server's by its words", [warn, info, old] == ["warn", "info", "warn"], [warn, info, old])
    no_errors(p, "answers")
    p.close()

    # The settings sheet, every tab, with the server's words in a stand-in
    p = Page(br, s, english_rows()[:1], w=1600, h=1000, locale=EN)
    p.send(english_settings())
    p.js("() => openSettings()")
    p.wait(300)
    tabs = p.js("() => [...document.querySelectorAll('.set-tab')].map((b) => b.dataset.sec)")
    bad = []
    for sec in tabs:
        p.js("(sec) => document.querySelector(`.set-tab[data-sec='${sec}']`).click()", sec)
        p.wait(150)
        bad += [f"{sec}: {x}" for x in hangul(p)]
    check(f"the settings sheet, {len(tabs)} tabs: no Hangul of the panel's own", tabs and not bad, bad[:6])
    no_errors(p, "settings")
    p.close()


def group_korean(br, s):
    if not T.group("korean"):
        return
    # A key written twice is not an error in a script: the later one wins, and changes the word where the first was meant
    table = re.findall(r'^\s*("(?:[^"\\]|\\.)*")\s*:', (h.PANEL / "i18n" / "ko.js").read_text(encoding="utf-8"), re.M)
    twice = sorted({k for k in table if table.count(k) > 1})
    check(f"no key stands twice in the Korean table ({len(table)})", table and not twice, twice)
    words = "() => [document.documentElement.lang, $('pause-text').textContent, $('reanalyze').textContent.trim(), $('settings-title').textContent]"
    want = ["ko", "일시정지", "다시 분석", "풀이 설정"]
    p = Page(br, s, [], locale=EN, query="?lang=ko")
    check("?lang=ko gives the Korean page in an English browser", p.js(words) == want, p.js(words))
    check("and tells the server Korean first", p.js("() => window.__sent[0]") == {"type": "ui_lang", "lang": "ko"}, p.js("() => window.__sent.slice(0, 3)"))
    p.close()
    p = Page(br, s, [], locale="ko-KR")
    check("a Korean browser gets the Korean page", p.js(words) == want, p.js(words))
    check("a date is written with a Korean weekday", p.js("() => fmtDay(new Date(2026, 10, 2, 12).getTime())") == "11.02(월)",
          p.js("() => fmtDay(new Date(2026, 10, 2, 12).getTime())"))
    p.close()
    p = Page(br, s, [], locale="ko-KR", query="?lang=en")
    check("?lang=en gives the English page in a Korean browser", p.js(words)[:2] == ["en", "Pause"], p.js(words))
    p.close()
    # A word searched for and not found is said with no particle after it: a Latin word's ("GPU", read 지피유) is not told by its letters
    p = Page(br, s, english_rows(), locale="ko-KR")
    said = {}
    for typed in ("큐", "스택", "GPU"):
        p.js("(v) => { const q = $('hist-q'); q.value = v; q.dispatchEvent(new Event('input', { bubbles: true })); }", typed)
        p.wait(150)
        said[typed] = p.js("() => $('hist-nomatch').textContent")
    check("a word searched for and not found is said with no particle after it",
          said == {"큐": "'큐' 검색 결과 없음", "스택": "'스택' 검색 결과 없음", "GPU": "'GPU' 검색 결과 없음"}, said)
    # The particle after a Hangul word goes by its last letter, inside its quotes and past a bracketed aside
    picked = p.js("(ws) => ws.map((w) => w + particle(w, '이/가'))", ["'큐'", "'스택'", "스택 (2)"])
    check("the particle after a quoted word goes by the word", picked == ["'큐'가", "'스택'이", "스택 (2)이"], picked)
    no_errors(p, "korean")
    p.close()


def group_menu(br, s):
    """The menu's Language: a pick reopens the page in that language, kept in this browser; Auto goes back to the
    browser's, and a pick drops an address's ?lang=, which would otherwise win over it."""
    if not T.group("menu"):
        return
    words = "() => [document.documentElement.lang, $('pause-text').textContent, localStorage.getItem('sidenote-lang'), [...document.querySelectorAll('#lang-seg button')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.lang)]"
    p = Page(br, s, [], locale="ko-KR")
    check("a Korean browser: the menu's Language stands at Auto", p.js(words) == ["ko", "일시정지", None, ["auto"]], p.js(words))
    names = p.js("() => [...document.querySelectorAll('#lang-seg button')].map((b) => b.textContent.trim())")
    check("the choices are Auto in the panel's language, and each language in its own words, in the Speech setting's order", names == ["자동", "한국어", "English"], names)
    p.page.click("#more")
    with p.page.expect_navigation():
        p.page.click("#lang-seg button[data-lang='en']")
    p.wait(600)
    check("English picked: the page opens again in English, and the choice is kept", p.js(words) == ["en", "Pause", "en", ["en"]], p.js(words))
    check("and tells the server English", {"type": "ui_lang", "lang": "en"} in p.js("() => window.__sent"), p.js("() => window.__sent.slice(0, 3)"))
    p.page.goto(s.url)
    p.wait(600)
    check("the kept choice wins over the browser's language on the next visit", p.js(words)[:2] == ["en", "Pause"], p.js(words))
    p.page.click("#more")
    with p.page.expect_navigation():
        p.page.click("#lang-seg button[data-lang='auto']")
    p.wait(600)
    check("Auto: the browser's language again, nothing kept", p.js(words) == ["ko", "일시정지", None, ["auto"]], p.js(words))
    p.page.goto(s.url + "?lang=en")
    p.wait(600)
    p.page.click("#more")
    with p.page.expect_navigation():
        p.page.click("#lang-seg button[data-lang='ko']")
    p.wait(600)
    check("a pick on a page opened with ?lang=en drops it from the address", p.js(words)[:3] == ["ko", "일시정지", "ko"] and "lang=" not in p.page.url,
          [p.js(words), p.page.url])
    no_errors(p, "menu")
    p.close()


def group_download(br, s):
    """The desktop app's server (status.desktop, engines.local.pull): a missing model is offered with a Download key on
    the local model's card and in the band, its progress is drawn, and Ollama not answering points at where to get it.
    In English and in Korean, so both tables have the words."""
    if not T.group("download"):
        return
    import copy
    for locale, words in ((EN, ("of", "Download")), (h.support.LOCALE, ("중", "받기"))):
        p = Page(br, s, [], w=1920, h=1040, locale=locale)
        eng = copy.deepcopy(h.ENGINES)
        eng["local"].update(ok=False, missing=True, model="sidenote-gemma4:e4b", gpu_gb=12.9, fits=True, pull=True,
                            want=["sidenote-gemma4:e4b", "sidenote-gemma4:e2b"], loaded=None)
        eng["ready"] = True
        eng["agent"]["login"] = "claude"          # what the app's server names for the sign-in (agents.login_hint)
        p.send({"type": "status", "text": "connected", "desktop": True, "engines": eng})
        p.wait(300)
        keys = p.js("() => [...document.querySelectorAll('.pull-model')].map((b) => [b.dataset.model, b.textContent])")
        check(f"{locale}: the app's missing model gets a key for the model that fits, on the card and in the band",
              len(keys) >= 2 and {k[0] for k in keys} == {"sidenote-gemma4:e4b"} and all(k[1] == words[1] for k in keys), keys)
        text = p.js("() => document.body.innerText")
        check(f"{locale}: ...and no launcher command", "./sidenote" not in text, [ln for ln in text.splitlines() if "./sidenote" in ln][:3])
        p.js("() => document.querySelector('.pull-model').click()")
        p.js("() => document.querySelector('.pull-model') && document.querySelector('.pull-model').click()")
        p.wait(150)
        asked = p.js("() => window.__sent.filter((m) => m.type === 'llm_pull')")
        check(f"{locale}: a press asks the server once, for that model", asked == [{"type": "llm_pull", "model": "sidenote-gemma4:e4b"}], asked)
        p.send({"type": "llm_pull", "model": "sidenote-gemma4:e4b", "status": "pulling", "completed": 3_000_000_000,
                "total": 6_000_000_000})
        p.wait(250)
        bar = p.js("() => { const b = document.querySelector('.pull-bar > span'); return b && b.style.width; }")
        note = p.js("() => (document.querySelector('.pull-bar') || {}).parentElement?.textContent || ''")
        check(f"{locale}: its progress is a bar, with how much of how much", bar == "50%" and "3.0" in note and "6.0" in note
              and words[0] in note, [bar, note])
        p.send({"type": "llm_pull", "model": "sidenote-gemma4:e4b", "status": "done"})
        p.wait(250)
        check(f"{locale}: done, and the bar goes", not p.js("() => !!document.querySelector('.pull-bar')"))
        eng = copy.deepcopy(eng)
        eng["local"].update(missing=False, error="the local LLM server does not answer")
        p.send({"type": "status", "engines": eng})
        p.wait(250)
        check(f"{locale}: Ollama not answering: where to get it", p.js(
            "() => document.querySelectorAll('a[href=\"https://ollama.com/download\"]').length") >= 1)
        if locale == EN:
            found = hangul(p)
            check("en-US: none of it in Hangul", not found, found[:6])
        no_errors(p, f"download {locale}")
        p.close()


MARKS = ("- **Advantages**: fast lookups by key.\n- **Disadvantages**: more memory than a list.\n\n"
         "| Option | Verdict | Why |\n|---|---|---|\n| A | Correct | ordered |\n| B | Wrong | broadcast is UDP's |\n\n"
         "Warning: the order of the checks matters.")


def group_marks(br, s):
    """An English answer gets the marks a Korean one gets from its words: a good or bad name, a verdict's colour in a
    table, a warning paragraph."""
    if not T.group("marks"):
        return
    p = Page(br, s, [row(301, "essay", "Hash map or list?", "a hash map", MARKS, ago=60)], w=1920, h=1040, locale=EN,
             settle=1200)
    tones = p.js("() => Object.fromEntries([...document.querySelectorAll('[data-tone]')].map((e) => [e.textContent.trim(), e.dataset.tone]))")
    check("en-US: 'Advantages' and 'Disadvantages' named as good and bad", tones.get("Advantages") == "good"
          and tones.get("Disadvantages") == "bad", tones)
    cells = p.js("() => [...document.querySelectorAll('td.v-yes, td.v-no')].map((c) => [c.textContent.trim(), c.className])")
    check("en-US: a verdict of Correct or Wrong is coloured", any(t == "Correct" and "v-yes" in c for t, c in cells)
          and any(t == "Wrong" and "v-no" in c for t, c in cells), cells)
    check("en-US: a paragraph that starts with 'Warning:' is set apart", p.js("() => !!document.querySelector('p.v-note')"))
    no_errors(p, "marks")
    p.close()


def no_errors(p, group):
    check(f"{group}: the page threw nothing", not p.errors, p.errors[:3])


def main() -> int:
    h.support.need_vendor(h.PANEL)   # exits with a word if the panel's libraries are missing
    s = Stand("lang")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_english, group_korean, group_menu, group_download, group_marks):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
