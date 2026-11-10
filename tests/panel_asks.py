"""The follow-up buttons under the newest answer.

    .venv-panel/bin/python tests/panel_asks.py

An answer that was right but thin left the person at the PC to work out what to type to get the rest of it.
A row of buttons under the newest answer now asks for them: Go deeper always, and a few that suit
the kind of answer it is. They send a whole instruction, not a label, so the depth comes from what
is asked rather than from making every first pass longer. Checked here:

  - the row is under the newest answered entry and not under an older one
  - Go deeper is always there, and the kind-specific ones match the answer's type
  - pressing one sends that instruction as a follow-up question
  - a screen with nothing to solve leaves the row on the last real answer
"""
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import support  # tests/support.py: the output folder, a fresh copy of the panel, the panel's libraries

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
STATIC = support.out("panelstatic")             # the copy of panel/ that is served

ALGO = "TYPE: algorithm\nANSWER: 해시맵, O(N)\n\n풀이입니다.\n\n```python\nprint(1)\n```\n"
WORK = "TYPE: work\nANSWER: 커넥션 풀 고갈\n\n원인을 봅니다.\n"
NONE = "TYPE: none\n"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail else ""))


def seed(text, seq):
    return [{"type": "analysis_start", "id": seq, "ts": 1793000000, "thumb": None,
             "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
            {"type": "analysis_done", "id": seq, "text": text, "usage": {}, "cost_usd": 0.0,
             "model": "sidenote-gemma4:26b", "engine": "local", "sent": [],
             "stages": {"local": True, "agent": False}, "elapsed": 1.0, "region": None}]


def labels(page, nth=-1):
    """The words on the follow-up buttons of the nth entry (-1 = the newest)."""
    return page.evaluate("""(nth) => {
      const es = [...document.querySelectorAll(".entry")];
      const e = nth < 0 ? es[es.length + nth] : es[nth];
      return e ? [...e.querySelectorAll(".row.asks [data-ask]")].map((b) => b.innerText.trim()) : null;
    }""", nth)


def main() -> int:
    support.need_vendor(ROOT / "panel")
    support.panel_copy(STATIC)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        page = br.new_page(viewport={"width": 1300, "height": 900}, locale=support.LOCALE)
        page.set_default_timeout(5000)
        # The follow-up buttons can be pressed only while the socket is up (they used to stay live after
        # it dropped, panel_review.py bug 3). The static server here has no socket, and the page's own
        # attempts would keep failing and taking that state back down, so the socket is a stand-in that
        # never connects, and the page is told it is up, the way a live one tells it.
        page.add_init_script("window.WebSocket = function () { this.close = function () {}; "
                             "this.send = function () {}; this.readyState = 0; };")
        page.goto(url, wait_until="load")
        page.wait_for_timeout(300)
        page.evaluate("""() => { wsState = 'up'; window.__sent = []; window.send = (m) => { window.__sent.push(m); return true; };
            handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true,
                     run_enabled: false,
                     // the engines as server/app.py engines_status() always sends them: local, claude and
                     // search each present. Trimmed to local alone, it was a message no server sends, and
                     // with the socket up the alerts read the missing claude and stopped the page.
                     engines: { local: { ok: true, method: "local", model: "sidenote-gemma4:26b", present: true, on: true, busy: null,
                                         loaded: { model: "sidenote-gemma4:26b", vram_gb: null } },
                                agent: { ok: true, method: "claude.ai", present: true, mode: "hard", effective: "hard",
                                          payload: "crop", model: "", asked_model: "", effort: "", brake: "" },
                                search: { present: true, on: true }, ready: true } }); }""")

        page.evaluate("(s) => s.forEach(handle)", seed(ALGO, 1793000001))
        page.wait_for_timeout(350)
        got = labels(page)
        check("an algorithm answer has the row of follow-up buttons under it", bool(got), str(got))
        check("Go deeper is always there, first", got and got[0] == "더 깊게", str(got))
        check("an algorithm answer gets the questions of its kind",
              got and {"다른 풀이", "복잡도 근거", "반례 찾기"} <= set(got), str(got))
        check("every button wears a drawn mark",
              page.evaluate("""() => [...document.querySelectorAll(".row.asks [data-ask]")]
                                     .every((b) => b.querySelector("svg"))"""))

        # pressing one sends the whole instruction, not the label
        page.evaluate("""() => document.querySelector('.row.asks [data-ask]').click()""")
        page.wait_for_timeout(150)
        sent = page.evaluate("() => window.__sent")
        check("a press sends the whole instruction as the question",
              len(sent) == 1 and sent[0]["type"] == "ask" and sent[0]["text"].startswith("방금 답을 더 깊게"),
              json.dumps(sent, ensure_ascii=False)[:110])
        # held as a key at work, which keeps the keyboard's focus (disabled, the focus fell to the page): a press sends nothing
        page.evaluate("""() => { const b = document.querySelector('.row.asks [data-ask]'); b.focus(); b.click(); }""")
        check("and it cannot be pressed again for a moment after, the focus kept on it",
              page.evaluate("""() => { const b = document.querySelector('.row.asks [data-ask]');
                                      return b.getAttribute('aria-disabled') === 'true' && document.activeElement === b; }""")
              and len(page.evaluate("() => window.__sent")) == 1)

        # a newer answer of another kind: the old row goes, the new one suits its type
        page.evaluate("(s) => s.forEach(handle)", seed(WORK, 1793000002))
        page.wait_for_timeout(350)
        old, new = labels(page, 0), labels(page)
        check("the older answer keeps no follow-up buttons", old == [], str(old))
        check("a work answer gets the questions for work", new and {"확인 방법", "다른 원인"} <= set(new), str(new))

        # A screen with nothing to solve writes no entry at all, so the row must stay where it was:
        # the last answer is still the one a follow-up would be asked about.
        before = page.evaluate("() => document.querySelectorAll('.entry').length")
        page.evaluate("(s) => s.forEach(handle)", seed(NONE, 1793000003))
        page.wait_for_timeout(300)
        after = page.evaluate("() => document.querySelectorAll('.entry').length")
        check("a screen with nothing to solve makes no entry", after == before, f"{before} -> {after}")
        check("and the last answer keeps its follow-up buttons",
              labels(page) and {"확인 방법", "다른 원인"} <= set(labels(page)), str(labels(page)))
        br.close()
    srv.shutdown()
    print(f"\n{len(PASS)} ok, {len(FAIL)} FAIL")
    for f in FAIL:
        print(f"  FAIL {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
