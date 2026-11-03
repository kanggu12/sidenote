"""What the panel does with the live pattern, and with a press, a caret or an open follow-up inside an answer.

    SIDENOTE_ANALYZER=mock .venv-panel/bin/python tests/panel_churn.py      (PANEL_DIR=... for a copy)

A screen analysis that starts and is cancelled as superseded 0.1 to 0.9 s later, every few seconds while the panel
is in use, moved the thread, flipped the rail and dropped the keyboard focus; whole-entry redraws threw away a press, a
caret, a follow-up's open answer; and a dozen smaller things, each measured. Each check here failed on the
panel of 2d1df3a. Serves a copy of panel/ with the server's CSP behind panel_review.py's stand-in socket.

Many of the pages are filled with answers the local model wrote for the bench (SIDENOTE_BENCH): where the bench is
missing, each group of checks is skipped from the point it asks for one, and the suite says so in one line.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT / "tests"))      # panel_review, panel_viz and support beside it, wherever this is run from
import panel_review as pr  # noqa: E402
import support  # noqa: E402  (the settings message, the panel's libraries and the skip line)

PANEL = Path(os.environ.get("PANEL_DIR") or ROOT / "panel")
ONLY = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]
PASS, FAIL = [], []
CSP = "".join(re.findall(r'"([^"]*)"', re.search(r"^CSP = \((.*?)\)$", (ROOT / "server" / "app.py").read_text(),
                                                  re.S | re.M).group(1)))
F = "```"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail and not cond else ""))


class WithCsp(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def log_message(self, *a):
        pass


class P(pr.Panel):
    """panel_review's page, with the clipboard granted and a record of what the page sends."""
    def __init__(self, br, url, width=1440, theme="dark", height=900):
        self.ctx = br.new_context(viewport={"width": width, "height": height}, device_scale_factor=1, color_scheme=theme, locale=support.LOCALE)
        self.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=url.rstrip("/"))
        self.pg = self.ctx.new_page()
        self.errors = []
        self.pg.on("pageerror", lambda e: self.errors.append(str(e)))
        self.pg.add_init_script(pr.FAKE_WS.replace("%THEME%", theme))
        self.pg.goto(url, wait_until="load")
        self.pg.wait_for_timeout(300)
        pr.OPEN.append(self)                 # closed with panel_review's close(), or by run() when a group is skipped

    def sent(self, kind):
        return [m for m in (self.ev("() => window.__sent || []") or []) if m.get("type") == kind]


start, done, bench = pr.start, pr.done, pr.bench


def cancelled(seq, reason="superseded"):
    return {"type": "analysis_cancelled", "id": seq, "reason": reason}


def answer(kind, body, ans="답"):
    return f"TYPE: {kind}\nANSWER: {ans}\n\n" + body


def rgb(c):
    """(r, g, b) of a colour written rgb(...) or #rrggbb"""
    if c.startswith("#"):
        c = c[1:]
        if len(c) == 3:
            c = "".join(x * 2 for x in c)
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(round(float(x)) for x in re.findall(r"[\d.]+", c)[:3])


def same_colour(a, b):
    # equal within rounding: a contrast ratio near 1 is no test of this, two hues of one lightness measure 1.0
    return all(abs(x - y) <= 2 for x, y in zip(rgb(a), rgb(b)))


def contrast(a, b):
    """WCAG contrast of two colours written rgb(...) or #rrggbb."""
    def lum(c):
        if c.startswith("#"):
            c = c[1:]
            if len(c) == 3:
                c = "".join(x * 2 for x in c)
            rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
        else:
            rgb = [float(x) for x in re.findall(r"[\d.]+", c)[:3]]
        lin = [(v / 255 / 12.92) if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


WATCH = """() => { const w = window.__mut = { welcome: 0, tail: 0, history: 0, shot: 0 };
  const mo = (id, key, sub) => new MutationObserver((ms) => { for (const m of ms) if (m.type === 'childList') { w[key]++; break; } })
    .observe(document.getElementById(id), { childList: true, subtree: !!sub });
  mo('welcome', 'welcome'); mo('thread-tail', 'tail'); mo('history', 'history'); mo('shot-title', 'shot', true); }"""


def main():
    from playwright.sync_api import sync_playwright
    support.need_vendor(PANEL)                  # the page's libraries, which are fetched rather than kept in git
    work = Path(tempfile.mkdtemp(prefix="panel-churn-"))
    static = work / "panel"
    shutil.copytree(PANEL, static)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(WithCsp, directory=str(static)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    pr.SETTINGS = support.settings_message()    # what server/settings.py sends a panel that connects
    pr.SETTINGS["values"]["roi_box"] = None
    errors = []
    print(f"checking {PANEL}")

    with sync_playwright() as p:
        br = p.chromium.launch(args=["--no-sandbox"])

        def run(name, fn):
            if ONLY and not any(name.startswith(x) for x in ONLY):
                return
            print(f"\n== {name}")
            opened = len(pr.OPEN)
            try:
                fn()
            except support.Missing as missing:   # the rest of the group needs the bench: skipped, not failed
                support.skip(name, missing)
                for pn in pr.OPEN[opened:]:      # the pages it opened and did not get to close
                    pn.close()
            except Exception as e:   # a check that cannot run is a failure, not a crash of the suite
                check(f"{name} ran", False, f"{type(e).__name__}: {str(e)[:200]}")

        def churn():
            # the live pattern on an empty page and on a thread being followed
            pn = P(br, url)
            pn.up()
            pn.ev(WATCH)
            for k in range(6):
                pn.push(start(100 + k)); pn.pg.wait_for_timeout(300); pn.push(cancelled(100 + k)); pn.pg.wait_for_timeout(120)
            mut = pn.ev("() => window.__mut")
            check("C1 superseded looks on an empty page redraw neither the welcome nor the rail's screen card",
                  mut["welcome"] == 0 and mut["shot"] == 0, json.dumps(mut))
            errors.extend(pn.errors); pn.close()

            pn = P(br, url)
            pn.up()
            for i, nm in enumerate(["calc_short_subnet", "code_prog_peak", "calc_mcq_cache", "exam_form_deadlock", "aws_s3_denied"]):
                pn.push(start(i + 1), done(i + 1, bench(nm)))
            pn.pg.wait_for_timeout(700)
            pn.ev("() => window.scrollTo(0, document.documentElement.scrollHeight)"); pn.pg.wait_for_timeout(400)
            pn.ev(WATCH)
            y0 = pn.ev("() => Math.round(scrollY)")
            ys = []
            for k in range(5):
                pn.push(start(200 + k)); pn.pg.wait_for_timeout(300); ys.append(pn.ev("() => Math.round(scrollY)"))
                pn.push(cancelled(200 + k)); pn.pg.wait_for_timeout(120)
            mut = pn.ev("() => window.__mut")
            check("C2 superseded looks do not move a followed thread or rebuild the index",
                  all(y == y0 for y in ys) and mut["history"] == 0, f"y0={y0} during={ys} {json.dumps(mut)}")
            pn.ev("() => document.querySelector('#history .h').focus()")
            pn.push(start(300)); pn.pg.wait_for_timeout(250); pn.push(cancelled(300)); pn.pg.wait_for_timeout(120)
            f = pn.ev("() => document.activeElement.closest('#history') ? 'index' : document.activeElement.tagName")
            check("C3 a focus on an index row stays through a superseded look", f == "index", f)
            # a look that runs on is still said: after REVEAL_MS the foot says it is looking
            pn.push(start(301)); pn.pg.wait_for_timeout(2400)
            pend = pn.ev("() => !!document.querySelector('#thread-tail [data-pending]')")
            pn.push(cancelled(301))
            check("C4 a look that runs past two seconds is said in the foot of the thread", pend, str(pend))
            errors.extend(pn.errors); pn.close()

        def confirm():
            import time
            pn = P(br, url)
            pn.up()
            pn.push(start(1), done(1, bench("calc_mcq_cache")))
            pn.push({"type": "agent_confirm", "id": 50, "cid": "c50", "what": "문제 부분 화면", "text": "질문 글",
                     "timeout": 60, "ts": time.time()})
            pn.pg.wait_for_timeout(300)
            # D: the question is a row of the sheet, not a framed card
            st = pn.ev("""() => { const c = getComputedStyle(document.querySelector('.alert.confirm'));
                return { b: c.borderTopWidth, sh: c.boxShadow, bg: c.backgroundColor }; }""")
            check("C7 the send-to-Claude question has no frame, shadow or fill of its own",
                  st["b"] == "0px" and st["sh"] == "none" and st["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), json.dumps(st))
            btn = pn.pg.locator('[data-confirm="c50"][data-send="1"]')
            btn.scroll_into_view_if_needed(); btn.focus()
            pn.push(start(51, trigger="voice", transcript="문제 읽는 소리")); pn.pg.wait_for_timeout(200)
            pn.push(cancelled(51)); pn.pg.wait_for_timeout(120)
            act = pn.ev("() => document.activeElement?.dataset?.confirm || document.activeElement.tagName")
            check("C5 the focus on Send survives the foot being redrawn", act == "c50", act)
            pn.ev("() => { window.__sent = []; }")
            box = pn.pg.locator('[data-confirm="c50"][data-send="1"]').bounding_box()
            pn.pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            pn.pg.mouse.down()
            pn.push(start(52, trigger="voice", transcript="다른 소리")); pn.pg.wait_for_timeout(60)
            pn.pg.mouse.up(); pn.pg.wait_for_timeout(150)
            got = pn.sent("agent_confirm_reply")
            check("C6 a press on Send across a redraw of the foot is not lost", len(got) == 1, json.dumps(got))
            pn.push(cancelled(52))
            errors.extend(pn.errors); pn.close()

        def continuation():
            label = "스크롤해 이어 본 문제로 풀이 보강"
            pn = P(br, url)
            pn.up()
            for i, nm in enumerate(["calc_short_subnet", "code_prog_peak", "calc_mcq_cache", "exam_form_deadlock"]):
                pn.push(start(i + 1), done(i + 1, bench(nm)))
            pn.pg.wait_for_timeout(700)
            pn.ev("() => toBottom()"); pn.pg.wait_for_timeout(300)   # the panel's own following, not a hand scroll
            y0 = pn.ev("() => Math.round(scrollY)")
            for k in range(3):
                pn.push(start(500 + k, thumb=None, trigger="continue", transcript=label, about=1)); pn.pg.wait_for_timeout(300)
                pn.push(cancelled(500 + k)); pn.pg.wait_for_timeout(150)
            st = pn.ev("""() => ({ turns: document.querySelectorAll('.entry[data-id="1"] .turn').length, y: Math.round(scrollY), stick })""")
            check("C8 stopped continuations that wrote nothing leave no stub and do not take the view",
                  st["turns"] == 0 and abs(st["y"] - y0) <= 1 and st["stick"], f"y0={y0} {json.dumps(st)}")   # a pixel: heights are fractional, and scroll positions rounded
            pn.push(start(9), done(9, bench("aws_s3_denied"))); pn.pg.wait_for_timeout(600)
            # following brings the end of the thread (the panel's stageEnd), not the page's padding under it, into view
            fol = pn.ev("() => [Math.round(Math.max(0, stageEnd() - innerHeight) - scrollY), document.getElementById('jump').hidden]")
            check("C9 the next answer after them is followed as usual", abs(fol[0]) <= 2 and fol[1], str(fol))
            errors.extend(pn.errors); pn.close()

        def redraw():
            code = answer("coding", f"풀이.\n\n{F}python\nimport sys\nn = int(sys.stdin.readline())\nprint(n * 2)\n{F}\n", "두 배")
            pn = P(br, url)
            pn.up()
            pn.push(start(1), done(1, code)); pn.pg.wait_for_timeout(800)
            pn.pg.locator(".entry .runbox .runtools .stdin-toggle").first.click(); pn.pg.wait_for_timeout(100)
            pn.pg.keyboard.type("12")
            pn.push({"type": "check", "id": 1, "running": True}); pn.pg.wait_for_timeout(200)
            pn.pg.keyboard.type("3")
            st = pn.ev("() => ({ stdin: document.activeElement.classList.contains('stdin'), v: document.querySelector('.entry[data-id=\"1\"] .stdin')?.value })")
            check("C10 typing into the run box's input goes on through a redraw of its answer",
                  st["stdin"] and st["v"] == "123", json.dumps(st))
            # a Copy press across a check message
            pn.ev("() => navigator.clipboard.writeText('before')")
            b = pn.pg.locator(".entry[data-id='1'] .codebar .copy").first.bounding_box()
            pn.pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
            pn.pg.mouse.down(); pn.push({"type": "check", "id": 1, "running": False, "ok": True, "passed": 1, "total": 1})
            pn.pg.wait_for_timeout(60); pn.pg.mouse.up(); pn.pg.wait_for_timeout(250)
            clip = pn.ev("() => navigator.clipboard.readText()")
            check("C11 a Copy press across a redraw of its answer copies the code", "print(n * 2)" in (clip or ""), repr(clip)[:80])
            errors.extend(pn.errors); pn.close()

            pn = P(br, url)
            pn.up()
            pn.push(start(1), done(1, bench("calc_mcq_cache"))); pn.pg.wait_for_timeout(300)
            pn.push(start(10, thumb=None, trigger="ask", transcript="왜 그 답이야?", about=1))
            pn.push({"type": "delta", "id": 10, "text": "TYPE: followup\nANSWER: 캐시 적중률 때문\n이유는 다음과 같다. "})
            pn.pg.wait_for_timeout(300)
            for k, nm in zip((2, 3, 4), ("calc_short_subnet", "aws_s3_denied", "exam_form_deadlock")):
                pn.push(start(k), done(k, bench(nm))); pn.pg.wait_for_timeout(200)
            pn.push(done(10, "TYPE: followup\nANSWER: 캐시 적중률 때문\n이유는 다음과 같다. 적중하면 메모리까지 가지 않는다.", engine="agent"))
            pn.pg.wait_for_timeout(500)
            st = pn.ev("""() => { const e = document.querySelector('.entry[data-id="1"]'), t = e.querySelector('.turn');
                return { folded: e.classList.contains('folded'), h: Math.round(t.getBoundingClientRect().height) }; }""")
            check("C12 a follow-up question stays open when it finishes after newer answers", not st["folded"] and st["h"] > 0,
                  json.dumps(st))
            errors.extend(pn.errors); pn.close()

        def code():
            src = {
                "python": "from collections import deque\nseen = {}\nnums = []\nq = deque()\nnums.append(1)\nx = seen.get(2)\ny = q.popleft()\n",
                "cpp": "#include <vector>\nint main() {\n    std::vector<int> v;\n    v.push_back(1);\n    return v.size();\n}\n",
                "java": "import java.util.*;\nclass A {\n    void f() {\n        List<Integer> list = new ArrayList<>();\n        list.add(1);\n    }\n}\n",
                "go": "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfor i := 0; i < 3; i++ {\n\t\tif i > 1 {\n\t\t\tfmt.Println(i)\n\t\t}\n\t}\n}\n",
                "constructor": "x = 1\n",
            }
            body = "".join(f"{F}{lang}\n{s}{F}\n\n" for lang, s in src.items()) + f"{F}python\na = 1\n\nb = 2\n\n\nc = 3\n{F}\n"
            pn = P(br, url, 1100, "light", 1000)
            pn.up()
            pn.push(start(1), done(1, answer("coding", body))); pn.pg.wait_for_timeout(1200)
            docs = pn.ev("() => [...document.querySelectorAll('.entry .md pre code')].map((c) => [...c.querySelectorAll('.doc')].map((d) => d.textContent))")
            want = [{"append", "get", "popleft"}, {"push_back", "size"}, {"add"}]
            check("C13 a method called on a value is explained (append, get, popleft, push_back, size, add)",
                  all(w <= set(d) for w, d in zip(want, docs)), json.dumps(docs[:3], ensure_ascii=False))
            go = pn.ev("""() => { const c = document.querySelectorAll('.entry .md pre code')[3];
                const ch = parseFloat(getComputedStyle(c).fontSize) * 0.6;   // a rough ch, only to compare the two
                return [...c.querySelectorAll('.ln')].map((l) => { const t = l.querySelector('.tx'), r = document.createRange();
                  const txt = t.firstChild; if (!t.textContent.trim()) return null;
                  const ind = +getComputedStyle(l).getPropertyValue('--ind');
                  const lead = t.textContent.match(/^[\\t ]*/)[0]; const cols = [...lead].reduce((n, x) => x === '\\t' ? n + 4 - (n % 4) : n + 1, 0);
                  return [ind, cols]; }).filter(Boolean); }""")
            tab = pn.ev("() => getComputedStyle(document.querySelectorAll('.entry .md pre')[3]).tabSize")
            check("C14 tab-indented code: the guides' indentation is the one the code is drawn with (a tab is 4)",
                  tab == "4" and all(a == b for a, b in go), f"tab-size {tab} {go}")
            lbl = pn.ev("() => [...document.querySelectorAll('.entry .codebar .lang')].map((l) => l.textContent)")
            runs = pn.ev("() => [...document.querySelectorAll('.entry .md pre')].map((p) => !!p.parentElement.querySelector(':scope > .runbox') || !!p.nextElementSibling?.classList?.contains('runbox'))")
            check("C15 a fence named constructor is not read off Object's prototype", "function Object" not in " ".join(lbl), json.dumps(lbl))
            # manual copy of a block with blank lines
            pn.ev("""() => { const c = document.querySelectorAll('.entry .md pre code')[5], r = document.createRange();
                r.selectNodeContents(c); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }""")
            pn.pg.keyboard.press("Control+C"); pn.pg.wait_for_timeout(200)
            clip = pn.ev("() => navigator.clipboard.readText()")
            check("C16 copying a selection keeps the code's empty lines empty", clip.split("\n") == ["a = 1", "", "b = 2", "", "", "c = 3"],
                  repr(clip))
            # the hover box goes when the pointer leaves the window
            sp = pn.pg.locator(".entry .md pre code .doc").first
            sp.scroll_into_view_if_needed(); sp.hover(); pn.pg.wait_for_timeout(500)
            shown = pn.ev("() => !!document.querySelector('.doc-tip') && !document.querySelector('.doc-tip').hidden")
            pn.ev("() => document.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: null }))")
            pn.pg.wait_for_timeout(100)
            gone = pn.ev("() => !document.querySelector('.doc-tip') || document.querySelector('.doc-tip').hidden")
            check("C17 the function box goes when the pointer leaves the window", shown and gone, f"shown={shown} gone={gone}")
            errors.extend(pn.errors); pn.close()

        # The layout checks come in three groups: the index of thirty answers (C18, C19) and the toast beside an answer
        # (C22, C23) read answers of the bench, the bar and the question box under an alert (C20, C21) read none, so
        # they still run when the bench is missing. With it, the three run one after the other as one group did.
        def layout_index():
            pn = P(br, url, 900, "dark", 800)
            pn.up()
            for i in range(30):
                pn.push(start(i + 1), done(i + 1, bench(["calc_mcq_cache", "calc_short_subnet", "aws_s3_denied"][i % 3])))
            pn.pg.wait_for_timeout(800)
            mh = pn.ev("() => document.getElementById('history').style.maxHeight")
            check("C18 one column: the index is shown whole, not as a small box that scrolls", mh == "", repr(mh))
            errors.extend(pn.errors); pn.close()
            pn = P(br, url, 1440, "dark", 800)
            pn.up()
            for i in range(30):
                pn.push(start(i + 1), done(i + 1, bench(["calc_mcq_cache", "calc_short_subnet", "aws_s3_denied"][i % 3])))
            pn.pg.wait_for_timeout(800)
            cut = pn.ev("""() => { const l = document.getElementById('history'), r = l.getBoundingClientRect();
                return [...l.children].map((c) => c.getBoundingClientRect()).filter((b) => b.top < r.bottom - 1 && b.bottom > r.bottom + 1).length; }""")
            check("C19 two columns: the index's box ends between rows, none cut through", cut == 0, str(cut))
            errors.extend(pn.errors); pn.close()

        def layout_bar():
            for w in (730, 760):
                pn = P(br, url, w, "light", 800)
                pn.up()
                bar = pn.ev("""() => { const b = document.querySelector('header.bar').getBoundingClientRect(),
                    a = document.getElementById('reanalyze').getBoundingClientRect(), s = document.querySelector('.signals').getBoundingClientRect(),
                    n = document.querySelector('.brand').getBoundingClientRect();
                    return { h: Math.round(b.height), btnRow: Math.round(a.top - n.top), sigBelow: s.top >= a.bottom - 1 }; }""")
                check(f"C20 {w}px: brand and buttons share the first row and the signals take the second",
                      bar["h"] <= 92 and abs(bar["btnRow"]) <= 12 and (bar["sigBelow"] or bar["h"] <= 60), json.dumps(bar))   # Classic has no readings in its bar
                pn.close()
            # an alert above the column of an empty page that does not scroll: nothing fires a scroll when it comes
            pn = P(br, url, 1440, "dark", 1250)
            pn.up()
            pn.pg.wait_for_timeout(400)
            pn.ev("() => { const d = document.createElement('div'); d.className = 'alert warn'; d.style.height = '600px'; document.getElementById('alerts').append(d); }")
            pn.pg.wait_for_timeout(500)
            st = pn.ev("""() => { const f = document.getElementById('askform'), st = document.getElementById('stage').getBoundingClientRect();
                const cs = getComputedStyle(f); const rest = st.bottom - parseFloat(cs.marginBottom), hold = innerHeight - parseFloat(cs.bottom);
                return { floating: f.classList.contains('floating'), should: rest > hold + 1, fixed: getComputedStyle(document.getElementById('alerts')).position === 'fixed' }; }""")
            check("C21 an alert appearing above the column re-measures the question box's shape",
                  st["fixed"] or (st["should"] and st["floating"] == st["should"]), json.dumps(st))   # in the bar, a band moves nothing
            pn.close()

        def layout_toast():
            pn = P(br, url, 1440, "dark", 900)
            pn.up()
            pn.push(start(1), done(1, bench("calc_mcq_cache"))); pn.pg.wait_for_timeout(500)
            # the toast stands clear of the resting question box
            pn.ev("() => { document.getElementById('alerts').replaceChildren(); window.scrollTo(0, document.documentElement.scrollHeight); }")
            pn.pg.wait_for_timeout(500)
            pn.ev("() => toast('지금 화면을 다시 분석합니다.')"); pn.pg.wait_for_timeout(300)
            ov = pn.ev("""() => { const a = document.getElementById('toast').getBoundingClientRect(), b = document.getElementById('askform').getBoundingClientRect();
                return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)); }""")
            z = pn.ev("() => +getComputedStyle(document.getElementById('toast')).zIndex")
            check("C22 the toast does not cover the resting question box, and shows over the settings sheet", ov == 0 and z > 35,
                  f"overlap {ov}px2 z {z}")
            # the dark switch knob on its track
            knob = pn.ev("""() => { const s = document.querySelector('.switch[aria-checked="true"]');
                return s ? [getComputedStyle(s).backgroundColor, getComputedStyle(s, '::after').backgroundColor] : null; }""")
            check("C23 dark: a switch's white knob reads on its on-track at 3:1 or more", bool(knob) and contrast(*knob) >= 3,
                  f"{knob} {contrast(*knob) if knob else ''}")
            errors.extend(pn.errors); pn.close()

        def pictures():
            for theme in ("light", "dark"):
                pn = P(br, url, 1100, theme, 1000)
                pn.up()
                spec = {"type": "gantt", "title": "RR", "unit": "ms", "tasks": [
                    {"name": f"P{i}", "start": 2 * i, "end": 2 * i + 2} for i in range(1, 9)]}
                pn.push(start(1), done(1, answer("algorithm", f"순서.\n\n{F}chart\n{json.dumps(spec)}\n{F}\n")))
                pn.pg.wait_for_timeout(1200)
                pairs = pn.ev("""() => [...document.querySelectorAll('.viz-plot text.in')].map((t) => {
                    const r = t.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
                    const rect = [...t.ownerSVGElement.querySelectorAll('rect.mark')].find((m) => { const b = m.getBoundingClientRect();
                      return x > b.left && x < b.right && y > b.top && y < b.bottom; });
                    return rect ? [getComputedStyle(t).fill, getComputedStyle(rect).fill] : null; }).filter(Boolean)""")
                worst = min((contrast(a, b) for a, b in pairs), default=0)
                check(f"C24 {theme}: every name inside a timetable block reads at 4.5:1 or more", len(pairs) >= 6 and worst >= 4.5,
                      f"{len(pairs)} names, worst {worst:.2f}")
                pn.close()

        def bands():
            pn = P(br, url, 1100, "dark", 1000)
            pn.up()
            pn.push(start(1), done(1, answer("coding", f"{F}python\nprint(1)\n{F}\n")))
            pn.pg.wait_for_timeout(800)
            pn.ev("""() => { const o = document.createElement('pre'); o.className = 'run-out err'; o.textContent = 'x';
                document.querySelector('.entry .runbox').append(o); }""")
            st = pn.ev("() => { const c = getComputedStyle(document.querySelector('.run-out')); return [c.borderLeftWidth, c.borderTopWidth]; }")
            check("C25 the run output carries no coloured band on its left", st[0] == st[1], str(st))
            pn.push({"type": "delta", "id": 2, "text": ""})
            pn.close()
            # offline: the server step reads red like the alert
            pn = P(br, url, 1440, "light", 900)
            pn.ev("() => { wsState = 'down'; renderAlerts && renderAlerts(); syncEmpty(); }")
            pn.pg.wait_for_timeout(300)
            col = pn.ev("""() => { const li = [...document.querySelectorAll('.steps li')].find((l) => l.querySelector('.t')?.textContent === '서버');
                return li ? [getComputedStyle(li.querySelector('.s')).color, getComputedStyle(document.documentElement).getPropertyValue('--bad').trim()] : null; }""")
            ok = bool(col) and same_colour(col[0], col[1])
            check("C26 offline: the server step's Not connected is the alert's red", ok, str(col))
            print("     (server step:", col, ")")
            # summaries wear a drawn mark, not the browser's triangle
            pn.close()
            pn = P(br, url, 1100, "light", 1000)
            pn.up()
            import panel_viz as pv   # its sample answer with six charts, each with its See as a table
            pn.push(start(1), done(1, pv.CHARTS))
            pn.pg.wait_for_timeout(900)
            ls = pn.ev("() => { const s = document.querySelector('.viz-more > summary'); return s ? [getComputedStyle(s).listStyleType, getComputedStyle(s).display] : null; }")
            check("C27 a summary shows the page's drawn mark, not the browser's triangle", bool(ls) and ls[0] == "none", str(ls))
            errors.extend(pn.errors); pn.close()

        def voice():
            pn = P(br, url)
            pn.up()
            pn.push({"type": "transcript", "text": "스택과 큐의 차이를 설명하시오.", "lang": "ko", "waiting": False, "pending": True})
            pn.pg.wait_for_timeout(200)
            before = pn.ev("() => document.getElementById('hear-state').textContent")
            pn.push(start(71)); pn.pg.wait_for_timeout(300); pn.push(cancelled(71)); pn.pg.wait_for_timeout(200)
            after = pn.ev("() => document.getElementById('hear-state').textContent")
            check("C28 a screen look stopped beside a spoken problem leaves the spoken problem's status", before == after,
                  f"{before[:40]!r} -> {after[:40]!r}")
            errors.extend(pn.errors); pn.close()

        def stream():
            # formulas are set while the answer streams, and the dark bar's glass is the colour of the page under it
            pn = P(br, url, 1100, "dark", 900)
            pn.up()
            pn.push(start(1), {"type": "delta", "id": 1, "text": "TYPE: math\nANSWER: 8\n\n계산은 $1 \\times 2^3 = 8$ 이고 이어서 "})
            pn.pg.wait_for_timeout(600)
            live = pn.ev("() => ({ live: !!items.get(1)?.live, done: document.querySelectorAll('.entry .md span.math.done .katex').length, raw: document.querySelector('.entry .md')?.innerText.includes('\\\\times') })")
            check("C29 a formula is set while its answer is still streaming", live["live"] and live["done"] == 1 and not live["raw"], json.dumps(live))
            classic = pn.ev("() => document.documentElement.dataset.skin === 'classic'")
            tok = pn.ev("""() => { const c = getComputedStyle(document.documentElement);
                return ['--paper', '--paper-top', '--sheet', '--glass'].map((k) => c.getPropertyValue(k).trim()); }""")
            paper, top, sheet, glass = [rgb(x) if x.startswith("#") else rgb(x) for x in tok]
            third = all(p_ <= t_ <= p_ + (s_ - p_) / 3 + 1 for p_, t_, s_ in zip(paper, top, sheet))
            check("C30 dark: the top of the page is at most a third of the way to the sheets, and the bar's glass is that colour",
                  third and (not classic or same_colour("#%02x%02x%02x" % top, "#%02x%02x%02x" % glass)), json.dumps(tok))   # New's pill is a panel, not the page
            errors.extend(pn.errors); pn.close()

        def rail():
            # the rail: plain words for the GPU line and a way to put the model
            # back, Claude on and off from its card, a bar that is the page at the top, lit signals, livelier colour
            import copy
            st = copy.deepcopy(pr.STATUS)
            st["engines"]["local"]["loaded"] = None          # the GPU was given back
            pn = P(br, url, 1440, "dark", 900)
            pn.up(status=st)
            pn.pg.wait_for_timeout(300)
            card = pn.ev("() => document.getElementById('st-local').textContent")   # New folds it under the name
            load = pn.ev("() => !document.getElementById('gpu-load').hidden")
            check("R1 the GPU line says it in plain words, and the button that loads the model is offered while the GPU is empty",
                  "다음 문제에서 올림" not in card and "문제가 오면 자동으로 올림" in card and load, f"{card!r} load={load}")
            pn.ev("() => { window.__sent = []; }")
            pn.pg.click("#gpu-load"); pn.pg.wait_for_timeout(150)
            check("R2 that button asks the server to load the model", len(pn.sent("gpu_load")) == 1, json.dumps(pn.ev("() => window.__sent")))
            sw = pn.ev("() => { const s = document.getElementById('sw-agent'); return s && !s.hidden ? s.getAttribute('aria-checked') : null; }")
            pn.ev("() => { window.__sent = []; }")
            pn.pg.click("#sw-agent"); pn.pg.wait_for_timeout(150)
            off = [m for m in pn.sent("setting") if m.get("key") == "agent_mode"]
            pn.pg.click("#sw-agent"); pn.pg.wait_for_timeout(150)
            both = [m.get("value") for m in pn.sent("setting") if m.get("key") == "agent_mode"]
            check("R3 Claude has its own switch on its card: off, then back to the mode it had", sw == "true" and both == ["off", "hard"],
                  f"switch {sw} sent {both}")
            # the bar at the top of the page is the page; glass once the thread scrolls under it
            for i in range(4):
                pn.push(start(i + 1), done(i + 1, pr.bench(["calc_mcq_cache", "exam_lms_essay"][i % 2])))
            pn.pg.wait_for_timeout(600)
            pn.ev("() => window.scrollTo(0, 0)"); pn.pg.wait_for_timeout(400)
            top = pn.ev("() => { const c = getComputedStyle(document.querySelector('header.bar')); return [c.backgroundColor, c.backdropFilter]; }")
            classic = pn.ev("() => document.documentElement.dataset.skin === 'classic'")
            pn.ev("() => window.scrollTo(0, 600)"); pn.pg.wait_for_timeout(400)
            # Classic draws the scrolled bar's glass on a layer of its own, so the menu inside the bar can still blur what is behind it
            down = pn.ev("(classic) => { const c = getComputedStyle(document.querySelector('header.bar'), classic ? '::before' : null); return [c.backgroundImage !== 'none' ? c.backgroundImage : c.backgroundColor, c.backdropFilter]; }", classic)
            # New: the strip behind the pill stays clear at any scroll; the pill itself is the surface
            check("R4 at the top the bar has no surface (the page runs under it); scrolled, it is glass",
                  top[0] in ("rgba(0, 0, 0, 0)", "transparent") and top[1] in ("none", "") and down[0] != top[0], f"{top} {down}")
            lamp = pn.ev("() => { const d = document.querySelector('#sig-server .dot'), c = getComputedStyle(d); return [c.boxShadow, c.backgroundImage]; }")
            check("R5 a working signal is lit: a halo of its colour and a bright centre", "rgb" in lamp[0] and "radial-gradient" in lamp[1], str(lamp)[:160])
            ink = pn.ev("() => ['--ink', '--t-mcq', '--t-short', '--t-essay', '--t-coding', '--t-algorithm', '--t-math', '--t-work', '--t-diagram', '--t-other', '--t-followup'].map((k) => getComputedStyle(document.documentElement).getPropertyValue(k).trim())")
            def okl(h):
                import math
                r, g, b = [((c / 255) / 12.92) if c / 255 <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in rgb(h)]
                l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
                m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
                s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
                L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
                a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
                bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
                return L, math.hypot(a, bb)
            kinds = [okl(h) for h in ink[1:]]
            check("R6 dark: the text is brighter than Slack's grey and every kind colour is lively (a coloured pen, or the white one)",
                  okl(ink[0])[0] > 0.9 and all(L >= 0.6 and (C >= 0.10 or L >= 0.9) for L, C in kinds),
                  f"ink {ink[0]} kinds {[(round(L, 2), round(C, 3)) for L, C in kinds]}")
            errors.extend(pn.errors); pn.close()

        def livecode():
            # a code block wears its finished look, line numbers and all, while its answer is written, not only once
            # it is finished, and comments sit a text size below the code
            pn = P(br, url, 1100, "dark", 900)
            pn.up()
            head = ("TYPE: algorithm\nANSWER: 힙에 넣고 하나씩 꺼낸다\n\n풀이\n\n" + F + "python\nimport heapq\n\n"
                    "def solution(nums):\n    h = []  # 최소 힙: 가장 작은 값이 맨 앞\n")
            pn.push(start(1), {"type": "delta", "id": 1, "text": head})
            pn.pg.wait_for_timeout(450)
            look = """() => { const c = document.querySelector('.entry .md pre > code'); const bar = c?.parentElement.querySelector(':scope > .codebar');
                return c && { lined: c.classList.contains('lined'), nos: c.querySelectorAll('.no').length,
                  hl: c.querySelectorAll('[class*="hljs-"]').length, lang: bar?.querySelector('.lang')?.textContent || null,
                  wait: !!bar?.querySelector('.wait'), copy: !!bar?.querySelector('.copy'), barH: bar ? bar.getBoundingClientRect().height : 0,
                  docs: c.dataset.docs || null, tips: c.querySelectorAll('.doc').length }; }"""
            mid = pn.ev(look)
            check("K1 code still being written has numbered lines, colours and its bar with the language",
                  bool(mid) and mid["lined"] and mid["nos"] == 4 and mid["hl"] > 0 and mid["lang"] == "Python" and mid["wait"]
                  and not mid["copy"], json.dumps(mid))
            more = "    for x in nums:  # 하나씩 넣으면 힙 순서가 지켜진다\n        heapq.heappush(h, x)\n"
            pn.push({"type": "delta", "id": 1, "text": more})
            pn.pg.wait_for_timeout(350)
            grown = pn.ev(look)
            check("K2 lines are numbered as they come in", bool(grown) and grown["nos"] == 6 and grown["lined"], json.dumps(grown))
            pn.push(done(1, head + more + "    return h  # 힙 순서의 리스트\n" + F + "\n\n끝."))
            pn.pg.wait_for_timeout(700)
            fin = pn.ev(look)
            check("K3 done: the buttons take the place of the still-writing note and the bar keeps its height, the library names explain themselves",
                  bool(fin) and fin["copy"] and not fin["wait"] and fin["nos"] == 7 and abs(fin["barH"] - mid["barH"]) <= 1
                  and fin["docs"] == "1" and fin["tips"] >= 1, json.dumps({"mid": mid, "fin": fin}))
            size = pn.ev("""() => { const c = document.querySelector('.entry .md pre > code .tx');
                const m = document.querySelector('.entry .md pre .hljs-comment');
                const line = (sel) => document.querySelector(sel)?.getBoundingClientRect().height || 0;
                return { code: parseFloat(getComputedStyle(c).fontSize), comment: m ? parseFloat(getComputedStyle(m).fontSize) : 0,
                         plainLine: line('.entry .md pre > code .ln:nth-child(1)'), commentLine: line('.entry .md pre > code .ln:nth-child(4)') }; }""")
            check("K4 comments are a size below the code they explain, and a line with one keeps the code's height",
                  0 < size["comment"] < size["code"] * 0.95 and abs(size["plainLine"] - size["commentLine"]) <= 1, json.dumps(size))
            errors.extend(pn.errors); pn.close()

        for name, fn in (("rail", rail), ("stream", stream), ("churn", churn), ("confirm", confirm), ("continuation", continuation), ("redraw", redraw),
                         ("code", code), ("layout index", layout_index), ("layout bar", layout_bar), ("layout toast", layout_toast),
                         ("pictures", pictures), ("bands", bands), ("voice", voice), ("livecode", livecode)):
            run(name, fn)
        br.close()
    srv.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    check("no script errors on any page", not errors, "; ".join(errors)[:300])
    support.skip_line()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
