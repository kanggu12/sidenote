"""Faults of the panel, each as a check that failed before its fix. Written for the New design;
New (Beta) is switched off, so every check runs on Classic, and one checks that New stays off.

    .venv-panel/bin/python tests/panel_new.py

Checked here: the highlighter, the contents staying inside their card, the rail's rows, the connection's rows that open,
history over a reconnect, the filters' counts and empty state, Export, the lists of Export and the filters opened at a phone's
foot clear of the contents' card, and the live drawing of a long answer.
"""
import json
import re
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import support  # tests/support.py: the output folder, a fresh copy of the panel, the panel's libraries

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
STATIC = support.out("panelstatic-new")         # the copy of panel/ that is served

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail and not cond else ""))


def answer(seq, ts, kind="short", text="풀이 **핵심 구절** 입니다.\n\n`코드` 와 **`굵은 코드`** 도 있습니다."):
    full = f"TYPE: {kind}\nANSWER: 답 {seq}\n\n{text}\n"
    return [{"type": "analysis_start", "id": seq, "ts": ts, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
            {"type": "analysis_done", "id": seq, "text": full, "usage": {}, "cost_usd": 0.0, "model": "m", "engine": "local",
             "sent": [], "stages": {"local": True, "agent": False}, "elapsed": 1.0, "region": None}]


def row(seq, ts, kind="short"):
    """One row of the server's /history."""
    return {"id": seq, "ts": ts, "kind": kind, "trigger": "screen", "transcript": "", "text": f"TYPE: {kind}\nANSWER: 옛 답 {seq}\n\n옛 풀이 {seq}.\n",
            "model": "m", "engine": "local", "sent": [], "usage": {}, "elapsed": 1.0, "thumb": None}


def fresh(br, url, width=1440, height=900, rows=(), theme="dark", skin="classic"):
    page = br.new_page(viewport={"width": width, "height": height}, accept_downloads=True, locale=support.LOCALE)
    page.set_default_timeout(5000)
    page.add_init_script(f"localStorage.setItem('sidenote-theme','{theme}');localStorage.setItem('sidenote-design','{skin}');"
                         "window.WebSocket = function () { window.__ws = this; this.close = function () {}; this.send = function () {}; this.readyState = 0; };")
    box = {"rows": list(rows), "asked": 0}
    def history(route):
        path = route.request.url
        if "history/days" in path:
            route.fulfill(json={"days": []})
        else:
            box["asked"] += 1
            route.fulfill(json={"answers": box["rows"]})
    page.route("**/history*", history)
    page.route("**/history/days*", history)
    page.goto(url, wait_until="load")
    page.wait_for_timeout(200)
    page.evaluate("""() => { wsState = 'up'; window.send = () => true; __ws.onopen && __ws.onopen();
        handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: false,
                 engines: { local: { ok: true, method: "local", model: "m", present: true, on: true, loaded: { model: "m" } },
                            agent: { ok: true, method: "claude.ai", present: true, mode: "hard", effective: "hard", payload: "crop", label: "Claude Code", short: "Claude" },
                            search: { present: true, on: true }, ready: true } });
        handle({ type: "capture", clients: 1, last_frame: Date.now() / 1000, last_audio: Date.now() / 1000, screen_on: true, audio_on: true, caps: { screen: true, audio: true, monitor: 1 } }); }""")
    page.wait_for_timeout(200)
    return page, box


def push(page, msgs):
    page.evaluate("(s) => s.forEach(handle)", msgs)


def many(page, n, start=100):
    now = time.time()
    for i in range(n):
        push(page, answer(start + i, now + i))
    page.wait_for_timeout(500)


def main() -> int:
    support.need_vendor(ROOT / "panel")
    support.panel_copy(STATIC)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(STATIC)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()

        print("[the highlighter]")
        for skin in ("classic",):
            page, _ = fresh(br, url, skin=skin)
            head = page.evaluate("() => getComputedStyle(document.querySelector('.welcome h1 mark.key')).backgroundImage")
            check(f"{skin}: the welcome's headline carries the highlighter on its key phrase", "gradient" in head, head)
            many(page, 1)
            bold = page.evaluate("""() => { const b = document.querySelector('.entry .md p strong'), c = getComputedStyle(b); return [c.backgroundImage, b.textContent]; }""")
            check(f"{skin}: bold in an answer wears it", "gradient" in bold[0] and bold[1] == "핵심 구절", str(bold))
            page.close()
        page, _ = fresh(br, url)
        many(page, 1)
        code = page.evaluate("() => getComputedStyle(document.querySelector('.entry .md strong code')).backgroundColor")
        check("bold code has no dark box on the marker", code in ("rgba(0, 0, 0, 0)", "transparent"), code)
        page.close()

        page, _ = fresh(br, url, height=600)
        page.wait_for_timeout(300)
        top = page.evaluate("() => [window.scrollY, document.querySelector('.welcome h1').getBoundingClientRect().top < innerHeight]")
        check("with nothing answered the welcome page opens at its top", top == [0, True], str(top))
        page.close()

        print("[the rail]")
        for skin in ("classic",):
            page, _ = fresh(br, url, skin=skin)
            many(page, 16)
            got = page.evaluate("""() => { const l = document.getElementById('history'), c = l.closest('.card').getBoundingClientRect();
                return { over: Math.min(l.getBoundingClientRect().bottom, l.lastElementChild.getBoundingClientRect().bottom) - c.bottom, cap: l.style.maxHeight }; }""")
            check(f"{skin}: the contents stay inside their card", got["over"] <= 0, str(got))
            reach = page.evaluate("""() => { const l = document.getElementById('history'); l.scrollTop = l.scrollHeight; return new Promise((f) => setTimeout(() => {
                const r = document.querySelector('.rail').getBoundingClientRect(); f([l.lastElementChild.getBoundingClientRect().bottom <= l.getBoundingClientRect().bottom + 2, r.bottom <= innerHeight, r.top]); }, 300)); }""")
            check(f"{skin}: its last row can be reached", reach[0], str(reach))
            page.set_viewport_size({"width": 900, "height": 900})
            page.wait_for_timeout(300)
            one = page.evaluate("() => document.querySelector('.rail').className")
            check(f"{skin}: narrowed to one column, no inner scroller is left", one.strip() == "rail", one)
            page.close()
        page, _ = fresh(br, url)
        many(page, 3)
        bars = page.evaluate("""() => { const w = document.createElement('div'); w.className = 'bars'; w.innerHTML = '<div class="bar"></div>'; document.getElementById('usage-local').append(w);
            const c = getComputedStyle(w.firstChild), out = [c.paddingTop, c.pointerEvents]; w.remove(); return out; }""")
        check("the usage bars are not taken for the top bar", bars == ["0px", "auto"], str(bars))
        page.close()

        print("[history over a connection]")
        now = time.time()
        page, box = fresh(br, url, rows=[row(i, now - 100 + i) for i in range(1, 6)])
        page.wait_for_timeout(300)
        first = page.evaluate("() => [thread.length, nearBottom(), viewId, window.scrollY, innerHeight, document.documentElement.scrollHeight]")
        check("a page with history opens on the newest answer", first[0] == 5 and first[1] and first[2] == 5, str(first))
        box["rows"] = [row(i, now - 100 + i) for i in range(1, 9)]
        page.evaluate("() => { __ws.onclose && __ws.onclose(); wsState = 'down'; __ws.onopen && __ws.onopen(); }")
        page.wait_for_timeout(400)
        check("what was answered while the connection was down comes in", page.evaluate("() => thread.length") == 8, str(box["asked"]))
        page.close()
        page, box = fresh(br, url)
        push(page, [answer(50, time.time())[0], {"type": "delta", "id": 50, "text": "TYPE: short\nANSWER: 반쪽\n\n쓰다 만"}])
        page.wait_for_timeout(200)
        page.evaluate("() => { items.get(50).shown = true; interruptLive(); }")
        cut = page.evaluate("() => items.get(50).hint")
        box["rows"] = [{**row(50, time.time()), "text": "TYPE: short\nANSWER: 전체\n\n끝까지 쓴 풀이.\n"}]
        page.evaluate("() => loadHistory({ limit: 40 })")
        page.wait_for_timeout(300)
        whole = page.evaluate("() => [items.get(50).hint, items.get(50).head.answer, document.querySelectorAll('.entry').length]")
        check("a card the drop cut off is replaced by the whole answer", cut == "interrupted" and not whole[0] and whole[1] == "전체" and whole[2] == 1, str(whole))
        page.close()
        page, _ = fresh(br, url)
        many(page, 1)
        page.evaluate("() => { window.send = () => false; clearArmed = Date.now() - 1000; document.getElementById('clear').click(); }")
        page.wait_for_timeout(100)
        check("Clear while offline deletes nothing and says so", page.evaluate("() => thread.length") == 1 and "못 지움" in page.evaluate("() => document.getElementById('toast').textContent"))
        page.evaluate("() => { toggleMenu(true); document.getElementById('clear').click(); toggleMenu(false); }")
        check("closing the menu disarms Clear", page.evaluate("() => clearArmed") == 0)
        # A double click arms it and asks again, and clears nothing: both presses came at once, and every answer was gone
        # with nothing asked (Reset to defaults the same)
        page.evaluate("() => { window.__sent = []; window.send = (m) => { window.__sent.push(m); return true; }; toggleMenu(true); }")
        page.evaluate("() => { const b = document.getElementById('clear'); b.click(); b.click(); }")
        page.wait_for_timeout(100)
        check("a double click on Clear history asks again and clears nothing",
              page.evaluate("() => thread.length === 1 && !window.__sent.some((m) => m.type === 'history_clear') && clearArmed > 0"))
        page.evaluate("() => { toggleMenu(false); openSettings(); const b = document.getElementById('settings-reset'); b.click(); b.click(); }")
        page.wait_for_timeout(100)
        check("...nor does one on Reset to defaults reset anything",
              page.evaluate("() => !window.__sent.some((m) => m.type === 'settings_reset') && resetArmed > 0"))
        page.evaluate("() => closeSettings()")
        page.close()

        print("[filters]")
        page, _ = fresh(br, url, height=1200, skin="classic")
        now = time.time()
        for i, kind in enumerate(("short", "math", "short", "math", "essay")):
            push(page, answer(200 + i, now + i, kind=kind))
        page.wait_for_timeout(400)
        kinds = page.evaluate("() => [...document.getElementById('hist-kind').options].map((o) => o.value)")
        days = page.evaluate("() => document.getElementById('hist-day').options.length")
        check("the filters offer what the page holds without a history fetch", {"short", "math", "essay"} <= set(kinds) and days == 2, str([kinds, days]))
        page.select_option("#hist-kind", "math")
        page.wait_for_timeout(200)
        check("the count says how many of how many", page.evaluate("() => document.getElementById('hist-count').textContent") == "2/5")
        with page.expect_download() as dl:
            page.click("#hist-export")
            page.click("#export-menu [data-export='md']")   # Export's menu: the Markdown file
        md = Path(dl.value.path()).read_text(encoding="utf-8")
        check("Export writes what the contents list, without the engine's lines", md.count("\n## ") == 2 and "TYPE:" not in md and "ANSWER:" not in md, md[:160])
        check("and says how many it wrote", "답 2개" in page.evaluate("() => document.getElementById('toast').textContent"))
        page.evaluate("""() => { histKind = 'math'; histDay = '2001-01-01'; renderIndex(); }""")
        page.wait_for_timeout(100)
        none = page.evaluate("() => [document.getElementById('choice-none').hidden, document.getElementById('hist-nomatch').hidden]")
        check("a filter that hides everything says so, on the stage and in the contents", none == [False, False], str(none))
        page.click("#choice-reset")
        page.wait_for_timeout(100)
        check("and offers the way back", page.evaluate("() => [histDay, histKind, document.getElementById('choice-none').hidden]") == ["", "", True])
        page.fill("#hist-q", "TCP없음")
        page.wait_for_timeout(500)
        said = page.evaluate("() => document.getElementById('hist-nomatch').textContent")
        # what was typed in its quotes, and no particle after it: one after a Latin word ("GPU") could not be told by its letters
        check("the search says what was typed", said == "'TCP없음' 검색 결과 없음", said)
        page.close()

        print("[what the panel keeps while it redraws]")
        page, _ = fresh(br, url)
        many(page, 12)
        gaps = page.evaluate("""() => new Promise((done) => { stick = false; const es = [...document.querySelectorAll('.entry')], e = es[5];
            const seen = new Set(); let y = e.offsetTop - innerHeight * 0.33 - 30; const end = y + 80;
            const step = () => { if (y > end) return done([...seen]); window.scrollTo(0, y); stick = false; updateView(); seen.add(viewId); y += 4; requestAnimationFrame(step); }; step(); })""")
        check("crossing a gap, the screen in the rail stays on what is being read", page.evaluate("() => latestId()") not in gaps and len(gaps) <= 2, str(gaps))
        kept = page.evaluate("""() => { const id = latestId(), it = items.get(id), el = entryEl(id), d = document.createElement('details');
            d.innerHTML = '<summary>x</summary>y'; el.querySelector('[data-body]').append(d); d.open = true;
            const first = el.querySelector('details');
            // what the entry draws has no details of its own in this answer: an answer with a chart does, and renderEntry restores by place
            renderEntry(it); return !!first; }""")
        check("(an entry draws again without an error)", kept)
        page.close()

        print("[rows and columns]")
        page, _ = fresh(br, url, width=1500)
        now = time.time()
        push(page, answer(400, now, text="문단입니다.\n\n```python\nprint(1)\n```\n\n| 가 | 나 |\n|---|---|\n| 1 | 2 |\n"))
        page.wait_for_timeout(500)
        got = page.evaluate("""() => { const R = (e) => e.getBoundingClientRect(), n = (x) => Math.round(x), set = (a) => [...new Set(a.map(n))];
            const e = document.querySelector('.entry'), b = R(e), conn = document.querySelector('.conn'), c = R(conn), hist = document.querySelector('.history'), h = R(hist);
            const glyph = (x) => { const r = document.createRange(); r.selectNodeContents(x); return r.getBoundingClientRect(); };
            return { left: set([...e.querySelectorAll('.md > p, .md > pre, .md > .tablewrap')].map((x) => R(x).left - b.left)),
                     kind: n(R(e.querySelector('.kind')).left - b.left),
                     right: set([...e.querySelectorAll('.md > pre, .md > .tablewrap')].map((x) => b.right - R(x).right)),
                     pills: set([...conn.querySelectorAll('.pill')].filter((x) => x.offsetParent).map((x) => c.right - R(x).right)),
                     icons: set([...conn.querySelectorAll('.src-name svg')].filter((x) => x.getBoundingClientRect().width).map((x) => R(x).left - c.left)),
                     heads: [conn.querySelector('h2')?.offsetHeight ? n(R(conn.querySelector('h2')).left - c.left) : n(R(hist.querySelector('h2')).left - h.left), n(R(hist.querySelector('h2')).left - h.left)],
                     titles: set([...hist.querySelectorAll('.ht')].map((x) => R(x).left - h.left)), times: set([...hist.querySelectorAll('.h time')].map((x) => h.right - R(x).right)) }; }""")
        # Classic: the kind is in the margin column, before the text (New had them on one edge, and its bar on the panels' edges)
        check("an answer's text, code and table start on one edge, its kind in the margin before them",
              len(got["left"]) == 1 and got["kind"] < got["left"][0], str(got))
        check("its code and table end on one edge", len(got["right"]) == 1, str(got))
        check("a connection's state is in one column, with or without a switch", len(got["pills"]) == 1, str(got))
        check("the rail's marks and headings start on one edge", got["icons"] == got["heads"][:1] and got["heads"][0] == got["heads"][1], str(got))
        check("the contents' titles and times keep one column each", len(got["titles"]) == 1 and len(got["times"]) == 1, str(got))
        page.close()

        print("[the default and the answer's copy button]")
        page = br.new_page(viewport={"width": 1400, "height": 900}, locale=support.LOCALE); page.add_init_script("window.WebSocket = function () { window.__ws = this; this.close = function () {}; this.send = function () {}; };")
        page.route("**/history*", lambda r: r.fulfill(json={"answers": [], "days": []}))
        page.goto(url, wait_until="load")
        check("the design is Classic and the menu offers no other", page.evaluate("() => [document.documentElement.dataset.skin, !!document.getElementById('skin-seg')]") == ["classic", False])
        check("loading the page writes no choice", page.evaluate("() => localStorage.getItem('sidenote-design')") is None)
        page.close()
        page, _ = fresh(br, url, skin="new")    # New picked before it was switched off: what was stored is not read
        check("a New picked before still opens Classic", page.evaluate("() => document.documentElement.dataset.skin") == "classic")
        page.close()
        for skin in ("classic",):
            page, _ = fresh(br, url, width=1400, skin=skin)
            push(page, answer(600, time.time()))
            page.wait_for_timeout(400)
            right = page.evaluate("""() => { const e = document.querySelector('.entry'), a = e.querySelector('[data-copy-answer]'), t = e.querySelector('.tools .btn:last-child');
                return [Math.round(a.getBoundingClientRect().right), Math.round(t.getBoundingClientRect().right)]; }""")
            check(f"{skin}: the answer's copy button ends on the same edge as the other tools", abs(right[0] - right[1]) <= 16, str(right))   # the answer's group has its own inset
            page.close()

        print("[opening the page]")
        page = br.new_page(viewport={"width": 1400, "height": 900}, locale=support.LOCALE)
        page.add_init_script("window.WebSocket = function () { window.__ws = this; this.close = function () {}; this.send = function () {}; };")
        import threading as _t
        gate = _t.Event()
        def slow(route):
            gate.wait(2)
            route.fulfill(json={"answers": [row(i, time.time() - 50 + i) for i in range(1, 6)], "days": []})
        page.route("**/history*", slow)
        page.route("**/history/days*", lambda r: r.fulfill(json={"days": []}))
        page.goto(url, wait_until="commit")
        page.wait_for_selector("#boot", state="attached")
        page.wait_for_timeout(300)
        boot = page.evaluate("""() => { __ws.onopen && __ws.onopen(); return [document.documentElement.classList.contains('booting'), getComputedStyle(document.getElementById('boot')).display, getComputedStyle(document.getElementById('welcome')).visibility]; }""")
        check("while the history comes, placeholders stand in and the welcome page does not flash", boot == [True, "grid", "hidden"], str(boot))
        gate.set()
        page.wait_for_function("() => !document.documentElement.classList.contains('booting')", timeout=4000)
        done = page.evaluate("() => [getComputedStyle(document.getElementById('boot')).display, thread.length]")
        check("then they go, the answers in place", done == ["none", 5], str(done))
        page.close()
        # A history that takes longer than the page waits with no server at all (1.8 s): the placeholders stay until it
        # comes. Let go at 1.8 s, the first-run welcome page and its checklist stood there for the rest of the wait
        page = br.new_page(viewport={"width": 1400, "height": 900}, locale=support.LOCALE)
        page.add_init_script("window.WebSocket = function () { window.__ws = this; this.close = function () {}; this.send = function () {}; };")
        held = []                                        # the request for the answers, kept unanswered
        page.route("**/history*", lambda r: held.append(r))   # a function of this file: the browser driver marks the handler it is given, and a list's own method takes no mark
        page.route("**/history/days*", lambda r: r.fulfill(json={"days": []}))
        page.goto(url, wait_until="commit")
        page.wait_for_selector("#boot", state="attached")
        page.wait_for_timeout(300)
        page.evaluate("() => { __ws.onopen && __ws.onopen(); }")
        page.wait_for_timeout(2400)                      # 2.7 s after it opened, the history still on its way
        waiting = page.evaluate("() => [document.documentElement.classList.contains('booting'), getComputedStyle(document.getElementById('welcome')).visibility]")
        check("a history slower than 1.8 s is waited for, the welcome page not shown meanwhile", len(held) == 1 and waiting == [True, "hidden"], f"{len(held)} {waiting}")
        if held:
            held[0].fulfill(json={"answers": [row(i, time.time() - 50 + i) for i in range(1, 6)], "days": []})
        page.wait_for_function("() => !document.documentElement.classList.contains('booting')", timeout=4000)
        done = page.evaluate("() => [getComputedStyle(document.getElementById('boot')).display, thread.length]")
        check("...and they go as it comes, the answers in place", done == ["none", 5], str(done))
        page.close()
        page, _ = fresh(br, url)
        ended = page.evaluate("() => document.documentElement.classList.contains('booting')")
        check("with no server the placeholders do not stay", not ended or page.wait_for_function("() => !document.documentElement.classList.contains('booting')", timeout=4000) is not None)
        page.close()

        print("[the menu]")
        page, _ = fresh(br, url)
        page.wait_for_timeout(2000)
        page.click("#more")
        veil = page.evaluate("() => { const v = document.getElementById('menu-veil'), c = getComputedStyle(v); return [v.hidden, c.position, c.backgroundColor !== 'rgba(0, 0, 0, 0)', document.elementFromPoint(300, 500) === v]; }")
        check("behind the open menu the page steps back", veil == [False, "fixed", True, True], str(veil))
        page.mouse.click(300, 500)
        check("and a click there closes it", page.evaluate("() => [document.getElementById('menu').hidden, document.getElementById('menu-veil').hidden]") == [True, True])
        page.close()

        print("[the GPU chart and the agent card]")
        page, _ = fresh(br, url, width=1500, height=1200, skin="classic")
        page.evaluate("""() => { for (let i = 0; i < 5; i++) handle({ type: "gpu", util: 20 + i * 10, used: 8000, total: 23000, temp: 60, power: 100 });
            handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: false,
              engines: { local: { ok: true, method: "local", model: "m", present: true, on: true, loaded: { model: "m" } },
                agent: { ok: true, method: "claude.ai", present: true, mode: "hard", effective: "hard", payload: "crop", label: "Claude Code", short: "Claude", product: "Claude Code", account: { email: "me@example.com", plan: "pro" } },
                search: { present: true, on: true }, ready: true } }); }""")
        page.wait_for_timeout(200)
        viz = page.evaluate("""() => { const g = document.getElementById('gpu-viz'), a = document.getElementById('st-agent');
            return { shown: !g.hidden && g.getBoundingClientRect().height > 40, h: g.getBoundingClientRect().height, tight: document.querySelector('.rail').className, util: g.textContent.includes('60%'), mem: g.textContent.includes('7.8 / 22.5 GB'), points: g.querySelector('polyline').getAttribute('points').split(' ').length,
                     mail: a.querySelector('.mail')?.textContent, how: a.querySelector('.how')?.textContent, scales: a.querySelectorAll('.agent-scale').length, onMode: a.querySelectorAll('.agent-scale:first-of-type .on').length, wide: document.documentElement.scrollWidth - innerWidth }; }""")
        check("the GPU chart shows how busy and how full", viz["shown"] and viz["util"] and viz["mem"] and viz["points"] == 5, str(viz))
        check("the agent card names the account and shows its settings on scales", viz["mail"] == "me@example.com" and viz["how"] == "Claude Code Pro" and viz["scales"] == 2 and viz["wide"] <= 0, str(viz))
        page.evaluate("""() => { handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: false,
            engines: { local: { ok: true, method: "local", model: "m", present: true, on: true, loaded: null }, agent: { ok: true, method: "claude.ai", present: true, mode: "hard", effective: "hard", payload: "crop" }, search: { present: true, on: true }, ready: true } }); }""")
        page.wait_for_timeout(100)
        left = page.evaluate("() => { handle({ type: 'gpu', util: 5, used: 2000, total: 23000, temp: 40, power: 50 }); return [document.getElementById('gpu-viz').textContent, document.getElementById('st-local').textContent]; }")
        check("the gauge stays, and the GPU's line says the model has left", "GPU 사용" in left[0] and "비어 있음" in left[1], left)
        page.close()

        page, _ = fresh(br, url, skin="classic")
        push(page, answer(800, time.time(), text="**요지:** 풀이입니다.\n\n- **분산 트랜잭션:** 설명 **핵심** 끝"))
        page.wait_for_timeout(400)
        labs = page.evaluate("""() => [...document.querySelectorAll('.entry .md strong')].map((b) => [b.textContent, b.classList.contains('lab'), getComputedStyle(b).backgroundImage.includes('gradient')])""")
        check("a paragraph's short label is in the red pen, what is stressed under the highlighter", labs[0] == ["요지:", True, False] and labs[-1] == ["핵심", False, True], str(labs))
        page.close()

        page, _ = fresh(br, url, width=1500, skin="classic")
        many(page, 6)
        page.evaluate("() => handle({ type: 'status', paused: true, lang: 'auto', audio: true, can_ask: true, run_enabled: false, engines: eng() })")
        page.wait_for_timeout(400)
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        edges = page.evaluate("""() => { const R = (s) => document.querySelector(s).getBoundingClientRect(), a = R('.alert'), r = R('.rail'), t = R('.sheet.thread'), b = R('header.bar');
            return { lines: Math.abs(t.top - r.top), over: a.right - r.left, gap: a.top - b.bottom, railGap: Math.round(r.top - b.bottom) }; }""")
        check("the right column starts one gap under the bar", edges["railGap"] == 18, str(edges))
        page.close()

        for height in (700, 900, 1040, 1100, 1200):
            page, _ = fresh(br, url, width=1500, height=height, skin="classic")
            many(page, 12)
            # Going down the last of the page the column never moves by itself: one that fits under the bar stands still in the
            # window; one taller than the window (it drifts) moves up with the page by no more than the page moved, until its
            # foot is in the window, and from there stands still, a pixel at the page's end included
            seen = page.evaluate("""async () => { const r = document.querySelector('.rail'), wait = (n) => new Promise((f) => setTimeout(f, n)); await wait(300);
                const seen = [], end = document.documentElement.scrollHeight - innerHeight;
                for (const y of [end - 300, end - 120, end - 40, end - 10, end - 2, end]) { window.scrollTo(0, y); await wait(120); const R = r.getBoundingClientRect(); seen.push([scrollY, R.top, R.bottom, innerHeight, r.classList.contains('stick')]); }
                return seen; }""")
            with_page = all(-(b[0] - a[0]) - 0.5 <= b[1] - a[1] <= 0.5 for a, b in zip(seen, seen[1:]))
            still_at_end = abs(seen[-1][1] - seen[-2][1]) <= 0.5 and seen[-1][2] <= seen[-1][3] + 0.5
            fits_still = not seen[0][4] or max(abs(x[1] - seen[0][1]) for x in seen) <= 0.5
            check(f"{height} px: going down the last of the page the column moves no more than the page, never by itself, its foot in view at the end",
                  with_page and still_at_end and fits_still, str(seen))
            page.close()
        page, _ = fresh(br, url, width=1500, skin="classic")
        many(page, 6)
        page.evaluate("() => handle({ type: 'status', paused: true, lang: 'auto', audio: true, can_ask: true, run_enabled: false, engines: eng() })")
        page.wait_for_timeout(400)
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        grid = page.evaluate("""() => { const R = (s) => document.querySelector(s).getBoundingClientRect();
            const a = R('.alerts'), t = R('.sheet.thread'), r = R('.rail');
            return { pills: [...document.querySelectorAll('.conn .src-top')].filter((e) => e.offsetParent).map((e) => Math.round(e.querySelector('.pill').getBoundingClientRect().left - e.querySelector('.src-name').getBoundingClientRect().right)),
                     inset: [Math.round(a.left - t.left), Math.round(t.right - a.right)], tops: Math.round(Math.abs(a.top - r.top)), sheet: Math.round(Math.abs(t.top - r.top)) }; }""")
        # Beside its name, not out at a column of its own
        check("a connection's state stands beside its name", grid["pills"] and all(0 <= g <= 12 for g in grid["pills"]), str(grid))
        top = page.evaluate("""() => { const a = document.querySelector('.alerts').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect(); return [document.documentElement.classList.contains('bands-in-bar'), a.bottom <= b.bottom + 1]; }""")
        check("at the very top of the page the band sits in the bar, over nothing of the thread", top == [True, True], str(top))
        check("a band takes no room: the thread starts level with the right column", grid["sheet"] <= 1, str(grid))
        page.evaluate("() => window.scrollTo(0, 700)")
        page.wait_for_timeout(300)
        scrolled = page.evaluate("() => Math.abs(document.querySelector('.alerts').getBoundingClientRect().top - document.querySelector('.rail .card').getBoundingClientRect().top) ")
        check("and still level once scrolled", scrolled <= 1 or page.evaluate("() => document.querySelector('.rail').offsetHeight > innerHeight"), str(scrolled))
        out = page.evaluate("""() => { const a = document.querySelector('.alerts').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect();
            return { inBar: document.documentElement.classList.contains('bands-in-bar'), within: a.top >= b.top && a.bottom <= b.bottom }; }""")
        # in the bar scrolled too: floating under it once scrolled, it lay over the cards and their edges ran under it
        check("scrolled, it stays in the bar, over nothing of the thread", out["inBar"] and out["within"], str(out))
        page.close()
        page, _ = fresh(br, url, skin="classic")
        push(page, answer(810, time.time(), text="## (1) 첫 질문?\n\n답 하나.\n\n- 항목\n\n## (2) 둘째 질문?\n\n답 둘.\n\n맺음말은 둘째 뒤."))
        page.wait_for_timeout(500)
        qa = page.evaluate("""() => [...document.querySelectorAll('.entry .md > .qa')].map((b) => [b.querySelector('.qa-no')?.textContent, b.firstElementChild.textContent.trim()])""")
        check("several questions at once are set off, each under its numbered head, each under its numbered head", qa == [["(1)", "(1) 첫 질문?"], ["(2)", "(2) 둘째 질문?"]], str(qa))
        page.close()

        for height in (700, 950, 1100):
            page, _ = fresh(br, url, width=1500, height=height, skin="classic")
            many(page, 12)
            page.wait_for_timeout(300)
            # One gap under the bar at the top of the page; its foot is in the window once the page is scrolled to it (the page
            # scrolls at least as far as the right column is tall), nothing of it cut or folded to fit
            still = page.evaluate("""async () => { const r = document.querySelector('.rail'), b = document.querySelector('header.bar'), wait = () => new Promise((f) => setTimeout(f, 150));
                window.scrollTo(0, 0); await wait(); const gap = Math.round(r.getBoundingClientRect().top - b.getBoundingClientRect().bottom);
                window.scrollTo(0, r.getBoundingClientRect().bottom + scrollY - innerHeight + 24); await wait();
                return { gap, foot: Math.round(r.getBoundingClientRect().bottom), win: innerHeight, cls: r.className, cut: r.style.overflow + r.style.maxHeight }; }""")
            check(f"{height} px: the column starts one gap under the bar, and the page scrolls far enough to bring its foot into the window",
                  still["gap"] == 18 and still["foot"] <= still["win"] and still["cls"] in ("rail stick", "rail drift") and not still["cut"], str(still))
            inner = page.evaluate("() => { const r = document.querySelector('.rail'), c = getComputedStyle(r); return [c.overflowY, r.scrollHeight - r.clientHeight]; }")
            check(f"{height} px: the rail has no scroller of its own", inner[0] in ("visible", "hidden"), str(inner))
            page.close()
        print("[the contents' dropdowns and the lamps]")
        page, _ = fresh(br, url, width=1500, skin="classic")
        now = time.time()
        for i, kind in enumerate(("short", "math", "short")):
            push(page, answer(700 + i, now + i, kind=kind))
        page.wait_for_timeout(2000)
        page.click('.combo-btn[data-proxy="hist-kind"]')
        page.wait_for_timeout(120)
        li = page.evaluate("() => [...document.querySelectorAll('.combo-list:not([hidden]) li')].map((l) => l.textContent.trim())")
        check("the filter opens the page's own list, not the browser's", len(li) >= 3 and li[0] == "모든 유형", str(li))
        page.click('.combo-list:not([hidden]) li:nth-child(3)')
        page.wait_for_timeout(150)
        picked = page.evaluate("() => [document.getElementById('hist-kind').value, histKind, document.querySelector('.combo-btn[data-proxy=hist-kind] .combo-val').textContent, document.querySelectorAll('#history .h').length]")
        check("picking there filters, and the button says it", picked[0] == picked[1] != "" and picked[3] < 3, str(picked))
        lamps = page.evaluate("""() => { const s = (e, p) => { const c = getComputedStyle(e, p); return c.width + '/' + c.borderRadius; };
            const out = new Set(); document.querySelectorAll('.signal[data-state=ok] .dot').forEach((e) => out.add(s(e))); document.querySelectorAll('.pill[data-state=ok]').forEach((e) => out.add(s(e, '::before')));
            document.querySelectorAll('.meta .by').forEach((e) => out.add(s(e, '::before'))); document.querySelectorAll('.facts .lit').forEach((e) => out.add(s(e, '::before'))); return [...out]; }""")
        check("every lamp is the same lamp", len(lamps) == 1, str(lamps))
        page.close()

        print("[the contents' lists at a phone's foot]")
        # Export's menu and the two filters' lists, their key at the foot of a phone's window: under the key, the page scrolled
        # up for them as far as it goes. Opened over the key, they ran across the top edge of the contents' card
        page, _ = fresh(br, url, width=390, height=844, skin="classic")
        now = time.time()
        for i, kind in enumerate(("short", "math", "short", "math", "essay")):
            push(page, answer(800 + i, now + i, kind=kind))
        page.wait_for_timeout(600)
        for name, key, shown in (("Export's menu", "#hist-export", "#export-menu"),
                                 ("the dates' list", '.combo-btn[data-proxy="hist-day"]', ".combo-list:not([hidden])"),
                                 ("the types' list", '.combo-btn[data-proxy="hist-kind"]', ".combo-list:not([hidden])")):
            page.evaluate("(k) => { window.scrollTo(0, 0); document.querySelector(k).scrollIntoView({ block: 'end' }); }", key)   # the key at the window's foot
            page.wait_for_timeout(150)
            page.evaluate("(k) => document.querySelector(k).click()", key)
            page.wait_for_timeout(200)
            got = page.evaluate("""([k, m]) => { const key = document.querySelector(k).getBoundingClientRect(), list = document.querySelector(m)?.getBoundingClientRect();
                const card = document.querySelector('.card.history').getBoundingClientRect();
                return list ? { list: [Math.round(list.top), Math.round(list.bottom)], key: [Math.round(key.top), Math.round(key.bottom)], card: Math.round(card.top), h: innerHeight } : null; }""",
                                [key, shown])
            check(f"390 px: {name} opens clear of the contents card's top edge, inside the window",
                  bool(got) and got["list"][0] >= got["card"] and got["list"][1] <= got["h"], str(got))
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
        page.close()

        print("[the live drawing of a long answer]")
        page, _ = fresh(br, url)
        body = "".join(f"## 절 {i}\n\n문단 {i}의 **핵심** 내용입니다. " + "긴 문장을 이어 씁니다. " * 12 + f"\n\n- 항목 {i}\n- 항목 {i}+1\n\n```python\nprint({i})\n```\n\n| 열 | 값 |\n|---|---|\n| a | {i} |\n\n$$x_{i}^2$$\n\n" for i in range(40))
        full = "TYPE: essay\nANSWER: 긴 답\n\n" + body
        page.evaluate("(m) => handle(m)", answer(77, time.time())[0])
        step = 1400
        for at in range(0, len(full), step):
            page.evaluate("(m) => handle(m)", {"type": "delta", "id": 77, "text": full[at:at + step]})
            page.wait_for_timeout(40)
        page.wait_for_timeout(300)
        live = page.evaluate("""() => { const b = entryEl(77).querySelector('[data-body]'); return [!!b.__live, b.innerText.replace(/\\s+/g, ''), b.querySelectorAll('h2').length, b.querySelectorAll('pre').length, b.querySelectorAll('table').length, b.querySelectorAll('.katex-display').length]; }""")
        check("a long answer is drawn block by block", live[0], str(live[0]))
        page.evaluate("(m) => handle(m)", {"type": "analysis_done", "id": 77, "text": full, "usage": {}, "cost_usd": 0.0, "model": "m", "engine": "local", "sent": [], "stages": {}, "elapsed": 1.0, "region": None})
        page.wait_for_timeout(500)
        done = page.evaluate("""() => { const b = entryEl(77).querySelector('[data-body]'); return [!!b.__live, b.innerText.replace(/\\s+/g, ''), b.querySelectorAll('h2').length, b.querySelectorAll('pre').length, b.querySelectorAll('table').length, b.querySelectorAll('.katex-display').length]; }""")
        check("the same headings, code, tables and formulas as the final drawing", live[2:] == done[2:] and not done[0], json.dumps([live[2:], done[2:]]))
        page.close()

        print("[folded answers]")
        page, _ = fresh(br, url)
        many(page, 8)
        page.evaluate("() => refold && refold()")
        page.wait_for_timeout(300)
        got = page.evaluate("""() => { const f = document.querySelector('.entry.folded'); return f ? [f.querySelector('[data-body]').childElementCount, f.dataset.id] : null; }""")
        if got:
            check("a folded answer's body is not drawn until it is opened", got[0] == 0, str(got))
            page.evaluate("(id) => { unfolded.add(+id); renderEntry(items.get(+id)); }", got[1])
            math = page.evaluate("""() => { const it = items.get(latestId() - 3); unfolded.delete(it.id); it.raw = 'TYPE: short\\nANSWER: 시간 $O(n)$\\n\\n풀이.'; it.head = splitHead(it.raw, true);
                renderEntry(it); const a = entryEl(it.id).querySelector('.hl'); return [entryEl(it.id).classList.contains('folded'), a.textContent.includes('$'), !!a.querySelector('.katex')]; }""")
            check("a formula in a folded answer's line is still set", math == [True, False, True], str(math))
            check("and is drawn when it is", page.evaluate("(id) => entryEl(+id).querySelector('[data-body]').childElementCount", got[1]) > 0)
        else:
            check("(an answer folds)", False, "none folded")
        page.close()

        print("[the right column at every window size]")
        STATUS = """(L) => handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: false,
            engines: { local: Object.assign({ ok: true, method: "local", model: "m", present: true, on: true, loaded: { model: "m" } }, L || {}),
              agent: { ok: true, method: "claude.ai", present: true, mode: "hard", effective: "hard", payload: "crop", label: "Claude Code", short: "Claude", product: "Claude Code", account: { email: "me@example.com", plan: "pro" } },
              search: { present: true, on: true }, ready: true } })"""
        CAPTURE = """(n) => handle({ type: "capture", clients: n, last_frame: Date.now() / 1000, last_audio: Date.now() / 1000, screen_on: true, audio_on: true,
            caps: { screen: true, audio: true, audio_device: "speakers", monitor: 1 } })"""
        GAUGE = """() => { for (let i = 0; i < 5; i++) handle({ type: "gpu", util: 40, used: 8000, total: 23000, temp: 60, power: 100 }); }"""
        RAIL = """() => { const r = document.querySelector('.rail'), s = getComputedStyle(r.parentElement), l = document.getElementById('history');
            return { cls: r.className, foot: r.getBoundingClientRect().bottom, room: innerHeight, cut: r.style.overflow, gpu: !!document.getElementById('gpu-viz').offsetHeight,
                     agent: !!document.querySelector('.agent-viz')?.offsetHeight, rows: l.querySelectorAll('.h').length, capped: l.scrollHeight > l.clientHeight + 1,
                     facts: r.querySelectorAll('.facts dd').length && [...r.querySelectorAll('.facts')].filter((f) => f.offsetHeight).length, agentFacts: !!document.querySelector('#st-agent .facts')?.offsetHeight, sums: !!document.getElementById('usage-local').offsetHeight && document.getElementById('usage-local').innerText.includes('TTFT') && document.querySelector('.usage-top').scrollWidth <= document.querySelector('.usage-top').clientWidth, rowH: l.querySelector('.h')?.getBoundingClientRect().height, free: innerHeight - 36 - r.getBoundingClientRect().bottom,
                     shot: document.getElementById('shot').getBoundingClientRect().height,
                     gpuline: [...document.querySelectorAll('#st-local .fact')].find((f) => f.querySelector('dt')?.textContent === 'GPU')?.innerText || '',
                     reach: document.scrollingElement.scrollHeight >= r.getBoundingClientRect().bottom + scrollY,
                     vis: [...r.querySelectorAll('*')].filter((e) => e.getClientRects().length && !e.closest('#history')).length,
                     lines: [...l.children].filter((c) => { const a = c.getBoundingClientRect(), b = l.getBoundingClientRect(); return a.height && a.top >= b.top - 1 && a.bottom <= b.bottom + 1; }).length }; }"""
        rail = {}
        for w, h in ((1920, 1080), (1500, 950), (1366, 768), (1500, 700), (1500, 620)):
            page, _ = fresh(br, url, width=w, height=h, skin="classic")
            page.evaluate(STATUS, None)
            page.evaluate(CAPTURE, 1)
            page.evaluate(GAUGE)
            page.evaluate("""() => handle({ type: "usage", answers: 3, tokens_in: 33401, tokens_out: 560, cost_usd: 0.03, errors: 0, elapsed_p50: 3.2, first_token_avg: 1.6, tps_avg: 45.2 })""")
            many(page, 30)
            page.wait_for_timeout(200)
            rail[h] = page.evaluate(RAIL)
            # Nothing folds, hides or is cut to fit a window: everything shows, the same at every resolution; the page is as tall as
            # the column, so its foot is reached by scrolling
            check(f"at {w}x{h} nothing in the column is folded or cut, and the page reaches its foot", rail[h]["cls"] in ("rail stick", "rail drift") and not rail[h]["cut"] and rail[h]["reach"], json.dumps(rail[h]))
            page.close()
        # No screen has come in these rows: the picture's box is the one line that says so. With a picture, tests/panel_design.py and fit tables hold it
        check("at every size the GPU's gauges, the agent's card and the picture's place", all(r["gpu"] and r["agent"] and r["shot"] >= 40 for r in rail.values()), json.dumps(rail))
        check("at every size the sources' details", all(r["facts"] >= 3 for r in rail.values()), json.dumps({h: r["facts"] for h, r in rail.items()}))
        check("at every size the average TTFT and TPS, on one line", all(r["sums"] for r in rail.values()), json.dumps({h: r["sums"] for h, r in rail.items()}))
        check("at every size the agent's account and its model", all(r["agent"] and r["agentFacts"] for r in rail.values()), json.dumps(rail[768]))
        check("the same things show at every size", len({r["vis"] for r in rail.values()}) == 1, json.dumps({h: r["vis"] for h, r in rail.items()}))
        page, _ = fresh(br, url, width=1500, height=950, skin="classic")
        page.evaluate("""() => handle({ type: "status", paused: false, lang: "auto", audio: true, can_ask: true, run_enabled: false,
            engines: { local: { ok: true, method: "local", model: "m", present: true, on: true, loaded: { model: "m", quant: "Q4_K_M", params: "26B", ctx: 32768 } },
              agent: { ok: true, method: "claude.ai", present: true, mode: "hard", effective: "hard", payload: "crop", label: "Claude Code", short: "Claude", product: "Claude Code", model: "claude-opus-5-5", effort: "medium", effort_own: true, thinking: "adaptive", max_tokens: 128000 },
              search: { present: true, on: true }, ready: true } })""")
        page.wait_for_timeout(100)
        said = page.evaluate("() => [document.getElementById('st-agent').innerText, document.getElementById('st-local').innerText]")
        # The thinking setting and the output limit are not worth a row; the model and its effort stay, on one row
        check("the agent's card names its model and effort, and not its thinking or output limit",
              all(w in said[0] for w in ("claude-opus-5-5", "보통")) and not any(w in said[0] for w in ("adaptive", "128,000", "최대 출력")), said[0])
        check("the local model's card names its size, quantization and context", all(w in said[1] for w in ("Q4_K_M", "26B", "32,768")), said[1])
        page.close()
        # The contents' list keeps a scroll of its own: its first nine lines (rows and the days' tabs) whole, the same at every size
        check("the contents' list shows its first nine lines whole at every size, and scrolls inside its card for the rest",
              all(r["capped"] and r["lines"] == 9 for r in rail.values()), json.dumps({h: [r["capped"], r["lines"]] for h, r in rail.items()}))

        page, _ = fresh(br, url, width=1500, height=380, skin="classic")
        page.evaluate(STATUS, None); page.evaluate(GAUGE); many(page, 12)
        page.set_viewport_size({"width": 900, "height": 1000})
        page.wait_for_timeout(200)
        left = page.evaluate("""() => { const r = document.querySelector('.rail'); return [r.style.maxHeight, r.style.overflow, document.documentElement.style.getPropertyValue('--shot-h'), r.className]; }""")
        check("narrowed to one column, nothing a short window asked of the rail stays", left[:3] == ["", "", ""] and "tight" not in left[3], str(left))
        page.close()

        page, _ = fresh(br, url, width=1500, height=1200, skin="classic")
        page.evaluate(STATUS, None); page.evaluate(CAPTURE, 0)
        page.wait_for_timeout(100)
        off = page.evaluate("""() => { const p = document.getElementById('pill-screen'), s = document.getElementById('sw-screen'); return [p.dataset.state, s.dataset.dead, getComputedStyle(s).backgroundColor, document.getElementById('pill-audio').dataset.state]; }""")
        rgb = lambda c: [float(x) for x in re.findall(r"\d*\.?\d+", c.split("(", 1)[1])[:3]]
        check("the capture program off is grey and at rest on the pill and the switch", off[0] == "idle" and off[3] == "idle" and off[1] == "true" and page.evaluate("() => document.getElementById('sw-screen').disabled"), str(off))
        page.evaluate(CAPTURE, 1); page.wait_for_timeout(50)
        check("and back on, green", page.evaluate("() => document.getElementById('sw-screen').dataset.dead") == "false")
        # the GPU's load
        page.evaluate(STATUS, {"loaded": None, "loading": True})
        load = page.evaluate("""() => { const b = document.getElementById('gpu-load'); return [document.getElementById('pill-local').textContent, b.hidden, b.textContent, getComputedStyle(b).color, document.getElementById('gpu-release').hidden]; }""")
        check("while loading the pill says so and Cancel is orange, with the steps under it", load[0] == "올리는 중" and not load[1] and load[2] == "취소" and load[3] == "rgb(255, 176, 102)" and page.evaluate("() => document.querySelectorAll('#st-local .load-steps span').length") == 4, str(load))
        page.evaluate(STATUS, {"loaded": {"model": "m"}, "loading": True})
        load = page.evaluate("() => [document.getElementById('gpu-load').hidden, document.getElementById('gpu-release').hidden]")
        check("Ollama listing the model mid-load does not take the cancel away", load == [False, True], str(load))
        # the gauge
        page.evaluate(STATUS, None); page.evaluate(GAUGE)
        check("a gauge is shown while readings come", page.evaluate("() => !document.getElementById('gpu-viz').hidden"))
        page.evaluate("() => handle({ type: 'gpu', none: true })")
        check("readings stopping takes it away and its line with it", page.evaluate("() => document.getElementById('gpu-viz').hidden && gpuSeen.length === 0"))
        # the pause key
        page.mouse.move(0, 0)
        rest = page.evaluate("() => getComputedStyle(document.getElementById('pause')).borderTopColor")
        page.hover("#pause"); page.wait_for_timeout(250)
        over = page.evaluate("() => getComputedStyle(document.getElementById('pause')).borderTopColor")
        grey = lambda c: len({x.strip() for x in c[c.index("(") + 1:-1].split(",")[:3]}) == 1
        check("the pause key keeps its colour under the pointer", not grey(over) and not grey(rest), f"{rest} {over}")
        page.mouse.move(0, 0)
        # the toast
        page.evaluate("() => { toast('막혔습니다', null, 'bad'); }")
        page.wait_for_timeout(300)
        # in the bar, where it covers no box (index.html, .toast): over the thread's middle it lay over the cards
        t = page.evaluate("""() => { const a = document.getElementById('toast').getBoundingClientRect(), b = document.querySelector('header.bar').getBoundingClientRect();
            return [a.left >= b.left && a.right <= b.right && a.top >= b.top && a.bottom <= b.bottom, document.getElementById('toast').dataset.tone]; }""")
        check("a notice stands in the bar, tinted by what it says", t[0] and t[1] == "bad", str(t))
        page.evaluate("() => handle({ type: 'notice', text: '저장된 기록을 지우지 못했습니다.' })")
        check("a server notice of what could not be done is the warning tone", page.evaluate("() => document.getElementById('toast').dataset.tone") == "warn")
        page.evaluate("() => document.getElementById('toast').classList.remove('show')")
        # the settings sheet
        page.evaluate("() => { document.getElementById('settings-overlay').hidden = false; }")
        page.wait_for_timeout(350)   # it comes in with a small rise
        over_top = page.evaluate("""() => { const t = document.getElementById('settings').getBoundingClientRect().top, b = document.querySelector('header.bar').getBoundingClientRect().bottom; document.getElementById('settings-overlay').hidden = true; return Math.round(t - b); }""")
        check("the settings sheet hangs one gap under the bar", 16 <= over_top <= 20, str(over_top))
        # the keyboard in the contents' dropdowns
        many(page, 3)
        tabs = page.evaluate("() => [document.getElementById('hist-day').tabIndex, document.getElementById('hist-kind').tabIndex]")
        check("the hidden selects are not tab stops", tabs == [-1, -1], str(tabs))
        got = page.evaluate("""() => { const b = document.querySelector('.combo-btn[data-proxy="hist-kind"]'); if (!b) return null; b.focus(); b.click(); return !!comboOpen; }""")
        if got:
            page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
            check("picking with Enter leaves the focus on the button", page.evaluate("() => document.activeElement.classList.contains('combo-btn')"), page.evaluate("() => document.activeElement.tagName"))
            page.evaluate("""() => document.querySelector('.combo-btn[data-proxy="hist-kind"]').click()""")
            page.keyboard.press("Tab")
            check("Tab closes the list", page.evaluate("() => !comboOpen"))
        else:
            check("(the contents' dropdown opens)", False)
        page.close()

        # the picture stays its own shape, however low the box
        page, _ = fresh(br, url, width=1500, height=620, skin="classic")
        page.evaluate(STATUS, None); page.evaluate(GAUGE)
        many(page, 12)
        shape = page.evaluate("""() => new Promise((ok) => { const it = items.get(latestId()); it.thumb = 'data:image/svg+xml;utf8,' + encodeURIComponent("<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'/>"); renderShot();
            setTimeout(() => { const r = document.getElementById('thumb').getBoundingClientRect(), b = document.getElementById('shot').getBoundingClientRect(); ok([r.width / r.height, b.width / b.height, r.height]); }, 300); })""")
        check("the picture is not squashed on a short window: its frame takes the card's width, the picture keeps its shape", abs(shape[0] - 16 / 9) < .03 and shape[1] >= 16 / 9, str(shape))
        page.close()

        # auto, on a light system
        page = br.new_page(viewport={"width": 1500, "height": 950}, color_scheme="light", locale=support.LOCALE)
        page.add_init_script("localStorage.setItem('sidenote-theme','auto');window.WebSocket = function () { this.close = function () {}; this.send = function () {}; this.readyState = 0; };")
        page.route("**/history**", lambda r: r.fulfill(json={"days": [], "answers": []}))
        page.goto(url); page.wait_for_timeout(300)
        auto = page.evaluate("() => [document.documentElement.dataset.theme, themeNow()]")
        check("auto on a light system is the light theme, and is still stored as auto", auto == ["light", "auto"], str(auto))
        page.emulate_media(color_scheme="dark"); page.wait_for_timeout(100)
        check("and turns over with the system", page.evaluate("() => document.documentElement.dataset.theme") == "dark")
        page.close()

        # several questions in one answer
        page, _ = fresh(br, url, width=1500, height=1200, skin="classic")
        qa = """(text) => { const d = document.createElement('div'); d.innerHTML = '<div class="md"></div>'; renderInto(d.firstChild, text); document.body.append(d); textStyle(d); groupAnswers(d);
            const out = [...d.querySelectorAll('.qa')].map((b) => [b.firstElementChild.textContent.slice(0, 12), b.childElementCount]); const no = d.querySelector('.qa-no')?.textContent ?? null; d.remove(); return { out, no }; }"""
        steps = page.evaluate(qa, "## 1. Q one\n\n**1. a**\n\nx\n\n**2. b**\n\ny\n\n**3. c**\n\nz\n\n## 2. Q two\n\n**1. d**\n\nw\n\n**2. e**\n\nv")
        check("the questions are the blocks, not the steps numbered inside them", [o[0][:2] for o in steps["out"]] == ["1.", "2."], str(steps))
        deci = page.evaluate(qa, "## 2.5배 빠른 이유\n\nx\n\n## 1.1 개요\n\ny")
        check("a decimal is not a question's number", deci["no"] is None, str(deci))
        foot = page.evaluate(qa, "## 1. one\n\nx\n\n## 2. two\n\ny\n\n## 정리\n\nz")
        check("a closing heading is a block of its own, not part of the last question", [o[1] for o in foot["out"]] == [2, 2, 2], str(foot))
        plain = page.evaluate(qa, "## 핵심 아이디어\n\nx\n\n## 예제 검증\n\ny\n\n## 코드\n\nz")
        check("every kind of answer is set in blocks, numbered or not", [o[1] for o in plain["out"]] == [2, 2, 2], str(plain))
        runs = page.evaluate("""() => { const d = document.createElement('div'); d.innerHTML = checkHtml({ probe: true, passed: 1, total: 1, lang: 'python', how: 'stdin', rows: [{ ok: true, input: '3\\n10 15 20', got: '20' }] });
            return [...d.querySelectorAll('.vcheck .vc-case pre')].map((x) => x.textContent); }""")
        check("a code check says what went in and what came out", runs == ["3\n10 15 20", "20"], str(runs))
        # a row of the contents never names itself with a bare mark
        push(page, answer(300, time.time()))
        page.evaluate("""() => { const it = items.get(300); it.raw = 'TYPE: mcq\\nANSWER: ④\\n\\n네 번째 보기가 맞습니다. 나머지는 틀립니다.\\n'; it.head = splitHead(it.raw); renderEntry(it); renderIndex(); }""")
        page.wait_for_timeout(100)
        rowtext = page.evaluate("() => document.querySelector('.h[data-id=\"300\"] .ht').textContent")
        check("a row with only a mark for an answer is named by its first sentence", "네 번째" in rowtext, rowtext)
        # commands
        cmd = """(t) => { const d = document.createElement('div'); d.innerHTML = '<div class="md"><pre><code></code></pre></div>'; d.querySelector('code').textContent = t; document.body.append(d); enhance(d);
            const c = d.querySelector('code'); const out = { nos: [...c.querySelectorAll('.no')].map((n) => n.textContent), tx: [...c.querySelectorAll('.tx')].map((n) => n.textContent), comments: c.querySelectorAll('.hljs-comment').length, copy: codeText(c) }; d.remove(); return out; }"""
        a = page.evaluate(cmd, "kubectl debug <pod> -it --copy-to=dbg")
        check("an unlabelled command is not coloured as a comment", a["comments"] == 0 and a["nos"] == ["$"], str(a))
        b = page.evaluate(cmd, "$ kubectl get pods\nNAME READY\nweb 1/1")
        check("a block with its own prompts: no $ $, none on the output", b["nos"] == ["$", "", ""] and b["tx"][0] == "kubectl get pods" and b["copy"] == "kubectl get pods", str(b))
        # the captions
        cap = page.evaluate("""() => { const d = document.createElement('div'); d.innerHTML = '<div class="md"></div>'; renderInto(d.firstChild, '## 대기 시간\\n\\n| 프로세스 | 대기 |\\n|---|---|\\n| P1 | 4 |\\n\\n```python\\nprint(1)\\n```\\n\\n```\\nkubectl get pods\\n```'); document.body.append(d); textStyle(d); enhance(d);
            const out = [...d.querySelectorAll('.codebar .lang')].map((l) => l.textContent); d.remove(); return out; }""")
        check("tables, programs and commands are numbered and say what they are", cap == ["표 1. 대기 시간", "코드 1. Python: 대기 시간", "명령어 1. 대기 시간"], str(cap))
        # bands that would be cut in the bar float instead
        page.set_viewport_size({"width": 1040, "height": 1200})
        page.evaluate("""() => { document.getElementById('alerts').innerHTML = ['서버가 응답하지 않습니다. 잠시 뒤 다시 연결합니다', '캡처 프로그램이 꺼져 있어 아무것도 받지 못합니다', '에이전트의 사용 한도에 닿아 이 PC의 모델로 풉니다'].map((t) => `<div class="alert"><div class="msg">${t}</div></div>`).join(''); placeBands(); }""")
        check("three bands that would be cut in the bar float under it", page.evaluate("() => !document.documentElement.classList.contains('bands-in-bar')"))
        page.evaluate("""() => { document.getElementById('alerts').innerHTML = '<div class="alert"><div class="msg">일시 정지됨</div></div>'; placeBands(); }""")
        check("one short band stays in the bar", page.evaluate("() => document.documentElement.classList.contains('bands-in-bar')"))
        page.evaluate("() => { document.getElementById('alerts').innerHTML = ''; }")
        # a wide flow is drawn downwards
        wide = "flowchart LR\n" + "\n".join(f"  N{i}[단계 {i} 이름이 조금 긴 상자] --> N{i + 1}[단계 {i + 1} 이름이 조금 긴 상자]" for i in range(9))
        push(page, answer(301, time.time(), text="그림:\n\n```mermaid\n" + wide + "\n```\n"))
        page.wait_for_selector(".viz-diagram img", timeout=15000)
        page.wait_for_timeout(300)
        dia = page.evaluate("""() => { const i = document.querySelector('.viz-diagram img'); return [i.naturalWidth, i.getBoundingClientRect().width, i.closest('figure').clientWidth]; }""")
        check("a wide flow is not shrunk to words too small to read", dia[1] / dia[0] >= .72, str(dia))
        # the scrolled bar is glass, and the menu inside it can still see through
        page.evaluate("() => { document.querySelector('header.bar').classList.add('under'); }")
        glass = page.evaluate("""() => { const b = document.querySelector('header.bar'), a = getComputedStyle(b, '::before'); return [getComputedStyle(b).backdropFilter, a.backdropFilter, a.content]; }""")
        check("the bar under the page is glass, on its own layer", glass[0] == "none" and "blur" in glass[1], str(glass))
        page.close()

        # light
        page, _ = fresh(br, url, width=1500, height=1200, skin="classic", theme="light")
        page.evaluate(STATUS, {"loaded": None}); page.wait_for_timeout(100)
        lum = """(c) => { const [r, g, b] = c.match(/[\\d.]+/g).map(Number).map((v) => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; }"""
        ink = page.evaluate("() => getComputedStyle(document.getElementById('gpu-load')).color")
        ratio = 1.05 / (page.evaluate(lum, ink) + .05)
        check("a state's key reads on paper", ratio >= 4.5, f"{ink} {ratio:.2f}")
        band = page.evaluate("() => [getComputedStyle(document.documentElement).getPropertyValue('--hl-top').trim(), getComputedStyle(document.documentElement).getPropertyValue('--hl-yellow').trim()]")
        check("the highlighter on paper is a stroke under the letters", band[0] == "86%" and ".9" in band[1], str(band))
        page.close()
        br.close()
    srv.shutdown()
    print(f"\n{len(PASS)} ok, {len(FAIL)} FAIL")
    for f in FAIL:
        print(f"  FAIL {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
