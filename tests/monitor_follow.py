"""Follow the changing screen: with several monitors, the capture program reads the one where a new screen came to rest.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/monitor_follow.py [path to capture.py]

Checked here, on screens drawn here (no monitor, no Windows): what counts as a new screen (another page, the next slide)
and what does not (a notification, a chat that takes a message, lines typed), a 4K monitor read shrunk with the same
answers; the rules of ScreenFollow, fed signatures
and times (a slide change moves the reading once it rests, a video never does, the hold after a move, the way back to
the chosen monitor, a new screen on the monitor read keeping it there, one monitor and all of them as one doing nothing,
the switch turned off going back at once, a monitor with a window of Skip windows on it left alone, a scrolled problem
being joined holding the reading); the screen loop on two made-up monitors (none looked at with the switch off, the move
and its one line, the screen of the monitor moved to sent, the way back, the switch off, a window of Skip windows, this
tool's panel on the other monitor); the control message the program takes; and the server's half: the setting, the
control message, `following` in caps as far as the panel and the API, and a drawn region cleared when the monitor read
changes by itself.
"""
import base64
import importlib.util
import io
import json
import os
import random
import sys
import tempfile
import threading
import time
import types
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_SEARCH_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-follow-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_LANG="ko")
ROOT = Path(__file__).resolve().parents[1]                     # the repository: this file is in tests/
CAPTURE = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "client" / "capture.py")
spec = importlib.util.spec_from_file_location("cap_follow", CAPTURE)   # the capture program, or an older copy named
cap = importlib.util.module_from_spec(spec)
sys.modules["cap_follow"] = cap
spec.loader.exec_module(cap)

from PIL import Image, ImageDraw         # noqa: E402

OK, BAD = [], []


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"  {'ok' if cond else 'FAIL'} {name}" + (f": {got}" if got != "" and not cond else ""), flush=True)


def has(name: str) -> bool:
    """Whether the program loaded has this part: an older copy has none of them, and each check that needs one fails."""
    return hasattr(cap, name)


# ---------------------------------------------------------------- screens drawn here
W, H = 1600, 900


def words(d, rnd, x0, y, x1, h, shade):
    """A line of words as dark bars, which is how text reads at the signature's size."""
    x = x0
    while True:
        wide = rnd.randint(30, 140)
        if x + wide > x1:
            return
        d.rectangle([x, y, x + wide, y + h], fill=shade)
        x += wide + rnd.randint(10, 22)


def page(seed):
    """A page of text under a browser's bar: some thirty lines down the screen, its words its own."""
    img = Image.new("RGB", (W, H), "white")
    d, rnd = ImageDraw.Draw(img), random.Random(seed)
    d.rectangle([0, 0, W, 50], fill=(222, 225, 230))
    for i in range(28):
        words(d, rnd, 60, 80 + i * 28, rnd.randint(700, 1500), 12, (40, 40, 40))
    return img


def slide(i):
    """A deck's page: the same frame on each (a bar, a logo, the page number), its title and bullets its own."""
    img = Image.new("RGB", (W, H), (250, 250, 248))
    d, rnd = ImageDraw.Draw(img), random.Random(100 + i)
    d.rectangle([0, 0, W, 90], fill=(28, 52, 96))
    d.ellipse([W - 120, 20, W - 70, 70], fill=(240, 180, 40))
    words(d, rnd, 100, 150, 1100, 40, (20, 20, 20))
    for j in range(rnd.randint(3, 5)):
        y = 280 + j * 95
        d.ellipse([110, y + 10, 124, y + 24], fill=(28, 52, 96))
        words(d, rnd, 150, y, rnd.randint(900, 1450), 26, (40, 40, 40))
    d.rectangle([W - 90, H - 60, W - 60, H - 36], fill=(120, 120, 120))
    return img


def notified(img):
    """A notification in the corner, the size Windows draws one (364 x 104), dark, with three lines of words."""
    out = img.copy()
    d, rnd = ImageDraw.Draw(out), random.Random(7)
    x0, y0 = W - 376, H - 164
    d.rounded_rectangle([x0, y0, x0 + 364, y0 + 104], radius=8, fill=(43, 43, 43))
    d.rectangle([x0 + 14, y0 + 16, x0 + 46, y0 + 48], fill=(80, 140, 230))
    for k in range(3):
        words(d, rnd, x0 + 60, y0 + 16 + k * 26, x0 + 340, 10, (225, 225, 225))
    return out


MESSAGES = []
for _n in range(40):                     # one chat's messages: an avatar, a name, one to three lines each
    _rnd = random.Random(500 + _n)
    _lines = _rnd.choice((1, 1, 2, 3))
    _m = Image.new("RGB", (W - 260, 44 + 22 * _lines), "white")
    _d = ImageDraw.Draw(_m)
    _d.rectangle([16, 8, 52, 44], fill=tuple(_rnd.randint(60, 200) for _ in range(3)))
    words(_d, _rnd, 64, 8, 64 + _rnd.randint(80, 160), 12, (29, 28, 29))
    for _j in range(_lines):
        words(_d, _rnd, 64, 30 + 22 * _j, _rnd.randint(500, W - 300), 11, (50, 50, 50))
    MESSAGES.append(_m)


def chat(n):
    """A chat across the screen beside its channels, with its first n messages, the newest at the foot of the pane."""
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 260, H], fill=(63, 14, 64))
    for i in range(14):
        words(d, random.Random(i), 20, 90 + 30 * i, 220, 10, (220, 200, 220))
    pane = Image.new("RGB", (W - 260, H - 170), "white")
    y = pane.height
    for m in reversed(MESSAGES[:n]):
        y -= m.height
        if y + m.height < 0:
            break
        pane.paste(m, (0, y))
    img.paste(pane, (260, 80))
    d.rounded_rectangle([276, H - 76, W - 16, H - 30], radius=8, outline=(160, 160, 160))
    return img


def typed(img, lines):
    """Lines typed at the foot of what the screen shows."""
    out = img.copy()
    d, rnd = ImageDraw.Draw(out), random.Random(lines)
    for k in range(lines):
        words(d, rnd, 60, 700 + k * 20, 900, 10, (30, 30, 30))
    return out


def video(base, n):
    """A video playing in a box half the screen wide: shapes that are somewhere else at every look."""
    out = base.copy()
    d, rnd = ImageDraw.Draw(out), random.Random(9000 + n)
    x0, y0, x1, y1 = 760, 120, 1560, 570
    d.rectangle([x0, y0, x1, y1], fill=(60, 70, 90))
    for _ in range(40):
        cx, cy, r = rnd.randint(x0, x1), rnd.randint(y0, y1), rnd.randint(8, 60)
        d.ellipse([max(x0, cx - r), max(y0, cy - r), min(x1, cx + r), min(y1, cy + r)],
                  fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return out


class FakeGrab:
    """A grab as mss hands one over: the size, and the bytes in BGRA."""

    def __init__(self, img):
        self.size = img.size
        self.bgra = img.convert("RGBA").tobytes("raw", "BGRA")


def reading(img):
    """What a look takes of a screen, as the program takes it of every monitor: its signature and row profile."""
    return cap.follow_reading(FakeGrab(img), None)


def new(a, b) -> bool:
    (sa, pa), (sb, pb) = reading(a), reading(b)
    return bool(cap.new_screen(sa, sb, pa, pb))


def big(img):
    """The same screen on a 3840x2160 monitor."""
    return img.resize((3840, 2160), Image.LANCZOS)


# ---------------------------------------------------------------- what a new screen is
print("[what a new screen is]")
if has("new_screen") and has("follow_reading"):
    check("another page is a new screen", new(page(1), page(2)))
    check("the next slide is a new screen", new(slide(0), slide(1)))
    check("a notification in a corner is none, though it changes the screen as much as a new problem", not new(page(1), notified(page(1)))
          and cap.distance(reading(page(1))[0], reading(notified(page(1)))[0]) >= cap.FOLLOW_NEW,
          cap.distance(reading(page(1))[0], reading(notified(page(1)))[0]))
    check("...nor is its going", not new(notified(page(1)), page(1)))
    check("a chat that takes a message is none: what was there moved up", not any(new(chat(n), chat(n + 1)) for n in range(18, 24)),
          [new(chat(n), chat(n + 1)) for n in range(18, 24)])
    check("...nor two at once", not any(new(chat(n), chat(n + 2)) for n in range(18, 22)))
    check("lines typed are none", not new(page(1), typed(page(1), 3)))
    check("the same screen is none", not new(page(1), page(1)))
    made, whole = [], Image.fromarray       # the images a look builds, by their size
    Image.fromarray = lambda a, *more: (made.append(a.shape[:2]), whole(a, *more))[1]
    try:
        reading(big(page(1)))
    finally:
        Image.fromarray = whole
    check("a 3840x2160 monitor is read at 1280x720, never turned into an image at full size, with the same answers",
          made == [(720, 1280)] and new(big(page(1)), big(page(2))) and not new(big(page(1)), big(notified(page(1)))), made)
else:
    check("the program has new_screen and follow_reading, what a new screen is to following", False, "missing")


# ---------------------------------------------------------------- which monitor to read
print("\n[which monitor to read]")
STILL, LOOK = 0.1, 1.5   # --threshold's default, and how often a monitor is looked at


class Script:
    """A ScreenFollow fed looks at FOLLOW_LOOK_SEC's pace: each step a screen for each monitor, then which one it reads."""

    def __init__(self, on=True, chosen=1, count=2, hold=10.0):
        self.f = cap.ScreenFollow(STILL, hold=hold)
        self.f.setup(on, chosen, count)
        self.t = 0.0

    def step(self, **screens):
        for name, img in screens.items():
            k = int(name[1:])
            if img is None:
                self.f.look(k, None, None, self.t)       # not looked at: a window of Skip windows shows there
            else:
                self.f.look(k, *reading(img), self.t)
        got = self.f.pick(self.t)
        self.t += LOOK
        return got


if has("ScreenFollow"):
    s = Script()
    seen = [s.step(m1=page(1), m2=slide(0)), s.step(m1=page(1), m2=slide(0))]
    seen += [s.step(m1=page(1), m2=slide(1)), s.step(m1=page(1), m2=slide(1))]
    check("a slide changing on the other monitor: not while it moves, nor at its first look at rest", seen == [1, 1, 1, 1], seen)
    seen.append(s.step(m1=page(1), m2=slide(1)))
    check("...the reading moves there once it has rested two looks", seen[-1] == 2 and s.f.following == 2, (seen, s.f.following))

    s = Script()
    seen = [s.step(m1=page(1), m2=video(page(3), n)) for n in range(24)]
    check("a video playing on the other monitor never takes it: it never rests", set(seen) == {1}, seen)

    s = Script()
    for _ in range(2):
        s.step(m1=page(1), m2=page(3))
    seen = [s.step(m1=page(1), m2=notified(page(3))) for _ in range(5)] + [s.step(m1=page(1), m2=page(3)) for _ in range(4)]
    check("a notification on the other monitor, coming and going, does not take it", set(seen) == {1}, seen)
    s = Script()
    seen = [s.step(m1=page(1), m2=chat(n // 3 + 18)) for n in range(18)]
    check("a chat taking messages on the other monitor does not take it", set(seen) == {1}, seen)

    # the hold, then back to the chosen monitor the same way
    s = Script()
    for img in (slide(0), slide(0), slide(1), slide(1), slide(1)):
        moved = s.step(m1=page(1), m2=img)
    at = s.t - LOOK                                           # when it moved
    later = [s.step(m1=page(5), m2=slide(1)) for _ in range(4)]
    check("moved, then a new screen rests on the chosen monitor within the hold: it stays where it moved",
          moved == 2 and later == [2, 2, 2, 2], (moved, later))
    while s.t < at + 10.0:
        last = s.step(m1=page(5), m2=slide(1))
    back = s.step(m1=page(5), m2=slide(1))
    check("...and goes back to the chosen monitor once the hold is over, the chosen one counted as any other",
          last == 2 and back == 1 and s.f.following is None, (last, back, s.f.following))

    # a new screen on the one read since the other's change began keeps it
    s = Script()
    s.step(m1=page(1), m2=slide(0))
    s.step(m1=page(1), m2=slide(0))
    seen = [s.step(m1=page(2), m2=slide(1)) for _ in range(5)]
    check("a new screen resting on the monitor read as well as on the other: it stays on the one read", set(seen) == {1}, seen)

    for count, chosen, what in ((1, 1, "one monitor"), (2, 0, "all monitors as one picture (0)")):
        s = Script(chosen=chosen, count=count)
        seen = [s.step(m1=page(1), m2=img) for img in (slide(0), slide(0), slide(1), slide(1), slide(1), slide(1))]
        check(f"{what}: nothing to follow, the chosen one read", set(seen) == {chosen} and not s.f.active, (seen, s.f.active))

    s = Script()
    for img in (slide(0), slide(0), slide(1), slide(1), slide(1)):
        s.step(m1=page(1), m2=img)
    s.f.setup(False, 1, 2)
    check("the switch turned off: the chosen monitor read again at once, before any look", s.f.reading == 1 and s.f.following is None,
          (s.f.reading, s.f.following))
    s.f.setup(True, 1, 2)
    seen = [s.step(m1=page(1), m2=slide(1)) for _ in range(4)]
    check("...and on again: what rests on the other monitor then is no new screen", set(seen) == {1}, seen)

    s = Script()
    s.step(m1=page(1), m2=slide(0))
    s.step(m1=page(1), m2=slide(0))
    s.step(m1=page(1), m2=slide(1))
    s.step(m1=page(1), m2=slide(1))
    seen = [s.step(m1=page(1), m2=None)] + [s.step(m1=page(1), m2=slide(1)) for _ in range(4)]
    check("a monitor with a window of Skip windows on it is not moved to, and what it shows after is no new screen",
          set(seen) == {1}, seen)

    # Moved to the other monitor, then a window of Skip windows comes up there: the monitor read is not looked at, so a new
    # screen that rests on the chosen one takes the reading back within the hold, there being nothing to read where it is
    s = Script()
    for img in (slide(0), slide(0), slide(1), slide(1), slide(1)):
        moved = s.step(m1=page(1), m2=img)
    at = s.t - LOOK                                           # when it moved
    seen = [s.step(m1=page(5), m2=None) for _ in range(3)]    # changing, then at rest two looks, on the chosen monitor
    check("moved, then a window of Skip windows on the monitor read: a new screen resting on the chosen one takes the "
          "reading back, within the hold", moved == 2 and seen == [2, 2, 1] and s.t - LOOK < at + 10.0 and s.f.following is None,
          (moved, seen, s.t - LOOK - at))
    seen = [s.step(m1=page(5), m2=slide(1)) for _ in range(8)]   # past the hold of that move too
    check("...and the monitor left, once it shows again, does not take it back by what it shows then", set(seen) == {1}, seen)

    s = Script()
    for img in (slide(0), slide(0), slide(1), slide(1)):
        s.step(m1=page(1), m2=img)
    s.f.look(2, *reading(slide(1)), s.t)
    s.f.look(1, *reading(page(1)), s.t)
    s.f.stay(s.t)                                            # a scrolled problem being joined on the monitor read
    held = s.f.pick(s.t)
    s.t += LOOK
    after = [s.step(m1=page(1), m2=slide(1)) for _ in range(8)]
    check("a scrolled problem being joined holds the reading, and what rested elsewhere meanwhile is let go",
          held == 1 and set(after) == {1}, (held, after))
else:
    check("the program has ScreenFollow, which monitor to read while following", False, "missing")


# ---------------------------------------------------------------- the screen loop on two monitors
print("\n[the screen loop]")


class FakeMSS:
    """Two monitors side by side, each showing what SCREENS holds for it now; the grabs of each counted."""
    screens: dict = {}
    grabs: Counter = Counter()
    monitors = [{"left": 0, "top": 0, "width": 2 * W, "height": H},
                {"left": 0, "top": 0, "width": W, "height": H},
                {"left": W, "top": 0, "width": W, "height": H}]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def grab(self, mon):
        k = next(i for i, m in enumerate(FakeMSS.monitors) if m is mon)
        FakeMSS.grabs[k] += 1
        return FakeGrab(FakeMSS.screens[k])


class FakeSender:
    def __init__(self, **wants):
        self.wants = {"screen": True, "audio": True, "monitor": 1, "stitch": False, "monitor_follow": True, **wants}
        self.epoch, self.connected, self.sent, self.caps = 0, True, [], []

    def keepalive(self):
        pass

    def set_caps(self, **kw):
        self.caps.append(kw)

    def send(self, msg):
        self.sent.append(msg)

    def following(self):
        """What the server was last told of the monitor read (caps), or 'never'."""
        told = [c["following"] for c in self.caps if "following" in c]
        return told[-1] if told else "never"


def until(what, limit=15.0) -> bool:
    end = time.time() + limit
    while time.time() < end:
        if what():
            return True
        time.sleep(0.03)
    return False


def shown(msg):
    return Image.open(io.BytesIO(base64.b64decode(msg["data"]))).convert("RGB")


def loop(sender):
    """The screen loop on FakeMSS for `sender`, in a thread: (its stop, the thread, what it printed). What it prints goes
    to a print of the program's own, so this suite's lines, printed meanwhile, stay on its output."""
    stop, out = threading.Event(), io.StringIO()
    args = types.SimpleNamespace(stable_polls=1, settle=0.3, threshold=0.1, fps=20.0, max_width=W, monitor=None,
                                 stitch=None, once=False, no_auto_stitch=False, log="")
    cap.print = lambda *a, **k: out.write(" ".join(str(x) for x in a) + "\n")
    t = threading.Thread(target=cap.screen_loop, args=(sender, stop, args), daemon=True)
    t.start()
    return stop, t, out


def done(stop, t):
    stop.set()
    t.join(timeout=5)
    cap.__dict__.pop("print", None)   # the program's prints back to the console


if has("ScreenFollow") and has("watch_look"):
    cap._grabber = lambda: FakeMSS
    cap.window_rects = lambda mon, limit=40: ([], [])     # no window list here
    cap.FOLLOW_LOOK_SEC, cap.FOLLOW_HOLD_SEC = 0.15, 1.0   # its pace, quickened: the rules are the class's, checked above
    line = cap.t("a new screen came to rest on monitor {to}: reading it instead of monitor {at}", to=2, at=1)

    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    sender = FakeSender(monitor_follow=False)
    stop, t, out = loop(sender)
    time.sleep(1.0)
    FakeMSS.screens[2] = slide(1)
    time.sleep(1.5)
    done(stop, t)
    check("the switch off: only the chosen monitor is grabbed, the other never looked at",
          FakeMSS.grabs[1] > 5 and FakeMSS.grabs[2] == 0 and sender.following() in ("never", None), (dict(FakeMSS.grabs), sender.caps))

    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    sender = FakeSender()
    stop, t, out = loop(sender)
    time.sleep(0.8)
    looked, polls = FakeMSS.grabs[2], FakeMSS.grabs[1]       # the looks at each so far, taken together
    FakeMSS.screens[2] = slide(1)
    moved = until(lambda: sender.following() == 2)
    sent_from = len(sender.sent)
    got = until(lambda: any(cap.distance(reading(shown(m))[0], reading(slide(1))[0]) < 0.1 for m in sender.sent[sent_from:]), 5)
    check("on: the other monitor is looked at now and then, not at every poll", 2 <= looked <= polls // 2, (looked, polls))
    check("a new slide rests on the other monitor: the reading moves there and the server is told which (caps)", moved, sender.caps)
    check("...and the screen of the monitor moved to goes out", got, len(sender.sent))
    said = out.getvalue()
    check("...said in one line, with the two monitors' numbers and nothing of what they show", said.count(line) == 1, said[-600:])
    FakeMSS.screens[1] = page(7)
    back = until(lambda: sender.following() is None)
    check("a new screen rests on the chosen monitor after the hold: back there, and the server told", back, sender.caps)
    FakeMSS.screens[2] = slide(2)
    until(lambda: sender.following() == 2)
    sender.wants["monitor_follow"] = False
    off = until(lambda: sender.following() is None, 3)
    check("the switch turned off while it reads the other: the chosen monitor again at once, said so",
          off and cap.t("following is off: back to monitor {n}", n=1) in out.getvalue(), (sender.caps, out.getvalue()[-300:]))
    done(stop, t)

    # A window of Skip windows on the other monitor: that monitor is neither grabbed nor moved to
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    real_skip, real_front = cap.skip_now, cap.FrontWindow
    cap.skip_now = lambda front, words, mon: mon is FakeMSS.monitors[2]
    cap.FrontWindow = lambda: types.SimpleNamespace(limit="", why="")
    sender = FakeSender(skip_windows=["vault"])
    stop, t, out = loop(sender)
    time.sleep(0.6)
    FakeMSS.screens[2] = slide(1)
    polls = FakeMSS.grabs[1]
    time.sleep(2.0)
    polls = FakeMSS.grabs[1] - polls                         # the looks the loop took since the change
    done(stop, t)
    cap.skip_now, cap.FrontWindow = real_skip, real_front
    check("a window of Skip windows on the other monitor: nothing of it grabbed, and no move there in the looks since",
          polls >= 10 and FakeMSS.grabs[2] == 0 and sender.following() in ("never", None), (polls, dict(FakeMSS.grabs), sender.caps))

    # Moved to the other monitor, then a window of Skip windows comes up there, behind the window in front: nothing of that
    # monitor is grabbed or sent, and following goes on looking at the chosen one, so a new problem resting there takes the
    # reading back and goes out. The loop once stopped at the skip before following's look, and sent nothing for good.
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    shows = {"vault": False}                                 # whether the window shows on monitor 2 now
    real_skip, real_front = cap.skip_now, cap.FrontWindow
    cap.skip_now = lambda front, words, mon: shows["vault"] and mon is FakeMSS.monitors[2]
    cap.FrontWindow = lambda: types.SimpleNamespace(limit="", why="")
    sender = FakeSender(skip_windows=["vault"])
    stop, t, out = loop(sender)
    until(lambda: FakeMSS.grabs[2] >= 2)                     # the other monitor looked at, at rest on its first slide
    FakeMSS.screens[2] = slide(1)
    moved = until(lambda: sender.following() == 2)
    shows["vault"] = True                                    # a password manager comes up on monitor 2
    skipped = until(lambda: any(c.get("skipping") is True for c in sender.caps), 5)
    grabbed, sent_from = FakeMSS.grabs[2], len(sender.sent)
    FakeMSS.screens[1] = page(9)                             # the next problem, on the chosen monitor
    back = until(lambda: sender.following() is None, 8)
    got = until(lambda: any(cap.distance(reading(shown(m))[0], reading(page(9))[0]) < 0.1 for m in sender.sent[sent_from:]), 5)
    done(stop, t)
    cap.skip_now, cap.FrontWindow = real_skip, real_front
    said = out.getvalue()
    check("moved, then a window of Skip windows on the monitor read: a new problem resting on the chosen monitor takes the "
          "reading back, and the server is told", moved and skipped and back, (moved, skipped, sender.caps[-4:]))
    check("...and that problem goes out", got, len(sender.sent) - sent_from)
    check("...with nothing of the monitor showing the window grabbed meanwhile",
          FakeMSS.grabs[2] == grabbed and not any(cap.distance(reading(shown(m))[0], reading(slide(1))[0]) < 0.1
                                                  for m in sender.sent[sent_from:]), (FakeMSS.grabs[2] - grabbed,))
    check("...the move back said in one line, as any move is",
          said.count(cap.t("a new screen came to rest on monitor {to}: reading it instead of monitor {at}", to=1, at=2)) == 1, said[-600:])
    check("...and the skip's end as the reading moving off, not as the window gone, which still shows there",
          cap.t("Reading another monitor: capturing the screen again") in said
          and cap.t("The window to skip is no longer on screen: capturing the screen again") not in said, said[-600:])

    # Moved to the other monitor, then its grab fails (a UAC prompt, a monitor going away): the block starts again on the
    # chosen monitor, which is said in the log, once, as a move is, and the server told. It went back there without a word.
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    sender = FakeSender()
    stop, t, out = loop(sender)
    until(lambda: FakeMSS.grabs[2] >= 2)                     # the other monitor looked at, at rest on its first slide
    FakeMSS.screens[2] = slide(1)
    moved = until(lambda: sender.following() == 2)
    real_grab, fails = FakeMSS.grab, {"left": 1}

    def failing(self, mon):
        """The next grab of monitor 2, the one read, fails: following's looks at the others never grab it"""
        if mon is FakeMSS.monitors[2] and fails["left"]:
            fails["left"] -= 1
            raise OSError("the grab failed")
        return real_grab(self, mon)
    FakeMSS.grab = failing
    back = until(lambda: sender.following() is None, 8)
    again = until(lambda: FakeMSS.grabs[1] > 3 and cap.t("screen capture works again") in out.getvalue(), 8)
    FakeMSS.grab = real_grab
    done(stop, t)
    said = out.getvalue()
    check("moved, then the grab of the monitor read fails: back to the chosen monitor, said once in the log and told the server",
          moved and back and again and said.count(cap.t("the capture failed: back to monitor {n}", n=1)) == 1, (moved, back, said[-500:]))

    def halves(left, right):
        """A monitor whose left half shows one screen and its right half another."""
        out = left.copy()
        out.paste(right.crop((W // 2, 0, W, H)), (W // 2, 0))
        return out

    # This tool's panel on the right half of the other monitor, its answer being written: painted over before the monitor
    # is read, so what it writes is no new screen there
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: page(3)}, Counter()
    cap.window_rects = lambda mon, limit=40: (([[0.5, 0.0, 1.0, 1.0]], [0]) if mon is FakeMSS.monitors[2] else ([], []))
    sender = FakeSender()
    stop, t, out = loop(sender)
    time.sleep(0.6)
    FakeMSS.screens[2] = halves(page(3), slide(4))           # what the panel shows, wholly new
    looked = FakeMSS.grabs[2]
    time.sleep(2.0)
    looked = FakeMSS.grabs[2] - looked                       # the looks at that monitor since the change
    done(stop, t)
    cap.window_rects = lambda mon, limit=40: ([], [])
    check("this tool's panel on the other monitor, its words all new: painted over, so no move in the looks since",
          looked >= 4 and sender.following() in ("never", None), (looked, dict(FakeMSS.grabs), sender.caps))
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: page(3)}, Counter()
    sender = FakeSender()
    stop, t, out = loop(sender)
    time.sleep(0.6)
    FakeMSS.screens[2] = halves(page(3), slide(4))
    moved = until(lambda: sender.following() == 2, 10)
    done(stop, t)
    check("...where the same change, with no panel there, is a move", moved, sender.caps)

    # No window list to find this tool's panel by (off Windows and macOS): an answer written there would be a new screen to
    # move to, so nothing is followed, and the program says it cannot follow for the panel to grey the switch out
    cap.window_rects = lambda mon, limit=40: None
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    sender = FakeSender()
    stop, t, out = loop(sender)
    time.sleep(0.6)
    FakeMSS.screens[2] = slide(1)
    time.sleep(1.5)
    done(stop, t)
    cap.window_rects = lambda mon, limit=40: ([], [])
    told = [c["follow_ok"] for c in sender.caps if "follow_ok" in c]
    check("no window list to find this tool's panel by: the other monitor never looked at, and the program says it cannot follow",
          FakeMSS.grabs[1] > 5 and FakeMSS.grabs[2] == 0 and sender.following() in ("never", None) and told[-1:] == [False],
          (dict(FakeMSS.grabs), sender.caps))
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    sender = FakeSender()
    stop, t, out = loop(sender)
    until(lambda: any("follow_ok" in c for c in sender.caps), 3)
    done(stop, t)
    check("...where it can read the window list, it says it can", [c["follow_ok"] for c in sender.caps if "follow_ok" in c][-1:] == [True],
          sender.caps)

    # The panel's own Join scrolled screens joining a problem holds the reading, as the program's own join does
    real_stitcher = cap.ScrollStitcher

    class Joining(real_stitcher):
        """A join under way that does not end while this is looked at: a long problem scrolled slowly"""

        def feed(self, img, gl=None):
            return None

        def joining(self):
            return True

    cap.ScrollStitcher = Joining
    FakeMSS.screens, FakeMSS.grabs = {1: page(1), 2: slide(0)}, Counter()
    sender = FakeSender(stitch=True)
    stop, t, out = loop(sender)
    time.sleep(0.6)
    FakeMSS.screens[2] = slide(1)
    looked = FakeMSS.grabs[2]
    time.sleep(2.0)
    looked = FakeMSS.grabs[2] - looked
    done(stop, t)
    cap.ScrollStitcher = real_stitcher
    check("the panel's Join scrolled screens joining a problem: the reading stays where the join is",
          looked >= 4 and sender.following() in ("never", None), (looked, dict(FakeMSS.grabs), sender.caps))

    # A window of Skip windows that came up on a monitor while it was grabbed: that look is let go, unread
    asked = []

    def skip_once_grabbed(front, words, mon):
        asked.append(mon)
        return len(asked) > 1                                # none before the grab, one there once it was taken

    real_skip = cap.skip_now
    cap.skip_now = skip_once_grabbed
    FakeMSS.screens = {1: page(1), 2: slide(0)}
    got = cap.watch_look(FakeMSS(), FakeMSS.monitors[2], object(), ["vault"])
    cap.skip_now = real_skip
    check("a window of Skip windows that came up while a monitor was grabbed: the look let go, unread",
          got == (None, None) and len(asked) == 2, (got, len(asked)))
else:
    check("the screen loop follows the changing screen (ScreenFollow, watch_look)", False, "missing")


# ---------------------------------------------------------------- a join under way
print("\n[a join under way]")
st = cap.ScrollStitcher(1)
if hasattr(st, "joining"):
    states = [st.joining()]
    st.pending.append(None)                                  # a scroll seen, the scrolling part not yet sure
    states.append(st.joining())
    st.pending.clear()
    st.region, st.emitted = (0, 0, 10, 10), False            # a page grown by a scroll, not yet sent
    states.append(st.joining())
    st.emitted = True                                        # sent: nothing held until the next scroll
    states.append(st.joining())
    check("a join is under way while frames are held or a grown page is not yet sent", states == [False, True, True, False], states)
else:
    check("the stitcher says whether a join is under way (joining)", False, "missing")


# ---------------------------------------------------------------- the control message
print("\n[the control message]")
real = cap.Sender.__new__(cap.Sender)
real.wants = {"screen": True, "audio": True, "stitch": False, "monitor": 1}
real.told = threading.Event()
real.quit_asked = False
check("a program starts with it off, until the server says on", cap.Sender("ws://127.0.0.1:1/ingest").wants.get("monitor_follow") is False,
      cap.Sender("ws://127.0.0.1:1/ingest").wants)
with redirect_stdout(io.StringIO()) as said:
    real._on_message('{"type": "control", "monitor_follow": true}')
check("the control message's monitor_follow switches it on, said once",
      real.wants.get("monitor_follow") is True and cap.t("following the changing screen on (from the panel)") in said.getvalue(),
      (real.wants, said.getvalue()))
with redirect_stdout(io.StringIO()):
    real._on_message('{"type": "control", "screen": true}')
check("...a message without it (an older server's) leaves it as it is", real.wants.get("monitor_follow") is True, real.wants)
with redirect_stdout(io.StringIO()):
    real._on_message('{"type": "control", "monitor_follow": "no"}')
check("...a value that is not a yes or a no is not taken", real.wants.get("monitor_follow") is True, real.wants)
with redirect_stdout(io.StringIO()) as said:
    real._on_message('{"type": "control", "monitor_follow": false}')
check("...and false switches it off, said once", real.wants.get("monitor_follow") is False
      and cap.t("following the changing screen off (from the panel)") in said.getvalue(), (real.wants, said.getvalue()))


# ---------------------------------------------------------------- the server
print("\n[the server]")
sys.path.insert(0, str(ROOT))
from starlette.testclient import TestClient  # noqa: E402

import server.app as A  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

ORIGIN = {"origin": "http://127.0.0.1:8777"}


class Reader:
    """Every message a socket gets, read in a thread, so a wait that comes to nothing ends instead of hanging."""

    def __init__(self, ws):
        self.ws, self.msgs = ws, []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.msgs.append(json.loads(self.ws.receive_text()))
        except Exception:
            pass

    def wait(self, pred, timeout=8.0, after=0):
        end = time.time() + timeout
        while time.time() < end:
            for m in list(self.msgs[after:]):
                if pred(m):
                    return m
            time.sleep(0.05)
        return None


def caps_of(m):
    return m.get("type") == "capture" and m.get("caps") or {}


with TestClient(A.app, base_url="http://127.0.0.1:8777") as client:
    with client.websocket_connect("ws://127.0.0.1:8777/ingest") as ing, \
            client.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as pws:
        ing.send_text(json.dumps({"type": "hello", "info": "capture/win32", "screen": True, "audio": True, "no_audio": False,
                                  "monitor": 1, "monitors": [[3840, 2160], [1440, 2560]], "following": None, "flags": {}}))
        prog, panel = Reader(ing), Reader(pws)
        first = prog.wait(lambda m: m.get("type") == "control")
        check("the capture program is told on connect, off to begin with", bool(first) and first.get("monitor_follow") is False, first)
        meta = panel.wait(lambda m: m.get("type") == "settings" and "meta" in m)
        items = (meta or {}).get("meta", {}).get("items", [])
        keys = [i["key"] for i in items]
        item = next((i for i in items if i["key"] == "monitor_follow"), {})
        check("the panel gets the setting, a switch in Capture right after Monitor, off by default, in Korean",
              item.get("section") == "capture" and item.get("kind") == "bool" and item.get("default") is False
              and "monitor" in keys and keys.index("monitor_follow") == keys.index("monitor") + 1
              and item.get("label") == "바뀐 화면 따라가기" and "모니터" in item.get("help", ""), item)
        n = len(prog.msgs)
        pws.send_text(json.dumps({"type": "setting", "key": "monitor_follow", "value": True}))
        got = prog.wait(lambda m: m.get("type") == "control" and m.get("monitor_follow") is True, after=n)
        check("switched on in the panel, the program is told at once", bool(got), got)
        file = Path(os.environ["SIDENOTE_LOG_DIR"]) / ".settings.json"
        kept = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
        check("...and it is kept in .settings.json", kept.get("monitor_follow") is True, kept)
        status = client.get("/api/v1/status").json()["capture"]
        check("a program reading the chosen monitor says so from its hello: following is null", "following" in status.get("caps", {})
              and status["caps"]["following"] is None, status.get("caps"))
        m = len(panel.msgs)
        ing.send_text(json.dumps({"type": "caps", "following": 2}))
        seen = panel.wait(lambda x: caps_of(x).get("following") == 2, after=m)
        check("the program reads monitor 2 by following: the panel's capture message says it", bool(seen), seen)
        check("...and so do the API's status and /health", client.get("/api/v1/status").json()["capture"]["caps"].get("following") == 2
              and client.get("/health").json()["capture"]["caps"].get("following") == 2, client.get("/health").json()["capture"])
        told = []
        for value, want in ((False, False), (True, True), ("no", False), (1, False)):
            m = len(panel.msgs)
            ing.send_text(json.dumps({"type": "caps", "follow_ok": value}))
            seen = panel.wait(lambda x: x.get("type") == "capture" and caps_of(x).get("follow_ok") is want, after=m)
            told.append(bool(seen))
        check("whether the program can follow (follow_ok) reaches the panel, as a yes or a no whatever is sent", all(told), told)
        for value, why in (("2", "a string"), (True, "true"), (0, "0"), (65, "a number past any monitor"), ([2], "a list")):
            m = len(panel.msgs)
            ing.send_text(json.dumps({"type": "caps", "following": value}))
            seen = panel.wait(lambda x: x.get("type") == "capture" and "following" in (x.get("caps") or {}), after=m)
            check(f"...{why} is no monitor: null", bool(seen) and seen["caps"]["following"] is None, seen)
        # A drawn region belongs to the screen it was drawn on: a move off it clears it, said; a word that moves nothing keeps it
        pws.send_text(json.dumps({"type": "setting", "key": "roi_box", "value": [0.1, 0.1, 0.6, 0.6]}))
        panel.wait(lambda x: x.get("type") == "settings" and (x.get("values") or {}).get("roi_box"))
        m = len(panel.msgs)
        ing.send_text(json.dumps({"type": "caps", "following": None}))
        time.sleep(0.5)
        kept = SETTINGS.get("roi_box")                       # the program said again it reads the chosen monitor
        ing.send_text(json.dumps({"type": "caps", "following": 2}))
        note = panel.wait(lambda x: x.get("type") == "notice" and "영역 해제" in x.get("text", ""), after=m)
        check("a region drawn on the chosen monitor stays while the program reads it, and goes, said, once it moves to monitor 2",
              kept is not None and SETTINGS.get("roi_box") is None and bool(note)
              and note.get("text") == "모니터가 바뀌어 영역 해제 · 화면 전체를 봄", (kept, SETTINGS.get("roi_box"), note))
        n = len(prog.msgs)
        pws.send_text(json.dumps({"type": "settings_reset"}))
        got = prog.wait(lambda x: x.get("type") == "control" and x.get("monitor_follow") is False, after=n)
        check("Reset to defaults switches it off in the program too", bool(got), got)

print(f"\n==== {len(OK)} passed, {len(BAD)} failed ====")
sys.exit(1 if BAD else 0)
