"""What the scenario and design suites share: the panel in a headless browser over a stand-in server.

Not a suite: tests/panel_scenarios.py and tests/panel_design.py import it. The page is a copy of panel/ (or of PANEL_DIR, to watch a
check fail on an older one) served with the server's own CSP and a /history kept in a list the test can change; its socket is a
stand-in the test speaks through, as the server would. Nothing here needs a server, a GPU or the network.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]         # the repository: this file is in tests/
sys.path.insert(0, str(ROOT / "tests"))            # support.py beside it, wherever this is run from
import support  # noqa: E402

PANEL = Path(os.environ.get("PANEL_DIR") or ROOT / "panel")
CSP = "".join(re.findall(r'"([^"]*)"', re.search(r"^CSP = \((.*?)\)$", (ROOT / "server" / "app.py").read_text(encoding="utf-8"),
                                                  re.S | re.M).group(1)))
SHOTS = support.out("shots")

# The stand-in socket: it opens by itself and sends nothing anywhere. `OPEN` is there because the page compares readyState with it.
SOCKET = """
window.__sent = [];
window.WebSocket = function () {
  this.readyState = 1; window.__sock = this;
  this.close = () => {};
  this.send = (x) => { try { window.__sent.push(JSON.parse(x)); } catch (_) { window.__sent.push(x); } };
  setTimeout(() => { if (this.onopen) this.onopen({}); }, 10);
};
window.WebSocket.OPEN = 1; window.WebSocket.CONNECTING = 0; window.WebSocket.CLOSED = 3;
"""

ENGINES = {"local": {"ok": True, "method": "local", "model": "sidenote-gemma4:26b", "present": True, "on": True, "busy": None,
                     "stand_in": "", "loaded": {"model": "sidenote-gemma4:26b", "vram_gb": 16.2}, "loading": False},
           "agent": {"ok": True, "method": "claude.ai", "plan": "pro", "present": True, "mode": "hard", "effective": "hard", "payload": "crop",
                     "model": "claude-opus-5-5", "asked_model": "", "effort": "medium", "effort_own": True, "thinking": "adaptive", "max_tokens": 128000,
                     "brake": "", "label": "Claude Code", "short": "Claude", "product": "Claude Code", "limit_until": None,
                     "account": {"email": "reader@example.com", "plan": "pro"}},
           "search": {"present": True, "on": True}, "ready": True}
CAPTURE = {"type": "capture", "clients": 1, "info": "capture/win32", "last_frame": None, "last_audio": None, "screen_on": True, "audio_on": True,
           "caps": {"screen": True, "audio": True, "monitor": 1, "no_audio": False, "monitors": [[3840, 2160], [1440, 2560]]}}
USAGE = {"type": "usage", "answers": 18, "empty": 2, "tokens_in": 42110, "tokens_out": 9102, "cost_usd": 0.43, "errors": 0, "elapsed_p50": 17.2,
         "first_token_p50": 4.1, "first_token_avg": 4.6, "tps_avg": 58.3, "last_error": None,
         "engines": {"local": {"answers": 15, "errors": 0, "last_error": None, "tokens_in": 26110, "tokens_out": 6102, "cost_usd": 0, "elapsed_p50": 12.4, "first_token_avg": 2.1, "tps_avg": 96.3,
                               "recent": [{"ts": 1793500000 + i * 300, "elapsed": 4.0 + i * 1.5, "first_token": 1.0 + i * .2, "tps": 90.0 + i} for i in range(15)]},
                     "agent": {"answers": 3, "errors": 1, "last_error": 1793500000, "tokens_in": 16000, "tokens_out": 3000, "cost_usd": 0.43, "elapsed_p50": 41.7, "first_token_avg": 22.8, "tps_avg": 71.2,
                               "recent": [{"ts": 1793500000 + i * 900, "elapsed": 30.0 + i * 9, "first_token": 18.0 + i, "tps": 70.0 + i} for i in range(3)]}}}
GPU = {"type": "gpu", "used": 16200, "total": 23028, "util": 41, "temp": 55, "power": 180}


def row(i: int, kind: str = "essay", asked: str = "무엇을 묻는가", key: str = "답", body: str = "풀이", ago: float = 0.0, **more) -> dict:
    """One answer as /history gives it."""
    head = f"TYPE: {kind}\nANSWER: {key}\n" + (f"ASKED: {asked}\n" if asked else "") + "\n"
    return {"id": i, "ts": time.time() - ago, "trigger": "screen", "transcript": "", "text": head + body, "model": "sidenote-gemma4:26b", "engine": "local",
            "sent": [], "stages": {"local": True, "agent": False}, "usage": {"input_tokens": 100, "output_tokens": 40}, "cost_usd": None, "elapsed": 12.0,
            "region": None, "thumb": None, "kind": kind, "turns": [], **more}


def thumb(w: int, h: int) -> str:
    """A screen of w x h as a picture the CSP lets in: a data URL of an SVG."""
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}'><rect width='{w}' height='{h}' fill='#345'/></svg>"
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


class Stand:
    """The server's half: serves the panel and its /history, for as many pages as a suite opens."""

    def __init__(self, name: str):
        self.static = support.out(f"panelstatic-{name}")
        shutil.rmtree(self.static, ignore_errors=True)
        shutil.copytree(PANEL, self.static)
        (self.static / "health").write_text('{"ok":true}')
        self.rows: list[dict] = []
        stand = self

        class H(SimpleHTTPRequestHandler):
            def end_headers(self):
                self.send_header("Content-Security-Policy", CSP)
                super().end_headers()

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/history":
                    q = parse_qs(url.query)
                    rows = sorted(stand.rows, key=lambda r: r["ts"], reverse=True)
                    limit = int(q.get("limit", ["40"])[0])
                    return self._json({"answers": rows[:limit]})
                if url.path == "/history/days":
                    days: dict = {}
                    for r in stand.rows:
                        d = time.strftime("%Y-%m-%d", time.localtime(r["ts"]))
                        e = days.setdefault(d, {"day": d, "n": 0, "first": r["ts"], "last": r["ts"]})
                        e["n"] += 1
                        e["first"], e["last"] = min(e["first"], r["ts"]), max(e["last"], r["ts"])
                    return self._json({"days": sorted(days.values(), key=lambda x: x["day"], reverse=True)})
                return super().do_GET()

            def _json(self, data):
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=str(self.static)))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"


class Page:
    """A page of the panel: opened on the rows given, told what a server tells a panel that opens."""

    def __init__(self, browser, stand: Stand, rows=(), w=1600, h=1000, theme="dark", settle=700, status=True, reduced=True,
                 locale=None, query=""):
        # locale: the browser's language, Korean unless a suite asks for another (support.LOCALE); query: added to the
        # address, as ?lang=ko
        stand.rows = list(rows)
        self.stand = stand
        self.errors: list[str] = []
        self.ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=theme, reduced_motion="reduce" if reduced else "no-preference",
                                       locale=locale or support.LOCALE, accept_downloads=True)
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(8000)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" and "Failed to load" not in m.text else None)
        self.page.add_init_script(SOCKET)
        self.page.add_init_script(f"try {{ localStorage.setItem('sidenote-theme', {json.dumps(theme)}); }} catch (e) {{}}")
        # Motion is on unless it is turned off (theme.js): a page asked for less motion here is one set to follow the system
        if reduced:
            self.page.add_init_script("try { localStorage.setItem('sidenote-motion', 'system'); } catch (e) {}")
        self.page.goto(stand.url + query, wait_until="load")
        self.page.wait_for_timeout(120)
        if status:
            self.open_messages()
        self.page.wait_for_timeout(settle)

    def open_messages(self, engines=None, capture=None, usage=None, gpu=True):
        now = self.js("() => Date.now() / 1000")
        self.send({"type": "status", "text": "connected", "paused": False, "lang": "auto", "audio": True, "voice": True, "can_ask": True, "run_enabled": True,
                   "runner": True, "engines": engines or ENGINES})
        self.send({**(capture or CAPTURE), "now": now, "last_frame": now - 2, "last_audio": now - 3})
        self.send(usage or USAGE)
        if gpu:
            self.send(GPU)

    def js(self, expr, arg=None):
        return self.page.evaluate(expr, arg) if arg is not None else self.page.evaluate(expr)

    def send(self, *msgs):
        """Through the socket's own path: what the page's onmessage would have got."""
        for m in msgs:
            self.js("(m) => window.__sock.onmessage({ data: JSON.stringify(m) })", m)

    def wait(self, ms=200):
        self.page.wait_for_timeout(ms)

    def drop(self):
        """The connection falling, as the browser says it."""
        self.js("() => { window.__sock.readyState = 3; window.__sock.onclose({}); }")

    def answer(self, i, kind="essay", asked="", key="답", body="풀이", final=True, ts=None):
        """An answer arriving as a server sends it: start, the text, and its end."""
        text = f"TYPE: {kind}\nANSWER: {key}\n" + (f"ASKED: {asked}\n" if asked else "") + "\n" + body
        now = ts or self.js("() => Date.now() / 1000")
        self.send({"type": "analysis_start", "id": i, "ts": now, "thumb": None, "transcript": "", "pages": 0, "trigger": "screen", "roi": None},
                  {"type": "delta", "id": i, "text": text})
        if final:
            self.done(i, text)
        return text

    def done(self, i, text):
        self.send({"type": "analysis_done", "id": i, "text": text, "usage": {}, "cost_usd": None, "model": "sidenote-gemma4:26b", "engine": "local",
                   "sent": [], "stages": {"local": True, "agent": False}, "elapsed": 3.0, "region": None})

    def shot(self, name, full=False):
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=full)
        return path

    def close(self):
        self.ctx.close()


def pixels(browser, png: bytes, boxes: list) -> list:
    """The mean colour of each box [x0, y0, x1, y1] of a screenshot, read by a browser page of its own: the interpreter running the panel
    suites may hold Playwright alone, with no image library."""
    ctx = browser.new_context()
    p = ctx.new_page()
    out = p.evaluate("""async ([src, boxes]) => {
        const bits = await createImageBitmap(await (await fetch(src)).blob());
        const c = new OffscreenCanvas(bits.width, bits.height), g = c.getContext('2d');
        g.drawImage(bits, 0, 0);
        return boxes.map(([x0, y0, x1, y1]) => {
          const w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0), d = g.getImageData(x0, y0, w, h).data, m = [0, 0, 0];
          for (let i = 0; i < d.length; i += 4) { m[0] += d[i]; m[1] += d[i + 1]; m[2] += d[i + 2]; }
          return m.map((v) => v / (d.length / 4));
        });
    }""", ["data:image/png;base64," + base64.b64encode(png).decode(), boxes])
    ctx.close()
    return out


def background_of(browser, png: bytes, box: list) -> list:
    """The commonest colour of a box of a screenshot: what the words in it stand on."""
    ctx = browser.new_context()
    p = ctx.new_page()
    out = p.evaluate("""async ([src, [x0, y0, x1, y1]]) => {
        const bits = await createImageBitmap(await (await fetch(src)).blob());
        const c = new OffscreenCanvas(bits.width, bits.height), g = c.getContext('2d');
        g.drawImage(bits, 0, 0);
        const d = g.getImageData(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0)).data, n = new Map();
        for (let i = 0; i < d.length; i += 4) { const k = (d[i] >> 2) << 16 | (d[i + 1] >> 2) << 8 | d[i + 2] >> 2; n.set(k, (n.get(k) || 0) + 1); }
        const top = [...n].sort((a, b) => b[1] - a[1])[0][0];
        return [(top >> 16 & 255) * 4 + 2, (top >> 8 & 255) * 4 + 2, (top & 255) * 4 + 2];
    }""", ["data:image/png;base64," + base64.b64encode(png).decode(), box])
    ctx.close()
    return out


def contrast(a: list, b: list) -> float:
    def lum(c):
        v = [x / 255 for x in c[:3]]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


class Tally:
    """One line per check and the tally tests/run.sh reads."""

    def __init__(self):
        self.ok, self.bad, self.groups = 0, [], 0
        self.only = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]

    def check(self, name, cond, detail=""):
        if cond:
            self.ok += 1
        else:
            self.bad.append(name)
        print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {str(detail)[:300]}" if detail != "" and not cond else ""), flush=True)

    def group(self, name) -> bool:
        """A heading, and whether this group runs (ONLY="ladder,region" for some of them)."""
        if self.only and not any(o in name for o in self.only):
            return False
        print(f"[{name}]", flush=True)
        return True

    def end(self) -> int:
        print(f"\n==== {self.ok} passed, {len(self.bad)} failed ====")
        for b in self.bad:
            print(f"  FAIL {b}")
        return 1 if self.bad else 0

