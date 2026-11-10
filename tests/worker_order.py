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
        self.wrote = ""            # the first words each solve writes as soon as it starts, "" for none (it is still reading)
        self.words = []            # what each solve was given to read
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
        self.words.append(transcript)
        try:
            if self.wrote:
                await on_delta(self.wrote)
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.append((seq, bool(voice)))
            raise
        return Outcome(text=self.answer, model="mock", usage=None, cost_usd=0.0, engine="local")


def speak(text="이 문제 좀 풀어 줘"):
    """What the transcriber would have left behind: the voice branch reads these, and starts nothing without them."""
    now = time.time()
    # A second of speech, half a second after the last: one run of speech, each at its own place in the sound
    at = A.STATE.utterances[-1]["end"] + 8000 if A.STATE.utterances else 0
    A.STATE.utterances.append({"start": at, "end": at + 16000, "text": text, "ts": now})


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


REAL_CANCEL_CHECK, REAL_CANCEL_VERIFY = A.cancel_check, A.cancel_verify   # before patch() stands them in


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


def said_to_panel():
    """What the worker tells the panel, kept to be read: what a panel draws both answers from."""
    msgs = []

    async def tell(msg):
        msgs.append(msg)
    A.broadcast = tell
    return msgs


async def next_answer(pipe, msgs, n):
    """Let the running one finish, until `n` answers have ended on the panel."""
    pipe.release.set()
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) >= n)
    pipe.release.clear()


async def case_nothing_written_yet_the_longer_version_replaces_it():
    """A spoken problem that has written nothing is still being read: the newer, longer version replaces it."""
    pipe, det = Pipe(), Detector()
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    speak("What does a write ahead log do"); A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    speak("and why is it faster than writing the table?"); A.STATE.voice_pending = True
    await asyncio.sleep(0.4)
    check("it is stopped", pipe.cancelled == [(1, True)], f"{pipe.cancelled}")
    check("...said as a newer one replacing it", [m["reason"] for m in msgs if m["type"] == "analysis_cancelled"] == ["voice"], f"{msgs}")
    check("...and the longer version runs, whole", pipe.words == ["What does a write ahead log do", "What does a write ahead log do and why is it faster than writing the table?"], f"{pipe.words}")
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_an_answer_being_written_is_let_finish():
    """A spoken problem that has written its first words finishes; the newer one waits for it, and the panel gets both."""
    pipe, det = Pipe(), Detector()
    pipe.wrote = "TYPE: essay\nANSWER: 첫 답"
    pipe.answer = "TYPE: essay\nANSWER: 첫 답\n풀이"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    speak("What does a write ahead log do?"); A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    check("the first starts", pipe.started == [(1, True)], f"{pipe.started}")
    speak("And what is a checkpoint?"); A.STATE.voice_pending = True
    await asyncio.sleep(0.5)
    check("a newer one does not stop an answer being written", pipe.cancelled == [], f"{pipe.cancelled}")
    check("...and does not start beside it", len(pipe.started) == 1, f"{pipe.started}")
    check("...and is kept waiting", A.STATE.voice_pending is True)
    speak("And what about a torn page?"); A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    check("a still newer one changes nothing while it runs", pipe.cancelled == [] and len(pipe.started) == 1, f"{pipe.started}")
    pipe.wrote = ""       # the next is still reading when the newest words come
    await next_answer(pipe, msgs, 1)
    await until(lambda: len(pipe.started) == 2)
    check("the answer ends", [m["id"] for m in msgs if m["type"] == "analysis_done"] == [1], f"{msgs}")
    check("...and one more starts: one waits, whatever was said meanwhile", pipe.started == [(1, True), (2, True)] and A.STATE.voice_pending is False, f"{pipe.started}")
    check("it reads what came after, and not what has its answer", pipe.words[1] == "And what is a checkpoint? And what about a torn page?", pipe.words[1])
    starts = [m for m in msgs if m["type"] == "analysis_start"]
    check("the panel's card shows the words that came after, the answered ones not again", starts[1]["transcript"] == "And what is a checkpoint? And what about a torn page?", f"{starts}")
    # A still newer one, while this second one has written nothing: it is replaced, and it is its words that are read
    speak("Is a checkpoint a full write?"); A.STATE.voice_pending = True
    await asyncio.sleep(0.4)
    check("a still newer one replaces the one that has written nothing", pipe.cancelled == [(2, True)] and pipe.started[-1] == (3, True), f"{pipe.cancelled} {pipe.started}")
    check("...with the words of both", pipe.words[2] == "And what is a checkpoint? And what about a torn page? Is a checkpoint a full write?", pipe.words[2])
    await next_answer(pipe, msgs, 2)
    await asyncio.sleep(0.3)
    check("both answers reached the panel, the first not cut", [m["id"] for m in msgs if m["type"] == "analysis_done"] == [1, 3], f"{msgs}")
    check("nothing is asked again with nothing new", len(pipe.started) == 3 and A.STATE.voice_pending is False, f"{pipe.started}")
    A.STATE.voice_pending = True   # a flag with nothing new behind it
    await asyncio.sleep(0.3)
    check("a flag with no new words starts nothing", len(pipe.started) == 3, f"{pipe.started}")
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_a_quizs_options_go_with_their_question():
    """The options of a quiz mean nothing alone: they go with the question read a sentence earlier, as one problem."""
    pipe, det = Pipe(), Detector()
    pipe.wrote = "TYPE: essay\nANSWER: 답"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    speak("Which of these is not a property of a B-tree?"); A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    speak("A, it stays balanced. B, every node has two children."); A.STATE.voice_pending = True
    await asyncio.sleep(0.2)
    await next_answer(pipe, msgs, 1)
    await until(lambda: len(pipe.started) == 2)
    check("they run with their question", pipe.words[1] == "Which of these is not a property of a B-tree? A, it stays balanced. B, every node has two children.", pipe.words[1])
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)
    q = {"start": 0, "end": 10, "text": "Q?"}

    def then(words):
        return [q, {"start": 20, "end": 30, "text": words}]
    for group, to, want in (([q], 0, "Q?"), ([q], 5, "Q?"), ([q], 10, ""), (then("And more."), 10, "And more."), (then("And more."), 0, "Q? And more."), (then("And more."), 30, ""),
                            ([], 10, ""), (then("Q?"), 10, "Q?")):
        check(f"to {to}: {[u['text'] for u in group]} reads {want!r}", A.after_the_answer(group, to) == want, A.after_the_answer(group, to))
    for words in ("일번, 연결 지향.", "1번 연결 지향", "1. 연결 지향", "첫 번째 보기는 해시입니다", "보기 1은 해시입니다", "① 연결 지향", "가. 연결 지향", "A, it stays balanced.", "A: it stays balanced.",
                  "A. it stays balanced.", "Option A is a hash.", "One, a hash. Two, a tree.", "하나, 해시. 둘, 트리."):
        check(f"options go with their question: {words!r}", A.after_the_answer(then(words), 10) == f"Q? {words}", A.after_the_answer(then(words), 10))
    for words in ("And when does it fail?", "그건 왜 그래요?", "So what is that?"):
        check(f"so does a question that leans on the one before it: {words!r}", A.after_the_answer(then(words), 10) == f"Q? {words}", A.after_the_answer(then(words), 10))
    for words in ("이번에는 다른 얘기입니다.", "A B-tree is balanced.", "보기에는 괜찮았어요.", "We had that problem last month, you know?", "And what is a checkpoint?", "1.5배 빨라졌어요.", "첫 번째로 재시작했어요.", "A, which is fine.", "Option one was too slow.", "One, we drained the node.", "First, we drained the node."):
        check(f"and what only looks like one does not: {words!r}", A.after_the_answer(then(words), 10) == words, A.after_the_answer(then(words), 10))


def sentence(text, after_seconds):
    """A sentence after a pause of `after_seconds`, to the sound's own clock."""
    at = A.STATE.utterances[-1]["end"] + int(after_seconds * 16000) if A.STATE.utterances else 0
    A.STATE.utterances.append({"start": at, "end": at + 16000, "text": text, "ts": time.time()})


async def case_a_place_in_the_sound_not_its_words():
    """What has its answer is known by where it was said: the same words said again are asked again, and an old sentence aging out
    of the run takes nothing else with it."""
    pipe, det = Pipe(), Detector()
    pipe.release.set()
    pipe.answer = "TYPE: essay\nANSWER: 답"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    sentence("GTID가 뭔가요?", 0); A.STATE.voice_pending = True
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) == 1)
    sentence("GTID가 뭔가요?", 600); A.STATE.voice_pending = True
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) == 2)
    check("the same words said again later are asked again", pipe.words == ["GTID가 뭔가요?", "GTID가 뭔가요?"], f"{pipe.words}")
    sentence("TCP 설명해 주세요", 600); A.STATE.voice_pending = True
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) == 3)
    sentence("TCP 설명해 주세요 그리고 UDP도요", 2); A.STATE.voice_pending = True
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) == 4)
    check("a new sentence that opens with the old one's words is read whole", pipe.words[-1] == "TCP 설명해 주세요 그리고 UDP도요", pipe.words[-1])
    # A run of speech longer than speech_context_sec: its first sentence ages out and the place still holds
    sentence("What does a write ahead log do?", 600); A.STATE.voice_pending = True
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) == 5)
    sentence("And what is a checkpoint?", 2); A.STATE.voice_pending = True
    A.STATE.utterances[-2]["ts"] = time.time() - A.CONFIG.speech_context_sec - 5
    await until(lambda: sum(m["type"] == "analysis_done" for m in msgs) == 6)
    check("a sentence aged out of the run brings nothing answered back", pipe.words[-1] == "And what is a checkpoint?", pipe.words[-1])
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_a_newer_problem_takes_the_place_of_the_one_waiting():
    """One waits: what is said in the same run joins it, and after a pause a newer problem takes its place."""
    pipe, det = Pipe(), Detector()
    pipe.wrote = "TYPE: essay\nANSWER: 답"
    pipe.answer = "TYPE: essay\nANSWER: 답"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    sentence("What does a write ahead log do?", 0); A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    sentence("And what is a checkpoint?", 1); A.STATE.voice_pending = True
    await asyncio.sleep(0.2)
    sentence("What is a torn page?", 20); A.STATE.voice_pending = True
    await asyncio.sleep(0.2)
    check("the answer being written is not stopped", pipe.cancelled == [] and len(pipe.started) == 1, f"{pipe.started}")
    await next_answer(pipe, msgs, 1)
    await until(lambda: len(pipe.started) == 2)
    check("after a pause the newer problem takes the place of the one waiting", pipe.words[1] == "What is a torn page?", pipe.words[1])
    await next_answer(pipe, msgs, 2)
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_what_waits_does_not_age_out():
    """What waits behind an answer being written is still asked, however long that answer takes; and with nothing to ask nothing starts."""
    was = knobs(speech_context_sec=0.5)
    pipe, det = Pipe(), Detector()
    pipe.wrote = "TYPE: essay\nANSWER: 답"
    pipe.answer = "TYPE: essay\nANSWER: 답"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    sentence("How does a bloom filter answer so fast?", 0); A.STATE.voice_pending = True
    await asyncio.sleep(0.25)
    sentence("And what makes a false yes happen?", 1); A.STATE.voice_pending = True
    await asyncio.sleep(0.9)                  # the answer goes on past the age of what was said
    check("the answer is still being written, and the newer question waits", len(pipe.started) == 1 and A.STATE.voice_pending is True, f"{pipe.started}")
    await next_answer(pipe, msgs, 1)
    await until(lambda: len(pipe.started) == 2)
    check("what waited is asked when the answer ends, and it counts as speech", pipe.started[1:] == [(2, True)], f"{pipe.started}")
    check("...in its own words", pipe.words[1:] == ["And what makes a false yes happen?"], f"{pipe.words}")
    await next_answer(pipe, msgs, 2)
    check("age counts as usual again once nothing waits", A.STATE.voice_held_at == 0.0, A.STATE.voice_held_at)
    # A flag with no words behind it at all, and a screen already answered: nothing starts from the voice branch
    await asyncio.sleep(0.6)
    A.STATE.utterances.clear()
    push("answered")
    A.STATE.latest_frame.sig = "answered"
    det.committed.append(A.STATE.latest_frame)
    n = len(pipe.started)
    A.STATE.voice_pending = True
    await asyncio.sleep(0.4)
    check("a flag with nothing left to read starts no analysis, of the speech or of the screen", len(pipe.started) == n, f"{pipe.started}")
    check("...and goes down", A.STATE.voice_pending is False)
    await stop(task)
    knobs(**was)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_nothing_to_ask_stops_nothing():
    """A flag with no new words does not stop the spoken problem that is still being read."""
    pipe, det = Pipe(), Detector()
    pipe.answer = "TYPE: essay\nANSWER: 답"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    sentence("What does a bloom filter store?", 0); A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    A.STATE.voice_answered_to = A.STATE.utterances[-1]["end"]   # its words have their answer by another way (Reanalyze)
    A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    check("the one still being read is not stopped for nothing", pipe.cancelled == [] and len(pipe.started) == 1, f"{pipe.cancelled} {pipe.started}")
    await next_answer(pipe, msgs, 1)
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_first_words_end_the_asking():
    """Once the answer is being written, what is said next asks for itself: it no longer extends the question."""
    pipe, det = Pipe(), Detector()
    pipe.wrote = "TYPE: essay\nANSWER: 답"
    task = await start_worker(pipe, det)
    speak("What does a write ahead log do?"); A.STATE.voice_asked = A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    check("the first words clear it", A.STATE.voice_asked is False)
    await stop(task)
    pipe, det = Pipe(), Detector()
    task = await start_worker(pipe, det)
    speak("What does a write ahead log do?"); A.STATE.voice_asked = A.STATE.voice_pending = True
    await asyncio.sleep(0.3)
    check("while nothing is written, it stands", A.STATE.voice_asked is True)
    await stop(task)


async def case_after_nothing_to_solve_it_is_all_still_to_read():
    """An analysis that found nothing to solve answered nothing: the next one reads all of it, and the panel says why."""
    pipe, det = Pipe(), Detector()
    pipe.answer = "TYPE: none"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    speak("So the rebuild took two hours, right?"); A.STATE.voice_pending = True
    await next_answer(pipe, msgs, 1)
    told = [m for m in msgs if m["type"] == "utterance"]
    check("the panel is told a sentence that only sounded like a question was not solved", [(m["text"], m["why"]) for m in told] == [("So the rebuild took two hours, right?", "told")], f"{told}")
    check("and nothing counts as answered", A.STATE.voice_answered_to == 0, A.STATE.voice_answered_to)
    speak("What is a checkpoint?"); A.STATE.voice_pending = True
    pipe.answer = "TYPE: essay\nANSWER: 답"
    await next_answer(pipe, msgs, 2)
    check("the next one reads all of it, as nothing has its answer", pipe.words[1] == "So the rebuild took two hours, right? What is a checkpoint?", pipe.words[1])
    check("an answer says nothing to the card's sentences", len([m for m in msgs if m["type"] == "utterance"]) == 1, f"{msgs}")
    await stop(task)
    pipe, det = Pipe(), Detector()
    pipe.answer = "TYPE: none"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    speak("We moved the whole team to GitHub Actions last year."); A.STATE.voice_pending = True
    await next_answer(pipe, msgs, 1)
    check("with no question in it, it says no question", [m["why"] for m in msgs if m["type"] == "utterance"] == ["none"], f"{msgs}")
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_an_answer_done_is_let_end_not_cut():
    """A spoken problem answered while a slow panel takes its end is let end: a newer screen then neither cancels it nor asks it again."""
    pipe, det = Pipe(), Detector()
    sent, real = [], A.broadcast

    async def slow_end(msg):            # a send that waits on the end of the card: a panel's socket full, or closing
        sent.append(msg)
        if msg.get("type") == "analysis_done":
            await asyncio.sleep(0.6)
    A.broadcast = slow_end
    pipe.release.set()
    task = await start_worker(pipe, det)
    push(b"a")
    det.committed.append(A.STATE.latest_frame)   # the screen is answered already: the spoken problem alone runs
    speak("이 문제 좀 풀어 줘 두 수의 합은?")
    A.STATE.voice_pending = True
    await asyncio.sleep(0.3)            # its answer is done, and the worker is in the broadcast of its end
    det.moved = True
    push(b"b")                          # a clearly different screen comes meanwhile
    await asyncio.sleep(2.5)
    voice_runs = [s for s in pipe.started if s[1]]
    cancelled = [m for m in sent if m.get("type") == "analysis_cancelled"]
    done = [m.get("id") for m in sent if m.get("type") == "analysis_done"]
    check("the spoken problem's card ends as done, not cancelled", 1 in done and not cancelled, f"done {done}, cancelled {cancelled}")
    check("...it is not asked again", len(voice_runs) == 1 and A.STATE.voice_retake == "", f"{pipe.started} retake {A.STATE.voice_retake!r}")
    check("...and no reason to cancel is left for the next one", A.STATE.cancel_reason is None, A.STATE.cancel_reason)
    await stop(task)
    A.broadcast = real


async def case_a_pause_during_a_done_answers_end_starts_nothing_after_it():
    """A pause pressed while a done answer's end goes to a slow panel: the answer is let end, and the code check and the
    agent's check its end would start are not started (the pause had stopped them before they existed, and they ran on
    after it, the agent's one sending the screen while paused)."""
    started, real = [], dict(broadcast=A.broadcast, cancel_check=A.cancel_check, cancel_verify=A.cancel_verify,
                             runner_here=A.runner_here, checkable=A.checkable, run_check=A.run_check,
                             run_verify=A.run_verify, save_switches=A.save_switches)

    async def fake_check(app, seq, frame, outcome):
        started.append(("check", seq))
        await asyncio.sleep(30)

    async def fake_verify(seq, frame, transcript, voice, outcome, by_user=False):
        started.append(("verify", seq))
        await asyncio.sleep(30)
    sent = []

    async def slow_end(msg):            # a panel slow to take the answer's end
        sent.append(msg.get("type"))
        if msg.get("type") == "analysis_done":
            await asyncio.sleep(0.8)
    A.broadcast, A.runner_here, A.checkable = slow_end, (lambda: True), (lambda *a, **k: True)
    A.run_check, A.run_verify, A.save_switches = fake_check, fake_verify, (lambda: None)
    A.cancel_check, A.cancel_verify = REAL_CANCEL_CHECK, REAL_CANCEL_VERIFY   # the real ones: the pause's own stop
    pipe, det = Pipe(), Detector()
    pipe.verifying = lambda result: True     # Check answers: the agent checks this PC's answer
    pipe.answer = "TYPE: coding\n```python\nprint(1)\n```"
    pipe.release.set()
    task = await start_worker(pipe, det)
    push(b"a")
    for _ in range(100):                     # until the worker is inside the slow end
        await asyncio.sleep(0.02)
        if "analysis_done" in sent:
            break
    await asyncio.sleep(0.1)
    await A.set_paused(True)
    await asyncio.sleep(1.6)
    check("a pause during a done answer's end starts no code check and no agent's check after it",
          "analysis_done" in sent and "analysis_cancelled" not in sent and started == [], f"sent {sent}, started {started}")
    for t in (A.STATE.check_task, A.STATE.verify_task):
        if t is not None and not t.done():
            t.cancel()
    await stop(task)
    for k, v in real.items():
        setattr(A, k, v)
    A.STATE.paused = False


async def case_words_are_kept_once_the_card_is_done():
    """The words a problem went out to the agent in are kept when its card is done, and not when it is stopped before that."""
    real_shown, real = A.shown_box, A.broadcast
    for pause in (False, True):
        pipe, det = Pipe(), Detector()
        kept, sent = [], []
        pipe.recent = types.SimpleNamespace(add=lambda *a, **k: None, forget=lambda: None,
                                            add_words=lambda seq, words: kept.append((seq, words)))

        async def listen(msg):
            sent.append(msg)
        A.broadcast = listen
        # placing the box on the screen takes a moment: a pause landing there stops the card before it is done
        A.shown_box = lambda frame, region: time.sleep(0.6) or region

        async def solve(seq, frame, transcript, voice, on_delta, by_user=False):
            pipe.started.append((seq, bool(voice)))
            await on_delta("TYPE: math\n")
            return Outcome(text="TYPE: math\nANSWER: 3", model="m", usage=None, cost_usd=None, engine="agent",
                           region=(0.1, 0.1, 0.5, 0.5), region_placed=True, words="두 수의 합은?")
        pipe.solve = solve
        task = await start_worker(pipe, det)
        push(b"a")
        if pause:
            await asyncio.sleep(0.35)   # solve came back; the worker is placing the box
            A.request_stop("pause")
            A.STATE.paused = True
        await asyncio.sleep(1.2)
        reasons = [m.get("reason") for m in sent if m.get("type") == "analysis_cancelled"]
        if pause:
            check("...a pause before the card is done stops it, and its words are not kept", reasons == ["pause"] and kept == [],
                  f"cancelled {reasons}, kept {kept}")
        else:
            check("a card done keeps the words it went out in", kept == [(1, "두 수의 합은?")], f"kept {kept}")
        await stop(task)
    A.shown_box, A.broadcast = real_shown, real


async def case_a_decline_keeps_no_words():
    """A reply with no head (the agent declined, or gave no answer) stands for no problem: its words are not kept, and the
    same problem seen again is asked again (it was "already solved", pointing at the decline)."""
    real = A.broadcast
    pipe, det = Pipe(), Detector()
    kept = []
    pipe.recent = types.SimpleNamespace(add=lambda *a, **k: None, forget=lambda: None,
                                        add_words=lambda seq, words: kept.append((seq, words)))

    async def solve(seq, frame, transcript, voice, on_delta, by_user=False):
        pipe.started.append((seq, bool(voice)))
        return Outcome(text="I can't help with this one.", model="m", usage=None, cost_usd=None, engine="agent",
                       region=(0.1, 0.1, 0.5, 0.5), region_placed=True, words="두 수의 합은?")
    pipe.solve = solve
    A.broadcast = lambda msg: asyncio.sleep(0)
    task = await start_worker(pipe, det)
    push(b"a")
    await asyncio.sleep(0.8)
    check("a decline's card (no head) keeps no words", pipe.started and kept == [], f"started {pipe.started}, kept {kept}")
    await stop(task)
    A.broadcast = real


async def case_a_worker_started_again_takes_over_its_analysis():
    """A worker that stops on an error is started again (worker_ended): the analysis it left running is the new one's."""
    pipe, det = Pipe(), Detector()
    task = await start_worker(pipe, det)
    push(b"one")
    await until(lambda: pipe.started)
    check("(an analysis of the screen runs)", pipe.started == [(1, False)], f"{pipe.started}")
    broken = {"n": 0}

    def ready():   # one look of the worker's loop raises: what a bug in it does
        broken["n"] += 1
        if broken["n"] == 1:
            raise RuntimeError("a bug in the worker's loop")
        return True
    pipe.ready = ready
    await asyncio.sleep(0.3)
    check("(the worker stopped on it)", task.done() and task.exception() is not None, f"{task}")
    app = types.SimpleNamespace(state=types.SimpleNamespace(transcriber=None, detector=det))
    again = asyncio.create_task(A.analysis_worker(app))   # as worker_ended starts it: the state as it was
    await asyncio.sleep(0.25)
    push(b"two")   # a newer screen, not a clearly different one: the analysis running is let finish
    await asyncio.sleep(0.5)
    check("the analysis left running is the new worker's: a newer screen starts none beside it", len(pipe.started) == 1, f"{pipe.started}")
    await A.set_paused(True)
    await asyncio.sleep(0.4)
    check("...and the pause stops it", pipe.cancelled == [(1, False)], f"{pipe.cancelled}")
    await A.set_paused(False)
    await stop(again)


async def case_reanalyze_reads_the_screen_once_the_old_one_stopped():
    """Reanalyze reads what it runs on once the analysis it replaces has stopped: a screen switched off meanwhile starts none."""
    pipe, det = Pipe(), Detector()
    msgs = said_to_panel()
    real = pipe.solve

    async def solve(seq, frame, transcript, voice, on_delta, by_user=False):
        try:
            return await real(seq, frame, transcript, voice, on_delta, by_user)
        except asyncio.CancelledError:
            A.STATE.latest_frame, A.STATE.screen_on = None, False   # the screen switched off while it was stopping,
            A.STATE.screen_epoch += 1                               # as set_capture switches it off
            raise
    pipe.solve = solve
    task = await start_worker(pipe, det)
    push(b"one")
    await until(lambda: pipe.started)
    A.STATE.force_analyze = True
    await asyncio.sleep(0.6)
    check("Reanalyze stops the analysis running", pipe.cancelled == [(1, False)], f"{pipe.cancelled}")
    check("...and with no screen left by then, and nothing heard, it starts none: an empty question went to the agent",
          len(pipe.started) == 1, f"{pipe.started} {pipe.words}")
    check("...and says why", any(m.get("type") == "notice" and m.get("level") == "warn" for m in msgs), f"{msgs}")
    stopped = [m for m in msgs if m.get("type") == "analysis_cancelled"]
    check("...the one it stopped is said stopped by the screen-off, its half answer kept with that note, not dropped",
          [m.get("reason") for m in stopped] == ["screen_off"], f"{stopped}")
    check("...and the id Reanalyze was given goes with it, for no later analysis to take", A.STATE.force_seq == 0, A.STATE.force_seq)
    A.STATE.screen_on = True
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_words_heard_go_when_the_sound_goes_off_as_the_answer_ends():
    """The sound switched off while a spoken problem's answer ends: what was heard is not kept with it for the next question."""
    pipe, det = Pipe(), Detector()
    pipe.answer = "TYPE: essay\nANSWER: 답\n\n풀이"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    speak("What does a write ahead log do?"); A.STATE.voice_pending = True
    await until(lambda: pipe.started)
    slow = A.note_success

    async def note_success(*a, **k):   # a panel slow to take the message: the sound is switched off meanwhile
        A.STATE.sound_off_epoch += 1    # what set_capture(audio=False) does to what was heard (its saving and its
        A.STATE.reset_speech()          # messages to the capture program are not this harness's)
    A.note_success = note_success
    real_remembered = A.remembered
    A.remembered = lambda result, frame, seq, voice=False: {**real_remembered(result, frame, seq, voice), "words": "what was heard"}
    try:
        await next_answer(pipe, msgs, 1)
        await asyncio.sleep(0.2)
    finally:
        A.note_success, A.remembered = slow, real_remembered
    last = A.STATE.last_result or {}
    check("(the answer is the last one, for questions about it)", last.get("id") == 1, f"{last}")
    check("...without the words heard before the sound went off", not last.get("words"), f"{last.get('words')!r}")
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_a_clock_set_back_does_not_stop_the_watching():
    """The PC's clock set back an hour: a new screen is still looked at, the gap between looks is on a clock that does not go back."""
    pipe, det = Pipe(), Detector()
    was = knobs(min_analyze_interval=0.0)   # no gap at all: on the wall clock the last look was still an hour ahead
    task = await start_worker(pipe, det)
    real_time = A.time.time
    push(b"one")
    await until(lambda: pipe.started)
    pipe.release.set()
    await asyncio.sleep(0.3)
    pipe.release.clear()
    A.time.time = lambda: real_time() - 3600   # the clock goes back
    try:
        push(b"two")
        await asyncio.sleep(1.0)
        check("a new screen is looked at with the clock an hour back", len(pipe.started) == 2, f"{pipe.started}")
    finally:
        A.time.time = real_time
        knobs(**was)
    await stop(task)


async def case_a_resume_is_no_sound_off():
    """An answer to what was heard, asked for while paused (Reanalyze), that ends after the resume keeps what was heard."""
    pipe, det = Pipe(), Detector()
    pipe.answer = "TYPE: essay\nANSWER: 답\n\n풀이"
    msgs = said_to_panel()
    task = await start_worker(pipe, det)
    A.STATE.latest_frame = None
    await A.set_paused(True)
    speak("What does a write ahead log do?")
    A.STATE.force_analyze = True   # Reanalyze, while paused: it runs on what was heard
    await until(lambda: pipe.started)
    slow = A.note_success

    async def note_success(*a, **k):   # the resume comes while the answer ends
        await A.set_paused(False)
    A.note_success = note_success
    real_remembered = A.remembered
    A.remembered = lambda result, frame, seq, voice=False: {**real_remembered(result, frame, seq, voice), "words": "what was heard"}
    try:
        await next_answer(pipe, msgs, 1)
        await asyncio.sleep(0.2)
    finally:
        A.note_success, A.remembered = slow, real_remembered
    last = A.STATE.last_result or {}
    check("(the answer to what was heard is the last one)", last.get("id") == pipe.started[0][0] and pipe.started[0][1], f"{pipe.started} {last}")
    check("...and the resume during its end is no sound switched off: it keeps what was heard", last.get("words") == "what was heard",
          f"{last.get('words')!r}")
    await stop(task)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def main():
    patch()
    for case in (case_voice_does_not_cancel_screen, case_screen_takes_over_from_voice,
                 case_brake_starts_nothing, case_settle_waits_for_a_still_screen,
                 case_the_settle_is_longer_mid_burst_than_after_a_calm_stretch,
                 case_a_screen_that_never_rests_is_still_asked_about, case_a_call_beside_a_still_screen_does_not_hold_the_start,
                 case_quiet_after_a_run_of_empty_answers, case_an_answer_does_not_wait_for_its_picture,
                 case_a_problem_seen_again_is_the_one_asked_about, case_nothing_written_yet_the_longer_version_replaces_it,
                 case_an_answer_being_written_is_let_finish, case_a_quizs_options_go_with_their_question, case_a_place_in_the_sound_not_its_words,
                 case_a_newer_problem_takes_the_place_of_the_one_waiting, case_what_waits_does_not_age_out,
                 case_nothing_to_ask_stops_nothing, case_first_words_end_the_asking,
                 case_after_nothing_to_solve_it_is_all_still_to_read, case_an_answer_done_is_let_end_not_cut,
                 case_a_pause_during_a_done_answers_end_starts_nothing_after_it, case_a_decline_keeps_no_words,
                 case_words_are_kept_once_the_card_is_done, case_a_worker_started_again_takes_over_its_analysis,
                 case_reanalyze_reads_the_screen_once_the_old_one_stopped, case_words_heard_go_when_the_sound_goes_off_as_the_answer_ends,
                 case_a_clock_set_back_does_not_stop_the_watching, case_a_resume_is_no_sound_off):
        print(case.__doc__.splitlines()[0])
        await case()
    print(f"\n  ==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
