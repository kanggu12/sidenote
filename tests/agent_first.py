"""Claude first, the local model when Claude cannot, and the fixes live use called for: a drawn region left from
an earlier sitting, a video beside a still problem, a GPU taken by another program.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/agent_first.py

Checks, each a thing the server did differently before:
  routing   work, essay and other are Claude's by default; a deep problem of any type goes to Claude when the
            local model would be 1.5 times as slow to start answering, or another program has the GPU; it stays on
            this PC when the local model is not slower, and always when Claude is off
  speed     the time to the first piece of each answer is noted once per answer and kept across restarts
  deadline  a first pass that brings no token in local_first_token_sec hands the screen on at once (it waited
            local_fast_timeout, 45 s); one whose first token comes in time runs as before
  thinking  the thinking pass tells how far it has thought, every THOUGHT_EVERY seconds
  video     a video moving beside the same problem is not a new screen; a scroll that has stopped is, video or not
  region    a drawn region is not written to the settings file nor read back from an old one, and a capture program
            starting clears it
  verify    the verify mode reads the problem's words from the model's box on a 4K screen where it places nothing, as
            the answer's own path does, and from the whole screen elsewhere
"""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-agent-first-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="")
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from server.analyzer import AnalysisResult, FastResult, LocalLlmAnalyzer, make_engines  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.pipeline import Hooks, Pipeline  # noqa: E402
from server.settings import SETTINGS, Settings  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f"  - {detail}" if detail and not ok else ""))


class FakeFrame:
    """A screen as prepare_frame makes one (the fields the pipeline reads)."""

    def __init__(self, w=200, h=120):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, format="PNG")
        self.full_png = buf.getvalue()
        self.model_b64 = base64.b64encode(self.full_png).decode()
        self.thumb_url = "data:image/png;base64," + self.model_b64
        self.ts, self.width, self.height = 0.0, w, h
        self.extra_b64, self.windows, self.ocr_lines, self.sig = [], None, None, b""
        self.model_box = (0.0, 0.0, 1.0, 1.0)


async def _none(*a, **k):
    return None


async def _yes(*a, **k):
    return True


def make_pipeline(stages=None):
    engines = make_engines(CONFIG)   # MockLocal and the mock Claude

    async def stage(seq, name, detail, restart=False, **_):
        if stages is not None:
            stages.append((name, detail))
    hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_none, stage=stage, confirm=_yes,
                  agent_failed=_none)
    pipe = Pipeline(engines, hooks)
    # these checks ask the same problem again on purpose, to see which engine takes it (the repeat is repeats_check's)
    pipe.recent.add_words = lambda *a, **k: None
    return pipe, engines


async def routing():
    print("\n[routing: Claude first]")
    from server.pipeline import Speed
    check("work, essay and other are among Claude's types by default",
          {"work", "essay", "other"} <= set(Settings(None).get("agent_hard_types")),
          str(Settings(None).get("agent_hard_types")))
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               agent_hard_types=["algorithm", "coding", "math"])
        pipe, eng = make_pipeline()

        async def deep_mcq(*a, **k):   # the first pass says: a choice question that needs reasoning
            return FastResult(text=None, head="TYPE: mcq\nROUTE: deep\n", type="mcq", route="deep")
        eng.local.fast = deep_mcq
        pipe.speed = Speed(None)       # nothing measured: the defaults, 20 s against 8 s
        out = await pipe.solve(71, FakeFrame(), "", False, _none)
        check("a deep problem of a type not chosen goes to Claude while the local model is 1.5x as slow to start",
              out.engine == "agent", out.engine)
        pipe.speed.times = {"think": [5.0], "agent": [20.0]}   # Claude slow today
        out = await pipe.solve(72, FakeFrame(), "", False, _none)
        check("...and stays on this PC when the local model is not slower", out.engine == "local", out.engine)
        eng.local.busy = True
        out = await pipe.solve(73, FakeFrame(), "", False, _none)
        check("another program on the GPU sends it to Claude", out.engine == "agent", out.engine)
        eng.local.busy = False
        SETTINGS.values["agent_mode"] = "off"
        pipe.speed.times = {}
        out = await pipe.solve(74, FakeFrame(), "", False, _none)
        check("with Claude off the local model answers whatever the speeds", out.engine == "local", out.engine)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def spanning_box():
    print("\n[a box that runs into another window: where the problem's words are read from]")
    # The first pass's box once ran into a second window, so it placed nothing (located), the words were
    # read from the whole 4K screen, nothing came back (as on the 4K desktops of section 11, span_sharp.py), nothing
    # went to Claude, and this PC's model took 169 s. Now a large screen's box is read, and the whole screen when that
    # gives nothing (box_first); any other screen is read as before, the whole screen once.
    import logging
    from server.pipeline import Speed
    saved = dict(SETTINGS.values)
    lines = []

    class Keep(logging.Handler):   # the log, where the route taken in real use is looked for
        def emit(self, record):
            lines.append(record.getMessage())
    keep, logger = Keep(), logging.getLogger("sidenote.pipeline")
    level = logger.level
    logger.setLevel(logging.INFO)   # setLevel, not .level: the logger caches what it lets through
    logger.addHandler(keep)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               extract=True, roi=True, roi_windows=True)
        pipe, eng = make_pipeline()

        async def deep_coding(*a, **k):   # a coding problem, its box half in the left window and half in the right
            # on the local model's 0-1000 grid (LocalLlmAnalyzer.region_scale, as MockLocal's)
            return FastResult(text=None, head="TYPE: coding\nREGION: 300 200 700 800\nROUTE: deep\n", type="coding",
                              route="deep")
        eng.local.fast = deep_coding
        read, says = [], {}

        async def extract(images=(), speech=""):   # the whole screen is the frame's own size; the box is cut smaller
            size = Image.open(io.BytesIO(base64.b64decode(images[0]))).size if images else (0, 0)
            read.append("screen" if size in ((1000, 600), (3840, 2160)) else "box")
            return says[read[-1]]
        eng.local.extract = extract
        sent = []
        real_run = eng.agent.run

        async def claude_run(images, text, on_delta, web=False):
            sent.append(text)
            return await real_run(images, text, on_delta)
        eng.agent.run = claude_run
        pipe.speed = Speed(None)
        problem = "문자열 압축: s 를 받아 가장 짧은 압축 길이를 돌려준다"
        for w, h, screen, box, want in ((1000, 600, "", problem, ["screen"]),
                                        (1000, 600, problem, problem, ["screen"]),
                                        (3840, 2160, "", problem, ["box"]),
                                        (3840, 2160, problem, "", ["box", "screen"])):
            read.clear()
            sent.clear()
            lines.clear()
            says.update(screen=screen, box=box)
            frame = FakeFrame(w, h)
            frame.windows = [[0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 1.0, 1.0]]   # two windows side by side
            out = await pipe.solve(81, frame, "", False, _none)
            what = (f"{w}x{h}, the whole screen " + ("gives nothing" if not screen else "gives the problem")
                    + (", the box nothing" if not box else ""))
            check(f"{what}: read {' then '.join(want)}", read == want, str(read))
            # a small screen that gives nothing goes to this PC's model as before; the others go to Claude as words
            to_agent = bool(screen) or w > 3000
            check(f"{what}: {'the words go to Claude, which answers' if to_agent else 'this PC model answers, as before'}",
                  (out.engine == "agent" and any("문자열 압축" in t for t in sent)) if to_agent
                  else (out.engine == "local" and not sent), f"{out.engine} {[t[-60:] for t in sent]}")
            # and the code check and the problem text of Claude's answer read where its words came from: the box
            # when the box gave them, else the screen (an answer of this PC's model keeps the thinking pass's own
            # view, as before)
            if to_agent:
                from_box = read[-1] == "box"
                check(f"{what}: read again afterwards from {'the box' if from_box else 'the screen'}",
                      (out.local_view is not None) == from_box, str(out.local_view))
                # and the log says so, the one place real use shows which way the words went
                said = [x for x in lines if "the agent gets" in x]
                check(f"{what}: the log says {'they came from the box' if from_box else 'nothing of a box'}",
                      bool(said) and ("from the model's box" in said[-1]) == from_box, str(said))
    finally:
        logger.removeHandler(keep)
        logger.setLevel(level)
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def verify_spanning_box():
    print("\n[the verify mode reads Claude's words where the answer's own path reads them]")
    # The verify mode built its payload from the placed box alone, so on a 4K screen whose box ran into another window
    # the words were read from the whole screen, which there comes back empty (span_sharp.py), and nothing went to
    # Claude, while an answer of Claude's own on the same screen read them from the box (box_first).
    from server.pipeline import NotSent
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="verify", agent_payload="crop", agent_confirm=False,
                               extract=True, roi=True, roi_windows=True)
        pipe, eng = make_pipeline()

        async def deep_coding(*a, **k):   # the box half in the left window and half in the right, as in spanning_box
            return FastResult(text=None, head="TYPE: coding\nREGION: 300 200 700 800\nROUTE: deep\n", type="coding",
                              route="deep")
        eng.local.fast = deep_coding
        problem = "문자열 압축: s 를 받아 가장 짧은 압축 길이를 돌려준다"
        read = []

        async def extract(images=(), speech=""):   # the whole screen gives nothing, the box gives the problem
            size = Image.open(io.BytesIO(base64.b64decode(images[0]))).size if images else (0, 0)
            read.append("screen" if size in ((1000, 600), (3840, 2160)) else "box")
            return problem if read[-1] == "box" else ""
        eng.local.extract = extract
        sent = []

        async def claude_run(images, text, on_delta, web=False):   # the check's reply: the answer holds
            sent.append(text)
            return SimpleNamespace(text="TYPE: verify\nANSWER: OK", model="mock-claude", cost_usd=0.001,
                                   usage={"input_tokens": 10, "output_tokens": 3})
        eng.agent.run = claude_run
        for w, h in ((3840, 2160), (1000, 600)):
            frame = FakeFrame(w, h)
            frame.windows = [[0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 1.0, 1.0]]   # two windows side by side
            out = await pipe.solve(95, frame, "", False, _none)
            check(f"{w}x{h}: this PC's model answers in the verify mode", out.engine == "local", out.engine)
            read.clear()
            sent.clear()
            try:
                res = await pipe.verify(95, frame, "", False, out)
            except NotSent as why:
                res = {"not_sent": str(why)}
            if w > 3000:
                check(f"{w}x{h}: the words are read from the box", read == ["box"], str(read))
                check(f"{w}x{h}: ...and go to Claude, which checks the answer",
                      res.get("verdict") == "ok" and any("문자열 압축" in t for t in sent), f"{res} {sent}")
            else:   # a small screen is read whole, as before, and nothing went out when it gave nothing
                check(f"{w}x{h}: the whole screen is read once, as before", read == ["screen"], str(read))
                check(f"{w}x{h}: ...and nothing goes to Claude when it gives nothing",
                      "not_sent" in res and not sent, f"{res} {sent}")
        # "confirm before sending" shows the words of the problem that go, not only the end of a long answer appended
        # to them: those words may have been read off a box running into another window
        SETTINGS.values["agent_confirm"] = True
        shown = []

        async def confirm(seq, preview):
            shown.append(preview)
            return True
        pipe.hooks.confirm = confirm
        frame = FakeFrame(3840, 2160)
        frame.windows = [[0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 1.0, 1.0]]
        out = await pipe.solve(96, frame, "", False, _none)
        out.text = out.text + "\n" + "풀이 설명이 길게 이어집니다. " * 200   # a long answer
        await pipe.verify(96, frame, "", False, out)
        check("verify: the confirm shows the problem's words, a long answer after them",
              shown and "문자열 압축" in shown[-1]["text"], (shown[-1]["text"][:120] if shown else "no confirm"))
        SETTINGS.values["agent_confirm"] = False
        # the direct pass (no thinking, no first pass) writes its REGION y first at times: its box is not where
        # Claude's words are read from in the verify mode; the screen is, as before
        SETTINGS.values["local_think"] = "never"

        async def direct(images, text, on_delta, prior=None, think=True, on_thought=None):
            return AnalysisResult(text="TYPE: coding\nREGION: 300 200 700 800\nANSWER: x\n```python\npass\n```",
                                  model="mock-local")
        eng.local.deep = direct
        read.clear()
        sent.clear()
        out = await pipe.solve(97, frame, "", False, _none)
        try:
            await pipe.verify(97, frame, "", False, out)
        except NotSent:
            pass
        check("verify after a direct pass: no box of its own for the words, the screen is read",
              out.seen is None and read == ["screen"], f"{out.seen} {read}")
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def not_sent_record():
    print("\n[why nothing went to Claude is on record, a confirm not given too]")
    # The log line read `why or "not confirmed"`, and an exception is always true, so a confirm
    # not given (NotSent() with no words) was logged as "()"
    import logging
    import server.telemetry as telemetry
    saved = dict(SETTINGS.values)
    lines, events = [], []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())
    keep, logger = Keep(), logging.getLogger("sidenote.pipeline")
    level = logger.level
    logger.setLevel(logging.INFO)   # setLevel, not .level: the logger caches what it lets through, and only it clears that
    logger.addHandler(keep)
    plain_event = telemetry.event

    def event(name, **fields):   # the event record, as the server writes it (no log folder in this run)
        events.append({"event": name, **fields})
        return plain_event(name, **fields)
    telemetry.event = event
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=True)
        pipe, eng = make_pipeline()

        async def no(*a, **k):   # Send is not pressed
            return False
        pipe.hooks.confirm = no
        out = await pipe.solve(91, FakeFrame(), "", False, _none)
        said = [x for x in lines if "nothing sent to the agent" in x]
        check("a confirm not given: this PC's model answers", out.engine == "local", out.engine)
        check("...and the log says why: not confirmed", any("(not confirmed)" in x for x in said), str(said))
        ev = [r for r in events if r.get("event") == "agent_not_sent" and r.get("id") == 91]
        check("...and so does the event", bool(ev) and ev[-1].get("reason") == "not confirmed", str(ev))
    finally:
        logger.removeHandler(keep)
        logger.setLevel(level)
        telemetry.event = plain_event
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def speed():
    print("\n[the speed book]")
    from server.pipeline import Speed
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".speed.json"
        sp = Speed(path)
        got = []

        async def sink(t):
            got.append(t)
        w = sp.timed("agent", sink)
        await asyncio.sleep(0.05)
        await w("a")
        await w("b")
        check("the time to the first piece of the answer is noted once, and every piece passed on",
              len(sp.times.get("agent", [])) == 1 and 0.04 < sp.times["agent"][0] < 1 and got == ["a", "b"],
              str(sp.times))
        check("and read back after a restart", Speed(path).times == sp.times, path.read_text())
        sp.times = {"think": [30.0, 31.0, 29.0], "agent": [10.0, 9.0, 12.0]}
        check("the rule reads the medians (30 s against 10 s is slower than 1.5x)", sp.local_slower(1.5))
        check("a ratio of 0 turns the rule off", not sp.local_slower(0))


async def deadline():
    print("\n[the first-token deadline]")
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    local._ready = _none   # no model to load in a test

    async def late(body, on_delta):     # a model just loaded, reading the whole prompt: its first token comes late
        await asyncio.sleep(0.6)
        await on_delta("TYPE: none\n")
        return "TYPE: none\n", {"output_tokens": 3}, [], {"finish": "stop", "thought": ""}
    local._stream = late
    res = await local.fast([], "q", _none, first_deadline=0.3)
    check("a model just loaded gets the longer limit: not called busy, and it answers", not res.slow and res.type == "none" and not local.pace.busy() and local.model in local._warm,
          f"slow={res.slow} busy={local.pace.busy()}")
    local._warm.clear()
    local._warm.add(local.model)         # warm from here on: silence means something

    async def silent(body, on_delta):   # a GPU taken by another program: nothing comes
        await asyncio.sleep(30)
        return "", None, [], {"finish": "stop", "thought": ""}
    local._stream = silent
    t0 = time.monotonic()
    res = await local.fast([], "q", _none, first_deadline=0.3)
    took = time.monotonic() - t0
    check("no first token within the deadline: handed on at once and counted as a busy GPU",
          res.slow and res.text is None and took < 2 and local.pace.busy(), f"slow={res.slow} took={took:.2f}")
    local.pace.busy_until = 0.0

    async def quick(body, on_delta):
        await on_delta("TYPE: none\n")
        return "TYPE: none\n", {"output_tokens": 3}, [], {"finish": "stop", "thought": ""}
    local._stream = quick
    res = await local.fast([], "q", _none, first_deadline=0.3)
    check("a first token in time: the pass runs as before", not res.slow and res.type == "none",
          f"slow={res.slow} type={res.type}")
    local._stream = silent
    t0 = time.monotonic()
    task = asyncio.ensure_future(local.fast([], "q", _none))   # no deadline: waits (here, until cancelled)
    await asyncio.sleep(0.6)
    check("without a deadline (no Claude to hand it to) the pass keeps waiting", not task.done())
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class FakeSSE:
    """The local model's server streaming chat completions: `lines` as the stream's lines, `delay` apart."""

    def __init__(self, lines, delay=0.0):
        self.lines, self.delay = lines, delay

    def stream(self, method, url, json=None):
        outer = self

        class Resp:
            status_code = 200

            async def aiter_lines(self):
                for line in outer.lines:
                    await asyncio.sleep(outer.delay)
                    yield line

            async def aread(self):
                return b""

        class Ctx:
            async def __aenter__(self):
                return Resp()

            async def __aexit__(self, *a):
                return False
        return Ctx()

    async def aclose(self):
        pass


async def thinking():
    print("\n[the thinking progress]")
    import server.analyzer as an
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    local._ready = _none
    chunk = lambda d: "data: " + json.dumps({"choices": [{"delta": d}]})   # noqa: E731
    local._client = FakeSSE([chunk({"reasoning": "생각" * 10}) for _ in range(8)]
                            + [chunk({"content": "TYPE: short\nANSWER: 1\n답"}), "data: [DONE]"], delay=0.1)
    notes, every = [], an.THOUGHT_EVERY
    an.THOUGHT_EVERY = 0.25

    tails = []

    async def note(chars, tail=""):   # and the end of the thinking so far, for the card's last line
        notes.append(chars)
        tails.append(tail)
    try:
        res = await local.deep([], "q", _none, think=True, on_thought=note)
    finally:
        an.THOUGHT_EVERY = every
    check("the thinking pass says how far it has thought while it thinks, the count growing",
          len(notes) >= 2 and notes == sorted(notes) and notes[-1] <= 160 and "답" in res.text, str(notes))
    check("...with the end of what it has thought, for the card's last line",
          tails and all(t and set(t) <= set("생각") for t in tails) and len(tails[-1]) == notes[-1], str(tails[-1:]))
    stages = []
    pipe, eng = make_pipeline(stages)
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="off")

        async def deep(images, text, on_delta, prior=None, think=True, on_thought=None):
            await on_thought(1240)
            return await type(eng.local).deep(eng.local, images, text, on_delta, prior=prior, think=think)
        eng.local.deep = deep
        await pipe.solve(81, FakeFrame(), "", False, _none)
        check("the card's status line gets it", ("think", "생각 1,240자") in stages, str(stages))
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


def video():
    print("\n[a video beside a still problem]")
    from server.detector import ChangeDetector
    from server.gate import SIG_SIZE
    w, h = SIG_SIZE
    base = np.zeros((h, w), np.uint8)
    base[20:60, 40:120] = 80                       # the problem's text

    def frame(v, scrolled=False):
        s = base.copy()
        if scrolled:                               # the page moved down by ten cells
            s[20:60, 40:120] = 0
            s[30:70, 40:120] = 80
        s[90:118, 0:30] = v                        # a video call in the corner
        return SimpleNamespace(sig=s.tobytes())
    d = ChangeDetector(CONFIG)
    d.commit(frame(10))
    for v in (60, 120, 30, 200):
        d.observe(frame(v))
    check("a video moving beside the same problem is not a new screen", not d.is_new(frame(200)))
    old = ChangeDetector(CONFIG)                   # what the detector said before: no frames observed
    old.commit(frame(10))
    check("(it was, before: the whole-screen distance counts the video)", old.is_new(frame(200)))
    check("nor is it reason to drop an answer in progress", not d.moved_on(frame(10), frame(200)))
    for v in (90, 140):                            # one scroll, and the video goes on
        d.observe(frame(v, scrolled=True))
    check("a scroll that has stopped is a new screen while the video goes on", d.is_new(frame(140, scrolled=True)))
    d.set_region((0.25, 0.15, 0.75, 0.6))          # an answered problem's box
    check("inside an answered problem's box too", d.is_new(frame(140, scrolled=True)))
    d2 = ChangeDetector(CONFIG)
    d2.commit(frame(10))
    d2.observe(frame(10, scrolled=True))
    d2.observe(frame(10, scrolled=True))
    d2._seen_at -= 10                              # nothing has come for ten seconds: the screen is still
    check("a still screen is compared in full", d2.live() is None and d2.is_new(frame(10, scrolled=True)))
    # A person in a call moves now and then, not at every frame: half the call's cells change at odd steps, the other
    # half at even ones, so no cell moves in two steps running (the mask used to be "both of the last two")
    def call(k, problem=0):
        s = base.copy()
        if problem:
            s[20:60, 40:120] = problem                 # the next problem in the same place
        s[90:118, 0:15] = 90 if (k + 1) // 2 % 2 else 10    # changes at steps 1, 3, 5, ...
        s[90:118, 15:30] = 90 if k // 2 % 2 else 10         # changes at steps 2, 4, 6, ...
        return SimpleNamespace(sig=s.tobytes())
    d3 = ChangeDetector(CONFIG)
    d3.commit(call(0))
    said = [d3.observe(call(k)) for k in range(0, 7)]      # the real clock: frames a moment apart, still coming
    check("(the call at step 6 differs from the screen analyzed: both halves moved)", call(6).sig != call(0).sig)
    check("a call that moves now and then is not a new screen", not d3.is_new(call(6)))
    check("nor is it reason to drop an answer in progress", not d3.moved_on(call(0), call(6)))
    check("once the call has been seen moving, its frames are not the screen being driven",
          said[5:] == [False, False], str(said))
    nxt = d3.observe(call(7, problem=200))
    check("the next problem appearing beside it is a change", nxt is True and d3.is_new(call(7, problem=200)))
    d3.observe(call(8, problem=200))
    check("and stays one in the frames after it (one step of change is never left out)",
          d3.is_new(call(8, problem=200)))


def region():
    print("\n[a drawn region]")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / ".settings.json"
        st = Settings(path)
        st.set("roi_box", [0.6, 0.4, 0.9, 0.7])
        st.set("dedupe", False)
        saved = json.loads(path.read_text())
        check("a drawn region is not written to the settings file (others are)",
              "roi_box" not in saved and saved.get("dedupe") is False, str(saved))
        path.write_text(json.dumps({"roi_box": [0.6, 0.4, 0.9, 0.7], "dedupe": False}))
        back = Settings(path)
        back.load()
        check("nor read back from one an older server wrote", back.get("roi_box") is None and back.get("dedupe") is False)
    from starlette.testclient import TestClient
    import server.app as A
    with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
        SETTINGS.values["roi_box"] = [0.6, 0.4, 0.9, 0.7]
        with c.websocket_connect("ws://127.0.0.1:8777/ingest", headers={"origin": "http://127.0.0.1:8777"}) as ws:
            ws.send_text(json.dumps({"type": "hello", "info": "capture/win32", "screen": True, "audio": False,
                                     "no_audio": True, "monitor": 1, "flags": {}}))
            time.sleep(0.4)
            check("a capture program starting clears the region drawn in the last sitting",
                  SETTINGS.get("roi_box") is None, str(SETTINGS.get("roi_box")))


def png_b64(color="white", w=640, h=400, text_rows=6, seed=0):
    """A screen with a few dark bars standing for lines of text (the change detector reads edges)."""
    from PIL import ImageDraw
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    for r in range(text_rows):
        d.rectangle([40, 40 + r * 40 + seed, 40 + 300 + (r * 37 + seed) % 200, 52 + r * 40 + seed], fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def continuation():
    print("\n[a problem scrolled together after its answer]")
    from starlette.testclient import TestClient
    import server.app as A
    saved = dict(SETTINGS.values)
    try:
        with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
            SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_confirm=False)
            A.STATE.local, A.STATE.agent = {"ok": True}, {"ok": True}
            with c.websocket_connect("ws://127.0.0.1:8777/panel", headers={"origin": "http://127.0.0.1:8777"}) as panel, \
                    c.websocket_connect("ws://127.0.0.1:8777/ingest", headers={"origin": "http://127.0.0.1:8777"}) as ws:
                ws.send_text(json.dumps({"type": "hello", "info": "capture/test", "screen": True, "audio": False,
                                         "no_audio": True, "monitor": 1, "flags": {}}))
                ws.send_text(json.dumps({"type": "frame", "data": png_b64()}))
                seen, first_done = [], None
                end = time.time() + 30
                while time.time() < end and first_done is None:
                    m = json.loads(panel.receive_text())
                    seen.append(m)
                    if m.get("type") == "analysis_done":
                        first_done = m
                check("the first screen is answered as usual", first_done is not None,
                      str([x.get("type") for x in seen][-8:]))
                if first_done is None:
                    return
                # a scroll: the capture program sends the screen with the problem scrolled together
                ws.send_text(json.dumps({"type": "frame", "data": png_b64(seed=7), "extra": [png_b64(h=900, text_rows=18)]}))
                start = None
                end = time.time() + 30
                while time.time() < end and start is None:
                    m = json.loads(panel.receive_text())
                    if m.get("type") == "analysis_start":
                        start = m
                check("it is answered under the same card, as a continuation, not as a new problem",
                      start is not None and start.get("transcript") == A.t(A.CONTINUE_LABEL)
                      and start.get("about") == first_done.get("id"), str(start))
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


async def main():
    await routing()
    await spanning_box()
    await verify_spanning_box()
    await not_sent_record()
    await speed()
    await deadline()
    await thinking()
    video()
    region()
    continuation()
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


asyncio.run(main())
