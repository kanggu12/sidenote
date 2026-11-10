"""What commit 5ee14b1 left wrong in the server, and one older loop, each a thing the server did differently
before.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/server_review.py [section ...]

Sections (numbered; any of the names as arguments runs only those):
  handoff    1  a first pass that brings no token by its deadline is asked once more, on the model used while the
                GPU is busy, for the kind and the place: a screen with nothing on it ends there (no writing out, no
                toast, no thinking pass), a problem goes to Claude as its crop, and when that look brings nothing
                either nothing is sent and nothing is thought about
  misfile    2  a problem scrolled together continues the last answer only when that answer was to a screen, is the
                last screen analysis started, and no screen since moved on from it
  voice      3  a spoken question a screen change stopped is asked again after that screen, and only once
  brake      4  a problem scrolled together while Claude's spend brake holds is solved by this PC's model
  slots      5  the retry and the continuation have a slot each: neither orphans nor stops the other
  remark     6  an analysis that finds nothing leaves the continuation running (the change already made in app.py)
  region     7  no continuation while a region is drawn
  reconnect  8  a capture program reconnecting keeps the drawn region
  pages      9  the same stitched pages are not continued from twice
  shared    10  a first pass that waited behind another request of this server does not count the GPU busy
  release   11  the idle release gives the GPU back once per idle stretch, not every 20 s while another client of the
                same runtime keeps the model loaded
  gpu       12  the panel's button that puts the model on the GPU loads it and says so; a screen the busy GPU could
                not read at all leaves no card when the watching asked for it (a quiet back-off and one note), and a
                card when Reanalyze was pressed
  gap       13  the example check reads with this PC's model only between analyses: the next screen's
                first pass does not wait behind it, and the check starts over after that analysis, keeping what it read
"""
import asyncio
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-server-review-"), SIDENOTE_STALL_WARN_SEC="0",
                  SIDENOTE_STALL_EXIT_SEC="0", SIDENOTE_SEARCH_URL="")
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

import server.analyzer as an  # noqa: E402
from server.analyzer import Engines, FastResult, LoadStopped, LocalLlmAnalyzer, make_engines  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.heads import head_of  # noqa: E402
from server.pipeline import Hooks, Pipeline  # noqa: E402
from server.settings import SETTINGS  # noqa: E402
import server.app as _app  # noqa: E402

# A code runner stands in: the checks' runs are this suite's own (run_cases and runner_exec patched where they run), and
# with no runner set up the server starts no check at all (server/app.py runner_here)
_app.runner_here = lambda: True

PASS, FAIL = [], []
ORIGIN = {"origin": "http://127.0.0.1:8777"}
NONE_HEAD = "TYPE: none\n"
DEEP_HEAD = "TYPE: algorithm\nROUTE: deep\nANSWER: 목업\nREGION: 100 120 600 700\n"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f"  - {detail}" if detail and not ok else ""))


async def _none(*a, **k):
    return None


async def _yes(*a, **k):
    return True


class FakeFrame:
    """A screen as prepare_frame makes one (the fields the pipeline reads)."""

    def __init__(self, w=640, h=400):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, format="PNG")
        self.full_png = buf.getvalue()
        self.model_b64 = base64.b64encode(self.full_png).decode()
        self.thumb_url = "data:image/png;base64," + self.model_b64
        self.ts, self.width, self.height = 0.0, w, h
        self.extra_b64, self.windows, self.ocr_lines, self.sig = [], None, None, b""
        self.model_box = (0.0, 0.0, 1.0, 1.0)


def png_b64(color="white", w=640, h=400, text_rows=6, seed=0, x0=40):
    """A screen with dark bars standing for lines of text (the change detector reads edges)."""
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    for r in range(text_rows):
        d.rectangle([x0, 40 + r * 40 + seed, x0 + 300 + (r * 37 + seed) % 200, 52 + r * 40 + seed], fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def frame_msg(data, extra=None):
    """What the capture program sends for a screen, with the problem scrolled together when there is one."""
    return json.dumps({"type": "frame", "data": data, **({"extra": extra} if extra else {})})


class Panel:
    """Reads every panel message in a thread, with the time it came."""

    def __init__(self, ws):
        self.ws, self.msgs, self.t0 = ws, [], time.time()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                m = json.loads(self.ws.receive_text())
                m["_t"] = round(time.time() - self.t0, 2)
                self.msgs.append(m)
        except Exception:
            pass

    def wait(self, pred, timeout=30, after=0):
        end = time.time() + timeout
        while time.time() < end:
            for m in self.msgs[after:]:
                if pred(m):
                    return m
            time.sleep(0.05)
        return None

    def of(self, kind, **match):
        return [m for m in self.msgs if m.get("type") == kind and all(m.get(k) == v for k, v in match.items())]


def started(trigger=None, label=None):
    """A predicate for an analysis_start, by trigger and by the label it shows (the transcript)."""
    return lambda m: (m.get("type") == "analysis_start" and (trigger is None or m.get("trigger") == trigger)
                      and (label is None or m.get("transcript") == label))


def done_of(seq):
    return lambda m: m.get("type") == "analysis_done" and m.get("id") == seq


@contextlib.contextmanager
def server(**settings):
    """An in-process server in mock mode, a panel and a capture program connected to it, and `settings` for the run.
    The module keeps its state from one run to the next, so it starts from a clean one."""
    from starlette.testclient import TestClient
    import server.app as A
    A.STATE.__init__()
    # What the last run left to take up after a restart: each run here is a server that has never run, or its first screen is taken for the last one's
    if A.telemetry.LOG_DIR:
        (Path(A.telemetry.LOG_DIR) / ".restart.npz").unlink(missing_ok=True)
    saved = dict(SETTINGS.values)
    try:
        with TestClient(A.app, base_url="http://127.0.0.1:8777") as c:
            SETTINGS.values.update({"local_llm": True, "agent_mode": "hard", "agent_payload": "crop",
                                    "agent_confirm": False, "autocheck": False, "roi_box": None, **settings})
            A.STATE.local, A.STATE.agent = {"ok": True}, {"ok": True}
            with c.websocket_connect("ws://127.0.0.1:8777/panel", headers=ORIGIN) as pws, \
                    c.websocket_connect("ws://127.0.0.1:8777/ingest", headers=ORIGIN) as ws:
                p = Panel(pws)
                ws.send_text(json.dumps({"type": "hello", "info": "capture/test", "screen": True, "audio": True,
                                         "no_audio": False, "monitor": 1, "flags": {}}))
                time.sleep(0.3)
                try:
                    yield A, c, p, ws, pws
                finally:
                    # what the watching left running stops in the server's own loop, before the loop goes
                    for stop in (A.cancel_retry, A.cancel_check, A.cancel_verify):
                        c.portal.call(stop)
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)


def first_answer(p, ws):
    """The first screen, answered (by Claude in the hard mode: the mock first pass calls it an algorithm)."""
    ws.send_text(frame_msg(png_b64()))
    return p.wait(lambda m: m.get("type") == "analysis_done", timeout=30)


def say(A, text):
    """What the speech pass leaves behind for a finished utterance with a question word in it."""
    sr = A.STATE.audio_sr
    A.STATE.utterances.append({"start": 0, "end": 3 * sr, "text": text, "ts": time.time()})
    A.STATE.voice_asked, A.STATE.voice_runs, A.STATE.voice_pending = True, 1, True


@contextlib.contextmanager
def patched(obj, name, value):
    """`obj.name` is `value` for the block."""
    was = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, was)


# ---------- 1: the first-token hand-off ----------

def make_pipeline(notes, stages):
    engines = make_engines(CONFIG)   # MockLocal and the mock Claude

    async def notice(t):
        notes.append(t)

    async def stage(seq, name, detail, restart=False, **_):
        stages.append(name)
    hooks = Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=notice, stage=stage, confirm=_yes,
                  agent_failed=_none)
    return Pipeline(engines, hooks), engines


async def handoff():
    print("\n[1 a first pass that brings nothing by its deadline]")
    saved = dict(SETTINGS.values)
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               extract=True, roi_box=None)

        async def run(plan, problem=""):
            """solve() with the first pass answering by `plan` ("slow", "none", "deep" in turn) and the writing out
            finding `problem`. Gives back (outcome or the exception, what each part was asked)."""
            notes, stages = [], []
            pipe, eng = make_pipeline(notes, stages)
            asked = {"fast": [], "extract": 0, "deep": 0, "agent": []}
            plan = list(plan)

            async def fast(images, text, on_delta, *, want_region=False, escalate_all=False, first_deadline=None):
                asked["fast"].append(first_deadline)
                step = plan.pop(0) if plan else "slow"
                if step == "slow":   # what LocalLlmAnalyzer.fast gives back when no token came by the deadline
                    return FastResult(text=None, head="", type="", route="", slow=True)
                if step == "none":
                    await on_delta(NONE_HEAD)
                    return FastResult(text=NONE_HEAD, head=NONE_HEAD, type="none")
                return FastResult(text=None, head=DEEP_HEAD, type="algorithm", route="deep")

            async def extract(images=(), speech=""):
                asked["extract"] += 1
                return problem

            async def deep(*a, **k):
                asked["deep"] += 1
                return an.AnalysisResult(text=an.MOCK_ALGO, model="mock-local (think)")
            plain_run = eng.agent.run

            async def claude_run(images, text, on_delta):
                asked["agent"].append(len(images))
                return await plain_run(images, text, on_delta)
            eng.local.fast, eng.local.extract, eng.local.deep, eng.agent.run = fast, extract, deep, claude_run
            try:
                out = await pipe.solve(1, FakeFrame(), "", False, _none)
            except Exception as exc:   # the hand-off may end the analysis with an error, which the card shows
                out = exc
            return out, asked, notes

        out, asked, notes = await run(["slow", "none"])
        check("an empty screen on a busy GPU ends at the second look: nothing to solve, no writing out, no toast, "
              "no thinking pass, nothing to Claude",
              not isinstance(out, Exception) and head_of(out.text)[0] == "none" and asked["extract"] == 0
              and asked["deep"] == 0 and not asked["agent"] and not notes and len(asked["fast"]) == 2,
              f"out={getattr(out, 'text', out)!r} asked={asked} notes={notes}")
        out, asked, notes = await run(["slow", "deep"], problem="두 수의 합을 구하시오.")
        check("a problem goes to Claude as its crop, from the place the second look read, without writing it out",
              not isinstance(out, Exception) and out.engine == "agent" and asked["agent"] == [1]
              and asked["extract"] == 0 and asked["deep"] == 0
              and any("문제 부분 화면" in s.get("what", "") for s in out.sent),
              f"out={getattr(out, 'engine', out)!r} asked={asked} sent={getattr(out, 'sent', None)}")
        out, asked, notes = await run(["slow", "slow"])
        check("when the second look brings nothing either, nothing is sent, written out or thought about, and the "
              "card says why", isinstance(out, TimeoutError) and asked["extract"] == 0 and asked["deep"] == 0
              and not asked["agent"] and "nothing went to the agent" in str(out),
              f"out={out!r} asked={asked} notes={notes}")
    finally:
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)
    await handoff_model()


async def handoff_model():
    """The second look runs on the model this PC switches to while the GPU is held."""
    saved, opts = dict(SETTINGS.values), dict(SETTINGS.dynamic_options)
    deadline = CONFIG.local_first_token_sec
    main, small = "sidenote-gemma4:26b", "sidenote-gemma4:e4b"   # a model named, not "auto": the test is about the switch
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    local._ready = _none   # no model to load in a test
    local._warm.add(local.model)   # warm, so the short limit is the one under test
    asked = []

    async def stream(body, on_delta):
        """The main model is stuck behind another program; the smaller one answers that nothing is there."""
        asked.append(body["model"])
        if body["model"] != small:
            await asyncio.sleep(30)
        await on_delta(NONE_HEAD)
        return NONE_HEAD, {"output_tokens": 3}, [], {"finish": "stop", "thought": ""}
    local._stream = stream
    try:
        SETTINGS.values.update(local_llm=True, agent_mode="hard", agent_payload="crop", agent_confirm=False,
                               extract=True, roi_box=None, local_model=main, local_busy_model=small)
        SETTINGS.set_options("local_busy_model", [("", "바꾸지 않음"), (small, small)])
        CONFIG.local_first_token_sec = 0.3
        claude = make_engines(CONFIG).agent
        pipe = Pipeline(Engines(local, claude), Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=_none,
                                                      stage=_none, confirm=_yes, agent_failed=_none))
        out = await pipe.solve(2, FakeFrame(), "", False, _none)
        check("the second look is asked of the busy-GPU model, which reads the empty screen as empty",
              asked[:2] == [main, small] and out.engine == "local" and head_of(out.text)[0] == "none"
              and not claude.calls, f"asked={asked} engine={out.engine} text={out.text!r} claude={len(claude.calls)}")
    finally:
        CONFIG.local_first_token_sec = deadline
        SETTINGS.values.clear()
        SETTINGS.values.update(saved)
        SETTINGS.dynamic_options.clear()
        SETTINGS.dynamic_options.update(opts)


# ---------- 2: which scrolled problems continue the last answer ----------

def misfile():
    print("\n[2 a problem scrolled together that is not the last answer's]")
    plain = an.MockAnalyzer.run

    async def slow_run(self, images, text, on_delta):   # Claude takes a few seconds, as it does
        await asyncio.sleep(2.5)
        return await plain(self, images, text, on_delta)
    with patched(an.MockAnalyzer, "run", slow_run), server() as (A, c, p, ws, pws):
        a = first_answer(p, ws)
        time.sleep(5)                                            # the screen moves on to problem B
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(color="#f4f4f4", text_rows=9, seed=17, x0=90)))
        b = p.wait(started("screen"), after=n)
        time.sleep(0.5)                                          # B is being answered; B is scrolled
        ws.send_text(frame_msg(png_b64(color="#f4f4f4", text_rows=9, seed=29, x0=90),
                               [png_b64(color="#f4f4f4", h=900, text_rows=20, seed=3, x0=90)]))
        nxt = p.wait(lambda m: m.get("type") == "analysis_start" and m.get("id") != (b or {}).get("id"),
                     after=n, timeout=20)
        check("a new problem whose first analysis its scroll stopped is solved as its own, not as the last "
              "answer's continuation", bool(a and b and nxt) and nxt.get("trigger") == "screen"
              and nxt.get("transcript") != A.t(A.CONTINUE_LABEL) and nxt.get("pages", 0) >= 1, str(nxt))

    with server(voice_auto=True) as (A, c, p, ws, pws):
        a = first_answer(p, ws)
        n = len(p.msgs)
        say(A, "프로세스와 스레드의 차이가 뭐야?")                   # a question heard, answered after the screen
        v = p.wait(started("voice"), after=n, timeout=20)
        vd = p.wait(done_of((v or {}).get("id")), timeout=20)
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))
        nxt = p.wait(started(), after=n, timeout=20)
        check("a problem scrolled together after a spoken question's answer is not filed under that answer",
              bool(a and vd and nxt) and nxt.get("trigger") == "screen" and nxt.get("transcript") != A.t(A.CONTINUE_LABEL),
              f"voice done={bool(vd)} next={nxt}")

    with server() as (A, c, p, ws, pws):
        a = first_answer(p, ws)
        time.sleep(5)
        n = len(p.msgs)
        # Problem B is on screen and is scrolled at once, before anything analyzed it: its stitched page
        # comes 0.3 s after its first screen, which the worker is still waiting on to come to rest.
        ws.send_text(frame_msg(png_b64(color="#202020", text_rows=9, seed=17, x0=90)))
        time.sleep(0.3)
        ws.send_text(frame_msg(png_b64(color="#202020", text_rows=9, seed=29, x0=90),
                               [png_b64(color="#202020", h=900, text_rows=20, seed=3, x0=90)]))
        nxt = p.wait(started(), after=n, timeout=20)
        check("a problem scrolled together on a screen that had moved on from the last answer's is solved as its own",
              bool(a and nxt) and nxt.get("trigger") == "screen" and nxt.get("transcript") != A.t(A.CONTINUE_LABEL),
              str(nxt))

    with server() as (A, c, p, ws, pws):
        a = first_answer(p, ws)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))       # scrolled: continued
        c1 = p.wait(started(label=A.t(A.CONTINUE_LABEL)), timeout=20)
        p.wait(done_of((c1 or {}).get("id")), timeout=20)
        ws.send_text(frame_msg(png_b64(seed=7)))   # the join ended: the screen it ended on comes once more, alone
        time.sleep(1.0)
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(seed=13), [png_b64(h=900, text_rows=22, seed=5)]))   # read on: joined again
        c2 = p.wait(started(), after=n, timeout=20)
        check("(guard, passed before too) reading on in a second join still fills the same answer out",
              bool(a and c1 and c2) and c2.get("transcript") == A.t(A.CONTINUE_LABEL) and c2.get("about") == a.get("id"),
              str(c2))


# ---------- 3: a spoken question a screen change stopped ----------

def voice():
    print("\n[3 a spoken question a screen change stopped]")
    plain = an.MockLocal.fast
    asked = []

    async def fast(self, images, text, on_delta, **kw):
        if text.startswith("[음성으로 들어온 문제]"):
            asked.append(text)
            await asyncio.sleep(4.0)      # a spoken question takes a while to answer (Claude, the thinking pass)
        return await plain(self, images, text, on_delta, **kw)
    question = "프로세스와 스레드의 차이가 뭐야?"
    with patched(an.MockLocal, "fast", fast), server(voice_auto=True) as (A, c, p, ws, pws):
        first_answer(p, ws)
        time.sleep(2)
        n = len(p.msgs)
        say(A, question)
        v = p.wait(started("voice"), after=n, timeout=20)
        time.sleep(1.0)
        ws.send_text(frame_msg(png_b64(color="#202020", text_rows=10, seed=11, x0=10)))   # the screen moves on
        s = p.wait(started("screen"), after=n, timeout=20)
        r = p.wait(lambda m: started("voice")(m) and m.get("id") != (v or {}).get("id"), after=n, timeout=25)
        check("the spoken question is asked again after the screen that stopped it",
              bool(v and s and r) and r["_t"] > s["_t"] and r.get("transcript") == question
              and bool(p.of("analysis_cancelled", id=v["id"])), f"voice={v} screen={s} again={r}")
        time.sleep(1.0)
        ws.send_text(frame_msg(png_b64(color="#305030", text_rows=4, seed=23, x0=200)))   # and on again
        time.sleep(10)
        voices = [m["id"] for m in p.msgs[n:] if started("voice")(m)]
        check("only once: a screen change that stops it again does not bring it back a third time",
              len(voices) == 2 and bool(r and p.of("analysis_cancelled", id=r["id"])), f"voice starts {voices}")


# ---------- 4: the spend brake ----------

def brake():
    print("\n[4 a problem scrolled together while Claude's brake holds]")
    with server() as (A, c, p, ws, pws):
        a = first_answer(p, ws)
        A.PIPELINE.spend.cool_until, A.PIPELINE.spend.ran = time.time() + 300, 6   # the row of empty answers trips it
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))
        s = p.wait(started("screen"), after=n, timeout=20)
        d = p.wait(done_of((s or {}).get("id")), timeout=30)
        check("it is solved as a problem by this PC's model instead of being dropped at the brake",
              bool(a and a.get("engine") == "agent" and s and d) and s.get("pages", 0) >= 1
              and d.get("engine") == "local", f"first={a and a.get('engine')} start={s} done={d and d.get('engine')}")


# ---------- 5: the retry and the continuation ----------

def slots():
    print("\n[5 the retry and the continuation, each in a slot of its own]")
    import server.app as A
    calls = []
    plain = an.MockAnalyzer.run
    timing = {"[이어 보기]": 10.0, "[예제 실패]": 1.0}

    async def slow_run(self, images, text, on_delta):
        kind = next((k for k in timing if k in text), "")
        calls.append(kind)
        await asyncio.sleep(timing.get(kind, 1.0))
        return await plain(self, images, text, on_delta)

    async def failing_check(pipeline, frame, outcome, run, cases=None, any_type=False, **kw):
        await asyncio.sleep(check_wait[0])   # reading the examples and running the code takes a while
        if any_type:
            return {"passed": 2, "total": 2}
        return {"passed": 1, "total": 2, "fails": [{"input": [[3, 2, 4], 6], "expected": [1, 2], "got": [0, 0]}],
                "cases": {"cases": []}}
    check_wait = [6.0]
    with patched(an.MockAnalyzer, "run", slow_run), patched(A, "check_code", failing_check), \
            server(autocheck=True) as (A, c, p, ws, pws):
        a = first_answer(p, ws)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))   # scrolled right after the answer
        cont = p.wait(started(label=A.t(A.CONTINUE_LABEL)), timeout=20)
        retry = p.wait(started("retry"), timeout=20)
        time.sleep(0.3)
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(color="#eeeeee", text_rows=3, seed=61, x0=200)))   # the next problem
        newer = p.wait(started("screen"), after=n, timeout=20)
        nd = p.wait(done_of((newer or {}).get("id")), timeout=20)
        time.sleep(1.0)
        cid, rid = (cont or {}).get("id"), (retry or {}).get("id")
        # the retry is stopped as it stands: still being written, or its fixed code still being run
        retry_stopped = bool(p.of("analysis_cancelled", id=rid) or p.of("check", id=rid, cancelled=True))
        check("a retry starting while the continuation runs does not orphan it: the next answer stops both",
              bool(a and cont and retry and nd) and bool(p.of("analysis_cancelled", id=cid))
              and not p.of("analysis_done", id=cid) and retry_stopped,
              f"continuation cancelled={bool(p.of('analysis_cancelled', id=cid))} "
              f"done={bool(p.of('analysis_done', id=cid))} retry stopped={retry_stopped} newer done={bool(nd)}")

    timing.update({"[예제 실패]": 7.0, "[이어 보기]": 1.0})
    check_wait[0] = 0.3
    with patched(an.MockAnalyzer, "run", slow_run), patched(A, "check_code", failing_check), \
            server(autocheck=True) as (A, c, p, ws, pws):
        first_answer(p, ws)
        retry = p.wait(started("retry"), timeout=20)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))   # scrolled while it is rewritten
        cont = p.wait(started(label=A.t(A.CONTINUE_LABEL)), timeout=20)
        rd = p.wait(done_of((retry or {}).get("id")), timeout=20)
        check("a continuation starting while the retry runs does not stop the retry",
              bool(retry and cont and rd) and cont["_t"] < rd["_t"]
              and not p.of("analysis_cancelled", id=retry["id"]),
              f"retry={retry and retry['id']} continuation={cont and cont['id']} retry done={bool(rd)} "
              f"cancelled={bool(retry and p.of('analysis_cancelled', id=retry['id']))}")


# ---------- 6: an analysis that finds nothing ----------

def remark():
    print("\n[6 a remark heard while the continuation runs]")
    plain_run, plain_fast = an.MockAnalyzer.run, an.MockLocal.fast

    async def slow_run(self, images, text, on_delta):
        if "[이어 보기]" in text:
            await asyncio.sleep(5.0)
        return await plain_run(self, images, text, on_delta)

    async def fast(self, images, text, on_delta, **kw):
        if text.startswith("[음성으로 들어온 문제]"):   # a line of a video: nothing to solve
            await on_delta(NONE_HEAD)
            return FastResult(text=NONE_HEAD, head=NONE_HEAD, type="none")
        return await plain_fast(self, images, text, on_delta, **kw)
    with patched(an.MockAnalyzer, "run", slow_run), patched(an.MockLocal, "fast", fast), \
            server(voice_auto=True) as (A, c, p, ws, pws):
        first_answer(p, ws)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))
        cont = p.wait(started(label=A.t(A.CONTINUE_LABEL)), timeout=20)
        time.sleep(1.0)
        say(A, "오늘 회의는 여기까지 하겠습니다 왜")
        v = p.wait(started("voice"), timeout=10)
        cd = p.wait(done_of((cont or {}).get("id")), timeout=20)
        check("the continuation goes on through an analysis that finds nothing, and is answered",
              bool(cont and v and cd) and not p.of("analysis_cancelled", id=cont["id"]),
              f"continuation={cont and cont['id']} voice={bool(v)} done={bool(cd)}")


# ---------- 7, 8: a drawn region ----------

def region():
    print("\n[7 a problem scrolled together while a region is drawn]")
    with server() as (A, c, p, ws, pws):
        ws.send_text(frame_msg(png_b64()))
        time.sleep(0.3)
        pws.send_text(json.dumps({"type": "setting", "key": "roi_box", "value": [0.05, 0.05, 0.6, 0.45]}))
        a = p.wait(lambda m: m.get("type") == "analysis_done", timeout=20)
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(seed=7), [png_b64(h=900, text_rows=18)]))
        s = p.wait(started(), after=n, timeout=20)
        d = p.wait(done_of((s or {}).get("id")), timeout=20)
        tiles = list(A.STATE.latest_frame.extra_b64)   # the stitched pane as the server cut it into tiles
        sent = [x["images"] for x in A.ENGINES.agent.calls]
        check("it is solved from the drawn region, not continued with the whole stitched pane",
              bool(a and s and d and tiles) and s.get("transcript") != A.t(A.CONTINUE_LABEL)
              and s.get("trigger") == "screen" and tiles not in sent and len(sent[-1]) == 1,
              f"start={s} images sent={[len(x) for x in sent]}")

    print("\n[8 a capture program reconnecting]")
    with server() as (A, c, p, ws, pws):
        SETTINGS.values["roi_box"] = [0.1, 0.1, 0.5, 0.5]
        with c.websocket_connect("ws://127.0.0.1:8777/ingest", headers=ORIGIN) as again:
            again.send_text(json.dumps({"type": "hello", "info": "capture/win32", "screen": True, "audio": True,
                                        "no_audio": False, "monitor": 1}))   # a reconnect's hello: no flags
            time.sleep(0.4)
        check("a reconnect keeps the drawn region (only the hello of a start clears it)",
              SETTINGS.get("roi_box") == [0.1, 0.1, 0.5, 0.5], str(SETTINGS.get("roi_box")))


# ---------- 9: the same pages ----------

def pages():
    print("\n[9 the same stitched pages again]")
    with server() as (A, c, p, ws, pws):
        first_answer(p, ws)
        tile = png_b64(h=900, text_rows=18)
        ws.send_text(frame_msg(png_b64(seed=7), [tile]))           # scrolled down: the page is joined
        c1 = p.wait(started(label=A.t(A.CONTINUE_LABEL)), timeout=20)
        p.wait(done_of((c1 or {}).get("id")), timeout=20)
        tiles = list(A.STATE.latest_frame.extra_b64)                # the page as the server cut it into tiles
        n = len(p.msgs)
        ws.send_text(frame_msg(png_b64(seed=0), [tile]))           # back up: the same page comes again
        again = p.wait(started(), after=n, timeout=8)
        same = [x for x in A.ENGINES.agent.calls if x["images"] == tiles]
        check("scrolling back up does not send the same pages to Claude again", bool(c1 and tiles) and again is None
              and len(same) == 1, f"second start={again} turns with those pages={len(same)}")


# ---------- 10: the first-token deadline behind this server's own request ----------

class FakeClient:
    """The local model's server: the writing out streams a little at a time, the first pass gets nothing."""

    def __init__(self):
        self.opened = 0

    def stream(self, method, url, json=None):
        outer = self
        busy = (json or {}).get("max_tokens") == 3000   # the writing out of a problem (extract)

        class Resp:
            status_code = 200

            async def aiter_lines(self):
                outer.opened += 1
                if not busy:
                    await asyncio.sleep(30)                 # the first pass: nothing comes
                for _ in range(10):
                    await asyncio.sleep(0.1)
                    yield "data: " + __import__("json").dumps({"choices": [{"delta": {"content": "글 "}}]})
                yield "data: [DONE]"

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


async def shared():
    print("\n[10 a first pass waiting behind this server's own request]")
    local = LocalLlmAnalyzer(CONFIG)
    await local._client.aclose()
    local._ready = _none
    local._warm.add(local.model)    # warm: the short limit is the one under test
    local._client = FakeClient()
    other = asyncio.ensure_future(local.extract([FakeFrame().model_b64]))   # the example check's reading, say
    await asyncio.sleep(0.05)
    res = await local.fast([FakeFrame().model_b64], "q", _none, first_deadline=0.3)
    await other
    check("the screen still goes on, but the GPU is not counted busy and the smaller model is not swapped in",
          res.slow and not local.pace.busy(), f"slow={res.slow} busy={local.pace.busy()}")


# ---------- 11: the idle release ----------

async def release():
    print("\n[11 the idle release while another client keeps the model loaded]")
    import server.app as A
    eng = make_engines(CONFIG)
    unloads = []

    async def held():          # the runtime lists the model whatever this server does: another client uses it
        return {"model": eng.local.model, "vram_gb": 0.0}

    async def unload(model=None):
        unloads.append(model)
        return True
    eng.local.loaded, eng.local.unload = held, unload
    eng.local.last_used = time.time() - 3600       # this server last used it an hour ago
    real_sleep = asyncio.sleep
    quick = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("__")})
    quick.sleep = lambda s, *a, **k: real_sleep(0.01)   # ten seconds of the watch loop in a hundredth
    was = (A.ENGINES, A.PIPELINE, A.asyncio, A.STATE.local, A.STATE.agent, dict(SETTINGS.values))
    try:
        A.ENGINES, A.PIPELINE, A.asyncio = eng, None, quick
        A.STATE.local = {"ok": True, "method": "local", "model": eng.local.model, "loaded": await held()}
        A.STATE.agent = {"ok": True, "method": "mock"}
        SETTINGS.values.update(gpu_idle_min=10, local_llm=True)
        task = asyncio.ensure_future(A.engine_watch())
        await real_sleep(0.4)                       # some thirty turns of the loop, fifteen status checks
        once = len(unloads)
        eng.local.last_used = time.time() - 3500    # this server used the model again since, long ago too
        await real_sleep(0.4)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        check("the GPU is given back once for the idle stretch, not again at every status check",
              once == 1, f"{once} releases")
        check("...and once for the next stretch, after this server used the model again", len(unloads) == 2,
              f"{len(unloads)} releases in all")
    finally:
        A.ENGINES, A.PIPELINE, A.asyncio, A.STATE.local, A.STATE.agent = was[:5]
        SETTINGS.values.clear()
        SETTINGS.values.update(was[5])


# ---------- 11b: the local server that starts beside this one ----------

async def starting():
    print("\n[11b the local server starting beside this one]")
    import server.app as A
    eng = make_engines(CONFIG)
    down = {"ok": False, "method": "local", "model": eng.local.model, "error": "the local LLM server does not answer"}
    real_sleep = asyncio.sleep
    was = (A.ENGINES, A.PIPELINE, A.asyncio, A.STATE.local, A.STATE.agent, A.check_local, A.broadcast_engines)

    async def watch(answers):
        """engine_watch from a state of `down` with the local server's next answers: the waits it asked for, and the
        panels told, once it has gone on past the first looks."""
        asked = []
        told = []
        looks = iter(answers)

        def sleep(s, *a, **k):
            asked.append(s)
            return real_sleep(0.001)
        quick = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("__")})
        quick.sleep = sleep

        async def check():
            return dict(next(looks, answers[-1]))

        async def tell():
            told.append(dict(A.STATE.local))
        A.ENGINES, A.PIPELINE, A.asyncio, A.check_local, A.broadcast_engines = eng, None, quick, check, tell
        A.STATE.local, A.STATE.agent = dict(down), {"ok": True, "method": "mock"}
        task = asyncio.ensure_future(A.engine_watch())
        await real_sleep(0.3)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return asked, told

    try:
        up = {"ok": True, "method": "local", "model": eng.local.model, "loaded": None}
        asked, told = await watch([down, down, up])
        check("a local server that is starting is looked at every 2 s, and answers after 6 s, not after the 20 s of a normal look",
              asked[:3] == [A.STARTING_EVERY] * 3 and asked[3] == 10, f"waits {asked[:5]}")
        check("...and the panels are told as soon as it answers", bool(told) and told[0].get("ok"), f"told {told[:1]}")
        asked, _ = await watch([down])
        short = [s for s in asked if s == A.STARTING_EVERY]
        check("one that does not come goes back to the normal looks after a minute", len(short) == A.STARTING_LOOKS and asked[A.STARTING_LOOKS] == 10,
              f"{len(short)} short looks")
        A.STATE.local = {"ok": False, "method": "local", "model": eng.local.model, "missing": True}
        asked = []

        def sleep_missing(s, *a, **k):
            asked.append(s)
            return real_sleep(0.001)
        quick = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("__")})
        quick.sleep = sleep_missing
        A.asyncio = quick
        task = asyncio.ensure_future(A.engine_watch())
        await real_sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        check("a server that answered without the model is not looked at more often: it is up", asked[:1] == [10], f"waits {asked[:3]}")
    finally:
        A.ENGINES, A.PIPELINE, A.asyncio, A.STATE.local, A.STATE.agent, A.check_local, A.broadcast_engines = was


# ---------- 12: the GPU from the panel, and a GPU too busy to read a screen ----------

def gpu():
    print("\n[12 the model put on the GPU from the panel, and a screen the busy GPU could not read]")
    from server.pipeline import GpuBusy
    with server() as (A, c, p, ws, pws):
        loads = []

        local = A.ENGINES.local

        async def load():
            loads.append(time.time())
            local._loaded = True   # as the stand-in's own load does: the panel's button reads this back
        with patched(A.ENGINES.local, "load", load):
            n = len(p.msgs)
            pws.send_text(json.dumps({"type": "gpu_load"}))
            note = p.wait(lambda m: m.get("type") == "notice" and "GPU에 올림" in m.get("text", ""), after=n, timeout=10)
        check("the panel's load button puts this PC's model on the GPU and says so", len(loads) == 1 and bool(note),
              f"loads={len(loads)} note={note}")

        # The load path
        unloads = []
        async def count_unload(*a, **k):
            unloads.append(1)
            return True
        with patched(local, "unload", count_unload):
            n = len(p.msgs)
            pws.send_text(json.dumps({"type": "gpu_load_cancel"}))
            late = p.wait(lambda m: m.get("type") == "notice" and "이미 올림" in m.get("text", ""), after=n, timeout=10)
        check("a cancel pressed after the load ended takes nothing off the GPU", bool(late) and not unloads, f"{late} unloads={len(unloads)}")

        async def said_nothing_loaded(*a, **k):
            return None
        with patched(local, "loaded", said_nothing_loaded):
            n = len(p.msgs)
            pws.send_text(json.dumps({"type": "gpu_load"}))
            refused = p.wait(lambda m: m.get("type") == "notice" and "올리기 실패" in m.get("text", ""), after=n, timeout=10)
        check("a load that left nothing on the GPU is not announced as done", bool(refused), str(refused))

        async def stopped(*a, **k):
            raise LoadStopped("stopped")
        with patched(local, "load", stopped):
            n = len(p.msgs)
            pws.send_text(json.dumps({"type": "gpu_load"}))
            quiet = p.wait(lambda m: m.get("type") == "notice" and "올리기 멈춤" in m.get("text", ""), after=n, timeout=10)
        check("a load stopped on purpose blames no hardware", bool(quiet) and "메모리" not in quiet.get("text", ""), str(quiet))

        check("the account is not in what /health and /stats are built from", "account" not in A.engines_status()["agent"])
        check("it is in what the panel gets", "account" in A.panel_engines()["agent"])

        async def busy(*a, **k):
            raise GpuBusy("local LLM: no first token in 6 s from either model")
        with patched(A.PIPELINE, "solve", busy):
            n = len(p.msgs)
            ws.send_text(frame_msg(png_b64(seed=21)))
            gone = p.wait(lambda m: m.get("type") == "analysis_cancelled" and m.get("reason") == "gpu_busy", after=n, timeout=20)
            time.sleep(0.5)
            errs = [m for m in p.msgs[n:] if m.get("type") == "error"]
            notes = [m for m in p.msgs[n:] if m.get("type") == "notice" and "GPU" in m.get("text", "")]
            check("a screen the watching asked about leaves no card when the busy GPU could not read it: one note, "
                  "and the watching backs off", bool(gone) and not errs and len(notes) == 1 and A.STATE.retry_after > time.monotonic(),
                  f"cancelled={gone} errors={errs} notes={len(notes)} retry_in={A.STATE.retry_after - time.monotonic():.0f}s")
            A.STATE.retry_after = 0.0
            n = len(p.msgs)
            pws.send_text(json.dumps({"type": "reanalyze"}))
            err = p.wait(lambda m: m.get("type") == "error", after=n, timeout=20)
        check("Reanalyze on a GPU too busy to read still gets its card, since the person at the PC is waiting on it", bool(err),
              f"error={err}")


# ---------- 13: the example check reads between analyses ----------

def gap():
    print("\n[13 the example check reads with this PC's model between analyses, not in front of them]")
    # The check of an answer once read its examples for 84 s on a busy GPU, and the first passes of the next
    # two screens waited behind it, gave up at 6 s and were taken up again 15 and 30 s later. The model serves one
    # request at a time here (a lock, as Ollama does with one slot), so a pass asked during a read waits for it.
    import server.pipeline as P
    marks, model, t0 = [], {}, [time.time()]
    delay = {"cases": 3.0, "text": 0.2, "run": 0.0}

    def mark(what):
        marks.append((round(time.time() - t0[0], 2), what))

    async def serving(what, seconds):
        """One request to the model: it waits for the model, then takes `seconds`, and says where it got."""
        lock = model.setdefault("lock", asyncio.Lock())   # made in the server's own loop
        async with lock:
            mark(what)
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                mark(what + " cut")
                raise
            mark(what + " read")

    async def cases(self, images=(), problem=""):
        await serving("cases", delay["cases"])
        return {"function": "solution", "cases": [{"args": [1], "expected": 2}]}

    async def extract(self, images=(), speech=""):
        await serving("text", delay["text"])
        return "입출력 예\nsolution(1) -> 2"

    plain_fast, passes = an.MockLocal.fast, [0]

    async def fast(self, images, text, on_delta, **k):   # the first screen holds a problem, the next ones nothing
        passes[0] += 1
        await serving(f"pass {passes[0]}", 0.1)
        if passes[0] == 1:
            return await plain_fast(self, images, text, on_delta, **k)
        return FastResult(text=NONE_HEAD, head=NONE_HEAD, type="none", route="")

    async def ran(text, found, run):   # the runner sandbox, as it answers when the code is right (no model in it)
        mark("run")
        try:
            await asyncio.sleep(delay["run"])
        except asyncio.CancelledError:
            mark("run cut")
            raise
        mark("run done")
        return {"passed": 1, "total": 1, "how": "function", "lang": "python"}

    def code(pipeline, frame, outcome, any_type=False):   # a coding answer with code the runner can run
        return ("python", "def solution(x):\n    return x + 1") if head_of(outcome.text)[0] != "none" else None

    def at(what, n=1):
        """When `what` happened the n-th time (None: it did not)."""
        hits = [t for t, w in marks if w == what]
        return hits[n - 1] if len(hits) >= n else None

    for cut in ("cases", "text", "run"):
        marks.clear()
        model.clear()   # a lock is bound to the loop it was first waited on in, and each server() has its own
        passes[0] = 0
        delay.update({k: 8.0 if cut == k else 0.2 for k in ("cases", "text", "run")})   # past the settle
        with patched(an.MockLocal, "cases", cases), patched(an.MockLocal, "extract", extract), \
                patched(an.MockLocal, "fast", fast), patched(P, "run_cases", ran), patched(P, "checkable", code), \
                patched(P, "seen_cases", lambda found, text: found), server(autocheck=True) as (A, c, p, ws, pws), \
                patched(A, "checkable", code):
            t0[0] = time.time()
            first_answer(p, ws)
            end = time.time() + 10
            while time.time() < end and at(cut) is None:   # the check is reading: the read about to be cut has begun
                time.sleep(0.02)
            time.sleep(0.3)
            n = len(p.msgs)
            sent_at = time.time()
            ws.send_text(frame_msg(png_b64(color="#eeeeee", text_rows=3, seed=61, x0=200)))   # the next screen
            newer = p.wait(started("screen"), after=n, timeout=20)
            nd = p.wait(done_of((newer or {}).get("id")), timeout=20)
            res = p.wait(lambda m: m.get("type") == "check" and ("passed" in m or m.get("cancelled")), after=n,
                         timeout=20)
            began, second = at(cut), at("pass 2")
            print(f"    cut at {cut}: {marks}\n    sent at {round(sent_at - t0[0], 2)}, analysis began at "
                  f"{round((newer or {}).get('_t', -1) + p.t0 - t0[0], 2)}, ended at {round((nd or {}).get('_t', -1) + p.t0 - t0[0], 2)}")
            if cut == "run":
                # The runner holds no model, and a run cut here goes on in the runner all the
                # same (a thread) while the check sends it again; the analysis does not wait for it either way
                check("a run on the code runner is not cut for an analysis, nor sent again",
                      bool(newer and nd) and at("run cut") is None and at("run", 2) is None and at("run done") is not None
                      and second is not None and second < at("run done"), f"marks {marks}")
                check("...and the check's result comes once the run is done", bool(res) and res.get("passed") == 1,
                      f"result {res}")
                continue
            check(f"the next screen's first pass does not wait behind the check reading its {cut}: the read is cut",
                  bool(newer and nd) and at(cut + " cut") is not None and second is not None
                  and second - began < delay[cut] - 0.5, f"read began {began}, pass 2 at {second}, marks {marks}")
            check(f"the check starts over after that analysis, and its result comes ({cut})",
                  bool(res) and res.get("passed") == 1 and at(cut, 2) is not None and at(cut, 2) >= at("pass 2 read"),
                  f"result {res}, marks {marks}")
            if cut == "text":
                check("what it read before it gave way is not read again: the examples once, the text twice",
                      at("cases", 2) is None and at("text", 2) is not None, f"marks {marks}")


async def main():
    only = set(sys.argv[1:])
    runs = [("handoff", handoff), ("misfile", misfile), ("voice", voice), ("brake", brake), ("slots", slots),
            ("remark", remark), ("region", region), ("pages", pages), ("shared", shared), ("release", release), ("starting", starting),
            ("gpu", gpu), ("gap", gap)]
    for name, fn in runs:
        if only and name not in only:
            continue
        if asyncio.iscoroutinefunction(fn):
            await fn()
        else:
            await asyncio.to_thread(fn)   # the in-process server runs its own loop; this one only waits
    print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


asyncio.run(main())
