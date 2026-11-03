"""Does the screen loop look less often once the screen stops changing, and come straight back?

    .venv/bin/python tests/poll_rate.py

The loop is the capture program's whole expense: one look at a 4K screen costs 174 ms (112 of it
the grab), so three a second is a third of a core, spent whether the screen holds a problem or the
same desktop as ten minutes ago. It now slows to STILL_PERIOD once the screen has not changed for
STILL_POLLS looks. The three things that must stay true are checked here against the real loop:
the rate does drop, a change still gets through and brings the rate back, and a scroll that starts
from a still screen is still joined into one page.

No Windows and no server: mss is replaced by a grabber that hands out prepared frames and writes
down when each look happened, and the sender collects what was sent.
"""
import base64
import io
import random
import sys
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))   # client/ of the repository
from PIL import Image, ImageDraw               # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {detail}" if detail else ""))


def page(offset=0, w=1600, h=900, shade=0):
    """A page of text that scrolls by `offset`; `shade` moves every pixel, which is a change."""
    img = Image.new("RGB", (w, h), (255 - shade, 255 - shade, 255 - shade))
    d = ImageDraw.Draw(img)
    for i in range(90):
        y = 20 + i * 28 - offset
        if -30 < y < h:
            rnd = random.Random(500 + i)
            x = 40
            for _ in range(rnd.randint(2, 7)):
                wl = rnd.randint(30, 150)
                if x + wl > w - 40:
                    break
                d.rectangle([x, y + rnd.randint(0, 4), x + wl, y + 14], fill=(rnd.randint(0, 90),) * 3)
                x += wl + rnd.randint(8, 24)
    return img


class Grab:
    def __init__(self, img):
        self.size = img.size
        self.bgra = img.convert("RGBA").tobytes("raw", "BGRA")


class Screen:
    """The screen the loop is looking at, and the time of every look it took.

    `show` changes what is there from now on, for the checks about the rate. `play` hands over a
    list that is consumed one frame per look instead, which is how a scroll has to be fed: driven
    by the wall clock, the same frame is seen several times in a row at full rate and the loop never
    sees the two moves in a row that a scroll is read from."""

    def __init__(self, img):
        self.img = img
        self.queue: list = []              # frames waiting to be handed out, one per look
        self.at: list[float] = []          # when each look happened
        self.lock = threading.Lock()

    def show(self, img):
        with self.lock:
            self.img, self.queue = img, []

    def play(self, frames):
        with self.lock:
            self.queue = list(frames)

    def looks_between(self, t0, t1):
        return len([t for t in self.at if t0 <= t < t1])


SCREEN: Screen | None = None


class FakeMSS:
    def __init__(self):
        self.monitors = [{"left": 0, "top": 0, "width": 1600, "height": 900},
                         {"left": 0, "top": 0, "width": 1600, "height": 900}]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def grab(self, mon):
        SCREEN.at.append(time.time())
        with SCREEN.lock:
            if SCREEN.queue:               # a frame per look, the way a real poll advances
                SCREEN.img = SCREEN.queue.pop(0)
            return Grab(SCREEN.img)


class FakeSender:
    def __init__(self):
        self.wants = {"screen": True, "audio": True, "monitor": 1, "stitch": False}
        self.epoch = 0
        self.connected = True
        self.sent = []

    def keepalive(self):
        pass

    def set_caps(self, **kw):
        pass

    def send(self, msg):
        self.sent.append(msg)


def start(first):
    """Start the real loop on a screen showing `first`. Returns (screen, sender, stop, thread)."""
    global SCREEN
    import capture
    capture.window_rects = lambda mon, limit=40: ([], [])
    capture._grabber = lambda: FakeMSS
    SCREEN = Screen(first)
    sender = FakeSender()
    stop = threading.Event()
    # fps=20 so a full-rate stretch is unmistakable next to STILL_PERIOD, and stable_polls=1 so a
    # changed screen is sent on the look after it changed, as it is on the real thing at 3 fps.
    args = types.SimpleNamespace(stable_polls=1, settle=0.3, threshold=0.1, fps=20.0, max_width=1600,
                                 monitor=None, stitch=None, once=False, no_auto_stitch=False, log="")
    t = threading.Thread(target=capture.screen_loop, args=(sender, stop, args), daemon=True)
    t.start()
    return SCREEN, sender, stop, t


def wait_for_looks(screen, n, timeout=25.0):
    """Wait until the loop has taken n looks (it slows down, so this is not a fixed sleep)."""
    end = time.time() + timeout
    while time.time() < end and len(screen.at) < n:
        time.sleep(0.02)
    return len(screen.at)


import capture                                 # noqa: E402  after the stubs are in place


print(f"STILL_POLLS={capture.STILL_POLLS} STILL_PERIOD={capture.STILL_PERIOD}s  (test runs at 20 fps)")

# ---------------------------------------------------------------- it slows down on a still screen
still, changed = page(0), page(0, shade=60)
screen, sender, stop, t = start(still)
# Let it get past the point where it should slow down, then watch a 2.5 s stretch.
took = wait_for_looks(screen, capture.STILL_POLLS + 3)
check(f"a still screen is looked at at the full rate for its first {capture.STILL_POLLS} looks", took >= capture.STILL_POLLS + 3,
      f"{took} looks")
t0 = time.time()
time.sleep(2.5)
slow_looks = screen.looks_between(t0, time.time())
# At 20 fps a 2.5 s stretch is ~50 looks; at STILL_PERIOD it is 2 or 3.
expect = 2.5 / capture.STILL_PERIOD
check("a screen that does not change is looked at slowly", slow_looks <= expect + 2,
      f"{slow_looks} looks in 2.5 s (about {expect:.0f} at the slow rate, 50 at the full rate)")

# ---------------------------------------------------------------- a change still gets through
sent_before = len(sender.sent)
screen.show(changed)
t1 = time.time()
time.sleep(0.2 + capture.STILL_PERIOD)          # the look that notices it is up to STILL_PERIOD away
time.sleep(1.0)                                 # and then a second at full rate
fast_looks = screen.looks_between(t1 + capture.STILL_PERIOD + 0.2, time.time())
check("a change brings the full rate back", fast_looks >= 10,
      f"{fast_looks} looks in the second after the change (20 at the full rate, 1 at the slow one)")
check("a screen that changed while it was looked at slowly is sent", len(sender.sent) > sent_before,
      f"{len(sender.sent) - sent_before} sent")
stop.set()
t.join(timeout=3)

# ---------------------------------------------------------------- a scroll from a still screen
# The screen is left still long enough to slow down, then scrolled. The join must still happen: the
# look that notices the scroll is not read as one (rows a whole wait apart are not a shift anyone
# can line up), and the looks after it are back at full rate and find it. One frame per look, as a
# real poll advances: this is the part a wall-clock test got wrong and called a failure.
screen, sender, stop, t = start(page(0))
wait_for_looks(screen, capture.STILL_POLLS + 3)
time.sleep(capture.STILL_PERIOD * 2)             # it is looking slowly now
screen.play([page(o) for o in (120, 240, 360, 480, 600)] + [page(600)] * 6)
wait_for_looks(screen, len(screen.at) + 14)
time.sleep(0.6)
stop.set()
t.join(timeout=3)
joined = [m for m in sender.sent if m.get("extra")]
check("a scroll of a screen looked at slowly is still joined into one page", bool(joined),
      f"{len(sender.sent)} sent, {len(joined)} of them joined")
if joined:
    tall = max(Image.open(io.BytesIO(base64.b64decode(e))).size[1] for e in joined[-1]["extra"])
    check("the joined page is taller than the screen", tall > 900, f"{tall}px")

print(f"\n{len(PASS)} ok, {len(FAIL)} FAIL")
for f in FAIL:
    print(f"  FAIL {f}")
sys.exit(1 if FAIL else 0)
