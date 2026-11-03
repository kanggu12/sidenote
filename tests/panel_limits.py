"""What the panel shows of design note 89: the thinking pass's last sentence while it thinks, finding and exporting
the answers of a sitting, a notice that brings the answer it is about into view, and the agent resting at its
limit with this PC's model standing in.

    .venv-panel/bin/python tests/panel_limits.py

Checked here:

  - the foot of the notebook shows the thinking's last sentence under the status, and drops it when the answer starts
  - Find in the answers narrows the contents to the answers holding every word, marks the words, and says when
    none hold them; Export gives one Markdown file with every answer and its follow-up
  - a notice with `of` is pressable and brings that answer into view
  - the agent resting on its plan's limit: a band at the top and the agent's card say until when; this PC's model,
    switched off, standing in: its card says so
"""
import json
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import support  # tests/support.py: the output folder, a fresh copy of the panel, the panel's libraries

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
STATIC = support.out("panelstatic-limits")      # the copy of panel/ that is served
SHOTS = support.out("shots")

ALGO = "TYPE: algorithm\nANSWER: 나이트 이동은 BFS\n\n체스판에서 너비 우선 탐색으로 최소 이동 수를 셉니다.\n"
MATH = "TYPE: math\nANSWER: 42\n\n곱셈을 차례로 합니다.\n"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail and not cond else ""))


def answer(text, seq, ts):
    return [{"type": "analysis_start", "id": seq, "ts": ts, "thumb": None,
             "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
            {"type": "analysis_done", "id": seq, "text": text, "usage": {}, "cost_usd": 0.0,
             "model": "sidenote-gemma4:26b", "engine": "local", "sent": [],
             "stages": {"local": True, "agent": False}, "elapsed": 1.0, "region": None}]


def engines(limit_until=None, local_on=True, stand_in=""):
    """The engines as server/app.py engines_status() sends them."""
    return {"local": {"ok": True, "method": "local", "model": "sidenote-gemma4:26b", "present": True, "on": local_on,
                      "busy": None, "stand_in": stand_in, "loaded": {"model": "sidenote-gemma4:26b", "vram_gb": None}},
            "agent": {"ok": True, "method": "claude.ai", "present": True, "mode": "hard", "effective": "hard",
                      "payload": "crop", "model": "", "asked_model": "", "effort": "", "brake": "",
                      "label": "Claude Code", "short": "Claude", "limit_until": limit_until},
            "search": {"present": True, "on": True}, "ready": True}


def main() -> int:
    support.need_vendor(ROOT / "panel")
    support.panel_copy(STATIC)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        page = br.new_page(viewport={"width": 1300, "height": 900}, accept_downloads=True, locale=support.LOCALE)
        page.set_default_timeout(5000)
        # a socket that never connects, the page told it is up (as panel_asks.py does)
        page.add_init_script("window.WebSocket = function () { this.close = function () {}; "
                             "this.send = function () {}; this.readyState = 0; };")
        errors = []   # what the page threw, or logged as an error
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load" not in m.text else None)
        page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 and "/history" not in r.url else None)   # no server here
        page.goto(url, wait_until="load")
        page.wait_for_timeout(300)
        page.evaluate("""(e) => { wsState = 'up'; window.send = () => true;
            handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: false,
                     engines: e }); }""", engines())

        print("[the thinking's last sentence]")
        now = time.time()
        page.evaluate("(m) => handle(m)", {"type": "analysis_start", "id": 9001, "ts": now, "thumb": None,
                                            "transcript": "", "pages": 0, "trigger": "screen", "roi": None})
        page.evaluate("(m) => handle(m)", {"type": "stage", "id": 9001, "stage": "think", "detail": "생각 1,200자",
                                            "thought": "We need BFS over the board to find the fewest moves."})
        # an automatic look is drawn only once it has run REVEAL_MS (a thinking pass always has), and the foot is
        # filled by the clock's tick after that
        page.wait_for_timeout(page.evaluate("() => REVEAL_MS") + 1300)
        shown = page.evaluate("""() => [...document.querySelectorAll('[data-thought]')]
                                       .filter((p) => !p.hidden).map((p) => p.textContent)""")
        check("the foot shows the thinking's last sentence while it thinks",
              shown and shown[0] == "We need BFS over the board to find the fewest moves.", str(shown))
        page.screenshot(path=str(SHOTS / "limits_thinking.png"))
        page.evaluate("(m) => handle(m)", {"type": "delta", "id": 9001, "text": ALGO})
        page.wait_for_timeout(1300)
        left = page.evaluate("""() => [...document.querySelectorAll('[data-thought]')].filter((p) => !p.hidden).length""")
        check("...and drops it once the answer starts", left == 0, str(left))
        page.evaluate("(m) => handle(m)", answer(ALGO, 9001, now)[1])
        page.wait_for_timeout(400)

        print("[finding and exporting the answers]")
        page.evaluate("(s) => s.forEach(handle)", answer(MATH, 9002, now + 5))
        page.wait_for_timeout(400)
        rows = lambda: page.evaluate("() => document.querySelectorAll('#history .h').length")  # noqa: E731
        check("the contents hold both answers and the search field shows", rows() == 2
              and page.evaluate("() => !document.getElementById('hist-tools').hidden"))
        page.fill("#hist-q", "bfs")
        page.wait_for_timeout(200)
        marked = page.evaluate("() => [...document.querySelectorAll('#history mark')].map((m) => m.textContent)")
        check("typing narrows the contents to the answers holding the word, marked", rows() == 1 and marked == ["BFS"],
              f"{rows()} {marked}")
        check("...and the count says how many of how many", page.evaluate(
            "() => document.getElementById('hist-count').textContent") == "1/2")
        page.fill("#hist-q", "체스판 bfs")
        page.wait_for_timeout(200)
        check("a word not in the first line finds it too", rows() == 1)
        page.fill("#hist-q", "체스판 42")
        page.wait_for_timeout(200)
        check("every word has to be in the same answer", rows() == 0, str(rows()))
        page.fill("#hist-q", "answer")
        page.wait_for_timeout(200)
        check("the protocol's head lines are not searched (\"answer\" finds nothing)", rows() == 0, str(rows()))
        page.fill("#hist-q", "&amp")
        page.wait_for_timeout(200)
        check("a word in no answer leaves none and says so", rows() == 0 and page.evaluate(
            "() => !document.getElementById('hist-nomatch').hidden"))
        page.fill("#hist-q", "")
        page.wait_for_timeout(200)
        check("an empty field shows them all again", rows() == 2)
        page.screenshot(path=str(SHOTS / "limits_contents.png"))
        with page.expect_download() as dl:
            page.click("#hist-export")
        path = dl.value.path()
        md = Path(path).read_text(encoding="utf-8") if path else ""
        check("Export gives one Markdown file with every answer", dl.value.suggested_filename.endswith(".md")
              and "나이트 이동은 BFS" in md and "답: 42" in md and "ANSWER:" not in md and md.count("\n## ") == 2, md[:200])

        print("[a notice that brings its answer into view]")
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.evaluate("(m) => handle(m)", {"type": "notice", "of": 9001,
                                            "text": "위에서 푼 문제가 다시 보여 다시 풀지 않았습니다."})
        page.wait_for_timeout(150)
        check("the notice can be pressed", page.evaluate(
            "() => document.getElementById('toast').classList.contains('go')"))
        page.click("#toast")
        page.wait_for_timeout(900)
        check("pressing it marks that answer", page.evaluate(
            "() => entryEl(9001)?.classList.contains('flash')"))
        page.evaluate("(m) => handle(m)", {"type": "notice", "text": "그냥 알림"})
        page.wait_for_timeout(150)
        check("a notice about nothing in particular is not pressable", page.evaluate(
            "() => !document.getElementById('toast').classList.contains('go')"))

        print("[the agent at its limit, this PC's model standing in]")
        until = int(time.time()) + 2 * 86400 + 4 * 3600 + 120
        page.evaluate("(e) => handle({ type: 'status', engines: e })", engines(until, local_on=False, stand_in="limit"))
        page.wait_for_timeout(300)
        band = page.evaluate("() => document.getElementById('alerts').innerText")
        check("a band at the top says until when the agent rests, and who answers meanwhile",
              "까지 쉼" in band and "대신 풂" in band, band)
        card = page.evaluate("() => document.getElementById('st-agent').innerText")
        check("the agent's card counts the time down", "2일 4시간 뒤" in card, card)
        check("the time left is whole minutes, never 60 of them", page.evaluate(
            "() => restLeft(serverNow() + 3 * 3600 + 59 * 60 + 30)") == "4시간 0분")
        check("the agent's card says it rests at its limit", page.evaluate(
            "() => document.getElementById('pill-agent').textContent") == "한도로 쉼")
        check("this PC's model's card says it solves in the agent's place", page.evaluate(
            "() => document.getElementById('pill-local').textContent") == "대신 푸는 중")
        page.screenshot(path=str(SHOTS / "limits_rest.png"), full_page=False)
        page.evaluate("(e) => handle({ type: 'status', engines: e })", engines(None, local_on=False))
        page.wait_for_timeout(300)
        check("when it is over the band goes and the model's card says it is off", "까지 쉼" not in page.evaluate(
            "() => document.getElementById('alerts').innerText") and page.evaluate(
            "() => document.getElementById('pill-local').textContent") == "꺼 둠")
        print("[a lit word and the quieter words after it]")
        page.evaluate("""(e) => { e.local.loaded = null; handle({ type: 'status', engines: e }); }""", engines())
        page.wait_for_timeout(300)
        lines = page.evaluate("""() => {
            const lit = document.querySelector('#st-local .lit'), sub = lit && lit.nextElementSibling;
            if (!sub) return null;
            const box = (el) => { const r = document.createRange(); r.selectNodeContents(el);
                                  const b = r.getBoundingClientRect(); return b.top + b.height / 2; };
            return [lit.textContent, sub.textContent, box(lit), box(sub)]; }""")
        check("'비어 있음' and what follows it stand on one line, centre to centre within 1 px",
              lines and lines[0] == "비어 있음" and abs(lines[2] - lines[3]) <= 1, str(lines))
        print("[how an answer reads]")
        page.evaluate("(s) => s.forEach(handle)", answer("TYPE: short\nANSWER: 1) 필터링과 점수 2) 컨테이너만 재시작 3) 볼륨 갱신\n\n**풀이 방법**\n\n본문입니다.\n\n```\nkubectl debug pod -it \\\n  --copy-to=dbg -- sh\n```\n\n```python\nprint(1)\n```\n", 9101, time.time()))
        page.wait_for_timeout(500)
        got = page.evaluate("""() => { const e = entryEl(9101); return {
            items: [...e.querySelectorAll('.ans-list li')].map((l) => l.textContent.trim()),
            marks: e.querySelectorAll('.ans-list mark.hl').length,
            head: !!e.querySelector('.para-head'),
            gutters: [...e.querySelectorAll('code.lined')].map((c) => [...c.querySelectorAll('.no')].map((n) => n.textContent)),
            label: e.querySelector('.codebar .lang')?.textContent }; }""")
        check("several answers in one line become a list, each with its highlighter", got["items"] == ["필터링과 점수", "컨테이너만 재시작", "볼륨 갱신"]
              and got["marks"] == 3, str(got))
        check("a line that is all bold reads as a heading", got["head"], str(got))
        check("a command has a prompt, not a line number, and none on a carried-on line; a program keeps its numbers",
              got["gutters"] == [["$", ""], ["1"]] and got["label"].startswith("명령어 1."), str(got))
        band = page.evaluate("() => getComputedStyle(entryEl(9101).querySelector('.hl')).backgroundImage")
        check("the answer's stroke is the yellow highlighter", any(c in band for c in ("rgba(245, 208, 79", "rgba(251, 215, 80", "rgba(242, 199, 68")), band)
        print("[what needs doing stays in view]")
        page.evaluate("() => { setPaused(true); renderAlerts(); document.getElementById('alerts').scrollIntoView(); window.scrollTo(0, document.documentElement.scrollHeight); }")
        page.wait_for_timeout(300)
        spot = page.evaluate("""() => { const a = document.getElementById('alerts').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect();
                                        return [a.top - b.bottom, a.height]; }""")
        check("a band stays right under the bar however far the thread has scrolled", -60 <= spot[0] <= 20 and spot[1] > 20, str(spot))
        rail = page.evaluate("""() => { const r = document.querySelector('.rail'), a = document.getElementById('alerts').getBoundingClientRect();
            return [getComputedStyle(r).position, r.getBoundingClientRect().top >= a.bottom - 1, r.getBoundingClientRect().height,
                    parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--rail-room')), r.getBoundingClientRect().top, a.bottom, innerHeight,
                    r.getBoundingClientRect().bottom]; }""")
        # It follows under the bands while it fits under them; taller than the window it follows too, its foot in the window at
        # the end of a long thread (it drifts: down to its foot going down, back to its head going up)
        fits = rail[2] <= rail[3] + 0.5
        check("the rail follows under the bands while it fits, and with its foot in the window when it is taller than the window",
              page.viewport_size["width"] <= 1000 or (rail[0] == "sticky" and (rail[1] if fits else rail[7] <= rail[6] + 0.5)), str(rail))
        page.evaluate("() => setPaused(false)")
        print("[what is kept comes back, by day and kind]")
        day = time.time() - 3 * 86400
        page.evaluate("""([row]) => { restore(row); thread.sort((a, b) => items.get(a).ts - items.get(b).ts); historyDays = [{ day: dayOf(row.ts * 1000), n: 1 }]; fillChoices(); renderThread(); renderAll(); }""",
                      [{"id": 8001, "ts": day, "kind": "math", "trigger": "screen", "text": MATH, "model": "m", "engine": "local", "elapsed": 2.0,
                        "turns": [{"id": 8002, "q": "왜?", "text": "TYPE: followup\nANSWER: 이유\n", "kind": "ask"}], "check": {"passed": 1, "total": 1, "how": "function"}}])
        page.wait_for_timeout(300)
        old = page.evaluate("""() => { const e = entryEl(8001); return { when: e.querySelector('time')?.textContent, turn: !!e.querySelector('[data-turn]') || items.get(8001).turns.length === 1,
                                       days: document.querySelectorAll('#history .h-day').length }; }""")
        check("an entry from the history comes back with its day and its follow-up, and the contents head each day", bool(old["when"]) and old["turn"] and old["days"] >= 2, str(old))
        page.evaluate("(d) => { const s = document.getElementById('hist-day'); s.value = d; s.dispatchEvent(new Event('change')); }", time.strftime("%Y-%m-%d", time.localtime(day)))
        page.wait_for_timeout(400)
        seen = page.evaluate("""() => [...document.querySelectorAll('.entry')].filter((e) => !e.hidden).length""")
        check("a day chosen shows that day's answers", seen == 1, str(seen))
        page.evaluate("() => { const s = document.getElementById('hist-day'); s.value = ''; s.dispatchEvent(new Event('change')); }")
        print("[the rail goes with the page]")
        page.set_viewport_size({"width": 1300, "height": 640})
        page.wait_for_timeout(300)
        rest = page.evaluate("""async () => { const r = document.querySelector('.rail'), c = getComputedStyle(r), wait = () => new Promise((f) => setTimeout(f, 200));
            for (let i = 0; i < 12; i++) handle({ type: "analysis_start", id: 9700 + i, ts: Date.now() / 1000, thumb: null, transcript: "", pages: 0, trigger: "screen", roi: null }), handle({ type: "analysis_done", id: 9700 + i, text: "TYPE: short\\nANSWER: 답\\n\\n" + "긴 풀이입니다. ".repeat(200), usage: {}, cost_usd: 0, model: "m", engine: "local", sent: [], stages: {}, elapsed: 1, region: null });
            await wait(); await wait();
            const out = { scroller: c.overflowY, snap: c.scrollSnapType, mask: c.maskImage || 'none', tall: r.offsetHeight > innerHeight };
            return out; }""")
        check("the rail has no snap or fade of its own", rest["snap"] in ("none", "") and rest["mask"] == "none", str(rest))
        page.set_viewport_size({"width": 1300, "height": 900})
        print("[one design: Classic]")
        # New (Beta) is switched off: the menu offers no design, new.css is not loaded, and the page is Classic
        got = page.evaluate("""() => [document.documentElement.dataset.skin, !!document.getElementById('skin-seg'),
            [...document.styleSheets].some((x) => /new\\.css/.test(x.href || '')),
            getComputedStyle(document.documentElement).getPropertyValue('--paper').trim(),
            getComputedStyle(document.querySelector('.brand')).fontFamily, getComputedStyle(document.body, '::after').backgroundImage.includes('radial')]""")
        check("the menu offers no design and new.css is not loaded", got[:3] == ["classic", False, False], str(got))
        check("Classic is what it was: its colours, its name's face, its dot grid", got[3] == "#161719" and "Bricolage" in got[4] and got[5], str(got))
        # Each menu heading wears its own mark: counted by place, the marks slid onto the wrong headings when Design left, and Motion had none (a filled square)
        marks = page.evaluate("""() => [...document.querySelectorAll('#menu h3')].map((h) => { const c = getComputedStyle(h, '::before');
            return [h.textContent.trim(), c.webkitMaskImage || c.maskImage || 'none']; })""")
        mine = {"밝기": "r='4'", "움직임": "M3 12h4"}   # the sun's disc, the pulse line
        check("each menu heading wears its own mark", len(marks) >= 2 and all("url(" in m and mine.get(t, "url(") in m for t, m in marks)
              and len({m for _, m in marks}) == len(marks), str([(t, m[-60:]) for t, m in marks]))
        # In Classic: a page for each answer with the margin column, the details open, and bold still wearing the yellow
        cl = page.evaluate("""() => ({ sheet: getComputedStyle(document.querySelector('.thread > .entry')).boxShadow !== 'none',
            col: getComputedStyle(document.querySelector('.entry .row:not(.head):not([hidden])')).display,
                        role: document.querySelector('.conn .src-name').getAttribute('role') })""")
        check("Classic keeps its pages and its margin column", cl["sheet"] and cl["col"] == "grid" and cl["role"] in (None, "button"), str(cl))
        # The highlighter: a stressed word in prose wears it, a line that is only bold (a heading) does not; the welcome's headline too
        marks = page.evaluate("""() => { const hold = document.createElement('div'); hold.className = 'md';
            hold.innerHTML = '<p>앞 <strong id="st1">핵심</strong> 뒤</p><p class="lead"><strong id="st2">제목</strong></p><ul><li><strong id="st3">항목</strong></li></ul>';
            document.querySelector('.entry .ct').append(hold);
            const y = (id) => getComputedStyle(document.getElementById(id)).backgroundImage.includes('gradient');
            const out = [y('st1'), y('st2'), y('st3')]; hold.remove(); return out; }""")
        check("bold in prose wears the highlighter, a heading line does not", marks == [True, False, True], str(marks))
        print("[clearing, toasts, focus and the settings tabs at 360 px]")
        page.fill("#hist-q", "bfs")
        page.evaluate("() => { clearArmed = Date.now(); document.getElementById('clear').click(); }")
        page.wait_for_timeout(200)
        check("clearing the answers clears the search, so the next answer is listed", page.evaluate(
            "() => histQuery === '' && document.getElementById('hist-q').value === ''"))
        page.set_viewport_size({"width": 360, "height": 780})
        page.evaluate("(m) => handle(m)", {"type": "notice", "text": "서버에 연결되어 있지 않습니다. 잠시 뒤에 다시 해 보세요."})
        page.wait_for_timeout(300)
        box = page.evaluate("""() => { const r = document.getElementById('toast').getBoundingClientRect();
                                       return {w: r.width, top: r.top}; }""")
        check("at 360 px a toast takes the width it needs, not half the window, and sits under the bar",
              box["w"] > 200 and box["top"] < 120, str(box))
        check("a toast shows over the settings sheet", page.evaluate(
            "() => +getComputedStyle(document.getElementById('toast')).zIndex > "
            "+getComputedStyle(document.getElementById('settings-overlay')).zIndex"))
        page.evaluate("(s) => s.forEach(handle)", answer(ALGO, 9003, time.time()))
        page.wait_for_timeout(300)
        page.evaluate("() => document.querySelector('#history .h')?.focus()")
        page.evaluate("(e) => handle({ type: 'status', engines: e })", engines())
        check("a contents row keeps the keyboard's focus through a status message", page.evaluate(
            "() => document.activeElement?.classList.contains('h')"))
        page.evaluate("(m) => handle(m)", support.settings_message())
        page.evaluate("() => openSettings()")
        page.wait_for_timeout(300)
        over = page.evaluate("""() => [...document.querySelectorAll('.set-tab')].filter((t) => {
                                  const r = document.createRange(); r.selectNodeContents(t);
                                  return r.getBoundingClientRect().right > t.getBoundingClientRect().right + 0.5; })
                                .map((t) => t.textContent)""")
        check("at 360 px no settings tab's label runs out of its tab", not over, str(over))
        page.evaluate("() => closeSettings()")
        check("no errors on the page", not errors, json.dumps(errors)[:200])
        br.close()
    srv.shutdown()
    print(f"\n{len(PASS)} ok, {len(FAIL)} FAIL   shots in {SHOTS}")
    for f in FAIL:
        print(f"  FAIL {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
