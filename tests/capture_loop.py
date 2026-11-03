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
import sys
import threading
import time
import types
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

print(f"\n==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
sys.exit(1 if FAIL else 0)
