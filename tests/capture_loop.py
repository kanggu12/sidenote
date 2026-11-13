"""Drive the capture program's screen loop with made-up screens and see what it sends.

    .venv/bin/python tests/capture_loop.py

No Windows and no server: mss is replaced by a grabber that hands out prepared frames, and the
sender collects the messages. The loop is where the parts meet (the send gate, the scroll reading,
the stitcher, the panel's switches), and nothing was watching it: the automatic joining of a
scrolled problem never joined anything for a day, because the panel's switch check threw the
stitcher away on the poll after it was made.
"""
import base64
import io
import os
import sys
import threading
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))   # client/ of the repository
import random                                  # noqa: E402
from PIL import Image, ImageDraw               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail and not cond else ""))


def page(offset=0, w=1600, h=900, editor_line=0):
    """A problem pane on the left that scrolls by `offset`, an editor on the right that does not."""
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for i in range(90):
        y = 20 + i * 28 - offset
        if -30 < y < h:
            rnd = random.Random(500 + i)
            x = 40
            for _ in range(rnd.randint(2, 7)):
                wl = rnd.randint(30, 150)
                if x + wl > w // 2:
                    break
                d.rectangle([x, y + rnd.randint(0, 4), x + wl, y + 14], fill=(rnd.randint(0, 90),) * 3)
                x += wl + rnd.randint(8, 24)
    d.rectangle([w // 2 + 20, 0, w, h], fill="#1e2430")
    for i in range(editor_line):          # lines typed into the editor, which must not read as a scroll
        d.rectangle([w // 2 + 60, 40 + i * 24, w // 2 + 60 + 40 + (i * 37) % 300, 52 + i * 24], fill="#9fd2a0")
    return img


class FakeGrab:
    def __init__(self, img):
        self.size = img.size
        self.bgra = img.convert("RGBA").tobytes("raw", "BGRA")


class FakeMSS:
    frames: list = []
    pos = 0

    def __init__(self):
        self.monitors = [{"left": 0, "top": 0, "width": 1600, "height": 900},
                         {"left": 0, "top": 0, "width": 1600, "height": 900}]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def grab(self, mon):
        img = FakeMSS.frames[min(FakeMSS.pos, len(FakeMSS.frames) - 1)]
        FakeMSS.pos += 1
        return FakeGrab(img)


class FakeSender:
    def __init__(self, connected=True, **wants):
        self.wants = {"screen": True, "audio": True, "monitor": 1, "stitch": False, **wants}
        self.epoch = 0
        self.connected = connected   # the real one has no socket until the server answers
        self.sent = []

    def keepalive(self):
        pass

    def set_caps(self, **kw):
        pass

    def send(self, msg):
        self.sent.append(msg)


def run(frames, polls=None, no_auto_stitch=False, **wants):
    """Feed the loop these frames, one per poll, and return what it sent."""
    import capture
    capture.window_rects = lambda mon, limit=40: ([], [])      # no window list on this machine
    capture._grabber = lambda: FakeMSS
    FakeMSS.frames, FakeMSS.pos = frames, 0
    sender = FakeSender(**wants)
    stop = threading.Event()
    args = types.SimpleNamespace(stable_polls=1, settle=0.3, threshold=0.1, fps=50.0, max_width=1600,
                                 monitor=None, stitch=None, once=False, no_auto_stitch=no_auto_stitch, log="")
    t = threading.Thread(target=capture.screen_loop, args=(sender, stop, args), daemon=True)
    t.start()
    end = time.time() + 20
    want = polls if polls is not None else len(frames)
    while time.time() < end and FakeMSS.pos < want:
        time.sleep(0.05)
    time.sleep(0.4)
    stop.set()
    t.join(timeout=3)
    return sender.sent


def sizes(msgs):
    out = []
    for m in msgs:
        img = Image.open(io.BytesIO(base64.b64decode(m["data"])))
        extra = [Image.open(io.BytesIO(base64.b64decode(e))).size for e in (m.get("extra") or [])]
        out.append((img.size, extra))
    return out


# --- a problem read by scrolling: the frames are joined into one page ---
scrolled = [page(0)] * 2 + [page(o) for o in (120, 240, 360, 480)] + [page(480)] * 3
sent = run(scrolled)
joined = [m for m in sent if m.get("extra")]
check("a problem read by scrolling is sent joined into one page", bool(joined),
      f"{len(sent)} sent, {len(joined)} of them joined")
if joined:
    tall = max(Image.open(io.BytesIO(base64.b64decode(e))).size[1] for e in joined[-1]["extra"])
    check("the joined page is taller than the screen", tall > 900, f"{tall}px")

# --- typing in the editor is not a scroll ---
typing = [page(0, editor_line=i) for i in range(8)]
sent = run(typing)
check("typing in the editor is not a scroll", not any(m.get("extra") for m in sent),
      f"{sum(1 for m in sent if m.get('extra'))} joined")

# --- a still screen is sent once, not over and over ---
still = [page(0)] * 8
sent = run(still)
check("a still screen is sent once", len(sent) <= 2, f"{len(sent)} sent")

# --- the panel's own stitch switch still works on its own ---
sent = run([page(0)] * 2 + [page(o) for o in (150, 300)] + [page(300)] * 4, stitch=True)
check("joining switched on in the panel still works", any(m.get("extra") for m in sent),
      f"{len(sent)} sent, {sum(1 for m in sent if m.get('extra'))} of them joined")

# ---- ending it from outside: ./sidenote capture-stop asks through the server, so the program
# ends itself and the tray icon goes with it. Killing it leaves the icon behind, and the tray
# library answers a window-close message with nothing at all (pystray 0.19.5).
import capture                                 # noqa: E402

real = capture.Sender.__new__(capture.Sender)
real.wants = {"screen": True, "audio": True, "stitch": False, "monitor": 1}
real.told = threading.Event()
real.quit_asked = False
real._on_message('{"type": "control", "screen": false}')
check("a control message only flips the switch", real.wants["screen"] is False and not real.quit_asked,
      f"{real.wants['screen']} {real.quit_asked}")
real._on_message('{"type": "quit"}')
check("a quit message gets the program ready to end", real.quit_asked is True, str(real.quit_asked))
real.quit_asked = False
real._on_message('not json')
real._on_message('{"type": "other"}')
check("a message it does not know does not end it", real.quit_asked is False, str(real.quit_asked))
# Join scrolled screens switched from the panel is said by the panel's name for it, in English too ("scroll stitching")
lang, capture.LANG = capture.LANG, "en"
with redirect_stdout(io.StringIO()) as out:
    real._on_message('{"type": "control", "stitch": true}')
capture.LANG = lang
check("Join scrolled screens switched from the panel is said by the panel's name for it", "Join scrolled screens on (from the panel)" in out.getvalue(),
      out.getvalue())

# Under the desktop app (SIDENOTE_SUPERVISED) there is no ./sidenote to name: a quit or a restart through the server comes
# from the app ending or from the API there, and the lines said ./sidenote capture-stop and capture-restart all the same
said = {}
for kind, message in (("quit", '{"type": "quit"}'), ("restart", '{"type": "restart"}')):
    for app in (False, True):
        os.environ.pop("SIDENOTE_SUPERVISED", None)
        if app:
            os.environ["SIDENOTE_SUPERVISED"] = "1"
        real.quit_asked = real.restart_asked = False
        real.taken_over = False
        with redirect_stdout(io.StringIO()) as out:
            real._on_message(message)
        said[(kind, app)] = out.getvalue()
os.environ.pop("SIDENOTE_SUPERVISED", None)
check("a quit or a restart through the server names ./sidenote where it is run, and not under the desktop app",
      "./sidenote capture-stop" in said[("quit", False)] and "./sidenote capture-restart" in said[("restart", False)]
      and not any("./sidenote" in said[(k, True)] for k in ("quit", "restart")) and all(said.values()), said)

# The panel's All monitors is monitor 0 to mss, and the program said "monitor 0" for it
with redirect_stdout(io.StringIO()) as out:
    real._on_message('{"type": "control", "monitor": 0}')
    real._on_message('{"type": "control", "monitor": 2}')
check("All monitors chosen in the panel is said by its name, another monitor by its number",
      capture.t("all monitors (from the panel)") in out.getvalue() and capture.t("monitor {n} (from the panel)", n=2) in out.getvalue()
      and capture.t("monitor {n} (from the panel)", n=0) not in out.getvalue(), out.getvalue())
real.wants["monitor"] = 1

# What the server sends that is JSON but no object (a list, a number, a string): read as a message, it raised in the reading
# thread, which ended there. What the server said after it was never taken, nothing answered its pings, and the socket was
# left open with nothing reading it. And a socket whose reading ends (a frame the library will not take) is closed.
from websockets.sync.server import serve      # noqa: E402  (a package of the server's: server/requirements.txt)


class Peer:
    """The server's side of one connection, run in a thread: it sends `script` after the hello, and notes the close."""

    def __init__(self, script):
        self.script, self.sent, self.closed = script, threading.Event(), threading.Event()
        self.server = serve(self.handle, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}/ingest"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def handle(self, ws):
        ws.recv()                                 # the program's hello
        for raw, text in self.script:
            ws.send(raw, text=text)
        self.sent.set()
        try:
            while True:
                ws.recv(timeout=30)               # until the program closes it, or this suite lets it go below
        except TimeoutError:
            return
        except Exception:
            self.closed.set()

    def end(self, held):
        """The program's socket shut from this side, whatever the program did with it, and the server closed: its
        connection's thread is no daemon, and one left waiting would keep this suite from ending."""
        if held is not None:
            held.abort()                          # wakes a read still waiting on it
            held.shutdown()
        self.server.shutdown()


def wait(cond, limit=5.0):
    end = time.time() + limit
    while time.time() < end and not cond():
        time.sleep(0.05)
    return cond()


peer = Peer([(raw, True) for raw in ("[1, 2]", "42", '"text"', "null", '{"type": "control", "screen": false}')])
prog = capture.Sender(peer.url)
with redirect_stdout(io.StringIO()):
    prog.keepalive()                              # connects, says its hello, and starts reading
    held = prog._ws                               # the socket it read, for the end below
    taken = peer.sent.wait(5) and wait(lambda: prog.wants["screen"] is False)
check("JSON that is no object is let go: the reading goes on, and the message after it is taken",
      taken and prog.connected and not peer.closed.is_set(), (prog.wants["screen"], prog.connected))
peer.end(held)

peer = Peer([(b"\xff\xfe", True)])                # a text frame that is no UTF-8: the library raises as it reads it
prog = capture.Sender(peer.url)
with redirect_stdout(io.StringIO()):
    prog.keepalive()
    held = prog._ws
    ended = peer.sent.wait(5) and wait(lambda: not prog.connected)
    shut = peer.closed.wait(8)                    # the program's own close, before this suite shuts anything
check("a socket whose reading ended is closed, not left open with nothing reading it", ended and shut, (ended, shut))
peer.end(held)

# No server to send to: the loop must not grab and encode screens for nobody (a 4K PNG three
# times a second on the PC this tool is supposed to leave alone).
sent = run([page(0)] * 4, connected=False)
check("with no server the screen is not grabbed", not sent, f"{len(sent)} sent")
sent = run([page(0)] * 4, connected=True)
check("with a server it is grabbed as usual", bool(sent), f"{len(sent)} sent")

# The tray's "Open the panel" looks before it opens: without a server the browser would land on an
# error page that says nothing about this tool.
import http.server                               # noqa: E402

class _OK(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a):
        pass

srv = http.server.HTTPServer(("127.0.0.1", 0), _OK)
threading.Thread(target=srv.serve_forever, daemon=True).start()
check("the panel is opened when the server answers", capture.server_up(f"http://127.0.0.1:{srv.server_port}/") is True)
srv.shutdown()
check("and not when there is no server", capture.server_up("http://127.0.0.1:1/", timeout=0.5) is False)

# --- with the automatic join switched off, a scrolled screen is sent as it is ---
# The loop then never reads the row profile either, which is most of what a look costs after the
# grab (scratch/smoke/poll_cost.py), so the flag has to still send every screen without it.
off = run(scrolled, no_auto_stitch=True)
check("with automatic joining off a scrolled screen is sent a screen at a time",
      bool(off) and not any(m.get("extra") for m in off),
      f"{len(off)} sent, {sum(1 for m in off if m.get('extra'))} of them joined")


# --- what the loop says as it starts: All monitors by its name, and a monitor that is not there pointed to where the
# monitors are listed, which under the desktop app is the panel's Monitor: there is no ./sidenote there
def said_at_start(app=False, **wants):
    """The lines the loop printed over a few polls, under the desktop app (SIDENOTE_SUPERVISED) or not."""
    lines = []
    os.environ.pop("SIDENOTE_SUPERVISED", None)
    if app:
        os.environ["SIDENOTE_SUPERVISED"] = "1"
    capture.print = lambda *a, **k: lines.append(" ".join(str(x) for x in a))   # the program's own print, kept
    try:
        run([page(0)] * 3, **wants)
    finally:
        del capture.print
        os.environ.pop("SIDENOTE_SUPERVISED", None)
    return "\n".join(lines)


mode = capture.t("single-shot")
lines = said_at_start(monitor=0)
check("All monitors read: said by its name, not as monitor 0",
      capture.t("capturing all monitors: {w}x{h} ({mode})", w=1600, h=900, mode=mode) in lines
      and capture.t("capturing monitor {i}: {w}x{h} ({mode})", i=0, w=1600, h=900, mode=mode) not in lines, lines[:400])
lines = said_at_start(monitor=3)
check("a monitor that is not there: the first one read, and ./sidenote capture --list-monitors named where it runs",
      capture.t("monitor {asked} not found; {n} attached. Using 1.", asked=3, n=1) in lines
      and capture.t("./sidenote capture --list-monitors shows them.") in lines, lines[:400])
lines = said_at_start(app=True, monitor=3)
check("...and under the desktop app the panel's Monitor, with no ./sidenote named",
      capture.t("Monitor in Solver settings lists them.") in lines and "./sidenote" not in lines, lines[:400])

print(f"\n==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)
