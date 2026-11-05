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
                 case_after_nothing_to_solve_it_is_all_still_to_read):
        print(case.__doc__.splitlines()[0])
        await case()
    print(f"\n  ==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
