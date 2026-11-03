"""The capture program's sound path, with a fake device and a socket that takes a second (as it does while the
screen thread holds the same lock): the device is read on time all the same, what cannot be sent in time is
dropped rather than held, and nothing goes out after sound is switched off. Before the sending moved off the
device thread, this probe measured a 1.05 s gap between reads and two reads in three seconds, which is what
makes a device with a one-second buffer drop what it recorded.
  python tests/audio_path.py [path to capture.py]"""
import importlib.util, queue, sys, threading, time, types
from pathlib import Path

# the capture program of this repository (this file is in tests/), or an older copy named on the command line
spec = importlib.util.spec_from_file_location(
    "cap", sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "client" / "capture.py"))
cap = importlib.util.module_from_spec(spec)
sys.modules["cap"] = cap
spec.loader.exec_module(cap)
OK, BAD = [], []


def check(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  {got}" if got and not cond else ""))


# a device that hands back one second of silence per read and counts how long between reads
class Rec:
    def __init__(self, gaps):
        self.gaps, self.last = gaps, None

    def record(self, numframes):
        now = time.monotonic()
        if self.last is not None:
            self.gaps.append(now - self.last)
        self.last = now
        time.sleep(0.05)   # the device's own second, shortened
        import numpy as np
        return np.zeros((numframes, 2), dtype="float32")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Mic:
    name = "fake speaker"

    def recorder(self, samplerate, channels, blocksize):
        return REC


class Slow:
    """A sender whose socket takes a second, as it does while the screen thread holds the lock."""

    def __init__(self):
        self.wants = {"audio": True}
        self.caps = {}
        self.sent = 0
        self.connected = True   # the real Sender has this: no socket until the server answers

    def send(self, message):
        time.sleep(1.0)
        self.sent += 1

    def set_caps(self, **caps):
        self.caps.update(caps)

    def keepalive(self):
        pass


gaps = []
REC = Rec(gaps)
cap.sc = types.SimpleNamespace()
sys.modules["soundcard"] = types.SimpleNamespace(default_speaker=lambda: Mic(),
                                                 get_microphone=lambda name, include_loopback: Mic())
cap.AUDIO_BUFFER_SEC = 0.05
cap.AUDIO_QUEUE_SEC = 0.15   # three reads may wait
sender = Slow()
stop = threading.Event()
t = threading.Thread(target=cap.audio_loop, args=(sender, stop, types.SimpleNamespace(audio_device=None)), daemon=True)
t.start()
time.sleep(3.0)
stop.set()
t.join(timeout=3)
worst = max(gaps) if gaps else 0.0
check("the device is read on time while a send is stuck", worst < 0.5, f"worst gap {worst:.2f}s of {len(gaps)} reads")
check("the device was read many times, not once per send", len(gaps) > sender.sent + 3,
      f"{len(gaps)} reads, {sender.sent} sent")
# sound switched off: what was recorded before it does not go out afterwards
sender2 = Slow()
sender2.send = lambda message: sender2.__dict__.__setitem__("sent", sender2.sent + 1)
stop2 = threading.Event()
REC.last = None
t2 = threading.Thread(target=cap.audio_loop, args=(sender2, stop2, types.SimpleNamespace(audio_device=None)),
                      daemon=True)
t2.start()
time.sleep(0.5)
sender2.wants["audio"] = False
time.sleep(0.3)
was = sender2.sent
time.sleep(0.5)
stop2.set()
t2.join(timeout=3)
check("nothing goes out after sound is switched off", sender2.sent == was, f"{was} then {sender2.sent}")

# no server: the device is not opened at all. The screen loop has always stopped grabbing when there
# is nothing to send to; this loop kept recording the speakers into a queue it then threw away, so a
# program left running after the server went down recorded for nothing.
cap.DOWN_POLL = 0.1          # the real one waits two seconds between looks for a server
sender3 = Slow()
sender3.send = lambda message: sender3.__dict__.__setitem__("sent", sender3.sent + 1)
sender3.connected = False
stop3 = threading.Event()
gaps.clear()
REC.last = None
t3 = threading.Thread(target=cap.audio_loop, args=(sender3, stop3, types.SimpleNamespace(audio_device=None)),
                      daemon=True)
t3.start()
time.sleep(0.8)
reads_down = len(gaps)
check("with no server the sound device is not read", reads_down == 0 and sender3.sent == 0,
      f"{reads_down} reads, {sender3.sent} sent")
sender3.connected = True     # the server came back
time.sleep(0.8)
stop3.set()
t3.join(timeout=3)
check("it is read again once the server is back", len(gaps) > 0, f"{len(gaps)} reads after it came back")

q: queue.Queue = queue.Queue(maxsize=2)
check("the oldest is dropped when the queue is full",
      cap.audio_offer(q, (1, b"a")) and cap.audio_offer(q, (1, b"b")) and not cap.audio_offer(q, (1, b"c"))
      and q.get()[1] == b"b" and q.get()[1] == b"c")
print(f"\n==== {len(OK)} of {len(OK) + len(BAD)} as expected")
if BAD:
    print("FAILURES: " + ", ".join(BAD))
sys.exit(1 if BAD else 0)   # tests/run.sh counts a suite by its exit status
