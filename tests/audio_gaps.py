"""The capture program's minute line about sound the device dropped says whether this program was behind.

soundcard's "data discontinuity in recording" says the device's buffer had a gap, not why. The line said
"(this program fell behind reading it)" every time. Measured on this PC (scratch/audio_probe/): a
recorder with the capture program's settings and nothing else to do was never more than 60 ms behind its 2 s
buffer and still got one, with the device position jumping 40 ms ahead. So the loop now measures how far behind
it was (the time since the device opened, less the sound read in that time) and says that instead.

A fake device here keeps time the way a real one does: sound is ready at the pace it is recorded, the buffer
holds AUDIO_BUFFER_SEC of it, and a reader away for longer loses the oldest and gets soundcard's warning. Cases:
a gap the device makes while the reader keeps up, a reader that stalls past the buffer, sound handed back ahead
of the clock (soundcard's made-up silence overlapping the sound after it), and a gap just before sound is
switched off, which used to wait for sound to be switched on again before it was said.
  python tests/audio_gaps.py [path to capture.py]"""
import importlib.util
import sys
import threading
import time
import types
import warnings
from pathlib import Path

import numpy as np

# the capture program of this repository (this file is in tests/), or an older copy named on the command line
spec = importlib.util.spec_from_file_location(
    "cap", sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "client" / "capture.py"))
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)
OK, BAD = [], []
SR = 16000


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  {got}" if got and not cond else ""))


lines = []
cap.print = lambda *a, **k: lines.append(" ".join(str(x) for x in a))   # the loop's own lines, collected


class Rec:
    """A loopback recorder that keeps a real device's time. `gap_at`: the read on which the device itself
    reports a gap while the reader is on time. `stall_at`/`stall`: the read before which the reader is away."""

    def __init__(self, blocksize, gap_at=0, stall_at=0, stall=0.0, ahead_at=0, ahead=0.0):
        self.buf = blocksize / SR                  # what the device holds, in seconds, as asked for
        self.gap_at, self.stall_at, self.stall, self.n = gap_at, stall_at, stall, 0
        # `ahead_at`/`ahead`: the read on which more sound comes back than the clock has run, as soundcard does
        # when the silence it made up for an idle speaker is followed by sound that overlaps it
        self.ahead_at, self.ahead = ahead_at, ahead
        self.flag_next = False                     # a loss happened: the next read meets the flagged packet

    def __enter__(self):
        self.t0, self.taken = time.perf_counter(), 0.0     # opened now; nothing read yet (in frames)
        return self

    def __exit__(self, *a):
        return False

    def record(self, numframes):
        self.n += 1
        if self.n == self.ahead_at:
            self.t0 -= self.ahead                  # from here on the device is that much ahead of the clock
        if self.n == self.stall_at:
            time.sleep(self.stall)                 # the reader is away; the device keeps recording
        now = time.perf_counter()
        recorded = (now - self.t0) * SR            # frames the device has recorded since it opened
        lost = recorded - self.taken > self.buf * SR
        if lost:                                   # more than it holds: what came after the buffer filled is gone
            self.taken = recorded - self.buf * SR
        ready = self.t0 + (self.taken + numframes) / SR
        if ready > now:
            time.sleep(ready - now)                # sound is handed over at the pace it is recorded
        self.taken += numframes
        if self.flag_next:                         # the packet WASAPI flagged after a loss comes after the sound
            warnings.warn("data discontinuity in recording", RuntimeWarning)   # it still held: a read later
            self.flag_next = False
        self.flag_next = self.flag_next or lost
        if self.n == self.gap_at:                  # a gap of the device's own while this reader is on time
            warnings.warn("data discontinuity in recording", RuntimeWarning)
        return np.zeros((numframes, 2), dtype="float32")


class Sender:
    def __init__(self):
        self.wants = {"audio": True}
        self.caps = {}
        self.connected = True

    def send(self, message):
        pass

    def set_caps(self, **caps):
        self.caps.update(caps)

    def keepalive(self):
        pass


def run(rec_kwargs, seconds, switch_off_at=None):
    """audio_loop against one fake device for `seconds`; the [audio] lines it said about dropped sound."""
    class Mic:
        name = "fake speaker"

        def recorder(self, samplerate, channels, blocksize):
            return Rec(blocksize, **rec_kwargs)

    sys.modules["soundcard"] = types.SimpleNamespace(default_speaker=lambda: Mic(),
                                                     get_microphone=lambda name, include_loopback: Mic())
    lines.clear()
    sender, stop = Sender(), threading.Event()
    t = threading.Thread(target=cap.audio_loop, args=(sender, stop, types.SimpleNamespace(audio_device=None)),
                         daemon=True)
    t.start()
    if switch_off_at is not None:
        time.sleep(switch_off_at)
        sender.wants["audio"] = False              # switched off in the panel
        time.sleep(seconds - switch_off_at)
    else:
        time.sleep(seconds)
    stop.set()
    t.join(timeout=3)
    return [x for x in lines if "dropped sound" in x]


cap.AUDIO_READ_SEC = 0.05      # one read: 800 frames
cap.AUDIO_BUFFER_SEC = 0.15    # the device holds three reads
cap.AUDIO_GAP_NOTE_SEC = 0.6   # the minute, shortened

said = run({"gap_at": 3}, 1.0)
check("a gap the device makes while this program keeps up is said", len(said) == 1, f"{said}")
check("... and is not blamed on this program falling behind",
      bool(said) and "fell" not in said[0] and "not lost by reading late" in said[0], f"{said}")

said = run({"stall_at": 4, "stall": 0.35}, 1.2)
check("a reader away longer than the buffer is said to have fallen behind",
      len(said) == 1 and "fell" in said[0], f"{said}")
try:
    away = float(said[0].split(" fell ")[1].split(" s ")[0]) if said else 0.0
except (IndexError, ValueError):
    away = 0.0
check("... by about as long as it was away (0.35 s, less one read at most)", 0.25 <= away <= 0.45, f"{said}")

cap.AUDIO_GAP_NOTE_SEC = 0.3   # the minute ends right after the late read, before the flagged packet is read
said = run({"stall_at": 4, "stall": 0.35}, 1.2)
check("a stall that ends just as the minute does is still said as falling behind",
      bool(said) and "fell" in said[0], f"{said}")

cap.AUDIO_GAP_NOTE_SEC = 0.6
said = run({"gap_at": 8, "ahead_at": 4, "ahead": 0.12}, 1.0)
check("sound that comes back ahead of the clock is not counted as falling behind",
      len(said) == 1 and "fell" not in said[0] and "not lost by reading late" in said[0], f"{said}")

cap.AUDIO_GAP_NOTE_SEC = 30.0  # the minute never comes: only switching off can say it
said = run({"gap_at": 3}, 1.0, switch_off_at=0.4)
check("a gap just before sound is switched off is said when it stops, not when it comes back",
      len(said) == 1, f"{said}")

print(f"\n==== {len(OK)} of {len(OK) + len(BAD)} as expected")
if BAD:
    print("FAILURES: " + ", ".join(BAD))
    sys.exit(1)
