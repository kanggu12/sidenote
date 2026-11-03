"""The run box: what happens when the code reads input and there is none.

    .venv-panel/bin/python tests/panel_run.py

Pasted into the panel, a solution that starts with `input()` and is run with the input box folded
away dies on its first line, and what comes back is a traceback ending in EOFError. The box that
would have fixed it is right there, folded, and nothing says so. This drives the real panel:

  - a run of code that reads input, with nothing typed, opens the box and says what it needs
  - pressing run again sends it anyway, for someone who meant to
  - what was typed is sent even when the box is folded away
  - a run that did die on EOF says so in words, with the traceback kept underneath
  - the bar's buttons wear a drawn mark, not a character from whatever font has it
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
OUT = support.out("shots")                      # the screenshot

ANSWER = ("TYPE: algorithm\n정답은 **6** 입니다.\n\n나이트가 갈 수 있는 칸을 셉니다.\n\n"
          "```python\ninput_data = input().strip()\nrow = int(input_data[1])\nprint(row)\n```\n")
NO_INPUT = ("TYPE: algorithm\n정답입니다.\n\n```python\nprint(sum(range(10)))\n```\n")
EXAMPLES = ("TYPE: algorithm\n압축\n\n```python\ndef solution(s):\n    return len(s)\n\n\n"
            "if __name__ == \"__main__\":  # 입력 칸이 비면 문제의 입출력 예로 실행\n    import sys, ast\n"
            "    lines = sys.stdin.read().splitlines()\n    if lines:\n        print(solution(ast.literal_eval(lines[0])))\n"
            "    else:\n        for s, want in [(\"aabbaccc\", 7)]:\n            print(solution(s), want)\n```\n")

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


def main() -> int:
    support.need_vendor(ROOT / "panel")
    support.panel_copy(STATIC)
    OUT.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        page = br.new_page(viewport={"width": 1300, "height": 900}, locale=support.LOCALE)
        page.set_default_timeout(5000)   # a check that hangs for thirty seconds tells you nothing
        errs = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(url, wait_until="load")
        page.wait_for_timeout(400)
        # Catch what the panel tries to send, and say it went out, so a run can be followed without
        # a server behind it.
        page.evaluate("""() => { window.__sent = []; window.send = (m) => { window.__sent.push(m); return true; }; }""")
        # The run button only appears when the server has said it has a runner, so that is said
        # first; without it the panel is right to draw no run box at all.
        page.evaluate("""() => handle({ type: "status", paused: false, lang: "auto", audio: true,
            can_ask: true, run_enabled: true, runner: true,
            engines: { local: { present: true, on: true, ok: true, method: "local" },
                       agent: { present: true, ok: true, method: "claude.ai" }, ready: true } })""")
        # One at a time: the newest entry is the open one, and a folded entry has no body to run.
        page.evaluate("(s) => s.forEach(handle)", seed(ANSWER, 1793000001))
        page.wait_for_timeout(500)

        boxes = page.locator(".runbox")
        # Run and Input sit in a bar at the foot of the code box, not in its header, over the input and the output they open
        tools = page.locator(".md pre + .runbox > .runbar .runtools")
        head = page.locator(".md pre .codebar .runtools")
        check("the run box sits under the code, Run and Input in the strip at its foot (none in the code's header)",
              boxes.count() == 1 and tools.count() == 1 and head.count() == 0,
              f"{boxes.count()} run boxes, {tools.count()} strips at the foot, {head.count()} in the header")
        check("with nothing opened the strip shows Run and Input alone, the input box and the output hidden",
              boxes.nth(0).is_visible() and tools.nth(0).is_visible() and not boxes.nth(0).locator(".stdin").is_visible()
              and not boxes.nth(0).locator(".run-out").is_visible())
        # the foot sits right under the code: the block's bottom edge is the bar's top edge
        gap = page.evaluate("""() => { const p = document.querySelector('.md pre'), b = p.nextElementSibling;
            return b.getBoundingClientRect().top - p.getBoundingClientRect().bottom; }""")
        check("the strip sits right under the code block", abs(gap) < 1.5, f"{gap:.1f}px")
        if boxes.count() != 1 or tools.nth(0).locator(".run").count() != 1:
            print("    runbox html:", page.evaluate("() => document.querySelector('.runbox')?.outerHTML || 'none'")[:400])
            print("    pre html:", page.evaluate("() => document.querySelector('.md pre')?.outerHTML.slice(0,200) || 'none'"))
            print("    errors:", errs[:4])
            srv.shutdown(); br.close(); return 1
        box = boxes.nth(0)
        bar = tools.nth(0)

        # --- the marks on the bar
        check("the Run button wears a drawn mark", bar.locator(".run svg").count() == 1)
        check("the Input button wears a drawn mark", bar.locator(".stdin-toggle svg").count() == 1)
        check("the Run button does not use the character ▶", "▶" not in (bar.locator(".run").inner_text() or ""),
              bar.locator(".run").inner_text())

        # --- input is read, nothing typed: the box opens and says so, and nothing is sent
        bar.locator(".run").click()
        page.wait_for_timeout(200)
        check("code that reads input, run with the input empty, opens the input box", box.locator(".stdin").is_visible())
        check("and says what it needs", "예시 입력" in box.locator(".run-out").inner_text(),
              box.locator(".run-out").inner_text()[:60])
        check("and sends no run while it is so", page.evaluate("() => window.__sent.length") == 0,
              str(page.evaluate("() => window.__sent")))

        # --- pressing it again runs it anyway
        bar.locator(".run").click()
        page.wait_for_timeout(200)
        sent = page.evaluate("() => window.__sent")
        check("a second press sends it without input", len(sent) == 1 and sent[0]["type"] == "run" and sent[0]["stdin"] == "",
              json.dumps(sent, ensure_ascii=False)[:120])

        # --- the run that went out with no input dies on EOF: said in words, box opened
        rid = sent[0]["id"]
        page.evaluate("""(rid) => handle({ type: "run_result", id: rid, ok: false, exit: 1, elapsed: 0.01,
            stdout: "", stderr: "Traceback (most recent call last):\\n  File \\"/work/main.py\\", line 1,"
              + " in <module>\\n    input_data = input().strip()\\nEOFError: EOF when reading a line\\n",
            stage: "run" })""", rid)
        page.wait_for_timeout(200)
        out = box.locator(".run-out").inner_text()
        check("a run that died on EOF first says in words what happened", out.startswith("입력을 다 읽기 전에 끝남"), out[:46])
        check("and keeps the original message under it", "EOFError" in out and "원래 메시지" in out, out[-50:].replace("\n", " "))
        check("and opens the input box then", box.locator(".stdin").is_visible())

        # --- what was typed goes with the run even when the box is folded away
        page.evaluate("() => { window.__sent = []; }")
        box.locator(".stdin").fill("a1\n")
        bar.locator(".stdin-toggle").click()           # fold it
        page.wait_for_timeout(150)
        check("folding it hides the input box", not box.locator(".stdin").is_visible())
        bar.locator(".run").click()
        page.wait_for_timeout(200)
        sent = page.evaluate("() => window.__sent")
        check("what was typed goes with the run while it is folded away", len(sent) == 1 and sent[0]["stdin"] == "a1\n",
              json.dumps(sent, ensure_ascii=False)[:110])
        page.evaluate("""(rid) => handle({ type: "run_result", id: rid, ok: true, exit: 0, elapsed: 0.01,
            stdout: "1\\n", stderr: "", stage: "run" })""", sent[0]["id"])
        page.wait_for_timeout(200)
        check("a run that works shows its output alone", box.locator(".run-out").inner_text().strip() == "1",
              box.locator(".run-out").inner_text()[:40])

        # --- code that reads nothing is not interrupted
        page.evaluate("() => { window.__sent = []; }")
        page.evaluate("(s) => s.forEach(handle)", seed(NO_INPUT, 1793000002))
        page.wait_for_timeout(500)
        page.locator(".md pre + .runbox .runtools").last.locator(".run").click()
        page.wait_for_timeout(200)
        sent = page.evaluate("() => window.__sent")
        check("code that reads no input runs at once", len(sent) == 1 and sent[0]["type"] == "run",
              json.dumps(sent, ensure_ascii=False)[:120])

        # --- a runner that reads the box when it holds something and runs the problem's examples when it is empty
        # (an answer's code): the empty box is no mistake there, and the box says what to type
        page.evaluate("() => { window.__sent = []; }")
        page.evaluate("(s) => s.forEach(handle)", seed(EXAMPLES, 1793000003))
        page.wait_for_timeout(500)
        last = page.locator(".md pre + .runbox .runtools").last
        last.locator(".run").click()
        page.wait_for_timeout(200)
        sent = page.evaluate("() => window.__sent")
        check("a runner that runs the problem's examples when the input is empty runs at once", len(sent) == 1 and sent[0]["stdin"] == "",
              json.dumps(sent, ensure_ascii=False)[:120])
        last.locator(".stdin-toggle").click()
        page.wait_for_timeout(150)
        hint = page.locator(".runbox").last.locator(".stdin").get_attribute("placeholder") or ""
        check("its input box asks for the function's values one a line", "한 줄에 하나씩" in hint and "입출력 예" in hint, hint)

        page.screenshot(path=str(OUT / "run-stdin.png"), full_page=False)
        br.close()
    srv.shutdown()
    print(f"\n{len(PASS)} ok, {len(FAIL)} FAIL")
    for f in FAIL:
        print(f"  FAIL {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
