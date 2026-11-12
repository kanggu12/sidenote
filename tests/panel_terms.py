"""Pick from text, under Extra terms in Solver settings' Speech section: the key under the box, the area it opens in the row,
a text pasted and its terms found (the reply written by the server's own code, server/terms.py), the terms pressed in and out,
and Add: the setting message holds exactly the words, the box shows them and the text box is empty again. Then the limit of
Extra terms, a text past what the server reads, nothing found, Escape and closing, a dropped connection, the words in English,
and the area at a phone's width and two screens' in both themes, nothing past its edges.

    PY=.venv/bin/python .venv-panel/bin/python tests/panel_terms.py
    ONLY="flow,limit" ...   # only the groups named

A press or a text on something the page does not have is passed over, so that on an older panel (PANEL_DIR) every check is
still run, and says what is missing.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_harness as h  # noqa: E402
from panel_harness import Page, Stand, contrast  # noqa: E402

T = h.Tally()
check = T.check
SUPPORT = h.support

# A job posting, made up, naming made-up products beside real ones: new terms, terms the built-in lists hold, and one Extra
# terms holds already (in other capitals)
TEXT = ("[가상랩스] 플랫폼 엔지니어\n"
        "- Kubernetes 위에서 LangGraph 에이전트와 Zephyrflow 파이프라인을 운영합니다\n"
        "- QuokkaDB, Redis, Marmotq 경험\n"
        "- GitHub Actions와 Argo CD로 배포합니다\n"
        "- Zephyrflow와 QuokkaDB를 같이 다뤄 보신 분\n")
HELD = ["Lumenstack", "argo cd"]   # Extra terms before the find
NEW, LISTED, HAVE = "새 용어", "기본 힌트에 있음", "추가 용어에 있음"   # the three groups' names, in Korean

# Where the area and what is in it stand, and anything past an edge: the page sideways, the area past its pane or its row, a
# key or a term past the area, two terms over each other, words cut inside their box
MEASURE = """() => {
  const out = { side: document.documentElement.scrollWidth - document.documentElement.clientWidth, area: false, past: [], over: [], cut: [] };
  const area = document.querySelector('#settings .terms-area'), pane = document.querySelector('#settings .set-pane');
  if (!area) return out;
  out.area = true;
  const row = area.closest('.set'), a = area.getBoundingClientRect(), p = pane.getBoundingClientRect(), r = row.getBoundingClientRect();
  if (a.left < p.left - .5 || a.right > p.right + .5) out.past.push('area past the pane');
  if (a.left < r.left - .5 || a.right > r.right + .5) out.past.push('area past its row');
  for (const el of area.querySelectorAll('button, textarea, .terms-said, .terms-line, .terms-h')) {
    const b = el.getBoundingClientRect();
    if (b.left < a.left - .5 || b.right > a.right + .5) out.past.push((el.dataset.term || el.dataset.terms || el.className) + ' past the area');
    if (el.scrollWidth > el.clientWidth + 1 && el.tagName !== 'TEXTAREA') out.cut.push(el.dataset.term || el.className);
  }
  const chips = [...area.querySelectorAll('[data-term]')].map((el) => [el.dataset.term, el.getBoundingClientRect()]);
  for (let i = 0; i < chips.length; i++) for (let j = i + 1; j < chips.length; j++) {
    const [x, b] = chips[i], [y, c] = chips[j];
    if (b.left < c.right - .5 && c.left < b.right - .5 && b.top < c.bottom - .5 && c.top < b.bottom - .5) out.over.push(x + ' / ' + y);
  }
  return out;
}"""


def server_terms(text: str, extra: list) -> list:
    """The terms the server's own code finds in `text`, marked against the built-in lists and `extra`, as terms_find replies."""
    code = ("import json, sys\nfrom server import terms\nfrom server.config import WHISPER_HINTS\n"
            "print(json.dumps(terms.marked(terms.find(sys.argv[1]), WHISPER_HINTS, sys.argv[2:])))")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SIDENOTE_")}   # no log folder: nothing written anywhere
    made = subprocess.run([SUPPORT.server_python(), "-c", code, text, *extra], cwd=h.ROOT, env=env, capture_output=True, text=True)
    if made.returncode != 0:
        print(f"  the terms could not be found with {SUPPORT.server_python()} (set PY to the server's interpreter):\n{made.stderr[-600:]}")
        sys.exit(2)
    return json.loads(made.stdout)


def speech(p: Page, values: dict | None = None) -> None:
    """The settings sent as the server sends them, and Solver settings opened on its Speech section."""
    msg = SUPPORT.settings_message()
    msg["values"]["speech_terms"] = list(HELD)
    msg["values"].update(values or {})
    p.send(msg)
    p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='speech']\").click(); }")
    p.wait(250)


def press(p: Page, sel: str, force: bool = False) -> None:
    """A press on what `sel` names, as a hand presses it; passed over when the page has no such thing. `force`: pressed
    although it says it cannot be (aria-disabled), as a hand does not ask."""
    if p.js("(s) => !!document.querySelector(s)", sel):
        p.page.click(sel, force=force, timeout=5000)
    p.wait(100)


def paste(p: Page, text: str) -> None:
    """A text put in the area's text box, as a paste puts it there (an input event); passed over with no text box."""
    p.js("""(t) => { const b = document.querySelector('#settings textarea.terms-text'); if (!b) return;
        b.focus(); b.value = t; b.dispatchEvent(new Event('input', { bubbles: true })); }""", text)
    p.wait(60)


def found(p: Page, terms: list) -> None:
    """Find pressed, and the server's reply arriving as it sends it."""
    press(p, "[data-terms=find]")
    p.send({"type": "terms_found", "terms": terms, "limit": 50})
    p.wait(150)


def sent(p: Page, kind: str) -> list:
    """The messages of one type the page has sent since it opened."""
    return p.js("(k) => window.__sent.filter((m) => m && m.type === k)", kind)


def state(p: Page) -> dict:
    """What the area shows: its keys, the terms in their groups, what is said, and the boxes' words."""
    return p.js("""() => {
      const area = document.querySelector('#settings .terms-area'), key = document.querySelector('#settings [data-terms=open]');
      const one = (sel) => area?.querySelector(sel), btn = (sel) => one(sel) && { text: one(sel).textContent.trim(), off: one(sel).getAttribute('aria-disabled') === 'true' };
      return {
        key: { text: key?.textContent.trim() ?? null, expanded: key?.getAttribute('aria-expanded') ?? null },
        open: !!area, focus: document.activeElement?.dataset?.terms || document.activeElement?.dataset?.term || document.activeElement?.tagName,
        text: one('textarea.terms-text')?.value ?? null, hint: one('textarea.terms-text')?.placeholder ?? null,
        find: btn('[data-terms=find]') || { text: null, off: null }, add: btn('[data-terms=add]') || null,
        said: one('.terms-said')?.textContent ?? null, warn: !!one('.terms-said.warn'), line: one('.terms-line')?.textContent ?? null,
        groups: [...(area?.querySelectorAll('.terms-group') || [])].map((g) => ({ name: g.querySelector('.seg').getAttribute('aria-label'),
          head: g.querySelector('.terms-h').textContent,
          terms: [...g.querySelectorAll('[data-term]')].map((b) => ({ word: b.dataset.term, pressed: b.getAttribute('aria-pressed') === 'true',
            disabled: b.disabled, blocked: b.getAttribute('aria-disabled') === 'true', label: b.getAttribute('aria-label') })) })),
        box: document.querySelector('#settings textarea[data-set=speech_terms]')?.value ?? null,
        sheet: !document.getElementById('settings-overlay').hidden,
        sheets: SHEETS.filter((o) => !document.getElementById(o).hidden).length,   // the panel's own list of its sheets
        held: typeof termsPick === 'undefined' ? 'none' : termsPick === null ? null : termsPick.text,
      };
    }""")


def group_of(st: dict, name: str) -> list:
    """The terms of one group as the area shows them, none when it has no such group."""
    return next((g["terms"] for g in st["groups"] if g["name"] == name), [])


def group_key(br, s):
    if not T.group("the key"):
        return
    p = Page(br, s, [], w=1366, h=768, settle=300)
    speech(p)
    st = state(p)
    check("Speech: a key 'Pick from text' (글에서 고르기) under Extra terms, its area closed", st["key"] == {"text": "글에서 고르기", "expanded": "false"}
          and not st["open"], st["key"])
    order = p.js("""() => { const row = document.querySelector('#settings textarea[data-set=speech_terms]').closest('.set');
        const box = row.querySelector('textarea.words'), key = row.querySelector('[data-terms=open]');
        return !!key && !!(box.compareDocumentPosition(key) & Node.DOCUMENT_POSITION_FOLLOWING)
          && key.getBoundingClientRect().top >= box.getBoundingClientRect().bottom; }""")
    check("...in the row of the box, under it", order)
    p.js("() => document.querySelector(\".set-tab[data-sec='screen']\").click()")
    p.wait(150)
    other = p.js("() => !document.querySelector('#settings [data-terms]') && !!document.querySelector('#settings textarea[data-set=skip_windows]')")
    check("no other box of words has one (Skip windows), and the page threw nothing", other and order and not p.errors, p.errors[:2])
    p.close()


def group_flow(br, s):
    if not T.group("flow"):
        return
    reply = server_terms(TEXT, HELD)
    words = [x["word"] for x in reply]
    if not {"Zephyrflow", "QuokkaDB", "Marmotq", "GitHub Actions", "Kubernetes", "LangGraph", "Redis", "Argo CD"} <= set(words):
        print(f"  the server's code found other terms in the posting than these checks are written for: {words}")
        sys.exit(2)
    p = Page(br, s, [], w=1366, h=768, settle=300)
    speech(p)
    press(p, "[data-terms=open]")
    st = state(p)
    check("pressed, it opens an area in the row, not a second sheet over the sheet", st["open"] and st["sheets"] == 1
          and st["key"]["expanded"] == "true" and p.js("() => !!document.querySelector('#settings .set .terms-area')"), st)
    check("...the text box has the keyboard, with its hint in Korean", st["focus"] == "text" and st["hint"] == "채용 공고, 이력서, 메모 붙여넣기", st)
    check("...Find (용어 찾기) waits for a text, and the note says the text is kept nowhere", st["find"] == {"text": "용어 찾기", "off": True}
          and st["said"] == "서버가 읽기만 하고 남기지 않음", st)
    paste(p, TEXT)
    check("a text pasted: Find can be pressed", state(p)["find"]["off"] is False, state(p)["find"])
    # The server's messages redraw the sheet: while the text box has the keyboard nothing is drawn under it
    p.js("() => { const b = document.querySelector('#settings textarea.terms-text'); if (b) b.setSelectionRange(5, 5); window.__tb = b; }")
    p.send({"type": "settings", "values": {"speech_lang": "auto"}})
    p.wait(150)
    kept = p.js("() => { const b = document.querySelector('#settings textarea.terms-text'); return { same: !!b && b === window.__tb, caret: b?.selectionStart, focus: !!b && document.activeElement === b }; }")
    check("a redraw while it is typed in keeps the box, the caret and the keyboard", kept == {"same": True, "caret": 5, "focus": True}, kept)
    press(p, "[data-terms=find]")
    asked = sent(p, "terms_find")
    # (numbered: the answer says which Find it answers)
    check("Find sends the text, exactly, once", [{k: v for k, v in a.items() if k != "ask"} for a in asked] == [{"type": "terms_find", "text": TEXT}]
          and [a.get("ask") for a in asked] == [1], asked)
    st = state(p)
    check("...and waits, saying so, Find not to be pressed again meanwhile", st["said"] == "찾는 중" and st["find"]["off"] is True, st)
    press(p, "[data-terms=find]", force=True)
    check("...a second press meanwhile sends nothing", len(asked) == 1 and len(sent(p, "terms_find")) == 1, len(sent(p, "terms_find")))
    p.send({"type": "terms_found", "terms": reply, "limit": 50})
    p.wait(150)
    st = state(p)
    new, listed, have = group_of(st, NEW), group_of(st, LISTED), group_of(st, HAVE)
    check("the terms in three groups: new, in the built-in hints, in Extra terms", [g["name"] for g in st["groups"]] == [NEW, LISTED, HAVE]
          and {t["word"] for t in new} == {"Zephyrflow", "QuokkaDB", "Marmotq", "GitHub Actions"}
          and {t["word"] for t in listed} == {"Kubernetes", "LangGraph", "Redis"} and [t["word"] for t in have] == ["Argo CD"], st["groups"])
    check("...in the server's order (the most frequent first)", bool(new) and [t["word"] for t in new] == [w for w in words if w in {t["word"] for t in new}],
          [t["word"] for t in new])
    check("...each group's head says how many it holds", bool(st["groups"]) and all(g["head"].endswith(str(len(g["terms"]))) for g in st["groups"]),
          st["groups"])
    check("the new ones pressed in to begin with, the built-in ones not", bool(new) and bool(listed) and all(t["pressed"] for t in new)
          and not any(t["pressed"] for t in listed), st["groups"])
    check("one Extra terms holds (in other capitals) shows pressed and cannot be pressed again", bool(have) and have[0]["pressed"] and have[0]["disabled"], have)
    check("a term said twice says so to a screen reader", any(t["label"] == "Zephyrflow, 2번" for t in new), new)
    check("the line: how many are added, and how many Extra terms will hold of 50", st["line"] == "4개 추가 · 추가 용어 6/50", st["line"])
    # Pressed out and in, the keyboard stays on the term through the redraw
    press(p, "[data-term=Marmotq]")
    press(p, "[data-term=Redis]")
    st = state(p)
    pressed = {t["word"]: t["pressed"] for g in st["groups"] for t in g["terms"]}
    check("a new term pressed out and a built-in one pressed in: the line follows", st["line"] == "4개 추가 · 추가 용어 6/50"
          and pressed.get("Marmotq") is False and pressed.get("Redis") is True, st)
    check("...the keyboard still on the term pressed", st["focus"] == "Redis", st["focus"])
    before = len(sent(p, "setting"))
    press(p, "[data-terms=add]")
    p.wait(50)
    settings = sent(p, "setting")[before:]
    want = HELD + [w for w in words if w in {"Zephyrflow", "QuokkaDB", "GitHub Actions", "Redis"}]
    check("Add sends one setting message, the box's own, holding exactly the words: those held, then those pressed",
          settings == [{"type": "setting", "key": "speech_terms", "value": want}], settings)
    st = state(p)
    check("the box shows them", st["box"] == ", ".join(want), st["box"])
    check("the text box is empty again, with the keyboard, the terms gone", st["open"] and st["text"] == "" and st["focus"] == "text"
          and not st["groups"] and st["add"] is None, st)
    check("...and the area says what went in, the page having thrown nothing", st["said"] == "4개 넣음 · 추가 용어 6/50" and not p.errors,
          [st["said"], p.errors[:2]])
    p.close()


def group_limit(br, s):
    if not T.group("limit"):
        return
    reply = server_terms(TEXT, HELD)
    many = [f"term{i}" for i in range(47)]      # three places left of fifty
    p = Page(br, s, [], w=1366, h=768, settle=300)
    speech(p, {"speech_terms": many})
    press(p, "[data-terms=open]")
    paste(p, TEXT)
    found(p, server_terms(TEXT, many))
    st = state(p)
    new = group_of(st, NEW)
    check("three places left: the three most frequent new ones are pressed in, the rest not",
          len(new) > 3 and [t["pressed"] for t in new] == [True] * 3 + [False] * (len(new) - 3), new)
    check("...the rest cannot be pressed while it is full, a built-in one neither", len(new) > 3
          and all(t["blocked"] for g in st["groups"] for t in g["terms"] if not t["pressed"]), st["groups"])
    check("...and the line says why", st["line"] == f"3개 추가 · 추가 용어 50/50 · 가득 참, {len(new) - 3}개 제외", st["line"])
    last = new[-1]["word"] if new else "Marmotq"
    press(p, f"[data-term='{last}']", force=True)
    check("a press on one that has no room does nothing", bool(new) and not {t["word"]: t["pressed"] for t in group_of(state(p), NEW)}.get(last, True))
    press(p, f"[data-term='{new[0]['word'] if new else 'Zephyrflow'}']")
    st = state(p)
    check("one pressed out makes room: the line says 49, and the others can be pressed", st["line"] == "2개 추가 · 추가 용어 49/50"
          and bool(st["groups"]) and not any(t["blocked"] for g in st["groups"] for t in g["terms"]), st["line"])
    press(p, f"[data-term='{last}']")
    before = len(sent(p, "setting"))
    press(p, "[data-terms=add]")
    value = (sent(p, "setting")[before:] or [{"value": []}])[0]["value"]
    check("Add never sends more than 50", len(value) == 50 and value[:47] == many and value[-1] == last, value[-4:])
    # The box filled meanwhile (from another panel): what no longer fits comes out at the next drawing
    p.send({"type": "settings", "values": {"speech_terms": [f"other{i}" for i in range(40)]}})
    paste(p, TEXT)
    found(p, reply)
    fresh = len(group_of(state(p), NEW))
    check("room for ten: every new one pressed in", fresh > 1 and state(p)["line"] == f"{fresh}개 추가 · 추가 용어 {40 + fresh}/50", state(p)["line"])
    p.send({"type": "settings", "values": {"speech_terms": [f"other{i}" for i in range(49)]}})
    p.wait(150)
    st = state(p)
    check("Extra terms filled elsewhere meanwhile: the terms pressed in are cut to the room left, the most frequent kept",
          fresh > 1 and st["line"] == f"1개 추가 · 추가 용어 50/50 · 가득 참, {fresh - 1}개 제외"
          and [t["pressed"] for t in group_of(st, NEW)] == [True] + [False] * (fresh - 1) and not p.errors, [st["line"], p.errors[:2]])
    p.close()


def group_edges(br, s):
    if not T.group("edges"):
        return
    p = Page(br, s, [], w=1366, h=768, settle=300)
    speech(p)
    press(p, "[data-terms=open]")
    paste(p, "Kafka 운영 경험 " * 4000)        # some 80 KB: past what the server reads
    press(p, "[data-terms=find]")
    st = state(p)
    check("a text past 64 KB is not sent, and the area says so in the warning colour", st["open"] and sent(p, "terms_find") == []
          and st["warn"] and st["said"] == "64KB 넘는 글 · 나눠서 붙여넣기", st)
    paste(p, "오늘은 날씨가 좋네요.")
    found(p, [])
    st = state(p)
    check("a text with nothing technical: the area says no terms were found, and has no Add", st["open"] and st["said"] == "기술 용어 없음"
          and st["add"] is None and not st["groups"], st)
    # Escape in the area closes the area, and the sheet stays
    p.js("() => document.querySelector('#settings textarea.terms-text')?.focus()")
    p.page.keyboard.press("Escape")
    p.wait(150)
    st = state(p)
    check("Escape in the text box closes the area, not the sheet, the keyboard back on the key", st["held"] is None and not st["open"]
          and st["sheet"] and st["focus"] == "open" and st["key"]["expanded"] == "false", st)
    press(p, "[data-terms=open]")
    check("opened again, it holds no text", state(p)["text"] == "", state(p)["text"])
    paste(p, TEXT)
    press(p, "[data-terms=close]")
    st = state(p)
    check("Close closes it", st["held"] is None and not st["open"] and st["focus"] == "open", st)
    press(p, "[data-terms=open]")
    paste(p, TEXT)
    p.js("() => closeSettings()")
    p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='speech']\").click(); }")
    p.wait(200)
    st = state(p)
    check("the sheet closed and opened again: the area is closed and the text is gone", st["held"] is None and not st["open"], st)
    # Closed, the sheet keeps no copy of the text in its hidden page either (it draws nothing while hidden)
    press(p, "[data-terms=open]")
    paste(p, "SECRET-RESUME-WORDS Kubernetes")
    p.js("() => closeSettings()")
    p.wait(100)
    kept = p.js("() => [...document.querySelectorAll('textarea, input')].some((b) => (b.value || '').includes('SECRET-RESUME-WORDS'))"
                " || document.body.innerHTML.includes('SECRET-RESUME-WORDS')")
    check("the sheet closed: the pasted text is nowhere in the page", kept is False, kept)
    p.js("() => { openSettings(); document.querySelector(\".set-tab[data-sec='speech']\").click(); }")
    p.wait(200)
    # Escape that ends a Korean syllable being put together: the syllable's, and the sheet stays open with the text
    press(p, "[data-terms=open]")
    paste(p, TEXT)
    p.js("""() => document.querySelector('#settings textarea.terms-text').dispatchEvent(new KeyboardEvent('keydown',
        { key: 'Escape', isComposing: true, keyCode: 229, bubbles: true, cancelable: true }))""")
    p.wait(150)
    st = state(p)
    check("Escape while a Korean syllable is put together: the sheet and the area stay, the text in them", st["sheet"] and st["open"]
          and st["text"] == TEXT, st)
    press(p, "[data-terms=close]")
    # An answer to a Find made before the area was closed and opened again: dropped, and the new Find's answer drawn
    press(p, "[data-terms=open]")
    paste(p, TEXT)
    press(p, "[data-terms=find]")
    first = (sent(p, "terms_find") or [{}])[-1].get("ask")
    press(p, "[data-terms=close]")
    press(p, "[data-terms=open]")
    paste(p, "Terraform")
    press(p, "[data-terms=find]")
    second = (sent(p, "terms_find") or [{}])[-1].get("ask")
    p.send({"type": "terms_found", "ask": first, "terms": server_terms(TEXT, HELD), "limit": 50})
    p.wait(150)
    late = state(p)["groups"]
    p.send({"type": "terms_found", "ask": second, "terms": [{"word": "Terraform", "count": 1, "listed": False, "have": False}], "limit": 50})
    p.wait(150)
    st = state(p)
    check("each Find is numbered, and an answer to an earlier one is not drawn for the new text", isinstance(first, int) and second == first + 1
          and late == [] and [t["word"] for g in st["groups"] for t in g["terms"]] == ["Terraform"], [first, second, late, st["groups"]])
    press(p, "[data-terms=close]")
    # A connection that drops while a find is on its way: the reply will not come, and Find can be pressed again
    press(p, "[data-terms=open]")
    paste(p, TEXT)
    press(p, "[data-terms=find]")
    p.drop()
    p.page.wait_for_function("() => wsState === 'up'", timeout=8000)   # the page connects again by itself
    p.wait(150)
    st = state(p)
    check("a dropped connection while finding: the text stays and Find can be pressed again", st["text"] == TEXT and st["find"]["off"] is False
          and st["said"] not in ("찾는 중", None), st)
    p.send({"type": "terms_found", "terms": server_terms(TEXT, HELD), "limit": 50})
    p.wait(120)
    st = state(p)
    check("...a reply that comes for no find of this page's is not drawn, the page having thrown nothing", st["open"] and st["groups"] == []
          and not p.errors, [st["groups"], p.errors[:2]])
    p.close()


def group_english(br, s):
    if not T.group("english"):
        return
    p = Page(br, s, [], w=1366, h=768, settle=300, locale="en-US")
    speech(p)
    press(p, "[data-terms=open]")
    paste(p, TEXT)
    found(p, server_terms(TEXT, HELD))
    st = state(p)
    words = p.js("""() => { const area = document.querySelector('#settings .terms-area'), key = document.querySelector('#settings [data-terms=open]');
        if (!area || !key) return null;
        const out = [key.textContent, area.getAttribute('aria-label'), area.querySelector('textarea').placeholder, area.querySelector('textarea').getAttribute('aria-label')];
        for (const el of area.querySelectorAll('button, .terms-said, .terms-line, .terms-h, [aria-label]')) out.push(el.getAttribute('aria-label') || el.textContent);
        return out; }""")
    hangul = [w for w in words or [] if re.search(r"[가-힣]", w or "")]
    check("an English page: the key and the area in English, no Hangul but in the text pasted", words is not None and not hangul, hangul[:4] or words)
    check("...the keys and the line in its words, the page having thrown nothing", st["key"]["text"] == "Pick from text"
          and st["find"]["text"] == "Find terms" and (st["add"] or {}).get("text") == "Add to Extra terms" and st["line"] == "4 to add · Extra terms 6/50"
          and [g["name"] for g in st["groups"]] == ["New terms", "In the built-in hints", "In Extra terms"] and not p.errors, [st, p.errors[:2]])
    p.close()


def group_widths(br, s):
    if not T.group("widths"):
        return
    longest = "Q" + "uokkaFlow" * 6 + "DB"       # a term of 57 letters: wraps inside its key at a phone's width
    reply = server_terms(TEXT, HELD) + [{"word": longest, "count": 1, "listed": False, "have": False}]
    for theme in ("dark", "light"):
        for w, hh in ((390, 844), (1366, 768), (1920, 1080)):
            name = f"{theme} {w}x{hh}"
            p = Page(br, s, [], w=w, h=hh, theme=theme, settle=300)
            speech(p)
            press(p, "[data-terms=open]")
            paste(p, TEXT)
            found(p, reply)
            p.js("() => document.querySelector('#settings .terms-area')?.scrollIntoView({ block: 'start' })")
            p.wait(150)
            m = p.js(MEASURE)
            check(f"{name}: the area stands in its row inside the pane, every key and term inside it, none over another, no word cut",
                  m["area"] and not m["past"] and not m["over"] and not m["cut"], m)
            check(f"{name}: the page does not scroll sideways", m["area"] and m["side"] <= 0, m)
            ink = p.js("""() => [...document.querySelectorAll('#settings .terms-line, #settings .terms-said, #settings [data-term=Zephyrflow], #settings .terms-h')]
                .map((e) => { e.scrollIntoView({ block: 'nearest' }); const r = e.getBoundingClientRect(); return { what: e.dataset.term || e.className,
                  box: [Math.floor(r.left + 2), Math.floor(r.top + 2), Math.ceil(r.right - 2), Math.ceil(r.bottom - 2)], ink: getComputedStyle(e).color.match(/[\\d.]+/g).map(Number) }; })""")
            png = p.page.screenshot()
            low = [f"{x['what']} {r:.2f}" for x in ink for r in [contrast(x["ink"], h.background_of(br, png, x["box"]))] if r < 4.5]
            # the three group heads, the line, the note and a term: six things read
            check(f"{name}: the line, the note, a term and the groups' heads read at 4.5:1 or better, the page having thrown nothing",
                  len(ink) == 6 and not low and not p.errors, [low, len(ink), p.errors[:2]])
            if w in (390, 1366):
                print(f"     shot: {p.shot(f'terms-{theme}-{w}x{hh}')}")
            p.close()


def main() -> int:
    SUPPORT.need_vendor(h.PANEL)   # exits with a word if the panel's libraries are missing
    s = Stand("terms")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for group in (group_key, group_flow, group_limit, group_edges, group_english, group_widths):
            group(br, s)
        br.close()
    return T.end()


if __name__ == "__main__":
    sys.exit(main())
