"""Ten bugs and eleven design faults of the panel, each as a check that fails on the panel it was found in.

    .venv-panel/bin/python tests/panel_review.py
    PANEL_DIR=/some/older/copy/of/panel .venv-panel/bin/python tests/panel_review.py

Serves a copy of panel/ (or of PANEL_DIR, which is how the checks were watched failing on the files that
had the faults) from a local HTTP server, so what is checked is the working tree and not the image
the live server was built from. The page's socket is a stand-in that this script opens, drops and opens
again itself, and every message fed through it has the shape server/app.py broadcasts: the status and
capture messages below were copied from a live panel connection, and the settings message is written
straight out of server/settings.py (tests/support.py). Nothing reaches a live server.

The answers fed to the page are ones the local model wrote for the bench's screens (SIDENOTE_BENCH,
out-depth/), which are not in the repository: a group of checks that feeds one is skipped where the bench
is missing, and the suite says so in one line.

Bugs, each a thing the panel did wrong:
   1  a copy button pressed twice inside its reset window stayed on Copied for good
   2  the failed-example box and the error details got a code block's bar, and the box lost its padding
   3  the follow-up buttons outlived the connection, and outlived a restarted server that cannot answer them
   4  an answer the server finished after a dropped connection stayed marked as cut off
   5  an engine starting the answer over left the discarded answer line on the card
   6  a settings message reaches the controls, and the notes that read the same values
   7  what the problem asks was shown with its markdown as written
   8  wording: a particle after a variable word, the outbound note, a card that is not on the right
   9  walking the settings tabs with the arrow keys stopped the notebook following new answers
  10  two ages read a server stamp against this browser's clock
Design, each a thing that looked wrong next to the rest:
   1  a narrow window: a three-row top bar, and an entry head split over two lines
   2  the one control in the settings sheet the operating system draws (the type ticks)
   3  the two buttons of the send-to-Claude question split apart in a narrow window
   4  a dropdown in a narrow sheet hanging out past the sheet's edge
   5  the dark index's current row: coloured words on an olive band
   6  an error entry opening with a blank line
   7  the first analysis on an empty page: a second, nearly empty sheet, and a screen card saying no screen
   8  a long answer line drawn as big as a one-word one
   9  a code block cut at the right edge with nothing saying it scrolls
  10  controls whose state does not show (the input toggle, an idle switch, the bar while offline, an armed clear)
  11  the settings sheet see-through, a pill under 4.5:1, a lone tab, a screen card disagreeing with
      itself, characters standing in for drawn marks
"""
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import support  # tests/support.py: the settings message, the panel's libraries, the bench and the skip line

HERE = Path(__file__).resolve().parent      # tests/
ROOT = HERE.parent                          # the repository
# The panel to check: the working tree unless told otherwise.
PANEL = Path(os.environ.get("PANEL_DIR") or ROOT / "panel")
# Where in the bench (SIDENOTE_BENCH) the local model's answers to its screens are, one file a screen
BENCH = "out-depth/sidenote-gemma4_26b+both_dbase"
PASS, FAIL = [], []
# ONLY="bug 3,design 5" runs just the groups whose names start with one of those
ONLY = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


# What a live server sent a panel that had just connected (copied from the socket),
# trimmed of nothing: a status built from guesses drew a card the real one never shows.
STATUS = {"type": "status", "text": "connected", "analyzer": "local", "gate": "signature", "paused": False,
          "lang": "auto", "audio": True, "voice": True, "crop": False, "can_ask": True, "run_enabled": True,
          "runner": True,
          "engines": {"local": {"ok": True, "method": "local", "model": "sidenote-gemma4:26b",
                                "loaded": {"model": "sidenote-gemma4:26b", "vram_gb": None}, "present": True,
                                "on": True, "busy": None},
                      "agent": {"ok": True, "method": "claude.ai", "present": True, "label": "Claude Code", "short": "Claude", "login": "./sidenote login", "mode": "hard",
                                 "effective": "hard", "payload": "crop", "model": "", "asked_model": "",
                                 "effort": "", "brake": ""},
                      "search": {"present": True, "on": True}, "ready": True},
          "build": "1558c791b0cb"}
CAPTURE = {"type": "capture", "clients": 1, "info": "", "now": 0, "last_frame": None, "last_audio": None,
           "screen_on": True, "audio_on": True,
           "caps": {"screen": True, "audio": True, "audio_device": "스피커 (Realtek(R) Audio)", "monitor": 1,
                    "monitors": [[2560, 1440], [1920, 1080]]}, "empty_run": 0, "quiet_sec": 0}
USAGE = {"type": "usage", "answers": 0, "empty": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
         "errors": 0, "elapsed_p50": None, "first_token_p50": None, "last_error": None}
# A screen to show in the rail: an SVG, so no file is needed (the panel takes data: images).
THUMB = "data:image/svg+xml;utf8," + ("<svg xmlns='http://www.w3.org/2000/svg' width='640' height='360'>"
                                     "<rect width='640' height='360' fill='%23f4f4f4'/>"
                                     "<rect x='40' y='40' width='300' height='20' fill='%23333'/></svg>")

# The page's socket, replaced before the panel's own script runs: the test says when it opens, what
# arrives on it and when it drops, and what the panel sends is kept instead of sent anywhere.
FAKE_WS = """
(() => {
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; window.__ws = this;
      window.__wsMade = (window.__wsMade || 0) + 1; }
    send(d) { (window.__sent = window.__sent || []).push(JSON.parse(d)); }
    close() { this.readyState = 3; }
  }
  FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
  window.WebSocket = FakeWS;
  window.__open = () => { const w = window.__ws; w.readyState = 1; w.onopen && w.onopen(); };
  window.__push = (m) => window.__ws.onmessage({ data: JSON.stringify(m) });
  window.__drop = () => { const w = window.__ws; w.readyState = 3; w.onclose && w.onclose(); };
  try { localStorage.setItem('sidenote-theme', '%THEME%'); } catch (_) {}
})();
"""

# Text made invisible, so a screenshot shows only what is painted behind it (the glass included).
HIDE_TEXT = """* { color: transparent !important; -webkit-text-fill-color: transparent !important;
  text-shadow: none !important; } svg, img, .katex { visibility: hidden !important; }"""
# The median colour inside each box of a screenshot, read in the page itself (the venv has no PIL).
SAMPLE = """async ([png, boxes]) => {
  const img = new Image();
  img.src = 'data:image/png;base64,' + png;
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.width; c.height = img.height;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  const lum = (p) => 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2];
  return boxes.map(([x0, y0, x1, y1]) => {
    const w = Math.max(1, Math.round(x1 - x0)), h = Math.max(1, Math.round(y1 - y0));
    const d = g.getImageData(Math.round(x0), Math.round(y0), w, h).data;
    const px = [];
    for (let i = 0; i < d.length; i += 4) px.push([d[i], d[i + 1], d[i + 2]]);
    px.sort((a, b) => lum(a) - lum(b));
    return px[Math.floor(px.length / 2)];
  });
}"""
# The i-th text matching a selector, brought into the middle of the window first (a screenshot holds
# only the window, and a box below the fold sampled as black), with its colour, the ancestors' opacity
# applied, and its box inset from its edges. A colour made with color-mix() comes back as
# "color(srgb r g b / a)" with channels from 0 to 1, not 0 to 255.
ONE_TEXT = """([sel, i]) => {
  const e = document.querySelectorAll(sel)[i];
  if (!e || !e.textContent.trim()) return null;
  e.scrollIntoView({ block: "center", inline: "nearest" });
  const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
  let op = 1; for (let p = e; p; p = p.parentElement) op *= +getComputedStyle(p).opacity;
  const c = cs.color.match(/[\\d.]+/g).map(Number), k = cs.color.startsWith("color(") ? 255 : 1;
  return { text: e.textContent.trim().slice(0, 20), color: [c[0] * k, c[1] * k, c[2] * k, (c.length > 3 ? c[3] : 1) * op],
           box: [r.left + 2, r.top + 2, r.right - 2, r.bottom - 2] }; }"""


def lin(v):
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def ratio(a, b):
    la = 0.2126 * lin(a[0]) + 0.7152 * lin(a[1]) + 0.0722 * lin(a[2])
    lb = 0.2126 * lin(b[0]) + 0.7152 * lin(b[1]) + 0.0722 * lin(b[2])
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def contrasts(pg, sel):
    """The contrast of every text matching sel against what is really painted under it, one at a time."""
    out = []
    for i in range(pg.evaluate("(s) => document.querySelectorAll(s).length", sel)):
        it = pg.evaluate(ONE_TEXT, [sel, i])
        if not it:
            continue
        pg.wait_for_timeout(80)
        style = pg.add_style_tag(content=HIDE_TEXT)
        pg.wait_for_timeout(80)
        png = base64.b64encode(pg.screenshot()).decode()
        pg.evaluate("(s) => s.remove()", style)
        bg = pg.evaluate(SAMPLE, [png, [it["box"]]])[0]
        r, g, b, a = it["color"]
        txt = [r * a + m * (1 - a) for r, m in zip((r, g, b), bg)]   # the text as drawn on that ground
        out.append((round(ratio(txt, bg), 2), it["text"]))
    return out


def bench(name):
    """The answer the local model wrote for one screen of the bench. Where the bench is not here, as in CI, a written stand-in of the same shape
    (tests/data/answers): the groups that read them would otherwise go unchecked there, and they did, 49 checks of two suites."""
    try:
        return support.bench(f"{BENCH}/{name}.md").read_text(encoding="utf-8")
    except support.Missing:
        return (Path(__file__).resolve().parent / "data" / "answers" / f"{name}.md").read_text(encoding="utf-8")


def start(seq, thumb=THUMB, trigger="screen", transcript="", about=None):
    m = {"type": "analysis_start", "id": seq, "ts": time.time(), "thumb": thumb, "transcript": transcript,
         "pages": 0, "trigger": trigger, "roi": None}
    if about is not None:
        m["about"] = about
    return m


def done(seq, text, engine="local", elapsed=4.2):
    return {"type": "analysis_done", "id": seq, "text": text, "usage": {"input_tokens": 1830, "output_tokens": 412},
            "cost_usd": None, "model": "sidenote-gemma4:26b", "engine": engine, "sent": [],
            "stages": {"local": True, "agent": False}, "elapsed": elapsed, "region": None}


OPEN = []   # the pages open now: a group skipped part way closes the ones it left open (run)


class Panel:
    """One page of the panel behind the stand-in socket."""

    def __init__(self, br, url, width=1440, theme="dark", height=900):
        self.ctx = br.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                  color_scheme=theme, locale=support.LOCALE)
        # the copy buttons write to the clipboard: without the grant every copy fails, and a failed copy
        # walks a different branch of the code under test
        self.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=url.rstrip("/"))
        self.pg = self.ctx.new_page()
        self.errors = []
        self.pg.on("pageerror", lambda e: self.errors.append(str(e)))
        self.pg.add_init_script(FAKE_WS.replace("%THEME%", theme))
        self.pg.goto(url, wait_until="load")
        self.pg.wait_for_timeout(300)
        OPEN.append(self)

    def push(self, *msgs):
        self.pg.evaluate("(ms) => ms.forEach((m) => window.__push(m))", list(msgs))

    def up(self, can_ask=True, clients=1, status=None, settings=True):
        """Open the socket and send what the server sends a panel that has just connected."""
        self.pg.evaluate("() => window.__open()")
        st = json.loads(json.dumps(status or STATUS))
        st["can_ask"] = can_ask
        cap = dict(CAPTURE, clients=clients, now=time.time(), last_frame=time.time() - 3 if clients else None,
                   last_audio=time.time() - 1 if clients else None)
        msgs = [st] + ([SETTINGS] if settings else []) + [cap, USAGE]
        self.push(*msgs)
        self.pg.wait_for_timeout(150)

    def drop_and_return(self, **kw):
        """The socket drops, the panel makes a new one after its 1.5 s wait, and the server answers it."""
        self.pg.evaluate("() => window.__drop()")
        self.pg.wait_for_timeout(1700)
        self.up(**kw)

    def ev(self, js, arg=None):
        return self.pg.evaluate(js, arg) if arg is not None else self.pg.evaluate(js)

    def close(self):
        self.ctx.close()
        if self in OPEN:
            OPEN.remove(self)


class Quiet(SimpleHTTPRequestHandler):
    """The static server without its request log, which buried the results."""

    def log_message(self, *args):
        pass


def run(name, fn):
    """A group of checks; an exception inside it is a failure of that group, not the end of the run. A group that
    asks for measurement data that is not here is skipped from that point on, and noted for the skip line."""
    if ONLY and not any(name.startswith(x) for x in ONLY):
        return
    print(f"\n[{name}]")
    opened = len(OPEN)
    try:
        fn()
    except support.Missing as missing:   # the checks after it need the data: they are skipped, not failed
        support.skip(name, missing)
        for pn in OPEN[opened:]:          # the pages it opened and did not get to close
            pn.close()
    except Exception as exc:   # noqa: BLE001 - every failure is reported, none ends the run
        check(f"{name}: ran to the end", False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}")


def main():
    global SETTINGS
    from playwright.sync_api import sync_playwright
    support.need_vendor(PANEL)                    # the page's libraries, which are fetched rather than kept in git
    SETTINGS = support.settings_message()         # what server/settings.py sends a panel that connects
    SETTINGS["values"]["roi_box"] = None          # the checks draw their own region where they need one
    work = Path(tempfile.mkdtemp(prefix="panel-review-"))
    static = work / "panel"
    shutil.copytree(PANEL, static)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(static)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"checking {PANEL} (served from {static})")
    errors = []

    with sync_playwright() as p:
        br = p.chromium.launch(args=["--no-sandbox"])

        def new(width=1440, theme="dark", height=900):
            return Panel(br, url, width, theme, height)

        # ---------------- bugs ----------------
        def b1():
            pn = new()
            st = json.loads(json.dumps(STATUS))
            st["engines"]["agent"]["ok"] = False                # not signed in: the band with the login command's copy button
            pn.up(clients=0, status=st)                        # and no capture program: that band has no copy button
            pn.push(start(11), done(11, bench("calc_short_subnet")))
            pn.pg.wait_for_timeout(400)
            off = pn.ev("() => [...document.querySelectorAll('#alerts .alert')].filter((a) => a.textContent.includes('캡처 프로그램')).map((a) => !!a.querySelector('[data-copy]'))")
            check("B1 the band that says the capture program is off has no copy button", off == [False], off)
            for sel in ("#alerts [data-copy]", ".entry [data-copy-answer]"):
                before = pn.ev("(s) => document.querySelector(s).innerHTML", sel)
                # pressed where it is: with two bands up, they float over the first answer's head (index.html, .alerts), and what is
                # checked here is the key's own two presses, not what lies over it
                pn.ev("(s) => document.querySelector(s).click()", sel)
                pn.pg.wait_for_timeout(250)
                pn.ev("(s) => document.querySelector(s).click()", sel)   # the second press, inside the 1.4 s
                pn.pg.wait_for_timeout(1900)
                after = pn.ev("(s) => { const b = document.querySelector(s); return [b.innerHTML, b.classList.contains('done'), b.innerText.trim()]; }", sel)
                check(f"B1 {sel}: back to its own word and mark after two quick presses",
                      after[0] == before and not after[1], f"now reads '{after[2]}'")
            errors.extend(pn.errors)
            pn.close()

        def b2():
            pn = new()
            pn.up()
            pn.push(start(21), done(21, bench("code_prog_peak")))
            pn.push({"type": "check", "id": 21, "passed": 2, "total": 3, "lang": "python", "how": "stdin", "rule": "",
                     "fails": [{"input": "3\n1 4\n2 5\n4 6", "expected": "2", "got": "3"}]})
            pn.pg.wait_for_timeout(400)
            r = pn.ev("""() => { const p = document.querySelector('.entry .vcheck .vc-case.bad .vc-io.got pre');
                if (!p) return null; const cs = getComputedStyle(p);
                return {bar: !!p.querySelector('.codebar'), pad: parseFloat(cs.paddingLeft), text: p.innerText.slice(0, 30)}; }""")
            check("B2 a failed example is a run of the check, with no code block bar", r is not None and not r["bar"], json.dumps(r, ensure_ascii=False))
            check("B2 and its text keeps clear of the border", r is not None and r["pad"] >= 8, json.dumps(r, ensure_ascii=False))
            # an answer cut off half way: its error details are a message, not code
            pn.push(start(22), {"type": "delta", "id": 22, "text": bench("exam_lms_java")[:300]})
            pn.pg.wait_for_timeout(300)
            pn.ev("() => window.__drop()")
            pn.pg.wait_for_timeout(400)
            d = pn.ev("""() => [...document.querySelectorAll('.entry[data-id="22"] details pre')].map((p) => !!p.querySelector('.codebar'))""")
            check("B2 the error details of a cut-off answer have no code block bar", d == [False], str(d))
            errors.extend(pn.errors)
            pn.close()

        def b3():
            pn = new()
            pn.up(can_ask=True)
            pn.push(start(31), done(31, bench("term_keyerror")))
            pn.pg.wait_for_timeout(400)
            live = "() => [...document.querySelectorAll('[data-ask]')].filter((b) => !b.disabled).length"
            check("B3 the follow-up buttons are there while connected", pn.ev(live) > 0, str(pn.ev(live)))
            pn.ev("() => window.__drop()")
            pn.pg.wait_for_timeout(300)
            check("B3 none can be pressed while the server is gone", pn.ev(live) == 0, f"{pn.ev(live)} still enabled")
            pn.pg.wait_for_timeout(1400)
            pn.up(can_ask=False)                               # a restarted server: nothing to ask about
            pn.ev("() => { window.__sent = []; const b = document.querySelector('[data-ask]'); if (b) b.click(); }")
            sent = pn.ev("() => (window.__sent || []).filter((m) => m.type === 'ask').length")
            check("B3 none can be pressed after reconnecting to a server that cannot answer them",
                  pn.ev(live) == 0 and sent == 0, f"{pn.ev(live)} enabled, {sent} sent")
            pn.close()
            pn = new()
            pn.up(can_ask=True)
            pn.push(start(32), done(32, bench("term_keyerror")))
            pn.pg.wait_for_timeout(300)
            pn.drop_and_return(can_ask=True)                   # the same server, back after a short drop
            pn.pg.wait_for_timeout(200)
            check("B3 they come back when the same server is back", pn.ev(live) > 0, str(pn.ev(live)))
            errors.extend(pn.errors)
            pn.close()

        def b4():
            pn = new()
            pn.up()
            text = bench("calc_short_subnet")
            pn.push(start(41), {"type": "delta", "id": 41, "text": text[:120]})
            pn.pg.wait_for_timeout(300)
            pn.drop_and_return()
            pn.push({"type": "delta", "id": 41, "text": text[120:]}, done(41, text))
            pn.pg.wait_for_timeout(400)
            r = pn.ev("""() => { const e = document.querySelector('.entry[data-id="41"]');
                return {err: !!e.querySelector('.errbox'), kind: e.querySelector('.kind').innerText,
                        labels: [...e.querySelectorAll('.mg')].map((m) => m.innerText.trim()).filter(Boolean)}; }""")
            check("B4 an answer finished after a short drop is not shown as cut off",
                  not r["err"] and r["kind"] == "단답형" and not any("쓰다 만" in x for x in r["labels"]),
                  json.dumps(r, ensure_ascii=False))
            # and a follow-up finished the same way
            pn.push(start(42, trigger="ask", transcript="큰 파일이면?", about=41),
                    {"type": "delta", "id": 42, "text": "TYPE: followup\nANSWER: 줄 단위로"})
            pn.pg.wait_for_timeout(300)
            pn.drop_and_return()
            pn.push(done(42, "TYPE: followup\nANSWER: 줄 단위로 읽습니다.\n\n한 줄씩 읽으면 메모리를 아낍니다."))
            pn.pg.wait_for_timeout(400)
            t = pn.ev("""() => { const t = document.querySelector('[data-turn="42"]'); return t ? !!t.querySelector('.errbox') : null; }""")
            check("B4 a follow-up finished after a short drop is not shown as cut off", t is False, str(t))
            errors.extend(pn.errors)
            pn.close()

        def b5():
            pn = new()
            pn.up()
            pn.push(start(51), {"type": "stage", "id": 51, "stage": "agent", "detail": "claude-opus-5-5"},
                    {"type": "delta", "id": 51, "text": "TYPE: mcq\nANSWER: ③ 12ns\n\n캐시 적중률이 95% 이므로"})
            pn.pg.wait_for_timeout(300)
            pn.push({"type": "stage", "id": 51, "stage": "local", "detail": "", "restart": True},
                    {"type": "delta", "id": 51, "text": "TYPE: mcq\n평균 접근 시간은"})
            pn.pg.wait_for_timeout(300)
            r = pn.ev("""() => { const e = document.querySelector('.entry[data-id="51"]'), a = e.querySelector('[data-answer]');
                return {hidden: a.hidden, text: a.innerText.replace(/\\s+/g, ' ').trim()}; }""")
            check("B5 the answer line of a discarded attempt goes with it",
                  r["hidden"] or "12ns" not in r["text"], json.dumps(r, ensure_ascii=False))
            errors.extend(pn.errors)
            pn.close()

        def b6():
            pn = new()
            pn.up()
            pn.pg.click("#more"); pn.pg.click("#open-settings"); pn.pg.wait_for_timeout(300)
            pn.pg.click("#settings [data-sec='agent']"); pn.pg.wait_for_timeout(250)
            pressed = "() => document.querySelector('#settings [data-set=\"agent_mode\"][aria-pressed=\"true\"]')?.dataset.val"
            pn.pg.click("#settings [data-set='agent_mode'][data-val='\"all\"']")
            pn.pg.wait_for_timeout(150)
            # the server turned the value down and sends the one it kept
            pn.push({"type": "settings", "values": {"agent_mode": "hard"}})
            pn.pg.wait_for_timeout(150)
            check("B6 a row of choices shows the value the server sent back", pn.ev(pressed) == '"hard"', str(pn.ev(pressed)))
            pn.pg.click("#settings [data-combo='agent_effort'] .combo-btn"); pn.pg.wait_for_timeout(200)
            pn.pg.click(".combo-list:not([hidden]) li[data-val='\"max\"']"); pn.pg.wait_for_timeout(150)
            pn.push({"type": "settings", "values": {"agent_effort": ""}})
            pn.pg.wait_for_timeout(150)
            v = pn.ev("() => document.querySelector('#settings [data-combo=\"agent_effort\"] .combo-val').innerText.trim()")
            check("B6 a dropdown shows the value the server sent back", v == "기본", v)
            state = """() => [...document.querySelectorAll('#settings [data-set="agent_hard_types"][data-multi]')]
                .filter((e) => e.checked === true || e.getAttribute('aria-pressed') === 'true').map((e) => e.dataset.multi)"""
            kept = pn.ev(state)
            pn.ev("() => document.querySelector('#settings [data-set=\"agent_hard_types\"][data-multi=\"mcq\"]').click()")
            pn.pg.wait_for_timeout(150)
            pn.push({"type": "settings", "values": {"agent_hard_types": kept}})
            pn.pg.wait_for_timeout(150)
            check("B6 the type choices show the list the server sent back", pn.ev(state) == kept, f"{pn.ev(state)} vs {kept}")
            pn.pg.keyboard.press("Escape"); pn.pg.wait_for_timeout(200)
            note = "() => [...document.querySelectorAll('#alerts .alert')].some((a) => a.innerText.includes('화면 일부만'))"
            pn.push({"type": "settings", "values": {"roi_box": [0.1, 0.1, 0.5, 0.5]}})
            pn.pg.wait_for_timeout(150)
            on = pn.ev(note)
            pn.push({"type": "settings", "values": {"roi_box": None}})
            pn.pg.wait_for_timeout(150)
            check("B6 the 'part of the screen' note follows a settings message at once", on and not pn.ev(note),
                  f"after drawing {on}, after clearing {pn.ev(note)}")
            errors.extend(pn.errors)
            pn.close()

        def b7():
            pn = new()
            pn.up()
            pn.push(start(71), done(71, bench("term_keyerror")))     # its ASKED line holds `count.py` in backticks
            pn.pg.wait_for_timeout(400)
            r = pn.ev("""() => { const a = document.querySelector('.entry[data-id="71"] [data-asked]');
                return {text: a.innerText.trim(), code: !!a.querySelector('code')}; }""")
            check("B7 what the problem asks is shown without its markdown marks",
                  "`" not in r["text"] and r["code"], json.dumps(r, ensure_ascii=False))
            errors.extend(pn.errors)
            pn.close()

        def b8():
            for mode, bad in (("all", "모두을"), ("verify", "검토을")):
                pn = new()
                st = json.loads(json.dumps(STATUS))
                st["engines"]["agent"].update(mode=mode, effective=mode)
                pn.up(clients=0, status=st)
                step = pn.ev("() => [...document.querySelectorAll('.steps li .d')].map((d) => d.innerText).find((t) => t.includes('Claude Code가')) || ''")
                # the step is named after the agent the server uses, and must be found for the check to mean anything
                check(f"B8 the agent's step reads right with the mode '{mode}'",
                      bool(step) and bad not in step and "검토을" not in step, step)
                pn.pg.click("#more"); pn.pg.click("#open-settings"); pn.pg.wait_for_timeout(250)
                pn.pg.click("#settings [data-sec='agent']"); pn.pg.wait_for_timeout(200)
                note = pn.ev("() => document.querySelector('#settings .sec-note')?.innerText || ''")
                check(f"B8 the outbound note has no brackets in brackets and ends its sentences ({mode})",
                      "))" not in note and not re.search(r"\)\s+[가-힣A-Za-z]", note), note)
                pn.close()
            pn = new(width=760)
            pn.up(clients=0)
            tips = pn.ev("() => document.querySelector('.tips').innerText")
            check("B8 in one column, the tips do not point to a card on the right", "오른쪽" not in tips, tips[-60:])
            pn.close()

        def b9():
            pn = new()
            pn.up()
            pn.push(start(91), done(91, bench("calc_short_subnet")))
            pn.pg.wait_for_timeout(300)
            pn.pg.click("#more"); pn.pg.click("#open-settings"); pn.pg.wait_for_timeout(300)
            pn.ev("() => { stick = true; }")
            pn.pg.focus("#settings .set-tab[aria-selected='true']")
            for k in ("ArrowDown", "ArrowUp", "End", "Home"):
                pn.pg.keyboard.press(k)
                pn.pg.wait_for_timeout(80)
            check("B9 walking the settings tabs leaves the notebook following new answers", pn.ev("() => stick") is True)
            errors.extend(pn.errors)
            pn.close()

        def b10():
            pn = new()
            pn.up()
            skew = 600                                        # the server's clock ten minutes behind this one's
            server_now = time.time() - skew
            pn.push(dict(CAPTURE, now=server_now, last_frame=server_now - 2, last_audio=server_now - 1))
            st = json.loads(json.dumps(STATUS))
            st["engines"]["local"]["busy"] = {"model": "sidenote-gemma4:e4b", "until": server_now + 90}
            pn.push(st)
            pn.pg.wait_for_timeout(200)
            left = pn.ev("() => { const d = [...document.querySelectorAll('#st-local dt')].find((x) => x.innerText.includes('돌아감')); return d ? d.nextElementSibling.innerText : ''; }")
            check("B10 the busy GPU's countdown reads the server's clock", left == "2분 뒤", left)
            pn.ev("() => { window.__sent = []; document.getElementById('roi-draw').click(); }")
            pn.push({"type": "thumb", "url": THUMB, "ts": server_now - 120, "live": False})
            pn.pg.wait_for_timeout(200)
            title = pn.ev("() => document.getElementById('shot-title').innerText")
            # the whole bracketed age: the "12 minutes ago" the browser's clock gives also contains "2 minutes ago"
            check("B10 the age of the last screen reads the server's clock", "2분" in title and "12분" not in title, title)
            errors.extend(pn.errors)
            pn.close()

        for name, fn in (("bug 1 copy", b1), ("bug 2 code bars", b2), ("bug 3 follow-up buttons", b3),
                         ("bug 4 finished after a drop", b4), ("bug 5 restart", b5), ("bug 6 settings messages", b6),
                         ("bug 7 asked", b7), ("bug 8 wording", b8), ("bug 9 tab keys", b9), ("bug 10 clocks", b10)):
            run(name, fn)

        # ---------------- design ----------------
        def d1():
            for w in (360, 420, 730, 760, 800, 1440):   # 730 and 800 either side of the two-row bar's edge (780)
                pn = new(width=w, height=800)
                pn.up()
                pn.push(start(101), done(101, bench("calc_short_subnet")))
                pn.pg.wait_for_timeout(300)
                bar = pn.ev("() => Math.round(document.querySelector('header.bar').getBoundingClientRect().height)")
                head = pn.ev("() => Math.round(document.querySelector('.entry .row.head').getBoundingClientRect().height)")
                classic = pn.ev("() => document.documentElement.dataset.skin === 'classic'")
                # Classic: two rows up to 780 px since the signals sit in their well. New: its floating pill and the gap over it
                limit = (92 if w <= 780 else 56) if classic else (96 if w <= 790 else 66)
                check(f"D1 {w}px: the top bar is at most {limit}px tall", bar <= limit, f"{bar}px")
                check(f"D1 {w}px: an entry's head is one line", head <= 44, f"{head}px")
                pn.close()

        def d2():
            pn = new()
            pn.up()
            pn.pg.click("#more"); pn.pg.click("#open-settings"); pn.pg.wait_for_timeout(250)
            pn.pg.click("#settings [data-sec='agent']"); pn.pg.wait_for_timeout(200)
            r = pn.ev("""() => ({native: document.querySelectorAll('#settings input[type=checkbox]').length,
                multi: [...new Set([...document.querySelectorAll('#settings [data-multi]')].map((e) => Math.round(e.getBoundingClientRect().height)))],
                seg: [...new Set([...document.querySelectorAll('#settings [data-set="agent_mode"]')].map((e) => Math.round(e.getBoundingClientRect().height)))]})""")
            check("D2 the sheet has no control the operating system draws", r["native"] == 0, json.dumps(r))
            check("D2 the type choices are the same box as a row of choices", r["multi"] == r["seg"], json.dumps(r))
            pn.close()

        def d3():
            pn = new(width=420)
            pn.up()
            pn.push(start(131), {"type": "agent_confirm", "id": 131, "cid": "c131", "what": "문제 부분 화면 1180x900",
                                 "thumb": THUMB, "timeout": 120, "ts": time.time()})
            pn.pg.wait_for_timeout(300)
            tops = pn.ev("() => [...document.querySelectorAll('[data-confirm]')].map((b) => Math.round(b.getBoundingClientRect().top))")
            check("D3 420px: the two answers to the send-to-Claude question stay side by side", len(tops) == 2 and tops[0] == tops[1], str(tops))
            pn.close()

        def d4():
            for w in (420, 1440):
                pn = new(width=w)
                pn.up()
                pn.pg.click("#more"); pn.pg.click("#open-settings"); pn.pg.wait_for_timeout(250)
                pn.pg.click("#settings [data-sec='capture']"); pn.pg.wait_for_timeout(200)
                pn.pg.click("#settings [data-combo='monitor'] .combo-btn"); pn.pg.wait_for_timeout(250)
                r = pn.ev("""() => { const l = document.querySelector('.combo-list:not([hidden])').getBoundingClientRect();
                    const b = document.querySelector('.combo-btn[aria-expanded="true"]').getBoundingClientRect();
                    const s = document.getElementById('settings').getBoundingClientRect();
                    return {l: [l.left, l.right].map(Math.round), b: [b.left, b.right].map(Math.round), s: [s.left, s.right].map(Math.round)}; }""")
                inside = r["l"][0] >= r["s"][0] and r["l"][1] <= r["s"][1]
                lined = abs(r["l"][0] - r["b"][0]) <= 2 or abs(r["l"][1] - r["b"][1]) <= 2
                check(f"D4 {w}px: the open list stays inside the sheet, lined up with its control", inside and lined, json.dumps(r))
                pn.close()

        def d5():
            # both widths: in one column the rail sits over another part of the page's pools of light
            for w in (1440, 420):
                pn = new(width=w)
                pn.up()
                names = ["calc_mcq_cache", "exam_lms_essay", "calc_short_subnet", "code_prog_peak", "term_keyerror"]
                for i, n in enumerate(names):
                    pn.push(start(150 + i), done(150 + i, bench(n)))
                pn.push(start(160), {"type": "delta", "id": 160, "text": "TYPE: mcq\nANSWER: ②"})   # still being written
                pn.pg.wait_for_timeout(500)
                worst = []
                # every row in turn as the current one: each kind's own colour lies on the band
                for hid in [150 + i for i in range(len(names))] + [160]:
                    pn.ev(f"() => {{ viewId = {hid}; markIndex(); document.querySelector('#history .h[data-id=\"{hid}\"]').scrollIntoView({{block: 'center'}}); }}")
                    pn.pg.wait_for_timeout(120)
                    worst += contrasts(pn.pg, "#history .h[aria-current='true'] .hk, #history .h[aria-current='true'] time")
                low = [x for x in worst if x[0] < 4.5]
                check(f"D5 dark {w}px: the index's current row keeps every word at 4.5:1 or more", not low, str(low))
                pn.close()

        def d6():
            pn = new()
            pn.up()
            pn.push(start(171), {"type": "error", "id": 171, "text": "RuntimeError: usage limit reached", "hint": "limit"})
            pn.pg.wait_for_timeout(300)
            gap = pn.ev("""() => { const e = document.querySelector('.entry[data-id="171"]');
                return Math.round(e.querySelector('.errbox h2').getBoundingClientRect().top - e.querySelector('.kind').getBoundingClientRect().top); }""")
            # Classic sets the message beside the label; New sets it right under the chip, its label
            classic = pn.ev("() => document.documentElement.dataset.skin === 'classic'")
            check("D6 an error entry says what went wrong on its first line", gap <= (12 if classic else 40), f"{gap}px below the label")
            pn.close()

        def d7():
            pn = new()
            pn.up()
            pn.push(start(181), {"type": "stage", "id": 181, "stage": "local"})
            # An automatic look is said once it has run two seconds (panel/app.js REVEAL_MS: the looks that
            # find nothing within a second, most of them, no longer flip the welcome and the rail every few seconds)
            pn.pg.wait_for_timeout(2400)
            r = pn.ev("""() => ({thread: !document.getElementById('thread').hidden,
                pending: [...document.querySelectorAll('#welcome [data-pending]')].map((e) => e.innerText),
                title: document.getElementById('shot-title').innerText, img: !document.getElementById('thumb').hidden,
                empty: document.getElementById('shot-empty').hidden ? '' : document.getElementById('shot-empty').innerText})""")
            check("D7 the first analysis is shown on the welcome sheet, not on a sheet of its own",
                  not r["thread"] and r["pending"] and r["pending"][0], json.dumps(r, ensure_ascii=False))
            check("D7 the screen card shows the screen being looked at", r["img"] and "없습니다" not in r["empty"],
                  json.dumps(r, ensure_ascii=False))
            pn.close()

        def d8():
            pn = new()
            pn.up()
            pn.push(start(191), done(191, bench("exam_lms_essay")),                  # a 90-character answer line
                    start(192), done(192, "TYPE: short\nANSWER: 30개\n\n풀이."),
                    start(193), done(193, "TYPE: short\nANSWER: 30개, 192.168.10.95\n\n풀이."))
            pn.pg.wait_for_timeout(400)
            size = "(id) => parseFloat(getComputedStyle(document.querySelector(`.entry[data-id=\"${id}\"] .hl`)).fontSize)"
            s = [pn.ev(size, i) for i in (191, 192, 193)]
            check("D8 a long answer line is drawn smaller than a short one", s[0] <= 18 and s[1] > s[2] > s[0] and s[1] >= 28, str(s))
            pn.close()

        def d9():
            pn = new(width=420)
            pn.up()
            pn.push(start(201), done(201, bench("term_keyerror")))
            pn.pg.wait_for_timeout(400)
            pn.pg.mouse.move(2, 2)
            # No sideways scroll inside a code box either: a long line wraps onto the next row instead of the box
            # scrolling sideways, so nothing is cut at the right edge at all: no block is wider than its box, and a
            # wrapped row hangs from its line's indentation.
            r = pn.ev("""() => { const codes = [...document.querySelectorAll('.md pre > code')];
                const wide = codes.filter((x) => x.scrollWidth > x.clientWidth + 1).length;
                const wrapped = [...document.querySelectorAll('.md pre > code.lined .tx')].find((t) => t.getClientRects().length > 1
                    || t.getBoundingClientRect().height > parseFloat(getComputedStyle(t).lineHeight) * 1.5);
                const hang = wrapped ? getComputedStyle(wrapped).paddingLeft : null;
                return { blocks: codes.length, wide, wrappedOne: !!wrapped, hang }; }""")
            check("D9 a long code line wraps inside its box instead of running off the right",
                  r["blocks"] > 0 and r["wide"] == 0 and r["wrappedOne"], str(r))
            pn.close()

        def d10():
            pn = new()
            pn.up(clients=0)                                   # no capture program: the switches have nothing to act on
            pn.push(start(211), done(211, bench("code_prog_peak")))
            pn.pg.wait_for_timeout(400)
            look = "() => { const b = document.querySelector('.runbox .runtools .stdin-toggle'); const s = getComputedStyle(b); return [s.boxShadow, s.backgroundColor, s.color].join(' | '); }"
            closed = pn.ev(look)
            pn.ev("() => document.querySelector('.runbox .runtools .stdin-toggle').click()")
            pn.pg.wait_for_timeout(250)
            pn.pg.mouse.move(2, 2)
            pn.pg.wait_for_timeout(250)
            check("D10 the input toggle looks pressed while its box is open", pn.ev(look) != closed, closed)
            sw = pn.ev("() => { const s = document.getElementById('sw-screen'); return {on: s.getAttribute('aria-checked'), op: getComputedStyle(s).opacity, dis: s.disabled}; }")
            check("D10 a switch with no capture program to act on is greyed out and not pressable", sw["on"] == "true" and float(sw["op"]) < 1.0 and sw["dis"], json.dumps(sw))
            arm = "() => getComputedStyle(document.getElementById('clear')).color"
            pn.pg.click("#more"); pn.pg.wait_for_timeout(150)
            rest = pn.ev(arm)
            pn.pg.click("#clear"); pn.pg.wait_for_timeout(150)
            check("D10 Clear history changes colour while it waits for the second press", pn.ev(arm) != rest, rest)
            pn.pg.keyboard.press("Escape")
            pn.ev("() => window.__drop()")
            pn.pg.wait_for_timeout(300)
            dis = pn.ev("() => [document.getElementById('reanalyze').disabled, document.getElementById('pause').disabled]")
            check("D10 Reanalyze and Pause cannot be pressed while the server is gone", dis == [True, True], str(dis))
            pn.close()

        def d11():
            pn = new(width=420, theme="light")
            pn.up()
            pn.pg.wait_for_timeout(200)
            low = [x for x in contrasts(pn.pg, ".pill[data-state='ok']") if x[0] < 4.5]
            check("D11 light: the Connected pill reads at 4.5:1 or more", not low, str(low))
            pn.pg.click("#more"); pn.pg.click("#open-settings"); pn.pg.wait_for_timeout(300)
            bg = pn.ev("() => getComputedStyle(document.getElementById('settings')).backgroundColor")
            alpha = re.findall(r"[\d.]+", bg)
            check("D11 the settings sheet can be read over the page", len(alpha) == 3 or float(alpha[-1]) >= .6, bg)
            rows = pn.ev("""() => { const t = {}; for (const b of document.querySelectorAll('#settings .set-tab')) {
                const y = Math.round(b.getBoundingClientRect().top); t[y] = (t[y] || 0) + 1; } return Object.values(t); }""")
            check("D11 420px: no settings tab sits alone on its row", min(rows) >= 2, str(rows))
            close = pn.ev("() => { const b = document.getElementById('settings-close'); return {svg: !!b.querySelector('svg'), text: b.innerText.trim()}; }")
            check("D11 the sheet's close button wears a drawn mark", close["svg"] and "✕" not in close["text"], json.dumps(close, ensure_ascii=False))
            pn.close()
            pn = new()
            pn.up()
            pn.push(start(221, thumb=None, trigger="voice", transcript="프로세스와 스레드의 차이를 말해 보세요."),
                    done(221, "TYPE: short\nANSWER: 메모리 공유 여부\n\n프로세스는 메모리를 따로 쓰고, 스레드는 함께 씁니다."))
            pn.pg.wait_for_timeout(400)
            r = pn.ev("() => [document.getElementById('shot-title').innerText, document.getElementById('shot-empty').innerText]")
            check("D11 a spoken problem's screen card does not promise a screen it then says it lacks",
                  not (r[0].startswith("이 답의 화면") and "없습니다" in r[1]), " / ".join(r))
            meta = pn.ev("() => { const b = document.querySelector('.meta-more'); return b ? {svg: !!b.querySelector('svg'), text: b.innerText.trim()} : null; }")
            check("D11 the ⋯ beside the answer's facts is a drawn mark", meta and meta["svg"] and "⋯" not in meta["text"], json.dumps(meta, ensure_ascii=False))
            pn.ev("() => { stick = false; document.getElementById('jump').hidden = false; }")
            jump = pn.ev("() => { const b = document.getElementById('jump'); return {svg: !!b.querySelector('svg'), text: b.innerText.trim()}; }")
            check("D11 the jump to the newest answer wears a drawn arrow", jump["svg"] and "↓" not in jump["text"], json.dumps(jump, ensure_ascii=False))
            pn.close()
            pn = new()
            pn.up()                                            # the welcome page, with three steps done
            tick = pn.ev("""() => { const b = document.querySelector('.steps li[data-done="true"] .box');
                return {svg: !!b.querySelector('svg'), after: getComputedStyle(b, '::after').content}; }""")
            check("D11 a done step is ticked with a drawn mark", tick["svg"] and "✓" not in tick["after"], json.dumps(tick, ensure_ascii=False))
            pn.close()

        for name, fn in (("design 1 narrow", d1), ("design 2 native control", d2), ("design 3 confirm", d3),
                         ("design 4 dropdown", d4), ("design 5 index row", d5), ("design 6 error entry", d6),
                         ("design 7 first analysis", d7), ("design 8 long answer", d8), ("design 9 code scroll", d9),
                         ("design 10 states", d10), ("design 11", d11)):
            run(name, fn)
        br.close()
    srv.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    print("\npage errors:", errors[:5] if errors else "none")
    support.skip_line()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    for f in FAIL:
        print(f"  FAIL {f}")
    return 1 if FAIL or errors else 0


if __name__ == "__main__":
    sys.exit(main())
