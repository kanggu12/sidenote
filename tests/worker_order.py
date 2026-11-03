"""Who gets to run: the screen, or a problem heard through the microphone.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/worker_order.py

The analysis worker is the one place that decides what starts, what waits and what is cancelled,
and nothing was watching it. What the microphone hears is mostly whatever the PC is playing, and
anything long enough that the speaker then pauses is queued as a problem, so a video's dialogue
used to cancel the screen analysis the person at the PC was waiting for.

The real worker runs here, against stubs for everything it talks to: the pipeline's solve() waits
on an event this file sets, so an analysis can be held open and the next decision watched while it
is still running.
"""
import asyncio
import os
import sys
import time
import types
from pathlib import Path

os.environ.setdefault("SIDENOTE_ANALYZER", "mock")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repository: this file is in tests/

from server import app as A                      # noqa: E402
from server.pipeline import Outcome, Repeat      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok " if cond else "FAIL ") + name + (f"  - {detail}" if detail and not cond else ""))


class Detector:
    """Stands in for the change detector. `moved` is what the next moved_on() answers, `jump` what
    the next jumped() measures (the distance from the screen analysed last, over the whole screen)."""

    def __init__(self):
        self.moved = False
        self.jump = 255.0
        self.committed = []

    def is_new(self, frame):
        """New until it has been analysed, which is what commit() records. The real detector compares
        signatures and stops offering the screen it already answered about; a stub that always said
        yes would let the worker analyse one frame again as fast as its loop turns, which hides every
        gate the loop has."""
        return all(frame is not f for f in self.committed)

    def moved_on(self, old, new):  # "a clearly different screen", set by each check
        return self.moved

    def jumped(self, frame):       # "the screen changed wholesale", set by each check
        return self.jump

    def commit(self, frame):
        self.committed.append(frame)

    def set_region(self, region):
        pass


class Pipe:
    """Stands in for the pipeline. solve() hangs until `release` is set, so an analysis can be held
    open while the worker's next decision is watched."""

    def __init__(self):
        self.release = asyncio.Event()
        self.started = []          # (seq, voice) for every solve that was entered
        self.sigs = []             # the signature of the frame each solve was given
        self.cancelled = []        # the ones that were cancelled before they answered
        self.brake = ""            # what auto_blocked() says
        self.answer = "TYPE: math\n답"   # what solve() comes back with; "TYPE: none" = nothing to solve
        self.spend = types.SimpleNamespace(asked=lambda: None)

    def ready(self):
        return True

    def auto_blocked(self):
        return self.brake

    def verifying(self, result):
        return False

    async def say_brake(self, why):
        pass

    async def solve(self, seq, frame, transcript, voice, on_delta, by_user=False):
        self.started.append((seq, bool(voice)))
        self.sigs.append(getattr(frame, "sig", None))
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.append((seq, bool(voice)))
            raise
        return Outcome(text=self.answer, model="mock", usage=None, cost_usd=0.0, engine="local")


def speak(text="이 문제 좀 풀어 줘"):
    """What the transcriber would have left behind: recent_speech() reads these, and an empty one
    makes the worker start a *screen* analysis from the voice branch, which looks like a pass."""
    now = time.time()
    A.STATE.utterances.append({"start": 0.0, "end": 1.0, "text": text, "ts": now})


def frame(ts, sig):
    """A frame the worker will accept. Only the fields it reads are filled in."""
    return A.Frame(model_b64="", thumb_url="", sig=sig, ts=ts, width=1920, height=1080)


def push(sig, driving=False, after=None):
    """A frame arriving, as the ingest path leaves it: the frame itself and the stamps the worker
    reads to tell whether the screen has come to rest, and whether it was being driven before it.

    `driving` stamps it now, so the screen counts as still being driven and the settle holds.
    Without it the stamp is a minute old: the screen came to rest long ago, which is the state every
    check here but the settle ones is about.
    `after` is how long the screen was calm before this frame. Left out, there is no frame before
    this one at all, which reads as calm."""
    A.STATE.latest_frame = frame(time.time(), sig)
    now = time.time() if driving else time.time() - 60
    A.STATE.prev_frame_ts = (now - after) if after is not None else 0.0
    A.STATE.last_frame_ts = now


def knobs(**kw):
    """Set config values for one check and give back what they were, so the next check is not run
    against the one before's settings. The real defaults are in server/config.py; what is set here
    is only ever a shorter version of the same thing, because a check that waited the real 15 s
    would not be run."""
    was = {k: getattr(A.CONFIG, k) for k in kw}
    for k, v in kw.items():
        setattr(A.CONFIG, k, v)
    return was


def patch():
    """Everything the worker talks to besides the pipeline and the detector."""
    A.broadcast = lambda msg: asyncio.sleep(0)       # awaitable, and says nothing to anybody
    A.telemetry.event = lambda *a, **k: None
    A.note_success = lambda *a, **k: asyncio.sleep(0)
    A.note_sent = lambda *a, **k: None
    A.usage_message = lambda: {"type": "usage"}
    A.watch_region = lambda *a, **k: None
    A.checkable = lambda *a, **k: False              # no code check in this harness
    A.cancel_check = A.cancel_verify = A.cancel_retry = lambda: None


async def start_worker(pipe, det):
    """The real worker, with the stubs in place and the state it reads reset."""
    A.PIPELINE = pipe
    A.STATE.__init__()                 # a clean state for each check
    A.STATE.screen_on = True
    app = types.SimpleNamespace(state=types.SimpleNamespace(transcriber=None, detector=det))
    task = asyncio.create_task(A.analysis_worker(app))
    await asyncio.sleep(0.25)          # the loop ticks every 0.1 s
    return task


async def stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def case_voice_does_not_cancel_screen():
    """A screen analysis is running and something is heard: the screen is not interrupted."""
    pipe, det = Pipe(), Detector()
    task = await start_worker(pipe, det)
    push(b"a")
    await asyncio.sleep(0.4)
    check("a screen analysis starts", pipe.started == [(1, False)], f"{pipe.started}")

    speak(); A.STATE.voice_pending = True   # the microphone heard a whole utterance
    await asyncio.sleep(0.5)
    check("a spoken problem does not cancel the running screen analysis", pipe.cancelled == [],
          f"cancelled {pipe.cancelled}")
    check("and does not start beside it", len(pipe.started) == 1, f"{pipe.started}")
    check("the spoken problem is kept, not dropped", A.STATE.voice_pending is True)

    pipe.release.set()                 # the screen answer is written
    await asyncio.sleep(0.5)
    check("the spoken problem runs once the screen answer is in",
          any(v for _, v in pipe.started), f"{pipe.started}")
    await stop(task)


async def case_screen_takes_over_from_voice():
    """A spoken problem is running and the screen has clearly moved on: the screen takes over."""
    pipe, det = Pipe(), Detector()
    task = await start_worker(pipe, det)
    push(b"a")
    speak(); A.STATE.voice_pending = True
    await asyncio.sleep(0.4)
    check("the spoken problem starts when nothing else runs", pipe.started == [(1, True)], f"{pipe.started}")

    det.moved = False                  # the same screen: the spoken problem is left alone
    push(b"a2")
    await asyncio.sleep(0.4)
    check("a screen that has not moved on leaves it alone", pipe.cancelled == [], f"{pipe.cancelled}")

    det.moved = True                   # a clearly different screen
    push(b"b")
    await asyncio.sleep(0.4)
    check("a clearly different screen takes over from it", pipe.cancelled == [(1, True)], f"{pipe.cancelled}")
    await stop(task)


async def case_brake_starts_nothing():
    """Claude alone and its spend brake holding: nothing is started, so nothing has to be refused."""
    pipe, det = Pipe(), Detector()
    pipe.brake = "연달아 6번 풀 것이 없어 5분 동안 Claude 에 자동으로 보내지 않습니다"
    task = await start_worker(pipe, det)
    push(b"a")
    await asyncio.sleep(0.5)
    check("the brake starts no analysis at all", pipe.started == [], f"{pipe.started}")

    pipe.brake = ""                    # it lifts
    await asyncio.sleep(0.4)
    check("and the screen that was waiting is solved when it lifts", pipe.started == [(1, False)],
          f"{pipe.started}")
    await stop(task)


async def case_settle_waits_for_a_still_screen():
    """A screen still being driven is not asked about, and what finally goes is where it came to rest."""
    pipe, det = Pipe(), Detector()
    was = knobs(settle_sec=0.6, settle_max_sec=30)
    task = await start_worker(pipe, det)
    for i in range(6):                   # typing, scrolling: a frame every 0.12 s for 0.72 s
        push(f"drive{i}".encode(), driving=True)
        await asyncio.sleep(0.12)
    check("a screen still being driven is not asked about", pipe.started == [], f"{pipe.started}")

    push(b"rested", driving=True)        # the last frame of the burst, and then quiet
    await asyncio.sleep(1.0)
    check("it is asked about once the screen comes to rest", len(pipe.started) == 1, f"{pipe.started}")
    check("and about the screen it came to rest on, not the first of the burst",
          pipe.sigs == [b"rested"], f"{pipe.sigs}")
    knobs(**was)
    await stop(task)


async def case_the_settle_is_longer_mid_burst_than_after_a_calm_stretch():
    """The pause between two frames of a burst is not a stop to read; the first frame
    after a calm stretch is. 50 of 122 analyses in 14 minutes of real use were cancelled by the next
    frame, 37 of them within two seconds, because both waited the same short settle."""
    pipe, det = Pipe(), Detector()
    pipe.release.set()                   # every analysis answers at once
    was = knobs(settle_sec=0.3, settle_busy=1.2, busy_gap=4.0, settle_max_sec=30,
                min_analyze_interval=0.0)
    task = await start_worker(pipe, det)

    push(b"mid-burst", driving=True, after=0.5)   # the frame before it came half a second earlier
    await asyncio.sleep(0.7)             # past the short settle, not past the long one
    check("a frame in the middle of a burst is not asked about at the short settle",
          pipe.started == [], f"{pipe.started}")
    await asyncio.sleep(0.9)             # now it has rested the longer settle
    check("it goes once it has rested the longer settle", len(pipe.started) == 1, f"{pipe.started}")

    push(b"after-calm", driving=True, after=20.0)  # nothing had happened on the screen for 20 s
    await asyncio.sleep(0.55)            # past the short settle only
    check("a frame arriving on a calm screen goes at the short settle",
          len(pipe.started) == 2, f"{pipe.started}")
    knobs(**was)
    await stop(task)


async def case_a_screen_that_never_rests_is_still_asked_about():
    """A video in a corner: frames never stop coming, and the watching must not starve."""
    pipe, det = Pipe(), Detector()
    was = knobs(settle_sec=5.0, settle_max_sec=0.8)   # it will never be still for 5 s
    task = await start_worker(pipe, det)
    for i in range(4):
        push(f"video{i}".encode(), driving=True)
        await asyncio.sleep(0.15)
    check("still nothing while it has not waited long enough", pipe.started == [], f"{pipe.started}")
    for i in range(6):
        push(f"video{i + 4}".encode(), driving=True)
        await asyncio.sleep(0.15)
    check("a screen that never rests is asked about anyway", len(pipe.started) == 1, f"{pipe.started}")
    knobs(**was)
    await stop(task)


async def case_a_call_beside_a_still_screen_does_not_hold_the_start():
    """A video call in a corner: the capture program sends a frame each time it moves, and only a change anywhere
    else restarts the settle (stamp_frame), so the problem beside it goes at the usual settle, not after
    settle_max_sec. In a rehearsal, every analysis beside a call waited the full 8 s."""
    pipe, det = Pipe(), Detector()
    # settle_busy the same as settle_sec: the burst below would otherwise wait the longer settle, another check's job
    was = knobs(settle_sec=0.4, settle_busy=0.4, settle_max_sec=30, min_analyze_interval=0.0)
    task = await start_worker(pipe, det)
    problem = frame(time.time(), b"problem")
    A.STATE.latest_frame = problem
    A.stamp_frame(True)                          # the problem shows: the screen changed
    for i in range(8):                           # the call goes on: a frame every 0.15 s, nothing else moving
        await asyncio.sleep(0.15)
        # the same screen to the change detector (what the stub tells by identity; ChangeDetector's own mask is
        # checked in agent_first.py), and to the ingest a frame that changed nothing but the call
        A.STATE.latest_frame = problem
        A.stamp_frame(False)
    check("frames that moved only the call do not hold the analysis back", len(pipe.started) == 1,
          f"{pipe.started}")
    check("the screen card still sees every frame", time.time() - A.STATE.last_seen_ts < 0.3
          and time.time() - A.STATE.last_frame_ts > 1.0,
          f"seen {time.time() - A.STATE.last_seen_ts:.2f}s ago, changed {time.time() - A.STATE.last_frame_ts:.2f}s ago")
    pipe.release.set()
    await asyncio.sleep(0.1)
    for i in range(4):                           # now the screen is driven: each frame a change
        A.STATE.latest_frame = frame(time.time(), b"driven %d" % i)
        A.stamp_frame(True)
        await asyncio.sleep(0.15)
    check("a screen being driven still waits for its rest", len(pipe.started) == 1, f"{pipe.started}")
    await asyncio.sleep(0.6)
    check("and goes once it has rested", len(pipe.started) == 2, f"{pipe.started}")
    knobs(**was)
    await stop(task)


async def case_quiet_after_a_run_of_empty_answers():
    """Every answer found nothing: a small change waits, a wholesale one does not, a question ends it."""
    pipe, det = Pipe(), Detector()
    pipe.answer = "TYPE: none"           # nothing to solve, over and over
    pipe.release.set()                   # every analysis answers at once
    was = knobs(quiet_after=3, quiet_sec=3.0, min_analyze_interval=0.0, settle_sec=0.0)
    task = await start_worker(pipe, det)
    det.jump = 0.1                       # a small change: typing on the same page
    for i in range(4):                   # four empty answers, which is past quiet_after
        push(f"same{i}".encode())
        await asyncio.sleep(0.25)
    ran = len(pipe.started)
    check("the run of empty answers is counted", A.STATE.empty_run >= 3, f"empty_run {A.STATE.empty_run}")

    push(b"same9")                       # another small change, while the watching is quiet
    await asyncio.sleep(0.6)
    check("a small change waits while the watching is quiet", len(pipe.started) == ran,
          f"{ran} -> {len(pipe.started)}")

    det.jump = 1.0                       # another window, another page
    push(b"elsewhere")
    await asyncio.sleep(0.5)
    check("a wholesale change is not held back", len(pipe.started) == ran + 1,
          f"{ran} -> {len(pipe.started)}")

    det.jump = 0.1                       # back to small changes, and a question comes
    ran = len(pipe.started)
    A.user_asked()
    check("a question ends the run", A.STATE.empty_run == 0, f"empty_run {A.STATE.empty_run}")
    push(b"same10")
    await asyncio.sleep(0.5)
    check("and a small change is looked at again at once", len(pipe.started) == ran + 1,
          f"{ran} -> {len(pipe.started)}")
    knobs(**was)
    await stop(task)


async def until(cond, seconds=6.0):
    """Wait for something the worker does in its own time."""
    end = time.time() + seconds
    while not cond() and time.time() < end:
        await asyncio.sleep(0.05)
    return cond()


async def case_an_answer_does_not_wait_for_its_picture():
    """An answer is done before its picture is kept, so a cancel cannot land between the two."""
    pipe, det = Pipe(), Detector()
    added = []

    def slow_add(*a, **k):          # the real one takes about 0.2 s; a cancel landing in it lost the finished answer
        time.sleep(0.8)
        added.append(a[0])
    pipe.recent = types.SimpleNamespace(add=slow_add, forget=lambda: added.clear())
    pipe.answer = "TYPE: math\n답"
    sent, real = [], A.broadcast

    async def listen(msg):
        sent.append(msg)
    A.broadcast = listen
    real_solve = pipe.solve

    async def solve(*a, **k):
        out = await real_solve(*a, **k)
        out.region = (0.1, 0.1, 0.5, 0.5)
        return out
    pipe.solve = solve
    pipe.release.set()
    task = await start_worker(pipe, det)
    push(b"a")
    done = await until(lambda: any(m.get("type") == "analysis_done" for m in sent))
    check("the answer is done while its picture is still being kept", done and not added, f"{done} {added}")
    await until(lambda: bool(added))
    check("and the picture is kept", added == [1], f"{added}")
    await stop(task)
    A.broadcast = real


async def case_a_problem_seen_again_is_the_one_asked_about():
    """A problem seen again makes its answer the one a question is about, not the newest."""
    pipe, det = Pipe(), Detector()
    pipe.release.set()
    pipe.recent = types.SimpleNamespace(add=lambda *a, **k: None, forget=lambda: None)
    real_solve = pipe.solve
    box = (0.2, 0.2, 0.6, 0.6)

    async def solve(seq, *a, **k):
        if len(pipe.started) == 2:    # the third screen: the first problem again
            pipe.started.append((seq, False))
            raise Repeat(1, box, 0.9)
        pipe.answer = f"TYPE: math\n답 {seq}"
        return await real_solve(seq, *a, **k)
    pipe.solve = solve
    task = await start_worker(pipe, det)
    push(b"a")
    await until(lambda: (A.STATE.last_result or {}).get("id") == 1)
    push(b"b")
    await until(lambda: (A.STATE.last_result or {}).get("id") == 2)
    check("the newest answer is the one asked about", A.STATE.last_result["id"] == 2)
    push(b"c")
    await until(lambda: (A.STATE.last_result or {}).get("id") == 1)
    last = A.STATE.last_result
    check("the first problem seen again: a question is about its answer", last["id"] == 1 and "답 1" in last["text"],
          str(last.get("id")))
    check("...read from the screen it stands on now", last["frame"] is not None and last["crop_box"] == box,
          str(last.get("crop_box")))
    check("...and a problem scrolled together continues it", A.STATE.screen_started == 1, str(A.STATE.screen_started))
    check("answers kept for that hold no screens", all(a["frame"] is None for a in A.STATE.answers.values()))
    await stop(task)


async def main():
    patch()
    for case in (case_voice_does_not_cancel_screen, case_screen_takes_over_from_voice,
                 case_brake_starts_nothing, case_settle_waits_for_a_still_screen,
                 case_the_settle_is_longer_mid_burst_than_after_a_calm_stretch,
                 case_a_screen_that_never_rests_is_still_asked_about, case_a_call_beside_a_still_screen_does_not_hold_the_start,
                 case_quiet_after_a_run_of_empty_answers, case_an_answer_does_not_wait_for_its_picture,
                 case_a_problem_seen_again_is_the_one_asked_about):
        print(case.__doc__.splitlines()[0])
        await case()
    print(f"\n  ==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
